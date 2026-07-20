from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import SCHEMA_VERSION, SessionManifest


@dataclass(frozen=True, slots=True)
class JsonlWarning:
    file_name: str
    line_number: int
    code: str

    def public_message(self) -> str:
        return f"{self.file_name}:{self.line_number}:{self.code}"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[JsonlWarning]]:
    records: list[dict[str, Any]] = []
    warnings: list[JsonlWarning] = []
    if not path.is_file():
        return records, warnings
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeError):
                warnings.append(JsonlWarning(path.name, line_number, "malformed_json"))
                continue
            if not isinstance(value, dict):
                warnings.append(JsonlWarning(path.name, line_number, "not_an_object"))
                continue
            record = dict(value)
            record["_event_index"] = len(records)
            record["_line_number"] = line_number
            records.append(record)
    return records, warnings


def _event_type(record: Mapping[str, Any]) -> str:
    event_type = str(record.get("type", "")).strip()
    if event_type:
        return event_type
    if all(str(record.get(key, "")).strip() for key in ("segment_id", "text")):
        return "final_transcript"
    return "unknown"


def _timestamp_key(value: Any) -> tuple[int, float]:
    if not isinstance(value, str) or not value.strip():
        return (1, 0.0)
    try:
        return (0, datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return (1, 0.0)


def _sort_key(segment: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _timestamp_key(segment.get("started_at")),
        _timestamp_key(segment.get("ended_at")),
        int(segment.get("event_index", 0)),
        str(segment.get("segment_id", "")),
    )


def _translation_success(record: Mapping[str, Any]) -> bool:
    return bool(str(record.get("translated_text", "")).strip()) and _event_type(record) == "translation"


def assemble_session(
    session_id: str,
    records: Iterable[Mapping[str, Any]],
    *,
    manifest: SessionManifest | Mapping[str, Any] | None = None,
    warnings: Iterable[str] = (),
    analysis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(manifest, SessionManifest):
        manifest_payload = manifest.to_dict()
    else:
        manifest_payload = dict(manifest or {})

    finals: dict[str, dict[str, Any]] = {}
    successes: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}
    normalizations: dict[str, dict[str, Any]] = {}
    orphan_translations: set[str] = set()

    for fallback_index, raw_record in enumerate(records):
        record = dict(raw_record)
        event_index = int(record.get("event_index", record.get("_event_index", fallback_index)))
        event_type = _event_type(record)
        segment_id = str(record.get("segment_id", "")).strip()
        if not segment_id:
            continue
        if event_type in {"final_transcript", "segment_marker"}:
            text_value = record.get("text") if event_type == "final_transcript" else None
            original_saved = isinstance(text_value, str) and bool(text_value.strip())
            finals[segment_id] = {
                "segment_id": segment_id,
                "source": str(record.get("source", "system")),
                "language": str(record.get("language", "unknown")),
                "language_probability": record.get("language_probability"),
                "original_text": text_value.strip() if original_saved else None,
                "original_saved": original_saved,
                "korean_translation": None,
                "translation_status": "not_requested",
                "translation_provider": None,
                "translation_model": None,
                "translation_latency_ms": None,
                "translation_error_code": None,
                "started_at": record.get("started_at"),
                "ended_at": record.get("ended_at"),
                "event_index": event_index,
            }
        elif _translation_success(record):
            successes[segment_id] = {**record, "_event_index": event_index}
            if segment_id not in finals:
                orphan_translations.add(segment_id)
        elif event_type == "translation_error":
            failures[segment_id] = {**record, "_event_index": event_index}
        elif event_type == "context_normalization":
            normalizations[segment_id] = {**record, "_event_index": event_index}

    for segment_id, segment in finals.items():
        normalization = normalizations.get(segment_id)
        if normalization is not None:
            normalized_text = str(normalization.get("normalized_text", "")).strip()
            segment.update(
                normalized_text=normalized_text or segment.get("original_text"),
                context_profile_id=str(normalization.get("profile_id", "general")),
                context_changed=bool(normalization.get("changed", False)),
                context_matches=list(normalization.get("matches", [])),
            )
        else:
            segment.update(
                normalized_text=segment.get("original_text"),
                context_profile_id=None,
                context_changed=False,
                context_matches=[],
            )
        success = successes.get(segment_id)
        failure = failures.get(segment_id)
        if success is not None:
            segment.update(
                korean_translation=str(success.get("translated_text", "")).strip(),
                translation_status="success",
                translation_provider=str(success.get("provider", "none")),
                translation_model=success.get("model"),
                translation_latency_ms=success.get("latency_ms"),
                translation_error_code=(
                    str(failure.get("code"))
                    if failure is not None
                    and int(failure.get("_event_index", 0)) > int(success.get("_event_index", 0))
                    else None
                ),
            )
        elif failure is not None:
            segment.update(
                translation_status="failed",
                translation_provider=str(failure.get("provider", "none")),
                translation_error_code=str(failure.get("code", "TRANSLATION_ERROR")),
            )
        else:
            segment["translation_status"] = "missing"

    public_warnings = [str(value) for value in warnings if str(value).strip()]
    for segment_id in sorted(orphan_translations):
        public_warnings.append(f"orphan_translation:{segment_id}")
    segments = sorted(finals.values(), key=_sort_key)
    translated_count = sum(1 for item in segments if item["translation_status"] == "success")
    metadata = {
        key: value
        for key, value in manifest_payload.items()
        if key not in {"schema_version", "session_id", "warnings"}
    }
    metadata["segment_count"] = len(segments)
    metadata["translated_segment_count"] = translated_count
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "metadata": metadata,
        "segments": segments,
        "analysis": dict(analysis) if analysis is not None else None,
        "warnings": list(dict.fromkeys(public_warnings)),
    }


__all__ = ["JsonlWarning", "assemble_session", "read_jsonl"]
