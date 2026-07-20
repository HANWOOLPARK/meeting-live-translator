from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")


def test_phase3a_session_controls_are_present() -> None:
    for control_id in (
        "currentSessionId",
        "sessionStatusBadge",
        "saveOriginalToggle",
        "saveTranslationToggle",
        "saveAnalysisToggle",
        "sessionSelect",
        "restoreSessionButton",
        "copyOriginalButton",
        "copyTranslationButton",
    ):
        assert f'id="{control_id}"' in HTML
    for kind in ("json", "original-txt", "translation-txt", "markdown"):
        assert f'data-session-download="{kind}"' in HTML
    assert 'id="saveAudioToggle"' not in HTML
    assert "오디오 저장은 지원하지 않습니다" in HTML


def test_phase3a_frontend_uses_safe_session_apis_and_clipboard_fallback() -> None:
    for endpoint in (
        'apiRequest("/api/sessions")',
        'apiRequest("/api/session/settings")',
        "/download/${format}",
    ):
        assert endpoint in JS
    assert "navigator.clipboard?.writeText" in JS
    assert "document.execCommand(\"copy\")" in JS
    assert "클립보드 복사 실패" in JS
    assert "URL.revokeObjectURL" in JS


def test_session_events_are_handled_before_generic_final_event() -> None:
    session_handler = JS.index('["session_created", "session_status", "session_finalized", "session_recovered"]')
    generic_final = JS.index('if (type.includes("final")')
    assert session_handler < generic_final


def test_phase3a_layout_has_responsive_rules() -> None:
    assert ".session-layout" in CSS
    assert ".download-button-grid" in CSS
    assert "@media" in CSS


def test_long_secondary_sections_are_accessible_collapsibles_closed_by_default() -> None:
    panels = (
        ("live-share-card", "liveShareDetails", "liveShareDetailsBody"),
        ("context-card", "contextDetails", "contextDetailsBody"),
        ("session-card", "sessionDetails", "sessionDetailsBody"),
        ("analysis-card", "analysisDetails", "analysisDetailsBody"),
    )
    for card_class, details_id, body_id in panels:
        details = re.search(
            rf'<details class="{card_class} collapsible-card" id="{details_id}"[^>]*>',
            HTML,
        )
        assert details is not None
        assert re.search(r"\sopen(?:\s|=|>)", details.group(0)) is None
        assert f'aria-controls="{body_id}"' in HTML
        assert f'class="collapsible-card-body" id="{body_id}"' in HTML

    assert HTML.count('class="collapsible-chevron" aria-hidden="true"') == 4
    assert HTML.count('aria-expanded="false"') >= 4
    assert 'document.querySelectorAll("details.collapsible-card")' in JS
    assert 'details.addEventListener("toggle", syncExpandedState)' in JS
    assert 'if (!["Enter", " "].includes(event.key)) return' in JS
    assert ".collapsible-card > summary:focus-visible" in CSS
    assert ".collapsible-card[open] .collapsible-chevron" in CSS
    assert ".collapsible-card > .collapsible-card-body" in CSS


def test_phase3b_analysis_controls_and_result_sections_are_present() -> None:
    for control_id in (
        "analysisProviderSelect",
        "analysisAutoRunToggle",
        "analysisApplyButton",
        "analysisTargetSession",
        "generateAnalysisButton",
        "cancelAnalysisButton",
        "retryAnalysisButton",
        "analysisStatusBadge",
        "analysisPurpose",
        "analysisDiscussions",
        "analysisDecisions",
        "analysisActions",
        "analysisQuestions",
        "analysisWarnings",
    ):
        assert f'id="{control_id}"' in HTML
    assert "회사 보안정책" in HTML
    assert "참가자의 동의" in HTML
    assert '<option value="gemini">Gemini API</option>' in HTML
    assert 'id="analysisGeminiWarning"' in HTML


def test_phase3b_frontend_uses_explicit_analysis_apis_and_evidence_navigation() -> None:
    for endpoint in (
        'apiRequest("/api/analysis/providers")',
        'apiRequest("/api/analysis/settings")',
        "/api/sessions/${encodeURIComponent(sessionId)}/analysis",
        'action === "generate" ? "" : `/${action}`',
    ):
        assert endpoint in JS
    assert "dataset.evidenceSegmentId" in JS
    assert "scrollIntoView" in JS
    assert "evidence-highlight" in JS
    assert "analysis_completed" in JS


def test_phase3b_page_load_does_not_post_analysis_or_embed_external_urls() -> None:
    assert 'method: "POST"' in JS
    assert "RUN_OPENAI_ANALYSIS_LIVE_TEST" not in JS
    assert "OPENAI_API_KEY" not in HTML
    assert "https://" not in HTML + JS
    assert "http://" not in HTML + JS


def test_translation_only_saved_segments_remain_restorable() -> None:
    assert "segment.text || segment.translation_result" in JS
    assert "원문 저장 안 함" in JS
    assert "event.original_saved === false" in JS


def test_phase3b_layout_has_overflow_and_mobile_rules() -> None:
    assert ".analysis-card" in CSS
    assert ".analysis-action-details" in CSS
    assert ".evidence-button" in CSS
    assert "overflow-wrap" in CSS
    assert "@media" in CSS


def test_local_translation_worker_status_is_visible_and_polled_safely() -> None:
    assert 'id="providerDetailWorkerRow"' in HTML
    assert 'id="providerDetailWorkerStatus"' in HTML
    assert 'apiRequest("/api/diagnostics"' in JS
    assert "startTranslationWorkerPolling" in JS
    assert "translationWorkerText" in JS
    asset_versions = re.findall(
        r'/static/(?:style\.css|i18n\.js|app\.js)\?v=([^"\']+)',
        HTML,
    )
    assert len(asset_versions) == 3
    assert len(set(asset_versions)) == 1


def test_runtime_stt_audio_and_translation_queue_health_is_visible() -> None:
    for control_id in (
        "sttRuntimeHealth",
        "audioRuntimeHealth",
        "translationQueueHealth",
    ):
        assert f'id="{control_id}"' in HTML
    for diagnostic_field in (
        "reconnecting",
        "reconnect_exhausted",
        "buffered_audio_ms",
        "dropped_audio_ms",
        "oldest_wait_ms",
    ):
        assert diagnostic_field in JS
    assert "applyRuntimeDiagnostics" in JS
    assert ".runtime-health" in CSS


def test_context_engine_frontend_contains_consent_based_controls() -> None:
    for element_id in (
        "contextProfileSelect",
        "contextEntryCategory",
        "contextCanonicalInput",
        "contextVariantsInput",
        "generateContextSuggestionsButton",
        "contextSuggestionList",
    ):
        assert f'id="{element_id}"' in HTML
    assert "사람 이름" in HTML
    assert "자동 등록하지 않습니다" in HTML
    assert "/api/context/suggestions/" in JS
    assert 'accept: decision === "accept"' in JS
    assert "max-height: 350px" in CSS
    assert "overflow-y: auto" in CSS
    assert 'aria-label="등록된 용어와 사람 이름"' in HTML
