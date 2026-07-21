(() => {
  "use strict";

  const i18n = window.MLTI18n;
  if (!i18n) throw new Error("UI internationalization module is unavailable.");
  const { t } = i18n;
  const UI_LOCALE = i18n.language === "en" ? "en-US" : "ko-KR";
  i18n.bindLanguageControls(document);

  const API_TIMEOUT_MS = 10_000;
  const MAX_TRANSCRIPTS = 500;
  const RECONNECT_MAX_MS = 15_000;
  const TRANSLATION_DIRECTIONS = Object.freeze([
    "ja_to_ko",
    "ja_to_en",
    "en_to_ko",
    "en_to_ja",
    "ko_to_ja",
    "ko_to_en",
  ]);
  const DEFAULT_PARTIAL_TEXT = t("캡처를 시작하면 현재 발화가 여기에 표시됩니다.");
  let captionWindow = null;
  let mediaCaptionWindow = null;
  let decisionRadarWindow = null;
  let captionChannel = null;
  let decisionRadarChannel = null;
  try {
    if (typeof BroadcastChannel === "function") {
      captionChannel = new BroadcastChannel("mlt-caption-window-v1");
    }
  } catch (_error) {
    captionChannel = null;
  }
  try {
    if (typeof BroadcastChannel === "function") {
      decisionRadarChannel = new BroadcastChannel("mlt-decision-radar-window-v1");
    }
  } catch (_error) {
    decisionRadarChannel = null;
  }

  const state = {
    source: "system",
    captionViewMode: "both",
    devices: { outputs: [], loopbacks: [], microphones: [] },
    defaults: { system: null, microphone: null },
    selectedDevice: { system: null, microphone: null },
    stt: { provider: "local", deepgramConfigured: false, model: "nova-3", language: "ja" },
    translationDirection: "ja_to_ko",
    context: {
      activeProfileId: "general",
      profiles: [],
      suggestions: [],
      keytermCount: 0,
      loading: true,
      busy: false,
    },
    captureState: "idle",
    displayState: "idle",
    requestInFlight: false,
    ws: null,
    reconnectAttempt: 0,
    reconnectTimer: null,
    intentionalClose: false,
    lastLevelAt: 0,
    renderedLevel: 0,
    peakLevel: 0,
    seenFinals: new Set(),
    fallbackFinals: new Map(),
    translation: {
      providers: new Map(),
      selected: "none",
      applied: "none",
      settings: {},
      loading: true,
      saving: false,
      testing: false,
      status: "disabled",
      cards: new Map(),
      deferredEvents: new Map(),
      worker: {
        state: "unknown",
        available: false,
        configured: false,
        modelInstalled: false,
        pid: null,
        restartCount: 0,
        model: "",
        lastError: "",
      },
      workerPollTimer: null,
      workerStatusLoading: false,
    },
    sessions: {
      current: null,
      list: [],
      selectedId: "",
      restoredId: "",
      loadingList: false,
      loadingSession: false,
      savingSettings: false,
      downloading: false,
      settings: {
        saveOriginal: true,
        saveTranslation: true,
        saveAnalysis: true,
      },
      savedSettings: {
        saveOriginal: true,
        saveTranslation: true,
        saveAnalysis: true,
      },
      segmentsBySession: new Map(),
      originalSegmentIds: new Map(),
      translatedSegmentIds: new Map(),
    },
    analysis: {
      providers: new Map(),
      selected: "none",
      applied: "none",
      settings: {
        model: "",
        autoRunOnStop: false,
      },
      savedSettings: {
        provider: "none",
        autoRunOnStop: false,
      },
      sessionId: "",
      status: "idle",
      result: null,
      metadata: {},
      loading: true,
      loadingResult: false,
      saving: false,
      actionInFlight: false,
      pollTimer: null,
      pollAttempts: 0,
    },
    decisionRadar: {
      providers: new Map(),
      selected: "none",
      applied: "none",
      status: "disabled",
      model: "",
      sessionId: "",
      queueSize: 0,
      queueMaxSize: 0,
      items: [],
      loading: true,
      saving: false,
      mutating: false,
      editingId: "",
      confirmingProvider: "",
      activeTab: "core",
      unreadByTab: { core: 0, decision: 0, action: 0, issues: 0 },
      knownItemIds: new Set(),
      tabTrackingInitialized: false,
      pinnedToLatest: true,
    },
    liveShare: {
      configured: false,
      active: false,
      status: "loading",
      viewerUrl: "",
      expiresAt: "",
      requestInFlight: false,
      consentConfirmed: false,
      lastLatencyMs: null,
      lastErrorCode: "",
      accessHistory: [],
      selectedAccessRoomId: "",
      accessLogLoading: false,
      accessLogPollTimer: null,
      verifiedAttendeeCount: 0,
    },
  };

  const elements = {
    appStatus: document.querySelector("#appStatus"),
    appStatusPill: document.querySelector("#appStatusPill"),
    wsStatus: document.querySelector("#wsStatus"),
    wsStatusPill: document.querySelector("#wsStatusPill"),
    sourceInputs: [...document.querySelectorAll('input[name="audioSource"]')],
    deviceSelect: document.querySelector("#deviceSelect"),
    deviceLabel: document.querySelector("#deviceLabel"),
    deviceHint: document.querySelector("#deviceHint"),
    sttProviderSelect: document.querySelector("#sttProviderSelect"),
    sttProviderHint: document.querySelector("#sttProviderHint"),
    translationDirectionSelect: document.querySelector("#translationDirectionSelect"),
    translationDirectionHint: document.querySelector("#translationDirectionHint"),
    modelSelect: document.querySelector("#modelSelect"),
    refreshDevicesButton: document.querySelector("#refreshDevicesButton"),
    startButton: document.querySelector("#startButton"),
    pauseButton: document.querySelector("#pauseButton"),
    resumeButton: document.querySelector("#resumeButton"),
    stopButton: document.querySelector("#stopButton"),
    levelValue: document.querySelector("#levelValue"),
    audioLevel: document.querySelector("#audioLevel"),
    levelFill: document.querySelector("#levelFill"),
    levelPeak: document.querySelector("#levelPeak"),
    loopbackGuidance: document.querySelector("#loopbackGuidance"),
    deviceWarnings: document.querySelector("#deviceWarnings"),
    sttRuntimeHealth: document.querySelector("#sttRuntimeHealth"),
    audioRuntimeHealth: document.querySelector("#audioRuntimeHealth"),
    translationQueueHealth: document.querySelector("#translationQueueHealth"),
    liveShareStatusBadge: document.querySelector("#liveShareStatusBadge"),
    liveShareConsent: document.querySelector("#liveShareConsent"),
    startLiveShareButton: document.querySelector("#startLiveShareButton"),
    stopLiveShareButton: document.querySelector("#stopLiveShareButton"),
    liveShareLinkPanel: document.querySelector("#liveShareLinkPanel"),
    liveShareUrl: document.querySelector("#liveShareUrl"),
    copyLiveShareLinkButton: document.querySelector("#copyLiveShareLinkButton"),
    liveShareFeedback: document.querySelector("#liveShareFeedback"),
    liveShareError: document.querySelector("#liveShareError"),
    liveShareDetails: document.querySelector("#liveShareDetails"),
    liveShareAuditPanel: document.querySelector("#liveShareAuditPanel"),
    refreshLiveShareAuditButton: document.querySelector("#refreshLiveShareAuditButton"),
    liveShareAuditRoomSelect: document.querySelector("#liveShareAuditRoomSelect"),
    liveShareVerifiedCount: document.querySelector("#liveShareVerifiedCount"),
    liveShareRejectedCount: document.querySelector("#liveShareRejectedCount"),
    liveShareAttendeeList: document.querySelector("#liveShareAttendeeList"),
    liveShareAuditEmpty: document.querySelector("#liveShareAuditEmpty"),
    liveShareAuditError: document.querySelector("#liveShareAuditError"),
    contextStatusBadge: document.querySelector("#contextStatusBadge"),
    contextProfileSelect: document.querySelector("#contextProfileSelect"),
    activateContextProfileButton: document.querySelector("#activateContextProfileButton"),
    contextProfileHint: document.querySelector("#contextProfileHint"),
    contextProfileNameInput: document.querySelector("#contextProfileNameInput"),
    createContextProfileButton: document.querySelector("#createContextProfileButton"),
    contextEntryForm: document.querySelector("#contextEntryForm"),
    contextEntryCategory: document.querySelector("#contextEntryCategory"),
    contextCanonicalInput: document.querySelector("#contextCanonicalInput"),
    contextVariantsInput: document.querySelector("#contextVariantsInput"),
    addContextEntryButton: document.querySelector("#addContextEntryButton"),
    contextEntryList: document.querySelector("#contextEntryList"),
    generateContextSuggestionsButton: document.querySelector("#generateContextSuggestionsButton"),
    contextSuggestionList: document.querySelector("#contextSuggestionList"),
    contextFeedback: document.querySelector("#contextFeedback"),
    contextError: document.querySelector("#contextError"),
    errorBanner: document.querySelector("#errorBanner"),
    errorMessage: document.querySelector("#errorMessage"),
    dismissErrorButton: document.querySelector("#dismissErrorButton"),
    autoScrollToggle: document.querySelector("#autoScrollToggle"),
    captionCard: document.querySelector("#captions"),
    captionTitle: document.querySelector("#captionTitle"),
    captionViewModeSelect: document.querySelector("#captionViewModeSelect"),
    openCaptionWindowButton: document.querySelector("#openCaptionWindowButton"),
    openMediaCaptionWindowButton: document.querySelector("#openMediaCaptionWindowButton"),
    fontSizeRange: document.querySelector("#fontSizeRange"),
    fontSizeValue: document.querySelector("#fontSizeValue"),
    partialPanel: document.querySelector("#partialPanel"),
    partialText: document.querySelector("#partialText"),
    partialLanguage: document.querySelector("#partialLanguage"),
    transcriptScroll: document.querySelector("#transcriptScroll"),
    transcriptList: document.querySelector("#transcriptList"),
    emptyState: document.querySelector("#emptyState"),
    transcriptItemTemplate: document.querySelector("#transcriptItemTemplate"),
    latencyHint: document.querySelector("#latencyHint"),
    translationMethodSelect: document.querySelector("#translationMethodSelect"),
    translationMethodHint: document.querySelector("#translationMethodHint"),
    translationApplyButton: document.querySelector("#translationApplyButton"),
    translationTestButton: document.querySelector("#translationTestButton"),
    translationTestResult: document.querySelector("#translationTestResult"),
    translationConfigError: document.querySelector("#translationConfigError"),
    translationCard: document.querySelector("#translationCard"),
    translationConfigToggle: document.querySelector("#translationConfigToggle"),
    translationBarDirection: document.querySelector("#translationBarDirection"),
    translationBarProvider: document.querySelector("#translationBarProvider"),
    translationGlobalStatus: document.querySelector("#translationGlobalStatus"),
    translationTitle: document.querySelector("#translationTitle"),
    providerAvailabilityList: document.querySelector("#providerAvailabilityList"),
    providerDetailProvider: document.querySelector("#providerDetailProvider"),
    providerDetailAvailability: document.querySelector("#providerDetailAvailability"),
    providerDetailExternal: document.querySelector("#providerDetailExternal"),
    providerDetailApiKey: document.querySelector("#providerDetailApiKey"),
    providerDetailLocalModel: document.querySelector("#providerDetailLocalModel"),
    providerDetailStatus: document.querySelector("#providerDetailStatus"),
    providerDetailWorkerRow: document.querySelector("#providerDetailWorkerRow"),
    providerDetailWorkerStatus: document.querySelector("#providerDetailWorkerStatus"),
    translationSecurityNotice: document.querySelector("#translationSecurityNotice"),
    translationGeminiNotice: document.querySelector("#translationGeminiNotice"),
    translationLocalNotice: document.querySelector("#translationLocalNotice"),
    decisionRadarStatusBadge: document.querySelector("#decisionRadarStatusBadge"),
    openDecisionRadarWindowButton: document.querySelector("#openDecisionRadarWindowButton"),
    decisionRadarProviderSelect: document.querySelector("#decisionRadarProviderSelect"),
    decisionRadarProviderHint: document.querySelector("#decisionRadarProviderHint"),
    decisionRadarAvailability: document.querySelector("#decisionRadarAvailability"),
    decisionRadarModel: document.querySelector("#decisionRadarModel"),
    decisionRadarApplyButton: document.querySelector("#decisionRadarApplyButton"),
    decisionRadarSecurityNotice: document.querySelector("#decisionRadarSecurityNotice"),
    decisionRadarFeedback: document.querySelector("#decisionRadarFeedback"),
    decisionRadarError: document.querySelector("#decisionRadarError"),
    decisionRadarSession: document.querySelector("#decisionRadarSession"),
    decisionRadarQueue: document.querySelector("#decisionRadarQueue"),
    decisionRadarTabs: document.querySelector("#decisionRadarTabs"),
    decisionRadarCoreTabCount: document.querySelector("#decisionRadarCoreTabCount"),
    decisionRadarDecisionTabCount: document.querySelector("#decisionRadarDecisionTabCount"),
    decisionRadarActionTabCount: document.querySelector("#decisionRadarActionTabCount"),
    decisionRadarIssuesTabCount: document.querySelector("#decisionRadarIssuesTabCount"),
    decisionRadarLatestButton: document.querySelector("#decisionRadarLatestButton"),
    decisionRadarLatestCount: document.querySelector("#decisionRadarLatestCount"),
    decisionRadarScroll: document.querySelector("#decisionRadarScroll"),
    decisionRadarEmpty: document.querySelector("#decisionRadarEmpty"),
    decisionRadarDecisionsGroup: document.querySelector("#decisionRadarDecisionsGroup"),
    decisionRadarActionsGroup: document.querySelector("#decisionRadarActionsGroup"),
    decisionRadarQuestionsGroup: document.querySelector("#decisionRadarQuestionsGroup"),
    decisionRadarConfirmationsGroup: document.querySelector("#decisionRadarConfirmationsGroup"),
    decisionRadarDecisions: document.querySelector("#decisionRadarDecisions"),
    decisionRadarActions: document.querySelector("#decisionRadarActions"),
    decisionRadarQuestions: document.querySelector("#decisionRadarQuestions"),
    decisionRadarConfirmations: document.querySelector("#decisionRadarConfirmations"),
    decisionRadarDecisionsCount: document.querySelector("#decisionRadarDecisionsCount"),
    decisionRadarActionsCount: document.querySelector("#decisionRadarActionsCount"),
    decisionRadarQuestionsCount: document.querySelector("#decisionRadarQuestionsCount"),
    decisionRadarConfirmationsCount: document.querySelector("#decisionRadarConfirmationsCount"),
    decisionRadarHistoryDetails: document.querySelector("#decisionRadarHistoryDetails"),
    decisionRadarHistoryCount: document.querySelector("#decisionRadarHistoryCount"),
    decisionRadarHistory: document.querySelector("#decisionRadarHistory"),
    sessionStatusBadge: document.querySelector("#sessionStatusBadge"),
    sessionViewMode: document.querySelector("#sessionViewMode"),
    currentSessionId: document.querySelector("#currentSessionId"),
    currentSessionTime: document.querySelector("#currentSessionTime"),
    currentSessionSource: document.querySelector("#currentSessionSource"),
    currentSessionModel: document.querySelector("#currentSessionModel"),
    currentSessionTranslation: document.querySelector("#currentSessionTranslation"),
    currentSessionOriginalCount: document.querySelector("#currentSessionOriginalCount"),
    currentSessionTranslationCount: document.querySelector("#currentSessionTranslationCount"),
    saveOriginalToggle: document.querySelector("#saveOriginalToggle"),
    saveTranslationToggle: document.querySelector("#saveTranslationToggle"),
    saveAnalysisToggle: document.querySelector("#saveAnalysisToggle"),
    saveSessionSettingsButton: document.querySelector("#saveSessionSettingsButton"),
    refreshSessionsButton: document.querySelector("#refreshSessionsButton"),
    sessionSelect: document.querySelector("#sessionSelect"),
    sessionSelectionHint: document.querySelector("#sessionSelectionHint"),
    restoreSessionButton: document.querySelector("#restoreSessionButton"),
    copyOriginalButton: document.querySelector("#copyOriginalButton"),
    copyTranslationButton: document.querySelector("#copyTranslationButton"),
    sessionDownloadButtons: [...document.querySelectorAll("[data-session-download]")],
    sessionFeedback: document.querySelector("#sessionFeedback"),
    sessionError: document.querySelector("#sessionError"),
    analysisStatusBadge: document.querySelector("#analysisStatusBadge"),
    analysisProviderSelect: document.querySelector("#analysisProviderSelect"),
    analysisProviderHint: document.querySelector("#analysisProviderHint"),
    analysisAutoRunToggle: document.querySelector("#analysisAutoRunToggle"),
    analysisProviderAvailability: document.querySelector("#analysisProviderAvailability"),
    analysisModelLabel: document.querySelector("#analysisModelLabel"),
    analysisApplyButton: document.querySelector("#analysisApplyButton"),
    analysisTargetSession: document.querySelector("#analysisTargetSession"),
    generateAnalysisButton: document.querySelector("#generateAnalysisButton"),
    cancelAnalysisButton: document.querySelector("#cancelAnalysisButton"),
    retryAnalysisButton: document.querySelector("#retryAnalysisButton"),
    analysisFeedback: document.querySelector("#analysisFeedback"),
    analysisError: document.querySelector("#analysisError"),
    analysisOpenAIWarning: document.querySelector("#analysisOpenAIWarning"),
    analysisGeminiWarning: document.querySelector("#analysisGeminiWarning"),
    analysisLocalNotice: document.querySelector("#analysisLocalNotice"),
    analysisEmptyState: document.querySelector("#analysisEmptyState"),
    analysisResults: document.querySelector("#analysisResults"),
    analysisResultMeta: document.querySelector("#analysisResultMeta"),
    analysisSummary: document.querySelector("#analysisSummary"),
    analysisPurpose: document.querySelector("#analysisPurpose"),
    analysisDiscussions: document.querySelector("#analysisDiscussions"),
    analysisDecisions: document.querySelector("#analysisDecisions"),
    analysisActions: document.querySelector("#analysisActions"),
    analysisQuestions: document.querySelector("#analysisQuestions"),
    analysisWarnings: document.querySelector("#analysisWarnings"),
  };

  const statusLabels = {
    idle: t("대기"),
    listening: t("수신 중"),
    paused: t("일시정지"),
    transcribing: t("전사 중"),
    error: t("오류"),
    stopped: t("중지됨"),
  };

  const languageLabels = {
    ja: "日本語 · JA",
    en: "English · EN",
    mixed: t("혼합 · MIXED"),
    unknown: t("미확인"),
  };

  const sourceLabels = {
    system: t("시스템"),
    microphone: t("마이크"),
  };

  const translationStatusLabels = {
    disabled: t("사용 안 함"),
    pending: t("대기 중"),
    translating: t("번역 중"),
    success: t("번역 완료"),
    error: t("번역 오류"),
  };

  const providerLabels = {
    none: t("사용 안 함"),
    local: t("로컬 모델"),
    openai: "OpenAI API",
    gemini: "Gemini API",
  };

  const analysisProviderLabels = {
    none: t("사용 안 함"),
    rule_based: t("규칙 기반 · 로컬"),
    openai: "OpenAI API",
    gemini: "Gemini API",
  };

  const analysisStatusLabels = {
    idle: t("분석 없음"),
    pending: t("대기 중"),
    running: t("분석 중"),
    completed: t("분석 완료"),
    error: t("분석 오류"),
    cancelled: t("취소됨"),
  };

  const decisionRadarStatusLabels = {
    disabled: t("사용 안 함"),
    idle: t("준비됨"),
    buffering: t("근거 수집 중"),
    running: t("Radar 분석 중"),
    error: t("Radar 오류"),
    closed: t("중지됨"),
  };

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null);
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function asArray(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null) return [];
    return [value];
  }

  function normalizeStatus(value) {
    const raw = String(value || "idle").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    const aliases = {
      ready: "idle",
      initialized: "idle",
      running: "listening",
      recording: "listening",
      active: "listening",
      capturing: "listening",
      pause: "paused",
      suspended: "paused",
      processing: "transcribing",
      loading: "transcribing",
      stopping: "stopped",
      stop: "stopped",
      failed: "error",
      failure: "error",
    };
    const normalized = aliases[raw] || raw;
    return Object.hasOwn(statusLabels, normalized) ? normalized : "idle";
  }

  function normalizeLanguage(value) {
    const raw = String(value || "unknown").trim().toLowerCase();
    const aliases = {
      japanese: "ja",
      jp: "ja",
      english: "en",
      eng: "en",
      multilingual: "mixed",
      mix: "mixed",
      und: "unknown",
      undefined: "unknown",
    };
    const normalized = aliases[raw] || raw;
    return Object.hasOwn(languageLabels, normalized) ? normalized : "unknown";
  }

  function normalizeSource(value) {
    const raw = String(value || "").toLowerCase();
    if (["mic", "input", "microphone"].includes(raw)) return "microphone";
    return "system";
  }

  function extractMessage(payload, fallback = t("요청을 처리하지 못했습니다.")) {
    if (typeof payload === "string" && payload.trim()) return i18n.localizeExternalText(payload.trim());
    if (Array.isArray(payload)) {
      const combined = payload.map((item) => extractMessage(item, "")).filter(Boolean).join(" · ");
      return combined || fallback;
    }
    const object = asObject(payload);
    const candidate = firstDefined(object.message, object.error, object.reason, object.description);
    if (typeof candidate === "string" && candidate.trim()) return i18n.localizeExternalText(candidate.trim());
    if (object.detail !== undefined) return extractMessage(object.detail, fallback);
    if (candidate && typeof candidate === "object") return extractMessage(candidate, fallback);
    return fallback;
  }

  function redactSensitiveText(value) {
    return String(value || "")
      .replace(/\bsk-[a-z0-9_-]{8,}\b/gi, () => `[${t("API 키 보호됨")}]`)
      .replace(/\bAIza[a-z0-9_-]{16,}\b/gi, () => `[${t("API 키 보호됨")}]`)
      .replace(/((?:(?:openai|gemini)[_ -]?)?api[_ -]?key\s*[:=]\s*)\S+/gi, (_match, prefix) => `${prefix}[${t("보호됨")}]`)
      .replace(/(authorization\s*:\s*bearer\s+)\S+/gi, (_match, prefix) => `${prefix}[${t("보호됨")}]`);
  }

  async function apiRequest(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT_MS);
    const request = {
      method: options.method || "GET",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      signal: controller.signal,
      cache: "no-store",
    };

    if (options.body !== undefined) {
      request.headers["Content-Type"] = "application/json";
      request.body = JSON.stringify(options.body);
    }

    try {
      const response = await fetch(path, request);
      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("json")
        ? await response.json().catch(() => ({}))
        : await response.text().catch(() => "");

      if (!response.ok) {
        const error = new Error(extractMessage(payload, t("요청 실패 (HTTP {status})", { status: response.status })));
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error(t("서버 응답 시간이 초과되었습니다."));
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function setAppStatus(text, tone = "neutral") {
    elements.appStatus.textContent = i18n.localizeExternalText(text);
    elements.appStatusPill.dataset.tone = tone;
  }

  function setWebSocketStatus(text, tone = "neutral") {
    elements.wsStatus.textContent = i18n.localizeExternalText(text);
    elements.wsStatusPill.dataset.tone = tone;
  }

  function showError(message) {
    const safeMessage = redactSensitiveText(extractMessage(message, t("알 수 없는 오류가 발생했습니다.")));
    elements.errorMessage.textContent = safeMessage;
    elements.errorBanner.hidden = false;
  }

  function dismissError() {
    elements.errorBanner.hidden = true;
    elements.errorMessage.textContent = "";
  }

  function setRequestInFlight(active) {
    state.requestInFlight = active;
    updateControls();
  }

  function isReverseTranslation() {
    return ["ko_to_ja", "ko_to_en"].includes(state.translationDirection);
  }

  function requiresExternalTranslationProvider() {
    return directionTargetLanguage() !== "ko";
  }

  function directionSourceLanguage() {
    return state.translationDirection.split("_to_")[0] || "ja";
  }

  function directionTargetLanguage() {
    return state.translationDirection.split("_to_")[1] || "ko";
  }

  function directionTargetLanguageLabel() {
    return {
      ko: t("한국어"),
      ja: t("일본어"),
      en: t("영어"),
    }[directionTargetLanguage()];
  }

  function reverseTranslationReady() {
    const sttReady = !isReverseTranslation() || state.stt.provider === "deepgram";
    const translationReady = !requiresExternalTranslationProvider()
      || ["gemini", "openai"].includes(state.translation.applied);
    return sttReady && translationReady;
  }

  function renderTranslationDirection({ resetInvalid = true } = {}) {
    const directionLabels = {
      ja_to_ko: t("일본어 → 한국어"),
      ja_to_en: t("일본어 → 영어"),
      en_to_ko: t("영어 → 한국어"),
      en_to_ja: t("영어 → 일본어"),
      ko_to_ja: t("한국어 → 일본어"),
      ko_to_en: t("한국어 → 영어"),
    };
    [...elements.translationDirectionSelect.options].forEach((option) => {
      option.textContent = directionLabels[option.value] || option.textContent;
    });
    const reverseOptions = [...elements.translationDirectionSelect.options]
      .filter((option) => ["ko_to_ja", "ko_to_en"].includes(option.value));
    reverseOptions.forEach((option) => {
      option.disabled = state.stt.provider !== "deepgram";
    });
    if (resetInvalid && isReverseTranslation() && state.stt.provider !== "deepgram") {
      state.translationDirection = "ja_to_ko";
      elements.translationDirectionSelect.value = "ja_to_ko";
    }

    const reverse = isReverseTranslation();
    const externalOnly = requiresExternalTranslationProvider();
    const localOption = [...elements.translationMethodSelect.options]
      .find((option) => option.value === "local");
    if (localOption) localOption.disabled = externalOnly;
    elements.translationTitle.textContent = {
      ko: t("한국어 번역 설정"),
      ja: t("일본어 번역 설정"),
      en: t("영어 번역 설정"),
    }[directionTargetLanguage()];
    elements.translationBarDirection.textContent = directionLabels[state.translationDirection];
    if (externalOnly && !["gemini", "openai"].includes(state.translation.applied)) {
      elements.translationDirectionHint.textContent = reverse
        ? t("Deepgram과 Gemini 또는 OpenAI 번역 설정이 필요합니다.")
        : t("Gemini 또는 OpenAI 번역 설정이 필요합니다.");
    } else if (state.translationDirection === "ja_to_ko") {
      elements.translationDirectionHint.textContent = t("일본어 음성을 한국어로 번역합니다.");
    } else if (state.translationDirection === "ja_to_en") {
      elements.translationDirectionHint.textContent = t("일본어 음성을 영어로 번역합니다.");
    } else if (state.translationDirection === "en_to_ko") {
      elements.translationDirectionHint.textContent = t("영어 음성을 한국어로 번역합니다.");
    } else if (state.translationDirection === "en_to_ja") {
      elements.translationDirectionHint.textContent = t("영어 음성을 일본어로 번역합니다.");
    } else if (!["gemini", "openai"].includes(state.translation.applied)) {
      elements.translationDirectionHint.textContent = t("Deepgram과 Gemini 또는 OpenAI 번역 설정이 필요합니다.");
    } else if (state.translationDirection === "ko_to_ja") {
      elements.translationDirectionHint.textContent = t("Deepgram으로 한국어를 인식해 일본어로 번역합니다.");
    } else {
      elements.translationDirectionHint.textContent = t("Deepgram으로 한국어를 인식해 영어로 번역합니다.");
    }
  }

  function updateControls() {
    const persistentStatus = state.captureState;
    const active = ["listening", "transcribing", "paused"].includes(persistentStatus);
    const canStart = Boolean(elements.deviceSelect.value)
      && !active
      && !state.requestInFlight
      && reverseTranslationReady();

    elements.startButton.disabled = !canStart;
    elements.pauseButton.disabled =
      state.requestInFlight || !["listening", "transcribing"].includes(persistentStatus);
    elements.resumeButton.disabled = state.requestInFlight || persistentStatus !== "paused";
    elements.stopButton.disabled = state.requestInFlight || !active;
    elements.deviceSelect.disabled = state.requestInFlight || active || currentDevices().length === 0;
    elements.sttProviderSelect.disabled = state.requestInFlight || active;
    elements.translationDirectionSelect.disabled = state.requestInFlight || active;
    elements.modelSelect.disabled = state.requestInFlight || active || state.stt.provider === "deepgram";
    elements.refreshDevicesButton.disabled = state.requestInFlight || active;
    elements.sourceInputs.forEach((input) => {
      input.disabled = state.requestInFlight || active;
    });
    updateTranslationControls();
    updateLiveShareControls();
  }

  function updateLiveShareControls() {
    const sharing = state.liveShare;
    const busy = sharing.requestInFlight;
    elements.liveShareConsent.disabled = busy || sharing.active || !sharing.configured;
    elements.startLiveShareButton.disabled = busy
      || sharing.active
      || !sharing.configured
      || !sharing.consentConfirmed;
    elements.stopLiveShareButton.disabled = busy || !sharing.active;
    elements.copyLiveShareLinkButton.disabled = !sharing.active || !sharing.viewerUrl;
    elements.startLiveShareButton.setAttribute("aria-busy", String(busy && !sharing.active));
    elements.stopLiveShareButton.setAttribute("aria-busy", String(busy && sharing.active));
  }

  function setLiveShareFeedback(message = "") {
    elements.liveShareFeedback.textContent = message;
    elements.liveShareFeedback.hidden = !message;
  }

  function setLiveShareError(message = "") {
    elements.liveShareError.textContent = message;
    elements.liveShareError.hidden = !message;
  }

  function applyLiveSharePayload(payload) {
    const source = asObject(firstDefined(payload.live_share, payload.share, payload));
    state.liveShare.configured = source.configured === true;
    state.liveShare.active = source.active === true;
    state.liveShare.status = String(source.status || (source.active ? "active" : "idle"));
    state.liveShare.viewerUrl = String(source.viewer_url || "");
    state.liveShare.expiresAt = String(source.expires_at || "");
    state.liveShare.lastLatencyMs = source.last_latency_ms ?? null;
    state.liveShare.lastErrorCode = String(source.last_error_code || "");
    state.liveShare.verifiedAttendeeCount = Number(source.verified_attendee_count || 0);
    renderLiveShare();
  }

  function shareAccessTime(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(UI_LOCALE, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function selectedShareAccessLog() {
    const history = state.liveShare.accessHistory;
    return history.find((item) => item.room_id === state.liveShare.selectedAccessRoomId)
      || history[0]
      || null;
  }

  function renderLiveShareAccessLogs() {
    const history = state.liveShare.accessHistory;
    const selected = selectedShareAccessLog();
    elements.liveShareAuditPanel.hidden = history.length === 0 && !state.liveShare.active;
    elements.refreshLiveShareAuditButton.disabled = state.liveShare.accessLogLoading;
    elements.liveShareAuditRoomSelect.disabled = history.length < 2;
    const previousRoom = elements.liveShareAuditRoomSelect.value;
    elements.liveShareAuditRoomSelect.replaceChildren();
    history.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.room_id;
      const suffix = String(item.room_id || "").slice(-6);
      option.textContent = `${shareAccessTime(item.created_at)} · …${suffix}`;
      elements.liveShareAuditRoomSelect.append(option);
    });
    const desiredRoom = selected?.room_id || previousRoom;
    if (desiredRoom) elements.liveShareAuditRoomSelect.value = desiredRoom;

    const attendees = Array.isArray(selected?.attendees) ? selected.attendees : [];
    const events = Array.isArray(selected?.events) ? selected.events : [];
    elements.liveShareVerifiedCount.textContent = String(attendees.length);
    elements.liveShareRejectedCount.textContent = String(
      events.filter((item) => item.event_type === "verification_code_rejected").length,
    );
    elements.liveShareAttendeeList.replaceChildren();
    attendees.forEach((attendee) => {
      const item = document.createElement("li");
      const identity = document.createElement("div");
      const email = document.createElement("strong");
      const status = document.createElement("span");
      email.textContent = String(attendee.email || "");
      status.textContent = attendee.active ? t("접속 중") : t("접속 종료");
      status.dataset.active = String(attendee.active === true);
      identity.append(email, status);
      const meta = document.createElement("p");
      meta.textContent = `${t("최초 인증")} ${shareAccessTime(attendee.first_verified_at)} · ${t("마지막 확인")} ${shareAccessTime(attendee.last_seen_at)}`;
      item.append(identity, meta);
      elements.liveShareAttendeeList.append(item);
    });
    elements.liveShareAuditEmpty.hidden = attendees.length > 0;
  }

  async function loadLiveShareAccessLogs({ quiet = false } = {}) {
    if (state.liveShare.accessLogLoading) return;
    state.liveShare.accessLogLoading = true;
    if (!quiet) {
      elements.liveShareAuditError.hidden = true;
      elements.liveShareAuditError.textContent = "";
    }
    renderLiveShareAccessLogs();
    try {
      const payload = await apiRequest("/api/share/access-log", { timeout: 7_000 });
      const candidates = [payload.current, ...(Array.isArray(payload.history) ? payload.history : [])]
        .filter((item) => item && item.room_id);
      const unique = [];
      const seen = new Set();
      candidates.forEach((item) => {
        if (seen.has(item.room_id)) return;
        seen.add(item.room_id);
        unique.push(item);
      });
      state.liveShare.accessHistory = unique;
      if (!unique.some((item) => item.room_id === state.liveShare.selectedAccessRoomId)) {
        state.liveShare.selectedAccessRoomId = unique[0]?.room_id || "";
      }
      if (payload.refresh_error && !quiet) throw new Error("access_log_refresh_failed");
    } catch (_error) {
      if (!quiet) {
        elements.liveShareAuditError.textContent = t("접속 기록을 확인하지 못했습니다.");
        elements.liveShareAuditError.hidden = false;
      }
    } finally {
      state.liveShare.accessLogLoading = false;
      renderLiveShareAccessLogs();
    }
  }

  function startLiveShareAccessLogPolling() {
    if (state.liveShare.accessLogPollTimer) return;
    state.liveShare.accessLogPollTimer = window.setInterval(() => {
      if (!state.liveShare.active || document.visibilityState !== "visible") return;
      void loadLiveShareAccessLogs({ quiet: true });
    }, 10_000);
  }

  function renderLiveShare() {
    const sharing = state.liveShare;
    const labels = {
      loading: t("확인 중"),
      unconfigured: t("설정 필요"),
      idle: t("공유 안 함"),
      active: t("공유 중"),
      degraded: t("연결 지연"),
      expired: t("공유 만료"),
    };
    elements.liveShareStatusBadge.dataset.status = sharing.status;
    elements.liveShareStatusBadge.textContent = labels[sharing.status] || labels.idle;
    elements.liveShareLinkPanel.hidden = !sharing.active || !sharing.viewerUrl;
    elements.liveShareUrl.value = sharing.viewerUrl;
    if (!sharing.configured && sharing.status !== "loading") {
      setLiveShareError(t("초대 링크 공유 서버 설정이 필요합니다."));
    } else if (sharing.status === "degraded") {
      setLiveShareError(t("공유 서버 연결이 지연되고 있습니다. 로컬 자막과 번역은 계속됩니다."));
    }
    renderLiveShareAccessLogs();
    updateLiveShareControls();
  }

  async function loadLiveShareStatus() {
    try {
      applyLiveSharePayload(await apiRequest("/api/share", { timeout: 5_000 }));
    } catch (error) {
      state.liveShare.status = "unconfigured";
      setLiveShareError(extractMessage(error, t("공유 상태를 확인하지 못했습니다.")));
      renderLiveShare();
    }
  }

  async function startLiveShare() {
    if (!state.liveShare.consentConfirmed || state.liveShare.requestInFlight) return;
    state.liveShare.requestInFlight = true;
    setLiveShareFeedback();
    setLiveShareError();
    updateLiveShareControls();
    try {
      const payload = await apiRequest("/api/share/start", {
        method: "POST",
        body: { consent_confirmed: true },
        timeout: 10_000,
      });
      applyLiveSharePayload(payload);
      await loadLiveShareAccessLogs({ quiet: true });
      setLiveShareFeedback(t("초대 링크 공유를 시작했습니다."));
    } catch (error) {
      setLiveShareError(extractMessage(error, t("초대 링크 공유를 시작하지 못했습니다.")));
    } finally {
      state.liveShare.requestInFlight = false;
      renderLiveShare();
    }
  }

  async function stopLiveShare() {
    if (!state.liveShare.active || state.liveShare.requestInFlight) return;
    state.liveShare.requestInFlight = true;
    setLiveShareFeedback();
    setLiveShareError();
    updateLiveShareControls();
    try {
      const payload = await apiRequest("/api/share/stop", { method: "POST", timeout: 10_000 });
      applyLiveSharePayload(payload);
      await loadLiveShareAccessLogs({ quiet: true });
      state.liveShare.consentConfirmed = false;
      elements.liveShareConsent.checked = false;
      setLiveShareFeedback(t("공유를 종료하고 중계 텍스트를 삭제했습니다."));
    } catch (error) {
      setLiveShareError(extractMessage(error, t("공유 종료 상태를 확인하지 못했습니다.")));
    } finally {
      state.liveShare.requestInFlight = false;
      renderLiveShare();
    }
  }

  async function copyLiveShareLink() {
    if (!state.liveShare.viewerUrl) return;
    const copied = await writeClipboard(state.liveShare.viewerUrl);
    setLiveShareFeedback(copied ? t("초대 링크를 복사했습니다.") : t("초대 링크를 복사하지 못했습니다."));
  }

  function updateTranslationControls() {
    const translation = state.translation;
    const selectedProvider = translation.providers.get(translation.selected);
    const directionCompatible = !requiresExternalTranslationProvider()
      || ["gemini", "openai"].includes(translation.selected);
    const available = (translation.selected === "none" || selectedProvider?.available === true)
      && directionCompatible;
    const busy = translation.loading || translation.saving || translation.testing;
    elements.translationMethodSelect.disabled = busy;
    elements.translationApplyButton.disabled =
      busy || translation.selected === translation.applied || !available;
    elements.translationTestButton.disabled =
      busy
      || ["none", "gemini"].includes(translation.selected)
      || translation.selected !== translation.applied
      || !available;
    elements.translationApplyButton.setAttribute("aria-busy", String(translation.saving));
    elements.translationTestButton.setAttribute("aria-busy", String(translation.testing));
    updateSessionControls();
  }

  function updateSessionControls() {
    const sessions = state.sessions;
    const activeCapture = ["listening", "transcribing", "paused"].includes(state.captureState);
    const hasSelection = Boolean(sessions.selectedId);
    const busy = sessions.loadingList || sessions.loadingSession || sessions.downloading;
    const settingsDirty =
      sessions.settings.saveOriginal !== sessions.savedSettings.saveOriginal ||
      sessions.settings.saveTranslation !== sessions.savedSettings.saveTranslation ||
      sessions.settings.saveAnalysis !== sessions.savedSettings.saveAnalysis;

    elements.refreshSessionsButton.disabled = sessions.loadingList;
    elements.refreshSessionsButton.setAttribute("aria-busy", String(sessions.loadingList));
    elements.sessionSelect.disabled = sessions.loadingList || sessions.list.length === 0;
    elements.restoreSessionButton.disabled = busy || !hasSelection || activeCapture;
    elements.copyOriginalButton.disabled = busy || !hasSelection;
    elements.copyTranslationButton.disabled = busy || !hasSelection;
    elements.sessionDownloadButtons.forEach((button) => {
      button.disabled = busy || !hasSelection;
    });

    elements.saveOriginalToggle.disabled = sessions.savingSettings;
    elements.saveTranslationToggle.disabled = sessions.savingSettings;
    elements.saveAnalysisToggle.disabled = sessions.savingSettings;
    elements.saveSessionSettingsButton.disabled = sessions.savingSettings || !settingsDirty;
    elements.saveSessionSettingsButton.setAttribute("aria-busy", String(sessions.savingSettings));
    updateAnalysisControls();
  }

  function selectedAnalysisProvider() {
    return state.analysis.providers.get(state.analysis.selected) || {
      name: state.analysis.selected,
      available: state.analysis.selected === "none",
      reason: "",
    };
  }

  function updateAnalysisControls() {
    const analysis = state.analysis;
    const provider = selectedAnalysisProvider();
    const targetSessionId = state.sessions.selectedId || state.sessions.current?.sessionId || "";
    const activeStatus = ["pending", "running"].includes(analysis.status);
    const busy = analysis.loading || analysis.loadingResult || analysis.saving || analysis.actionInFlight;
    const settingsDirty =
      analysis.selected !== analysis.savedSettings.provider ||
      analysis.settings.autoRunOnStop !== analysis.savedSettings.autoRunOnStop;
    const available = analysis.selected === "none" || provider.available === true;
    const appliedProvider = analysis.providers.get(analysis.applied);
    const canRun =
      Boolean(targetSessionId) &&
      analysis.applied !== "none" &&
      appliedProvider?.available === true &&
      !activeStatus;

    elements.analysisProviderSelect.disabled = busy || activeStatus;
    elements.analysisAutoRunToggle.disabled = busy || activeStatus || analysis.selected === "none";
    elements.analysisApplyButton.disabled = busy || activeStatus || !settingsDirty || !available;
    elements.analysisApplyButton.setAttribute("aria-busy", String(analysis.saving));
    elements.generateAnalysisButton.disabled = busy || !canRun;
    elements.cancelAnalysisButton.disabled = busy || !targetSessionId || !activeStatus;
    elements.retryAnalysisButton.disabled =
      busy || !targetSessionId || !["error", "cancelled"].includes(analysis.status) || analysis.applied === "none";
    elements.analysisTargetSession.textContent = targetSessionId || t("세션을 선택하세요");
  }

  function applyCaptureState(payload) {
    const object = asObject(payload);
    const nested = asObject(firstDefined(object.data, object.capture, object.snapshot));
    const captureValue = firstDefined(
      object.state,
      object.capture_state,
      nested.state,
      nested.capture_state,
      object.status,
    );
    const displayValue = firstDefined(
      object.display_state,
      nested.display_state,
      object.processing_state,
      captureValue,
    );

    if (captureValue !== undefined && typeof captureValue !== "object") {
      state.captureState = normalizeStatus(captureValue);
    }
    if (displayValue !== undefined && typeof displayValue !== "object") {
      state.displayState = normalizeStatus(displayValue);
    } else {
      state.displayState = state.captureState;
    }

    const effectiveStatus = state.displayState === "transcribing" ? "transcribing" : state.captureState;
    const tone = effectiveStatus === "error"
      ? "danger"
      : ["listening", "transcribing"].includes(effectiveStatus)
        ? "active"
        : effectiveStatus === "paused"
          ? "warning"
          : effectiveStatus === "idle" || effectiveStatus === "stopped"
            ? "success"
            : "neutral";
    setAppStatus(statusLabels[effectiveStatus] || t("대기"), tone);

    const payloadSource = firstDefined(object.source, nested.source);
    if (payloadSource) {
      const normalizedSource = normalizeSource(payloadSource);
      const payloadDeviceId = firstDefined(object.device_id, nested.device_id);
      if (payloadDeviceId !== undefined && payloadDeviceId !== null) {
        state.selectedDevice[normalizedSource] = String(payloadDeviceId);
      }
      setSource(normalizedSource);
    }
    const payloadModel = firstDefined(object.model, nested.model);
    if (payloadModel && [...elements.modelSelect.options].some((option) => option.value === payloadModel)) {
      elements.modelSelect.value = payloadModel;
    }
    const payloadDirection = String(
      firstDefined(object.translation_direction, nested.translation_direction, ""),
    ).toLowerCase();
    if (TRANSLATION_DIRECTIONS.includes(payloadDirection)) {
      state.translationDirection = payloadDirection;
      elements.translationDirectionSelect.value = payloadDirection;
    }
    const payloadSttProvider = String(firstDefined(object.stt_provider, nested.stt_provider, "")).toLowerCase();
    if (["local", "deepgram"].includes(payloadSttProvider)) {
      state.stt.provider = payloadSttProvider;
      elements.sttProviderSelect.value = payloadSttProvider;
      renderSttProvider();
    } else if (payloadDirection) {
      renderTranslationDirection({ resetInvalid: false });
    }

    if (["idle", "stopped", "error"].includes(state.captureState)) {
      setAudioLevel(0, true);
      if (state.captureState !== "error") clearPartial();
    }
    syncSessionFromCapturePayload(object, nested);
    updateControls();
  }

  function normalizeDevice(device, category) {
    const raw = asObject(device);
    const id = firstDefined(raw.device_id, raw.id, raw.index, raw.deviceIndex, raw.device_index);
    const inputChannels = Number(firstDefined(raw.max_input_channels, raw.maxInputChannels, raw.input_channels, 0));
    const outputChannels = Number(firstDefined(raw.max_output_channels, raw.maxOutputChannels, raw.output_channels, 0));
    const loopback = Boolean(firstDefined(raw.is_loopback, raw.isLoopbackDevice, raw.loopback, category === "loopback"));
    return {
      rawId: id,
      id: id === undefined || id === null ? "" : String(id),
      name: String(firstDefined(raw.name, raw.label, raw.device_name, t("오디오 장치 {id}", { id: id ?? "" }))),
      hostApi: String(firstDefined(raw.host_api, raw.hostApi, raw.host_api_name, "")),
      isLoopback: loopback,
      isDefault: Boolean(firstDefined(raw.is_default, raw.default, raw.isDefault, false)),
      inputChannels: Number.isFinite(inputChannels) ? inputChannels : 0,
      outputChannels: Number.isFinite(outputChannels) ? outputChannels : 0,
      sampleRate: Number(firstDefined(raw.default_sample_rate, raw.defaultSampleRate, raw.sample_rate, 0)) || 0,
      pairedOutputId: firstDefined(
        raw.paired_output_device_id,
        raw.output_device_id,
        raw.pairedOutputDeviceId,
      ),
      raw,
    };
  }

  function uniqueDevices(devices) {
    const seen = new Set();
    return devices.filter((device) => {
      const key = device.id || `${device.name}|${device.hostApi}|${device.isLoopback}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function normalizeDevicePayload(payload) {
    const outer = asObject(payload);
    const nested = asObject(firstDefined(outer.data, outer.devices));
    const root = Object.keys(nested).length ? { ...outer, ...nested } : outer;
    const flatDevices = Array.isArray(payload)
      ? payload
      : Array.isArray(outer.devices)
        ? outer.devices
        : asArray(firstDefined(root.all_devices, root.items, []));

    let outputs = asArray(firstDefined(root.outputs, root.output_devices, root.speakers));
    let loopbacks = asArray(firstDefined(root.loopbacks, root.loopback_devices, root.system_devices));
    let microphones = asArray(firstDefined(root.microphones, root.input_devices, root.inputs, root.mics));

    if (flatDevices.length) {
      flatDevices.forEach((device) => {
        const normalized = normalizeDevice(device, "unknown");
        const kind = String(firstDefined(device.kind, device.type, device.source, "")).toLowerCase();
        if (normalized.isLoopback || kind.includes("loopback") || kind === "system") {
          loopbacks.push(device);
        } else if (normalized.inputChannels > 0 || kind.includes("input") || kind.includes("mic")) {
          microphones.push(device);
        } else if (normalized.outputChannels > 0 || kind.includes("output") || kind.includes("speaker")) {
          outputs.push(device);
        }
      });
    }

    outputs = uniqueDevices(outputs.map((device) => normalizeDevice(device, "output")));
    loopbacks = uniqueDevices(loopbacks.map((device) => normalizeDevice(device, "loopback")));
    microphones = uniqueDevices(microphones.map((device) => normalizeDevice(device, "microphone")));

    const outputLoopbackPairs = asObject(firstDefined(
      root.output_loopback_pairs,
      root.outputLoopbackPairs,
      root.device_pairs,
    ));
    Object.entries(outputLoopbackPairs).forEach(([outputId, loopbackId]) => {
      const loopback = loopbacks.find((device) => device.id === String(loopbackId));
      if (loopback && (loopback.pairedOutputId === undefined || loopback.pairedOutputId === null)) {
        loopback.pairedOutputId = outputId;
      }
    });

    return {
      outputs,
      loopbacks,
      microphones,
      defaultOutputId: firstDefined(root.default_output_id, root.defaultOutputId),
      defaultLoopbackId: firstDefined(root.default_loopback_id, root.defaultLoopbackId),
      defaultMicrophoneId: firstDefined(root.default_microphone_id, root.default_input_id, root.defaultMicrophoneId),
      warnings: asArray(firstDefined(root.warnings, root.warning, [])),
    };
  }

  function currentDevices() {
    return state.source === "system" ? state.devices.loopbacks : state.devices.microphones;
  }

  function findOutputName(pairedOutputId) {
    if (pairedOutputId === undefined || pairedOutputId === null) return "";
    return state.devices.outputs.find((device) => device.id === String(pairedOutputId))?.name || "";
  }

  function deviceOptionLabel(device) {
    const displayName = device.isDefault || state.defaults[state.source] === device.id
      ? t("기본 · {name}", { name: device.name })
      : device.name;
    const hostSuffix = device.hostApi && !device.name.toLowerCase().includes(device.hostApi.toLowerCase())
      ? ` · ${device.hostApi}`
      : "";
    if (state.source === "system") {
      const outputName = findOutputName(device.pairedOutputId);
      const pairSuffix = outputName && !device.name.toLowerCase().includes(outputName.toLowerCase())
        ? ` ↔ ${outputName}`
        : "";
      return `${displayName}${pairSuffix}${hostSuffix}`;
    }
    return `${displayName}${hostSuffix}`;
  }

  function renderDevices() {
    const devices = currentDevices();
    const previous = state.selectedDevice[state.source];
    const defaultId = state.defaults[state.source];
    elements.deviceSelect.replaceChildren();

    if (!devices.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = state.source === "system"
        ? t("사용 가능한 WASAPI Loopback이 없습니다")
        : t("사용 가능한 마이크가 없습니다");
      elements.deviceSelect.append(option);
      elements.deviceSelect.value = "";
      updateControls();
      return;
    }

    devices.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = deviceOptionLabel(device);
      option.title = option.textContent;
      elements.deviceSelect.append(option);
    });

    const preferred = [previous, defaultId, devices.find((device) => device.isDefault)?.id, devices[0].id]
      .find((id) => id !== null && id !== undefined && devices.some((device) => device.id === String(id)));
    elements.deviceSelect.value = String(preferred ?? devices[0].id);
    state.selectedDevice[state.source] = elements.deviceSelect.value;
    updateControls();
  }

  function renderDeviceWarnings(warnings) {
    const messages = warnings.map((warning) => extractMessage(warning, "")).filter(Boolean);
    elements.deviceWarnings.replaceChildren();
    if (!messages.length) {
      elements.deviceWarnings.hidden = true;
      return;
    }
    messages.forEach((message) => {
      const paragraph = document.createElement("p");
      paragraph.textContent = `• ${message}`;
      elements.deviceWarnings.append(paragraph);
    });
    elements.deviceWarnings.hidden = false;
  }

  function setSource(source) {
    state.source = normalizeSource(source);
    elements.sourceInputs.forEach((input) => {
      input.checked = input.value === state.source;
    });
    const system = state.source === "system";
    elements.deviceLabel.textContent = system ? t("출력 Loopback 장치") : t("마이크 입력 장치");
    elements.deviceHint.textContent = system
      ? t("Windows 출력 장치에 대응하는 WASAPI Loopback을 선택하세요.")
      : t("말할 마이크 입력 장치를 선택하세요.");
    elements.loopbackGuidance.hidden = !system;
    renderDevices();
  }

  async function loadDevices({ refresh = false } = {}) {
    elements.refreshDevicesButton.setAttribute("aria-busy", "true");
    try {
      let payload;
      if (refresh) {
        payload = await apiRequest("/api/audio/refresh", { method: "POST" });
      }
      const hasDeviceCollections = payload && typeof payload === "object" && [
        "outputs", "loopbacks", "microphones", "devices", "data",
      ].some((key) => key in payload);
      if (!hasDeviceCollections) payload = await apiRequest("/api/audio/devices");

      const normalized = normalizeDevicePayload(payload);
      state.devices = {
        outputs: normalized.outputs,
        loopbacks: normalized.loopbacks,
        microphones: normalized.microphones,
      };
      state.defaults.system = normalized.defaultLoopbackId === undefined || normalized.defaultLoopbackId === null
        ? null
        : String(normalized.defaultLoopbackId);
      state.defaults.microphone = normalized.defaultMicrophoneId === undefined || normalized.defaultMicrophoneId === null
        ? null
        : String(normalized.defaultMicrophoneId);
      renderDeviceWarnings(normalized.warnings);
      renderDevices();

      if (refresh) {
        setAppStatus(statusLabels[state.captureState], state.captureState === "error" ? "danger" : "success");
      }
    } catch (error) {
      showError(t("오디오 장치 조회 실패: {message}", { message: extractMessage(error) }));
      state.devices = { outputs: [], loopbacks: [], microphones: [] };
      renderDevices();
    } finally {
      elements.refreshDevicesButton.removeAttribute("aria-busy");
      updateControls();
    }
  }

  function modelLabel(model) {
    const labels = {
      tiny: t("tiny · 가장 빠름"),
      base: t("base · 빠름"),
      small: t("small · 기본"),
      medium: t("medium · 정확도 우선"),
    };
    return labels[model] || model;
  }

  function renderSttProvider() {
    const deepgram = state.stt.provider === "deepgram";
    renderTranslationDirection();
    const sourceLabel = directionSourceLanguage() === "ko"
      ? t("한국어")
      : directionSourceLanguage() === "en"
        ? t("영어")
        : t("일본어");
    elements.sttProviderHint.textContent = deepgram
      ? t("Deepgram {model} 스트리밍 · {language} 인식 · 음성이 외부 API로 전송됩니다.", {
        model: state.stt.model,
        language: sourceLabel,
      })
      : t("로컬 PC의 faster-whisper로 음성을 인식합니다.");
    updateControls();
  }

  function selectedSttModelLabel() {
    return state.stt.provider === "deepgram"
      ? `Deepgram ${state.stt.model}`
      : elements.modelSelect.value;
  }

  async function loadSettings() {
    try {
      const payload = await apiRequest("/api/settings");
      const object = { ...asObject(payload), ...asObject(payload.data) };
      const allowed = asArray(firstDefined(object.allowed_models, object.models, ["tiny", "base", "small", "medium"]))
        .map(String)
        .filter((model) => ["tiny", "base", "small", "medium"].includes(model));
      const models = allowed.length ? [...new Set(allowed)] : ["tiny", "base", "small", "medium"];
      const selected = String(firstDefined(object.selected_model, object.default_model, object.model, "small"));
      const deepgram = asObject(object.deepgram);
      state.stt.deepgramConfigured = booleanValue(deepgram.configured, false);
      state.stt.model = String(firstDefined(deepgram.model, "nova-3"));
      state.stt.language = String(firstDefined(deepgram.language, "ja"));
      const configuredProvider = String(firstDefined(object.stt_provider, "local")).toLowerCase();
      const configuredDirection = String(firstDefined(object.translation_direction, "ja_to_ko")).toLowerCase();

      elements.sttProviderSelect.replaceChildren();
      const localOption = document.createElement("option");
      localOption.value = "local";
      localOption.textContent = t("로컬 Whisper");
      elements.sttProviderSelect.append(localOption);
      const deepgramOption = document.createElement("option");
      deepgramOption.value = "deepgram";
      deepgramOption.textContent = `Deepgram · ${state.stt.model}`;
      deepgramOption.disabled = !state.stt.deepgramConfigured;
      if (!state.stt.deepgramConfigured) deepgramOption.textContent += ` · ${t("API 키 필요")}`;
      elements.sttProviderSelect.append(deepgramOption);
      state.stt.provider = configuredProvider === "deepgram" && state.stt.deepgramConfigured
        ? "deepgram"
        : "local";
      elements.sttProviderSelect.value = state.stt.provider;
      state.translationDirection = TRANSLATION_DIRECTIONS.includes(configuredDirection)
        ? configuredDirection
        : "ja_to_ko";
      elements.translationDirectionSelect.value = state.translationDirection;

      elements.modelSelect.replaceChildren();
      models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = modelLabel(model);
        elements.modelSelect.append(option);
      });
      elements.modelSelect.value = models.includes(selected) ? selected : models.includes("small") ? "small" : models[0];
      renderSttProvider();

      const latency = asArray(firstDefined(object.target_latency_seconds, object.target_latency, []));
      if (latency.length >= 2) {
        elements.latencyHint.textContent = t("목표 표시 지연 {start}–{end}초", {
          start: latency[0],
          end: latency[1],
        });
      }
    } catch (error) {
      showError(t("설정 조회 실패: {message}", { message: extractMessage(error) }));
    }
  }

  function booleanValue(value, fallback = false) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (["true", "1", "yes", "available", "configured", "installed"].includes(normalized)) return true;
      if (["false", "0", "no", "unavailable", "missing", "not_installed"].includes(normalized)) return false;
    }
    return fallback;
  }

  function normalizeProviderId(value) {
    const raw = String(value || "none").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["off", "disabled", "disable", "none"].includes(raw)) return "none";
    if (["local", "offline", "local_model"].includes(raw)) return "local";
    if (["openai", "openai_api", "api"].includes(raw)) return "openai";
    if (["gemini", "gemini_api", "google", "google_gemini"].includes(raw)) return "gemini";
    return raw;
  }

  function normalizeTranslationStatus(value, provider = state.translation.applied) {
    const raw = String(value || "").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["disabled", "off", "none", "skipped"].includes(raw)) return "disabled";
    if (!raw && provider === "none") return "disabled";
    if (["queued", "queue", "waiting", "pending"].includes(raw)) return "pending";
    if (["running", "processing", "in_progress", "translating"].includes(raw)) return "translating";
    if (["ok", "ready", "active", "completed", "complete", "done", "success", "succeeded"].includes(raw)) return "success";
    if (["failed", "failure", "cancelled", "canceled", "unavailable", "timeout", "error"].includes(raw)) return "error";
    return provider === "none" ? "disabled" : "pending";
  }

  function normalizeTranslationProvider(rawProvider, fallbackId) {
    const raw = typeof rawProvider === "string" ? { id: rawProvider } : asObject(rawProvider);
    const id = normalizeProviderId(firstDefined(raw.id, raw.provider, raw.type, raw.name, fallbackId));
    const available = id === "none" || booleanValue(
      firstDefined(raw.available, raw.is_available, raw.enabled, raw.ready),
      false,
    );
    return {
      id,
      name: i18n.localizeExternalText(String(firstDefined(raw.display_name, raw.name, providerLabels[id], id))),
      available,
      external: booleanValue(firstDefined(raw.external, raw.is_external), ["openai", "gemini"].includes(id)),
      reason: redactSensitiveText(i18n.localizeExternalText(firstDefined(raw.reason, raw.unavailable_reason, ""))),
      apiKeyConfigured: booleanValue(firstDefined(raw.api_key_configured, raw.openai_api_key_configured, raw.has_api_key), false),
      model: String(firstDefined(raw.model, raw.model_name, "")),
    };
  }

  function normalizedTranslationRoot(payload) {
    const outer = asObject(payload);
    const data = asObject(outer.data);
    const settings = asObject(firstDefined(outer.settings, data.settings));
    return { ...outer, ...data, ...settings };
  }

  function normalizeTranslationWorker(payload) {
    const outer = asObject(payload);
    const root = asObject(firstDefined(
      outer.translation_worker,
      outer.worker,
      asObject(outer.translation).worker,
      outer,
    ));
    const stateName = String(firstDefined(root.state, root.status, "unknown"))
      .trim()
      .toLowerCase()
      .replace(/[\s.-]+/g, "_");
    return {
      state: stateName || "unknown",
      available: booleanValue(root.available, stateName === "ready"),
      configured: booleanValue(root.configured, false),
      modelInstalled: booleanValue(root.model_installed, false),
      runtimeInstalled: booleanValue(root.runtime_installed, false),
      pid: Number.isInteger(Number(root.pid)) && Number(root.pid) > 0 ? Number(root.pid) : null,
      restartCount: Math.max(0, Number(root.restart_count) || 0),
      model: String(firstDefined(root.model, "")),
      coldStartMs: Number(root.cold_start_ms) || 0,
      priority: String(firstDefined(root.process_priority, "")),
      lastError: String(firstDefined(root.last_error, "")),
    };
  }

  function translationWorkerText(worker = state.translation.worker) {
    if (worker.state === "ready" && worker.available) {
      return worker.pid ? t("준비됨 · PID {pid}", { pid: worker.pid }) : t("준비됨");
    }
    if (worker.state === "starting") return t("모델 선행 로드 중");
    if (worker.state === "restarting") return t("자동 복구 중 · {count}회", { count: worker.restartCount });
    if (worker.state === "degraded") return t("일시 오류 · 자동 복구 대기");
    if (worker.state === "stopped") return t("중지됨");
    if (worker.state === "unavailable") return t("실행 환경 또는 모델 확인 필요");
    if (worker.state === "unmanaged") return t("별도 관리되지 않음");
    return t("상태 확인 중");
  }

  function applyTranslationWorkerPayload(payload, { render = true } = {}) {
    const worker = normalizeTranslationWorker(payload);
    state.translation.worker = worker;
    const local = state.translation.providers.get("local");
    const managed = !["unknown", "unmanaged"].includes(worker.state);
    if (local && managed) {
      local.available = worker.available;
      local.model = worker.model || local.model;
      local.reason = worker.available
        ? ""
        : worker.state === "starting" || worker.state === "restarting"
          ? t("로컬 번역 Worker가 모델을 준비하고 있습니다.")
          : t("로컬 번역 Worker를 사용할 수 없습니다. 원문 전사는 계속 동작합니다.");
    }
    state.translation.settings.localModelInstalled = worker.modelInstalled;
    if (state.translation.applied === "local") {
      if (!worker.available) {
        setTranslationGlobalStatus("error", worker.state === "restarting" ? t("복구 중") : t("Worker 오류"));
      } else if (state.translation.status === "error") {
        setTranslationGlobalStatus("success", t("준비됨"));
      }
    }
    if (render) renderTranslationProviderDetails();
  }

  function translationSettingsFrom(payload, fallbackProvider = state.translation.applied) {
    const root = normalizedTranslationRoot(payload);
    return {
      ...root,
      provider: normalizeProviderId(firstDefined(
        root.provider,
        root.selected_provider,
        root.translation_provider,
        root.mode,
        fallbackProvider,
      )),
      status: firstDefined(root.status, root.translation_status, root.state, ""),
      external: booleanValue(root.external, false),
      openaiModel: String(firstDefined(root.openai_model, root.api_model, "")),
      openaiApiKeyConfigured: booleanValue(firstDefined(
        root.openai_api_key_configured,
        root.api_key_configured,
        root.has_api_key,
      ), false),
      geminiModel: String(firstDefined(root.gemini_model, "")),
      geminiApiKeyConfigured: booleanValue(root.gemini_api_key_configured, false),
      localModelInstalled: booleanValue(firstDefined(
        root.local_model_installed,
        root.local_installed,
        root.model_installed,
      ), false),
      contextSegments: Number(firstDefined(root.context_segments, root.context_size, 0)) || 0,
      timeoutSeconds: Number(firstDefined(root.timeout_seconds, root.timeout, 0)) || 0,
      maxRetries: Number(firstDefined(root.max_retries, root.retries, 0)) || 0,
      worker: asObject(firstDefined(root.worker, root.translation_worker)),
    };
  }

  function setTranslationConfigError(message = "") {
    if (!message) {
      elements.translationConfigError.hidden = true;
      elements.translationConfigError.textContent = "";
      return;
    }
    elements.translationConfigError.textContent = redactSensitiveText(i18n.localizeExternalText(message));
    elements.translationConfigError.hidden = false;
  }

  function setTranslationFeedback(message = "", tone = "success") {
    if (!message) {
      elements.translationTestResult.hidden = true;
      elements.translationTestResult.textContent = "";
      elements.translationTestResult.dataset.tone = "";
      return;
    }
    elements.translationTestResult.textContent = redactSensitiveText(i18n.localizeExternalText(message));
    elements.translationTestResult.dataset.tone = tone;
    elements.translationTestResult.hidden = false;
  }

  function setTranslationConfigCollapsed(collapsed) {
    const isCollapsed = Boolean(collapsed);
    elements.translationCard.dataset.collapsed = String(isCollapsed);
    elements.translationConfigToggle.setAttribute("aria-expanded", String(!isCollapsed));
    elements.translationConfigToggle.textContent = isCollapsed
      ? t("번역 설정 열기")
      : t("번역 설정 닫기");
  }

  function setTranslationGlobalStatus(status, customLabel = "") {
    const normalized = normalizeTranslationStatus(status, state.translation.applied);
    state.translation.status = normalized;
    elements.translationGlobalStatus.dataset.status = normalized;
    elements.translationGlobalStatus.textContent = customLabel || (
      normalized === "success" ? t("준비됨") : translationStatusLabels[normalized]
    );
    elements.providerDetailStatus.textContent = elements.translationGlobalStatus.textContent;
  }

  function selectedTranslationProvider() {
    return state.translation.providers.get(state.translation.selected) || normalizeTranslationProvider(
      { id: state.translation.selected, available: state.translation.selected === "none" },
      state.translation.selected,
    );
  }

  function renderProviderAvailability() {
    elements.providerAvailabilityList.replaceChildren();
    ["none", "local", "openai", "gemini"].forEach((id) => {
      const provider = state.translation.providers.get(id) || normalizeTranslationProvider({ id }, id);
      const item = document.createElement("li");
      item.dataset.selected = String(id === state.translation.selected);
      if (provider.reason) item.title = i18n.localizeExternalText(provider.reason);

      const name = document.createElement("span");
      name.className = "provider-name";
      name.textContent = providerLabels[id] || provider.name;

      const availability = document.createElement("span");
      availability.className = "availability-badge";
      availability.dataset.available = String(provider.available);
      availability.textContent = provider.available ? t("사용 가능") : t("사용 불가");
      item.append(name, availability);
      elements.providerAvailabilityList.append(item);
    });
  }

  function renderTranslationProviderDetails() {
    const provider = selectedTranslationProvider();
    const settings = state.translation.settings;
    const isOpenAI = provider.id === "openai";
    const isGemini = provider.id === "gemini";
    const isLocal = provider.id === "local";
    const apiKeyConfigured = booleanValue(
      firstDefined(
        isGemini ? settings.geminiApiKeyConfigured : settings.openaiApiKeyConfigured,
        provider.apiKeyConfigured,
      ),
      false,
    );
    const external = isOpenAI || isGemini || booleanValue(firstDefined(provider.external, settings.external), false);

    elements.providerDetailProvider.textContent = providerLabels[provider.id] || provider.name;
    elements.translationBarProvider.textContent = providerLabels[provider.id] || provider.name;
    elements.providerDetailAvailability.textContent = provider.available ? t("사용 가능") : t("사용 불가");
    elements.providerDetailExternal.textContent = isGemini
      ? t("예 · Google Gemini")
      : external ? t("예 · 외부 전송") : t("아니요");
    elements.providerDetailApiKey.textContent = isOpenAI || isGemini
      ? apiKeyConfigured ? t("서버에 설정됨 · 값 비공개") : t("설정되지 않음")
      : t("해당 없음 · 값 표시 안 함");
    elements.providerDetailLocalModel.textContent = isLocal
      ? settings.localModelInstalled
        ? provider.model || state.translation.worker.model || t("설치됨")
        : t("미설치")
      : isOpenAI
        ? settings.openaiModel || provider.model || t("서버 기본 모델")
        : isGemini ? settings.geminiModel || provider.model || t("설정되지 않음") : t("해당 없음");
    elements.providerDetailWorkerRow.hidden = !isLocal;
    elements.providerDetailWorkerStatus.dataset.state = state.translation.worker.state;
    elements.providerDetailWorkerStatus.textContent = translationWorkerText();
    elements.translationSecurityNotice.hidden = !isOpenAI;
    elements.translationGeminiNotice.hidden = !isGemini;
    elements.translationLocalNotice.hidden = !isLocal;

    if (requiresExternalTranslationProvider() && isLocal) {
      elements.translationMethodHint.textContent = t("로컬 번역 모델은 일본어·영어→한국어 전용입니다. Gemini 또는 OpenAI를 선택하세요.");
    } else if (provider.id === "none") {
      elements.translationMethodHint.textContent = t("원문 전사만 표시하며 외부 API를 호출하지 않습니다.");
    } else if (!provider.available) {
      elements.translationMethodHint.textContent = i18n.localizeExternalText(provider.reason) || t("이 Provider를 현재 사용할 수 없습니다.");
    } else if (isOpenAI) {
      elements.translationMethodHint.textContent = t("확정 원문만 서버를 통해 OpenAI API로 번역합니다.");
    } else if (isGemini) {
      elements.translationMethodHint.textContent = t("확정 원문만 Google Gemini API로 번역합니다.");
    } else {
      elements.translationMethodHint.textContent = t("설치된 로컬 모델로 확정 원문을 번역합니다.");
    }
    renderTranslationDirection({ resetInvalid: false });
    if (state.translation.selected !== state.translation.applied) {
      elements.providerDetailStatus.textContent = t("설정 적용 전");
    }
    renderProviderAvailability();
    updateTranslationControls();
  }

  function installTranslationProviders(payload) {
    const root = normalizedTranslationRoot(payload);
    const rawProviders = firstDefined(root.providers, root.items, root.available_providers, []);
    const map = new Map();
    if (Array.isArray(rawProviders)) {
      rawProviders.forEach((provider) => {
        const normalized = normalizeTranslationProvider(provider);
        map.set(normalized.id, normalized);
      });
    } else {
      Object.entries(asObject(rawProviders)).forEach(([id, provider]) => {
        const normalized = normalizeTranslationProvider(provider, id);
        map.set(normalized.id, normalized);
      });
    }
    map.set("none", normalizeTranslationProvider({ id: "none", available: true, external: false }));
    ["local", "openai", "gemini"].forEach((id) => {
      if (!map.has(id)) map.set(id, normalizeTranslationProvider({ id, available: false }, id));
    });
    state.translation.providers = map;

    const selected = normalizeProviderId(firstDefined(root.selected_provider, root.provider, state.translation.selected));
    if (["none", "local", "openai", "gemini"].includes(selected)) state.translation.selected = selected;
  }

  function applyTranslationSettingsPayload(payload, fallbackProvider) {
    const settings = translationSettingsFrom(payload, fallbackProvider);
    state.translation.settings = settings;
    if (Object.keys(settings.worker).length) {
      applyTranslationWorkerPayload(settings.worker, { render: false });
    }
    state.translation.applied = settings.provider;
    state.translation.selected = settings.provider;
    if (state.sessions?.current && !state.sessions.restoredId) {
      state.sessions.current = { ...state.sessions.current, translationProvider: settings.provider };
      renderCurrentSession();
    }
    elements.translationMethodSelect.value = settings.provider;

    const provider = state.translation.providers.get(settings.provider);
    const providerAvailable = settings.provider === "none" || provider?.available === true;
    const status = settings.provider === "none"
      ? "disabled"
      : !providerAvailable
        ? "error"
        : normalizeTranslationStatus(settings.status || "ready", settings.provider);
    setTranslationGlobalStatus(status, status === "success" ? t("준비됨") : "");
    renderTranslationProviderDetails();
  }

  async function loadTranslationConfiguration() {
    state.translation.loading = true;
    setTranslationConfigError();
    updateTranslationControls();
    const [providersResult, settingsResult] = await Promise.allSettled([
      apiRequest("/api/translation/providers"),
      apiRequest("/api/translation/settings"),
    ]);

    if (providersResult.status === "fulfilled") {
      installTranslationProviders(providersResult.value);
    } else {
      installTranslationProviders({ providers: [{ id: "none", available: true }] });
      setTranslationConfigError(t("Provider 조회 실패: {message}", { message: extractMessage(providersResult.reason) }));
    }

    if (settingsResult.status === "fulfilled") {
      applyTranslationSettingsPayload(settingsResult.value, state.translation.selected);
    } else {
      state.translation.applied = "none";
      state.translation.selected = "none";
      state.translation.settings = translationSettingsFrom({}, "none");
      elements.translationMethodSelect.value = "none";
      setTranslationGlobalStatus("disabled");
      renderTranslationProviderDetails();
      const prefix = elements.translationConfigError.hidden ? "" : `${elements.translationConfigError.textContent} · `;
      setTranslationConfigError(`${prefix}${t("설정 조회 실패: {message}", { message: extractMessage(settingsResult.reason) })}`);
    }

    state.translation.loading = false;
    updateTranslationControls();
  }

  function setRuntimeHealth(element, text, tone = "neutral") {
    if (!element) return;
    element.textContent = i18n.localizeExternalText(text);
    element.dataset.tone = tone;
  }

  function applyRuntimeDiagnostics(payload) {
    const object = asObject(payload);
    const server = asObject(object.server);
    const stt = asObject(server.stt);
    const capture = asObject(server.capture);
    const queue = asObject(server.translation_queue);
    const activeCapture = ["listening", "transcribing", "paused"].includes(
      String(firstDefined(server.capture_state, state.captureState, "")),
    );

    if (String(stt.provider) === "deepgram") {
      if (booleanValue(stt.reconnect_exhausted, false)) {
        setRuntimeHealth(elements.sttRuntimeHealth, t("재연결 실패"), "danger");
      } else if (booleanValue(stt.reconnecting, false)) {
        const attempt = Math.max(0, Number(stt.reconnect_attempts) || 0);
        setRuntimeHealth(elements.sttRuntimeHealth, t("재연결 중 · {count}회", { count: attempt }), "warning");
      } else if (booleanValue(stt.connected, false)) {
        const count = Math.max(0, Number(stt.reconnect_count) || 0);
        setRuntimeHealth(
          elements.sttRuntimeHealth,
          count ? t("연결됨 · 복구 {count}회", { count }) : t("연결됨"),
          "success",
        );
      } else {
        setRuntimeHealth(
          elements.sttRuntimeHealth,
          activeCapture ? t("연결 끊김") : t("대기"),
          activeCapture ? "danger" : "neutral",
        );
      }
    } else {
      setRuntimeHealth(
        elements.sttRuntimeHealth,
        activeCapture ? t("로컬 인식 중") : t("로컬 대기"),
        activeCapture ? "success" : "neutral",
      );
    }

    const droppedFrames = Math.max(0, Number(capture.dropped_frames) || 0);
    const bufferedMs = Math.max(0, Number(stt.buffered_audio_ms) || 0);
    const droppedAudioMs = Math.max(0, Number(stt.dropped_audio_ms) || 0);
    if (droppedFrames || droppedAudioMs) {
      const details = [];
      if (droppedFrames) details.push(t("프레임 {count}", { count: droppedFrames }));
      if (droppedAudioMs) details.push(t("재연결 {milliseconds}ms", { milliseconds: Math.round(droppedAudioMs) }));
      setRuntimeHealth(elements.audioRuntimeHealth, t("드롭 · {details}", { details: details.join(" / ") }), "danger");
    } else if (bufferedMs) {
      setRuntimeHealth(elements.audioRuntimeHealth, t("버퍼 {milliseconds}ms", { milliseconds: Math.round(bufferedMs) }), "warning");
    } else {
      setRuntimeHealth(elements.audioRuntimeHealth, t("정상"), "success");
    }

    const queueSize = Math.max(0, Number(queue.queue_size) || 0);
    const queueMax = Math.max(1, Number(queue.queue_max_size) || 100);
    const oldestWaitMs = Math.max(0, Number(queue.oldest_wait_ms) || 0);
    const delayed = queueSize > 0
      && (oldestWaitMs >= 2_000 || queueSize >= Math.ceil(queueMax / 2));
    const queueText = oldestWaitMs
      ? `${queueSize} / ${queueMax} · ${t("{seconds}초", { seconds: Math.round(oldestWaitMs / 100) / 10 })}`
      : `${queueSize} / ${queueMax}`;
    setRuntimeHealth(
      elements.translationQueueHealth,
      queueText,
      delayed ? "warning" : queueSize ? "neutral" : "success",
    );
  }

  async function refreshTranslationWorkerStatus({ quiet = true } = {}) {
    if (state.translation.workerStatusLoading) return;
    state.translation.workerStatusLoading = true;
    try {
      const payload = await apiRequest("/api/diagnostics", { timeout: 5_000 });
      applyTranslationWorkerPayload(payload);
      applyRuntimeDiagnostics(payload);
    } catch (error) {
      if (!quiet) {
        setTranslationConfigError(t("Worker 상태 조회 실패: {message}", { message: extractMessage(error) }));
      }
    } finally {
      state.translation.workerStatusLoading = false;
    }
  }

  function startTranslationWorkerPolling() {
    if (state.translation.workerPollTimer) window.clearInterval(state.translation.workerPollTimer);
    state.translation.workerPollTimer = window.setInterval(
      () => refreshTranslationWorkerStatus({ quiet: true }),
      2_000,
    );
  }

  function refreshCardsAfterProviderChange() {
    if (state.translation.applied !== "none") return;
    state.translation.cards.forEach((card) => {
      const current = card.querySelector(".segment-translation")?.dataset.status;
      if (current !== "success") {
        updateTranslationCard(card, { status: "disabled" }, { force: true });
      }
    });
  }

  async function saveTranslationSettings() {
    const provider = state.translation.selected;
    const selected = selectedTranslationProvider();
    if (provider !== "none" && !selected.available) {
      setTranslationConfigError(i18n.localizeExternalText(selected.reason) || t("선택한 Provider를 현재 사용할 수 없습니다."));
      return;
    }
    state.translation.saving = true;
    setTranslationConfigError();
    setTranslationFeedback();
    setTranslationGlobalStatus("pending", t("설정 적용 중"));
    updateTranslationControls();
    try {
      const payload = await apiRequest("/api/translation/settings", {
        method: "POST",
        body: { provider },
        timeout: 20_000,
      });
      applyTranslationSettingsPayload(payload, provider);
      refreshCardsAfterProviderChange();
      setTranslationFeedback(t("{provider} 설정을 적용했습니다.", { provider: providerLabels[state.translation.applied] }));
    } catch (error) {
      setTranslationConfigError(t("번역 설정 적용 실패: {message}", { message: extractMessage(error) }));
      state.translation.selected = state.translation.applied;
      elements.translationMethodSelect.value = state.translation.applied;
      setTranslationGlobalStatus(state.translation.applied === "none" ? "disabled" : "error");
      renderTranslationProviderDetails();
    } finally {
      state.translation.saving = false;
      updateTranslationControls();
    }
  }

  function translationLatencyValue(payload) {
    const root = normalizedTranslationRoot(payload);
    const milliseconds = Number(firstDefined(root.latency_ms, root.duration_ms, root.elapsed_ms, root.inference_ms));
    if (Number.isFinite(milliseconds) && milliseconds >= 0) return milliseconds;
    const seconds = Number(firstDefined(root.latency_seconds, root.duration_seconds, root.elapsed_seconds));
    return Number.isFinite(seconds) && seconds >= 0 ? seconds * 1_000 : null;
  }

  function formatTranslationLatency(milliseconds) {
    if (!Number.isFinite(milliseconds)) return "";
    return milliseconds < 1_000
      ? `${Math.round(milliseconds)}ms`
      : t("{seconds}초", { seconds: (milliseconds / 1_000).toFixed(2) });
  }

  async function testTranslationProvider() {
    const provider = state.translation.selected;
    if (provider === "none") return;
    state.translation.testing = true;
    setTranslationConfigError();
    setTranslationFeedback(t("번역 연결을 테스트하는 중입니다…"), "pending");
    updateTranslationControls();
    try {
      const payload = await apiRequest("/api/translation/test", {
        method: "POST",
        body: {
          text: {
            ko: "회의를 시작하겠습니다",
            ja: "会議を始めます",
            en: "We will start the meeting",
          }[directionSourceLanguage()],
          source_language: directionSourceLanguage(),
          target_language: directionTargetLanguage(),
        },
        timeout: 30_000,
      });
      const root = normalizedTranslationRoot(payload);
      const status = normalizeTranslationStatus(firstDefined(root.status, root.result_status, "success"), provider);
      if (status === "error" || root.success === false) {
        throw new Error(extractMessage(root, t("번역 테스트에 실패했습니다.")));
      }
      const latency = formatTranslationLatency(translationLatencyValue(root));
      setTranslationFeedback(t("테스트 성공 · {provider}{latency}", {
        provider: providerLabels[provider],
        latency: latency ? ` · ${latency}` : "",
      }));
    } catch (error) {
      setTranslationFeedback();
      setTranslationConfigError(t("번역 테스트 실패: {message}", { message: extractMessage(error) }));
    } finally {
      state.translation.testing = false;
      updateTranslationControls();
    }
  }

  function normalizeSessionStatus(value) {
    const raw = String(value || "").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["active", "running", "recording", "listening", "transcribing", "stopping", "finalizing"].includes(raw)) return "active";
    if (["completed", "complete", "saved", "stopped", "closed", "archived", "recovered"].includes(raw)) return "saved";
    if (["failed", "failure", "error"].includes(raw)) return "error";
    if (raw === "paused") return "paused";
    return "idle";
  }

  function normalizeSession(rawSession) {
    const raw = asObject(rawSession);
    const metadata = asObject(firstDefined(raw.metadata, raw.session_metadata));
    const sessionId = firstDefined(raw.session_id, raw.sessionId, raw.id, metadata.session_id, metadata.id);
    return {
      sessionId: sessionId === undefined || sessionId === null ? "" : String(sessionId),
      status: String(firstDefined(raw.status, raw.session_status, metadata.status, "saved")),
      createdAt: firstDefined(raw.created_at, raw.createdAt, metadata.created_at),
      startedAt: firstDefined(raw.started_at, raw.startedAt, metadata.started_at, raw.created_at),
      endedAt: firstDefined(raw.ended_at, raw.endedAt, metadata.ended_at),
      source: normalizeSource(firstDefined(raw.source, raw.audio_source, metadata.source, "system")),
      model: String(firstDefined(raw.whisper_model, raw.model, metadata.whisper_model, metadata.model, "—")),
      translationProvider: normalizeProviderId(firstDefined(
        raw.translation_provider,
        raw.translationProvider,
        raw.provider,
        metadata.translation_provider,
        "none",
      )),
      segmentCount: Math.max(0, Number(firstDefined(
        raw.segment_count,
        raw.segmentCount,
        raw.original_count,
        metadata.segment_count,
        0,
      )) || 0),
      translatedSegmentCount: Math.max(0, Number(firstDefined(
        raw.translated_segment_count,
        raw.translatedSegmentCount,
        raw.translation_count,
        metadata.translated_segment_count,
        0,
      )) || 0),
    };
  }

  function normalizeSessionListPayload(payload) {
    if (Array.isArray(payload)) return payload.map(normalizeSession).filter((session) => session.sessionId);
    const root = normalizedTranslationRoot(payload);
    return asArray(firstDefined(root.sessions, root.items, root.results, []))
      .map(normalizeSession)
      .filter((session) => session.sessionId);
  }

  function normalizeSessionSegment(rawSegment, fallbackSessionId = "") {
    const raw = asObject(rawSegment);
    const original = asObject(firstDefined(raw.original, raw.transcript, raw.segment));
    const translation = asObject(firstDefined(raw.translation, raw.translation_result));
    const segmentId = firstDefined(raw.segment_id, raw.segmentId, raw.id, original.segment_id);
    const text = String(firstDefined(
      raw.text,
      raw.original_text,
      raw.source_text,
      original.text,
      original.source_text,
      "",
    )).trim();
    const translated = String(firstDefined(
      raw.translated_text,
      raw.translation_text,
      raw.korean_translation,
      translation.translated_text,
      translation.text,
      "",
    )).trim();
    const status = firstDefined(
      translation.status,
      raw.translation_status,
      translated ? "completed" : "disabled",
    );
    const translationFailed = ["failed", "failure", "error", "cancelled", "canceled", "timeout"]
      .includes(String(status).toLowerCase());
    return {
      segment_id: segmentId === undefined || segmentId === null ? "" : String(segmentId),
      session_id: String(firstDefined(raw.session_id, original.session_id, fallbackSessionId, "")),
      text,
      normalized_text: String(firstDefined(raw.normalized_text, raw.normalizedText, text)).trim(),
      context_changed: booleanValue(firstDefined(raw.context_changed, raw.contextChanged), false),
      context_matches: asArray(firstDefined(raw.context_matches, raw.contextMatches, [])),
      original_saved: booleanValue(firstDefined(raw.original_saved, raw.originalSaved), Boolean(text)),
      language: firstDefined(raw.language, raw.source_language, original.language, "unknown"),
      language_probability: firstDefined(raw.language_probability, original.language_probability),
      source: firstDefined(raw.source, original.source, "system"),
      started_at: firstDefined(raw.started_at, raw.start_time, original.started_at, raw.timestamp),
      ended_at: firstDefined(raw.ended_at, raw.end_time, original.ended_at, raw.timestamp),
      historical: true,
      translation_result: translated
        ? {
            type: "translation",
            segment_id: segmentId,
            session_id: firstDefined(raw.session_id, fallbackSessionId),
            translated_text: translated,
            provider: firstDefined(translation.provider, raw.translation_provider, raw.provider, "unknown"),
            model: firstDefined(translation.model, raw.translation_model),
            status,
            latency_ms: firstDefined(translation.latency_ms, raw.translation_latency_ms, raw.latency_ms),
            completed_at: firstDefined(translation.completed_at, raw.translation_completed_at),
          }
        : translationFailed
          ? {
              type: "translation_error",
              segment_id: segmentId,
              session_id: firstDefined(raw.session_id, fallbackSessionId),
              provider: firstDefined(translation.provider, raw.translation_provider, raw.provider, "unknown"),
              status,
              error_code: firstDefined(raw.translation_error_code, translation.error_code),
              error_message: t("저장된 세션에서 이 문장의 번역이 완료되지 않았습니다."),
            }
          : null,
    };
  }

  function normalizeSessionSegmentsPayload(payload, sessionId = "") {
    if (Array.isArray(payload)) {
      return payload
        .map((segment) => normalizeSessionSegment(segment, sessionId))
        .filter((segment) => segment.segment_id && (segment.text || segment.translation_result));
    }
    const outer = asObject(payload);
    const data = asObject(outer.data);
    const root = { ...outer, ...data };
    const resolvedSessionId = String(firstDefined(root.session_id, sessionId, ""));
    return asArray(firstDefined(root.segments, root.items, root.transcripts, []))
      .map((segment) => normalizeSessionSegment(segment, resolvedSessionId))
      .filter((segment) => segment.segment_id && (segment.text || segment.translation_result));
  }

  function sessionIdSet(map, sessionId) {
    if (!sessionId) return null;
    if (!map.has(sessionId)) map.set(sessionId, new Set());
    return map.get(sessionId);
  }

  function registerOriginalSegment(sessionId, segmentId) {
    if (!sessionId || !segmentId) return;
    sessionIdSet(state.sessions.originalSegmentIds, sessionId).add(segmentId);
    if (state.sessions.current?.sessionId === sessionId) renderCurrentSession();
  }

  function registerTranslatedSegment(sessionId, segmentId) {
    if (!sessionId || !segmentId) return;
    sessionIdSet(state.sessions.translatedSegmentIds, sessionId).add(segmentId);
    if (state.sessions.current?.sessionId === sessionId) renderCurrentSession();
  }

  function sessionCount(session, map, fallbackKey) {
    if (!session?.sessionId) return 0;
    const tracked = map.get(session.sessionId);
    return tracked ? tracked.size : Number(session[fallbackKey] || 0);
  }

  function formatSessionTime(session) {
    if (!session) return "—";
    const start = parseDate(firstDefined(session.startedAt, session.createdAt));
    const end = parseDate(session.endedAt);
    if (!start && !end) return "—";
    const dateFormatter = new Intl.DateTimeFormat(UI_LOCALE, {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    const startText = start ? dateFormatter.format(start) : t("시작 미확인");
    if (!end) return t("{start}–진행 중", { start: startText });
    const endText = dateFormatter.format(end);
    return `${startText}–${endText}`;
  }

  function sessionStatusPresentation(session) {
    const status = normalizeSessionStatus(session?.status);
    const labels = {
      active: t("진행 중"),
      paused: t("일시정지"),
      saved: t("저장됨"),
      error: t("오류"),
      idle: t("세션 없음"),
    };
    return { status, label: labels[status] };
  }

  function renderCurrentSession() {
    const session = state.sessions.current;
    const presentation = sessionStatusPresentation(session);
    elements.sessionStatusBadge.dataset.status = presentation.status;
    elements.sessionStatusBadge.textContent = presentation.label;
    elements.sessionViewMode.textContent = state.sessions.restoredId ? t("보관 세션 보기") : t("실시간");
    elements.currentSessionId.textContent = session?.sessionId || "—";
    elements.currentSessionTime.textContent = formatSessionTime(session);
    elements.currentSessionSource.textContent = session ? sourceLabels[session.source] || session.source : "—";
    elements.currentSessionModel.textContent = session?.model || "—";
    elements.currentSessionTranslation.textContent = session
      ? providerLabels[session.translationProvider] || session.translationProvider
      : providerLabels[state.translation.applied];
    elements.currentSessionOriginalCount.textContent = String(sessionCount(
      session,
      state.sessions.originalSegmentIds,
      "segmentCount",
    ));
    elements.currentSessionTranslationCount.textContent = String(sessionCount(
      session,
      state.sessions.translatedSegmentIds,
      "translatedSegmentCount",
    ));
  }

  function setSessionFeedback(message = "") {
    elements.sessionFeedback.textContent = i18n.localizeExternalText(message);
    elements.sessionFeedback.hidden = !message;
  }

  function setSessionError(message = "") {
    elements.sessionError.textContent = message ? redactSensitiveText(i18n.localizeExternalText(message)) : "";
    elements.sessionError.hidden = !message;
  }

  function sessionOptionLabel(session) {
    const start = parseDate(firstDefined(session.startedAt, session.createdAt));
    const date = start
      ? new Intl.DateTimeFormat(UI_LOCALE, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(start)
      : t("시간 미확인");
    const source = sourceLabels[session.source] || session.source;
    return t("{date} · {source} · 원문 {count}", { date, source, count: session.segmentCount });
  }

  function renderSessionList() {
    const sessions = state.sessions.list;
    const previous = state.sessions.selectedId;
    elements.sessionSelect.replaceChildren();
    if (!sessions.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = t("저장된 세션이 없습니다");
      elements.sessionSelect.append(option);
      state.sessions.selectedId = "";
      elements.sessionSelectionHint.textContent = t("캡처를 시작하면 저장된 세션이 여기에 표시됩니다.");
      updateSessionControls();
      return;
    }

    sessions.forEach((session) => {
      const option = document.createElement("option");
      option.value = session.sessionId;
      option.textContent = sessionOptionLabel(session);
      option.title = `${session.sessionId} · ${option.textContent}`;
      elements.sessionSelect.append(option);
    });
    const preferred = [state.sessions.current?.sessionId, previous, sessions[0].sessionId]
      .find((id) => id && sessions.some((session) => session.sessionId === id));
    state.sessions.selectedId = preferred || sessions[0].sessionId;
    elements.sessionSelect.value = state.sessions.selectedId;
    updateSessionSelectionHint();
    updateSessionControls();
  }

  function updateSessionSelectionHint() {
    const selected = state.sessions.list.find((session) => session.sessionId === state.sessions.selectedId);
    elements.sessionSelectionHint.textContent = selected
      ? t("{sessionId} · 원문 {originalCount} · 번역 {translationCount}", {
        sessionId: selected.sessionId,
        originalCount: selected.segmentCount,
        translationCount: selected.translatedSegmentCount,
      })
      : t("저장된 세션을 선택해 자막을 다시 표시할 수 있습니다.");
  }

  async function loadSessionList({ quiet = false } = {}) {
    state.sessions.loadingList = true;
    if (!quiet) {
      setSessionError();
      setSessionFeedback();
    }
    updateSessionControls();
    try {
      const payload = await apiRequest("/api/sessions");
      state.sessions.list = normalizeSessionListPayload(payload);
      renderSessionList();
      if (!quiet) setSessionFeedback(t("저장된 세션 {count}개를 불러왔습니다.", { count: state.sessions.list.length }));
    } catch (error) {
      state.sessions.list = [];
      renderSessionList();
      if (!quiet) setSessionError(t("세션 목록 조회 실패: {message}", { message: extractMessage(error) }));
    } finally {
      state.sessions.loadingList = false;
      updateSessionControls();
    }
  }

  function normalizeSessionSettings(payload) {
    const root = normalizedTranslationRoot(payload);
    return {
      saveOriginal: booleanValue(firstDefined(root.save_original, root.saveOriginal), true),
      saveTranslation: booleanValue(firstDefined(root.save_translation, root.saveTranslation), true),
      saveAnalysis: booleanValue(firstDefined(root.save_analysis, root.saveAnalysis), true),
    };
  }

  function renderSessionSettings() {
    elements.saveOriginalToggle.checked = state.sessions.settings.saveOriginal;
    elements.saveTranslationToggle.checked = state.sessions.settings.saveTranslation;
    elements.saveAnalysisToggle.checked = state.sessions.settings.saveAnalysis;
    updateSessionControls();
  }

  async function loadSessionSettings() {
    try {
      const payload = await apiRequest("/api/session/settings");
      const settings = normalizeSessionSettings(payload);
      state.sessions.settings = { ...settings };
      state.sessions.savedSettings = { ...settings };
      renderSessionSettings();
    } catch (error) {
      setSessionError(t("저장 설정 조회 실패: {message}", { message: extractMessage(error) }));
      renderSessionSettings();
    }
  }

  async function saveSessionSettings() {
    state.sessions.savingSettings = true;
    setSessionError();
    setSessionFeedback();
    updateSessionControls();
    try {
      const payload = await apiRequest("/api/session/settings", {
        method: "POST",
        body: {
          save_original: state.sessions.settings.saveOriginal,
          save_translation: state.sessions.settings.saveTranslation,
          save_analysis: state.sessions.settings.saveAnalysis,
        },
      });
      const settings = normalizeSessionSettings(payload);
      state.sessions.settings = { ...settings };
      state.sessions.savedSettings = { ...settings };
      renderSessionSettings();
      setSessionFeedback(t("세션 저장 설정을 적용했습니다."));
    } catch (error) {
      setSessionError(t("저장 설정 적용 실패: {message}", { message: extractMessage(error) }));
    } finally {
      state.sessions.savingSettings = false;
      updateSessionControls();
    }
  }

  async function loadSessionBundle(sessionId, { refresh = false } = {}) {
    if (!refresh && state.sessions.segmentsBySession.has(sessionId)) {
      const summary = state.sessions.list.find((session) => session.sessionId === sessionId);
      return { session: summary || normalizeSession({ session_id: sessionId }), segments: state.sessions.segmentsBySession.get(sessionId) };
    }

    const encodedId = encodeURIComponent(sessionId);
    const [detailResult, segmentsResult] = await Promise.allSettled([
      apiRequest(`/api/sessions/${encodedId}`),
      apiRequest(`/api/sessions/${encodedId}/segments`),
    ]);
    if (detailResult.status === "rejected" && segmentsResult.status === "rejected") {
      throw new Error(
        t("세션 상세 조회 실패: {detail} · {segments}", {
          detail: extractMessage(detailResult.reason),
          segments: extractMessage(segmentsResult.reason),
        }),
      );
    }

    const detailPayload = detailResult.status === "fulfilled" ? detailResult.value : {};
    const detailRoot = normalizedTranslationRoot(detailPayload);
    const detailSession = Object.keys(asObject(detailRoot.session)).length
      ? asObject(detailRoot.session)
      : detailRoot;
    const session = normalizeSession({
      ...(state.sessions.list.find((item) => item.sessionId === sessionId) || {}),
      ...detailSession,
      session_id: sessionId,
    });
    const segmentPayload = segmentsResult.status === "fulfilled"
      ? segmentsResult.value
      : firstDefined(detailRoot.segments, detailSession.segments, []);
    const segments = normalizeSessionSegmentsPayload(segmentPayload, sessionId);
    state.sessions.segmentsBySession.set(sessionId, segments);
    return { session, segments };
  }

  function clearTranscriptView() {
    elements.transcriptList.replaceChildren();
    elements.emptyState.hidden = false;
    state.seenFinals.clear();
    state.fallbackFinals.clear();
    state.translation.cards.clear();
    state.translation.deferredEvents.clear();
    clearPartial();
  }

  async function restoreSelectedSession() {
    const sessionId = state.sessions.selectedId;
    if (!sessionId) return;
    if (["listening", "transcribing", "paused"].includes(state.captureState)) {
      setSessionError(t("캡처 중에는 보관 세션을 복원할 수 없습니다. 먼저 캡처를 중지하세요."));
      return;
    }
    state.sessions.loadingSession = true;
    setSessionError();
    setSessionFeedback(t("세션 자막을 복원하는 중입니다…"));
    updateSessionControls();
    try {
      const bundle = await loadSessionBundle(sessionId, { refresh: true });
      clearTranscriptView();
      state.sessions.restoredId = sessionId;
      state.sessions.current = {
        ...bundle.session,
        segmentCount: bundle.segments.length,
        translatedSegmentCount: bundle.segments.filter((segment) => segment.translation_result?.translated_text).length,
      };
      state.sessions.originalSegmentIds.set(sessionId, new Set());
      state.sessions.translatedSegmentIds.set(sessionId, new Set());
      bundle.segments.forEach(renderFinalTranscript);
      renderCurrentSession();
      await loadAnalysisForSession(sessionId, { quiet: true });
      setSessionFeedback(t("세션 원문 {count}개를 순서대로 복원했습니다.", { count: bundle.segments.length }));
    } catch (error) {
      setSessionError(t("세션 복원 실패: {message}", { message: extractMessage(error) }));
      setSessionFeedback();
    } finally {
      state.sessions.loadingSession = false;
      updateSessionControls();
    }
  }

  function copyFallback(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.append(textarea);
    textarea.focus();
    textarea.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (_error) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  async function writeClipboard(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await Promise.race([
          navigator.clipboard.writeText(text),
          new Promise((_, reject) => window.setTimeout(
            () => reject(new Error("clipboard_timeout")),
            1_500,
          )),
        ]);
        return true;
      } catch (_error) {
        // A clearly reported legacy fallback is attempted below.
      }
    }
    return copyFallback(text);
  }

  async function copySelectedSession(kind) {
    const sessionId = state.sessions.selectedId;
    if (!sessionId) return;
    state.sessions.loadingSession = true;
    setSessionError();
    setSessionFeedback();
    updateSessionControls();
    try {
      const { segments } = await loadSessionBundle(sessionId, { refresh: true });
      const lines = kind === "translation"
        ? segments.map((segment) => segment.translation_result?.translated_text || "").filter(Boolean)
        : segments.map((segment) => segment.text).filter(Boolean);
      if (!lines.length) {
        throw new Error(kind === "translation" ? t("복사할 번역이 없습니다.") : t("복사할 원문이 없습니다."));
      }
      const copied = await writeClipboard(lines.join("\n"));
      if (!copied) {
        throw new Error(
          t("클립보드 권한이 거부되었습니다. localhost의 클립보드 권한을 허용하거나 TXT 다운로드를 이용하세요."),
        );
      }
      setSessionFeedback(kind === "translation"
        ? t("전체 번역을 클립보드에 복사했습니다.")
        : t("전체 원문을 클립보드에 복사했습니다."));
    } catch (error) {
      setSessionError(t("클립보드 복사 실패: {message}", { message: extractMessage(error) }));
    } finally {
      state.sessions.loadingSession = false;
      updateSessionControls();
    }
  }

  function downloadFilename(response, sessionId, format) {
    const disposition = response.headers.get("content-disposition") || "";
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
    let filename = "";
    try {
      filename = decodeURIComponent(firstDefined(utf8Match?.[1], plainMatch?.[1], ""));
    } catch (_error) {
      filename = "";
    }
    const extensions = { json: "json", "original-txt": "txt", "translation-txt": "txt", markdown: "md" };
    const fallback = `meeting-session-${sessionId}.${extensions[format] || "txt"}`;
    const safe = filename.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").trim();
    return safe || fallback;
  }

  async function downloadSelectedSession(format) {
    const sessionId = state.sessions.selectedId;
    if (!sessionId || !["json", "original-txt", "translation-txt", "markdown"].includes(format)) return;
    state.sessions.downloading = true;
    setSessionError();
    setSessionFeedback(t("{format} 파일을 준비하는 중입니다…", { format: format.toUpperCase() }));
    updateSessionControls();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    try {
      const url = `/api/sessions/${encodeURIComponent(sessionId)}/download/${format}`;
      const response = await fetch(url, {
        method: "GET",
        headers: { Accept: "application/octet-stream, application/json, text/plain, text/markdown" },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) {
        const payload = await response.text().catch(() => "");
        throw new Error(extractMessage(payload, t("다운로드 실패 (HTTP {status})", { status: response.status })));
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = downloadFilename(response, sessionId, format);
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
      setSessionFeedback(t("{filename} 다운로드를 시작했습니다.", { filename: anchor.download }));
    } catch (error) {
      const message = error.name === "AbortError" ? t("다운로드 응답 시간이 초과되었습니다.") : extractMessage(error);
      setSessionError(t("세션 다운로드 실패: {message}", { message }));
      setSessionFeedback();
    } finally {
      window.clearTimeout(timeout);
      state.sessions.downloading = false;
      updateSessionControls();
    }
  }

  function syncSessionFromCapturePayload(object, nested) {
    const sessionIdValue = firstDefined(object.session_id, nested.session_id);
    const sessionId = sessionIdValue === undefined || sessionIdValue === null ? "" : String(sessionIdValue);
    const captureStatus = normalizeStatus(firstDefined(object.state, nested.state, object.status, state.captureState));
    if (sessionId) {
      const isNewSession = state.sessions.current?.sessionId !== sessionId;
      if (isNewSession && (state.sessions.restoredId || elements.transcriptList.children.length)) {
        clearTranscriptView();
      }
      state.sessions.restoredId = "";
      state.sessions.current = {
        ...(isNewSession ? {} : state.sessions.current),
        sessionId,
        status: ["listening", "transcribing", "paused"].includes(captureStatus) ? captureStatus : "saved",
        createdAt: isNewSession ? new Date().toISOString() : state.sessions.current?.createdAt || new Date().toISOString(),
        startedAt: isNewSession ? new Date().toISOString() : state.sessions.current?.startedAt || new Date().toISOString(),
        endedAt: ["stopped", "error"].includes(captureStatus) ? new Date().toISOString() : null,
        source: normalizeSource(firstDefined(object.source, nested.source, state.source)),
        model: String(firstDefined(object.model, nested.model, elements.modelSelect.value, "—")),
        translationProvider: state.translation.applied,
        segmentCount: isNewSession ? 0 : state.sessions.current?.segmentCount || 0,
        translatedSegmentCount: isNewSession ? 0 : state.sessions.current?.translatedSegmentCount || 0,
      };
    } else if (state.sessions.current && ["stopped", "error"].includes(captureStatus) && !state.sessions.restoredId) {
      state.sessions.current = {
        ...state.sessions.current,
        status: captureStatus === "error" ? "error" : "saved",
        endedAt: state.sessions.current.endedAt || new Date().toISOString(),
      };
    }
    renderCurrentSession();
  }

  function normalizeDecisionRadarProviderId(value) {
    const raw = String(value || "none").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["none", "off", "disabled"].includes(raw)) return "none";
    if (["openai", "openai_api"].includes(raw)) return "openai";
    if (["gemini", "gemini_api", "google", "google_gemini"].includes(raw)) return "gemini";
    return raw;
  }

  function normalizeDecisionRadarStatus(value, provider = state.decisionRadar.applied) {
    if (normalizeDecisionRadarProviderId(provider) === "none") return "disabled";
    const raw = String(value || "idle").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["queued", "pending", "collecting", "buffering"].includes(raw)) return "buffering";
    if (["running", "processing", "analyzing", "in_progress"].includes(raw)) return "running";
    if (["failed", "failure", "unavailable", "error"].includes(raw)) return "error";
    if (["closed", "stopped"].includes(raw)) return "closed";
    return "idle";
  }

  function normalizeDecisionRadarProvider(rawProvider, fallbackId) {
    const raw = typeof rawProvider === "string" ? { name: rawProvider } : asObject(rawProvider);
    const id = normalizeDecisionRadarProviderId(firstDefined(raw.id, raw.provider, raw.name, fallbackId));
    return {
      id,
      name: i18n.localizeExternalText(String(firstDefined(raw.display_name, providerLabels[id], raw.name, id))),
      available: id === "none" || booleanValue(firstDefined(raw.available, raw.is_available, raw.ready), false),
      external: id !== "none" && booleanValue(firstDefined(raw.external, raw.is_external), true),
      reason: redactSensitiveText(i18n.localizeExternalText(firstDefined(raw.reason, raw.unavailable_reason, ""))),
      model: String(firstDefined(raw.model, "")),
      apiKeyConfigured: booleanValue(firstDefined(raw.api_key_configured, raw.apiKeyConfigured), false),
    };
  }

  function installDecisionRadarProviders(payload) {
    const root = normalizedTranslationRoot(payload);
    const rawProviders = firstDefined(root.providers, root.items, []);
    const providers = new Map();
    if (Array.isArray(rawProviders)) {
      rawProviders.forEach((provider) => {
        const normalized = normalizeDecisionRadarProvider(provider);
        providers.set(normalized.id, normalized);
      });
    } else {
      Object.entries(asObject(rawProviders)).forEach(([id, provider]) => {
        const normalized = normalizeDecisionRadarProvider(provider, id);
        providers.set(normalized.id, normalized);
      });
    }
    providers.set("none", normalizeDecisionRadarProvider({ id: "none", available: true, external: false }));
    ["openai", "gemini"].forEach((id) => {
      if (!providers.has(id)) providers.set(id, normalizeDecisionRadarProvider({ id, available: false }, id));
    });
    state.decisionRadar.providers = providers;
    const selected = normalizeDecisionRadarProviderId(firstDefined(root.selected_provider, root.provider, state.decisionRadar.selected));
    if (["none", "openai", "gemini"].includes(selected)) state.decisionRadar.selected = selected;
  }

  function selectedDecisionRadarProvider() {
    return state.decisionRadar.providers.get(state.decisionRadar.selected)
      || normalizeDecisionRadarProvider({ id: state.decisionRadar.selected, available: false });
  }

  function normalizeDecisionRadarItem(value) {
    const item = asObject(value);
    const category = String(firstDefined(item.category, "decision")).trim().toLowerCase();
    return {
      id: String(firstDefined(item.item_id, item.id, "")).trim(),
      category: ["decision", "action_item", "open_question", "needs_confirmation"].includes(category)
        ? category
        : "needs_confirmation",
      text: String(firstDefined(item.text, item.task, "")).trim(),
      assignee: String(firstDefined(item.assignee, "")).trim(),
      dueDate: String(firstDefined(item.due_date, item.dueDate, "")).trim(),
      confirmationKind: String(firstDefined(item.confirmation_kind, item.kind, "")).trim().toLowerCase(),
      evidence: normalizeEvidenceIds(firstDefined(item.evidence_segment_ids, item.evidence, [])),
      reviewStatus: String(firstDefined(item.review_status, "suggested")) === "approved" ? "approved" : "suggested",
      userEdited: booleanValue(firstDefined(item.user_edited, item.userEdited), false),
      lifecycleStatus: ["active", "superseded", "resolved", "retracted"].includes(String(firstDefined(item.lifecycle_status, "active")))
        ? String(firstDefined(item.lifecycle_status, "active"))
        : "active",
      lifecycleReason: String(firstDefined(item.lifecycle_reason, "")).trim(),
      lifecycleUpdatedAt: firstDefined(item.lifecycle_updated_at, item.lifecycleUpdatedAt),
      updatedAt: firstDefined(item.updated_at, item.updatedAt),
    };
  }

  function setDecisionRadarFeedback(message = "") {
    elements.decisionRadarFeedback.textContent = message
      ? redactSensitiveText(i18n.localizeExternalText(message))
      : "";
    elements.decisionRadarFeedback.hidden = !message;
  }

  function setDecisionRadarError(message = "") {
    elements.decisionRadarError.textContent = message
      ? redactSensitiveText(i18n.localizeExternalText(message))
      : "";
    elements.decisionRadarError.hidden = !message;
  }

  const decisionRadarTabCategories = Object.freeze({
    core: ["decision", "action_item"],
    decision: ["decision"],
    action: ["action_item"],
    issues: ["open_question", "needs_confirmation"],
  });

  function decisionRadarTabsForCategory(category) {
    if (category === "decision") return ["core", "decision"];
    if (category === "action_item") return ["core", "action"];
    return ["issues"];
  }

  function trackDecisionRadarItems(nextItems) {
    const radar = state.decisionRadar;
    const nextIds = new Set(nextItems.filter((item) => item.lifecycleStatus === "active").map((item) => item.id));
    if (!radar.tabTrackingInitialized) {
      radar.knownItemIds = nextIds;
      radar.tabTrackingInitialized = true;
      return;
    }
    nextItems
      .filter((item) => item.lifecycleStatus === "active" && !radar.knownItemIds.has(item.id))
      .forEach((item) => {
        decisionRadarTabsForCategory(item.category).forEach((tab) => {
          if (tab !== radar.activeTab || !radar.pinnedToLatest) {
            radar.unreadByTab[tab] += 1;
          }
        });
      });
    radar.knownItemIds = nextIds;
  }

  function applyDecisionRadarSnapshot(payload, { preserveItems = false } = {}) {
    const root = normalizedTranslationRoot(payload);
    const radar = state.decisionRadar;
    const previousApplied = radar.applied;
    const provider = normalizeDecisionRadarProviderId(firstDefined(root.provider, root.selected_provider, previousApplied));
    if (["none", "openai", "gemini"].includes(provider)) {
      radar.applied = provider;
      if (radar.loading || radar.selected === previousApplied) radar.selected = provider;
    }
    radar.status = normalizeDecisionRadarStatus(firstDefined(root.status, root.state), radar.applied);
    radar.model = String(firstDefined(root.model, root.provider_model, radar.model, ""));
    radar.sessionId = String(firstDefined(root.session_id, root.sessionId, radar.sessionId, ""));
    radar.queueSize = Math.max(0, Number(firstDefined(root.queue_size, root.queueSize, radar.queueSize, 0)) || 0);
    radar.queueMaxSize = Math.max(0, Number(firstDefined(root.queue_max_size, root.queueMaxSize, radar.queueMaxSize, 0)) || 0);
    if (!preserveItems && Array.isArray(root.items)) {
      const nextItems = root.items.map(normalizeDecisionRadarItem).filter((item) => item.id && item.text && item.evidence.length);
      trackDecisionRadarItems(nextItems);
      radar.items = nextItems;
      if (radar.editingId && !radar.items.some((item) => item.id === radar.editingId)) radar.editingId = "";
    }
    renderDecisionRadar();
    publishDecisionRadarSnapshot();
  }

  function updateDecisionRadarControls() {
    const radar = state.decisionRadar;
    const provider = selectedDecisionRadarProvider();
    const busy = radar.loading || radar.saving || radar.mutating || radar.status === "running";
    const available = radar.selected === "none" || provider.available;
    elements.decisionRadarProviderSelect.disabled = busy;
    elements.decisionRadarApplyButton.disabled = busy || !available || radar.selected === radar.applied;
    elements.decisionRadarApplyButton.setAttribute("aria-busy", String(radar.saving));
    elements.decisionRadarScroll.querySelectorAll("button, textarea, input").forEach((control) => {
      control.disabled = radar.mutating;
    });
  }

  function renderDecisionRadarSettings() {
    const radar = state.decisionRadar;
    const provider = selectedDecisionRadarProvider();
    elements.decisionRadarProviderSelect.value = radar.selected;
    elements.decisionRadarStatusBadge.dataset.status = radar.status;
    elements.decisionRadarStatusBadge.textContent = decisionRadarStatusLabels[radar.status] || radar.status;
    elements.decisionRadarAvailability.textContent = provider.available ? t("사용 가능") : t("사용 불가");
    elements.decisionRadarModel.textContent = `model ${provider.model || radar.model || "—"}`;
    elements.decisionRadarApplyButton.textContent = radar.confirmingProvider === radar.selected
      ? t("외부 API 적용 확인")
      : t("Radar 설정 적용");
    elements.decisionRadarSecurityNotice.hidden = !["openai", "gemini"].includes(radar.selected);
    if (radar.selected === "none") {
      elements.decisionRadarProviderHint.textContent = t("final 자막은 분석하지 않으며 외부 API도 호출하지 않습니다.");
    } else if (!provider.available) {
      elements.decisionRadarProviderHint.textContent = provider.reason || t("선택한 Radar Provider를 사용할 수 없습니다.");
    } else {
      elements.decisionRadarProviderHint.textContent = t("final 자막만 묶어서 분석하고 모든 항목을 원문 근거에 연결합니다.");
    }
    elements.decisionRadarSession.textContent = radar.sessionId
      ? t("세션 {session}", { session: radar.sessionId })
      : t("세션 대기 중");
    elements.decisionRadarQueue.textContent = radar.queueMaxSize
      ? t("대기열 {size}/{max}", { size: radar.queueSize, max: radar.queueMaxSize })
      : t("대기열 {size}", { size: radar.queueSize });
    updateDecisionRadarControls();
  }

  function decisionRadarKindLabel(item) {
    if (item.category === "needs_confirmation") {
      return {
        person: t("사람 이름"),
        term: t("용어"),
        translation: t("번역"),
      }[item.confirmationKind] || t("확인 필요");
    }
    return {
      decision: t("결정"),
      action_item: "Action",
      open_question: t("질문"),
    }[item.category] || item.category;
  }

  function decisionRadarEditForm(item) {
    const form = document.createElement("form");
    form.className = "decision-radar-edit-form";
    form.dataset.radarEditForm = item.id;
    const textarea = document.createElement("textarea");
    textarea.name = "text";
    textarea.maxLength = 4_000;
    textarea.required = true;
    textarea.value = item.text;
    textarea.setAttribute("aria-label", t("항목 내용"));
    form.append(textarea);
    if (item.category === "action_item") {
      const fields = document.createElement("div");
      fields.className = "decision-radar-edit-fields";
      const assignee = document.createElement("input");
      assignee.name = "assignee";
      assignee.maxLength = 240;
      assignee.placeholder = t("담당자");
      assignee.value = item.assignee;
      const dueDate = document.createElement("input");
      dueDate.name = "due_date";
      dueDate.maxLength = 240;
      dueDate.placeholder = t("기한");
      dueDate.value = item.dueDate;
      fields.append(assignee, dueDate);
      form.append(fields);
    }
    const actions = document.createElement("div");
    actions.className = "decision-radar-edit-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button button-ghost button-small";
    cancel.dataset.radarAction = "cancel-edit";
    cancel.textContent = t("취소");
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "button button-primary button-small";
    save.textContent = t("저장");
    actions.append(cancel, save);
    form.append(actions);
    return form;
  }

  function decisionRadarItemCard(item, { historical = false } = {}) {
    const card = document.createElement("article");
    card.className = "decision-radar-item";
    card.dataset.radarItemId = item.id;
    card.dataset.reviewStatus = item.reviewStatus;
    const head = document.createElement("div");
    head.className = "decision-radar-item-head";
    const review = document.createElement("span");
    review.className = "decision-radar-review-label";
    review.textContent = item.reviewStatus === "approved" ? t("승인됨") : t("제안");
    const kind = document.createElement("span");
    kind.className = "decision-radar-kind";
    kind.textContent = decisionRadarKindLabel(item);
    head.append(review, kind);
    if (historical) {
      review.textContent = ({ superseded: "대체됨", resolved: "해결됨", retracted: "철회됨" }[item.lifecycleStatus] || "변경됨");
    }
    const copy = document.createElement("p");
    copy.className = "decision-radar-item-copy";
    copy.textContent = item.text;
    card.append(head, copy);
    const metaValues = [];
    if (item.assignee) metaValues.push(t("담당자 {value}", { value: item.assignee }));
    if (item.dueDate) metaValues.push(t("기한 {value}", { value: item.dueDate }));
    if (item.userEdited) metaValues.push(t("사용자 수정"));
    if (historical && item.lifecycleReason) metaValues.push(item.lifecycleReason);
    if (metaValues.length) {
      const meta = document.createElement("div");
      meta.className = "decision-radar-item-meta";
      metaValues.forEach((value) => {
        const span = document.createElement("span");
        span.textContent = value;
        meta.append(span);
      });
      card.append(meta);
    }
    const evidence = evidenceButtons(item.evidence);
    if (evidence) card.append(evidence);
    if (historical) return card;
    if (state.decisionRadar.editingId === item.id) {
      card.append(decisionRadarEditForm(item));
      return card;
    }
    const actions = document.createElement("div");
    actions.className = "decision-radar-item-actions";
    if (item.reviewStatus !== "approved") {
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "button button-ghost button-small";
      approve.dataset.radarAction = "approve";
      approve.textContent = t("승인");
      actions.append(approve);
    }
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "button button-ghost button-small";
    edit.dataset.radarAction = "edit";
    edit.textContent = t("수정");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button-ghost button-small";
    remove.dataset.radarAction = "delete";
    remove.textContent = t("삭제");
    actions.append(edit, remove);
    card.append(actions);
    return card;
  }

  function renderDecisionRadarItems() {
    const mappings = [
      ["decision", elements.decisionRadarDecisionsGroup, elements.decisionRadarDecisions, elements.decisionRadarDecisionsCount],
      ["action_item", elements.decisionRadarActionsGroup, elements.decisionRadarActions, elements.decisionRadarActionsCount],
      ["open_question", elements.decisionRadarQuestionsGroup, elements.decisionRadarQuestions, elements.decisionRadarQuestionsCount],
      ["needs_confirmation", elements.decisionRadarConfirmationsGroup, elements.decisionRadarConfirmations, elements.decisionRadarConfirmationsCount],
    ];
    const radar = state.decisionRadar;
    const visibleCategories = decisionRadarTabCategories[radar.activeTab] || decisionRadarTabCategories.core;
    const previousScrollTop = elements.decisionRadarScroll.scrollTop;
    let total = 0;
    mappings.forEach(([category, group, container, count]) => {
      const items = radar.items.filter((item) => item.lifecycleStatus === "active" && item.category === category);
      if (visibleCategories.includes(category)) total += items.length;
      count.textContent = String(items.length);
      group.hidden = !visibleCategories.includes(category) || items.length === 0;
      container.replaceChildren(...items.map(decisionRadarItemCard));
    });
    const historyItems = radar.items.filter((item) => item.lifecycleStatus !== "active");
    elements.decisionRadarHistoryDetails.hidden = historyItems.length === 0;
    elements.decisionRadarHistoryCount.textContent = String(historyItems.length);
    elements.decisionRadarHistory.replaceChildren(
      ...historyItems.slice().reverse().map((item) => decisionRadarItemCard(item, { historical: true })),
    );
    elements.decisionRadarEmpty.hidden = total > 0;
    renderDecisionRadarTabs();
    window.requestAnimationFrame(() => {
      if (radar.pinnedToLatest) {
        elements.decisionRadarScroll.scrollTo({ top: elements.decisionRadarScroll.scrollHeight, behavior: "smooth" });
      } else {
        elements.decisionRadarScroll.scrollTop = previousScrollTop;
      }
    });
    updateDecisionRadarControls();
  }

  function renderDecisionRadarTabs() {
    const radar = state.decisionRadar;
    const counts = {
      core: radar.items.filter((item) => item.lifecycleStatus === "active" && ["decision", "action_item"].includes(item.category)).length,
      decision: radar.items.filter((item) => item.lifecycleStatus === "active" && item.category === "decision").length,
      action: radar.items.filter((item) => item.lifecycleStatus === "active" && item.category === "action_item").length,
      issues: radar.items.filter((item) => item.lifecycleStatus === "active" && ["open_question", "needs_confirmation"].includes(item.category)).length,
    };
    elements.decisionRadarCoreTabCount.textContent = String(counts.core);
    elements.decisionRadarDecisionTabCount.textContent = String(counts.decision);
    elements.decisionRadarActionTabCount.textContent = String(counts.action);
    elements.decisionRadarIssuesTabCount.textContent = String(counts.issues);
    elements.decisionRadarTabs.querySelectorAll("[data-radar-tab]").forEach((button) => {
      const tab = button.dataset.radarTab;
      const selected = tab === radar.activeTab;
      button.setAttribute("aria-selected", String(selected));
      button.dataset.unread = String((radar.unreadByTab[tab] || 0) > 0);
      button.title = radar.unreadByTab[tab]
        ? t("새 항목 {count}개", { count: radar.unreadByTab[tab] })
        : "";
    });
    const activeUnread = radar.unreadByTab[radar.activeTab] || 0;
    elements.decisionRadarLatestCount.textContent = String(activeUnread);
    elements.decisionRadarLatestButton.hidden = activeUnread === 0;
  }

  function selectDecisionRadarTab(tab) {
    if (!decisionRadarTabCategories[tab]) return;
    const radar = state.decisionRadar;
    radar.activeTab = tab;
    radar.unreadByTab[tab] = 0;
    radar.pinnedToLatest = true;
    renderDecisionRadarItems();
  }

  function scrollDecisionRadarToLatest() {
    const radar = state.decisionRadar;
    radar.unreadByTab[radar.activeTab] = 0;
    radar.pinnedToLatest = true;
    renderDecisionRadarTabs();
    elements.decisionRadarScroll.scrollTo({ top: elements.decisionRadarScroll.scrollHeight, behavior: "smooth" });
  }

  function renderDecisionRadar() {
    renderDecisionRadarSettings();
    renderDecisionRadarItems();
  }

  function decisionRadarWindowSnapshot() {
    const radar = state.decisionRadar;
    return {
      type: "bootstrap_response",
      provider: radar.applied,
      status: radar.status,
      model: radar.model,
      session_id: radar.sessionId,
      queue_size: radar.queueSize,
      queue_max_size: radar.queueMaxSize,
      items: radar.items.map((item) => ({
        item_id: item.id,
        category: item.category,
        text: item.text,
        assignee: item.assignee,
        due_date: item.dueDate,
        confirmation_kind: item.confirmationKind,
        evidence_segment_ids: [...item.evidence],
        review_status: item.reviewStatus,
        user_edited: item.userEdited,
        lifecycle_status: item.lifecycleStatus,
        lifecycle_reason: item.lifecycleReason,
        lifecycle_updated_at: item.lifecycleUpdatedAt,
        updated_at: item.updatedAt,
      })),
    };
  }

  function publishDecisionRadarSnapshot(requestId = "") {
    decisionRadarChannel?.postMessage({
      ...decisionRadarWindowSnapshot(),
      request_id: requestId,
    });
  }

  async function loadDecisionRadarConfiguration() {
    const radar = state.decisionRadar;
    radar.loading = true;
    setDecisionRadarError();
    renderDecisionRadar();
    const [providersResult, settingsResult, stateResult] = await Promise.allSettled([
      apiRequest("/api/decision-radar/providers"),
      apiRequest("/api/decision-radar/settings"),
      apiRequest("/api/decision-radar"),
    ]);
    if (providersResult.status === "fulfilled") {
      installDecisionRadarProviders(providersResult.value);
    } else {
      installDecisionRadarProviders({ providers: [{ id: "none", available: true }] });
      setDecisionRadarError(t("Radar Provider 조회 실패: {message}", { message: extractMessage(providersResult.reason) }));
    }
    if (settingsResult.status === "fulfilled") {
      applyDecisionRadarSnapshot(settingsResult.value, { preserveItems: true });
    } else {
      const prefix = elements.decisionRadarError.hidden ? "" : `${elements.decisionRadarError.textContent} · `;
      setDecisionRadarError(`${prefix}${t("Radar 설정 조회 실패: {message}", { message: extractMessage(settingsResult.reason) })}`);
    }
    if (stateResult.status === "fulfilled") {
      applyDecisionRadarSnapshot(stateResult.value);
    }
    radar.loading = false;
    renderDecisionRadar();
  }

  async function loadDecisionRadarForSession(sessionId, { quiet = false } = {}) {
    const normalized = String(sessionId || "").trim();
    if (!normalized) return;
    try {
      const payload = await apiRequest(
        `/api/decision-radar?session_id=${encodeURIComponent(normalized)}`,
      );
      applyDecisionRadarSnapshot(payload);
      if (!quiet) setDecisionRadarFeedback(t("선택한 세션의 Radar 항목을 불러왔습니다."));
    } catch (error) {
      if (!quiet) {
        setDecisionRadarError(t("Radar 기록 조회 실패: {message}", { message: extractMessage(error) }));
      }
    }
  }

  async function saveDecisionRadarSettings() {
    const radar = state.decisionRadar;
    const provider = selectedDecisionRadarProvider();
    if (radar.selected !== "none" && !provider.available) {
      setDecisionRadarError(provider.reason || t("선택한 Radar Provider를 사용할 수 없습니다."));
      return;
    }
    if (["openai", "gemini"].includes(radar.selected) && radar.confirmingProvider !== radar.selected) {
      radar.confirmingProvider = radar.selected;
      setDecisionRadarError();
      setDecisionRadarFeedback(t("{provider} Decision Radar는 확정 원문과 Context Engine 용어를 외부 API로 전송하며 사용량에 따른 비용이 발생할 수 있습니다. 적용하려면 확인 버튼을 다시 누르세요.", {
        provider: providerLabels[radar.selected],
      }));
      renderDecisionRadarSettings();
      return;
    }
    radar.confirmingProvider = "";
    radar.saving = true;
    setDecisionRadarError();
    setDecisionRadarFeedback();
    renderDecisionRadarSettings();
    try {
      const payload = await apiRequest("/api/decision-radar/settings", {
        method: "POST",
        body: { provider: radar.selected },
        timeout: 20_000,
      });
      applyDecisionRadarSnapshot(payload, { preserveItems: true });
      setDecisionRadarFeedback(t("{provider} Decision Radar 설정을 적용했습니다.", {
        provider: providerLabels[state.decisionRadar.applied],
      }));
    } catch (error) {
      radar.selected = radar.applied;
      setDecisionRadarError(t("Radar 설정 적용 실패: {message}", { message: extractMessage(error) }));
    } finally {
      radar.saving = false;
      renderDecisionRadar();
    }
  }

  async function mutateDecisionRadarItem(itemId, body) {
    const radar = state.decisionRadar;
    radar.mutating = true;
    setDecisionRadarError();
    updateDecisionRadarControls();
    try {
      const payload = await apiRequest(`/api/decision-radar/items/${encodeURIComponent(itemId)}`, {
        method: "PATCH",
        body,
        timeout: 20_000,
      });
      radar.editingId = "";
      applyDecisionRadarSnapshot(asObject(payload).decision_radar || payload);
      setDecisionRadarFeedback(t("Radar 항목을 반영했습니다."));
    } catch (error) {
      setDecisionRadarError(t("Radar 항목 반영 실패: {message}", { message: extractMessage(error) }));
    } finally {
      radar.mutating = false;
      renderDecisionRadar();
    }
  }

  async function deleteDecisionRadarItem(itemId) {
    if (!window.confirm(t("이 Radar 항목을 삭제할까요? 같은 내용은 이 세션에서 다시 자동 제안되지 않습니다."))) return;
    const radar = state.decisionRadar;
    radar.mutating = true;
    setDecisionRadarError();
    updateDecisionRadarControls();
    try {
      const payload = await apiRequest(`/api/decision-radar/items/${encodeURIComponent(itemId)}`, {
        method: "DELETE",
        timeout: 20_000,
      });
      radar.editingId = "";
      applyDecisionRadarSnapshot(asObject(payload).decision_radar || payload);
      setDecisionRadarFeedback(t("Radar 항목을 삭제했습니다."));
    } catch (error) {
      setDecisionRadarError(t("Radar 항목 삭제 실패: {message}", { message: extractMessage(error) }));
    } finally {
      radar.mutating = false;
      renderDecisionRadar();
    }
  }

  async function navigateToDecisionRadarEvidence(segmentId) {
    if (!segmentId) return;
    const radarSessionId = state.decisionRadar.sessionId;
    let card = state.translation.cards.get(segmentId);
    if (!card?.isConnected || (radarSessionId && card.dataset.sessionId !== radarSessionId)) {
      if (["listening", "transcribing", "paused"].includes(state.captureState)) {
        return setDecisionRadarError(t("현재 화면에 남아 있지 않은 실시간 근거입니다. 세션 종료 후 기록에서 다시 확인할 수 있습니다."));
      }
      if (radarSessionId) {
        state.sessions.selectedId = radarSessionId;
        if ([...elements.sessionSelect.options].some((option) => option.value === radarSessionId)) {
          elements.sessionSelect.value = radarSessionId;
          await restoreSelectedSession();
        }
      }
      card = state.translation.cards.get(segmentId);
    }
    if (!card?.isConnected) {
      return setDecisionRadarError(t("근거 구간 {segment}을 현재 자막 목록에서 찾을 수 없습니다.", { segment: segmentId }));
    }
    setDecisionRadarError();
    card.tabIndex = -1;
    card.classList.remove("evidence-highlight");
    void card.offsetWidth;
    card.classList.add("evidence-highlight");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.focus({ preventScroll: true });
    window.setTimeout(() => card.classList.remove("evidence-highlight"), 1_600);
  }

  function handleDecisionRadarWebSocketEvent(payload) {
    const event = unwrapEvent(payload);
    const type = normalizedEventType(event);
    if (type === "decision_radar_updated") {
      applyDecisionRadarSnapshot(asObject(event.decision_radar));
      setDecisionRadarError();
      return;
    }
    if (type === "decision_radar_status") {
      state.decisionRadar.status = normalizeDecisionRadarStatus(event.status, event.provider);
      state.decisionRadar.queueSize = Math.max(0, Number(event.queue_size || 0));
      if (event.session_id) state.decisionRadar.sessionId = String(event.session_id);
      renderDecisionRadarSettings();
      return;
    }
    if (type === "decision_radar_error") {
      state.decisionRadar.status = "error";
      setDecisionRadarError(extractMessage(event, t("Decision Radar 분석에 실패했습니다. 자막과 번역은 계속 동작합니다.")));
      renderDecisionRadarSettings();
    }
  }

  function normalizeAnalysisProviderId(value) {
    const raw = String(value || "none").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["none", "off", "disabled"].includes(raw)) return "none";
    if (["rule", "rules", "rulebased", "rule_based", "local"].includes(raw)) return "rule_based";
    if (["openai", "openai_api", "api"].includes(raw)) return "openai";
    if (["gemini", "gemini_api", "google", "google_gemini"].includes(raw)) return "gemini";
    return raw;
  }

  function normalizeAnalysisStatus(value) {
    const raw = String(value || "").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["pending", "queued", "queue", "waiting"].includes(raw)) return "pending";
    if (["running", "processing", "analyzing", "in_progress", "generating"].includes(raw)) return "running";
    if (["completed", "complete", "success", "succeeded", "done", "ready"].includes(raw)) return "completed";
    if (["error", "failed", "failure", "timeout"].includes(raw)) return "error";
    if (["cancelled", "canceled"].includes(raw)) return "cancelled";
    return "idle";
  }

  function normalizeAnalysisProvider(rawProvider, fallbackId) {
    const raw = typeof rawProvider === "string" ? { name: rawProvider } : asObject(rawProvider);
    const id = normalizeAnalysisProviderId(firstDefined(raw.id, raw.provider, raw.name, fallbackId));
    return {
      id,
      name: i18n.localizeExternalText(String(firstDefined(raw.display_name, analysisProviderLabels[id], raw.name, id))),
      available: id === "none" || booleanValue(firstDefined(raw.available, raw.is_available, raw.ready), false),
      reason: redactSensitiveText(i18n.localizeExternalText(firstDefined(raw.reason, raw.unavailable_reason, ""))),
      model: String(firstDefined(raw.model, "")),
    };
  }

  function installAnalysisProviders(payload) {
    const root = normalizedTranslationRoot(payload);
    const rawProviders = firstDefined(root.providers, root.items, []);
    const providers = new Map();
    if (Array.isArray(rawProviders)) {
      rawProviders.forEach((provider) => {
        const normalized = normalizeAnalysisProvider(provider);
        providers.set(normalized.id, normalized);
      });
    } else {
      Object.entries(asObject(rawProviders)).forEach(([id, provider]) => {
        const normalized = normalizeAnalysisProvider(provider, id);
        providers.set(normalized.id, normalized);
      });
    }
    providers.set("none", normalizeAnalysisProvider({ name: "none", available: true }));
    ["rule_based", "openai", "gemini"].forEach((id) => {
      if (!providers.has(id)) providers.set(id, normalizeAnalysisProvider({ name: id, available: false }, id));
    });
    state.analysis.providers = providers;
    const selected = normalizeAnalysisProviderId(firstDefined(root.selected_provider, root.provider, state.analysis.selected));
    if (["none", "rule_based", "openai", "gemini"].includes(selected)) state.analysis.selected = selected;
  }

  function normalizeAnalysisSettings(payload, fallbackProvider = state.analysis.applied) {
    const root = normalizedTranslationRoot(payload);
    return {
      provider: normalizeAnalysisProviderId(firstDefined(root.provider, root.selected_provider, fallbackProvider)),
      model: String(firstDefined(root.model, root.analysis_model, "")),
      autoRunOnStop: booleanValue(firstDefined(root.auto_run_on_stop, root.autoRunOnStop), false),
      timeoutSeconds: Number(firstDefined(root.timeout_seconds, root.timeout, 0)) || 0,
      maxRetries: Number(firstDefined(root.max_retries, root.retries, 0)) || 0,
      maxSegmentsPerChunk: Number(firstDefined(root.max_segments_per_chunk, 0)) || 0,
      maxCharsPerChunk: Number(firstDefined(root.max_chars_per_chunk, 0)) || 0,
    };
  }

  function setAnalysisFeedback(message = "") {
    elements.analysisFeedback.textContent = message
      ? redactSensitiveText(i18n.localizeExternalText(message))
      : "";
    elements.analysisFeedback.hidden = !message;
  }

  function setAnalysisError(message = "") {
    elements.analysisError.textContent = message
      ? redactSensitiveText(i18n.localizeExternalText(message))
      : "";
    elements.analysisError.hidden = !message;
  }

  function setAnalysisStatus(status, customLabel = "") {
    const normalized = normalizeAnalysisStatus(status);
    state.analysis.status = normalized;
    elements.analysisStatusBadge.dataset.status = normalized;
    elements.analysisStatusBadge.textContent = customLabel || analysisStatusLabels[normalized];
    updateAnalysisControls();
  }

  function renderAnalysisSettings() {
    const analysis = state.analysis;
    const provider = selectedAnalysisProvider();
    elements.analysisProviderSelect.value = analysis.selected;
    elements.analysisAutoRunToggle.checked = analysis.settings.autoRunOnStop;
    elements.analysisProviderAvailability.textContent = provider.available ? t("사용 가능") : t("사용 불가");
    elements.analysisModelLabel.textContent = `model ${provider.model || analysis.settings.model || "—"}`;
    elements.analysisOpenAIWarning.hidden = analysis.selected !== "openai";
    elements.analysisGeminiWarning.hidden = analysis.selected !== "gemini";
    elements.analysisLocalNotice.hidden = analysis.selected !== "rule_based";

    if (analysis.selected === "none") {
      elements.analysisProviderHint.textContent = t("분석을 생성하지 않으며 외부 API를 호출하지 않습니다.");
    } else if (!provider.available) {
      elements.analysisProviderHint.textContent = i18n.localizeExternalText(provider.reason)
        || t("이 분석 Provider를 현재 사용할 수 없습니다.");
    } else if (["openai", "gemini"].includes(analysis.selected)) {
      elements.analysisProviderHint.textContent = t("명시적으로 생성하거나 자동 분석을 켠 경우에만 외부 API를 호출합니다.");
    } else {
      elements.analysisProviderHint.textContent = t("저장된 세션을 로컬 규칙으로 분석하고 근거 segment를 연결합니다.");
    }
    updateAnalysisControls();
  }

  function applyAnalysisSettingsPayload(payload, fallbackProvider) {
    const settings = normalizeAnalysisSettings(payload, fallbackProvider);
    state.analysis.applied = settings.provider;
    state.analysis.selected = settings.provider;
    state.analysis.settings = { ...settings };
    state.analysis.savedSettings = {
      provider: settings.provider,
      autoRunOnStop: settings.autoRunOnStop,
    };
    renderAnalysisSettings();
  }

  async function loadAnalysisConfiguration() {
    state.analysis.loading = true;
    setAnalysisError();
    updateAnalysisControls();
    const [providersResult, settingsResult] = await Promise.allSettled([
      apiRequest("/api/analysis/providers"),
      apiRequest("/api/analysis/settings"),
    ]);
    if (providersResult.status === "fulfilled") {
      installAnalysisProviders(providersResult.value);
    } else {
      installAnalysisProviders({ providers: [{ name: "none", available: true }] });
      setAnalysisError(t("분석 Provider 조회 실패: {message}", { message: extractMessage(providersResult.reason) }));
    }
    if (settingsResult.status === "fulfilled") {
      applyAnalysisSettingsPayload(settingsResult.value, state.analysis.selected);
    } else {
      applyAnalysisSettingsPayload({ provider: "none", auto_run_on_stop: false }, "none");
      const prefix = elements.analysisError.hidden ? "" : `${elements.analysisError.textContent} · `;
      setAnalysisError(`${prefix}${t("분석 설정 조회 실패: {message}", { message: extractMessage(settingsResult.reason) })}`);
    }
    state.analysis.loading = false;
    updateAnalysisControls();
  }

  async function saveAnalysisSettings() {
    const analysis = state.analysis;
    const provider = selectedAnalysisProvider();
    if (analysis.selected !== "none" && !provider.available) {
      setAnalysisError(i18n.localizeExternalText(provider.reason) || t("선택한 분석 Provider를 사용할 수 없습니다."));
      return;
    }
    if (
      ["openai", "gemini"].includes(analysis.selected) &&
      !window.confirm(
        analysis.settings.autoRunOnStop
          ? t("{provider} 자동 분석은 세션 종료마다 외부 전송과 비용을 발생시킬 수 있습니다. 이 설정을 적용할까요?", {
            provider: analysisProviderLabels[analysis.selected],
          })
          : t("{provider} 분석은 회의 내용을 외부 API로 전송하며 비용이 발생할 수 있습니다. 이 설정을 적용할까요?", {
            provider: analysisProviderLabels[analysis.selected],
          }),
      )
    ) return;

    analysis.saving = true;
    setAnalysisError();
    setAnalysisFeedback();
    updateAnalysisControls();
    try {
      const payload = await apiRequest("/api/analysis/settings", {
        method: "POST",
        body: { provider: analysis.selected, auto_run_on_stop: analysis.settings.autoRunOnStop },
        timeout: 20_000,
      });
      applyAnalysisSettingsPayload(payload, analysis.selected);
      setAnalysisFeedback(t("{provider} 분석 설정을 적용했습니다.", {
        provider: analysisProviderLabels[state.analysis.applied],
      }));
    } catch (error) {
      state.analysis.selected = state.analysis.savedSettings.provider;
      state.analysis.settings.autoRunOnStop = state.analysis.savedSettings.autoRunOnStop;
      renderAnalysisSettings();
      setAnalysisError(t("분석 설정 적용 실패: {message}", { message: extractMessage(error) }));
    } finally {
      analysis.saving = false;
      updateAnalysisControls();
    }
  }

  function normalizeEvidenceIds(value) {
    return [...new Set(asArray(value).map((item) => String(item || "").trim()).filter(Boolean))];
  }

  function normalizeAnalysisNarrative(value) {
    if (typeof value === "string") return { text: value.trim(), evidence: [] };
    const item = asObject(value);
    return {
      text: String(firstDefined(item.text, item.summary, item.content, "")).trim(),
      evidence: normalizeEvidenceIds(firstDefined(item.evidence_segment_ids, item.evidence, item.segment_ids, [])),
    };
  }

  function normalizeAnalysisNarrativeList(value) {
    return asArray(value).map(normalizeAnalysisNarrative).filter((item) => item.text);
  }

  function normalizeAnalysisResult(value) {
    const root = asObject(value);
    const actionItems = asArray(firstDefined(root.action_items, root.actions, [])).map((value) => {
      const item = asObject(value);
      return {
        task: String(firstDefined(item.task, item.text, item.action, "")).trim(),
        assignee: String(firstDefined(item.assignee, item.owner, t("미정"))).trim() || t("미정"),
        dueDate: String(firstDefined(item.due_date, item.due, item.deadline, t("미정"))).trim() || t("미정"),
        evidence: normalizeEvidenceIds(firstDefined(item.evidence_segment_ids, item.evidence, item.segment_ids, [])),
      };
    }).filter((item) => item.task);
    const warnings = asArray(firstDefined(root.warnings, root.analysis_warnings, [])).map((warning) => {
      if (typeof warning === "string") return warning.trim();
      const item = asObject(warning);
      return String(firstDefined(item.message, item.text, item.code, "")).trim();
    }).filter(Boolean);
    return {
      summary: normalizeAnalysisNarrative(firstDefined(root.summary, root.meeting_summary, "")),
      purpose: normalizeAnalysisNarrative(firstDefined(root.meeting_purpose, root.purpose, "")),
      discussions: normalizeAnalysisNarrativeList(firstDefined(root.key_discussions, root.discussions, [])),
      decisions: normalizeAnalysisNarrativeList(firstDefined(root.decisions, root.decision_items, [])),
      actionItems,
      openQuestions: normalizeAnalysisNarrativeList(firstDefined(root.open_questions, root.questions, [])),
      nextChecks: normalizeAnalysisNarrativeList(firstDefined(root.next_meeting_checks, root.next_checks, [])),
      warnings,
    };
  }

  function evidenceButtons(evidenceIds) {
    if (!evidenceIds.length) return null;
    const container = document.createElement("div");
    container.className = "analysis-evidence";
    evidenceIds.forEach((segmentId, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "evidence-button";
      button.dataset.evidenceSegmentId = segmentId;
      button.textContent = t("근거 {index} · {segment}", { index: index + 1, segment: segmentId });
      button.title = t("근거 자막 {segment}로 이동", { segment: segmentId });
      container.append(button);
    });
    return container;
  }

  function analysisPlaceholder(message = t("해당 항목이 없습니다.")) {
    const paragraph = document.createElement("p");
    paragraph.className = "analysis-placeholder";
    paragraph.textContent = message;
    return paragraph;
  }

  function analysisNarrativeItem(item) {
    const wrapper = document.createElement("div");
    wrapper.className = "analysis-item";
    const text = document.createElement("p");
    text.className = "analysis-item-copy";
    text.textContent = item.text;
    wrapper.append(text);
    const evidence = evidenceButtons(item.evidence);
    if (evidence) wrapper.append(evidence);
    return wrapper;
  }

  function renderNarrativeList(container, items) {
    container.replaceChildren();
    if (!items.length) return container.append(analysisPlaceholder());
    const list = document.createElement("ul");
    list.className = "analysis-list";
    items.forEach((item) => {
      const row = document.createElement("li");
      row.append(analysisNarrativeItem(item));
      list.append(row);
    });
    container.append(list);
  }

  function appendQuestionGroup(container, label, items) {
    const heading = document.createElement("h4");
    heading.className = "analysis-group-label";
    heading.textContent = label;
    container.append(heading);
    if (!items.length) return container.append(analysisPlaceholder());
    const list = document.createElement("ul");
    list.className = "analysis-list";
    items.forEach((item) => {
      const row = document.createElement("li");
      row.append(analysisNarrativeItem(item));
      list.append(row);
    });
    container.append(list);
  }

  function renderAnalysisResult(rawResult, metadata = {}) {
    if (!rawResult || typeof rawResult !== "object") {
      state.analysis.result = null;
      elements.analysisResults.hidden = true;
      elements.analysisEmptyState.hidden = false;
      return;
    }
    const result = normalizeAnalysisResult(rawResult);
    state.analysis.result = result;
    elements.analysisEmptyState.hidden = true;
    elements.analysisResults.hidden = false;
    const generated = parseDate(firstDefined(metadata.generated_at, metadata.completed_at));
    const generatedText = generated
      ? new Intl.DateTimeFormat(UI_LOCALE, { dateStyle: "medium", timeStyle: "medium" }).format(generated)
      : t("생성 시각 미확인");
    const provider = normalizeAnalysisProviderId(firstDefined(metadata.provider, state.analysis.applied));
    elements.analysisResultMeta.textContent = `${analysisProviderLabels[provider] || provider} · ${metadata.model || t("model 미확인")} · ${generatedText}`;

    elements.analysisSummary.replaceChildren();
    if (result.summary.text) elements.analysisSummary.append(analysisNarrativeItem(result.summary));
    const metrics = document.createElement("div");
    metrics.className = "analysis-summary-metrics";
    [
      t("논의 {count}", { count: result.discussions.length }),
      t("결정 {count}", { count: result.decisions.length }),
      `Action ${result.actionItems.length}`,
      t("질문 {count}", { count: result.openQuestions.length }),
      t("경고 {count}", { count: result.warnings.length }),
    ].forEach((label) => {
      const metric = document.createElement("span");
      metric.textContent = label;
      metrics.append(metric);
    });
    elements.analysisSummary.append(metrics);

    elements.analysisPurpose.replaceChildren();
    elements.analysisPurpose.append(result.purpose.text ? analysisNarrativeItem(result.purpose) : analysisPlaceholder());
    renderNarrativeList(elements.analysisDiscussions, result.discussions);
    renderNarrativeList(elements.analysisDecisions, result.decisions);
    elements.analysisActions.replaceChildren();
    if (!result.actionItems.length) {
      elements.analysisActions.append(analysisPlaceholder());
    } else {
      const list = document.createElement("ul");
      list.className = "analysis-action-list";
      result.actionItems.forEach((item) => {
        const row = document.createElement("li");
        row.className = "analysis-action-item";
        const task = document.createElement("p");
        task.className = "analysis-item-copy";
        task.textContent = item.task;
        const details = document.createElement("dl");
        details.className = "analysis-action-details";
        [[t("담당자"), item.assignee], [t("기한"), item.dueDate]].forEach(([term, value]) => {
          const group = document.createElement("div");
          const dt = document.createElement("dt");
          const dd = document.createElement("dd");
          dt.textContent = term;
          dd.textContent = value === "미정" ? t("미정") : value;
          group.append(dt, dd);
          details.append(group);
        });
        row.append(task, details);
        const evidence = evidenceButtons(item.evidence);
        if (evidence) row.append(evidence);
        list.append(row);
      });
      elements.analysisActions.append(list);
    }
    elements.analysisQuestions.replaceChildren();
    appendQuestionGroup(elements.analysisQuestions, t("미해결 질문"), result.openQuestions);
    appendQuestionGroup(elements.analysisQuestions, t("다음 회의 확인"), result.nextChecks);
    elements.analysisWarnings.replaceChildren();
    if (!result.warnings.length) {
      elements.analysisWarnings.append(analysisPlaceholder(t("분석 경고가 없습니다.")));
    } else {
      const list = document.createElement("ul");
      list.className = "analysis-warning-list";
      result.warnings.forEach((warning) => {
        const row = document.createElement("li");
        row.textContent = warning;
        list.append(row);
      });
      elements.analysisWarnings.append(list);
    }
  }

  function applyAnalysisPayload(payload, fallbackSessionId = "") {
    const root = normalizedTranslationRoot(payload);
    const sessionId = String(firstDefined(root.session_id, root.sessionId, fallbackSessionId, ""));
    if (sessionId) state.analysis.sessionId = sessionId;
    state.analysis.metadata = {
      provider: normalizeAnalysisProviderId(firstDefined(root.provider, state.analysis.applied)),
      model: String(firstDefined(root.model, "")),
      started_at: firstDefined(root.started_at, root.startedAt),
      generated_at: firstDefined(root.generated_at, root.completed_at, root.generatedAt),
      has_previous_result: booleanValue(root.has_previous_result, false),
    };
    const status = normalizeAnalysisStatus(firstDefined(root.status, root.analysis_status, root.state));
    setAnalysisStatus(status);
    const result = firstDefined(root.result, root.analysis_result, root.analysis);
    if (result && typeof result === "object") renderAnalysisResult(result, state.analysis.metadata);
    if (status === "error") {
      setAnalysisError(extractMessage(firstDefined(root.error, root.error_message), t("분석을 완료하지 못했습니다.")));
    }
    return status;
  }

  function stopAnalysisPolling() {
    if (state.analysis.pollTimer) window.clearTimeout(state.analysis.pollTimer);
    state.analysis.pollTimer = null;
    state.analysis.pollAttempts = 0;
  }

  function scheduleAnalysisPoll(sessionId) {
    if (!sessionId || !["pending", "running"].includes(state.analysis.status)) return;
    if (state.analysis.pollTimer) window.clearTimeout(state.analysis.pollTimer);
    state.analysis.pollTimer = window.setTimeout(async () => {
      state.analysis.pollTimer = null;
      state.analysis.pollAttempts += 1;
      if (state.analysis.pollAttempts > 120) {
        setAnalysisFeedback(t("분석은 계속될 수 있지만 자동 상태 확인을 중단했습니다. 세션을 다시 선택해 확인하세요."));
        return;
      }
      await loadAnalysisForSession(sessionId, { quiet: true, preserveResult: true });
      if (["pending", "running"].includes(state.analysis.status)) scheduleAnalysisPoll(sessionId);
    }, 1_500);
  }

  async function loadAnalysisForSession(sessionId, { quiet = false, preserveResult = false } = {}) {
    if (!sessionId) return;
    if (state.analysis.sessionId !== sessionId) {
      stopAnalysisPolling();
      state.analysis.sessionId = sessionId;
      state.analysis.status = "idle";
      state.analysis.result = null;
      elements.analysisResults.hidden = true;
      elements.analysisEmptyState.hidden = false;
    }
    state.analysis.loadingResult = true;
    if (!quiet) {
      setAnalysisError();
      setAnalysisFeedback(t("분석 상태를 확인하는 중입니다…"));
    }
    updateAnalysisControls();
    try {
      const payload = await apiRequest(`/api/sessions/${encodeURIComponent(sessionId)}/analysis`);
      const status = applyAnalysisPayload(payload, sessionId);
      if (!quiet) setAnalysisFeedback(status === "completed" ? t("저장된 분석을 불러왔습니다.") : "");
      if (["pending", "running"].includes(status)) scheduleAnalysisPoll(sessionId);
    } catch (error) {
      if (error.status === 404) {
        setAnalysisStatus("idle");
        if (!preserveResult) renderAnalysisResult(null);
        if (!quiet) setAnalysisFeedback();
      } else if (!quiet) {
        setAnalysisError(t("분석 상태 조회 실패: {message}", { message: extractMessage(error) }));
        setAnalysisFeedback();
      }
    } finally {
      state.analysis.loadingResult = false;
      updateAnalysisControls();
    }
  }

  function confirmAnalysisExternalCall(action) {
    if (state.analysis.applied !== "openai") return true;
    return window.confirm(
      t("{provider} 분석 {action}은 저장된 회의 내용을 외부 API로 전송하며 비용이 발생할 수 있습니다. 계속할까요?", {
        provider: analysisProviderLabels[state.analysis.applied],
        action: action === "retry" ? t("재시도") : t("생성"),
      }),
    );
  }

  async function runAnalysisAction(action) {
    const sessionId = state.sessions.selectedId || state.sessions.current?.sessionId || "";
    if (!sessionId) return setAnalysisError(t("분석할 저장 세션을 먼저 선택하세요."));
    if (["generate", "retry"].includes(action) && !confirmAnalysisExternalCall(action)) return;
    if (action === "generate" && state.analysis.result && !window.confirm(t("기존 분석 결과가 있습니다. 새 분석을 생성할까요?"))) return;
    state.analysis.actionInFlight = true;
    setAnalysisError();
    setAnalysisFeedback(action === "cancel"
      ? t("분석 취소를 요청하는 중입니다…")
      : t("분석 작업을 등록하는 중입니다…"));
    updateAnalysisControls();
    const suffix = action === "generate" ? "" : `/${action}`;
    try {
      const payload = await apiRequest(`/api/sessions/${encodeURIComponent(sessionId)}/analysis${suffix}`, {
        method: "POST",
        timeout: 20_000,
      });
      const status = applyAnalysisPayload(payload, sessionId);
      if (action === "cancel") {
        stopAnalysisPolling();
        setAnalysisStatus(status === "idle" ? "cancelled" : status);
        setAnalysisFeedback(t("분석 취소 요청을 처리했습니다."));
      } else {
        if (!["pending", "running"].includes(status)) setAnalysisStatus("pending");
        setAnalysisFeedback(t("분석이 대기열에 등록되었습니다."));
        state.analysis.pollAttempts = 0;
        scheduleAnalysisPoll(sessionId);
      }
    } catch (error) {
      const label = action === "cancel" ? t("취소") : action === "retry" ? t("재시도") : t("생성");
      setAnalysisError(t("분석 {action} 실패: {message}", { action: label, message: extractMessage(error) }));
      setAnalysisFeedback();
    } finally {
      state.analysis.actionInFlight = false;
      updateAnalysisControls();
    }
  }

  function handleAnalysisWebSocketEvent(payload) {
    const event = unwrapEvent(payload);
    const sessionId = String(firstDefined(event.session_id, event.sessionId, ""));
    const targetId = state.sessions.selectedId || state.analysis.sessionId;
    if (sessionId && targetId && sessionId !== targetId) return;
    const type = normalizedEventType(event);
    const status = type === "analysis_pending" ? "pending"
      : type === "analysis_completed" ? "completed"
        : type === "analysis_error" ? "error"
          : type === "analysis_cancelled" ? "cancelled"
            : normalizeAnalysisStatus(firstDefined(event.status, event.state));
    state.analysis.sessionId = sessionId || targetId || state.analysis.sessionId;
    setAnalysisStatus(status);
    if (status === "completed") {
      stopAnalysisPolling();
      setAnalysisFeedback(t("분석이 완료되었습니다. 결과를 불러오는 중입니다…"));
      loadAnalysisForSession(state.analysis.sessionId, { quiet: true, preserveResult: true });
    } else if (status === "error") {
      stopAnalysisPolling();
      setAnalysisError(extractMessage(
        firstDefined(event.error, event.error_message, event.message),
        t("분석 중 오류가 발생했습니다."),
      ));
    } else if (status === "cancelled") {
      stopAnalysisPolling();
      setAnalysisFeedback(t("분석이 취소되었습니다."));
    } else {
      scheduleAnalysisPoll(state.analysis.sessionId);
    }
  }

  async function navigateToEvidence(segmentId) {
    if (!segmentId) return;
    const analysisSessionId = state.analysis.sessionId || state.sessions.selectedId;
    let card = state.translation.cards.get(segmentId);
    if (!card?.isConnected || (analysisSessionId && card.dataset.sessionId !== analysisSessionId)) {
      if (["listening", "transcribing", "paused"].includes(state.captureState)) {
        return setAnalysisError(t("캡처 중에는 보관 세션의 근거로 이동할 수 없습니다. 캡처를 먼저 중지하세요."));
      }
      if (analysisSessionId) {
        state.sessions.selectedId = analysisSessionId;
        if ([...elements.sessionSelect.options].some((option) => option.value === analysisSessionId)) {
          elements.sessionSelect.value = analysisSessionId;
        }
        await restoreSelectedSession();
      }
      card = state.translation.cards.get(segmentId);
    }
    if (!card?.isConnected) {
      return setAnalysisError(t("근거 구간 {segment}을(를) 복원된 자막에서 찾지 못했습니다.", {
        segment: segmentId,
      }));
    }
    setAnalysisError();
    card.tabIndex = -1;
    card.classList.remove("evidence-highlight");
    void card.offsetWidth;
    card.classList.add("evidence-highlight");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.focus({ preventScroll: true });
    window.setTimeout(() => card.classList.remove("evidence-highlight"), 1_600);
  }

  function handleSessionWebSocketEvent(event, type) {
    const sessionId = String(firstDefined(event.session_id, event.sessionId, ""));
    if (!sessionId) return;
    const status = String(firstDefined(event.status, type === "session_finalized" ? "completed" : "running"));
    if (type === "session_created") {
      state.sessions.restoredId = "";
      state.sessions.current = normalizeSession({
        session_id: sessionId,
        status,
        started_at: event.timestamp,
        source: state.source,
        whisper_model: selectedSttModelLabel(),
        translation_provider: state.translation.applied,
      });
    } else if (state.sessions.current?.sessionId === sessionId) {
      state.sessions.current = {
        ...state.sessions.current,
        status,
        endedAt: ["completed", "recovered"].includes(status)
          ? firstDefined(event.timestamp, state.sessions.current.endedAt)
          : state.sessions.current.endedAt,
        segmentCount: Math.max(
          Number(state.sessions.current.segmentCount || 0),
          Number(event.segment_count || 0),
        ),
      };
    }
    renderCurrentSession();
    if (["session_finalized", "session_recovered"].includes(type)) {
      loadSessionList({ quiet: true });
    }
  }

  async function healthCheck({ quiet = false } = {}) {
    try {
      const payload = await apiRequest("/api/health", { timeout: 5_000 });
      const object = { ...asObject(payload), ...asObject(payload.data) };
      const healthy = !["error", "failed", "unhealthy"].includes(String(object.status || "ok").toLowerCase());
      if (!healthy) throw new Error(extractMessage(payload, t("서버 상태가 정상이 아닙니다.")));
      if (!["listening", "transcribing", "paused"].includes(state.captureState)) {
        setAppStatus(statusLabels[state.captureState], "success");
      }
      return true;
    } catch (error) {
      setAppStatus(t("서버 연결 안 됨"), "danger");
      if (!quiet) showError(t("서버 상태 확인 실패: {message}", { message: extractMessage(error) }));
      return false;
    }
  }

  async function syncCaptureState({ quiet = true } = {}) {
    try {
      const payload = await apiRequest("/api/capture/state", { timeout: 5_000 });
      applyCaptureState(payload);
    } catch (error) {
      if (!quiet && error.status !== 404) {
        showError(t("캡처 상태 조회 실패: {message}", { message: extractMessage(error) }));
      }
    }
  }

  function selectedDeviceRawId() {
    const selected = currentDevices().find((device) => device.id === elements.deviceSelect.value);
    return selected ? selected.rawId : elements.deviceSelect.value;
  }

  async function startCapture() {
    const deviceId = selectedDeviceRawId();
    if (deviceId === undefined || deviceId === null || deviceId === "") {
      showError(t("캡처할 오디오 장치를 먼저 선택하세요."));
      return;
    }

    dismissError();
    setRequestInFlight(true);
    setAppStatus(t("시작 중"), "warning");
    try {
      ensureWebSocket();
      const payload = await apiRequest("/api/capture/start", {
        method: "POST",
        body: {
          source: state.source,
          device_id: deviceId,
          model: elements.modelSelect.value,
          stt_provider: state.stt.provider,
          translation_direction: state.translationDirection,
        },
        timeout: 30_000,
      });
      applyCaptureState(Object.keys(asObject(payload)).length ? payload : { state: "listening" });
      if (["idle", "stopped"].includes(state.captureState)) {
        applyCaptureState({ state: "listening" });
      }
    } catch (error) {
      showError(t("캡처 시작 실패: {message}", { message: extractMessage(error) }));
      applyCaptureState({ state: "error" });
      await syncCaptureState({ quiet: true });
    } finally {
      setRequestInFlight(false);
    }
  }

  async function captureAction(action) {
    const pendingLabels = {
      pause: t("일시정지 중"),
      resume: t("재개 중"),
      stop: t("중지 중"),
    };
    const actionLabels = {
      pause: t("일시정지"),
      resume: t("재개"),
      stop: t("중지"),
    };
    dismissError();
    setRequestInFlight(true);
    setAppStatus(pendingLabels[action], "warning");
    try {
      const payload = await apiRequest(`/api/capture/${action}`, { method: "POST" });
      const fallbackStates = { pause: "paused", resume: "listening", stop: "stopped" };
      applyCaptureState(Object.keys(asObject(payload)).length ? payload : { state: fallbackStates[action] });
      const reported = firstDefined(payload?.state, payload?.status, payload?.data?.state);
      if (reported === undefined) applyCaptureState({ state: fallbackStates[action] });
      if (action === "stop") window.setTimeout(() => loadSessionList({ quiet: true }), 250);
    } catch (error) {
      showError(t("{action} 실패: {message}", {
        action: actionLabels[action],
        message: extractMessage(error),
      }));
      await syncCaptureState({ quiet: true });
    } finally {
      setRequestInFlight(false);
    }
  }

  function setContextFeedback(message = "") {
    elements.contextFeedback.textContent = i18n.localizeExternalText(String(message || ""));
    elements.contextFeedback.hidden = !message;
  }

  function setContextError(message = "") {
    elements.contextError.textContent = redactSensitiveText(extractMessage(message, ""));
    elements.contextError.hidden = !elements.contextError.textContent;
  }

  function applyContextPayload(payload) {
    const object = asObject(payload);
    state.context.activeProfileId = String(firstDefined(object.active_profile_id, "general"));
    state.context.profiles = asArray(object.profiles).map((profile) => ({
      ...asObject(profile),
      id: String(asObject(profile).id || ""),
      name: String(asObject(profile).name || t("프로필")),
      entries: asArray(asObject(profile).entries),
    })).filter((profile) => profile.id);
    state.context.suggestions = asArray(object.suggestions).map(asObject);
    state.context.keytermCount = Number(object.keyterm_count || 0);
    state.context.loading = false;
    renderContextEngine();
  }

  function activeContextProfile() {
    return state.context.profiles.find((profile) => profile.id === state.context.activeProfileId)
      || state.context.profiles[0]
      || null;
  }

  function contextCategoryLabel(category) {
    return category === "person" ? t("사람 이름") : t("일반 용어");
  }

  function contextProfileDisplayName(profile) {
    return profile.id === "general" ? t("일반") : profile.name;
  }

  function renderContextEngine() {
    const selectedBefore = elements.contextProfileSelect.value;
    elements.contextProfileSelect.replaceChildren();
    state.context.profiles.forEach((profile) => {
      const option = document.createElement("option");
      option.value = profile.id;
      const profileName = contextProfileDisplayName(profile);
      option.textContent = profile.id === state.context.activeProfileId
        ? t("{profile} · 사용 중", { profile: profileName })
        : profileName;
      elements.contextProfileSelect.append(option);
    });
    elements.contextProfileSelect.value = state.context.profiles.some((item) => item.id === selectedBefore)
      ? selectedBefore
      : state.context.activeProfileId;

    const profile = activeContextProfile();
    elements.contextEntryList.replaceChildren();
    if (!profile || !profile.entries.length) {
      const empty = document.createElement("li");
      empty.className = "context-empty-item";
      empty.textContent = t("이 프로필에 등록된 용어나 이름이 없습니다.");
      elements.contextEntryList.append(empty);
    } else {
      profile.entries.forEach((entry) => {
        const item = document.createElement("li");
        item.className = "context-entry-item";

        const copy = document.createElement("div");
        copy.className = "context-entry-copy";
        const title = document.createElement("strong");
        const badge = document.createElement("span");
        badge.className = "context-category-badge";
        badge.textContent = contextCategoryLabel(entry.category);
        title.append(badge, document.createTextNode(String(entry.canonical || "")));
        const variants = document.createElement("small");
        const aliases = asArray(entry.variants).map(String).filter(Boolean);
        variants.textContent = aliases.length
          ? t("오인식·별칭: {aliases}", { aliases: aliases.join(" · ") })
          : t("오인식·별칭 없음");
        copy.append(title, variants);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "context-entry-delete";
        remove.dataset.entryId = String(entry.id || "");
        remove.textContent = t("삭제");
        item.append(copy, remove);
        elements.contextEntryList.append(item);
      });
    }

    elements.contextSuggestionList.replaceChildren();
    if (!state.context.suggestions.length) {
      const empty = document.createElement("li");
      empty.className = "context-empty-item";
      empty.textContent = t("승인을 기다리는 추천 후보가 없습니다.");
      elements.contextSuggestionList.append(empty);
    } else {
      state.context.suggestions.forEach((suggestion) => {
        const item = document.createElement("li");
        item.className = "context-suggestion-item";
        item.dataset.suggestionId = String(suggestion.id || "");

        const main = document.createElement("div");
        main.className = "context-suggestion-main";
        const copy = document.createElement("div");
        copy.className = "context-suggestion-copy";
        const title = document.createElement("strong");
        const badge = document.createElement("span");
        badge.className = "context-category-badge";
        badge.textContent = contextCategoryLabel(suggestion.category);
        title.append(badge, document.createTextNode(String(suggestion.canonical || "")));
        const detail = document.createElement("small");
        detail.textContent = t("{reason} · {count}회", {
          reason: i18n.localizeExternalText(suggestion.reason) || t("회의에서 발견"),
          count: Number(suggestion.occurrences || 1),
        });
        copy.append(title, detail);
        main.append(copy);

        const actions = document.createElement("div");
        actions.className = "context-suggestion-actions";
        [
          ["accept", t("추가")],
          ["ignore", t("무시")],
        ].forEach(([decision, label]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.decision = decision;
          button.textContent = label;
          actions.append(button);
        });
        item.append(main, actions);
        elements.contextSuggestionList.append(item);
      });
    }

    const ready = !state.context.loading && Boolean(profile);
    elements.contextStatusBadge.dataset.status = ready ? "ready" : "loading";
    elements.contextStatusBadge.textContent = ready
      ? `${contextProfileDisplayName(profile)} · keyterm ${state.context.keytermCount}`
      : t("불러오는 중");
    elements.contextProfileHint.textContent = state.captureState === "listening"
      ? t("정규화는 즉시 적용됩니다. Deepgram keyterm 변경은 다음 캡처 시작부터 적용됩니다.")
      : t("사람 이름과 용어는 다음 Deepgram 연결의 keyterm과 번역 glossary에 적용됩니다.");
    updateContextControls();
  }

  function updateContextControls() {
    const disabled = state.context.loading || state.context.busy;
    const selected = elements.contextProfileSelect.value;
    elements.contextProfileSelect.disabled = disabled || !state.context.profiles.length;
    elements.activateContextProfileButton.disabled = disabled
      || !selected
      || selected === state.context.activeProfileId;
    elements.createContextProfileButton.disabled = disabled;
    elements.contextProfileNameInput.disabled = disabled;
    elements.contextEntryCategory.disabled = disabled;
    elements.contextCanonicalInput.disabled = disabled;
    elements.contextVariantsInput.disabled = disabled;
    elements.addContextEntryButton.disabled = disabled || !activeContextProfile();
    elements.generateContextSuggestionsButton.disabled = disabled;
  }

  async function loadContextEngine({ quiet = false } = {}) {
    if (!quiet) state.context.loading = true;
    updateContextControls();
    try {
      applyContextPayload(await apiRequest("/api/context"));
      if (!quiet) setContextError();
    } catch (error) {
      state.context.loading = false;
      updateContextControls();
      if (!quiet) setContextError(error);
    }
  }

  async function runContextMutation(path, options, successMessage) {
    state.context.busy = true;
    setContextError();
    setContextFeedback();
    updateContextControls();
    try {
      const payload = await apiRequest(path, options);
      applyContextPayload(payload);
      setContextFeedback(successMessage);
      return true;
    } catch (error) {
      setContextError(error);
      return false;
    } finally {
      state.context.busy = false;
      updateContextControls();
    }
  }

  async function activateContextProfile() {
    const profileId = elements.contextProfileSelect.value;
    if (!profileId || profileId === state.context.activeProfileId) return;
    await runContextMutation(
      `/api/context/profiles/${encodeURIComponent(profileId)}/activate`,
      { method: "POST" },
      state.captureState === "listening"
        ? t("프로필을 적용했습니다. Deepgram keyterm은 다음 캡처부터 적용됩니다.")
        : t("프로필을 적용했습니다."),
    );
  }

  async function createContextProfile() {
    const name = elements.contextProfileNameInput.value.trim();
    if (!name) {
      setContextError(t("새 프로필 이름을 입력하세요."));
      return;
    }
    const saved = await runContextMutation(
      "/api/context/profiles",
      { method: "POST", body: { name, description: "" } },
      t("새 프로필을 만들고 활성화했습니다."),
    );
    if (saved) elements.contextProfileNameInput.value = "";
  }

  function parseContextVariants() {
    return [...new Set(elements.contextVariantsInput.value
      .split(/[\n,]/)
      .map((value) => value.trim())
      .filter(Boolean))].slice(0, 20);
  }

  async function addContextEntry(event) {
    event.preventDefault();
    const profile = activeContextProfile();
    const canonical = elements.contextCanonicalInput.value.trim();
    if (!profile || !canonical) {
      setContextError(t("정확한 표기를 입력하세요."));
      return;
    }
    const saved = await runContextMutation(
      `/api/context/profiles/${encodeURIComponent(profile.id)}/entries`,
      {
        method: "POST",
        body: {
          category: elements.contextEntryCategory.value === "person" ? "person" : "term",
          canonical,
          variants: parseContextVariants(),
        },
      },
      t("용어를 등록했습니다. 자동으로 학습하지 않고 이 프로필에서만 사용합니다."),
    );
    if (saved) {
      elements.contextCanonicalInput.value = "";
      elements.contextVariantsInput.value = "";
    }
  }

  async function deleteContextEntry(entryId) {
    const profile = activeContextProfile();
    if (!profile || !entryId) return;
    await runContextMutation(
      `/api/context/profiles/${encodeURIComponent(profile.id)}/entries/${encodeURIComponent(entryId)}`,
      { method: "DELETE" },
      t("등록 항목을 삭제했습니다."),
    );
  }

  function contextSuggestionSessionId() {
    return String(
      state.sessions.selectedId
      || state.sessions.current?.sessionId
      || state.sessions.restoredId
      || state.analysis.sessionId
      || "",
    );
  }

  async function generateContextSuggestions() {
    const sessionId = contextSuggestionSessionId();
    if (!sessionId) {
      setContextError(t("먼저 완료된 세션을 선택하세요."));
      return;
    }
    const before = state.context.suggestions.length;
    const saved = await runContextMutation(
      "/api/context/suggestions/generate",
      { method: "POST", body: { session_id: sessionId } },
      t("회의에서 발견한 후보를 만들었습니다. 추가할 항목만 승인하세요."),
    );
    if (saved && state.context.suggestions.length === before) {
      setContextFeedback(t("새로 추천할 고유 용어나 이름을 찾지 못했습니다."));
    }
  }

  async function decideContextSuggestion(suggestionId, decision) {
    if (!suggestionId) return;
    await runContextMutation(
      `/api/context/suggestions/${encodeURIComponent(suggestionId)}/decision`,
      { method: "POST", body: { accept: decision === "accept", variants: [] } },
      decision === "accept"
        ? t("추천 항목을 현재 프로필에 추가했습니다.")
        : t("추천 항목을 무시했습니다."),
    );
  }

  function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/live`;
  }

  function scheduleReconnect() {
    if (state.intentionalClose || state.reconnectTimer) return;
    const baseDelay = Math.min(RECONNECT_MAX_MS, 750 * (2 ** state.reconnectAttempt));
    const delay = Math.round(baseDelay + Math.random() * Math.min(500, baseDelay * 0.2));
    state.reconnectAttempt = Math.min(state.reconnectAttempt + 1, 8);
    setWebSocketStatus(t("{seconds}초 후 재연결", {
      seconds: Math.max(1, Math.ceil(delay / 1000)),
    }), "warning");
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      connectWebSocket();
    }, delay);
  }

  function connectWebSocket() {
    if (state.intentionalClose) return;
    if (state.ws && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.ws.readyState)) return;

    setWebSocketStatus(t("연결 중"), "warning");
    let socket;
    try {
      socket = new WebSocket(websocketUrl());
    } catch (_error) {
      setWebSocketStatus(t("연결 실패"), "danger");
      scheduleReconnect();
      return;
    }
    state.ws = socket;

    socket.addEventListener("open", () => {
      if (state.ws !== socket) return;
      state.reconnectAttempt = 0;
      setWebSocketStatus(t("연결됨"), "success");
      syncCaptureState({ quiet: true });
    });

    socket.addEventListener("message", (message) => {
      try {
        const payload = JSON.parse(message.data);
        asArray(payload).forEach(handleWebSocketEvent);
      } catch (_error) {
        showError(t("WebSocket에서 해석할 수 없는 메시지를 받았습니다."));
      }
    });

    socket.addEventListener("error", () => {
      if (state.ws === socket) setWebSocketStatus(t("연결 오류"), "danger");
    });

    socket.addEventListener("close", () => {
      if (state.ws !== socket) return;
      state.ws = null;
      if (!state.intentionalClose) {
        setWebSocketStatus(t("연결 끊김"), "danger");
        scheduleReconnect();
      }
    });
  }

  function ensureWebSocket() {
    if (!state.ws || ![WebSocket.CONNECTING, WebSocket.OPEN].includes(state.ws.readyState)) {
      connectWebSocket();
    }
  }

  function unwrapEvent(payload) {
    const original = asObject(payload);
    const nestedPayload = asObject(original.payload);
    const nestedData = asObject(original.data);
    const merged = { ...nestedData, ...nestedPayload, ...original };
    merged.type = firstDefined(original.type, original.event, original.kind, original.name, nestedPayload.type, nestedData.type);
    return merged;
  }

  function normalizedEventType(event) {
    return String(event.type || "").trim().toLowerCase().replace(/[\s.:-]+/g, "_");
  }

  function handleSnapshot(event) {
    const snapshot = asObject(firstDefined(event.snapshot, event.data, event.payload, event));
    const capture = asObject(snapshot.capture);
    const contextSnapshot = asObject(snapshot.context);
    if (asArray(contextSnapshot.profiles).length) applyContextPayload(contextSnapshot);
    const snapshotState = firstDefined(
      capture.capture_state,
      capture.state,
      capture.status,
      snapshot.capture_state,
      snapshot.state,
      snapshot.status,
    );
    if (snapshotState !== undefined) {
      if (typeof snapshotState === "object") applyCaptureState(snapshotState);
      else applyCaptureState({ ...snapshot, ...capture, state: snapshotState });
    }

    const finals = firstDefined(
      snapshot.final_transcripts,
      snapshot.final_segments,
      snapshot.segments,
      snapshot.finals,
      snapshot.transcripts,
    );
    asArray(finals).filter(Boolean).forEach(renderFinalTranscript);

    const partial = firstDefined(snapshot.partial_transcript, snapshot.partial, snapshot.current_partial);
    if (partial) renderPartialTranscript(typeof partial === "string" ? { text: partial } : partial);

    const level = firstDefined(snapshot.audio_level, snapshot.level);
    if (level !== undefined) {
      setAudioLevel(normalizeLevel(typeof level === "object" ? level : { level }));
    }

    const translationSnapshot = asObject(snapshot.translation);
    const translationProviders = firstDefined(
      snapshot.translation_providers,
      translationSnapshot.providers,
    );
    if (translationProviders) {
      installTranslationProviders({
        providers: translationProviders,
        selected_provider: firstDefined(
          translationSnapshot.provider,
          snapshot.translation_provider,
          state.translation.selected,
        ),
      });
    }

    const translationSettings = firstDefined(
      snapshot.translation_settings,
      translationSnapshot.settings,
      translationSnapshot.provider ? translationSnapshot : undefined,
    );
    if (translationSettings) applyTranslationSettingsPayload(translationSettings, state.translation.applied);

    const translationEvents = firstDefined(
      snapshot.translation_events,
      snapshot.translations,
      snapshot.translation_results,
      translationSnapshot.events,
      translationSnapshot.results,
    );
    asArray(translationEvents).filter(Boolean).forEach(handleTranslationWebSocketEvent);

    const decisionRadarSnapshot = asObject(snapshot.decision_radar);
    if (Object.keys(decisionRadarSnapshot).length) {
      applyDecisionRadarSnapshot(decisionRadarSnapshot);
    }
    const liveShareSnapshot = asObject(snapshot.live_share);
    if (Object.keys(liveShareSnapshot).length) applyLiveSharePayload(liveShareSnapshot);
  }

  function handleWebSocketEvent(payload) {
    const event = unwrapEvent(payload);
    const type = normalizedEventType(event);

    if (type === "snapshot" || type === "initial_state" || type === "sync") {
      handleSnapshot(event);
      return;
    }

    if (type === "context_updated") {
      loadContextEngine({ quiet: true });
      return;
    }

    if (type === "live_share_status") {
      applyLiveSharePayload(event);
      return;
    }

    if (
      type === "translation" ||
      type === "translation_pending" ||
      type === "translation_status" ||
      type === "translation_error" ||
      type === "translation_success" ||
      type === "translation_completed"
    ) {
      handleTranslationWebSocketEvent(event);
      return;
    }

    if (["session_created", "session_status", "session_finalized", "session_recovered"].includes(type)) {
      handleSessionWebSocketEvent(event, type);
      return;
    }

    if (["analysis_pending", "analysis_status", "analysis_completed", "analysis_error", "analysis_cancelled"].includes(type)) {
      handleAnalysisWebSocketEvent(event);
      return;
    }

    if (type.startsWith("decision_radar_")) {
      handleDecisionRadarWebSocketEvent(event);
      return;
    }

    if (type.includes("error") || (event.recoverable !== undefined && event.message && !event.text)) {
      showError(extractMessage(event, t("백엔드에서 오류가 발생했습니다.")));
      if (event.status || event.recoverable === false) {
        applyCaptureState({ ...event, state: event.status || "error" });
      }
      return;
    }

    if (type.includes("audio_level") || type === "level" || type === "volume" || type === "meter") {
      setAudioLevel(normalizeLevel(event));
      return;
    }

    if (type === "partial_clear" || type === "clear_partial") {
      const clearId = String(firstDefined(event.utterance_id, event.utteranceId, ""));
      const currentId = elements.partialPanel.dataset.utteranceId || "";
      if (!clearId || !currentId || clearId === currentId) clearPartial();
      return;
    }

    if (type.includes("partial") || event.is_final === false || event.final === false) {
      renderPartialTranscript(event);
      if (event.status) applyCaptureState({ state: event.status, display_state: event.status });
      return;
    }

    if (type.includes("final") || event.is_final === true || event.final === true) {
      renderFinalTranscript(event);
      if (event.status) applyCaptureState({ state: event.status, display_state: event.status });
      return;
    }

    if (["state", "status", "capture_state", "state_changed", "capture_status"].includes(type)) {
      applyCaptureState(event);
      return;
    }

    if (type.includes("device") && (event.devices || event.loopbacks || event.microphones)) {
      const normalized = normalizeDevicePayload(event);
      state.devices = {
        outputs: normalized.outputs,
        loopbacks: normalized.loopbacks,
        microphones: normalized.microphones,
      };
      renderDevices();
      renderDeviceWarnings(normalized.warnings);
      return;
    }

    if (event.status || event.capture_state) applyCaptureState(event);
  }

  function normalizeLevel(event) {
    let value = Number(firstDefined(event.level, event.audio_level, event.rms, event.peak, event.value, 0));
    const dbfs = Number(firstDefined(event.dbfs, event.db, event.decibels));

    if ((!Number.isFinite(value) || value === 0) && Number.isFinite(dbfs)) {
      value = 10 ** (Math.max(-60, Math.min(0, dbfs)) / 20);
    } else if (Number.isFinite(value) && value < 0) {
      value = 10 ** (Math.max(-60, Math.min(0, value)) / 20);
    } else if (value > 1) {
      value /= 100;
    }
    return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  }

  function setAudioLevel(level, immediate = false) {
    const normalized = Math.max(0, Math.min(1, Number(level) || 0));
    state.lastLevelAt = normalized > 0 ? performance.now() : 0;
    state.renderedLevel = immediate ? normalized : Math.max(normalized, state.renderedLevel * 0.58);
    state.peakLevel = immediate && normalized === 0
      ? 0
      : Math.max(state.peakLevel * 0.92, state.renderedLevel);
    renderAudioLevel();
  }

  function renderAudioLevel() {
    const percent = Math.round(state.renderedLevel * 100);
    const peakPercent = Math.round(state.peakLevel * 100);
    elements.levelFill.style.width = `${percent}%`;
    elements.levelPeak.style.left = `calc(${peakPercent}% - 1px)`;
    elements.levelPeak.style.opacity = peakPercent > 1 ? "1" : "0";
    elements.levelValue.value = `${percent}%`;
    elements.levelValue.textContent = `${percent}%`;
    elements.audioLevel.setAttribute("aria-valuenow", String(percent));
  }

  function levelDecayLoop(now) {
    if (state.lastLevelAt && now - state.lastLevelAt > 250 && state.renderedLevel > 0.001) {
      state.renderedLevel *= 0.9;
      state.peakLevel *= 0.94;
      if (state.renderedLevel < 0.001) state.renderedLevel = 0;
      renderAudioLevel();
    }
    window.requestAnimationFrame(levelDecayLoop);
  }

  function transcriptText(event) {
    const result = asObject(event.result);
    const transcript = event.transcript;
    if (typeof transcript === "string") return transcript.trim();
    return String(firstDefined(event.text, event.content, result.text, asObject(transcript).text, "")).trim();
  }

  function eventLanguage(event) {
    const result = asObject(event.result);
    return normalizeLanguage(firstDefined(event.language, event.detected_language, event.lang, result.language));
  }

  function languageDescription(language, probability) {
    const numericProbability = Number(probability);
    if (!Number.isFinite(numericProbability)) return languageLabels[language];
    const normalized = numericProbability > 1 ? numericProbability : numericProbability * 100;
    return `${languageLabels[language]} · ${Math.round(normalized)}%`;
  }

  function renderPartialTranscript(payload) {
    const event = unwrapEvent(payload);
    const text = transcriptText(event);
    if (!text) {
      clearPartial();
      return;
    }
    const language = eventLanguage(event);
    const probability = firstDefined(event.language_probability, event.languageProbability, event.probability, event.confidence);
    elements.partialText.textContent = text;
    elements.partialLanguage.textContent = languageDescription(language, probability);
    elements.partialPanel.dataset.active = "true";
    elements.partialPanel.dataset.utteranceId = String(firstDefined(event.utterance_id, event.utteranceId, ""));
  }

  function clearPartial() {
    elements.partialText.textContent = DEFAULT_PARTIAL_TEXT;
    elements.partialLanguage.textContent = "—";
    elements.partialPanel.dataset.active = "false";
    elements.partialPanel.dataset.utteranceId = "";
  }

  function parseDate(value) {
    if (!value) return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatTimestamp(startValue, endValue) {
    const start = parseDate(startValue);
    const end = parseDate(endValue);
    const formatter = new Intl.DateTimeFormat(UI_LOCALE, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    if (!start && !end) return { display: t("시간 미확인"), dateTime: "" };
    const first = start || end;
    const last = end || start;
    const firstText = formatter.format(first);
    const lastText = formatter.format(last);
    return {
      display: firstText === lastText ? firstText : `${firstText}–${lastText}`,
      dateTime: first.toISOString(),
    };
  }

  function finalEventKey(event, text) {
    const explicitId = firstDefined(event.segment_id, event.segmentId, event.id, event.utterance_id, event.utteranceId);
    if (explicitId !== undefined && explicitId !== null && explicitId !== "") return `id:${explicitId}`;
    const normalizedText = text.toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
    const time = String(firstDefined(event.ended_at, event.end_time, event.timestamp, event.created_at, ""));
    return time ? `fallback:${normalizedText}|${time}` : `ephemeral:${normalizedText}`;
  }

  function rememberFinal(key) {
    state.seenFinals.add(key);
    if (state.seenFinals.size > MAX_TRANSCRIPTS * 2) {
      const first = state.seenFinals.values().next().value;
      state.seenFinals.delete(first);
    }
  }

  function translationSegmentId(payload) {
    const event = unwrapEvent(payload);
    const translation = asObject(event.translation);
    const result = asObject(event.result);
    const value = firstDefined(
      event.segment_id,
      event.segmentId,
      event.transcript_segment_id,
      translation.segment_id,
      result.segment_id,
    );
    return value === undefined || value === null || value === "" ? "" : String(value);
  }

  function translatedText(payload) {
    const event = unwrapEvent(payload);
    const translation = event.translation;
    const result = asObject(event.result);
    if (typeof translation === "string") return translation.trim();
    return String(firstDefined(
      event.translated_text,
      event.target_text,
      event.korean_text,
      asObject(translation).translated_text,
      asObject(translation).text,
      result.translated_text,
      result.translation,
      result.text,
      event.text,
      "",
    )).trim();
  }

  function translationEventStatus(payload) {
    const event = unwrapEvent(payload);
    const type = normalizedEventType(event);
    if (type === "translation_pending") return "pending";
    if (type === "translation_error") return "error";
    if (type === "translation" || type === "translation_success" || type === "translation_completed") {
      return translatedText(event) ? "success" : "error";
    }
    return normalizeTranslationStatus(firstDefined(
      event.translation_status,
      event.status,
      event.state,
      event.phase,
      "pending",
    ), firstDefined(event.provider, state.translation.applied));
  }

  function translationEventTime(payload) {
    const event = unwrapEvent(payload);
    const raw = firstDefined(
      event.updated_at,
      event.completed_at,
      event.timestamp,
      event.created_at,
      event.queued_at,
    );
    const parsed = raw ? Date.parse(raw) : Number.NaN;
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function translationStatusRank(status) {
    return { disabled: 0, pending: 1, translating: 2, error: 3, success: 4 }[status] ?? 0;
  }

  function shouldReplaceDeferred(previous, next) {
    if (!previous) return true;
    const previousTime = translationEventTime(previous);
    const nextTime = translationEventTime(next);
    if (previousTime && nextTime) return nextTime >= previousTime;
    if (nextTime && !previousTime) return true;
    if (previousTime && !nextTime) return false;
    return translationStatusRank(translationEventStatus(next)) >= translationStatusRank(translationEventStatus(previous));
  }

  function bufferTranslationEvent(segmentId, event) {
    const previous = state.translation.deferredEvents.get(segmentId);
    if (shouldReplaceDeferred(previous, event)) state.translation.deferredEvents.set(segmentId, event);
    while (state.translation.deferredEvents.size > 250) {
      state.translation.deferredEvents.delete(state.translation.deferredEvents.keys().next().value);
    }
  }

  function reportTranslationPocDisplay(kind, card, text = "") {
    if (new URLSearchParams(window.location.search).get("translation_poc") !== "1") return;
    const segmentId = String(card?.dataset?.segmentId || "");
    if (!segmentId || !["final", "translation"].includes(kind)) return;
    fetch("/api/poc/browser-display", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        segment_id: segmentId,
        browser_epoch_ms: Date.now(),
        text: String(text || "").slice(0, 4_000),
      }),
    }).catch(() => {});
  }

  function updateTranslationCard(card, payload, options = {}) {
    if (!card) return false;
    const event = unwrapEvent(payload);
    const panel = card.querySelector(".segment-translation");
    const badge = card.querySelector(".segment-translation-status");
    const textElement = card.querySelector(".segment-translation-text");
    const errorElement = card.querySelector(".segment-translation-error");
    const retryButton = card.querySelector(".segment-retry-button");
    const metrics = card.querySelector(".segment-translation-metrics");
    const providerElement = card.querySelector(".segment-provider");
    const latencyElement = card.querySelector(".segment-latency");
    if (!panel || !badge || !textElement) return false;

    let status = options.status || translationEventStatus(event);
    status = normalizeTranslationStatus(status, firstDefined(event.provider, state.translation.applied));
    const currentStatus = panel.dataset.status || "disabled";
    const previousTranslation = panel.dataset.lastTranslation
      || (currentStatus === "success" ? textElement.textContent.trim() : "");
    const eventTime = options.eventTime ?? translationEventTime(event);
    const previousTime = Number(panel.dataset.translationEventTime || 0);

    if (!options.force) {
      if (eventTime && previousTime && eventTime < previousTime) return false;
      if (!eventTime && currentStatus === "success" && status !== "success") return false;
      if (!eventTime && translationStatusRank(status) < translationStatusRank(currentStatus)) return false;
    }

    const translation = translatedText(event);
    if (status === "success" && !translation) status = "error";
    const provider = normalizeProviderId(firstDefined(
      event.provider,
      event.translation_provider,
      event.method,
      asObject(event.result).provider,
      state.translation.applied,
    ));
    const latency = translationLatencyValue(event);
    const errorMessage = redactSensitiveText(extractMessage(
      firstDefined(event.error_message, event.error, event.message, event.detail),
      status === "error" ? t("번역 결과를 받지 못했습니다.") : "",
    ));

    panel.dataset.status = status;
    panel.setAttribute("aria-busy", String(["pending", "translating"].includes(status)));
    badge.dataset.status = status;
    badge.textContent = translationStatusLabels[status];
    if (eventTime) panel.dataset.translationEventTime = String(eventTime);

    if (status === "disabled") {
      textElement.textContent = card.dataset.segmentId
        ? t("번역을 사용하지 않습니다.")
        : t("segment_id가 없어 이 원문에 번역 결과를 안전하게 연결할 수 없습니다.");
    } else if (status === "pending") {
      textElement.textContent = previousTranslation || t("번역 대기열에 등록되었습니다…");
    } else if (status === "translating") {
      textElement.textContent = previousTranslation
        || t("{language}로 번역하고 있습니다…", {
          language: directionTargetLanguageLabel(),
        });
    } else if (status === "success") {
      textElement.textContent = translation;
      panel.dataset.lastTranslation = translation;
      reportTranslationPocDisplay("translation", card, translation);
    } else {
      textElement.textContent = previousTranslation
        || t("원문은 보존되었습니다. 번역만 완료하지 못했습니다.");
    }

    errorElement.textContent = status === "error" ? errorMessage : "";
    errorElement.hidden = status !== "error";
    const activeProvider = state.translation.applied;
    const providerAvailable = activeProvider !== "none" && state.translation.providers.get(activeProvider)?.available === true;
    retryButton.hidden = !["error", "success"].includes(status)
      || !card.dataset.segmentId
      || !providerAvailable;
    retryButton.disabled = false;
    retryButton.removeAttribute("aria-busy");

    providerElement.textContent = provider !== "none" ? providerLabels[provider] || provider : "";
    latencyElement.textContent = formatTranslationLatency(latency);
    metrics.hidden = !providerElement.textContent && !latencyElement.textContent;

    if (status === "success" && card.dataset.sessionId && card.dataset.segmentId) {
      registerTranslatedSegment(card.dataset.sessionId, card.dataset.segmentId);
    }

    if (elements.autoScrollToggle.checked) {
      elements.transcriptScroll.scrollTo({ top: elements.transcriptScroll.scrollHeight, behavior: "smooth" });
    }
    return true;
  }

  function initializeTranslationCard(card, segmentId) {
    if (!segmentId) {
      updateTranslationCard(card, { status: "disabled" }, { force: true });
      return;
    }

    const deferred = state.translation.deferredEvents.get(segmentId);
    if (deferred) {
      state.translation.deferredEvents.delete(segmentId);
      updateTranslationCard(card, deferred, { force: true });
      return;
    }

    const provider = state.translation.providers.get(state.translation.applied);
    if (state.translation.applied === "none" || !provider?.available) {
      updateTranslationCard(card, { status: "disabled" }, { force: true });
    } else {
      updateTranslationCard(
        card,
        { status: "pending", provider: state.translation.applied },
        { force: true },
      );
    }
  }

  function handleTranslationWebSocketEvent(payload) {
    const event = unwrapEvent(payload);
    const segmentId = translationSegmentId(event);
    if (!segmentId) {
      const status = translationEventStatus(event);
      const customLabel = status === "success" ? t("준비됨") : "";
      setTranslationGlobalStatus(status, customLabel);
      if (status === "error") {
        setTranslationConfigError(extractMessage(event, t("번역 Provider 오류가 발생했습니다.")));
      }
      return;
    }

    const card = state.translation.cards.get(segmentId);
    if (!card || !card.isConnected) {
      bufferTranslationEvent(segmentId, event);
      return;
    }
    updateTranslationCard(card, event);
  }

  async function retryTranslation(segmentId, button) {
    const card = state.translation.cards.get(segmentId);
    if (!card || button.disabled) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    updateTranslationCard(
      card,
      { status: "pending", provider: state.translation.applied },
      { force: true, eventTime: Date.now() },
    );
    try {
      const payload = await apiRequest(`/api/translation/retry/${encodeURIComponent(segmentId)}`, {
        method: "POST",
        timeout: 20_000,
      });
      const result = asObject(payload);
      if (Object.keys(result).length) {
        updateTranslationCard(card, { ...result, segment_id: segmentId });
      }
    } catch (error) {
      updateTranslationCard(
        card,
        {
          type: "translation_error",
          segment_id: segmentId,
          provider: state.translation.applied,
          message: t("재시도 요청 실패: {message}", { message: extractMessage(error) }),
          timestamp: new Date().toISOString(),
        },
        { force: true },
      );
    }
  }

  function renderFinalTranscript(payload) {
    const event = unwrapEvent(payload);
    const text = transcriptText(event);
    const inlineTranslation = firstDefined(event.translation_result, event.translation);
    if (!text && !inlineTranslation) return;
    const displayText = text || (event.original_saved === false
      ? t("원문 저장 안 함")
      : t("저장된 원문이 없습니다."));
    const segmentId = translationSegmentId(event);
    let key = finalEventKey(event, displayText);
    if (key.startsWith("ephemeral:")) {
      const now = Date.now();
      const previous = state.fallbackFinals.get(key) || 0;
      if (now - previous < 1_500) return;
      state.fallbackFinals.set(key, now);
      key = `${key}|${now}`;
      if (state.fallbackFinals.size > 100) {
        const oldest = state.fallbackFinals.keys().next().value;
        state.fallbackFinals.delete(oldest);
      }
    }
    if (state.seenFinals.has(key)) return;
    rememberFinal(key);

    const fragment = elements.transcriptItemTemplate.content.cloneNode(true);
    const item = fragment.querySelector(".transcript-item");
    const timeElement = fragment.querySelector(".transcript-time");
    const languageElement = fragment.querySelector(".language-badge");
    const sourceElement = fragment.querySelector(".source-badge");
    const textElement = fragment.querySelector(".transcript-text");
    const normalizedElement = fragment.querySelector(".context-normalized-text");
    const language = eventLanguage(event);
    const source = normalizeSource(firstDefined(event.source, state.source));
    const probability = firstDefined(event.language_probability, event.languageProbability, event.probability, event.confidence);
    const sessionId = String(firstDefined(event.session_id, event.sessionId, state.sessions.current?.sessionId, ""));
    const time = formatTimestamp(
      firstDefined(event.started_at, event.start_time, event.start, event.timestamp),
      firstDefined(event.ended_at, event.end_time, event.end, event.timestamp),
    );

    item.dataset.key = key;
    item.dataset.segmentId = segmentId;
    item.dataset.sessionId = sessionId;
    timeElement.textContent = time.display;
    if (time.dateTime) timeElement.dateTime = time.dateTime;
    languageElement.textContent = languageLabels[language];
    languageElement.dataset.language = language;
    languageElement.title = languageDescription(language, probability);
    sourceElement.textContent = sourceLabels[source];
    textElement.textContent = displayText;
    const normalizedText = String(firstDefined(event.normalized_text, event.normalizedText, "")).trim();
    const contextChanged = booleanValue(
      firstDefined(event.context_changed, event.contextChanged),
      Boolean(normalizedText && normalizedText !== displayText),
    );
    if (contextChanged && normalizedText && normalizedText !== displayText) {
      normalizedElement.textContent = t("Context 적용: {text}", { text: normalizedText });
      normalizedElement.hidden = false;
    }

    elements.emptyState.hidden = true;
    elements.transcriptList.append(fragment);
    reportTranslationPocDisplay("final", item, displayText);
    if (segmentId) state.translation.cards.set(segmentId, item);
    initializeTranslationCard(item, segmentId);

    if (event.historical && !event.translation_result && !event.translation) {
      updateTranslationCard(item, { status: "disabled" }, { force: true });
    }

    if (inlineTranslation && (typeof inlineTranslation === "string" || typeof inlineTranslation === "object")) {
      const inlineEvent = typeof inlineTranslation === "string"
        ? { type: "translation", segment_id: segmentId, session_id: sessionId, translated_text: inlineTranslation }
        : { ...inlineTranslation, segment_id: segmentId, session_id: sessionId };
      updateTranslationCard(item, inlineEvent);
    }

    if (sessionId && segmentId) {
      if (!state.sessions.current) {
        state.sessions.current = normalizeSession({
          session_id: sessionId,
          status: event.historical ? "saved" : state.captureState,
          started_at: event.started_at,
          ended_at: event.historical ? event.ended_at : null,
          source,
          whisper_model: selectedSttModelLabel(),
          translation_provider: state.translation.applied,
        });
      }
      if (text && event.original_saved !== false) registerOriginalSegment(sessionId, segmentId);
    }

    while (elements.transcriptList.children.length > MAX_TRANSCRIPTS) {
      const oldest = elements.transcriptList.firstElementChild;
      const oldestSegmentId = oldest?.dataset.segmentId;
      if (oldestSegmentId && state.translation.cards.get(oldestSegmentId) === oldest) {
        state.translation.cards.delete(oldestSegmentId);
      }
      oldest?.remove();
    }

    const finalUtteranceId = String(firstDefined(event.utterance_id, event.utteranceId, ""));
    if (!finalUtteranceId || finalUtteranceId === elements.partialPanel.dataset.utteranceId) clearPartial();
    if (elements.autoScrollToggle.checked) {
      elements.transcriptScroll.scrollTo({ top: elements.transcriptScroll.scrollHeight, behavior: "smooth" });
    }
  }

  function loadDisplayPreferences() {
    try {
      const savedSize = Number(localStorage.getItem("mlt-caption-font-size"));
      if (Number.isFinite(savedSize) && savedSize >= 16 && savedSize <= 30) {
        elements.fontSizeRange.value = String(savedSize);
      }
      const savedAutoScroll = localStorage.getItem("mlt-auto-scroll");
      if (savedAutoScroll !== null) elements.autoScrollToggle.checked = savedAutoScroll !== "false";
      const savedViewMode = localStorage.getItem("mlt-caption-view-mode");
      if (["both", "original", "translation"].includes(savedViewMode)) {
        state.captionViewMode = savedViewMode;
      }
    } catch (_error) {
      // Browser privacy settings may disable localStorage; the UI still works with defaults.
    }
    applyCaptionViewMode(state.captionViewMode, { persist: false });
    applyFontSize(elements.fontSizeRange.value);
  }

  function applyCaptionViewMode(value, { persist = true } = {}) {
    const mode = ["both", "original", "translation"].includes(value) ? value : "both";
    state.captionViewMode = mode;
    elements.captionCard.dataset.viewMode = mode;
    elements.captionViewModeSelect.value = mode;
    elements.captionTitle.textContent = {
      both: t("원문·번역 자막"),
      original: t("원문 자막"),
      translation: t("번역 자막"),
    }[mode];
    if (!persist) return;
    try {
      localStorage.setItem("mlt-caption-view-mode", mode);
    } catch (_error) {
      // Preference persistence is optional.
    }
  }

  async function openCaptionWindow() {
    if (window.mltDesktop?.openOverlay) {
      try {
        if (await window.mltDesktop.openOverlay("caption")) return;
      } catch (_error) {
        // A safe user-facing error is shown below.
      }
      showError(t("네이티브 자막 창을 열지 못했습니다. 일반 브라우저 자막 창은 계속 사용할 수 있습니다."));
      return;
    }
    if (captionWindow && !captionWindow.closed) {
      captionWindow.focus();
      return;
    }
    captionWindow = window.open(
      "/captions",
      "whykaigi-captions",
      "popup=yes,width=920,height=620,resizable=yes,scrollbars=no",
    );
    if (!captionWindow) {
      showError(t("자막 창을 열지 못했습니다. 브라우저의 팝업 차단 설정을 확인하세요."));
    }
  }

  async function openMediaCaptionWindow() {
    if (window.mltDesktop?.openOverlay) {
      try {
        if (await window.mltDesktop.openOverlay("media")) return;
      } catch (_error) {
        // A safe user-facing error is shown below.
      }
      showError(t("네이티브 미디어 자막을 열지 못했습니다. 일반 브라우저 미디어 자막은 계속 사용할 수 있습니다."));
      return;
    }
    if (mediaCaptionWindow && !mediaCaptionWindow.closed) {
      mediaCaptionWindow.focus();
      return;
    }
    const availableWidth = Math.max(640, Number(window.screen.availWidth) || 1280);
    const availableHeight = Math.max(240, Number(window.screen.availHeight) || 720);
    const width = Math.min(availableWidth, Math.max(640, Math.round(availableWidth * 0.94)));
    const height = Math.min(220, availableHeight);
    const left = (Number(window.screen.availLeft) || 0) + Math.round((availableWidth - width) / 2);
    const top = (Number(window.screen.availTop) || 0) + availableHeight - height - 12;
    mediaCaptionWindow = window.open(
      "/captions?layout=media",
      "whykaigi-media-captions",
      `popup=yes,width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=no`,
    );
    if (!mediaCaptionWindow) {
      showError(t("미디어 자막을 열지 못했습니다. 브라우저의 팝업 차단 설정을 확인하세요."));
    }
  }

  async function openDecisionRadarWindow() {
    if (window.mltDesktop?.openOverlay) {
      try {
        if (await window.mltDesktop.openOverlay("radar")) return;
      } catch (_error) {
        // A safe user-facing error is shown below.
      }
      showError(t("네이티브 Radar 결과 창을 열지 못했습니다. 일반 브라우저 결과 창은 계속 사용할 수 있습니다."));
      return;
    }
    if (decisionRadarWindow && !decisionRadarWindow.closed) {
      decisionRadarWindow.focus();
      return;
    }
    decisionRadarWindow = window.open(
      "/decision-radar",
      "whykaigi-decision-radar",
      "popup=yes,width=560,height=760,resizable=yes,scrollbars=no",
    );
    if (!decisionRadarWindow) {
      showError(t("Decision Radar 결과 창을 열지 못했습니다. 브라우저의 팝업 차단 설정을 확인하세요."));
    }
  }

  function captionWindowSnapshot() {
    const segments = [...elements.transcriptList.querySelectorAll(".transcript-item")].map((item) => {
      const translationPanel = item.querySelector(".segment-translation");
      const translationStatus = translationPanel?.dataset.status || "missing";
      const translationText = translationStatus === "success"
        ? String(
          translationPanel?.dataset.lastTranslation
          || item.querySelector(".segment-translation-text")?.textContent
          || "",
        ).trim()
        : "";
      const time = item.querySelector(".transcript-time");
      return {
        segment_id: item.dataset.segmentId || item.dataset.key || "",
        session_id: item.dataset.sessionId || "",
        original_text: String(item.querySelector(".transcript-text")?.textContent || "").trim(),
        korean_translation: translationText,
        translation_status: translationStatus,
        language: item.querySelector(".language-badge")?.dataset.language || "unknown",
        started_at: time?.dateTime || null,
        time_display: String(time?.textContent || "").trim(),
      };
    }).filter((segment) => segment.segment_id);
    return {
      type: "bootstrap_response",
      session_id: state.sessions.current?.sessionId || "",
      segments,
      partial: {
        active: elements.partialPanel.dataset.active === "true",
        text: elements.partialText.textContent.trim(),
        language_label: elements.partialLanguage.textContent.trim(),
      },
    };
  }

  function applyFontSize(value) {
    const size = Math.max(16, Math.min(30, Number(value) || 20));
    document.documentElement.style.setProperty("--caption-size", `${size}px`);
    elements.fontSizeValue.value = `${size}px`;
    elements.fontSizeValue.textContent = `${size}px`;
    try {
      localStorage.setItem("mlt-caption-font-size", String(size));
    } catch (_error) {
      // Non-persistent preferences are acceptable when storage is unavailable.
    }
  }

  function bindCollapsibleCards() {
    document.querySelectorAll("details.collapsible-card").forEach((details) => {
      const summary = details.firstElementChild;
      if (!summary || summary.tagName !== "SUMMARY") return;
      const syncExpandedState = () => {
        summary.setAttribute("aria-expanded", String(details.open));
      };
      summary.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        details.open = !details.open;
        syncExpandedState();
      });
      details.addEventListener("toggle", syncExpandedState);
      syncExpandedState();
    });
  }

  function bindEvents() {
    bindCollapsibleCards();
    elements.sourceInputs.forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) setSource(input.value);
      });
    });
    elements.deviceSelect.addEventListener("change", () => {
      state.selectedDevice[state.source] = elements.deviceSelect.value;
      updateControls();
    });
    elements.sttProviderSelect.addEventListener("change", () => {
      state.stt.provider = elements.sttProviderSelect.value === "deepgram" ? "deepgram" : "local";
      renderSttProvider();
    });
    elements.translationDirectionSelect.addEventListener("change", () => {
      const selectedDirection = elements.translationDirectionSelect.value;
      state.translationDirection = TRANSLATION_DIRECTIONS.includes(selectedDirection)
        ? selectedDirection
        : "ja_to_ko";
      renderSttProvider();
      renderTranslationProviderDetails();
      updateControls();
    });
    elements.refreshDevicesButton.addEventListener("click", () => loadDevices({ refresh: true }));
    elements.startButton.addEventListener("click", startCapture);
    elements.pauseButton.addEventListener("click", () => captureAction("pause"));
    elements.resumeButton.addEventListener("click", () => captureAction("resume"));
    elements.stopButton.addEventListener("click", () => captureAction("stop"));
    elements.liveShareConsent.addEventListener("change", () => {
      state.liveShare.consentConfirmed = elements.liveShareConsent.checked;
      updateLiveShareControls();
    });
    elements.startLiveShareButton.addEventListener("click", startLiveShare);
    elements.stopLiveShareButton.addEventListener("click", stopLiveShare);
    elements.copyLiveShareLinkButton.addEventListener("click", copyLiveShareLink);
    elements.refreshLiveShareAuditButton.addEventListener("click", () => loadLiveShareAccessLogs());
    elements.liveShareAuditRoomSelect.addEventListener("change", () => {
      state.liveShare.selectedAccessRoomId = elements.liveShareAuditRoomSelect.value;
      renderLiveShareAccessLogs();
    });
    elements.liveShareDetails.addEventListener("toggle", () => {
      if (elements.liveShareDetails.open) void loadLiveShareAccessLogs({ quiet: true });
    });
    elements.contextProfileSelect.addEventListener("change", updateContextControls);
    elements.activateContextProfileButton.addEventListener("click", activateContextProfile);
    elements.createContextProfileButton.addEventListener("click", createContextProfile);
    elements.contextEntryForm.addEventListener("submit", addContextEntry);
    elements.contextEntryList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-entry-id]");
      if (button) deleteContextEntry(button.dataset.entryId);
    });
    elements.generateContextSuggestionsButton.addEventListener("click", generateContextSuggestions);
    elements.contextSuggestionList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-decision]");
      const item = button?.closest("[data-suggestion-id]");
      if (button && item) decideContextSuggestion(item.dataset.suggestionId, button.dataset.decision);
    });
    elements.translationMethodSelect.addEventListener("change", () => {
      state.translation.selected = normalizeProviderId(elements.translationMethodSelect.value);
      setTranslationConfigError();
      setTranslationFeedback();
      renderTranslationProviderDetails();
    });
    elements.translationConfigToggle.addEventListener("click", () => {
      setTranslationConfigCollapsed(elements.translationCard.dataset.collapsed !== "true");
    });
    elements.translationApplyButton.addEventListener("click", saveTranslationSettings);
    elements.translationTestButton.addEventListener("click", testTranslationProvider);
    elements.decisionRadarProviderSelect.addEventListener("change", () => {
      state.decisionRadar.selected = normalizeDecisionRadarProviderId(elements.decisionRadarProviderSelect.value);
      state.decisionRadar.confirmingProvider = "";
      setDecisionRadarError();
      setDecisionRadarFeedback();
      renderDecisionRadarSettings();
    });
    elements.decisionRadarApplyButton.addEventListener("click", saveDecisionRadarSettings);
    elements.decisionRadarTabs.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-radar-tab]")?.dataset.radarTab;
      if (tab) selectDecisionRadarTab(tab);
    });
    elements.decisionRadarLatestButton.addEventListener("click", scrollDecisionRadarToLatest);
    elements.decisionRadarScroll.addEventListener("scroll", () => {
      const remaining = elements.decisionRadarScroll.scrollHeight
        - elements.decisionRadarScroll.scrollTop
        - elements.decisionRadarScroll.clientHeight;
      const atLatest = remaining <= 36;
      state.decisionRadar.pinnedToLatest = atLatest;
      if (atLatest && state.decisionRadar.unreadByTab[state.decisionRadar.activeTab]) {
        state.decisionRadar.unreadByTab[state.decisionRadar.activeTab] = 0;
        renderDecisionRadarTabs();
      }
    }, { passive: true });
    elements.decisionRadarScroll.addEventListener("click", (event) => {
      const evidenceButton = event.target.closest("[data-evidence-segment-id]");
      if (evidenceButton) {
        navigateToDecisionRadarEvidence(evidenceButton.dataset.evidenceSegmentId);
        return;
      }
      const actionButton = event.target.closest("[data-radar-action]");
      const card = actionButton?.closest("[data-radar-item-id]");
      if (!actionButton || !card) return;
      const itemId = card.dataset.radarItemId;
      if (actionButton.dataset.radarAction === "approve") {
        mutateDecisionRadarItem(itemId, { review_status: "approved" });
      } else if (actionButton.dataset.radarAction === "edit") {
        state.decisionRadar.editingId = itemId;
        renderDecisionRadarItems();
        elements.decisionRadarScroll
          .querySelector(`[data-radar-item-id="${CSS.escape(itemId)}"] textarea`)
          ?.focus();
      } else if (actionButton.dataset.radarAction === "cancel-edit") {
        state.decisionRadar.editingId = "";
        renderDecisionRadarItems();
      } else if (actionButton.dataset.radarAction === "delete") {
        deleteDecisionRadarItem(itemId);
      }
    });
    elements.decisionRadarScroll.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-radar-edit-form]");
      if (!form) return;
      event.preventDefault();
      const item = state.decisionRadar.items.find((candidate) => candidate.id === form.dataset.radarEditForm);
      if (!item) return;
      const data = new FormData(form);
      const body = { text: String(data.get("text") || "").trim() };
      if (item.category === "action_item") {
        body.assignee = String(data.get("assignee") || "").trim();
        body.due_date = String(data.get("due_date") || "").trim();
      }
      mutateDecisionRadarItem(item.id, body);
    });
    elements.analysisProviderSelect.addEventListener("change", () => {
      state.analysis.selected = normalizeAnalysisProviderId(elements.analysisProviderSelect.value);
      if (state.analysis.selected === "none") state.analysis.settings.autoRunOnStop = false;
      setAnalysisError();
      setAnalysisFeedback();
      renderAnalysisSettings();
    });
    elements.analysisAutoRunToggle.addEventListener("change", () => {
      state.analysis.settings.autoRunOnStop = elements.analysisAutoRunToggle.checked;
      updateAnalysisControls();
    });
    elements.analysisApplyButton.addEventListener("click", saveAnalysisSettings);
    elements.generateAnalysisButton.addEventListener("click", () => runAnalysisAction("generate"));
    elements.cancelAnalysisButton.addEventListener("click", () => runAnalysisAction("cancel"));
    elements.retryAnalysisButton.addEventListener("click", () => runAnalysisAction("retry"));
    elements.analysisResults.addEventListener("click", (event) => {
      const button = event.target.closest("[data-evidence-segment-id]");
      if (button) navigateToEvidence(button.dataset.evidenceSegmentId);
    });
    elements.saveOriginalToggle.addEventListener("change", () => {
      state.sessions.settings.saveOriginal = elements.saveOriginalToggle.checked;
      updateSessionControls();
    });
    elements.saveTranslationToggle.addEventListener("change", () => {
      state.sessions.settings.saveTranslation = elements.saveTranslationToggle.checked;
      updateSessionControls();
    });
    elements.saveAnalysisToggle.addEventListener("change", () => {
      state.sessions.settings.saveAnalysis = elements.saveAnalysisToggle.checked;
      updateSessionControls();
    });
    elements.saveSessionSettingsButton.addEventListener("click", saveSessionSettings);
    elements.refreshSessionsButton.addEventListener("click", () => loadSessionList());
    elements.sessionSelect.addEventListener("change", () => {
      state.sessions.selectedId = elements.sessionSelect.value;
      setSessionError();
      setSessionFeedback();
      updateSessionSelectionHint();
      updateSessionControls();
      if (state.sessions.selectedId) {
        loadAnalysisForSession(state.sessions.selectedId);
        if (!["listening", "transcribing", "paused"].includes(state.captureState)) {
          loadDecisionRadarForSession(state.sessions.selectedId);
        }
      }
    });
    elements.restoreSessionButton.addEventListener("click", restoreSelectedSession);
    elements.copyOriginalButton.addEventListener("click", () => copySelectedSession("original"));
    elements.copyTranslationButton.addEventListener("click", () => copySelectedSession("translation"));
    elements.sessionDownloadButtons.forEach((button) => {
      button.addEventListener("click", () => downloadSelectedSession(button.dataset.sessionDownload));
    });
    elements.transcriptList.addEventListener("click", (event) => {
      const button = event.target.closest(".segment-retry-button");
      if (!button) return;
      const card = button.closest(".transcript-item");
      const segmentId = card?.dataset.segmentId || "";
      if (segmentId) retryTranslation(segmentId, button);
    });
    elements.dismissErrorButton.addEventListener("click", dismissError);
    elements.openCaptionWindowButton.addEventListener("click", openCaptionWindow);
    elements.openMediaCaptionWindowButton.addEventListener("click", openMediaCaptionWindow);
    elements.openDecisionRadarWindowButton.addEventListener("click", openDecisionRadarWindow);
    elements.captionViewModeSelect.addEventListener("change", (event) => {
      applyCaptionViewMode(event.target.value);
    });
    elements.fontSizeRange.addEventListener("input", (event) => applyFontSize(event.target.value));
    elements.autoScrollToggle.addEventListener("change", () => {
      try {
        localStorage.setItem("mlt-auto-scroll", String(elements.autoScrollToggle.checked));
      } catch (_error) {
        // Preference persistence is optional.
      }
      if (elements.autoScrollToggle.checked) {
        elements.transcriptScroll.scrollTo({ top: elements.transcriptScroll.scrollHeight, behavior: "smooth" });
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") ensureWebSocket();
    });
    window.addEventListener("storage", (event) => {
      if (event.key === "mlt-caption-view-mode" && event.newValue) {
        applyCaptionViewMode(event.newValue, { persist: false });
      }
    });
    captionChannel?.addEventListener("message", (event) => {
      if (asObject(event.data).type !== "bootstrap_request") return;
      captionChannel.postMessage({
        ...captionWindowSnapshot(),
        request_id: asObject(event.data).request_id || "",
      });
    });
    decisionRadarChannel?.addEventListener("message", (event) => {
      const message = asObject(event.data);
      if (message.type === "bootstrap_request") {
        publishDecisionRadarSnapshot(message.request_id || "");
        return;
      }
      if (message.type === "navigate_evidence" && message.segment_id) {
        window.focus();
        navigateToDecisionRadarEvidence(String(message.segment_id));
      }
    });
    window.addEventListener("beforeunload", () => {
      state.intentionalClose = true;
      if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
      if (state.translation.workerPollTimer) window.clearInterval(state.translation.workerPollTimer);
      if (state.liveShare.accessLogPollTimer) window.clearInterval(state.liveShare.accessLogPollTimer);
      stopAnalysisPolling();
      state.ws?.close(1000, "page closing");
      captionChannel?.close();
      decisionRadarChannel?.close();
    });
  }

  async function initialize() {
    bindEvents();
    loadDisplayPreferences();
    setSource("system");
    renderTranslationDirection({ resetInvalid: false });
    renderCurrentSession();
    connectWebSocket();
    window.requestAnimationFrame(levelDecayLoop);

    await Promise.allSettled([
      healthCheck(),
      loadSettings(),
      loadContextEngine(),
      loadDevices(),
      syncCaptureState({ quiet: true }),
      loadTranslationConfiguration(),
      refreshTranslationWorkerStatus({ quiet: true }),
      loadSessionList({ quiet: true }),
      loadSessionSettings(),
      loadAnalysisConfiguration(),
      loadDecisionRadarConfiguration(),
      loadLiveShareStatus(),
      loadLiveShareAccessLogs({ quiet: true }),
    ]);
    startTranslationWorkerPolling();
    startLiveShareAccessLogPolling();
    updateControls();
  }

  initialize();
})();
