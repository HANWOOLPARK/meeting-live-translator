"""Backend-neutral audio capture contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable

from .models import AudioDeviceInfo, AudioFrame


FrameCallback = Callable[[AudioFrame], None]


class CaptureState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class AudioCaptureError(RuntimeError):
    """Recoverable failure at the audio backend boundary."""


class AudioCaptureBase(ABC):
    """Interface implemented by replaceable audio capture backends."""

    @property
    @abstractmethod
    def device(self) -> AudioDeviceInfo:
        raise NotImplementedError

    @property
    @abstractmethod
    def state(self) -> CaptureState:
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return self.state is CaptureState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state is CaptureState.PAUSED

    @abstractmethod
    def start(self, callback: FrameCallback | None = None) -> None:
        """Open the device and start delivering frames to ``callback``."""

        raise NotImplementedError

    @abstractmethod
    def pause(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def resume(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "AudioCaptureBase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

