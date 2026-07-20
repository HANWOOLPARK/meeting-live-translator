"""Lazy faster-whisper adapter with a tested CUDA-to-CPU fallback."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from .language import classify_language
from .models import TranscriptionResult


LOGGER = logging.getLogger(__name__)
ModelFactory = Callable[..., Any]


class TranscriptionLoadError(RuntimeError):
    """Raised when neither the preferred nor the fallback model can load."""


class TranscriptionInferenceError(RuntimeError):
    """Raised when inference fails and no safe retry remains."""


@runtime_checkable
class TranscriptionEngine(Protocol):
    """Replaceable interface used by the capture/session orchestrator."""

    def ensure_loaded(self) -> None:
        """Load any heavyweight model resources if necessary."""

    def model_info(self) -> Mapping[str, object]:
        """Return non-sensitive runtime information for health/settings APIs."""

    def transcribe(
        self,
        samples: NDArray[np.float32],
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
        beam_size: int | None = None,
    ) -> TranscriptionResult:
        """Transcribe one mono 16 kHz float32 utterance."""


class FasterWhisperEngine:
    """Near-real-time utterance transcription using faster-whisper.

    Construction is cheap and does not import ``faster_whisper``.  On first
    inference (or an explicit :meth:`ensure_loaded`) the engine tries an actual
    CUDA model construction.  Any CUDA construction failure falls back to a
    CPU/int8 model.  A CUDA-only error raised while consuming the lazy segment
    iterator also triggers one CPU retry.
    """

    def __init__(
        self,
        model_name: str = "small",
        model_factory: ModelFactory | None = None,
        prefer_cuda: bool = True,
        local_files_only: bool = False,
    ) -> None:
        if not model_name or not model_name.strip():
            raise ValueError("model_name must not be empty")
        self.model_name = model_name.strip()
        self.prefer_cuda = bool(prefer_cuda)
        self.local_files_only = bool(local_files_only)
        self._model_factory = model_factory
        self._model: Any | None = None
        self._device: str | None = None
        self._compute_type: str | None = None
        self._cuda_error: str | None = None
        self._lock = threading.RLock()

    def _factory(self) -> ModelFactory:
        if self._model_factory is not None:
            return self._model_factory

        # Keep the optional/heavy dependency out of module import and server
        # startup.  ImportError is reported as a normal model load error below.
        from faster_whisper import WhisperModel

        return WhisperModel

    @staticmethod
    def _safe_error(error: BaseException) -> str:
        message = " ".join(str(error).split())
        if len(message) > 240:
            message = f"{message[:237]}..."
        return f"{type(error).__name__}: {message}" if message else type(error).__name__

    def _construct(self, device: str, compute_type: str) -> Any:
        kwargs: dict[str, Any] = {
            "device": device,
            "compute_type": compute_type,
        }
        if self.local_files_only:
            kwargs["local_files_only"] = True
        return self._factory()(self.model_name, **kwargs)

    @staticmethod
    def _cuda_compute_type() -> str:
        """Choose a CTranslate2-reported CUDA type, with a safe probe fallback."""

        try:
            import ctranslate2

            supported = set(ctranslate2.get_supported_compute_types("cuda"))
        except Exception:
            # Actual model construction below remains the authoritative CUDA
            # probe and will fall back to CPU/int8 if float16 is unsupported.
            return "float16"
        for candidate in ("float16", "int8_float16", "int8", "float32"):
            if candidate in supported:
                return candidate
        return "float32"

    def _load_cpu_locked(self, cuda_error: BaseException | None = None) -> None:
        if cuda_error is not None:
            self._cuda_error = self._safe_error(cuda_error)
            LOGGER.warning("CUDA transcription unavailable; using CPU/int8: %s", self._cuda_error)
        try:
            model = self._construct("cpu", "int8")
        except Exception as error:
            safe_error = self._safe_error(error)
            raise TranscriptionLoadError(
                f"Unable to initialize the CPU/int8 transcription model ({safe_error})"
            ) from error
        self._model = model
        self._device = "cpu"
        self._compute_type = "int8"

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            if self.prefer_cuda:
                # A custom factory is a deterministic test/integration seam;
                # hardware capability probing applies to the real backend.
                cuda_compute_type = (
                    self._cuda_compute_type()
                    if self._model_factory is None
                    else "float16"
                )
                try:
                    model = self._construct("cuda", cuda_compute_type)
                except Exception as error:
                    self._load_cpu_locked(cuda_error=error)
                else:
                    self._model = model
                    self._device = "cuda"
                    self._compute_type = cuda_compute_type
            else:
                self._load_cpu_locked()

    def model_info(self) -> dict[str, object]:
        with self._lock:
            return {
                "model_name": self.model_name,
                "loaded": self._model is not None,
                "device": self._device,
                "compute_type": self._compute_type,
                "prefer_cuda": self.prefer_cuda,
                "cuda_fallback": self._device == "cpu" and self._cuda_error is not None,
                "cuda_error": self._cuda_error,
            }

    @staticmethod
    def _field(value: object, name: str, default: object) -> object:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    def _consume_transcription(
        self,
        model: Any,
        samples: NDArray[np.float32],
        *,
        language: str | None,
        initial_prompt: str | None,
        beam_size: int | None,
    ) -> tuple[list[object], object]:
        kwargs: dict[str, Any] = {"language": language}
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        if beam_size is not None:
            kwargs.update(
                beam_size=max(1, int(beam_size)),
                condition_on_previous_text=False,
            )
        # The ordinary local STT path passes language=None on every call. The
        # hybrid Deepgram recheck path intentionally supplies its fixed source
        # language and a bounded approved-term prompt.
        segments, info = model.transcribe(samples, **kwargs)
        return list(segments), info

    @staticmethod
    def _join_segment_text(pieces: list[str]) -> str:
        """Join model segments without inserting spaces into Japanese text."""

        combined = ""
        for piece in pieces:
            if not piece:
                continue
            if not combined:
                combined = piece.lstrip()
                continue
            if combined[-1].isspace() or piece[0].isspace():
                combined += piece
            elif (
                combined[-1].isascii()
                and piece[0].isascii()
                and combined[-1].isalnum()
                and piece[0].isalnum()
            ):
                combined += f" {piece}"
            else:
                combined += piece
        return combined.strip()

    def _fallback_after_cuda_inference_error(self, error: BaseException, failed_model: Any) -> Any:
        with self._lock:
            # Another worker may already have replaced this exact CUDA model.
            if self._model is not failed_model and self._model is not None:
                return self._model
            self._model = None
            self._device = None
            self._compute_type = None
            self._load_cpu_locked(cuda_error=error)
            return self._model

    def transcribe(
        self,
        samples: NDArray[np.float32],
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
        beam_size: int | None = None,
    ) -> TranscriptionResult:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("samples must be a one-dimensional mono array")
        if not np.isfinite(audio).all():
            audio = np.nan_to_num(audio, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)
        if audio.size == 0:
            return TranscriptionResult("", "unknown", 0.0, 0.0, 0.0, 0.0)

        self.ensure_loaded()
        with self._lock:
            model = self._model
            device = self._device
        assert model is not None  # ensure_loaded either sets it or raises

        started = perf_counter()
        try:
            segments, info = self._consume_transcription(
                model,
                audio,
                language=language,
                initial_prompt=initial_prompt,
                beam_size=beam_size,
            )
        except Exception as error:
            if device != "cuda":
                raise TranscriptionInferenceError(
                    f"Transcription inference failed ({self._safe_error(error)})"
                ) from error
            cpu_model = self._fallback_after_cuda_inference_error(error, model)
            try:
                segments, info = self._consume_transcription(
                    cpu_model,
                    audio,
                    language=language,
                    initial_prompt=initial_prompt,
                    beam_size=beam_size,
                )
            except Exception as retry_error:
                raise TranscriptionInferenceError(
                    f"CPU transcription retry failed ({self._safe_error(retry_error)})"
                ) from retry_error

        texts: list[str] = []
        segment_starts: list[float] = []
        segment_ends: list[float] = []
        for segment in segments:
            text = str(self._field(segment, "text", ""))
            if text.strip():
                texts.append(text)
            try:
                segment_start = float(self._field(segment, "start", 0.0))
                segment_end = float(self._field(segment, "end", segment_start))
            except (TypeError, ValueError):
                continue
            if math.isfinite(segment_start):
                segment_starts.append(max(0.0, segment_start))
            if math.isfinite(segment_end):
                segment_ends.append(max(0.0, segment_end))

        raw_language = str(self._field(info, "language", "") or "")
        try:
            language_probability = float(self._field(info, "language_probability", 0.0))
        except (TypeError, ValueError):
            language_probability = 0.0
        if not math.isfinite(language_probability):
            language_probability = 0.0

        combined_text = self._join_segment_text(texts)
        detected_language = classify_language(
            raw_language,
            language_probability,
            combined_text,
        )
        inference_seconds = max(0.0, perf_counter() - started)
        return TranscriptionResult(
            text=combined_text,
            detected_language=detected_language,
            language_probability=max(0.0, min(1.0, language_probability)),
            started_offset=min(segment_starts) if segment_starts else 0.0,
            ended_offset=max(segment_ends) if segment_ends else 0.0,
            inference_seconds=inference_seconds,
        )


__all__ = [
    "FasterWhisperEngine",
    "TranscriptionEngine",
    "TranscriptionInferenceError",
    "TranscriptionLoadError",
]
