"""Structured, serializable Phase 3B meeting analysis models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping


ANALYSIS_SCHEMA_VERSION = 1
UNDECIDED = "미정"


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _unique_strings(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


class AnalysisStatus(str, Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    segment_id: str
    original_text: str | None
    korean_translation: str | None = None
    language: str = "unknown"
    source: str = "system"
    started_at: str | None = None
    ended_at: str | None = None
    normalized_text: str | None = None

    def __post_init__(self) -> None:
        segment_id = str(self.segment_id).strip()
        original = str(self.original_text).strip() if self.original_text is not None else None
        korean = (
            str(self.korean_translation).strip()
            if self.korean_translation is not None
            else None
        )
        normalized = (
            str(self.normalized_text).strip()
            if self.normalized_text is not None
            else None
        )
        if not segment_id:
            raise ValueError("segment_id must not be empty")
        if not original and not normalized and not korean:
            raise ValueError("analysis segment requires original or translated text")
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "original_text", original or None)
        object.__setattr__(self, "korean_translation", korean or None)
        object.__setattr__(self, "normalized_text", normalized or None)
        object.__setattr__(self, "language", str(self.language).strip().lower() or "unknown")
        object.__setattr__(self, "source", str(self.source).strip().lower() or "system")

    @property
    def preferred_text(self) -> str:
        return self.normalized_text or self.original_text or self.korean_translation or ""

    @property
    def prompt_characters(self) -> int:
        return (
            len(self.original_text or "")
            + len(self.normalized_text or "")
            + len(self.korean_translation or "")
        )

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "korean_translation": self.korean_translation,
            "language": self.language,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    session_id: str
    segments: tuple[AnalysisSegment, ...]
    requested_at: str = field(default_factory=iso_now)

    def __post_init__(self) -> None:
        session_id = str(self.session_id).strip()
        segments = tuple(self.segments)
        if not session_id:
            raise ValueError("session_id must not be empty")
        ids = [segment.segment_id for segment in segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment_id values must be unique")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "segments", segments)

    @property
    def segment_ids(self) -> frozenset[str]:
        return frozenset(segment.segment_id for segment in self.segments)

    def with_segments(self, segments: Iterable[AnalysisSegment]) -> "AnalysisRequest":
        return replace(self, segments=tuple(segments))


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    text: str
    evidence_segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text = str(self.text).strip()
        if not text:
            raise ValueError("analysis item text must not be empty")
        object.__setattr__(self, "text", text)
        object.__setattr__(
            self,
            "evidence_segment_ids",
            _unique_strings(self.evidence_segment_ids),
        )

    @classmethod
    def from_value(cls, value: Any, *, default_text: str | None = None) -> "EvidenceItem":
        if isinstance(value, EvidenceItem):
            return value
        if isinstance(value, Mapping):
            extras = set(value).difference({"text", "evidence_segment_ids"})
            if extras:
                raise ValueError("evidence item contains unsupported fields")
            text = str(value.get("text", default_text or "")).strip()
            evidence = value.get("evidence_segment_ids", ())
            if not isinstance(evidence, (list, tuple)):
                raise ValueError("evidence_segment_ids must be an array")
            return cls(text or default_text or UNDECIDED, tuple(evidence))
        text = str(value or default_text or UNDECIDED).strip()
        return cls(text or UNDECIDED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence_segment_ids": list(self.evidence_segment_ids),
        }


@dataclass(frozen=True, slots=True)
class ActionItem:
    task: str
    assignee: str = UNDECIDED
    due_date: str = UNDECIDED
    evidence_segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        task = str(self.task).strip()
        if not task:
            raise ValueError("action item task must not be empty")
        assignee = str(self.assignee).strip() or UNDECIDED
        due_date = str(self.due_date).strip() or UNDECIDED
        ambiguous_assignees = {
            "we",
            "they",
            "team",
            "our team",
            "the team",
            "우리",
            "우리 팀",
            "저희",
            "저희 팀",
            "담당팀",
            "チーム",
            "私たち",
            "我々",
            "担当チーム",
        }
        if assignee.casefold() in {value.casefold() for value in ambiguous_assignees}:
            assignee = UNDECIDED
        ambiguous_dates = {
            "asap",
            "soon",
            "later",
            "sometime",
            "as soon as possible",
            "빠른 시일 내",
            "빠른시일내",
            "가능한 한 빨리",
            "가능한 빨리",
            "나중에",
            "추후",
            "조속히",
            "後で",
            "後ほど",
            "早めに",
            "早急に",
            "できるだけ早く",
            "なるべく早く",
        }
        normalized_due = due_date.casefold().strip(" .")
        if normalized_due.startswith("by "):
            normalized_due = normalized_due[3:].strip()
        if normalized_due in {value.casefold() for value in ambiguous_dates}:
            due_date = UNDECIDED
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "assignee", assignee)
        object.__setattr__(self, "due_date", due_date)
        object.__setattr__(
            self,
            "evidence_segment_ids",
            _unique_strings(self.evidence_segment_ids),
        )

    @classmethod
    def from_value(cls, value: Any) -> "ActionItem":
        if isinstance(value, ActionItem):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("action item must be an object")
        extras = set(value).difference(
            {"task", "assignee", "due_date", "evidence_segment_ids"}
        )
        if extras:
            raise ValueError("action item contains unsupported fields")
        evidence = value.get("evidence_segment_ids", ())
        if not isinstance(evidence, (list, tuple)):
            raise ValueError("evidence_segment_ids must be an array")
        return cls(
            task=str(value.get("task", "")),
            assignee=str(value.get("assignee", UNDECIDED)),
            due_date=str(value.get("due_date", UNDECIDED)),
            evidence_segment_ids=tuple(evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "evidence_segment_ids": list(self.evidence_segment_ids),
        }


def _evidence_items(value: Any) -> tuple[EvidenceItem, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("analysis collection must be an array")
    return tuple(EvidenceItem.from_value(item) for item in value)


@dataclass(frozen=True, slots=True)
class MeetingAnalysis:
    session_id: str
    provider: str
    model: str | None
    status: AnalysisStatus
    meeting_purpose: EvidenceItem
    key_discussions: tuple[EvidenceItem, ...] = ()
    decisions: tuple[EvidenceItem, ...] = ()
    action_items: tuple[ActionItem, ...] = ()
    open_questions: tuple[EvidenceItem, ...] = ()
    next_meeting_checks: tuple[EvidenceItem, ...] = ()
    warnings: tuple[str, ...] = ()
    generated_at: str = field(default_factory=iso_now)
    schema_version: int = ANALYSIS_SCHEMA_VERSION
    revision: int = 1

    def __post_init__(self) -> None:
        if not str(self.session_id).strip():
            raise ValueError("session_id must not be empty")
        if not str(self.provider).strip():
            raise ValueError("provider must not be empty")
        if self.schema_version != ANALYSIS_SCHEMA_VERSION:
            raise ValueError("unsupported analysis schema_version")
        if self.revision <= 0:
            raise ValueError("revision must be positive")
        object.__setattr__(self, "session_id", str(self.session_id).strip())
        object.__setattr__(self, "provider", str(self.provider).strip().lower())
        object.__setattr__(self, "status", AnalysisStatus(self.status))
        object.__setattr__(self, "meeting_purpose", EvidenceItem.from_value(self.meeting_purpose))
        object.__setattr__(self, "key_discussions", tuple(self.key_discussions))
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "action_items", tuple(self.action_items))
        object.__setattr__(self, "open_questions", tuple(self.open_questions))
        object.__setattr__(self, "next_meeting_checks", tuple(self.next_meeting_checks))
        object.__setattr__(self, "warnings", _unique_strings(self.warnings))

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        session_id: str,
        provider: str,
        model: str | None,
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        generated_at: str | None = None,
        revision: int = 1,
    ) -> "MeetingAnalysis":
        allowed = {
            "meeting_purpose",
            "key_discussions",
            "decisions",
            "action_items",
            "open_questions",
            "next_meeting_checks",
            "warnings",
        }
        payload_keys = set(payload)
        if payload_keys.difference(allowed):
            raise ValueError("analysis payload contains unsupported fields")
        if allowed.difference(payload_keys):
            raise ValueError("analysis payload is missing required fields")
        action_value = payload.get("action_items", ())
        if not isinstance(action_value, (list, tuple)):
            raise ValueError("action_items must be an array")
        warning_value = payload.get("warnings", ())
        if not isinstance(warning_value, (list, tuple)):
            raise ValueError("warnings must be an array")
        return cls(
            session_id=session_id,
            provider=provider,
            model=model,
            status=status,
            meeting_purpose=EvidenceItem.from_value(
                payload.get("meeting_purpose"),
                default_text=UNDECIDED,
            ),
            key_discussions=_evidence_items(payload.get("key_discussions")),
            decisions=_evidence_items(payload.get("decisions")),
            action_items=tuple(ActionItem.from_value(item) for item in action_value),
            open_questions=_evidence_items(payload.get("open_questions")),
            next_meeting_checks=_evidence_items(payload.get("next_meeting_checks")),
            warnings=tuple(str(item) for item in warning_value),
            generated_at=generated_at or iso_now(),
            revision=revision,
        )

    def with_revision(self, revision: int) -> "MeetingAnalysis":
        return replace(self, revision=revision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "generated_at": self.generated_at,
            "revision": self.revision,
            "meeting_purpose": self.meeting_purpose.to_dict(),
            "key_discussions": [item.to_dict() for item in self.key_discussions],
            "decisions": [item.to_dict() for item in self.decisions],
            "action_items": [item.to_dict() for item in self.action_items],
            "open_questions": [item.to_dict() for item in self.open_questions],
            "next_meeting_checks": [item.to_dict() for item in self.next_meeting_checks],
            "warnings": list(self.warnings),
        }

    model_dump = to_dict


@dataclass(frozen=True, slots=True)
class AnalysisProviderHealth:
    provider_id: str
    name: str
    available: bool
    external: bool
    reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "name": self.name,
            "available": self.available,
            "external": self.external,
            "reason": self.reason,
            "model": self.model,
        }


@dataclass(frozen=True, slots=True)
class AnalysisSubmission:
    accepted: bool
    session_id: str
    reason: str
    status: AnalysisStatus

    def __bool__(self) -> bool:
        return self.accepted


@dataclass(slots=True)
class AnalysisRecord:
    request: AnalysisRequest
    provider: str
    model: str | None = None
    status: AnalysisStatus = AnalysisStatus.NOT_STARTED
    revision: int = 0
    result: MeetingAnalysis | None = None
    last_error_code: str | None = None
    attempts: int = 0


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "ActionItem",
    "AnalysisProviderHealth",
    "AnalysisRecord",
    "AnalysisRequest",
    "AnalysisSegment",
    "AnalysisStatus",
    "AnalysisSubmission",
    "EvidenceItem",
    "MeetingAnalysis",
    "UNDECIDED",
    "iso_now",
]
