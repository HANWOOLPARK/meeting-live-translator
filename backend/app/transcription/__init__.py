"""Near-real-time transcription building blocks.

The package deliberately has no eager dependency on :mod:`faster_whisper`.  It
is therefore safe to import the web application, enumerate audio devices, and
run unit tests on machines on which the model runtime has not been installed.
"""

from .buffer import UtteranceSegmenter
from .audio_ring import Pcm16RingBuffer, Pcm16Slice
from .deduplicator import TranscriptDeduplicator
from .deepgram_stream import (
    DeepgramStreamError,
    DeepgramStreamingClient,
    DeepgramTranscript,
    DeepgramWord,
    has_explicit_korean_date,
    has_malformed_korean_date_format,
)
from .engine import (
    FasterWhisperEngine,
    TranscriptionEngine,
    TranscriptionInferenceError,
    TranscriptionLoadError,
)
from .language import classify_language
from .models import SegmentEvent, SegmentEventType, TranscriptionResult
from .vad import EnergyVoiceActivityDetector

__all__ = [
    "EnergyVoiceActivityDetector",
    "FasterWhisperEngine",
    "DeepgramStreamError",
    "DeepgramStreamingClient",
    "DeepgramTranscript",
    "DeepgramWord",
    "has_explicit_korean_date",
    "has_malformed_korean_date_format",
    "Pcm16RingBuffer",
    "Pcm16Slice",
    "SegmentEvent",
    "SegmentEventType",
    "TranscriptDeduplicator",
    "TranscriptionEngine",
    "TranscriptionInferenceError",
    "TranscriptionLoadError",
    "TranscriptionResult",
    "UtteranceSegmenter",
    "classify_language",
]
