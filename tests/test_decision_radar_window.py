from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services

from .fakes import FakeCaptureFactory, FakeDeviceProvider, FakeEngine


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "frontend" / "static"
MAIN_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "app.js").read_text(encoding="utf-8")
RADAR_HTML = (STATIC / "decision-radar.html").read_text(encoding="utf-8")
RADAR_JS = (STATIC / "decision-radar-window.js").read_text(encoding="utf-8")
RADAR_CSS = (STATIC / "decision-radar-window.css").read_text(encoding="utf-8")


def _services(tmp_path: Path, static_dir: Path):
    settings = AppSettings(
        project_root=ROOT,
        session_dir=tmp_path / "sessions",
        static_dir=static_dir,
    )
    return build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        capture_factory=FakeCaptureFactory(),
        engine_factory=FakeEngine,
    )


def test_decision_radar_window_route_serves_results_only_page(tmp_path: Path) -> None:
    with TestClient(create_app(_services(tmp_path, STATIC))) as client:
        response = client.get("/decision-radar")
        assert response.status_code == 200
        assert "실시간 Radar 결과" in response.text
        assert '/static/decision-radar-window.js?v=' in response.text
        assert 'id="decisionRadarProviderSelect"' not in response.text


def test_missing_decision_radar_window_returns_safe_error(tmp_path: Path) -> None:
    empty_static = tmp_path / "static"
    empty_static.mkdir()
    with TestClient(
        create_app(_services(tmp_path, empty_static)),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/decision-radar")
        assert response.status_code == 503
        assert response.json()["code"] == "decision_radar_window_missing"
        assert str(tmp_path) not in response.text


def test_main_page_opens_dedicated_decision_radar_results_window() -> None:
    assert 'id="openDecisionRadarWindowButton"' in MAIN_HTML
    assert 'window.open(\n      "/decision-radar"' in MAIN_JS
    assert 'new BroadcastChannel("mlt-decision-radar-window-v1")' in MAIN_JS
    assert "decisionRadarWindowSnapshot" in MAIN_JS
    assert 'message.type === "navigate_evidence"' in MAIN_JS


def test_results_window_is_live_editable_and_ready_for_native_transparency() -> None:
    for control_id in (
        "radarConnectionStatus",
        "radarStatusBadge",
        "radarProviderModel",
        "radarBackgroundOpacityRange",
        "closeRadarWindowButton",
        "radarScroll",
        "radarDecisions",
        "radarActions",
        "radarQuestions",
        "radarConfirmations",
    ):
        assert f'id="{control_id}"' in RADAR_HTML
    assert 'id="decisionRadarProviderSelect"' not in RADAR_HTML
    assert 'apiRequest("/api/decision-radar")' in RADAR_JS
    assert "/api/decision-radar/items/${encodeURIComponent(itemId)}" in RADAR_JS
    assert "new WebSocket(websocketUrl())" in RADAR_JS
    assert "new BroadcastChannel(CHANNEL_NAME)" in RADAR_JS
    assert 'type: "navigate_evidence"' in RADAR_JS
    assert 'localStorage.setItem("mlt-radar-background-transparency"' in RADAR_JS
    assert 'document.documentElement.dataset.nativeOverlay = "true"' in RADAR_JS
    assert "textContent" in RADAR_JS
    assert "innerHTML" not in RADAR_JS
    assert '--radar-surface-opacity' in RADAR_CSS
    assert 'html[data-native-overlay="true"]' in RADAR_CSS
    assert "https://" not in RADAR_HTML + RADAR_JS
    assert "http://" not in RADAR_HTML + RADAR_JS
