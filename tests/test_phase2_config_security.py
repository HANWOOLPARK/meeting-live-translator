from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config.settings import (
    DEFAULT_OPENAI_TRANSLATION_MODEL,
    AppSettings,
)
from backend.app.api.schemas import StartCaptureRequest, TranslationTestRequest
from backend.app.translation import (
    DEFAULT_GLOSSARY_TERMS,
    TranslationErrorCode,
    TranslationResult,
    TranslationStatus,
    load_glossary_file,
)


def test_translation_defaults_are_safe_without_api_key(tmp_path, monkeypatch) -> None:
    for name in (
        "TRANSLATION_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_TRANSLATION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AppSettings.from_env(tmp_path)

    assert settings.translation_provider == "none"
    assert settings.openai_api_key is None
    assert settings.openai_translation_model == DEFAULT_OPENAI_TRANSLATION_MODEL
    assert "api_key" not in str(settings.public_dict()).lower()


def test_english_to_korean_direction_is_public_and_accepted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRANSLATION_DIRECTION", "en_to_ko")
    monkeypatch.setenv("DEEPGRAM_STT_LANGUAGE", "en")

    settings = AppSettings.from_env(tmp_path)

    assert settings.translation_direction == "en_to_ko"
    assert settings.deepgram_stt_language == "en"
    assert settings.public_dict()["translation_direction"] == "en_to_ko"
    assert settings.public_dict()["allowed_translation_directions"] == [
        "ja_to_ko",
        "ja_to_en",
        "en_to_ko",
        "en_to_ja",
        "ko_to_ja",
        "ko_to_en",
    ]


@pytest.mark.parametrize(
    ("translation_direction", "source_language", "target_language"),
    (("ja_to_en", "ja", "en"), ("en_to_ja", "en", "ja")),
)
def test_cross_language_directions_accept_local_stt_and_api_schema(
    tmp_path,
    translation_direction: str,
    source_language: str,
    target_language: str,
) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        translation_direction=translation_direction,
        stt_provider="local",
    )
    capture_request = StartCaptureRequest(
        source="system",
        device_id="loopback-test",
        stt_provider="local",
        translation_direction=translation_direction,
    )
    translation_request = TranslationTestRequest(
        text="Meeting translation test",
        source_language=source_language,
        target_language=target_language,
    )

    assert settings.translation_direction == translation_direction
    assert capture_request.translation_direction == translation_direction
    assert translation_request.source_language == source_language
    assert translation_request.target_language == target_language


def test_korean_to_english_requires_deepgram_and_is_accepted_by_api(tmp_path) -> None:
    with pytest.raises(ValueError, match="requires Deepgram"):
        AppSettings(
            project_root=tmp_path,
            translation_direction="ko_to_en",
            stt_provider="local",
        )

    settings = AppSettings(
        project_root=tmp_path,
        translation_direction="ko_to_en",
        stt_provider="deepgram",
        deepgram_stt_language="ko",
    )
    capture_request = StartCaptureRequest(
        source="system",
        device_id="loopback-test",
        stt_provider="deepgram",
        translation_direction="ko_to_en",
    )
    translation_request = TranslationTestRequest(
        text="회의를 시작하겠습니다.",
        source_language="ko",
        target_language="en",
    )

    assert settings.translation_direction == "ko_to_en"
    assert settings.public_dict()["translation_direction"] == "ko_to_en"
    assert capture_request.translation_direction == "ko_to_en"
    assert translation_request.target_language == "en"


def test_api_key_is_not_exposed_by_repr_or_public_settings(tmp_path) -> None:
    secret = "phase2-test-secret"
    settings = AppSettings(
        project_root=tmp_path,
        openai_api_key=secret,
    )

    assert secret not in repr(settings)
    assert secret not in str(settings.public_dict())


def test_environment_takes_priority_over_project_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "TRANSLATION_PROVIDER=local\nOPENAI_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRANSLATION_PROVIDER", "none")
    monkeypatch.setenv("OPENAI_API_KEY", "process-secret")

    settings = AppSettings.from_env(tmp_path)

    assert settings.translation_provider == "none"
    assert settings.openai_api_key == "process-secret"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("translation_provider", "invalid"),
        ("translation_timeout_seconds", 0),
        ("translation_max_retries", -1),
        ("translation_context_segments", 21),
        ("translation_queue_max_size", 0),
        ("translation_max_concurrency", 0),
        ("deepgram_reconnect_max_attempts", 0),
        ("deepgram_reconnect_base_delay_seconds", -0.1),
        ("deepgram_reconnect_max_delay_seconds", 0),
        ("deepgram_reconnect_buffer_seconds", 0.4),
        ("deepgram_max_segment_seconds", 0.9),
    ],
)
def test_invalid_translation_settings_are_rejected(
    tmp_path,
    field: str,
    value: object,
) -> None:
    values = {"project_root": tmp_path, field: value}
    with pytest.raises(ValueError):
        AppSettings(**values)


def test_dotenv_and_runtime_outputs_are_ignored() -> None:
    project_root = Path(__file__).resolve().parents[1]
    rules = (project_root / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in rules
    assert ".run/" in rules
    assert ".venv/" in rules


def test_custom_glossary_file_extends_one_central_default(tmp_path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text(
        '{"terms":["Custom Rack", "mk119", "Custom Rack"]}',
        encoding="utf-8",
    )

    glossary = load_glossary_file(path)

    assert glossary.terms[: len(DEFAULT_GLOSSARY_TERMS)] == DEFAULT_GLOSSARY_TERMS
    assert glossary.terms.count("Custom Rack") == 1
    assert not any(term == "mk119" for term in glossary.terms)


def test_translation_result_validation_rejects_empty_success_and_raw_error() -> None:
    base = {
        "segment_id": "segment-1",
        "source_text": "Test",
        "translated_text": "번역",
        "source_language": "en",
        "target_language": "ko",
        "provider": "fake",
        "model": "fake-model",
        "status": TranslationStatus.COMPLETED,
        "requested_at": "2026-07-10T20:30:10+09:00",
        "completed_at": "2026-07-10T20:30:11+09:00",
        "latency_ms": 10,
    }
    with pytest.raises(ValueError):
        TranslationResult(**{**base, "translated_text": ""})

    failed = TranslationResult(
        **{
            **base,
            "translated_text": None,
            "status": TranslationStatus.FAILED,
            "error_code": TranslationErrorCode.AUTHENTICATION_FAILED,
            "error_message": "raw secret should be normalized",
        }
    )
    assert failed.error_message == "번역 API 인증에 실패했습니다."
