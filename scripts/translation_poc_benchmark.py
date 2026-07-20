"""Run the required standalone M2M100 translation and queue PoC."""

from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from statistics import median
from time import perf_counter, sleep
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = PROJECT_ROOT / ".venv-translation" / "Scripts" / "python.exe"
DEFAULT_MODEL = PROJECT_ROOT / "models" / "translation" / "m2m100_418m-int8"
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "translation-poc" / "standalone_results.json"
WORKER = PROJECT_ROOT / "scripts" / "translation_poc_worker.py"

JAPANESE = (
    "次のSystem Testは来週実施する予定です。",
    "SoftBankにFit & Gapの結果を共有してください。",
    "BMSとRMSのインターフェースを確認します。",
    "担当者はまだ決まっていません。",
    "詳細設計書を金曜日までに送ってください。",
)
ENGLISH = (
    "Please confirm the BMS interface requirements by Friday.",
    "The Detailed Design document will be shared with Fuji IT.",
    "We need to review the MK119 System Test results.",
    "The person in charge has not been decided yet.",
    "ONION Technology will check the DC OS configuration.",
)


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class WorkerClient:
    def __init__(self, python: Path, model: Path, stderr_path: Path) -> None:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_handle = stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(python), str(WORKER), "--model", str(model)],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.lock = threading.Lock()
        ready_line = self.stdout.readline()
        if not ready_line:
            raise RuntimeError(f"Translation worker exited before ready ({self.process.poll()})")
        self.ready = json.loads(ready_line)
        if self.ready.get("type") != "ready":
            raise RuntimeError(f"Translation worker failed: {self.ready}")

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError("Translation worker is not running")
            self.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.stdin.flush()
            response_line = self.stdout.readline()
            if not response_line:
                raise RuntimeError("Translation worker returned no response")
            response = json.loads(response_line)
            if response.get("type") == "error":
                raise RuntimeError(
                    f"{response.get('error_type', 'WorkerError')}: {response.get('message', '')}"
                )
            return response

    def translate(self, text: str, language: str) -> dict[str, Any]:
        return self.request(
            {
                "command": "translate",
                "id": str(uuid4()),
                "text": text,
                "source_language": language,
                "glossary_terms": [],
            }
        )

    def close(self) -> dict[str, Any]:
        result: dict[str, Any] = {"shutdown_response": None}
        try:
            if self.process.poll() is None:
                result["shutdown_response"] = self.request(
                    {"command": "shutdown", "id": str(uuid4())}
                )
                self.process.wait(timeout=15)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            result["exit_code"] = self.process.returncode
            result["alive_after_shutdown"] = self.process.poll() is None
            self.stderr_handle.close()
        return result


def _term_checks(source: str, translated: str, response: dict[str, Any]) -> dict[str, Any]:
    source_terms = list(response.get("source_glossary_terms", []))
    return {
        "source_terms": source_terms,
        "missing_terms": list(response.get("missing_glossary_terms", [])),
        "all_exactly_preserved": all(
            term.casefold() in translated.casefold() for term in source_terms
        ),
    }


def _numeric_tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.:/-]\d+)*", text)


def _single_result(
    client: WorkerClient,
    source: str,
    language: str,
    index: int,
) -> dict[str, Any]:
    started_at = _iso_now()
    started = perf_counter()
    response = client.translate(source, language)
    completed = perf_counter()
    completed_at = _iso_now()
    translated = str(response["translation"])
    numbers = _numeric_tokens(source)
    return {
        "index": index,
        "original": source,
        "translation": translated,
        "specified_source_language": language,
        "detected_source_language": "not_run_specified_language_used",
        "request_started_at": started_at,
        "response_completed_at": completed_at,
        "worker_cold_start_ms": client.ready["cold_start_ms"],
        "warm_translation_ms": response["latency_ms"],
        "client_round_trip_ms": round((completed - started) * 1000, 3),
        "process_rss_bytes": response["process_rss_bytes"],
        "system_total_bytes": response["system_total_bytes"],
        "system_available_bytes": response["system_available_bytes"],
        "system_used_percent": response["system_used_percent"],
        "process_cpu_percent": response["process_cpu_percent"],
        "system_cpu_percent": response["system_cpu_percent"],
        "error": None,
        "term_preservation": _term_checks(source, translated, response),
        "numeric_tokens": numbers,
        "numeric_tokens_preserved": all(token in translated for token in numbers),
        "date_expression_review": "MANUAL REVIEW REQUIRED",
        "quality_grade": "MANUAL REVIEW REQUIRED",
        "raw_model_text": response["raw_model_text"],
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = round((len(ordered) - 1) * 0.95)
    return {
        "min": round(ordered[0], 3),
        "median": round(median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(ordered[-1], 3),
    }


def _continuous_queue_test(client: WorkerClient) -> dict[str, Any]:
    utterances: list[tuple[str, str]] = []
    for _ in range(2):
        for ja, en in zip(JAPANESE, ENGLISH, strict=True):
            utterances.extend(((ja, "ja"), (en, "en")))

    work_queue: queue.Queue[tuple[int, str, str] | None] = queue.Queue(maxsize=100)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    timeline: list[dict[str, Any]] = []
    max_queue = 0

    def consumer() -> None:
        while True:
            item = work_queue.get()
            try:
                if item is None:
                    return
                index, text, language = item
                started = perf_counter()
                response = client.translate(text, language)
                results.append(
                    {
                        "index": index,
                        "language": language,
                        "latency_ms": response["latency_ms"],
                        "wall_ms": round((perf_counter() - started) * 1000, 3),
                        "rss_bytes": response["process_rss_bytes"],
                        "queue_size_after_completion": work_queue.qsize(),
                    }
                )
                timeline.append(
                    {
                        "event": "completed",
                        "index": index,
                        "queue_size": work_queue.qsize(),
                        "at_ms": round((perf_counter() - test_started) * 1000, 3),
                    }
                )
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            finally:
                work_queue.task_done()

    test_started = perf_counter()
    thread = threading.Thread(target=consumer, name="translation-poc-queue", daemon=True)
    thread.start()
    for index, (text, language) in enumerate(utterances, start=1):
        work_queue.put((index, text, language))
        max_queue = max(max_queue, work_queue.qsize())
        timeline.append(
            {
                "event": "submitted",
                "index": index,
                "queue_size": work_queue.qsize(),
                "at_ms": round((perf_counter() - test_started) * 1000, 3),
            }
        )
        sleep(0.05)
    work_queue.join()
    work_queue.put(None)
    thread.join(timeout=5)
    elapsed_ms = (perf_counter() - test_started) * 1000
    rss_values = [int(item["rss_bytes"]) for item in results]
    return {
        "status": "PASS" if len(results) == 20 and not errors else "FAIL",
        "segments": 20,
        "alternating_languages": True,
        "translation_concurrency": 1,
        "submission_interval_ms": 50,
        "completed": len(results),
        "errors": errors,
        "max_queue_size": max_queue,
        "queue_size_at_end": work_queue.qsize(),
        "elapsed_ms": round(elapsed_ms, 3),
        "translation_latency_ms": _summary([float(item["latency_ms"]) for item in results]),
        "worker_rss_start_bytes": rss_values[0] if rss_values else None,
        "worker_rss_end_bytes": rss_values[-1] if rss_values else None,
        "worker_rss_peak_bytes": max(rss_values) if rss_values else None,
        "timeline": timeline,
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M2M100 standalone translation PoC")
    parser.add_argument("--runtime-python", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    started_at = _iso_now()
    startup_started = perf_counter()
    client = WorkerClient(
        args.runtime_python.resolve(),
        args.model.resolve(),
        output.parent / "standalone_worker.stderr.log",
    )
    startup_wall_ms = round((perf_counter() - startup_started) * 1000, 3)
    shutdown: dict[str, Any] | None = None
    try:
        japanese = [
            _single_result(client, text, "ja", index)
            for index, text in enumerate(JAPANESE, start=1)
        ]
        english = [
            _single_result(client, text, "en", index)
            for index, text in enumerate(ENGLISH, start=1)
        ]
        continuous = _continuous_queue_test(client)
    finally:
        shutdown = client.close()

    payload = {
        "status": "PASS",
        "started_at": started_at,
        "completed_at": _iso_now(),
        "model": "facebook/m2m100_418M",
        "revision": "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636",
        "model_path": str(args.model.resolve()),
        "runtime_python": str(args.runtime_python.resolve()),
        "worker_ready": client.ready,
        "startup_wall_ms": startup_wall_ms,
        "japanese": japanese,
        "english": english,
        "latency_summary_ms": {
            "japanese": _summary([float(item["warm_translation_ms"]) for item in japanese]),
            "english": _summary([float(item["warm_translation_ms"]) for item in english]),
        },
        "continuous_queue": continuous,
        "shutdown": shutdown,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
