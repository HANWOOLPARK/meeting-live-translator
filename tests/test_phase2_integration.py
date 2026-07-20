from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
from fastapi.testclient import TestClient

from backend.app.capture.controller import CaptureController
from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sessions.repository import JsonlSessionRepository
from backend.app.translation import (
    NoneTranslationProvider,
    ProviderHealth,
    TranslationProvider,
    TranslationManager,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
)

from .fakes import (
    LOOPBACK,
    FakeCaptureFactory,
    FakeDeviceProvider,
    FakeEngine,
    RecordingManager,
)


class FakeAvailableProvider(TranslationProvider):
    def __init__(self, provider_name: str = "local", *, delay: float = 0.0) -> None:
        self.provider_name = provider_name
        self.display_name = f"Fake {provider_name}"
        self.external = provider_name == "openai"
        self.delay = delay
        self.closed = False

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=not self.closed,
            external=self.external,
            model="fake-model",
        )

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text="현재 확인하고 있습니다.",
            source_language=request.source_language,
            target_language="ko",
            provider=self.provider_name,
            model="fake-model",
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=request.requested_at,
            latency_ms=10,
        )

    async def close(self) -> None:
        self.closed = True


def _services(tmp_path, *, api_key: str | None = None):
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
        openai_api_key=api_key,
    )
    factories = {
        "none": NoneTranslationProvider,
        "local": lambda: FakeAvailableProvider("local"),
        "openai": lambda: FakeAvailableProvider("openai"),
    }
    return build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        capture_factory=FakeCaptureFactory(),
        engine_factory=FakeEngine,
        translation_provider_factories=factories,
    )


def test_translation_api_defaults_to_none_and_changes_provider_without_restart(
    tmp_path,
) -> None:
    app = create_app(_services(tmp_path))
    with TestClient(app) as client:
        providers = client.get("/api/translation/providers")
        assert providers.status_code == 200
        assert providers.json()["selected_provider"] == "none"
        assert [item["id"] for item in providers.json()["providers"]] == [
            "none",
            "local",
            "openai",
            "gemini",
        ]

        initial = client.get("/api/translation/settings").json()
        assert initial["provider"] == "none"
        assert initial["status"] == "disabled"
        assert initial["openai_api_key_configured"] is False

        changed = client.post(
            "/api/translation/settings",
            json={"provider": "local"},
        )
        assert changed.status_code == 200
        assert changed.json()["provider"] == "local"
        assert client.get("/api/health").json()["phase"] == 2

        translated = client.post(
            "/api/translation/test",
            json={"text": "現在確認しています", "source_language": "ja"},
        )
        assert translated.status_code == 200
        assert translated.json()["translated_text"] == "현재 확인하고 있습니다."

        disabled = client.post(
            "/api/translation/settings",
            json={"provider": "none"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["provider"] == "none"
        assert client.get("/api/health").status_code == 200


def test_api_key_value_never_appears_in_translation_api_responses(tmp_path) -> None:
    secret = "phase2-super-secret-key"
    app = create_app(_services(tmp_path, api_key=secret))
    with TestClient(app) as client:
        bodies = [
            client.get("/api/health").text,
            client.get("/api/translation/providers").text,
            client.get("/api/translation/settings").text,
        ]
        assert all(secret not in body for body in bodies)
        assert client.get("/api/translation/settings").json()[
            "openai_api_key_configured"
        ] is True


def test_translation_test_is_rejected_while_translation_is_disabled(tmp_path) -> None:
    app = create_app(_services(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/translation/test",
            json={"text": "Test sentence", "source_language": "en"},
        )
        assert response.status_code == 409
        assert client.get("/api/health").status_code == 200


def test_unavailable_real_providers_do_not_stop_transcription_server(tmp_path) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
    )
    services = build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        capture_factory=FakeCaptureFactory(),
        engine_factory=FakeEngine,
    )
    app = create_app(services)
    with TestClient(app) as client:
        providers = {
            item["id"]: item
            for item in client.get("/api/translation/providers").json()["providers"]
        }
        assert providers["none"]["available"] is True
        assert providers["local"]["available"] is False
        assert providers["openai"]["available"] is False
        assert providers["gemini"]["available"] is False

        unavailable = client.post(
            "/api/translation/settings",
            json={"provider": "openai"},
        )
        assert unavailable.status_code == 409
        assert services.translation_manager.provider.provider_name == "none"
        assert client.get("/api/health").status_code == 200


def test_controller_submits_only_final_transcripts_to_translation(tmp_path) -> None:
    class RecordingTranslationManager:
        def __init__(self, websocket: RecordingManager) -> None:
            self.websocket = websocket
            self.events: list[dict[str, object]] = []
            self.final_was_broadcast_first = False

        async def submit_event(self, event, *, force=False):
            del force
            self.final_was_broadcast_first = any(
                item.get("type") == "final_transcript"
                and item.get("segment_id") == event.get("segment_id")
                for item in self.websocket.events
            )
            self.events.append(dict(event))

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        websocket = RecordingManager()
        translations = RecordingTranslationManager(websocket)
        captures = FakeCaptureFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            websocket,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
            translation_manager=translations,  # type: ignore[arg-type]
        )
        await controller.start("system", LOOPBACK.device_id, "small")
        speech = np.full(1_600, 0.1, dtype=np.float32)
        silence = np.zeros(1_600, dtype=np.float32)
        for _ in range(12):
            captures.latest.emit(speech)
        for _ in range(100):
            if any(item.get("type") == "partial_transcript" for item in websocket.events):
                break
            await asyncio.sleep(0.01)
        assert translations.events == []

        for _ in range(8):
            captures.latest.emit(silence)
        for _ in range(200):
            if translations.events:
                break
            await asyncio.sleep(0.01)

        assert len(translations.events) == 1
        event = translations.events[0]
        assert event["type"] == "final_transcript"
        assert event["segment_id"]
        assert translations.final_was_broadcast_first is True
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_provider_failure_keeps_final_transcript_and_capture_running(tmp_path) -> None:
    secret = "secret-key private source details"

    class FailingProvider(FakeAvailableProvider):
        async def translate(self, request: TranslationRequest) -> TranslationResult:
            del request
            raise RuntimeError(secret)

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
        )
        websocket = RecordingManager()
        translations = TranslationManager(
            FailingProvider("openai"),
            max_retries=0,
            event_sink=websocket.broadcast,
        )
        captures = FakeCaptureFactory()
        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            websocket,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=FakeEngine,
            translation_manager=translations,
        )
        await controller.start("system", LOOPBACK.device_id, "small")
        speech = np.full(1_600, 0.1, dtype=np.float32)
        silence = np.zeros(1_600, dtype=np.float32)
        for _ in range(12):
            captures.latest.emit(speech)
        for _ in range(8):
            captures.latest.emit(silence)
        for _ in range(300):
            event_types = [item.get("type") for item in websocket.events]
            if "final_transcript" in event_types and "translation_error" in event_types:
                break
            await asyncio.sleep(0.01)

        event_types = [item.get("type") for item in websocket.events]
        assert event_types.index("final_transcript") < event_types.index("translation_error")
        assert controller.snapshot()["state"] == "listening"
        assert secret not in str(websocket.events)
        await controller.stop()
        await controller.shutdown()
        await translations.shutdown()

    asyncio.run(scenario())


def test_provider_exception_logs_and_events_are_sanitized(caplog) -> None:
    secret = "sk-test-secret and private transcript"

    class FailingProvider(FakeAvailableProvider):
        async def translate(self, request: TranslationRequest) -> TranslationResult:
            del request
            raise RuntimeError(secret)

    async def scenario() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        manager = TranslationManager(
            FailingProvider("openai"),
            max_retries=0,
            event_sink=events.append,
        )
        await manager.submit(
            TranslationRequest(
                segment_id="secure-segment",
                source_text="private transcript",
                source_language="en",
            )
        )
        await manager.wait_idle(1)
        await manager.shutdown()
        return events

    caplog.set_level(logging.ERROR)
    events = asyncio.run(scenario())
    assert any(event.get("type") == "translation_error" for event in events)
    assert secret not in caplog.text
    assert "private transcript" not in str(events)


def test_successful_translation_is_appended_after_unchanged_final_jsonl(tmp_path) -> None:
    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            translation_provider="local",
        )
        websocket = RecordingManager()
        captures = FakeCaptureFactory()
        factories = {
            "none": NoneTranslationProvider,
            "local": lambda: FakeAvailableProvider("local"),
            "openai": lambda: FakeAvailableProvider("openai"),
        }
        services = build_services(
            settings,
            device_provider=FakeDeviceProvider(),
            websocket_manager=websocket,  # type: ignore[arg-type]
            capture_factory=captures,
            engine_factory=FakeEngine,
            translation_provider_factories=factories,
        )
        await services.translation_manager.start()
        await services.controller.start("system", LOOPBACK.device_id, "small")
        speech = np.full(1_600, 0.1, dtype=np.float32)
        silence = np.zeros(1_600, dtype=np.float32)
        for _ in range(12):
            captures.latest.emit(speech)
        for _ in range(8):
            captures.latest.emit(silence)
        for _ in range(300):
            if any(event.get("type") == "translation" for event in websocket.events):
                break
            await asyncio.sleep(0.01)
        await services.translation_manager.wait_idle(1)
        await services.controller.stop()

        files = list(settings.session_dir.glob("*.jsonl"))
        assert len(files) == 1
        records = [
            json.loads(line)
            for line in files[0].read_text(encoding="utf-8").splitlines()
        ]
        assert len(records) == 2
        assert "type" not in records[0]
        assert records[0]["text"] == "確定した文章です"
        assert records[1]["type"] == "translation"
        assert records[1]["segment_id"] == records[0]["segment_id"]
        assert records[1]["translated_text"] == "현재 확인하고 있습니다."

        await services.controller.shutdown()
        await services.translation_manager.shutdown()

    asyncio.run(scenario())
