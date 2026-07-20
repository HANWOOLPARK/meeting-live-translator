"""PoC-only subprocess provider for an isolated M2M100 runtime."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import threading
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.app.translation import (
    ProviderHealth,
    TranslationErrorCode,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
    translation_error,
)


REQUIRED_MODEL_FILES = (
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "sentencepiece.bpe.model",
    "vocab.json",
)
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


class TranslationWorkerClient:
    def __init__(
        self,
        *,
        runtime_python: Path,
        worker_script: Path,
        model_path: Path,
        stderr_path: Path,
    ) -> None:
        self.runtime_python = runtime_python
        self.worker_script = worker_script
        self.model_path = model_path
        self.stderr_path = stderr_path
        self.process: subprocess.Popen[str] | None = None
        self.stderr_handle: Any | None = None
        self.ready: dict[str, Any] | None = None
        self.shutdown_result: dict[str, Any] | None = None
        self._lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None and self.process.poll() is None else None

    def _start_unlocked(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                str(self.runtime_python),
                str(self.worker_script),
                "--model",
                str(self.model_path),
            ],
            cwd=self.worker_script.parents[1],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdout is not None
        ready_line = self.process.stdout.readline()
        if not ready_line:
            raise RuntimeError(f"Translation worker exited before ready ({self.process.poll()})")
        self.ready = json.loads(ready_line)
        if self.ready.get("type") != "ready":
            raise RuntimeError(f"Translation worker startup failed: {self.ready}")

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._start_unlocked()
            assert self.process is not None
            assert self.process.stdin is not None
            assert self.process.stdout is not None
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("Translation worker returned no response")
            response = json.loads(line)
            if response.get("type") == "error":
                raise RuntimeError(
                    f"{response.get('error_type', 'WorkerError')}: {response.get('message', '')}"
                )
            return response

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        glossary_terms: tuple[str, ...],
    ) -> dict[str, Any]:
        return self.request(
            {
                "command": "translate",
                "id": str(uuid4()),
                "text": text,
                "source_language": source_language,
                "glossary_terms": list(glossary_terms),
            }
        )

    def close(self) -> dict[str, Any]:
        with self._lock:
            process = self.process
            result: dict[str, Any] = {
                "pid": process.pid if process is not None else None,
                "shutdown_response": None,
                "exit_code": process.returncode if process is not None else None,
                "alive_after_shutdown": False,
            }
            try:
                if process is not None and process.poll() is None:
                    assert process.stdin is not None
                    assert process.stdout is not None
                    request_id = str(uuid4())
                    process.stdin.write(
                        json.dumps({"command": "shutdown", "id": request_id}) + "\n"
                    )
                    process.stdin.flush()
                    line = process.stdout.readline()
                    if line:
                        result["shutdown_response"] = json.loads(line)
                    process.wait(timeout=15)
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if process is not None:
                    result["exit_code"] = process.returncode
                    result["alive_after_shutdown"] = process.poll() is None
                if self.stderr_handle is not None:
                    self.stderr_handle.close()
                self.stderr_handle = None
                self.process = None
                self.shutdown_result = result
            return result


class SubprocessM2M100Provider(TranslationProvider):
    provider_name = "local"
    display_name = "로컬 번역 (격리 PoC worker)"
    external = False

    def __init__(
        self,
        *,
        runtime_python: Path,
        worker_script: Path,
        model_path: Path,
        stderr_path: Path,
    ) -> None:
        self.runtime_python = runtime_python.resolve()
        self.worker_script = worker_script.resolve()
        self.model_path = model_path.resolve()
        self.client = TranslationWorkerClient(
            runtime_python=self.runtime_python,
            worker_script=self.worker_script,
            model_path=self.model_path,
            stderr_path=stderr_path.resolve(),
        )
        self.metrics: list[dict[str, Any]] = []
        self._closed = False

    def _installed(self) -> bool:
        return (
            self.runtime_python.is_file()
            and self.worker_script.is_file()
            and all((self.model_path / name).is_file() for name in REQUIRED_MODEL_FILES)
        )

    async def health_check(self) -> ProviderHealth:
        available = self._installed() and not self._closed
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=available,
            external=False,
            reason=None if available else "격리된 로컬 번역 worker 또는 모델이 준비되지 않았습니다.",
            model=self.model_path.name if self.model_path else None,
        )

    @staticmethod
    def _language(request: TranslationRequest) -> str:
        if request.source_language in {"ja", "en"}:
            return request.source_language
        if request.source_language == "mixed":
            return "ja" if _JAPANESE_RE.search(request.source_text) else "en"
        raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self._installed() or self._closed:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        language = self._language(request)
        wall_started = perf_counter()
        started_at = iso_now()
        try:
            response = await asyncio.to_thread(
                self.client.translate,
                text=request.source_text,
                source_language=language,
                glossary_terms=request.glossary_terms,
            )
        except Exception as error:
            self.metrics.append(
                {
                    "segment_id": request.segment_id,
                    "started_at": started_at,
                    "completed_at": iso_now(),
                    "error_type": type(error).__name__,
                }
            )
            raise translation_error(TranslationErrorCode.UNKNOWN_PROVIDER_ERROR) from error
        completed_at = iso_now()
        wall_ms = round((perf_counter() - wall_started) * 1000, 3)
        metric = {
            "segment_id": request.segment_id,
            "session_id": request.session_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "provider_wall_ms": wall_ms,
            **response,
        }
        self.metrics.append(metric)
        if len(self.metrics) > 250:
            del self.metrics[:-250]
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=str(response["translation"]),
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=self.model_path.name,
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=completed_at,
            latency_ms=max(0, round(wall_ms)),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self.client.close)


__all__ = ["SubprocessM2M100Provider", "TranslationWorkerClient"]
