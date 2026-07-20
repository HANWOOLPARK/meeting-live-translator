"""Strict Pydantic schema used only at the external Provider boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidencePayload(StrictAnalysisModel):
    text: str = Field(min_length=1)
    evidence_segment_ids: list[str]


class ActionItemPayload(StrictAnalysisModel):
    task: str = Field(min_length=1)
    assignee: str
    due_date: str
    evidence_segment_ids: list[str]


class AnalysisResponsePayload(StrictAnalysisModel):
    meeting_purpose: EvidencePayload
    key_discussions: list[EvidencePayload]
    decisions: list[EvidencePayload]
    action_items: list[ActionItemPayload]
    open_questions: list[EvidencePayload]
    next_meeting_checks: list[EvidencePayload]
    warnings: list[str]


__all__ = [
    "ActionItemPayload",
    "AnalysisResponsePayload",
    "EvidencePayload",
]
