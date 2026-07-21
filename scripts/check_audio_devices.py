"""Inspect Windows audio devices through the application's audio boundary.

This diagnostic does not change Windows audio settings and does not open a
capture stream.  Run it from the project root with the project virtualenv::

    .venv\Scripts\python.exe scripts\check_audio_devices.py
    .venv\Scripts\python.exe scripts\check_audio_devices.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.audio.models import AudioDeviceInfo, DeviceCatalog  # noqa: E402
from backend.app.audio.devices import PyAudioWPatchDeviceProvider  # noqa: E402


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List output, WASAPI loopback, and microphone devices without changing settings."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="write the same catalog as UTF-8 JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a failure code unless at least one loopback and microphone are found",
    )
    return parser


def _device_line(device: AudioDeviceInfo) -> str:
    flags: list[str] = []
    if device.is_default:
        flags.append("default")
    if device.is_loopback:
        flags.append("loopback")
    marker = f" [{' / '.join(flags)}]" if flags else ""
    sample_rate = f"{device.default_sample_rate:g} Hz" if device.default_sample_rate else "unknown rate"
    return (
        f"  - {device.device_id}: {device.name}{marker}\n"
        f"    host={device.host_api}, in={device.max_input_channels}, "
        f"out={device.max_output_channels}, rate={sample_rate}"
    )


def _print_group(title: str, devices: Iterable[AudioDeviceInfo]) -> None:
    device_list = list(devices)
    print(f"\n{title} ({len(device_list)})")
    if not device_list:
        print("  - none")
        return
    for device in device_list:
        print(_device_line(device))


def _name_for(catalog: DeviceCatalog, device_id: str | None) -> str:
    if not device_id:
        return "none"
    device = catalog.find(device_id)
    return f"{device_id} ({device.name})" if device else device_id


def _print_catalog(catalog: DeviceCatalog) -> None:
    print("WhyKaigi - audio device check")
    print("Read-only inspection; no device or Windows setting is changed.")
    print(f"\nDefault output:     {_name_for(catalog, catalog.default_output_id)}")
    print(f"Default loopback:   {_name_for(catalog, catalog.default_loopback_id)}")
    print(f"Default microphone: {_name_for(catalog, catalog.default_microphone_id)}")

    _print_group("Audio outputs", catalog.outputs)
    _print_group("WASAPI loopbacks", catalog.loopbacks)
    _print_group("Microphone inputs", catalog.microphones)

    print(f"\nOutput -> loopback pairs ({len(catalog.output_loopback_pairs)})")
    if catalog.output_loopback_pairs:
        for output_id, loopback_id in catalog.output_loopback_pairs.items():
            print(f"  - {_name_for(catalog, output_id)}")
            print(f"    -> {_name_for(catalog, loopback_id)}")
    else:
        print("  - none")

    if catalog.warnings:
        print(f"\nWarnings ({len(catalog.warnings)})")
        for warning in catalog.warnings:
            print(f"  - {warning}")


def main() -> int:
    _configure_console()
    args = _parser().parse_args()

    if importlib.util.find_spec("pyaudiowpatch") is None:
        print(
            "ERROR: PyAudioWPatch is not installed in this Python environment.\n"
            "Run setup.bat from the project root and retry.",
            file=sys.stderr,
        )
        return 2

    try:
        catalog = PyAudioWPatchDeviceProvider().list_devices()
    except Exception as error:  # The diagnostic must turn backend-specific failures into a readable result.
        print(
            f"ERROR: audio device inspection failed ({type(error).__name__}).\n"
            "No Windows setting was changed. See the server log for additional diagnostics.",
            file=sys.stderr,
        )
        return 3

    if args.json:
        print(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_catalog(catalog)

    any_device = bool(catalog.outputs or catalog.loopbacks or catalog.microphones)
    if not any_device:
        if not args.json:
            print("\nERROR: PortAudio returned no usable audio devices.", file=sys.stderr)
        return 3

    if args.strict and (not catalog.loopbacks or not catalog.microphones):
        if not args.json:
            print(
                "\nERROR: strict check requires both a loopback and a microphone device.",
                file=sys.stderr,
            )
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
