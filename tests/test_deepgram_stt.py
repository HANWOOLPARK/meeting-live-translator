from __future__ import annotations

import asyncio
import json
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.capture.controller import CaptureController
from backend.app.config.settings import AppSettings
from backend.app.errors import SafeAppError
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sessions.repository import JsonlSessionRepository
from backend.app.transcription import (
    DeepgramStreamError,
    DeepgramStreamingClient,
    DeepgramTranscript,
    has_explicit_korean_date,
    has_malformed_korean_date_format,
)

from .fakes import LOOPBACK, FakeCaptureFactory, FakeDeviceProvider, RecordingManager


_END = object()


class FakeSocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[str | bytes] = []
        self.closed = False

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> str | bytes:
        value = await self.incoming.get()
        if value is _END:
            raise StopAsyncIteration
        assert isinstance(value, (str, bytes))
        return value

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)
        if isinstance(message, str) and '"CloseStream"' in message:
            await self.incoming.put(_END)

    async def close(self) -> None:
        self.closed = True
        await self.incoming.put(_END)


class HangingControlSocket(FakeSocket):
    async def send(self, message: str | bytes) -> None:
        if isinstance(message, str):
            await asyncio.Event().wait()
        await super().send(message)


async def _wait_until(predicate: Any, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition was not reached")


def test_deepgram_stream_emits_partial_and_final_without_exposing_key() -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        connection: dict[str, Any] = {}

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            connection.update(url=url, kwargs=kwargs)
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="top-secret-deepgram-key",
            model="nova-3",
            language="ja",
            connector=connector,
        )
        await client.start(events.append)
        await client.send_audio(b"\x00\x00" * 160)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.4,
                    "is_final": False,
                    "speech_final": False,
                    "channel": {
                        "alternatives": [
                            {"transcript": "こんにちは", "confidence": 0.92}
                        ]
                    },
                },
                ensure_ascii=False,
            )
        )
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.8,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [
                            {"transcript": "こんにちは。", "confidence": 0.95}
                        ]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: len(events) == 2)
        assert [event.kind for event in events] == ["partial", "final"]
        assert events[-1].text == "こんにちは。"
        assert isinstance(socket.sent[0], bytes)
        assert "top-secret-deepgram-key" not in connection["url"]
        assert "top-secret-deepgram-key" not in str(client.snapshot())
        assert connection["kwargs"]["additional_headers"]["Authorization"].startswith("Token ")
        await client.stop()
        assert socket.closed is True
        assert any('"Finalize"' in item for item in socket.sent if isinstance(item, str))

    asyncio.run(scenario())


def test_deepgram_stream_requires_api_key_without_network_call() -> None:
    async def scenario() -> None:
        client = DeepgramStreamingClient(api_key=None)
        with pytest.raises(DeepgramStreamError, match="deepgram_api_key_missing"):
            await client.start(lambda _: None)

    asyncio.run(scenario())


def test_deepgram_stream_reports_clean_connection_loss() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        errors: list[str] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            connector=connector,
        )
        await client.start(lambda _: None, errors.append)
        await socket.incoming.put(_END)
        await _wait_until(lambda: errors == ["deepgram_connection_lost"])
        assert client.connected is False
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_stop_is_bounded_when_control_send_hangs() -> None:
    async def scenario() -> None:
        socket = HangingControlSocket()

        async def connector(url: str, **kwargs: Any) -> HangingControlSocket:
            del url, kwargs
            return socket

        client = DeepgramStreamingClient(
            api_key="configured-secret",
            connector=connector,
        )
        await client.start(lambda _: None)
        await asyncio.wait_for(client.stop(), timeout=3.0)
        assert socket.closed is True

    asyncio.run(scenario())


def test_deepgram_stream_assembles_stable_english_chunks_until_sentence_end() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            max_segment_seconds=4.0,
            connector=connector,
        )
        await client.start(events.append)
        for payload in (
            {
                "type": "Results",
                "start": 0.0,
                "duration": 2.2,
                "is_final": True,
                "speech_final": False,
                "channel": {"alternatives": [{"transcript": "This is stable", "confidence": 0.95}]},
            },
            {
                "type": "Results",
                "start": 2.2,
                "duration": 2.0,
                "is_final": True,
                "speech_final": False,
                "channel": {"alternatives": [{"transcript": "and bounded", "confidence": 0.96}]},
            },
            {
                "type": "Results",
                "start": 4.2,
                "duration": 1.2,
                "is_final": True,
                "speech_final": False,
                "channel": {"alternatives": [{"transcript": "Done.", "confidence": 0.97}]},
            },
        ):
            await socket.incoming.put(json.dumps(payload))

        await _wait_until(lambda: len(events) == 3)
        assert [event.kind for event in events] == ["partial", "partial", "final"]
        assert events[1].text == "This is stable and bounded"
        assert events[2].text == "This is stable and bounded Done."
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_keeps_four_second_checkpoint_ui_only() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ko",
            max_segment_seconds=7.0,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.8,
                    "is_final": False,
                    "speech_final": False,
                    "channel": {
                        "alternatives": [
                            {"transcript": "계속 말하는 중", "confidence": 0.94}
                        ]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: len(events) == 1)

        await client.send_audio(b"\x00\x00" * (4 * 16_000))
        finalize_messages = [
            item
            for item in socket.sent
            if isinstance(item, str) and '"Finalize"' in item
        ]
        assert finalize_messages == []

        # A UI checkpoint must not force provider-side finalization. Interim
        # and stable partial text stay on screen without translation.
        await client.send_audio(b"\x00\x00" * 16_000)
        finalize_messages = [
            item
            for item in socket.sent
            if isinstance(item, str) and '"Finalize"' in item
        ]
        assert finalize_messages == []

        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 4.1,
                    "is_final": True,
                    "speech_final": False,
                    "channel": {
                        "alternatives": [
                            {"transcript": "계속 말하는 중입니다", "confidence": 0.96}
                        ]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: len(events) == 2)
        assert events[-1].kind == "partial"
        assert events[-1].text == "계속 말하는 중입니다"
        await socket.incoming.put(json.dumps({"type": "UtteranceEnd"}))
        await _wait_until(lambda: len(events) == 3)
        assert events[-1].kind == "final"
        assert events[-1].text == "계속 말하는 중입니다"
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_joins_japanese_stable_chunks_without_spaces() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ja",
            max_segment_seconds=8.0,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 4.0,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{"transcript": "修正見積書は七月", "confidence": 0.96}]},
        }, ensure_ascii=False))
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 4.0, "duration": 3.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{"transcript": "二十一日の午後三時までに提出します。", "confidence": 0.97}]},
        }, ensure_ascii=False))
        await _wait_until(lambda: len(events) == 2)
        assert [event.kind for event in events] == ["partial", "final"]
        assert events[-1].text == "修正見積書は七月二十一日の午後三時までに提出します。"
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_delayed_hard_response_finalizes_requested_audio_once() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            max_segment_seconds=6.0,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.5,
            "is_final": False, "speech_final": False,
            "channel": {"alternatives": [{"transcript": "A long explanation", "confidence": 0.94}]},
        }))
        await _wait_until(lambda: len(events) == 1)
        await client.send_audio(b"\x00\x00" * (10 * 16_000))
        finalize_messages = [
            item
            for item in socket.sent
            if isinstance(item, str) and '"Finalize"' in item
        ]
        assert len(finalize_messages) == 1

        # More audio may be sent while Deepgram prepares the hard-limit result.
        # The delayed response must retain the boundary/reason recorded when
        # Finalize was requested, and a pending request must not be duplicated.
        await client.send_audio(b"\x00\x00" * (2 * 16_000))
        assert len([
            item
            for item in socket.sent
            if isinstance(item, str) and '"Finalize"' in item
        ]) == 1
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 10.0,
            "is_final": True, "speech_final": False, "from_finalize": True,
            "channel": {"alternatives": [{
                "transcript": "A long explanation continues without a pause and reaches the limit",
                "confidence": 0.96,
            }]},
        }))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        finals = [event for event in events if event.kind == "final"]
        assert len(finals) == 1
        assert finals[0].text == "A long explanation continues without a pause and reaches the limit"
        assert finals[0].ended_offset == 10.0
        assert finals[0].boundary_reason == "hard_limit"
        assert "forced_boundary" in finals[0].risk_reasons
        await socket.incoming.put(json.dumps({"type": "UtteranceEnd"}))
        await asyncio.sleep(0.02)
        assert len([event for event in events if event.kind == "final"]) == 1
        await client.stop()

    asyncio.run(scenario())


def test_hard_limit_incomplete_japanese_uses_grace_and_keeps_late_suffix() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ja",
            max_segment_seconds=8.0,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            incomplete_final_wait_seconds=0.2,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.5,
            "is_final": False, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "撮影させ", "confidence": 0.92,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: len(events) == 1)
        await client.send_audio(b"\x00\x00" * (10 * 16_000))
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 10.0,
            "is_final": True, "speech_final": True, "from_finalize": True,
            "channel": {"alternatives": [{
                "transcript": "撮影させ", "confidence": 0.94,
                "words": [{
                    "word": "撮影させ", "punctuated_word": "撮影させ",
                    "start": 0.0, "end": 10.0, "confidence": 0.75,
                }],
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        assert not any(event.kind == "final" for event in events)

        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 10.0, "duration": 0.8,
            "is_final": False, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "ていただきました。", "confidence": 0.96,
                "words": [{
                    "word": "ていただきました",
                    "punctuated_word": "ていただきました。",
                    "start": 10.0, "end": 10.8, "confidence": 0.96,
                }],
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        first = next(event for event in events if event.kind == "final")
        assert first.text == "撮影させていただきました。"
        assert first.boundary_reason == "candidate_timeout"
        assert "forced_boundary" in first.risk_reasons

        # A later stable result overlaps the promoted interim. Word offsets
        # must preserve only the unseen suffix instead of dropping it.
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 10.0, "duration": 2.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "ていただきました。内容です。", "confidence": 0.97,
                "words": [
                    {
                        "word": "ていただきました",
                        "punctuated_word": "ていただきました。",
                        "start": 10.0, "end": 10.8, "confidence": 0.97,
                    },
                    {
                        "word": "内容です",
                        "punctuated_word": "内容です。",
                        "start": 10.8, "end": 12.0, "confidence": 0.98,
                    },
                ],
            }]},
        }, ensure_ascii=False))
        await _wait_until(
            lambda: len([event for event in events if event.kind == "final"]) == 2
        )
        assert [event.text for event in events if event.kind == "final"] == [
            "撮影させていただきました。",
            "内容です。",
        ]
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_empty_hard_ack_flushes_stable_text_once() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            max_segment_seconds=6.0,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 4.0,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "A stable beginning",
                "confidence": 0.96,
            }]},
        }))
        await _wait_until(lambda: len(events) == 1)
        assert events[-1].kind == "partial"

        await client.send_audio(b"\x00\x00" * (10 * 16_000))
        assert len([
            item
            for item in socket.sent
            if isinstance(item, str) and '"Finalize"' in item
        ]) == 1
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 10.0, "duration": 0.0,
            "is_final": True, "speech_final": False, "from_finalize": True,
            "channel": {"alternatives": [{"transcript": "", "confidence": 0.0}]},
        }))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        finals = [event for event in events if event.kind == "final"]
        assert [(event.text, event.ended_offset) for event in finals] == [
            ("A stable beginning", 4.0)
        ]

        await socket.incoming.put(json.dumps({"type": "UtteranceEnd"}))
        await asyncio.sleep(0.02)
        assert len([event for event in events if event.kind == "final"]) == 1
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_hard_finalize_watchdog_flushes_stable_text_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            max_segment_seconds=6.0,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            finalize_response_timeout_seconds=0.05,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 4.0,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "Stable before timeout",
                "confidence": 0.95,
            }]},
        }))
        await _wait_until(lambda: len(events) == 1)

        await client.send_audio(b"\x00\x00" * (10 * 16_000))
        await asyncio.sleep(0.02)
        # Implementations without a background timer may check the watchdog on
        # the next audio send; either form must resolve the pending hard final.
        await client.send_audio(b"\x00\x00" * 1_600)
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        finals = [event for event in events if event.kind == "final"]
        assert [event.text for event in finals] == ["Stable before timeout"]

        # A late provider response for the timed-out request cannot create a
        # second final or attach the old text to a new utterance.
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 10.0,
            "is_final": True, "speech_final": False, "from_finalize": True,
            "channel": {"alternatives": [{
                "transcript": "Stable before timeout",
                "confidence": 0.95,
            }]},
        }))
        await asyncio.sleep(0.02)
        assert len([event for event in events if event.kind == "final"]) == 1
        await client.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("language", "soft_seconds", "first", "second", "expected"),
    (
        (
            "en",
            6.0,
            "The first clause,",
            "and the second clause,",
            "The first clause, and the second clause,",
        ),
        (
            "ja",
            8.0,
            "\u6700\u521d\u306e\u8aac\u660e\u3001",
            "\u6b21\u306e\u8aac\u660e\u3001",
            "\u6700\u521d\u306e\u8aac\u660e\u3001\u6b21\u306e\u8aac\u660e\u3001",
        ),
    ),
)
def test_deepgram_stream_uses_language_soft_boundary_without_provider_finalize(
    language: str,
    soft_seconds: float,
    first: str,
    second: str,
    expected: str,
) -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language=language,
            max_segment_seconds=soft_seconds,
            checkpoint_seconds=4.0,
            hard_limit_seconds=10.0,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": soft_seconds - 0.2,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{"transcript": first, "confidence": 0.95}]},
        }, ensure_ascii=False))
        await _wait_until(lambda: len(events) == 1)
        assert events[-1].kind == "partial"
        assert not any(
            isinstance(item, str) and '"Finalize"' in item
            for item in socket.sent
        )

        await socket.incoming.put(json.dumps({
            "type": "Results", "start": soft_seconds - 0.2, "duration": 0.3,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{"transcript": second, "confidence": 0.96}]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [expected]
        assert not any(
            isinstance(item, str) and '"Finalize"' in item
            for item in socket.sent
        )
        await client.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("language", "first", "second", "expected"),
    (
        (
            "en",
            "This is stable,",
            "and bounded.",
            "This is stable, and bounded.",
        ),
        (
            "ko",
            "\uc624\ub298 \ud68c\uc758\ub294",
            "\uc5ec\uae30\uc11c \ub05d\ub0a9\ub2c8\ub2e4.",
            "\uc624\ub298 \ud68c\uc758\ub294 \uc5ec\uae30\uc11c \ub05d\ub0a9\ub2c8\ub2e4.",
        ),
    ),
)
def test_deepgram_stream_joins_english_and_korean_chunks_with_spaces(
    language: str,
    first: str,
    second: str,
    expected: str,
) -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language=language,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 2.0,
            "is_final": True, "speech_final": False,
            "channel": {"alternatives": [{"transcript": first, "confidence": 0.95}]},
        }, ensure_ascii=False))
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 2.0, "duration": 2.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{"transcript": second, "confidence": 0.96}]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [expected]
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_stream_stop_preserves_trailing_interim_once() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 1.5,
            "is_final": False, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "Trailing words before stop",
                "confidence": 0.93,
            }]},
        }))
        await _wait_until(lambda: len(events) == 1)
        assert events[-1].kind == "partial"

        await client.stop()
        finals = [event for event in events if event.kind == "final"]
        assert [event.text for event in finals] == ["Trailing words before stop"]
        assert socket.closed is True

    asyncio.run(scenario())


def test_deepgram_controller_path_persists_only_final_and_skips_whisper(tmp_path) -> None:
    class RecordingTranslationManager:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        async def submit_event(self, event: dict[str, Any]) -> None:
            self.events.append(event)

    class FakeDeepgram:
        def __init__(self) -> None:
            self.transcript_sink: Any = None
            self.audio: list[bytes] = []
            self.connected = False

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            self.transcript_sink = transcript_sink
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            self.audio.append(pcm)
            if len(self.audio) == 1:
                await self.transcript_sink(
                    DeepgramTranscript("partial", "会議中", 0.9, 0.0, 0.2)
                )

        async def stop(self) -> None:
            if self.connected:
                self.connected = False
                await self.transcript_sink(
                    DeepgramTranscript("final", "会議を始めます。", 0.94, 0.0, 0.8)
                )

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": "ja",
                "last_error": None,
            }

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
        )
        captures = FakeCaptureFactory()
        manager = RecordingManager()
        translations = RecordingTranslationManager()
        deepgram = FakeDeepgram()

        def forbidden_engine(_: str) -> Any:
            raise AssertionError("local Whisper must not load on Deepgram path")

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            engine_factory=forbidden_engine,
            deepgram_factory=lambda _language: deepgram,
            translation_manager=translations,  # type: ignore[arg-type]
        )
        started = await controller.start(
            "system", LOOPBACK.device_id, "small", "deepgram"
        )
        assert started["stt_provider"] == "deepgram"
        captures.latest.emit(np.full(1_600, 0.1, dtype=np.float32))
        await _wait_until(
            lambda: any(event.get("type") == "partial_transcript" for event in manager.events)
        )
        assert list(settings.session_dir.glob("*.jsonl")) == []
        await controller.stop()
        final = next(event for event in manager.events if event.get("type") == "final_transcript")
        assert final["text"] == "会議を始めます。"
        assert final["language"] == "ja"
        assert translations.events[0]["text"] == "会議を始めます。"
        assert translations.events[0]["language"] == "ja"
        assert translations.events[0]["target_language"] == "ko"
        files = list(settings.session_dir.glob("*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "会議を始めます。" in content
        assert "会議中" not in content
        await controller.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("translation_direction", "target_language"),
    (("ko_to_ja", "ja"), ("ko_to_en", "en")),
)
def test_korean_source_translation_uses_deepgram_and_requested_target(
    tmp_path,
    translation_direction: str,
    target_language: str,
) -> None:
    class RecordingTranslationManager:
        provider = type("Provider", (), {"provider_name": "gemini"})()

        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        async def submit_event(self, event: dict[str, Any]) -> None:
            self.events.append(event)

    class FakeDeepgram:
        def __init__(self, language: str) -> None:
            self.language = language
            self.transcript_sink: Any = None
            self.connected = False

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            self.transcript_sink = transcript_sink
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            return None

        async def stop(self) -> None:
            if self.connected:
                self.connected = False
                await self.transcript_sink(
                    DeepgramTranscript("final", "회의를 시작하겠습니다.", 0.96, 0.0, 0.8)
                )

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": self.language,
                "last_error": None,
            }

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
        )
        languages: list[str] = []
        translations = RecordingTranslationManager()

        def deepgram_factory(language: str) -> FakeDeepgram:
            languages.append(language)
            return FakeDeepgram(language)

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            deepgram_factory=deepgram_factory,  # type: ignore[arg-type]
            translation_manager=translations,  # type: ignore[arg-type]
        )
        with pytest.raises(SafeAppError) as rejected:
            await controller.start(
                "system",
                LOOPBACK.device_id,
                "small",
                "local",
                translation_direction,
            )
        assert rejected.value.code == "reverse_translation_requires_deepgram"

        translations.provider = type("Provider", (), {"provider_name": "none"})()
        with pytest.raises(SafeAppError) as provider_rejected:
            await controller.start(
                "system",
                LOOPBACK.device_id,
                "small",
                "deepgram",
                translation_direction,
            )
        assert provider_rejected.value.code == "reverse_translation_provider_required"

        translations.provider = type("Provider", (), {"provider_name": "gemini"})()
        started = await controller.start(
            "system",
            LOOPBACK.device_id,
            "small",
            "deepgram",
            translation_direction,
        )
        assert started["translation_direction"] == translation_direction
        assert started["source_language"] == "ko"
        assert started["target_language"] == target_language
        assert languages == ["ko"]
        await controller.stop()
        assert translations.events[0]["language"] == "ko"
        assert translations.events[0]["target_language"] == target_language
        await controller.shutdown()

    asyncio.run(scenario())


def test_english_to_korean_uses_english_deepgram_and_korean_target(tmp_path) -> None:
    class RecordingTranslationManager:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        async def submit_event(self, event: dict[str, Any]) -> None:
            self.events.append(event)

    class FakeDeepgram:
        def __init__(self, language: str) -> None:
            self.language = language
            self.transcript_sink: Any = None
            self.connected = False

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            self.transcript_sink = transcript_sink
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            return None

        async def stop(self) -> None:
            if self.connected:
                self.connected = False
                await self.transcript_sink(
                    DeepgramTranscript("final", "We will start the meeting.", 0.97, 0.0, 0.8)
                )

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": self.language,
                "last_error": None,
            }

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
        )
        languages: list[str] = []
        translations = RecordingTranslationManager()

        def deepgram_factory(language: str) -> FakeDeepgram:
            languages.append(language)
            return FakeDeepgram(language)

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            deepgram_factory=deepgram_factory,  # type: ignore[arg-type]
            translation_manager=translations,  # type: ignore[arg-type]
        )
        started = await controller.start(
            "system", LOOPBACK.device_id, "small", "deepgram", "en_to_ko"
        )
        assert started["translation_direction"] == "en_to_ko"
        assert started["source_language"] == "en"
        assert started["target_language"] == "ko"
        assert languages == ["en"]
        await controller.stop()
        assert translations.events[0]["language"] == "en"
        assert translations.events[0]["target_language"] == "ko"
        await controller.shutdown()

    asyncio.run(scenario())


def test_controller_reconnects_deepgram_with_bounded_recent_audio(tmp_path) -> None:
    reconnect_gate: asyncio.Event

    class FakeDeepgram:
        def __init__(self, index: int, language: str) -> None:
            self.index = index
            self.language = language
            self.connected = False
            self.starting = False
            self.audio: list[bytes] = []

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            del transcript_sink, error_sink
            self.starting = True
            if self.index > 0:
                await reconnect_gate.wait()
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            if self.index == 0:
                self.connected = False
                raise DeepgramStreamError("simulated_disconnect")
            self.audio.append(pcm)

        async def stop(self) -> None:
            self.connected = False

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": self.language,
                "last_error": None,
            }

    async def scenario() -> None:
        nonlocal reconnect_gate
        reconnect_gate = asyncio.Event()
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
            deepgram_reconnect_max_attempts=3,
            deepgram_reconnect_base_delay_seconds=0,
            deepgram_reconnect_max_delay_seconds=0.1,
            deepgram_reconnect_buffer_seconds=0.5,
        )
        captures = FakeCaptureFactory()
        instances: list[FakeDeepgram] = []

        def deepgram_factory(language: str) -> FakeDeepgram:
            instance = FakeDeepgram(len(instances), language)
            instances.append(instance)
            return instance

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            deepgram_factory=deepgram_factory,  # type: ignore[arg-type]
        )
        await controller.start(
            "system", LOOPBACK.device_id, "small", "deepgram", "en_to_ko"
        )
        frame = np.full(1_600, 0.1, dtype=np.float32)
        captures.latest.emit(frame)
        await _wait_until(lambda: len(instances) >= 2 and instances[1].starting)

        for _ in range(10):
            captures.latest.emit(frame)
        await _wait_until(
            lambda: controller.public_stt_info()["buffered_audio_ms"] >= 500
        )
        assert controller.public_stt_info()["buffered_audio_ms"] == 500
        assert controller.public_stt_info()["dropped_audio_ms"] >= 500

        reconnect_gate.set()
        await _wait_until(
            lambda: controller.public_stt_info()["reconnect_count"] == 1
        )
        runtime = controller.public_stt_info()
        assert runtime["connected"] is True
        assert runtime["reconnecting"] is False
        assert runtime["buffered_audio_ms"] == 0
        assert len(instances[1].audio) == 5
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_controller_retries_one_transient_initial_deepgram_failure(tmp_path) -> None:
    class FakeDeepgram:
        def __init__(self, index: int, language: str) -> None:
            self.index = index
            self.language = language
            self.connected = False

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            del transcript_sink, error_sink
            if self.index == 0:
                raise DeepgramStreamError("simulated_initial_failure")
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            del pcm

        async def stop(self) -> None:
            self.connected = False

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": self.language,
                "last_error": None,
            }

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
            deepgram_reconnect_base_delay_seconds=0,
        )
        instances: list[FakeDeepgram] = []

        def factory(language: str) -> FakeDeepgram:
            instance = FakeDeepgram(len(instances), language)
            instances.append(instance)
            return instance

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            RecordingManager(),  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=FakeCaptureFactory(),
            deepgram_factory=factory,  # type: ignore[arg-type]
        )
        started = await controller.start(
            "system", LOOPBACK.device_id, "small", "deepgram", "en_to_ko"
        )
        assert started["state"] == "listening"
        assert len(instances) == 2
        assert instances[0].connected is False
        assert instances[1].connected is True
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_controller_stops_bounded_reconnects_and_discards_unrecoverable_audio(
    tmp_path,
) -> None:
    class FakeDeepgram:
        def __init__(self, index: int) -> None:
            self.index = index
            self.connected = False

        async def start(self, transcript_sink: Any, error_sink: Any = None) -> None:
            del transcript_sink, error_sink
            if self.index > 0:
                raise DeepgramStreamError("simulated_reconnect_failure")
            self.connected = True

        async def send_audio(self, pcm: bytes) -> None:
            del pcm
            self.connected = False
            raise DeepgramStreamError("simulated_disconnect")

        async def stop(self) -> None:
            self.connected = False

        def snapshot(self) -> dict[str, Any]:
            return {
                "provider": "deepgram",
                "configured": True,
                "connected": self.connected,
                "model": "nova-3",
                "language": "ja",
                "last_error": None,
            }

    async def scenario() -> None:
        settings = AppSettings(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            static_dir=tmp_path,
            deepgram_api_key="configured-secret",
            deepgram_reconnect_max_attempts=2,
            deepgram_reconnect_base_delay_seconds=0,
            deepgram_reconnect_max_delay_seconds=0.1,
            deepgram_reconnect_buffer_seconds=0.5,
        )
        captures = FakeCaptureFactory()
        manager = RecordingManager()
        instances: list[FakeDeepgram] = []

        def deepgram_factory(_language: str) -> FakeDeepgram:
            instance = FakeDeepgram(len(instances))
            instances.append(instance)
            return instance

        controller = CaptureController(
            settings,
            FakeDeviceProvider(),
            manager,  # type: ignore[arg-type]
            JsonlSessionRepository(settings.session_dir),
            capture_factory=captures,
            deepgram_factory=deepgram_factory,  # type: ignore[arg-type]
        )
        await controller.start("system", LOOPBACK.device_id, "small", "deepgram")
        frame = np.full(1_600, 0.1, dtype=np.float32)
        captures.latest.emit(frame)
        await _wait_until(
            lambda: controller.public_stt_info()["reconnect_exhausted"]
        )

        runtime = controller.public_stt_info()
        assert len(instances) == 3
        assert runtime["reconnect_attempts"] == 2
        assert runtime["buffered_audio_ms"] == 0
        assert runtime["dropped_audio_ms"] >= 100
        assert any(
            event.get("code") == "deepgram_reconnect_failed"
            for event in manager.events
        )

        captures.latest.emit(frame)
        await _wait_until(
            lambda: controller.public_stt_info()["dropped_audio_ms"] >= 200
        )
        assert len(instances) == 3
        await controller.stop()
        await controller.shutdown()

    asyncio.run(scenario())


def test_deepgram_public_settings_report_configuration_without_key(tmp_path) -> None:
    secret = "never-return-this-deepgram-key"
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
        deepgram_api_key=secret,
        stt_provider="deepgram",
    )
    services = build_services(settings, device_provider=FakeDeviceProvider())
    with TestClient(create_app(services)) as client:
        response = client.get("/api/settings")
        diagnostics = client.get("/api/diagnostics")
        assert response.status_code == 200
        assert response.json()["deepgram"]["configured"] is True
        assert response.json()["deepgram"]["model"] == "nova-3"
        selective_recheck = diagnostics.json()["server"]["stt"]["selective_recheck"]
        assert selective_recheck["enabled"] is True
        assert selective_recheck["model"] == "small"
        assert selective_recheck["local_files_only"] is True
        assert secret not in response.text + diagnostics.text
        assert secret not in repr(settings)


@pytest.mark.parametrize(
    ("language", "first", "second", "expected"),
    (
        ("ja", "本日", "の会議を開始します。", "本日の会議を開始します。"),
        (
            "en",
            "We reviewed the budget and",
            "approved the proposal.",
            "We reviewed the budget and approved the proposal.",
        ),
        ("ko", "회의 일정은", "금요일로 결정했습니다.", "회의 일정은 금요일로 결정했습니다."),
    ),
)
def test_incomplete_speech_final_is_held_and_merged_by_language(
    language: str,
    first: str,
    second: str,
    expected: str,
) -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language=language,
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.7,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [{"transcript": first, "confidence": 0.96}]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: any(event.kind == "partial" for event in events))
        assert not any(event.kind == "final" for event in events)

        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.7,
                    "duration": 1.1,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [{"transcript": second, "confidence": 0.97}]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        finals = [event for event in events if event.kind == "final"]
        assert [event.text for event in finals] == [expected]
        assert finals[0].risk_reasons == ()
        assert client.snapshot()["candidate_held_count"] == 1
        assert client.snapshot()["candidate_merged_count"] == 1
        await client.stop()

    asyncio.run(scenario())


def test_korean_unpunctuated_clause_is_held_until_formal_sentence_ending() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ko",
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 1.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "화면 디자인, 비용과 법무 과제",
                "confidence": 0.98,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        assert not any(event.kind == "final" for event in events)

        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 1.0, "duration": 1.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "법무 과제를 확인하겠습니다.",
                "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [
            "화면 디자인, 비용과 법무 과제를 확인하겠습니다."
        ]
        await client.stop()

    asyncio.run(scenario())


def test_candidate_grace_refreshes_while_interim_speech_continues() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ko",
            incomplete_final_wait_seconds=0.2,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.5,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "영어 지원은", "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        await asyncio.sleep(0.12)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.5, "duration": 0.5,
            "is_final": False, "speech_final": False,
            "channel": {"alternatives": [{
                "transcript": "지원은 자막만 제공하는 경우와",
                "confidence": 0.98,
            }]},
        }, ensure_ascii=False))
        await asyncio.sleep(0.12)
        assert not any(event.kind == "final" for event in events)

        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.5, "duration": 1.5,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": (
                    "지원은 자막만 제공하는 경우와 화면 전체를 영어로 "
                    "바꾸는 경우를 비교하겠습니다."
                ),
                "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [
            "영어 지원은 자막만 제공하는 경우와 화면 전체를 영어로 "
            "바꾸는 경우를 비교하겠습니다."
        ]
        await client.stop()

    asyncio.run(scenario())


def test_low_confidence_korean_syllable_candidate_is_replaced_by_stable_final() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ko",
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.3,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "십", "confidence": 0.90,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.3, "duration": 1.5,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "시험 도입은 세 개 회사부터 시작합니다.",
                "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [
            "시험 도입은 세 개 회사부터 시작합니다."
        ]
        await client.stop()

    asyncio.run(scenario())


def test_unpunctuated_korean_formal_sentence_is_finalized_immediately() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ko",
            incomplete_final_wait_seconds=0.2,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 1.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "결과를 확인하겠습니다", "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [
            "결과를 확인하겠습니다"
        ]
        assert client.snapshot()["candidate_held_count"] == 0
        await client.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("language", "text"),
    (("ja", "はい"), ("en", "Yes"), ("ko", "네")),
)
def test_short_acknowledgement_is_finalized_immediately(language: str, text: str) -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language=language,
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.4,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [{"transcript": text, "confidence": 0.98}]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [text]
        assert client.snapshot()["candidate_held_count"] == 0
        await client.stop()

    asyncio.run(scenario())


def test_utterance_end_keeps_an_incomplete_candidate_until_grace_timeout() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.5,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [
                            {"transcript": "We reviewed the budget and", "confidence": 0.97}
                        ]
                    },
                }
            )
        )
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        await socket.incoming.put(json.dumps({"type": "UtteranceEnd"}))
        await asyncio.sleep(0.05)
        assert not any(event.kind == "final" for event in events)
        await _wait_until(lambda: any(event.kind == "final" for event in events))

        finals = [event for event in events if event.kind == "final"]
        assert len(finals) == 1
        assert finals[0].text == "We reviewed the budget and"
        assert finals[0].boundary_reason == "candidate_timeout"
        assert "incomplete_ending" in finals[0].risk_reasons
        await client.stop()

    asyncio.run(scenario())


def test_false_utterance_end_merges_short_japanese_time_fragment() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ja",
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.5,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{"transcript": "先日", "confidence": 0.98}]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        await socket.incoming.put(json.dumps({"type": "UtteranceEnd"}))
        await asyncio.sleep(0.05)
        assert not any(event.kind == "final" for event in events)

        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.5, "duration": 1.2,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "は打ち合わせありがとうございました。",
                "confidence": 0.99,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        finals = [event for event in events if event.kind == "final"]
        assert [event.text for event in finals] == [
            "先日は打ち合わせありがとうございました。"
        ]
        assert client.snapshot()["candidate_merged_count"] == 1
        await client.stop()

    asyncio.run(scenario())


def test_punctuated_japanese_connector_is_not_treated_as_complete_sentence() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ja",
            incomplete_final_wait_seconds=0.5,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.0, "duration": 0.8,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "ですけれども。", "confidence": 0.97,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: client.snapshot()["candidate_held_count"] == 1)
        assert not any(event.kind == "final" for event in events)
        await socket.incoming.put(json.dumps({
            "type": "Results", "start": 0.8, "duration": 1.0,
            "is_final": True, "speech_final": True,
            "channel": {"alternatives": [{
                "transcript": "予算はまだ未決定です。", "confidence": 0.98,
            }]},
        }, ensure_ascii=False))
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        assert [event.text for event in events if event.kind == "final"] == [
            "ですけれども。予算はまだ未決定です。"
        ]
        await client.stop()

    asyncio.run(scenario())


def test_word_confidence_marks_risky_final_even_when_chunk_confidence_is_high() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="en",
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 1.2,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [
                            {
                                "transcript": "The budget is approved.",
                                "confidence": 0.96,
                                "words": [
                                    {"word": "the", "punctuated_word": "The", "start": 0.0, "end": 0.2, "confidence": 0.98},
                                    {"word": "budget", "start": 0.2, "end": 0.6, "confidence": 0.42},
                                    {"word": "is", "start": 0.6, "end": 0.8, "confidence": 0.97},
                                    {"word": "approved", "punctuated_word": "approved.", "start": 0.8, "end": 1.2, "confidence": 0.96},
                                ],
                            }
                        ]
                    },
                }
            )
        )
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        final = next(event for event in events if event.kind == "final")
        assert len(final.words) == 4
        assert "low_word_confidence" in final.risk_reasons
        assert "low_transcript_confidence" not in final.risk_reasons
        await client.stop()

    asyncio.run(scenario())


def test_korean_numeric_date_missing_day_suffix_is_marked_risky() -> None:
    malformed = "\uacf5\uac1c\uc77c\uc740 8 \uc6d4 21\ub85c \ud655\uc815\ud569\ub2c8\ub2e4."
    complete = "\uacf5\uac1c\uc77c\uc740 8\uc6d4 20\uc77c\ub85c \ud655\uc815\ud569\ub2c8\ub2e4."
    assert has_malformed_korean_date_format(malformed)
    assert not has_malformed_korean_date_format(complete)
    assert has_explicit_korean_date(complete)

    client = DeepgramStreamingClient(
        api_key="configured-secret",
        language="ko",
    )
    assert "malformed_date_format" in client._quality_risk_reasons(
        malformed,
        0.99,
        (),
        "speech_final",
        (),
    )


def test_incomplete_candidate_timeout_is_bounded_and_marked_risky() -> None:
    async def scenario() -> None:
        socket = FakeSocket()

        async def connector(url: str, **kwargs: Any) -> FakeSocket:
            del url, kwargs
            return socket

        events: list[DeepgramTranscript] = []
        client = DeepgramStreamingClient(
            api_key="configured-secret",
            language="ja",
            incomplete_final_wait_seconds=0.2,
            connector=connector,
        )
        await client.start(events.append)
        await socket.incoming.put(
            json.dumps(
                {
                    "type": "Results",
                    "start": 0.0,
                    "duration": 0.3,
                    "is_final": True,
                    "speech_final": True,
                    "channel": {
                        "alternatives": [{"transcript": "に", "confidence": 0.95}]
                    },
                },
                ensure_ascii=False,
            )
        )
        await _wait_until(lambda: any(event.kind == "final" for event in events))
        final = next(event for event in events if event.kind == "final")
        assert final.boundary_reason == "candidate_timeout"
        assert {"short_fragment", "incomplete_ending", "forced_boundary"}.issubset(
            final.risk_reasons
        )
        assert client.snapshot()["candidate_timeout_count"] == 1
        await client.stop()

    asyncio.run(scenario())


def test_deepgram_environment_settings_and_frontend_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "configured-by-environment")
    monkeypatch.setenv("DEEPGRAM_STT_MODEL", "nova-3")
    monkeypatch.setenv("DEEPGRAM_STT_LANGUAGE", "ja")
    monkeypatch.setenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS", "3.5")
    monkeypatch.setenv("DEEPGRAM_RECONNECT_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("DEEPGRAM_RECONNECT_BASE_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("DEEPGRAM_RECONNECT_MAX_DELAY_SECONDS", "2")
    monkeypatch.setenv("DEEPGRAM_RECONNECT_BUFFER_SECONDS", "4")
    monkeypatch.setenv("DEEPGRAM_STT_INCOMPLETE_FINAL_WAIT_SECONDS", "1.2")
    monkeypatch.setenv("DEEPGRAM_RECHECK_ENABLED", "true")
    monkeypatch.setenv("DEEPGRAM_RECHECK_MODEL", "base")
    monkeypatch.setenv("DEEPGRAM_RECHECK_BUFFER_SECONDS", "15")
    monkeypatch.setenv("DEEPGRAM_RECHECK_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("DEEPGRAM_RECHECK_QUEUE_MAX_SIZE", "3")
    monkeypatch.setenv("DEEPGRAM_RECHECK_LOCAL_FILES_ONLY", "true")
    settings = AppSettings.from_env(tmp_path)
    assert settings.stt_provider == "deepgram"
    assert settings.deepgram_stt_model == "nova-3"
    assert settings.deepgram_max_segment_seconds == 3.5
    assert settings.public_dict()["deepgram"]["configured"] is True
    assert settings.public_dict()["deepgram"]["max_segment_seconds"] == 3.5
    assert settings.deepgram_reconnect_max_attempts == 7
    assert settings.deepgram_reconnect_base_delay_seconds == 0.25
    assert settings.deepgram_reconnect_max_delay_seconds == 2
    assert settings.deepgram_reconnect_buffer_seconds == 4
    assert settings.deepgram_incomplete_final_wait_seconds == 1.2
    assert settings.deepgram_en_incomplete_final_wait_seconds == 1.2
    assert settings.deepgram_ko_incomplete_final_wait_seconds == 1.2
    assert settings.deepgram_incomplete_wait("ja") == 1.2
    assert settings.deepgram_incomplete_wait("en") == 1.2
    assert settings.deepgram_recheck_enabled is True
    assert settings.deepgram_recheck_model == "base"
    assert settings.deepgram_recheck_buffer_seconds == 15
    assert settings.deepgram_recheck_timeout_seconds == 3
    assert settings.deepgram_recheck_queue_max_size == 3
    assert settings.deepgram_recheck_local_files_only is True
    assert settings.public_dict()["deepgram"]["reconnect_max_attempts"] == 7
    assert settings.public_dict()["deepgram"]["reconnect_buffer_seconds"] == 4
    assert settings.public_dict()["deepgram"]["selective_recheck"]["model"] == "base"


def test_deepgram_language_specific_incomplete_grace_defaults_and_overrides(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPGRAM_STT_INCOMPLETE_FINAL_WAIT_SECONDS", raising=False)
    settings = AppSettings.from_env(tmp_path)
    assert settings.deepgram_incomplete_wait("ja") == 0.9
    assert settings.deepgram_incomplete_wait("en") == 0.7
    assert settings.deepgram_incomplete_wait("ko") == 1.5

    monkeypatch.setenv("DEEPGRAM_STT_JA_INCOMPLETE_FINAL_WAIT_SECONDS", "1.0")
    monkeypatch.setenv("DEEPGRAM_STT_EN_INCOMPLETE_FINAL_WAIT_SECONDS", "0.6")
    monkeypatch.setenv("DEEPGRAM_STT_KO_INCOMPLETE_FINAL_WAIT_SECONDS", "0.75")
    overridden = AppSettings.from_env(tmp_path)
    assert overridden.deepgram_incomplete_wait("ja") == 1.0
    assert overridden.deepgram_incomplete_wait("en") == 0.6
    assert overridden.deepgram_incomplete_wait("ko") == 0.75
    profiles = overridden.public_dict()["deepgram"]["language_profiles"]
    assert profiles["ja"]["incomplete_final_wait_seconds"] == 1.0
    assert profiles["en"]["incomplete_final_wait_seconds"] == 0.6
    assert profiles["ko"]["incomplete_final_wait_seconds"] == 0.75

    project = AppSettings.from_env().project_root
    html = (project / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (project / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="sttProviderSelect"' in html
    assert 'id="translationDirectionSelect"' in html
    assert '<option value="en_to_ko">영어 → 한국어</option>' in html
    assert '<option value="ja_to_en">일본어 → 영어</option>' in html
    assert '<option value="en_to_ja">영어 → 일본어</option>' in html
    assert '<option value="ko_to_en">한국어 → 영어</option>' in html
    assert "Deepgram · Nova-3" in html
    assert "stt_provider: state.stt.provider" in javascript
    assert "translation_direction: state.translationDirection" in javascript
    assert "reverseTranslationReady" in javascript
    assert "deepgramConfigured" in javascript
    assert 'state.translationDirection === "en_to_ko"' in javascript
    assert '"ja_to_en"' in javascript
    assert '"en_to_ja"' in javascript


def test_deepgram_language_profiles_auto_follow_translation_direction(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPGRAM_STT_ENDPOINTING_MS", "510")
    monkeypatch.setenv("DEEPGRAM_STT_UTTERANCE_END_MS", "1310")
    monkeypatch.setenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS", "8.1")
    monkeypatch.setenv("DEEPGRAM_STT_EN_ENDPOINTING_MS", "410")
    monkeypatch.setenv("DEEPGRAM_STT_EN_UTTERANCE_END_MS", "1010")
    monkeypatch.setenv("DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS", "6.1")
    monkeypatch.setenv("DEEPGRAM_STT_KO_ENDPOINTING_MS", "460")
    monkeypatch.setenv("DEEPGRAM_STT_KO_UTTERANCE_END_MS", "1210")
    monkeypatch.setenv("DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS", "7.1")
    settings = AppSettings.from_env(tmp_path)
    assert settings.deepgram_profile("ja") == (510, 1310, 8.1)
    assert settings.deepgram_profile("en") == (410, 1010, 6.1)
    assert settings.deepgram_profile("ko") == (460, 1210, 7.1)
    public = settings.public_dict()["deepgram"]
    assert public["checkpoint_seconds"] == 4.0
    assert public["hard_limit_seconds"] == 10.0
    assert public["language_profiles"]["en"]["max_segment_seconds"] == 6.1


def test_deepgram_legacy_global_timing_remains_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPGRAM_STT_ENDPOINTING_MS", "600")
    monkeypatch.setenv("DEEPGRAM_STT_UTTERANCE_END_MS", "1500")
    monkeypatch.setenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS", "9")
    monkeypatch.delenv("DEEPGRAM_STT_EN_ENDPOINTING_MS", raising=False)
    monkeypatch.delenv("DEEPGRAM_STT_EN_UTTERANCE_END_MS", raising=False)
    monkeypatch.delenv("DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS", raising=False)
    settings = AppSettings.from_env(tmp_path)
    assert settings.deepgram_profile("ja") == (600, 1500, 9.0)
    assert settings.deepgram_profile("en") == (600, 1500, 9.0)


@pytest.mark.parametrize(
    "max_setting",
    (
        "DEEPGRAM_STT_MAX_SEGMENT_SECONDS",
        "DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS",
        "DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS",
    ),
)
def test_unset_hard_limit_expands_to_resolved_profile_maximum(
    tmp_path,
    monkeypatch,
    max_setting: str,
) -> None:
    for name in (
        "DEEPGRAM_STT_MAX_SEGMENT_SECONDS",
        "DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS",
        "DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS",
        "DEEPGRAM_STT_HARD_LIMIT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(max_setting, "12")

    settings = AppSettings.from_env(tmp_path)

    assert settings.deepgram_hard_limit_seconds == 12.0


def test_explicit_hard_limit_smaller_than_profile_remains_invalid(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS", "12")
    monkeypatch.setenv("DEEPGRAM_STT_HARD_LIMIT_SECONDS", "10")

    with pytest.raises(ValueError, match="hard limit must cover every language profile"):
        AppSettings.from_env(tmp_path)


def test_automatic_hard_limit_preserves_thirty_second_ceiling(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS", "30")
    monkeypatch.delenv("DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS", raising=False)
    monkeypatch.delenv("DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS", raising=False)
    monkeypatch.delenv("DEEPGRAM_STT_HARD_LIMIT_SECONDS", raising=False)

    assert AppSettings.from_env(tmp_path).deepgram_hard_limit_seconds == 30.0

    monkeypatch.setenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS", "30.1")
    with pytest.raises(ValueError, match="max segment must be between 1 and 30"):
        AppSettings.from_env(tmp_path)


def test_deepgram_idle_diagnostics_show_selected_language_profile(tmp_path) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
        stt_provider="deepgram",
        translation_direction="en_to_ko",
    )
    services = build_services(settings, device_provider=FakeDeviceProvider())
    info = services.controller.public_stt_info()
    assert info["language"] == "en"
    assert info["endpointing_ms"] == 400
    assert info["utterance_end_ms"] == 1000
    assert info["max_segment_seconds"] == 6.0
    assert info["checkpoint_seconds"] == 4.0
    assert info["hard_limit_seconds"] == 10.0
