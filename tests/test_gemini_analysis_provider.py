from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.analysis import (
    AnalysisErrorCode,
    AnalysisProviderError,
    AnalysisRequest,
    AnalysisResponsePayload,
    AnalysisSegment,
    AnalysisStatus,
    GeminiAnalysisProvider,
)


def _payload(segment_id: str = "seg-1") -> dict[str, Any]:
    return {
        "meeting_purpose": {
            "text": "데이터 센터 전환 일정 확인",
            "evidence_segment_ids": [segment_id],
        },
        "key_discussions": [],
        "decisions": [
            {"text": "7월 20일로 결정", "evidence_segment_ids": [segment_id]}
        ],
        "action_items": [],
        "open_questions": [],
        "next_meeting_checks": [],
        "warnings": [],
    }


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        "session-1",
        (
            AnalysisSegment(
                segment_id="seg-1",
                original_text="7月20日に決定しました。",
                normalized_text="Data Centerは7月20日に決定しました。",
                korean_translation="데이터 센터는 7월 20일로 결정했습니다.",
                language="ja",
            ),
        ),
    )


class _FakeModels:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _FakeAsyncClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.aio = _FakeAsyncClient(models)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_gemini_analysis_uses_structured_output_and_evidence_validation() -> None:
    async def scenario() -> None:
        models = _FakeModels(
            SimpleNamespace(
                parsed=AnalysisResponsePayload.model_validate(_payload()),
                text=None,
            )
        )
        client = _FakeClient(models)
        provider = GeminiAnalysisProvider(
            api_key="configured-test-value",
            model="gemini-test-model",
            client=client,
        )

        result = await provider.analyze(_request())

        assert result.status is AnalysisStatus.COMPLETED
        assert result.provider == "gemini"
        assert result.decisions[0].evidence_segment_ids == ("seg-1",)
        call = models.calls[0]
        assert call["model"] == "gemini-test-model"
        assert "seg-1" in str(call["contents"])
        assert "normalized_text" in str(call["contents"])
        config = call["config"]
        assert isinstance(config, dict)
        assert config["response_mime_type"] == "application/json"
        assert "response_schema" not in config
        assert (
            config["response_json_schema"]
            == AnalysisResponsePayload.model_json_schema()
        )
        assert config["response_json_schema"]["additionalProperties"] is False
        assert "Do not use outside knowledge" in str(config["system_instruction"])

        await provider.close()
        assert client.aio.closed is True
        assert client.closed is True

    asyncio.run(scenario())


def test_gemini_analysis_accepts_strict_json_text_fallback() -> None:
    async def scenario() -> None:
        payload = AnalysisResponsePayload.model_validate(_payload())
        models = _FakeModels(SimpleNamespace(parsed=None, text=payload.model_dump_json()))
        provider = GeminiAnalysisProvider(
            api_key="configured-test-value",
            model="gemini-test-model",
            client=_FakeClient(models),
        )
        result = await provider.analyze(_request())
        assert result.meeting_purpose.text == "데이터 센터 전환 일정 확인"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("api_key", "model", "expected_reason"),
    [
        (None, "gemini-test-model", "GEMINI_API_KEY"),
        ("configured-test-value", None, "GEMINI_ANALYSIS_MODEL"),
    ],
)
def test_gemini_analysis_missing_configuration_is_unavailable(
    api_key: str | None,
    model: str | None,
    expected_reason: str,
) -> None:
    async def scenario() -> None:
        provider = GeminiAnalysisProvider(api_key=api_key, model=model)
        health = await provider.health_check()
        assert health.available is False
        assert expected_reason in str(health.reason)
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request())
        assert caught.value.code in {
            AnalysisErrorCode.API_KEY_MISSING,
            AnalysisErrorCode.PROVIDER_UNAVAILABLE,
        }

    asyncio.run(scenario())


def test_gemini_analysis_rejects_unknown_evidence_and_malformed_output() -> None:
    async def scenario(outcome: object) -> AnalysisErrorCode:
        provider = GeminiAnalysisProvider(
            api_key="configured-test-value",
            model="gemini-test-model",
            client=_FakeClient(_FakeModels(outcome)),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request())
        return caught.value.code

    unknown = SimpleNamespace(
        parsed=AnalysisResponsePayload.model_validate(_payload("missing-segment")),
        text=None,
    )
    malformed = SimpleNamespace(parsed=None, text="not-json")
    assert asyncio.run(scenario(unknown)) is AnalysisErrorCode.INVALID_EVIDENCE
    assert asyncio.run(scenario(malformed)) is AnalysisErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("status_code", "status", "expected"),
    [
        (400, "INVALID_ARGUMENT", AnalysisErrorCode.INVALID_RESPONSE),
        (400, "FAILED_PRECONDITION", AnalysisErrorCode.PROVIDER_UNAVAILABLE),
        (401, "UNAUTHENTICATED", AnalysisErrorCode.AUTHENTICATION_FAILED),
        (429, "RESOURCE_EXHAUSTED", AnalysisErrorCode.RATE_LIMITED),
        (504, "DEADLINE_EXCEEDED", AnalysisErrorCode.REQUEST_TIMEOUT),
        (503, "UNAVAILABLE", AnalysisErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_gemini_analysis_errors_are_sanitized(
    status_code: int,
    status: str,
    expected: AnalysisErrorCode,
) -> None:
    class ClientError(Exception):
        code = status_code

    ClientError.status = status

    async def scenario() -> None:
        provider = GeminiAnalysisProvider(
            api_key="configured-test-value",
            model="gemini-test-model",
            client=_FakeClient(_FakeModels(ClientError("confidential payload"))),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(_request())
        assert caught.value.code is expected
        assert "confidential" not in f"{caught.value!s} {caught.value!r}"

    asyncio.run(scenario())
