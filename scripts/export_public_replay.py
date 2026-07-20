from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PIPELINE = [
    {"stage": "STT", "provider": "Deepgram", "model": "Nova-3"},
    {
        "stage": "Context",
        "provider": "Meeting Live Translator",
        "model": "Approved terms and people",
    },
    {
        "stage": "Translation",
        "provider": "Google Gemini",
        "model": "Gemini 3.1 Flash Lite",
    },
    {
        "stage": "Decision Radar",
        "provider": "OpenAI",
        "model": "GPT-5.6 Luna",
    },
]


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _elapsed_ms(value: str, origin: datetime) -> int:
    return max(0, round((_parse_timestamp(value) - origin).total_seconds() * 1_000))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = round(percentile * (len(ordered) - 1))
    return ordered[index]


def build_public_fixture(project_root: Path, session_id: str) -> dict[str, Any]:
    session_dir = project_root / "data" / "sessions" / session_id
    session = _read_json(session_dir / "session.json")
    events = _read_jsonl(session_dir / "events.jsonl")
    radar_store = _read_json(project_root / "data" / "decision_radar.json")
    radar_session = radar_store.get("sessions", {}).get(session_id)
    if not isinstance(radar_session, dict):
        raise ValueError("The selected session has no Decision Radar state.")

    metadata = session.get("metadata", {})
    origin = _parse_timestamp(str(metadata["started_at"]))
    translation_direction = str(metadata.get("translation_direction") or "").strip()
    try:
        source_language, target_language = translation_direction.split("_to_", 1)
    except ValueError as error:
        raise ValueError("The selected session has no valid translation direction.") from error
    if source_language not in {"ja", "en", "ko"} or target_language not in {"ja", "en", "ko"}:
        raise ValueError("The selected session uses an unsupported translation direction.")
    segments = list(session.get("segments", []))
    if not segments:
        raise ValueError("The selected session has no transcript segments.")

    segment_ids = {
        str(segment["segment_id"]): f"segment-{index:03d}"
        for index, segment in enumerate(segments, start=1)
    }
    translation_events = {
        str(event["segment_id"]): event
        for event in events
        if event.get("type") == "translation" and event.get("segment_id")
    }
    normalization_events = {
        str(event["segment_id"]): event
        for event in events
        if event.get("type") == "context_normalization" and event.get("segment_id")
    }

    public_events: list[dict[str, Any]] = []
    translation_latencies: list[int] = []
    source_end_ms = 0
    normalized_count = 0

    for segment in segments:
        private_id = str(segment["segment_id"])
        public_id = segment_ids[private_id]
        final_at_ms = _elapsed_ms(str(segment["ended_at"]), origin)
        source_end_ms = max(source_end_ms, final_at_ms)
        public_events.append(
            {
                "at_ms": final_at_ms,
                "type": "final_transcript",
                "segment_id": public_id,
                "language": str(segment.get("language") or "unknown"),
                "text": str(segment.get("original_text") or ""),
            }
        )

        normalization = normalization_events.get(private_id)
        if normalization:
            matches = [
                {
                    "category": str(match.get("category") or "term"),
                    "from": str(match.get("from") or ""),
                    "to": str(match.get("to") or ""),
                }
                for match in normalization.get("matches", [])
                if match.get("from") and match.get("to")
            ]
            changed = bool(normalization.get("changed"))
            normalized_count += int(changed)
            public_events.append(
                {
                    "at_ms": _elapsed_ms(str(normalization["timestamp"]), origin),
                    "type": "context_normalization",
                    "segment_id": public_id,
                    "changed": changed,
                    "normalized_text": str(normalization.get("normalized_text") or ""),
                    "matches": matches,
                }
            )

        translation = translation_events.get(private_id)
        if translation:
            event_target = str(translation.get("target_language") or "")
            if event_target != target_language:
                raise ValueError("A translation event does not match the session target language.")
            latency_ms = int(translation.get("total_latency_ms") or translation.get("latency_ms") or 0)
            translation_latencies.append(latency_ms)
            public_events.append(
                {
                    "at_ms": _elapsed_ms(str(translation["timestamp"]), origin),
                    "type": "translation",
                    "segment_id": public_id,
                    "text": str(translation.get("translated_text") or ""),
                    "provider": "Gemini",
                    "model": "Gemini 3.1 Flash Lite",
                    "latency_ms": latency_ms,
                }
            )

    radar_batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, item in enumerate(radar_session.get("items", []), start=1):
        private_evidence = [str(value) for value in item.get("evidence_segment_ids", [])]
        missing = [value for value in private_evidence if value not in segment_ids]
        if missing:
            raise ValueError(f"Radar evidence does not exist in the transcript: {missing}")
        created_at = str(item["created_at"])
        at_ms = _elapsed_ms(created_at, origin)
        radar_batches[at_ms].append(
            {
                "item_id": f"radar-{index:03d}",
                "category": str(item["category"]),
                "text": str(item["text"]),
                "assignee": item.get("assignee"),
                "due_date": item.get("due_date"),
                "review_status": str(item.get("review_status") or "suggested"),
                "lifecycle_status": str(item.get("lifecycle_status") or "active"),
                "evidence_segment_ids": [segment_ids[value] for value in private_evidence],
            }
        )

    for at_ms, items in radar_batches.items():
        public_events.append(
            {
                "at_ms": at_ms,
                "type": "radar_update",
                "items": items,
            }
        )

    public_events.sort(key=lambda event: (int(event["at_ms"]), str(event["type"])))
    last_event_ms = max(int(event["at_ms"]) for event in public_events)
    duration_ms = last_event_ms + 1_200
    evidence_references = sum(
        len(item["evidence_segment_ids"])
        for items in radar_batches.values()
        for item in items
    )

    fixture = {
        "schema_version": 1,
        "replay_id": "build-week-verified-replay",
        "title": {
            "en": "Evidence-linked product launch meeting",
            "ko": "근거 연결형 제품 출시 회의",
        },
        "recorded_on": origin.date().isoformat(),
        "source": {
            "kind": "synthetic_business_meeting",
            "language": source_language,
            "target_language": target_language,
            "audio_retained": False,
            "source_duration_ms": source_end_ms,
        },
        "disclosure": {
            "en": "Replay of a real API run using a fictional meeting. Audio was not retained under the product privacy policy.",
            "ko": "개인정보가 없는 가상 회의를 실제 API로 실행한 Replay입니다. 제품 개인정보 보호 정책에 따라 오디오는 보관하지 않았습니다.",
        },
        "pipeline": PIPELINE,
        "metrics": {
            "final_segments": len(segments),
            "translated_segments": len(translation_latencies),
            "context_corrected_segments": normalized_count,
            "translation_latency_ms": {
                "median": round(statistics.median(translation_latencies)) if translation_latencies else 0,
                "p95_nearest": _nearest_rank(translation_latencies, 0.95),
                "max": max(translation_latencies, default=0),
            },
            "radar_items": sum(len(items) for items in radar_batches.values()),
            "radar_revisions": int(radar_session.get("revision") or 0),
            "evidence_references": evidence_references,
            "evidence_valid": True,
        },
        "duration_ms": duration_ms,
        "events": public_events,
    }

    serialized = json.dumps(fixture, ensure_ascii=False)
    forbidden = (session_id, str(session_dir), "api_key", "host_token", "relay_secret")
    if any(value and value in serialized for value in forbidden):
        raise ValueError("The public fixture contains a forbidden private identifier.")
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized public replay fixture.")
    parser.add_argument("session_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    fixture = build_public_fixture(args.project_root.resolve(), args.session_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "events": len(fixture["events"]),
                "duration_ms": fixture["duration_ms"],
                "evidence_valid": fixture["metrics"]["evidence_valid"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
