"""Meeting analysis Provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AnalysisProviderHealth, AnalysisRequest, MeetingAnalysis


class AnalysisProvider(ABC):
    provider_name: str
    display_name: str
    external: bool = False

    @abstractmethod
    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> AnalysisProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


__all__ = ["AnalysisProvider"]
