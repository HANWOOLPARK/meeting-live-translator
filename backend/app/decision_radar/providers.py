"""OpenAI and Gemini providers for live evidence-linked Decision Radar updates."""

from __future__ import annotations

import importlib.util
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..analysis.exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    analysis_error,
    normalize_analysis_error,
)
from ..analysis.gemini_provider import normalize_gemini_analysis_error
from ..analysis.models import AnalysisProviderHealth
from .models import (
    RadarBatchResult,
    RadarItemCategory,
    RadarRequest,
    RadarSuggestion,
)
from .prompts import build_radar_input, build_radar_instructions
from .structured import RadarResponsePayload


ClientFactory = Callable[..., Any]


def _result_from_payload(
    payload: RadarResponsePayload,
    *,
    provider: str,
    model: str | None,
    valid_segment_ids: frozenset[str],
    focus_segment_ids: frozenset[str],
    valid_retraction_ids: frozenset[str],
    request_input_characters: int = 0,
) -> RadarBatchResult:
    suggestions: list[RadarSuggestion] = []
    for item in payload.decisions:
        suggestions.append(
            RadarSuggestion(
                RadarItemCategory.DECISION,
                item.text,
                tuple(item.evidence_segment_ids),
            )
        )
    for item in payload.action_items:
        suggestions.append(
            RadarSuggestion(
                RadarItemCategory.ACTION_ITEM,
                item.task,
                tuple(item.evidence_segment_ids),
                assignee=item.assignee,
                due_date=item.due_date,
            )
        )
    for item in payload.open_questions:
        suggestions.append(
            RadarSuggestion(
                RadarItemCategory.OPEN_QUESTION,
                item.text,
                tuple(item.evidence_segment_ids),
            )
        )
    for item in payload.needs_confirmation:
        suggestions.append(
            RadarSuggestion(
                RadarItemCategory.NEEDS_CONFIRMATION,
                item.text,
                tuple(item.evidence_segment_ids),
                confirmation_kind=item.kind,
            )
        )
    sanitized_suggestions: list[RadarSuggestion] = []
    discarded_evidence_references = 0
    discarded_suggestions = 0
    for suggestion in suggestions:
        valid_evidence = tuple(
            evidence_id
            for evidence_id in suggestion.evidence_segment_ids
            if evidence_id in valid_segment_ids
        )
        discarded_evidence_references += (
            len(suggestion.evidence_segment_ids) - len(valid_evidence)
        )
        if not valid_evidence or not focus_segment_ids.intersection(valid_evidence):
            discarded_suggestions += 1
            continue
        sanitized_suggestions.append(
            suggestion
            if valid_evidence == suggestion.evidence_segment_ids
            else replace(suggestion, evidence_segment_ids=valid_evidence)
        )
    retracted_item_ids = tuple(dict.fromkeys(payload.retract_item_ids))
    if any(
        not item_id or item_id not in valid_retraction_ids
        for item_id in retracted_item_ids
    ):
        raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE)
    if suggestions and not sanitized_suggestions and not retracted_item_ids:
        raise analysis_error(AnalysisErrorCode.INVALID_EVIDENCE)
    return RadarBatchResult(
        provider,
        model,
        tuple(sanitized_suggestions),
        retracted_item_ids,
        discarded_evidence_references,
        discarded_suggestions,
        request_input_characters,
    )


class DecisionRadarProvider(ABC):
    provider_name: str
    display_name: str
    external = True

    @abstractmethod
    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> AnalysisProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class NoneDecisionRadarProvider(DecisionRadarProvider):
    provider_name = "none"
    display_name = "사용 안 함"
    external = False
    model = None
    api_key_configured = False

    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        return RadarBatchResult(self.provider_name, None, ())

    async def health_check(self) -> AnalysisProviderHealth:
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            True,
            False,
            model=None,
        )

    async def close(self) -> None:
        return None


class OpenAIDecisionRadarProvider(DecisionRadarProvider):
    provider_name = "openai"
    display_name = "OpenAI API"

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

    async def health_check(self) -> AnalysisProviderHealth:
        available = bool(self.model and self._api_key and not self._closed)
        if available and self._client is None and self._client_factory is None:
            try:
                available = importlib.util.find_spec("openai") is not None
            except (ImportError, ValueError):
                available = False
        reason = None
        if not self.model:
            reason = "OPENAI_DECISION_RADAR_MODEL이 설정되지 않았습니다."
        elif not self._api_key:
            reason = "OPENAI_API_KEY가 설정되지 않았습니다."
        elif not available:
            reason = "OpenAI Python SDK를 사용할 수 없습니다."
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            available,
            True,
            reason=reason,
            model=self.model or None,
        )

    def _ensure_client(self) -> Any:
        if self._closed or not self.model:
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
            self._client = factory(api_key=self._api_key, max_retries=0)
        except Exception as error:
            raise normalize_analysis_error(error) from error
        return self._client

    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        client = self._ensure_client()
        instructions = build_radar_instructions(request.output_language)
        radar_input = build_radar_input(request)
        try:
            response = await client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=radar_input,
                text_format=RadarResponsePayload,
                store=False,
            )
            parsed = (
                response.get("output_parsed")
                if isinstance(response, dict)
                else getattr(response, "output_parsed", None)
            )
            if parsed is None:
                raise ValueError("empty parsed radar output")
            payload = RadarResponsePayload.model_validate(parsed)
            return _result_from_payload(
                payload,
                provider=self.provider_name,
                model=self.model,
                valid_segment_ids=request.segment_ids,
                focus_segment_ids=request.focus_segment_id_set,
                valid_retraction_ids=request.retractable_item_ids,
                request_input_characters=len(instructions) + len(radar_input),
            )
        except AnalysisProviderError:
            raise
        except (ValueError, TypeError) as error:
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE) from error
        except Exception as error:
            raise normalize_analysis_error(error) from error

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        if client is None:
            return
        closer = getattr(client, "close", None) or getattr(client, "aclose", None)
        if closer is not None:
            outcome = closer()
            if inspect.isawaitable(outcome):
                await outcome


class GeminiDecisionRadarProvider(DecisionRadarProvider):
    provider_name = "gemini"
    display_name = "Gemini API"

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

    async def health_check(self) -> AnalysisProviderHealth:
        available = bool(self.model and self._api_key and not self._closed)
        if available and self._client is None and self._client_factory is None:
            try:
                available = importlib.util.find_spec("google.genai") is not None
            except (ImportError, ValueError):
                available = False
        reason = None
        if not self.model:
            reason = "GEMINI_DECISION_RADAR_MODEL이 설정되지 않았습니다."
        elif not self._api_key:
            reason = "GEMINI_API_KEY가 설정되지 않았습니다."
        elif not available:
            reason = "Google Gen AI Python SDK를 사용할 수 없습니다."
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            available,
            True,
            reason=reason,
            model=self.model or None,
        )

    def _ensure_client(self) -> Any:
        if self._closed or not self.model:
            raise analysis_error(AnalysisErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise analysis_error(AnalysisErrorCode.API_KEY_MISSING)
        if self._client is not None:
            return self._client
        try:
            if self._client_factory is not None:
                factory = self._client_factory
            else:
                from google import genai

                factory = genai.Client
            self._client = factory(api_key=self._api_key)
        except Exception as error:
            raise normalize_gemini_analysis_error(error) from error
        return self._client

    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        client = self._ensure_client()
        instructions = build_radar_instructions(request.output_language)
        radar_input = build_radar_input(request)
        try:
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=radar_input,
                config={
                    "system_instruction": instructions,
                    "response_mime_type": "application/json",
                    "response_json_schema": RadarResponsePayload.model_json_schema(),
                },
            )
            parsed = (
                response.get("parsed")
                if isinstance(response, dict)
                else getattr(response, "parsed", None)
            )
            if parsed is not None:
                payload = RadarResponsePayload.model_validate(parsed)
            else:
                text = (
                    response.get("text")
                    if isinstance(response, dict)
                    else getattr(response, "text", None)
                )
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("empty radar output")
                payload = RadarResponsePayload.model_validate_json(text)
            return _result_from_payload(
                payload,
                provider=self.provider_name,
                model=self.model,
                valid_segment_ids=request.segment_ids,
                focus_segment_ids=request.focus_segment_id_set,
                valid_retraction_ids=request.retractable_item_ids,
                request_input_characters=len(instructions) + len(radar_input),
            )
        except AnalysisProviderError:
            raise
        except (ValueError, TypeError) as error:
            raise analysis_error(AnalysisErrorCode.INVALID_RESPONSE) from error
        except Exception as error:
            raise normalize_gemini_analysis_error(error) from error

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
            outcome = async_closer()
            if inspect.isawaitable(outcome):
                await outcome
        closer = getattr(client, "close", None)
        if closer is not None:
            outcome = closer()
            if inspect.isawaitable(outcome):
                await outcome


__all__ = [
    "DecisionRadarProvider",
    "GeminiDecisionRadarProvider",
    "NoneDecisionRadarProvider",
    "OpenAIDecisionRadarProvider",
]
