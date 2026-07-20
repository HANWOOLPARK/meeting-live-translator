"""Bounded asynchronous translation scheduling, policy, and event delivery."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from math import ceil
from time import monotonic
from typing import Any

from .base import TranslationProvider
from .exceptions import (
    TranslationErrorCode,
    TranslationProviderError,
    normalize_provider_error,
    translation_error,
)
from .glossary import (
    DEFAULT_GLOSSARY_TERMS,
    TranslationGlossary,
    merge_glossary_terms,
    select_relevant_glossary_terms,
)
from .models import (
    ProviderHealth,
    TranslationRecord,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    TranslationSubmission,
    iso_now,
)
from .queue import TranslationQueue


LOGGER = logging.getLogger(__name__)
EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
SleepFunction = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class _TranslationJob:
    request: TranslationRequest
    provider: TranslationProvider
    submission_number: int
    timeout_seconds: float
    max_retries: int
    queued_at: float = field(default_factory=monotonic)
    started_at: float | None = None
    queue_wait_ms: int = 0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class TranslationManager:
    """Keep translation I/O outside audio and transcription execution paths."""

    def __init__(
        self,
        provider: TranslationProvider,
        *,
        queue_max_size: int = 100,
        max_concurrency: int = 2,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        context_segments: int = 3,
        translate_unknown: bool = False,
        glossary: TranslationGlossary | Iterable[str] | None = None,
        event_sink: EventSink | None = None,
        sleep_func: SleepFunction = asyncio.sleep,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0 or backoff_seconds < 0 or context_segments < 0:
            raise ValueError("retry/backoff/context values must not be negative")
        self.provider = provider
        self.queue: TranslationQueue[_TranslationJob] = TranslationQueue(queue_max_size)
        self.max_concurrency = int(max_concurrency)
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.backoff_seconds = float(backoff_seconds)
        self.context_segments = int(context_segments)
        self.translate_unknown = bool(translate_unknown)
        if isinstance(glossary, TranslationGlossary):
            self.glossary = glossary
        else:
            self.glossary = TranslationGlossary(
                merge_glossary_terms(DEFAULT_GLOSSARY_TERMS, glossary or ())
            )
        self.event_sink = event_sink
        self.sleep_func = sleep_func

        self._records: dict[str, TranslationRecord] = {}
        self._context: deque[tuple[str, str, tuple[str, ...]]] = deque(maxlen=20)
        self._glossary_candidate_terms = 0
        self._glossary_terms_sent = 0
        self._workers: list[asyncio.Task[None]] = []
        self._active_jobs: dict[str, _TranslationJob] = {}
        self._active_calls: dict[str, asyncio.Task[TranslationResult]] = {}
        self._pending_since: dict[str, float] = {}
        self._retired_providers: list[TranslationProvider] = []
        self._closed_provider_ids: set[int] = set()
        self._lock = asyncio.Lock()
        self._accepting = True
        self._closed = False
        self._latency_count = 0
        self._queue_wait_total_ms = 0
        self._queue_wait_last_ms = 0
        self._queue_wait_max_ms = 0
        self._provider_latency_total_ms = 0
        self._provider_latency_last_ms = 0
        self._provider_latency_max_ms = 0
        self._total_latency_total_ms = 0
        self._total_latency_last_ms = 0
        self._total_latency_max_ms = 0

    @property
    def running(self) -> bool:
        return bool(self._workers) and any(not worker.done() for worker in self._workers)

    async def start(self) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("translation manager is closed")
            if self.running:
                return
            self._workers = [
                asyncio.create_task(self._worker(index), name=f"translation-worker-{index}")
                for index in range(self.max_concurrency)
            ]
            prepare = getattr(self.provider, "start_prepare", None)
            if callable(prepare):
                prepare()

    async def provider_health(self) -> ProviderHealth:
        return await self.provider.health_check()

    def snapshot(self) -> dict[str, Any]:
        now = monotonic()
        oldest_wait_ms = 0
        if self._pending_since:
            # A queued item is operationally waiting even when the elapsed
            # interval is below the platform timer's millisecond resolution.
            oldest_wait_ms = max(
                1,
                ceil((now - min(self._pending_since.values())) * 1_000),
            )
        return {
            "provider": self.provider.provider_name,
            "running": self.running,
            "accepting": self._accepting and not self._closed,
            "queue_size": self.queue.size,
            "queue_max_size": self.queue.max_size,
            "active": len(self._active_jobs),
            "oldest_wait_ms": oldest_wait_ms,
            "tracked_segments": len(self._records),
            "max_concurrency": self.max_concurrency,
            "glossary_candidate_terms": self._glossary_candidate_terms,
            "glossary_terms_sent": self._glossary_terms_sent,
            "latency": {
                "completed": self._latency_count,
                "queue_wait_last_ms": self._queue_wait_last_ms,
                "queue_wait_average_ms": (
                    round(self._queue_wait_total_ms / self._latency_count)
                    if self._latency_count
                    else 0
                ),
                "queue_wait_max_ms": self._queue_wait_max_ms,
                "provider_last_ms": self._provider_latency_last_ms,
                "provider_average_ms": (
                    round(self._provider_latency_total_ms / self._latency_count)
                    if self._latency_count
                    else 0
                ),
                "provider_max_ms": self._provider_latency_max_ms,
                "total_last_ms": self._total_latency_last_ms,
                "total_average_ms": (
                    round(self._total_latency_total_ms / self._latency_count)
                    if self._latency_count
                    else 0
                ),
                "total_max_ms": self._total_latency_max_ms,
            },
        }

    def get_record(self, segment_id: str) -> TranslationRecord | None:
        record = self._records.get(segment_id)
        return replace(record) if record is not None else None

    def get_result(self, segment_id: str) -> TranslationResult | None:
        record = self._records.get(segment_id)
        return record.result if record is not None else None

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            outcome = self.event_sink(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as error:
            LOGGER.warning("Translation event sink failed: %s", type(error).__name__)

    @staticmethod
    def _submission(
        accepted: bool,
        segment_id: str | None,
        reason: str,
        queue_size: int,
    ) -> TranslationSubmission:
        return TranslationSubmission(accepted, segment_id, reason, queue_size)

    def _remember_context(
        self,
        request: TranslationRequest,
        glossary_terms: tuple[str, ...],
    ) -> None:
        if not any(segment_id == request.segment_id for segment_id, _, _ in self._context):
            self._context.append(
                (request.segment_id, request.source_text, glossary_terms)
            )

    def _enrich_request(
        self,
        request: TranslationRequest,
        *,
        context_segments: int,
    ) -> TranslationRequest:
        if context_segments <= 0:
            context: tuple[str, ...] = ()
        elif request.previous_context:
            context = request.previous_context[-context_segments:]
        else:
            context = tuple(text for _, text, _ in self._context)[-context_segments:]
        recent_records = (
            tuple(self._context)[-context_segments:]
            if context_segments > 0
            else ()
        )
        recent_glossary = tuple(
            term
            for _, _, terms in recent_records
            for term in terms
        )
        candidates = merge_glossary_terms(
            self.glossary.terms,
            recent_glossary,
            request.glossary_terms,
        )
        terms = select_relevant_glossary_terms(
            candidates,
            (request.source_text, *context),
        )
        self._glossary_candidate_terms += len(candidates)
        self._glossary_terms_sent += len(terms)
        enriched = request.with_context_and_glossary(context, terms)
        self._remember_context(request, terms)
        return enriched

    async def submit_event(
        self,
        event: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> TranslationSubmission:
        event_type = str(event.get("type", ""))
        segment_id = str(event.get("segment_id", "")).strip() or None
        if event_type != "final_transcript":
            return self._submission(False, segment_id, "not_final", self.queue.size)
        text = str(
            event.get("normalized_text")
            or event.get("text", event.get("source_text", ""))
        ).strip()
        if not text or segment_id is None:
            return self._submission(False, segment_id, "invalid_transcript", self.queue.size)
        quality = event.get("stt_quality")
        quality_fields = quality if isinstance(quality, Mapping) else {}
        boundary_reason = str(
            event.get("boundary_reason")
            or quality_fields.get("boundary_reason")
            or ""
        ).strip().lower()
        risk_reasons = {
            str(value).strip().lower()
            for value in (
                event.get("risk_reasons")
                or quality_fields.get("risk_reasons")
                or []
            )
            if str(value).strip()
        }
        explicit_incomplete = event.get("source_is_incomplete")
        source_is_incomplete = (
            bool(explicit_incomplete)
            if explicit_incomplete is not None
            else (
                bool(
                    {"short_fragment", "incomplete_ending"}.intersection(
                        risk_reasons
                    )
                )
                or (
                    boundary_reason in {"hard_limit", "candidate_timeout"}
                    and not text.rstrip().endswith((".", "?", "!", "。", "？", "！"))
                )
            )
        )
        try:
            request = TranslationRequest(
                segment_id=segment_id,
                session_id=(str(event["session_id"]) if event.get("session_id") else None),
                source_text=text,
                source_language=str(
                    event.get("language", event.get("source_language", "unknown"))
                ),
                target_language=str(event.get("target_language", "ko")),
                source=str(event.get("source", "system")),
                started_at=(str(event["started_at"]) if event.get("started_at") else None),
                ended_at=(str(event["ended_at"]) if event.get("ended_at") else None),
                boundary_reason=boundary_reason or None,
                source_is_incomplete=source_is_incomplete,
                glossary_terms=tuple(
                    str(value)
                    for value in event.get("glossary_terms", [])
                    if str(value).strip()
                ),
            )
        except ValueError:
            return self._submission(False, segment_id, "invalid_transcript", self.queue.size)
        return await self.submit(request, event_type=event_type, force=force)

    async def submit(
        self,
        request: TranslationRequest,
        *,
        event_type: str = "final_transcript",
        force: bool = False,
    ) -> TranslationSubmission:
        if event_type != "final_transcript":
            return self._submission(False, request.segment_id, "not_final", self.queue.size)
        await self.start()
        event: dict[str, Any] | None = None
        job: _TranslationJob | None = None
        async with self._lock:
            if not self._accepting or self._closed:
                return self._submission(
                    False, request.segment_id, "manager_closed", self.queue.size
                )
            existing = self._records.get(request.segment_id)
            if existing is not None and not force:
                return self._submission(
                    False, request.segment_id, "duplicate_segment", self.queue.size
                )
            if force and existing is not None and existing.status in {
                TranslationStatus.PENDING,
                TranslationStatus.TRANSLATING,
            }:
                return self._submission(
                    False, request.segment_id, "already_in_progress", self.queue.size
                )

            provider = self.provider
            context_segments = int(
                getattr(provider, "context_segments", self.context_segments)
            )
            timeout_seconds = float(
                getattr(provider, "timeout_seconds", self.timeout_seconds)
            )
            max_retries = int(getattr(provider, "max_retries", self.max_retries))
            enriched = self._enrich_request(
                request,
                context_segments=context_segments,
            )
            submission_number = (existing.submission_number + 1) if existing else 1

            if enriched.source_language == "unknown" and not self.translate_unknown:
                result = TranslationResult(
                    segment_id=enriched.segment_id,
                    session_id=enriched.session_id,
                    source_text=enriched.source_text,
                    translated_text=None,
                    source_language=enriched.source_language,
                    target_language=enriched.target_language,
                    provider=provider.provider_name,
                    model=getattr(provider, "model", None),
                    status=TranslationStatus.SKIPPED,
                    requested_at=enriched.requested_at,
                    completed_at=iso_now(),
                    latency_ms=0,
                )
                self._records[enriched.segment_id] = TranslationRecord(
                    request=enriched,
                    provider=provider.provider_name,
                    status=TranslationStatus.SKIPPED,
                    submission_number=submission_number,
                    result=result,
                )
                event = self._status_event(enriched, provider.provider_name, "skipped")
                reason = "unknown_language"
            elif provider.provider_name == "none":
                result = TranslationResult(
                    segment_id=enriched.segment_id,
                    session_id=enriched.session_id,
                    source_text=enriched.source_text,
                    translated_text=None,
                    source_language=enriched.source_language,
                    target_language=enriched.target_language,
                    provider="none",
                    model=None,
                    status=TranslationStatus.DISABLED,
                    requested_at=enriched.requested_at,
                    completed_at=iso_now(),
                    latency_ms=0,
                )
                self._records[enriched.segment_id] = TranslationRecord(
                    request=enriched,
                    provider="none",
                    status=TranslationStatus.DISABLED,
                    submission_number=submission_number,
                    result=result,
                )
                event = self._status_event(enriched, "none", "disabled")
                reason = "translation_disabled"
            else:
                if self.queue.full:
                    queue_error = translation_error(TranslationErrorCode.QUEUE_FULL)
                    failure = self._immediate_failure_result(enriched, provider, queue_error)
                    self._records[enriched.segment_id] = TranslationRecord(
                        request=enriched,
                        provider=provider.provider_name,
                        status=TranslationStatus.FAILED,
                        submission_number=submission_number,
                        result=existing.result if existing and existing.result else failure,
                        last_error=failure,
                    )
                    event = self._error_event(
                        enriched,
                        provider.provider_name,
                        queue_error,
                    )
                    reason = "queue_full"
                else:
                    record = TranslationRecord(
                        request=enriched,
                        provider=provider.provider_name,
                        status=TranslationStatus.PENDING,
                        submission_number=submission_number,
                        result=existing.result if existing else None,
                    )
                    job = _TranslationJob(
                        enriched,
                        provider,
                        submission_number,
                        timeout_seconds,
                        max_retries,
                    )
                    if not self.queue.put_nowait(job):
                        queue_error = translation_error(TranslationErrorCode.QUEUE_FULL)
                        failure = self._immediate_failure_result(enriched, provider, queue_error)
                        self._records[enriched.segment_id] = TranslationRecord(
                            request=enriched,
                            provider=provider.provider_name,
                            status=TranslationStatus.FAILED,
                            submission_number=submission_number,
                            result=existing.result if existing and existing.result else failure,
                            last_error=failure,
                        )
                        event = self._error_event(
                            enriched,
                            provider.provider_name,
                            queue_error,
                        )
                        reason = "queue_full"
                    else:
                        self._records[enriched.segment_id] = record
                        self._pending_since[enriched.segment_id] = job.queued_at
                        event = self._pending_event(
                            enriched,
                            provider.provider_name,
                            queue_size=self.queue.size,
                            queue_max_size=self.queue.max_size,
                        )
                        reason = "accepted"

        if event is not None:
            await self._emit(event)
        return self._submission(job is not None, request.segment_id, reason, self.queue.size)

    async def retry(self, segment_id: str) -> TranslationSubmission:
        record = self._records.get(segment_id)
        if record is None:
            return self._submission(False, segment_id, "segment_not_found", self.queue.size)
        return await self.submit(record.request.renewed(), force=True)

    @staticmethod
    def _immediate_failure_result(
        request: TranslationRequest,
        provider: TranslationProvider,
        error: TranslationProviderError,
    ) -> TranslationResult:
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=None,
            source_language=request.source_language,
            target_language=request.target_language,
            provider=provider.provider_name,
            model=getattr(provider, "model", None),
            status=TranslationStatus.FAILED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=0,
            error_code=error.code,
            error_message=error.safe_message,
        )

    async def _worker(self, index: int) -> None:
        del index
        while True:
            job = await self.queue.get()
            job.started_at = monotonic()
            job.queue_wait_ms = max(
                0,
                round((job.started_at - job.queued_at) * 1_000),
            )
            self._pending_since.pop(job.request.segment_id, None)
            self._active_jobs[job.request.segment_id] = job
            try:
                await self._process_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOGGER.error("Translation worker error: %s", type(error).__name__)
                await self._finish_error(job, normalize_provider_error(error))
            finally:
                self._active_jobs.pop(job.request.segment_id, None)
                self.queue.task_done()

    async def _process_job(self, job: _TranslationJob) -> None:
        last_error: TranslationProviderError | None = None
        for attempt_index in range(job.max_retries + 1):
            if job.cancel_event.is_set():
                await self._finish_error(
                    job,
                    translation_error(TranslationErrorCode.CANCELLED),
                    cancelled=True,
                )
                return
            record = self._records.get(job.request.segment_id)
            if record is not None and record.submission_number == job.submission_number:
                record.status = TranslationStatus.TRANSLATING
                record.attempts = attempt_index + 1
            await self._emit(
                self._status_event(
                    job.request,
                    job.provider.provider_name,
                    "translating",
                    attempt=attempt_index + 1,
                )
            )
            call = asyncio.create_task(job.provider.translate(job.request))
            self._active_calls[job.request.segment_id] = call
            try:
                result = await asyncio.wait_for(call, timeout=job.timeout_seconds)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                if job.cancel_event.is_set():
                    await self._finish_error(
                        job,
                        translation_error(TranslationErrorCode.CANCELLED),
                        cancelled=True,
                    )
                    return
                raise
            except Exception as error:
                last_error = normalize_provider_error(error)
            else:
                if (
                    result.segment_id != job.request.segment_id
                    or result.status is not TranslationStatus.COMPLETED
                    or not (result.translated_text or "").strip()
                ):
                    last_error = translation_error(TranslationErrorCode.INVALID_RESPONSE)
                else:
                    await self._finish_success(job, result)
                    return
            finally:
                self._active_calls.pop(job.request.segment_id, None)
                if not call.done():
                    call.cancel()
                    await asyncio.gather(call, return_exceptions=True)

            assert last_error is not None
            if not last_error.retryable or attempt_index >= job.max_retries:
                break
            if not await self._backoff_or_cancel(
                job,
                self.backoff_seconds * (2**attempt_index),
            ):
                await self._finish_error(
                    job,
                    translation_error(TranslationErrorCode.CANCELLED),
                    cancelled=True,
                )
                return
        await self._finish_error(
            job,
            last_error or translation_error(TranslationErrorCode.UNKNOWN_PROVIDER_ERROR),
        )

    async def _backoff_or_cancel(self, job: _TranslationJob, delay: float) -> bool:
        if delay <= 0:
            return not job.cancel_event.is_set()
        sleep_task = asyncio.create_task(self.sleep_func(delay))
        cancel_task = asyncio.create_task(job.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {sleep_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            return sleep_task in done and not job.cancel_event.is_set()
        finally:
            for task in (sleep_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleep_task, cancel_task, return_exceptions=True)

    async def _finish_success(self, job: _TranslationJob, result: TranslationResult) -> None:
        record = self._records.get(job.request.segment_id)
        if record is None or record.submission_number != job.submission_number:
            return
        if record.status in {TranslationStatus.COMPLETED, TranslationStatus.CANCELLED}:
            return
        record.status = TranslationStatus.COMPLETED
        record.result = result
        record.last_error = None
        total_latency_ms = max(0, round((monotonic() - job.queued_at) * 1_000))
        self._record_latency(
            queue_wait_ms=job.queue_wait_ms,
            provider_latency_ms=result.latency_ms,
            total_latency_ms=total_latency_ms,
        )
        await self._emit(
            {
                "type": "translation",
                "segment_id": result.segment_id,
                "session_id": result.session_id,
                "source_text": result.source_text,
                "translated_text": result.translated_text,
                "source_language": result.source_language,
                "target_language": result.target_language,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "queue_wait_ms": job.queue_wait_ms,
                "provider_latency_ms": result.latency_ms,
                "total_latency_ms": total_latency_ms,
                "timestamp": result.completed_at,
            }
        )

    def _record_latency(
        self,
        *,
        queue_wait_ms: int,
        provider_latency_ms: int,
        total_latency_ms: int,
    ) -> None:
        self._latency_count += 1
        self._queue_wait_last_ms = queue_wait_ms
        self._queue_wait_total_ms += queue_wait_ms
        self._queue_wait_max_ms = max(self._queue_wait_max_ms, queue_wait_ms)
        self._provider_latency_last_ms = provider_latency_ms
        self._provider_latency_total_ms += provider_latency_ms
        self._provider_latency_max_ms = max(
            self._provider_latency_max_ms,
            provider_latency_ms,
        )
        self._total_latency_last_ms = total_latency_ms
        self._total_latency_total_ms += total_latency_ms
        self._total_latency_max_ms = max(
            self._total_latency_max_ms,
            total_latency_ms,
        )

    def _reset_latency_metrics(self) -> None:
        self._latency_count = 0
        self._queue_wait_total_ms = 0
        self._queue_wait_last_ms = 0
        self._queue_wait_max_ms = 0
        self._provider_latency_total_ms = 0
        self._provider_latency_last_ms = 0
        self._provider_latency_max_ms = 0
        self._total_latency_total_ms = 0
        self._total_latency_last_ms = 0
        self._total_latency_max_ms = 0

    def _failure_result(
        self,
        job: _TranslationJob,
        error: TranslationProviderError,
        *,
        cancelled: bool,
    ) -> TranslationResult:
        return TranslationResult(
            segment_id=job.request.segment_id,
            session_id=job.request.session_id,
            source_text=job.request.source_text,
            translated_text=None,
            source_language=job.request.source_language,
            target_language=job.request.target_language,
            provider=job.provider.provider_name,
            model=getattr(job.provider, "model", None),
            status=TranslationStatus.CANCELLED if cancelled else TranslationStatus.FAILED,
            requested_at=job.request.requested_at,
            completed_at=iso_now(),
            latency_ms=max(0, round((monotonic() - job.queued_at) * 1_000)),
            error_code=error.code,
            error_message=error.safe_message,
        )

    async def _finish_error(
        self,
        job: _TranslationJob,
        error: TranslationProviderError,
        *,
        cancelled: bool = False,
    ) -> None:
        record = self._records.get(job.request.segment_id)
        if record is None or record.submission_number != job.submission_number:
            return
        if record.status is TranslationStatus.COMPLETED:
            return
        if (
            record.status in {TranslationStatus.FAILED, TranslationStatus.CANCELLED}
            and record.last_error is not None
            and record.last_error.error_code is error.code
        ):
            return
        failure = self._failure_result(job, error, cancelled=cancelled)
        record.status = failure.status
        record.last_error = failure
        if record.result is None or record.result.status is not TranslationStatus.COMPLETED:
            record.result = failure
        await self._emit(self._error_event(job.request, job.provider.provider_name, error))

    @staticmethod
    def _pending_event(
        request: TranslationRequest,
        provider: str,
        *,
        queue_size: int,
        queue_max_size: int,
    ) -> dict[str, Any]:
        return {
            "type": "translation_pending",
            "segment_id": request.segment_id,
            "session_id": request.session_id,
            "provider": provider,
            "queue_size": queue_size,
            "queue_max_size": queue_max_size,
            "timestamp": iso_now(),
        }

    @staticmethod
    def _status_event(
        request: TranslationRequest,
        provider: str,
        status: str,
        **fields: Any,
    ) -> dict[str, Any]:
        return {
            "type": "translation_status",
            "segment_id": request.segment_id,
            "session_id": request.session_id,
            "status": status,
            "provider": provider,
            "timestamp": iso_now(),
            **fields,
        }

    @staticmethod
    def _error_event(
        request: TranslationRequest,
        provider: str,
        error: TranslationProviderError,
    ) -> dict[str, Any]:
        return {
            "type": "translation_error",
            "segment_id": request.segment_id,
            "session_id": request.session_id,
            "provider": provider,
            "code": error.code.value,
            "message": error.safe_message,
            "recoverable": error.recoverable,
            "timestamp": iso_now(),
        }

    async def cancel(self, segment_id: str) -> bool:
        removed = self.queue.remove(lambda job: job.request.segment_id == segment_id)
        active = self._active_jobs.get(segment_id)
        if active is not None:
            active.cancel_event.set()
            call = self._active_calls.get(segment_id)
            if call is not None:
                call.cancel()
        for job in removed:
            self._pending_since.pop(job.request.segment_id, None)
            job.cancel_event.set()
            await self._finish_error(
                job,
                translation_error(TranslationErrorCode.CANCELLED),
                cancelled=True,
            )
        return bool(removed or active)

    async def switch_provider(
        self,
        provider: TranslationProvider,
        *,
        cancel_pending: bool = True,
        require_available: bool = True,
    ) -> ProviderHealth:
        health = await provider.health_check()
        if require_available and not health.available:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        old = self.provider
        if old is provider:
            return health
        self.provider = provider
        self._reset_latency_metrics()
        prepare = getattr(provider, "start_prepare", None)
        if callable(prepare):
            prepare()
        if cancel_pending:
            removed = self.queue.remove(lambda job: job.provider is old)
            active = [job for job in self._active_jobs.values() if job.provider is old]
            active_calls: list[asyncio.Task[TranslationResult]] = []
            for job in active:
                job.cancel_event.set()
                call = self._active_calls.get(job.request.segment_id)
                if call is not None:
                    call.cancel()
                    active_calls.append(call)
                await self._finish_error(
                    job,
                    translation_error(TranslationErrorCode.CANCELLED),
                    cancelled=True,
                )
            if active_calls:
                await asyncio.gather(*active_calls, return_exceptions=True)
            for job in removed:
                self._pending_since.pop(job.request.segment_id, None)
                job.cancel_event.set()
                await self._finish_error(
                    job,
                    translation_error(TranslationErrorCode.CANCELLED),
                    cancelled=True,
                )
            await self._close_provider(old)
        else:
            self._retired_providers.append(old)
        await self._emit(
            {
                "type": "translation_provider_status",
                "provider": provider.provider_name,
                "available": health.available,
                "external": health.external,
                "timestamp": iso_now(),
            }
        )
        return health

    async def wait_idle(self, timeout_seconds: float | None = None) -> None:
        if timeout_seconds is None:
            await self.queue.join()
        else:
            await asyncio.wait_for(self.queue.join(), timeout=timeout_seconds)

    async def _close_provider(self, provider: TranslationProvider) -> None:
        identity = id(provider)
        if identity in self._closed_provider_ids:
            return
        self._closed_provider_ids.add(identity)
        try:
            await provider.close()
        except Exception as error:
            LOGGER.warning("Translation provider close failed: %s", type(error).__name__)

    async def shutdown(
        self,
        *,
        graceful: bool = True,
        timeout_seconds: float = 5.0,
    ) -> None:
        if self._closed:
            return
        self._accepting = False
        if graceful and self.running:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=max(0.0, timeout_seconds))
            except asyncio.TimeoutError:
                pass
        removed = self.queue.drain()
        for job in removed:
            self._pending_since.pop(job.request.segment_id, None)
        active = list(self._active_jobs.values())
        for job in active:
            job.cancel_event.set()
        for call in list(self._active_calls.values()):
            call.cancel()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for job in removed + active:
            await self._finish_error(
                job,
                translation_error(TranslationErrorCode.CANCELLED),
                cancelled=True,
            )
        providers = [self.provider, *self._retired_providers]
        self._retired_providers.clear()
        for provider in providers:
            await self._close_provider(provider)
        self._closed = True

    close = shutdown


__all__ = ["TranslationManager"]
