"""Sanitized, provider-independent meeting analysis errors."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any


class AnalysisErrorCode(str, Enum):
    API_KEY_MISSING = "API_KEY_MISSING"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"
    CANCELLED = "CANCELLED"
    ALREADY_RUNNING = "ALREADY_RUNNING"


SAFE_ANALYSIS_MESSAGES: dict[AnalysisErrorCode, str] = {
    AnalysisErrorCode.API_KEY_MISSING: "OPENAI_API_KEY가 설정되지 않았습니다.",
    AnalysisErrorCode.AUTHENTICATION_FAILED: "회의 분석 API 인증에 실패했습니다.",
    AnalysisErrorCode.RATE_LIMITED: "회의 분석 API 요청 한도를 초과했습니다.",
    AnalysisErrorCode.REQUEST_TIMEOUT: "회의 분석 요청 시간이 초과되었습니다.",
    AnalysisErrorCode.NETWORK_ERROR: "회의 분석 서버에 연결하지 못했습니다.",
    AnalysisErrorCode.INVALID_RESPONSE: "회의 분석 응답 형식이 올바르지 않습니다.",
    AnalysisErrorCode.INVALID_EVIDENCE: "분석 결과에 존재하지 않는 근거 문장이 포함되었습니다.",
    AnalysisErrorCode.PROVIDER_UNAVAILABLE: "선택한 회의 분석 방식을 현재 사용할 수 없습니다.",
    AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR: "회의 분석 중 오류가 발생했습니다.",
    AnalysisErrorCode.CANCELLED: "회의 분석 작업이 취소되었습니다.",
    AnalysisErrorCode.ALREADY_RUNNING: "다른 회의 분석 작업이 이미 진행 중입니다.",
}


class AnalysisProviderError(RuntimeError):
    def __init__(
        self,
        code: AnalysisErrorCode,
        *,
        recoverable: bool,
        retryable: bool,
    ) -> None:
        self.code = code
        self.safe_message = SAFE_ANALYSIS_MESSAGES[code]
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


def analysis_error(
    code: AnalysisErrorCode,
    *,
    recoverable: bool | None = None,
    retryable: bool | None = None,
) -> AnalysisProviderError:
    retry_defaults = {
        AnalysisErrorCode.RATE_LIMITED,
        AnalysisErrorCode.REQUEST_TIMEOUT,
        AnalysisErrorCode.NETWORK_ERROR,
        AnalysisErrorCode.PROVIDER_UNAVAILABLE,
    }
    nonrecoverable = {
        AnalysisErrorCode.API_KEY_MISSING,
        AnalysisErrorCode.AUTHENTICATION_FAILED,
        AnalysisErrorCode.INVALID_EVIDENCE,
    }
    return AnalysisProviderError(
        code,
        recoverable=(code not in nonrecoverable if recoverable is None else recoverable),
        retryable=(code in retry_defaults if retryable is None else retryable),
    )


def normalize_analysis_error(error: BaseException) -> AnalysisProviderError:
    if isinstance(error, AnalysisProviderError):
        return error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return analysis_error(AnalysisErrorCode.REQUEST_TIMEOUT)
    name = type(error).__name__.lower()
    status_code: Any = getattr(error, "status_code", None)
    if "authentication" in name or "permissiondenied" in name or status_code in {401, 403}:
        return analysis_error(AnalysisErrorCode.AUTHENTICATION_FAILED)
    if "ratelimit" in name or status_code == 429:
        return analysis_error(AnalysisErrorCode.RATE_LIMITED)
    if "timeout" in name:
        return analysis_error(AnalysisErrorCode.REQUEST_TIMEOUT)
    if (
        "connection" in name
        or "network" in name
        or isinstance(error, (ConnectionError, OSError))
    ):
        return analysis_error(AnalysisErrorCode.NETWORK_ERROR)
    if "internalserver" in name or (isinstance(status_code, int) and status_code >= 500):
        return analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
    return analysis_error(
        AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR,
        recoverable=True,
        retryable=False,
    )


__all__ = [
    "AnalysisErrorCode",
    "AnalysisProviderError",
    "SAFE_ANALYSIS_MESSAGES",
    "analysis_error",
    "normalize_analysis_error",
]
