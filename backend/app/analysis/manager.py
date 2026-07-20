"""Explicit-run, single-concurrency Phase 3B analysis orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from .base import AnalysisProvider
from .chunking import chunk_request, merge_analyses
from .exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    analysis_error,
    normalize_analysis_error,
)
from .models import (
    ANALYSIS_SCHEMA_VERSION,
    AnalysisProviderHealth,
    AnalysisRecord,
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    AnalysisSubmission,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
    iso_now,
)
from .none_provider import NoneAnalysisProvider
from .structured import AnalysisResponsePayload
from .validation import validate_evidence


LOGGER = logging.getLogger(__name__)
ProviderFactory = Callable[[], AnalysisProvider]
EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
SleepFunction = Callable[[float], Awaitable[None]]


class AnalysisManager:
    """Run analysis only after an explicit ``submit``/``retry`` call.

    Construction, provider listing, session listing, and ``get`` never invoke
    a Provider's ``analyze`` method. Only one session analysis runs at a time.
    """

    def __init__(
        self,
        repository: Any,
        provider: AnalysisProvider | None = None,
        *,
        provider_factories: Mapping[str, ProviderFactory] | None = None,
        selected_provider: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        backoff_seconds: float = 0.5,
        max_segments_per_chunk: int = 100,
        max_characters_per_chunk: int = 24_000,
        max_concurrency: int = 1,
        event_sink: EventSink | None = None,
        sleep_func: SleepFunction = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0 or backoff_seconds < 0:
            raise ValueError("retry values must not be negative")
        if max_segments_per_chunk <= 0 or max_characters_per_chunk <= 0:
            raise ValueError("chunk limits must be positive")
        if max_concurrency != 1:
            raise ValueError("Phase 3 analysis concurrency must be 1")
        self.repository = repository
        self.provider_factories = dict(provider_factories or {})
        if provider is None:
            provider_name = selected_provider or "none"
            factory = self.provider_factories.get(provider_name)
            provider = factory() if factory is not None else NoneAnalysisProvider()
        self.provider = provider
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.backoff_seconds = float(backoff_seconds)
        self.max_segments_per_chunk = int(max_segments_per_chunk)
        self.max_characters_per_chunk = int(max_characters_per_chunk)
        self.max_concurrency = 1
        self.event_sink = event_sink
        self.sleep_func = sleep_func

        self._records: dict[str, AnalysisRecord] = {}
        self._tasks: dict[str, asyncio.Task[MeetingAnalysis]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def running_session_id(self) -> str | None:
        for session_id, task in self._tasks.items():
            if not task.done():
                return session_id
        return None

    def snapshot(self) -> dict[str, Any]:
        running = self.running_session_id
        return {
            "provider": self.provider.provider_name,
            "running": running is not None,
            "running_session_id": running,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_concurrency": self.max_concurrency,
            "max_segments_per_chunk": self.max_segments_per_chunk,
            "max_characters_per_chunk": self.max_characters_per_chunk,
            "auto_run_on_stop": False,
        }

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            outcome = self.event_sink(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as error:
            LOGGER.warning("Analysis event sink failed: %s", type(error).__name__)

    async def _repository_call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        function = getattr(self.repository, name, None)
        if function is None:
            return None
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        return await asyncio.to_thread(function, *args, **kwargs)

    async def providers(self) -> list[dict[str, Any]]:
        names = set(self.provider_factories)
        names.add(self.provider.provider_name)
        payloads: list[dict[str, Any]] = []
        for name in sorted(names, key=lambda value: (value != "none", value)):
            if name == self.provider.provider_name:
                candidate = self.provider
                should_close = False
            else:
                factory = self.provider_factories.get(name)
                if factory is None:
                    continue
                candidate = factory()
                should_close = True
            try:
                health = await candidate.health_check()
                payloads.append(health.to_dict())
            finally:
                if should_close:
                    await candidate.close()
        return payloads

    async def public_settings(self) -> dict[str, Any]:
        health = await self.provider.health_check()
        return {
            **self.snapshot(),
            "provider_available": health.available,
            "provider_external": health.external,
            "provider_reason": health.reason,
            "provider_model": health.model,
            "openai_api_key_configured": bool(
                getattr(self.provider, "api_key_configured", False)
            ),
        }

    async def configure(self, provider_name: str) -> dict[str, Any]:
        await self.switch_provider(provider_name)
        return await self.public_settings()

    async def switch_provider(
        self,
        provider: AnalysisProvider | str,
        *,
        cancel_active: bool = True,
        require_available: bool = True,
    ) -> AnalysisProviderHealth:
        if isinstance(provider, str):
            factory = self.provider_factories.get(provider)
            if factory is None:
                raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
            candidate = factory()
        else:
            candidate = provider
        health = await candidate.health_check()
        if require_available and not health.available:
            if candidate is not self.provider:
                await candidate.close()
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        if candidate is self.provider:
            return health
        if self.running_session_id is not None:
            if not cancel_active:
                if candidate is not self.provider:
                    await candidate.close()
                raise analysis_error(AnalysisErrorCode.ALREADY_RUNNING)
            await self.cancel(self.running_session_id)
        old, self.provider = self.provider, candidate
        await old.close()
        await self._emit(
            {
                "type": "analysis_status",
                "status": "provider_changed",
                "provider": candidate.provider_name,
                "timestamp": iso_now(),
            }
        )
        return health

    async def _request_from_repository(self, session_id: str) -> AnalysisRequest:
        session = await self._repository_call("get_session", session_id)
        if not isinstance(session, Mapping):
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        segments: list[AnalysisSegment] = []
        raw_segments = session.get("segments", ())
        if not isinstance(raw_segments, (list, tuple)):
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE)
        for raw in raw_segments:
            if not isinstance(raw, Mapping):
                continue
            original = raw.get("original_text")
            normalized = raw.get("normalized_text")
            korean = raw.get("korean_translation")
            if not str(original or "").strip() and not str(korean or "").strip():
                continue
            try:
                segments.append(
                    AnalysisSegment(
                        segment_id=str(raw.get("segment_id", "")),
                        original_text=(str(original) if original is not None else None),
                        korean_translation=(str(korean) if korean is not None else None),
                        normalized_text=(
                            str(normalized) if normalized is not None else None
                        ),
                        language=str(raw.get("language", "unknown")),
                        source=str(raw.get("source", "system")),
                        started_at=(
                            str(raw["started_at"]) if raw.get("started_at") else None
                        ),
                        ended_at=(str(raw["ended_at"]) if raw.get("ended_at") else None),
                    )
                )
            except ValueError:
                continue
        return AnalysisRequest(session_id=session_id, segments=tuple(segments))

    @staticmethod
    def _from_saved(payload: Mapping[str, Any]) -> MeetingAnalysis:
        required_metadata = {
            "schema_version",
            "session_id",
            "provider",
            "model",
            "status",
            "generated_at",
            "revision",
        }
        if required_metadata.difference(payload):
            raise ValueError("saved analysis is missing required metadata")
        if type(payload.get("schema_version")) is not int or (
            payload["schema_version"] != ANALYSIS_SCHEMA_VERSION
        ):
            raise ValueError("unsupported saved analysis schema_version")
        if str(payload.get("status")) != AnalysisStatus.COMPLETED.value:
            raise ValueError("saved analysis must be completed")
        if type(payload.get("revision")) is not int:
            raise ValueError("saved analysis revision must be an integer")
        if (
            type(payload.get("session_id")) is not str
            or not payload["session_id"].strip()
        ):
            raise ValueError("saved analysis session_id must be a non-empty string")
        if type(payload.get("provider")) is not str or not payload["provider"].strip():
            raise ValueError("saved analysis provider must be a non-empty string")
        if payload.get("model") is not None and type(payload["model"]) is not str:
            raise ValueError("saved analysis model must be a string or null")
        generated_at = payload.get("generated_at")
        if type(generated_at) is not str or not generated_at.strip():
            raise ValueError("saved analysis generated_at must be a non-empty string")
        try:
            parsed_generated_at = datetime.fromisoformat(generated_at)
        except ValueError as error:
            raise ValueError("saved analysis generated_at must be ISO 8601") from error
        if parsed_generated_at.utcoffset() is None:
            raise ValueError("saved analysis generated_at must include a timezone")
        semantic_keys = {
            "meeting_purpose",
            "key_discussions",
            "decisions",
            "action_items",
            "open_questions",
            "next_meeting_checks",
            "warnings",
        }
        semantic = {key: payload[key] for key in semantic_keys if key in payload}
        semantic = AnalysisResponsePayload.model_validate(semantic).model_dump()
        return MeetingAnalysis.from_payload(
            semantic,
            session_id=str(payload.get("session_id", "")),
            provider=str(payload.get("provider", "none")),
            model=(str(payload["model"]) if payload.get("model") else None),
            status=AnalysisStatus(str(payload.get("status", "completed"))),
            generated_at=generated_at,
            revision=int(payload.get("revision", 1)),
        )

    async def get(self, session_id: str) -> MeetingAnalysis | None:
        record = self._records.get(session_id)
        if record is not None and record.result is not None:
            return record.result
        payload = await self._repository_call("load_analysis", session_id)
        if isinstance(payload, Mapping):
            try:
                result = self._from_saved(payload)
                validate_evidence(result, (await self._request_from_repository(session_id)).segment_ids)
                return result
            except (ValueError, AnalysisProviderError):
                return None
        return None

    async def detail(self, session_id: str) -> dict[str, Any]:
        """Return the current run state together with any prior successful result.

        Repository status is authoritative after a process restart, while the
        in-memory record is authoritative for a run owned by this manager.
        A failed, cancelled, pending, or running re-analysis intentionally keeps
        the last completed result available to callers.
        """

        record = self._records.get(session_id)
        session: Mapping[str, Any] | None = None
        if record is None:
            repository_session = await self._repository_call("get_session", session_id)
            if isinstance(repository_session, Mapping):
                session = repository_session

        result = record.result if record is not None else await self.get(session_id)
        if record is not None:
            status = record.status
            provider = record.provider
            model = record.model
            revision = record.revision
            error_code = record.last_error_code
        else:
            metadata_value = session.get("metadata", {}) if session is not None else {}
            metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
            try:
                status = AnalysisStatus(
                    str(
                        metadata.get(
                            "analysis_status",
                            result.status.value if result is not None else "not_started",
                        )
                    )
                )
            except ValueError:
                status = result.status if result is not None else AnalysisStatus.NOT_STARTED
            provider = str(
                metadata.get(
                    "analysis_provider",
                    result.provider if result is not None else self.provider.provider_name,
                )
            )
            revision = int(
                metadata.get(
                    "analysis_revision",
                    result.revision if result is not None else 0,
                )
                or 0
            )
            error_code = None
            model = result.model if result is not None else None

        if model is None and provider == self.provider.provider_name:
            model = getattr(self.provider, "model", None) or None
        generated_at = result.generated_at if result is not None else None
        has_previous = result is not None and status is not AnalysisStatus.COMPLETED
        return {
            "session_id": session_id,
            "status": status.value,
            "provider": provider,
            "model": model,
            "generated_at": generated_at,
            "revision": revision,
            "error_code": error_code,
            "has_previous_result": has_previous,
            "result": result.to_dict() if result is not None else None,
        }

    async def submit(
        self,
        session_id: str,
        *,
        force: bool = False,
    ) -> AnalysisSubmission:
        if self._closed:
            return AnalysisSubmission(False, session_id, "manager_closed", AnalysisStatus.FAILED)
        async with self._lock:
            running = self.running_session_id
            if running is not None:
                reason = "already_running" if running == session_id else "another_session_running"
                return AnalysisSubmission(False, session_id, reason, AnalysisStatus.RUNNING)

        request = await self._request_from_repository(session_id)
        loaded_previous = self._records.get(session_id)
        if loaded_previous is None:
            persisted = await self.get(session_id)
            if persisted is not None:
                loaded_previous = AnalysisRecord(
                    request=request,
                    provider=persisted.provider,
                    model=persisted.model,
                    status=persisted.status,
                    revision=persisted.revision,
                    result=persisted,
                )

        # Repository loading above must not hold the manager lock. Re-check and
        # register atomically here so simultaneous submit calls cannot both pass.
        async with self._lock:
            if self._closed:
                return AnalysisSubmission(
                    False,
                    session_id,
                    "manager_closed",
                    AnalysisStatus.FAILED,
                )
            running = self.running_session_id
            if running is not None:
                reason = (
                    "already_running"
                    if running == session_id
                    else "another_session_running"
                )
                return AnalysisSubmission(
                    False,
                    session_id,
                    reason,
                    AnalysisStatus.RUNNING,
                )
            previous = self._records.get(session_id) or loaded_previous
            if previous is not None and previous.result is not None and not force:
                return AnalysisSubmission(
                    False,
                    session_id,
                    "already_completed",
                    previous.status,
                )

            revision = (previous.revision + 1) if previous else 1
            selected_provider = self.provider
            record = AnalysisRecord(
                request=request,
                provider=selected_provider.provider_name,
                model=getattr(selected_provider, "model", None) or None,
                status=AnalysisStatus.PENDING,
                revision=revision,
                result=previous.result if previous else None,
            )
            self._records[session_id] = record
            task = asyncio.create_task(
                self._execute(record, selected_provider),
                name=f"meeting-analysis-{session_id}",
            )
            self._tasks[session_id] = task
            task.add_done_callback(self._consume_task_exception)
        return AnalysisSubmission(True, session_id, "pending", AnalysisStatus.PENDING)

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[MeetingAnalysis]) -> None:
        if task.cancelled():
            return
        try:
            task.exception()
        except Exception:
            pass

    async def _set_repository_status(
        self,
        session_id: str,
        status: AnalysisStatus,
        provider: str,
    ) -> None:
        try:
            await self._repository_call(
                "set_analysis_status",
                session_id,
                status.value,
                provider=provider,
            )
        except Exception as error:
            LOGGER.warning("Analysis status persistence failed: %s", type(error).__name__)

    async def _execute(
        self,
        record: AnalysisRecord,
        provider: AnalysisProvider,
    ) -> MeetingAnalysis:
        request = record.request
        session_id = request.session_id
        try:
            await self._set_repository_status(
                session_id,
                AnalysisStatus.PENDING,
                provider.provider_name,
            )
            await self._emit(
                {
                    "type": "analysis_pending",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "timestamp": iso_now(),
                }
            )
            record.status = AnalysisStatus.RUNNING
            await self._set_repository_status(
                session_id,
                AnalysisStatus.RUNNING,
                provider.provider_name,
            )
            await self._emit(
                {
                    "type": "analysis_status",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "status": AnalysisStatus.RUNNING.value,
                    "timestamp": iso_now(),
                }
            )

            if provider.provider_name == "none":
                result = await provider.analyze(request)
                record.status = AnalysisStatus.NOT_STARTED
                record.result = result
                await self._set_repository_status(
                    session_id,
                    AnalysisStatus.NOT_STARTED,
                    provider.provider_name,
                )
                return result

            if not request.segments:
                result = MeetingAnalysis(
                    session_id=session_id,
                    provider=provider.provider_name,
                    model=getattr(provider, "model", None),
                    status=AnalysisStatus.COMPLETED,
                    meeting_purpose=EvidenceItem(UNDECIDED),
                    warnings=("no_analyzable_segments",),
                )
            else:
                chunks = chunk_request(
                    request,
                    max_segments=self.max_segments_per_chunk,
                    max_characters=self.max_characters_per_chunk,
                )
                parts: list[MeetingAnalysis] = []
                chunk_warnings: list[str] = []
                for chunk_request_value, warnings in chunks:
                    chunk_warnings.extend(warnings)
                    parts.append(
                        await self._analyze_chunk(provider, chunk_request_value, record)
                    )
                result = merge_analyses(
                    session_id,
                    parts,
                    provider=provider.provider_name,
                    model=getattr(provider, "model", None),
                    warnings=chunk_warnings,
                )
                validate_evidence(result, request.segment_ids)
            result = result.with_revision(record.revision)
            saved = await self._repository_call("save_analysis", session_id, result.to_dict())
            if isinstance(saved, Mapping):
                result = self._from_saved(saved)
            record.result = result
            record.status = AnalysisStatus.COMPLETED
            record.last_error_code = None
            await self._emit(
                {
                    "type": "analysis_completed",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "generated_at": result.generated_at,
                    "revision": result.revision,
                    "timestamp": iso_now(),
                }
            )
            return result
        except asyncio.CancelledError:
            record.status = AnalysisStatus.CANCELLED
            record.last_error_code = AnalysisErrorCode.CANCELLED.value
            await self._set_repository_status(
                session_id,
                AnalysisStatus.CANCELLED,
                provider.provider_name,
            )
            await self._emit(
                {
                    "type": "analysis_cancelled",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "timestamp": iso_now(),
                }
            )
            raise
        except Exception as raw_error:
            error = normalize_analysis_error(raw_error)
            record.status = AnalysisStatus.FAILED
            record.last_error_code = error.code.value
            await self._set_repository_status(
                session_id,
                AnalysisStatus.FAILED,
                provider.provider_name,
            )
            await self._emit(
                {
                    "type": "analysis_error",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "code": error.code.value,
                    "message": error.safe_message,
                    "recoverable": error.recoverable,
                    "timestamp": iso_now(),
                }
            )
            raise error from raw_error
        finally:
            current = asyncio.current_task()
            if self._tasks.get(session_id) is current:
                self._tasks.pop(session_id, None)

    async def _analyze_chunk(
        self,
        provider: AnalysisProvider,
        request: AnalysisRequest,
        record: AnalysisRecord,
    ) -> MeetingAnalysis:
        last_error: AnalysisProviderError | None = None
        for attempt in range(self.max_retries + 1):
            record.attempts += 1
            try:
                result = await asyncio.wait_for(
                    provider.analyze(request),
                    timeout=self.timeout_seconds,
                )
                if (
                    not isinstance(result, MeetingAnalysis)
                    or result.status is not AnalysisStatus.COMPLETED
                    or result.session_id != request.session_id
                    or result.provider != provider.provider_name
                ):
                    raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE)
                return validate_evidence(result, request.segment_ids)
            except asyncio.CancelledError:
                raise
            except Exception as raw_error:
                last_error = normalize_analysis_error(raw_error)
                if not last_error.retryable or attempt >= self.max_retries:
                    break
                await self.sleep_func(self.backoff_seconds * (2**attempt))
        raise last_error or analysis_error(AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR)

    async def wait(self, session_id: str) -> MeetingAnalysis | None:
        task = self._tasks.get(session_id)
        if task is not None:
            return await asyncio.shield(task)
        record = self._records.get(session_id)
        if record is None:
            return await self.get(session_id)
        if record.status in {AnalysisStatus.FAILED, AnalysisStatus.CANCELLED}:
            try:
                code = AnalysisErrorCode(
                    record.last_error_code
                    or AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR.value
                )
            except ValueError:
                code = AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR
            raise analysis_error(code)
        return record.result

    async def cancel(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await self._ensure_cancelled_state(session_id)
        self._tasks.pop(session_id, None)
        return True

    async def _ensure_cancelled_state(self, session_id: str) -> None:
        """Cover cancellation before ``_execute`` receives its first timeslice."""

        record = self._records.get(session_id)
        if record is None or record.status is AnalysisStatus.CANCELLED:
            return
        record.status = AnalysisStatus.CANCELLED
        record.last_error_code = AnalysisErrorCode.CANCELLED.value
        await self._set_repository_status(
            session_id,
            AnalysisStatus.CANCELLED,
            record.provider,
        )
        await self._emit(
            {
                "type": "analysis_cancelled",
                "session_id": session_id,
                "provider": record.provider,
                "timestamp": iso_now(),
            }
        )

    async def retry(self, session_id: str) -> AnalysisSubmission:
        return await self.submit(session_id, force=True)

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        active = [
            (session_id, task)
            for session_id, task in self._tasks.items()
            if not task.done()
        ]
        for _, task in active:
            task.cancel()
        await asyncio.gather(*(task for _, task in active), return_exceptions=True)
        for session_id, _ in active:
            await self._ensure_cancelled_state(session_id)
        self._tasks.clear()
        await self.provider.close()

    close = shutdown


__all__ = ["AnalysisManager"]
