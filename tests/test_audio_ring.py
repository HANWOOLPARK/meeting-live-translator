from __future__ import annotations

import numpy as np

from backend.app.transcription import Pcm16RingBuffer


def _pcm(value: int, samples: int) -> bytes:
    return np.full(samples, value, dtype="<i2").tobytes()


def test_pcm_ring_is_bounded_and_extracts_across_chunks() -> None:
    ring = Pcm16RingBuffer(sample_rate=10, max_seconds=2.0)
    ring.append(_pcm(1_000, 10), started_offset=0.0)
    ring.append(_pcm(2_000, 10), started_offset=1.0)
    ring.append(_pcm(3_000, 10), started_offset=2.0)

    snapshot = ring.snapshot()
    assert snapshot["buffered_seconds"] == 2.0
    assert snapshot["buffered_bytes"] == 40

    audio = ring.extract(1.5, 2.5, padding_before=0.0, padding_after=0.0)
    assert audio is not None
    assert audio.started_offset == 1.5
    assert audio.ended_offset == 2.5
    assert audio.samples.shape == (10,)
    np.testing.assert_allclose(audio.samples[:5], 2_000 / 32768.0)
    np.testing.assert_allclose(audio.samples[5:], 3_000 / 32768.0)


def test_pcm_ring_uses_absolute_offsets_across_stream_reconnects() -> None:
    ring = Pcm16RingBuffer(sample_rate=10, max_seconds=14.0)
    ring.append(_pcm(1_000, 5), started_offset=4.5)
    # A reconnected provider stream starts at zero internally, but the capture
    # controller continues appending with the absolute session offset.
    ring.append(_pcm(2_000, 5), started_offset=5.0)

    audio = ring.extract(4.8, 5.2, padding_before=0.0, padding_after=0.0)
    assert audio is not None
    assert audio.started_offset == 4.8
    assert audio.ended_offset == 5.2
    np.testing.assert_allclose(audio.samples[:2], 1_000 / 32768.0)
    np.testing.assert_allclose(audio.samples[2:], 2_000 / 32768.0)


def test_pcm_ring_clear_removes_audio_without_persistence(tmp_path) -> None:
    ring = Pcm16RingBuffer(sample_rate=16_000, max_seconds=14.0)
    ring.append(_pcm(1_000, 16_000), started_offset=0.0)
    ring.clear()
    assert ring.extract(0.0, 1.0) is None
    assert ring.snapshot() == {"buffered_seconds": 0.0, "buffered_bytes": 0}
    assert list(tmp_path.iterdir()) == []
