"""Mockable official Google Gen AI SDK meeting analysis Provider."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from collections.abc import Callable
from typing import Any

from .base import AnalysisProvider
from .exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    analysis_error,
)
from .models import AnalysisProviderHealth, AnalysisRequest, MeetingAnalysis
from .prompts import build_analysis_input, build_analysis_instructions
from .structured import AnalysisResponsePayload
from .validation import validate_evidence


ClientFactory = Callable[..., Any]


def normalize_gemini_analysis_error(error: BaseException) -> AnalysisProviderError:
    """Map Google SDK/network errors without exposing upstream payloads."""

    if isinstance(error, AnalysisProviderError):
        return error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return analysis_error(AnalysisErrorCode.REQUEST_TIMEOUT)
    if isinstance(error, (ModuleNotFoundError, ImportError)):
        return analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)

    name = type(error).__name__.casefold()
    raw_code = getattr(error, "code", getattr(error, "status_code", None))
    try:
        status_code = int(raw_code)
    except (TypeError, ValueError):
        status_code = None
    status = str(getattr(error, "status", "")).casefold()

    if status_code in {401, 403} or any(
        marker in name or marker in status
        for marker in ("authentication", "unauthenticated", "permission")
    ):
        return analysis_error(AnalysisErrorCode.AUTHENTICATION_FAILED)
    if status_code == 429 or "resource_exhausted" in status or "ratelimit" in name:
        return analysis_error(AnalysisErrorCode.RATE_LIMITED)
    if status_code in {408, 504} or "timeout" in name or "deadline" in name:
        return analysis_error(AnalysisErrorCode.REQUEST_TIMEOUT)
    if "failed_precondition" in status:
        return analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
    if status_code == 400 or "invalid_argument" in status or "badrequest" in name:
        return analysis_error(AnalysisErrorCode.INVALID_RESPONSE, retryable=False)
    if (
        "connection" in name
        or "network" in name
        or isinstance(error, (ConnectionError, OSError))
    ):
        return analysis_error(AnalysisErrorCode.NETWORK_ERROR)
    if status_code == 404 or "not_found" in status:
        return analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
    if isinstance(status_code, int) and status_code >= 500:
        return analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
    return analysis_error(
        AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR,
        recoverable=True,
        retryable=False,
    )


class GeminiAnalysisProvider(AnalysisProvider):
    provider_name = "gemini"
    display_name = "Gemini 회의 분석"
    external = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        client: Any | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self._client = client
        self._client_factory = client_factory
        self._closed = False

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _sdk_installed() -> bool:
        try:
            return importlib.util.find_spec("google.genai") is not None
        except (ImportError, ValueError):
            return False

    async def health_check(self) -> AnalysisProviderHealth:
        if not self.model:
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason=(
                    "GEMINI_ANALYSIS_MODEL 또는 GEMINI_TRANSLATION_MODEL이 "
                    "설정되지 않았습니다."
                ),
                model=None,
            )
        if not self._api_key:
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason="GEMINI_API_KEY가 설정되지 않았습니다.",
                model=self.model,
            )
        if (
            self._client is None
            and self._client_factory is None
            and not self._sdk_installed()
        ):
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason="Google Gen AI Python SDK가 설치되지 않았습니다.",
                model=self.model,
            )
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            not self._closed,
            True,
            reason="회의 분석 Provider가 종료되었습니다." if self._closed else None,
            model=self.model,
        )

    def _ensure_client(self) -> Any:
        if self._closed or not self.model:
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise analysis_error(AnalysisErrorCode.API_KEY_MISSING)
        if self._client is not None:
            return self._client
        if self._client_factory is None and not self._sdk_installed():
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        try:
            if self._client_factory is not None:
                factory = self._client_factory
            else:
                from google import genai

                factory = genai.Client
            # Construction and health checks never issue a generation request.
            self._client = factory(api_key=self._api_key)
        except AnalysisProviderError:
            raise
        except Exception as error:
            mapped = normalize_gemini_analysis_error(error)
            if mapped.code is AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR:
                mapped = analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
            raise mapped from error
        return self._client

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        if not request.segments:
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE)
        client = self._ensure_client()
        try:
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=build_analysis_input(request),
                config={
                    "system_instruction": build_analysis_instructions(),
                    "response_mime_type": "application/json",
                    "response_json_schema": AnalysisResponsePayload.model_json_schema(),
                },
            )
        except AnalysisProviderError:
            raise
        except Exception as error:
            error_name = type(error).__name__.casefold()
            if any(
                marker in error_name
                for marker in ("validation", "parsing", "decode", "finishreason")
            ):
                raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE) from error
            raise normalize_gemini_analysis_error(error) from error

        try:
            parsed = (
                response.get("parsed")
                if isinstance(response, dict)
                else getattr(response, "parsed", None)
            )
            if parsed is not None:
                structured = AnalysisResponsePayload.model_validate(parsed)
            else:
                text = (
                    response.get("text")
                    if isinstance(response, dict)
                    else getattr(response, "text", None)
                )
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("empty structured output")
                structured = AnalysisResponsePayload.model_validate_json(text)
            result = MeetingAnalysis.from_payload(
                structured.model_dump(),
                session_id=request.session_id,
                provider=self.provider_name,
                model=self.model,
            )
        except Exception as error:
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE) from error
        return validate_evidence(result, request.segment_ids)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        if client is None:
            return
        async_client = getattr(client, "aio", None)
        async_closer = getattr(async_client, "aclose", None)
        if async_closer is not None:
            result = async_closer()
            if inspect.isawaitable(result):
                await result
        closer = getattr(client, "close", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result


__all__ = ["GeminiAnalysisProvider", "normalize_gemini_analysis_error"]
