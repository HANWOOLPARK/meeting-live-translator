from __future__ import annotations

from .repository import JsonlSessionRepository


def recover_incomplete_sessions(repository: JsonlSessionRepository) -> list[str]:
    """Recover only Phase 3 directories; legacy JSONL remains read-only."""

    return repository.recover_incomplete()


__all__ = ["recover_incomplete_sessions"]
