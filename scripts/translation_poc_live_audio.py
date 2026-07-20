"""Drive 20 alternating SAPI utterances through the real loopback/app pipeline."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable

import requests
import websockets


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "translation-poc" / "live" / "live_audio_results.json"

JAPANESE = (
    "次のSystem Testは来週実施する予定です。",
    "SoftBankにFit & Gapの結果を共有してください。",
    "BMSとRMSのインターフェースを確認します。",
    "担当者はまだ決まっていません。",
    "詳細設計書を金曜日までに送ってください。",
    "MK119のSystem Test結果を確認してください。",
    "ONION TechnologyはDC OSの設定を確認します。",
    "確認しました。",
    "今日の会議では、Fuji ITとDetailed Designの変更点、BMSの接続条件、来週のテスト計画を順番に確認します。",
    "Data CenterのOperation Testは午後三時に開始します。",
)
ENGLISH = (
    "Please confirm the BMS interface requirements by Friday.",
    "The Detailed Design document will be shared with Fuji IT.",
    "We need to review the MK119 System Test results.",
    "The person in charge has not been decided yet.",
    "ONION Technology will check the DC OS configuration.",
    "Please send the Fit & Gap summary to SoftBank tomorrow.",
    "BMS and RMS will be checked during the Operation Test.",
    "Confirmed.",
    "During today's meeting, Fuji IT will review the Detailed Design changes, the BMS connection requirements, and next week's System Test plan.",
    "The Data Center Operation Test starts at three PM.",
)
VOICES = {"ja": "Microsoft Haruka Desktop", "en": "Microsoft Zira Desktop"}


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _http(method: str, url: str, **kwargs: Any) -> Any:
    response = requests.request(method, url, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json()


def _speak(text: str, voice: str) -> None:
    text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}'));"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$s.Rate=-1;$s.Volume=100;$s.Speak($t);$s.Dispose();"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
        timeout=45,
    )


def _process_snapshot(pid: int) -> dict[str, Any]:
    command = (
        f"$p=Get-Process -Id {int(pid)} -ErrorAction Stop;"
        "[pscustomobject]@{Pid=$p.Id;WorkingSetBytes=[int64]$p.WorkingSet64;"
        "PrivateBytes=[int64]$p.PrivateMemorySize64;"
        "CpuSeconds=[double]$p.TotalProcessorTime.TotalSeconds}|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=15,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    payload["sampled_epoch_ms"] = round(time.time() * 1000, 3)
    return payload


class EventCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.condition = asyncio.Condition()

    async def receive(self, websocket: Any) -> None:
        async for raw in websocket:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event["_received_epoch_ms"] = round(time.time() * 1000, 3)
            async with self.condition:
                self.events.append(event)
                self.condition.notify_all()

    async def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        start_index: int,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        cursor = start_index
        async with self.condition:
            while True:
                while cursor < len(self.events):
                    event = self.events[cursor]
                    cursor += 1
                    if predicate(event):
                        return event
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for WebSocket event")
                await asyncio.wait_for(self.condition.wait(), timeout=remaining)


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    p95_index = round((len(ordered) - 1) * 0.95)
    return {
        "min": round(ordered[0], 3),
        "median": round(median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(ordered[-1], 3),
    }


def _main_cpu(samples: list[dict[str, Any]]) -> dict[str, float] | None:
    if len(samples) < 2:
        return None
    percentages: list[float] = []
    logical = max(1, os.cpu_count() or 1)
    for previous, current in zip(samples, samples[1:]):
        wall = (current["sampled_epoch_ms"] - previous["sampled_epoch_ms"]) / 1000
        cpu = current["CpuSeconds"] - previous["CpuSeconds"]
        if wall > 0 and cpu >= 0:
            percentages.append(cpu / wall / logical * 100)
    return _summary(percentages)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/live"
    devices = await asyncio.to_thread(_http, "GET", f"{base_url}/api/audio/devices")
    device_id = args.device_id or devices.get("default_loopback_id")
    if not device_id:
        raise RuntimeError("No default WASAPI loopback device is available")

    utterances: list[tuple[str, str]] = []
    for japanese, english in zip(JAPANESE, ENGLISH, strict=True):
        utterances.extend((("ja", japanese), ("en", english)))

    collector = EventCollector()
    speech_records: list[dict[str, Any]] = []
    process_samples: list[dict[str, Any]] = []
    queue_samples: list[dict[str, Any]] = []
    capture_start: dict[str, Any] | None = None
    capture_stop: dict[str, Any] | None = None
    sampler_stop = asyncio.Event()

    async with websockets.connect(ws_url, max_size=2**20, ping_interval=20) as websocket:
        receiver = asyncio.create_task(collector.receive(websocket))

        async def sample_queue() -> None:
            while not sampler_stop.is_set():
                try:
                    snapshot = await asyncio.to_thread(
                        _http, "GET", f"{base_url}/api/poc/metrics"
                    )
                    queue_samples.append(
                        {
                            "epoch_ms": round(time.time() * 1000, 3),
                            "queue_size": snapshot.get("queue", {}).get("queue_size", 0),
                            "worker_pid": snapshot.get("worker_pid"),
                            "completed_translations": len(snapshot.get("translation_metrics", [])),
                        }
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.25)

        sampler = asyncio.create_task(sample_queue())
        try:
            await asyncio.to_thread(
                _http,
                "POST",
                f"{base_url}/api/translation/settings",
                json={"provider": "local" if args.mode == "local" else "none"},
            )
            capture_start = await asyncio.to_thread(
                _http,
                "POST",
                f"{base_url}/api/capture/start",
                json={"source": "system", "device_id": device_id, "model": args.whisper_model},
            )
            session_id = str(capture_start["session_id"])
            metrics = await asyncio.to_thread(_http, "GET", f"{base_url}/api/poc/metrics")
            server_pid = int(metrics["server_pid"])
            process_samples.append(await asyncio.to_thread(_process_snapshot, server_pid))
            await asyncio.sleep(1.5)

            for index, (language, source_text) in enumerate(utterances, start=1):
                speech_started_epoch_ms = round(time.time() * 1000, 3)
                speech_started_at = _iso_now()
                await asyncio.to_thread(_speak, source_text, VOICES[language])
                speech_ended_epoch_ms = round(time.time() * 1000, 3)
                speech_records.append(
                    {
                        "index": index,
                        "planned_language": language,
                        "planned_text": source_text,
                        "voice": VOICES[language],
                        "speech_started_at": speech_started_at,
                        "speech_ended_at": _iso_now(),
                        "speech_started_epoch_ms": speech_started_epoch_ms,
                        "speech_ended_epoch_ms": speech_ended_epoch_ms,
                    }
                )
                print(f"[{index:02d}/20] played {language}", flush=True)
                await asyncio.sleep(args.silence_seconds)
                if index == 10:
                    process_samples.append(
                        await asyncio.to_thread(_process_snapshot, server_pid)
                    )

            # Stop flushes the last VAD buffer.  Translation draining must happen
            # afterwards because the final segment can be created by this call.
            capture_stop = await asyncio.to_thread(
                _http, "POST", f"{base_url}/api/capture/stop"
            )
            deadline = asyncio.get_running_loop().time() + args.drain_timeout
            while True:
                finals = [
                    event
                    for event in collector.events
                    if event.get("type") == "final_transcript"
                    and str(event.get("session_id", "")) == session_id
                ]
                final_ids = {str(event.get("segment_id", "")) for event in finals}
                translations = [
                    event
                    for event in collector.events
                    if event.get("type") == "translation"
                    and str(event.get("segment_id", "")) in final_ids
                ]
                complete = len(finals) >= 20 and (
                    args.mode == "off" or len(translations) >= len(finals)
                )
                if complete or asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.2)

            await asyncio.sleep(0.5)
            poc_metrics = await asyncio.to_thread(_http, "GET", f"{base_url}/api/poc/metrics")
            process_samples.append(await asyncio.to_thread(_process_snapshot, server_pid))
        finally:
            if capture_start is not None and capture_stop is None:
                try:
                    capture_stop = await asyncio.to_thread(
                        _http, "POST", f"{base_url}/api/capture/stop"
                    )
                except Exception:
                    pass
            sampler_stop.set()
            await asyncio.gather(sampler, return_exceptions=True)
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)

    session_id = str(capture_start.get("session_id", "")) if capture_start else ""
    finals = [
        event
        for event in collector.events
        if event.get("type") == "final_transcript"
        and str(event.get("session_id", "")) == session_id
    ]
    pending_by_id = {
        str(event.get("segment_id", "")): event
        for event in collector.events
        if event.get("type") == "translation_pending"
    }
    translations_by_id = {
        str(event.get("segment_id", "")): event
        for event in collector.events
        if event.get("type") == "translation"
    }
    provider_metrics_by_id = {
        str(item.get("segment_id", "")): item
        for item in poc_metrics.get("translation_metrics", [])
    }
    display_by_id = poc_metrics.get("browser_display", {})
    results: list[dict[str, Any]] = []
    for speech, final_event in zip(speech_records, finals, strict=False):
        segment_id = str(final_event.get("segment_id", ""))
        pending = pending_by_id.get(segment_id)
        translation = translations_by_id.get(segment_id)
        browser_display = display_by_id.get(segment_id)
        speech_end = float(speech["speech_ended_epoch_ms"])
        final_ms = float(final_event["_received_epoch_ms"])
        pending_ms = float(pending["_received_epoch_ms"]) if pending else None
        translation_ms = float(translation["_received_epoch_ms"]) if translation else None
        display_ms = (
            float(browser_display["translation"]["browser_epoch_ms"])
            if browser_display and browser_display.get("translation")
            else None
        )
        results.append(
            {
                **speech,
                "segment_id": segment_id,
                "final_text": final_event.get("text"),
                "detected_language": final_event.get("language"),
                "language_probability": final_event.get("language_probability"),
                "whisper_inference_seconds": final_event.get("inference_seconds"),
                "translation": translation.get("translated_text") if translation else None,
                "audio_end_to_final_ms": round(final_ms - speech_end, 3),
                "final_to_queue_ms": (
                    round(pending_ms - final_ms, 3) if pending_ms is not None else None
                ),
                "queue_to_translation_ms": (
                    round(translation_ms - pending_ms, 3)
                    if translation_ms is not None and pending_ms is not None
                    else None
                ),
                "audio_end_to_translation_event_ms": (
                    round(translation_ms - speech_end, 3) if translation_ms is not None else None
                ),
                "browser_display": browser_display,
                "browser_display_epoch_ms": display_ms,
                "audio_end_to_browser_display_ms": (
                    round(display_ms - speech_end, 3) if display_ms is not None else None
                ),
                "worker_metric": provider_metrics_by_id.get(segment_id),
            }
        )

    final_latencies = [float(item["audio_end_to_final_ms"]) for item in results]
    translation_latencies = [
        float(item["audio_end_to_translation_event_ms"])
        for item in results
        if item.get("audio_end_to_translation_event_ms") is not None
    ]
    queue_latencies = [
        float(item["queue_to_translation_ms"])
        for item in results
        if item.get("queue_to_translation_ms") is not None
    ]
    display_latencies = [
        float(item["audio_end_to_browser_display_ms"])
        for item in results
        if item.get("audio_end_to_browser_display_ms") is not None
    ]
    worker_rss = [
        int(item["worker_metric"]["process_rss_bytes"])
        for item in results
        if item.get("worker_metric") and item["worker_metric"].get("process_rss_bytes")
    ]
    server_working_set = [int(item["WorkingSetBytes"]) for item in process_samples]
    translation_count = sum(item.get("translation") is not None for item in results)
    browser_count = sum(item.get("browser_display_epoch_ms") is not None for item in results)
    passed = len(finals) == 20 and (
        args.mode == "off" or (translation_count == 20 and browser_count == 20)
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "mode": args.mode,
        "started_at": process_samples[0].get("sampled_epoch_ms") if process_samples else None,
        "completed_at": _iso_now(),
        "base_url": base_url,
        "device_id": device_id,
        "whisper_model": args.whisper_model,
        "voices": VOICES,
        "requested_utterances": 20,
        "played_utterances": len(speech_records),
        "final_utterances": len(finals),
        "translated_utterances": translation_count,
        "browser_displayed_translations": browser_count,
        "mapping_policy": "TTS playback order matched to serial final_transcript order",
        "errors": [],
        "capture_start": capture_start,
        "capture_stop": capture_stop,
        "latency_summary_ms": {
            "audio_end_to_final": _summary(final_latencies),
            "final_to_queue": _summary(
                [float(item["final_to_queue_ms"]) for item in results if item.get("final_to_queue_ms") is not None]
            ),
            "queue_to_translation": _summary(queue_latencies),
            "audio_end_to_translation_event": _summary(translation_latencies),
            "audio_end_to_browser_display": _summary(display_latencies),
        },
        "resources": {
            "server_cpu_percent_normalized": _main_cpu(process_samples),
            "server_working_set_bytes": {
                "start": server_working_set[0] if server_working_set else None,
                "end": server_working_set[-1] if server_working_set else None,
                "peak": max(server_working_set) if server_working_set else None,
            },
            "worker_rss_bytes": {
                "start": worker_rss[0] if worker_rss else None,
                "end": worker_rss[-1] if worker_rss else None,
                "peak": max(worker_rss) if worker_rss else None,
            },
            "process_samples": process_samples,
        },
        "queue": {
            "samples": queue_samples,
            "max_size": max((int(item["queue_size"]) for item in queue_samples), default=0),
            "end_size": queue_samples[-1]["queue_size"] if queue_samples else None,
        },
        "results": results,
        "relevant_websocket_events": [
            event
            for event in collector.events
            if event.get("type")
            in {
                "final_transcript",
                "translation_pending",
                "translation_status",
                "translation",
                "translation_error",
                "error",
            }
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real loopback + Whisper + local translation PoC")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--whisper-model", choices=("tiny", "base", "small", "medium"), default="small")
    parser.add_argument("--mode", choices=("local", "off"), default="local")
    parser.add_argument("--silence-seconds", type=float, default=1.1)
    parser.add_argument("--drain-timeout", type=float, default=240.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = asyncio.run(_run(args))
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
