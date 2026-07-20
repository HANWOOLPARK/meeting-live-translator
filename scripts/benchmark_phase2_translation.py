"""Non-billable Phase 2 queue benchmark using a deterministic fake provider."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.translation import (
    NoneTranslationProvider,
    ProviderHealth,
    TranslationManager,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)


class DelayedFakeProvider(TranslationProvider):
    provider_name = "benchmark-fake"
    display_name = "Benchmark fake"
    external = False

    def __init__(self, delay_seconds: float = 0.05) -> None:
        self.delay_seconds = delay_seconds

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            self.provider_name,
            self.display_name,
            True,
            False,
            model="deterministic-fake",
        )

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        started = perf_counter()
        await asyncio.sleep(self.delay_seconds)
        return TranslationResult(
            segment_id=request.segment_id,
            source_text=request.source_text,
            translated_text=f"번역 {request.segment_id}",
            source_language=request.source_language,
            target_language="ko",
            provider=self.provider_name,
            model="deterministic-fake",
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=round((perf_counter() - started) * 1_000),
        )

    async def close(self) -> None:
        return None


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


async def benchmark(provider: TranslationProvider, count: int = 20) -> dict[str, object]:
    event_times: dict[tuple[str, str], float] = {}

    def sink(event: dict[str, object]) -> None:
        segment_id = str(event.get("segment_id", ""))
        event_times[(segment_id, str(event.get("type", "")))] = perf_counter()

    manager = TranslationManager(
        provider,
        queue_max_size=max(100, count + 1),
        max_concurrency=2,
        timeout_seconds=2,
        max_retries=0,
        event_sink=sink,
    )
    registration_ms: list[float] = []
    final_times: dict[str, float] = {}
    for index in range(count):
        segment_id = f"segment-{index:02d}"
        final_times[segment_id] = perf_counter()
        await manager.submit(
            TranslationRequest(
                segment_id=segment_id,
                source_text=f"Non-sensitive test sentence {index}",
                source_language="en",
            )
        )
        registration_ms.append((perf_counter() - final_times[segment_id]) * 1_000)

    await manager.wait_idle(10)
    completion_ms = [
        (event_times[(segment_id, "translation")] - final_time) * 1_000
        for segment_id, final_time in final_times.items()
        if (segment_id, "translation") in event_times
    ]
    result: dict[str, object] = {
        "provider": provider.provider_name,
        "segments": count,
        "final_to_registration_ms": summary(registration_ms),
        "translations_completed": len(completion_ms),
    }
    if completion_ms:
        result["final_to_translation_event_ms"] = summary(completion_ms)
    await manager.shutdown()
    return result


async def main() -> None:
    results = {
        "translation_off": await benchmark(NoneTranslationProvider()),
        "translation_on_fake_50ms": await benchmark(DelayedFakeProvider(0.05)),
        "note": (
            "The fake provider makes no network/API request. The controller broadcasts "
            "final_transcript before this measured registration call."
        ),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
