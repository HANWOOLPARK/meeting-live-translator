from __future__ import annotations

import asyncio

import pytest

from backend.app.translation import (
    ProviderHealth,
    TranslationErrorCode,
    TranslationManager,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
    translation_error,
)


class FakeProvider(TranslationProvider):
    provider_name = "fake"
    display_name = "Fake"
    external = False

    def __init__(self, behavior=None, *, available=True, name="fake"):
        self.provider_name = name
        self.behavior = behavior
        self.available = available
        self.calls = []
        self.closed = False

    async def translate(self, request):
        self.calls.append(request)
        if self.behavior is not None:
            value = self.behavior(request, len(self.calls))
            if asyncio.iscoroutine(value):
                value = await value
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, TranslationResult):
                return value
            translated = value
        else:
            translated = f"KO:{request.source_text}"
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=translated,
            source_language=request.source_language,
            target_language="ko",
            provider=self.provider_name,
            model="fake-model",
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=1,
        )

    async def health_check(self):
        return ProviderHealth(self.provider_name, self.display_name, self.available, False)

    async def close(self):
        self.closed = True


def final_event(segment_id="s1", language="en", text="Test sentence"):
    return {
        "type": "final_transcript",
        "segment_id": segment_id,
        "session_id": "session-1",
        "text": text,
        "language": language,
        "source": "system",
    }


def test_manager_final_only_duplicate_language_policy_and_events():
    async def scenario():
        events = []
        provider = FakeProvider()
        manager = TranslationManager(provider, event_sink=events.append)

        partial = dict(final_event(), type="partial_transcript")
        assert not await manager.submit_event(partial)
        assert (await manager.submit_event(final_event("unknown", "unknown"))).reason == "unknown_language"
        assert await manager.submit_event(final_event("mixed", "mixed", "今日は System Test"))
        assert not await manager.submit_event(final_event("mixed", "mixed", "duplicate"))
        await manager.wait_idle(1)

        assert [call.segment_id for call in provider.calls] == ["mixed"]
        assert manager.get_result("mixed").translated_text.startswith("KO:")
        types = [event["type"] for event in events]
        assert "translation_pending" in types
        assert "translation_status" in types
        assert "translation" in types
        translation = next(event for event in events if event["type"] == "translation")
        assert translation["segment_id"] == "mixed"
        assert translation["session_id"] == "session-1"
        assert translation["queue_wait_ms"] >= 0
        assert translation["provider_latency_ms"] == translation["latency_ms"]
        assert translation["total_latency_ms"] >= 0
        latency = manager.snapshot()["latency"]
        assert latency["completed"] == 1
        assert latency["provider_last_ms"] == 1
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_sends_only_glossary_terms_relevant_to_current_and_recent_context():
    async def scenario():
        provider = FakeProvider()
        manager = TranslationManager(provider, context_segments=1)

        first = final_event("term-1", text="MK119 connects to the service")
        first["glossary_terms"] = ["MK119", "Unused Custom Term"]
        assert await manager.submit_event(first)
        await manager.wait_idle(1)

        second = final_event("term-2", text="Please verify that connection")
        second["glossary_terms"] = ["Another Unused Term"]
        assert await manager.submit_event(second)
        await manager.wait_idle(1)

        third = final_event("term-3", text="This sentence has no registered terminology")
        third["glossary_terms"] = ["Still Unused"]
        assert await manager.submit_event(third)
        await manager.wait_idle(1)

        assert provider.calls[0].glossary_terms == ("MK119",)
        assert provider.calls[1].glossary_terms == ("MK119",)
        assert provider.calls[2].glossary_terms == ()
        snapshot = manager.snapshot()
        assert snapshot["glossary_candidate_terms"] > snapshot["glossary_terms_sent"]
        assert snapshot["glossary_terms_sent"] == 2
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_marks_forced_unpunctuated_final_as_incomplete() -> None:
    async def scenario():
        provider = FakeProvider()
        manager = TranslationManager(provider)
        event = final_event("forced", language="ja", text="イベントを行う")
        event["stt_quality"] = {
            "boundary_reason": "hard_limit",
            "risk_reasons": ["forced_boundary"],
        }
        assert await manager.submit_event(event)
        await manager.wait_idle(1)
        assert provider.calls[0].boundary_reason == "hard_limit"
        assert provider.calls[0].source_is_incomplete is True

        complete = final_event("forced-complete", language="ja", text="終了しました。")
        complete["stt_quality"] = {
            "boundary_reason": "hard_limit",
            "risk_reasons": ["forced_boundary"],
        }
        assert await manager.submit_event(complete)
        await manager.wait_idle(1)
        assert provider.calls[1].source_is_incomplete is False
        await manager.shutdown()

    asyncio.run(scenario())


def test_completion_order_does_not_break_segment_matching():
    gates = {"slow": asyncio.Event(), "fast": asyncio.Event()}

    async def behavior(request, call_number):
        del call_number
        await gates[request.segment_id].wait()
        return f"translated-{request.segment_id}"

    async def scenario():
        events = []
        manager = TranslationManager(FakeProvider(behavior), max_concurrency=2, event_sink=events.append)
        await manager.submit_event(final_event("slow"))
        await manager.submit_event(final_event("fast"))
        await asyncio.sleep(0)
        gates["fast"].set()
        await asyncio.sleep(0.01)
        gates["slow"].set()
        await manager.wait_idle(1)
        translated = [event for event in events if event["type"] == "translation"]
        assert [event["segment_id"] for event in translated] == ["fast", "slow"]
        assert all(event["translated_text"] == f"translated-{event['segment_id']}" for event in translated)
        await manager.shutdown()

    asyncio.run(scenario())


def test_bounded_queue_reports_safe_error_without_blocking_submitter():
    active = asyncio.Event()
    release = asyncio.Event()

    async def behavior(request, call_number):
        del request, call_number
        active.set()
        await release.wait()
        return "done"

    async def scenario():
        events = []
        manager = TranslationManager(
            FakeProvider(behavior),
            queue_max_size=1,
            max_concurrency=1,
            event_sink=events.append,
        )
        assert await manager.submit_event(final_event("one"))
        await asyncio.wait_for(active.wait(), 1)
        assert await manager.submit_event(final_event("two"))
        third = await manager.submit_event(final_event("three"))
        assert not third and third.reason == "queue_full"
        error = next(event for event in events if event.get("segment_id") == "three")
        assert error["type"] == "translation_error"
        assert error["code"] == "QUEUE_FULL"
        assert "Test sentence" not in str(error)
        release.set()
        await manager.wait_idle(1)
        assert await manager.retry("three")
        await manager.wait_idle(1)
        assert manager.get_result("three").status is TranslationStatus.COMPLETED
        await manager.shutdown()

    asyncio.run(scenario())


def test_queue_snapshot_reports_depth_and_oldest_wait_without_exposing_text():
    active = asyncio.Event()
    release = asyncio.Event()

    async def behavior(request, call_number):
        del request, call_number
        active.set()
        await release.wait()
        return "done"

    async def scenario():
        events = []
        manager = TranslationManager(
            FakeProvider(behavior),
            queue_max_size=3,
            max_concurrency=1,
            event_sink=events.append,
        )
        assert await manager.submit_event(final_event("active", text="private active"))
        await asyncio.wait_for(active.wait(), 1)
        assert await manager.submit_event(final_event("waiting", text="private waiting"))
        await asyncio.sleep(0.01)

        snapshot = manager.snapshot()
        assert snapshot["queue_size"] == 1
        assert snapshot["queue_max_size"] == 3
        assert snapshot["oldest_wait_ms"] > 0
        pending = next(
            event
            for event in events
            if event["type"] == "translation_pending"
            and event["segment_id"] == "waiting"
        )
        assert pending["queue_size"] == 1
        assert pending["queue_max_size"] == 3
        assert "private waiting" not in str(snapshot) + str(pending)

        release.set()
        await manager.wait_idle(1)
        assert manager.snapshot()["oldest_wait_ms"] == 0
        await manager.shutdown()

    asyncio.run(scenario())


def test_retry_backoff_is_bounded_and_worker_continues_after_error():
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    def behavior(request, call_number):
        if request.segment_id == "retry" and call_number < 3:
            return translation_error(TranslationErrorCode.RATE_LIMITED)
        if request.segment_id == "fatal":
            return translation_error(TranslationErrorCode.AUTHENTICATION_FAILED)
        return "recovered"

    async def scenario():
        events = []
        provider = FakeProvider(behavior)
        manager = TranslationManager(
            provider,
            max_retries=2,
            backoff_seconds=0.1,
            sleep_func=fake_sleep,
            event_sink=events.append,
        )
        await manager.submit_event(final_event("retry"))
        await manager.wait_idle(1)
        assert manager.get_result("retry").status is TranslationStatus.COMPLETED
        assert sleeps == [0.1, 0.2]

        await manager.submit_event(final_event("fatal"))
        await manager.submit_event(final_event("after"))
        await manager.wait_idle(1)
        assert manager.get_record("fatal").attempts == 1
        assert manager.get_result("after").status is TranslationStatus.COMPLETED
        assert any(event.get("code") == "AUTHENTICATION_FAILED" for event in events)
        await manager.shutdown()

    asyncio.run(scenario())


def test_timeout_attempts_are_limited_and_explicit_retry_is_allowed():
    release = asyncio.Event()

    async def slow(request, call_number):
        del request, call_number
        await release.wait()
        return "late"

    async def scenario():
        events = []
        provider = FakeProvider(slow)
        manager = TranslationManager(
            provider,
            timeout_seconds=0.01,
            max_retries=1,
            backoff_seconds=0,
            event_sink=events.append,
        )
        await manager.submit_event(final_event("timeout"))
        await manager.wait_idle(1)
        assert len(provider.calls) == 2
        assert manager.get_result("timeout").error_code is TranslationErrorCode.REQUEST_TIMEOUT

        provider.behavior = lambda request, call_number: "manual retry success"
        assert await manager.retry("timeout")
        await manager.wait_idle(1)
        assert manager.get_result("timeout").translated_text == "manual retry success"
        assert any(event.get("code") == "REQUEST_TIMEOUT" for event in events)
        await manager.shutdown()

    asyncio.run(scenario())


def test_provider_switch_rejects_unavailable_and_cancels_old_work():
    started = asyncio.Event()
    never = asyncio.Event()

    async def blocking(request, call_number):
        del request, call_number
        started.set()
        await never.wait()
        return "old"

    async def scenario():
        events = []
        old = FakeProvider(blocking, name="old")
        manager = TranslationManager(old, event_sink=events.append)
        await manager.submit_event(final_event("old-segment"))
        await asyncio.wait_for(started.wait(), 1)

        unavailable = FakeProvider(available=False, name="unavailable")
        with pytest.raises(TranslationProviderError):
            await manager.switch_provider(unavailable)
        assert manager.provider is old

        new = FakeProvider(name="new")
        health = await manager.switch_provider(new, cancel_pending=True)
        assert health.available and manager.provider is new
        await asyncio.sleep(0)
        assert old.closed
        assert manager.get_record("old-segment").status is TranslationStatus.CANCELLED
        assert await manager.submit_event(final_event("new-segment"))
        await manager.wait_idle(1)
        assert manager.get_result("new-segment").provider == "new"
        await manager.shutdown()
        assert new.closed

    asyncio.run(scenario())


def test_shutdown_cancels_inflight_call_and_closes_provider_safely():
    started = asyncio.Event()
    never = asyncio.Event()

    async def blocking(request, call_number):
        del request, call_number
        started.set()
        await never.wait()

    async def scenario():
        provider = FakeProvider(blocking)
        manager = TranslationManager(provider)
        await manager.submit_event(final_event("active"))
        await asyncio.wait_for(started.wait(), 1)
        await manager.shutdown(graceful=False)
        assert provider.closed
        assert not manager.running
        assert manager.get_record("active").status is TranslationStatus.CANCELLED

    asyncio.run(scenario())
