from __future__ import annotations

import struct

import pytest

from backend.app.audio.base import AudioCaptureError, CaptureState
from backend.app.audio.models import AudioDeviceInfo
from backend.app.audio.pyaudio_wpatch_capture import (
    PyAudioWPatchCapture,
    create_audio_capture,
    parse_portaudio_device_id,
)


class FakeStream:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.started = 0
        self.stopped = 0
        self.closed = False

    def start_stream(self) -> None:
        self.started += 1

    def stop_stream(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed = True

    def emit(self, data: bytes, frame_count: int, status_flags: int = 0):
        return self.callback(data, frame_count, {}, status_flags)


class FakePyAudio:
    def __init__(self) -> None:
        self.open_kwargs = None
        self.stream = None
        self.terminated = False

    def open(self, **kwargs):
        self.open_kwargs = kwargs
        self.stream = FakeStream(kwargs["stream_callback"])
        return self.stream

    def terminate(self) -> None:
        self.terminated = True


class FakeModule:
    paInt16 = 8
    paContinue = 17
    paComplete = 18

    def __init__(self) -> None:
        self.audio = FakePyAudio()

    def PyAudio(self) -> FakePyAudio:
        return self.audio


def loopback_device() -> AudioDeviceInfo:
    return AudioDeviceInfo(
        device_id="pa:7",
        name="USB Headset (Loopback)",
        host_api="Windows WASAPI",
        is_loopback=True,
        max_input_channels=2,
        default_sample_rate=48_000,
    )


def test_capture_start_pause_resume_stop_and_frames() -> None:
    module = FakeModule()
    received = []
    capture = PyAudioWPatchCapture(
        loopback_device(),
        callback=received.append,
        frames_per_buffer=960,
        pyaudio_module=module,
    )

    assert capture.state is CaptureState.IDLE
    capture.start()
    stream = module.audio.stream
    assert stream is not None
    assert capture.is_running
    assert module.audio.open_kwargs["input_device_index"] == 7
    assert module.audio.open_kwargs["channels"] == 2
    assert module.audio.open_kwargs["rate"] == 48_000
    assert module.audio.open_kwargs["start"] is False

    pcm = struct.pack("<hhhh", 100, -100, 200, -200)
    assert stream.emit(pcm, frame_count=2, status_flags=3) == (None, module.paContinue)
    assert len(received) == 1
    assert received[0].data == pcm
    assert received[0].frame_count == 2
    assert received[0].device_id == "pa:7"
    assert received[0].status_flags == 3

    capture.pause()
    assert capture.is_paused
    stream.emit(pcm, frame_count=2)
    assert len(received) == 1

    capture.resume()
    assert capture.is_running
    stream.emit(pcm, frame_count=2)
    assert len(received) == 2

    capture.stop()
    capture.stop()  # idempotent
    assert capture.state is CaptureState.STOPPED
    assert stream.started == 2
    assert stream.stopped == 2
    assert stream.closed is True
    assert module.audio.terminated is True
    assert stream.emit(pcm, frame_count=2) == (None, module.paComplete)


def test_callback_exception_is_recorded_without_leaking_to_audio_thread() -> None:
    module = FakeModule()

    def broken_callback(frame) -> None:
        raise RuntimeError("consumer failed")

    capture = PyAudioWPatchCapture(
        loopback_device(), callback=broken_callback, pyaudio_module=module
    )
    capture.start()
    result = module.audio.stream.emit(b"\x00\x00\x00\x00", frame_count=1)

    assert result == (None, module.paContinue)
    assert "consumer failed" in (capture.last_error or "")
    assert capture.is_running
    capture.stop()


def test_factory_accepts_audio_device_info() -> None:
    capture = create_audio_capture(loopback_device(), pyaudio_module=FakeModule())
    assert isinstance(capture, PyAudioWPatchCapture)
    assert capture.device.device_id == "pa:7"


@pytest.mark.parametrize("value", ["7", "other:7", "pa:-1", "pa:", "pa:abc"])
def test_invalid_device_id_is_rejected(value: str) -> None:
    with pytest.raises(AudioCaptureError):
        parse_portaudio_device_id(value)


def test_output_device_requires_its_loopback() -> None:
    output = AudioDeviceInfo(
        device_id="pa:4",
        name="Speakers",
        max_output_channels=2,
        default_sample_rate=48_000,
    )
    with pytest.raises(AudioCaptureError, match="loopback"):
        PyAudioWPatchCapture(output, pyaudio_module=FakeModule())


def test_capture_requires_callback() -> None:
    capture = PyAudioWPatchCapture(loopback_device(), pyaudio_module=FakeModule())
    with pytest.raises(AudioCaptureError, match="callback"):
        capture.start()

