"""Replaceable Windows audio discovery and capture boundary."""

from .base import (
    AudioCaptureBase,
    AudioCaptureError,
    CaptureState,
    FrameCallback,
)
from .devices import PyAudioWPatchDeviceProvider, pair_output_loopback
from .models import AudioDeviceInfo, AudioFrame, DeviceCatalog
from .processing import (
    audio_level_from_pcm16,
    calculate_audio_level,
    calculate_dbfs,
    pcm16_to_mono_float32,
    pcm16_to_mono_resampled,
    resample_audio,
)
from .pyaudio_wpatch_capture import PyAudioWPatchCapture, create_audio_capture

__all__ = [
    "AudioCaptureBase",
    "AudioCaptureError",
    "AudioDeviceInfo",
    "AudioFrame",
    "CaptureState",
    "DeviceCatalog",
    "FrameCallback",
    "PyAudioWPatchCapture",
    "PyAudioWPatchDeviceProvider",
    "audio_level_from_pcm16",
    "calculate_audio_level",
    "calculate_dbfs",
    "create_audio_capture",
    "pair_output_loopback",
    "pcm16_to_mono_float32",
    "pcm16_to_mono_resampled",
    "resample_audio",
]
