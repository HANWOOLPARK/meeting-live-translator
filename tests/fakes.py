from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.audio.base import AudioCaptureBase, CaptureState, FrameCallback
from backend.app.audio.models import AudioDeviceInfo, AudioFrame, DeviceCatalog
from backend.app.transcription.models import TranscriptionResult


LOOPBACK = AudioDeviceInfo(
    device_id="pa:10",
    name="Speakers [Loopback]",
    host_api="Windows WASAPI",
    is_loopback=True,
    is_default=True,
    max_input_channels=2,
    default_sample_rate=16_000,
)
MICROPHONE = AudioDeviceInfo(
    device_id="pa:11",
    name="Microphone",
    host_api="Windows WASAPI",
    is_default=True,
    max_input_channels=1,
    default_sample_rate=16_000,
)
OUTPUT = AudioDeviceInfo(
    device_id="pa:9",
    name="Speakers",
    host_api="Windows WASAPI",
    is_default=True,
    max_output_channels=2,
    default_sample_rate=16_000,
)


class FakeDeviceProvider:
    def __init__(self, catalog: DeviceCatalog | None = None) -> None:
        self.catalog = catalog or DeviceCatalog(
            outputs=[OUTPUT],
            loopbacks=[LOOPBACK],
            microphones=[MICROPHONE],
            default_output_id=OUTPUT.device_id,
            default_loopback_id=LOOPBACK.device_id,
            default_microphone_id=MICROPHONE.device_id,
            output_loopback_pairs={OUTPUT.device_id: LOOPBACK.device_id},
        )
        self.refresh_count = 0

    def list_devices(self) -> DeviceCatalog:
        return self.catalog

    def refresh(self) -> DeviceCatalog:
        self.refresh_count += 1
        return self.catalog


class ExplodingDeviceProvider(FakeDeviceProvider):
    def list_devices(self) -> DeviceCatalog:
        raise RuntimeError("SECRET=C:\\Users\\private\\meeting.wav")


class FakeCapture(AudioCaptureBase):
    def __init__(self, device: AudioDeviceInfo) -> None:
        self._device = device
        self._state = CaptureState.IDLE
        self.callback: FrameCallback | None = None

    @property
    def device(self) -> AudioDeviceInfo:
        return self._device

    @property
    def state(self) -> CaptureState:
        return self._state

    def start(self, callback: FrameCallback | None = None) -> None:
        if callback is None:
            raise RuntimeError("callback required")
        self.callback = callback
        self._state = CaptureState.RUNNING

    def pause(self) -> None:
        self._state = CaptureState.PAUSED

    def resume(self) -> None:
        self._state = CaptureState.RUNNING

    def stop(self) -> None:
        self._state = CaptureState.STOPPED

    def emit(self, samples: np.ndarray, *, sample_rate: int = 16_000) -> None:
        if self.callback is None or self._state is not CaptureState.RUNNING:
            return
        clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 0.999969)
        pcm = (clipped * 32768.0).astype("<i2").tobytes()
        self.callback(
            AudioFrame(
                data=pcm,
                sample_rate=sample_rate,
                channels=1,
                device_id=self.device.device_id,
            )
        )


class FakeCaptureFactory:
    def __init__(self) -> None:
        self.instances: list[FakeCapture] = []

    def __call__(self, device: AudioDeviceInfo) -> FakeCapture:
        capture = FakeCapture(device)
        self.instances.append(capture)
        return capture

    @property
    def latest(self) -> FakeCapture:
        return self.instances[-1]


class FakeEngine:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.loaded = False
        self.calls = 0

    def ensure_loaded(self) -> None:
        self.loaded = True

    def model_info(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "loaded": self.loaded,
            "device": "cpu",
            "compute_type": "int8",
            "cuda_fallback": True,
            "cuda_error": "secret local detail",
        }

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        self.calls += 1
        duration = len(samples) / 16_000
        text = "確定した文章です" if duration >= 1.8 else "途中の字幕です"
        return TranscriptionResult(
            text=text,
            detected_language="ja",
            language_probability=0.93,
            started_offset=0.0,
            ended_offset=duration,
            inference_seconds=0.01,
        )


class RecordingManager:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def broadcast(self, event: dict[str, object]) -> None:
        self.events.append(event)

