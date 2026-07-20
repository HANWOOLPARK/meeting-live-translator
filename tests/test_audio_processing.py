from __future__ import annotations

import numpy as np
import pytest

from backend.app.audio.processing import (
    audio_level_from_pcm16,
    calculate_audio_level,
    calculate_dbfs,
    pcm16_to_mono_float32,
    pcm16_to_mono_resampled,
    resample_audio,
)


def test_pcm16_stereo_downmixes_without_integer_overflow() -> None:
    interleaved = np.array(
        [32767, 32767, -32768, -32768, 32767, -32768], dtype="<i2"
    )

    mono = pcm16_to_mono_float32(interleaved.tobytes(), channels=2)

    assert mono.dtype == np.float32
    assert mono.shape == (3,)
    np.testing.assert_allclose(
        mono,
        np.array([32767 / 32768, -1.0, -0.5 / 32768], dtype=np.float32),
        atol=1e-7,
    )


def test_resample_length_and_original_sample_positions() -> None:
    source = np.array([0.0, 1.0, 0.0, -1.0], dtype=np.float32)

    result = resample_audio(source, source_rate=4, target_rate=8)

    assert result.dtype == np.float32
    assert result.shape == (8,)
    np.testing.assert_allclose(result[::2], source)


def test_pcm_decode_and_resample_composition() -> None:
    pcm = np.arange(12, dtype="<i2").tobytes()
    result = pcm16_to_mono_resampled(pcm, channels=2, source_rate=6, target_rate=3)
    assert result.shape == (3,)


def test_audio_level_and_dbfs() -> None:
    assert calculate_audio_level(np.zeros(16, dtype=np.float32)) == 0.0
    assert calculate_dbfs(np.zeros(16, dtype=np.float32)) == -96.0
    assert calculate_audio_level(np.ones(16, dtype=np.float32)) == 1.0
    assert calculate_dbfs(np.ones(16, dtype=np.float32)) == pytest.approx(0.0)
    assert calculate_audio_level(np.full(16, 0.5, dtype=np.float32)) == pytest.approx(0.5)
    assert calculate_dbfs(np.full(16, 0.5, dtype=np.float32)) == pytest.approx(
        -6.0206, abs=1e-3
    )


def test_pcm_level_convenience_function() -> None:
    pcm = np.full(32, 16384, dtype="<i2").tobytes()
    assert audio_level_from_pcm16(pcm, channels=1) == pytest.approx(0.5)


@pytest.mark.parametrize("channels", [0, -1])
def test_pcm_conversion_rejects_bad_channel_count(channels: int) -> None:
    with pytest.raises(ValueError):
        pcm16_to_mono_float32(b"\x00\x00", channels=channels)


def test_pcm_conversion_rejects_partial_samples_and_frames() -> None:
    with pytest.raises(ValueError):
        pcm16_to_mono_float32(b"\x00", channels=1)
    with pytest.raises(ValueError):
        pcm16_to_mono_float32(b"\x00\x00", channels=2)


def test_resample_rejects_invalid_shape_or_rate() -> None:
    with pytest.raises(ValueError):
        resample_audio(np.zeros((2, 2), dtype=np.float32), 48_000, 16_000)
    with pytest.raises(ValueError):
        resample_audio(np.zeros(2, dtype=np.float32), 0, 16_000)

