from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from backend.app.translation import (
    ProviderHealth,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    compare_same_source,
    iso_now,
)


class _Provider(TranslationProvider):
    display_name = "A/B fake"
    external = True

    def __init__(self, name: str) -> None:
        self.provider_name = name
        self.calls: list[TranslationRequest] = []

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=None,
            source_text=request.source_text,
            translated_text=f"{self.provider_name}:{request.source_text}",
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=f"{self.provider_name}-model",
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=1,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            self.provider_name,
            self.display_name,
            True,
            True,
        )

    async def close(self) -> None:
        return None


def test_ab_compare_sends_identical_context_free_requests() -> None:
    async def scenario() -> None:
        openai = _Provider("openai")
        gemini = _Provider("gemini")
        rows = await compare_same_source(
            {"openai": openai, "gemini": gemini},
            ["同じ原文です。", "", "次の文です。"],
            source_language="ja",
            target_language="ko",
        )
        assert len(rows) == 2
        assert [call.source_text for call in openai.calls] == [
            "同じ原文です。",
            "次の文です。",
        ]
        assert openai.calls == gemini.calls
        assert all(call.previous_context == () for call in openai.calls)
        assert [result["provider"] for result in rows[0]["results"]] == [
            "openai",
            "gemini",
        ]

    asyncio.run(scenario())


def test_ab_cli_refuses_calls_without_double_consent_gate(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("外部送信しない", encoding="utf-8")
    environment = dict(os.environ)
    environment.pop("RUN_TRANSLATION_AB_TEST", None)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/compare_translation_providers.py",
            str(source),
        ],
        cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "Refusing external calls" in result.stderr

