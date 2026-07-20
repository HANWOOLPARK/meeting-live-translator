from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return local_now().isoformat(timespec="milliseconds")


def make_event(event_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "event_id": str(uuid4()),
        "timestamp": iso_now(),
        **fields,
    }


def state_event(status: str, **fields: Any) -> dict[str, Any]:
    return make_event("state", status=status, **fields)


def error_event(
    code: str,
    message: str,
    *,
    recoverable: bool = True,
    **fields: Any,
) -> dict[str, Any]:
    return make_event(
        "error",
        code=code,
        message=message,
        recoverable=recoverable,
        status="error",
        **fields,
    )

