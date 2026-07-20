"""Isolated local-translation worker lifecycle and provider adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any, BinaryIO
from uuid import uuid4

from .base import TranslationProvider
from .exceptions import TranslationErrorCode, translation_error
from .models import (
    ProviderHealth,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)


LOGGER = logging.getLogger(__name__)
PROTOCOL = "mlt.translation-worker.v1"
REQUIRED_MODEL_FILES = (
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "sentencepiece.bpe.model",
    "vocab.json",
)
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


class LocalTranslationWorkerSupervisor:
    """Own one preloaded sidecar process and recover it after isolated failure."""

    def __init__(
        self,
        *,
        project_root: Path,
        runtime_python: Path,
        worker_script: Path,
        model_path: Path,
        pid_file: Path,
        stderr_path: Path,
        startup_timeout_seconds: float = 90.0,
        request_timeout_seconds: float = 30.0,
        recovery_wait_seconds: float = 8.0,
    ) -> None:
        self.project_root = project_root.resolve()
        self.runtime_python = runtime_python.resolve()
        self.worker_script = worker_script.resolve()
        self.model_path = model_path.resolve()
        self.pid_file = pid_file.resolve()
        self.stderr_path = stderr_path.resolve()
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.recovery_wait_seconds = float(recovery_wait_seconds)

        self._process: asyncio.subprocess.Process | None = None
        self._stderr_handle: BinaryIO | None = None
        self._actual_pid: int | None = None
        self._ready_payload: dict[str, Any] = {}
        self._last_metrics: dict[str, Any] = {}
        self._state = "stopped"
        self._last_error: str | None = None
        self._desired_running = False
        self._restart_count = 0
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        self._last_ready_at: str | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._ready_event = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None

    @property
    def model_name(self) -> str:
        return self.model_path.name

    @property
    def model_installed(self) -> bool:
        return self.model_path.is_dir() and all(
            (self.model_path / name).is_file() for name in REQUIRED_MODEL_FILES
        )

    @property
    def runtime_installed(self) -> bool:
        return self.runtime_python.is_file()

    @property
    def worker_script_installed(self) -> bool:
        return self.worker_script.is_file()

    @property
    def configured(self) -> bool:
        return (
            self.runtime_installed
            and self.worker_script_installed
            and self.model_installed
        )

    def _configuration_error(self) -> str | None:
        if not self.runtime_installed:
            return "runtime_missing"
        if not self.worker_script_installed:
            return "worker_script_missing"
        if not self.model_installed:
            return "model_missing"
        return None

    def snapshot(self) -> dict[str, Any]:
        process_alive = self._process is not None and self._process.returncode is None
        state = self._state
        if state == "ready" and not process_alive:
            state = "degraded"
        ready = state == "ready" and process_alive and self._actual_pid is not None
        payload = {
            "configured": self.configured,
            "model_installed": self.model_installed,
            "runtime_installed": self.runtime_installed,
            "state": state,
            "available": ready,
            "desired_running": self._desired_running,
            "pid": self._actual_pid if ready else None,
            "model": self.model_name,
            "model_revision": self._ready_payload.get("model_revision"),
            "device": "cpu",
            "compute_type": "int8",
            "inter_threads": 1,
            "intra_threads": 2,
            "translation_concurrency": 1,
            "beam_size": 1,
            "process_priority": self._ready_payload.get(
                "process_priority",
                "below_normal_requested",
            ),
            "cold_start_ms": self._ready_payload.get("cold_start_ms"),
            "restart_count": self._restart_count,
            "last_ready_at": self._last_ready_at,
            "last_error": self._last_error,
        }
        if self._last_metrics:
            payload["last_translation"] = dict(self._last_metrics)
        return payload

    def _write_pid_file(self, pid: int) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.pid_file.with_suffix(self.pid_file.suffix + ".tmp")
        temporary.write_text(str(pid), encoding="ascii")
        os.replace(temporary, self.pid_file)

    def _remove_owned_pid_file(self, pid: int | None) -> None:
        if pid is None:
            return
        try:
            saved = self.pid_file.read_text(encoding="ascii").strip()
            if saved == str(pid):
                self.pid_file.unlink(missing_ok=True)
        except OSError:
            return

    def _inspect_process_sync(self, pid: int) -> tuple[str, str]:
        """Return (found|missing|unknown, command line) without extra packages."""

        if pid <= 0:
            return ("missing", "")
        if os.name == "nt":
            command = (
                "$id=0; "
                "if (-not [int]::TryParse($env:MLT_INSPECT_PID,[ref]$id)) { exit 4 }; "
                "$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id) "
                "-ErrorAction SilentlyContinue; "
                "if ($null -eq $p) { exit 3 }; "
                "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                "[Console]::Write([string]$p.CommandLine)"
            )
            environment = os.environ.copy()
            environment["MLT_INSPECT_PID"] = str(pid)
            try:
                completed = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    capture_output=True,
                    check=False,
                    timeout=5.0,
                    env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                return ("unknown", "")
            if completed.returncode == 3:
                return ("missing", "")
            if completed.returncode != 0:
                return ("unknown", "")
            return ("found", completed.stdout.decode("utf-8", errors="replace"))

        proc_command = Path("/proc") / str(pid) / "cmdline"
        try:
            return (
                "found",
                proc_command.read_bytes().replace(b"\0", b" ").decode(
                    "utf-8", errors="replace"
                ),
            )
        except FileNotFoundError:
            return ("missing", "")
        except OSError:
            return ("unknown", "")

    async def _process_identity(self, pid: int) -> str:
        status, command_line = await asyncio.to_thread(self._inspect_process_sync, pid)
        if status != "found":
            return status
        normalized = command_line.casefold()
        if (
            "local_translation_worker.py" in normalized
            and str(self.project_root).casefold() in normalized
        ):
            return "owned"
        return "other"

    async def _wait_until_not_owned(self, pid: int, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            identity = await self._process_identity(pid)
            if identity in {"missing", "other"}:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.2)

    async def _terminate_owned_pid(self, pid: int, timeout: float = 7.0) -> bool:
        identity = await self._process_identity(pid)
        if identity in {"missing", "other"}:
            return True
        if identity != "owned":
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except (PermissionError, OSError):
            return False
        return await self._wait_until_not_owned(pid, timeout)

    async def _reconcile_stale_pid_file_locked(self) -> bool:
        if not self.pid_file.is_file():
            return True
        try:
            raw = self.pid_file.read_text(encoding="ascii").strip()
            pid = int(raw)
        except (OSError, ValueError):
            self.pid_file.unlink(missing_ok=True)
            return True
        if pid <= 0:
            self.pid_file.unlink(missing_ok=True)
            return True
        if self._actual_pid == pid:
            return True

        identity = await self._process_identity(pid)
        if identity in {"missing", "other"}:
            self.pid_file.unlink(missing_ok=True)
            return True
        if identity != "owned" or not await self._terminate_owned_pid(pid):
            self._state = "degraded"
            self._last_error = "stale_worker_stop_failed"
            return False
        self._remove_owned_pid_file(pid)
        return True

    def _set_unavailable_from_configuration(self) -> None:
        self._ready_event.clear()
        self._actual_pid = None
        self._ready_payload = {}
        self._state = "unavailable"
        self._last_error = self._configuration_error()

    async def start(self) -> bool:
        """Preload the worker; failure remains isolated from the FastAPI server."""

        self._desired_running = True
        if not self.configured:
            self._set_unavailable_from_configuration()
            return False
        success = await self._spawn(restarting=self._restart_count > 0)
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(),
                name="local-translation-worker-monitor",
            )
        return success

    async def _spawn(self, *, restarting: bool) -> bool:
        async with self._lifecycle_lock:
            if not self._desired_running:
                return False
            if not self.configured:
                self._set_unavailable_from_configuration()
                return False
            if (
                self._state == "ready"
                and self._process is not None
                and self._process.returncode is None
            ):
                return True

            if not await self._dispose_process_locked(force=True):
                self._state = "degraded"
                self._last_error = "worker_stop_failed"
                self._consecutive_failures += 1
                return False
            if not await self._reconcile_stale_pid_file_locked():
                self._consecutive_failures += 1
                return False
            self._state = "restarting" if restarting else "starting"
            self._last_error = None
            self._ready_event.clear()
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = self.stderr_path.open("ab", buffering=0)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = await asyncio.create_subprocess_exec(
                    str(self.runtime_python),
                    str(self.worker_script),
                    "--model",
                    str(self.model_path),
                    "--parent-pid",
                    str(os.getpid()),
                    cwd=str(self.project_root),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=stderr_handle,
                    creationflags=creationflags,
                )
                self._process = process
                self._stderr_handle = stderr_handle
                assert process.stdout is not None
                deadline = (
                    asyncio.get_running_loop().time() + self.startup_timeout_seconds
                )
                ready: dict[str, Any] | None = None
                while ready is None:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=remaining,
                    )
                    if not line:
                        raise RuntimeError("worker_exited_before_ready")
                    message = json.loads(line.decode("utf-8", errors="replace"))
                    if message.get("protocol") != PROTOCOL:
                        raise RuntimeError("worker_protocol_mismatch")
                    message_type = message.get("type")
                    if message_type == "startup_error":
                        raise RuntimeError("worker_reported_startup_error")
                    if message_type not in {"starting", "ready"}:
                        raise RuntimeError("worker_protocol_mismatch")
                    pid = message.get("pid")
                    if not isinstance(pid, int) or pid <= 0:
                        raise RuntimeError("worker_pid_invalid")
                    if self._actual_pid is not None and self._actual_pid != pid:
                        raise RuntimeError("worker_pid_changed_during_startup")
                    if self._actual_pid is None:
                        self._actual_pid = pid
                        self._write_pid_file(pid)
                    if message_type == "ready":
                        ready = message

                self._ready_payload = {
                    key: ready.get(key)
                    for key in (
                        "model_revision",
                        "device",
                        "compute_type",
                        "inter_threads",
                        "intra_threads",
                        "translation_concurrency",
                        "beam_size",
                        "process_priority",
                        "cold_start_ms",
                    )
                }
                self._state = "ready"
                self._last_error = None
                self._consecutive_failures = 0
                self._last_ready_at = iso_now()
                self._ready_event.set()
                return True
            except asyncio.CancelledError:
                if self._stderr_handle is None:
                    stderr_handle.close()
                await self._dispose_process_locked(force=True)
                raise
            except Exception as error:
                LOGGER.error(
                    "Local translation worker startup failed: %s",
                    type(error).__name__,
                )
                if self._stderr_handle is None:
                    stderr_handle.close()
                self._state = "degraded"
                self._last_error = "startup_failed"
                self._consecutive_failures += 1
                self._ready_event.clear()
                disposed = await self._dispose_process_locked(force=True)
                if not disposed:
                    self._last_error = "worker_stop_failed"
                return False

    async def _monitor_loop(self) -> None:
        backoff = (1.0, 2.0, 4.0, 8.0, 15.0)
        while self._desired_running:
            process = self._process
            if process is not None:
                try:
                    await process.wait()
                except asyncio.CancelledError:
                    return
                if not self._desired_running:
                    return
                async with self._lifecycle_lock:
                    if self._process is process:
                        self._state = "degraded"
                        self._last_error = "worker_exited"
                        self._consecutive_failures += 1
                        if not await self._dispose_process_locked(force=True):
                            self._last_error = "worker_stop_failed"
                            return

            if not self._desired_running:
                return
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._state = "degraded"
                self._last_error = "auto_restart_exhausted"
                return
            self._restart_count += 1
            self._state = "restarting"
            delay = backoff[
                min(max(self._consecutive_failures, 1) - 1, len(backoff) - 1)
            ]
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if self._desired_running:
                await self._spawn(restarting=True)

    def _close_stderr_handle(self) -> None:
        handle, self._stderr_handle = self._stderr_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    @staticmethod
    async def _wait_process(process: asyncio.subprocess.Process, timeout: float) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def _dispose_process_locked(self, *, force: bool) -> bool:
        process, pid = self._process, self._actual_pid
        self._ready_event.clear()
        if process is not None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

        actual_stopped = True
        if force and pid is not None:
            actual_stopped = await self._terminate_owned_pid(pid)

        if process is not None:
            if force and process.returncode is None:
                try:
                    process.kill()
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            await self._wait_process(process, 5.0)

        if pid is not None and not actual_stopped:
            # Killing the launcher or losing the parent should also trigger the
            # Worker watchdog.  Confirm the actual interpreter is gone before
            # discarding its identity or allowing a replacement to spawn.
            actual_stopped = await self._wait_until_not_owned(pid, 5.0)
        if not actual_stopped:
            if process is not None and process.returncode is not None:
                self._process = None
            self._ready_payload = {}
            self._state = "degraded"
            self._last_error = "worker_stop_failed"
            self._close_stderr_handle()
            return False

        self._process = None
        self._actual_pid = None
        self._ready_payload = {}
        self._remove_owned_pid_file(pid)
        self._close_stderr_handle()
        return True

    async def _break_worker(self, process: asyncio.subprocess.Process, code: str) -> None:
        async with self._lifecycle_lock:
            if self._process is not process:
                return
            self._state = "degraded"
            self._last_error = code
            if not await self._dispose_process_locked(force=True):
                self._last_error = "worker_stop_failed"

    async def _wait_ready(self) -> None:
        if self.snapshot()["available"]:
            return
        if not self._desired_running or not self.configured:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        try:
            await asyncio.wait_for(
                self._ready_event.wait(),
                timeout=self.recovery_wait_seconds,
            )
        except asyncio.TimeoutError as error:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE) from error
        if not self.snapshot()["available"]:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)

    async def translate(
        self,
        *,
        text: str,
        source_language: str,
        glossary_terms: tuple[str, ...],
    ) -> dict[str, Any]:
        await self._wait_ready()
        async with self._request_lock:
            await self._wait_ready()
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
            request_id = str(uuid4())
            payload = {
                "command": "translate",
                "id": request_id,
                "text": text,
                "source_language": source_language,
                "glossary_terms": list(glossary_terms),
            }
            started = perf_counter()
            try:
                process.stdin.write(
                    (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
                )
                await process.stdin.drain()
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=self.request_timeout_seconds,
                )
                if not line:
                    raise ConnectionError("worker_pipe_closed")
                response = json.loads(line.decode("utf-8", errors="replace"))
                if (
                    response.get("protocol") != PROTOCOL
                    or response.get("id") != request_id
                ):
                    raise ValueError("worker_protocol_mismatch")
                if response.get("type") == "error":
                    raise translation_error(
                        TranslationErrorCode.UNKNOWN_PROVIDER_ERROR,
                        recoverable=True,
                        retryable=False,
                    )
                if response.get("type") != "translation":
                    raise ValueError("worker_response_invalid")
                translated = str(response.get("translation", "")).strip()
                if not translated:
                    raise translation_error(TranslationErrorCode.INVALID_RESPONSE)
            except asyncio.CancelledError:
                await asyncio.shield(self._break_worker(process, "request_cancelled"))
                raise
            except asyncio.TimeoutError as error:
                await self._break_worker(process, "request_timeout")
                raise translation_error(TranslationErrorCode.REQUEST_TIMEOUT) from error
            except Exception as error:
                if hasattr(error, "code"):
                    raise
                await self._break_worker(process, "protocol_or_transport_error")
                raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE) from error

            provider_wall_ms = round((perf_counter() - started) * 1000, 3)
            self._last_metrics = {
                "completed_at": iso_now(),
                "latency_ms": response.get("latency_ms"),
                "provider_wall_ms": provider_wall_ms,
                "process_rss_bytes": response.get("process_rss_bytes"),
                "process_cpu_percent": response.get("process_cpu_percent"),
            }
            return {**response, "provider_wall_ms": provider_wall_ms}

    async def restart(self) -> bool:
        self._desired_running = True
        self._restart_count += 1
        self._consecutive_failures = 0
        monitor = self._monitor_task
        if monitor is not None and not monitor.done():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self._monitor_task = None
        async with self._request_lock:
            async with self._lifecycle_lock:
                if not await self._dispose_process_locked(force=True):
                    return False
        return await self.start()

    async def stop(self) -> None:
        self._desired_running = False
        monitor = self._monitor_task
        if monitor is not None and not monitor.done():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self._monitor_task = None

        async with self._request_lock:
            async with self._lifecycle_lock:
                process = self._process
                if (
                    process is not None
                    and process.returncode is None
                    and process.stdin is not None
                    and process.stdout is not None
                ):
                    request_id = str(uuid4())
                    try:
                        process.stdin.write(
                            (
                                json.dumps(
                                    {"command": "shutdown", "id": request_id},
                                    separators=(",", ":"),
                                )
                                + "\n"
                            ).encode("utf-8")
                        )
                        await process.stdin.drain()
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                        response = json.loads(line.decode("utf-8", errors="replace"))
                        if (
                            response.get("type") != "shutdown"
                            or response.get("protocol") != PROTOCOL
                            or response.get("id") != request_id
                        ):
                            raise ValueError("worker_shutdown_protocol_mismatch")
                        await self._wait_process(process, 10.0)
                    except Exception as error:
                        LOGGER.warning(
                            "Local translation worker graceful stop failed: %s",
                            type(error).__name__,
                        )
                disposed = await self._dispose_process_locked(force=True)
        if disposed:
            self._state = "stopped"
            self._last_error = None
        else:
            self._state = "degraded"
            self._last_error = "worker_stop_failed"

    close = stop


class SidecarLocalTranslationProvider(TranslationProvider):
    """Thin Provider wrapper; closing it never stops the shared sidecar."""

    provider_name = "local"
    display_name = "로컬 번역"
    external = False

    def __init__(self, supervisor: LocalTranslationWorkerSupervisor) -> None:
        self.supervisor = supervisor
        self.model = supervisor.model_name
        self._closed = False

    async def health_check(self) -> ProviderHealth:
        worker = self.supervisor.snapshot()
        available = bool(worker["available"] and not self._closed)
        if self._closed:
            reason = "번역 Provider가 종료되었습니다."
        elif worker["state"] in {"starting", "restarting"}:
            reason = "로컬 번역 Worker가 모델을 준비하고 있습니다."
        elif not worker["model_installed"]:
            reason = "로컬 번역 모델이 설치되지 않았습니다. 원문 전사는 계속 사용할 수 있습니다."
        elif not worker["runtime_installed"]:
            reason = "격리된 로컬 번역 실행 환경이 설치되지 않았습니다."
        elif not worker["available"]:
            reason = "로컬 번역 Worker를 사용할 수 없습니다. 원문 전사는 계속 동작합니다."
        else:
            reason = None
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=available,
            external=False,
            reason=reason,
            model=self.model,
        )

    @staticmethod
    def _route_language(request: TranslationRequest) -> str:
        if request.source_language in {"ja", "en"}:
            return request.source_language
        if request.source_language == "mixed":
            return "ja" if _JAPANESE_RE.search(request.source_text) else "en"
        raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if self._closed:
            raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
        if request.target_language != "ko":
            raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)
        language = self._route_language(request)
        started = perf_counter()
        response = await self.supervisor.translate(
            text=request.source_text,
            source_language=language,
            glossary_terms=request.glossary_terms,
        )
        translated = str(response.get("translation", "")).strip()
        if not translated:
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE)
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=translated,
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=self.model,
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
        )

    async def close(self) -> None:
        self._closed = True


__all__ = [
    "LocalTranslationWorkerSupervisor",
    "SidecarLocalTranslationProvider",
]
