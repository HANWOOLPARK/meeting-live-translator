"""Run the real app with an isolated PoC translation worker and data directory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config.settings import AppSettings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.services import build_services  # noqa: E402
from backend.app.translation import (  # noqa: E402
    NoneTranslationProvider,
    OpenAITranslationProvider,
)
from scripts.translation_poc_ipc import SubprocessM2M100Provider  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Meeting Live Translator isolated translation PoC")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--runtime-python",
        type=Path,
        default=PROJECT_ROOT / ".venv-translation" / "Scripts" / "python.exe",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT / "models" / "translation" / "m2m100_418m-int8",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=PROJECT_ROOT / "work" / "translation-poc" / "live",
    )
    return parser


async def _serve(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    provider = SubprocessM2M100Provider(
        runtime_python=args.runtime_python,
        worker_script=PROJECT_ROOT / "scripts" / "translation_poc_worker.py",
        model_path=args.model,
        stderr_path=work_dir / "worker.stderr.log",
    )
    settings = AppSettings(
        project_root=PROJECT_ROOT,
        host=args.host,
        port=args.port,
        default_model="small",
        selected_model="small",
        prefer_cuda=False,
        session_dir=work_dir / "sessions",
        static_dir=PROJECT_ROOT / "frontend" / "static",
        translation_provider="local",
        translation_timeout_seconds=30.0,
        translation_max_retries=0,
        translation_context_segments=0,
        translation_queue_max_size=100,
        translation_max_concurrency=1,
        translation_translate_unknown=False,
        local_translation_model=str(args.model.resolve()),
        session_save_original=True,
        session_save_translation=True,
        session_save_analysis=False,
        session_auto_recover=False,
        analysis_provider="none",
        analysis_auto_run_on_stop=False,
    )
    factories = {
        "none": NoneTranslationProvider,
        "local": lambda: provider,
        "openai": lambda: OpenAITranslationProvider(api_key=None, model="not-configured"),
    }
    services = build_services(settings, translation_provider_factories=factories)
    app = create_app(services)
    shutdown_event = asyncio.Event()
    browser_display: dict[str, dict[str, Any]] = {}

    @app.get("/api/poc/metrics")
    async def poc_metrics() -> dict[str, Any]:
        return {
            "server_pid": os.getpid(),
            "worker_pid": provider.client.pid,
            "worker_ready": provider.client.ready,
            "worker_shutdown": provider.client.shutdown_result,
            "translation_metrics": provider.metrics,
            "browser_display": browser_display,
            "queue": services.translation_manager.snapshot(),
            "session_dir": str(settings.session_dir),
        }

    @app.post("/api/poc/shutdown")
    async def poc_shutdown(_: Request) -> dict[str, Any]:
        shutdown_event.set()
        return {"status": "stopping"}

    @app.post("/api/poc/browser-display")
    async def poc_browser_display(request: Request) -> dict[str, Any]:
        payload = await request.json()
        kind = str(payload.get("kind", ""))
        segment_id = str(payload.get("segment_id", "")).strip()
        if kind not in {"final", "translation"} or not segment_id or len(segment_id) > 128:
            return {"accepted": False}
        entry = browser_display.setdefault(segment_id, {})
        if kind not in entry:
            entry[kind] = {
                "browser_epoch_ms": float(payload.get("browser_epoch_ms", 0)),
                "server_received_epoch_ms": round(__import__("time").time() * 1000, 3),
                "text": str(payload.get("text", ""))[:4_000],
            }
        return {"accepted": True}

    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    async def stop_when_requested() -> None:
        await shutdown_event.wait()
        server.should_exit = True

    watcher = asyncio.create_task(stop_when_requested())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        result = {
            "server_pid": os.getpid(),
            "worker_ready": provider.client.ready,
            "worker_shutdown": provider.client.shutdown_result,
            "translation_metrics": provider.metrics,
            "browser_display": browser_display,
            "queue": services.translation_manager.snapshot(),
        }
        (work_dir / "provider_metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if server.started else 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(_serve(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
