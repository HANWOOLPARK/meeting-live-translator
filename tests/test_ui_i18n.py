from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "frontend" / "static"
MAIN_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "app.js").read_text(encoding="utf-8")
MAIN_CSS = (STATIC / "style.css").read_text(encoding="utf-8")
CAPTION_HTML = (STATIC / "captions.html").read_text(encoding="utf-8")
CAPTION_JS = (STATIC / "captions.js").read_text(encoding="utf-8")
CAPTION_CSS = (STATIC / "captions.css").read_text(encoding="utf-8")
RADAR_HTML = (STATIC / "decision-radar.html").read_text(encoding="utf-8")
RADAR_JS = (STATIC / "decision-radar-window.js").read_text(encoding="utf-8")
RADAR_CSS = (STATIC / "decision-radar-window.css").read_text(encoding="utf-8")
I18N_JS = (STATIC / "i18n.js").read_text(encoding="utf-8")


def _dictionary_keys() -> set[str]:
    return set(re.findall(r'^\s+"((?:[^"\\]|\\.)+)":', I18N_JS, re.MULTILINE))


def _markup_keys(markup: str) -> set[str]:
    return set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', markup))


def _javascript_keys(javascript: str) -> set[str]:
    return set(re.findall(r'\bt\("((?:[^"\\]|\\.)+)"', javascript))


def test_main_caption_and_radar_pages_load_shared_i18n_before_page_scripts() -> None:
    assert MAIN_HTML.index('/static/i18n.js?v=') < MAIN_HTML.index('/static/app.js?v=')
    assert CAPTION_HTML.index('/static/i18n.js?v=') < CAPTION_HTML.index('/static/captions.js?v=')
    assert RADAR_HTML.index('/static/i18n.js?v=') < RADAR_HTML.index('/static/decision-radar-window.js?v=')
    assert "window.MLTI18n" in I18N_JS
    assert 'const i18n = window.MLTI18n' in MAIN_JS
    assert 'const i18n = window.MLTI18n' in CAPTION_JS
    assert 'const i18n = window.MLTI18n' in RADAR_JS
    assert "i18n.bindLanguageControls(document)" in MAIN_JS
    assert "i18n.bindLanguageControls(document)" in CAPTION_JS
    assert "i18n.bindLanguageControls(document)" in RADAR_JS


def test_language_switch_is_korean_first_persistent_and_window_synchronized() -> None:
    for markup in (MAIN_HTML, CAPTION_HTML, RADAR_HTML):
        assert 'data-ui-language="ko"' in markup
        assert 'data-ui-language="en"' in markup
        assert 'aria-pressed="true">한국어</button>' in markup
    assert 'let currentLanguage = "ko"' in I18N_JS
    assert 'const STORAGE_KEY = "mlt-ui-language"' in I18N_JS
    assert 'const CHANNEL_NAME = "mlt-ui-language-v1"' in I18N_JS
    assert "localStorage.setItem(STORAGE_KEY, language)" in I18N_JS
    assert 'window.addEventListener("storage"' in I18N_JS
    assert 'languageChannel?.postMessage({ type: "language", language })' in I18N_JS
    assert "window.location.reload()" in I18N_JS


def test_every_declared_static_and_dynamic_ui_key_has_an_english_translation() -> None:
    dictionary = _dictionary_keys()
    declared = (
        _markup_keys(MAIN_HTML)
        | _markup_keys(CAPTION_HTML)
        | _markup_keys(RADAR_HTML)
        | _javascript_keys(MAIN_JS)
        | _javascript_keys(CAPTION_JS)
        | _javascript_keys(RADAR_JS)
    )
    assert declared - dictionary == set()
    assert len(dictionary) >= 400


def test_transcript_and_model_generated_content_are_not_run_through_ui_translation() -> None:
    assert "textElement.textContent = displayText" in MAIN_JS
    assert "textElement.textContent = translation" in MAIN_JS
    assert "text.textContent = item.text" in MAIN_JS
    assert "row.textContent = warning" in MAIN_JS
    assert "original.textContent = segment.originalText" in CAPTION_JS
    assert "return segment.translationText" in CAPTION_JS


def test_language_switch_styles_cover_main_and_caption_windows() -> None:
    assert ".language-switcher" in MAIN_CSS
    assert '.language-switcher button[data-active="true"]' in MAIN_CSS
    assert ".caption-language-switcher" in CAPTION_CSS
    assert '.caption-language-switcher button[data-active="true"]' in CAPTION_CSS
    assert "@media (max-width: 650px)" in MAIN_CSS
    assert "@media (max-width: 500px)" in CAPTION_CSS
    assert ".radar-language-switcher" in RADAR_CSS
    assert '.radar-language-switcher button[data-active="true"]' in RADAR_CSS
