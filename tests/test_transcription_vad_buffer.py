from __future__ import annotations

import numpy as np
import pytest

from backend.app.transcription.buffer import UtteranceSegmenter
from backend.app.transcription.models import SegmentEventType
from backend.app.transcription.vad import EnergyVoiceActivityDetector


def test_energy_vad_uses_float_rms_and_handles_non_finite_values():
    detector = EnergyVoiceActivityDetector(threshold=0.02)
    assert detector.rms(np.zeros(100, dtype=np.float32)) == 0.0
    assert detector.is_speech(np.full(100, 0.03, dtype=np.float32))
    assert not detector.is_speech(np.full(100, 0.01, dtype=np.float32))
    assert detector.rms(np.array([np.nan, np.inf, -np.inf], dtype=np.float32)) == pytest.approx(
        np.sqrt(2 / 3)
    )


def test_segmenter_defaults_match_phase1_buffer_policy():
    segmenter = UtteranceSegmenter()
    assert segmenter.sample_rate == 16_000
    assert segmenter.pre_buffer_samples == 6_400
    assert segmenter.silence_grace_samples == 12_800
    assert segmenter.min_utterance_samples == 4_000


def test_prebuffer_grace_and_minimum_voice_produce_one_final_event():
    segmenter = UtteranceSegmenter()
    silence = np.zeros(1_600, dtype=np.float32)  # 100 ms
    voice = np.full(1_600, 0.05, dtype=np.float32)

    events = []
    for _ in range(4):
        events.extend(segmenter.process(silence, is_speech=False))
    for _ in range(3):
        events.extend(segmenter.process(voice, is_speech=True))
    for _ in range(8):
        events.extend(segmenter.process(silence, is_speech=False))

    finals = [event for event in events if event.event_type is SegmentEventType.FINAL]
    assert len(finals) == 1
    final = finals[0]
    assert final.reason == "silence"
    assert final.started_offset == pytest.approx(0.1)
    assert final.ended_offset == pytest.approx(1.5)
    assert final.samples.size == 22_400
    # The captured snapshot begins with the configured pre-roll and retains the
    # complete 300 ms speech burst before its 800 ms grace tail.
    assert np.all(final.samples[:4_800] == 0.0)
    assert np.all(final.samples[4_800:9_600] == 0.05)


def test_short_voice_burst_is_discarded():
    segmenter = UtteranceSegmenter()
    voice = np.full(1_600, 0.05, dtype=np.float32)
    silence = np.zeros(1_600, dtype=np.float32)

    events = []
    for _ in range(2):  # 200 ms voiced, below the 250 ms minimum
        events.extend(segmenter.process(voice, is_speech=True))
    for _ in range(8):
        events.extend(segmenter.process(silence, is_speech=False))

    assert not any(event.event_type is SegmentEventType.FINAL for event in events)
    assert not segmenter.active


def test_partial_schedule_snapshot_window_flush_and_reset_contract():
    segmenter = UtteranceSegmenter(
        sample_rate=1_000,
        pre_buffer_ms=0,
        silence_grace_ms=200,
        min_utterance_ms=100,
        partial_start_ms=300,
        partial_interval_ms=200,
        partial_window_ms=400,
        max_utterance_ms=2_000,
    )
    frame = np.full(100, 0.1, dtype=np.float32)

    events = []
    for _ in range(5):
        events.extend(segmenter.process(frame, is_speech=True))

    partials = [event for event in events if event.event_type is SegmentEventType.PARTIAL]
    assert [event.ended_offset for event in partials] == pytest.approx([0.3, 0.5])
    assert partials[-1].samples.size == 400  # capped partial window
    on_demand = segmenter.snapshot()
    assert on_demand is not None and on_demand.samples.size == 400

    flushed = segmenter.flush()
    assert len(flushed) == 1
    assert flushed[0].event_type is SegmentEventType.FINAL
    assert flushed[0].reason == "flush"
    assert flushed[0].samples.size == 500

    reset = segmenter.reset(reason="new_session")
    assert len(reset) == 1
    assert reset[0].event_type is SegmentEventType.RESET
    assert reset[0].samples.size == 0
    assert reset[0].reason == "new_session"
    assert segmenter.elapsed_seconds == 0.0
