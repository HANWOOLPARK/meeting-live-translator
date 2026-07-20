"""Safe default provider that performs no translation work."""

from __future__ import annotations

from .base import TranslationProvider
from .models import (
    ProviderHealth,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)


class NoneTranslationProvider(TranslationProvider):
    provider_name = "none"
    display_name = "번역 사용 안 함"
    external = False

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        completed_at = iso_now()
        return TranslationResult(
            segment_id=request.segment_id,
            source_text=request.source_text,
            translated_text=None,
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=None,
            status=TranslationStatus.DISABLED,
            requested_at=request.requested_at,
            completed_at=completed_at,
            latency_ms=0,
            session_id=request.session_id,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=True,
            external=False,
        )

    async def close(self) -> None:
        return None


__all__ = ["NoneTranslationProvider"]
