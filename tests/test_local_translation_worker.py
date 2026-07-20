from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from backend.app.translation import (
    LocalTranslationWorkerSupervisor,
    SidecarLocalTranslationProvider,
    TranslationErrorCode,
    TranslationProviderError,
    TranslationRequest,
)


FAKE_WORKER = r'''
import json
import os
import sys
import time

PROTOCOL = "mlt.translation-worker.v1"
print(json.dumps({
    "type": "starting",
    "protocol": PROTOCOL,
    "pid": os.getpid(),
}), flush=True)
print(json.dumps({
    "type": "ready",
    "protocol": PROTOCOL,
    "pid": os.getpid(),
    "model": "fake-model",
    "model_revision": "fake-revision",
    "device": "cpu",
    "compute_type": "int8",
    "inter_threads": 1,
    "intra_threads": 2,
    "translation_concurrency": 1,
    "beam_size": 1,
    "process_priority": "below_normal",
    "cold_start_ms": 1.0,
}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    command = request.get("command")
    if command == "shutdown":
        print(json.dumps({
            "type": "shutdown", "protocol": PROTOCOL,
            "id": request.get("id"), "pid": os.getpid(),
        }), flush=True)
        raise SystemExit(0)
    if command == "translate":
        time.sleep(0.03)
        print(json.dumps({
            "type": "translation", "protocol": PROTOCOL,
            "id": request.get("id"), "translation": "테스트 번역",
            "latency_ms": 30, "process_rss_bytes": 1,
            "process_cpu_percent": 0,
        }), flush=True)
'''


def _supervisor(tmp_path: Path) -> LocalTranslationWorkerSupervisor:
    model = tmp_path / "fake-model"
    model.mkdir()
    for name in (
        "model.bin",
        "config.json",
        "shared_vocabulary.json",
        "sentencepiece.bpe.model",
        "vocab.json",
    ):
        (model / name).write_bytes(b"test")
    worker = tmp_path / "local_translation_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    return LocalTranslationWorkerSupervisor(
        project_root=tmp_path,
        runtime_python=Path(sys.executable),
        worker_script=worker,
        model_path=model,
        pid_file=tmp_path / ".run" / "translation-worker.pid",
        stderr_path=tmp_path / ".run" / "translation-worker.stderr.log",
        startup_timeout_seconds=5,
        request_timeout_seconds=2,
        recovery_wait_seconds=4,
    )


def test_worker_preloads_translates_recovers_and_cleans_pid(tmp_path: Path) -> None:
    async def scenario() -> None:
        supervisor = _supervisor(tmp_path)
        assert await supervisor.start()
        first = supervisor.snapshot()
        assert first["state"] == "ready"
        assert first["available"] is True
        assert first["translation_concurrency"] == 1
        assert first["inter_threads"] == 1
        assert first["intra_threads"] == 2
        assert first["beam_size"] == 1
        assert first["pid"]
        assert (tmp_path / ".run" / "translation-worker.pid").read_text() == str(
            first["pid"]
        )

        provider = SidecarLocalTranslationProvider(supervisor)
        with pytest.raises(TranslationProviderError) as unsupported:
            await provider.translate(
                TranslationRequest(
                    segment_id="unsupported-target",
                    source_text="hello",
                    source_language="en",
                    target_language="en",
                )
            )
        assert unsupported.value.code is TranslationErrorCode.UNSUPPORTED_LANGUAGE
        result = await provider.translate(
            TranslationRequest(
                segment_id="segment-1",
                source_text="hello",
                source_language="en",
            )
        )
        assert result.translated_text == "테스트 번역"

        await provider.close()
        assert supervisor.snapshot()["available"] is True
        replacement = SidecarLocalTranslationProvider(supervisor)
        assert (await replacement.health_check()).available is True

        os.kill(int(first["pid"]), signal.SIGTERM)
        deadline = asyncio.get_running_loop().time() + 10
        recovered = None
        while asyncio.get_running_loop().time() < deadline:
            snapshot = supervisor.snapshot()
            if snapshot["available"] and snapshot["pid"] != first["pid"]:
                recovered = snapshot
                break
            await asyncio.sleep(0.1)
        assert recovered is not None
        assert recovered["restart_count"] >= 1

        result = await replacement.translate(
            TranslationRequest(
                segment_id="segment-2",
                source_text="こんにちは",
                source_language="ja",
            )
        )
        assert result.translated_text == "테스트 번역"
        await supervisor.stop()
        assert supervisor.snapshot()["state"] == "stopped"
        assert not (tmp_path / ".run" / "translation-worker.pid").exists()

    asyncio.run(scenario())


def test_worker_snapshot_never_exposes_configured_paths(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    payload = str(supervisor.snapshot())
    assert str(tmp_path) not in payload
    assert "local_translation_worker.py" not in payload
