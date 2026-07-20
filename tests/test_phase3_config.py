from __future__ import annotations

from backend.app.config.settings import AppSettings


def test_phase3_storage_defaults_are_safe(tmp_path, monkeypatch) -> None:
    for name in (
        "SESSION_SAVE_ORIGINAL",
        "SESSION_SAVE_TRANSLATION",
        "SESSION_SAVE_ANALYSIS",
        "SESSION_AUTO_RECOVER",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AppSettings.from_env(tmp_path)

    assert settings.session_save_original is True
    assert settings.session_save_translation is True
    assert settings.session_save_analysis is True
    assert settings.session_auto_recover is True
    assert settings.public_dict()["session_storage"] == {
        "save_original": True,
        "save_translation": True,
        "save_analysis": True,
        "save_audio": False,
        "auto_recover": True,
    }


def test_phase3_storage_environment_flags(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SESSION_SAVE_ORIGINAL", "false")
    monkeypatch.setenv("SESSION_SAVE_TRANSLATION", "0")
    monkeypatch.setenv("SESSION_SAVE_ANALYSIS", "no")
    monkeypatch.setenv("SESSION_AUTO_RECOVER", "off")

    settings = AppSettings.from_env(tmp_path)

    assert settings.session_save_original is False
    assert settings.session_save_translation is False
    assert settings.session_save_analysis is False
    assert settings.session_auto_recover is False


def test_phase3_analysis_defaults_are_opt_in_and_bounded(tmp_path, monkeypatch) -> None:
    for name in (
        "ANALYSIS_PROVIDER",
        "OPENAI_ANALYSIS_MODEL",
        "GEMINI_ANALYSIS_MODEL",
        "GEMINI_TRANSLATION_MODEL",
        "ANALYSIS_TIMEOUT_SECONDS",
        "ANALYSIS_MAX_RETRIES",
        "ANALYSIS_AUTO_RUN_ON_STOP",
        "ANALYSIS_MAX_SEGMENTS_PER_CHUNK",
        "ANALYSIS_MAX_CHARS_PER_CHUNK",
        "ANALYSIS_MAX_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AppSettings.from_env(tmp_path)

    assert settings.analysis_provider == "none"
    assert settings.openai_analysis_model is None
    assert settings.gemini_analysis_model is None
    assert settings.analysis_auto_run_on_stop is False
    assert settings.analysis_timeout_seconds == 60
    assert settings.analysis_max_retries == 1
    assert settings.analysis_max_segments_per_chunk == 100
    assert settings.analysis_max_chars_per_chunk == 24_000
    assert settings.analysis_max_concurrency == 1


def test_phase3_analysis_environment_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANALYSIS_PROVIDER", "rule_based")
    monkeypatch.setenv("OPENAI_ANALYSIS_MODEL", "configured-model")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "shared-gemini-model")
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("ANALYSIS_MAX_RETRIES", "2")
    monkeypatch.setenv("ANALYSIS_AUTO_RUN_ON_STOP", "true")
    monkeypatch.setenv("ANALYSIS_MAX_SEGMENTS_PER_CHUNK", "50")
    monkeypatch.setenv("ANALYSIS_MAX_CHARS_PER_CHUNK", "12000")

    settings = AppSettings.from_env(tmp_path)

    assert settings.analysis_provider == "rule_based"
    assert settings.openai_analysis_model == "configured-model"
    assert settings.gemini_analysis_model == "shared-gemini-model"
    assert settings.analysis_timeout_seconds == 45
    assert settings.analysis_max_retries == 2
    assert settings.analysis_auto_run_on_stop is True
    assert settings.analysis_max_segments_per_chunk == 50
    assert settings.analysis_max_chars_per_chunk == 12_000


def test_gemini_analysis_model_can_override_translation_model(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "translation-model")
    monkeypatch.setenv("GEMINI_ANALYSIS_MODEL", "analysis-model")

    settings = AppSettings.from_env(tmp_path)

    assert settings.gemini_translation_model == "translation-model"
    assert settings.gemini_analysis_model == "analysis-model"

    shared = AppSettings(
        project_root=tmp_path,
        analysis_provider="gemini",
        gemini_translation_model="translation-model",
    )
    assert shared.public_dict()["analysis"]["model"] == "translation-model"
