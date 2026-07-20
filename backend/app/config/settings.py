from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


ALLOWED_MODELS = ("tiny", "base", "small", "medium")
ALLOWED_STT_PROVIDERS = ("local", "deepgram")
ALLOWED_TRANSLATION_DIRECTIONS = (
    "ja_to_ko",
    "ja_to_en",
    "en_to_ko",
    "en_to_ja",
    "ko_to_ja",
    "ko_to_en",
)
KOREAN_SOURCE_TRANSLATION_DIRECTIONS = ("ko_to_ja", "ko_to_en")
EXTERNAL_ONLY_TRANSLATION_DIRECTIONS = (
    "ja_to_en",
    "en_to_ja",
    *KOREAN_SOURCE_TRANSLATION_DIRECTIONS,
)
ALLOWED_TRANSLATION_PROVIDERS = ("none", "local", "openai", "gemini")
ALLOWED_ANALYSIS_PROVIDERS = ("none", "rule_based", "openai", "gemini")
ALLOWED_DECISION_RADAR_PROVIDERS = ("none", "openai", "gemini")
DEFAULT_OPENAI_TRANSLATION_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_DECISION_RADAR_MODEL = "gpt-5.4-mini"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_path(name: str, root: Path) -> Path | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


@dataclass(frozen=True, slots=True)
class AppSettings:
    project_root: Path
    host: str = "127.0.0.1"
    port: int = 8765
    default_model: str = "small"
    selected_model: str = "small"
    sample_rate: int = 16_000
    prefer_cuda: bool = True
    frame_queue_size: int = 256
    stt_provider: str = "local"
    translation_direction: str = "ja_to_ko"
    deepgram_api_key: str | None = field(default=None, repr=False)
    deepgram_stt_model: str = "nova-3"
    deepgram_stt_language: str = "ja"
    deepgram_endpointing_ms: int = 500
    deepgram_utterance_end_ms: int = 1_300
    deepgram_max_segment_seconds: float = 8.0
    deepgram_en_endpointing_ms: int = 400
    deepgram_en_utterance_end_ms: int = 1_000
    deepgram_en_max_segment_seconds: float = 6.0
    deepgram_ko_endpointing_ms: int = 650
    deepgram_ko_utterance_end_ms: int = 1_500
    deepgram_ko_max_segment_seconds: float = 8.0
    deepgram_checkpoint_seconds: float = 4.0
    deepgram_hard_limit_seconds: float = 10.0
    deepgram_open_timeout_seconds: float = 10.0
    deepgram_incomplete_final_wait_seconds: float = 0.9
    deepgram_en_incomplete_final_wait_seconds: float = 0.7
    deepgram_ko_incomplete_final_wait_seconds: float = 1.5
    deepgram_reconnect_max_attempts: int = 5
    deepgram_reconnect_base_delay_seconds: float = 0.5
    deepgram_reconnect_max_delay_seconds: float = 5.0
    deepgram_reconnect_buffer_seconds: float = 3.0
    deepgram_recheck_enabled: bool = True
    deepgram_recheck_model: str | None = None
    deepgram_recheck_buffer_seconds: float = 14.0
    deepgram_recheck_timeout_seconds: float = 4.0
    deepgram_recheck_queue_max_size: int = 2
    deepgram_recheck_local_files_only: bool = True
    session_dir: Path | None = None
    static_dir: Path | None = None
    translation_provider: str = "none"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_translation_model: str = DEFAULT_OPENAI_TRANSLATION_MODEL
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_translation_model: str | None = None
    gemini_translation_timeout_seconds: float = 20.0
    gemini_translation_max_retries: int = 2
    gemini_translation_context_segments: int = 3
    translation_timeout_seconds: float = 20.0
    translation_max_retries: int = 2
    translation_context_segments: int = 3
    translation_queue_max_size: int = 100
    translation_max_concurrency: int = 2
    translation_translate_unknown: bool = False
    translation_glossary_file: Path | None = None
    local_translation_runtime_python: Path | None = None
    local_translation_model: str | None = None
    local_translation_ja_model: str | None = None
    local_translation_en_model: str | None = None
    session_save_original: bool = True
    session_save_translation: bool = True
    session_save_analysis: bool = True
    session_auto_recover: bool = True
    analysis_provider: str = "none"
    openai_analysis_model: str | None = None
    gemini_analysis_model: str | None = None
    analysis_timeout_seconds: float = 60.0
    analysis_max_retries: int = 1
    analysis_auto_run_on_stop: bool = False
    analysis_max_segments_per_chunk: int = 100
    analysis_max_chars_per_chunk: int = 24_000
    analysis_max_concurrency: int = 1
    decision_radar_provider: str = "none"
    openai_decision_radar_model: str = DEFAULT_OPENAI_DECISION_RADAR_MODEL
    gemini_decision_radar_model: str | None = None
    decision_radar_batch_size: int = 10
    decision_radar_batch_wait_seconds: float = 20.0
    decision_radar_context_segments: int = 16
    decision_radar_queue_max_size: int = 100
    decision_radar_timeout_seconds: float = 30.0
    decision_radar_max_retries: int = 1
    share_relay_url: str | None = None
    share_relay_secret: str | None = field(default=None, repr=False)
    share_relay_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.selected_model not in ALLOWED_MODELS:
            raise ValueError(f"Unsupported Whisper model: {self.selected_model}")
        if self.default_model not in ALLOWED_MODELS:
            raise ValueError(f"Unsupported default Whisper model: {self.default_model}")
        if self.stt_provider not in ALLOWED_STT_PROVIDERS:
            raise ValueError(f"Unsupported STT provider: {self.stt_provider}")
        if self.translation_direction not in ALLOWED_TRANSLATION_DIRECTIONS:
            raise ValueError(
                f"Unsupported translation direction: {self.translation_direction}"
            )
        if (
            self.translation_direction in KOREAN_SOURCE_TRANSLATION_DIRECTIONS
            and self.stt_provider != "deepgram"
        ):
            raise ValueError("Korean-source translation requires Deepgram STT")
        if not self.deepgram_stt_model.strip():
            raise ValueError("Deepgram STT model cannot be empty")
        if self.deepgram_stt_language not in {"ja", "en", "ko"}:
            raise ValueError("Deepgram STT language must be ja, en, or ko")
        if not (0 <= self.deepgram_endpointing_ms <= 10_000):
            raise ValueError("Deepgram endpointing must be between 0 and 10000 ms")
        if not (1_000 <= self.deepgram_utterance_end_ms <= 10_000):
            raise ValueError("Deepgram utterance end must be between 1000 and 10000 ms")
        if not (1.0 <= self.deepgram_max_segment_seconds <= 30.0):
            raise ValueError("Deepgram max segment must be between 1 and 30 seconds")
        for language, endpointing, utterance_end, max_segment in (
            ("en", self.deepgram_en_endpointing_ms, self.deepgram_en_utterance_end_ms, self.deepgram_en_max_segment_seconds),
            ("ko", self.deepgram_ko_endpointing_ms, self.deepgram_ko_utterance_end_ms, self.deepgram_ko_max_segment_seconds),
        ):
            if not (0 <= endpointing <= 10_000):
                raise ValueError(f"Deepgram {language} endpointing must be between 0 and 10000 ms")
            if not (1_000 <= utterance_end <= 10_000):
                raise ValueError(f"Deepgram {language} utterance end must be between 1000 and 10000 ms")
            if not (1.0 <= max_segment <= 30.0):
                raise ValueError(f"Deepgram {language} max segment must be between 1 and 30 seconds")
        if not (1.0 <= self.deepgram_checkpoint_seconds <= 10.0):
            raise ValueError("Deepgram checkpoint must be between 1 and 10 seconds")
        if not (self.deepgram_checkpoint_seconds <= self.deepgram_hard_limit_seconds <= 30.0):
            raise ValueError("Deepgram hard limit must be between checkpoint and 30 seconds")
        if self.deepgram_hard_limit_seconds < max(
            self.deepgram_max_segment_seconds,
            self.deepgram_en_max_segment_seconds,
            self.deepgram_ko_max_segment_seconds,
        ):
            raise ValueError("Deepgram hard limit must cover every language profile")
        if self.deepgram_open_timeout_seconds <= 0:
            raise ValueError("Deepgram open timeout must be positive")
        for language, wait_seconds in (
            ("ja", self.deepgram_incomplete_final_wait_seconds),
            ("en", self.deepgram_en_incomplete_final_wait_seconds),
            ("ko", self.deepgram_ko_incomplete_final_wait_seconds),
        ):
            if not (0.2 <= wait_seconds <= 3.0):
                raise ValueError(
                    f"Deepgram {language} incomplete-final wait must be between 0.2 and 3 seconds"
                )
        if not (1 <= self.deepgram_reconnect_max_attempts <= 20):
            raise ValueError("Deepgram reconnect attempts must be between 1 and 20")
        if self.deepgram_reconnect_base_delay_seconds < 0:
            raise ValueError("Deepgram reconnect base delay must not be negative")
        if self.deepgram_reconnect_max_delay_seconds <= 0:
            raise ValueError("Deepgram reconnect max delay must be positive")
        if (
            self.deepgram_reconnect_max_delay_seconds
            < self.deepgram_reconnect_base_delay_seconds
        ):
            raise ValueError("Deepgram reconnect max delay must be at least the base delay")
        if not (0.5 <= self.deepgram_reconnect_buffer_seconds <= 15.0):
            raise ValueError("Deepgram reconnect buffer must be between 0.5 and 15 seconds")
        if self.deepgram_recheck_model not in {None, *ALLOWED_MODELS}:
            raise ValueError("Unsupported Deepgram recheck Whisper model")
        if not (10.0 <= self.deepgram_recheck_buffer_seconds <= 30.0):
            raise ValueError("Deepgram recheck buffer must be between 10 and 30 seconds")
        if not (0.5 <= self.deepgram_recheck_timeout_seconds <= 15.0):
            raise ValueError("Deepgram recheck timeout must be between 0.5 and 15 seconds")
        if not (1 <= self.deepgram_recheck_queue_max_size <= 10):
            raise ValueError("Deepgram recheck queue size must be between 1 and 10")
        if not (1 <= self.port <= 65_535):
            raise ValueError("Port must be between 1 and 65535")
        if self.translation_provider not in ALLOWED_TRANSLATION_PROVIDERS:
            raise ValueError(
                f"Unsupported translation provider: {self.translation_provider}"
            )
        if not self.openai_translation_model.strip():
            raise ValueError("OpenAI translation model cannot be empty")
        if self.gemini_translation_timeout_seconds <= 0:
            raise ValueError("Gemini translation timeout must be positive")
        if not (0 <= self.gemini_translation_max_retries <= 10):
            raise ValueError("Gemini translation retries must be between 0 and 10")
        if not (0 <= self.gemini_translation_context_segments <= 20):
            raise ValueError("Gemini translation context segments must be between 0 and 20")
        if self.translation_timeout_seconds <= 0:
            raise ValueError("Translation timeout must be positive")
        if not (0 <= self.translation_max_retries <= 10):
            raise ValueError("Translation retries must be between 0 and 10")
        if not (0 <= self.translation_context_segments <= 20):
            raise ValueError("Translation context segments must be between 0 and 20")
        if self.translation_queue_max_size <= 0:
            raise ValueError("Translation queue size must be positive")
        if self.translation_max_concurrency <= 0:
            raise ValueError("Translation concurrency must be positive")
        if self.analysis_provider not in ALLOWED_ANALYSIS_PROVIDERS:
            raise ValueError(f"Unsupported analysis provider: {self.analysis_provider}")
        if self.analysis_timeout_seconds <= 0:
            raise ValueError("Analysis timeout must be positive")
        if not (0 <= self.analysis_max_retries <= 10):
            raise ValueError("Analysis retries must be between 0 and 10")
        if self.analysis_max_segments_per_chunk <= 0:
            raise ValueError("Analysis chunk segment limit must be positive")
        if self.analysis_max_chars_per_chunk <= 0:
            raise ValueError("Analysis chunk character limit must be positive")
        if self.analysis_max_concurrency <= 0:
            raise ValueError("Analysis concurrency must be positive")
        if self.decision_radar_provider not in ALLOWED_DECISION_RADAR_PROVIDERS:
            raise ValueError(
                f"Unsupported Decision Radar provider: {self.decision_radar_provider}"
            )
        if not self.openai_decision_radar_model.strip():
            raise ValueError("OpenAI Decision Radar model cannot be empty")
        if not (1 <= self.decision_radar_batch_size <= 20):
            raise ValueError("Decision Radar batch size must be between 1 and 20")
        if not (1.0 <= self.decision_radar_batch_wait_seconds <= 60.0):
            raise ValueError("Decision Radar batch wait must be between 1 and 60 seconds")
        if not (
            self.decision_radar_batch_size
            <= self.decision_radar_context_segments
            <= 200
        ):
            raise ValueError(
                "Decision Radar context segments must cover a batch and be at most 200"
            )
        if self.decision_radar_queue_max_size <= 0:
            raise ValueError("Decision Radar queue size must be positive")
        if self.decision_radar_timeout_seconds <= 0:
            raise ValueError("Decision Radar timeout must be positive")
        if not (0 <= self.decision_radar_max_retries <= 3):
            raise ValueError("Decision Radar retries must be between 0 and 3")
        if self.share_relay_timeout_seconds <= 0:
            raise ValueError("Share relay timeout must be positive")

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "AppSettings":
        root = (project_root or Path(__file__).resolve().parents[3]).resolve()
        try:
            from dotenv import load_dotenv

            # A dedicated, ignored sharing file keeps the relay credential out
            # of the user's normal provider configuration. Explicit process
            # environment values still win because neither load overrides them.
            load_dotenv(root / ".share.env", override=False)
            load_dotenv(root / ".env", override=False)
        except ImportError:
            # setup.bat installs python-dotenv; keeping this optional makes
            # configuration importable for lightweight tooling.
            pass
        model = os.getenv("MLT_WHISPER_MODEL", "small").strip().lower()
        translation_provider = os.getenv(
            "TRANSLATION_PROVIDER", "none"
        ).strip().lower()
        openai_model = (
            os.getenv("OPENAI_TRANSLATION_MODEL", "").strip()
            or DEFAULT_OPENAI_TRANSLATION_MODEL
        )
        gemini_model = os.getenv("GEMINI_TRANSLATION_MODEL", "").strip() or None
        gemini_analysis_model = (
            os.getenv("GEMINI_ANALYSIS_MODEL", "").strip() or gemini_model
        )
        gemini_decision_radar_model = (
            os.getenv("GEMINI_DECISION_RADAR_MODEL", "").strip()
            or gemini_analysis_model
            or gemini_model
        )
        timeout_value = os.getenv(
            "TRANSLATION_TIMEOUT_SECONDS",
            os.getenv("OPENAI_TRANSLATION_TIMEOUT_SECONDS", "20"),
        )
        retries_value = os.getenv(
            "TRANSLATION_MAX_RETRIES",
            os.getenv("OPENAI_TRANSLATION_MAX_RETRIES", "2"),
        )
        local_runtime = _env_path("LOCAL_TRANSLATION_RUNTIME_PYTHON", root)
        if local_runtime is None:
            local_runtime = (
                root / ".venv-translation" / "Scripts" / "python.exe"
            ).resolve()
        local_model = (
            os.getenv("LOCAL_TRANSLATION_MODEL", "").strip()
            or "models/translation/m2m100_418m-int8"
        )
        legacy_max_segment_value = os.getenv("DEEPGRAM_STT_MAX_SEGMENT_SECONDS")
        deepgram_max_segment_seconds = float(
            legacy_max_segment_value
            if legacy_max_segment_value is not None
            else "8"
        )
        deepgram_en_max_segment_seconds = float(
            os.getenv(
                "DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS",
                legacy_max_segment_value
                if legacy_max_segment_value is not None
                else "6",
            )
        )
        deepgram_ko_max_segment_seconds = float(
            os.getenv(
                "DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS",
                legacy_max_segment_value
                if legacy_max_segment_value is not None
                else "8",
            )
        )
        explicit_hard_limit = os.getenv(
            "DEEPGRAM_STT_HARD_LIMIT_SECONDS", ""
        ).strip()
        deepgram_hard_limit_seconds = (
            float(explicit_hard_limit)
            if explicit_hard_limit
            else max(
                10.0,
                deepgram_max_segment_seconds,
                deepgram_en_max_segment_seconds,
                deepgram_ko_max_segment_seconds,
            )
        )
        legacy_incomplete_wait = os.getenv(
            "DEEPGRAM_STT_INCOMPLETE_FINAL_WAIT_SECONDS", ""
        ).strip()
        return cls(
            project_root=root,
            host=os.getenv("MLT_HOST", "127.0.0.1"),
            port=int(os.getenv("MLT_PORT", "8765")),
            default_model="small",
            selected_model=model,
            sample_rate=int(os.getenv("MLT_SAMPLE_RATE", "16000")),
            prefer_cuda=_env_bool("MLT_PREFER_CUDA", True),
            frame_queue_size=int(os.getenv("MLT_FRAME_QUEUE_SIZE", "256")),
            stt_provider=os.getenv("STT_PROVIDER", "local").strip().lower(),
            translation_direction=os.getenv(
                "TRANSLATION_DIRECTION", "ja_to_ko"
            ).strip().lower(),
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", "").strip() or None,
            deepgram_stt_model=(
                os.getenv("DEEPGRAM_STT_MODEL", "nova-3").strip() or "nova-3"
            ),
            deepgram_stt_language=(
                os.getenv("DEEPGRAM_STT_LANGUAGE", "ja").strip().lower() or "ja"
            ),
            deepgram_endpointing_ms=int(
                os.getenv("DEEPGRAM_STT_ENDPOINTING_MS", "500")
            ),
            deepgram_utterance_end_ms=int(
                os.getenv("DEEPGRAM_STT_UTTERANCE_END_MS", "1300")
            ),
            deepgram_max_segment_seconds=deepgram_max_segment_seconds,
            deepgram_en_endpointing_ms=int(
                os.getenv(
                    "DEEPGRAM_STT_EN_ENDPOINTING_MS",
                    os.getenv("DEEPGRAM_STT_ENDPOINTING_MS", "400"),
                )
            ),
            deepgram_en_utterance_end_ms=int(
                os.getenv(
                    "DEEPGRAM_STT_EN_UTTERANCE_END_MS",
                    os.getenv("DEEPGRAM_STT_UTTERANCE_END_MS", "1000"),
                )
            ),
            deepgram_en_max_segment_seconds=deepgram_en_max_segment_seconds,
            deepgram_ko_endpointing_ms=int(
                os.getenv(
                    "DEEPGRAM_STT_KO_ENDPOINTING_MS",
                    os.getenv("DEEPGRAM_STT_ENDPOINTING_MS", "650"),
                )
            ),
            deepgram_ko_utterance_end_ms=int(
                os.getenv(
                    "DEEPGRAM_STT_KO_UTTERANCE_END_MS",
                    os.getenv("DEEPGRAM_STT_UTTERANCE_END_MS", "1500"),
                )
            ),
            deepgram_ko_max_segment_seconds=deepgram_ko_max_segment_seconds,
            deepgram_checkpoint_seconds=float(
                os.getenv("DEEPGRAM_STT_CHECKPOINT_SECONDS", "4")
            ),
            deepgram_hard_limit_seconds=deepgram_hard_limit_seconds,
            deepgram_open_timeout_seconds=float(
                os.getenv("DEEPGRAM_STT_OPEN_TIMEOUT_SECONDS", "10")
            ),
            deepgram_incomplete_final_wait_seconds=float(
                os.getenv(
                    "DEEPGRAM_STT_JA_INCOMPLETE_FINAL_WAIT_SECONDS",
                    legacy_incomplete_wait or "0.9",
                )
            ),
            deepgram_en_incomplete_final_wait_seconds=float(
                os.getenv(
                    "DEEPGRAM_STT_EN_INCOMPLETE_FINAL_WAIT_SECONDS",
                    legacy_incomplete_wait or "0.7",
                )
            ),
            deepgram_ko_incomplete_final_wait_seconds=float(
                os.getenv(
                    "DEEPGRAM_STT_KO_INCOMPLETE_FINAL_WAIT_SECONDS",
                    legacy_incomplete_wait or "1.5",
                )
            ),
            deepgram_reconnect_max_attempts=int(
                os.getenv("DEEPGRAM_RECONNECT_MAX_ATTEMPTS", "5")
            ),
            deepgram_reconnect_base_delay_seconds=float(
                os.getenv("DEEPGRAM_RECONNECT_BASE_DELAY_SECONDS", "0.5")
            ),
            deepgram_reconnect_max_delay_seconds=float(
                os.getenv("DEEPGRAM_RECONNECT_MAX_DELAY_SECONDS", "5")
            ),
            deepgram_reconnect_buffer_seconds=float(
                os.getenv("DEEPGRAM_RECONNECT_BUFFER_SECONDS", "3")
            ),
            deepgram_recheck_enabled=_env_bool("DEEPGRAM_RECHECK_ENABLED", True),
            deepgram_recheck_model=(
                os.getenv("DEEPGRAM_RECHECK_MODEL", "").strip().lower() or None
            ),
            deepgram_recheck_buffer_seconds=float(
                os.getenv("DEEPGRAM_RECHECK_BUFFER_SECONDS", "14")
            ),
            deepgram_recheck_timeout_seconds=float(
                os.getenv("DEEPGRAM_RECHECK_TIMEOUT_SECONDS", "4")
            ),
            deepgram_recheck_queue_max_size=int(
                os.getenv("DEEPGRAM_RECHECK_QUEUE_MAX_SIZE", "2")
            ),
            deepgram_recheck_local_files_only=_env_bool(
                "DEEPGRAM_RECHECK_LOCAL_FILES_ONLY", True
            ),
            session_dir=root / "data" / "sessions",
            static_dir=root / "frontend" / "static",
            translation_provider=translation_provider,
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
            openai_translation_model=openai_model,
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
            gemini_translation_model=gemini_model,
            gemini_translation_timeout_seconds=float(
                os.getenv("GEMINI_TRANSLATION_TIMEOUT_SECONDS", "20")
            ),
            gemini_translation_max_retries=int(
                os.getenv("GEMINI_TRANSLATION_MAX_RETRIES", "2")
            ),
            gemini_translation_context_segments=int(
                os.getenv("GEMINI_TRANSLATION_CONTEXT_SEGMENTS", "3")
            ),
            translation_timeout_seconds=float(timeout_value),
            translation_max_retries=int(retries_value),
            translation_context_segments=int(
                os.getenv("TRANSLATION_CONTEXT_SEGMENTS", "3")
            ),
            translation_queue_max_size=int(
                os.getenv("TRANSLATION_QUEUE_MAX_SIZE", "100")
            ),
            translation_max_concurrency=int(
                os.getenv("TRANSLATION_MAX_CONCURRENCY", "2")
            ),
            translation_translate_unknown=_env_bool(
                "TRANSLATION_TRANSLATE_UNKNOWN", False
            ),
            translation_glossary_file=_env_path("TRANSLATION_GLOSSARY_FILE", root),
            local_translation_runtime_python=local_runtime,
            local_translation_model=local_model,
            local_translation_ja_model=(
                os.getenv("LOCAL_TRANSLATION_JA_MODEL", "").strip() or None
            ),
            local_translation_en_model=(
                os.getenv("LOCAL_TRANSLATION_EN_MODEL", "").strip() or None
            ),
            session_save_original=_env_bool("SESSION_SAVE_ORIGINAL", True),
            session_save_translation=_env_bool("SESSION_SAVE_TRANSLATION", True),
            session_save_analysis=_env_bool("SESSION_SAVE_ANALYSIS", True),
            session_auto_recover=_env_bool("SESSION_AUTO_RECOVER", True),
            analysis_provider=os.getenv("ANALYSIS_PROVIDER", "none").strip().lower(),
            openai_analysis_model=(
                os.getenv("OPENAI_ANALYSIS_MODEL", "").strip() or None
            ),
            gemini_analysis_model=gemini_analysis_model,
            analysis_timeout_seconds=float(
                os.getenv("ANALYSIS_TIMEOUT_SECONDS", "60")
            ),
            analysis_max_retries=int(os.getenv("ANALYSIS_MAX_RETRIES", "1")),
            analysis_auto_run_on_stop=_env_bool(
                "ANALYSIS_AUTO_RUN_ON_STOP", False
            ),
            analysis_max_segments_per_chunk=int(
                os.getenv("ANALYSIS_MAX_SEGMENTS_PER_CHUNK", "100")
            ),
            analysis_max_chars_per_chunk=int(
                os.getenv("ANALYSIS_MAX_CHARS_PER_CHUNK", "24000")
            ),
            analysis_max_concurrency=int(
                os.getenv("ANALYSIS_MAX_CONCURRENCY", "1")
            ),
            decision_radar_provider=os.getenv(
                "DECISION_RADAR_PROVIDER", "none"
            ).strip().lower(),
            openai_decision_radar_model=(
                os.getenv(
                    "OPENAI_DECISION_RADAR_MODEL",
                    DEFAULT_OPENAI_DECISION_RADAR_MODEL,
                ).strip()
                or DEFAULT_OPENAI_DECISION_RADAR_MODEL
            ),
            gemini_decision_radar_model=gemini_decision_radar_model,
            decision_radar_batch_size=int(
                os.getenv("DECISION_RADAR_BATCH_SIZE", "10")
            ),
            decision_radar_batch_wait_seconds=float(
                os.getenv("DECISION_RADAR_BATCH_WAIT_SECONDS", "20")
            ),
            decision_radar_context_segments=int(
                os.getenv("DECISION_RADAR_CONTEXT_SEGMENTS", "16")
            ),
            decision_radar_queue_max_size=int(
                os.getenv("DECISION_RADAR_QUEUE_MAX_SIZE", "100")
            ),
            decision_radar_timeout_seconds=float(
                os.getenv("DECISION_RADAR_TIMEOUT_SECONDS", "30")
            ),
            decision_radar_max_retries=int(
                os.getenv("DECISION_RADAR_MAX_RETRIES", "1")
            ),
            share_relay_url=(
                os.getenv("MLT_SHARE_RELAY_URL", "").strip() or None
            ),
            share_relay_secret=(
                os.getenv("MLT_SHARE_RELAY_SECRET", "").strip() or None
            ),
            share_relay_timeout_seconds=float(
                os.getenv("MLT_SHARE_RELAY_TIMEOUT_SECONDS", "5")
            ),
        )

    def with_model(self, model: str) -> "AppSettings":
        normalized = model.strip().lower()
        if normalized not in ALLOWED_MODELS:
            raise ValueError(f"Unsupported Whisper model: {normalized}")
        return replace(self, selected_model=normalized)

    def deepgram_profile(self, language: str) -> tuple[int, int, float]:
        normalized = str(language).strip().lower()
        if normalized == "en":
            return (
                self.deepgram_en_endpointing_ms,
                self.deepgram_en_utterance_end_ms,
                self.deepgram_en_max_segment_seconds,
            )
        if normalized == "ko":
            return (
                self.deepgram_ko_endpointing_ms,
                self.deepgram_ko_utterance_end_ms,
                self.deepgram_ko_max_segment_seconds,
            )
        return (
            self.deepgram_endpointing_ms,
            self.deepgram_utterance_end_ms,
            self.deepgram_max_segment_seconds,
        )

    def deepgram_incomplete_wait(self, language: str) -> float:
        normalized = str(language).strip().lower()
        if normalized == "en":
            return self.deepgram_en_incomplete_final_wait_seconds
        if normalized == "ko":
            return self.deepgram_ko_incomplete_final_wait_seconds
        return self.deepgram_incomplete_final_wait_seconds

    def public_dict(self) -> dict[str, Any]:
        return {
            "default_model": self.default_model,
            "selected_model": self.selected_model,
            "allowed_models": list(ALLOWED_MODELS),
            "stt_provider": self.stt_provider,
            "allowed_stt_providers": list(ALLOWED_STT_PROVIDERS),
            "translation_direction": self.translation_direction,
            "allowed_translation_directions": list(ALLOWED_TRANSLATION_DIRECTIONS),
            "deepgram": {
                "configured": bool(self.deepgram_api_key),
                "model": self.deepgram_stt_model,
                "language": self.deepgram_stt_language,
                "streaming": True,
                "interim_results": True,
                "smart_format": True,
                "endpointing_ms": self.deepgram_endpointing_ms,
                "utterance_end_ms": self.deepgram_utterance_end_ms,
                "max_segment_seconds": self.deepgram_max_segment_seconds,
                "checkpoint_seconds": self.deepgram_checkpoint_seconds,
                "hard_limit_seconds": self.deepgram_hard_limit_seconds,
                "incomplete_final_wait_seconds": self.deepgram_incomplete_final_wait_seconds,
                "language_profiles": {
                    "ja": {
                        "endpointing_ms": self.deepgram_endpointing_ms,
                        "utterance_end_ms": self.deepgram_utterance_end_ms,
                        "max_segment_seconds": self.deepgram_max_segment_seconds,
                        "incomplete_final_wait_seconds": self.deepgram_incomplete_final_wait_seconds,
                    },
                    "en": {
                        "endpointing_ms": self.deepgram_en_endpointing_ms,
                        "utterance_end_ms": self.deepgram_en_utterance_end_ms,
                        "max_segment_seconds": self.deepgram_en_max_segment_seconds,
                        "incomplete_final_wait_seconds": self.deepgram_en_incomplete_final_wait_seconds,
                    },
                    "ko": {
                        "endpointing_ms": self.deepgram_ko_endpointing_ms,
                        "utterance_end_ms": self.deepgram_ko_utterance_end_ms,
                        "max_segment_seconds": self.deepgram_ko_max_segment_seconds,
                        "incomplete_final_wait_seconds": self.deepgram_ko_incomplete_final_wait_seconds,
                    },
                },
                "reconnect_max_attempts": self.deepgram_reconnect_max_attempts,
                "reconnect_buffer_seconds": self.deepgram_reconnect_buffer_seconds,
                "selective_recheck": {
                    "enabled": self.deepgram_recheck_enabled,
                    "model": self.deepgram_recheck_model or self.selected_model,
                    "buffer_seconds": self.deepgram_recheck_buffer_seconds,
                    "timeout_seconds": self.deepgram_recheck_timeout_seconds,
                    "queue_max_size": self.deepgram_recheck_queue_max_size,
                    "local_files_only": self.deepgram_recheck_local_files_only,
                },
            },
            "sample_rate": self.sample_rate,
            "target_latency_seconds": [2, 4],
            "capture_mode": "near-real-time",
            "prefer_cuda": self.prefer_cuda,
            "session_storage": {
                "save_original": self.session_save_original,
                "save_translation": self.session_save_translation,
                "save_analysis": self.session_save_analysis,
                "save_audio": False,
                "auto_recover": self.session_auto_recover,
            },
            "analysis": {
                "provider": self.analysis_provider,
                "model": (
                    self.gemini_analysis_model or self.gemini_translation_model
                    if self.analysis_provider == "gemini"
                    else self.openai_analysis_model
                ),
                "auto_run_on_stop": self.analysis_auto_run_on_stop,
                "timeout_seconds": self.analysis_timeout_seconds,
                "max_retries": self.analysis_max_retries,
                "max_segments_per_chunk": self.analysis_max_segments_per_chunk,
                "max_chars_per_chunk": self.analysis_max_chars_per_chunk,
                "max_concurrency": self.analysis_max_concurrency,
            },
            "decision_radar": {
                "provider": self.decision_radar_provider,
                "openai_model": self.openai_decision_radar_model,
                "gemini_model": self.gemini_decision_radar_model,
                "batch_size": self.decision_radar_batch_size,
                "batch_wait_seconds": self.decision_radar_batch_wait_seconds,
                "context_segments": self.decision_radar_context_segments,
                "queue_max_size": self.decision_radar_queue_max_size,
                "timeout_seconds": self.decision_radar_timeout_seconds,
                "max_retries": self.decision_radar_max_retries,
            },
            "live_share": {
                "configured": bool(self.share_relay_url and self.share_relay_secret),
                "external_transmission": True,
                "retention_policy": "delete_on_stop",
            },
        }
