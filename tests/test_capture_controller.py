from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.app.capture.controller import CaptureController, CaptureStatus
from backend.app.config.settings import AppSettings
from backend.app.errors import SafeAppError
from backend.app.sessions.repository import JsonlSessionRepository
from backend.app.transcription.models import (
    SegmentEvent,
    SegmentEventType,
    TranscriptionResult,
)

from .fakes import (
    LOOPBACK,
    FakeCaptureFactory,
    FakeDeviceProvider,
    FakeEngine,
    RecordingManager,
)


async def _wait_for_event(
    manager: RecordingManager,
    event_type: str,
    *,
    timeout: float = 3.0,
) -> dict[str, object]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for event in manager.events:
            if event.get("type") == event_type:
                return event
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {event_type}")


def test_controller_emits_partial_final_and_persists_only_final(tmp_path) -> None:
    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        manager = RecordingManager()
        captures = FakeCaptureFactory()
        repository = JsonlSessionRepository(settings.session_dir)
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            repository,
            capture_factory=captures,
            engine_factory=FakeEngine,
        )

        result = await controller.start("system", LOOPBACK.device_id, "small")
        assert result["state"] == "listening"
        assert list(settings.session_dir.glob("*.jsonl")) == []

        speech = np.full(1_600, 0.1, dtype=np.float32)
        silence = np.zeros(1_600, dtype=np.float32)
        for _ in range(12):
            captures.latest.emit(speech)
        partial = await _wait_for_event(manager, "partial_transcript")
        assert partial["text"] == "途中の字幕です"
        assert list(settings.session_dir.glob("*.jsonl")) == []

        for _ in range(8):
            captures.latest.emit(silence)
        final = await _wait_for_event(manager, "final_transcript")
        assert final["text"] == "確定した文章です"
        assert final["language"] == "ja"
        files = list(settings.session_dir.glob("*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "確定した文章です" in content
        assert "途中の字幕です" not in content

        paused = await controller.pause()
        assert paused["state"] == "paused"
        resumed = await controller.resume()
        assert resumed["state"] == "listening"
        stopped = await controller.stop()
        assert stopped["state"] == "stopped"
        assert await controller.stop() == stopped
        await controller.shutdown()

    asyncio.run(scenario())


def test_local_whisper_accepts_english_to_korean_direction(tmp_path) -> None:
    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            engine_factory=FakeEngine,
        )

        started = await controller.start(
            "system", LOOPBACK.device_id, "small", "local", "en_to_ko"
        )

        assert started["translation_direction"] == "en_to_ko"
        assert started["source_language"] == "en"
        assert started["target_language"] == "ko"
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("translation_direction", "source_language", "target_language"),
    (("ja_to_en", "ja", "en"), ("en_to_ja", "en", "ja")),
)
def test_cross_language_directions_require_external_translation_but_allow_local_stt(
    tmp_path,
    translation_direction: str,
    source_language: str,
    target_language: str,
) -> None:
    class RecordingTranslationManager:
        provider = type("Provider", (), {"provider_name": "none"})()

        async def submit_event(self, event):
            return None

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        translations = RecordingTranslationManager()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            engine_factory=FakeEngine,
            translation_manager=translations,  # type: ignore[arg-type]
        )

        with pytest.raises(SafeAppError) as rejected:
            await controller.start(
                "system",
                LOOPBACK.device_id,
                "small",
                "local",
                translation_direction,
            )
        assert rejected.value.code == "reverse_translation_provider_required"

        translations.provider = type("Provider", (), {"provider_name": "gemini"})()
        started = await controller.start(
            "system",
            LOOPBACK.device_id,
            "small",
            "local",
            translation_direction,
        )
        assert started["translation_direction"] == translation_direction
        assert started["source_language"] == source_language
        assert started["target_language"] == target_language
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_pause_failure_rolls_back_controller_state(tmp_path) -> None:
    class PauseFailureCapture(FakeCaptureFactory):
        def __call__(self, device):
            capture = super().__call__(device)

            def fail_pause():
                raise RuntimeError("driver refused pause")

            capture.pause = fail_pause  # type: ignore[method-assign]
            return capture

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        captures = PauseFailureCapture()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
        )
        await controller.start("system", LOOPBACK.device_id)
        with pytest.raises(SafeAppError) as captured:
            await controller.pause()
        assert captured.value.code == "capture_pause_failed"
        assert controller.status is CaptureStatus.LISTENING
        assert controller.snapshot()["display_state"] == "listening"
        assert captures.latest.state.value == "running"
        assert controller._accept_frames is True
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_cancelled_model_load_cleans_controller_state(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    class GateEngine(FakeEngine):
        def ensure_loaded(self) -> None:
            started.set()
            assert release.wait(timeout=2.0)
            self.loaded = True

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            engine_factory=GateEngine,
        )
        task = asyncio.create_task(
            controller.start("system", LOOPBACK.device_id),
        )
        assert await asyncio.to_thread(started.wait, 1.0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert controller.status is CaptureStatus.STOPPED
        assert controller.snapshot()["display_state"] == "stopped"
        assert controller._accept_frames is False
        await controller.shutdown()

    asyncio.run(scenario())


def test_cancelled_pause_finishes_consistent_paused_state(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowPauseFactory(FakeCaptureFactory):
        def __call__(self, device):
            capture = super().__call__(device)

            def slow_pause():
                started.set()
                assert release.wait(timeout=2.0)
                capture._state = capture._state.__class__.PAUSED

            capture.pause = slow_pause  # type: ignore[method-assign]
            return capture

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        captures = SlowPauseFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
        )
        await controller.start("system", LOOPBACK.device_id)
        task = asyncio.create_task(controller.pause())
        assert await asyncio.to_thread(started.wait, 1.0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert controller.status is CaptureStatus.PAUSED
        assert captures.latest.state.value == "paused"
        assert controller._accept_frames is False
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_stop_drains_captured_frames_before_finalizing(tmp_path) -> None:
    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        manager = RecordingManager()
        captures = FakeCaptureFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
        )
        await controller.start("system", LOOPBACK.device_id)
        speech = np.full(1_600, 0.1, dtype=np.float32)
        for _ in range(3):
            captures.latest.emit(speech)
        await controller.stop()
        assert any(event.get("type") == "final_transcript" for event in manager.events)
        assert len(list(settings.session_dir.glob("*.jsonl"))) == 1
        await controller.shutdown()

    asyncio.run(scenario())


def test_pause_duration_is_reflected_in_later_transcript_timestamps(tmp_path) -> None:
    class UniqueEngine(FakeEngine):
        def transcribe(self, samples):
            self.calls += 1
            duration = len(samples) / 16_000
            return TranscriptionResult(
                text=f"문장 {self.calls}",
                detected_language="ja",
                language_probability=0.9,
                started_offset=0.0,
                ended_offset=duration,
                inference_seconds=0.01,
            )

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        manager = RecordingManager()
        captures = FakeCaptureFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=UniqueEngine,
        )
        speech = np.full(1_600, 0.1, dtype=np.float32)
        await controller.start("system", LOOPBACK.device_id)
        for _ in range(3):
            captures.latest.emit(speech)
        await controller.pause()
        assert controller._paused_at is not None
        controller._paused_at -= timedelta(minutes=10)
        await controller.resume()
        for _ in range(3):
            captures.latest.emit(speech)
        await controller.pause()
        await controller.stop()
        finals = [
            event for event in manager.events if event.get("type") == "final_transcript"
        ]
        assert len(finals) == 2
        first_end = datetime.fromisoformat(str(finals[0]["ended_at"]))
        second_end = datetime.fromisoformat(str(finals[1]["ended_at"]))
        assert (second_end - first_end).total_seconds() >= 600
        await controller.shutdown()

    asyncio.run(scenario())


def test_stop_waits_for_a_final_already_queued(tmp_path) -> None:
    class SlowEngine(FakeEngine):
        def transcribe(self, samples):
            time.sleep(0.05)
            return super().transcribe(samples)

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        manager = RecordingManager()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            engine_factory=SlowEngine,
        )
        await controller.start("system", LOOPBACK.device_id)
        controller._enqueue_segment(  # regression: final queued before stop's flush
            SegmentEvent(
                event_type=SegmentEventType.FINAL,
                samples=np.full(32_000, 0.1, dtype=np.float32),
                started_offset=0.0,
                ended_offset=2.0,
                reason="test",
            )
        )
        await controller.stop()
        assert any(event.get("type") == "final_transcript" for event in manager.events)
        assert len(list(settings.session_dir.glob("*.jsonl"))) == 1
        await controller.shutdown()

    asyncio.run(scenario())


def test_queue_overflow_keeps_latest_frames_and_server_state(tmp_path) -> None:
    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            frame_queue_size=2,
        )
        manager = RecordingManager()
        captures = FakeCaptureFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
        )
        await controller.start("system", LOOPBACK.device_id)
        frame = np.full(1_600, 0.1, dtype=np.float32)
        for _ in range(100):
            captures.latest.emit(frame)
        await asyncio.sleep(0.05)
        assert controller.status.value == "listening"
        assert controller.snapshot()["dropped_frames"] >= 0
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())
