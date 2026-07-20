from __future__ import annotations

import asyncio

from backend.app.websocket.manager import WebSocketManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict[str, object]) -> None:
        self.sent.append(event)


def test_transcript_and_translation_events_are_delivered_in_order() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        websocket = FakeWebSocket()
        await manager.connect(websocket)  # type: ignore[arg-type]
        assert websocket.accepted

        await manager.broadcast({"type": "partial_transcript", "text": "途中"})
        await manager.broadcast({"type": "final_transcript", "text": "確定"})
        await manager.broadcast(
            {"type": "translation_pending", "segment_id": "segment-1"}
        )
        await manager.broadcast(
            {
                "type": "translation",
                "segment_id": "segment-1",
                "translated_text": "확정",
            }
        )
        for _ in range(50):
            if len(websocket.sent) == 4:
                break
            await asyncio.sleep(0.01)
        assert [event["type"] for event in websocket.sent] == [
            "partial_transcript",
            "final_transcript",
            "translation_pending",
            "translation",
        ]
        await manager.close_all()
        assert manager.connection_count == 0

    asyncio.run(scenario())


def test_phase3_session_events_are_small_and_ordered() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        websocket = FakeWebSocket()
        await manager.connect(websocket)  # type: ignore[arg-type]

        for event in (
            {"type": "session_created", "session_id": "safe-session"},
            {
                "type": "session_status",
                "session_id": "safe-session",
                "status": "finalizing",
            },
            {"type": "session_finalized", "session_id": "safe-session"},
        ):
            await manager.broadcast(event)

        for _ in range(50):
            if len(websocket.sent) == 3:
                break
            await asyncio.sleep(0.01)
        assert [event["type"] for event in websocket.sent] == [
            "session_created",
            "session_status",
            "session_finalized",
        ]
        assert all("segments" not in event for event in websocket.sent)
        await manager.close_all()

    asyncio.run(scenario())


def test_main_and_caption_window_clients_receive_critical_events() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        main_window = FakeWebSocket()
        caption_window = FakeWebSocket()
        await manager.connect(main_window)  # type: ignore[arg-type]
        await manager.connect(caption_window)  # type: ignore[arg-type]

        events = (
            {"type": "final_transcript", "segment_id": "segment-1", "text": "確定"},
            {
                "type": "translation",
                "segment_id": "segment-1",
                "translated_text": "확정",
            },
        )
        for event in events:
            await manager.broadcast(event)

        for _ in range(50):
            if len(main_window.sent) == len(caption_window.sent) == 2:
                break
            await asyncio.sleep(0.01)
        expected = ["final_transcript", "translation"]
        assert [event["type"] for event in main_window.sent] == expected
        assert [event["type"] for event in caption_window.sent] == expected
        await manager.close_all()

    asyncio.run(scenario())


def test_auxiliary_event_sink_receives_a_copy_without_a_browser_client() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        received: list[dict[str, object]] = []

        async def sink(event: dict[str, object]) -> None:
            event["sink_only"] = True
            received.append(event)

        manager.add_event_sink(sink)
        original: dict[str, object] = {
            "type": "final_transcript",
            "segment_id": "segment-1",
            "text": "hello",
        }
        await manager.broadcast(original)
        assert received == [{**original, "sink_only": True}]
        assert "sink_only" not in original

        manager.remove_event_sink(sink)
        await manager.broadcast({"type": "state", "status": "stopped"})
        assert len(received) == 1

    asyncio.run(scenario())
