from __future__ import annotations

import asyncio
import os

import pytest

from backend.app.analysis import (
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    OpenAIAnalysisProvider,
)


def test_live_openai_analysis_requires_all_explicit_opt_in_gates() -> None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_ANALYSIS_MODEL", "").strip()
    enabled = os.getenv("RUN_OPENAI_ANALYSIS_LIVE_TEST", "").strip() == "1"
    if not (api_key and model and enabled):
        pytest.skip(
            "Live OpenAI analysis requires OPENAI_API_KEY, "
            "OPENAI_ANALYSIS_MODEL, and RUN_OPENAI_ANALYSIS_LIVE_TEST=1"
        )

    async def scenario() -> None:
        provider = OpenAIAnalysisProvider(api_key=api_key, model=model)
        try:
            result = await provider.analyze(
                AnalysisRequest(
                    "synthetic-live-test",
                    (
                        AnalysisSegment(
                            "seg-001",
                            "We decided to run System Test next week.",
                            language="en",
                        ),
                    ),
                )
            )
            assert result.status is AnalysisStatus.COMPLETED
            assert all(
                evidence_id == "seg-001"
                for item in result.decisions
                for evidence_id in item.evidence_segment_ids
            )
        finally:
            await provider.close()

    asyncio.run(scenario())
