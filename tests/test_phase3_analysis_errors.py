from __future__ import annotations

import asyncio

import pytest

from backend.app.analysis import (
    AnalysisErrorCode,
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    NoneAnalysisProvider,
    RuleBasedAnalysisProvider,
    AnalysisManager,
    normalize_analysis_error,
)


class AuthenticationError(Exception):
    status_code = 401


class RateLimitError(Exception):
    status_code = 429


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthenticationError("raw secret"), AnalysisErrorCode.AUTHENTICATION_FAILED),
        (RateLimitError("raw secret"), AnalysisErrorCode.RATE_LIMITED),
        (APITimeoutError("raw secret"), AnalysisErrorCode.REQUEST_TIMEOUT),
        (APIConnectionError("raw secret"), AnalysisErrorCode.NETWORK_ERROR),
    ],
)
def test_analysis_provider_errors_are_classified_without_raw_message(
    error: Exception,
    expected: AnalysisErrorCode,
) -> None:
    normalized = normalize_analysis_error(error)

    assert normalized.code is expected
    assert "raw secret" not in str(normalized)
    assert "raw secret" not in repr(normalized)


def test_none_analysis_provider_performs_no_analysis() -> None:
    async def scenario() -> None:
        provider = NoneAnalysisProvider()
        result = await provider.analyze(
            AnalysisRequest(
                "session-1",
                (AnalysisSegment("seg-1", "決定しました。"),),
            )
        )
        health = await provider.health_check()

        assert result.status is AnalysisStatus.NOT_STARTED
        assert not result.decisions
        assert result.warnings == ("analysis_disabled",)
        assert health.available is True
        assert health.external is False

    asyncio.run(scenario())


def test_rule_based_distinguishes_proposal_question_and_action() -> None:
    async def scenario() -> None:
        provider = RuleBasedAnalysisProvider()
        result = await provider.analyze(
            AnalysisRequest(
                "session-1",
                (
                    AnalysisSegment("seg-1", "We should move the System Test."),
                    AnalysisSegment("seg-2", "Who owns the checklist?"),
                    AnalysisSegment("seg-3", "Alice will verify the checklist."),
                    AnalysisSegment("seg-4", "We agreed to keep the schedule."),
                ),
            )
        )

        assert [item.text for item in result.decisions] == [
            "We agreed to keep the schedule."
        ]
        assert [item.text for item in result.open_questions] == [
            "Who owns the checklist?"
        ]
        assert [item.task for item in result.action_items] == [
            "Alice will verify the checklist."
        ]

    asyncio.run(scenario())


def test_analysis_event_sink_log_does_not_copy_sensitive_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-phase3-log-secret"

    def failing_sink(_event: dict[str, object]) -> None:
        raise RuntimeError(secret)

    async def scenario() -> None:
        manager = AnalysisManager(object(), event_sink=failing_sink)
        await manager._emit({"type": "analysis_status", "status": "test"})
        await manager.shutdown()

    caplog.set_level("WARNING")
    asyncio.run(scenario())
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text
