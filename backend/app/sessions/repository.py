from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from .assembler import assemble_session, read_jsonl
from .exceptions import (
    SessionError,
    invalid_session_id,
    session_not_found,
    session_storage_failed,
)
from .exporters import (
    atomic_write_json,
    atomic_write_text,
    render_markdown,
    render_original_txt,
    render_translation_txt,
)
from .models import (
    FinalTranscript,
    SCHEMA_VERSION,
    SessionManifest,
    SessionStatus,
    StoragePolicy,
    iso_now,
)


_PHASE3_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[0-9a-f]{6,12}$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_EXPORT_FILES = {
    "json": "session.json",
    "original-txt": "transcript_original.txt",
    "translation-txt": "transcript_korean.txt",
    "markdown": "meeting_report.md",
}
_ANALYSIS_STATUSES = {
    "not_started",
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
}


def validate_session_id(session_id: str) -> str:
    value = str(session_id).strip()
    if not value or len(value) > 64 or any(ord(char) < 32 for char in value):
        raise invalid_session_id()
    if "/" in value or "\\" in value or ".." in value or ":" in value:
        raise invalid_session_id()
    if value.upper().split(".")[0] in _WINDOWS_RESERVED:
        raise invalid_session_id()
    if _PHASE3_ID.fullmatch(value):
        return value
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise invalid_session_id() from error
    return value


class JsonlSessionRepository:
    """Legacy-compatible append log plus Phase 3 atomic completed sessions.

    The default constructor keeps the Phase 1/2 root ``<uuid>.jsonl`` behavior.
    The application opts into Phase 3 folders with ``phase3=True``.
    """

    def __init__(
        self,
        root: Path,
        *,
        phase3: bool = False,
        storage_policy: StoragePolicy | None = None,
        now: Callable[[], str] = iso_now,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.phase3 = bool(phase3)
        self._storage_policy = storage_policy or StoragePolicy()
        self._now = now
        self._session_id: str | None = None
        self._known_sessions: set[str] = set()
        self._legacy_active: set[str] = set()
        self._event_indices: dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def storage_policy(self) -> StoragePolicy:
        return self._storage_policy

    def storage_settings(self) -> dict[str, bool]:
        return self._storage_policy.to_dict()

    def configure_storage(
        self,
        *,
        save_original: bool,
        save_translation: bool,
        save_analysis: bool,
    ) -> dict[str, bool]:
        with self._lock:
            self._storage_policy = StoragePolicy(
                save_original=bool(save_original),
                save_translation=bool(save_translation),
                save_analysis=bool(save_analysis),
                save_audio=False,
            )
            return self.storage_settings()

    @staticmethod
    def _new_session_id() -> str:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{timestamp}_{uuid4().hex[:6]}"

    def _session_dir(self, session_id: str) -> Path:
        safe_id = validate_session_id(session_id)
        path = (self.root / safe_id).resolve()
        if path.parent != self.root:
            raise invalid_session_id()
        return path

    def _legacy_path(self, session_id: str) -> Path:
        safe_id = validate_session_id(session_id)
        path = (self.root / f"{safe_id}.jsonl").resolve()
        if path.parent != self.root:
            raise invalid_session_id()
        return path

    def _manifest_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "manifest.json"

    def _events_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "events.jsonl"

    def _is_phase3_session(self, session_id: str) -> bool:
        return self._session_dir(session_id).is_dir() and session_id not in self._legacy_active

    def _load_manifest(self, session_id: str) -> SessionManifest:
        path = self._manifest_path(session_id)
        if not path.is_file():
            if self._legacy_path(session_id).is_file():
                return SessionManifest(
                    session_id=session_id,
                    status=SessionStatus.RECOVERED.value,
                    save_original=True,
                    save_translation=True,
                    save_analysis=True,
                    warnings=["legacy_import"],
                )
            raise session_not_found()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            manifest = SessionManifest.from_dict(payload)
            if manifest.schema_version > SCHEMA_VERSION:
                raise SessionError(
                    "unsupported_session_schema",
                    "이 세션은 현재 앱보다 새로운 스키마를 사용합니다.",
                    status_code=409,
                )
            if manifest.session_id != session_id:
                raise ValueError("session id mismatch")
            return manifest
        except SessionError:
            raise
        except Exception as error:
            raise session_storage_failed() from error

    def _write_manifest(self, manifest: SessionManifest) -> None:
        atomic_write_json(self._manifest_path(manifest.session_id), manifest.to_dict())

    def start_session(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        storage_policy: StoragePolicy | None = None,
        session_id: str | None = None,
    ) -> str:
        with self._lock:
            use_phase3 = self.phase3 or metadata is not None or session_id is not None
            if not use_phase3:
                legacy_id = str(uuid4())
                self._session_id = legacy_id
                self._known_sessions.add(legacy_id)
                self._legacy_active.add(legacy_id)
                return legacy_id

            safe_id = validate_session_id(session_id) if session_id else self._new_session_id()
            directory = self._session_dir(safe_id)
            if directory.exists() or self._legacy_path(safe_id).exists():
                raise SessionError(
                    "session_already_exists",
                    "같은 세션 ID가 이미 존재합니다.",
                    status_code=409,
                )
            directory.mkdir(parents=False, exist_ok=False)
            values = dict(metadata or {})
            policy = storage_policy or self._storage_policy
            now_value = self._now()
            manifest = SessionManifest(
                session_id=safe_id,
                status=SessionStatus.RUNNING.value,
                created_at=now_value,
                started_at=str(values.get("started_at") or now_value),
                source=(str(values["source"]) if values.get("source") else None),
                audio_device_name=(
                    str(values["audio_device_name"])
                    if values.get("audio_device_name")
                    else None
                ),
                whisper_model=(
                    str(values["whisper_model"])
                    if values.get("whisper_model")
                    else None
                ),
                translation_provider=str(values.get("translation_provider") or "none"),
                translation_direction=str(
                    values.get("translation_direction") or "ja_to_ko"
                ),
                analysis_provider="none",
                save_original=policy.save_original,
                save_translation=policy.save_translation,
                save_analysis=policy.save_analysis,
                save_audio=False,
            )
            self._write_manifest(manifest)
            self._session_id = safe_id
            self._known_sessions.add(safe_id)
            self._event_indices[safe_id] = 0
            return safe_id

    def _assert_known(self, session_id: str) -> None:
        validate_session_id(session_id)
        if (
            session_id not in self._known_sessions
            and not self._session_dir(session_id).is_dir()
            and not self._legacy_path(session_id).is_file()
        ):
            raise RuntimeError("Unknown transcription session")

    def _next_event_index(self, session_id: str) -> int:
        if session_id not in self._event_indices:
            path = self._events_path(session_id)
            if not path.is_file():
                self._event_indices[session_id] = 0
            else:
                with path.open("r", encoding="utf-8") as handle:
                    self._event_indices[session_id] = sum(1 for _ in handle)
        value = self._event_indices[session_id]
        self._event_indices[session_id] = value + 1
        return value

    @staticmethod
    def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(record), ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()

    def append_final(self, transcript: FinalTranscript) -> None:
        with self._lock:
            self._assert_known(transcript.session_id)
            if not self._is_phase3_session(transcript.session_id):
                self._append_jsonl(
                    self._legacy_path(transcript.session_id),
                    transcript.to_dict(),
                )
                return
            manifest = self._load_manifest(transcript.session_id)
            common = {
                "schema_version": SCHEMA_VERSION,
                "event_index": self._next_event_index(transcript.session_id),
                "session_id": transcript.session_id,
                "segment_id": transcript.segment_id,
                "source": transcript.source,
                "started_at": transcript.started_at,
                "ended_at": transcript.ended_at,
            }
            if manifest.save_original:
                record = {
                    **common,
                    "type": "final_transcript",
                    "utterance_id": transcript.utterance_id,
                    "text": transcript.text,
                    "language": transcript.language,
                    "language_probability": transcript.language_probability,
                    "inference_seconds": transcript.inference_seconds,
                }
            else:
                record = {
                    **common,
                    "type": "segment_marker",
                    "original_saved": False,
                }
            self._append_jsonl(self._events_path(transcript.session_id), record)
            # Phase 2 readers expect the original root-level append log. Keep a
            # non-authoritative compatibility mirror for saved original rows;
            # Phase 3 assembly always reads events.jsonl.
            if manifest.save_original:
                self._append_jsonl(
                    self._legacy_path(transcript.session_id),
                    transcript.to_dict(),
                )

    def append_translation(
        self,
        session_id: str,
        translation: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._assert_known(session_id)
            segment_id = str(translation.get("segment_id", "")).strip()
            translated_text = str(translation.get("translated_text", "")).strip()
            if not segment_id or not translated_text:
                raise ValueError("Translation segment and text are required")
            record = {
                "type": "translation",
                "segment_id": segment_id,
                "source_language": str(translation.get("source_language", "unknown")),
                "target_language": str(translation.get("target_language", "ko")),
                "translated_text": translated_text,
                "provider": str(translation.get("provider", "none")),
                "model": translation.get("model"),
                "latency_ms": translation.get("latency_ms"),
                "queue_wait_ms": translation.get("queue_wait_ms"),
                "provider_latency_ms": translation.get(
                    "provider_latency_ms",
                    translation.get("latency_ms"),
                ),
                "total_latency_ms": translation.get("total_latency_ms"),
                "timestamp": translation.get("completed_at") or translation.get("timestamp"),
            }
            if not self._is_phase3_session(session_id):
                self._append_jsonl(self._legacy_path(session_id), record)
                return
            manifest = self._load_manifest(session_id)
            if not manifest.save_translation:
                return
            phase3_record = {
                "schema_version": SCHEMA_VERSION,
                "event_index": self._next_event_index(session_id),
                "session_id": session_id,
                **record,
            }
            self._append_jsonl(self._events_path(session_id), phase3_record)
            self._append_jsonl(self._legacy_path(session_id), record)
            if manifest.status in {
                SessionStatus.COMPLETED.value,
                SessionStatus.RECOVERED.value,
            }:
                self.finalize_session(
                    session_id,
                    recovered=manifest.status == SessionStatus.RECOVERED.value,
                )

    def append_context_normalization(
        self,
        session_id: str,
        normalization: Mapping[str, Any],
    ) -> None:
        """Persist a derived normalization without altering original transcript rows."""

        with self._lock:
            self._assert_known(session_id)
            if not self._is_phase3_session(session_id):
                return
            segment_id = str(normalization.get("segment_id", "")).strip()
            normalized_text = str(normalization.get("normalized_text", "")).strip()
            if not segment_id or not normalized_text:
                return
            raw_matches = normalization.get("matches", [])
            matches = [
                {
                    "entry_id": str(item.get("entry_id", "")),
                    "category": str(item.get("category", "term")),
                    "from": str(item.get("from", "")),
                    "to": str(item.get("to", "")),
                }
                for item in raw_matches
                if isinstance(item, Mapping)
            ]
            self._append_jsonl(
                self._events_path(session_id),
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_index": self._next_event_index(session_id),
                    "type": "context_normalization",
                    "session_id": session_id,
                    "segment_id": segment_id,
                    "profile_id": str(normalization.get("profile_id", "general")),
                    "normalized_text": normalized_text,
                    "changed": bool(normalization.get("changed", False)),
                    "matches": matches,
                    "timestamp": normalization.get("timestamp") or self._now(),
                },
            )

    def append_transcription_quality(
        self,
        session_id: str,
        quality: Mapping[str, Any],
    ) -> None:
        """Append derived hybrid-STT audit data without modifying transcript rows."""

        with self._lock:
            self._assert_known(session_id)
            if not self._is_phase3_session(session_id):
                return
            segment_id = str(quality.get("segment_id", "")).strip()
            if not segment_id:
                return
            manifest = self._load_manifest(session_id)
            record: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "event_index": self._next_event_index(session_id),
                "type": "transcription_quality",
                "session_id": session_id,
                "segment_id": segment_id,
                "provider": "deepgram",
                "boundary_reason": str(quality.get("boundary_reason", "provider"))[:48],
                "confidence": quality.get("confidence"),
                "word_count": max(0, int(quality.get("word_count", 0))),
                "minimum_word_confidence": quality.get("minimum_word_confidence"),
                "low_word_ratio": quality.get("low_word_ratio"),
                "risk_reasons": [
                    str(value)[:64]
                    for value in quality.get("risk_reasons", [])
                    if str(value).strip()
                ][:12],
                "recheck_status": str(quality.get("recheck_status", "not_requested"))[:48],
                "recheck_model": (
                    str(quality.get("recheck_model"))[:64]
                    if quality.get("recheck_model")
                    else None
                ),
                "recheck_latency_ms": quality.get("recheck_latency_ms"),
                "recheck_accepted": bool(quality.get("recheck_accepted", False)),
                "provider_received_at": quality.get("provider_received_at"),
                "audio_end_to_provider_ms": quality.get(
                    "audio_end_to_provider_ms"
                ),
                "canonical_ready_at": quality.get("canonical_ready_at"),
                "canonical_processing_ms": quality.get(
                    "canonical_processing_ms"
                ),
                "final_queue_wait_ms": quality.get("final_queue_wait_ms"),
                "provisional_displayed": bool(
                    quality.get("provisional_displayed", False)
                ),
                "timestamp": quality.get("timestamp") or self._now(),
            }
            # Text follows the session's original-storage consent. Audio is
            # never stored by this event.
            if manifest.save_original:
                record["deepgram_text"] = str(quality.get("deepgram_text", ""))
                record["selected_text"] = str(quality.get("selected_text", ""))
                if quality.get("whisper_text"):
                    record["whisper_text"] = str(quality.get("whisper_text"))
            self._append_jsonl(self._events_path(session_id), record)

    def append_translation_error(
        self,
        session_id: str,
        error: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._assert_known(session_id)
            if not self._is_phase3_session(session_id):
                return
            manifest = self._load_manifest(session_id)
            if not manifest.save_translation:
                return
            segment_id = str(error.get("segment_id", "")).strip()
            if not segment_id:
                return
            self._append_jsonl(
                self._events_path(session_id),
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_index": self._next_event_index(session_id),
                    "type": "translation_error",
                    "session_id": session_id,
                    "segment_id": segment_id,
                    "provider": str(error.get("provider", "unknown")),
                    "code": str(error.get("code", "TRANSLATION_ERROR")),
                    "recoverable": bool(error.get("recoverable", True)),
                    "timestamp": error.get("timestamp") or self._now(),
                },
            )
            if manifest.status in {
                SessionStatus.COMPLETED.value,
                SessionStatus.RECOVERED.value,
            }:
                self.finalize_session(
                    session_id,
                    recovered=manifest.status == SessionStatus.RECOVERED.value,
                )

    def update_status(self, session_id: str, status: str) -> dict[str, Any]:
        with self._lock:
            self._assert_known(session_id)
            if not self._is_phase3_session(session_id):
                return {"session_id": session_id, "status": status}
            allowed = {item.value for item in SessionStatus}
            if status not in allowed:
                raise ValueError("Unsupported session status")
            manifest = self._load_manifest(session_id)
            manifest.status = status
            self._write_manifest(manifest)
            return manifest.to_dict()

    def stop_session(
        self,
        *,
        ended_at: str | None = None,
        finalize: bool | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            session_id = self._session_id
            if session_id is None:
                return None
            self._session_id = None
            if session_id in self._legacy_active:
                self._legacy_active.discard(session_id)
                return None
            should_finalize = self.phase3 if finalize is None else bool(finalize)
            manifest = self._load_manifest(session_id)
            manifest.status = SessionStatus.STOPPING.value
            manifest.ended_at = ended_at or self._now()
            self._write_manifest(manifest)
            if not should_finalize:
                return manifest.to_dict()
            return self.finalize_session(session_id)

    def _source_path(self, session_id: str) -> Path:
        events = self._events_path(session_id)
        if events.is_file():
            return events
        legacy = self._legacy_path(session_id)
        if legacy.is_file():
            return legacy
        if self._session_dir(session_id).is_dir():
            return events
        raise session_not_found()

    def finalize_session(
        self,
        session_id: str,
        *,
        recovered: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            safe_id = validate_session_id(session_id)
            source_path = self._source_path(safe_id)
            directory = self._session_dir(safe_id)
            directory.mkdir(parents=True, exist_ok=True)
            try:
                manifest = self._load_manifest(safe_id)
            except SessionError as error:
                if error.code != "session_not_found":
                    raise
                manifest = SessionManifest(
                    session_id=safe_id,
                    status=SessionStatus.RECOVERED.value,
                    warnings=["legacy_import"],
                )
            manifest.status = SessionStatus.FINALIZING.value
            self._write_manifest(manifest)
            try:
                records, read_warnings = read_jsonl(source_path)
                warnings = [*manifest.warnings]
                warnings.extend(item.public_message() for item in read_warnings)
                analysis_path = directory / "analysis.json"
                analysis: dict[str, Any] | None = None
                if manifest.save_analysis and analysis_path.is_file():
                    value = json.loads(analysis_path.read_text(encoding="utf-8"))
                    analysis = value if isinstance(value, dict) else None
                session = assemble_session(
                    safe_id,
                    records,
                    manifest=manifest,
                    warnings=warnings,
                    analysis=analysis,
                )
                atomic_write_json(directory / "session.json", session)
                atomic_write_text(
                    directory / "transcript_original.txt",
                    render_original_txt(session),
                )
                atomic_write_text(
                    directory / "transcript_korean.txt",
                    render_translation_txt(session),
                )
                atomic_write_text(
                    directory / "meeting_report.md",
                    render_markdown(session),
                )
                manifest.segment_count = len(session["segments"])
                manifest.translated_segment_count = sum(
                    1
                    for item in session["segments"]
                    if item.get("translation_status") == "success"
                )
                manifest.finalized_at = self._now()
                manifest.status = (
                    SessionStatus.RECOVERED.value
                    if recovered
                    else SessionStatus.COMPLETED.value
                )
                manifest.warnings = list(session.get("warnings", []))
                if recovered:
                    manifest.recovered_at = manifest.finalized_at
                self._write_manifest(manifest)
                session["metadata"].update(
                    {
                        "status": manifest.status,
                        "finalized_at": manifest.finalized_at,
                        "segment_count": manifest.segment_count,
                        "translated_segment_count": manifest.translated_segment_count,
                    }
                )
                atomic_write_json(directory / "session.json", session)
                return session
            except SessionError:
                raise
            except Exception as error:
                manifest.status = SessionStatus.ERROR.value
                if "finalize_failed" not in manifest.warnings:
                    manifest.warnings.append("finalize_failed")
                try:
                    self._write_manifest(manifest)
                except Exception:
                    pass
                raise session_storage_failed() from error

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            safe_id = validate_session_id(session_id)
            completed_path = self._session_dir(safe_id) / "session.json"
            if completed_path.is_file():
                try:
                    payload = json.loads(completed_path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        return payload
                except Exception as error:
                    raise session_storage_failed() from error
            source = self._source_path(safe_id)
            try:
                manifest = self._load_manifest(safe_id)
            except SessionError as error:
                if error.code != "session_not_found":
                    raise
                manifest = SessionManifest(
                    session_id=safe_id,
                    status=SessionStatus.RECOVERED.value,
                    warnings=["legacy_import"],
                )
            records, read_warnings = read_jsonl(source)
            return assemble_session(
                safe_id,
                records,
                manifest=manifest,
                warnings=[
                    *manifest.warnings,
                    *(item.public_message() for item in read_warnings),
                ],
            )

    def _update_completed_analysis_metadata(
        self,
        session_id: str,
        manifest: SessionManifest,
    ) -> None:
        completed_path = self._session_dir(session_id) / "session.json"
        if not completed_path.is_file():
            return
        try:
            payload = json.loads(completed_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                payload["metadata"] = metadata
            metadata.update(
                {
                    "analysis_provider": manifest.analysis_provider,
                    "analysis_status": manifest.analysis_status,
                    "analysis_generated_at": manifest.analysis_generated_at,
                    "analysis_revision": manifest.analysis_revision,
                }
            )
            atomic_write_json(completed_path, payload)
        except Exception as error:
            raise session_storage_failed() from error

    def set_analysis_status(
        self,
        session_id: str,
        status: str,
        *,
        provider: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            safe_id = validate_session_id(session_id)
            self._source_path(safe_id)
            if status not in _ANALYSIS_STATUSES:
                raise ValueError("Unsupported analysis status")
            manifest = self._load_manifest(safe_id)
            manifest.analysis_status = status
            if provider is not None:
                manifest.analysis_provider = str(provider)
            self._write_manifest(manifest)
            self._update_completed_analysis_metadata(safe_id, manifest)
            return {
                "session_id": safe_id,
                "status": manifest.analysis_status,
                "provider": manifest.analysis_provider,
                "generated_at": manifest.analysis_generated_at,
                "revision": manifest.analysis_revision,
            }

    def load_analysis(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            safe_id = validate_session_id(session_id)
            self._source_path(safe_id)
            path = self._session_dir(safe_id) / "analysis.json"
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as error:
                raise session_storage_failed() from error
            if not isinstance(payload, dict):
                raise session_storage_failed()
            return payload

    def save_analysis(
        self,
        session_id: str,
        analysis: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            safe_id = validate_session_id(session_id)
            self._source_path(safe_id)
            payload = dict(analysis)
            if str(payload.get("session_id", "")) != safe_id:
                raise ValueError("Analysis session ID does not match")
            if str(payload.get("status", "")) != "completed":
                raise ValueError("Only completed analysis can be saved")
            manifest = self._load_manifest(safe_id)
            manifest.analysis_provider = str(payload.get("provider", "none"))
            manifest.analysis_status = "completed"
            manifest.analysis_generated_at = str(payload.get("generated_at") or self._now())
            requested_revision = payload.get("revision")
            if isinstance(requested_revision, int) and requested_revision > 0:
                manifest.analysis_revision = requested_revision
            else:
                manifest.analysis_revision += 1
                payload["revision"] = manifest.analysis_revision
            payload["generated_at"] = manifest.analysis_generated_at
            if manifest.save_analysis:
                atomic_write_json(self._session_dir(safe_id) / "analysis.json", payload)
            self._write_manifest(manifest)
            if manifest.save_analysis:
                self.finalize_session(
                    safe_id,
                    recovered=self._legacy_path(safe_id).is_file(),
                )
            else:
                self._update_completed_analysis_metadata(safe_id, manifest)
            return payload

    @staticmethod
    def _summary(session: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(session.get("metadata", {}))
        return {
            "session_id": session.get("session_id"),
            "status": metadata.get("status", SessionStatus.RECOVERED.value),
            "created_at": metadata.get("created_at"),
            "started_at": metadata.get("started_at"),
            "ended_at": metadata.get("ended_at"),
            "source": metadata.get("source"),
            "whisper_model": metadata.get("whisper_model"),
            "translation_provider": metadata.get("translation_provider", "none"),
            "segment_count": len(session.get("segments", [])),
            "translated_segment_count": sum(
                1
                for item in session.get("segments", [])
                if item.get("translation_status") == "success"
            ),
            "analysis_status": metadata.get("analysis_status", "not_started"),
            "warnings": list(session.get("warnings", [])),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = {
                path.name
                for path in self.root.iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and (_PHASE3_ID.fullmatch(path.name) or self._is_uuid(path.name))
            }
            ids.update(
                path.stem
                for path in self.root.glob("*.jsonl")
                if self._is_uuid(path.stem)
            )
            summaries: list[dict[str, Any]] = []
            for session_id in ids:
                try:
                    summaries.append(self._summary(self.get_session(session_id)))
                except Exception:
                    summaries.append(
                        {
                            "session_id": session_id,
                            "status": SessionStatus.ERROR.value,
                            "created_at": None,
                            "started_at": None,
                            "ended_at": None,
                            "source": None,
                            "whisper_model": None,
                            "translation_provider": "none",
                            "segment_count": 0,
                            "translated_segment_count": 0,
                            "analysis_status": "not_started",
                            "warnings": ["session_unreadable"],
                        }
                    )
            return sorted(
                summaries,
                key=lambda item: str(
                    item.get("started_at") or item.get("created_at") or item["session_id"]
                ),
                reverse=True,
            )

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def get_export_path(self, session_id: str, kind: str) -> Path:
        with self._lock:
            if kind not in _EXPORT_FILES:
                raise ValueError("Unsupported export kind")
            safe_id = validate_session_id(session_id)
            path = self._session_dir(safe_id) / _EXPORT_FILES[kind]
            if not path.is_file():
                self.finalize_session(
                    safe_id,
                    recovered=self._legacy_path(safe_id).is_file(),
                )
            if not path.is_file() or path.parent.resolve() != self._session_dir(safe_id):
                raise session_not_found()
            return path

    def recover_incomplete(self) -> list[str]:
        recovered: list[str] = []
        with self._lock:
            for directory in self.root.iterdir():
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                try:
                    session_id = validate_session_id(directory.name)
                    manifest = self._load_manifest(session_id)
                except Exception:
                    continue
                needs_recovery = manifest.status in {
                    SessionStatus.CREATED.value,
                    SessionStatus.RUNNING.value,
                    SessionStatus.PAUSED.value,
                    SessionStatus.STOPPING.value,
                    SessionStatus.FINALIZING.value,
                } or not (directory / "session.json").is_file()
                if not needs_recovery:
                    continue
                try:
                    self.finalize_session(session_id, recovered=True)
                    recovered.append(session_id)
                except SessionError:
                    continue
        return recovered


__all__ = ["JsonlSessionRepository", "validate_session_id"]
