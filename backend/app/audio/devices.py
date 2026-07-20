"""PyAudioWPatch device discovery behind a dependency-free boundary."""

from __future__ import annotations

import importlib
import re
from collections import defaultdict
from dataclasses import replace
from types import ModuleType
from typing import Any, Mapping, Sequence

from .models import AudioDeviceInfo, DeviceCatalog


_WHITESPACE = re.compile(r"\s+")
_LOOPBACK_MARKER = re.compile(
    r"(?:\[|\(|-|\s)*(?:wasapi\s+)?(?:loopback|loop\s*back|루프백)(?:\]|\))?",
    flags=re.IGNORECASE,
)
_SEPARATOR = re.compile(r"[\s\-_:\[\](){}]+")


def _canonical_device_name(name: str) -> str:
    without_marker = _LOOPBACK_MARKER.sub(" ", name.casefold())
    return _SEPARATOR.sub(" ", without_marker).strip()


def _compatible_host_api(output: AudioDeviceInfo, loopback: AudioDeviceInfo) -> bool:
    output_api = _WHITESPACE.sub(" ", output.host_api.casefold()).strip()
    loopback_api = _WHITESPACE.sub(" ", loopback.host_api.casefold()).strip()
    unknown = {"", "unknown"}
    return output_api in unknown or loopback_api in unknown or output_api == loopback_api


def pair_output_loopback(
    outputs: Sequence[AudioDeviceInfo],
    loopbacks: Sequence[AudioDeviceInfo],
    *,
    default_output_id: str | None = None,
    default_loopback_id: str | None = None,
) -> dict[str, str]:
    """Conservatively map output IDs to their corresponding loopback IDs.

    A pair is accepted when PyAudioWPatch explicitly identifies both defaults,
    or when normalized names form a unique one-to-one match on a compatible
    host API.  Ambiguous names are deliberately left unmatched.
    """

    pairs: dict[str, str] = {}
    used_loopbacks: set[str] = set()

    output_ids = {device.device_id for device in outputs}
    loopback_ids = {device.device_id for device in loopbacks}
    if (
        default_output_id in output_ids
        and default_loopback_id in loopback_ids
        and default_output_id is not None
        and default_loopback_id is not None
    ):
        pairs[default_output_id] = default_loopback_id
        used_loopbacks.add(default_loopback_id)

    candidates: dict[str, list[str]] = {}
    reverse_candidates: dict[str, list[str]] = defaultdict(list)
    for output in outputs:
        if output.device_id in pairs:
            continue
        output_name = _canonical_device_name(output.name)
        if not output_name:
            continue
        matches = [
            loopback.device_id
            for loopback in loopbacks
            if loopback.device_id not in used_loopbacks
            and _compatible_host_api(output, loopback)
            and _canonical_device_name(loopback.name) == output_name
        ]
        candidates[output.device_id] = matches
        for loopback_id in matches:
            reverse_candidates[loopback_id].append(output.device_id)

    for output_id, matches in candidates.items():
        if len(matches) != 1:
            continue
        loopback_id = matches[0]
        if len(reverse_candidates[loopback_id]) == 1:
            pairs[output_id] = loopback_id
            used_loopbacks.add(loopback_id)

    return pairs


def _format_warning(action: str, error: BaseException) -> str:
    # Native driver errors can contain user paths, device metadata, or values
    # copied from environment variables. Expose only the action and class.
    return f"{action}: {type(error).__name__}"


def _index_from_info(info: Mapping[str, Any] | None) -> int | None:
    if not info:
        return None
    try:
        index = int(info["index"])
    except (KeyError, TypeError, ValueError):
        return None
    return index if index >= 0 else None


class PyAudioWPatchDeviceProvider:
    """Enumerate Windows devices without importing PyAudioWPatch at import time."""

    def __init__(self, pyaudio_module: ModuleType | Any | None = None) -> None:
        self._module = pyaudio_module
        self._catalog: DeviceCatalog | None = None

    @property
    def last_catalog(self) -> DeviceCatalog | None:
        return self._catalog

    def _load_module(self) -> ModuleType | Any:
        if self._module is None:
            self._module = importlib.import_module("pyaudiowpatch")
        return self._module

    def refresh(self) -> DeviceCatalog:
        return self.list_devices()

    def get_device(self, device_id: str, *, refresh: bool = False) -> AudioDeviceInfo | None:
        catalog = self.list_devices() if refresh or self._catalog is None else self._catalog
        return catalog.find(device_id)

    def list_devices(self) -> DeviceCatalog:
        warnings: list[str] = []
        try:
            module = self._load_module()
        except (ImportError, OSError) as error:
            catalog = DeviceCatalog(
                warnings=[_format_warning("PyAudioWPatch is unavailable", error)]
            )
            self._catalog = catalog
            return catalog

        audio: Any | None = None
        catalog = DeviceCatalog(warnings=warnings)
        try:
            audio = module.PyAudio()
            raw_devices = self._enumerate_raw_devices(audio, warnings)
            if raw_devices is None:
                self._catalog = catalog
                return catalog

            loopback_indices = self._merge_loopback_devices(audio, raw_devices, warnings)
            default_output_index, default_loopback_index, default_input_index = (
                self._find_default_indices(module, audio, warnings)
            )

            host_names: dict[int, str] = {}
            outputs: list[AudioDeviceInfo] = []
            loopbacks: list[AudioDeviceInfo] = []
            microphones: list[AudioDeviceInfo] = []
            for index in sorted(raw_devices):
                raw = raw_devices[index]
                is_loopback = bool(raw.get("isLoopbackDevice", False)) or (
                    index in loopback_indices
                )
                device = self._make_device(audio, raw, index, is_loopback, host_names, warnings)
                if device is None:
                    continue
                if is_loopback:
                    loopbacks.append(device)
                else:
                    if device.max_output_channels > 0:
                        outputs.append(device)
                    if device.max_input_channels > 0:
                        microphones.append(device)

            default_output_id = self._existing_id(outputs, default_output_index)
            default_loopback_id = self._existing_id(loopbacks, default_loopback_index)
            default_microphone_id = self._existing_id(microphones, default_input_index)

            pairs = pair_output_loopback(
                outputs,
                loopbacks,
                default_output_id=default_output_id,
                default_loopback_id=default_loopback_id,
            )
            if default_loopback_id is None and default_output_id is not None:
                default_loopback_id = pairs.get(default_output_id)

            outputs = self._mark_default(outputs, default_output_id)
            loopbacks = self._mark_default(loopbacks, default_loopback_id)
            microphones = self._mark_default(microphones, default_microphone_id)

            if outputs and not loopbacks:
                warnings.append(
                    "No WASAPI loopback devices were found; system audio capture is unavailable."
                )

            catalog = DeviceCatalog(
                outputs=outputs,
                loopbacks=loopbacks,
                microphones=microphones,
                default_output_id=default_output_id,
                default_loopback_id=default_loopback_id,
                default_microphone_id=default_microphone_id,
                output_loopback_pairs=pairs,
                warnings=warnings,
            )
        except Exception as error:  # PortAudio backends expose several exception types.
            warnings.append(_format_warning("Audio device discovery failed", error))
            catalog = DeviceCatalog(warnings=warnings)
        finally:
            if audio is not None:
                try:
                    audio.terminate()
                except Exception as error:
                    warnings.append(_format_warning("PyAudio termination failed", error))

        self._catalog = catalog
        return catalog

    @staticmethod
    def _enumerate_raw_devices(
        audio: Any, warnings: list[str]
    ) -> dict[int, dict[str, Any]] | None:
        try:
            count = int(audio.get_device_count())
        except Exception as error:
            warnings.append(_format_warning("Could not read the audio device count", error))
            return None

        devices: dict[int, dict[str, Any]] = {}
        for index in range(max(0, count)):
            try:
                raw = dict(audio.get_device_info_by_index(index))
                raw.setdefault("index", index)
                devices[index] = raw
            except Exception as error:
                warnings.append(
                    _format_warning(f"Could not inspect PortAudio device {index}", error)
                )
        return devices

    @staticmethod
    def _merge_loopback_devices(
        audio: Any,
        raw_devices: dict[int, dict[str, Any]],
        warnings: list[str],
    ) -> set[int]:
        indices = {
            index
            for index, info in raw_devices.items()
            if bool(info.get("isLoopbackDevice", False))
        }
        generator = getattr(audio, "get_loopback_device_info_generator", None)
        if generator is None:
            return indices
        try:
            for generated in generator():
                info = dict(generated)
                index = _index_from_info(info)
                if index is None:
                    warnings.append("Ignored a loopback device without a valid PortAudio index.")
                    continue
                merged = dict(raw_devices.get(index, {}))
                merged.update(info)
                merged["index"] = index
                merged["isLoopbackDevice"] = True
                raw_devices[index] = merged
                indices.add(index)
        except Exception as error:
            warnings.append(_format_warning("Could not enumerate loopback devices", error))
        return indices

    @staticmethod
    def _find_default_indices(
        module: Any, audio: Any, warnings: list[str]
    ) -> tuple[int | None, int | None, int | None]:
        output_index: int | None = None
        wasapi_type = getattr(module, "paWASAPI", None)
        get_api_by_type = getattr(audio, "get_host_api_info_by_type", None)
        if wasapi_type is not None and get_api_by_type is not None:
            try:
                wasapi = dict(get_api_by_type(wasapi_type))
                value = int(wasapi.get("defaultOutputDevice", -1))
                output_index = value if value >= 0 else None
            except Exception as error:
                warnings.append(_format_warning("Could not identify the default WASAPI output", error))

        if output_index is None:
            output_index = PyAudioWPatchDeviceProvider._default_device_index(
                audio, "get_default_output_device_info", "default output", warnings
            )

        loopback_index = PyAudioWPatchDeviceProvider._default_device_index(
            audio, "get_default_wasapi_loopback", "default WASAPI loopback", warnings
        )
        input_index = PyAudioWPatchDeviceProvider._default_device_index(
            audio, "get_default_input_device_info", "default input", warnings
        )
        return output_index, loopback_index, input_index

    @staticmethod
    def _default_device_index(
        audio: Any, method_name: str, label: str, warnings: list[str]
    ) -> int | None:
        method = getattr(audio, method_name, None)
        if method is None:
            return None
        try:
            return _index_from_info(method())
        except Exception as error:
            warnings.append(_format_warning(f"Could not identify the {label}", error))
            return None

    @staticmethod
    def _make_device(
        audio: Any,
        raw: Mapping[str, Any],
        index: int,
        is_loopback: bool,
        host_names: dict[int, str],
        warnings: list[str],
    ) -> AudioDeviceInfo | None:
        try:
            host_index = int(raw.get("hostApi", -1))
            if host_index not in host_names:
                if host_index < 0:
                    host_names[host_index] = str(raw.get("hostApiName", "Unknown"))
                else:
                    try:
                        host_info = audio.get_host_api_info_by_index(host_index)
                        host_names[host_index] = str(host_info.get("name", f"Host API {host_index}"))
                    except Exception as error:
                        warnings.append(
                            _format_warning(
                                f"Could not inspect host API {host_index} for device {index}", error
                            )
                        )
                        host_names[host_index] = f"Host API {host_index}"

            return AudioDeviceInfo(
                device_id=f"pa:{index}",
                name=str(raw.get("name") or f"PortAudio device {index}"),
                host_api=host_names[host_index],
                is_loopback=is_loopback,
                max_input_channels=max(0, int(raw.get("maxInputChannels", 0))),
                max_output_channels=max(0, int(raw.get("maxOutputChannels", 0))),
                default_sample_rate=max(0.0, float(raw.get("defaultSampleRate", 0.0))),
            )
        except (TypeError, ValueError) as error:
            warnings.append(_format_warning(f"Ignored malformed PortAudio device {index}", error))
            return None

    @staticmethod
    def _existing_id(devices: Sequence[AudioDeviceInfo], index: int | None) -> str | None:
        if index is None:
            return None
        device_id = f"pa:{index}"
        return device_id if any(device.device_id == device_id for device in devices) else None

    @staticmethod
    def _mark_default(
        devices: Sequence[AudioDeviceInfo], default_id: str | None
    ) -> list[AudioDeviceInfo]:
        return [
            replace(device, is_default=(device.device_id == default_id))
            for device in devices
        ]
