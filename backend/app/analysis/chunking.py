"""Segment-boundary-preserving chunking and conservative result merging."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .models import (
    ActionItem,
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
)


@dataclass(frozen=True, slots=True)
class AnalysisChunk:
    index: int
    segments: tuple[AnalysisSegment, ...]
    character_count: int
    warnings: tuple[str, ...] = ()


def chunk_segments(
    segments: Iterable[AnalysisSegment],
    *,
    max_segments: int = 100,
    max_characters: int = 24_000,
) -> tuple[AnalysisChunk, ...]:
    if max_segments <= 0 or max_characters <= 0:
        raise ValueError("chunk limits must be positive")
    chunks: list[AnalysisChunk] = []
    current: list[AnalysisSegment] = []
    current_characters = 0

    def flush() -> None:
        nonlocal current, current_characters
        if not current:
            return
        warnings = (
            ("oversized_segment",)
            if len(current) == 1 and current_characters > max_characters
            else ()
        )
        chunks.append(
            AnalysisChunk(
                index=len(chunks),
                segments=tuple(current),
                character_count=current_characters,
                warnings=warnings,
            )
        )
        current = []
        current_characters = 0

    for segment in segments:
        size = segment.prompt_characters
        if current and (
            len(current) >= max_segments
            or current_characters + size > max_characters
        ):
            flush()
        current.append(segment)
        current_characters += size
        if len(current) >= max_segments or current_characters >= max_characters:
            flush()
    flush()
    return tuple(chunks)


def chunk_request(
    request: AnalysisRequest,
    *,
    max_segments: int = 100,
    max_characters: int = 24_000,
) -> tuple[tuple[AnalysisRequest, tuple[str, ...]], ...]:
    return tuple(
        (request.with_segments(chunk.segments), chunk.warnings)
        for chunk in chunk_segments(
            request.segments,
            max_segments=max_segments,
            max_characters=max_characters,
        )
    )


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s\W_]+", "", value)


def _merge_evidence(items: Iterable[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    merged: dict[str, EvidenceItem] = {}
    for item in items:
        key = _normalized(item.text)
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
        else:
            merged[key] = EvidenceItem(
                existing.text,
                (*existing.evidence_segment_ids, *item.evidence_segment_ids),
            )
    return tuple(merged.values())


def _merge_actions(items: Iterable[ActionItem]) -> tuple[ActionItem, ...]:
    grouped: dict[str, list[ActionItem]] = {}
    for item in items:
        key = _normalized(item.task)
        grouped.setdefault(key, []).append(item)

    merged: list[ActionItem] = []
    for group in grouped.values():
        assignees = {
            item.assignee for item in group if item.assignee != UNDECIDED
        }
        due_dates = {
            item.due_date for item in group if item.due_date != UNDECIDED
        }
        merged.append(
            ActionItem(
                task=group[0].task,
                assignee=next(iter(assignees)) if len(assignees) == 1 else UNDECIDED,
                due_date=next(iter(due_dates)) if len(due_dates) == 1 else UNDECIDED,
                evidence_segment_ids=tuple(
                    evidence_id
                    for item in group
                    for evidence_id in item.evidence_segment_ids
                ),
            )
        )
    return tuple(merged)


def merge_analyses(
    session_id: str,
    analyses: Iterable[MeetingAnalysis],
    *,
    provider: str,
    model: str | None,
    warnings: Iterable[str] = (),
) -> MeetingAnalysis:
    parts = tuple(analyses)
    purposes = [
        item.meeting_purpose
        for item in parts
        if item.meeting_purpose.text != UNDECIDED
    ]
    merged_warnings = list(warnings)
    merged_warnings.extend(warning for item in parts for warning in item.warnings)
    purpose_candidates = _merge_evidence(purposes)
    purpose = purpose_candidates[0] if purpose_candidates else EvidenceItem(UNDECIDED)
    if len(purpose_candidates) > 1:
        merged_warnings.append("multiple_meeting_purpose_candidates")

    decisions = _merge_evidence(item for part in parts for item in part.decisions)
    for index, left in enumerate(decisions):
        left_ids = set(left.evidence_segment_ids)
        for right in decisions[index + 1 :]:
            if left_ids.intersection(right.evidence_segment_ids) and _normalized(
                left.text
            ) != _normalized(right.text):
                merged_warnings.append("conflicting_decisions")
                break

    return MeetingAnalysis(
        session_id=session_id,
        provider=provider,
        model=model,
        status=AnalysisStatus.COMPLETED,
        meeting_purpose=purpose,
        key_discussions=_merge_evidence(
            item for part in parts for item in part.key_discussions
        ),
        decisions=decisions,
        action_items=_merge_actions(item for part in parts for item in part.action_items),
        open_questions=_merge_evidence(
            item for part in parts for item in part.open_questions
        ),
        next_meeting_checks=_merge_evidence(
            item for part in parts for item in part.next_meeting_checks
        ),
        warnings=tuple(merged_warnings),
    )


__all__ = [
    "AnalysisChunk",
    "chunk_request",
    "chunk_segments",
    "merge_analyses",
]
