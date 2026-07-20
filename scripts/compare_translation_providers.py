"""Compare OpenAI, Gemini, and NVIDIA Riva with approved identical input."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


# Windows shells commonly inherit CP949 even though comparison input and
# provider output are Unicode. Keep CLI output deterministic and pipe-safe.
for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config.settings import AppSettings
from backend.app.translation import (
    DEFAULT_NVIDIA_RIVA_MODEL,
    GeminiTranslationProvider,
    NvidiaRivaTranslationProvider,
    OpenAITranslationProvider,
)
from backend.app.translation.ab_compare import compare_same_source


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send each non-empty UTF-8 line to OpenAI, Gemini, and NVIDIA Riva with exactly "
            "the same translation request. Nothing is written to session storage."
        )
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--source-language", choices=("ja", "en", "ko"), default="ja")
    parser.add_argument("--target-language", choices=("ko", "ja", "en"), default="ko")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("openai", "gemini", "nvidia_riva"),
        default=("openai", "gemini", "nvidia_riva"),
        help="External providers to compare. Defaults to all three.",
    )
    parser.add_argument(
        "--confirm-external-calls",
        action="store_true",
        help="Required acknowledgement that all three external APIs will receive the text.",
    )
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> int:
    if not arguments.confirm_external_calls or os.getenv(
        "RUN_TRANSLATION_AB_TEST", ""
    ).strip() != "1":
        print(
            "Refusing external calls. Set RUN_TRANSLATION_AB_TEST=1 and pass "
            "--confirm-external-calls.",
            file=sys.stderr,
        )
        return 2
    path = arguments.input_file.resolve()
    if not path.is_file():
        print("Input file does not exist.", file=sys.stderr)
        return 2
    segments = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not segments:
        print("Input file has no non-empty segments.", file=sys.stderr)
        return 2

    settings = AppSettings.from_env(PROJECT_ROOT)
    available_providers = {
        "openai": OpenAITranslationProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_translation_model,
        ),
        "gemini": GeminiTranslationProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_translation_model,
            timeout_seconds=settings.gemini_translation_timeout_seconds,
            max_retries=0,
            context_segments=0,
        ),
        "nvidia_riva": NvidiaRivaTranslationProvider(
            api_key=os.getenv("NVIDIA_API_KEY"),
            model=os.getenv("NVIDIA_TRANSLATION_MODEL", "").strip()
            or DEFAULT_NVIDIA_RIVA_MODEL,
        ),
    }
    providers = {
        name: available_providers[name]
        for name in arguments.providers
    }
    try:
        health = await asyncio.gather(
            *(provider.health_check() for provider in providers.values())
        )
        unavailable = [item.name for item in health if not item.available]
        if unavailable:
            print(
                "Unavailable providers: " + ", ".join(unavailable),
                file=sys.stderr,
            )
            return 2
        rows = await compare_same_source(
            providers,
            segments,
            source_language=arguments.source_language,
            target_language=arguments.target_language,
        )
        print(json.dumps({"segments": rows}, ensure_ascii=False, indent=2))
        return 0
    finally:
        await asyncio.gather(
            *(provider.close() for provider in available_providers.values()),
            return_exceptions=True,
        )


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
