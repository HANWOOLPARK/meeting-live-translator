from __future__ import annotations


class SessionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        super().__init__(message)


def invalid_session_id() -> SessionError:
    return SessionError(
        "invalid_session_id",
        "세션 ID가 올바르지 않습니다.",
        status_code=400,
    )


def session_not_found() -> SessionError:
    return SessionError(
        "session_not_found",
        "세션을 찾을 수 없습니다.",
        status_code=404,
    )


def session_storage_failed() -> SessionError:
    return SessionError(
        "session_storage_failed",
        "세션 파일을 안전하게 처리하지 못했습니다.",
        status_code=500,
    )


__all__ = [
    "SessionError",
    "invalid_session_id",
    "session_not_found",
    "session_storage_failed",
]
