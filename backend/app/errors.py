from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SafeAppError(Exception):
    code: str
    message: str
    status_code: int = 400
    recoverable: bool = True

    def __str__(self) -> str:
        return self.message

    def as_dict(self, request_id: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if request_id:
            payload["request_id"] = request_id
        return payload


def exception_kind(exc: BaseException) -> str:
    """Return a safe diagnostic label without paths or exception contents."""

    return type(exc).__name__

