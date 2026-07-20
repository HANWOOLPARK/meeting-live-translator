"""Validated dataclass models used throughout the translation package."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any

from .exceptions import SAFE_ERROR_MESSAGES, TranslationErrorCode


SUPPORTED_SOURCE_LANGUAGES = frozenset({"ja", "en", "ko", "mixed", "unknown"})
SUPPORTED_TARGET_LANGUAGES = frozenset({"ko", "ja", "en"})


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class TranslationStatus(str, Enum):
    DISABLED = "disabled"
    PENDING = "pending"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    segment_id: str
    source_text: str
    source_language: str
    session_id: str | None = None
    target_language: str = "ko"
    source: str = "system"
    started_at: str | None = None
    ended_at: str | None = None
    boundary_reason: str | None = None
    source_is_incomplete: bool = False
    previous_context: tuple[str, ...] = ()
    glossary_terms: tuple[str, ...] = ()
    requested_at: str = field(default_factory=iso_now)

    def __post_init__(self) -> None:
        segment_id = str(self.segment_id).strip()
        source_text = str(self.source_text).strip()
        language = str(self.source_language).strip().lower()
        target = str(self.target_language).strip().lower()
        source = str(self.source).strip().lower()
        session_id = str(self.session_id).strip() if self.session_id is not None else None
        boundary_reason = (
            str(self.boundary_reason).strip().lower()
            if self.boundary_reason is not None
            else None
        )
        if not segment_id:
            raise ValueError("segment_id must not be empty")
        if not source_text:
            raise ValueError("source_text must not be empty")
        if language not in SUPPORTED_SOURCE_LANGUAGES:
            raise ValueError("source_language must be ja, en, ko, mixed, or unknown")
        if target not in SUPPORTED_TARGET_LANGUAGES:
            raise ValueError("target_language must be ko, ja, or en")
        if not source:
            raise ValueError("source must not be empty")
        context = tuple(str(item).strip() for item in self.previous_context if str(item).strip())
        glossary = tuple(str(item).strip() for item in self.glossary_terms if str(item).strip())
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "source_text", source_text)
        object.__setattr__(self, "source_language", language)
        object.__setattr__(self, "target_language", target)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "session_id", session_id or None)
        object.__setattr__(self, "boundary_reason", boundary_reason or None)
        object.__setattr__(self, "source_is_incomplete", bool(self.source_is_incomplete))
        object.__setattr__(self, "previous_context", context)
        object.__setattr__(self, "glossary_terms", glossary)

    def with_context_and_glossary(
        self,
        previous_context: tuple[str, ...],
        glossary_terms: tuple[str, ...],
    ) -> "TranslationRequest":
        return replace(
            self,
            previous_context=previous_context,
            glossary_terms=glossary_terms,
        )

    def renewed(self) -> "TranslationRequest":
        return replace(self, requested_at=iso_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "session_id": self.session_id,
            "source_text": self.source_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "source": self.source,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "boundary_reason": self.boundary_reason,
            "source_is_incomplete": self.source_is_incomplete,
            "previous_context": list(self.previous_context),
            "glossary_terms": list(self.glossary_terms),
            "requested_at": self.requested_at,
        }

    model_dump = to_dict


@dataclass(frozen=True, slots=True)
class TranslationResult:
    segment_id: str
    source_text: str
    translated_text: str | None
    source_language: str
    target_language: str
    provider: str
    model: str | None
    status: TranslationStatus
    requested_at: str
    completed_at: str
    latency_ms: int
    session_id: str | None = None
    error_code: TranslationErrorCode | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        segment_id = str(self.segment_id).strip()
        source_text = str(self.source_text).strip()
        source_language = str(self.source_language).strip().lower()
        target_language = str(self.target_language).strip().lower()
        provider = str(self.provider).strip().lower()
        session_id = str(self.session_id).strip() if self.session_id is not None else None
        status = TranslationStatus(self.status)
        error_code = TranslationErrorCode(self.error_code) if self.error_code else None
        translated_text = (
            str(self.translated_text).strip() if self.translated_text is not None else None
        )
        if not segment_id:
            raise ValueError("segment_id must not be empty")
        if not source_text:
            raise ValueError("source_text must not be empty")
        if source_language not in SUPPORTED_SOURCE_LANGUAGES:
            raise ValueError("invalid source_language")
        if target_language not in SUPPORTED_TARGET_LANGUAGES:
            raise ValueError("target_language must be ko, ja, or en")
        if not provider:
            raise ValueError("provider must not be empty")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        if status is TranslationStatus.COMPLETED and not translated_text:
            raise ValueError("completed translation requires translated_text")
        if status in {TranslationStatus.FAILED, TranslationStatus.CANCELLED}:
            if error_code is None:
                raise ValueError("failed/cancelled translation requires a safe error")
            object.__setattr__(self, "error_message", SAFE_ERROR_MESSAGES[error_code])
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "session_id", session_id or None)
        object.__setattr__(self, "source_text", source_text)
        object.__setattr__(self, "translated_text", translated_text)
        object.__setattr__(self, "source_language", source_language)
        object.__setattr__(self, "target_language", target_language)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "error_code", error_code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "session_id": self.session_id,
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code.value if self.error_code else None,
            "error_message": self.error_message,
        }

    model_dump = to_dict


@dataclass(frozen=True, slots=True)
class ProviderHealth:
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
class TranslationSubmission:
    accepted: bool
    segment_id: str | None
    reason: str
    queue_size: int

    def __bool__(self) -> bool:
        return self.accepted


@dataclass(slots=True)
class TranslationRecord:
    request: TranslationRequest
    provider: str
    status: TranslationStatus
    attempts: int = 0
    submission_number: int = 1
    result: TranslationResult | None = None
    last_error: TranslationResult | None = None


__all__ = [
    "ProviderHealth",
    "SUPPORTED_SOURCE_LANGUAGES",
    "SUPPORTED_TARGET_LANGUAGES",
    "TranslationRecord",
    "TranslationRequest",
    "TranslationResult",
    "TranslationStatus",
    "TranslationSubmission",
    "iso_now",
]
