"""Strict evidence validation for every analysis Provider."""

from __future__ import annotations

from typing import Iterable

from .exceptions import AnalysisErrorCode, analysis_error
from .models import MeetingAnalysis


def evidence_ids(analysis: MeetingAnalysis) -> tuple[str, ...]:
    values: list[str] = list(analysis.meeting_purpose.evidence_segment_ids)
    for collection in (
        analysis.key_discussions,
        analysis.decisions,
        analysis.open_questions,
        analysis.next_meeting_checks,
    ):
        for item in collection:
            values.extend(item.evidence_segment_ids)
    for item in analysis.action_items:
        values.extend(item.evidence_segment_ids)
    return tuple(values)


def validate_evidence(
    analysis: MeetingAnalysis,
    valid_segment_ids: Iterable[str],
) -> MeetingAnalysis:
    valid = frozenset(str(value) for value in valid_segment_ids)
    if (
        analysis.meeting_purpose.text != "미정"
        and not analysis.meeting_purpose.evidence_segment_ids
    ):
        raise analysis_error(AnalysisErrorCode.INVALID_EVIDENCE)
    evidence_required = [
        *analysis.key_discussions,
        *analysis.decisions,
        *analysis.open_questions,
        *analysis.next_meeting_checks,
        *analysis.action_items,
    ]
    if any(not item.evidence_segment_ids for item in evidence_required):
        raise analysis_error(AnalysisErrorCode.INVALID_EVIDENCE)
    if any(value not in valid for value in evidence_ids(analysis)):
        raise analysis_error(AnalysisErrorCode.INVALID_EVIDENCE)
    return analysis


__all__ = ["evidence_ids", "validate_evidence"]
