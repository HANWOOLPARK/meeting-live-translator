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
MAIN_CSS = (STATIC / "style.css").read_text(encoding="utf-8")
CAPTION_HTML = (STATIC / "captions.html").read_text(encoding="utf-8")
CAPTION_JS = (STATIC / "captions.js").read_text(encoding="utf-8")
CAPTION_CSS = (STATIC / "captions.css").read_text(encoding="utf-8")


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


def test_caption_window_route_serves_dedicated_page(tmp_path: Path) -> None:
    with TestClient(create_app(_services(tmp_path, STATIC))) as client:
        response = client.get("/captions")
        assert response.status_code == 200
        assert "실시간 자막 · VerbaRadar" in response.text
        assert '/static/captions.js?v=' in response.text
        assert response.headers["cache-control"] == "no-store"
        static_response = client.get("/static/captions.js")
        assert static_response.status_code == 200
        assert static_response.headers["cache-control"] == "no-store"


def test_missing_caption_window_returns_safe_error(tmp_path: Path) -> None:
    empty_static = tmp_path / "static"
    empty_static.mkdir()
    with TestClient(
        create_app(_services(tmp_path, empty_static)),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/captions")
        assert response.status_code == 503
        assert response.json()["code"] == "caption_window_missing"
        assert str(tmp_path) not in response.text


def test_main_page_exposes_popout_and_all_caption_view_modes() -> None:
    assert 'id="openCaptionWindowButton"' in MAIN_HTML
    assert 'id="openMediaCaptionWindowButton"' in MAIN_HTML
    assert 'id="captionViewModeSelect"' in MAIN_HTML
    for mode in ("both", "original", "translation"):
        assert f'value="{mode}"' in MAIN_HTML
    assert 'window.open(\n      "/captions"' in MAIN_JS
    assert '"/captions?layout=media"' in MAIN_JS
    assert 'window.mltDesktop.openOverlay("media")' in MAIN_JS
    assert 'new BroadcastChannel("mlt-caption-window-v1")' in MAIN_JS
    assert "captionWindowSnapshot" in MAIN_JS
    assert '#captions[data-view-mode="original"]' in MAIN_CSS
    assert '#captions[data-view-mode="translation"]' in MAIN_CSS


def test_caption_window_has_transparency_modes_and_safe_live_sync() -> None:
    for control_id in (
        "captionViewModeSelect",
        "backgroundOpacityRange",
        "backgroundOpacityValue",
        "captionAutoViewOption",
        "mediaWidthSelect",
        "mediaFontSizeRange",
        "mediaFontSizeValue",
        "closeCaptionWindowButton",
        "partialPanel",
        "captionList",
    ):
        assert f'id="{control_id}"' in CAPTION_HTML
    for mode in ("both", "original", "translation"):
        assert f'value="{mode}"' in CAPTION_HTML
    assert 'new BroadcastChannel(CHANNEL_NAME)' in CAPTION_JS
    assert 'new WebSocket(websocketUrl())' in CAPTION_JS
    assert "/api/sessions/${encodeURIComponent(sessionId)}/segments" in CAPTION_JS
    assert '"mlt-caption-view-mode"' in CAPTION_JS
    assert 'localStorage.setItem("mlt-caption-background-transparency"' in CAPTION_JS
    assert '"mlt-media-caption-view-mode"' in CAPTION_JS
    assert 'localStorage.setItem("mlt-media-caption-width"' in CAPTION_JS
    assert 'localStorage.setItem("mlt-media-caption-font-size"' in CAPTION_JS
    assert 'window.mltDesktop?.setMediaWidth' in CAPTION_JS
    assert "scheduleMediaFit" in CAPTION_JS
    assert "textContent" in CAPTION_JS
    assert "innerHTML" not in CAPTION_JS
    assert "--surface-opacity" in CAPTION_CSS
    assert 'body[data-view-mode="original"]' in CAPTION_CSS
    assert 'body[data-view-mode="translation"]' in CAPTION_CSS
    assert 'html[data-caption-layout="media"]' in CAPTION_CSS
    assert '.caption-item:last-child' in CAPTION_CSS
    assert 'body[data-view-mode="auto"]' in CAPTION_CSS
    assert 'white-space: nowrap' in CAPTION_CSS
    assert 'html[data-caption-layout="media"] .caption-scroll {' in CAPTION_CSS
    assert 'display: flex;' in CAPTION_CSS
    assert 'max-width: 100%;' in CAPTION_CSS
    assert "https://" not in CAPTION_HTML + CAPTION_JS
    assert "http://" not in CAPTION_HTML + CAPTION_JS
