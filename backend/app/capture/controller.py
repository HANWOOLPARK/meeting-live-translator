from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from enum import Enum
from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

import numpy as np

from ..audio.base import AudioCaptureBase
from ..audio.devices import PyAudioWPatchDeviceProvider
from ..audio.models import AudioDeviceInfo, AudioFrame, DeviceCatalog
from ..audio.processing import (
    calculate_audio_level,
    calculate_dbfs,
    pcm16_to_mono_resampled,
)
from ..config.settings import (
    ALLOWED_MODELS,
    ALLOWED_STT_PROVIDERS,
    ALLOWED_TRANSLATION_DIRECTIONS,
    EXTERNAL_ONLY_TRANSLATION_DIRECTIONS,
    KOREAN_SOURCE_TRANSLATION_DIRECTIONS,
    AppSettings,
)
from ..errors import SafeAppError, exception_kind
from ..sessions.models import FinalTranscript
from ..sessions.repository import JsonlSessionRepository
from ..transcription import (
    DeepgramStreamError,
    DeepgramStreamingClient,
    DeepgramTranscript,
    DeepgramWord,
    FasterWhisperEngine,
    Pcm16RingBuffer,
    SegmentEvent,
    SegmentEventType,
    TranscriptDeduplicator,
    TranscriptionEngine,
    TranscriptionLoadError,
    UtteranceSegmenter,
    has_explicit_korean_date,
    has_malformed_korean_date_format,
)
from ..websocket.events import error_event, make_event, state_event
from ..websocket.manager import WebSocketManager

if TYPE_CHECKING:
    from ..context_engine import ContextEngine
    from ..decision_radar import DecisionRadarManager
    from ..sessions import SessionManager
    from ..translation import TranslationManager


LOGGER = logging.getLogger(__name__)
CaptureFactory = Callable[[AudioDeviceInfo], AudioCaptureBase]
EngineFactory = Callable[[str], TranscriptionEngine]
DeepgramFactory = Callable[[str], DeepgramStreamingClient]


class CaptureStatus(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass(slots=True)
class _TranscriptionJob:
    kind: str
    samples: np.ndarray
    session_id: str
    utterance_id: str
    generation: int
    source: str
    started_at: datetime
    ended_at: datetime
    engine: TranscriptionEngine
    deduplicator: TranscriptDeduplicator
    completion: asyncio.Future[None] | None = None


@dataclass(frozen=True, slots=True)
class _BufferedDeepgramAudio:
    pcm: bytes
    started_offset: float
    duration: float


@dataclass(slots=True)
class _DeepgramFinalJob:
    event: DeepgramTranscript
    session_id: str
    utterance_id: str
    source: str
    started_at: datetime
    ended_at: datetime
    samples: np.ndarray | None
    allow_recheck: bool
    provider_received_at: datetime
    queued_at_perf: float
    provisional_displayed: bool
    completion: asyncio.Future[None]


def _default_capture_factory(device: AudioDeviceInfo) -> AudioCaptureBase:
    from ..audio.pyaudio_wpatch_capture import create_audio_capture

    return create_audio_capture(device)


class CaptureController:
    """Own audio/session state while keeping failures inside one capture session."""

    def __init__(
        self,
        settings: AppSettings,
        device_provider: PyAudioWPatchDeviceProvider,
        websocket_manager: WebSocketManager,
        repository: JsonlSessionRepository,
        *,
        context_engine: ContextEngine | None = None,
        capture_factory: CaptureFactory | None = None,
        engine_factory: EngineFactory | None = None,
        recheck_engine_factory: EngineFactory | None = None,
        deepgram_factory: DeepgramFactory | None = None,
        translation_manager: TranslationManager | None = None,
        session_manager: SessionManager | None = None,
        decision_radar_manager: DecisionRadarManager | None = None,
    ) -> None:
        self.settings = settings
        self.device_provider = device_provider
        self.websocket_manager = websocket_manager
        self.repository = repository
        self.context_engine = context_engine
        self.capture_factory = capture_factory or _default_capture_factory
        self.engine_factory = engine_factory or (
            lambda model: FasterWhisperEngine(
                model_name=model,
                prefer_cuda=settings.prefer_cuda,
            )
        )
        def default_deepgram_factory(language: str) -> DeepgramStreamingClient:
            endpointing_ms, utterance_end_ms, max_segment_seconds = (
                settings.deepgram_profile(language)
            )
            return DeepgramStreamingClient(
                api_key=settings.deepgram_api_key,
                model=settings.deepgram_stt_model,
                language=language,
                sample_rate=settings.sample_rate,
                endpointing_ms=endpointing_ms,
                utterance_end_ms=utterance_end_ms,
                max_segment_seconds=max_segment_seconds,
                checkpoint_seconds=settings.deepgram_checkpoint_seconds,
                hard_limit_seconds=settings.deepgram_hard_limit_seconds,
                open_timeout_seconds=settings.deepgram_open_timeout_seconds,
                incomplete_final_wait_seconds=settings.deepgram_incomplete_wait(
                    language
                ),
                keyterms=(context_engine.keyterms() if context_engine is not None else ()),
            )

        self.deepgram_factory = deepgram_factory or default_deepgram_factory
        self.recheck_engine_factory = recheck_engine_factory or (
            lambda model: FasterWhisperEngine(
                model_name=model,
                prefer_cuda=False,
                local_files_only=settings.deepgram_recheck_local_files_only,
            )
        )
        self.translation_manager = translation_manager
        self.session_manager = session_manager
        self.decision_radar_manager = decision_radar_manager

        self._status = CaptureStatus.IDLE
        self._source: str | None = None
        self._device_id: str | None = None
        self._selected_model = settings.selected_model
        self._selected_stt_provider = settings.stt_provider
        self._translation_direction = settings.translation_direction
        self._capture: AudioCaptureBase | None = None
        self._engine: TranscriptionEngine | None = None
        self._engine_model: str | None = None
        self._deepgram: DeepgramStreamingClient | None = None
        self._deepgram_utterance_id: str | None = None
        self._deepgram_failed = False
        self._deepgram_error_reported = False
        self._deepgram_reconnecting = False
        self._deepgram_reconnect_exhausted = False
        self._deepgram_reconnect_attempts = 0
        self._deepgram_reconnect_count = 0
        self._deepgram_stream_base_offset = 0.0
        self._deepgram_audio_received_seconds = 0.0
        self._deepgram_buffer: deque[_BufferedDeepgramAudio] = deque()
        self._deepgram_buffer_bytes = 0
        self._deepgram_dropped_audio_seconds = 0.0
        self._deepgram_reconnect_task: asyncio.Task[None] | None = None
        self._deepgram_audio_ring = Pcm16RingBuffer(
            sample_rate=settings.sample_rate,
            max_seconds=settings.deepgram_recheck_buffer_seconds,
        )
        self._deepgram_final_jobs: deque[_DeepgramFinalJob] = deque()
        self._deepgram_final_event = asyncio.Event()
        self._deepgram_final_task: asyncio.Task[None] | None = None
        self._recheck_engine: TranscriptionEngine | None = None
        self._recheck_engine_model: str | None = None
        self._recheck_background_task: asyncio.Task[Any] | None = None
        self._recheck_unavailable = False
        self._recheck_requested_count = 0
        self._recheck_accepted_count = 0
        self._recheck_failed_count = 0
        self._recheck_timeout_count = 0
        self._recheck_skipped_count = 0
        self._deepgram_latency_count = 0
        self._deepgram_audio_end_to_provider_total_ms = 0
        self._deepgram_audio_end_to_provider_last_ms = 0
        self._deepgram_audio_end_to_provider_max_ms = 0
        self._deepgram_canonical_processing_total_ms = 0
        self._deepgram_canonical_processing_last_ms = 0
        self._deepgram_canonical_processing_max_ms = 0
        self._session_id: str | None = None
        self._last_session_id: str | None = None
        self._session_started_at: datetime | None = None
        self._paused_at: datetime | None = None
        self._segmenter = UtteranceSegmenter(sample_rate=settings.sample_rate)
        self._deduplicator = TranscriptDeduplicator()
        self._generation = 0
        self._utterance_id: str | None = None
        self._transcription_active = False
        self._accept_frames = False
        self._dropped_frames = 0
        self._last_level_sent = 0.0

        self._loop: asyncio.AbstractEventLoop | None = None
        self._frame_queue: asyncio.Queue[AudioFrame] = asyncio.Queue(
            maxsize=settings.frame_queue_size
        )
        self._final_jobs: deque[_TranscriptionJob] = deque()
        self._pending_final_completions: set[asyncio.Future[None]] = set()
        self._latest_partial: _TranscriptionJob | None = None
        self._job_event = asyncio.Event()
        self._frame_task: asyncio.Task[None] | None = None
        self._transcription_task: asyncio.Task[None] | None = None
        self._control_lock = asyncio.Lock()

    @property
    def status(self) -> CaptureStatus:
        return self._status

    @property
    def display_status(self) -> str:
        if self._transcription_active:
            return "transcribing"
        return self._status.value

    @property
    def selected_model(self) -> str:
        return self._selected_model

    @property
    def selected_stt_provider(self) -> str:
        return self._selected_stt_provider

    @property
    def translation_direction(self) -> str:
        return self._translation_direction

    def _source_language(self) -> str:
        return {
            "ja_to_ko": "ja",
            "ja_to_en": "ja",
            "en_to_ko": "en",
            "en_to_ja": "en",
            "ko_to_ja": "ko",
            "ko_to_en": "ko",
        }[self._translation_direction]

    def _target_language(self) -> str:
        return {
            "ja_to_ko": "ko",
            "ja_to_en": "en",
            "en_to_ko": "ko",
            "en_to_ja": "ja",
            "ko_to_ja": "ja",
            "ko_to_en": "en",
        }[self._translation_direction]

    @property
    def is_active(self) -> bool:
        return self._status in {CaptureStatus.LISTENING, CaptureStatus.PAUSED}

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._status.value,
            "display_state": self.display_status,
            "source": self._source,
            "device_id": self._device_id,
            "model": self._selected_model,
            "stt_provider": self._selected_stt_provider,
            "translation_direction": self._translation_direction,
            "source_language": self._source_language(),
            "target_language": self._target_language(),
            "session_id": self._session_id,
            "last_session_id": self._last_session_id,
            "dropped_frames": self._dropped_frames,
            "model_runtime": self.public_model_info(),
            "stt_runtime": self.public_stt_info(),
        }

    def public_stt_info(self) -> dict[str, Any]:
        if self._selected_stt_provider == "deepgram":
            if self._deepgram is not None:
                info = dict(self._deepgram.snapshot())
            else:
                endpointing_ms, utterance_end_ms, max_segment_seconds = (
                    self.settings.deepgram_profile(self._source_language())
                )
                info = {
                    "provider": "deepgram",
                    "configured": bool(self.settings.deepgram_api_key),
                    "connected": False,
                    "model": self.settings.deepgram_stt_model,
                    "language": self._source_language(),
                    "streaming": True,
                    "interim_results": True,
                    "smart_format": True,
                    "endpointing_ms": endpointing_ms,
                    "utterance_end_ms": utterance_end_ms,
                    "max_segment_seconds": max_segment_seconds,
                    "checkpoint_seconds": self.settings.deepgram_checkpoint_seconds,
                    "hard_limit_seconds": self.settings.deepgram_hard_limit_seconds,
                    "last_error": None,
                }
            info.update(
                {
                    "reconnecting": self._deepgram_reconnecting,
                    "reconnect_exhausted": self._deepgram_reconnect_exhausted,
                    "reconnect_attempts": self._deepgram_reconnect_attempts,
                    "reconnect_count": self._deepgram_reconnect_count,
                    "buffered_audio_ms": round(
                        sum(item.duration for item in self._deepgram_buffer) * 1_000
                    ),
                    "dropped_audio_ms": round(
                        self._deepgram_dropped_audio_seconds * 1_000
                    ),
                    "capture_dropped_frames": self._dropped_frames,
                    "latency": {
                        "completed_finals": self._deepgram_latency_count,
                        "audio_end_to_provider_last_ms": (
                            self._deepgram_audio_end_to_provider_last_ms
                        ),
                        "audio_end_to_provider_average_ms": (
                            round(
                                self._deepgram_audio_end_to_provider_total_ms
                                / self._deepgram_latency_count
                            )
                            if self._deepgram_latency_count
                            else 0
                        ),
                        "audio_end_to_provider_max_ms": (
                            self._deepgram_audio_end_to_provider_max_ms
                        ),
                        "canonical_processing_last_ms": (
                            self._deepgram_canonical_processing_last_ms
                        ),
                        "canonical_processing_average_ms": (
                            round(
                                self._deepgram_canonical_processing_total_ms
                                / self._deepgram_latency_count
                            )
                            if self._deepgram_latency_count
                            else 0
                        ),
                        "canonical_processing_max_ms": (
                            self._deepgram_canonical_processing_max_ms
                        ),
                    },
                    "selective_recheck": {
                        "enabled": self.settings.deepgram_recheck_enabled,
                        "model": (
                            self.settings.deepgram_recheck_model
                            or self._selected_model
                        ),
                        "local_files_only": (
                            self.settings.deepgram_recheck_local_files_only
                        ),
                        "unavailable": self._recheck_unavailable,
                        "busy": bool(
                            self._recheck_background_task
                            and not self._recheck_background_task.done()
                        ),
                        "queue_depth": len(self._deepgram_final_jobs),
                        "queue_max_size": (
                            self.settings.deepgram_recheck_queue_max_size
                        ),
                        "requested": self._recheck_requested_count,
                        "accepted": self._recheck_accepted_count,
                        "failed": self._recheck_failed_count,
                        "timed_out": self._recheck_timeout_count,
                        "skipped": self._recheck_skipped_count,
                        **self._deepgram_audio_ring.snapshot(),
                    },
                }
            )
            return info
        return {
            "provider": "local",
            "configured": True,
            "connected": self._engine is not None,
            "capture_dropped_frames": self._dropped_frames,
            **self.public_model_info(),
        }

    def public_model_info(self) -> dict[str, Any]:
        if self._engine is None:
            return {
                "model_name": self._selected_model,
                "loaded": False,
                "device": None,
                "compute_type": None,
                "cuda_fallback": False,
            }
        info = dict(self._engine.model_info())
        # Runtime exception contents can include local cache paths.  The API only
        # needs the fallback decision; details remain in bounded server logs.
        info.pop("cuda_error", None)
        return info

    async def list_devices(self, *, refresh: bool = False) -> DeviceCatalog:
        method = self.device_provider.refresh if refresh else self.device_provider.list_devices
        return await asyncio.to_thread(method)

    async def set_model(self, model: str) -> dict[str, Any]:
        normalized = model.strip().lower()
        if normalized not in ALLOWED_MODELS:
            raise SafeAppError(
                "invalid_model",
                "Whisper 모델은 tiny, base, small, medium 중 하나여야 합니다.",
                400,
            )
        async with self._control_lock:
            if self.is_active:
                raise SafeAppError(
                    "capture_active",
                    "모델을 변경하려면 먼저 캡처를 중지하세요.",
                    409,
                )
            self._selected_model = normalized
            if self._engine_model != normalized:
                self._engine = None
                self._engine_model = None
        return self.snapshot()

    async def start(
        self,
        source: str,
        device_id: str,
        model: str | None = None,
        stt_provider: str | None = None,
        translation_direction: str | None = None,
    ) -> dict[str, Any]:
        source = source.strip().lower()
        if source not in {"system", "microphone"}:
            raise SafeAppError(
                "invalid_source",
                "오디오 소스는 system 또는 microphone이어야 합니다.",
                400,
            )
        selected_model = (model or self._selected_model).strip().lower()
        if selected_model not in ALLOWED_MODELS:
            raise SafeAppError(
                "invalid_model",
                "Whisper 모델은 tiny, base, small, medium 중 하나여야 합니다.",
                400,
            )
        selected_stt_provider = (
            stt_provider or self._selected_stt_provider
        ).strip().lower()
        if selected_stt_provider not in ALLOWED_STT_PROVIDERS:
            raise SafeAppError(
                "invalid_stt_provider",
                "음성 인식 방식은 local 또는 deepgram이어야 합니다.",
                400,
            )
        selected_translation_direction = (
            translation_direction or self._translation_direction
        ).strip().lower()
        if selected_translation_direction not in ALLOWED_TRANSLATION_DIRECTIONS:
            raise SafeAppError(
                "invalid_translation_direction",
                "지원하는 번역 방향을 선택하세요: 일본어→한국어/영어, 영어→한국어/일본어, 한국어→일본어/영어.",
                400,
            )
        if (
            selected_translation_direction in KOREAN_SOURCE_TRANSLATION_DIRECTIONS
            and selected_stt_provider != "deepgram"
        ):
            raise SafeAppError(
                "reverse_translation_requires_deepgram",
                "한국어 원문 번역은 Deepgram 음성 인식에서만 사용할 수 있습니다.",
                409,
            )
        translation_provider = getattr(
            getattr(self.translation_manager, "provider", None),
            "provider_name",
            "none",
        )
        if (
            selected_translation_direction in EXTERNAL_ONLY_TRANSLATION_DIRECTIONS
            and translation_provider not in {"gemini", "openai"}
        ):
            source_code, target_code = selected_translation_direction.split("_to_", 1)
            language_names = {"ja": "일본어", "en": "영어", "ko": "한국어"}
            raise SafeAppError(
                "reverse_translation_provider_required",
                f"{language_names[source_code]}→{language_names[target_code]} 번역에는 Gemini 또는 OpenAI 번역 Provider가 필요합니다.",
                409,
            )
        if selected_stt_provider == "deepgram" and not self.settings.deepgram_api_key:
            raise SafeAppError(
                "deepgram_api_key_missing",
                "DEEPGRAM_API_KEY가 설정되지 않았습니다. .env에 키를 설정하고 서버를 다시 시작하세요.",
                409,
            )

        async with self._control_lock:
            if self.is_active:
                await self._stop_locked(reason="device_or_model_change")

            catalog = await self.list_devices()
            device = catalog.find(device_id)
            if device is None:
                status = 503 if not catalog.capture_devices and catalog.warnings else 404
                raise SafeAppError(
                    "audio_device_not_found",
                    "선택한 오디오 장치를 찾을 수 없습니다. 장치 목록을 새로고침하세요.",
                    status,
                )
            if source == "system" and not device.is_loopback:
                raise SafeAppError(
                    "loopback_required",
                    "시스템 음성에는 WASAPI Loopback 장치를 선택해야 합니다.",
                    400,
                )
            if source == "microphone" and (
                device.is_loopback or device.max_input_channels <= 0
            ):
                raise SafeAppError(
                    "microphone_required",
                    "마이크 소스에는 일반 입력 장치를 선택해야 합니다.",
                    400,
                )

            self._loop = asyncio.get_running_loop()
            self._ensure_background_tasks()
            self._clear_frame_queue()
            self._latest_partial = None
            if not self._final_jobs:
                self._job_event.clear()
            self._segmenter = UtteranceSegmenter(sample_rate=self.settings.sample_rate)
            self._deduplicator = TranscriptDeduplicator()
            self._generation += 1
            self._utterance_id = None
            self._dropped_frames = 0
            self._reset_deepgram_runtime()
            self._source = source
            self._device_id = device_id
            self._selected_model = selected_model
            self._selected_stt_provider = selected_stt_provider
            self._translation_direction = selected_translation_direction
            self._session_started_at = None
            self._paused_at = None
            try:
                if selected_stt_provider == "local":
                    if self._engine is None or self._engine_model != selected_model:
                        self._engine = self.engine_factory(selected_model)
                        self._engine_model = selected_model
                    self._transcription_active = True
                    await self._broadcast_state(stage="model_loading")
                    await self._run_blocking(self._engine.ensure_loaded)
                    self._transcription_active = False
                else:
                    await self._broadcast_state(stage="provider_connecting")
                    await self._open_deepgram_with_retry()

                # Segment offsets begin when capture begins, not while a cold
                # model is still loading.
                self._session_started_at = datetime.now().astimezone()
                if self.session_manager is not None:
                    translation_provider = getattr(
                        getattr(self.translation_manager, "provider", None),
                        "provider_name",
                        "none",
                    )
                    self._session_id = await self.session_manager.start(
                        {
                            "started_at": self._session_started_at.isoformat(
                                timespec="milliseconds"
                            ),
                            "source": source,
                            "audio_device_name": device.name,
                            "whisper_model": (
                                selected_model
                                if selected_stt_provider == "local"
                                else f"deepgram:{self.settings.deepgram_stt_model}"
                            ),
                            "translation_provider": translation_provider,
                            "translation_direction": self._translation_direction,
                        }
                    )
                else:
                    self._session_id = self.repository.start_session()
                if self.decision_radar_manager is not None:
                    try:
                        await self.decision_radar_manager.begin_session(
                            self._session_id
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as radar_error:
                        # Decision Radar is an optional observer. A provider or
                        # persistence failure must never prevent audio capture.
                        LOGGER.warning(
                            "Decision Radar session initialization failed: %s",
                            exception_kind(radar_error),
                        )
                self._capture = self.capture_factory(device)
                self._accept_frames = True
                await self._run_blocking(self._capture.start, self._on_audio_frame)
            except asyncio.CancelledError:
                await self._cleanup_failed_start(CaptureStatus.STOPPED)
                await self._broadcast_state(reason="start_cancelled")
                raise
            except Exception as exc:
                await self._cleanup_failed_start(CaptureStatus.ERROR)
                LOGGER.error("Capture start failed: %s", exception_kind(exc))
                await self.websocket_manager.broadcast(
                    error_event(
                        "capture_start_failed",
                        "오디오 캡처 또는 전사 모델을 시작하지 못했습니다.",
                        recoverable=True,
                    )
                )
                await self._broadcast_state()
                raise SafeAppError(
                    "capture_start_failed",
                    "오디오 캡처 또는 전사 모델을 시작하지 못했습니다.",
                    503,
                ) from exc

            self._status = CaptureStatus.LISTENING
            await self._broadcast_state()
            return self.snapshot()

    async def pause(self) -> dict[str, Any]:
        async with self._control_lock:
            return await self._complete_on_cancel(self._pause_locked())

    async def resume(self) -> dict[str, Any]:
        async with self._control_lock:
            return await self._complete_on_cancel(self._resume_locked())

    async def _pause_locked(self) -> dict[str, Any]:
        if self._status is not CaptureStatus.LISTENING or self._capture is None:
            raise SafeAppError(
                "invalid_capture_state",
                "현재 상태에서는 일시정지할 수 없습니다.",
                409,
            )
        try:
            await asyncio.to_thread(self._capture.pause)
        except Exception as exc:
            LOGGER.warning("Capture pause failed: %s", exception_kind(exc))
            await self.websocket_manager.broadcast(
                error_event(
                    "capture_pause_failed",
                    "오디오 캡처를 일시정지하지 못했습니다.",
                    recoverable=True,
                )
            )
            await self._broadcast_state()
            raise SafeAppError(
                "capture_pause_failed",
                "오디오 캡처를 일시정지하지 못했습니다.",
                503,
            ) from exc

        await self._drain_captured_frames()
        self._status = CaptureStatus.PAUSED
        self._paused_at = datetime.now().astimezone()
        if self._selected_stt_provider == "deepgram" and self._deepgram is not None:
            await self._cancel_deepgram_reconnect(discard_buffer=True)
            await self._deepgram.stop()
        else:
            for event in self._segmenter.flush():
                self._enqueue_segment(event)
        self._generation += 1
        self._utterance_id = None
        await self._update_session_status("paused")
        await self._broadcast_level(0.0, -96.0)
        await self._broadcast_state()
        return self.snapshot()

    async def _resume_locked(self) -> dict[str, Any]:
        if self._status is not CaptureStatus.PAUSED or self._capture is None:
            raise SafeAppError(
                "invalid_capture_state",
                "현재 상태에서는 캡처를 재개할 수 없습니다.",
                409,
            )
        try:
            if self._selected_stt_provider == "deepgram":
                self._deepgram_failed = False
                self._deepgram_reconnect_exhausted = False
                self._deepgram_reconnect_attempts = 0
                self._deepgram_stream_base_offset = self._deepgram_audio_received_seconds
                self._deepgram_error_reported = False
                await self._open_deepgram_with_retry()
            await asyncio.to_thread(self._capture.resume)
        except Exception as exc:
            if self._selected_stt_provider == "deepgram" and self._deepgram is not None:
                try:
                    await self._deepgram.stop()
                except Exception:
                    pass
            LOGGER.warning("Capture resume failed: %s", exception_kind(exc))
            await self.websocket_manager.broadcast(
                error_event(
                    "capture_resume_failed",
                    "오디오 캡처를 재개하지 못했습니다.",
                    recoverable=True,
                )
            )
            await self._broadcast_state()
            raise SafeAppError(
                "capture_resume_failed",
                "오디오 캡처를 재개하지 못했습니다.",
                503,
            ) from exc

        resumed_at = datetime.now().astimezone()
        if self._paused_at is not None and self._session_started_at is not None:
            self._session_started_at += resumed_at - self._paused_at
        self._paused_at = None
        self._status = CaptureStatus.LISTENING
        self._accept_frames = True
        await self._update_session_status("running")
        await self._broadcast_state()
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        async with self._control_lock:
            return await self._stop_locked(reason="user_stop")

    async def _stop_locked(self, *, reason: str) -> dict[str, Any]:
        return await self._complete_on_cancel(self._stop_locked_impl(reason=reason))

    async def _stop_locked_impl(self, *, reason: str) -> dict[str, Any]:
        if self._capture is None and self._status in {
            CaptureStatus.IDLE,
            CaptureStatus.STOPPED,
        }:
            self._status = CaptureStatus.STOPPED
            await self._broadcast_state()
            return self.snapshot()

        capture = self._capture
        if capture is not None:
            try:
                await asyncio.to_thread(capture.stop)
            except Exception as exc:
                LOGGER.warning("Capture stop warning: %s", exception_kind(exc))
                await self.websocket_manager.broadcast(
                    error_event(
                        "capture_stop_warning",
                        "오디오 장치를 정리하는 중 경고가 발생했습니다.",
                        recoverable=True,
                    )
                )

        # Native callbacks have stopped. Allow call_soon_threadsafe deliveries
        # already in the event loop to land, then process every queued frame
        # before finalizing the utterance.
        await self._drain_captured_frames()
        self._status = CaptureStatus.STOPPED
        self._capture = None
        if self._selected_stt_provider == "deepgram" and self._deepgram is not None:
            await self._cancel_deepgram_reconnect(discard_buffer=True)
            await self._deepgram.stop()
        else:
            for event in self._segmenter.flush():
                self._enqueue_segment(event)
        self._generation += 1
        self._utterance_id = None

        pending = [
            completion
            for completion in self._pending_final_completions
            if not completion.done()
        ]
        if pending:
            _, still_pending = await asyncio.wait(pending, timeout=15.0)
            if still_pending:
                await self.websocket_manager.broadcast(
                    error_event(
                        "final_transcript_pending",
                        "마지막 문장 전사가 백그라운드에서 계속 진행 중입니다.",
                        recoverable=True,
                    )
                )

        completed_session_id = self._session_id
        if self.session_manager is not None:
            try:
                await self.session_manager.stop_and_finalize()
            except Exception as exc:
                LOGGER.error("Session finalize failed: %s", exception_kind(exc))
                await self.websocket_manager.broadcast(
                    error_event(
                        "session_finalize_failed",
                        "캡처는 중지됐지만 세션 완성본을 생성하지 못했습니다.",
                        recoverable=True,
                        session_id=completed_session_id,
                    )
                )
        else:
            self.repository.stop_session()
        self._last_session_id = completed_session_id
        self._session_id = None
        self._session_started_at = None
        self._paused_at = None
        self._deepgram_utterance_id = None
        await self._broadcast_level(0.0, -96.0)
        await self._broadcast_state(reason=reason)
        return self.snapshot()

    async def shutdown(self) -> None:
        async with self._control_lock:
            if self._capture is not None:
                await self._stop_locked(reason="server_shutdown")
            self._accept_frames = False
            await self._cancel_deepgram_reconnect(discard_buffer=True)

        pending = [
            completion
            for completion in self._pending_final_completions
            if not completion.done()
        ]
        if pending:
            await asyncio.wait(pending, timeout=15.0)

        for task in (
            self._frame_task,
            self._transcription_task,
            self._deepgram_final_task,
        ):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(
                task
                for task in (
                    self._frame_task,
                    self._transcription_task,
                    self._deepgram_final_task,
                )
                if task
            ),
            return_exceptions=True,
        )
        self._frame_task = None
        self._transcription_task = None
        self._deepgram_final_task = None
        background = self._recheck_background_task
        if background is not None and not background.done():
            # Native CTranslate2 inference cannot be force-cancelled safely;
            # detach its bounded background thread during server shutdown.
            background.cancel()
        self._recheck_background_task = None

    @staticmethod
    async def _run_blocking(function: Callable[..., Any], *args: Any) -> Any:
        """Wait for native work to finish before propagating request cancellation."""

        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    @staticmethod
    async def _complete_on_cancel(operation: Any) -> Any:
        """Shield a state transition, then propagate cancellation after it commits."""

        task = asyncio.create_task(operation)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _cleanup_failed_start(self, status: CaptureStatus) -> None:
        self._accept_frames = False
        self._transcription_active = False
        self._status = status
        capture, self._capture = self._capture, None
        if capture is not None:
            try:
                await asyncio.to_thread(capture.stop)
            except Exception:
                pass
        if self._deepgram is not None:
            await self._cancel_deepgram_reconnect(discard_buffer=True)
            try:
                await self._deepgram.stop()
            except Exception:
                pass
        if self.session_manager is not None:
            try:
                await self.session_manager.stop_and_finalize()
            except Exception as exc:
                LOGGER.warning("Failed-start session cleanup failed: %s", exception_kind(exc))
        else:
            self.repository.stop_session()
        self._last_session_id = self._session_id
        self._session_id = None
        self._session_started_at = None
        self._paused_at = None

    async def _drain_captured_frames(self) -> None:
        # Capture.stop/pause has returned, so no new native callbacks should
        # begin. Two event-loop turns admit callbacks already scheduled from
        # the PortAudio thread before closing the acceptance gate.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self._accept_frames = False
        await self._frame_queue.join()

    async def _open_deepgram_with_retry(self) -> None:
        """Open the initial stream twice so one transient handshake is recoverable."""

        attempts = min(2, self.settings.deepgram_reconnect_max_attempts)
        for attempt in range(1, attempts + 1):
            client = self.deepgram_factory(self._source_language())
            self._deepgram = client
            try:
                await client.start(
                    self._on_deepgram_transcript,
                    self._on_deepgram_error,
                )
                return
            except asyncio.CancelledError:
                try:
                    await client.stop()
                except Exception:
                    pass
                raise
            except DeepgramStreamError:
                try:
                    await client.stop()
                except Exception:
                    pass
                if attempt >= attempts:
                    raise
                await self._broadcast_state(
                    stage="provider_connect_retrying",
                    attempt=attempt,
                )
                delay = min(
                    self.settings.deepgram_reconnect_base_delay_seconds,
                    self.settings.deepgram_reconnect_max_delay_seconds,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

    def _reset_deepgram_runtime(self) -> None:
        self._deepgram_utterance_id = None
        self._deepgram_failed = False
        self._deepgram_error_reported = False
        self._deepgram_reconnecting = False
        self._deepgram_reconnect_exhausted = False
        self._deepgram_reconnect_attempts = 0
        self._deepgram_reconnect_count = 0
        self._deepgram_stream_base_offset = 0.0
        self._deepgram_audio_received_seconds = 0.0
        self._deepgram_buffer.clear()
        self._deepgram_buffer_bytes = 0
        self._deepgram_dropped_audio_seconds = 0.0
        self._deepgram_audio_ring.clear()
        self._recheck_unavailable = False
        self._recheck_requested_count = 0
        self._recheck_accepted_count = 0
        self._recheck_failed_count = 0
        self._recheck_timeout_count = 0
        self._recheck_skipped_count = 0
        self._deepgram_latency_count = 0
        self._deepgram_audio_end_to_provider_total_ms = 0
        self._deepgram_audio_end_to_provider_last_ms = 0
        self._deepgram_audio_end_to_provider_max_ms = 0
        self._deepgram_canonical_processing_total_ms = 0
        self._deepgram_canonical_processing_last_ms = 0
        self._deepgram_canonical_processing_max_ms = 0

    def _buffer_deepgram_audio(
        self,
        pcm: bytes,
        started_offset: float,
        duration: float,
    ) -> None:
        if not pcm or duration <= 0:
            return
        if self._deepgram_reconnect_exhausted:
            self._deepgram_dropped_audio_seconds += duration
            return
        item = _BufferedDeepgramAudio(pcm, started_offset, duration)
        self._deepgram_buffer.append(item)
        self._deepgram_buffer_bytes += len(pcm)
        max_bytes = max(
            1,
            round(
                self.settings.sample_rate
                * 2
                * self.settings.deepgram_reconnect_buffer_seconds
            ),
        )
        while self._deepgram_buffer_bytes > max_bytes and self._deepgram_buffer:
            dropped = self._deepgram_buffer.popleft()
            self._deepgram_buffer_bytes -= len(dropped.pcm)
            self._deepgram_dropped_audio_seconds += dropped.duration

    async def _cancel_deepgram_reconnect(self, *, discard_buffer: bool) -> None:
        task = self._deepgram_reconnect_task
        self._deepgram_reconnect_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._deepgram_reconnecting = False
        if discard_buffer:
            self._deepgram_dropped_audio_seconds += sum(
                item.duration for item in self._deepgram_buffer
            )
            self._deepgram_buffer.clear()
            self._deepgram_buffer_bytes = 0

    def _ensure_deepgram_reconnect(self) -> None:
        if self._deepgram_reconnect_exhausted:
            return
        task = self._deepgram_reconnect_task
        if task is None or task.done():
            self._deepgram_reconnect_task = asyncio.create_task(
                self._recover_deepgram(),
                name="deepgram-reconnect",
            )

    async def _recover_deepgram(self) -> None:
        self._deepgram_reconnecting = True
        try:
            old_client = self._deepgram
            if old_client is not None:
                try:
                    await old_client.stop()
                except Exception:
                    pass

            for attempt in range(1, self.settings.deepgram_reconnect_max_attempts + 1):
                if (
                    self._status is not CaptureStatus.LISTENING
                    or self._selected_stt_provider != "deepgram"
                ):
                    return
                self._deepgram_reconnect_attempts = attempt
                if attempt > 1:
                    delay = min(
                        self.settings.deepgram_reconnect_max_delay_seconds,
                        self.settings.deepgram_reconnect_base_delay_seconds
                        * (2 ** (attempt - 2)),
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)

                client = self.deepgram_factory(self._source_language())
                first_buffered = (
                    self._deepgram_buffer[0].started_offset
                    if self._deepgram_buffer
                    else self._deepgram_audio_received_seconds
                )
                self._deepgram_stream_base_offset = first_buffered
                try:
                    await client.start(
                        self._on_deepgram_transcript,
                        self._on_deepgram_error,
                    )
                    self._deepgram = client
                    while self._deepgram_buffer:
                        item = self._deepgram_buffer.popleft()
                        self._deepgram_buffer_bytes -= len(item.pcm)
                        try:
                            await client.send_audio(item.pcm)
                        except Exception:
                            self._deepgram_buffer.appendleft(item)
                            self._deepgram_buffer_bytes += len(item.pcm)
                            raise
                except asyncio.CancelledError:
                    try:
                        await client.stop()
                    except Exception:
                        pass
                    raise
                except Exception:
                    try:
                        await client.stop()
                    except Exception:
                        pass
                    self._deepgram_failed = True
                    continue

                self._deepgram_failed = False
                self._deepgram_reconnecting = False
                self._deepgram_reconnect_exhausted = False
                self._deepgram_error_reported = False
                self._deepgram_reconnect_count += 1
                await self.websocket_manager.broadcast(
                    make_event(
                        "stt_reconnected",
                        provider="deepgram",
                        attempt=attempt,
                        buffered_audio_ms=0,
                        dropped_audio_ms=round(
                            self._deepgram_dropped_audio_seconds * 1_000
                        ),
                    )
                )
                await self._broadcast_state(stage="provider_reconnected")
                return

            self._deepgram_reconnect_exhausted = True
            self._deepgram_reconnecting = False
            self._deepgram_failed = True
            self._deepgram_dropped_audio_seconds += sum(
                item.duration for item in self._deepgram_buffer
            )
            self._deepgram_buffer.clear()
            self._deepgram_buffer_bytes = 0
            await self.websocket_manager.broadcast(
                error_event(
                    "deepgram_reconnect_failed",
                    "Deepgram 자동 재연결 횟수를 초과했습니다. 버퍼 한도를 넘는 음성은 폐기되며 캡처를 다시 시작해야 합니다.",
                    recoverable=True,
                    session_id=self._session_id,
                )
            )
            await self._broadcast_state(stage="provider_unavailable")
        finally:
            if self._deepgram_reconnect_task is asyncio.current_task():
                self._deepgram_reconnect_task = None

    def _ensure_background_tasks(self) -> None:
        if self._frame_task is None or self._frame_task.done():
            self._frame_task = asyncio.create_task(
                self._frame_processor(),
                name="audio-frame-processor",
            )
        if self._transcription_task is None or self._transcription_task.done():
            self._transcription_task = asyncio.create_task(
                self._transcription_worker(),
                name="transcription-worker",
            )
        if self._deepgram_final_task is None or self._deepgram_final_task.done():
            self._deepgram_final_task = asyncio.create_task(
                self._deepgram_final_worker(),
                name="deepgram-final-worker",
            )

    def _on_audio_frame(self, frame: AudioFrame) -> None:
        loop = self._loop
        if not self._accept_frames or loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._queue_frame, frame)
        except RuntimeError:
            return

    def _queue_frame(self, frame: AudioFrame) -> None:
        if not self._accept_frames:
            return
        if self._frame_queue.full():
            try:
                self._frame_queue.get_nowait()
                self._frame_queue.task_done()
                self._dropped_frames += 1
            except asyncio.QueueEmpty:
                pass
        try:
            self._frame_queue.put_nowait(frame)
        except asyncio.QueueFull:
            self._dropped_frames += 1

    def _clear_frame_queue(self) -> None:
        while True:
            try:
                self._frame_queue.get_nowait()
                self._frame_queue.task_done()
            except asyncio.QueueEmpty:
                return

    async def _frame_processor(self) -> None:
        while True:
            frame = await self._frame_queue.get()
            try:
                if self._status is not CaptureStatus.LISTENING:
                    continue
                samples = pcm16_to_mono_resampled(
                    frame.data,
                    frame.channels,
                    frame.sample_rate,
                    self.settings.sample_rate,
                )
                now = asyncio.get_running_loop().time()
                if now - self._last_level_sent >= 0.1:
                    self._last_level_sent = now
                    await self._broadcast_level(
                        calculate_audio_level(samples),
                        calculate_dbfs(samples),
                    )
                if self._selected_stt_provider == "deepgram":
                    pcm16 = (
                        np.clip(samples, -1.0, 1.0) * 32767.0
                    ).astype("<i2", copy=False).tobytes()
                    duration = len(pcm16) / (2 * self.settings.sample_rate)
                    started_offset = self._deepgram_audio_received_seconds
                    self._deepgram_audio_received_seconds += duration
                    self._deepgram_audio_ring.append(
                        pcm16,
                        started_offset=started_offset,
                    )
                    if self._deepgram_reconnecting or self._deepgram_failed:
                        self._buffer_deepgram_audio(
                            pcm16,
                            started_offset,
                            duration,
                        )
                        if not self._deepgram_reconnect_exhausted:
                            self._ensure_deepgram_reconnect()
                    elif self._deepgram is not None:
                        try:
                            await self._deepgram.send_audio(pcm16)
                        except DeepgramStreamError:
                            self._deepgram_failed = True
                            self._buffer_deepgram_audio(
                                pcm16,
                                started_offset,
                                duration,
                            )
                            await self._on_deepgram_error(
                                "deepgram_audio_send_failed"
                            )
                    else:
                        self._deepgram_failed = True
                        self._buffer_deepgram_audio(
                            pcm16,
                            started_offset,
                            duration,
                        )
                        self._ensure_deepgram_reconnect()
                else:
                    for event in self._segmenter.process(samples):
                        self._enqueue_segment(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("Audio processing failed: %s", exception_kind(exc))
                await self.websocket_manager.broadcast(
                    error_event(
                        "audio_processing_error",
                        "오디오 프레임을 처리하지 못했습니다. 서버는 계속 실행됩니다.",
                        recoverable=True,
                    )
                )
            finally:
                self._frame_queue.task_done()

    def _enqueue_segment(
        self,
        event: SegmentEvent,
    ) -> asyncio.Future[None] | None:
        if event.event_type is SegmentEventType.RESET:
            self._generation += 1
            self._utterance_id = None
            self._latest_partial = None
            return None
        if (
            self._session_id is None
            or self._session_started_at is None
            or self._source is None
            or self._engine is None
        ):
            return None

        if self._utterance_id is None:
            self._utterance_id = str(uuid4())
        started_at = self._session_started_at + timedelta(seconds=event.started_offset)
        ended_at = self._session_started_at + timedelta(seconds=event.ended_offset)
        completion: asyncio.Future[None] | None = None
        if event.event_type is SegmentEventType.FINAL:
            completion = asyncio.get_running_loop().create_future()
            self._pending_final_completions.add(completion)
            completion.add_done_callback(self._pending_final_completions.discard)

        job = _TranscriptionJob(
            kind=event.event_type.value,
            samples=event.samples.copy(),
            session_id=self._session_id,
            utterance_id=self._utterance_id,
            generation=self._generation,
            source=self._source,
            started_at=started_at,
            ended_at=ended_at,
            engine=self._engine,
            deduplicator=self._deduplicator,
            completion=completion,
        )
        if event.event_type is SegmentEventType.FINAL:
            self._final_jobs.append(job)
            self._latest_partial = None
            self._generation += 1
            self._utterance_id = None
        else:
            self._latest_partial = job
        self._job_event.set()
        return completion

    async def _on_deepgram_transcript(self, event: DeepgramTranscript) -> None:
        session_id = self._session_id
        session_started_at = self._session_started_at
        source = self._source
        if session_id is None or session_started_at is None or source is None:
            return
        if self._deepgram_utterance_id is None:
            self._deepgram_utterance_id = str(uuid4())
        utterance_id = self._deepgram_utterance_id
        absolute_started_offset = self._deepgram_stream_base_offset + event.started_offset
        absolute_ended_offset = self._deepgram_stream_base_offset + event.ended_offset
        started_at = session_started_at + timedelta(seconds=absolute_started_offset)
        ended_at = session_started_at + timedelta(seconds=absolute_ended_offset)
        if event.kind == "partial":
            await self.websocket_manager.broadcast(
                make_event(
                    "partial_transcript",
                    session_id=session_id,
                    utterance_id=utterance_id,
                    source=source,
                    text=event.text.strip(),
                    language=self._source_language(),
                    language_probability=event.confidence,
                    timestamp=ended_at.isoformat(timespec="milliseconds"),
                    status="transcribing",
                    inference_seconds=0.0,
                    stt_provider="deepgram",
                )
            )
            return

        self._deepgram_utterance_id = None
        if self._deduplicator.is_duplicate(event.text):
            await self.websocket_manager.broadcast(
                make_event(
                    "partial_clear",
                    session_id=session_id,
                    utterance_id=utterance_id,
                )
            )
            return
        self._deduplicator.add(event.text)
        provider_received_at = datetime.now().astimezone()
        queued_at_perf = perf_counter()
        completion = asyncio.get_running_loop().create_future()
        self._pending_final_completions.add(completion)
        completion.add_done_callback(self._pending_final_completions.discard)
        risk_reasons = tuple(event.risk_reasons)
        provisional_displayed = bool(risk_reasons)
        if provisional_displayed:
            # Keep the original subtitle responsive while the canonical final
            # waits for bounded local quality review. This remains a transient
            # partial event: it is neither persisted nor sent to translation or
            # Decision Radar.
            await self.websocket_manager.broadcast(
                make_event(
                    "partial_transcript",
                    session_id=session_id,
                    utterance_id=utterance_id,
                    source=source,
                    text=event.text.strip(),
                    language=self._source_language(),
                    language_probability=event.confidence,
                    timestamp=provider_received_at.isoformat(
                        timespec="milliseconds"
                    ),
                    status="transcribing",
                    stage="quality_review",
                    provisional=True,
                    boundary_reason=event.boundary_reason,
                    risk_reasons=list(risk_reasons),
                    stt_provider="deepgram",
                )
            )
        pending_rechecks = sum(
            1 for pending in self._deepgram_final_jobs if pending.allow_recheck
        )
        if self._recheck_background_task is not None and not self._recheck_background_task.done():
            pending_rechecks += 1
        allow_recheck = bool(
            risk_reasons
            and pending_rechecks < self.settings.deepgram_recheck_queue_max_size
        )
        if risk_reasons and not allow_recheck:
            self._recheck_skipped_count += 1
        audio_slice = (
            self._deepgram_audio_ring.extract(
                absolute_started_offset,
                absolute_ended_offset,
            )
            if risk_reasons
            else None
        )
        self._deepgram_final_jobs.append(
            _DeepgramFinalJob(
                event=event,
                session_id=session_id,
                utterance_id=utterance_id,
                source=source,
                started_at=started_at,
                ended_at=ended_at,
                samples=(audio_slice.samples if audio_slice is not None else None),
                allow_recheck=allow_recheck,
                provider_received_at=provider_received_at,
                queued_at_perf=queued_at_perf,
                provisional_displayed=provisional_displayed,
                completion=completion,
            )
        )
        self._deepgram_final_event.set()

    async def _deepgram_final_worker(self) -> None:
        while True:
            await self._deepgram_final_event.wait()
            while self._deepgram_final_jobs:
                job = self._deepgram_final_jobs.popleft()
                try:
                    await self._process_deepgram_final(job)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    LOGGER.error(
                        "Deepgram final processing failed: %s",
                        exception_kind(error),
                    )
                finally:
                    await self.websocket_manager.broadcast(
                        make_event(
                            "partial_clear",
                            session_id=job.session_id,
                            utterance_id=job.utterance_id,
                        )
                    )
                    if not job.completion.done():
                        job.completion.set_result(None)
            self._deepgram_final_event.clear()

    async def _process_deepgram_final(self, job: _DeepgramFinalJob) -> None:
        processing_started_perf = perf_counter()
        event = job.event
        deepgram_text = event.text.strip()
        selected_text = deepgram_text
        whisper_text = ""
        recheck_status = "not_requested"
        recheck_latency_ms: int | None = None
        recheck_accepted = False
        inference_seconds = 0.0

        if event.risk_reasons:
            if not self.settings.deepgram_recheck_enabled:
                recheck_status = "disabled"
                self._recheck_skipped_count += 1
            elif self._recheck_unavailable:
                recheck_status = "model_unavailable"
                self._recheck_skipped_count += 1
            elif not job.allow_recheck:
                recheck_status = "queue_busy"
            elif job.samples is None or job.samples.size == 0:
                recheck_status = "audio_unavailable"
                self._recheck_skipped_count += 1
            elif (
                self._recheck_background_task is not None
                and not self._recheck_background_task.done()
            ):
                recheck_status = "engine_busy"
                self._recheck_skipped_count += 1
            else:
                self._recheck_requested_count += 1
                try:
                    result, recheck_latency_ms = await self._run_selective_recheck(
                        job.samples,
                        language=self._source_language(),
                    )
                    whisper_text = result.text.strip()
                    inference_seconds = result.inference_seconds
                    selected_text, recheck_status, recheck_accepted = (
                        self._select_recheck_text(
                            deepgram_text,
                            whisper_text,
                            tuple(event.risk_reasons),
                            self._source_language(),
                            tuple(event.words),
                        )
                    )
                    if recheck_accepted:
                        self._recheck_accepted_count += 1
                except TimeoutError:
                    recheck_status = "timeout"
                    self._recheck_timeout_count += 1
                except TranscriptionLoadError:
                    recheck_status = "model_unavailable"
                    self._recheck_unavailable = True
                    self._recheck_failed_count += 1
                except Exception as error:
                    recheck_status = "failed"
                    self._recheck_failed_count += 1
                    LOGGER.warning(
                        "Selective Whisper recheck failed: %s",
                        exception_kind(error),
                    )

        canonical_ready_at = datetime.now().astimezone()
        canonical_processing_ms = max(
            0,
            round((perf_counter() - processing_started_perf) * 1_000),
        )
        audio_end_to_provider_ms = max(
            0,
            round(
                (job.provider_received_at - job.ended_at).total_seconds()
                * 1_000
            ),
        )
        self._deepgram_latency_count += 1
        self._deepgram_audio_end_to_provider_last_ms = audio_end_to_provider_ms
        self._deepgram_audio_end_to_provider_total_ms += audio_end_to_provider_ms
        self._deepgram_audio_end_to_provider_max_ms = max(
            self._deepgram_audio_end_to_provider_max_ms,
            audio_end_to_provider_ms,
        )
        self._deepgram_canonical_processing_last_ms = canonical_processing_ms
        self._deepgram_canonical_processing_total_ms += canonical_processing_ms
        self._deepgram_canonical_processing_max_ms = max(
            self._deepgram_canonical_processing_max_ms,
            canonical_processing_ms,
        )

        segment_id = str(uuid4())
        word_confidences = [word.confidence for word in event.words]
        quality = {
            "segment_id": segment_id,
            "boundary_reason": event.boundary_reason,
            "confidence": event.confidence,
            "word_count": len(event.words),
            "minimum_word_confidence": (
                min(word_confidences) if word_confidences else None
            ),
            "low_word_ratio": (
                sum(value < 0.80 for value in word_confidences)
                / len(word_confidences)
                if word_confidences
                else None
            ),
            "risk_reasons": list(event.risk_reasons),
            "recheck_status": recheck_status,
            "recheck_model": (
                self.settings.deepgram_recheck_model or self._selected_model
            ),
            "recheck_latency_ms": recheck_latency_ms,
            "recheck_accepted": recheck_accepted,
            "provider_received_at": job.provider_received_at.isoformat(
                timespec="milliseconds"
            ),
            "audio_end_to_provider_ms": audio_end_to_provider_ms,
            "canonical_ready_at": canonical_ready_at.isoformat(
                timespec="milliseconds"
            ),
            "canonical_processing_ms": canonical_processing_ms,
            "final_queue_wait_ms": max(
                0,
                round((processing_started_perf - job.queued_at_perf) * 1_000),
            ),
            "provisional_displayed": job.provisional_displayed,
            "deepgram_text": deepgram_text,
            "whisper_text": whisper_text,
            "selected_text": selected_text,
        }
        transcript = FinalTranscript(
            segment_id=segment_id,
            session_id=job.session_id,
            utterance_id=job.utterance_id,
            source=job.source,
            text=selected_text,
            language=self._source_language(),
            language_probability=event.confidence,
            started_at=job.started_at.isoformat(timespec="milliseconds"),
            ended_at=job.ended_at.isoformat(timespec="milliseconds"),
            inference_seconds=inference_seconds if recheck_accepted else 0.0,
        )
        await self._publish_final_transcript(
            transcript,
            target_language=self._target_language(),
            transcription_quality=quality,
        )

    async def _run_selective_recheck(
        self,
        samples: np.ndarray,
        *,
        language: str,
    ) -> tuple[Any, int]:
        model = self.settings.deepgram_recheck_model or self._selected_model
        if self._recheck_engine is None or self._recheck_engine_model != model:
            self._recheck_engine = self.recheck_engine_factory(model)
            self._recheck_engine_model = model
        prompt = ""
        if self.context_engine is not None:
            prompt = ", ".join(self.context_engine.keyterms()[:30])[:500]
        started = perf_counter()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._recheck_engine.transcribe,
                samples,
                language=language,
                initial_prompt=prompt or None,
                beam_size=1,
            ),
            name="selective-whisper-recheck",
        )
        self._recheck_background_task = task
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self.settings.deepgram_recheck_timeout_seconds,
            )
        except TimeoutError:
            task.add_done_callback(self._finish_background_recheck)
            raise
        finally:
            if task.done() and self._recheck_background_task is task:
                self._recheck_background_task = None
        return result, round((perf_counter() - started) * 1_000)

    def _finish_background_recheck(self, task: asyncio.Task[Any]) -> None:
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass
        if self._recheck_background_task is task:
            self._recheck_background_task = None

    def _select_recheck_text(
        self,
        deepgram_text: str,
        whisper_text: str,
        risk_reasons: tuple[str, ...],
        language: str,
        words: tuple[DeepgramWord, ...] = (),
    ) -> tuple[str, str, bool]:
        if not whisper_text:
            return deepgram_text, "empty", False
        deepgram_normalized = (
            self.context_engine.normalize(deepgram_text)
            if self.context_engine is not None
            else None
        )
        whisper_normalized = (
            self.context_engine.normalize(whisper_text)
            if self.context_engine is not None
            else None
        )
        deepgram_compare = self._comparison_text(
            deepgram_normalized.normalized_text
            if deepgram_normalized is not None
            else deepgram_text
        )
        whisper_compare = self._comparison_text(
            whisper_normalized.normalized_text
            if whisper_normalized is not None
            else whisper_text
        )
        if deepgram_compare == whisper_compare:
            return deepgram_text, "agreed", False
        similarity = SequenceMatcher(None, deepgram_compare, whisper_compare).ratio()
        deepgram_incomplete = self._is_structurally_incomplete(deepgram_text, language)
        whisper_incomplete = self._is_structurally_incomplete(whisper_text, language)
        if (
            language == "ko"
            and "malformed_date_format" in risk_reasons
            and has_malformed_korean_date_format(deepgram_text)
            and has_explicit_korean_date(whisper_text)
            and similarity >= 0.75
            and self._preserves_clause_count(deepgram_text, whisper_text)
        ):
            return whisper_text, "accepted_date_format", True
        if (
            deepgram_incomplete
            and not whisper_incomplete
            and len(whisper_compare) >= len(deepgram_compare)
            and any(
                reason in {"short_fragment", "incomplete_ending", "forced_boundary"}
                for reason in risk_reasons
            )
        ):
            return whisper_text, "accepted_complete", True
        deepgram_matches = len(deepgram_normalized.matches) if deepgram_normalized else 0
        whisper_matches = len(whisper_normalized.matches) if whisper_normalized else 0
        context_better = whisper_matches > deepgram_matches
        localized = self._localized_recheck_patch(
            deepgram_text,
            whisper_text,
            words,
            context_better=context_better,
        )
        if localized and localized != deepgram_text:
            return (
                localized,
                "accepted_local_context" if context_better else "accepted_local",
                True,
            )
        if (
            context_better
            and similarity >= 0.80
            and self._preserves_clause_count(deepgram_text, whisper_text)
        ):
            return whisper_text, "accepted_context", True
        if similarity >= 0.92 and not whisper_incomplete and deepgram_incomplete:
            return whisper_text, "accepted_consensus", True
        return deepgram_text, "disagreed", False

    @classmethod
    def _localized_recheck_patch(
        cls,
        deepgram_text: str,
        whisper_text: str,
        words: tuple[DeepgramWord, ...],
        *,
        context_better: bool = False,
    ) -> str | None:
        if not words or not deepgram_text or not whisper_text:
            return None
        similarity = SequenceMatcher(
            None,
            deepgram_text,
            whisper_text,
            autojunk=False,
        ).ratio()
        if similarity < 0.72 or not cls._preserves_clause_count(
            deepgram_text,
            whisper_text,
        ):
            return None
        low_spans = cls._low_confidence_text_spans(deepgram_text, words)
        if not low_spans:
            return None

        matcher = SequenceMatcher(
            None,
            deepgram_text,
            whisper_text,
            autojunk=False,
        )
        pieces: list[str] = []
        changed = False
        for tag, source_start, source_end, target_start, target_end in matcher.get_opcodes():
            source_piece = deepgram_text[source_start:source_end]
            target_piece = whisper_text[target_start:target_end]
            if tag == "equal":
                pieces.append(source_piece)
                continue
            safe = False
            if tag == "insert":
                safe = (
                    len(target_piece) <= 4
                    and not any(mark in target_piece for mark in ".?!。？！")
                    and cls._near_low_confidence(source_start, low_spans)
                )
            elif tag == "replace":
                semantic_source = re.sub(r"[\s\W_]+", "", source_piece)
                semantic_target = re.sub(r"[\s\W_]+", "", target_piece)
                ideograph_swap = bool(
                    re.search(r"[\u3400-\u9fff]", semantic_source)
                    and re.search(r"[\u3400-\u9fff]", semantic_target)
                )
                safe = (
                    len(source_piece) <= 3
                    and len(target_piece) <= 4
                    and cls._range_is_low_confidence(
                        source_start,
                        source_end,
                        deepgram_text,
                        low_spans,
                    )
                    and (context_better or not ideograph_swap)
                )
            elif tag == "delete":
                # Never let a secondary recognizer remove semantic content or
                # another speaker's short response. Punctuation-only cleanup is
                # harmless and remains local.
                safe = not re.sub(r"[\s\W_]+", "", source_piece)
            if safe:
                pieces.append(target_piece)
                changed = changed or source_piece != target_piece
            else:
                pieces.append(source_piece)
        candidate = "".join(pieces).strip()
        if not changed or not candidate:
            return None
        return candidate

    @staticmethod
    def _low_confidence_text_spans(
        text: str,
        words: tuple[DeepgramWord, ...],
    ) -> tuple[tuple[int, int], ...]:
        spans: list[tuple[int, int]] = []
        cursor = 0
        for word in words:
            token = (word.word or word.punctuated_word).strip()
            if not token:
                continue
            position = text.find(token, cursor)
            if position < 0:
                position = text.find(token)
            if position < 0:
                continue
            end = position + len(token)
            cursor = end
            if word.confidence < 0.80:
                spans.append((position, end))
        return tuple(spans)

    @staticmethod
    def _near_low_confidence(
        position: int,
        spans: tuple[tuple[int, int], ...],
    ) -> bool:
        return any(start - 1 <= position <= end + 1 for start, end in spans)

    @staticmethod
    def _range_is_low_confidence(
        start: int,
        end: int,
        text: str,
        spans: tuple[tuple[int, int], ...],
    ) -> bool:
        semantic_positions = [
            position
            for position in range(start, end)
            if re.match(r"\w|[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text[position])
        ]
        return bool(semantic_positions) and all(
            any(span_start <= position < span_end for span_start, span_end in spans)
            for position in semantic_positions
        )

    @staticmethod
    def _preserves_clause_count(deepgram_text: str, whisper_text: str) -> bool:
        def boundaries(value: str) -> int:
            return len(re.findall(r"[.!?。？！]", value))

        return boundaries(whisper_text) >= boundaries(deepgram_text)

    @staticmethod
    def _comparison_text(text: str) -> str:
        return re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", text).casefold()

    @staticmethod
    def _is_structurally_incomplete(text: str, language: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped.endswith((".", "?", "!", "。", "？", "！")):
            return False
        if language == "ja":
            compact = re.sub(r"\s+", "", stripped)
            return len(compact) <= 2 or stripped.endswith(
                ("は", "が", "を", "に", "で", "と", "の", "も", "へ", "や", "から", "まで", "ので", "けど", "て")
            )
        if language == "en":
            tokens = re.findall(r"[A-Za-z0-9']+", stripped.casefold())
            return len(tokens) <= 1 or bool(
                tokens
                and tokens[-1]
                in {"and", "or", "but", "because", "to", "of", "for", "with", "the", "a", "an"}
            )
        if language == "ko":
            compact = re.sub(r"\s+", "", stripped)
            return len(compact) <= 2 or stripped.endswith(
                ("은", "는", "이", "가", "을", "를", "에", "에서", "와", "과", "도", "로", "으로")
            )
        return False

    async def _on_deepgram_error(self, code: str) -> None:
        if (
            self._status is not CaptureStatus.LISTENING
            or self._selected_stt_provider != "deepgram"
        ):
            return
        self._deepgram_failed = True
        self._deepgram_reconnecting = not self._deepgram_reconnect_exhausted
        self._ensure_deepgram_reconnect()
        if not self._deepgram_error_reported:
            self._deepgram_error_reported = True
            LOGGER.warning("Deepgram streaming STT interrupted: %s", code)
            await self.websocket_manager.broadcast(
                error_event(
                    code,
                    "Deepgram 연결이 끊겨 자동 재연결 중입니다. 최근 음성은 제한된 버퍼에 임시 보관됩니다.",
                    recoverable=True,
                    session_id=self._session_id,
                )
            )
        await self._broadcast_state(stage="provider_reconnecting")

    async def _publish_final_transcript(
        self,
        transcript: FinalTranscript,
        *,
        target_language: str = "ko",
        transcription_quality: dict[str, Any] | None = None,
    ) -> None:
        normalization = (
            self.context_engine.normalize(transcript.text)
            if self.context_engine is not None
            else None
        )
        normalized_text = (
            normalization.normalized_text if normalization is not None else transcript.text
        )
        context_snapshot = (
            self.context_engine.snapshot() if self.context_engine is not None else None
        )
        profile_id = (
            str(context_snapshot["active_profile_id"])
            if context_snapshot is not None
            else None
        )
        matches = (
            [dict(item) for item in normalization.matches]
            if normalization is not None
            else []
        )
        matched_glossary_terms = list(
            dict.fromkeys(
                str(item.get("canonical") or item.get("to") or "").strip()
                for item in matches
                if str(item.get("canonical") or item.get("to") or "").strip()
            )
        )
        try:
            await asyncio.to_thread(self.repository.append_final, transcript)
        except Exception as storage_error:
            LOGGER.error(
                "Final transcript persistence failed: %s",
                exception_kind(storage_error),
            )
            await self.websocket_manager.broadcast(
                error_event(
                    "session_storage_failed",
                    "원문은 표시하지만 세션 파일에 저장하지 못했습니다.",
                    recoverable=True,
                    session_id=transcript.session_id,
                    segment_id=transcript.segment_id,
                )
            )
        if transcription_quality is not None:
            try:
                await asyncio.to_thread(
                    self.repository.append_transcription_quality,
                    transcript.session_id,
                    transcription_quality,
                )
            except Exception as quality_storage_error:
                LOGGER.warning(
                    "Transcription quality persistence failed: %s",
                    exception_kind(quality_storage_error),
                )
        if self.context_engine is not None:
            try:
                await asyncio.to_thread(
                    self.repository.append_context_normalization,
                    transcript.session_id,
                    {
                        "segment_id": transcript.segment_id,
                        "profile_id": profile_id,
                        "normalized_text": normalized_text,
                        "changed": bool(normalization and normalization.changed),
                        "matches": matches,
                    },
                )
            except Exception as context_storage_error:
                LOGGER.error(
                    "Context normalization persistence failed: %s",
                    exception_kind(context_storage_error),
                )
                await self.websocket_manager.broadcast(
                    error_event(
                        "context_storage_failed",
                        "원문은 유지하지만 Context 적용 기록을 저장하지 못했습니다.",
                        recoverable=True,
                        session_id=transcript.session_id,
                        segment_id=transcript.segment_id,
                    )
                )
        final_payload = {
            **transcript.to_dict(),
            "target_language": self._target_language(),
            "normalized_text": normalized_text,
            "context_profile_id": profile_id,
            "context_changed": bool(normalization and normalization.changed),
            "context_matches": matches,
            "stt_quality": (
                {
                    key: transcription_quality.get(key)
                    for key in (
                        "boundary_reason",
                        "risk_reasons",
                        "recheck_status",
                        "recheck_accepted",
                        "recheck_latency_ms",
                    )
                }
                if transcription_quality is not None
                else None
            ),
        }
        await self.websocket_manager.broadcast(
            make_event("final_transcript", **final_payload)
        )
        if self.decision_radar_manager is not None:
            try:
                await self.decision_radar_manager.submit_final(
                    {"type": "final_transcript", **final_payload}
                )
            except asyncio.CancelledError:
                raise
            except Exception as radar_error:
                # Keep the original transcript and translation pipeline alive
                # even if real-time meeting analysis is unavailable.
                LOGGER.warning(
                    "Decision Radar enqueue failed: %s",
                    exception_kind(radar_error),
                )
        if self.translation_manager is None:
            return
        try:
            quality_risks = {
                str(value)
                for value in (
                    transcription_quality.get("risk_reasons", [])
                    if transcription_quality is not None
                    else []
                )
            }
            boundary_reason = (
                str(transcription_quality.get("boundary_reason", ""))
                if transcription_quality is not None
                else ""
            )
            source_is_incomplete = bool(
                {"short_fragment", "incomplete_ending"}.intersection(
                    quality_risks
                )
                or (
                    boundary_reason in {"hard_limit", "candidate_timeout"}
                    and not normalized_text.rstrip().endswith(
                        (".", "?", "!", "。", "？", "！")
                    )
                )
            )
            await self.translation_manager.submit_event(
                {
                    "type": "final_transcript",
                    **transcript.to_dict(),
                    "target_language": target_language,
                    "normalized_text": normalized_text,
                    "glossary_terms": matched_glossary_terms,
                    "boundary_reason": boundary_reason or None,
                    "risk_reasons": sorted(quality_risks),
                    "source_is_incomplete": source_is_incomplete,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.error("Translation enqueue failed: %s", exception_kind(exc))
            await self.websocket_manager.broadcast(
                make_event(
                    "translation_error",
                    segment_id=transcript.segment_id,
                    provider="unknown",
                    code="PROVIDER_UNAVAILABLE",
                    message="번역 작업을 등록하지 못했습니다. 원문 전사는 계속됩니다.",
                    recoverable=True,
                )
            )

    async def _transcription_worker(self) -> None:
        while True:
            await self._job_event.wait()
            while True:
                if self._final_jobs:
                    job = self._final_jobs.popleft()
                elif self._latest_partial is not None:
                    job, self._latest_partial = self._latest_partial, None
                else:
                    self._job_event.clear()
                    break

                self._transcription_active = True
                await self._broadcast_state()
                try:
                    result = await asyncio.to_thread(job.engine.transcribe, job.samples)
                    if not result.text.strip():
                        continue
                    if job.kind == SegmentEventType.PARTIAL.value:
                        # A final may have been queued while this inference was
                        # running.  The worker is serial, so it is still useful
                        # and cannot arrive after that final.  Only discard it
                        # when its entire session has already been replaced.
                        if job.session_id != self._session_id:
                            continue
                        await self.websocket_manager.broadcast(
                            make_event(
                                "partial_transcript",
                                session_id=job.session_id,
                                utterance_id=job.utterance_id,
                                source=job.source,
                                text=result.text.strip(),
                                language=result.detected_language,
                                language_probability=result.language_probability,
                                timestamp=job.ended_at.isoformat(timespec="milliseconds"),
                                status="transcribing",
                                inference_seconds=result.inference_seconds,
                            )
                        )
                    elif not job.deduplicator.is_duplicate(result.text):
                        transcript = FinalTranscript(
                            segment_id=str(uuid4()),
                            session_id=job.session_id,
                            utterance_id=job.utterance_id,
                            source=job.source,
                            text=result.text.strip(),
                            language=result.detected_language,
                            language_probability=result.language_probability,
                            started_at=job.started_at.isoformat(timespec="milliseconds"),
                            ended_at=job.ended_at.isoformat(timespec="milliseconds"),
                            inference_seconds=result.inference_seconds,
                        )
                        job.deduplicator.add(result.text)
                        await self._publish_final_transcript(transcript)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.error("Transcription job failed: %s", exception_kind(exc))
                    await self.websocket_manager.broadcast(
                        error_event(
                            "transcription_error",
                            "전사 처리 중 오류가 발생했습니다. 다음 발화를 계속 처리합니다.",
                            recoverable=True,
                            session_id=job.session_id,
                        )
                    )
                finally:
                    if job.kind == SegmentEventType.FINAL.value:
                        await self.websocket_manager.broadcast(
                            make_event(
                                "partial_clear",
                                session_id=job.session_id,
                                utterance_id=job.utterance_id,
                            )
                        )
                    self._transcription_active = False
                    if job.completion is not None and not job.completion.done():
                        job.completion.set_result(None)
                    await self._broadcast_state()

    async def _broadcast_level(self, level: float, dbfs: float) -> None:
        await self.websocket_manager.broadcast(
            make_event(
                "audio_level",
                source=self._source,
                level=max(0.0, min(1.0, float(level))),
                dbfs=float(dbfs),
                status=self.display_status,
            )
        )

    async def _update_session_status(self, status: str) -> None:
        if self.session_manager is None:
            return
        try:
            await self.session_manager.set_status(status)
        except Exception as exc:
            LOGGER.warning("Session status update failed: %s", exception_kind(exc))
            await self.websocket_manager.broadcast(
                error_event(
                    "session_status_update_failed",
                    "세션 상태를 저장하지 못했지만 캡처는 계속됩니다.",
                    recoverable=True,
                    session_id=self._session_id,
                )
            )

    async def _broadcast_state(self, **fields: Any) -> None:
        await self.websocket_manager.broadcast(
            state_event(
                self.display_status,
                state=self._status.value,
                source=self._source,
                device_id=self._device_id,
                model=self._selected_model,
                stt_provider=self._selected_stt_provider,
                translation_direction=self._translation_direction,
                source_language=self._source_language(),
                target_language=self._target_language(),
                stt_runtime=self.public_stt_info(),
                session_id=self._session_id,
                **fields,
            )
        )
