from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)

SHARE_IDLE_TIMEOUT_SECONDS = 15 * 60
SHARE_HARD_TTL_SECONDS = 8 * 60 * 60
SHARE_QUEUE_MAX_SIZE = 256
SHARE_BATCH_SIZE = 20
SHARE_BATCH_WAIT_SECONDS = 0.12
SHARE_HEARTBEAT_SECONDS = 30.0

LOSSY_SHARE_EVENT_TYPES = {
    "partial_transcript",
    "partial_clear",
    "translation_pending",
    "decision_radar_status",
    "state",
}

RelayRequest = Callable[
    [str, str, Mapping[str, Any] | None, str | None],
    Awaitable[dict[str, Any]],
]


class ShareRelayError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        status_code: int = 503,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _clean_text(value: Any, *, maximum: int = 4_000) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:maximum].rstrip()


def _safe_identifier(value: Any) -> str:
    return _clean_text(value, maximum=128)


def _safe_language(value: Any) -> str:
    language = _clean_text(value, maximum=16).lower()
    return language if language in {"ja", "en", "ko", "mixed", "unknown"} else "unknown"


def _safe_timestamp(value: Any) -> str | None:
    text = _clean_text(value, maximum=64)
    return text or None


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _sanitize_radar_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in value[:100]:
        if not isinstance(raw, Mapping):
            continue
        item_id = _safe_identifier(raw.get("item_id"))
        text = _clean_text(raw.get("text"))
        evidence_raw = raw.get("evidence_segment_ids")
        evidence = (
            [
                identifier
                for identifier in (
                    _safe_identifier(item) for item in evidence_raw[:20]
                )
                if identifier
            ]
            if isinstance(evidence_raw, list)
            else []
        )
        category = _clean_text(raw.get("category"), maximum=32)
        if (
            not item_id
            or not text
            or not evidence
            or category
            not in {
                "decision",
                "action_item",
                "open_question",
                "needs_confirmation",
            }
        ):
            continue
        review_status = _clean_text(raw.get("review_status"), maximum=16)
        lifecycle_status = _clean_text(raw.get("lifecycle_status"), maximum=32)
        items.append(
            {
                "item_id": item_id,
                "category": category,
                "text": text,
                "assignee": _clean_text(raw.get("assignee"), maximum=240) or None,
                "due_date": _clean_text(raw.get("due_date"), maximum=240) or None,
                "confirmation_kind": (
                    _clean_text(raw.get("confirmation_kind"), maximum=32) or None
                ),
                "evidence_segment_ids": list(dict.fromkeys(evidence)),
                "review_status": (
                    review_status
                    if review_status in {"suggested", "approved"}
                    else "suggested"
                ),
                "lifecycle_status": (
                    lifecycle_status
                    if lifecycle_status in {"active", "superseded", "resolved", "retracted"}
                    else "active"
                ),
                "lifecycle_reason": _clean_text(raw.get("lifecycle_reason"), maximum=500) or None,
            }
        )
    return items


def sanitize_share_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Create a new payload containing only fields safe for invited viewers."""

    event_type = _clean_text(event.get("type"), maximum=48)
    public: dict[str, Any] = {
        "type": event_type,
        "event_id": _safe_identifier(event.get("event_id")),
        "timestamp": _safe_timestamp(event.get("timestamp")),
    }

    if event_type == "partial_transcript":
        text = _clean_text(event.get("text"))
        if not text:
            return None
        public.update(
            {
                "utterance_id": _safe_identifier(event.get("utterance_id")),
                "text": text,
                "language": _safe_language(
                    event.get("detected_language", event.get("language"))
                ),
            }
        )
        return public

    if event_type == "partial_clear":
        public["utterance_id"] = _safe_identifier(event.get("utterance_id"))
        return public

    if event_type == "final_transcript":
        segment_id = _safe_identifier(event.get("segment_id"))
        text = _clean_text(event.get("text"))
        if not segment_id or not text:
            return None
        public.update(
            {
                "segment_id": segment_id,
                "text": text,
                "language": _safe_language(
                    event.get("detected_language", event.get("language"))
                ),
                "started_at": _safe_timestamp(event.get("started_at")),
                "ended_at": _safe_timestamp(event.get("ended_at")),
            }
        )
        return public

    if event_type in {"translation_pending", "translation"}:
        segment_id = _safe_identifier(event.get("segment_id"))
        if not segment_id:
            return None
        public["segment_id"] = segment_id
        if event_type == "translation":
            translated = _clean_text(
                event.get("translated_text", event.get("text"))
            )
            if not translated:
                return None
            public["translated_text"] = translated
        return public

    if event_type == "translation_error":
        segment_id = _safe_identifier(event.get("segment_id"))
        if not segment_id:
            return None
        public.update(
            {
                "segment_id": segment_id,
                "message": "번역을 표시하지 못했지만 원문 공유는 계속됩니다.",
            }
        )
        return public

    if event_type == "decision_radar_updated":
        radar = event.get("decision_radar")
        if not isinstance(radar, Mapping):
            return None
        public["decision_radar"] = {
            "status": _clean_text(radar.get("status"), maximum=24) or "idle",
            "revision": _safe_nonnegative_int(radar.get("revision")),
            "updated_at": _safe_timestamp(radar.get("updated_at")),
            "items": _sanitize_radar_items(radar.get("items")),
        }
        return public

    if event_type == "decision_radar_status":
        public.update(
            {
                "status": _clean_text(event.get("status"), maximum=24) or "idle",
                "queue_size": _safe_nonnegative_int(event.get("queue_size")),
            }
        )
        return public

    if event_type == "decision_radar_error":
        public.update(
            {
                "status": "error",
                "message": "Decision Radar 분석이 지연되고 있습니다. 자막 공유는 계속됩니다.",
            }
        )
        return public

    if event_type == "state":
        public["status"] = _clean_text(
            event.get("status", event.get("state")), maximum=24
        )
        return public

    return None


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class ShareRelayManager:
    """Non-blocking, viewer-only relay client for the local application."""

    def __init__(
        self,
        *,
        relay_url: str | None,
        create_secret: str | None,
        request_timeout_seconds: float = 5.0,
        queue_max_size: int = SHARE_QUEUE_MAX_SIZE,
        request_sender: RelayRequest | None = None,
    ) -> None:
        self.relay_url = str(relay_url or "").strip().rstrip("/")
        self._create_secret = str(create_secret or "").strip()
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            max(1, int(queue_max_size))
        )
        self._request_sender = request_sender or self._request_json
        self._worker: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._room_id: str | None = None
        self._host_token: str | None = None
        self._viewer_url: str | None = None
        self._expires_at: str | None = None
        self._status = "unconfigured" if not self.configured else "idle"
        self._last_error_code: str | None = None
        self._last_success_at: str | None = None
        self._last_latency_ms: int | None = None
        self._dropped_events = 0
        self._sent_batches = 0
        self._closed = False

    @property
    def configured(self) -> bool:
        if not self.relay_url or not self._create_secret:
            return False
        parsed = urlparse(self.relay_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @property
    def active(self) -> bool:
        return bool(self._room_id and self._host_token)

    async def start(self) -> None:
        if self._closed or self._worker is not None:
            return
        self._worker = asyncio.create_task(
            self._worker_loop(), name="live-share-relay-worker"
        )

    async def start_share(self) -> dict[str, Any]:
        if not self.configured:
            raise ShareRelayError(
                "share_not_configured",
                "초대 링크 공유 서버가 아직 설정되지 않았습니다.",
                status_code=409,
            )
        if self.active:
            return self.snapshot()
        await self.start()
        async with self._send_lock:
            payload = await self._request_sender(
                "POST",
                "/api/rooms",
                {
                    "retention_policy": "delete_on_stop",
                    "idle_ttl_seconds": SHARE_IDLE_TIMEOUT_SECONDS,
                    "hard_ttl_seconds": SHARE_HARD_TTL_SECONDS,
                },
                self._create_secret,
            )
        room_id = _safe_identifier(payload.get("room_id"))
        host_token = _clean_text(payload.get("host_token"), maximum=256)
        viewer_url = _clean_text(payload.get("viewer_url"), maximum=2_000)
        if not room_id or not host_token or not viewer_url:
            raise ShareRelayError(
                "invalid_relay_response",
                "공유 서버가 올바른 초대 정보를 반환하지 않았습니다.",
            )
        parsed_viewer = urlparse(viewer_url)
        if parsed_viewer.scheme not in {"http", "https"} or not parsed_viewer.netloc:
            raise ShareRelayError(
                "invalid_viewer_url",
                "공유 서버의 초대 링크를 확인할 수 없습니다.",
            )
        self._room_id = room_id
        self._host_token = host_token
        self._viewer_url = viewer_url
        self._expires_at = _safe_timestamp(payload.get("expires_at"))
        self._status = "active"
        self._last_error_code = None
        self._last_success_at = _iso_now()
        if self._heartbeat is None or self._heartbeat.done():
            self._heartbeat = asyncio.create_task(
                self._heartbeat_loop(), name="live-share-relay-heartbeat"
            )
        return self.snapshot()

    async def stop_share(self) -> dict[str, Any]:
        room_id = self._room_id
        host_token = self._host_token
        self._room_id = None
        self._host_token = None
        self._viewer_url = None
        self._expires_at = None
        self._status = "idle" if self.configured else "unconfigured"
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._heartbeat is not None and not self._heartbeat.done():
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
        self._heartbeat = None
        if room_id and host_token:
            try:
                async with self._send_lock:
                    await self._request_sender(
                        "DELETE",
                        f"/api/rooms/{room_id}",
                        None,
                        host_token,
                    )
                self._last_success_at = _iso_now()
                self._last_error_code = None
            except Exception as error:
                self._last_error_code = self._error_code(error)
                LOGGER.warning(
                    "Live share cleanup will rely on relay expiry: %s",
                    type(error).__name__,
                )
        return self.snapshot()

    async def publish_event(self, event: dict[str, Any]) -> None:
        if not self.active:
            return
        sanitized = sanitize_share_event(event)
        if sanitized is None:
            return
        if not self._queue.full():
            self._queue.put_nowait(sanitized)
            return
        if sanitized["type"] in LOSSY_SHARE_EVENT_TYPES:
            self._dropped_events += 1
            return
        retained: list[dict[str, Any]] = []
        removed = False
        while not self._queue.empty():
            queued = self._queue.get_nowait()
            if not removed and queued.get("type") in LOSSY_SHARE_EVENT_TYPES:
                removed = True
                self._dropped_events += 1
                continue
            retained.append(queued)
        for queued in retained:
            if not self._queue.full():
                self._queue.put_nowait(queued)
        if not self._queue.full():
            self._queue.put_nowait(sanitized)
        else:
            self._dropped_events += 1

    async def _worker_loop(self) -> None:
        try:
            while True:
                first = await self._queue.get()
                batch = [first]
                deadline = (
                    asyncio.get_running_loop().time() + SHARE_BATCH_WAIT_SECONDS
                )
                while len(batch) < SHARE_BATCH_SIZE:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(
                                self._queue.get(), timeout=remaining
                            )
                        )
                    except asyncio.TimeoutError:
                        break
                room_id = self._room_id
                host_token = self._host_token
                if not room_id or not host_token:
                    continue
                started = asyncio.get_running_loop().time()
                delivered = False
                for attempt in range(3):
                    try:
                        async with self._send_lock:
                            if room_id != self._room_id or host_token != self._host_token:
                                break
                            await self._request_sender(
                                "POST",
                                f"/api/rooms/{room_id}/events",
                                {"events": batch},
                                host_token,
                            )
                        delivered = True
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        self._last_error_code = self._error_code(error)
                        if isinstance(error, ShareRelayError) and error.status_code in {
                            401,
                            404,
                            410,
                        }:
                            self._status = "expired"
                            self._room_id = None
                            self._host_token = None
                            self._viewer_url = None
                            self._expires_at = None
                            break
                        if attempt < 2:
                            await asyncio.sleep(0.25 * (2**attempt))
                if delivered:
                    self._sent_batches += 1
                    self._status = "active"
                    self._last_error_code = None
                    self._last_success_at = _iso_now()
                    self._last_latency_ms = max(
                        0,
                        round((asyncio.get_running_loop().time() - started) * 1_000),
                    )
                else:
                    self._dropped_events += len(batch)
                    if self.active:
                        self._status = "degraded"
        except asyncio.CancelledError:
            raise

    async def _heartbeat_loop(self) -> None:
        try:
            while self.active:
                await asyncio.sleep(SHARE_HEARTBEAT_SECONDS)
                room_id = self._room_id
                host_token = self._host_token
                if not room_id or not host_token:
                    return
                try:
                    async with self._send_lock:
                        await self._request_sender(
                            "POST",
                            f"/api/rooms/{room_id}/heartbeat",
                            {},
                            host_token,
                        )
                    self._last_success_at = _iso_now()
                    self._last_error_code = None
                    if self.active:
                        self._status = "active"
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._last_error_code = self._error_code(error)
                    if self.active:
                        self._status = "degraded"
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, ShareRelayError):
            return error.code
        return "relay_unreachable"

    async def _request_json(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        bearer: str | None,
    ) -> dict[str, Any]:
        url = urljoin(f"{self.relay_url}/", path.lstrip("/"))
        payload = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )

        def perform() -> dict[str, Any]:
            headers = {"Accept": "application/json"}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            request = Request(url, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.request_timeout_seconds) as response:
                    raw = response.read(256_000)
                    if not raw:
                        return {}
                    decoded = json.loads(raw.decode("utf-8"))
                    return decoded if isinstance(decoded, dict) else {}
            except HTTPError as error:
                raise ShareRelayError(
                    "relay_http_error",
                    "공유 서버가 요청을 처리하지 못했습니다.",
                    status_code=int(error.code),
                ) from None
            except (URLError, TimeoutError, OSError) as error:
                raise ShareRelayError(
                    "relay_unreachable",
                    "공유 서버에 연결하지 못했습니다. 원문 전사와 번역은 계속됩니다.",
                ) from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ShareRelayError(
                    "invalid_relay_response",
                    "공유 서버 응답을 확인하지 못했습니다.",
                ) from error

        return await asyncio.to_thread(perform)

    def snapshot(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "active": self.active,
            "status": self._status,
            "viewer_url": self._viewer_url if self.active else None,
            "expires_at": self._expires_at if self.active else None,
            "retention_policy": "delete_on_stop",
            "idle_timeout_seconds": SHARE_IDLE_TIMEOUT_SECONDS,
            "hard_ttl_seconds": SHARE_HARD_TTL_SECONDS,
            "external_transmission": True,
            "shared_data": [
                "partial_transcript",
                "final_transcript",
                "translation",
                "decision_radar",
            ],
            "excluded_data": [
                "audio",
                "api_keys",
                "provider_settings",
                "past_sessions",
            ],
            "queue_size": self._queue.qsize(),
            "queue_max_size": self._queue.maxsize,
            "dropped_events": self._dropped_events,
            "sent_batches": self._sent_batches,
            "last_success_at": self._last_success_at,
            "last_latency_ms": self._last_latency_ms,
            "last_error_code": self._last_error_code,
        }

    async def shutdown(self) -> None:
        if self._closed:
            return
        await self.stop_share()
        self._closed = True
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
