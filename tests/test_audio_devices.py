from __future__ import annotations

import json

from backend.app.audio.devices import (
    PyAudioWPatchDeviceProvider,
    pair_output_loopback,
)
from backend.app.audio.models import AudioDeviceInfo, AudioFrame, DeviceCatalog


class FakePyAudio:
    def __init__(self) -> None:
        self.terminated = False
        self.devices = [
            {
                "index": 0,
                "name": "Speakers (USB Headset)",
                "hostApi": 0,
                "maxInputChannels": 0,
                "maxOutputChannels": 2,
                "defaultSampleRate": 48000.0,
            },
            {
                "index": 1,
                "name": "Speakers (USB Headset) [Loopback]",
                "hostApi": 0,
                "maxInputChannels": 2,
                "maxOutputChannels": 0,
                "defaultSampleRate": 48000.0,
                "isLoopbackDevice": True,
            },
            {
                "index": 2,
                "name": "Microphone Array",
                "hostApi": 0,
                "maxInputChannels": 1,
                "maxOutputChannels": 0,
                "defaultSampleRate": 48000.0,
            },
            {
                "index": 3,
                "name": "HDMI Output",
                "hostApi": 0,
                "maxInputChannels": 0,
                "maxOutputChannels": 2,
                "defaultSampleRate": 48000.0,
            },
        ]

    def get_device_count(self) -> int:
        return len(self.devices)

    def get_device_info_by_index(self, index: int):
        return self.devices[index]

    def get_loopback_device_info_generator(self):
        # Returning a copy checks that generator metadata is merged safely.
        yield dict(self.devices[1])

    def get_host_api_info_by_index(self, index: int):
        assert index == 0
        return {"name": "Windows WASAPI"}

    def get_host_api_info_by_type(self, host_type: int):
        assert host_type == 13
        return {"defaultOutputDevice": 0}

    def get_default_wasapi_loopback(self):
        return self.devices[1]

    def get_default_input_device_info(self):
        return self.devices[2]

    def terminate(self) -> None:
        self.terminated = True


class FakeModule:
    paWASAPI = 13

    def __init__(self, audio: FakePyAudio | None = None) -> None:
        self.audio = audio or FakePyAudio()

    def PyAudio(self) -> FakePyAudio:
        return self.audio


def device(
    device_id: str,
    name: str,
    *,
    loopback: bool = False,
    host_api: str = "Windows WASAPI",
) -> AudioDeviceInfo:
    return AudioDeviceInfo(
        device_id=device_id,
        name=name,
        host_api=host_api,
        is_loopback=loopback,
        max_input_channels=2 if loopback else 0,
        max_output_channels=0 if loopback else 2,
        default_sample_rate=48_000,
    )


def test_models_are_json_safe() -> None:
    output = device("pa:0", "Speakers")
    loopback = device("pa:1", "Speakers (Loopback)", loopback=True)
    frame = AudioFrame(b"\x00\x00", sample_rate=16_000, channels=1)
    catalog = DeviceCatalog(
        outputs=[output],
        loopbacks=[loopback],
        output_loopback_pairs={"pa:0": "pa:1"},
        warnings=["test warning"],
    )

    json.dumps(output.to_dict())
    json.dumps(frame.to_dict())
    decoded = json.loads(catalog.to_json())

    assert output.portaudio_index == 0
    assert loopback.source_kind == "system"
    assert frame.pcm == b"\x00\x00"
    assert decoded["output_loopback_pairs"] == {"pa:0": "pa:1"}


def test_provider_lists_classifies_defaults_and_pairs_devices() -> None:
    module = FakeModule()
    provider = PyAudioWPatchDeviceProvider(module)

    catalog = provider.list_devices()

    assert [item.device_id for item in catalog.outputs] == ["pa:0", "pa:3"]
    assert [item.device_id for item in catalog.loopbacks] == ["pa:1"]
    assert [item.device_id for item in catalog.microphones] == ["pa:2"]
    assert catalog.default_output_id == "pa:0"
    assert catalog.default_loopback_id == "pa:1"
    assert catalog.default_microphone_id == "pa:2"
    assert catalog.output_loopback_pairs == {"pa:0": "pa:1"}
    assert catalog.find("pa:1") is not None
    assert catalog.find("pa:404") is None
    assert catalog.warnings == []
    assert module.audio.terminated is True


def test_name_matching_is_one_to_one_and_conservative() -> None:
    outputs = [device("pa:0", "Headphones")]
    ambiguous_loopbacks = [
        device("pa:1", "Headphones (Loopback)", loopback=True),
        device("pa:2", "Headphones [Loopback]", loopback=True),
    ]

    assert pair_output_loopback(outputs, ambiguous_loopbacks) == {}
    assert pair_output_loopback(
        outputs,
        ambiguous_loopbacks,
        default_output_id="pa:0",
        default_loopback_id="pa:2",
    ) == {"pa:0": "pa:2"}


def test_host_api_mismatch_is_not_guessed() -> None:
    outputs = [device("pa:0", "Speakers", host_api="MME")]
    loopbacks = [
        device("pa:1", "Speakers (Loopback)", loopback=True, host_api="Windows WASAPI")
    ]
    assert pair_output_loopback(outputs, loopbacks) == {}


def test_provider_returns_warning_instead_of_raising() -> None:
    class BrokenModule:
        @staticmethod
        def PyAudio():
            raise OSError("PortAudio unavailable")

    catalog = PyAudioWPatchDeviceProvider(BrokenModule()).list_devices()

    assert catalog.outputs == []
    assert catalog.loopbacks == []
    assert any("OSError" in warning for warning in catalog.warnings)
    assert all("PortAudio unavailable" not in warning for warning in catalog.warnings)


def test_one_bad_device_does_not_abort_other_devices() -> None:
    class PartlyBrokenAudio(FakePyAudio):
        def get_device_info_by_index(self, index: int):
            if index == 3:
                raise OSError("device disappeared")
            return super().get_device_info_by_index(index)

    module = FakeModule(PartlyBrokenAudio())
    catalog = PyAudioWPatchDeviceProvider(module).list_devices()

    assert [item.device_id for item in catalog.outputs] == ["pa:0"]
    assert [item.device_id for item in catalog.microphones] == ["pa:2"]
    assert any("device 3" in warning for warning in catalog.warnings)
