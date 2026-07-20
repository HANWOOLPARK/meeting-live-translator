"""Pre-buffered utterance segmentation for near-real-time transcription."""

from __future__ import annotations

import math
from collections import deque

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .models import SegmentEvent, SegmentEventType
from .vad import EnergyVoiceActivityDetector


class UtteranceSegmenter:
    """Turn PCM callback frames into partial and final utterance snapshots.

    Public event contract:

    * :meth:`process` returns zero or more ``partial``/``final`` events.
    * :meth:`snapshot` returns an on-demand ``partial`` event without changing
      the automatic partial schedule.
    * :meth:`flush` emits at most one ``final`` event and preserves the session
      timeline, making it suitable for pause/stop.
    * :meth:`reset` emits one empty ``reset`` event and, by default, restarts the
      timeline at zero, making it suitable for a new capture session.

    Speech decisions are frame based.  Capture callbacks should therefore feed
    short, regular frames (roughly 20--30 ms).
    """

    def __init__(
        self,
        vad: EnergyVoiceActivityDetector | None = None,
        *,
        sample_rate: int = 16_000,
        pre_buffer_ms: int = 400,
        silence_grace_ms: int = 800,
        min_utterance_ms: int = 250,
        partial_start_ms: int = 1_200,
        partial_interval_ms: int = 1_500,
        partial_window_ms: int = 12_000,
        max_utterance_ms: int = 20_000,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        durations = {
            "pre_buffer_ms": pre_buffer_ms,
            "silence_grace_ms": silence_grace_ms,
            "min_utterance_ms": min_utterance_ms,
            "partial_start_ms": partial_start_ms,
            "partial_interval_ms": partial_interval_ms,
            "partial_window_ms": partial_window_ms,
            "max_utterance_ms": max_utterance_ms,
        }
        if any(value < 0 for value in durations.values()):
            raise ValueError("segment durations must not be negative")
        if partial_interval_ms <= 0 or partial_window_ms <= 0 or max_utterance_ms <= 0:
            raise ValueError("partial interval/window and maximum utterance must be positive")

        self.vad = vad or EnergyVoiceActivityDetector()
        self.sample_rate = int(sample_rate)
        self.pre_buffer_samples = self._milliseconds_to_samples(pre_buffer_ms)
        self.silence_grace_samples = self._milliseconds_to_samples(silence_grace_ms)
        self.min_utterance_samples = self._milliseconds_to_samples(min_utterance_ms)
        self.partial_start_samples = self._milliseconds_to_samples(partial_start_ms)
        self.partial_interval_samples = max(1, self._milliseconds_to_samples(partial_interval_ms))
        self.partial_window_samples = max(1, self._milliseconds_to_samples(partial_window_ms))
        self.max_utterance_samples = max(1, self._milliseconds_to_samples(max_utterance_ms))

        self._pre_buffer: deque[NDArray[np.float32]] = deque()
        self._pre_buffer_length = 0
        self._active_chunks: list[NDArray[np.float32]] = []
        self._active_length = 0
        self._active_started_sample: int | None = None
        self._last_voice_end_sample: int | None = None
        self._voiced_samples = 0
        self._next_partial_at_sample: int | None = None
        self._total_samples = 0

    def _milliseconds_to_samples(self, milliseconds: int) -> int:
        return int(round(self.sample_rate * milliseconds / 1_000.0))

    @staticmethod
    def _audio(samples: ArrayLike) -> NDArray[np.float32]:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("samples must be a one-dimensional mono array")
        if not np.isfinite(audio).all():
            audio = np.nan_to_num(audio, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)
        else:
            audio = audio.copy()
        return audio

    @property
    def active(self) -> bool:
        return self._active_started_sample is not None

    @property
    def elapsed_seconds(self) -> float:
        return self._total_samples / self.sample_rate

    def _append_pre_buffer(self, audio: NDArray[np.float32]) -> None:
        if self.pre_buffer_samples <= 0 or audio.size == 0:
            return
        self._pre_buffer.append(audio.copy())
        self._pre_buffer_length += int(audio.size)
        overflow = self._pre_buffer_length - self.pre_buffer_samples
        while overflow > 0 and self._pre_buffer:
            first = self._pre_buffer[0]
            if first.size <= overflow:
                self._pre_buffer.popleft()
                self._pre_buffer_length -= int(first.size)
                overflow -= int(first.size)
            else:
                self._pre_buffer[0] = first[overflow:].copy()
                self._pre_buffer_length -= overflow
                overflow = 0

    def _start_utterance(
        self,
        frame_start_sample: int,
        frame_end_sample: int,
        voiced_frame: NDArray[np.float32],
    ) -> None:
        self._active_chunks = [chunk.copy() for chunk in self._pre_buffer]
        self._active_length = self._pre_buffer_length
        if self._active_length:
            self._active_started_sample = frame_end_sample - self._active_length
        else:
            # With a disabled pre-buffer the triggering frame is not present in
            # the deque, so retain it explicitly.
            self._active_chunks = [voiced_frame.copy()]
            self._active_length = int(voiced_frame.size)
            self._active_started_sample = frame_start_sample
        self._last_voice_end_sample = frame_end_sample
        self._voiced_samples = int(voiced_frame.size)
        self._next_partial_at_sample = self._active_started_sample + self.partial_start_samples
        self._pre_buffer.clear()
        self._pre_buffer_length = 0

    def _append_active(self, audio: NDArray[np.float32]) -> None:
        if audio.size:
            self._active_chunks.append(audio.copy())
            self._active_length += int(audio.size)

    def _active_audio(self, *, end_sample: int | None = None) -> NDArray[np.float32]:
        if not self._active_chunks or self._active_started_sample is None:
            return np.empty(0, dtype=np.float32)
        combined = np.concatenate(self._active_chunks).astype(np.float32, copy=False)
        if end_sample is not None:
            wanted = max(0, end_sample - self._active_started_sample)
            combined = combined[:wanted]
        return combined.copy()

    def _clear_active(self) -> None:
        self._active_chunks.clear()
        self._active_length = 0
        self._active_started_sample = None
        self._last_voice_end_sample = None
        self._voiced_samples = 0
        self._next_partial_at_sample = None

    def _event(
        self,
        event_type: SegmentEventType,
        samples: NDArray[np.float32],
        started_sample: int,
        ended_sample: int,
        reason: str,
    ) -> SegmentEvent:
        return SegmentEvent(
            event_type=event_type,
            samples=samples.copy(),
            started_offset=max(0.0, started_sample / self.sample_rate),
            ended_offset=max(0.0, ended_sample / self.sample_rate),
            reason=reason,
        )

    def snapshot(self) -> SegmentEvent | None:
        """Copy the latest partial window, or return ``None`` while idle."""

        if self._active_started_sample is None:
            return None
        audio = self._active_audio()
        ended_sample = self._active_started_sample + int(audio.size)
        if audio.size > self.partial_window_samples:
            audio = audio[-self.partial_window_samples :].copy()
            started_sample = ended_sample - int(audio.size)
        else:
            started_sample = self._active_started_sample
        return self._event(
            SegmentEventType.PARTIAL,
            audio,
            started_sample,
            ended_sample,
            "interval",
        )

    def _finalize(self, *, reason: str, ended_sample: int | None = None) -> SegmentEvent | None:
        if self._active_started_sample is None:
            return None
        if ended_sample is None:
            ended_sample = self._active_started_sample + self._active_length
        started_sample = self._active_started_sample
        audio = self._active_audio(end_sample=ended_sample)
        emit = self._voiced_samples >= self.min_utterance_samples and audio.size > 0
        self._clear_active()
        if not emit:
            return None
        return self._event(
            SegmentEventType.FINAL,
            audio,
            started_sample,
            ended_sample,
            reason,
        )

    def process(
        self,
        samples: ArrayLike,
        *,
        is_speech: bool | None = None,
    ) -> list[SegmentEvent]:
        """Process one PCM frame and return newly ready events."""

        audio = self._audio(samples)
        if audio.size == 0:
            return []
        speech = self.vad.is_speech(audio) if is_speech is None else bool(is_speech)
        frame_start = self._total_samples
        frame_end = frame_start + int(audio.size)
        self._total_samples = frame_end
        events: list[SegmentEvent] = []

        if not self.active:
            self._append_pre_buffer(audio)
            if speech:
                self._start_utterance(frame_start, frame_end, audio)
        else:
            self._append_active(audio)
            if speech:
                self._last_voice_end_sample = frame_end
                self._voiced_samples += int(audio.size)

        if not self.active:
            return events

        assert self._active_started_sample is not None
        if self._active_length >= self.max_utterance_samples:
            final = self._finalize(reason="max_duration")
            if final is not None:
                events.append(final)
            return events

        if not speech and self._last_voice_end_sample is not None:
            silence = frame_end - self._last_voice_end_sample
            if silence >= self.silence_grace_samples:
                cutoff = self._last_voice_end_sample + self.silence_grace_samples
                trailing_count = max(0, frame_end - cutoff)
                trailing = audio[-trailing_count:].copy() if trailing_count else None
                final = self._finalize(reason="silence", ended_sample=cutoff)
                if trailing is not None:
                    self._append_pre_buffer(trailing)
                if final is not None:
                    events.append(final)
                return events

        if (
            self._next_partial_at_sample is not None
            and frame_end >= self._next_partial_at_sample
        ):
            partial = self.snapshot()
            if partial is not None:
                events.append(partial)
            # Move from the previous deadline so irregular callback frames do
            # not create long-term schedule drift.
            elapsed_intervals = max(
                1,
                math.floor(
                    (frame_end - self._next_partial_at_sample) / self.partial_interval_samples
                )
                + 1,
            )
            self._next_partial_at_sample += elapsed_intervals * self.partial_interval_samples

        return events

    # ``push`` is a concise alias useful in callback-oriented integrations.
    push = process

    def flush(self) -> list[SegmentEvent]:
        """Finalize a qualifying active utterance and clear buffered silence."""

        events: list[SegmentEvent] = []
        final = self._finalize(reason="flush")
        if final is not None:
            events.append(final)
        self._pre_buffer.clear()
        self._pre_buffer_length = 0
        return events

    def reset(self, *, reason: str = "reset", reset_timeline: bool = True) -> list[SegmentEvent]:
        """Discard all buffered audio and emit an explicit reset event."""

        current_sample = self._total_samples
        self._clear_active()
        self._pre_buffer.clear()
        self._pre_buffer_length = 0
        if reset_timeline:
            self._total_samples = 0
        event = self._event(
            SegmentEventType.RESET,
            np.empty(0, dtype=np.float32),
            current_sample,
            current_sample,
            reason,
        )
        return [event]
