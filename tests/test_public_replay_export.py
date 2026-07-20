from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.export_public_replay import build_public_fixture


def _write_fixture(project_root: Path, *, target_language: str = "en") -> str:
    session_id = "private-session-123"
    session_dir = project_root / "data" / "sessions" / session_id
    session_dir.mkdir(parents=True)
    session = {
        "metadata": {
            "started_at": "2026-07-20T10:00:00+09:00",
            "translation_direction": "ko_to_en",
        },
        "segments": [
            {
                "segment_id": "private-segment-1",
                "language": "ko",
                "original_text": "베타 공개일은 8월 20일로 결정했습니다.",
                "ended_at": "2026-07-20T10:00:04+09:00",
            }
        ],
    }
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False), encoding="utf-8"
    )
    events = [
        {
            "type": "context_normalization",
            "segment_id": "private-segment-1",
            "timestamp": "2026-07-20T10:00:04.050+09:00",
            "changed": True,
            "normalized_text": "Aster Bridge 공개일은 8월 20일로 결정했습니다.",
            "matches": [
                {"category": "term", "from": "아스터 브릿지", "to": "Aster Bridge"}
            ],
        },
        {
            "type": "translation",
            "segment_id": "private-segment-1",
            "timestamp": "2026-07-20T10:00:04.750+09:00",
            "target_language": target_language,
            "translated_text": "We decided to launch the beta on August 20.",
            "total_latency_ms": 700,
        },
    ]
    (session_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )
    radar = {
        "sessions": {
            session_id: {
                "revision": 1,
                "items": [
                    {
                        "item_id": "private-radar-1",
                        "category": "decision",
                        "text": "Launch the beta on August 20",
                        "assignee": None,
                        "due_date": None,
                        "review_status": "suggested",
                        "lifecycle_status": "active",
                        "evidence_segment_ids": ["private-segment-1"],
                        "created_at": "2026-07-20T10:00:05+09:00",
                    }
                ],
            }
        }
    }
    (project_root / "data" / "decision_radar.json").write_text(
        json.dumps(radar, ensure_ascii=False), encoding="utf-8"
    )
    return session_id


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_replay_export_uses_recorded_language_pair_and_preserves_sources(
    tmp_path: Path,
) -> None:
    session_id = _write_fixture(tmp_path)
    session_dir = tmp_path / "data" / "sessions" / session_id
    paths = (session_dir / "session.json", session_dir / "events.jsonl")
    before = {path: _sha256(path) for path in paths}

    fixture = build_public_fixture(tmp_path, session_id)

    assert fixture["source"]["language"] == "ko"
    assert fixture["source"]["target_language"] == "en"
    assert fixture["metrics"]["translation_latency_ms"]["median"] == 700
    assert fixture["metrics"]["evidence_valid"] is True
    assert fixture["events"][0]["segment_id"] == "segment-001"
    assert "audio" not in fixture
    serialized = json.dumps(fixture, ensure_ascii=False)
    assert session_id not in serialized
    assert "private-segment-1" not in serialized
    assert {path: _sha256(path) for path in paths} == before


def test_public_replay_export_aligns_consented_demo_audio_without_local_path(
    tmp_path: Path,
) -> None:
    session_id = _write_fixture(tmp_path)
    audio_hash = "a" * 64

    fixture = build_public_fixture(
        tmp_path,
        session_id,
        timeline_offset_ms=1_000,
        audio={
            "url": "/demo/verified-session-audio.mp3",
            "duration_ms": 8_000,
            "sha256": audio_hash,
        },
    )

    assert fixture["events"][0]["at_ms"] == 3_000
    assert fixture["duration_ms"] == 8_000
    assert fixture["audio"] == {
        "url": "/demo/verified-session-audio.mp3",
        "duration_ms": 8_000,
        "sha256": audio_hash,
        "kind": "consented_scripted_demo",
        "private_meeting_audio": False,
    }
    serialized = json.dumps(fixture, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "동의받은 데모 대본 녹음" in fixture["disclosure"]["ko"]


def test_public_replay_export_rejects_translation_target_mismatch(tmp_path: Path) -> None:
    session_id = _write_fixture(tmp_path, target_language="ko")

    with pytest.raises(ValueError, match="target language"):
        build_public_fixture(tmp_path, session_id)
