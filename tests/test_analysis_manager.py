from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import pytest

from backend.app.analysis import (
    AnalysisErrorCode,
    AnalysisManager,
    AnalysisProvider,
    AnalysisProviderHealth,
    AnalysisRequest,
    AnalysisStatus,
    EvidenceItem,
    MeetingAnalysis,
    analysis_error,
)


class FakeRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.saved: dict[str, dict[str, Any]] = {}
        self.statuses: list[tuple[str, str, str | None]] = []

    def add(self, session_id: str, *texts: str) -> None:
        self.sessions[session_id] = {
            "session_id": session_id,
            "metadata": {
                "analysis_status": "not_started",
                "analysis_provider": "none",
                "analysis_revision": 0,
            },
            "segments": [
                {
                    "segment_id": f"{session_id}-seg-{index}",
                    "original_text": text,
                    "korean_translation": None,
                    "language": "ja",
                    "source": "system",
                }
                for index, text in enumerate(texts, start=1)
            ],
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        return deepcopy(self.sessions[session_id])

    def load_analysis(self, session_id: str) -> dict[str, Any] | None:
        payload = self.saved.get(session_id)
        return deepcopy(payload) if payload is not None else None

    def set_analysis_status(
        self,
        session_id: str,
        status: str,
        *,
        provider: str | None = None,
    ) -> dict[str, Any]:
        metadata = self.sessions[session_id]["metadata"]
        metadata["analysis_status"] = status
        if provider is not None:
            metadata["analysis_provider"] = provider
        self.statuses.append((session_id, status, provider))
        return {"session_id": session_id, "status": status, "provider": provider}

    def save_analysis(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        saved = deepcopy(payload)
        self.saved[session_id] = saved
        metadata = self.sessions[session_id]["metadata"]
        metadata.update(
            {
                "analysis_status": "completed",
                "analysis_provider": saved["provider"],
                "analysis_revision": saved["revision"],
            }
        )
        return deepcopy(saved)


class CountingProvider(AnalysisProvider):
    provider_name = "counting"
    display_name = "Counting"
    external = False

    def __init__(self) -> None:
        self.calls: list[AnalysisRequest] = []
        self.closed = False

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        self.calls.append(request)
        segment = request.segments[0]
        return MeetingAnalysis(
            session_id=request.session_id,
            provider=self.provider_name,
            model=None,
            status=AnalysisStatus.COMPLETED,
            meeting_purpose=EvidenceItem("일정 확인", (segment.segment_id,)),
            decisions=(EvidenceItem(segment.preferred_text, (segment.segment_id,)),),
        )

    async def health_check(self) -> AnalysisProviderHealth:
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            not self.closed,
            self.external,
        )

    async def close(self) -> None:
        self.closed = True


class BlockingProvider(CountingProvider):
    provider_name = "blocking"

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        self.started.set()
        await self.release.wait()
        return await super().analyze(request)


class FailingProvider(CountingProvider):
    provider_name = "failing"

    def __init__(self, code: AnalysisErrorCode = AnalysisErrorCode.NETWORK_ERROR) -> None:
        super().__init__()
        self.code = code
        self.attempts = 0

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        self.attempts += 1
        raise analysis_error(self.code)


class WrongSessionProvider(CountingProvider):
    provider_name = "wrong_session"

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        result = await super().analyze(request)
        return MeetingAnalysis(
            session_id="another-session",
            provider=self.provider_name,
            model=result.model,
            status=result.status,
            meeting_purpose=result.meeting_purpose,
            decisions=result.decisions,
        )


class SlowProvider(CountingProvider):
    provider_name = "slow"

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        self.attempts += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def test_reads_and_provider_listing_do_not_trigger_analysis() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = CountingProvider()
        manager = AnalysisManager(repository, provider)

        assert await manager.get("session-1") is None
        assert (await manager.providers())[0]["available"] is True
        detail = await manager.detail("session-1")
        assert detail["status"] == "not_started"
        assert detail["result"] is None
        assert provider.calls == []
        await manager.shutdown()

    asyncio.run(scenario())


def test_submit_is_pending_immediately_then_chunks_and_persists() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "first decision", "second decision")
        provider = CountingProvider()
        events: list[dict[str, Any]] = []
        manager = AnalysisManager(
            repository,
            provider,
            max_segments_per_chunk=1,
            event_sink=events.append,
        )

        submission = await manager.submit("session-1")
        assert submission.accepted
        assert submission.status is AnalysisStatus.PENDING
        result = await manager.wait("session-1")

        assert result is not None
        assert result.status is AnalysisStatus.COMPLETED
        assert len(provider.calls) == 2
        assert len(result.decisions) == 2
        assert repository.saved["session-1"]["revision"] == 1
        assert [status for _, status, _ in repository.statuses] == [
            "pending",
            "running",
        ]
        assert {event["type"] for event in events} >= {
            "analysis_pending",
            "analysis_status",
            "analysis_completed",
        }
        await manager.shutdown()

    asyncio.run(scenario())


def test_simultaneous_submit_registers_only_one_task() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = BlockingProvider()
        manager = AnalysisManager(repository, provider)

        first, second = await asyncio.gather(
            manager.submit("session-1"),
            manager.submit("session-1"),
        )
        assert sum(item.accepted for item in (first, second)) == 1
        await provider.started.wait()
        assert await manager.cancel("session-1")
        detail = await manager.detail("session-1")
        assert detail["status"] == "cancelled"
        await manager.shutdown()

    asyncio.run(scenario())


def test_immediate_cancel_cannot_leave_pending_record() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = BlockingProvider()
        manager = AnalysisManager(repository, provider)

        assert (await manager.submit("session-1")).accepted
        assert await manager.cancel("session-1")
        detail = await manager.detail("session-1")
        assert detail["status"] == "cancelled"
        assert detail["error_code"] == "CANCELLED"
        assert repository.sessions["session-1"]["metadata"]["analysis_status"] == "cancelled"
        await manager.shutdown()

    asyncio.run(scenario())


def test_retry_is_bounded_and_uses_safe_error_code() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = FailingProvider()
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        manager = AnalysisManager(
            repository,
            provider,
            max_retries=1,
            backoff_seconds=0.25,
            sleep_func=sleep,
        )
        assert (await manager.submit("session-1")).accepted
        with pytest.raises(Exception) as caught:
            await manager.wait("session-1")
        assert isinstance(caught.value, type(analysis_error(AnalysisErrorCode.NETWORK_ERROR)))
        assert provider.attempts == 2
        assert delays == [0.25]
        detail = await manager.detail("session-1")
        assert detail["status"] == "failed"
        assert detail["error_code"] == "NETWORK_ERROR"
        assert "secret" not in str(caught.value)
        await manager.shutdown()

    asyncio.run(scenario())


def test_wait_replays_safe_failure_after_background_task_is_removed() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        manager = AnalysisManager(
            repository,
            FailingProvider(AnalysisErrorCode.AUTHENTICATION_FAILED),
            max_retries=0,
        )

        assert (await manager.submit("session-1")).accepted
        for _ in range(100):
            if (
                manager.running_session_id is None
                and (await manager.detail("session-1"))["status"] == "failed"
            ):
                break
            await asyncio.sleep(0.001)
        assert manager.running_session_id is None
        with pytest.raises(Exception) as caught:
            await manager.wait("session-1")
        assert getattr(caught.value, "code", None) is AnalysisErrorCode.AUTHENTICATION_FAILED
        await manager.shutdown()

    asyncio.run(scenario())


def test_provider_result_for_another_session_is_rejected() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        manager = AnalysisManager(
            repository,
            WrongSessionProvider(),
            max_retries=0,
        )

        assert (await manager.submit("session-1")).accepted
        with pytest.raises(Exception) as caught:
            await manager.wait("session-1")
        assert getattr(caught.value, "code", None) is AnalysisErrorCode.INVALID_RESPONSE
        assert (await manager.detail("session-1"))["status"] == "failed"
        await manager.shutdown()

    asyncio.run(scenario())


def test_provider_timeout_uses_manager_retry_limit() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = SlowProvider()
        manager = AnalysisManager(
            repository,
            provider,
            timeout_seconds=0.01,
            max_retries=1,
            backoff_seconds=0,
        )

        assert (await manager.submit("session-1")).accepted
        with pytest.raises(Exception) as caught:
            await manager.wait("session-1")
        assert getattr(caught.value, "code", None) is AnalysisErrorCode.REQUEST_TIMEOUT
        assert provider.attempts == 2
        assert (await manager.detail("session-1"))["error_code"] == "REQUEST_TIMEOUT"
        await manager.shutdown()

    asyncio.run(scenario())


def test_failed_reanalysis_preserves_previous_success() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        success = CountingProvider()
        manager = AnalysisManager(repository, success, max_retries=0)
        await manager.submit("session-1")
        previous = await manager.wait("session-1")
        assert previous is not None

        failing = FailingProvider(AnalysisErrorCode.AUTHENTICATION_FAILED)
        await manager.switch_provider(failing)
        submission = await manager.retry("session-1")
        assert submission.accepted
        with pytest.raises(Exception):
            await manager.wait("session-1")

        detail = await manager.detail("session-1")
        assert detail["status"] == "failed"
        assert detail["provider"] == "failing"
        assert detail["revision"] == 2
        assert detail["error_code"] == "AUTHENTICATION_FAILED"
        assert detail["has_previous_result"] is True
        assert detail["result"]["generated_at"] == previous.generated_at
        assert repository.saved["session-1"]["revision"] == 1
        await manager.shutdown()

    asyncio.run(scenario())


def test_saved_analysis_with_unsupported_schema_is_ignored() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        repository.saved["session-1"] = {
            "schema_version": 999,
            "session_id": "session-1",
            "provider": "counting",
            "model": None,
            "status": "completed",
            "generated_at": "2026-07-11T10:00:00+09:00",
            "revision": 1,
            "meeting_purpose": {
                "text": "미정",
                "evidence_segment_ids": [],
            },
            "key_discussions": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "next_meeting_checks": [],
            "warnings": [],
        }
        manager = AnalysisManager(repository, CountingProvider())

        assert await manager.get("session-1") is None
        await manager.shutdown()

    asyncio.run(scenario())


def test_shutdown_cancels_live_opt_in_work_and_closes_provider() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        repository.add("session-1", "決定しました。")
        provider = BlockingProvider()
        manager = AnalysisManager(repository, provider)

        assert provider.calls == []
        assert (await manager.submit("session-1")).accepted
        await provider.started.wait()
        await manager.shutdown()

        assert provider.closed
        assert manager.running_session_id is None
        assert (await manager.detail("session-1"))["status"] == "cancelled"
        rejected = await manager.retry("session-1")
        assert not rejected.accepted
        assert rejected.reason == "manager_closed"

    asyncio.run(scenario())
