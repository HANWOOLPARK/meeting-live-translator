"""Bounded, failure-isolated orchestration for live Decision Radar batches."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..analysis.exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    analysis_error,
    normalize_analysis_error,
)
from .models import (
    RADAR_SCHEMA_VERSION,
    RadarBatchResult,
    RadarItem,
    RadarLifecycleStatus,
    RadarRequest,
    RadarReviewStatus,
    RadarRuntimeStatus,
    RadarSegment,
    RadarSessionState,
    RadarSuggestion,
    iso_now,
)
from .providers import DecisionRadarProvider, NoneDecisionRadarProvider


LOGGER = logging.getLogger(__name__)
RadarProviderFactory = Callable[[], DecisionRadarProvider]
EventSink = Callable[[dict[str, Any]], Any]
ContextSupplier = Callable[[], Mapping[str, Any]]
MAX_ACTIVE_ITEMS_PER_SESSION = 100
MAX_HISTORY_ITEMS_PER_SESSION = 200
MAX_BUFFERED_SEGMENTS = 200


class DecisionRadarManager:
    """Analyze finalized segments in small batches without blocking transcription."""

    def __init__(
        self,
        *,
        store_path: str | Path,
        provider_factories: Mapping[str, RadarProviderFactory],
        selected_provider: str = "none",
        batch_size: int = 10,
        batch_wait_seconds: float = 20.0,
        context_window_segments: int = 16,
        queue_max_size: int = 100,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        event_sink: EventSink | None = None,
        context_supplier: ContextSupplier | None = None,
    ) -> None:
        if batch_size < 1 or queue_max_size < 1 or context_window_segments < 1:
            raise ValueError("Decision Radar batch and queue sizes must be positive")
        if context_window_segments < batch_size:
            raise ValueError("Decision Radar context window must cover one full batch")
        if context_window_segments > MAX_BUFFERED_SEGMENTS:
            raise ValueError("Decision Radar context window is too large")
        if batch_wait_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("Decision Radar timeouts must be positive")
        if max_retries < 0:
            raise ValueError("Decision Radar retries must not be negative")
        self.store_path = Path(store_path).resolve()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider_factories = dict(provider_factories)
        factory = self.provider_factories.get(selected_provider)
        self.provider = factory() if factory is not None else NoneDecisionRadarProvider()
        self.batch_size = int(batch_size)
        self.batch_wait_seconds = float(batch_wait_seconds)
        self.context_window_segments = int(context_window_segments)
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.event_sink = event_sink
        self.context_supplier = context_supplier

        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(
            maxsize=int(queue_max_size)
        )
        self._pending: set[tuple[str, str]] = set()
        self._segments: dict[str, OrderedDict[str, RadarSegment]] = defaultdict(
            OrderedDict
        )
        self._states = self._load_states()
        self._current_session_id: str | None = None
        self._runtime_status = (
            RadarRuntimeStatus.DISABLED
            if self.provider.provider_name == "none"
            else RadarRuntimeStatus.IDLE
        )
        self._last_error_code: str | None = None
        self._dropped_segments = 0
        self._processed_batches = 0
        self._provider_attempts = 0
        self._analyzed_focus_segments = 0
        self._request_input_characters = 0
        self._context_entries_sent = 0
        self._discarded_evidence_references = 0
        self._discarded_suggestions = 0
        self._processing_session_id: str | None = None
        self._worker: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    def _load_states(self) -> dict[str, RadarSessionState]:
        if not self.store_path.is_file():
            return {}
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("radar state must be an object")
            raw_sessions = payload.get("sessions", {})
            if not isinstance(raw_sessions, Mapping):
                raise ValueError("radar sessions must be an object")
            result: dict[str, RadarSessionState] = {}
            for session_id, raw_state in raw_sessions.items():
                if not isinstance(raw_state, Mapping):
                    continue
                state = RadarSessionState.from_dict(raw_state)
                if state.session_id and state.session_id == str(session_id):
                    result[state.session_id] = state
            return result
        except Exception as error:
            LOGGER.warning("Decision Radar state was ignored: %s", type(error).__name__)
            return {}

    def _write_states(self) -> None:
        payload = {
            "schema_version": RADAR_SCHEMA_VERSION,
            "sessions": {
                session_id: state.to_dict()
                for session_id, state in self._states.items()
            },
        }
        temporary = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.store_path)

    async def _persist(self) -> None:
        try:
            await asyncio.to_thread(self._write_states)
        except Exception as error:
            LOGGER.warning("Decision Radar persistence failed: %s", type(error).__name__)

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            outcome = self.event_sink(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as error:
            LOGGER.warning("Decision Radar event sink failed: %s", type(error).__name__)

    async def start(self) -> None:
        if self._closed or (self._worker is not None and not self._worker.done()):
            return
        self._worker = asyncio.create_task(
            self._run(),
            name="decision-radar-worker",
        )

    async def begin_session(self, session_id: str) -> None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return
        changed = normalized != self._current_session_id
        created = normalized not in self._states
        self._current_session_id = normalized
        self._states.setdefault(normalized, RadarSessionState(normalized))
        if not changed and not created:
            return
        await self._emit(
            {
                "type": "decision_radar_updated",
                "decision_radar": self.snapshot(normalized),
                "timestamp": iso_now(),
            }
        )

    @staticmethod
    def _context_entries(
        segments: tuple[RadarSegment, ...],
    ) -> tuple[dict[str, Any], ...]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for segment in segments:
            for match in segment.context_matches:
                canonical = str(
                    match.get("canonical") or match.get("to") or ""
                ).strip()
                category = str(match.get("category") or "term").strip() or "term"
                key = (category.casefold(), canonical.casefold())
                if not canonical or key in seen:
                    continue
                seen.add(key)
                entry: dict[str, Any] = {
                    "category": category,
                    "canonical": canonical,
                }
                matched_as = str(match.get("from") or "").strip()
                if matched_as and matched_as.casefold() != canonical.casefold():
                    entry["matched_as"] = matched_as
                entries.append(entry)
                if len(entries) >= 10:
                    return tuple(entries)
        return tuple(entries)

    async def submit_final(self, event: Mapping[str, Any]) -> bool:
        """Queue one finalized transcript. This method never calls a provider."""

        if self._closed or self.provider.provider_name == "none":
            return False
        try:
            session_id = str(event.get("session_id", "")).strip()
            segment_id = str(event.get("segment_id", "")).strip()
            text = str(event.get("text", "")).strip()
            segment = RadarSegment(
                session_id=session_id,
                segment_id=segment_id,
                original_text=text,
                normalized_text=event.get("normalized_text"),
                language=str(
                    event.get("detected_language", event.get("language", "unknown"))
                ),
                target_language=str(event.get("target_language", "ko")),
                started_at=(
                    str(event.get("started_at")) if event.get("started_at") else None
                ),
                ended_at=(str(event.get("ended_at")) if event.get("ended_at") else None),
                context_matches=tuple(event.get("context_matches", ()) or ()),
            )
        except Exception:
            return False
        await self.begin_session(segment.session_id)
        session_segments = self._segments[segment.session_id]
        session_segments[segment.segment_id] = segment
        session_segments.move_to_end(segment.segment_id)
        while len(session_segments) > MAX_BUFFERED_SEGMENTS:
            session_segments.popitem(last=False)

        key = (segment.session_id, segment.segment_id)
        if key in self._pending:
            return True
        try:
            self._queue.put_nowait(key)
            self._pending.add(key)
            self._runtime_status = RadarRuntimeStatus.BUFFERING
            await self._emit_status()
            return True
        except asyncio.QueueFull:
            self._dropped_segments += 1
            await self._emit(
                {
                    "type": "decision_radar_error",
                    "code": "queue_full",
                    "message": "Decision Radar 대기열이 가득 찼습니다. 원문 자막은 계속 표시됩니다.",
                    "recoverable": True,
                    "timestamp": iso_now(),
                }
            )
            return False

    async def update_translation(self, event: Mapping[str, Any]) -> None:
        session_id = str(event.get("session_id", "")).strip()
        segment_id = str(event.get("segment_id", "")).strip()
        if not session_id or not segment_id:
            return
        segment = self._segments.get(session_id, {}).get(segment_id)
        if segment is None:
            return
        translated = event.get("translated_text", event.get("text"))
        self._segments[session_id][segment_id] = segment.with_translation(
            str(translated) if translated is not None else None
        )

    async def _emit_status(self) -> None:
        await self._emit(
            {
                "type": "decision_radar_status",
                "status": self._runtime_status.value,
                "provider": self.provider.provider_name,
                "session_id": self._processing_session_id or self._current_session_id,
                "queue_size": self._queue.qsize(),
                "timestamp": iso_now(),
            }
        )

    async def _run(self) -> None:
        try:
            while True:
                first = await self._queue.get()
                batch = [first]
                deadline = asyncio.get_running_loop().time() + self.batch_wait_seconds
                while len(batch) < self.batch_size:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        )
                    except asyncio.TimeoutError:
                        break
                for key in batch:
                    self._pending.discard(key)
                grouped: dict[str, list[str]] = defaultdict(list)
                for session_id, segment_id in batch:
                    if segment_id not in grouped[session_id]:
                        grouped[session_id].append(segment_id)
                for session_id, segment_ids in grouped.items():
                    await self._process_batch(session_id, segment_ids)
        except asyncio.CancelledError:
            raise

    async def _process_batch(self, session_id: str, segment_ids: list[str]) -> None:
        if self.provider.provider_name == "none" or self._closed:
            return
        session_segments = self._segments.get(session_id)
        if not session_segments:
            return
        ordered_segments = list(session_segments.values())
        indexes = {
            segment.segment_id: index
            for index, segment in enumerate(ordered_segments)
        }
        focus_segment_ids = tuple(
            segment_id for segment_id in segment_ids if segment_id in indexes
        )
        if not focus_segment_ids:
            return
        last_focus_index = max(indexes[segment_id] for segment_id in focus_segment_ids)
        first_context_index = max(
            0,
            last_focus_index - self.context_window_segments + 1,
        )
        segments = tuple(ordered_segments[first_context_index : last_focus_index + 1])
        state = self._states.setdefault(session_id, RadarSessionState(session_id))
        request = RadarRequest(
            session_id,
            segments,
            focus_segment_ids=focus_segment_ids,
            context_entries=self._context_entries(segments),
            existing_items=tuple(
                item.to_prompt_dict()
                for item in state.items
                if item.lifecycle_status is RadarLifecycleStatus.ACTIVE
            ),
            output_language=next(
                segment.target_language
                for segment in reversed(segments)
                if segment.segment_id in focus_segment_ids
            ),
        )
        provider = self.provider
        self._processing_session_id = session_id
        self._runtime_status = RadarRuntimeStatus.RUNNING
        await self._emit_status()
        last_error: AnalysisProviderError | None = None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    self._provider_attempts += 1
                    self._context_entries_sent += len(request.context_entries)
                    result = await asyncio.wait_for(
                        provider.analyze(request),
                        timeout=self.timeout_seconds,
                    )
                    self._discarded_evidence_references += (
                        result.discarded_evidence_references
                    )
                    self._discarded_suggestions += result.discarded_suggestions
                    if (
                        result.discarded_evidence_references
                        or result.discarded_suggestions
                    ):
                        LOGGER.warning(
                            "Decision Radar accepted a partial provider response: "
                            "discarded_evidence=%d discarded_suggestions=%d",
                            result.discarded_evidence_references,
                            result.discarded_suggestions,
                        )
                    self._merge_result(state, result)
                    self._last_error_code = None
                    self._processed_batches += 1
                    self._analyzed_focus_segments += len(request.focus_segment_ids)
                    self._request_input_characters += result.request_input_characters
                    self._runtime_status = (
                        RadarRuntimeStatus.BUFFERING
                        if self._queue.qsize()
                        else RadarRuntimeStatus.IDLE
                    )
                    await self._persist()
                    await self._emit(
                        {
                            "type": "decision_radar_updated",
                            "decision_radar": self.snapshot(session_id),
                            "timestamp": iso_now(),
                        }
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as raw_error:
                    last_error = normalize_analysis_error(raw_error)
                    if not last_error.retryable or attempt >= self.max_retries:
                        break
                    await asyncio.sleep(0.5 * (2**attempt))
            error = last_error or analysis_error(AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR)
            self._last_error_code = error.code.value.lower()
            self._runtime_status = RadarRuntimeStatus.ERROR
            await self._emit(
                {
                    "type": "decision_radar_error",
                    "session_id": session_id,
                    "provider": provider.provider_name,
                    "code": self._last_error_code,
                    "message": error.safe_message,
                    "recoverable": error.recoverable,
                    "timestamp": iso_now(),
                }
            )
        finally:
            self._processing_session_id = None
            await self._emit_status()

    @staticmethod
    def _suggestion_key(suggestion: RadarSuggestion) -> tuple[str, str]:
        return suggestion.category.value, suggestion.text.casefold()

    def _merge_result(
        self,
        state: RadarSessionState,
        result: RadarBatchResult,
    ) -> None:
        now = iso_now()
        retracted_item_ids = set(result.retracted_item_ids)
        if retracted_item_ids:
            changed = False
            for index, item in enumerate(state.items):
                if (
                    item.item_id in retracted_item_ids
                    and item.lifecycle_status is RadarLifecycleStatus.ACTIVE
                    and item.review_status is RadarReviewStatus.SUGGESTED
                    and not item.user_edited
                ):
                    state.items[index] = replace(
                        item,
                        lifecycle_status=RadarLifecycleStatus.RETRACTED,
                        lifecycle_reason="후속 원문 분석에서 현재 유효한 항목으로 확인되지 않았습니다.",
                        lifecycle_updated_at=now,
                        updated_at=now,
                    )
                    changed = True
        else:
            changed = False
        by_key = {
            item.semantic_key(): index
            for index, item in enumerate(state.items)
            if item.lifecycle_status is RadarLifecycleStatus.ACTIVE
        }
        for suggestion in result.suggestions:
            key = self._suggestion_key(suggestion)
            if key in state.tombstones:
                continue
            index = by_key.get(key)
            if index is None:
                item = RadarItem.from_suggestion(suggestion)
                state.items.append(item)
                by_key[item.semantic_key()] = len(state.items) - 1
                changed = True
                continue
            current = state.items[index]
            evidence = tuple(
                dict.fromkeys(
                    (*current.evidence_segment_ids, *suggestion.evidence_segment_ids)
                )
            )
            if evidence == current.evidence_segment_ids:
                continue
            state.items[index] = replace(
                current,
                evidence_segment_ids=evidence,
                assignee=current.assignee or suggestion.assignee,
                due_date=current.due_date or suggestion.due_date,
                updated_at=now,
            )
            changed = True
        history_items = [
            item for item in state.items
            if item.lifecycle_status is not RadarLifecycleStatus.ACTIVE
        ]
        if len(history_items) > MAX_HISTORY_ITEMS_PER_SESSION:
            remove_count = len(history_items) - MAX_HISTORY_ITEMS_PER_SESSION
            remove_ids = {item.item_id for item in history_items[:remove_count]}
            state.items = [item for item in state.items if item.item_id not in remove_ids]
            changed = changed or bool(remove_ids)
        if changed:
            state.revision += 1
            state.updated_at = now

    def _state_for_item(self, item_id: str) -> tuple[RadarSessionState, int]:
        for state in self._states.values():
            for index, item in enumerate(state.items):
                if item.item_id == item_id:
                    return state, index
        raise KeyError(item_id)

    async def update_item(
        self,
        item_id: str,
        *,
        review_status: str | None = None,
        text: str | None = None,
        assignee: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any]:
        state, index = self._state_for_item(item_id)
        current = state.items[index]
        next_text = " ".join(str(text).split()).strip() if text is not None else current.text
        if not next_text or len(next_text) > 4_000:
            raise ValueError("invalid radar item text")
        next_status = (
            RadarReviewStatus(review_status)
            if review_status is not None
            else current.review_status
        )
        state.items[index] = replace(
            current,
            text=next_text,
            review_status=next_status,
            assignee=(
                " ".join(str(assignee).split()).strip() or None
                if assignee is not None
                else current.assignee
            ),
            due_date=(
                " ".join(str(due_date).split()).strip() or None
                if due_date is not None
                else current.due_date
            ),
            user_edited=current.user_edited
            or text is not None
            or assignee is not None
            or due_date is not None,
            updated_at=iso_now(),
        )
        state.revision += 1
        state.updated_at = iso_now()
        await self._persist()
        await self._emit(
            {
                "type": "decision_radar_updated",
                "decision_radar": self.snapshot(state.session_id),
                "timestamp": iso_now(),
            }
        )
        return state.items[index].to_dict()

    async def delete_item(self, item_id: str) -> dict[str, Any]:
        state, index = self._state_for_item(item_id)
        item = state.items.pop(index)
        state.tombstones.add(item.semantic_key())
        state.revision += 1
        state.updated_at = iso_now()
        await self._persist()
        await self._emit(
            {
                "type": "decision_radar_updated",
                "decision_radar": self.snapshot(state.session_id),
                "timestamp": iso_now(),
            }
        )
        return {"deleted": True, "item_id": item_id, "session_id": state.session_id}

    async def providers(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        names = set(self.provider_factories)
        names.add(self.provider.provider_name)
        for name in sorted(names, key=lambda value: (value != "none", value)):
            if name == self.provider.provider_name:
                candidate = self.provider
                close_candidate = False
            else:
                factory = self.provider_factories.get(name)
                if factory is None:
                    continue
                candidate = factory()
                close_candidate = True
            try:
                payloads.append((await candidate.health_check()).to_dict())
            finally:
                if close_candidate:
                    await candidate.close()
        return payloads

    async def configure(self, provider_name: str) -> dict[str, Any]:
        factory = self.provider_factories.get(provider_name)
        if factory is None:
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        candidate = factory()
        health = await candidate.health_check()
        if not health.available:
            await candidate.close()
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        async with self._lock:
            previous = self.provider
            self.provider = candidate
            self._runtime_status = (
                RadarRuntimeStatus.DISABLED
                if provider_name == "none"
                else RadarRuntimeStatus.IDLE
            )
            self._last_error_code = None
            if provider_name == "none":
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                self._pending.clear()
        if previous is not candidate:
            await previous.close()
        await self._emit_status()
        return await self.public_settings()

    def snapshot(self, session_id: str | None = None) -> dict[str, Any]:
        selected_session = str(session_id or self._current_session_id or "").strip()
        state = self._states.get(selected_session)
        items = [item.to_dict() for item in state.items] if state is not None else []
        return {
            "schema_version": RADAR_SCHEMA_VERSION,
            "enabled": self.provider.provider_name != "none",
            "provider": self.provider.provider_name,
            "model": getattr(self.provider, "model", None) or None,
            "status": self._runtime_status.value,
            "session_id": selected_session or None,
            "revision": state.revision if state is not None else 0,
            "updated_at": state.updated_at if state is not None else None,
            "items": items,
            "queue_size": self._queue.qsize(),
            "queue_max_size": self._queue.maxsize,
            "batch_size": self.batch_size,
            "batch_wait_seconds": self.batch_wait_seconds,
            "context_window_segments": self.context_window_segments,
            "discarded_evidence_references": self._discarded_evidence_references,
            "discarded_suggestions": self._discarded_suggestions,
            "processing_session_id": self._processing_session_id,
            "last_error_code": self._last_error_code,
        }

    def diagnostics(self) -> dict[str, Any]:
        state = self._states.get(self._current_session_id or "")
        category_counts: dict[str, int] = defaultdict(int)
        if state is not None:
            for item in state.items:
                key = (
                    item.category.value
                    if item.lifecycle_status is RadarLifecycleStatus.ACTIVE
                    else "history"
                )
                category_counts[key] += 1
        return {
            "enabled": self.provider.provider_name != "none",
            "provider": self.provider.provider_name,
            "model": getattr(self.provider, "model", None) or None,
            "status": self._runtime_status.value,
            "queue_size": self._queue.qsize(),
            "queue_max_size": self._queue.maxsize,
            "dropped_segments": self._dropped_segments,
            "processed_batches": self._processed_batches,
            "provider_attempts": self._provider_attempts,
            "analyzed_focus_segments": self._analyzed_focus_segments,
            "request_input_characters": self._request_input_characters,
            "average_request_input_characters": (
                round(self._request_input_characters / self._processed_batches)
                if self._processed_batches
                else 0
            ),
            "context_entries_sent": self._context_entries_sent,
            "discarded_evidence_references": self._discarded_evidence_references,
            "discarded_suggestions": self._discarded_suggestions,
            "context_window_segments": self.context_window_segments,
            "processing": self._processing_session_id is not None,
            "last_error_code": self._last_error_code,
            "item_counts": dict(category_counts),
        }

    async def public_settings(self) -> dict[str, Any]:
        health = await self.provider.health_check()
        return {
            **self.snapshot(),
            "items": [],
            "provider_available": health.available,
            "provider_external": health.external,
            "provider_reason": health.reason,
            "provider_model": health.model,
            "api_key_configured": bool(
                getattr(self.provider, "api_key_configured", False)
            ),
        }

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._runtime_status = RadarRuntimeStatus.CLOSED
        await self.provider.close()


__all__ = ["DecisionRadarManager", "RadarProviderFactory"]
