from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.analysis import AnalysisErrorCode, AnalysisProviderHealth, AnalysisProviderError
from backend.app.capture.controller import CaptureController
from backend.app.config.settings import AppSettings
from backend.app.decision_radar import (
    DecisionRadarManager,
    DecisionRadarProvider,
    GeminiDecisionRadarProvider,
    OpenAIDecisionRadarProvider,
    RadarBatchResult,
    RadarItemCategory,
    RadarRequest,
    RadarSegment,
    RadarSuggestion,
)
from backend.app.decision_radar.structured import RadarResponsePayload
from backend.app.decision_radar.prompts import (
    build_radar_input,
    build_radar_instructions,
)
from backend.app.main import create_app
from backend.app.services import build_services
from backend.app.sessions.models import FinalTranscript
from backend.app.sessions.repository import JsonlSessionRepository

from .fakes import FakeDeviceProvider, RecordingManager


class RecordingRadarProvider(DecisionRadarProvider):
    provider_name = "openai"
    display_name = "OpenAI API"
    external = True
    model = "fake-radar-model"
    api_key_configured = True

    def __init__(self, *, provider_name: str = "openai") -> None:
        self.provider_name = provider_name
        self.display_name = "Gemini API" if provider_name == "gemini" else "OpenAI API"
        self.calls: list[RadarRequest] = []
        self.closed = False

    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        self.calls.append(request)
        segment_ids = tuple(segment.segment_id for segment in request.segments)
        return RadarBatchResult(
            self.provider_name,
            self.model,
            (
                RadarSuggestion(
                    RadarItemCategory.DECISION,
                    "Ship the prototype on Friday",
                    segment_ids,
                ),
                RadarSuggestion(
                    RadarItemCategory.ACTION_ITEM,
                    "Min will verify the demo",
                    (segment_ids[-1],),
                    assignee="Min",
                    due_date="Friday",
                ),
            ),
        )

    async def health_check(self) -> AnalysisProviderHealth:
        return AnalysisProviderHealth(
            self.provider_name,
            self.display_name,
            not self.closed,
            self.external,
            model=self.model,
        )

    async def close(self) -> None:
        self.closed = True


class NoneLikeRadarProvider(RecordingRadarProvider):
    provider_name = "none"
    display_name = "Disabled"
    external = False
    model = None
    api_key_configured = False

    def __init__(self) -> None:
        super().__init__(provider_name="none")
        self.external = False
        self.model = None

    async def analyze(self, request: RadarRequest) -> RadarBatchResult:
        return RadarBatchResult("none", None, ())


def _event(
    segment_id: str,
    *,
    session_id: str = "session-1",
    target_language: str = "ko",
    context_matches: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "type": "final_transcript",
        "session_id": session_id,
        "segment_id": segment_id,
        "text": f"Final evidence {segment_id}",
        "normalized_text": f"Final evidence {segment_id}",
        "language": "en",
        "target_language": target_language,
        "started_at": "2026-07-15T12:00:00+09:00",
        "ended_at": "2026-07-15T12:00:01+09:00",
        "context_matches": list(context_matches),
    }


async def _wait_for_batches(manager: DecisionRadarManager, count: int = 1) -> None:
    for _ in range(200):
        if manager.diagnostics()["processed_batches"] >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("Decision Radar did not finish its test batch")


def test_manager_batches_finals_links_evidence_and_persists_review(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = RecordingRadarProvider()
        events: list[dict[str, Any]] = []
        manager = DecisionRadarManager(
            store_path=tmp_path / "decision_radar.json",
            provider_factories={
                "none": NoneLikeRadarProvider,
                "openai": lambda: provider,
                "gemini": lambda: RecordingRadarProvider(provider_name="gemini"),
            },
            selected_provider="openai",
            batch_size=2,
            batch_wait_seconds=0.05,
            timeout_seconds=1,
            max_retries=0,
            event_sink=events.append,
            context_supplier=lambda: {
                "active_profile_id": "general",
                "profiles": [
                    {
                        "id": "general",
                        "entries": [
                            {"category": "person", "canonical": "Min", "variants": ["Ming"]}
                        ],
                    }
                ],
            },
        )
        await manager.start()

        assert await manager.submit_final(_event("seg-1"))
        assert await manager.submit_final(
            _event(
                "seg-2",
                context_matches=(
                    {
                        "entry_id": "person-min",
                        "category": "person",
                        "from": "Ming",
                        "to": "Min",
                        "canonical": "Min",
                    },
                ),
            )
        )
        await _wait_for_batches(manager)

        assert len(provider.calls) == 1
        assert provider.calls[0].segment_ids == frozenset({"seg-1", "seg-2"})
        assert provider.calls[0].context_entries[0]["canonical"] == "Min"
        assert provider.calls[0].context_entries[0]["matched_as"] == "Ming"
        assert len(provider.calls[0].context_entries) == 1
        snapshot = manager.snapshot("session-1")
        assert snapshot["status"] == "idle"
        assert len(snapshot["items"]) == 2
        decision = next(item for item in snapshot["items"] if item["category"] == "decision")
        assert decision["evidence_segment_ids"] == ["seg-1", "seg-2"]

        updated = await manager.update_item(
            decision["item_id"],
            review_status="approved",
            text="Ship the verified prototype on Friday",
        )
        assert updated["review_status"] == "approved"
        assert updated["user_edited"] is True

        action = next(item for item in manager.snapshot()["items"] if item["category"] == "action_item")
        deleted = await manager.delete_item(action["item_id"])
        assert deleted["deleted"] is True
        assert len(manager.snapshot()["items"]) == 1

        saved = json.loads((tmp_path / "decision_radar.json").read_text(encoding="utf-8"))
        saved_state = saved["sessions"]["session-1"]
        assert saved_state["items"][0]["review_status"] == "approved"
        assert saved_state["tombstones"]
        assert {event["type"] for event in events} >= {
            "decision_radar_status",
            "decision_radar_updated",
        }
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_deduplicates_same_final_and_never_queues_partial(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = RecordingRadarProvider()
        manager = DecisionRadarManager(
            store_path=tmp_path / "radar.json",
            provider_factories={
                "none": NoneLikeRadarProvider,
                "openai": lambda: provider,
                "gemini": lambda: RecordingRadarProvider(provider_name="gemini"),
            },
            selected_provider="openai",
            batch_size=1,
            batch_wait_seconds=0.01,
            timeout_seconds=1,
            max_retries=0,
        )
        await manager.start()
        assert not await manager.submit_final({"type": "partial_transcript", "text": "partial"})
        assert await manager.submit_final(_event("seg-1"))
        assert await manager.submit_final(_event("seg-1"))
        await _wait_for_batches(manager)
        await asyncio.sleep(0.03)
        assert len(provider.calls) == 1
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_supplies_rolling_context_and_marks_only_new_focus(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        provider = RecordingRadarProvider()
        manager = DecisionRadarManager(
            store_path=tmp_path / "radar.json",
            provider_factories={
                "none": NoneLikeRadarProvider,
                "openai": lambda: provider,
                "gemini": lambda: RecordingRadarProvider(provider_name="gemini"),
            },
            selected_provider="openai",
            batch_size=1,
            batch_wait_seconds=0.01,
            context_window_segments=3,
            timeout_seconds=1,
            max_retries=0,
        )
        await manager.start()

        for index in range(1, 5):
            assert await manager.submit_final(_event(f"seg-{index}"))
            await _wait_for_batches(manager, index)

        assert [
            segment.segment_id for segment in provider.calls[2].segments
        ] == ["seg-1", "seg-2", "seg-3"]
        assert provider.calls[2].focus_segment_ids == ("seg-3",)
        assert [
            segment.segment_id for segment in provider.calls[3].segments
        ] == ["seg-2", "seg-3", "seg-4"]
        assert provider.calls[3].focus_segment_ids == ("seg-4",)
        assert manager.snapshot()["context_window_segments"] == 3
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_propagates_target_language_to_provider_request(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = RecordingRadarProvider()
        manager = DecisionRadarManager(
            store_path=tmp_path / "radar.json",
            provider_factories={
                "none": NoneLikeRadarProvider,
                "openai": lambda: provider,
                "gemini": lambda: RecordingRadarProvider(provider_name="gemini"),
            },
            selected_provider="openai",
            batch_size=1,
            batch_wait_seconds=0.01,
            timeout_seconds=1,
            max_retries=0,
        )
        await manager.start()
        assert await manager.submit_final(_event("seg-en", target_language="en"))
        await _wait_for_batches(manager)

        assert provider.calls[0].output_language == "en"
        assert provider.calls[0].segments[0].target_language == "en"
        await manager.shutdown()

    asyncio.run(scenario())


def test_manager_retracts_only_unreviewed_suggestions(tmp_path: Path) -> None:
    class RetractingProvider(RecordingRadarProvider):
        async def analyze(self, request: RadarRequest) -> RadarBatchResult:
            self.calls.append(request)
            focus_id = request.focus_segment_ids[-1]
            if len(self.calls) == 1:
                return RadarBatchResult(
                    self.provider_name,
                    self.model,
                    (
                        RadarSuggestion(
                            RadarItemCategory.DECISION,
                            "Approved decision remains",
                            (focus_id,),
                        ),
                        RadarSuggestion(
                            RadarItemCategory.ACTION_ITEM,
                            "Conditional advice was misclassified",
                            (focus_id,),
                            assignee="미정",
                            due_date="미정",
                        ),
                    ),
                )
            return RadarBatchResult(
                self.provider_name,
                self.model,
                (),
                tuple(str(item["item_id"]) for item in request.existing_items),
            )

    async def scenario() -> None:
        provider = RetractingProvider()
        manager = DecisionRadarManager(
            store_path=tmp_path / "radar.json",
            provider_factories={
                "none": NoneLikeRadarProvider,
                "openai": lambda: provider,
                "gemini": lambda: RecordingRadarProvider(provider_name="gemini"),
            },
            selected_provider="openai",
            batch_size=1,
            batch_wait_seconds=0.01,
            context_window_segments=3,
            timeout_seconds=1,
            max_retries=0,
        )
        await manager.start()
        assert await manager.submit_final(_event("seg-1"))
        await _wait_for_batches(manager, 1)

        first_items = manager.snapshot()["items"]
        approved = next(item for item in first_items if item["category"] == "decision")
        await manager.update_item(approved["item_id"], review_status="approved")

        assert await manager.submit_final(_event("seg-2"))
        await _wait_for_batches(manager, 2)
        remaining = manager.snapshot()["items"]
        assert [item["text"] for item in remaining] == [
            "Approved decision remains",
            "Conditional advice was misclassified",
        ]
        assert remaining[0]["review_status"] == "approved"
        assert remaining[0]["lifecycle_status"] == "active"
        assert remaining[1]["lifecycle_status"] == "retracted"
        assert remaining[1]["lifecycle_reason"]
        assert provider.calls[1].retractable_item_ids == frozenset(
            {
                next(
                    item["item_id"]
                    for item in provider.calls[1].existing_items
                    if item["category"] == "action_item"
                )
            }
        )
        assert all(
            "evidence_segment_ids" not in item
            and "created_at" not in item
            and "updated_at" not in item
            for item in provider.calls[1].existing_items
        )
        diagnostics = manager.diagnostics()
        assert diagnostics["provider_attempts"] == 2
        assert diagnostics["analyzed_focus_segments"] == 2
        await manager.shutdown()

    asyncio.run(scenario())


def _structured_payload(
    segment_id: str = "seg-1",
    *,
    retract_item_ids: tuple[str, ...] = (),
) -> RadarResponsePayload:
    return RadarResponsePayload.model_validate(
        {
            "decisions": [
                {"text": "Use the new deployment", "evidence_segment_ids": [segment_id]}
            ],
            "action_items": [
                {
                    "task": "Min verifies the build",
                    "assignee": "Min",
                    "due_date": "Friday",
                    "evidence_segment_ids": [segment_id],
                }
            ],
            "open_questions": [],
            "needs_confirmation": [
                {
                    "kind": "person",
                    "text": "Confirm whether the name is Min",
                    "evidence_segment_ids": [segment_id],
                }
            ],
            "retract_item_ids": list(retract_item_ids),
        }
    )


def _request() -> RadarRequest:
    return RadarRequest(
        "session-1",
        (
            RadarSegment(
                session_id="session-1",
                segment_id="seg-1",
                original_text="We decided to use the new deployment. Min will verify it.",
                normalized_text="We decided to use the new deployment. Min will verify it.",
                language="en",
            ),
        ),
        context_entries=(
            {"category": "person", "canonical": "Min", "variants": ["Ming"]},
        ),
    )


class FakeResponses:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


class FakeOpenAIClient:
    def __init__(self, parsed: Any) -> None:
        self.responses = FakeResponses(parsed)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeGeminiModels:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(parsed=self.parsed)


class FakeGeminiClient:
    def __init__(self, parsed: Any) -> None:
        self.models = FakeGeminiModels(parsed)
        self.aio = SimpleNamespace(models=self.models)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_openai_and_gemini_use_structured_outputs_and_validate_evidence() -> None:
    async def scenario() -> None:
        openai_client = FakeOpenAIClient(_structured_payload())
        openai = OpenAIDecisionRadarProvider(
            api_key="test-key",
            model="gpt-5.6-luna",
            client=openai_client,
        )
        openai_result = await openai.analyze(_request())
        assert len(openai_result.suggestions) == 3
        assert openai_result.suggestions[-1].confirmation_kind == "person"
        openai_call = openai_client.responses.calls[0]
        assert openai_call["text_format"] is RadarResponsePayload
        assert openai_call["store"] is False
        assert "seg-1" in openai_call["input"]
        assert "Min" in openai_call["input"]
        openai_input = json.loads(openai_call["input"])
        assert openai_input["focus_segment_ids"] == ["seg-1"]
        assert openai_input["finalized_segments"][0]["is_focus"] is True
        assert openai_input["retractable_item_ids"] == []
        assert "generic advice" in openai_call["instructions"]
        assert "retract_item_ids" in openai_call["instructions"]
        assert openai_result.request_input_characters == (
            len(openai_call["instructions"]) + len(openai_call["input"])
        )

        gemini_client = FakeGeminiClient(_structured_payload())
        gemini = GeminiDecisionRadarProvider(
            api_key="test-key",
            model="gemini-test",
            client=gemini_client,
        )
        gemini_result = await gemini.analyze(_request())
        assert len(gemini_result.suggestions) == 3
        gemini_call = gemini_client.models.calls[0]
        assert "response_schema" not in gemini_call["config"]
        assert (
            gemini_call["config"]["response_json_schema"]
            == RadarResponsePayload.model_json_schema()
        )
        assert gemini_call["config"]["response_json_schema"]["additionalProperties"] is False
        assert gemini_call["config"]["response_mime_type"] == "application/json"

        invalid = OpenAIDecisionRadarProvider(
            api_key="test-key",
            model="gpt-test",
            client=FakeOpenAIClient(_structured_payload("seg-not-in-request")),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await invalid.analyze(_request())
        assert caught.value.code is AnalysisErrorCode.INVALID_EVIDENCE

        unknown_retraction = OpenAIDecisionRadarProvider(
            api_key="test-key",
            model="gpt-test",
            client=FakeOpenAIClient(
                _structured_payload(retract_item_ids=("radar-unknown",))
            ),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await unknown_retraction.analyze(_request())
        assert caught.value.code is AnalysisErrorCode.INVALID_RESPONSE

        await openai.close()
        await gemini.close()

    asyncio.run(scenario())


def test_provider_rejects_suggestion_without_new_focus_evidence() -> None:
    async def scenario() -> None:
        request = RadarRequest(
            "session-1",
            (
                RadarSegment("session-1", "seg-context", "Earlier context"),
                RadarSegment("session-1", "seg-focus", "New final"),
            ),
            focus_segment_ids=("seg-focus",),
        )
        provider = OpenAIDecisionRadarProvider(
            api_key="test-key",
            model="gpt-test",
            client=FakeOpenAIClient(_structured_payload("seg-context")),
        )
        with pytest.raises(AnalysisProviderError) as caught:
            await provider.analyze(request)
        assert caught.value.code is AnalysisErrorCode.INVALID_EVIDENCE

    asyncio.run(scenario())


def test_provider_salvages_valid_items_and_evidence_from_partial_response() -> None:
    async def scenario() -> None:
        payload = RadarResponsePayload.model_validate(
            {
                "decisions": [
                    {
                        "text": "Use the new deployment",
                        "evidence_segment_ids": ["seg-1", "seg-invented"],
                    }
                ],
                "action_items": [
                    {
                        "task": "Invented action",
                        "assignee": "",
                        "due_date": "",
                        "evidence_segment_ids": ["seg-invented"],
                    }
                ],
                "open_questions": [],
                "needs_confirmation": [
                    {
                        "kind": "person",
                        "text": "Confirm whether the name is Min",
                        "evidence_segment_ids": ["seg-1"],
                    }
                ],
                "retract_item_ids": [],
            }
        )
        provider = OpenAIDecisionRadarProvider(
            api_key="test-key",
            model="gpt-test",
            client=FakeOpenAIClient(payload),
        )

        result = await provider.analyze(_request())

        assert [item.text for item in result.suggestions] == [
            "Use the new deployment",
            "Confirm whether the name is Min",
        ]
        assert result.suggestions[0].evidence_segment_ids == ("seg-1",)
        assert result.discarded_evidence_references == 2
        assert result.discarded_suggestions == 1

    asyncio.run(scenario())


def test_radar_prompt_contract_handles_reported_and_conditional_speech() -> None:
    request = RadarRequest(
        "session-1",
        (
            RadarSegment(
                "session-1",
                "seg-context",
                "以前の番組で一般的なアドバイスを紹介しました。",
                language="ja",
            ),
            RadarSegment(
                "session-1",
                "seg-focus",
                "続ける場合は長い期間が必要になるかもしれません。",
                language="ja",
            ),
        ),
        focus_segment_ids=("seg-focus",),
    )
    payload = json.loads(build_radar_input(request))
    instructions = build_radar_instructions()

    assert payload["focus_segment_ids"] == ["seg-focus"]
    assert [item["is_focus"] for item in payload["finalized_segments"]] == [
        False,
        True,
    ]
    for guardrail in (
        "reported speech",
        "audience request",
        "generic advice",
        "rhetorical question",
        "duration estimate",
        "explicit future commitment",
    ):
        assert guardrail in instructions


def test_radar_prompt_compacts_rolling_context_and_existing_items() -> None:
    request = RadarRequest(
        "session-1",
        (
            RadarSegment(
                "session-1",
                "seg-context",
                "Earlier finalized sentence",
                normalized_text="Earlier finalized sentence",
                translated_text="Earlier translation",
                language="en",
                started_at="2026-07-17T12:00:00+09:00",
                ended_at="2026-07-17T12:00:01+09:00",
            ),
            RadarSegment(
                "session-1",
                "seg-focus",
                "New finalized sentence",
                normalized_text="Canonical new sentence",
                translated_text="New translation",
                language="en",
                context_matches=({"canonical": "Aster", "category": "term"},),
            ),
        ),
        focus_segment_ids=("seg-focus",),
        existing_items=(
            {
                "item_id": "radar-1",
                "category": "action_item",
                "text": "Update the schedule",
                "review_status": "suggested",
                "user_edited": False,
            },
        ),
    )

    payload = json.loads(build_radar_input(request))
    context_segment, focus_segment = payload["finalized_segments"]

    assert "normalized_text" not in context_segment
    assert "translated_text" not in context_segment
    assert "started_at" not in context_segment
    assert "ended_at" not in context_segment
    assert focus_segment["normalized_text"] == "Canonical new sentence"
    assert focus_segment["translated_text"] == "New translation"
    assert focus_segment["context_matches"][0]["canonical"] == "Aster"
    assert payload["existing_items"] == list(request.existing_items)

    instructions = build_radar_instructions()
    for guardrail in (
        "Consolidate one workflow into one action item",
        "supporting rationale",
        "not an open question",
        "needs_confirmation, never as open_question",
        "Never infer a speaker's identity",
    ):
        assert guardrail in instructions


@pytest.mark.parametrize(
    ("output_language", "language_name", "unknown_value"),
    (("ko", "Korean", "미정"), ("en", "English", "TBD"), ("ja", "Japanese", "未定")),
)
def test_radar_prompt_follows_translation_target_language(
    output_language: str,
    language_name: str,
    unknown_value: str,
) -> None:
    request = RadarRequest(
        "session-1",
        (RadarSegment("session-1", "seg-1", "Final evidence"),),
        output_language=output_language,
    )

    payload = json.loads(build_radar_input(request))
    instructions = build_radar_instructions(output_language)

    assert payload["output_language"] == output_language
    assert f"write them in {language_name}" in instructions
    assert f"'{unknown_value}'" in instructions


def test_capture_publishes_only_final_payload_to_radar_observer(tmp_path: Path) -> None:
    class RadarObserver:
        def __init__(self) -> None:
            self.finals: list[dict[str, Any]] = []

        async def submit_final(self, event: dict[str, Any]) -> bool:
            self.finals.append(event)
            return True

    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "sessions")
        session_id = repository.start_session({"source": "system"})
        radar = RadarObserver()
        websocket = RecordingManager()
        controller = CaptureController(
            AppSettings(project_root=tmp_path, session_dir=tmp_path / "sessions"),
            FakeDeviceProvider(),
            websocket,
            repository,
            decision_radar_manager=radar,  # type: ignore[arg-type]
        )
        transcript = FinalTranscript(
            segment_id="seg-final",
            session_id=session_id,
            utterance_id="utterance-1",
            source="system",
            text="This is a finalized decision.",
            language="en",
            language_probability=0.99,
            started_at="2026-07-15T12:00:00+09:00",
            ended_at="2026-07-15T12:00:01+09:00",
            inference_seconds=0.05,
        )

        await controller._publish_final_transcript(transcript)

        assert len(radar.finals) == 1
        assert radar.finals[0]["type"] == "final_transcript"
        assert radar.finals[0]["segment_id"] == "seg-final"
        assert radar.finals[0]["text"] == transcript.text
        assert radar.finals[0]["target_language"] == "ko"
        assert any(event["type"] == "final_transcript" for event in websocket.events)
        await controller.shutdown()

    asyncio.run(scenario())


def test_radar_observer_failure_does_not_suppress_final_transcript(
    tmp_path: Path,
) -> None:
    class FailingRadarObserver:
        async def submit_final(self, event: dict[str, Any]) -> bool:
            raise RuntimeError("private provider failure")

    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "sessions")
        session_id = repository.start_session({"source": "system"})
        websocket = RecordingManager()
        controller = CaptureController(
            AppSettings(project_root=tmp_path, session_dir=tmp_path / "sessions"),
            FakeDeviceProvider(),
            websocket,
            repository,
            decision_radar_manager=FailingRadarObserver(),  # type: ignore[arg-type]
        )
        transcript = FinalTranscript(
            segment_id="seg-survives",
            session_id=session_id,
            utterance_id="utterance-1",
            source="system",
            text="The original must survive.",
            language="en",
            language_probability=0.99,
            started_at="2026-07-15T12:00:00+09:00",
            ended_at="2026-07-15T12:00:01+09:00",
            inference_seconds=0.05,
        )

        await controller._publish_final_transcript(transcript)

        assert any(
            event["type"] == "final_transcript"
            and event["segment_id"] == "seg-survives"
            for event in websocket.events
        )
        stored = repository.get_session(session_id)
        assert stored["segments"][0]["original_text"] == transcript.text
        await controller.shutdown()

    asyncio.run(scenario())


def test_decision_radar_api_provider_selection_items_and_secret_redaction(
    tmp_path: Path,
) -> None:
    created: list[RecordingRadarProvider] = []

    def provider_factory(name: str):
        def factory() -> RecordingRadarProvider:
            provider = RecordingRadarProvider(provider_name=name)
            created.append(provider)
            return provider

        return factory

    settings = AppSettings(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        static_dir=Path(__file__).resolve().parents[1] / "frontend" / "static",
        openai_api_key="secret-radar-key",
        openai_decision_radar_model="gpt-5.6-luna",
        decision_radar_provider="none",
        decision_radar_batch_size=1,
        decision_radar_batch_wait_seconds=1.0,
    )
    services = build_services(
        settings,
        device_provider=FakeDeviceProvider(),
        decision_radar_provider_factories={
            "none": NoneLikeRadarProvider,
            "openai": provider_factory("openai"),
            "gemini": provider_factory("gemini"),
        },
    )

    with TestClient(create_app(services)) as client:
        providers = client.get("/api/decision-radar/providers")
        public_settings = client.get("/api/decision-radar/settings")
        assert providers.status_code == 200
        assert {item["id"] for item in providers.json()["providers"]} == {
            "none",
            "openai",
            "gemini",
        }
        assert public_settings.json()["openai_api_key_configured"] is True
        assert "secret-radar-key" not in providers.text + public_settings.text
        assert str(tmp_path) not in providers.text + public_settings.text

        selected = client.post(
            "/api/decision-radar/settings",
            json={"provider": "openai"},
        )
        assert selected.status_code == 200
        assert selected.json()["provider"] == "openai"

        assert client.portal.call(
            services.decision_radar_manager.submit_final,
            _event("seg-api"),
        )
        for _ in range(100):
            radar = client.get("/api/decision-radar").json()
            if radar["items"]:
                break
            time.sleep(0.01)
        assert radar["items"]
        item_id = radar["items"][0]["item_id"]

        updated = client.patch(
            f"/api/decision-radar/items/{item_id}",
            json={"review_status": "approved", "text": "Approved API decision"},
        )
        assert updated.status_code == 200
        assert updated.json()["item"]["review_status"] == "approved"
        assert updated.json()["item"]["user_edited"] is True

        deleted = client.delete(f"/api/decision-radar/items/{item_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        diagnostics = client.get("/api/diagnostics")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["decision_radar"]["provider"] == "openai"
        assert "Approved API decision" not in diagnostics.text
        assert "secret-radar-key" not in diagnostics.text

        with client.websocket_connect("/ws/live") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert "decision_radar" in snapshot


def test_frontend_contains_live_radar_controls_and_evidence_actions() -> None:
    root = Path(__file__).resolve().parents[1] / "frontend" / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    style = (root / "style.css").read_text(encoding="utf-8")

    for element_id in (
        "decisionRadarProviderSelect",
        "decisionRadarApplyButton",
        "decisionRadarStatusBadge",
        "decisionRadarDecisions",
        "decisionRadarActions",
        "decisionRadarQuestions",
        "decisionRadarConfirmations",
        "decisionRadarTabs",
        "decisionRadarLatestButton",
        "translationConfigToggle",
    ):
        assert f'id="{element_id}"' in html
    assert "/api/decision-radar/settings" in script
    settings_handler = script[script.index("async function saveDecisionRadarSettings"):script.index("async function mutateDecisionRadarItem")]
    assert "window.confirm" not in settings_handler
    assert 'confirmingProvider !== radar.selected' in settings_handler
    assert 't("외부 API 적용 확인")' in script
    assert "data-radar-action" in script
    assert "data-evidence-segment-id" in script
    assert 'core: ["decision", "action_item"]' in script
    assert 'issues: ["open_question", "needs_confirmation"]' in script
    assert "pinnedToLatest" in script
    assert 'data-collapsed="true"' in html
    assert 'grid-template-areas:' in style
    assert '.decision-radar-tabs' in style
    assert ".decision-radar-card" in style
    assert "--live-panel-height" in style
    assert "height: var(--live-panel-height)" in style
    assert ".decision-radar-scroll::-webkit-scrollbar" in style
    assert "overscroll-behavior: contain" in style


def test_decision_radar_environment_configuration_is_bounded_and_public(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "DECISION_RADAR_PROVIDER": "gemini",
        "OPENAI_DECISION_RADAR_MODEL": "gpt-5.6-luna",
        "GEMINI_DECISION_RADAR_MODEL": "gemini-radar-test",
        "DECISION_RADAR_BATCH_SIZE": "4",
        "DECISION_RADAR_BATCH_WAIT_SECONDS": "8",
        "DECISION_RADAR_CONTEXT_SEGMENTS": "24",
        "DECISION_RADAR_QUEUE_MAX_SIZE": "55",
        "DECISION_RADAR_TIMEOUT_SECONDS": "18",
        "DECISION_RADAR_MAX_RETRIES": "2",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = AppSettings.from_env(tmp_path)

    assert settings.decision_radar_provider == "gemini"
    assert settings.gemini_decision_radar_model == "gemini-radar-test"
    assert settings.decision_radar_batch_size == 4
    assert settings.decision_radar_batch_wait_seconds == 8
    assert settings.decision_radar_context_segments == 24
    assert settings.decision_radar_queue_max_size == 55
    assert settings.decision_radar_timeout_seconds == 18
    assert settings.decision_radar_max_retries == 2
    public = settings.public_dict()["decision_radar"]
    assert public["provider"] == "gemini"
    assert public["context_segments"] == 24
    assert not any("key" in name.lower() for name in public)


def test_decision_radar_cost_safe_defaults(tmp_path: Path) -> None:
    settings = AppSettings(project_root=tmp_path)

    assert settings.openai_decision_radar_model == "gpt-5.4-mini"
    assert settings.decision_radar_batch_size == 10
    assert settings.decision_radar_batch_wait_seconds == 20
    assert settings.decision_radar_context_segments == 16
