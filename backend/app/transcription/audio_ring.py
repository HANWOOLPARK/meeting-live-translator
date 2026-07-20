"""Bounded in-memory PCM history for selective transcription rechecks."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Pcm16Slice:
    samples: NDArray[np.float32]
    started_offset: float
    ended_offset: float


@dataclass(frozen=True, slots=True)
class _Chunk:
    pcm: bytes
    started_offset: float
    ended_offset: float


class Pcm16RingBuffer:
    """Keep a small absolute-timeline PCM window without writing audio to disk."""

    def __init__(self, *, sample_rate: int = 16_000, max_seconds: float = 14.0) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if not (1.0 <= max_seconds <= 60.0):
            raise ValueError("max_seconds must be between 1 and 60")
        self.sample_rate = int(sample_rate)
        self.max_seconds = float(max_seconds)
        self._chunks: deque[_Chunk] = deque()
        self._bytes = 0

    def clear(self) -> None:
        self._chunks.clear()
        self._bytes = 0

    def append(self, pcm16_mono: bytes, *, started_offset: float) -> None:
        if not pcm16_mono:
            return
        usable = len(pcm16_mono) - (len(pcm16_mono) % 2)
        if usable <= 0:
            return
        pcm = bytes(pcm16_mono[:usable])
        started = max(0.0, float(started_offset))
        ended = started + usable / (2 * self.sample_rate)
        self._chunks.append(_Chunk(pcm, started, ended))
        self._bytes += usable
        self._trim(ended - self.max_seconds)

    def _trim(self, cutoff: float) -> None:
        while self._chunks and self._chunks[0].ended_offset <= cutoff:
            removed = self._chunks.popleft()
            self._bytes -= len(removed.pcm)
        if not self._chunks or self._chunks[0].started_offset >= cutoff:
            return
        first = self._chunks.popleft()
        drop_samples = min(
            len(first.pcm) // 2,
            max(0, int(round((cutoff - first.started_offset) * self.sample_rate))),
        )
        drop_bytes = drop_samples * 2
        retained = first.pcm[drop_bytes:]
        self._bytes -= drop_bytes
        if retained:
            retained_start = first.started_offset + drop_samples / self.sample_rate
            self._chunks.appendleft(_Chunk(retained, retained_start, first.ended_offset))

    def extract(
        self,
        started_offset: float,
        ended_offset: float,
        *,
        padding_before: float = 0.25,
        padding_after: float = 0.35,
    ) -> Pcm16Slice | None:
        if not self._chunks:
            return None
        wanted_start = max(0.0, float(started_offset) - max(0.0, padding_before))
        wanted_end = max(wanted_start, float(ended_offset) + max(0.0, padding_after))
        pieces: list[bytes] = []
        actual_start: float | None = None
        actual_end = 0.0
        for chunk in self._chunks:
            overlap_start = max(wanted_start, chunk.started_offset)
            overlap_end = min(wanted_end, chunk.ended_offset)
            if overlap_end <= overlap_start:
                continue
            start_sample = max(
                0,
                int(round((overlap_start - chunk.started_offset) * self.sample_rate)),
            )
            end_sample = min(
                len(chunk.pcm) // 2,
                int(round((overlap_end - chunk.started_offset) * self.sample_rate)),
            )
            if end_sample <= start_sample:
                continue
            pieces.append(chunk.pcm[start_sample * 2 : end_sample * 2])
            piece_start = chunk.started_offset + start_sample / self.sample_rate
            piece_end = chunk.started_offset + end_sample / self.sample_rate
            actual_start = piece_start if actual_start is None else min(actual_start, piece_start)
            actual_end = max(actual_end, piece_end)
        if not pieces or actual_start is None:
            return None
        pcm = b"".join(pieces)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        return Pcm16Slice(samples.copy(), actual_start, actual_end)

    def snapshot(self) -> dict[str, float | int]:
        if not self._chunks:
            return {"buffered_seconds": 0.0, "buffered_bytes": 0}
        return {
            "buffered_seconds": max(
                0.0,
                self._chunks[-1].ended_offset - self._chunks[0].started_offset,
            ),
            "buffered_bytes": self._bytes,
        }


__all__ = ["Pcm16RingBuffer", "Pcm16Slice"]
