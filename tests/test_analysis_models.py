from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.analysis import (
    ActionItem,
    AnalysisErrorCode,
    AnalysisProviderError,
    AnalysisRequest,
    AnalysisResponsePayload,
    AnalysisSegment,
    AnalysisStatus,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
    chunk_request,
    chunk_segments,
    merge_analyses,
    validate_evidence,
)


def _segment(segment_id: str, text: str) -> AnalysisSegment:
    return AnalysisSegment(
        segment_id=segment_id,
        original_text=text,
        language="ja",
    )


def _analysis(
    *,
    decisions: tuple[EvidenceItem, ...] = (),
    actions: tuple[ActionItem, ...] = (),
) -> MeetingAnalysis:
    return MeetingAnalysis(
        session_id="session-1",
        provider="rule_based",
        model=None,
        status=AnalysisStatus.COMPLETED,
        meeting_purpose=EvidenceItem(UNDECIDED),
        decisions=decisions,
        action_items=actions,
    )


def test_structured_schema_forbids_unknown_fields() -> None:
    payload = {
        "meeting_purpose": {"text": "미정", "evidence_segment_ids": []},
        "key_discussions": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "next_meeting_checks": [],
        "warnings": [],
        "secret": "must not pass",
    }

    with pytest.raises(ValidationError):
        AnalysisResponsePayload.model_validate(payload)


def test_analysis_payload_requires_every_schema_field() -> None:
    with pytest.raises(ValueError, match="missing required"):
        MeetingAnalysis.from_payload(
            {"meeting_purpose": {"text": "미정", "evidence_segment_ids": []}},
            session_id="session-1",
            provider="rule_based",
            model=None,
        )


@pytest.mark.parametrize(
    ("assignee", "due_date"),
    [
        ("we", "soon"),
        ("담당팀", "빠른 시일 내"),
        ("担当チーム", "できるだけ早く"),
    ],
)
def test_action_item_normalizes_ambiguous_fields(
    assignee: str,
    due_date: str,
) -> None:
    item = ActionItem("자료를 확인한다", assignee, due_date, ("seg-1",))

    assert item.assignee == UNDECIDED
    assert item.due_date == UNDECIDED


def test_action_item_preserves_explicit_relative_deadline() -> None:
    item = ActionItem("보고서를 제출한다", "Tanaka", "by next week", ("seg-1",))

    assert item.assignee == "Tanaka"
    assert item.due_date == "by next week"


def test_evidence_validation_rejects_missing_and_unknown_references() -> None:
    missing = _analysis(decisions=(EvidenceItem("결정했다"),))
    unknown = _analysis(decisions=(EvidenceItem("결정했다", ("seg-404",)),))

    for result in (missing, unknown):
        with pytest.raises(AnalysisProviderError) as caught:
            validate_evidence(result, {"seg-1"})
        assert caught.value.code is AnalysisErrorCode.INVALID_EVIDENCE


def test_chunking_keeps_segment_boundaries_and_marks_oversized_segment() -> None:
    segments = (
        _segment("seg-1", "a" * 4),
        _segment("seg-2", "b" * 7),
        _segment("seg-3", "c" * 3),
    )

    chunks = chunk_segments(segments, max_segments=2, max_characters=5)

    assert [[item.segment_id for item in chunk.segments] for chunk in chunks] == [
        ["seg-1"],
        ["seg-2"],
        ["seg-3"],
    ]
    assert chunks[1].warnings == ("oversized_segment",)
    request_chunks = chunk_request(
        AnalysisRequest("session-1", segments),
        max_segments=2,
        max_characters=5,
    )
    assert request_chunks[1][0].segments == (segments[1],)


def test_merge_deduplicates_action_by_task_and_resolves_conflicting_metadata() -> None:
    first = _analysis(
        decisions=(EvidenceItem("System Test로 결정했다.", ("seg-1",)),),
        actions=(ActionItem("결과를 공유한다", "Kim", "2026-07-15", ("seg-1",)),),
    )
    second = _analysis(
        decisions=(EvidenceItem(" system test로 결정했다 ", ("seg-2",)),),
        actions=(ActionItem("결과를 공유한다!", "Lee", "2026-07-16", ("seg-2",)),),
    )

    merged = merge_analyses(
        "session-1",
        (first, second),
        provider="rule_based",
        model=None,
    )

    assert len(merged.decisions) == 1
    assert merged.decisions[0].evidence_segment_ids == ("seg-1", "seg-2")
    assert len(merged.action_items) == 1
    assert merged.action_items[0].assignee == UNDECIDED
    assert merged.action_items[0].due_date == UNDECIDED
    assert merged.action_items[0].evidence_segment_ids == ("seg-1", "seg-2")


def test_merge_keeps_action_conflict_after_a_b_a_sequence() -> None:
    parts = tuple(
        _analysis(
            actions=(
                ActionItem(
                    "결과를 공유한다",
                    assignee,
                    due_date,
                    (f"seg-{index}",),
                ),
            )
        )
        for index, (assignee, due_date) in enumerate(
            (
                ("Kim", "2026-07-15"),
                ("Lee", "2026-07-16"),
                ("Kim", "2026-07-15"),
            ),
            start=1,
        )
    )

    merged = merge_analyses(
        "session-1",
        parts,
        provider="rule_based",
        model=None,
    )

    assert merged.action_items[0].assignee == UNDECIDED
    assert merged.action_items[0].due_date == UNDECIDED
    assert merged.action_items[0].evidence_segment_ids == (
        "seg-1",
        "seg-2",
        "seg-3",
    )


def test_merge_combines_evidence_for_same_meeting_purpose() -> None:
    first = MeetingAnalysis(
        session_id="session-1",
        provider="rule_based",
        model=None,
        status=AnalysisStatus.COMPLETED,
        meeting_purpose=EvidenceItem("System Test 일정 확인", ("seg-1",)),
    )
    second = MeetingAnalysis(
        session_id="session-1",
        provider="rule_based",
        model=None,
        status=AnalysisStatus.COMPLETED,
        meeting_purpose=EvidenceItem("system test 일정 확인!", ("seg-2",)),
    )

    merged = merge_analyses(
        "session-1",
        (first, second),
        provider="rule_based",
        model=None,
    )

    assert merged.meeting_purpose.evidence_segment_ids == ("seg-1", "seg-2")
    assert "multiple_meeting_purpose_candidates" not in merged.warnings


def test_saved_payload_preserves_generated_timestamp() -> None:
    generated_at = "2026-07-11T10:01:02.345+09:00"
    result = MeetingAnalysis.from_payload(
        {
            "meeting_purpose": {"text": "미정", "evidence_segment_ids": []},
            "key_discussions": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "next_meeting_checks": [],
            "warnings": [],
        },
        session_id="session-1",
        provider="rule_based",
        model=None,
        generated_at=generated_at,
    )

    assert result.generated_at == generated_at
