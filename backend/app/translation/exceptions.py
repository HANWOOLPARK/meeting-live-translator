"""Safe, provider-independent translation error taxonomy."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any


class TranslationErrorCode(str, Enum):
    API_KEY_MISSING = "API_KEY_MISSING"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"
    QUEUE_FULL = "QUEUE_FULL"
    CANCELLED = "CANCELLED"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    GEMINI_API_KEY_MISSING = "GEMINI_API_KEY_MISSING"
    GEMINI_MODEL_NOT_CONFIGURED = "GEMINI_MODEL_NOT_CONFIGURED"
    GEMINI_SDK_UNAVAILABLE = "GEMINI_SDK_UNAVAILABLE"
    GEMINI_AUTHENTICATION_FAILED = "GEMINI_AUTHENTICATION_FAILED"
    GEMINI_PERMISSION_DENIED = "GEMINI_PERMISSION_DENIED"
    GEMINI_MODEL_NOT_FOUND = "GEMINI_MODEL_NOT_FOUND"
    GEMINI_RATE_LIMITED = "GEMINI_RATE_LIMITED"
    GEMINI_QUOTA_EXHAUSTED = "GEMINI_QUOTA_EXHAUSTED"
    GEMINI_REQUEST_TIMEOUT = "GEMINI_REQUEST_TIMEOUT"
    GEMINI_NETWORK_ERROR = "GEMINI_NETWORK_ERROR"
    GEMINI_EMPTY_RESPONSE = "GEMINI_EMPTY_RESPONSE"
    GEMINI_INVALID_RESPONSE = "GEMINI_INVALID_RESPONSE"
    GEMINI_PROVIDER_UNAVAILABLE = "GEMINI_PROVIDER_UNAVAILABLE"
    GEMINI_UNKNOWN_ERROR = "GEMINI_UNKNOWN_ERROR"


SAFE_ERROR_MESSAGES: dict[TranslationErrorCode, str] = {
    TranslationErrorCode.API_KEY_MISSING: "OPENAI_API_KEY가 설정되지 않았습니다.",
    TranslationErrorCode.AUTHENTICATION_FAILED: "번역 API 인증에 실패했습니다.",
    TranslationErrorCode.RATE_LIMITED: "번역 API 요청 한도를 초과했습니다.",
    TranslationErrorCode.REQUEST_TIMEOUT: "번역 요청 시간이 초과되었습니다.",
    TranslationErrorCode.NETWORK_ERROR: "번역 서버에 연결하지 못했습니다.",
    TranslationErrorCode.INVALID_RESPONSE: "번역 서버가 올바른 번역문을 반환하지 않았습니다.",
    TranslationErrorCode.PROVIDER_UNAVAILABLE: "선택한 번역 방식을 현재 사용할 수 없습니다.",
    TranslationErrorCode.UNKNOWN_PROVIDER_ERROR: "번역 처리 중 오류가 발생했습니다.",
    TranslationErrorCode.QUEUE_FULL: "번역 대기열이 가득 차 번역 작업을 등록하지 못했습니다.",
    TranslationErrorCode.CANCELLED: "번역 작업이 취소되었습니다.",
    TranslationErrorCode.UNSUPPORTED_LANGUAGE: "감지된 언어는 현재 번역 대상이 아닙니다.",
    TranslationErrorCode.GEMINI_API_KEY_MISSING: "GEMINI_API_KEY가 설정되지 않았습니다.",
    TranslationErrorCode.GEMINI_MODEL_NOT_CONFIGURED: "GEMINI_TRANSLATION_MODEL이 설정되지 않았습니다.",
    TranslationErrorCode.GEMINI_SDK_UNAVAILABLE: "Google Gen AI Python SDK를 사용할 수 없습니다.",
    TranslationErrorCode.GEMINI_AUTHENTICATION_FAILED: "Gemini API 인증에 실패했습니다.",
    TranslationErrorCode.GEMINI_PERMISSION_DENIED: "Gemini API 사용 권한이 없습니다.",
    TranslationErrorCode.GEMINI_MODEL_NOT_FOUND: "설정한 Gemini 번역 모델을 찾을 수 없습니다.",
    TranslationErrorCode.GEMINI_RATE_LIMITED: "Gemini API 요청 한도를 초과했습니다.",
    TranslationErrorCode.GEMINI_QUOTA_EXHAUSTED: "Gemini API 할당량이 소진되었습니다.",
    TranslationErrorCode.GEMINI_REQUEST_TIMEOUT: "Gemini 번역 요청 시간이 초과되었습니다.",
    TranslationErrorCode.GEMINI_NETWORK_ERROR: "Gemini API 서버에 연결하지 못했습니다.",
    TranslationErrorCode.GEMINI_EMPTY_RESPONSE: "Gemini API가 빈 번역 응답을 반환했습니다.",
    TranslationErrorCode.GEMINI_INVALID_RESPONSE: "Gemini API 응답 형식이 올바르지 않습니다.",
    TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE: "Gemini 번역 Provider를 현재 사용할 수 없습니다.",
    TranslationErrorCode.GEMINI_UNKNOWN_ERROR: "Gemini 번역 중 오류가 발생했습니다.",
}


class TranslationProviderError(RuntimeError):
    """An error safe to expose through REST or WebSocket responses.

    Raw provider exceptions are retained only as ``__cause__`` and are never
    interpolated into this object's string or representation.
    """

    def __init__(
        self,
        code: TranslationErrorCode,
        *,
        recoverable: bool,
        retryable: bool,
    ) -> None:
        self.code = code
        self.safe_message = SAFE_ERROR_MESSAGES[code]
        self.recoverable = bool(recoverable)
        self.retryable = bool(retryable)
        super().__init__(self.safe_message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.safe_message,
            "recoverable": self.recoverable,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code.value!r}, "
            f"recoverable={self.recoverable!r}, retryable={self.retryable!r})"
        )


def translation_error(
    code: TranslationErrorCode,
    *,
    recoverable: bool | None = None,
    retryable: bool | None = None,
) -> TranslationProviderError:
    retry_defaults = {
        TranslationErrorCode.RATE_LIMITED,
        TranslationErrorCode.REQUEST_TIMEOUT,
        TranslationErrorCode.NETWORK_ERROR,
        TranslationErrorCode.INVALID_RESPONSE,
        TranslationErrorCode.PROVIDER_UNAVAILABLE,
        TranslationErrorCode.GEMINI_RATE_LIMITED,
        TranslationErrorCode.GEMINI_REQUEST_TIMEOUT,
        TranslationErrorCode.GEMINI_NETWORK_ERROR,
        TranslationErrorCode.GEMINI_EMPTY_RESPONSE,
        TranslationErrorCode.GEMINI_INVALID_RESPONSE,
        TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE,
    }
    nonrecoverable_defaults = {
        TranslationErrorCode.AUTHENTICATION_FAILED,
        TranslationErrorCode.API_KEY_MISSING,
        TranslationErrorCode.UNSUPPORTED_LANGUAGE,
        TranslationErrorCode.GEMINI_API_KEY_MISSING,
        TranslationErrorCode.GEMINI_MODEL_NOT_CONFIGURED,
        TranslationErrorCode.GEMINI_SDK_UNAVAILABLE,
        TranslationErrorCode.GEMINI_AUTHENTICATION_FAILED,
        TranslationErrorCode.GEMINI_PERMISSION_DENIED,
        TranslationErrorCode.GEMINI_MODEL_NOT_FOUND,
        TranslationErrorCode.GEMINI_QUOTA_EXHAUSTED,
    }
    return TranslationProviderError(
        code,
        recoverable=(code not in nonrecoverable_defaults if recoverable is None else recoverable),
        retryable=(code in retry_defaults if retryable is None else retryable),
    )


def normalize_provider_error(error: BaseException) -> TranslationProviderError:
    """Classify an SDK/runtime error without copying its message or payload."""

    if isinstance(error, TranslationProviderError):
        return error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return translation_error(TranslationErrorCode.REQUEST_TIMEOUT)

    name = type(error).__name__.lower()
    status_code: Any = getattr(error, "status_code", None)
    if "authentication" in name or status_code in {401, 403}:
        return translation_error(TranslationErrorCode.AUTHENTICATION_FAILED)
    if "ratelimit" in name or status_code == 429:
        return translation_error(TranslationErrorCode.RATE_LIMITED)
    if "timeout" in name:
        return translation_error(TranslationErrorCode.REQUEST_TIMEOUT)
    if (
        "connection" in name
        or "network" in name
        or isinstance(error, (ConnectionError, OSError))
    ):
        return translation_error(TranslationErrorCode.NETWORK_ERROR)
    if "internalserver" in name or (isinstance(status_code, int) and status_code >= 500):
        return translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
    return translation_error(
        TranslationErrorCode.UNKNOWN_PROVIDER_ERROR,
        recoverable=True,
        retryable=False,
    )


__all__ = [
    "SAFE_ERROR_MESSAGES",
    "TranslationErrorCode",
    "TranslationProviderError",
    "normalize_provider_error",
    "translation_error",
]
