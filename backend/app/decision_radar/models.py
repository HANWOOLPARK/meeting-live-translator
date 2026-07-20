"""Serializable models for the evidence-linked live Decision Radar."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import uuid4


RADAR_SCHEMA_VERSION = 2


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _clean(value: Any, *, maximum: int = 4_000) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > maximum:
        text = text[:maximum].rstrip()
    return text


def _unique(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value, maximum=128)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


class RadarItemCategory(str, Enum):
    DECISION = "decision"
    ACTION_ITEM = "action_item"
    OPEN_QUESTION = "open_question"
    NEEDS_CONFIRMATION = "needs_confirmation"


class RadarReviewStatus(str, Enum):
    SUGGESTED = "suggested"
    APPROVED = "approved"


class RadarLifecycleStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RESOLVED = "resolved"
    RETRACTED = "retracted"


class RadarRuntimeStatus(str, Enum):
    DISABLED = "disabled"
    IDLE = "idle"
    BUFFERING = "buffering"
    RUNNING = "running"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RadarSegment:
    session_id: str
    segment_id: str
    original_text: str
    normalized_text: str | None = None
    translated_text: str | None = None
    language: str = "unknown"
    target_language: str = "ko"
    started_at: str | None = None
    ended_at: str | None = None
    context_matches: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        session_id = _clean(self.session_id, maximum=128)
        segment_id = _clean(self.segment_id, maximum=128)
        original = _clean(self.original_text)
        if not session_id or not segment_id or not original:
            raise ValueError("radar segment requires session_id, segment_id, and text")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "original_text", original)
        object.__setattr__(self, "normalized_text", _clean(self.normalized_text) or None)
        object.__setattr__(self, "translated_text", _clean(self.translated_text) or None)
        object.__setattr__(self, "language", _clean(self.language, maximum=16).lower() or "unknown")
        target_language = _clean(self.target_language, maximum=16).lower() or "ko"
        if target_language not in {"ko", "en", "ja"}:
            raise ValueError("radar target language must be ko, en, or ja")
        object.__setattr__(self, "target_language", target_language)
        object.__setattr__(
            self,
            "context_matches",
            tuple(dict(item) for item in self.context_matches if isinstance(item, Mapping)),
        )

    def with_translation(self, text: str | None) -> "RadarSegment":
        return replace(self, translated_text=_clean(text) or None)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "translated_text": self.translated_text,
            "language": self.language,
            "target_language": self.target_language,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "context_matches": [dict(item) for item in self.context_matches],
        }


@dataclass(frozen=True, slots=True)
class RadarRequest:
    session_id: str
    segments: tuple[RadarSegment, ...]
    focus_segment_ids: tuple[str, ...] = ()
    context_entries: tuple[dict[str, Any], ...] = ()
    existing_items: tuple[dict[str, Any], ...] = ()
    output_language: str = "ko"

    def __post_init__(self) -> None:
        session_id = _clean(self.session_id, maximum=128)
        segments = tuple(self.segments)
        if not session_id or not segments:
            raise ValueError("radar request requires a session and finalized segments")
        if any(segment.session_id != session_id for segment in segments):
            raise ValueError("radar request segments must belong to one session")
        ids = [segment.segment_id for segment in segments]
        if len(ids) != len(set(ids)):
            raise ValueError("radar request segment IDs must be unique")
        focus_ids = _unique(self.focus_segment_ids) or tuple(ids)
        if any(segment_id not in ids for segment_id in focus_ids):
            raise ValueError("radar focus segment IDs must belong to the request")
        output_language = _clean(self.output_language, maximum=16).lower() or "ko"
        if output_language not in {"ko", "en", "ja"}:
            raise ValueError("radar output language must be ko, en, or ja")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "focus_segment_ids", focus_ids)
        object.__setattr__(self, "output_language", output_language)
        object.__setattr__(
            self,
            "context_entries",
            tuple(dict(item) for item in self.context_entries if isinstance(item, Mapping)),
        )
        object.__setattr__(
            self,
            "existing_items",
            tuple(dict(item) for item in self.existing_items if isinstance(item, Mapping)),
        )

    @property
    def segment_ids(self) -> frozenset[str]:
        return frozenset(segment.segment_id for segment in self.segments)

    @property
    def focus_segment_id_set(self) -> frozenset[str]:
        return frozenset(self.focus_segment_ids)

    @property
    def retractable_item_ids(self) -> frozenset[str]:
        result: set[str] = set()
        for item in self.existing_items:
            item_id = _clean(item.get("item_id"), maximum=128)
            if (
                item_id
                and str(item.get("review_status", "suggested")) == "suggested"
                and not bool(item.get("user_edited", False))
            ):
                result.add(item_id)
        return frozenset(result)


@dataclass(frozen=True, slots=True)
class RadarSuggestion:
    category: RadarItemCategory
    text: str
    evidence_segment_ids: tuple[str, ...]
    assignee: str | None = None
    due_date: str | None = None
    confirmation_kind: str | None = None

    def __post_init__(self) -> None:
        category = RadarItemCategory(self.category)
        text = _clean(self.text)
        evidence = _unique(self.evidence_segment_ids)
        if not text or not evidence:
            raise ValueError("radar suggestions require text and evidence")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "evidence_segment_ids", evidence)
        object.__setattr__(self, "assignee", _clean(self.assignee, maximum=240) or None)
        object.__setattr__(self, "due_date", _clean(self.due_date, maximum=240) or None)
        object.__setattr__(
            self,
            "confirmation_kind",
            _clean(self.confirmation_kind, maximum=32).lower() or None,
        )


@dataclass(frozen=True, slots=True)
class RadarBatchResult:
    provider: str
    model: str | None
    suggestions: tuple[RadarSuggestion, ...]
    retracted_item_ids: tuple[str, ...] = ()
    discarded_evidence_references: int = 0
    discarded_suggestions: int = 0
    request_input_characters: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "retracted_item_ids", _unique(self.retracted_item_ids))
        object.__setattr__(
            self,
            "discarded_evidence_references",
            max(0, int(self.discarded_evidence_references)),
        )
        object.__setattr__(
            self,
            "discarded_suggestions",
            max(0, int(self.discarded_suggestions)),
        )
        object.__setattr__(
            self,
            "request_input_characters",
            max(0, int(self.request_input_characters)),
        )


@dataclass(frozen=True, slots=True)
class RadarItem:
    item_id: str
    category: RadarItemCategory
    text: str
    evidence_segment_ids: tuple[str, ...]
    review_status: RadarReviewStatus = RadarReviewStatus.SUGGESTED
    assignee: str | None = None
    due_date: str | None = None
    confirmation_kind: str | None = None
    user_edited: bool = False
    lifecycle_status: RadarLifecycleStatus = RadarLifecycleStatus.ACTIVE
    lifecycle_reason: str | None = None
    lifecycle_updated_at: str | None = None
    created_at: str = field(default_factory=iso_now)
    updated_at: str = field(default_factory=iso_now)

    def __post_init__(self) -> None:
        item_id = _clean(self.item_id, maximum=128)
        text = _clean(self.text)
        evidence = _unique(self.evidence_segment_ids)
        if not item_id or not text or not evidence:
            raise ValueError("radar items require id, text, and evidence")
        object.__setattr__(self, "item_id", item_id)
        object.__setattr__(self, "category", RadarItemCategory(self.category))
        object.__setattr__(self, "review_status", RadarReviewStatus(self.review_status))
        object.__setattr__(self, "lifecycle_status", RadarLifecycleStatus(self.lifecycle_status))
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "evidence_segment_ids", evidence)
        object.__setattr__(self, "assignee", _clean(self.assignee, maximum=240) or None)
        object.__setattr__(self, "due_date", _clean(self.due_date, maximum=240) or None)
        object.__setattr__(
            self,
            "confirmation_kind",
            _clean(self.confirmation_kind, maximum=32).lower() or None,
        )
        object.__setattr__(self, "lifecycle_reason", _clean(self.lifecycle_reason, maximum=500) or None)

    @classmethod
    def from_suggestion(cls, suggestion: RadarSuggestion) -> "RadarItem":
        return cls(
            item_id=f"radar-{uuid4().hex[:16]}",
            category=suggestion.category,
            text=suggestion.text,
            evidence_segment_ids=suggestion.evidence_segment_ids,
            assignee=suggestion.assignee,
            due_date=suggestion.due_date,
            confirmation_kind=suggestion.confirmation_kind,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RadarItem":
        evidence = payload.get("evidence_segment_ids", ())
        if not isinstance(evidence, (list, tuple)):
            raise ValueError("invalid radar evidence")
        return cls(
            item_id=str(payload.get("item_id", "")),
            category=RadarItemCategory(str(payload.get("category", "decision"))),
            text=str(payload.get("text", "")),
            evidence_segment_ids=tuple(evidence),
            review_status=RadarReviewStatus(
                str(payload.get("review_status", "suggested"))
            ),
            assignee=payload.get("assignee"),
            due_date=payload.get("due_date"),
            confirmation_kind=payload.get("confirmation_kind"),
            user_edited=bool(payload.get("user_edited", False)),
            lifecycle_status=RadarLifecycleStatus(
                str(payload.get("lifecycle_status", "active"))
            ),
            lifecycle_reason=payload.get("lifecycle_reason"),
            lifecycle_updated_at=(
                str(payload.get("lifecycle_updated_at"))
                if payload.get("lifecycle_updated_at")
                else None
            ),
            created_at=str(payload.get("created_at", iso_now())),
            updated_at=str(payload.get("updated_at", iso_now())),
        )

    def semantic_key(self) -> tuple[str, str]:
        return self.category.value, self.text.casefold()

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category.value,
            "text": self.text,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "confirmation_kind": self.confirmation_kind,
            "evidence_segment_ids": list(self.evidence_segment_ids),
            "review_status": self.review_status.value,
            "user_edited": self.user_edited,
            "lifecycle_status": self.lifecycle_status.value,
            "lifecycle_reason": self.lifecycle_reason,
            "lifecycle_updated_at": self.lifecycle_updated_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_prompt_dict(self) -> dict[str, Any]:
        """Return only the fields needed to compare and retract live suggestions."""

        return {
            "item_id": self.item_id,
            "category": self.category.value,
            "text": self.text,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "confirmation_kind": self.confirmation_kind,
            "review_status": self.review_status.value,
            "user_edited": self.user_edited,
            "lifecycle_status": self.lifecycle_status.value,
        }


@dataclass(slots=True)
class RadarSessionState:
    session_id: str
    items: list[RadarItem] = field(default_factory=list)
    revision: int = 0
    updated_at: str | None = None
    tombstones: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RadarSessionState":
        raw_items = payload.get("items", [])
        items = (
            [RadarItem.from_dict(item) for item in raw_items if isinstance(item, Mapping)]
            if isinstance(raw_items, list)
            else []
        )
        raw_tombstones = payload.get("tombstones", [])
        tombstones: set[tuple[str, str]] = set()
        if isinstance(raw_tombstones, list):
            for value in raw_tombstones:
                if isinstance(value, list) and len(value) == 2:
                    tombstones.add((str(value[0]), str(value[1])))
        return cls(
            session_id=_clean(payload.get("session_id"), maximum=128),
            items=items,
            revision=max(0, int(payload.get("revision", 0) or 0)),
            updated_at=str(payload.get("updated_at")) if payload.get("updated_at") else None,
            tombstones=tombstones,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "items": [item.to_dict() for item in self.items],
            "revision": self.revision,
            "updated_at": self.updated_at,
            "tombstones": [list(value) for value in sorted(self.tombstones)],
        }


__all__ = [
    "RADAR_SCHEMA_VERSION",
    "RadarBatchResult",
    "RadarItem",
    "RadarItemCategory",
    "RadarLifecycleStatus",
    "RadarRequest",
    "RadarReviewStatus",
    "RadarRuntimeStatus",
    "RadarSegment",
    "RadarSessionState",
    "RadarSuggestion",
    "iso_now",
]
