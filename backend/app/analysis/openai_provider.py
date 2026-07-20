"""Mockable official AsyncOpenAI Responses API meeting analysis Provider."""

from __future__ import annotations

import importlib.util
import inspect
from collections.abc import Callable
from typing import Any

from .base import AnalysisProvider
from .exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    analysis_error,
    normalize_analysis_error,
)
from .models import (
    AnalysisProviderHealth,
    AnalysisRequest,
    MeetingAnalysis,
)
from .prompts import (
    build_analysis_input,
    build_analysis_instructions,
)
from .structured import AnalysisResponsePayload
from .validation import validate_evidence


ClientFactory = Callable[..., Any]


class OpenAIAnalysisProvider(AnalysisProvider):
    provider_name = "openai"
    display_name = "OpenAI 회의 분석"
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
        self.model = str(model).strip() if model is not None else ""
        self._client = client
        self._client_factory = client_factory
        self._closed = False

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _sdk_installed() -> bool:
        try:
            return importlib.util.find_spec("openai") is not None
        except (ImportError, ValueError):
            return False

    async def health_check(self) -> AnalysisProviderHealth:
        if not self.model:
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason="OPENAI_ANALYSIS_MODEL이 설정되지 않았습니다.",
                model=None,
            )
        if not self._api_key:
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason="OPENAI_API_KEY가 설정되지 않았습니다.",
                model=self.model,
            )
        if self._client is None and self._client_factory is None and not self._sdk_installed():
            return AnalysisProviderHealth(
                self.provider_name,
                self.display_name,
                False,
                True,
                reason="OpenAI Python SDK가 설치되지 않았습니다.",
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
        if self._closed:
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        if not self.model:
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise analysis_error(AnalysisErrorCode.API_KEY_MISSING)
        if self._client is not None:
            return self._client
        try:
            if self._client_factory is not None:
                factory = self._client_factory
            else:
                from openai import AsyncOpenAI

                factory = AsyncOpenAI
            # Timeout and retry are owned by AnalysisManager so a single
            # bounded policy controls the number and duration of requests.
            self._client = factory(api_key=self._api_key, max_retries=0)
        except AnalysisProviderError:
            raise
        except Exception as error:
            mapped = normalize_analysis_error(error)
            if mapped.code is AnalysisErrorCode.UNKNOWN_PROVIDER_ERROR:
                mapped = analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
            raise mapped from error
        return self._client

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        if not request.segments:
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE)
        client = self._ensure_client()
        try:
            response = await client.responses.parse(
                model=self.model,
                instructions=build_analysis_instructions(),
                input=build_analysis_input(request),
                text_format=AnalysisResponsePayload,
                store=False,
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
            raise normalize_analysis_error(error) from error

        try:
            parsed = (
                response.get("output_parsed")
                if isinstance(response, dict)
                else getattr(response, "output_parsed", None)
            )
            if parsed is None:
                raise ValueError("empty parsed output")
            payload = AnalysisResponsePayload.model_validate(parsed).model_dump()
            result = MeetingAnalysis.from_payload(
                payload,
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
        closer = getattr(client, "close", None) or getattr(client, "aclose", None)
        if closer is None:
            return
        result = closer()
        if inspect.isawaitable(result):
            await result


__all__ = ["OpenAIAnalysisProvider"]
