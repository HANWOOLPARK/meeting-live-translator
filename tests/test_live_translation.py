"""Opt-in live provider checks.

Normal test runs never call an external API or require a downloaded local model.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from backend.app.translation import (
    LocalTranslationProvider,
    OpenAITranslationProvider,
    TranslationRequest,
    TranslationStatus,
)

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_TRANSLATION_MODEL", "").strip()
RUN_OPENAI = _enabled("RUN_OPENAI_LIVE_TEST")


@pytest.mark.skipif(
    not (OPENAI_KEY and OPENAI_MODEL and RUN_OPENAI),
    reason=(
        "Live OpenAI test requires OPENAI_API_KEY, OPENAI_TRANSLATION_MODEL, "
        "and RUN_OPENAI_LIVE_TEST=1"
    ),
)
def test_openai_translation_live_opt_in() -> None:
    async def scenario() -> None:
        provider = OpenAITranslationProvider(
            api_key=OPENAI_KEY,
            model=OPENAI_MODEL,
        )
        try:
            result = await provider.translate(
                TranslationRequest(
                    segment_id="live-openai-ja",
                    source_text="次の会議は午後三時に始まります。",
                    source_language="ja",
                    source="test",
                )
            )
            assert result.status is TranslationStatus.COMPLETED
            assert (result.translated_text or "").strip()
        finally:
            await provider.close()

    asyncio.run(scenario())


LOCAL_MODEL = os.getenv("LOCAL_TRANSLATION_MODEL", "").strip()
RUN_LOCAL = _enabled("RUN_LOCAL_TRANSLATION_TEST")


@pytest.mark.skipif(
    not (LOCAL_MODEL and RUN_LOCAL),
    reason=(
        "Live local test requires LOCAL_TRANSLATION_MODEL and "
        "RUN_LOCAL_TRANSLATION_TEST=1"
    ),
)
def test_local_translation_live_opt_in() -> None:
    async def scenario() -> None:
        provider = LocalTranslationProvider(model_path=Path(LOCAL_MODEL))
        try:
            health = await provider.health_check()
            if not health.available:
                pytest.skip(health.reason or "Local translation provider is unavailable")
            result = await provider.translate(
                TranslationRequest(
                    segment_id="live-local-en",
                    source_text="The maintenance window starts at 3 PM.",
                    source_language="en",
                    source="test",
                )
            )
            assert result.status is TranslationStatus.COMPLETED
            assert (result.translated_text or "").strip()
        finally:
            await provider.close()

    asyncio.run(scenario())
