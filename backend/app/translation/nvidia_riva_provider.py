"""NVIDIA-hosted Riva Translate adapter used by the explicit A/B tool only."""

from __future__ import annotations

import importlib.util
import inspect
from time import perf_counter
from typing import Any

from .base import TranslationProvider
from .exceptions import TranslationErrorCode, TranslationProviderError, normalize_provider_error, translation_error
from .models import ProviderHealth, TranslationRequest, TranslationResult, TranslationStatus, iso_now

DEFAULT_NVIDIA_RIVA_MODEL = "nvidia/riva-translate-4b-instruct-v1.1"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_LANGUAGE_NAMES = {"ja": "Japanese", "ko": "Korean", "en": "English"}


class NvidiaRivaTranslationProvider(TranslationProvider):
    """Provider adapter intentionally not registered in the product UI."""

    provider_name = "nvidia_riva"
    display_name = "NVIDIA Riva Translate 4B"
    external = True

    def __init__(self, *, api_key: str | None, model: str = DEFAULT_NVIDIA_RIVA_MODEL,
                 base_url: str = DEFAULT_NVIDIA_BASE_URL, client: Any | None = None) -> None:
        self._api_key = (api_key or "").strip()
        self.model = str(model).strip()
        self.base_url = str(base_url).strip().rstrip("/")
        if not self.model or not self.base_url:
            raise ValueError("model and base_url must not be empty")
        self._client = client
        self._closed = False

    @staticmethod
    def _sdk_installed() -> bool:
        try:
            return importlib.util.find_spec("openai") is not None
        except (ImportError, ValueError):
            return False

    async def health_check(self) -> ProviderHealth:
        available, reason = not self._closed, None
        if not self._api_key:
            available, reason = False, "NVIDIA_API_KEY is not configured."
        elif self._client is None and not self._sdk_installed():
            available, reason = False, "The OpenAI-compatible Python SDK is unavailable."
        elif self._closed:
            reason = "The NVIDIA Riva comparison provider is closed."
        return ProviderHealth(self.provider_name, self.display_name, available, True, reason, self.model)

    def _ensure_client(self) -> Any:
        if self._closed:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise translation_error(TranslationErrorCode.API_KEY_MISSING)
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self._api_key, base_url=self.base_url, max_retries=0)
            except Exception as error:
                raise normalize_provider_error(error) from error
        return self._client

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        source = _LANGUAGE_NAMES.get(request.source_language)
        target = _LANGUAGE_NAMES.get(request.target_language)
        if source is None or target is None:
            raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)
        system = (
            f"You are an expert at translating text from {source} to {target}. "
            f"Return only the {target} translation. Do not add explanations or facts. "
            "Preserve names, numbers, dates, times, product names, and whether a statement "
            "is decided, proposed, or unresolved."
        )
        if request.source_is_incomplete:
            system += " The source is incomplete; do not invent its missing ending."
        started = perf_counter()
        try:
            response = await self._ensure_client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"What is the {target} translation of the sentence: {request.source_text}?"},
                ],
                temperature=0,
                max_tokens=512,
            )
        except TranslationProviderError:
            raise
        except Exception as error:
            raise normalize_provider_error(error) from error
        try:
            output = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as error:
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE) from error
        if not isinstance(output, str) or not output.strip():
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE)
        return TranslationResult(
            segment_id=request.segment_id, session_id=request.session_id,
            source_text=request.source_text, translated_text=output.strip(),
            source_language=request.source_language, target_language=request.target_language,
            provider=self.provider_name, model=self.model, status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at, completed_at=iso_now(),
            latency_ms=max(0, round((perf_counter() - started) * 1_000)),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        if client is None:
            return
        closer = getattr(client, "close", None) or getattr(client, "aclose", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result


__all__ = ["DEFAULT_NVIDIA_BASE_URL", "DEFAULT_NVIDIA_RIVA_MODEL", "NvidiaRivaTranslationProvider"]
