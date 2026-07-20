from __future__ import annotations

import asyncio
import threading
from time import perf_counter

from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services

from .fakes import (
    LOOPBACK,
    MICROPHONE,
    ExplodingDeviceProvider,
    FakeCaptureFactory,
    FakeDeviceProvider,
    FakeEngine,
)


def _services(tmp_path, provider=None):
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
    )
    captures = FakeCaptureFactory()
    services = build_services(
        settings,
        device_provider=provider or FakeDeviceProvider(),
        capture_factory=captures,
        engine_factory=FakeEngine,
    )
    return services, captures


def test_phase1_api_lifecycle_and_websocket_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    services, _ = _services(tmp_path)
    app = create_app(services)

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["api_key_required"] is False
        assert "translation_worker" in health.json()

        diagnostics = client.get("/api/diagnostics")
        assert diagnostics.status_code == 200
        diagnostics_body = diagnostics.json()
        assert diagnostics_body["translation_worker"]["state"] == "unavailable"
        assert diagnostics_body["server"]["capture"] == {
            "dropped_frames": 0,
            "frame_queue_max_size": 256,
        }
        assert diagnostics_body["server"]["stt"]["capture_dropped_frames"] == 0
        assert diagnostics_body["server"]["translation_queue"]["oldest_wait_ms"] == 0
        assert str(tmp_path) not in diagnostics.text

        devices = client.get("/api/audio/devices")
        assert devices.status_code == 200
        assert devices.json()["default_loopback_id"] == LOOPBACK.device_id
        assert client.post("/api/audio/refresh").status_code == 200

        settings = client.get("/api/settings").json()
        assert settings["selected_model"] == "small"
        assert settings["allowed_models"] == ["tiny", "base", "small", "medium"]

        with client.websocket_connect("/ws/live") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["capture"]["state"] == "idle"

        started = client.post(
            "/api/capture/start",
            json={
                "source": "system",
                "device_id": LOOPBACK.device_id,
                "model": "small",
            },
        )
        assert started.status_code == 200
        assert started.json()["state"] == "listening"
        assert "cuda_error" not in str(started.json())

        assert client.patch("/api/settings", json={"model": "base"}).status_code == 409
        assert client.post("/api/capture/pause").json()["state"] == "paused"
        assert client.post("/api/capture/resume").json()["state"] == "listening"
        assert client.post("/api/capture/stop").json()["state"] == "stopped"
        assert client.post("/api/capture/stop").status_code == 200
        assert client.patch("/api/settings", json={"model": "large"}).status_code == 422


def test_invalid_device_and_wrong_source_do_not_terminate_server(tmp_path) -> None:
    services, _ = _services(tmp_path)
    app = create_app(services)
    with TestClient(app) as client:
        missing = client.post(
            "/api/capture/start",
            json={"source": "system", "device_id": "pa:999", "model": "small"},
        )
        assert missing.status_code == 404
        wrong_source = client.post(
            "/api/capture/start",
            json={
                "source": "system",
                "device_id": MICROPHONE.device_id,
                "model": "small",
            },
        )
        assert wrong_source.status_code == 400
        assert client.get("/api/health").status_code == 200


def test_unexpected_errors_are_sanitized_and_health_survives(tmp_path) -> None:
    services, _ = _services(tmp_path, ExplodingDeviceProvider())
    app = create_app(services)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/audio/devices")
        assert response.status_code == 500
        body = response.text
        assert "SECRET" not in body
        assert "meeting.wav" not in body
        assert response.json()["code"] == "internal_error"
        assert client.get("/api/health").status_code == 200


def test_slow_local_worker_prewarm_never_blocks_server_readiness(tmp_path) -> None:
    class SlowWorker:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.stopped = False

        async def start(self) -> bool:
            self.started.set()
            await asyncio.Event().wait()
            return False

        async def stop(self) -> None:
            self.stopped = True

        def snapshot(self) -> dict[str, object]:
            return {
                "configured": True,
                "model_installed": True,
                "runtime_installed": True,
                "state": "starting",
                "available": False,
                "desired_running": True,
                "pid": None,
                "model": "fake-model",
                "last_error": None,
            }

    services, _ = _services(tmp_path)
    slow_worker = SlowWorker()
    services.local_translation_worker = slow_worker  # type: ignore[assignment]
    app = create_app(services)

    started = perf_counter()
    with TestClient(app) as client:
        assert perf_counter() - started < 2.0
        assert slow_worker.started.wait(timeout=1.0)
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/diagnostics").json()["translation_worker"][
            "state"
        ] == "starting"
    assert slow_worker.stopped is True
