from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import numpy as np

from backend.app.capture.controller import CaptureController
from backend.app.config.settings import AppSettings
from backend.app.sessions import FinalTranscript, SessionManager, StoragePolicy
from backend.app.sessions.repository import JsonlSessionRepository
from backend.app.transcription import (
    DeepgramTranscript,
    DeepgramWord,
    TranscriptionLoadError,
    TranscriptionResult,
)

from .fakes import LOOPBACK, FakeCaptureFactory, FakeDeviceProvider, RecordingManager


async def _wait_until(predicate: Any, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition was not reached")


class _TranslationManager:
    provider = type("Provider", (), {"provider_name": "none"})()

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def submit_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class _RadarManager:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def begin_session(self, session_id: str) -> None:
        self.session_id = session_id

    async def submit_final(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class _RiskyDeepgram:
    def __init__(self, text: str = "本日に") -> None:
        self.text = text
        self.connected = False
        self.transcript_sink: Any = None

    async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
        del error_sink
        self.transcript_sink = transcript_sink
        self.connected = True

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def stop(self) -> None:
        if not self.connected:
            return
        self.connected = False
        await self.transcript_sink(
            DeepgramTranscript(
                "final",
                self.text,
                0.72,
                0.0,
                0.1,
                boundary_reason="candidate_timeout",
                risk_reasons=("incomplete_ending", "low_transcript_confidence"),
            )
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": "deepgram",
            "configured": True,
            "connected": self.connected,
            "model": "nova-3",
            "language": "ja",
            "last_error": None,
        }


class _SuccessfulRecheck:
    def ensure_loaded(self) -> None:
        return None

    def model_info(self) -> dict[str, Any]:
        return {"model_name": "small", "loaded": True, "device": "cpu"}

    def transcribe(
        self,
        samples: np.ndarray,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
        beam_size: int | None = None,
    ) -> TranscriptionResult:
        assert samples.size > 0
        assert language == "ja"
        assert beam_size == 1
        del initial_prompt
        return TranscriptionResult(
            "本日の会議を開始します。",
            "ja",
            0.99,
            0.0,
            len(samples) / 16_000,
            0.02,
        )


class _UnavailableRecheck(_SuccessfulRecheck):
    def transcribe(self, samples: np.ndarray, **kwargs: Any) -> TranscriptionResult:
        del samples, kwargs
        raise TranscriptionLoadError("model is not present in the local cache")


class _SlowRecheck(_SuccessfulRecheck):
    def transcribe(self, samples: np.ndarray, **kwargs: Any) -> TranscriptionResult:
        time.sleep(0.7)
        return super().transcribe(samples, **kwargs)


async def _run_capture(tmp_path, engine: Any, *, timeout: float = 4.0) -> tuple[Any, ...]:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
        deepgram_api_key="configured-secret",
        deepgram_recheck_timeout_seconds=timeout,
    )
    repository = JsonlSessionRepository(settings.session_dir)
    session_manager = SessionManager(repository)
    captures = FakeCaptureFactory()
    websocket = RecordingManager()
    translations = _TranslationManager()
    radar = _RadarManager()
    deepgram = _RiskyDeepgram()
    controller = CaptureController(
        settings,
        FakeDeviceProvider(),
        websocket,  # type: ignore[arg-type]
        repository,
        capture_factory=captures,
        deepgram_factory=lambda _language: deepgram,
        recheck_engine_factory=lambda _model: engine,
        translation_manager=translations,  # type: ignore[arg-type]
        session_manager=session_manager,
        decision_radar_manager=radar,  # type: ignore[arg-type]
    )
    started = await controller.start(
        "system",
        LOOPBACK.device_id,
        "small",
        "deepgram",
        "ja_to_ko",
    )
    captures.latest.emit(np.full(1_600, 0.1, dtype=np.float32))
    await _wait_until(
        lambda: controller.public_stt_info()["selective_recheck"]["buffered_seconds"]
        >= 0.1
    )
    await controller.stop()
    runtime = controller.public_stt_info()["selective_recheck"]
    await controller.shutdown()
    return (
        started,
        websocket.events,
        translations.events,
        radar.events,
        runtime,
        settings.session_dir,
    )


def _quality_record(session_dir, session_id: str) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in (session_dir / session_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    return next(record for record in records if record["type"] == "transcription_quality")


def test_risky_deepgram_final_uses_conservative_whisper_recheck_once(tmp_path) -> None:
    async def scenario() -> None:
        started, events, translations, radar, runtime, session_dir = await _run_capture(
            tmp_path,
            _SuccessfulRecheck(),
        )
        final = next(event for event in events if event.get("type") == "final_transcript")
        provisional = next(
            event
            for event in events
            if event.get("type") == "partial_transcript"
            and event.get("provisional") is True
        )
        assert events.index(provisional) < events.index(final)
        assert provisional["stage"] == "quality_review"
        assert provisional["text"] == "本日に"
        assert final["text"] == "本日の会議を開始します。"
        assert final["stt_quality"]["recheck_status"] == "accepted_complete"
        assert len(translations) == 1
        assert translations[0]["text"] == "本日の会議を開始します。"
        assert len(radar) == 1
        assert radar[0]["text"] == "本日の会議を開始します。"
        assert runtime["requested"] == 1
        assert runtime["accepted"] == 1

        quality = _quality_record(session_dir, started["session_id"])
        assert quality["deepgram_text"] == "本日に"
        assert quality["selected_text"] == "本日の会議を開始します。"
        assert quality["recheck_accepted"] is True
        assert quality["provisional_displayed"] is True
        assert quality["audio_end_to_provider_ms"] >= 0
        assert quality["canonical_processing_ms"] >= 0
        assert quality["final_queue_wait_ms"] >= 0
        assert quality["provider_received_at"]
        assert quality["canonical_ready_at"]
        assert "audio" not in quality

    asyncio.run(scenario())


def test_low_confidence_japanese_insertions_are_patched_locally() -> None:
    words = (
        DeepgramWord("にちは", "にちは。", 0.42, 0.0, 0.4),
        DeepgramWord(
            "お世になております",
            "お世になております。",
            0.51,
            0.4,
            1.4,
        ),
    )
    patched = CaptureController._localized_recheck_patch(
        "にちは。お世になております。",
        "こんにちは。お世話になっております。",
        words,
    )
    assert patched == "こんにちは。お世話になっております。"


def test_malformed_korean_date_prefers_complete_whisper_date() -> None:
    controller = object.__new__(CaptureController)
    controller.context_engine = None
    selected, status, accepted = controller._select_recheck_text(
        "부하 시험 시간을 확보하기 위해 공개일은 8 월 21로 확정합니다.",
        "부하 시험 시간을 확보하기 위해 공개일은 8월 20일로 확정합니다.",
        ("malformed_date_format",),
        "ko",
    )
    assert selected.endswith("8월 20일로 확정합니다.")
    assert status == "accepted_date_format"
    assert accepted is True


def test_low_confidence_kanji_substitution_is_rejected_without_context_evidence() -> None:
    words = (
        DeepgramWord("聴解", "聴解", 0.43, 0.0, 0.4),
        DeepgramWord("に", "に", 0.98, 0.4, 0.5),
        DeepgramWord("挑戦します", "挑戦します。", 0.98, 0.5, 1.2),
    )
    patched = CaptureController._localized_recheck_patch(
        "聴解に挑戦します。",
        "調解に挑戦します。",
        words,
    )
    assert patched is None


def test_local_recheck_never_deletes_an_independent_response() -> None:
    words = (
        DeepgramWord(
            "よろしくお願いいたします",
            "よろしくお願いいたします。",
            0.61,
            0.0,
            1.0,
        ),
        DeepgramWord("お願いします", "お願いします。", 0.52, 1.0, 1.5),
    )
    patched = CaptureController._localized_recheck_patch(
        "よろしくお願いいたします。お願いします。",
        "よろしくお願いいたします。",
        words,
    )
    assert patched is None


def test_missing_cached_whisper_model_falls_back_without_duplicate_delivery(tmp_path) -> None:
    async def scenario() -> None:
        started, events, translations, radar, runtime, session_dir = await _run_capture(
            tmp_path,
            _UnavailableRecheck(),
        )
        finals = [event for event in events if event.get("type") == "final_transcript"]
        assert [event["text"] for event in finals] == ["本日に"]
        assert len(translations) == 1
        assert len(radar) == 1
        assert runtime["unavailable"] is True
        assert runtime["failed"] == 1
        quality = _quality_record(session_dir, started["session_id"])
        assert quality["recheck_status"] == "model_unavailable"
        assert quality["selected_text"] == "本日に"

    asyncio.run(scenario())


def test_whisper_timeout_keeps_deepgram_and_does_not_block_session_stop(tmp_path) -> None:
    async def scenario() -> None:
        started_at = time.perf_counter()
        started, events, translations, radar, runtime, session_dir = await _run_capture(
            tmp_path,
            _SlowRecheck(),
            timeout=0.5,
        )
        elapsed = time.perf_counter() - started_at
        final = next(event for event in events if event.get("type") == "final_transcript")
        assert final["text"] == "本日に"
        assert len(translations) == 1
        assert len(radar) == 1
        assert runtime["timed_out"] == 1
        assert elapsed < 1.5
        quality = _quality_record(session_dir, started["session_id"])
        assert quality["recheck_status"] == "timeout"

    asyncio.run(scenario())


def test_quality_event_respects_original_storage_consent(tmp_path) -> None:
    repository = JsonlSessionRepository(tmp_path / "sessions")
    session_id = repository.start_session(
        {"source": "system", "whisper_model": "deepgram:nova-3"},
        storage_policy=StoragePolicy(save_original=False),
    )
    repository.append_final(
        FinalTranscript(
            segment_id="segment-private",
            session_id=session_id,
            utterance_id="utterance-private",
            source="system",
            text="private source text",
            language="en",
            language_probability=0.7,
            started_at="2026-07-18T10:00:00+09:00",
            ended_at="2026-07-18T10:00:01+09:00",
            inference_seconds=0.0,
        )
    )
    repository.append_transcription_quality(
        session_id,
        {
            "segment_id": "segment-private",
            "deepgram_text": "private source text",
            "whisper_text": "private alternative text",
            "selected_text": "private source text",
            "risk_reasons": ["low_word_confidence"],
            "recheck_status": "disagreed",
        },
    )
    content = (tmp_path / "sessions" / session_id / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "transcription_quality" in content
    assert "private source text" not in content
    assert "private alternative text" not in content
