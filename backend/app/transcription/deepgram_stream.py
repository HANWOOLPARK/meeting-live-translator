"""Minimal Deepgram live transcription client built on the existing websocket runtime."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol
from urllib.parse import urlencode


LOGGER = logging.getLogger(__name__)
_AUDIO_SEND_TIMEOUT_SECONDS = 2.0
_CONTROL_SEND_TIMEOUT_SECONDS = 0.5
_FINALIZE_RESPONSE_TIMEOUT_SECONDS = 1.0
_OFFSET_TOLERANCE_SECONDS = 0.05
_INCOMPLETE_FINAL_WAIT_SECONDS = 0.9
_MALFORMED_KOREAN_DATE_RE = re.compile(
    r"(?:\uacf5\uac1c\uc77c|\ucd9c\uc2dc\uc77c|\ub9c8\uac10\uc77c|\uae30\ud55c|\ub0a0\uc9dc|\uc77c\uc815)"
    r"[^.!?\u3002\uff1f\uff01]{0,48}"
    r"(?:0?[1-9]|1[0-2])\s*\uc6d4\s*(?:[1-9]|[12]\d|3[01])\s*\ub85c"
    r"(?=\s|[,\.!?]|$)"
)
_EXPLICIT_KOREAN_DATE_RE = re.compile(
    r"(?:0?[1-9]|1[0-2])\s*\uc6d4\s*(?:[1-9]|[12]\d|3[01])\s*\uc77c"
)


def has_malformed_korean_date_format(text: str) -> bool:
    """Return true for a dated topic whose numeric day lost the Korean day suffix."""

    return bool(_MALFORMED_KOREAN_DATE_RE.search(str(text)))


def has_explicit_korean_date(text: str) -> bool:
    """Return true when a numeric Korean month/day expression keeps its day suffix."""

    return bool(_EXPLICIT_KOREAN_DATE_RE.search(str(text)))


@dataclass(frozen=True, slots=True)
class DeepgramWord:
    word: str
    punctuated_word: str
    confidence: float
    started_offset: float
    ended_offset: float


@dataclass(frozen=True, slots=True)
class DeepgramTranscript:
    kind: str
    text: str
    confidence: float
    started_offset: float
    ended_offset: float
    words: tuple[DeepgramWord, ...] = field(default_factory=tuple)
    boundary_reason: str = "interim"
    risk_reasons: tuple[str, ...] = field(default_factory=tuple)


TranscriptSink = Callable[[DeepgramTranscript], Awaitable[None] | None]
ErrorSink = Callable[[str], Awaitable[None] | None]


class _WebSocket(Protocol):
    async def send(self, message: str | bytes) -> None: ...
    async def close(self) -> None: ...
    def __aiter__(self) -> Any: ...


Connector = Callable[..., Awaitable[_WebSocket]]


class DeepgramStreamError(RuntimeError):
    """Safe operational failure without request or credential contents."""


class DeepgramStreamingClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "nova-3",
        language: str = "ja",
        sample_rate: int = 16_000,
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1_000,
        max_segment_seconds: float = 8.0,
        checkpoint_seconds: float = 4.0,
        hard_limit_seconds: float = 10.0,
        open_timeout_seconds: float = 10.0,
        finalize_response_timeout_seconds: float = _FINALIZE_RESPONSE_TIMEOUT_SECONDS,
        incomplete_final_wait_seconds: float = _INCOMPLETE_FINAL_WAIT_SECONDS,
        keyterms: Iterable[str] = (),
        connector: Connector | None = None,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.model = model.strip()
        self.language = language.strip().lower()
        self.sample_rate = int(sample_rate)
        self.endpointing_ms = int(endpointing_ms)
        self.utterance_end_ms = int(utterance_end_ms)
        self.max_segment_seconds = float(max_segment_seconds)
        self.checkpoint_seconds = float(checkpoint_seconds)
        self.hard_limit_seconds = float(hard_limit_seconds)
        self.open_timeout_seconds = float(open_timeout_seconds)
        self.finalize_response_timeout_seconds = float(
            finalize_response_timeout_seconds
        )
        self.incomplete_final_wait_seconds = float(incomplete_final_wait_seconds)
        self.keyterms = tuple(
            dict.fromkeys(str(value).strip() for value in keyterms if str(value).strip())
        )[:100]
        if not (1.0 <= self.max_segment_seconds <= 30.0):
            raise ValueError("max_segment_seconds must be between 1 and 30")
        if not (1.0 <= self.checkpoint_seconds <= 10.0):
            raise ValueError("checkpoint_seconds must be between 1 and 10")
        if not (self.max_segment_seconds <= self.hard_limit_seconds <= 30.0):
            raise ValueError(
                "hard_limit_seconds must cover max_segment_seconds and be at most 30"
            )
        if not (0.05 <= self.finalize_response_timeout_seconds <= 5.0):
            raise ValueError(
                "finalize_response_timeout_seconds must be between 0.05 and 5"
            )
        if not (0.2 <= self.incomplete_final_wait_seconds <= 3.0):
            raise ValueError(
                "incomplete_final_wait_seconds must be between 0.2 and 3"
            )
        self._connector = connector
        self._socket: _WebSocket | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._transcript_sink: TranscriptSink | None = None
        self._error_sink: ErrorSink | None = None
        self._committed: list[str] = []
        self._committed_start: float | None = None
        self._committed_end = 0.0
        self._committed_confidence: list[float] = []
        self._committed_words: list[DeepgramWord] = []
        self._committed_duration_seconds = 0.0
        self._audio_sent_seconds = 0.0
        self._active_transcript_start: float | None = None
        self._last_checkpoint_audio_seconds = 0.0
        self._latest_partial: DeepgramTranscript | None = None
        self._finalize_pending = False
        self._finalize_pending_reason: str | None = None
        self._finalize_requested_at_audio_seconds = 0.0
        self._finalize_request_serial = 0
        self._finalize_watchdog: asyncio.Task[None] | None = None
        self._candidate_watchdog: asyncio.Task[None] | None = None
        self._candidate_serial = 0
        self._candidate_held = False
        self._candidate_hold_reasons: tuple[str, ...] = ()
        self._candidate_hold_deadline: float | None = None
        self._candidate_held_count = 0
        self._candidate_merged_count = 0
        self._candidate_timeout_count = 0
        self._discard_results_through_offset = 0.0
        self._last_final_text = ""
        self._connected = False
        self._closing = False
        self._last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def connected(self) -> bool:
        return self._connected

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": "deepgram",
            "configured": self.configured,
            "connected": self._connected,
            "model": self.model,
            "language": self.language,
            "streaming": True,
            "interim_results": True,
            "smart_format": True,
            "endpointing_ms": self.endpointing_ms,
            "utterance_end_ms": self.utterance_end_ms,
            "max_segment_seconds": self.max_segment_seconds,
            "checkpoint_seconds": self.checkpoint_seconds,
            "hard_limit_seconds": self.hard_limit_seconds,
            "incomplete_final_wait_seconds": self.incomplete_final_wait_seconds,
            "keyterm_count": len(self.keyterms),
            "candidate_held_count": self._candidate_held_count,
            "candidate_merged_count": self._candidate_merged_count,
            "candidate_timeout_count": self._candidate_timeout_count,
            "last_error": self._last_error,
        }

    def _url(self) -> str:
        query = urlencode(
            {
                "model": self.model,
                "language": self.language,
                "encoding": "linear16",
                "sample_rate": self.sample_rate,
                "channels": 1,
                "interim_results": "true",
                "smart_format": "true",
                "punctuate": "true",
                "endpointing": self.endpointing_ms,
                "utterance_end_ms": self.utterance_end_ms,
                "vad_events": "true",
            }
        )
        if self.keyterms:
            query = f"{query}&{urlencode([('keyterm', value) for value in self.keyterms])}"
        return f"wss://api.deepgram.com/v1/listen?{query}"

    async def start(
        self,
        transcript_sink: TranscriptSink,
        error_sink: ErrorSink | None = None,
    ) -> None:
        if self._connected:
            return
        if not self.configured:
            raise DeepgramStreamError("deepgram_api_key_missing")
        connector = self._connector
        if connector is None:
            from websockets.asyncio.client import connect

            connector = connect
        self._transcript_sink = transcript_sink
        self._error_sink = error_sink
        self._reset_stream_state()
        self._last_error = None
        self._closing = False
        try:
            self._socket = await connector(
                self._url(),
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=self.open_timeout_seconds,
                ping_interval=20,
                ping_timeout=20,
                compression=None,
                max_size=1_048_576,
            )
        except Exception as error:
            self._last_error = "connection_failed"
            raise DeepgramStreamError("deepgram_connection_failed") from error
        self._connected = True
        self._receiver = asyncio.create_task(
            self._receive_loop(), name="deepgram-transcript-receiver"
        )

    async def send_audio(self, pcm16_mono: bytes) -> None:
        if not pcm16_mono:
            return
        socket = self._socket
        if not self._connected or socket is None:
            raise DeepgramStreamError("deepgram_not_connected")
        try:
            await asyncio.wait_for(
                socket.send(pcm16_mono),
                timeout=_AUDIO_SEND_TIMEOUT_SECONDS,
            )
            self._audio_sent_seconds += len(pcm16_mono) / (2 * self.sample_rate)
            if self._active_transcript_start is None:
                return
            utterance_elapsed = (
                self._audio_sent_seconds - self._active_transcript_start
            )
            checkpoint_elapsed = self._audio_sent_seconds - max(
                self._active_transcript_start,
                self._last_checkpoint_audio_seconds,
            )
            if checkpoint_elapsed >= self.checkpoint_seconds:
                # This is only a UI checkpoint. Deepgram interim text is already
                # displayed, while avoiding provider Finalize lets later words
                # still correct dates, names, and particles in the hypothesis.
                self._last_checkpoint_audio_seconds = self._audio_sent_seconds
            # A hard-limit result that still ends in a connector or auxiliary
            # gets one short grace window. Repeated Finalize requests during
            # that window would defeat the assembler and can create duplicate
            # provider acknowledgements.
            if self._candidate_held:
                return
            if (
                not self._finalize_pending
                and utterance_elapsed >= self.hard_limit_seconds
            ):
                await self._request_finalize(socket, reason="hard")
        except Exception as error:
            self._connected = False
            self._last_error = "audio_send_failed"
            await self._notify_error("deepgram_audio_send_failed")
            raise DeepgramStreamError("deepgram_audio_send_failed") from error

    async def stop(self) -> None:
        socket = self._socket
        receiver = self._receiver
        self._closing = True
        if socket is not None:
            try:
                if self._connected:
                    if not self._finalize_pending:
                        await self._request_finalize(socket, reason="stop")
                    # Give Deepgram a short chance to return the stable tail.
                    # The latest partial is promoted below if no reply arrives.
                    await asyncio.sleep(0.2)
                    await asyncio.wait_for(
                        socket.send(json.dumps({"type": "CloseStream"})),
                        timeout=_CONTROL_SEND_TIMEOUT_SECONDS,
                    )
            except Exception:
                pass
        if receiver is not None and not receiver.done():
            try:
                await asyncio.wait_for(asyncio.shield(receiver), timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
        await self._flush_final(include_interim=True, boundary_reason="stop")
        self._cancel_finalize_watchdog()
        self._cancel_candidate_watchdog()
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                pass
        self._socket = None
        self._receiver = None
        self._connected = False
        self._closing = False

    async def _receive_loop(self) -> None:
        socket = self._socket
        if socket is None:
            return
        try:
            async for raw in socket:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                await self._handle_message(payload)
            if not self._closing:
                self._last_error = "connection_lost"
                await self._notify_error("deepgram_connection_lost")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._closing:
                self._last_error = "connection_lost"
                await self._notify_error("deepgram_connection_lost")
        finally:
            self._connected = False

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        message_type = str(payload.get("type", ""))
        if message_type == "UtteranceEnd":
            await self._handle_utterance_end()
            return
        if message_type == "Error":
            self._last_error = "provider_error"
            await self._notify_error("deepgram_provider_error")
            return
        if message_type != "Results":
            return

        channel = payload.get("channel")
        alternatives = (
            channel.get("alternatives", []) if isinstance(channel, dict) else []
        )
        alternative = (
            alternatives[0]
            if alternatives and isinstance(alternatives[0], dict)
            else {}
        )
        text = str(alternative.get("transcript", "")).strip()
        confidence = max(
            0.0,
            min(1.0, self._bounded_float(alternative.get("confidence"), 0.0)),
        )
        started = max(0.0, self._bounded_float(payload.get("start"), 0.0))
        duration = max(0.0, self._bounded_float(payload.get("duration"), 0.0))
        ended = started + duration
        words = self._parse_words(alternative.get("words"))

        finalize_reason: str | None = None
        if bool(payload.get("from_finalize")):
            finalize_reason = self._acknowledge_finalize()
        elif (
            self._finalize_pending
            and bool(payload.get("is_final"))
            and ended + _OFFSET_TOLERANCE_SECONDS
            >= self._finalize_requested_at_audio_seconds
        ):
            # A stable result covering the requested boundary also acts as an
            # acknowledgement when Deepgram omits from_finalize.
            finalize_reason = self._acknowledge_finalize()

        if not text:
            if finalize_reason in {"hard", "stop"} or payload.get("speech_final"):
                await self._flush_final(
                    include_interim=True,
                    boundary_reason=(
                        "hard_limit"
                        if finalize_reason == "hard"
                        else "stop"
                        if finalize_reason == "stop"
                        else "speech_final"
                    ),
                )
            return
        text, started, words = self._remove_finalized_overlap(
            text,
            started,
            ended,
            words,
        )
        if not text:
            return

        if self._active_transcript_start is None:
            self._active_transcript_start = started
        else:
            self._active_transcript_start = min(
                self._active_transcript_start,
                started,
            )

        is_final = bool(payload.get("is_final"))
        if self._candidate_held and not is_final:
            # Deepgram can emit a short speech_final for the first syllable or
            # noun phrase of a longer sentence, then continue with interim
            # hypotheses. Treat that activity as proof that the utterance is
            # still alive instead of promoting the candidate on the original
            # short grace timer. The absolute hard-limit deadline remains in
            # force, so a continuous stream cannot hold a candidate forever.
            self._refresh_candidate_hold()

        if is_final:
            if self._candidate_held:
                self._candidate_merged_count += 1
                if self._should_replace_short_candidate(text):
                    self._discard_committed_candidate(started)
                self._clear_candidate_hold()
            self._committed.append(text)
            self._committed_start = (
                started
                if self._committed_start is None
                else min(self._committed_start, started)
            )
            self._committed_end = max(self._committed_end, ended)
            self._committed_confidence.append(confidence)
            self._committed_words.extend(words)
            self._committed_duration_seconds += duration
            committed_text = self._joined_committed()
            committed_duration = max(
                self._committed_duration_seconds,
                max(0.0, self._committed_end - (self._committed_start or 0.0)),
            )
            incomplete_reasons = self._incomplete_reasons(committed_text)
            sentence_complete = (
                committed_duration >= 1.0
                and committed_text.rstrip().endswith(
                    (".", "?", "!", "\u3002", "\uff1f", "\uff01")
                )
                and not incomplete_reasons
            )
            clause_boundary = (
                committed_duration >= self.max_segment_seconds
                and committed_text.rstrip().endswith(
                    (",", "\uff0c", "\u3001", ";", "\uff1b", ":", "\uff1a")
                )
            )
            hard_limit_reached = (
                committed_duration >= self.hard_limit_seconds
                or finalize_reason == "hard"
            )
            speech_final = bool(payload.get("speech_final"))
            if hard_limit_reached and incomplete_reasons:
                await self._hold_incomplete_final(
                    tuple(dict.fromkeys((*incomplete_reasons, "forced_boundary")))
                )
                await self._emit_partial(
                    DeepgramTranscript(
                        kind="partial",
                        text=committed_text,
                        confidence=self._average_confidence(),
                        started_offset=self._committed_start or 0.0,
                        ended_offset=self._committed_end,
                        words=tuple(self._committed_words),
                        boundary_reason="candidate_hold",
                        risk_reasons=tuple(
                            dict.fromkeys((*incomplete_reasons, "forced_boundary"))
                        ),
                    )
                )
            elif hard_limit_reached:
                # Provider acknowledgements can carry speech_final as well as
                # from_finalize. The locally requested hard cap is the more
                # precise product boundary and must remain observable.
                await self._flush_final(boundary_reason="hard_limit")
            elif speech_final and incomplete_reasons:
                await self._hold_incomplete_final(incomplete_reasons)
                await self._emit_partial(
                    DeepgramTranscript(
                        kind="partial",
                        text=committed_text,
                        confidence=self._average_confidence(),
                        started_offset=self._committed_start or 0.0,
                        ended_offset=self._committed_end,
                        words=tuple(self._committed_words),
                        boundary_reason="candidate_hold",
                        risk_reasons=incomplete_reasons,
                    )
                )
            elif speech_final:
                await self._flush_final(boundary_reason="speech_final")
            elif sentence_complete:
                await self._flush_final(boundary_reason="sentence")
            elif clause_boundary:
                await self._flush_final(boundary_reason="clause")
            elif finalize_reason == "stop":
                await self._flush_final(boundary_reason="stop")
            else:
                await self._emit_partial(
                    DeepgramTranscript(
                        kind="partial",
                        text=committed_text,
                        confidence=self._average_confidence(),
                        started_offset=self._committed_start or 0.0,
                        ended_offset=self._committed_end,
                        words=tuple(self._committed_words),
                    )
                )
            return

        combined = self._join_text(self._joined_committed(), text)
        await self._emit_partial(
            DeepgramTranscript(
                kind="partial",
                text=combined,
                confidence=confidence,
                started_offset=(
                    self._committed_start
                    if self._committed_start is not None
                    else started
                ),
                ended_offset=max(self._committed_end, ended),
                words=tuple(self._committed_words) + words,
            )
        )
        if finalize_reason in {"hard", "stop"}:
            await self._flush_final(
                include_interim=True,
                boundary_reason=("hard_limit" if finalize_reason == "hard" else "stop"),
            )

    async def _request_finalize(self, socket: _WebSocket, *, reason: str) -> None:
        await asyncio.wait_for(
            socket.send(json.dumps({"type": "Finalize"})),
            timeout=_CONTROL_SEND_TIMEOUT_SECONDS,
        )
        self._finalize_pending = True
        self._finalize_pending_reason = reason
        self._finalize_requested_at_audio_seconds = self._audio_sent_seconds
        self._finalize_request_serial += 1
        if reason == "hard":
            serial = self._finalize_request_serial
            self._cancel_finalize_watchdog()
            self._finalize_watchdog = asyncio.create_task(
                self._finalize_timeout(serial),
                name="deepgram-finalize-watchdog",
            )

    async def _finalize_timeout(self, serial: int) -> None:
        try:
            await asyncio.sleep(self.finalize_response_timeout_seconds)
        except asyncio.CancelledError:
            return
        if (
            self._finalize_pending
            and self._finalize_pending_reason == "hard"
            and self._finalize_request_serial == serial
        ):
            # A missing/empty provider acknowledgement must not leave the UI
            # and translation queue waiting forever. Promote exactly the text
            # already visible to the user and ignore a later stale response.
            self._clear_finalize_pending()
            await self._flush_final(
                include_interim=True,
                boundary_reason="hard_limit",
            )

    def _acknowledge_finalize(self) -> str | None:
        if not self._finalize_pending:
            return None
        reason = self._finalize_pending_reason
        self._clear_finalize_pending()
        return reason

    def _clear_finalize_pending(self) -> None:
        self._finalize_pending = False
        self._finalize_pending_reason = None
        self._finalize_requested_at_audio_seconds = 0.0
        task = self._finalize_watchdog
        self._finalize_watchdog = None
        if task is not None and not task.done():
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current:
                task.cancel()

    def _cancel_finalize_watchdog(self) -> None:
        task = self._finalize_watchdog
        self._finalize_watchdog = None
        if task is not None and not task.done():
            task.cancel()

    async def _flush_final(
        self,
        *,
        include_interim: bool = False,
        boundary_reason: str = "provider",
    ) -> None:
        held_reasons = self._candidate_hold_reasons
        self._clear_candidate_hold()
        text = self._joined_committed()
        started = self._committed_start or 0.0
        ended = self._committed_end
        confidence = self._average_confidence()
        words = tuple(self._committed_words)
        if include_interim and self._latest_partial is not None:
            latest = self._latest_partial
            if latest.ended_offset + _OFFSET_TOLERANCE_SECONDS >= ended:
                text = latest.text
                started = latest.started_offset
                ended = latest.ended_offset
                confidence = latest.confidence
                words = latest.words
        if text:
            risk_reasons = self._quality_risk_reasons(
                text,
                confidence,
                words,
                boundary_reason,
                held_reasons,
            )
            await self._emit(
                DeepgramTranscript(
                    kind="final",
                    text=text,
                    confidence=confidence,
                    started_offset=started,
                    ended_offset=ended,
                    words=words,
                    boundary_reason=boundary_reason,
                    risk_reasons=risk_reasons,
                )
            )
            self._discard_results_through_offset = max(
                self._discard_results_through_offset,
                ended,
            )
            self._last_final_text = text
        self._committed.clear()
        self._committed_start = None
        self._committed_end = 0.0
        self._committed_confidence.clear()
        self._committed_words.clear()
        self._committed_duration_seconds = 0.0
        self._active_transcript_start = None
        self._latest_partial = None
        self._clear_finalize_pending()
        self._last_checkpoint_audio_seconds = self._audio_sent_seconds

    async def _emit_partial(self, event: DeepgramTranscript) -> None:
        self._latest_partial = event
        await self._emit(event)

    async def _emit(self, event: DeepgramTranscript) -> None:
        if self._transcript_sink is None or not event.text.strip():
            return
        result = self._transcript_sink(event)
        if inspect.isawaitable(result):
            await result

    async def _notify_error(self, code: str) -> None:
        if self._error_sink is None:
            return
        result = self._error_sink(code)
        if inspect.isawaitable(result):
            await result

    async def _handle_utterance_end(self) -> None:
        text = self._joined_committed()
        started = self._committed_start or 0.0
        ended = self._committed_end
        confidence = self._average_confidence()
        words = tuple(self._committed_words)
        if self._latest_partial is not None:
            latest = self._latest_partial
            if latest.ended_offset + _OFFSET_TOLERANCE_SECONDS >= ended:
                text = latest.text
                started = latest.started_offset
                ended = latest.ended_offset
                confidence = latest.confidence
                words = latest.words
        reasons = self._incomplete_reasons(text)
        if text and reasons:
            # UtteranceEnd can be a short acoustic pause rather than a true
            # grammatical boundary. Keep the already visible candidate and
            # allow the next stable result to finish it.
            if not self._candidate_held:
                await self._hold_incomplete_final(reasons)
                await self._emit_partial(
                    DeepgramTranscript(
                        kind="partial",
                        text=text,
                        confidence=confidence,
                        started_offset=started,
                        ended_offset=ended,
                        words=words,
                        boundary_reason="candidate_hold",
                        risk_reasons=reasons,
                    )
                )
            return
        await self._flush_final(
            include_interim=True,
            boundary_reason="utterance_end",
        )

    def _reset_stream_state(self) -> None:
        self._cancel_finalize_watchdog()
        self._cancel_candidate_watchdog()
        self._committed.clear()
        self._committed_start = None
        self._committed_end = 0.0
        self._committed_confidence.clear()
        self._committed_words.clear()
        self._committed_duration_seconds = 0.0
        self._audio_sent_seconds = 0.0
        self._active_transcript_start = None
        self._last_checkpoint_audio_seconds = 0.0
        self._latest_partial = None
        self._finalize_pending = False
        self._finalize_pending_reason = None
        self._finalize_requested_at_audio_seconds = 0.0
        self._finalize_request_serial = 0
        self._candidate_serial = 0
        self._candidate_held = False
        self._candidate_hold_reasons = ()
        self._candidate_hold_deadline = None
        self._discard_results_through_offset = 0.0
        self._last_final_text = ""

    def _remove_finalized_overlap(
        self,
        text: str,
        started: float,
        ended: float,
        words: tuple[DeepgramWord, ...],
    ) -> tuple[str, float, tuple[DeepgramWord, ...]]:
        cutoff = self._discard_results_through_offset
        if ended <= cutoff + 0.01:
            return "", started, ()
        if started + 0.01 >= cutoff:
            return text, started, words
        remaining_words = tuple(
            word for word in words if word.ended_offset > cutoff + 0.01
        )
        if remaining_words:
            # Deepgram can return a stable hypothesis that overlaps a partial
            # promoted at candidate timeout. Word timestamps let us retain the
            # unseen suffix instead of dropping the whole late hypothesis.
            return (
                self._joined_words(remaining_words),
                max(cutoff, remaining_words[0].started_offset),
                remaining_words,
            )
        if self._last_final_text and text.startswith(self._last_final_text):
            return text[len(self._last_final_text) :].strip(), cutoff, ()
        # An overlapping late hypothesis cannot be split reliably without word
        # timestamps. Ignoring it is safer than duplicating an already persisted
        # and translated segment.
        return "", started, ()

    def _joined_words(self, words: tuple[DeepgramWord, ...]) -> str:
        result = ""
        for word in words:
            result = self._join_text(result, word.punctuated_word or word.word)
        return result

    def _joined_committed(self) -> str:
        result = ""
        for piece in self._committed:
            result = self._join_text(result, piece)
        return result

    def _average_confidence(self) -> float:
        if not self._committed_confidence:
            return 0.0
        return sum(self._committed_confidence) / len(self._committed_confidence)

    async def _hold_incomplete_final(self, reasons: tuple[str, ...]) -> None:
        self._candidate_held = True
        self._candidate_hold_reasons = tuple(dict.fromkeys(reasons))
        self._candidate_hold_deadline = (
            asyncio.get_running_loop().time() + self.hard_limit_seconds
        )
        self._candidate_held_count += 1
        self._schedule_candidate_watchdog()

    def _refresh_candidate_hold(self) -> None:
        if not self._candidate_held:
            return
        self._schedule_candidate_watchdog()

    def _schedule_candidate_watchdog(self) -> None:
        self._candidate_serial += 1
        serial = self._candidate_serial
        self._cancel_candidate_watchdog()
        delay = self.incomplete_final_wait_seconds
        if self._candidate_hold_deadline is not None:
            remaining = max(
                0.0,
                self._candidate_hold_deadline
                - asyncio.get_running_loop().time(),
            )
            delay = min(delay, remaining)
        self._candidate_watchdog = asyncio.create_task(
            self._candidate_timeout(serial, delay),
            name="deepgram-incomplete-final-watchdog",
        )

    async def _candidate_timeout(self, serial: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._candidate_held and self._candidate_serial == serial:
            self._candidate_timeout_count += 1
            await self._flush_final(
                include_interim=True,
                boundary_reason="candidate_timeout",
            )

    def _clear_candidate_hold(self) -> None:
        self._candidate_held = False
        self._candidate_hold_reasons = ()
        self._candidate_hold_deadline = None
        self._cancel_candidate_watchdog()

    def _should_replace_short_candidate(self, next_text: str) -> bool:
        """Drop a low-confidence syllable hypothesis before its stable result.

        This only runs when another stable result has already arrived, so no
        standalone speech is discarded. It prevents Korean fragments such as
        ``십`` + ``시험 도입은 ...`` from becoming duplicated final text.
        """

        if self.language != "ko" or self._average_confidence() >= 0.95:
            return False
        candidate = re.sub(
            r"[^\w\uac00-\ud7af]+",
            "",
            self._joined_committed(),
        )
        following = re.sub(r"[^\w\uac00-\ud7af]+", "", next_text)
        return bool(candidate and following and len(candidate) <= 2)

    def _discard_committed_candidate(self, next_started: float) -> None:
        self._committed.clear()
        self._committed_start = None
        self._committed_end = 0.0
        self._committed_confidence.clear()
        self._committed_words.clear()
        self._committed_duration_seconds = 0.0
        self._active_transcript_start = next_started
        self._latest_partial = None

    def _cancel_candidate_watchdog(self) -> None:
        task = self._candidate_watchdog
        self._candidate_watchdog = None
        if task is not None and not task.done():
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current:
                task.cancel()

    def _incomplete_reasons(self, text: str) -> tuple[str, ...]:
        stripped = text.strip()
        if not stripped:
            return ()
        has_terminal = stripped.endswith((".", "?", "!", "。", "？", "！"))
        semantic = stripped.rstrip(" \t\r\n.!?。？！").strip()
        folded = re.sub(r"[\s\W_]+", "", semantic, flags=re.UNICODE).casefold()
        acknowledgements = {
            "ja": {"はい", "いいえ", "了解", "承知しました", "わかりました"},
            "en": {"yes", "no", "okay", "ok", "thanks", "agreed"},
            "ko": {"네", "아니요", "좋아요", "알겠습니다", "동의합니다"},
        }.get(self.language, set())
        if folded in {value.casefold() for value in acknowledgements}:
            return ()

        reasons: list[str] = []
        if self.language == "ja":
            if (not has_terminal and len(folded) <= 2) or folded in {
                "先日", "本日", "今回", "次回"
            }:
                reasons.append("short_fragment")
            particle_endings = (
                "は", "が", "を", "に", "で", "と", "の", "も", "へ", "や",
                "から", "まで", "ので", "けど", "そして", "また", "及び", "て",
            )
            connector_endings = (
                "けれども", "けれど", "けども", "ですが", "だが", "のですが",
                "という", "っていう", "について", "に関して", "一方で",
            )
            auxiliary_endings = ("させ", "いただい", "しており")
            if (
                (not has_terminal and semantic.endswith(particle_endings))
                or semantic.endswith(connector_endings)
                or (not has_terminal and semantic.endswith(auxiliary_endings))
            ):
                reasons.append("incomplete_ending")
        elif self.language == "en":
            tokens = re.findall(r"[A-Za-z0-9']+", semantic.casefold())
            if len(tokens) <= 1 and not has_terminal:
                reasons.append("short_fragment")
            if tokens and tokens[-1] in {
                "and", "or", "but", "because", "to", "of", "for", "with",
                "that", "which", "the", "a", "an", "in", "on", "at", "by", "from",
            }:
                reasons.append("incomplete_ending")
        elif self.language == "ko":
            if len(folded) <= 2 and not has_terminal:
                reasons.append("short_fragment")
            particle_or_connector = semantic.endswith(
                ("은", "는", "이", "가", "을", "를", "에", "에서", "와", "과", "도", "로", "으로", "그리고", "하지만", "때문에")
            )
            trailing_clause_mark = semantic.endswith((",", "，", ";", "；", ":", "："))
            complete_endings = (
                "습니다", "ㅂ니다", "입니다", "합니다", "됩니다", "됐습니다",
                "겠습니다", "주세요", "하세요", "해요", "예요", "이에요",
                "네요", "군요", "죠", "지요", "했다", "한다", "된다",
                "있다", "없다", "맞다", "아니다", "겠다", "다",
            )
            if (
                particle_or_connector
                or trailing_clause_mark
                or (not has_terminal and not semantic.endswith(complete_endings))
            ):
                reasons.append("incomplete_ending")
        return tuple(dict.fromkeys(reasons))

    def _quality_risk_reasons(
        self,
        text: str,
        confidence: float,
        words: tuple[DeepgramWord, ...],
        boundary_reason: str,
        held_reasons: tuple[str, ...],
    ) -> tuple[str, ...]:
        reasons = list(self._incomplete_reasons(text))
        if confidence < 0.86:
            reasons.append("low_transcript_confidence")
        if words:
            confidences = [word.confidence for word in words]
            low_ratio = sum(value < 0.80 for value in confidences) / len(confidences)
            if min(confidences) < 0.60 or low_ratio >= 0.25:
                reasons.append("low_word_confidence")
        if boundary_reason in {"hard_limit", "candidate_timeout"}:
            reasons.append("forced_boundary")
        if self.language == "ko" and has_malformed_korean_date_format(text):
            reasons.append("malformed_date_format")
        if boundary_reason == "candidate_timeout":
            reasons.extend(held_reasons)
        return tuple(dict.fromkeys(reasons))

    def _parse_words(self, raw_words: Any) -> tuple[DeepgramWord, ...]:
        if not isinstance(raw_words, list):
            return ()
        words: list[DeepgramWord] = []
        for raw in raw_words:
            if not isinstance(raw, dict):
                continue
            word = str(raw.get("word", "")).strip()
            punctuated = str(raw.get("punctuated_word", word)).strip() or word
            if not word and not punctuated:
                continue
            started = max(0.0, self._bounded_float(raw.get("start"), 0.0))
            ended = max(started, self._bounded_float(raw.get("end"), started))
            confidence = max(
                0.0,
                min(1.0, self._bounded_float(raw.get("confidence"), 0.0)),
            )
            words.append(
                DeepgramWord(
                    word=word or punctuated,
                    punctuated_word=punctuated or word,
                    confidence=confidence,
                    started_offset=started,
                    ended_offset=ended,
                )
            )
        return tuple(words)

    def _join_text(self, left: str, right: str) -> str:
        left, right = left.strip(), right.strip()
        if not left:
            return right
        if not right:
            return left
        if self.language in {"en", "ko"}:
            left, right = self._merge_leading_token_overlap(left, right)
            if not right:
                return left
        closing = ".,?!;:%)]}\u3002\u3001\uff0c\uff1f\uff01\uff1b\uff1a\u300d\u300f\u3011\u3009"
        opening = "([{\u300c\u300e\u3010\u3008"
        if right[0] in closing or left[-1] in opening:
            return f"{left}{right}"
        if self.language == "ja":
            if (
                left[-1].isascii()
                and right[0].isascii()
                and left[-1].isalnum()
                and right[0].isalnum()
            ):
                return f"{left} {right}"
            return f"{left}{right}"
        return f"{left} {right}"

    def _merge_leading_token_overlap(
        self,
        left: str,
        right: str,
    ) -> tuple[str, str]:
        """Merge stable-token overlap inside one provider utterance."""

        left_tokens = list(re.finditer(r"[\w&'-]+", left, flags=re.UNICODE))
        right_tokens = list(re.finditer(r"[\w&'-]+", right, flags=re.UNICODE))
        maximum = min(6, len(left_tokens), len(right_tokens))
        for count in range(maximum, 0, -1):
            left_values = [
                self._overlap_token_value(match.group(0))
                for match in left_tokens[-count:]
            ]
            right_values = [
                self._overlap_token_value(match.group(0))
                for match in right_tokens[:count]
            ]
            if left_values != right_values:
                continue
            raw_left = [
                match.group(0).casefold() for match in left_tokens[-count:]
            ]
            raw_right = [
                match.group(0).casefold() for match in right_tokens[:count]
            ]
            if raw_left != raw_right:
                # Prefer the newer inflected Korean token (과제 -> 과제를)
                # while retaining the already stable prefix.
                stable_prefix = left[: left_tokens[-count].start()].rstrip()
                newer_overlap = right[: right_tokens[count - 1].end()].strip()
                left = self._join_without_overlap(stable_prefix, newer_overlap)
            return left, right[right_tokens[count - 1].end() :].lstrip()
        return left, right

    def _join_without_overlap(self, left: str, right: str) -> str:
        if not left:
            return right
        if not right:
            return left
        if self.language == "ja":
            return f"{left}{right}"
        return f"{left} {right}"

    def _overlap_token_value(self, token: str) -> str:
        value = token.casefold()
        if self.language == "ko" and len(value) > 2:
            value = re.sub(
                r"(?:으로|에서|은|는|이|가|을|를|에|와|과|도|로)$",
                "",
                value,
            )
        return value

    @staticmethod
    def _bounded_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if parsed != parsed or parsed in {float("inf"), float("-inf")}:
            return default
        return parsed


__all__ = [
    "DeepgramWord",
    "DeepgramStreamError",
    "DeepgramStreamingClient",
    "DeepgramTranscript",
]
