"""Benchmark Phase 3A session assembly, exports, and end-to-end finalize.

The benchmark creates only deterministic, non-sensitive synthetic utterances.
Fixture generation is deliberately outside the measured intervals.  It uses
the Phase 3 repository/assembler/exporter when installed and supports both the
managed session start API and the legacy ``JsonlSessionRepository.start_session``
creation API retained for Phase 1/2 compatibility.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import inspect
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import tracemalloc
from collections.abc import Mapping, Sequence
from dataclasses import is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SIZES = (10, 100, 500, 1_000)
KST = timezone(timedelta(hours=9))


def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _supported_call(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call an evolving public API with only the keyword fields it accepts."""

    signature = inspect.signature(function)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if not accepts_kwargs:
        kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return _resolve(function(*args, **kwargs))


def _construct_optional(
    module: Any,
    class_names: Sequence[str],
    values: Mapping[str, Any],
) -> Any:
    for name in class_names:
        cls = getattr(module, name, None)
        if cls is None:
            continue
        signature = inspect.signature(cls)
        kwargs = {key: value for key, value in values.items() if key in signature.parameters}
        try:
            return cls(**kwargs)
        except (TypeError, ValueError):
            continue
    return dict(values)


def _extract_session_id(result: Any, repository: Any) -> str:
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, Mapping):
        candidate = result.get("session_id")
        if candidate:
            return str(candidate)
    candidate = getattr(result, "session_id", None)
    if candidate:
        return str(candidate)
    candidate = getattr(repository, "session_id", None)
    if candidate:
        return str(candidate)
    raise RuntimeError("Session start API did not expose a session_id")


class Phase3SessionApi:
    """Narrow compatibility adapter around the public Phase 3A modules."""

    def __init__(self, root: Path) -> None:
        try:
            from backend.app.sessions import models as session_models
            from backend.app.sessions import assembler as assembler_module
            from backend.app.sessions import exporters as exporter_module
            from backend.app.sessions.repository import JsonlSessionRepository
        except ImportError as error:
            raise RuntimeError(
                "Phase 3A session modules are not available. "
                "Run this benchmark after SessionAssembler and SessionExporter are installed."
            ) from error

        try:
            from backend.app.sessions.manager import SessionManager
        except ImportError:
            SessionManager = None

        self.root = root
        self.models = session_models
        self.assembler_module = assembler_module
        storage_policy_class = getattr(session_models, "StoragePolicy", None)
        storage_policy = storage_policy_class() if storage_policy_class else None
        repository_kwargs = {
            "phase3": True,
            "storage_policy": storage_policy,
        }
        repository_signature = inspect.signature(JsonlSessionRepository)
        repository_kwargs = {
            key: value
            for key, value in repository_kwargs.items()
            if key in repository_signature.parameters
        }
        self.repository = JsonlSessionRepository(root, **repository_kwargs)
        self.manager = SessionManager(self.repository) if SessionManager is not None else None
        assembler_class = getattr(assembler_module, "SessionAssembler", None)
        self.assembler = (
            assembler_class()
            if assembler_class is not None
            else getattr(assembler_module, "assemble_session")
        )
        exporter_class = getattr(exporter_module, "SessionExporter", None)
        self.exporter = exporter_class() if exporter_class is not None else exporter_module
        if self.manager is not None:
            manager_start = getattr(self.manager, "start_session", None) or getattr(
                self.manager,
                "start",
                None,
            )
            self.creation_api = (
                f"SessionManager.{manager_start.__name__}"
                if manager_start is not None
                else "repository.start_session(managed)"
            )
        elif "metadata" in inspect.signature(self.repository.start_session).parameters:
            self.creation_api = "repository.start_session(managed)"
        else:
            self.creation_api = "legacy_start_session"
        self.finalize_api = (
            "repository.finalize_session"
            if hasattr(self.repository, "finalize_session")
            else "phase3_component_fallback"
        )

    def create_session(self) -> str:
        now = datetime.now(KST).isoformat(timespec="milliseconds")
        metadata_values = {
            "created_at": now,
            "started_at": now,
            "source": "system",
            "audio_device_name": "Synthetic benchmark device",
            "whisper_model": "small",
            "translation_provider": "synthetic",
            "analysis_provider": "none",
        }
        save_values = {
            "save_original": True,
            "save_translation": True,
            "save_analysis": True,
            "save_audio": False,
        }
        metadata = _construct_optional(
            self.models,
            ("SessionMetadata", "SessionStartMetadata"),
            metadata_values,
        )
        save_settings = _construct_optional(
            self.models,
            (
                "StoragePolicy",
                "SessionSaveSettings",
                "SaveSettings",
                "SessionStorageSettings",
            ),
            save_values,
        )
        if self.manager is not None:
            manager_start = getattr(self.manager, "start_session", None) or getattr(
                self.manager,
                "start",
                None,
            )
        else:
            manager_start = None
        if manager_start is not None:
            result = _supported_call(
                manager_start,
                metadata=metadata,
                storage_policy=save_settings,
                save_settings=save_settings,
            )
        else:
            # New repositories accept metadata/storage policy here. Older
            # Phase 1/2 repositories ignore unsupported keywords through the
            # signature adapter and retain root/<UUID>.jsonl behavior.
            result = _supported_call(
                self.repository.start_session,
                metadata=metadata,
                storage_policy=save_settings,
                save_settings=save_settings,
            )
        return _extract_session_id(result, self.repository)

    def append_synthetic_events(self, session_id: str, segment_count: int) -> None:
        from backend.app.sessions.models import FinalTranscript

        base = datetime(2026, 7, 11, 9, 0, tzinfo=KST)
        for index in range(segment_count):
            started = base + timedelta(seconds=index * 4)
            ended = started + timedelta(seconds=3)
            language = "ja" if index % 2 == 0 else "en"
            if language == "ja":
                text = (
                    f"テスト用セグメント{index + 1:04d}です。"
                    "System Testの時刻は15:30です。"
                )
            else:
                text = (
                    f"Synthetic segment {index + 1:04d} confirms the "
                    "System Test time at 15:30."
                )
            segment_id = f"segment-{index + 1:06d}"
            transcript = FinalTranscript(
                segment_id=segment_id,
                session_id=session_id,
                utterance_id=f"utterance-{index + 1:06d}",
                source="system",
                text=text,
                language=language,
                language_probability=0.98,
                started_at=started.isoformat(timespec="milliseconds"),
                ended_at=ended.isoformat(timespec="milliseconds"),
                inference_seconds=0.25,
            )
            self.repository.append_final(transcript)

            # Four of every five segments receive a translation so exporters
            # also exercise the missing-translation policy.
            if index % 5 != 4:
                self.repository.append_translation(
                    session_id,
                    {
                        "type": "translation",
                        "segment_id": segment_id,
                        "source_language": language,
                        "target_language": "ko",
                        "translated_text": (
                            f"합성 세그먼트 {index + 1:04d}의 "
                            "System Test 시간은 15:30입니다."
                        ),
                        "provider": "synthetic",
                        "model": "no-network-benchmark",
                        "latency_ms": 1,
                        "completed_at": (ended + timedelta(milliseconds=1)).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                )
        _supported_call(self.repository.stop_session, finalize=False)
        setter = getattr(self.repository, "set_status", None) or getattr(
            self.repository,
            "update_status",
            None,
        )
        if setter is not None:
            _supported_call(setter, session_id, status="stopping")

    def _events_and_warnings(self, session_id: str) -> tuple[list[Any], tuple[str, ...]]:
        reader = getattr(self.repository, "read_events", None)
        if reader is not None:
            result = _supported_call(reader, session_id)
        else:
            managed_path = self.root / session_id / "events.jsonl"
            source_path = (
                managed_path if managed_path.is_file() else self.root / f"{session_id}.jsonl"
            )
            result = self.assembler_module.read_jsonl(source_path)
        if isinstance(result, tuple) and len(result) == 2:
            events, warnings = result
            return list(events), tuple(self._warning_text(item) for item in warnings)
        if isinstance(result, Mapping):
            events = result.get("events", ())
            warnings = result.get("warnings", ())
            return list(events), tuple(str(item) for item in warnings)
        events = getattr(result, "events", result)
        warnings = getattr(result, "warnings", ())
        return list(events), tuple(self._warning_text(item) for item in warnings)

    @staticmethod
    def _warning_text(value: Any) -> str:
        public_message = getattr(value, "public_message", None)
        if callable(public_message):
            return str(public_message())
        return str(value)

    def assemble(self, session_id: str) -> Any:
        events, warnings = self._events_and_warnings(session_id)
        manifest_loader = getattr(self.repository, "load_manifest", None)
        if manifest_loader is not None:
            manifest = _supported_call(manifest_loader, session_id)
        else:
            manifest_path = self.root / session_id / "manifest.json"
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else None
            )
        assemble = getattr(self.assembler, "assemble", self.assembler)
        return _supported_call(
            assemble,
            session_id,
            events,
            manifest=manifest,
            metadata=manifest,
            warnings=warnings,
        )

    @staticmethod
    def _export_target(function: Any, directory: Path, filename: str) -> Path:
        parameters = list(inspect.signature(function).parameters.values())
        # Bound method parameters begin with session. The second public
        # parameter is either a directory or an explicit target path.
        destination = parameters[1].name.lower() if len(parameters) > 1 else "directory"
        return directory / filename if any(
            token in destination for token in ("path", "target", "file")
        ) else directory

    def export_json(self, session: Any, directory: Path) -> Any:
        directory.mkdir(parents=True, exist_ok=True)
        export_json = getattr(self.exporter, "export_json", None)
        if export_json is not None:
            target = self._export_target(export_json, directory, "session.json")
            return _supported_call(export_json, session, target)
        return _supported_call(
            self.exporter.atomic_write_json,
            directory / "session.json",
            session,
        )

    def export_markdown(self, session: Any, directory: Path) -> Any:
        directory.mkdir(parents=True, exist_ok=True)
        export_markdown = getattr(self.exporter, "export_markdown", None)
        if export_markdown is not None:
            target = self._export_target(
                export_markdown,
                directory,
                "meeting_report.md",
            )
            return _supported_call(export_markdown, session, target)
        markdown = self.exporter.render_markdown(session)
        return _supported_call(
            self.exporter.atomic_write_text,
            directory / "meeting_report.md",
            markdown,
        )

    def finalize(self, session_id: str) -> Any:
        finalizer = getattr(self.repository, "finalize_session", None)
        if finalizer is None and self.manager is not None:
            finalizer = getattr(self.manager, "finalize_session", None)
        if finalizer is not None:
            return _supported_call(finalizer, session_id)

        # Transitional compatibility for running the benchmark while the
        # repository still exposes only the Phase 2 writer. It uses the actual
        # Phase 3 assembler/exporters, never a second benchmark-only assembler.
        session = self.assemble(session_id)
        directory = self.root / session_id
        self.export_json(session, directory)
        _supported_call(
            self.exporter.atomic_write_text,
            directory / "transcript_original.txt",
            self.exporter.render_original_txt(session),
        )
        _supported_call(
            self.exporter.atomic_write_text,
            directory / "transcript_korean.txt",
            self.exporter.render_translation_txt(session),
        )
        self.export_markdown(session, directory)
        return session


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _run_once(run_root: Path, segment_count: int) -> dict[str, float | int | str]:
    api = Phase3SessionApi(run_root / "sessions")
    session_id = api.create_session()
    api.append_synthetic_events(session_id, segment_count)
    component_dir = run_root / "component_exports" / session_id

    gc.collect()
    tracemalloc.start()
    try:
        started = perf_counter()
        session = api.assemble(session_id)
        assemble_ms = (perf_counter() - started) * 1_000

        started = perf_counter()
        api.export_json(session, component_dir)
        json_ms = (perf_counter() - started) * 1_000

        started = perf_counter()
        api.export_markdown(session, component_dir)
        markdown_ms = (perf_counter() - started) * 1_000

        started = perf_counter()
        api.finalize(session_id)
        finalize_ms = (perf_counter() - started) * 1_000

        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    session_directory = run_root / "sessions" / session_id
    return {
        "segments": segment_count,
        "creation_api": api.creation_api,
        "finalize_api": api.finalize_api,
        "assemble_ms": assemble_ms,
        "json_export_ms": json_ms,
        "markdown_export_ms": markdown_ms,
        "finalize_ms": finalize_ms,
        "peak_memory_mib": peak_bytes / (1024 * 1024),
        "component_export_bytes": _directory_bytes(component_dir),
        "finalized_artifact_bytes": _directory_bytes(session_directory),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _aggregate(segment_count: int, samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = (
        "assemble_ms",
        "json_export_ms",
        "markdown_export_ms",
        "finalize_ms",
        "peak_memory_mib",
    )
    row: dict[str, Any] = {
        "segments": segment_count,
        "iterations": len(samples),
        "creation_api": samples[0]["creation_api"],
        "finalize_api": samples[0]["finalize_api"],
    }
    for metric in metrics:
        values = [float(sample[metric]) for sample in samples]
        row[f"{metric}_median"] = statistics.median(values)
        row[f"{metric}_p95"] = _percentile(values, 0.95)
        row[f"{metric}_max"] = max(values)
    row["component_export_bytes_median"] = round(
        statistics.median(float(sample["component_export_bytes"]) for sample in samples)
    )
    row["finalized_artifact_bytes_median"] = round(
        statistics.median(float(sample["finalized_artifact_bytes"]) for sample in samples)
    )
    return row


def _print_table(rows: Sequence[Mapping[str, Any]]) -> None:
    headers = (
        "segments",
        "assemble med/p95 ms",
        "JSON med/p95 ms",
        "Markdown med/p95 ms",
        "finalize med/p95 ms",
        "peak MiB",
    )
    print(" | ".join(headers))
    print("-" * 111)
    for row in rows:
        print(
            f"{row['segments']:>8} | "
            f"{row['assemble_ms_median']:>8.3f}/{row['assemble_ms_p95']:<8.3f} | "
            f"{row['json_export_ms_median']:>8.3f}/{row['json_export_ms_p95']:<8.3f} | "
            f"{row['markdown_export_ms_median']:>8.3f}/{row['markdown_export_ms_p95']:<8.3f} | "
            f"{row['finalize_ms_median']:>8.3f}/{row['finalize_ms_p95']:<8.3f} | "
            f"{row['peak_memory_mib_max']:>8.3f}"
        )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=list(DEFAULT_SIZES),
        help="Synthetic segment counts (default: 10 100 500 1000)",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--base-dir",
        type=Path,
        help="Keep artifacts beneath a new child of this directory",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep a generated temporary benchmark directory",
    )
    parser.add_argument("--json-output", type=Path, help="Optional aggregate result JSON")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.iterations <= 0 or any(size <= 0 for size in args.sizes):
        raise SystemExit("sizes and iterations must be positive")

    temporary_context: tempfile.TemporaryDirectory[str] | None = None
    if args.base_dir is not None:
        benchmark_root = args.base_dir.resolve() / (
            f"phase3-session-benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        benchmark_root.mkdir(parents=True, exist_ok=False)
    elif args.keep_data:
        benchmark_root = Path(tempfile.mkdtemp(prefix="phase3-session-benchmark-"))
    else:
        temporary_context = tempfile.TemporaryDirectory(prefix="phase3-session-benchmark-")
        benchmark_root = Path(temporary_context.name)

    all_samples: dict[int, list[dict[str, Any]]] = {}
    try:
        for size in args.sizes:
            samples: list[dict[str, Any]] = []
            for iteration in range(args.iterations):
                run_root = benchmark_root / f"segments-{size}" / f"iteration-{iteration + 1}"
                run_root.mkdir(parents=True, exist_ok=False)
                samples.append(_run_once(run_root, size))
            all_samples[size] = samples

        rows = [_aggregate(size, all_samples[size]) for size in args.sizes]
        payload = {
            "benchmark_schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "synthetic": True,
            "network_requests": 0,
            "sizes": list(args.sizes),
            "iterations": args.iterations,
            "results": rows,
        }
        _print_table(rows)
        if args.json_output is not None:
            _atomic_json(args.json_output.resolve(), payload)
            print(f"JSON result: {args.json_output.resolve()}")
        if args.base_dir is not None or args.keep_data:
            print(f"Synthetic artifacts: {benchmark_root}")
        return 0
    finally:
        if temporary_context is not None:
            temporary_context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
