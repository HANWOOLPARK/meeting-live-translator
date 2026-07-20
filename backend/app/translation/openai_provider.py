"""Official asynchronous OpenAI Responses API translation provider."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
from collections.abc import Callable
from threading import Lock
from time import perf_counter
from typing import Any

from .base import TranslationProvider
from .exceptions import (
    TranslationErrorCode,
    TranslationProviderError,
    normalize_provider_error,
    translation_error,
)
from .glossary import merge_glossary_terms
from .models import (
    ProviderHealth,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)


ClientFactory = Callable[..., Any]


def build_translation_instructions(
    glossary_terms: tuple[str, ...],
    *,
    source_language: str = "ja",
    target_language: str = "ko",
) -> str:
    terms = merge_glossary_terms(glossary_terms)
    if target_language == "ja":
        direction = "Korean meeting utterances into natural Japanese"
        output_rule = "Return only the Japanese translation"
    elif target_language == "en":
        direction = "Korean meeting utterances into natural English"
        output_rule = "Return only the English translation"
    else:
        direction = "Japanese or English meeting utterances into natural Korean"
        output_rule = "Return only the Korean translation"
    instructions = (
        f"You translate {direction}.\n"
        f"{output_rule} of the current utterance. Do not add labels, "
        "explanations, guesses, or information absent from the source. Previous context is "
        "reference only and must not be repeated in the response. Preserve data-center and "
        "IT meeting meaning. Preserve all numbers, dates, times, currencies, percentages, "
        "names, companies, products, versions, IP addresses, ports, commands, code, paths, "
        "table names, column names, and error codes exactly. Korean STT can insert spaces "
        "between Sino-Korean number morphemes, the date suffix '\uc77c', and a grammatical "
        "particle. Resolve the suffix before translating: '\uc774 \uc2ed \uc77c \uc77c' is "
        "'\uc774\uc2ed\uc77c\uc77c' (the 21st), while '\uc774 \uc2ed \uc77c\ub85c' is "
        "'\uc774\uc2ed\uc77c\ub85c' (the 20th followed by the particle -\ub85c). Do not otherwise "
        "normalize, round, or reinterpret a number. The JSON input may mark "
        "source_is_incomplete=true when STT had to cut an utterance at a bounded edge. "
        "In that case preserve an unfinished grammatical form and never invent a missing "
        "ending, tense, decision, or assertion."
    )
    if terms:
        glossary_block = "\n".join(f"- {term}" for term in terms)
        instructions += (
            " Preserve the spelling and case of these relevant glossary terms wherever "
            f"they appear:\n{glossary_block}"
        )
    return instructions


def build_translation_input(request: TranslationRequest) -> str:
    """Build a bounded, unambiguous user input for one current segment."""

    payload = {
        "source_language": request.source_language,
        "target_language": request.target_language,
        "previous_context_reference_only": list(request.previous_context),
        "current_utterance_translate_only_this": request.source_text,
    }
    if request.source_is_incomplete:
        payload["source_is_incomplete"] = True
        if request.boundary_reason:
            payload["boundary_reason"] = request.boundary_reason
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class OpenAITranslationProvider(TranslationProvider):
    provider_name = "openai"
    display_name = "OpenAI API 번역"
    external = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        client: Any | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self.model = str(model).strip()
        if not self.model:
            raise ValueError("model must not be empty")
        self._client = client
        self._client_factory = client_factory
        self._client_lock = Lock()
        self._prepare_task: asyncio.Task[Any] | None = None
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

    async def health_check(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                provider_id=self.provider_name,
                name=self.display_name,
                available=False,
                external=True,
                reason="OPENAI_API_KEY가 설정되지 않았습니다.",
                model=self.model,
            )
        if self._client is None and self._client_factory is None and not self._sdk_installed():
            return ProviderHealth(
                provider_id=self.provider_name,
                name=self.display_name,
                available=False,
                external=True,
                reason="OpenAI Python SDK가 설치되지 않았습니다.",
                model=self.model,
            )
        if self._prepare_task is not None and self._prepare_task.done():
            try:
                self._prepare_task.result()
            except (asyncio.CancelledError, Exception):
                return ProviderHealth(
                    provider_id=self.provider_name,
                    name=self.display_name,
                    available=False,
                    external=True,
                    reason="OpenAI 번역 Provider를 초기화하지 못했습니다.",
                    model=self.model,
                )
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=not self._closed,
            external=True,
            reason="번역 Provider가 종료되었습니다." if self._closed else None,
            model=self.model,
        )

    def _ensure_client(self) -> Any:
        if self._closed:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise translation_error(TranslationErrorCode.API_KEY_MISSING)
        with self._client_lock:
            if self._closed:
                raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
            if self._client is not None:
                return self._client
            try:
                if self._client_factory is not None:
                    factory = self._client_factory
                else:
                    from openai import AsyncOpenAI

                    factory = AsyncOpenAI
                # The manager is the single retry/timeout layer. Disabling SDK
                # retries prevents two retry policies from multiplying requests.
                # Client construction performs no translation/model request.
                self._client = factory(api_key=self._api_key, max_retries=0)
            except TranslationProviderError:
                raise
            except Exception as error:
                mapped = normalize_provider_error(error)
                if mapped.code is TranslationErrorCode.UNKNOWN_PROVIDER_ERROR:
                    mapped = translation_error(
                        TranslationErrorCode.PROVIDER_UNAVAILABLE
                    )
                raise mapped from error
            return self._client

    def start_prepare(self) -> None:
        """Construct the SDK client off-loop without issuing a paid request."""

        if (
            self._closed
            or not self._api_key
            or self._client is not None
            or (self._prepare_task is not None and not self._prepare_task.done())
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._prepare_task = loop.create_task(
            asyncio.to_thread(self._ensure_client),
            name="openai-translation-client-prepare",
        )
        self._prepare_task.add_done_callback(self._consume_prepare_result)

    @staticmethod
    def _consume_prepare_result(task: asyncio.Task[Any]) -> None:
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    async def _prepared_client(self) -> Any:
        if self._closed:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise translation_error(TranslationErrorCode.API_KEY_MISSING)
        if self._client is not None:
            return self._client
        self.start_prepare()
        task = self._prepare_task
        if task is not None:
            try:
                return await asyncio.shield(task)
            except TranslationProviderError:
                raise
            except Exception as error:
                mapped = normalize_provider_error(error)
                if mapped.code is TranslationErrorCode.UNKNOWN_PROVIDER_ERROR:
                    mapped = translation_error(
                        TranslationErrorCode.PROVIDER_UNAVAILABLE
                    )
                raise mapped from error
        return self._ensure_client()

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        client = await self._prepared_client()
        started = perf_counter()
        try:
            response = await client.responses.create(
                model=self.model,
                instructions=build_translation_instructions(
                    request.glossary_terms,
                    source_language=request.source_language,
                    target_language=request.target_language,
                ),
                input=build_translation_input(request),
            )
        except TranslationProviderError:
            raise
        except Exception as error:
            raise normalize_provider_error(error) from error

        try:
            if isinstance(response, dict):
                output_text = response.get("output_text")
            else:
                output_text = getattr(response, "output_text", None)
        except Exception as error:
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE) from error
        if not isinstance(output_text, str) or not output_text.strip():
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE)

        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=output_text.strip(),
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=self.model,
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=max(0, round((perf_counter() - started) * 1_000)),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        prepare_task, self._prepare_task = self._prepare_task, None
        if prepare_task is not None and not prepare_task.done():
            await asyncio.gather(prepare_task, return_exceptions=True)
        client, self._client = self._client, None
        if client is None:
            return
        closer = getattr(client, "close", None) or getattr(client, "aclose", None)
        if closer is None:
            return
        result = closer()
        if inspect.isawaitable(result):
            await result


__all__ = [
    "OpenAITranslationProvider",
    "build_translation_input",
    "build_translation_instructions",
]
