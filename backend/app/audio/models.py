"""Value objects shared by audio device discovery and capture.

The module deliberately has no dependency on PyAudioWPatch.  Keeping these
objects dependency-free lets the rest of the application and unit tests use
the audio boundary on machines where Windows audio support is unavailable.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AudioDeviceInfo:
    """Portable description of one PortAudio device.

    ``device_id`` is intentionally opaque to callers.  The PyAudioWPatch
    implementation uses ``pa:<index>`` so device indices are not confused
    with IDs from future capture backends.
    """

    device_id: str
    name: str
    host_api: str = "Unknown"
    is_loopback: bool = False
    is_default: bool = False
    max_input_channels: int = 0
    max_output_channels: int = 0
    default_sample_rate: float = 0.0

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if self.max_input_channels < 0 or self.max_output_channels < 0:
            raise ValueError("channel counts must not be negative")
        if self.default_sample_rate < 0:
            raise ValueError("default_sample_rate must not be negative")

    @property
    def portaudio_index(self) -> int:
        """Return the numeric index for a ``pa:<index>`` device ID."""

        prefix, separator, value = self.device_id.partition(":")
        if prefix != "pa" or separator != ":" or not value.isdecimal():
            raise ValueError(f"invalid PortAudio device ID: {self.device_id!r}")
        index = int(value)
        if index < 0:
            raise ValueError(f"invalid PortAudio device ID: {self.device_id!r}")
        return index

    @property
    def source_kind(self) -> str:
        if self.is_loopback:
            return "system"
        if self.max_input_channels > 0:
            return "microphone"
        return "output"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable API representation."""

        return {
            "device_id": self.device_id,
            "name": self.name,
            "host_api": self.host_api,
            "is_loopback": self.is_loopback,
            "is_default": self.is_default,
            "max_input_channels": self.max_input_channels,
            "max_output_channels": self.max_output_channels,
            "default_sample_rate": self.default_sample_rate,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One callback-sized PCM frame.

    Capture currently produces signed little-endian PCM16.  ``to_dict`` uses
    base64 for the payload so even diagnostic serialization remains JSON safe.
    Audio samples should normally stay in-process rather than be sent as JSON.
    """

    data: bytes
    sample_rate: int
    channels: int
    timestamp: datetime = field(default_factory=_utc_now)
    device_id: str | None = None
    sample_width: int = 2
    frame_count: int | None = None
    status_flags: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            object.__setattr__(self, "data", bytes(self.data))
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sample_width <= 0:
            raise ValueError("sample_width must be positive")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc))

        bytes_per_frame = self.channels * self.sample_width
        if len(self.data) % bytes_per_frame:
            raise ValueError("audio payload is not aligned to complete sample frames")
        inferred_count = len(self.data) // bytes_per_frame
        if self.frame_count is None:
            object.__setattr__(self, "frame_count", inferred_count)
        elif self.frame_count < 0:
            raise ValueError("frame_count must not be negative")

    @property
    def pcm(self) -> bytes:
        """Compatibility alias that makes the PCM nature of ``data`` clear."""

        return self.data

    @property
    def duration_seconds(self) -> float:
        return (self.frame_count or 0) / self.sample_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_base64": base64.b64encode(self.data).decode("ascii"),
            "encoding": "pcm_s16le",
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "timestamp": self.timestamp.isoformat(),
            "device_id": self.device_id,
            "sample_width": self.sample_width,
            "frame_count": self.frame_count,
            "status_flags": self.status_flags,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(slots=True)
class DeviceCatalog:
    """Device discovery result, including non-fatal discovery warnings."""

    outputs: list[AudioDeviceInfo] = field(default_factory=list)
    loopbacks: list[AudioDeviceInfo] = field(default_factory=list)
    microphones: list[AudioDeviceInfo] = field(default_factory=list)
    default_output_id: str | None = None
    default_loopback_id: str | None = None
    default_microphone_id: str | None = None
    output_loopback_pairs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def capture_devices(self) -> tuple[AudioDeviceInfo, ...]:
        return tuple((*self.loopbacks, *self.microphones))

    def find(self, device_id: str) -> AudioDeviceInfo | None:
        for device in (*self.outputs, *self.loopbacks, *self.microphones):
            if device.device_id == device_id:
                return device
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outputs": [device.to_dict() for device in self.outputs],
            "loopbacks": [device.to_dict() for device in self.loopbacks],
            "microphones": [device.to_dict() for device in self.microphones],
            "default_output_id": self.default_output_id,
            "default_loopback_id": self.default_loopback_id,
            "default_microphone_id": self.default_microphone_id,
            "output_loopback_pairs": dict(self.output_loopback_pairs),
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
