from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WhisperModelName = Literal["tiny", "base", "small", "medium"]
SttProviderName = Literal["local", "deepgram"]
TranslationDirectionName = Literal[
    "ja_to_ko",
    "ja_to_en",
    "en_to_ko",
    "en_to_ja",
    "ko_to_ja",
    "ko_to_en",
]
TranslationProviderName = Literal["none", "local", "openai", "gemini"]
AnalysisProviderName = Literal["none", "rule_based", "openai", "gemini"]
DecisionRadarProviderName = Literal["none", "openai", "gemini"]


class StartCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["system", "microphone"]
    device_id: str = Field(min_length=1, max_length=128)
    model: WhisperModelName = "small"
    stt_provider: SttProviderName | None = None
    translation_direction: TranslationDirectionName | None = None


class SettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: WhisperModelName


class TranslationSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: TranslationProviderName


class TranslationTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        default="現在確認しています",
        min_length=1,
        max_length=4_000,
    )
    source_language: Literal["ja", "en", "ko", "mixed", "unknown"] = "ja"
    target_language: Literal["ko", "ja", "en"] = "ko"


class SessionStorageSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    save_original: bool = True
    save_translation: bool = True
    save_analysis: bool = True


class AnalysisSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: AnalysisProviderName
    auto_run_on_stop: bool | None = None


class DecisionRadarSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: DecisionRadarProviderName


class LiveShareStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_confirmed: bool


class DecisionRadarItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: Literal["suggested", "approved"] | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4_000)
    assignee: str | None = Field(default=None, max_length=240)
    due_date: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def require_a_change(self) -> "DecisionRadarItemUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one Decision Radar field is required")
        return self


class ContextProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=240)


class ContextEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["term", "person"] = "term"
    canonical: str = Field(min_length=1, max_length=120)
    variants: list[str] = Field(default_factory=list, max_length=20)


class ContextSuggestionGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)


class ContextSuggestionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept: bool
    canonical: str | None = Field(default=None, min_length=1, max_length=120)
    category: Literal["term", "person"] | None = None
    variants: list[str] = Field(default_factory=list, max_length=20)
