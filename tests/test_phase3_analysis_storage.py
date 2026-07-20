from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.sessions.models import FinalTranscript, StoragePolicy
from backend.app.sessions.repository import JsonlSessionRepository


def _final(session_id: str) -> FinalTranscript:
    return FinalTranscript(
        segment_id="seg-001",
        session_id=session_id,
        utterance_id="utt-001",
        source="system",
        text="System Test 일정표를 확인합니다.",
        language="ja",
        language_probability=0.99,
        started_at="2026-07-11T10:00:00+09:00",
        ended_at="2026-07-11T10:00:03+09:00",
        inference_seconds=0.2,
    )


def _analysis(session_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "provider": "rule_based",
        "model": None,
        "status": "completed",
        "generated_at": "2026-07-11T10:01:00+09:00",
        "revision": 1,
        "meeting_purpose": {
            "text": "미정",
            "evidence_segment_ids": [],
        },
        "key_discussions": [],
        "decisions": [],
        "action_items": [
            {
                "task": "System Test 일정표를 확인합니다.",
                "assignee": "미정",
                "due_date": "미정",
                "evidence_segment_ids": ["seg-001"],
            }
        ],
        "open_questions": [],
        "next_meeting_checks": [],
        "warnings": [],
    }


def _completed_repository(
    tmp_path: Path,
    *,
    save_analysis: bool = True,
) -> tuple[JsonlSessionRepository, str]:
    repository = JsonlSessionRepository(
        tmp_path,
        phase3=True,
        storage_policy=StoragePolicy(save_analysis=save_analysis),
    )
    session_id = repository.start_session({"source": "system"})
    repository.append_final(_final(session_id))
    repository.stop_session()
    return repository, session_id


def test_analysis_result_is_atomic_and_refreshes_session_and_markdown(
    tmp_path: Path,
) -> None:
    repository, session_id = _completed_repository(tmp_path)
    saved = repository.save_analysis(session_id, _analysis(session_id))

    directory = tmp_path / session_id
    assert saved["status"] == "completed"
    assert repository.load_analysis(session_id) == saved
    assert repository.get_session(session_id)["analysis"]["provider"] == "rule_based"
    assert "System Test 일정표를 확인합니다." in (
        directory / "meeting_report.md"
    ).read_text(encoding="utf-8")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis_status"] == "completed"
    assert manifest["analysis_revision"] == 1
    assert not list(directory.glob("*.tmp"))


def test_failed_reanalysis_status_preserves_previous_success(tmp_path: Path) -> None:
    repository, session_id = _completed_repository(tmp_path)
    original = repository.save_analysis(session_id, _analysis(session_id))
    repository.set_analysis_status(session_id, "running", provider="openai")
    repository.set_analysis_status(session_id, "failed", provider="openai")

    assert repository.load_analysis(session_id) == original
    session = repository.get_session(session_id)
    assert session["analysis"] == original
    assert session["metadata"]["analysis_status"] == "failed"


def test_analysis_storage_off_does_not_write_analysis_content(tmp_path: Path) -> None:
    repository, session_id = _completed_repository(tmp_path, save_analysis=False)
    payload = _analysis(session_id)
    repository.save_analysis(session_id, payload)

    directory = tmp_path / session_id
    assert not (directory / "analysis.json").exists()
    assert "System Test 일정표를 확인합니다." not in (
        directory / "meeting_report.md"
    ).read_text(encoding="utf-8").split("## 1. 회의 목적", 1)[1].split(
        "## 전체 회의 기록", 1
    )[0]


def test_legacy_jsonl_remains_unchanged_after_analysis_export(tmp_path: Path) -> None:
    session_id = "4322cb3e-66e7-4e36-ad1a-aa85da3feba6"
    source = tmp_path / f"{session_id}.jsonl"
    source.write_text(
        json.dumps(_final(session_id).to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    repository = JsonlSessionRepository(tmp_path, phase3=True)
    repository.finalize_session(session_id, recovered=True)
    repository.save_analysis(session_id, _analysis(session_id))

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
