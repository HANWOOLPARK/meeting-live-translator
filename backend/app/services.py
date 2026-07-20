from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import (
    AnalysisManager,
    AnalysisProvider,
    GeminiAnalysisProvider,
    NoneAnalysisProvider,
    OpenAIAnalysisProvider,
    RuleBasedAnalysisProvider,
)
from .audio.devices import PyAudioWPatchDeviceProvider
from .capture.controller import (
    CaptureController,
    CaptureFactory,
    DeepgramFactory,
    EngineFactory,
)
from .config.settings import AppSettings
from .context_engine import ContextEngine
from .decision_radar import (
    DecisionRadarManager,
    DecisionRadarProvider,
    GeminiDecisionRadarProvider,
    NoneDecisionRadarProvider,
    OpenAIDecisionRadarProvider,
)
from .sessions import JsonlSessionRepository, SessionManager, StoragePolicy
from .translation import (
    GeminiTranslationProvider,
    LocalTranslationWorkerSupervisor,
    NoneTranslationProvider,
    OpenAITranslationProvider,
    SidecarLocalTranslationProvider,
    TranslationManager,
    TranslationProvider,
    TranslationGlossary,
    load_glossary_file,
)
from .websocket.events import make_event
from .websocket.manager import WebSocketManager


LOGGER = logging.getLogger(__name__)
TranslationProviderFactory = Callable[[], TranslationProvider]
AnalysisProviderFactory = Callable[[], AnalysisProvider]
DecisionRadarProviderFactory = Callable[[], DecisionRadarProvider]


@dataclass(slots=True)
class AppServices:
    settings: AppSettings
    device_provider: PyAudioWPatchDeviceProvider
    websocket_manager: WebSocketManager
    context_engine: ContextEngine
    repository: JsonlSessionRepository
    session_manager: SessionManager
    translation_manager: TranslationManager
    translation_provider_factories: Mapping[str, TranslationProviderFactory]
    local_translation_worker: LocalTranslationWorkerSupervisor | None
    analysis_manager: AnalysisManager
    analysis_provider_factories: Mapping[str, AnalysisProviderFactory]
    analysis_auto_run_on_stop: bool
    decision_radar_manager: DecisionRadarManager
    decision_radar_provider_factories: Mapping[str, DecisionRadarProviderFactory]
    controller: CaptureController


def _resolved_local_path(project_root: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return str(path.resolve())


def _translation_provider_factories(
    settings: AppSettings,
    local_worker: LocalTranslationWorkerSupervisor,
) -> dict[str, TranslationProviderFactory]:
    return {
        "none": NoneTranslationProvider,
        "local": lambda: SidecarLocalTranslationProvider(local_worker),
        "openai": lambda: OpenAITranslationProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_translation_model,
        ),
        "gemini": lambda: GeminiTranslationProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_translation_model,
            timeout_seconds=settings.gemini_translation_timeout_seconds,
            max_retries=settings.gemini_translation_max_retries,
            context_segments=settings.gemini_translation_context_segments,
        ),
    }


def _analysis_provider_factories(
    settings: AppSettings,
) -> dict[str, AnalysisProviderFactory]:
    return {
        "none": NoneAnalysisProvider,
        "rule_based": RuleBasedAnalysisProvider,
        "openai": lambda: OpenAIAnalysisProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_analysis_model,
        ),
        "gemini": lambda: GeminiAnalysisProvider(
            api_key=settings.gemini_api_key,
            model=(
                settings.gemini_analysis_model
                or settings.gemini_translation_model
            ),
        ),
    }


def _decision_radar_provider_factories(
    settings: AppSettings,
) -> dict[str, DecisionRadarProviderFactory]:
    return {
        "none": NoneDecisionRadarProvider,
        "openai": lambda: OpenAIDecisionRadarProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_decision_radar_model,
        ),
        "gemini": lambda: GeminiDecisionRadarProvider(
            api_key=settings.gemini_api_key,
            model=(
                settings.gemini_decision_radar_model
                or settings.gemini_analysis_model
                or settings.gemini_translation_model
            ),
        ),
    }


def _translation_event_sink(
    websocket_manager: WebSocketManager,
    repository: JsonlSessionRepository,
    decision_radar_manager: DecisionRadarManager | None = None,
) -> Callable[[dict[str, Any]], Any]:
    async def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "translation_error"))
        public_event = dict(event)
        if "event_id" not in public_event:
            public_event = make_event(
                event_type,
                **{key: value for key, value in public_event.items() if key != "type"},
            )
        if event_type in {"translation", "translation_error"}:
            session_id = str(public_event.get("session_id", "")).strip()
            if session_id:
                try:
                    if event_type == "translation":
                        await asyncio.to_thread(
                            repository.append_translation,
                            session_id,
                            public_event,
                        )
                    else:
                        await asyncio.to_thread(
                            repository.append_translation_error,
                            session_id,
                            public_event,
                        )
                except Exception as error:
                    # Persistence failure must not suppress the browser result or
                    # include source text/local paths in logs.
                    LOGGER.error(
                        "Translation persistence failed: %s",
                        type(error).__name__,
                    )
            if event_type == "translation" and decision_radar_manager is not None:
                try:
                    await decision_radar_manager.update_translation(public_event)
                except Exception as error:
                    LOGGER.warning(
                        "Decision Radar translation update failed: %s",
                        type(error).__name__,
                    )
        await websocket_manager.broadcast(public_event)

    return sink


def _session_event_sink(
    websocket_manager: WebSocketManager,
) -> Callable[[dict[str, Any]], Any]:
    async def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "session_status"))
        public_event = dict(event)
        if "event_id" not in public_event:
            public_event = make_event(
                event_type,
                **{key: value for key, value in public_event.items() if key != "type"},
            )
        await websocket_manager.broadcast(public_event)

    return sink


def _analysis_event_sink(
    websocket_manager: WebSocketManager,
) -> Callable[[dict[str, Any]], Any]:
    async def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "analysis_status"))
        public_event = dict(event)
        if "event_id" not in public_event:
            public_event = make_event(
                event_type,
                **{key: value for key, value in public_event.items() if key != "type"},
            )
        # Analysis result bodies are intentionally fetched over REST. Keeping
        # them out of WebSocket events prevents one large meeting from
        # monopolizing the bounded client queues.
        public_event.pop("result", None)
        public_event.pop("analysis", None)
        await websocket_manager.broadcast(public_event)

    return sink


def _decision_radar_event_sink(
    websocket_manager: WebSocketManager,
) -> Callable[[dict[str, Any]], Any]:
    async def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "decision_radar_status"))
        public_event = dict(event)
        if "event_id" not in public_event:
            public_event = make_event(
                event_type,
                **{key: value for key, value in public_event.items() if key != "type"},
            )
        await websocket_manager.broadcast(public_event)

    return sink


def build_services(
    settings: AppSettings | None = None,
    *,
    device_provider: PyAudioWPatchDeviceProvider | None = None,
    websocket_manager: WebSocketManager | None = None,
    context_engine: ContextEngine | None = None,
    repository: JsonlSessionRepository | None = None,
    capture_factory: CaptureFactory | None = None,
    engine_factory: EngineFactory | None = None,
    deepgram_factory: DeepgramFactory | None = None,
    translation_manager: TranslationManager | None = None,
    session_manager: SessionManager | None = None,
    analysis_manager: AnalysisManager | None = None,
    decision_radar_manager: DecisionRadarManager | None = None,
    translation_provider_factories: Mapping[
        str, TranslationProviderFactory
    ] | None = None,
    analysis_provider_factories: Mapping[
        str, AnalysisProviderFactory
    ] | None = None,
    decision_radar_provider_factories: Mapping[
        str, DecisionRadarProviderFactory
    ] | None = None,
) -> AppServices:
    resolved_settings = settings or AppSettings.from_env()
    provider = device_provider or PyAudioWPatchDeviceProvider()
    manager = websocket_manager or WebSocketManager()
    contexts = context_engine or ContextEngine(
        resolved_settings.project_root / "data" / "context_engine.json"
    )
    session_repository = repository or JsonlSessionRepository(
        resolved_settings.session_dir
        or resolved_settings.project_root / "data" / "sessions",
        phase3=True,
        storage_policy=StoragePolicy(
            save_original=resolved_settings.session_save_original,
            save_translation=resolved_settings.session_save_translation,
            save_analysis=resolved_settings.session_save_analysis,
            save_audio=False,
        ),
    )
    sessions = session_manager or SessionManager(
        session_repository,
        event_sink=_session_event_sink(manager),
    )
    radar_factories = dict(
        decision_radar_provider_factories
        or _decision_radar_provider_factories(resolved_settings)
    )
    radar_missing = {"none", "openai", "gemini"}.difference(radar_factories)
    if radar_missing:
        raise ValueError("Decision Radar provider factories are incomplete")
    radar = decision_radar_manager or DecisionRadarManager(
        store_path=resolved_settings.project_root / "data" / "decision_radar.json",
        provider_factories=radar_factories,
        selected_provider=resolved_settings.decision_radar_provider,
        batch_size=resolved_settings.decision_radar_batch_size,
        batch_wait_seconds=resolved_settings.decision_radar_batch_wait_seconds,
        context_window_segments=resolved_settings.decision_radar_context_segments,
        queue_max_size=resolved_settings.decision_radar_queue_max_size,
        timeout_seconds=resolved_settings.decision_radar_timeout_seconds,
        max_retries=resolved_settings.decision_radar_max_retries,
        event_sink=_decision_radar_event_sink(manager),
        context_supplier=contexts.snapshot,
    )
    local_worker: LocalTranslationWorkerSupervisor | None = None
    if translation_provider_factories is None:
        runtime_python = resolved_settings.local_translation_runtime_python or (
            resolved_settings.project_root
            / ".venv-translation"
            / "Scripts"
            / "python.exe"
        )
        model_value = (
            resolved_settings.local_translation_model
            or "models/translation/m2m100_418m-int8"
        )
        model_path = Path(
            _resolved_local_path(resolved_settings.project_root, model_value)
            or resolved_settings.project_root / model_value
        )
        local_worker = LocalTranslationWorkerSupervisor(
            project_root=resolved_settings.project_root,
            runtime_python=Path(runtime_python),
            worker_script=(
                resolved_settings.project_root / "scripts" / "local_translation_worker.py"
            ),
            model_path=model_path,
            pid_file=(
                resolved_settings.project_root / ".run" / "translation-worker.pid"
            ),
            stderr_path=(
                resolved_settings.project_root
                / ".run"
                / "translation-worker.stderr.log"
            ),
            request_timeout_seconds=max(
                30.0,
                resolved_settings.translation_timeout_seconds + 5.0,
            ),
        )
        provider_factories = dict(
            _translation_provider_factories(resolved_settings, local_worker)
        )
    else:
        provider_factories = dict(translation_provider_factories)
        provider_factories.setdefault(
            "gemini",
            lambda: GeminiTranslationProvider(
                api_key=resolved_settings.gemini_api_key,
                model=resolved_settings.gemini_translation_model,
                timeout_seconds=resolved_settings.gemini_translation_timeout_seconds,
                max_retries=resolved_settings.gemini_translation_max_retries,
                context_segments=resolved_settings.gemini_translation_context_segments,
            ),
        )
    missing = {"none", "local", "openai", "gemini"}.difference(provider_factories)
    if missing:
        raise ValueError("Translation provider factories are incomplete")
    try:
        glossary = load_glossary_file(resolved_settings.translation_glossary_file)
    except Exception as error:
        LOGGER.warning(
            "Custom translation glossary was ignored: %s",
            type(error).__name__,
        )
        glossary = TranslationGlossary()
    translations = translation_manager or TranslationManager(
        provider_factories[resolved_settings.translation_provider](),
        queue_max_size=resolved_settings.translation_queue_max_size,
        max_concurrency=resolved_settings.translation_max_concurrency,
        timeout_seconds=resolved_settings.translation_timeout_seconds,
        max_retries=resolved_settings.translation_max_retries,
        context_segments=resolved_settings.translation_context_segments,
        translate_unknown=resolved_settings.translation_translate_unknown,
        glossary=glossary,
        event_sink=_translation_event_sink(manager, session_repository, radar),
    )
    analysis_factories = dict(
        analysis_provider_factories or _analysis_provider_factories(resolved_settings)
    )
    analysis_missing = {"none", "rule_based", "openai", "gemini"}.difference(
        analysis_factories
    )
    if analysis_missing:
        raise ValueError("Analysis provider factories are incomplete")
    analyses = analysis_manager or AnalysisManager(
        session_repository,
        provider_factories=analysis_factories,
        selected_provider=resolved_settings.analysis_provider,
        timeout_seconds=resolved_settings.analysis_timeout_seconds,
        max_retries=resolved_settings.analysis_max_retries,
        max_segments_per_chunk=resolved_settings.analysis_max_segments_per_chunk,
        max_characters_per_chunk=resolved_settings.analysis_max_chars_per_chunk,
        event_sink=_analysis_event_sink(manager),
    )
    controller = CaptureController(
        resolved_settings,
        provider,
        manager,
        session_repository,
        context_engine=contexts,
        capture_factory=capture_factory,
        engine_factory=engine_factory,
        deepgram_factory=deepgram_factory,
        translation_manager=translations,
        session_manager=sessions,
        decision_radar_manager=radar,
    )
    return AppServices(
        settings=resolved_settings,
        device_provider=provider,
        websocket_manager=manager,
        context_engine=contexts,
        repository=session_repository,
        session_manager=sessions,
        translation_manager=translations,
        translation_provider_factories=provider_factories,
        local_translation_worker=local_worker,
        analysis_manager=analyses,
        analysis_provider_factories=analysis_factories,
        analysis_auto_run_on_stop=resolved_settings.analysis_auto_run_on_stop,
        decision_radar_manager=radar,
        decision_radar_provider_factories=radar_factories,
        controller=controller,
    )
