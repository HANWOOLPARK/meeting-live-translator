"""Small, deterministic PCM helpers used before VAD and transcription."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray


Float32Audio = NDArray[np.float32]


def pcm16_to_mono_float32(
    pcm: bytes | bytearray | memoryview | NDArray[Any],
    channels: int,
) -> Float32Audio:
    """Decode interleaved signed little-endian PCM16 and downmix to mono.

    The returned range is ``[-1.0, 1.0)``.  Channel averaging is performed in
    float32 so opposing or full-scale int16 samples cannot overflow.
    """

    if channels <= 0:
        raise ValueError("channels must be positive")

    if isinstance(pcm, np.ndarray):
        samples = np.asarray(pcm, dtype=np.int16).reshape(-1)
    else:
        payload = memoryview(pcm)
        if payload.nbytes % 2:
            raise ValueError("PCM16 payload must contain complete 2-byte samples")
        samples = np.frombuffer(payload, dtype="<i2")

    if samples.size % channels:
        raise ValueError("PCM16 sample count must be divisible by channels")
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)

    normalized = samples.astype(np.float32) / np.float32(32768.0)
    if channels == 1:
        return np.ascontiguousarray(normalized)
    return np.ascontiguousarray(normalized.reshape(-1, channels).mean(axis=1, dtype=np.float32))


def resample_audio(
    samples: ArrayLike,
    source_rate: int,
    target_rate: int = 16_000,
) -> Float32Audio:
    """Resample mono float audio with deterministic linear interpolation.

    Linear interpolation is sufficient for the short speech buffers in Phase
    1 and avoids adding a second optional native dependency.  A future backend
    may replace this implementation without changing the capture interface.
    """

    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim != 1:
        raise ValueError("resample_audio expects one-dimensional mono audio")
    if audio.size == 0:
        return np.empty(0, dtype=np.float32)
    if source_rate == target_rate:
        return np.ascontiguousarray(audio.copy())

    target_length = max(1, int(round(audio.size * target_rate / source_rate)))
    if audio.size == 1:
        return np.full(target_length, audio[0], dtype=np.float32)

    source_positions = np.arange(audio.size, dtype=np.float64)
    target_positions = np.arange(target_length, dtype=np.float64) * (
        source_rate / target_rate
    )
    target_positions = np.minimum(target_positions, audio.size - 1)
    result = np.interp(target_positions, source_positions, audio)
    return np.ascontiguousarray(result.astype(np.float32, copy=False))


def pcm16_to_mono_resampled(
    pcm: bytes | bytearray | memoryview | NDArray[Any],
    channels: int,
    source_rate: int,
    target_rate: int = 16_000,
) -> Float32Audio:
    mono = pcm16_to_mono_float32(pcm, channels)
    return resample_audio(mono, source_rate, target_rate)


def calculate_audio_level(samples: ArrayLike) -> float:
    """Return clipped RMS amplitude in the UI-friendly range ``0.0..1.0``."""

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return 0.0
    finite = audio[np.isfinite(audio)]
    if finite.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(finite.astype(np.float64)))))
    return min(1.0, max(0.0, rms))


def calculate_dbfs(samples: ArrayLike, *, floor_db: float = -96.0) -> float:
    """Return RMS dBFS, clamped to ``floor_db`` for silence."""

    if not math.isfinite(floor_db) or floor_db > 0:
        raise ValueError("floor_db must be a finite value no greater than zero")
    level = calculate_audio_level(samples)
    if level <= 0.0:
        return float(floor_db)
    return max(float(floor_db), 20.0 * math.log10(level))


def audio_level_from_pcm16(
    pcm: bytes | bytearray | memoryview | NDArray[Any], channels: int
) -> float:
    """Convenience wrapper returning RMS directly from interleaved PCM16."""

    return calculate_audio_level(pcm16_to_mono_float32(pcm, channels))

