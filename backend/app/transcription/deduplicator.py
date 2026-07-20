"""Conservative finalized-transcript duplicate suppression."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import deque
from collections.abc import Callable
from difflib import SequenceMatcher
from time import monotonic


_SEPARATOR_RE = re.compile(r"[\s\W_]+", re.UNICODE)


class TranscriptDeduplicator:
    """Remember recent final transcripts and reject only strong duplicates.

    Exact matches ignore case, width, whitespace, and punctuation.  Fuzzy and
    partial-overlap checks require long strings and deliberately high ratios,
    so two legitimate short acknowledgements or related sentences are not
    accidentally collapsed.
    """

    def __init__(
        self,
        max_history: int = 100,
        *,
        similarity_threshold: float = 0.96,
        partial_overlap_threshold: float = 0.90,
        minimum_fuzzy_characters: int = 12,
        duplicate_window_seconds: float = 3.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in (0, 1]")
        if not 0.0 < partial_overlap_threshold <= 1.0:
            raise ValueError("partial_overlap_threshold must be in (0, 1]")
        if minimum_fuzzy_characters <= 0:
            raise ValueError("minimum_fuzzy_characters must be positive")
        if duplicate_window_seconds <= 0:
            raise ValueError("duplicate_window_seconds must be positive")
        self.max_history = int(max_history)
        self.similarity_threshold = float(similarity_threshold)
        self.partial_overlap_threshold = float(partial_overlap_threshold)
        self.minimum_fuzzy_characters = int(minimum_fuzzy_characters)
        self.duplicate_window_seconds = float(duplicate_window_seconds)
        self._clock = clock
        self._history: deque[tuple[str, str, float]] = deque(maxlen=self.max_history)

    @staticmethod
    def normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(text)).casefold()
        return _SEPARATOR_RE.sub("", normalized)

    @property
    def history(self) -> tuple[str, ...]:
        return tuple(original for original, _, _ in self._history)

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self.duplicate_window_seconds
        while self._history and self._history[0][2] < cutoff:
            self._history.popleft()

    @staticmethod
    def _suffix_prefix_overlap(previous: str, candidate: str) -> int:
        limit = min(len(previous), len(candidate))
        for length in range(limit, 0, -1):
            if previous[-length:] == candidate[:length]:
                return length
        return 0

    def is_duplicate(self, text: str) -> bool:
        candidate = self.normalize(text)
        if not candidate:
            return True
        now = self._clock()
        self._prune_expired(now)
        for _, previous, _ in reversed(self._history):
            if candidate == previous:
                return True

            shorter = min(len(candidate), len(previous))
            longer = max(len(candidate), len(previous))
            if shorter < self.minimum_fuzzy_characters:
                continue

            # A candidate that is almost entirely contained in a prior final is
            # typically a repeated buffer tail.  A longer candidate containing
            # a prior final is retained because it may add new information.
            if (
                candidate in previous
                and len(candidate) / len(previous) >= self.partial_overlap_threshold
            ):
                return True

            length_ratio = shorter / longer
            if length_ratio >= self.partial_overlap_threshold:
                similarity = SequenceMatcher(None, previous, candidate, autojunk=False).ratio()
                if similarity >= self.similarity_threshold:
                    return True

            overlap = self._suffix_prefix_overlap(previous, candidate)
            required_overlap = max(
                self.minimum_fuzzy_characters,
                int(math.ceil(len(candidate) * self.partial_overlap_threshold)),
            )
            if overlap >= required_overlap:
                return True
        return False

    def add(self, text: str) -> None:
        normalized = self.normalize(text)
        if normalized:
            now = self._clock()
            self._prune_expired(now)
            self._history.append((str(text).strip(), normalized, now))

    def accept(self, text: str) -> bool:
        """Check and remember ``text``; return whether it should be emitted."""

        if self.is_duplicate(text):
            return False
        self.add(text)
        return True

    check_and_add = accept

    def filter(self, text: str) -> str | None:
        """Return stripped text when accepted, otherwise ``None``."""

        stripped = str(text).strip()
        return stripped if self.accept(stripped) else None

    def reset(self) -> None:
        self._history.clear()
