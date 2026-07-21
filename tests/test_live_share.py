from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sharing import ShareRelayManager, sanitize_share_event
from backend.app.sharing import manager as share_manager_module

from .fakes import FakeCaptureFactory, FakeDeviceProvider, FakeEngine


ROOM_ID = "abcdefghijklmnopqrstuvwx"
HOST_TOKEN = "host-token-that-must-never-be-public"
VIEWER_URL = f"https://viewer.example/room/{ROOM_ID}"


def test_relay_requests_use_an_explicit_product_user_agent(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(_maximum: int) -> bytes:
            return b"{}"

    def fake_urlopen(request, *, timeout):
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(share_manager_module, "urlopen", fake_urlopen)
    manager = ShareRelayManager(
        relay_url="https://viewer.example",
        create_secret="create-secret",
        request_timeout_seconds=7,
    )

    result = asyncio.run(manager._request_json("GET", "/health", None, None))

    assert result == {}
    assert captured == {
        "user_agent": "VerbaRadar/0.6",
        "timeout": 7,
    }


def _services(tmp_path):
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
    )
    return build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        capture_factory=FakeCaptureFactory(),
        engine_factory=FakeEngine,
    )


def test_share_sanitizer_is_allowlist_only() -> None:
    final = sanitize_share_event(
        {
            "type": "final_transcript",
            "event_id": "event-1",
            "timestamp": "2026-07-17T20:00:00+09:00",
            "segment_id": "segment-1",
            "session_id": "private-session",
            "text": "  release   is approved  ",
            "detected_language": "en",
            "device_id": "private-device",
            "audio": "never-send-this",
            "api_key": "never-send-this",
            "provider": {"model": "private-model"},
        }
    )
    assert final == {
        "type": "final_transcript",
        "event_id": "event-1",
        "timestamp": "2026-07-17T20:00:00+09:00",
        "segment_id": "segment-1",
        "text": "release is approved",
        "language": "en",
        "started_at": None,
        "ended_at": None,
    }
    assert "private" not in str(final)
    assert sanitize_share_event({"type": "session_created", "session_id": "x"}) is None
    assert sanitize_share_event({"type": "audio_level", "level": 0.7}) is None


def test_radar_sanitizer_keeps_only_grounded_items() -> None:
    result = sanitize_share_event(
        {
            "type": "decision_radar_updated",
            "decision_radar": {
                "status": "idle",
                "revision": 3,
                "provider": "private-provider",
                "items": [
                    {
                        "item_id": "item-1",
                        "category": "action_item",
                        "text": "Send the estimate",
                        "assignee": "Tanaka",
                        "due_date": "Friday",
                        "evidence_segment_ids": ["segment-1"],
                        "review_status": "suggested",
                        "private_reasoning": "never-send-this",
                    },
                    {
                        "item_id": "ungrounded",
                        "category": "decision",
                        "text": "No evidence",
                        "evidence_segment_ids": [],
                    },
                ],
            },
        }
    )
    assert result is not None
    radar = result["decision_radar"]
    assert len(radar["items"]) == 1
    assert radar["items"][0]["evidence_segment_ids"] == ["segment-1"]
    assert "provider" not in radar
    assert "private_reasoning" not in str(result)


def test_relay_manager_batches_without_blocking_capture_and_deletes_room(tmp_path) -> None:
    async def scenario() -> None:
        calls: list[tuple[str, str, dict[str, Any] | None, str | None]] = []

        async def sender(method, path, body, bearer):
            calls.append((method, path, dict(body) if body is not None else None, bearer))
            if method == "POST" and path == "/api/rooms":
                return {
                    "room_id": ROOM_ID,
                    "host_token": HOST_TOKEN,
                    "viewer_url": VIEWER_URL,
                    "expires_at": "2026-07-18T04:00:00+09:00",
                }
            if method == "GET" and path.endswith("/access-log"):
                return {
                    "room_id": ROOM_ID,
                    "status": "active",
                    "created_at": "2026-07-18T03:00:00+09:00",
                    "ended_at": None,
                    "retention_days": 30,
                    "verified_attendee_count": 1,
                    "attendees": [
                        {
                            "email": "viewer@example.com",
                            "first_verified_at": "2026-07-18T03:01:00+09:00",
                            "last_seen_at": "2026-07-18T03:02:00+09:00",
                            "view_count": 2,
                            "active": True,
                        }
                    ],
                    "events": [
                        {
                            "event_id": "access-event-1",
                            "email": "viewer@example.com",
                            "event_type": "access_granted",
                            "occurred_at": "2026-07-18T03:01:00+09:00",
                            "detail_code": "",
                        }
                    ],
                    "retained_until": "2026-08-17T03:00:00+09:00",
                }
            if method == "DELETE" and path.endswith(ROOM_ID):
                return {
                    "deleted": True,
                    "access_log": {
                        "room_id": ROOM_ID,
                        "status": "ended",
                        "created_at": "2026-07-18T03:00:00+09:00",
                        "ended_at": "2026-07-18T03:03:00+09:00",
                        "retention_days": 30,
                        "verified_attendee_count": 1,
                        "attendees": [
                            {
                                "email": "viewer@example.com",
                                "first_verified_at": "2026-07-18T03:01:00+09:00",
                                "last_seen_at": "2026-07-18T03:02:00+09:00",
                                "view_count": 2,
                                "active": False,
                            }
                        ],
                        "events": [],
                        "retained_until": "2026-08-17T03:00:00+09:00",
                    },
                }
            if path.endswith("/events"):
                await asyncio.sleep(0.08)
            return {"ok": True}

        manager = ShareRelayManager(
            relay_url="https://viewer.example",
            create_secret="create-secret",
            request_sender=sender,
            audit_dir=tmp_path / "share-access",
        )
        await manager.start()
        started = await manager.start_share()
        assert started["viewer_url"] == VIEWER_URL
        assert HOST_TOKEN not in str(started)
        assert "room_id" not in started

        before = perf_counter()
        await manager.publish_event(
            {
                "type": "final_transcript",
                "segment_id": "segment-1",
                "text": "hello",
                "detected_language": "en",
                "session_id": "private-session",
            }
        )
        assert perf_counter() - before < 0.05

        for _ in range(80):
            if any(path.endswith("/events") for _, path, _, _ in calls):
                break
            await asyncio.sleep(0.01)
        event_call = next(call for call in calls if call[1].endswith("/events"))
        assert "private-session" not in str(event_call[2])

        access_logs = await manager.access_logs()
        assert access_logs["current"]["attendees"][0]["email"] == "viewer@example.com"
        assert HOST_TOKEN not in str(access_logs)

        stopped = await manager.stop_share()
        assert stopped["active"] is False
        assert stopped["viewer_url"] is None
        assert any(method == "DELETE" and path.endswith(ROOM_ID) for method, path, _, _ in calls)
        saved = list((tmp_path / "share-access").glob("*.json"))
        assert len(saved) == 1
        assert "viewer@example.com" in saved[0].read_text(encoding="utf-8")
        assert HOST_TOKEN not in saved[0].read_text(encoding="utf-8")
        await manager.shutdown()

    asyncio.run(scenario())


def test_share_api_requires_consent_and_never_returns_host_token(tmp_path) -> None:
    async def sender(method, path, body, bearer):
        if method == "POST" and path == "/api/rooms":
            return {
                "room_id": ROOM_ID,
                "host_token": HOST_TOKEN,
                "viewer_url": VIEWER_URL,
                "expires_at": "2026-07-18T04:00:00+09:00",
            }
        if method == "GET" and path.endswith("/access-log"):
            return {
                "room_id": ROOM_ID,
                "status": "active",
                "created_at": "2026-07-18T03:00:00+09:00",
                "retention_days": 30,
                "attendees": [],
                "events": [],
            }
        return {"ok": True}

    manager = ShareRelayManager(
        relay_url="https://viewer.example",
        create_secret="create-secret",
        request_sender=sender,
        audit_dir=tmp_path / "share-access",
    )
    app = create_app(_services(tmp_path), live_share_manager=manager)
    with TestClient(app) as client:
        status = client.get("/api/share")
        assert status.status_code == 200
        assert status.json()["status"] == "idle"
        assert client.post("/api/share/start", json={"consent_confirmed": False}).status_code == 400

        started = client.post("/api/share/start", json={"consent_confirmed": True})
        assert started.status_code == 200
        assert started.json()["viewer_url"] == VIEWER_URL
        assert HOST_TOKEN not in started.text
        assert "room_id" not in started.json()

        diagnostics = client.get("/api/diagnostics").json()["live_share"]
        assert diagnostics["active"] is True
        assert diagnostics["external_transmission"] is True
        assert "past_sessions" in diagnostics["excluded_data"]
        assert diagnostics["access_control"] == "email_otp"

        access_log = client.get("/api/share/access-log")
        assert access_log.status_code == 200
        assert access_log.json()["current"]["room_id"] == ROOM_ID
        assert HOST_TOKEN not in access_log.text

        stopped = client.post("/api/share/stop")
        assert stopped.status_code == 200
        assert stopped.json()["active"] is False


def test_dedicated_share_env_precedes_general_dotenv(tmp_path, monkeypatch) -> None:
    for name in (
        "MLT_SHARE_RELAY_URL",
        "MLT_SHARE_RELAY_SECRET",
        "MLT_SHARE_RELAY_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "MLT_SHARE_RELAY_URL=\nMLT_SHARE_RELAY_SECRET=\n",
        encoding="utf-8",
    )
    (tmp_path / ".share.env").write_text(
        "MLT_SHARE_RELAY_URL=https://viewer.example\n"
        "MLT_SHARE_RELAY_SECRET=private-secret\n"
        "MLT_SHARE_RELAY_TIMEOUT_SECONDS=4\n",
        encoding="utf-8",
    )
    settings = AppSettings.from_env(tmp_path)
    assert settings.share_relay_url == "https://viewer.example"
    assert settings.share_relay_secret == "private-secret"
    assert settings.share_relay_timeout_seconds == 4
    public = settings.public_dict()["live_share"]
    assert public == {
        "configured": True,
        "external_transmission": True,
        "retention_policy": "delete_on_stop",
    }
    assert "private-secret" not in repr(settings)
    for name in (
        "MLT_SHARE_RELAY_URL",
        "MLT_SHARE_RELAY_SECRET",
        "MLT_SHARE_RELAY_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_expired_local_access_log_is_removed_without_touching_sessions(tmp_path) -> None:
    audit_dir = tmp_path / "data" / "share-access"
    audit_dir.mkdir(parents=True)
    expired = audit_dir / f"{ROOM_ID}.json"
    expired.write_text(
        json.dumps(
            {
                "room_id": ROOM_ID,
                "status": "ended",
                "created_at": "2026-06-01T00:00:00+09:00",
                "ended_at": "2026-06-01T01:00:00+09:00",
                "retention_days": 30,
                "retained_until": "2026-06-30T00:00:00+09:00",
                "attendees": [{"email": "viewer@example.com"}],
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    session_file = tmp_path / "data" / "sessions" / "untouched.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text('{"event":"unchanged"}\n', encoding="utf-8")

    manager = ShareRelayManager(
        relay_url="https://viewer.example",
        create_secret="create-secret",
        audit_dir=audit_dir,
    )

    assert manager.snapshot()["verified_attendee_count"] == 0
    assert not expired.exists()
    assert session_file.read_text(encoding="utf-8") == '{"event":"unchanged"}\n'
