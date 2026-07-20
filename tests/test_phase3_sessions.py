from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.sessions.assembler import assemble_session, read_jsonl
from backend.app.sessions.exceptions import SessionError
from backend.app.sessions.exporters import atomic_write_text
from backend.app.sessions.models import FinalTranscript, StoragePolicy
from backend.app.sessions.repository import JsonlSessionRepository, validate_session_id


def transcript(session_id: str, segment_id: str = "segment-1") -> FinalTranscript:
    return FinalTranscript(
        segment_id=segment_id,
        session_id=session_id,
        utterance_id=f"utterance-{segment_id}",
        source="system",
        text=f"{segment_id} System Test は来週です。",
        language="ja",
        language_probability=0.98,
        started_at="2026-07-11T10:00:01+09:00",
        ended_at="2026-07-11T10:00:04+09:00",
        inference_seconds=0.5,
    )


def translation(segment_id: str, text: str, timestamp: str) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "source_language": "ja",
        "target_language": "ko",
        "translated_text": text,
        "provider": "openai",
        "model": "test-model",
        "latency_ms": 120,
        "timestamp": timestamp,
    }


def phase3_repository(tmp_path: Path, **kwargs) -> JsonlSessionRepository:
    return JsonlSessionRepository(tmp_path, phase3=True, **kwargs)


def test_phase3_session_lifecycle_finalize_and_exports(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session(
        {
            "started_at": "2026-07-11T10:00:00+09:00",
            "source": "system",
            "audio_device_name": "Speakers",
            "whisper_model": "small",
            "translation_provider": "openai",
        }
    )
    directory = tmp_path / session_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "running"
    assert manifest["save_audio"] is False

    repository.update_status(session_id, "paused")
    assert json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["status"] == "paused"
    repository.update_status(session_id, "running")
    repository.append_final(transcript(session_id))
    repository.append_translation(
        session_id,
        translation("segment-1", "다음 주 System Test입니다.", "2026-07-11T10:00:05+09:00"),
    )
    completed = repository.stop_session(ended_at="2026-07-11T10:05:00+09:00")

    assert completed is not None
    assert completed["metadata"]["status"] == "completed"
    assert completed["segments"][0]["korean_translation"] == "다음 주 System Test입니다."
    assert (directory / "events.jsonl").is_file()
    assert (directory / "session.json").is_file()
    assert (directory / "transcript_original.txt").is_file()
    assert (directory / "transcript_korean.txt").is_file()
    assert (directory / "meeting_report.md").is_file()
    assert "분석이 아직 생성되지 않았습니다." in (directory / "meeting_report.md").read_text(encoding="utf-8")


def test_latest_success_translation_is_selected_and_late_success_refinalizes(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session({"source": "system"})
    repository.append_final(transcript(session_id))
    repository.append_translation(
        session_id,
        translation("segment-1", "첫 번역", "2026-07-11T10:00:05+09:00"),
    )
    repository.stop_session()
    repository.append_translation_error(
        session_id,
        {
            "segment_id": "segment-1",
            "provider": "openai",
            "code": "NETWORK_ERROR",
        },
    )
    repository.append_translation(
        session_id,
        translation("segment-1", "최신 번역", "2026-07-11T10:00:07+09:00"),
    )
    completed = repository.get_session(session_id)
    assert completed["segments"][0]["korean_translation"] == "최신 번역"
    assert completed["segments"][0]["translation_status"] == "success"


def test_failed_translation_keeps_original(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session({"source": "system"})
    repository.append_final(transcript(session_id))
    repository.append_translation_error(
        session_id,
        {"segment_id": "segment-1", "provider": "openai", "code": "REQUEST_TIMEOUT"},
    )
    completed = repository.stop_session()
    assert completed["segments"][0]["original_text"]
    assert completed["segments"][0]["translation_status"] == "failed"
    assert completed["segments"][0]["translation_error_code"] == "REQUEST_TIMEOUT"


def test_segment_sorting_uses_times_not_translation_order() -> None:
    records = [
        {
            "type": "final_transcript",
            "segment_id": "later",
            "text": "later",
            "started_at": "2026-07-11T10:00:10+09:00",
            "ended_at": "2026-07-11T10:00:11+09:00",
        },
        {
            "type": "final_transcript",
            "segment_id": "earlier",
            "text": "earlier",
            "started_at": "2026-07-11T10:00:01+09:00",
            "ended_at": "2026-07-11T10:00:02+09:00",
        },
        {"type": "translation", "segment_id": "later", "translated_text": "나중"},
        {"type": "translation", "segment_id": "earlier", "translated_text": "먼저"},
    ]
    session = assemble_session("safe", records)
    assert [item["segment_id"] for item in session["segments"]] == ["earlier", "later"]


def test_malformed_row_is_skipped_and_event_log_is_unchanged(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session({"source": "system"})
    repository.append_final(transcript(session_id))
    path = tmp_path / session_id / "events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken json\n")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    completed = repository.stop_session()
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after
    assert len(completed["segments"]) == 1
    assert any("malformed_json" in warning for warning in completed["warnings"])


def test_finalize_is_idempotent_and_does_not_append_events(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session({"source": "system"})
    repository.append_final(transcript(session_id))
    repository.stop_session()
    events = tmp_path / session_id / "events.jsonl"
    before = events.read_bytes()
    first = repository.finalize_session(session_id)
    second = repository.finalize_session(session_id)
    assert first["segments"] == second["segments"]
    assert events.read_bytes() == before


def test_incomplete_session_recovery_preserves_unknown_end_time(tmp_path: Path) -> None:
    first = phase3_repository(tmp_path)
    session_id = first.start_session({"source": "system"})
    first.append_final(transcript(session_id))

    restarted = phase3_repository(tmp_path)
    assert restarted.recover_incomplete() == [session_id]
    session = restarted.get_session(session_id)
    assert session["metadata"]["status"] == "recovered"
    assert session["metadata"]["ended_at"] is None


def test_legacy_jsonl_is_listed_and_never_modified(tmp_path: Path) -> None:
    session_id = "4322cb3e-66e7-4e36-ad1a-aa85da3feba6"
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(json.dumps(transcript(session_id).to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    repository = phase3_repository(tmp_path)

    listed = repository.list_sessions()
    assert listed[0]["session_id"] == session_id
    assert listed[0]["segment_count"] == 1
    export = repository.get_export_path(session_id, "json")
    assert export.is_file()
    assert len(repository.finalize_session(session_id, recovered=True)["segments"]) == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "value",
    ["../secret", "..\\secret", "C:\\secret", "CON", "NUL", "x" * 65, "bad\x01id"],
)
def test_unsafe_session_ids_are_rejected(value: str) -> None:
    with pytest.raises(SessionError):
        validate_session_id(value)


def test_storage_off_writes_only_marker_and_no_content(tmp_path: Path) -> None:
    repository = phase3_repository(
        tmp_path,
        storage_policy=StoragePolicy(
            save_original=False,
            save_translation=False,
            save_analysis=False,
        ),
    )
    session_id = repository.start_session({"source": "system"})
    secret_original = "PRIVATE ORIGINAL"
    item = transcript(session_id)
    item = FinalTranscript(**{**item.to_dict(), "text": secret_original})
    repository.append_final(item)
    repository.append_translation(
        session_id,
        translation("segment-1", "PRIVATE TRANSLATION", "2026-07-11T10:00:05+09:00"),
    )
    completed = repository.stop_session()
    all_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / session_id).iterdir()
        if path.is_file()
    )
    assert secret_original not in all_text
    assert "PRIVATE TRANSLATION" not in all_text
    assert completed["segments"][0]["original_saved"] is False


def test_one_corrupt_session_does_not_break_listing(tmp_path: Path) -> None:
    repository = phase3_repository(tmp_path)
    session_id = repository.start_session({"source": "system"})
    repository.append_final(transcript(session_id))
    repository.stop_session()
    corrupt = tmp_path / "2026-07-11_10-10-10_abcdef"
    corrupt.mkdir()
    (corrupt / "manifest.json").write_text("not json", encoding="utf-8")

    sessions = repository.list_sessions()
    assert {item["session_id"] for item in sessions} == {
        session_id,
        corrupt.name,
    }
    assert next(item for item in sessions if item["session_id"] == corrupt.name)["status"] == "error"


def test_atomic_text_failure_preserves_previous_target(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "session.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("simulated")

    monkeypatch.setattr("backend.app.sessions.exporters.os.replace", fail_replace)
    with pytest.raises(OSError):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))


def test_read_jsonl_reports_safe_file_and_line_only(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{}\nSECRET invalid\n", encoding="utf-8")
    records, warnings = read_jsonl(path)
    assert len(records) == 1
    assert warnings[0].public_message() == "events.jsonl:2:malformed_json"
    assert "SECRET" not in warnings[0].public_message()
