from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.translation import (
    DEFAULT_GLOSSARY_TERMS,
    LocalTranslationProvider,
    NoneTranslationProvider,
    OpenAITranslationProvider,
    TranslationErrorCode,
    TranslationGlossary,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationStatus,
    build_translation_instructions,
    restore_glossary_terms,
    select_relevant_glossary_terms,
)


def request(**changes):
    values = {
        "segment_id": "segment-1",
        "session_id": "session-1",
        "source_text": "Review MK119 on 2026-07-10 at 15:30.",
        "source_language": "en",
    }
    values.update(changes)
    return TranslationRequest(**values)


def test_translation_request_validation_and_serialization():
    item = request(
        previous_context=(" prior ", ""),
        glossary_terms=(" Custom ",),
        boundary_reason=" HARD_LIMIT ",
        source_is_incomplete=True,
    )
    assert item.previous_context == ("prior",)
    assert item.glossary_terms == ("Custom",)
    assert item.model_dump()["session_id"] == "session-1"
    assert item.boundary_reason == "hard_limit"
    assert item.model_dump()["source_is_incomplete"] is True
    with pytest.raises(ValueError):
        request(source_text="  ")
    reverse = request(
        source_text="회의를 시작하겠습니다.",
        source_language="ko",
        target_language="ja",
    )
    assert reverse.source_language == "ko"
    assert reverse.target_language == "ja"


def test_relevant_glossary_selection_is_bounded_and_uses_word_boundaries():
    terms = ("RMS", "BMS", "PrimeDrive", "Unused")

    assert select_relevant_glossary_terms(
        terms,
        ("ARMS is unrelated. BMS connects to PrimeDrive.",),
    ) == ("BMS", "PrimeDrive")
    assert select_relevant_glossary_terms(terms, ("BMS and PrimeDrive",), limit=1) == (
        "BMS",
    )
    assert "glossary terms" not in build_translation_instructions(())
    korean_to_english = request(
        source_text="회의를 시작하겠습니다.",
        source_language="ko",
        target_language="en",
    )
    assert korean_to_english.source_language == "ko"
    assert korean_to_english.target_language == "en"
    with pytest.raises(ValueError):
        request(target_language="fr")


def test_provider_is_an_abstract_interface_and_none_is_safe_default():
    with pytest.raises(TypeError):
        TranslationProvider()

    async def scenario():
        provider = NoneTranslationProvider()
        health = await provider.health_check()
        result = await provider.translate(request())
        assert health.available and not health.external
        assert result.status is TranslationStatus.DISABLED
        assert result.translated_text is None
        assert result.session_id == "session-1"
        await provider.close()

    asyncio.run(scenario())


def test_central_glossary_and_prompt_preservation_rules():
    glossary = TranslationGlossary().extend(("Custom Product", "mk119"))
    assert glossary.terms.count("MK119") == 1
    assert set(DEFAULT_GLOSSARY_TERMS).issubset(glossary.terms)
    prompt = build_translation_instructions(glossary.terms)
    for term in DEFAULT_GLOSSARY_TERMS:
        assert term in prompt
    for invariant in ("numbers", "dates", "times", "IP addresses", "ports", "paths"):
        assert invariant in prompt
    assert "Return only the Korean translation" in prompt

    reverse_prompt = build_translation_instructions(
        glossary.terms,
        source_language="ko",
        target_language="ja",
    )
    assert "Korean meeting utterances into natural Japanese" in reverse_prompt
    assert "Return only the Japanese translation" in reverse_prompt

    english_prompt = build_translation_instructions(
        glossary.terms,
        source_language="ko",
        target_language="en",
    )
    assert "Korean meeting utterances into natural English" in english_prompt
    assert "Return only the English translation" in english_prompt
    assert "'\uc774 \uc2ed \uc77c \uc77c' is '\uc774\uc2ed\uc77c\uc77c' (the 21st)" in english_prompt
    assert "'\uc774 \uc2ed \uc77c\ub85c' is '\uc774\uc2ed\uc77c\ub85c' (the 20th" in english_prompt


@pytest.mark.parametrize(
    "model_output",
    ("__MLT_TERM_0__", "_MLT_TERM_0__", "MLT _ TERM _ 0_"),
)
def test_glossary_restoration_tolerates_sentencepiece_marker_changes(model_output):
    assert restore_glossary_terms(model_output, {"__MLT_TERM_0__": "System Test"}) == (
        "System Test"
    )


def test_local_provider_detects_missing_installation_without_loading_models(tmp_path: Path):
    async def scenario():
        provider = LocalTranslationProvider(model_path=tmp_path / "missing")
        health = await provider.health_check()
        assert not health.available
        assert not health.external
        with pytest.raises(TranslationProviderError) as caught:
            await provider.translate(request())
        assert caught.value.code is TranslationErrorCode.PROVIDER_UNAVAILABLE

    asyncio.run(scenario())


def test_local_provider_requires_sentencepiece_asset(tmp_path: Path):
    model = tmp_path / "incomplete-ct2"
    model.mkdir()
    (model / "model.bin").write_bytes(b"fake")
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "shared_vocabulary.json").write_text("{}", encoding="utf-8")
    (model / "vocab.json").write_text("{}", encoding="utf-8")
    (model / "tokenizer_config.json").write_text("{}", encoding="utf-8")

    async def scenario():
        provider = LocalTranslationProvider(
            model_path=model,
            translator_factory=lambda _language, _path: lambda text: text,
        )
        assert not (await provider.health_check()).available

    asyncio.run(scenario())


def test_local_provider_uses_only_explicit_local_path_and_restores_glossary(tmp_path: Path):
    model = tmp_path / "m2m100-ct2"
    model.mkdir()
    (model / "model.bin").write_bytes(b"fake")
    (model / "sentencepiece.bpe.model").write_bytes(b"fake")
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "shared_vocabulary.json").write_text("{}", encoding="utf-8")
    (model / "vocab.json").write_text("{}", encoding="utf-8")
    factory_calls = []

    def factory(language, path):
        factory_calls.append((language, path))
        return lambda text: f"번역: {text}"

    async def scenario():
        provider = LocalTranslationProvider(model_path=model, translator_factory=factory)
        assert (await provider.health_check()).available
        with pytest.raises(TranslationProviderError) as unsupported:
            await provider.translate(request(target_language="en"))
        assert unsupported.value.code is TranslationErrorCode.UNSUPPORTED_LANGUAGE
        assert factory_calls == []
        result = await provider.translate(request(source_text="MK119 System Test"))
        assert result.status is TranslationStatus.COMPLETED
        assert "MK119" in result.translated_text
        assert "System Test" in result.translated_text
        assert factory_calls == [("en", model)]
        await provider.close()

    asyncio.run(scenario())


class FakeResponses:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeOpenAIClient:
    def __init__(self, outcome):
        self.responses = FakeResponses(outcome)
        self.closed = False

    async def close(self):
        self.closed = True


def test_openai_provider_uses_async_responses_api_and_output_text():
    client = FakeOpenAIClient(SimpleNamespace(output_text="MK119를 검토합니다."))

    async def scenario():
        provider = OpenAITranslationProvider(api_key="test-secret", model="test-model", client=client)
        assert (await provider.health_check()).available
        result = await provider.translate(request(
            glossary_terms=("MK119",),
            boundary_reason="hard_limit",
            source_is_incomplete=True,
        ))
        assert result.translated_text == "MK119를 검토합니다."
        call = client.responses.calls[0]
        assert call["model"] == "test-model"
        assert "MK119" in call["instructions"]
        assert "2026-07-10" in call["input"]
        assert '"source_is_incomplete":true' in call["input"]
        assert '"boundary_reason":"hard_limit"' in call["input"]
        assert "never invent a missing" in call["instructions"]
        assert "test-secret" not in repr(provider)
        assert "test-secret" not in str(result.to_dict())
        await provider.close()
        assert client.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("AuthenticationError", TranslationErrorCode.AUTHENTICATION_FAILED),
        ("RateLimitError", TranslationErrorCode.RATE_LIMITED),
        ("APIConnectionError", TranslationErrorCode.NETWORK_ERROR),
        ("APITimeoutError", TranslationErrorCode.REQUEST_TIMEOUT),
    ],
)
def test_openai_errors_are_classified_without_raw_message(error_type, expected):
    raw = type(error_type, (Exception,), {})("secret-key source text should never escape")
    client = FakeOpenAIClient(raw)

    async def scenario():
        provider = OpenAITranslationProvider(api_key="secret-key", model="test-model", client=client)
        with pytest.raises(TranslationProviderError) as caught:
            await provider.translate(request(source_text="private source text"))
        assert caught.value.code is expected
        exposed = f"{caught.value!s} {caught.value!r} {caught.value.as_dict()}"
        assert "secret-key" not in exposed
        assert "private source text" not in exposed

    asyncio.run(scenario())


def test_openai_missing_key_and_empty_response_are_not_success():
    async def scenario():
        missing = OpenAITranslationProvider(api_key=None, model="test-model", client=FakeOpenAIClient({}))
        assert not (await missing.health_check()).available
        with pytest.raises(TranslationProviderError) as missing_error:
            await missing.translate(request())
        assert missing_error.value.code is TranslationErrorCode.API_KEY_MISSING

        empty = OpenAITranslationProvider(
            api_key="configured",
            model="test-model",
            client=FakeOpenAIClient(SimpleNamespace(output_text="   ")),
        )
        with pytest.raises(TranslationProviderError) as invalid:
            await empty.translate(request())
        assert invalid.value.code is TranslationErrorCode.INVALID_RESPONSE

    asyncio.run(scenario())


def test_openai_client_factory_disables_sdk_retries():
    captured = {}
    client = FakeOpenAIClient(SimpleNamespace(output_text="번역"))

    def factory(**kwargs):
        captured.update(kwargs)
        return client

    async def scenario():
        provider = OpenAITranslationProvider(
            api_key="configured",
            model="test-model",
            client_factory=factory,
        )
        await provider.translate(request())
        assert captured == {"api_key": "configured", "max_retries": 0}
        assert "timeout" not in captured

    asyncio.run(scenario())


def test_openai_explicit_prepare_builds_client_without_generation_request():
    captured = []
    client = FakeOpenAIClient(SimpleNamespace(output_text="번역"))

    def factory(**kwargs):
        captured.append(kwargs)
        return client

    async def scenario():
        provider = OpenAITranslationProvider(
            api_key="configured",
            model="test-model",
            client_factory=factory,
        )
        health = await provider.health_check()
        assert health.available is True
        assert captured == []

        provider.start_prepare()
        for _ in range(100):
            if captured:
                break
            await asyncio.sleep(0.005)
        assert captured == [{"api_key": "configured", "max_retries": 0}]
        assert client.responses.calls == []

        result = await provider.translate(request())
        assert result.translated_text == "번역"
        assert len(captured) == 1
        assert len(client.responses.calls) == 1
        await provider.close()

    asyncio.run(scenario())
