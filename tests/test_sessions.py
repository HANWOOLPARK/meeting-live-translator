from __future__ import annotations

import json

from backend.app.sessions.models import FinalTranscript
from backend.app.sessions.repository import JsonlSessionRepository


def test_repository_creates_no_file_until_a_final_transcript(tmp_path) -> None:
    repository = JsonlSessionRepository(tmp_path)
    session_id = repository.start_session()
    assert list(tmp_path.iterdir()) == []

    repository.append_final(
        FinalTranscript(
            segment_id="segment-1",
            session_id=session_id,
            utterance_id="utterance-1",
            source="system",
            text="確認しました",
            language="ja",
            language_probability=0.95,
            started_at="2026-07-10T20:30:11+09:00",
            ended_at="2026-07-10T20:30:15+09:00",
            inference_seconds=0.5,
        )
    )
    path = tmp_path / f"{session_id}.jsonl"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["text"] == "確認しました"

    repository.append_translation(
        session_id,
        {
            "segment_id": "segment-1",
            "source_language": "ja",
            "target_language": "ko",
            "translated_text": "확인했습니다.",
            "provider": "openai",
            "model": "test-model",
            "latency_ms": 125,
            "completed_at": "2026-07-10T20:30:16+09:00",
            "api_key": "must-not-be-saved",
        },
    )
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["text"] == "確認しました"
    assert records[1]["type"] == "translation"
    assert records[1]["segment_id"] == "segment-1"
    assert records[1]["translated_text"] == "확인했습니다."
    assert "api_key" not in records[1]
    repository.stop_session()
