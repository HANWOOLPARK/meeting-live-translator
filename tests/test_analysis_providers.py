from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.analysis import (
    AnalysisErrorCode,
    AnalysisProviderError,
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    OpenAIAnalysisProvider,
    RuleBasedAnalysisProvider,
    UNDECIDED,
    build_analysis_instructions,
)
from backend.app.analysis.structured import AnalysisResponsePayload


def _request(*texts: tuple[str, str | None]) -> AnalysisRequest:
    return AnalysisRequest(
        "session-1",
        tuple(
            AnalysisSegment(
                segment_id=f"seg-{index}",
                original_text=original,
                korean_translation=korean,
                language="ja",
            )
            for index, (original, korean) in enumerate(texts, start=1)
        ),
    )


def _payload(segment_id: str = "seg-1") -> dict[str, Any]:
    return {
        "meeting_purpose": {
            "text": "System Test 일정 확정",
            "evidence_segment_ids": [segment_id],
        },
        "key_discussions": [],
        "decisions": [
            {"text": "7월 15일로 결정", "evidence_segment_ids": [segment_id]}
        ],
        "action_items": [],
        "open_questions": [],
        "next_meeting_checks": [],
        "warnings": [],
    }


class _Responses:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


class _RaisingResponses:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def parse(self, **_: Any) -> Any:
        raise self.error


class _Client:
    def __init__(self, parsed: Any) -> None:
        self.responses = _Responses(parsed)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_openai_provider_uses_mocked_responses_parse_and_strict_model() -> None:
    async def scenario() -> None:
        client = _Client(AnalysisResponsePayload.model_validate(_payload()))
        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-analysis-model",
            client=client,
        )

        result = await provider.analyze(_request(("7月15日に決定しました。", None)))

        assert result.status is AnalysisStatus.COMPLETED
        assert result.decisions[0].evidence_segment_ids == ("seg-1",)
        call = client.responses.calls[0]
        assert call["model"] == "test-analysis-model"
        assert call["text_format"] is AnalysisResponsePayload
        assert call["store"] is False
        assert "seg-1" in call["input"]
        assert "미정" in call["instructions"]
        await provider.close()
        assert client.closed

    asyncio.run(scenario())


def test_openai_provider_factory_disables_sdk_retries() -> None:
    async def scenario() -> None:
        captured: dict[str, Any] = {}
        client = _Client(_payload())

        def factory(**kwargs: Any) -> _Client:
            captured.update(kwargs)
            return client

        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-analysis-model",
            client_factory=factory,
        )
        await provider.analyze(_request(("決定しました。", None)))
        assert captured == {"api_key": "test-key", "max_retries": 0}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("api_key", "model", "expected_reason"),
    [
        ("test-key", None, "OPENAI_ANALYSIS_MODEL"),
        (None, "test-model", "OPENAI_API_KEY"),
    ],
)
def test_openai_provider_missing_configuration_is_safe(
    api_key: str | None,
    model: str | None,
    expected_reason: str,
) -> None:
    async def scenario() -> None:
        provider = OpenAIAnalysisProvider(api_key=api_key, model=model)
        health = await provider.health_check()
        assert not health.available
        assert expected_reason in str(health.reason)
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request(("決定しました。", None)))
        assert caught.value.code in {
            AnalysisErrorCode.API_KEY_MISSING,
            AnalysisErrorCode.PROVIDER_UNAVAILABLE,
        }

    asyncio.run(scenario())


def test_openai_provider_rejects_unknown_evidence() -> None:
    async def scenario() -> None:
        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-model",
            client=_Client(_payload("seg-missing")),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request(("決定しました。", None)))
        assert caught.value.code is AnalysisErrorCode.INVALID_EVIDENCE

    asyncio.run(scenario())


def test_openai_provider_rejects_empty_or_extra_structured_output() -> None:
    async def scenario(parsed: Any) -> AnalysisErrorCode:
        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-model",
            client=_Client(parsed),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request(("決定しました。", None)))
        return caught.value.code

    extra = {**_payload(), "unexpected": "value"}
    assert asyncio.run(scenario(None)) is AnalysisErrorCode.INVALID_RESPONSE
    assert asyncio.run(scenario(extra)) is AnalysisErrorCode.INVALID_RESPONSE


def test_openai_provider_classifies_parse_validation_as_invalid_response() -> None:
    async def scenario() -> None:
        validation_error: Exception
        try:
            AnalysisResponsePayload.model_validate({})
        except Exception as error:
            validation_error = error
        client = _Client(_payload())
        client.responses = _RaisingResponses(validation_error)
        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-model",
            client=client,
        )

        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request(("決定しました。", None)))
        assert caught.value.code is AnalysisErrorCode.INVALID_RESPONSE

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error_type", "status_code", "expected"),
    [
        ("AuthenticationError", 401, AnalysisErrorCode.AUTHENTICATION_FAILED),
        ("RateLimitError", 429, AnalysisErrorCode.RATE_LIMITED),
        ("APITimeoutError", None, AnalysisErrorCode.REQUEST_TIMEOUT),
        ("APIConnectionError", None, AnalysisErrorCode.NETWORK_ERROR),
    ],
)
def test_openai_provider_normalizes_sdk_errors_without_raw_details(
    error_type: str,
    status_code: int | None,
    expected: AnalysisErrorCode,
) -> None:
    async def scenario() -> None:
        error_class = type(error_type, (Exception,), {})
        raw_error = error_class("secret raw request body")
        if status_code is not None:
            raw_error.status_code = status_code
        client = _Client(_payload())
        client.responses = _RaisingResponses(raw_error)
        provider = OpenAIAnalysisProvider(
            api_key="test-key",
            model="test-model",
            client=client,
        )

        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request(("決定しました。", None)))
        assert caught.value.code is expected
        assert "secret raw request body" not in str(caught.value)

    asyncio.run(scenario())


def test_rule_based_provider_is_conservative_and_prefers_original_text() -> None:
    async def scenario() -> None:
        provider = RuleBasedAnalysisProvider()
        request = _request(
            ("これは提案です。", "결정했습니다."),
            ("Tanaka will verify the BMS report by next week.", None),
            ("確認します。", None),
            ("次回会議はいつですか？", None),
            ("7月15日に決定しました。", None),
        )

        result = await provider.analyze(request)

        assert result.meeting_purpose.text == UNDECIDED
        assert [item.text for item in result.decisions] == ["7月15日に決定しました。"]
        assert len(result.action_items) == 2
        assert result.action_items[0].assignee == "Tanaka"
        assert result.action_items[0].due_date == "by next week"
        assert result.action_items[1].assignee == UNDECIDED
        assert result.open_questions[0].evidence_segment_ids == ("seg-4",)
        assert result.next_meeting_checks[0].evidence_segment_ids == ("seg-4",)

    asyncio.run(scenario())


def test_rule_based_rejects_question_actions_and_negated_decisions() -> None:
    async def scenario() -> None:
        provider = RuleBasedAnalysisProvider()
        result = await provider.analyze(
            _request(
                ("Who will verify the report?", None),
                ("We have not decided yet.", None),
                ("We never agreed on that.", None),
            )
        )

        assert [item.text for item in result.open_questions] == [
            "Who will verify the report?"
        ]
        assert not result.action_items
        assert not result.decisions

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("text", "assignee", "due_date"),
    [
        ("田中さんが7月15日までに確認します。", "田中", "7月15日までに"),
        ("김철수님이 7월 15일까지 확인하겠습니다.", "김철수", "7월 15일까지"),
        ("Alice will verify it by July 15.", "Alice", "July 15"),
    ],
)
def test_rule_based_preserves_localized_explicit_due_date(
    text: str,
    assignee: str,
    due_date: str,
) -> None:
    async def scenario() -> None:
        result = await RuleBasedAnalysisProvider().analyze(_request((text, None)))
        assert len(result.action_items) == 1
        assert result.action_items[0].assignee == assignee
        assert result.action_items[0].due_date == due_date

    asyncio.run(scenario())


def test_prompt_contains_grounding_and_shared_glossary_rules() -> None:
    prompt = build_analysis_instructions()

    assert "Do not use outside knowledge" in prompt
    assert "original_text" in prompt
    assert "evidence" in prompt
    assert "Fit & Gap" in prompt
    assert "System Test" in prompt
