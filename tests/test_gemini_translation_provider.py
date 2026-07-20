from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.translation import (
    GeminiTranslationProvider,
    NoneTranslationProvider,
    ProviderHealth,
    TranslationErrorCode,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
)

from .fakes import FakeCaptureFactory, FakeDeviceProvider, FakeEngine


class FakeModels:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeGeminiClient:
    def __init__(self, models: FakeModels) -> None:
        self.aio = SimpleNamespace(models=models)


class FakeAvailableProvider(TranslationProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.display_name = f"Fake {provider_name}"
        self.external = provider_name == "openai"

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=True,
            external=self.external,
            model="fake-model",
        )

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text="모의 번역",
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model="fake-model",
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=request.requested_at,
            latency_ms=0,
        )

    async def close(self) -> None:
        return None


def request() -> TranslationRequest:
    return TranslationRequest(
        segment_id="gemini-segment-1",
        session_id="gemini-session-1",
        source_text="MK119 is listening on 127.0.0.1:8765.",
        source_language="en",
        previous_context=("Version 2.4.1 was deployed.",),
        glossary_terms=("MK119", "Data Center"),
    )


def test_missing_key_is_unavailable_without_constructing_client() -> None:
    constructed = False

    def factory(**_: object) -> object:
        nonlocal constructed
        constructed = True
        raise AssertionError("client must not be constructed without a key")

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key=None,
            model="mock-model",
            client_factory=factory,
        )
        health = await provider.health_check()
        assert health.available is False
        assert constructed is False
        with pytest.raises(TranslationProviderError) as caught:
            await provider.translate(request())
        assert caught.value.code is TranslationErrorCode.GEMINI_API_KEY_MISSING

    asyncio.run(scenario())


def test_health_check_is_nonblocking_and_explicit_prepare_uses_no_generation() -> None:
    models = FakeModels(SimpleNamespace(text="준비 완료"))
    client = FakeGeminiClient(models)
    constructed: list[dict[str, object]] = []

    def factory(**kwargs: object) -> object:
        constructed.append(kwargs)
        return client

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client_factory=factory,
        )
        health = await provider.health_check()
        assert health.available is True
        assert constructed == []

        provider.start_prepare()
        for _ in range(100):
            if constructed:
                break
            await asyncio.sleep(0.005)
        assert constructed == [{"api_key": "configured-test-value"}]
        assert models.calls == []

        result = await provider.translate(request())
        assert result.translated_text == "준비 완료"
        assert len(constructed) == 1
        assert len(models.calls) == 1
        await provider.close()

    asyncio.run(scenario())


def test_mock_success_parses_text_and_reuses_shared_prompt_rules() -> None:
    models = FakeModels(SimpleNamespace(text="MK119는 127.0.0.1:8765에서 수신 대기 중입니다."))

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client=FakeGeminiClient(models),
        )
        result = await provider.translate(request())
        assert result.translated_text == "MK119는 127.0.0.1:8765에서 수신 대기 중입니다."
        assert result.provider == "gemini"
        assert result.model == "mock-model"
        assert len(models.calls) == 1
        call = models.calls[0]
        assert call["model"] == "mock-model"
        assert "MK119" in str(call["contents"])
        assert "Version 2.4.1" in str(call["contents"])
        assert "Data Center" in str(call["config"])

    asyncio.run(scenario())


def test_mock_reverse_translation_uses_korean_to_japanese_prompt() -> None:
    models = FakeModels(SimpleNamespace(text="会議を始めます。"))

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client=FakeGeminiClient(models),
        )
        reverse = TranslationRequest(
            segment_id="reverse-segment",
            session_id="reverse-session",
            source_text="회의를 시작하겠습니다.",
            source_language="ko",
            target_language="ja",
        )
        result = await provider.translate(reverse)
        assert result.translated_text == "会議を始めます。"
        assert result.target_language == "ja"
        assert "Korean meeting utterances into natural Japanese" in str(
            models.calls[0]["config"]
        )

    asyncio.run(scenario())


def test_mock_korean_to_english_translation_uses_english_prompt() -> None:
    models = FakeModels(SimpleNamespace(text="We will start the meeting."))

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client=FakeGeminiClient(models),
        )
        korean_to_english = TranslationRequest(
            segment_id="korean-english-segment",
            session_id="korean-english-session",
            source_text="회의를 시작하겠습니다.",
            source_language="ko",
            target_language="en",
        )
        result = await provider.translate(korean_to_english)
        assert result.translated_text == "We will start the meeting."
        assert result.target_language == "en"
        assert "Korean meeting utterances into natural English" in str(
            models.calls[0]["config"]
        )
        assert "Return only the English translation" in str(
            models.calls[0]["config"]
        )

    asyncio.run(scenario())


def test_mock_quota_error_is_mapped_without_exposing_raw_message() -> None:
    class ClientError(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"
        message = "quota exhausted; confidential upstream payload"

    models = FakeModels(ClientError("confidential upstream payload"))

    async def scenario() -> None:
        provider = GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client=FakeGeminiClient(models),
        )
        with pytest.raises(TranslationProviderError) as caught:
            await provider.translate(request())
        assert caught.value.code is TranslationErrorCode.GEMINI_QUOTA_EXHAUSTED
        public_error = f"{caught.value!s} {caught.value!r} {caught.value.as_dict()}"
        assert "confidential" not in public_error

    asyncio.run(scenario())


def test_server_start_provider_reads_and_selection_make_zero_generation_calls(
    tmp_path,
) -> None:
    models = FakeModels(SimpleNamespace(text="호출되어서는 안 됩니다."))
    client = FakeGeminiClient(models)

    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
        gemini_api_key="configured-test-value",
        gemini_translation_model="mock-model",
    )
    factories = {
        "none": NoneTranslationProvider,
        "local": lambda: FakeAvailableProvider("local"),
        "openai": lambda: FakeAvailableProvider("openai"),
        "gemini": lambda: GeminiTranslationProvider(
            api_key="configured-test-value",
            model="mock-model",
            client=client,
        ),
    }
    services = build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        capture_factory=FakeCaptureFactory(),
        engine_factory=FakeEngine,
        translation_provider_factories=factories,
    )

    with TestClient(create_app(services)) as http:
        providers_response = http.get("/api/translation/providers")
        settings_response = http.get("/api/translation/settings")
        selected_response = http.post(
            "/api/translation/settings",
            json={"provider": "gemini"},
        )
        test_response = http.post(
            "/api/translation/test",
            json={"text": "This must not be sent.", "source_language": "en"},
        )

        assert providers_response.status_code == 200
        providers = {
            item["id"]: item for item in providers_response.json()["providers"]
        }
        assert set(providers) == {"none", "local", "openai", "gemini"}
        assert providers["gemini"]["available"] is True
        assert providers["gemini"]["api_key_configured"] is True
        assert providers["gemini"]["model"] == "mock-model"
        assert settings_response.json()["gemini_api_key_configured"] is True
        assert "configured-test-value" not in settings_response.text
        assert selected_response.status_code == 200
        assert selected_response.json()["provider"] == "gemini"
        assert test_response.status_code == 409
        assert test_response.json()["code"] == "gemini_test_disabled"
        assert models.calls == []
