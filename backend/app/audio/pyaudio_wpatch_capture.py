"""PyAudioWPatch capture implementation.

PyAudioWPatch is imported only when a capture starts.  Importing the FastAPI
application therefore remains safe on non-Windows development and test hosts.
"""

from __future__ import annotations

import importlib
import threading
from datetime import datetime, timezone
from types import ModuleType
from typing import Any

from .base import (
    AudioCaptureBase,
    AudioCaptureError,
    CaptureState,
    FrameCallback,
)
from .models import AudioDeviceInfo, AudioFrame


def parse_portaudio_device_id(device_id: str) -> int:
    prefix, separator, value = device_id.partition(":")
    if prefix != "pa" or separator != ":" or not value.isdecimal():
        raise AudioCaptureError(f"Invalid audio device ID: {device_id!r}")
    index = int(value)
    if index < 0:
        raise AudioCaptureError(f"Invalid audio device ID: {device_id!r}")
    return index


def _coerce_device(
    device: AudioDeviceInfo | str | int,
    *,
    sample_rate: int | None,
    channels: int | None,
) -> AudioDeviceInfo:
    if isinstance(device, AudioDeviceInfo):
        return device
    if isinstance(device, bool):
        raise AudioCaptureError("Boolean values are not valid audio device IDs")
    if isinstance(device, int):
        if device < 0:
            raise AudioCaptureError("PortAudio device index must not be negative")
        device_id = f"pa:{device}"
    elif isinstance(device, str):
        parse_portaudio_device_id(device)
        device_id = device
    else:
        raise AudioCaptureError("device must be AudioDeviceInfo, pa:<index>, or an index")

    # Raw IDs are supported for scripting.  DeviceCatalog information is
    # preferred because it preserves the real channel count and sample rate.
    return AudioDeviceInfo(
        device_id=device_id,
        name=device_id,
        max_input_channels=channels or 2,
        default_sample_rate=float(sample_rate or 48_000),
    )


class PyAudioWPatchCapture(AudioCaptureBase):
    """Callback-based PCM16 capture with explicit lifecycle transitions."""

    def __init__(
        self,
        device: AudioDeviceInfo | str | int,
        *,
        callback: FrameCallback | None = None,
        sample_rate: int | None = None,
        channels: int | None = None,
        frames_per_buffer: int = 960,
        pyaudio_module: ModuleType | Any | None = None,
    ) -> None:
        self._device = _coerce_device(
            device, sample_rate=sample_rate, channels=channels
        )
        try:
            self._device_index = parse_portaudio_device_id(self._device.device_id)
        except AudioCaptureError:
            raise

        available_channels = self._device.max_input_channels
        if available_channels <= 0:
            raise AudioCaptureError(
                f"Device {self._device.device_id!r} has no input channels; "
                "select its WASAPI loopback device for system audio."
            )
        selected_channels = channels if channels is not None else min(2, available_channels)
        if selected_channels <= 0 or selected_channels > available_channels:
            raise AudioCaptureError(
                f"Requested {selected_channels} channel(s), but device supports "
                f"{available_channels}."
            )

        selected_rate = sample_rate or int(round(self._device.default_sample_rate))
        if selected_rate <= 0:
            raise AudioCaptureError("A positive capture sample rate is required")
        if frames_per_buffer <= 0:
            raise AudioCaptureError("frames_per_buffer must be positive")

        self._sample_rate = selected_rate
        self._channels = selected_channels
        self._frames_per_buffer = frames_per_buffer
        self._callback = callback
        self._module = pyaudio_module
        self._audio: Any | None = None
        self._stream: Any | None = None
        self._state = CaptureState.IDLE
        self._last_error: str | None = None
        self._sequence = 0
        self._lock = threading.RLock()

    @property
    def device(self) -> AudioDeviceInfo:
        return self._device

    @property
    def state(self) -> CaptureState:
        with self._lock:
            return self._state

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def frames_per_buffer(self) -> int:
        return self._frames_per_buffer

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def _load_module(self) -> ModuleType | Any:
        if self._module is None:
            try:
                self._module = importlib.import_module("pyaudiowpatch")
            except (ImportError, OSError) as error:
                raise AudioCaptureError(
                    "PyAudioWPatch is unavailable; run the project setup first."
                ) from error
        return self._module

    def start(self, callback: FrameCallback | None = None) -> None:
        with self._lock:
            if self._state in (CaptureState.RUNNING, CaptureState.PAUSED):
                raise AudioCaptureError(f"Capture is already {self._state.value}")
            if callback is not None:
                self._callback = callback
            if self._callback is None:
                raise AudioCaptureError("A frame callback is required before capture can start")

            module = self._load_module()
            audio: Any | None = None
            stream: Any | None = None
            try:
                audio = module.PyAudio()
                stream = audio.open(
                    format=getattr(module, "paInt16", 8),
                    channels=self._channels,
                    rate=self._sample_rate,
                    input=True,
                    input_device_index=self._device_index,
                    frames_per_buffer=self._frames_per_buffer,
                    stream_callback=self._portaudio_callback,
                    start=False,
                )
                self._audio = audio
                self._stream = stream
                self._sequence = 0
                self._last_error = None
                self._state = CaptureState.RUNNING
                stream.start_stream()
            except Exception as error:
                self._audio = None
                self._stream = None
                self._state = CaptureState.STOPPED
                self._record_error("Could not start audio capture", error)
                self._cleanup(stream, audio, stop_stream=True)
                if isinstance(error, AudioCaptureError):
                    raise
                raise AudioCaptureError(self._last_error or "Could not start audio capture") from error

    def pause(self) -> None:
        with self._lock:
            if self._state is CaptureState.PAUSED:
                return
            if self._state is not CaptureState.RUNNING or self._stream is None:
                raise AudioCaptureError("Capture must be running before it can be paused")
            stream = self._stream
            self._state = CaptureState.PAUSED
            try:
                stream.stop_stream()
            except Exception as error:
                self._state = CaptureState.RUNNING
                self._record_error("Could not pause audio capture", error)
                raise AudioCaptureError(self._last_error or "Could not pause audio capture") from error

    def resume(self) -> None:
        with self._lock:
            if self._state is CaptureState.RUNNING:
                return
            if self._state is not CaptureState.PAUSED or self._stream is None:
                raise AudioCaptureError("Capture must be paused before it can be resumed")
            stream = self._stream
            self._state = CaptureState.RUNNING
            try:
                stream.start_stream()
            except Exception as error:
                self._state = CaptureState.PAUSED
                self._record_error("Could not resume audio capture", error)
                raise AudioCaptureError(self._last_error or "Could not resume audio capture") from error

    def stop(self) -> None:
        with self._lock:
            if self._state is CaptureState.STOPPED and self._stream is None:
                return
            previous_state = self._state
            stream, audio = self._stream, self._audio
            self._stream = None
            self._audio = None
            self._state = CaptureState.STOPPED
        self._cleanup(
            stream,
            audio,
            stop_stream=(previous_state is CaptureState.RUNNING),
        )

    def _portaudio_callback(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float] | None,
        status_flags: int,
    ) -> tuple[None, int]:
        module = self._module
        continue_flag = getattr(module, "paContinue", 0)
        complete_flag = getattr(module, "paComplete", 1)
        try:
            with self._lock:
                state = self._state
                callback = self._callback
                if state is CaptureState.STOPPED:
                    return None, complete_flag
                if state is not CaptureState.RUNNING or callback is None:
                    return None, continue_flag
                self._sequence += 1

            frame = AudioFrame(
                data=bytes(in_data),
                sample_rate=self._sample_rate,
                channels=self._channels,
                timestamp=datetime.now(timezone.utc),
                device_id=self._device.device_id,
                frame_count=int(frame_count),
                status_flags=int(status_flags),
            )
            callback(frame)
        except Exception as error:
            # PortAudio callbacks must never leak Python exceptions back into
            # the native audio thread.  The owner can inspect ``last_error``.
            self._record_error("Audio frame callback failed", error)
        return None, continue_flag

    def _record_error(self, action: str, error: BaseException) -> None:
        detail = str(error).strip()
        message = f"{action}: {type(error).__name__}"
        if detail:
            message = f"{message}: {detail}"
        with self._lock:
            self._last_error = message

    def _cleanup(
        self,
        stream: Any | None,
        audio: Any | None,
        *,
        stop_stream: bool,
    ) -> None:
        if stream is not None:
            if stop_stream:
                try:
                    stream.stop_stream()
                except Exception as error:
                    self._record_error("Could not stop the audio stream", error)
            try:
                stream.close()
            except Exception as error:
                self._record_error("Could not close the audio stream", error)
        if audio is not None:
            try:
                audio.terminate()
            except Exception as error:
                self._record_error("Could not terminate PyAudio", error)


def create_audio_capture(
    device: AudioDeviceInfo | str | int,
    *,
    callback: FrameCallback | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    frames_per_buffer: int = 960,
    pyaudio_module: ModuleType | Any | None = None,
) -> AudioCaptureBase:
    """Factory kept at the backend boundary for future capture implementations."""

    return PyAudioWPatchCapture(
        device,
        callback=callback,
        sample_rate=sample_rate,
        channels=channels,
        frames_per_buffer=frames_per_buffer,
        pyaudio_module=pyaudio_module,
    )

