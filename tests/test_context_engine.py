from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.app.config.settings import AppSettings
from backend.app.context_engine import ContextEngine, ContextEngineError
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sessions.models import FinalTranscript
from backend.app.transcription.deepgram_stream import DeepgramStreamingClient

from .fakes import FakeDeviceProvider


def test_profile_supports_people_aliases_and_persistence(tmp_path) -> None:
    path = tmp_path / "context.json"
    engine = ContextEngine(path)
    profile = engine.create_profile("프로젝트 A")
    entry = engine.add_entry(
        profile["id"],
        category="person",
        canonical="山田太郎",
        variants=["山田たろう", "山田 太郎"],
    )

    result = engine.normalize("山田たろうさん이 Fit & Gap을 설명합니다")

    assert result.normalized_text == "山田太郎さん이 Fit & Gap을 설명합니다"
    assert result.changed is True
    assert result.matches[0]["category"] == "person"
    assert result.matches[0]["canonical"] == "山田太郎"
    assert "山田太郎" in engine.keyterms()
    assert "山田たろう" in engine.keyterms()

    restored = ContextEngine(path)
    assert restored.snapshot()["active_profile_id"] == profile["id"]
    assert restored.snapshot()["profiles"][-1]["entries"][0]["id"] == entry["id"]

    exact = engine.normalize("山田太郎さんが説明します")
    assert exact.changed is False
    assert exact.matches[0]["canonical"] == "山田太郎"


def test_suggestions_require_explicit_accept_or_ignore(tmp_path) -> None:
    engine = ContextEngine(tmp_path / "context.json")
    segments = [
        {"segment_id": "s1", "original_text": "山田さんが BMS を確認します"},
        {"segment_id": "s2", "original_text": "BMS と PrimeDrive を接続します"},
    ]

    created = engine.generate_suggestions("session-1", segments)
    pending = engine.snapshot()["suggestions"]

    assert created
    assert all(item["status"] == "pending" for item in pending)
    assert not engine.snapshot()["profiles"][0]["entries"]

    person = next(item for item in pending if item["category"] == "person")
    resolved = engine.decide_suggestion(person["id"], accept=True)
    assert resolved["entry"]["canonical"] == "山田"
    assert resolved["entry"]["category"] == "person"

    remaining = engine.snapshot()["suggestions"]
    if remaining:
        ignored = engine.decide_suggestion(remaining[0]["id"], accept=False)
        assert ignored["suggestion"]["status"] == "ignored"


def test_duplicate_entry_is_rejected(tmp_path) -> None:
    engine = ContextEngine(tmp_path / "context.json")
    engine.add_entry("general", category="term", canonical="SoftBank")
    try:
        engine.add_entry("general", category="person", canonical="softbank")
    except ContextEngineError as error:
        assert error.code == "context_entry_exists"
    else:
        raise AssertionError("duplicate entry was accepted")


def test_aliases_cannot_overlap_or_cascade(tmp_path) -> None:
    engine = ContextEngine(tmp_path / "context.json")
    engine.add_entry(
        "general",
        category="term",
        canonical="PrimeDrive",
        variants=["prime drive"],
    )
    engine.add_entry(
        "general",
        category="term",
        canonical="PD Portal",
        variants=["PrimeDrive portal"],
    )

    # One pass prevents the first replacement from being consumed by the
    # second entry during the same normalization.
    assert engine.normalize("prime drive works").normalized_text == "PrimeDrive works"

    try:
        engine.add_entry(
            "general",
            category="person",
            canonical="다른 표기",
            variants=["prime drive"],
        )
    except ContextEngineError as error:
        assert error.code == "context_entry_exists"
    else:
        raise AssertionError("overlapping alias was accepted")


def test_deepgram_url_repeats_keyterm_parameters() -> None:
    client = DeepgramStreamingClient(
        api_key="test",
        model="nova-3",
        language="ja",
        keyterms=("山田太郎", "Fit & Gap"),
    )
    query = parse_qs(urlparse(client._url()).query)

    assert query["keyterm"] == ["山田太郎", "Fit & Gap"]
    assert client.snapshot()["keyterm_count"] == 2


def test_context_api_and_session_suggestions(tmp_path) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
    )
    services = build_services(settings, device_provider=FakeDeviceProvider())
    repository = services.repository
    session_id = repository.start_session({"source": "system", "whisper_model": "small"})
    repository.append_final(
        FinalTranscript(
            segment_id="s1",
            session_id=session_id,
            utterance_id="u1",
            source="system",
            text="山田さんが BMS を確認します",
            language="ja",
            language_probability=0.95,
            started_at="2026-07-15T10:00:00+09:00",
            ended_at="2026-07-15T10:00:02+09:00",
            inference_seconds=0.1,
        )
    )
    repository.stop_session()

    with TestClient(create_app(services)) as client:
        context = client.get("/api/context")
        assert context.status_code == 200
        assert context.json()["consent_required"] is True

        profile = client.post(
            "/api/context/profiles",
            json={"name": "회의 A", "description": "테스트"},
        )
        assert profile.status_code == 200
        profile_id = profile.json()["active_profile_id"]

        added = client.post(
            f"/api/context/profiles/{profile_id}/entries",
            json={
                "category": "person",
                "canonical": "山田太郎",
                "variants": ["山田たろう"],
            },
        )
        assert added.status_code == 200
        assert added.json()["keyterm_count"] == 2

        suggested = client.post(
            "/api/context/suggestions/generate",
            json={"session_id": session_id},
        )
        assert suggested.status_code == 200
        assert suggested.json()["created_suggestion_count"] >= 1


def test_final_keeps_original_but_translates_normalized_text(tmp_path) -> None:
    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=tmp_path,
    )
    context = ContextEngine(tmp_path / "context.json")
    context.add_entry(
        "general",
        category="person",
        canonical="山田太郎",
        variants=["山田たろう"],
    )
    services = build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        context_engine=context,
    )
    session_id = services.repository.start_session(
        {"source": "system", "whisper_model": "small"}
    )
    transcript = FinalTranscript(
        segment_id="segment-normalized",
        session_id=session_id,
        utterance_id="utterance-normalized",
        source="system",
        text="山田たろうさんが確認します",
        language="ja",
        language_probability=0.95,
        started_at="2026-07-15T10:00:00+09:00",
        ended_at="2026-07-15T10:00:02+09:00",
        inference_seconds=0.1,
    )

    async def scenario() -> None:
        await services.controller._publish_final_transcript(transcript)
        record = services.translation_manager.get_record("segment-normalized")
        assert record is not None
        assert record.request.source_text == "山田太郎さんが確認します"
        assert record.request.glossary_terms == ("山田太郎",)
        await services.translation_manager.shutdown()

    asyncio.run(scenario())
    session = services.repository.get_session(session_id)
    segment = session["segments"][0]
    assert segment["original_text"] == "山田たろうさんが確認します"
    assert segment["normalized_text"] == "山田太郎さんが確認します"
    assert segment["context_changed"] is True
