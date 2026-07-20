from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.analysis.chunking import chunk_request, merge_analyses
from backend.app.analysis.models import AnalysisRequest, AnalysisSegment
from backend.app.analysis.rule_based_provider import RuleBasedAnalysisProvider
from backend.app.analysis.validation import validate_evidence


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _request(count: int) -> AnalysisRequest:
    templates = (
        "Alice will confirm the System Test schedule by next week.",
        "We decided to keep port 8765 for the test.",
        "Who will review the Operation Test checklist?",
        "次回会議でFit & Gapの確認事項を確認します。",
    )
    return AnalysisRequest(
        session_id="benchmark-session",
        segments=tuple(
            AnalysisSegment(
                segment_id=f"seg-{index:05d}",
                original_text=templates[index % len(templates)],
                language="en" if index % len(templates) != 3 else "ja",
                started_at=f"2026-07-11T10:{(index // 60) % 60:02d}:{index % 60:02d}+09:00",
            )
            for index in range(count)
        ),
    )


async def _one(provider: RuleBasedAnalysisProvider, count: int) -> dict[str, float]:
    request = _request(count)
    tracemalloc.start()
    started = time.perf_counter()
    parts = []
    warnings: list[str] = []
    for chunk, chunk_warnings in chunk_request(request):
        parts.append(await provider.analyze(chunk))
        warnings.extend(chunk_warnings)
    merged = merge_analyses(
        request.session_id,
        parts,
        provider=provider.provider_name,
        model=None,
        warnings=warnings,
    )
    validate_evidence(merged, request.segment_ids)
    elapsed_ms = (time.perf_counter() - started) * 1_000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "elapsed_ms": elapsed_ms,
        "peak_memory_mib": peak / (1024 * 1024),
        "chunks": float(len(chunk_request(request))),
    }


async def run(iterations: int) -> dict[str, Any]:
    provider = RuleBasedAnalysisProvider()
    rows = []
    for count in (10, 100, 500, 1000):
        samples = [await _one(provider, count) for _ in range(iterations)]
        elapsed = [sample["elapsed_ms"] for sample in samples]
        peak = [sample["peak_memory_mib"] for sample in samples]
        rows.append(
            {
                "segments": count,
                "iterations": iterations,
                "chunks": int(samples[0]["chunks"]),
                "elapsed_ms_median": statistics.median(elapsed),
                "elapsed_ms_p95": _percentile(elapsed, 0.95),
                "elapsed_ms_max": max(elapsed),
                "peak_memory_mib_max": max(peak),
            }
        )
    await provider.close()
    return {"provider": "rule_based", "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if args.iterations <= 0:
        raise SystemExit("iterations must be positive")
    print(json.dumps(asyncio.run(run(args.iterations)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
