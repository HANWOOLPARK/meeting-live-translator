"""Small bounded queue wrapper with safe selective cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Generic, TypeVar


T = TypeVar("T")


class TranslationQueue(Generic[T]):
    def __init__(self, max_size: int = 100) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = int(max_size)
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=self.max_size)

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def full(self) -> bool:
        return self._queue.full()

    def put_nowait(self, item: T) -> bool:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            return False
        return True

    async def get(self) -> T:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def remove(self, predicate: Callable[[T], bool]) -> list[T]:
        removed: list[T] = []
        retained: list[T] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            (removed if predicate(item) else retained).append(item)
        for item in retained:
            self._queue.put_nowait(item)
        return removed

    def drain(self) -> list[T]:
        return self.remove(lambda item: True)


__all__ = ["TranslationQueue"]
