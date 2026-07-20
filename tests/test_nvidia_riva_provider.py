from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.translation import (
    DEFAULT_NVIDIA_RIVA_MODEL,
    NvidiaRivaTranslationProvider,
    TranslationErrorCode,
    TranslationProviderError,
    TranslationRequest,
)


class _Completions:
    def __init__(self, content: str | None = "번역 결과") -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class _Client:
    def __init__(self, content: str | None = "번역 결과") -> None:
        self.completions = _Completions(content)
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _request() -> TranslationRequest:
    return TranslationRequest(
        segment_id="segment-1",
        source_text="公開日は八月二十日に決定しました",
        source_language="ja",
        target_language="ko",
    )


def test_riva_uses_official_model_and_context_free_translation_prompt() -> None:
    async def scenario() -> None:
        client = _Client()
        provider = NvidiaRivaTranslationProvider(api_key="test-key", client=client)
        result = await provider.translate(_request())
        call = client.completions.calls[0]
        assert call["model"] == DEFAULT_NVIDIA_RIVA_MODEL
        assert call["temperature"] == 0
        assert call["max_tokens"] == 512
        assert "Japanese to Korean" in call["messages"][0]["content"]
        assert _request().source_text in call["messages"][1]["content"]
        assert result.translated_text == "번역 결과"
        assert result.provider == "nvidia_riva"
        await provider.close()
        assert client.closed is True

    asyncio.run(scenario())


def test_riva_missing_key_is_unavailable_without_calling_api() -> None:
    async def scenario() -> None:
        provider = NvidiaRivaTranslationProvider(api_key=None)
        health = await provider.health_check()
        assert health.available is False
        assert "NVIDIA_API_KEY" in (health.reason or "")
        with pytest.raises(TranslationProviderError) as raised:
            await provider.translate(_request())
        assert raised.value.code is TranslationErrorCode.API_KEY_MISSING

    asyncio.run(scenario())


def test_riva_rejects_empty_provider_response_safely() -> None:
    async def scenario() -> None:
        provider = NvidiaRivaTranslationProvider(api_key="test-key", client=_Client(""))
        with pytest.raises(TranslationProviderError) as raised:
            await provider.translate(_request())
        assert raised.value.code is TranslationErrorCode.INVALID_RESPONSE

    asyncio.run(scenario())
