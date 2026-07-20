"""Replaceable translation provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ProviderHealth, TranslationRequest, TranslationResult


class TranslationProvider(ABC):
    provider_name: str
    display_name: str
    external: bool = False

    @abstractmethod
    async def translate(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


__all__ = ["TranslationProvider"]
