"""Explicit, non-persistent same-input translation comparison helper."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from time import perf_counter
from typing import Any

from .base import TranslationProvider
from .exceptions import TranslationProviderError, normalize_provider_error
from .models import TranslationRequest


async def compare_same_source(
    providers: Mapping[str, TranslationProvider],
    source_segments: Iterable[str],
    *,
    source_language: str,
    target_language: str,
) -> list[dict[str, Any]]:
    """Send identical bounded requests to each explicitly supplied provider.

    The helper does not persist source text, add previous context, or retry. The
    caller remains responsible for external-transmission consent and cost gates.
    """

    names = tuple(providers)
    rows: list[dict[str, Any]] = []
    for index, raw_text in enumerate(source_segments, start=1):
        source_text = str(raw_text).strip()
        if not source_text:
            continue
        request = TranslationRequest(
            segment_id=f"ab-{index:04d}",
            source_text=source_text,
            source_language=source_language,
            target_language=target_language,
            source="comparison",
        )

        async def invoke(name: str) -> dict[str, Any]:
            provider = providers[name]
            started = perf_counter()
            try:
                result = await provider.translate(request)
            except Exception as error:
                normalized = (
                    error
                    if isinstance(error, TranslationProviderError)
                    else normalize_provider_error(error)
                )
                return {
                    "provider": name,
                    "status": "failed",
                    "error_code": normalized.code.value,
                    "elapsed_ms": max(
                        0, round((perf_counter() - started) * 1_000)
                    ),
                }
            return {
                "provider": name,
                "status": "completed",
                "model": result.model,
                "translated_text": result.translated_text,
                "provider_latency_ms": result.latency_ms,
                "elapsed_ms": max(0, round((perf_counter() - started) * 1_000)),
            }

        results = await asyncio.gather(*(invoke(name) for name in names))
        rows.append(
            {
                "segment_id": request.segment_id,
                "source_text": source_text,
                "source_language": source_language,
                "target_language": target_language,
                "results": results,
            }
        )
    return rows


__all__ = ["compare_same_source"]
