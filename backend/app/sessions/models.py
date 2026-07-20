from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


SCHEMA_VERSION = 1


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    RECOVERED = "recovered"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    save_original: bool = True
    save_translation: bool = True
    save_analysis: bool = True
    save_audio: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FinalTranscript:
    segment_id: str
    session_id: str
    utterance_id: str
    source: str
    text: str
    language: str
    language_probability: float
    started_at: str
    ended_at: str
    inference_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionManifest:
    session_id: str
    status: str = SessionStatus.CREATED.value
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=iso_now)
    started_at: str | None = None
    ended_at: str | None = None
    finalized_at: str | None = None
    source: str | None = None
    audio_device_name: str | None = None
    whisper_model: str | None = None
    translation_provider: str = "none"
    translation_direction: str = "ja_to_ko"
    analysis_provider: str = "none"
    save_original: bool = True
    save_translation: bool = True
    save_analysis: bool = True
    save_audio: bool = False
    segment_count: int = 0
    translated_segment_count: int = 0
    analysis_status: str = "not_started"
    analysis_generated_at: str | None = None
    analysis_revision: int = 0
    warnings: list[str] = field(default_factory=list)
    recovered_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionManifest":
        allowed = cls.__dataclass_fields__
        values = {key: payload[key] for key in allowed if key in payload}
        values["session_id"] = str(payload.get("session_id", ""))
        values["warnings"] = [
            str(value) for value in payload.get("warnings", []) if str(value).strip()
        ]
        return cls(**values)


__all__ = [
    "FinalTranscript",
    "SCHEMA_VERSION",
    "SessionManifest",
    "SessionStatus",
    "StoragePolicy",
    "iso_now",
]
