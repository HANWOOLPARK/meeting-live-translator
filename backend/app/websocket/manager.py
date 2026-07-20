from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


LOSSY_EVENT_TYPES = {
    "audio_level",
    "partial_transcript",
    "translation_pending",
    "translation_status",
    "session_status",
}
CRITICAL_EVENT_TYPES = {
    "state",
    "final_transcript",
    "translation",
    "translation_error",
    "session_created",
    "session_finalized",
    "session_recovered",
    "error",
    "snapshot",
}


@dataclass(slots=True)
class _Client:
    websocket: WebSocket
    queue: asyncio.Queue[dict[str, Any]]
    sender: asyncio.Task[None]


class WebSocketManager:
    """Fan out events without letting a slow browser block capture processing."""

    def __init__(self, queue_size: int = 100) -> None:
        self._clients: dict[int, _Client] = {}
        self._lock = asyncio.Lock()
        self._queue_size = queue_size
        self._event_sinks: list[
            Callable[[dict[str, Any]], Awaitable[None] | None]
        ] = []

    def add_event_sink(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None] | None],
    ) -> None:
        if sink not in self._event_sinks:
            self._event_sinks.append(sink)

    def remove_event_sink(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None] | None],
    ) -> None:
        if sink in self._event_sinks:
            self._event_sinks.remove(sink)

    @property
    def connection_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        sender = asyncio.create_task(
            self._sender_loop(websocket, queue),
            name=f"ws-sender-{id(websocket)}",
        )
        async with self._lock:
            self._clients[id(websocket)] = _Client(websocket, queue, sender)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            client = self._clients.pop(id(websocket), None)
        if client is None:
            return
        current = asyncio.current_task()
        if client.sender is not current:
            client.sender.cancel()
            await asyncio.gather(client.sender, return_exceptions=True)

    async def send_to(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        client = self._clients.get(id(websocket))
        if client is None:
            return
        await self._enqueue(client, event)

    async def broadcast(self, event: dict[str, Any]) -> None:
        clients = list(self._clients.values())
        stale: list[WebSocket] = []
        for client in clients:
            if not await self._enqueue(client, event):
                stale.append(client.websocket)
        for websocket in stale:
            await self.disconnect(websocket)
        for sink in list(self._event_sinks):
            try:
                result = sink(dict(event))
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Auxiliary sinks must never interrupt local browser delivery
                # or audio capture.
                continue

    async def close_all(self) -> None:
        clients = list(self._clients.values())
        for client in clients:
            await self.disconnect(client.websocket)

    async def _enqueue(self, client: _Client, event: dict[str, Any]) -> bool:
        if not client.queue.full():
            client.queue.put_nowait(event)
            return True

        event_type = str(event.get("type", ""))
        if event_type in LOSSY_EVENT_TYPES:
            retained: list[dict[str, Any]] = []
            removed = False
            while not client.queue.empty():
                queued = client.queue.get_nowait()
                if not removed and queued.get("type") == event_type:
                    removed = True
                    continue
                retained.append(queued)
            for queued in retained:
                if not client.queue.full():
                    client.queue.put_nowait(queued)
            if not client.queue.full():
                client.queue.put_nowait(event)
            return True

        # A client unable to receive critical events is disconnected; other clients continue.
        return event_type not in CRITICAL_EVENT_TYPES

    async def _sender_loop(
        self,
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.disconnect(websocket)
