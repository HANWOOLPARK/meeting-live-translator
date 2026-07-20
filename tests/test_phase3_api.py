from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sessions.models import FinalTranscript

from .fakes import FakeDeviceProvider


def services(tmp_path: Path, *, analysis_provider: str = "none"):
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=Path(__file__).resolve().parents[1] / "frontend" / "static",
        analysis_provider=analysis_provider,
    )
    return build_services(settings, device_provider=FakeDeviceProvider())


def add_completed_session(app_services) -> str:
    repository = app_services.repository
    session_id = repository.start_session(
        {
            "started_at": "2026-07-11T10:00:00+09:00",
            "source": "system",
            "audio_device_name": "Speakers",
            "whisper_model": "small",
            "translation_provider": "none",
        }
    )
    repository.append_final(
        FinalTranscript(
            segment_id="segment-1",
            session_id=session_id,
            utterance_id="utterance-1",
            source="system",
            text="System Test를 확인합니다.",
            language="mixed",
            language_probability=0.9,
            started_at="2026-07-11T10:00:01+09:00",
            ended_at="2026-07-11T10:00:03+09:00",
            inference_seconds=0.5,
        )
    )
    repository.stop_session(ended_at="2026-07-11T10:05:00+09:00")
    return session_id


def test_phase3_session_settings_api(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    app = create_app(app_services)
    with TestClient(app) as client:
        initial = client.get("/api/session/settings")
        assert initial.status_code == 200
        assert initial.json() == {
            "save_original": True,
            "save_translation": True,
            "save_analysis": True,
            "save_audio": False,
        }
        updated = client.post(
            "/api/session/settings",
            json={
                "save_original": False,
                "save_translation": False,
                "save_analysis": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["save_original"] is False
        assert updated.json()["save_audio"] is False


def test_session_list_detail_segments_and_downloads(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    app = create_app(app_services)
    with TestClient(app) as client:
        session_id = add_completed_session(app_services)

        listed = client.get("/api/sessions")
        assert listed.status_code == 200
        summary = next(
            item for item in listed.json()["sessions"] if item["session_id"] == session_id
        )
        assert summary["status"] == "completed"
        assert summary["segment_count"] == 1

        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["segments"][0]["segment_id"] == "segment-1"
        assert str(tmp_path) not in detail.text

        segments = client.get(f"/api/sessions/{session_id}/segments")
        assert segments.status_code == 200
        assert len(segments.json()["segments"]) == 1

        endpoints = {
            "json": "application/json",
            "original-txt": "text/plain",
            "translation-txt": "text/plain",
            "markdown": "text/markdown",
        }
        for suffix, content_type in endpoints.items():
            response = client.get(f"/api/sessions/{session_id}/download/{suffix}")
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
            disposition = response.headers["content-disposition"]
            assert session_id in disposition
            assert str(tmp_path) not in disposition


def test_session_api_rejects_unsafe_ids_without_path_disclosure(tmp_path: Path) -> None:
    app = create_app(services(tmp_path))
    with TestClient(app) as client:
        for unsafe in ("..%5Csecret", "C:%5Csecret", "CON"):
            response = client.get(f"/api/sessions/{unsafe}")
            assert response.status_code == 400
            body = response.text
            assert "invalid_session_id" in body
            assert str(tmp_path) not in body


def test_health_exposes_phase3_compatibility_level_and_no_paths(tmp_path: Path) -> None:
    app = create_app(services(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["phase"] == 2
        assert body["current_phase"] == 3
        assert body["session"]["storage"]["save_audio"] is False
        assert str(tmp_path) not in response.text


def test_startup_recovers_incomplete_session_without_blocking_list(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    session_id = app_services.repository.start_session({"source": "system"})
    app_services.repository.append_final(
        FinalTranscript(
            segment_id="segment-1",
            session_id=session_id,
            utterance_id="utterance-1",
            source="system",
            text="Recovery test",
            language="en",
            language_probability=0.99,
            started_at="2026-07-11T10:00:00+09:00",
            ended_at="2026-07-11T10:00:01+09:00",
            inference_seconds=0.1,
        )
    )
    corrupt = tmp_path / "sessions" / "2026-07-11_10-10-10_abcdef"
    corrupt.mkdir()
    (corrupt / "manifest.json").write_text("broken", encoding="utf-8")

    with TestClient(create_app(app_services)) as client:
        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["metadata"]["status"] == "recovered"
        listed = client.get("/api/sessions").json()["sessions"]
        assert len(listed) == 2
        assert any(item["status"] == "error" for item in listed)


def test_download_json_contains_no_secret_fields(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    with TestClient(create_app(app_services)) as client:
        session_id = add_completed_session(app_services)
        response = client.get(f"/api/sessions/{session_id}/download/json")
        payload = json.loads(response.content)
        flattened = json.dumps(payload).lower()
        assert "api_key" not in flattened
        assert "authorization" not in flattened
        assert "traceback" not in flattened
        assert str(tmp_path).lower() not in flattened


def test_analysis_settings_are_public_but_secrets_are_not(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    app_services.settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=Path(__file__).resolve().parents[1] / "frontend" / "static",
        openai_api_key="secret-test-key",
        openai_analysis_model="configured-model",
    )
    with TestClient(create_app(app_services)) as client:
        providers = client.get("/api/analysis/providers")
        settings = client.get("/api/analysis/settings")

        assert providers.status_code == 200
        assert {item["id"] for item in providers.json()["providers"]} == {
            "none",
            "rule_based",
            "openai",
            "gemini",
        }
        assert settings.status_code == 200
        assert settings.json()["openai_api_key_configured"] is True
        assert settings.json()["gemini_api_key_configured"] is False
        assert "secret-test-key" not in providers.text
        assert "secret-test-key" not in settings.text
        assert str(tmp_path) not in providers.text + settings.text


def test_rule_based_analysis_api_is_explicit_and_updates_markdown(
    tmp_path: Path,
) -> None:
    app_services = services(tmp_path, analysis_provider="rule_based")
    with TestClient(create_app(app_services)) as client:
        session_id = add_completed_session(app_services)

        # Page/config/detail reads do not start analysis.
        before = client.get(f"/api/sessions/{session_id}/analysis")
        assert before.status_code == 200
        assert before.json()["status"] == "not_started"
        assert before.json()["result"] is None

        started = client.post(f"/api/sessions/{session_id}/analysis")
        assert started.status_code == 200
        assert started.json()["status"] == "pending"

        detail = None
        for _ in range(100):
            detail = client.get(f"/api/sessions/{session_id}/analysis")
            if detail.json()["status"] == "completed":
                break
            time.sleep(0.01)
        assert detail is not None
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "completed"
        assert body["provider"] == "rule_based"
        assert body["result"]["meeting_purpose"]["text"] == "미정"

        markdown = client.get(
            f"/api/sessions/{session_id}/download/markdown"
        )
        assert markdown.status_code == 200
        assert "분석이 아직 생성되지 않았습니다." not in markdown.text


def test_analysis_runtime_settings_and_none_provider_rejection(tmp_path: Path) -> None:
    app_services = services(tmp_path)
    with TestClient(create_app(app_services)) as client:
        session_id = add_completed_session(app_services)
        rejected = client.post(f"/api/sessions/{session_id}/analysis")
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "analysis_disabled"

        configured = client.post(
            "/api/analysis/settings",
            json={"provider": "rule_based", "auto_run_on_stop": True},
        )
        assert configured.status_code == 200
        assert configured.json()["provider"] == "rule_based"
        assert configured.json()["auto_run_on_stop"] is True


def test_gemini_analysis_can_be_selected_without_generation_request(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=Path(__file__).resolve().parents[1] / "frontend" / "static",
        gemini_api_key="configured-test-value",
        gemini_translation_model="gemini-test-model",
    )
    app_services = build_services(settings, device_provider=FakeDeviceProvider())

    with TestClient(create_app(app_services)) as client:
        selected = client.post(
            "/api/analysis/settings",
            json={"provider": "gemini", "auto_run_on_stop": False},
        )

        assert selected.status_code == 200
        body = selected.json()
        assert body["provider"] == "gemini"
        assert body["provider_available"] is True
        assert body["provider_model"] == "gemini-test-model"
        assert body["gemini_api_key_configured"] is True
        assert "configured-test-value" not in selected.text


def test_websocket_analysis_snapshot_never_contains_api_key(tmp_path: Path) -> None:
    secret = "phase3-test-secret-never-expose"
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=Path(__file__).resolve().parents[1] / "frontend" / "static",
        openai_api_key=secret,
        openai_analysis_model="configured-model",
    )
    app_services = build_services(settings, device_provider=FakeDeviceProvider())

    with TestClient(create_app(app_services)) as client:
        with client.websocket_connect("/ws/live") as websocket:
            snapshot = websocket.receive_json()

    flattened = json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["type"] == "snapshot"
    assert snapshot["analysis"]["openai_api_key_configured"] is True
    assert secret not in flattened
    assert str(tmp_path) not in flattened
