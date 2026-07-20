"""Analysis-disabled Provider; performs no extraction or external call."""

from __future__ import annotations

from .base import AnalysisProvider
from .models import (
    AnalysisProviderHealth,
    AnalysisRequest,
    AnalysisStatus,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
)


class NoneAnalysisProvider(AnalysisProvider):
    provider_name = "none"
    display_name = "회의 분석 사용 안 함"
    external = False

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        return MeetingAnalysis(
            session_id=request.session_id,
            provider=self.provider_name,
            model=None,
            status=AnalysisStatus.NOT_STARTED,
            meeting_purpose=EvidenceItem(UNDECIDED),
            warnings=("analysis_disabled",),
        )

    async def health_check(self) -> AnalysisProviderHealth:
        return AnalysisProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=True,
            external=False,
        )

    async def close(self) -> None:
        return None


__all__ = ["NoneAnalysisProvider"]
