"""Phase 3B explicit meeting analysis core."""

from .base import AnalysisProvider
from .chunking import AnalysisChunk, chunk_request, chunk_segments, merge_analyses
from .exceptions import (
    AnalysisErrorCode,
    AnalysisProviderError,
    SAFE_ANALYSIS_MESSAGES,
    analysis_error,
    normalize_analysis_error,
)
from .gemini_provider import GeminiAnalysisProvider, normalize_gemini_analysis_error
from .manager import AnalysisManager
from .models import (
    ANALYSIS_SCHEMA_VERSION,
    ActionItem,
    AnalysisProviderHealth,
    AnalysisRecord,
    AnalysisRequest,
    AnalysisSegment,
    AnalysisStatus,
    AnalysisSubmission,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
)
from .none_provider import NoneAnalysisProvider
from .openai_provider import OpenAIAnalysisProvider
from .prompts import (
    ANALYSIS_RESPONSE_JSON_SCHEMA,
    build_analysis_input,
    build_analysis_instructions,
)
from .rule_based_provider import RuleBasedAnalysisProvider
from .structured import AnalysisResponsePayload
from .validation import evidence_ids, validate_evidence

__all__ = [
    "ANALYSIS_RESPONSE_JSON_SCHEMA",
    "ANALYSIS_SCHEMA_VERSION",
    "ActionItem",
    "AnalysisChunk",
    "AnalysisErrorCode",
    "AnalysisManager",
    "AnalysisProvider",
    "AnalysisProviderError",
    "AnalysisProviderHealth",
    "AnalysisRecord",
    "AnalysisRequest",
    "AnalysisResponsePayload",
    "AnalysisSegment",
    "AnalysisStatus",
    "AnalysisSubmission",
    "EvidenceItem",
    "GeminiAnalysisProvider",
    "MeetingAnalysis",
    "NoneAnalysisProvider",
    "OpenAIAnalysisProvider",
    "RuleBasedAnalysisProvider",
    "SAFE_ANALYSIS_MESSAGES",
    "UNDECIDED",
    "analysis_error",
    "build_analysis_input",
    "build_analysis_instructions",
    "chunk_request",
    "chunk_segments",
    "evidence_ids",
    "merge_analyses",
    "normalize_analysis_error",
    "normalize_gemini_analysis_error",
    "validate_evidence",
]
