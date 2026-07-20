"""Value objects shared by the transcription pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """One model inference result.

    Offsets are relative to the audio array passed to ``transcribe``.  Session
    wall-clock timestamps are intentionally owned by the orchestration layer.
    """

    text: str
    detected_language: str
    language_probability: float
    started_offset: float
    ended_offset: float
    inference_seconds: float


class SegmentEventType(str, Enum):
    """Events emitted by :class:`UtteranceSegmenter`."""

    PARTIAL = "partial"
    FINAL = "final"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class SegmentEvent:
    """A copied audio snapshot ready for downstream processing.

    ``partial`` snapshots are replaceable UI work and must not be persisted.
    ``final`` snapshots represent utterances that passed the configured minimum
    voiced duration.  ``reset`` carries an empty array and tells an orchestrator
    to discard any pending partial result.
    """

    event_type: SegmentEventType
    samples: NDArray[np.float32]
    started_offset: float
    ended_offset: float
    reason: str

    @property
    def type(self) -> str:
        """JSON-friendly alias used by simple integrations."""

        return self.event_type.value

    @property
    def kind(self) -> str:
        """Backward-friendly alias for consumers that call events ``kind``."""

        return self.event_type.value

    @property
    def is_partial(self) -> bool:
        return self.event_type is SegmentEventType.PARTIAL

    @property
    def is_final(self) -> bool:
        return self.event_type is SegmentEventType.FINAL
