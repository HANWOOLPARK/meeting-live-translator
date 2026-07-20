from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from .models import SessionStatus, StoragePolicy, iso_now
from .repository import JsonlSessionRepository


EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


class SessionManager:
    """Async lifecycle facade around the thread-safe session repository."""

    def __init__(
        self,
        repository: JsonlSessionRepository,
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        self.repository = repository
        self.event_sink = event_sink
        self._active_session_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id or self.repository.session_id

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        result = self.event_sink(event)
        if inspect.isawaitable(result):
            await result

    async def start(
        self,
        metadata: Mapping[str, Any],
        *,
        storage_policy: StoragePolicy | None = None,
    ) -> str:
        async with self._lock:
            session_id = await asyncio.to_thread(
                self.repository.start_session,
                metadata,
                storage_policy=storage_policy,
            )
            self._active_session_id = session_id
        await self._emit(
            {
                "type": "session_created",
                "session_id": session_id,
                "status": SessionStatus.RUNNING.value,
                "timestamp": iso_now(),
            }
        )
        return session_id

    async def set_status(self, status: str) -> dict[str, Any] | None:
        session_id = self.active_session_id
        if session_id is None:
            return None
        payload = await asyncio.to_thread(
            self.repository.update_status,
            session_id,
            status,
        )
        await self._emit(
            {
                "type": "session_status",
                "session_id": session_id,
                "status": status,
                "timestamp": iso_now(),
            }
        )
        return payload

    async def stop_and_finalize(self) -> dict[str, Any] | None:
        async with self._lock:
            session_id = self.active_session_id
            if session_id is None:
                return None
            await self.set_status(SessionStatus.STOPPING.value)
            await self._emit(
                {
                    "type": "session_status",
                    "session_id": session_id,
                    "status": SessionStatus.FINALIZING.value,
                    "timestamp": iso_now(),
                }
            )
            try:
                session = await asyncio.to_thread(self.repository.stop_session)
            finally:
                self._active_session_id = None
        if session is not None:
            await self._emit(
                {
                    "type": "session_finalized",
                    "session_id": session_id,
                    "status": SessionStatus.COMPLETED.value,
                    "segment_count": len(session.get("segments", [])),
                    "timestamp": iso_now(),
                }
            )
        return session

    async def finalize(self, session_id: str) -> dict[str, Any]:
        session = await asyncio.to_thread(self.repository.finalize_session, session_id)
        await self._emit(
            {
                "type": "session_finalized",
                "session_id": session_id,
                "status": SessionStatus.COMPLETED.value,
                "segment_count": len(session.get("segments", [])),
                "timestamp": iso_now(),
            }
        )
        return session

    async def recover(self, session_id: str) -> dict[str, Any]:
        session = await asyncio.to_thread(
            self.repository.finalize_session,
            session_id,
            recovered=True,
        )
        await self._emit(
            {
                "type": "session_recovered",
                "session_id": session_id,
                "status": SessionStatus.RECOVERED.value,
                "timestamp": iso_now(),
            }
        )
        return session

    async def recover_startup(self) -> list[str]:
        recovered = await asyncio.to_thread(self.repository.recover_incomplete)
        for session_id in recovered:
            await self._emit(
                {
                    "type": "session_recovered",
                    "session_id": session_id,
                    "status": SessionStatus.RECOVERED.value,
                    "timestamp": iso_now(),
                }
            )
        return recovered

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.list_sessions)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.get_session, session_id)

    async def get_export_path(self, session_id: str, kind: str) -> Path:
        return await asyncio.to_thread(self.repository.get_export_path, session_id, kind)


__all__ = ["SessionManager"]
