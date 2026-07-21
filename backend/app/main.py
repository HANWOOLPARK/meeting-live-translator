from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.schemas import (
    AnalysisSettingsRequest,
    ContextEntryRequest,
    ContextProfileCreateRequest,
    ContextSuggestionDecisionRequest,
    ContextSuggestionGenerateRequest,
    DecisionRadarItemUpdateRequest,
    DecisionRadarSettingsRequest,
    LiveShareStartRequest,
    SettingsPatchRequest,
    SessionStorageSettingsRequest,
    StartCaptureRequest,
    TranslationSettingsRequest,
    TranslationTestRequest,
)
from .analysis import AnalysisProviderError
from .context_engine import ContextEngineError
from .errors import SafeAppError, exception_kind
from .services import AppServices, build_services
from .sessions.exceptions import SessionError
from .sharing import ShareRelayError, ShareRelayManager
from .translation import (
    TranslationProviderError,
    TranslationRequest,
    TranslationStatus,
)
from .websocket.events import make_event


LOGGER = logging.getLogger(__name__)
APP_VERSION = "0.6.0-live-share"


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


def _public_settings(services: AppServices) -> dict[str, Any]:
    payload = services.settings.public_dict()
    payload["selected_model"] = services.controller.selected_model
    payload["model_runtime"] = services.controller.public_model_info()
    payload["stt_provider"] = services.controller.selected_stt_provider
    payload["stt_runtime"] = services.controller.public_stt_info()
    payload["translation_direction"] = services.controller.translation_direction
    return payload


def create_app(
    services: AppServices | None = None,
    *,
    live_share_manager: ShareRelayManager | None = None,
) -> FastAPI:
    resolved_services = services or build_services()
    sharing = live_share_manager or ShareRelayManager(
        relay_url=resolved_services.settings.share_relay_url,
        create_secret=resolved_services.settings.share_relay_secret,
        request_timeout_seconds=(
            resolved_services.settings.share_relay_timeout_seconds
        ),
        audit_dir=resolved_services.settings.project_root / "data" / "share-access",
    )
    share_event_sink = sharing.publish_event
    resolved_services.websocket_manager.add_event_sink(share_event_sink)

    def context_snapshot() -> dict[str, Any]:
        payload = resolved_services.context_engine.snapshot()
        payload["deepgram_applies_on_next_connection"] = True
        return payload

    def context_failure(error: ContextEngineError) -> SafeAppError:
        status = 404 if error.code.endswith("not_found") else 409
        return SafeAppError(error.code, error.safe_message, status)

    def translation_worker_snapshot() -> dict[str, Any]:
        worker = resolved_services.local_translation_worker
        if worker is not None:
            return worker.snapshot()
        return {
            "configured": False,
            "model_installed": False,
            "runtime_installed": False,
            "state": "unmanaged",
            "available": False,
            "desired_running": False,
            "pid": None,
            "model": None,
            "model_revision": None,
            "device": "cpu",
            "compute_type": "int8",
            "inter_threads": 1,
            "intra_threads": 2,
            "translation_concurrency": 1,
            "beam_size": 1,
            "process_priority": "below_normal_requested",
            "cold_start_ms": None,
            "restart_count": 0,
            "last_ready_at": None,
            "last_error": None,
        }

    async def translation_provider_payloads() -> list[dict[str, Any]]:
        current = resolved_services.translation_manager.provider
        payloads: list[dict[str, Any]] = []
        for provider_id in ("none", "local", "openai", "gemini"):
            temporary = provider_id != current.provider_name
            provider = (
                resolved_services.translation_provider_factories[provider_id]()
                if temporary
                else current
            )
            try:
                health = await provider.health_check()
                payload = health.to_dict()
                if provider_id == "openai":
                    payload["api_key_configured"] = bool(
                        resolved_services.settings.openai_api_key
                    )
                if provider_id == "gemini":
                    payload["api_key_configured"] = bool(
                        resolved_services.settings.gemini_api_key
                    )
                if provider_id == "local":
                    payload["worker"] = translation_worker_snapshot()
                payloads.append(payload)
            finally:
                if temporary:
                    await provider.close()
        return payloads

    async def translation_public_settings() -> dict[str, Any]:
        manager = resolved_services.translation_manager
        providers = await translation_provider_payloads()
        current = next(
            item for item in providers if item["id"] == manager.provider.provider_name
        )
        local = next(item for item in providers if item["id"] == "local")
        worker = translation_worker_snapshot()
        status = (
            "disabled"
            if current["id"] == "none"
            else "ready" if current["available"] else "unavailable"
        )
        return {
            "provider": current["id"],
            "status": status,
            "external": bool(current["external"] and current["available"]),
            "reason": current.get("reason"),
            "openai_model": resolved_services.settings.openai_translation_model,
            "openai_api_key_configured": bool(
                resolved_services.settings.openai_api_key
            ),
            "gemini_model": resolved_services.settings.gemini_translation_model,
            "gemini_api_key_configured": bool(
                resolved_services.settings.gemini_api_key
            ),
            "gemini_timeout_seconds": (
                resolved_services.settings.gemini_translation_timeout_seconds
            ),
            "gemini_max_retries": (
                resolved_services.settings.gemini_translation_max_retries
            ),
            "gemini_context_segments": (
                resolved_services.settings.gemini_translation_context_segments
            ),
            "local_model_installed": (
                bool(worker["model_installed"])
                if resolved_services.local_translation_worker is not None
                else bool(local["available"])
            ),
            "worker": worker,
            "context_segments": resolved_services.settings.translation_context_segments,
            "queue_max_size": resolved_services.settings.translation_queue_max_size,
            "max_concurrency": resolved_services.settings.translation_max_concurrency,
            "timeout_seconds": resolved_services.settings.translation_timeout_seconds,
            "max_retries": resolved_services.settings.translation_max_retries,
            "translate_unknown": resolved_services.settings.translation_translate_unknown,
            "queue": manager.snapshot(),
        }

    async def analysis_provider_payloads() -> list[dict[str, Any]]:
        return await resolved_services.analysis_manager.providers()

    async def analysis_public_settings() -> dict[str, Any]:
        manager = resolved_services.analysis_manager
        payload = await manager.public_settings()
        payload.update(
            {
                "provider": manager.provider.provider_name,
                "selected_provider": manager.provider.provider_name,
                "model": getattr(manager.provider, "model", None) or None,
                "openai_model": resolved_services.settings.openai_analysis_model,
                "gemini_model": (
                    resolved_services.settings.gemini_analysis_model
                    or resolved_services.settings.gemini_translation_model
                ),
                "auto_run_on_stop": resolved_services.analysis_auto_run_on_stop,
                "openai_api_key_configured": bool(
                    resolved_services.settings.openai_api_key
                ),
                "gemini_api_key_configured": bool(
                    resolved_services.settings.gemini_api_key
                ),
                "max_segments_per_chunk": manager.max_segments_per_chunk,
                "max_chars_per_chunk": manager.max_characters_per_chunk,
            }
        )
        return payload

    async def decision_radar_provider_payloads() -> list[dict[str, Any]]:
        payloads = await resolved_services.decision_radar_manager.providers()
        for payload in payloads:
            provider_id = str(payload.get("id", ""))
            if provider_id == "openai":
                payload["api_key_configured"] = bool(
                    resolved_services.settings.openai_api_key
                )
            elif provider_id == "gemini":
                payload["api_key_configured"] = bool(
                    resolved_services.settings.gemini_api_key
                )
        return payloads

    async def decision_radar_public_settings() -> dict[str, Any]:
        manager = resolved_services.decision_radar_manager
        payload = await manager.public_settings()
        payload.update(
            {
                "selected_provider": manager.provider.provider_name,
                "openai_model": resolved_services.settings.openai_decision_radar_model,
                "gemini_model": resolved_services.settings.gemini_decision_radar_model,
                "openai_api_key_configured": bool(
                    resolved_services.settings.openai_api_key
                ),
                "gemini_api_key_configured": bool(
                    resolved_services.settings.gemini_api_key
                ),
            }
        )
        return payload

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if resolved_services.settings.session_auto_recover:
            try:
                await resolved_services.session_manager.recover_startup()
            except Exception as error:
                LOGGER.error("Session recovery failed: %s", exception_kind(error))
        worker = resolved_services.local_translation_worker
        worker_start_task: asyncio.Task[None] | None = None

        async def prewarm_local_worker() -> None:
            assert worker is not None
            try:
                ready = await worker.start()
                if not ready:
                    LOGGER.warning(
                        "Local translation worker did not become ready; transcription remains available"
                    )
            except Exception as error:
                LOGGER.error(
                    "Local translation worker start failed: %s",
                    exception_kind(error),
                )

        if worker is not None:
            # Preload immediately, but never hold FastAPI/UI/original
            # transcription readiness behind a sidecar model load.
            worker_start_task = asyncio.create_task(
                prewarm_local_worker(),
                name="local-translation-worker-prewarm",
            )
        try:
            await resolved_services.translation_manager.start()
        except Exception as error:
            LOGGER.error("Translation worker start failed: %s", exception_kind(error))
        try:
            await resolved_services.decision_radar_manager.start()
        except Exception as error:
            LOGGER.error("Decision Radar start failed: %s", exception_kind(error))
        await sharing.start()
        try:
            yield
        finally:
            resolved_services.websocket_manager.remove_event_sink(share_event_sink)
            await sharing.shutdown()
            await resolved_services.controller.shutdown()
            await resolved_services.decision_radar_manager.shutdown()
            await resolved_services.analysis_manager.shutdown()
            await resolved_services.translation_manager.shutdown()
            if worker_start_task is not None and not worker_start_task.done():
                worker_start_task.cancel()
            if worker_start_task is not None:
                await asyncio.gather(worker_start_task, return_exceptions=True)
            if worker is not None:
                await worker.stop()
            await resolved_services.websocket_manager.close_all()

    app = FastAPI(
        title="WhyKaigi",
        version=APP_VERSION,
        description=(
            "Phase 3 near-real-time transcription, optional Korean translation, "
            "safe session exports, and explicit post-meeting analysis"
        ),
        lifespan=lifespan,
    )
    app.state.services = resolved_services
    app.state.live_share_manager = sharing

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path in {"/", "/captions", "/decision-radar"} or request.url.path.startswith(
            "/static/"
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SafeAppError)
    async def safe_error_handler(request: Request, exc: SafeAppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.as_dict(_request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "요청 값이 올바르지 않습니다.",
                "recoverable": True,
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(SessionError)
    async def session_error_handler(request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.safe_message,
                "recoverable": exc.status_code < 500,
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(AnalysisProviderError)
    async def analysis_error_handler(
        request: Request,
        exc: AnalysisProviderError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503 if exc.retryable else 409,
            content={
                "code": exc.code.value.lower(),
                "message": exc.safe_message,
                "recoverable": exc.recoverable,
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.error("Unhandled request error: %s", exception_kind(exc))
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "요청을 처리하지 못했습니다. 서버는 계속 실행됩니다.",
                "recoverable": True,
                "request_id": _request_id(request),
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            # Keep the Phase 2 field for existing API consumers; current_phase
            # is the forward-compatible feature level.
            "phase": 2,
            "current_phase": 3,
            "version": APP_VERSION,
            "capture": resolved_services.controller.snapshot(),
            "translation": resolved_services.translation_manager.snapshot(),
            "translation_worker": translation_worker_snapshot(),
            "analysis": {
                **resolved_services.analysis_manager.snapshot(),
                "auto_run_on_stop": resolved_services.analysis_auto_run_on_stop,
            },
            "decision_radar": resolved_services.decision_radar_manager.diagnostics(),
            "live_share": sharing.snapshot(),
            "websocket_connections": resolved_services.websocket_manager.connection_count,
            "api_key_required": False,
            "session": {
                "active_session_id": resolved_services.session_manager.active_session_id,
                "last_session_id": resolved_services.controller.snapshot().get(
                    "last_session_id"
                ),
                "storage": resolved_services.repository.storage_settings(),
            },
        }

    @app.get("/api/diagnostics")
    async def diagnostics() -> dict[str, Any]:
        """Return safe operational state without local paths or source text."""

        capture_snapshot = resolved_services.controller.snapshot()
        return {
            "status": "ok",
            "version": APP_VERSION,
            "server": {
                "capture_state": capture_snapshot["state"],
                "capture": {
                    "dropped_frames": capture_snapshot["dropped_frames"],
                    "frame_queue_max_size": resolved_services.settings.frame_queue_size,
                },
                "stt": resolved_services.controller.public_stt_info(),
                "translation_provider": (
                    resolved_services.translation_manager.provider.provider_name
                ),
                "translation_queue": resolved_services.translation_manager.snapshot(),
            },
            "translation_worker": translation_worker_snapshot(),
            "decision_radar": resolved_services.decision_radar_manager.diagnostics(),
            "live_share": sharing.snapshot(),
            "context_engine": {
                "active_profile_id": resolved_services.context_engine.snapshot()[
                    "active_profile_id"
                ],
                "keyterm_count": resolved_services.context_engine.snapshot()[
                    "keyterm_count"
                ],
                "consent_required": True,
            },
        }

    @app.get("/api/share")
    async def live_share_status() -> dict[str, Any]:
        return sharing.snapshot()

    @app.post("/api/share/start")
    async def start_live_share(body: LiveShareStartRequest) -> dict[str, Any]:
        if not body.consent_confirmed:
            raise SafeAppError(
                "share_consent_required",
                "외부 전송 범위와 보관 기간을 확인한 뒤 공유를 시작하세요.",
                400,
            )
        try:
            payload = await sharing.start_share()
        except ShareRelayError as error:
            raise SafeAppError(
                error.code,
                error.safe_message,
                error.status_code,
            ) from error
        await sharing.publish_event(
            make_event(
                "decision_radar_updated",
                decision_radar=(
                    resolved_services.decision_radar_manager.snapshot()
                ),
            )
        )
        await sharing.publish_event(
            make_event(
                "state",
                status=resolved_services.controller.display_status,
            )
        )
        await resolved_services.websocket_manager.broadcast(
            make_event("live_share_status", live_share=payload)
        )
        return payload

    @app.post("/api/share/stop")
    async def stop_live_share() -> dict[str, Any]:
        payload = await sharing.stop_share()
        await resolved_services.websocket_manager.broadcast(
            make_event("live_share_status", live_share=payload)
        )
        return payload

    @app.get("/api/share/access-log")
    async def live_share_access_log() -> dict[str, Any]:
        return await sharing.access_logs()

    @app.get("/api/audio/devices")
    async def audio_devices() -> dict[str, Any]:
        catalog = await resolved_services.controller.list_devices()
        return catalog.to_dict()

    @app.post("/api/audio/refresh")
    async def refresh_audio_devices() -> dict[str, Any]:
        catalog = await resolved_services.controller.list_devices(refresh=True)
        return catalog.to_dict()

    @app.get("/api/settings")
    async def settings() -> dict[str, Any]:
        return _public_settings(resolved_services)

    @app.patch("/api/settings")
    async def update_settings(body: SettingsPatchRequest) -> dict[str, Any]:
        await resolved_services.controller.set_model(body.model)
        return _public_settings(resolved_services)

    @app.get("/api/context")
    async def get_context() -> dict[str, Any]:
        return context_snapshot()

    @app.post("/api/context/profiles")
    async def create_context_profile(
        body: ContextProfileCreateRequest,
    ) -> dict[str, Any]:
        try:
            resolved_services.context_engine.create_profile(body.name, body.description)
        except ContextEngineError as error:
            raise context_failure(error) from error
        return context_snapshot()

    @app.post("/api/context/profiles/{profile_id}/activate")
    async def activate_context_profile(profile_id: str) -> dict[str, Any]:
        try:
            resolved_services.context_engine.activate_profile(profile_id)
        except ContextEngineError as error:
            raise context_failure(error) from error
        payload = context_snapshot()
        await resolved_services.websocket_manager.broadcast(
            make_event(
                "context_updated",
                active_profile_id=payload["active_profile_id"],
                keyterm_count=payload["keyterm_count"],
            )
        )
        return payload

    @app.post("/api/context/profiles/{profile_id}/entries")
    async def add_context_entry(
        profile_id: str,
        body: ContextEntryRequest,
    ) -> dict[str, Any]:
        try:
            resolved_services.context_engine.add_entry(
                profile_id,
                category=body.category,
                canonical=body.canonical,
                variants=body.variants,
            )
        except ContextEngineError as error:
            raise context_failure(error) from error
        return context_snapshot()

    @app.delete("/api/context/profiles/{profile_id}/entries/{entry_id}")
    async def delete_context_entry(profile_id: str, entry_id: str) -> dict[str, Any]:
        try:
            resolved_services.context_engine.delete_entry(profile_id, entry_id)
        except ContextEngineError as error:
            raise context_failure(error) from error
        return context_snapshot()

    @app.post("/api/context/suggestions/generate")
    async def generate_context_suggestions(
        body: ContextSuggestionGenerateRequest,
    ) -> dict[str, Any]:
        session = await resolved_services.session_manager.get_session(body.session_id)
        try:
            created = await asyncio.to_thread(
                resolved_services.context_engine.generate_suggestions,
                body.session_id,
                session.get("segments", []),
            )
        except ContextEngineError as error:
            raise context_failure(error) from error
        payload = context_snapshot()
        payload["created_suggestion_count"] = len(created)
        return payload

    @app.post("/api/context/suggestions/{suggestion_id}/decision")
    async def decide_context_suggestion(
        suggestion_id: str,
        body: ContextSuggestionDecisionRequest,
    ) -> dict[str, Any]:
        try:
            resolved_services.context_engine.decide_suggestion(
                suggestion_id,
                accept=body.accept,
                canonical=body.canonical,
                category=body.category,
                variants=body.variants,
            )
        except ContextEngineError as error:
            raise context_failure(error) from error
        return context_snapshot()

    @app.get("/api/capture/state")
    async def capture_state() -> dict[str, Any]:
        return resolved_services.controller.snapshot()

    @app.post("/api/capture/start")
    async def start_capture(body: StartCaptureRequest) -> dict[str, Any]:
        return await resolved_services.controller.start(
            body.source,
            body.device_id,
            body.model,
            body.stt_provider,
            body.translation_direction,
        )

    @app.post("/api/capture/pause")
    async def pause_capture() -> dict[str, Any]:
        return await resolved_services.controller.pause()

    @app.post("/api/capture/resume")
    async def resume_capture() -> dict[str, Any]:
        return await resolved_services.controller.resume()

    @app.post("/api/capture/stop")
    async def stop_capture() -> dict[str, Any]:
        payload = await resolved_services.controller.stop()
        if (
            resolved_services.analysis_auto_run_on_stop
            and resolved_services.analysis_manager.provider.provider_name != "none"
        ):
            session_id = str(
                payload.get("last_session_id")
                or resolved_services.controller.snapshot().get("last_session_id")
                or ""
            )
            health = await resolved_services.analysis_manager.provider.health_check()
            if session_id and health.available:
                submission = await resolved_services.analysis_manager.submit(session_id)
                payload["analysis_auto_run"] = {
                    "accepted": submission.accepted,
                    "status": submission.status.value,
                    "reason": submission.reason,
                }
        return payload

    @app.get("/api/session/settings")
    async def session_storage_settings() -> dict[str, Any]:
        return resolved_services.repository.storage_settings()

    @app.post("/api/session/settings")
    async def update_session_storage_settings(
        body: SessionStorageSettingsRequest,
    ) -> dict[str, Any]:
        return resolved_services.repository.configure_storage(
            save_original=body.save_original,
            save_translation=body.save_translation,
            save_analysis=body.save_analysis,
        )

    @app.get("/api/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": await resolved_services.session_manager.list_sessions()}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        return await resolved_services.session_manager.get_session(session_id)

    @app.get("/api/sessions/{session_id}/segments")
    async def get_session_segments(session_id: str) -> dict[str, Any]:
        session = await resolved_services.session_manager.get_session(session_id)
        return {
            "session_id": session_id,
            "segments": session.get("segments", []),
        }

    @app.post("/api/sessions/{session_id}/finalize")
    async def finalize_session(session_id: str) -> dict[str, Any]:
        return await resolved_services.session_manager.finalize(session_id)

    @app.post("/api/sessions/{session_id}/recover")
    async def recover_session(session_id: str) -> dict[str, Any]:
        return await resolved_services.session_manager.recover(session_id)

    @app.get("/api/sessions/{session_id}/analysis")
    async def get_session_analysis(session_id: str) -> dict[str, Any]:
        return await resolved_services.analysis_manager.detail(session_id)

    @app.post("/api/sessions/{session_id}/analysis")
    async def create_session_analysis(session_id: str) -> dict[str, Any]:
        manager = resolved_services.analysis_manager
        health = await manager.provider.health_check()
        if manager.provider.provider_name == "none":
            raise SafeAppError(
                "analysis_disabled",
                "회의 분석 방식을 먼저 선택하세요.",
                409,
            )
        if not health.available:
            raise SafeAppError(
                "analysis_provider_unavailable",
                health.reason or "선택한 회의 분석 방식을 사용할 수 없습니다.",
                409,
            )
        submission = await manager.submit(session_id)
        if not submission.accepted:
            raise SafeAppError(
                "analysis_request_rejected",
                "회의 분석 작업을 시작할 수 없습니다.",
                409,
            )
        return {
            "accepted": True,
            "session_id": submission.session_id,
            "status": submission.status.value,
            "provider": manager.provider.provider_name,
            "reason": submission.reason,
        }

    @app.post("/api/sessions/{session_id}/analysis/cancel")
    async def cancel_session_analysis(session_id: str) -> dict[str, Any]:
        cancelled = await resolved_services.analysis_manager.cancel(session_id)
        if not cancelled:
            raise SafeAppError(
                "analysis_not_running",
                "취소할 회의 분석 작업이 없습니다.",
                409,
            )
        return {
            "session_id": session_id,
            "status": "cancelled",
            "cancelled": True,
        }

    @app.post("/api/sessions/{session_id}/analysis/retry")
    async def retry_session_analysis(session_id: str) -> dict[str, Any]:
        manager = resolved_services.analysis_manager
        health = await manager.provider.health_check()
        if manager.provider.provider_name == "none" or not health.available:
            raise SafeAppError(
                "analysis_provider_unavailable",
                health.reason or "선택한 회의 분석 방식을 사용할 수 없습니다.",
                409,
            )
        submission = await manager.retry(session_id)
        if not submission.accepted:
            raise SafeAppError(
                "analysis_retry_rejected",
                "회의 분석을 다시 시작할 수 없습니다.",
                409,
            )
        return {
            "accepted": True,
            "session_id": submission.session_id,
            "status": submission.status.value,
            "provider": manager.provider.provider_name,
            "reason": submission.reason,
        }

    async def session_download(
        session_id: str,
        kind: str,
        filename_suffix: str,
        media_type: str,
    ) -> FileResponse:
        path = await resolved_services.session_manager.get_export_path(
            session_id,
            kind,
        )
        return FileResponse(
            path,
            filename=f"{session_id}_{filename_suffix}",
            media_type=media_type,
        )

    @app.get("/api/sessions/{session_id}/download/json")
    async def download_session_json(session_id: str) -> FileResponse:
        return await session_download(
            session_id,
            "json",
            "session.json",
            "application/json",
        )

    @app.get("/api/sessions/{session_id}/download/original-txt")
    async def download_original_txt(session_id: str) -> FileResponse:
        return await session_download(
            session_id,
            "original-txt",
            "original.txt",
            "text/plain; charset=utf-8",
        )

    @app.get("/api/sessions/{session_id}/download/translation-txt")
    async def download_translation_txt(session_id: str) -> FileResponse:
        return await session_download(
            session_id,
            "translation-txt",
            "korean.txt",
            "text/plain; charset=utf-8",
        )

    @app.get("/api/sessions/{session_id}/download/markdown")
    async def download_markdown(session_id: str) -> FileResponse:
        return await session_download(
            session_id,
            "markdown",
            "meeting_report.md",
            "text/markdown; charset=utf-8",
        )

    @app.get("/api/translation/providers")
    async def translation_providers() -> dict[str, Any]:
        return {
            "providers": await translation_provider_payloads(),
            "selected_provider": (
                resolved_services.translation_manager.provider.provider_name
            ),
        }

    @app.get("/api/translation/worker")
    async def translation_worker_status() -> dict[str, Any]:
        return translation_worker_snapshot()

    @app.post("/api/translation/worker/restart")
    async def restart_translation_worker() -> dict[str, Any]:
        worker = resolved_services.local_translation_worker
        if worker is None:
            raise SafeAppError(
                "translation_worker_unmanaged",
                "이 실행 구성에서는 로컬 번역 Worker를 관리하지 않습니다.",
                409,
            )
        ready = await worker.restart()
        payload = worker.snapshot()
        if not ready:
            raise SafeAppError(
                "translation_worker_unavailable",
                "로컬 번역 Worker를 준비하지 못했습니다. 원문 전사는 계속 사용할 수 있습니다.",
                503,
            )
        return payload

    @app.post("/api/translation/worker/stop")
    async def stop_translation_worker() -> dict[str, Any]:
        worker = resolved_services.local_translation_worker
        if worker is not None:
            await worker.stop()
        return translation_worker_snapshot()

    @app.get("/api/analysis/providers")
    async def analysis_providers() -> dict[str, Any]:
        return {
            "providers": await analysis_provider_payloads(),
            "selected_provider": (
                resolved_services.analysis_manager.provider.provider_name
            ),
        }

    @app.get("/api/analysis/settings")
    async def analysis_settings() -> dict[str, Any]:
        return await analysis_public_settings()

    @app.post("/api/analysis/settings")
    async def update_analysis_settings(
        body: AnalysisSettingsRequest,
    ) -> dict[str, Any]:
        manager = resolved_services.analysis_manager
        if manager.provider.provider_name != body.provider:
            await manager.configure(body.provider)
        elif body.provider != "none":
            health = await manager.provider.health_check()
            if not health.available:
                raise SafeAppError(
                    "analysis_provider_unavailable",
                    health.reason or "선택한 회의 분석 방식을 사용할 수 없습니다.",
                    409,
                )
        if body.auto_run_on_stop is not None:
            resolved_services.analysis_auto_run_on_stop = body.auto_run_on_stop
        return await analysis_public_settings()

    @app.get("/api/decision-radar/providers")
    async def decision_radar_providers() -> dict[str, Any]:
        manager = resolved_services.decision_radar_manager
        return {
            "providers": await decision_radar_provider_payloads(),
            "selected_provider": manager.provider.provider_name,
        }

    @app.get("/api/decision-radar/settings")
    async def decision_radar_settings() -> dict[str, Any]:
        return await decision_radar_public_settings()

    @app.post("/api/decision-radar/settings")
    async def update_decision_radar_settings(
        body: DecisionRadarSettingsRequest,
    ) -> dict[str, Any]:
        manager = resolved_services.decision_radar_manager
        if (
            manager.provider.provider_name != body.provider
            and manager.diagnostics()["processing"]
        ):
            raise SafeAppError(
                "decision_radar_busy",
                "Decision Radar가 현재 분석 중입니다. 잠시 후 다시 적용해 주세요.",
                409,
            )
        if manager.provider.provider_name != body.provider:
            candidate = resolved_services.decision_radar_provider_factories[
                body.provider
            ]()
            try:
                health = await candidate.health_check()
            finally:
                await candidate.close()
            if not health.available:
                raise SafeAppError(
                    "decision_radar_provider_unavailable",
                    health.reason
                    or "선택한 Decision Radar 분석 방식을 사용할 수 없습니다.",
                    409,
                )
            await manager.configure(body.provider)
        elif body.provider != "none":
            health = await manager.provider.health_check()
            if not health.available:
                raise SafeAppError(
                    "decision_radar_provider_unavailable",
                    health.reason
                    or "선택한 Decision Radar 분석 방식을 사용할 수 없습니다.",
                    409,
                )
        return await decision_radar_public_settings()

    @app.get("/api/decision-radar")
    async def get_decision_radar(
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return resolved_services.decision_radar_manager.snapshot(session_id)

    @app.patch("/api/decision-radar/items/{item_id}")
    async def update_decision_radar_item(
        item_id: str,
        body: DecisionRadarItemUpdateRequest,
    ) -> dict[str, Any]:
        try:
            item = await resolved_services.decision_radar_manager.update_item(
                item_id,
                review_status=body.review_status,
                text=body.text,
                assignee=body.assignee,
                due_date=body.due_date,
            )
        except KeyError as error:
            raise SafeAppError(
                "decision_radar_item_not_found",
                "Decision Radar 항목을 찾을 수 없습니다.",
                404,
            ) from error
        except ValueError as error:
            raise SafeAppError(
                "invalid_decision_radar_item",
                "Decision Radar 항목 값이 올바르지 않습니다.",
                422,
            ) from error
        return {
            "item": item,
            "decision_radar": resolved_services.decision_radar_manager.snapshot(),
        }

    @app.delete("/api/decision-radar/items/{item_id}")
    async def delete_decision_radar_item(item_id: str) -> dict[str, Any]:
        try:
            result = await resolved_services.decision_radar_manager.delete_item(
                item_id
            )
        except KeyError as error:
            raise SafeAppError(
                "decision_radar_item_not_found",
                "Decision Radar 항목을 찾을 수 없습니다.",
                404,
            ) from error
        return {
            **result,
            "decision_radar": resolved_services.decision_radar_manager.snapshot(),
        }

    @app.get("/api/translation/settings")
    async def translation_settings() -> dict[str, Any]:
        return await translation_public_settings()

    @app.post("/api/translation/settings")
    async def update_translation_settings(
        body: TranslationSettingsRequest,
    ) -> dict[str, Any]:
        manager = resolved_services.translation_manager
        if manager.provider.provider_name == body.provider:
            return await translation_public_settings()
        provider = resolved_services.translation_provider_factories[body.provider]()
        health = await provider.health_check()
        if not health.available:
            await provider.close()
            raise SafeAppError(
                "translation_provider_unavailable",
                health.reason or "선택한 번역 방식을 현재 사용할 수 없습니다.",
                409,
            )
        try:
            await manager.switch_provider(
                provider,
                cancel_pending=True,
                require_available=True,
            )
        except TranslationProviderError as error:
            await provider.close()
            raise SafeAppError(
                "translation_provider_unavailable",
                error.safe_message,
                409,
            ) from error
        return await translation_public_settings()

    @app.post("/api/translation/test")
    async def test_translation(body: TranslationTestRequest) -> dict[str, Any]:
        manager = resolved_services.translation_manager
        provider = manager.provider
        health = await provider.health_check()
        if provider.provider_name == "none":
            raise SafeAppError(
                "translation_disabled",
                "번역 방식을 먼저 선택하세요.",
                409,
            )
        if provider.provider_name == "gemini":
            raise SafeAppError(
                "gemini_test_disabled",
                "Gemini API는 실제 final 원문이 발생할 때만 호출합니다.",
                409,
            )
        if not health.available:
            raise SafeAppError(
                "translation_provider_unavailable",
                health.reason or "선택한 번역 방식을 현재 사용할 수 없습니다.",
                409,
            )
        request = TranslationRequest(
            segment_id=f"translation-test-{uuid4()}",
            source_text=body.text,
            source_language=body.source_language,
            target_language=body.target_language,
            source="test",
            glossary_terms=manager.glossary.terms,
        )
        try:
            result = await asyncio.wait_for(
                provider.translate(request),
                timeout=float(
                    getattr(provider, "timeout_seconds", manager.timeout_seconds)
                ),
            )
        except TranslationProviderError as error:
            raise SafeAppError(
                error.code.value.lower(),
                error.safe_message,
                503,
            ) from error
        except asyncio.TimeoutError as error:
            raise SafeAppError(
                "request_timeout",
                "번역 요청 시간이 초과되었습니다.",
                504,
            ) from error
        except Exception as error:
            LOGGER.error("Translation test failed: %s", exception_kind(error))
            raise SafeAppError(
                "translation_test_failed",
                "번역 테스트를 완료하지 못했습니다.",
                503,
            ) from error
        if (
            result.status is not TranslationStatus.COMPLETED
            or not (result.translated_text or "").strip()
        ):
            raise SafeAppError(
                "invalid_response",
                "번역 서버가 올바른 번역문을 반환하지 않았습니다.",
                502,
            )
        return {"success": True, **result.to_dict()}

    @app.post("/api/translation/retry/{segment_id}")
    async def retry_translation(segment_id: str) -> dict[str, Any]:
        submission = await resolved_services.translation_manager.retry(segment_id)
        if not submission.accepted:
            status_code = 404 if submission.reason == "segment_not_found" else 409
            raise SafeAppError(
                "translation_retry_rejected",
                "해당 문장의 번역을 다시 등록할 수 없습니다.",
                status_code,
            )
        return {
            "type": "translation_pending",
            "segment_id": segment_id,
            "provider": (
                resolved_services.translation_manager.provider.provider_name
            ),
            "status": "pending",
            "accepted": True,
            "queue_size": submission.queue_size,
        }

    @app.websocket("/ws/live")
    async def live(websocket: WebSocket) -> None:
        manager = resolved_services.websocket_manager
        await manager.connect(websocket)
        await manager.send_to(
            websocket,
            make_event(
                "snapshot",
                capture=resolved_services.controller.snapshot(),
                settings=_public_settings(resolved_services),
                translation=await translation_public_settings(),
                analysis=await analysis_public_settings(),
                decision_radar=(
                    resolved_services.decision_radar_manager.snapshot()
                ),
                live_share=sharing.snapshot(),
                context=context_snapshot(),
                session={
                    "active_session_id": (
                        resolved_services.session_manager.active_session_id
                    ),
                    "last_session_id": resolved_services.controller.snapshot().get(
                        "last_session_id"
                    ),
                    "storage": resolved_services.repository.storage_settings(),
                },
            ),
        )
        try:
            while True:
                message = await websocket.receive_json()
                if isinstance(message, dict) and message.get("type") == "ping":
                    await manager.send_to(websocket, make_event("pong"))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await manager.disconnect(websocket)

    static_dir = (
        resolved_services.settings.static_dir
        or resolved_services.settings.project_root / "frontend" / "static"
    )
    static_dir = Path(static_dir)
    app.mount("/static", StaticFiles(directory=static_dir, check_dir=False), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        path = static_dir / "index.html"
        if not path.is_file():
            raise SafeAppError(
                "frontend_missing",
                "프론트엔드 파일을 찾을 수 없습니다.",
                503,
            )
        return FileResponse(path)

    @app.get("/captions", include_in_schema=False)
    async def captions_window() -> FileResponse:
        path = static_dir / "captions.html"
        if not path.is_file():
            raise SafeAppError(
                "caption_window_missing",
                "자막 전용 화면을 찾을 수 없습니다.",
                503,
            )
        return FileResponse(path)

    @app.get("/decision-radar", include_in_schema=False)
    async def decision_radar_window() -> FileResponse:
        path = static_dir / "decision-radar.html"
        if not path.is_file():
            raise SafeAppError(
                "decision_radar_window_missing",
                "Decision Radar 결과 전용 화면을 찾을 수 없습니다.",
                503,
            )
        return FileResponse(path)

    return app


app = create_app()
