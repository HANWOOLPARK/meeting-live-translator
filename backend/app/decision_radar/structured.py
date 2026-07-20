"""Strict provider-boundary schema for live Decision Radar responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRadarModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RadarEvidencePayload(StrictRadarModel):
    text: str = Field(min_length=1)
    evidence_segment_ids: list[str] = Field(min_length=1)


class RadarActionPayload(StrictRadarModel):
    task: str = Field(min_length=1)
    assignee: str
    due_date: str
    evidence_segment_ids: list[str] = Field(min_length=1)


class RadarConfirmationPayload(StrictRadarModel):
    kind: Literal["person", "term", "translation"]
    text: str = Field(min_length=1)
    evidence_segment_ids: list[str] = Field(min_length=1)


class RadarResponsePayload(StrictRadarModel):
    decisions: list[RadarEvidencePayload]
    action_items: list[RadarActionPayload]
    open_questions: list[RadarEvidencePayload]
    needs_confirmation: list[RadarConfirmationPayload]
    retract_item_ids: list[str]


__all__ = [
    "RadarActionPayload",
    "RadarConfirmationPayload",
    "RadarEvidencePayload",
    "RadarResponsePayload",
]
