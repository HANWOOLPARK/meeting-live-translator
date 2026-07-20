"""Phase 2 asynchronous Korean translation core."""

from .base import TranslationProvider
from .ab_compare import compare_same_source
from .exceptions import (
    SAFE_ERROR_MESSAGES,
    TranslationErrorCode,
    TranslationProviderError,
    normalize_provider_error,
    translation_error,
)
from .glossary import (
    DEFAULT_GLOSSARY_TERMS,
    TranslationGlossary,
    load_glossary_file,
    merge_glossary_terms,
    protect_glossary_terms,
    restore_glossary_terms,
    select_relevant_glossary_terms,
)
from .gemini_provider import GeminiTranslationProvider, normalize_gemini_error
from .local_provider import LocalTranslationProvider
from .manager import TranslationManager
from .models import (
    ProviderHealth,
    TranslationRecord,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    TranslationSubmission,
    iso_now,
)
from .none_provider import NoneTranslationProvider
from .nvidia_riva_provider import (
    DEFAULT_NVIDIA_RIVA_MODEL,
    NvidiaRivaTranslationProvider,
)
from .openai_provider import (
    OpenAITranslationProvider,
    build_translation_input,
    build_translation_instructions,
)
from .queue import TranslationQueue
from .worker_provider import (
    LocalTranslationWorkerSupervisor,
    SidecarLocalTranslationProvider,
)

__all__ = [
    "DEFAULT_NVIDIA_RIVA_MODEL",
    "DEFAULT_GLOSSARY_TERMS",
    "GeminiTranslationProvider",
    "LocalTranslationProvider",
    "LocalTranslationWorkerSupervisor",
    "NoneTranslationProvider",
    "NvidiaRivaTranslationProvider",
    "OpenAITranslationProvider",
    "ProviderHealth",
    "SAFE_ERROR_MESSAGES",
    "TranslationErrorCode",
    "TranslationGlossary",
    "TranslationManager",
    "TranslationProvider",
    "compare_same_source",
    "TranslationProviderError",
    "TranslationQueue",
    "TranslationRecord",
    "TranslationRequest",
    "TranslationResult",
    "TranslationStatus",
    "TranslationSubmission",
    "SidecarLocalTranslationProvider",
    "build_translation_input",
    "build_translation_instructions",
    "load_glossary_file",
    "iso_now",
    "merge_glossary_terms",
    "normalize_provider_error",
    "normalize_gemini_error",
    "protect_glossary_terms",
    "restore_glossary_terms",
    "select_relevant_glossary_terms",
    "translation_error",
]
