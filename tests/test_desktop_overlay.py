from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
STATIC = ROOT / "frontend" / "static"

PACKAGE = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
LOCK = json.loads((DESKTOP / "package-lock.json").read_text(encoding="utf-8"))
MAIN = (DESKTOP / "main.cjs").read_text(encoding="utf-8")
PRELOAD = (DESKTOP / "preload.cjs").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
CAPTION_JS = (STATIC / "captions.js").read_text(encoding="utf-8")
CAPTION_CSS = (STATIC / "captions.css").read_text(encoding="utf-8")
RADAR_JS = (STATIC / "decision-radar-window.js").read_text(encoding="utf-8")
RADAR_CSS = (STATIC / "decision-radar-window.css").read_text(encoding="utf-8")
START_ALL = (ROOT / "start_all.bat").read_text(encoding="utf-8")
START_DESKTOP = (ROOT / "scripts" / "start_desktop.ps1").read_text(encoding="utf-8")
STOP_PROJECT = (ROOT / "scripts" / "stop_project.ps1").read_text(encoding="utf-8")
SETUP_DESKTOP = (ROOT / "scripts" / "setup_desktop_overlay.ps1").read_text(
    encoding="utf-8"
)
LITE_BUILD = (ROOT / "scripts" / "build_lite_release.ps1").read_text(encoding="utf-8")


def test_electron_is_project_local_and_exactly_pinned() -> None:
    assert PACKAGE["private"] is True
    assert PACKAGE["main"] == "main.cjs"
    assert PACKAGE["name"] == "whykaigi-desktop-overlay"
    assert PACKAGE["devDependencies"]["electron"] == "43.1.1"
    assert LOCK["packages"][""]["devDependencies"]["electron"] == "43.1.1"
    assert LOCK["packages"]["node_modules/electron"]["version"] == "43.1.1"


def test_whykaigi_brand_and_native_icon_are_applied() -> None:
    assert 'app.setName("WhyKaigi")' in MAIN
    assert 'app.setAppUserModelId("com.whykaigi.desktop")' in MAIN
    assert 'const iconPath = path.join(__dirname, "assets", "whykaigi.ico")' in MAIN
    assert MAIN.count("icon: iconPath") == 2
    assert (DESKTOP / "assets" / "whykaigi.ico").stat().st_size > 0
    assert (DESKTOP / "assets" / "whykaigi-icon.png").stat().st_size > 0


def test_desktop_clears_stale_renderer_bundles_before_opening_main_window() -> None:
    ready = MAIN.index("app.whenReady().then(async () =>")
    clear_cache = MAIN.index("session.defaultSession.clearCache()", ready)
    clear_code_cache = MAIN.index("session.defaultSession.clearCodeCaches({})", ready)
    create_window = MAIN.index("createMainWindow();", ready)
    assert clear_cache < create_window
    assert clear_code_cache < create_window


def test_native_overlays_are_transparent_frameless_and_always_on_top() -> None:
    for setting in (
        "frame: false",
        "transparent: true",
        'backgroundColor: "#00000000"',
        "hasShadow: false",
        "resizable: false",
        "alwaysOnTop: true",
        'window.setAlwaysOnTop(true, "floating")',
    ):
        assert setting in MAIN
    assert '["caption", "media", "radar"].includes(kind)' in MAIN
    assert 'media: "/captions?native=1&layout=media"' in MAIN
    assert 'additionalArguments: [`--mlt-window-kind=${kind}`]' in MAIN


def test_electron_renderer_boundary_is_restricted_to_local_app_capabilities() -> None:
    assert "contextIsolation: true" in MAIN
    assert "nodeIntegration: false" in MAIN
    assert "sandbox: true" in MAIN
    assert "setPermissionRequestHandler" in MAIN
    assert "callback(false)" in MAIN
    assert "setWindowOpenHandler" in MAIN
    assert "will-navigate" in MAIN
    assert "allowedOrigin" in MAIN
    assert 'contextBridge.exposeInMainWorld("mltDesktop"' in PRELOAD
    assert "Object.freeze" in PRELOAD
    assert "require(" not in APP_JS + CAPTION_JS + RADAR_JS
    assert "ipcRenderer" not in APP_JS + CAPTION_JS + RADAR_JS


def test_main_ui_uses_native_overlays_with_browser_popup_fallback() -> None:
    assert 'window.mltDesktop.openOverlay("caption")' in APP_JS
    assert 'window.mltDesktop.openOverlay("media")' in APP_JS
    assert 'window.mltDesktop.openOverlay("radar")' in APP_JS
    assert 'window.open(\n      "/captions"' in APP_JS
    assert '"/captions?layout=media"' in APP_JS
    assert 'window.open(\n      "/decision-radar"' in APP_JS
    assert "window.mltDesktop?.closeWindow" in CAPTION_JS
    assert "window.mltDesktop?.closeWindow" in RADAR_JS
    assert 'dataset.nativeOverlay = "true"' in CAPTION_JS
    assert 'dataset.nativeOverlay = "true"' in RADAR_JS
    assert 'html[data-native-overlay="true"]' in CAPTION_CSS
    assert 'html[data-native-overlay="true"]' in RADAR_CSS


def test_media_caption_overlay_tracks_the_current_display_and_safe_width_presets() -> None:
    assert 'screen.getDisplayMatching(window.getBounds())' in MAIN
    assert 'kind === "media"' in MAIN
    assert 'workArea.width * widthPercent / 100' in MAIN
    assert 'workArea.y + workArea.height - height - 12' in MAIN
    assert 'ipcMain.handle("mlt:set-media-width"' in MAIN
    assert '[60, 80, 94].includes(requested)' in MAIN
    assert 'overlayWindows.get("media") !== window' in MAIN
    assert 'screen.on("display-metrics-changed", repositionMediaOverlay)' in MAIN
    assert 'setMediaWidth: (widthPercent)' in PRELOAD
    assert '["caption", "media", "radar"].includes(windowKind)' in PRELOAD


def test_start_and_stop_scripts_target_only_project_owned_desktop_process() -> None:
    assert 'if /I "%MLT_DESKTOP%"=="0" goto :open_browser' in START_ALL
    assert "setup_desktop_overlay.bat" in START_ALL
    assert "scripts\\start_desktop.ps1" in START_ALL
    assert "desktop.pid" in START_ALL
    assert "desktop.ready" in START_ALL
    assert "Get-OwnedDesktopProcess" in START_DESKTOP
    assert "Get-CimInstance Win32_Process" in START_DESKTOP
    assert "desktop\\main.cjs" in STOP_PROJECT
    assert '"desktop\\assets\\whykaigi.ico"' in LITE_BUILD
    assert '"desktop\\assets\\whykaigi-icon.png"' in LITE_BUILD
    assert "Get-OwnedProcess" in STOP_PROJECT
    assert "taskkill.exe /PID $desktopProcessId /T /F" in STOP_PROJECT
    lowered = STOP_PROJECT.lower()
    assert "taskkill.exe /im electron" not in lowered
    assert "stop-process -name electron" not in lowered
    assert "get-process electron" not in lowered


def test_optional_setup_verifies_official_node_archive_and_stays_project_local() -> None:
    assert '"v24.18.0"' in SETUP_DESKTOP
    assert "https://nodejs.org/dist" in SETUP_DESKTOP
    assert "SHASUMS256.txt" in SETUP_DESKTOP
    assert "Get-FileHash" in SETUP_DESKTOP
    assert 'Join-Path $root ".runtime"' in SETUP_DESKTOP
    assert 'Join-Path $desktopRoot "node_modules\\electron\\dist\\electron.exe"' in SETUP_DESKTOP
    assert "electron\\install.js" in SETUP_DESKTOP
    assert "Start-Process" not in SETUP_DESKTOP


def test_lite_release_includes_sources_but_excludes_downloaded_runtimes() -> None:
    for path in (
        "setup_desktop_overlay.bat",
        "desktop\\main.cjs",
        "desktop\\preload.cjs",
        "desktop\\package.json",
        "desktop\\package-lock.json",
        "scripts\\setup_desktop_overlay.ps1",
        "scripts\\start_desktop.ps1",
    ):
        assert f'"{path}"' in LITE_BUILD
    assert '".runtime"' in LITE_BUILD
    assert '"node_modules"' in LITE_BUILD
