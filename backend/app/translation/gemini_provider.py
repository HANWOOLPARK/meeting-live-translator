"""Official Google Gen AI SDK translation provider."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from collections.abc import Callable
from threading import Lock
from time import perf_counter
from typing import Any

from .base import TranslationProvider
from .exceptions import (
    TranslationErrorCode,
    TranslationProviderError,
    translation_error,
)
from .models import (
    ProviderHealth,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)
from .openai_provider import build_translation_input, build_translation_instructions


ClientFactory = Callable[..., Any]


def normalize_gemini_error(error: BaseException) -> TranslationProviderError:
    """Map SDK/network failures without exposing provider payloads or messages."""

    if isinstance(error, TranslationProviderError):
        return error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return translation_error(TranslationErrorCode.GEMINI_REQUEST_TIMEOUT)
    if isinstance(error, (ModuleNotFoundError, ImportError)):
        return translation_error(TranslationErrorCode.GEMINI_SDK_UNAVAILABLE)

    name = type(error).__name__.casefold()
    raw_code = getattr(error, "code", getattr(error, "status_code", None))
    try:
        status_code = int(raw_code)
    except (TypeError, ValueError):
        status_code = None
    status = str(getattr(error, "status", "")).upper()

    if status_code == 401 or "authentication" in name or "unauthenticated" in status:
        return translation_error(TranslationErrorCode.GEMINI_AUTHENTICATION_FAILED)
    if status_code == 403 or "permission" in name or "permission_denied" in status:
        return translation_error(TranslationErrorCode.GEMINI_PERMISSION_DENIED)
    if status_code == 404 or "not_found" in status:
        return translation_error(TranslationErrorCode.GEMINI_MODEL_NOT_FOUND)
    if status_code == 429 or "resource_exhausted" in status or "ratelimit" in name:
        # Google can report both per-minute rate limits and account/project
        # quota exhaustion as HTTP 429. Inspect only for classification; the
        # provider message is never copied into public output.
        provider_message = str(getattr(error, "message", "")).casefold()
        code = (
            TranslationErrorCode.GEMINI_QUOTA_EXHAUSTED
            if "quota" in provider_message
            else TranslationErrorCode.GEMINI_RATE_LIMITED
        )
        return translation_error(code)
    if status_code in {408, 504} or "timeout" in name or "deadline" in name:
        return translation_error(TranslationErrorCode.GEMINI_REQUEST_TIMEOUT)
    if (
        "connection" in name
        or "network" in name
        or isinstance(error, (ConnectionError, OSError))
    ):
        return translation_error(TranslationErrorCode.GEMINI_NETWORK_ERROR)
    if isinstance(status_code, int) and status_code >= 500:
        return translation_error(TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE)
    return translation_error(
        TranslationErrorCode.GEMINI_UNKNOWN_ERROR,
        recoverable=True,
        retryable=False,
    )


class GeminiTranslationProvider(TranslationProvider):
    provider_name = "gemini"
    display_name = "Gemini API"
    external = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        context_segments: int = 3,
        client: Any | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.context_segments = int(context_segments)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not (0 <= self.max_retries <= 10):
            raise ValueError("max_retries must be between 0 and 10")
        if not (0 <= self.context_segments <= 20):
            raise ValueError("context_segments must be between 0 and 20")
        self._client = client
        self._client_factory = client_factory
        self._client_lock = Lock()
        self._prepare_task: asyncio.Task[Any] | None = None
        self._closed = False

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model_configured(self) -> bool:
        return bool(self.model)

    @staticmethod
    def _sdk_installed() -> bool:
        try:
            return importlib.util.find_spec("google.genai") is not None
        except (ImportError, ValueError):
            return False

    def _ensure_client(self) -> Any:
        if self._closed:
            raise translation_error(TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise translation_error(TranslationErrorCode.GEMINI_API_KEY_MISSING)
        if not self.model:
            raise translation_error(TranslationErrorCode.GEMINI_MODEL_NOT_CONFIGURED)
        with self._client_lock:
            if self._closed:
                raise translation_error(
                    TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE
                )
            if self._client is not None:
                return self._client
            if self._client_factory is None and not self._sdk_installed():
                raise translation_error(TranslationErrorCode.GEMINI_SDK_UNAVAILABLE)
            try:
                if self._client_factory is not None:
                    factory = self._client_factory
                else:
                    from google import genai

                    factory = genai.Client
                # Client construction does not issue a model or generation request.
                self._client = factory(api_key=self._api_key)
            except TranslationProviderError:
                raise
            except Exception as error:
                mapped = normalize_gemini_error(error)
                if mapped.code is TranslationErrorCode.GEMINI_UNKNOWN_ERROR:
                    mapped = translation_error(
                        TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE
                    )
                raise mapped from error
            return self._client

    async def health_check(self) -> ProviderHealth:
        error: TranslationProviderError | None = None
        if not self._api_key:
            error = translation_error(TranslationErrorCode.GEMINI_API_KEY_MISSING)
        elif not self.model:
            error = translation_error(
                TranslationErrorCode.GEMINI_MODEL_NOT_CONFIGURED
            )
        elif (
            self._client is None
            and self._client_factory is None
            and not self._sdk_installed()
        ):
            error = translation_error(TranslationErrorCode.GEMINI_SDK_UNAVAILABLE)
        elif self._prepare_task is not None and self._prepare_task.done():
            try:
                self._prepare_task.result()
            except (asyncio.CancelledError, Exception):
                error = translation_error(
                    TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE
                )
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=error is None and not self._closed,
            external=True,
            reason=(
                error.safe_message
                if error is not None
                else (
                    translation_error(
                        TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE
                    ).safe_message
                    if self._closed
                    else None
                )
            ),
            model=self.model or None,
        )

    def start_prepare(self) -> None:
        """Construct the SDK client off-loop without issuing a model request."""

        if (
            self._closed
            or not self._api_key
            or not self.model
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
            name="gemini-translation-client-prepare",
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
            raise translation_error(TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE)
        if not self._api_key:
            raise translation_error(TranslationErrorCode.GEMINI_API_KEY_MISSING)
        if not self.model:
            raise translation_error(TranslationErrorCode.GEMINI_MODEL_NOT_CONFIGURED)
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
                mapped = normalize_gemini_error(error)
                if mapped.code is TranslationErrorCode.GEMINI_UNKNOWN_ERROR:
                    mapped = translation_error(
                        TranslationErrorCode.GEMINI_PROVIDER_UNAVAILABLE
                    )
                raise mapped from error
        return self._ensure_client()

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        client = await self._prepared_client()
        started = perf_counter()
        try:
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=build_translation_input(request),
                config={
                    "system_instruction": build_translation_instructions(
                        request.glossary_terms,
                        source_language=request.source_language,
                        target_language=request.target_language,
                    )
                },
            )
        except TranslationProviderError:
            raise
        except Exception as error:
            raise normalize_gemini_error(error) from error

        if response is None:
            raise translation_error(TranslationErrorCode.GEMINI_INVALID_RESPONSE)
        try:
            output_text = (
                response.get("text")
                if isinstance(response, dict)
                else getattr(response, "text", None)
            )
        except Exception as error:
            raise translation_error(
                TranslationErrorCode.GEMINI_INVALID_RESPONSE
            ) from error
        if output_text is None:
            raise translation_error(TranslationErrorCode.GEMINI_EMPTY_RESPONSE)
        if not isinstance(output_text, str):
            raise translation_error(TranslationErrorCode.GEMINI_INVALID_RESPONSE)
        translated = output_text.strip()
        if not translated:
            raise translation_error(TranslationErrorCode.GEMINI_EMPTY_RESPONSE)

        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=translated,
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


__all__ = ["GeminiTranslationProvider", "normalize_gemini_error"]
