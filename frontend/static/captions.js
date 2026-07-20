(() => {
  "use strict";

  const i18n = window.MLTI18n;
  if (!i18n) throw new Error("UI internationalization module is unavailable.");
  const { t } = i18n;
  const UI_LOCALE = i18n.language === "en" ? "en-US" : "ko-KR";
  const requestedLayout = new URLSearchParams(window.location.search).get("layout");
  const CAPTION_LAYOUT = requestedLayout === "media" || window.mltDesktop?.windowKind === "media"
    ? "media"
    : "history";
  document.documentElement.dataset.captionLayout = CAPTION_LAYOUT;
  document.body.dataset.captionLayout = CAPTION_LAYOUT;
  i18n.bindLanguageControls(document);

  const MAX_CAPTIONS = 500;
  const RECONNECT_MAX_MS = 15_000;
  const VIEW_MODES = new Set(["auto", "both", "original", "translation"]);
  const MEDIA_WIDTHS = new Set([60, 80, 94]);
  const CHANNEL_NAME = "mlt-caption-window-v1";

  const state = {
    segments: new Map(),
    activeSessionId: "",
    sequence: 0,
    ws: null,
    reconnectAttempt: 0,
    reconnectTimer: null,
    closing: false,
    historyRequest: 0,
    viewMode: CAPTION_LAYOUT === "media" ? "auto" : "both",
    transparency: 10,
    mediaWidth: 94,
    mediaFontSize: 36,
    fitFrame: 0,
  };

  const elements = {
    statusDot: document.querySelector("#statusDot"),
    connectionStatus: document.querySelector("#connectionStatus"),
    windowTitle: document.querySelector("#captionWindowTitle"),
    viewModeSelect: document.querySelector("#captionViewModeSelect"),
    autoViewOption: document.querySelector("#captionAutoViewOption"),
    mediaWidthSelect: document.querySelector("#mediaWidthSelect"),
    mediaFontSizeRange: document.querySelector("#mediaFontSizeRange"),
    mediaFontSizeValue: document.querySelector("#mediaFontSizeValue"),
    transparencyRange: document.querySelector("#backgroundOpacityRange"),
    transparencyValue: document.querySelector("#backgroundOpacityValue"),
    closeButton: document.querySelector("#closeCaptionWindowButton"),
    partialPanel: document.querySelector("#partialPanel"),
    partialLanguage: document.querySelector("#partialLanguage"),
    partialText: document.querySelector("#partialText"),
    captionScroll: document.querySelector("#captionScroll"),
    captionList: document.querySelector("#captionList"),
    emptyState: document.querySelector("#emptyState"),
    itemTemplate: document.querySelector("#captionItemTemplate"),
  };

  const languageLabels = {
    ja: t("일본어"),
    en: t("영어"),
    ko: t("한국어"),
    mixed: t("혼합"),
    unknown: t("언어 미확정"),
  };

  let captionChannel = null;
  try {
    if (typeof BroadcastChannel === "function") {
      captionChannel = new BroadcastChannel(CHANNEL_NAME);
    }
  } catch (_error) {
    captionChannel = null;
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null);
  }

  function eventType(event) {
    return String(firstDefined(event.type, event.event, event.kind, ""))
      .trim()
      .toLowerCase()
      .replace(/[\s.:-]+/g, "_");
  }

  function segmentId(event) {
    return String(firstDefined(
      event.segment_id,
      event.segmentId,
      asObject(event.result).segment_id,
      "",
    )).trim();
  }

  function websocketUrl() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/ws/live`;
  }

  function setConnectionStatus(label, status) {
    elements.connectionStatus.textContent = i18n.localizeExternalText(label);
    elements.statusDot.dataset.state = status;
  }

  function applyViewMode(value, { persist = true } = {}) {
    const fallback = CAPTION_LAYOUT === "media" ? "auto" : "both";
    const requested = VIEW_MODES.has(value) ? value : fallback;
    const mode = CAPTION_LAYOUT === "history" && requested === "auto" ? "both" : requested;
    state.viewMode = mode;
    document.body.dataset.viewMode = mode;
    elements.viewModeSelect.value = mode;
    scheduleMediaFit();
    if (!persist) return;
    try {
      localStorage.setItem(
        CAPTION_LAYOUT === "media" ? "mlt-media-caption-view-mode" : "mlt-caption-view-mode",
        mode,
      );
    } catch (_error) {
      // The caption window remains usable when storage is unavailable.
    }
  }

  function applyTransparency(value, { persist = true } = {}) {
    const transparency = Math.max(0, Math.min(85, Number(value) || 0));
    const surfaceOpacity = (100 - transparency) / 100;
    state.transparency = transparency;
    document.documentElement.style.setProperty("--surface-opacity", surfaceOpacity.toFixed(2));
    elements.transparencyRange.value = String(transparency);
    elements.transparencyValue.value = `${transparency}%`;
    elements.transparencyValue.textContent = `${transparency}%`;
    if (!persist) return;
    try {
      localStorage.setItem("mlt-caption-background-transparency", String(transparency));
    } catch (_error) {
      // The caption window remains usable when storage is unavailable.
    }
  }

  function normalizeMediaWidth(value) {
    const width = Number(value);
    return MEDIA_WIDTHS.has(width) ? width : 94;
  }

  function applyMediaWidth(value, { persist = true, reposition = true } = {}) {
    if (CAPTION_LAYOUT !== "media") return;
    const width = normalizeMediaWidth(value);
    state.mediaWidth = width;
    elements.mediaWidthSelect.value = String(width);
    if (persist) {
      try {
        localStorage.setItem("mlt-media-caption-width", String(width));
      } catch (_error) {
        // The default width remains available when storage is unavailable.
      }
    }
    if (!reposition) return;
    if (window.mltDesktop?.setMediaWidth) {
      Promise.resolve(window.mltDesktop.setMediaWidth(width)).catch(() => {});
      return;
    }
    try {
      const availableWidth = Math.max(640, Number(window.screen.availWidth) || 1280);
      const availableHeight = Math.max(240, Number(window.screen.availHeight) || 720);
      const targetWidth = Math.min(
        availableWidth,
        Math.max(640, Math.round(availableWidth * width / 100)),
      );
      const targetHeight = Math.min(220, availableHeight);
      const left = (Number(window.screen.availLeft) || 0)
        + Math.round((availableWidth - targetWidth) / 2);
      const top = (Number(window.screen.availTop) || 0)
        + availableHeight - targetHeight - 12;
      window.resizeTo(targetWidth, targetHeight);
      window.moveTo(left, top);
    } catch (_error) {
      // Browsers may deny scripted resize/move; the responsive page remains usable.
    }
  }

  function applyMediaFontSize(value, { persist = true } = {}) {
    if (CAPTION_LAYOUT !== "media") return;
    const size = Math.max(22, Math.min(48, Number(value) || 36));
    state.mediaFontSize = size;
    document.documentElement.style.setProperty("--caption-size", `${size}px`);
    elements.mediaFontSizeRange.value = String(size);
    elements.mediaFontSizeValue.value = `${size}px`;
    elements.mediaFontSizeValue.textContent = `${size}px`;
    scheduleMediaFit();
    if (!persist) return;
    try {
      localStorage.setItem("mlt-media-caption-font-size", String(size));
    } catch (_error) {
      // The default media font size remains available when storage is unavailable.
    }
  }

  function fitMediaLine(element) {
    if (!element || element.offsetParent === null || element.clientWidth <= 0) return;
    element.style.removeProperty("font-size");
    let size = Math.max(18, Number.parseFloat(getComputedStyle(element).fontSize) || state.mediaFontSize);
    while (element.scrollWidth > element.clientWidth + 1 && size > 18) {
      size -= 1;
      element.style.fontSize = `${size}px`;
    }
  }

  function scheduleMediaFit() {
    if (CAPTION_LAYOUT !== "media" || state.fitFrame) return;
    state.fitFrame = window.requestAnimationFrame(() => {
      state.fitFrame = 0;
      document.querySelectorAll(
        ".live-partial[data-active='true'] #partialText, .caption-item:last-child .original-text, .caption-item:last-child .translation-text",
      ).forEach(fitMediaLine);
    });
  }

  function loadPreferences() {
    let viewMode = CAPTION_LAYOUT === "media" ? "auto" : "both";
    let transparency = 10;
    let fontSize = CAPTION_LAYOUT === "media" ? 36 : 24;
    let mediaWidth = 94;
    try {
      viewMode = localStorage.getItem(
        CAPTION_LAYOUT === "media" ? "mlt-media-caption-view-mode" : "mlt-caption-view-mode",
      ) || viewMode;
      const savedTransparencyValue = localStorage.getItem(
        "mlt-caption-background-transparency",
      );
      if (savedTransparencyValue !== null) {
        const savedTransparency = Number(savedTransparencyValue);
        if (Number.isFinite(savedTransparency)) transparency = savedTransparency;
      }
      const savedFontSizeValue = localStorage.getItem(
        CAPTION_LAYOUT === "media" ? "mlt-media-caption-font-size" : "mlt-caption-font-size",
      );
      if (savedFontSizeValue !== null) {
        const savedFontSize = Number(savedFontSizeValue);
        if (Number.isFinite(savedFontSize)) fontSize = savedFontSize;
      }
      const savedMediaWidth = Number(localStorage.getItem("mlt-media-caption-width"));
      if (MEDIA_WIDTHS.has(savedMediaWidth)) mediaWidth = savedMediaWidth;
    } catch (_error) {
      // Defaults are safe when storage is unavailable.
    }
    if (CAPTION_LAYOUT === "media") {
      applyMediaFontSize(fontSize, { persist: false });
      applyMediaWidth(mediaWidth, { persist: false });
    } else {
      document.documentElement.style.setProperty(
        "--caption-size",
        `${Math.max(16, Math.min(30, fontSize))}px`,
      );
    }
    applyViewMode(viewMode, { persist: false });
    applyTransparency(transparency, { persist: false });
  }

  function normalizedLanguage(value) {
    const language = String(value || "unknown").trim().toLowerCase().split(/[-_]/)[0];
    return languageLabels[language] ? language : "unknown";
  }

  function timestampValue(value) {
    const parsed = value ? Date.parse(String(value)) : Number.NaN;
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatTime(segment) {
    if (segment.timeDisplay) return segment.timeDisplay;
    const raw = firstDefined(segment.startedAt, segment.endedAt);
    const value = timestampValue(raw);
    if (!value) return t("시간 미상");
    return new Intl.DateTimeFormat(UI_LOCALE, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(value));
  }

  function translationText(event) {
    const translation = event.translation;
    const result = asObject(event.result);
    if (typeof translation === "string") return translation.trim();
    return String(firstDefined(
      event.translated_text,
      event.target_text,
      event.korean_translation,
      asObject(translation).translated_text,
      asObject(translation).text,
      result.translated_text,
      result.translation,
      result.text,
      "",
    )).trim();
  }

  function translationStatus(event) {
    const type = eventType(event);
    if (type === "translation_pending") return "pending";
    if (type === "translation_error") return "error";
    if (["translation", "translation_success", "translation_completed"].includes(type)) {
      return translationText(event) ? "success" : "error";
    }
    const status = String(firstDefined(
      event.translation_status,
      event.status,
      event.state,
      "missing",
    )).trim().toLowerCase();
    if (["completed", "complete", "success", "succeeded", "ready"].includes(status)) return "success";
    if (["pending", "queued", "translating", "running"].includes(status)) return "pending";
    if (["failed", "failure", "error", "unavailable"].includes(status)) return "error";
    if (["disabled", "not_requested"].includes(status)) return "disabled";
    return "missing";
  }

  function upsertSegment(id, patch, { render = true } = {}) {
    if (!id) return;
    const previous = state.segments.get(id) || {
      id,
      order: state.sequence++,
      originalText: "",
      translationText: "",
      translationStatus: "missing",
      language: "unknown",
      startedAt: null,
      endedAt: null,
      timeDisplay: "",
    };
    const next = { ...previous };
    Object.entries(patch).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (
        ["originalText", "translationText"].includes(key)
        && value === ""
        && next[key]
      ) return;
      next[key] = value;
    });
    if (
      previous.translationStatus === "success"
      && ["missing", "pending", "disabled"].includes(next.translationStatus)
    ) {
      next.translationStatus = previous.translationStatus;
      next.translationText = previous.translationText;
    }
    state.segments.set(id, next);
    while (state.segments.size > MAX_CAPTIONS) {
      const oldest = [...state.segments.values()].sort((left, right) => left.order - right.order)[0];
      if (!oldest) break;
      state.segments.delete(oldest.id);
    }
    if (render) renderSegments();
  }

  function segmentSortValue(segment) {
    return timestampValue(segment.startedAt) || segment.order;
  }

  function translationDisplay(segment) {
    if (
      ["success", "error"].includes(segment.translationStatus)
      && segment.translationText
    ) {
      return segment.translationText;
    }
    if (segment.translationStatus === "pending") return t("번역 중…");
    if (segment.translationStatus === "error") return t("번역을 완료하지 못했습니다.");
    if (segment.translationStatus === "disabled") return t("번역을 사용하지 않습니다.");
    return t("번역 결과가 없습니다.");
  }

  function renderSegments() {
    const segments = [...state.segments.values()].sort((left, right) => {
      const byTime = segmentSortValue(left) - segmentSortValue(right);
      return byTime || left.order - right.order;
    });
    const fragment = document.createDocumentFragment();
    segments.forEach((segment) => {
      const clone = elements.itemTemplate.content.cloneNode(true);
      const item = clone.querySelector(".caption-item");
      const time = clone.querySelector("time");
      const language = clone.querySelector(".language-label");
      const original = clone.querySelector(".original-text");
      const translation = clone.querySelector(".caption-translation");
      const translated = clone.querySelector(".translation-text");
      item.dataset.segmentId = segment.id;
      time.textContent = formatTime(segment);
      if (segment.startedAt) time.dateTime = String(segment.startedAt);
      language.textContent = languageLabels[normalizedLanguage(segment.language)];
      original.textContent = segment.originalText || t("원문을 기다리는 중입니다…");
      translation.dataset.status = segment.translationStatus || "missing";
      translated.textContent = translationDisplay(segment);
      fragment.append(clone);
    });
    elements.captionList.replaceChildren(fragment);
    elements.emptyState.hidden = segments.length > 0;
    window.requestAnimationFrame(() => {
      elements.captionScroll.scrollTop = elements.captionScroll.scrollHeight;
      scheduleMediaFit();
    });
  }

  function renderPartial(event) {
    const text = String(firstDefined(event.text, event.transcript, event.partial, "")).trim();
    if (!text) return;
    const language = normalizedLanguage(firstDefined(event.language, event.detected_language));
    elements.partialPanel.dataset.active = "true";
    document.body.dataset.partialActive = "true";
    elements.partialLanguage.textContent = String(
      i18n.localizeExternalText(firstDefined(event.language_label, languageLabels[language])),
    );
    elements.partialText.textContent = text;
    scheduleMediaFit();
  }

  function clearPartial() {
    elements.partialPanel.dataset.active = "false";
    document.body.dataset.partialActive = "false";
    elements.partialLanguage.textContent = "—";
    elements.partialText.textContent = t("새로운 음성을 기다리고 있습니다.");
  }

  function handleFinal(event) {
    const id = segmentId(event);
    const originalText = String(firstDefined(
      event.text,
      event.original_text,
      event.source_text,
      "",
    )).trim();
    if (!id && !originalText) return;
    const safeId = id || `ephemeral:${Date.now()}:${state.sequence}`;
    const inlineTranslation = translationText(event);
    upsertSegment(safeId, {
      originalText,
      language: normalizedLanguage(firstDefined(event.language, event.source_language)),
      startedAt: firstDefined(event.started_at, event.start_time, event.timestamp),
      endedAt: firstDefined(event.ended_at, event.end_time, event.timestamp),
      translationText: inlineTranslation || undefined,
      translationStatus: inlineTranslation ? "success" : undefined,
    });
    clearPartial();
  }

  function handleTranslation(event) {
    const id = segmentId(event);
    if (!id) return;
    const text = translationText(event);
    upsertSegment(id, {
      translationText: text || undefined,
      translationStatus: translationStatus(event),
    });
  }

  function normalizeHistoricalSegment(raw) {
    const segment = asObject(raw);
    return {
      id: String(firstDefined(segment.segment_id, segment.segmentId, "")).trim(),
      originalText: String(firstDefined(segment.original_text, segment.text, "")).trim(),
      translationText: String(firstDefined(
        segment.korean_translation,
        segment.translated_text,
        "",
      )).trim(),
      translationStatus: translationStatus(segment),
      language: normalizedLanguage(segment.language),
      startedAt: firstDefined(segment.started_at, segment.start_time),
      endedAt: firstDefined(segment.ended_at, segment.end_time),
      order: Number.isFinite(Number(segment.event_index))
        ? Number(segment.event_index)
        : undefined,
    };
  }

  async function loadActiveSession(sessionId) {
    if (!sessionId) return;
    const request = ++state.historyRequest;
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/segments`,
        { headers: { Accept: "application/json" } },
      );
      if (!response.ok) return;
      const payload = asObject(await response.json());
      if (request !== state.historyRequest || state.activeSessionId !== sessionId) return;
      const segments = Array.isArray(payload.segments) ? payload.segments : [];
      segments.forEach((raw) => {
        const segment = normalizeHistoricalSegment(raw);
        upsertSegment(segment.id, segment, { render: false });
      });
      renderSegments();
    } catch (_error) {
      // Live WebSocket events continue even when catch-up history is unavailable.
    }
  }

  function switchSession(sessionId, { clear = true } = {}) {
    const normalized = String(sessionId || "").trim();
    if (!normalized || normalized === state.activeSessionId) return;
    state.activeSessionId = normalized;
    state.historyRequest += 1;
    if (clear) {
      state.segments.clear();
      clearPartial();
      renderSegments();
    }
    loadActiveSession(normalized);
  }

  function handleSnapshot(event) {
    const session = asObject(event.session);
    const sessionId = String(firstDefined(
      session.active_session_id,
      asObject(event.capture).session_id,
      asObject(event.capture).last_session_id,
      "",
    )).trim();
    if (sessionId) switchSession(sessionId, { clear: state.segments.size === 0 });
  }

  function handleWebSocketEvent(payload) {
    const event = asObject(payload);
    const type = eventType(event);
    if (type === "snapshot") {
      handleSnapshot(event);
      return;
    }
    if (type === "session_created") {
      switchSession(firstDefined(event.session_id, event.sessionId), { clear: true });
      return;
    }
    if ([
      "translation",
      "translation_pending",
      "translation_status",
      "translation_error",
      "translation_success",
      "translation_completed",
    ].includes(type)) {
      handleTranslation(event);
      return;
    }
    if (type === "partial_clear") {
      clearPartial();
      return;
    }
    if (type.includes("partial") || event.is_final === false || event.final === false) {
      renderPartial(event);
      return;
    }
    if (type.includes("final") || event.is_final === true || event.final === true) {
      handleFinal(event);
    }
  }

  function scheduleReconnect() {
    if (state.closing || state.reconnectTimer) return;
    const delay = Math.min(RECONNECT_MAX_MS, 600 * (2 ** state.reconnectAttempt));
    state.reconnectAttempt = Math.min(state.reconnectAttempt + 1, 8);
    setConnectionStatus(t("{seconds}초 후 재연결", {
      seconds: Math.max(1, Math.ceil(delay / 1000)),
    }), "error");
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      connectWebSocket();
    }, delay);
  }

  function connectWebSocket() {
    if (state.closing) return;
    if (state.ws && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.ws.readyState)) return;
    setConnectionStatus(t("연결 중"), "connecting");
    let socket;
    try {
      socket = new WebSocket(websocketUrl());
    } catch (_error) {
      scheduleReconnect();
      return;
    }
    state.ws = socket;
    socket.addEventListener("open", () => {
      if (state.ws !== socket) return;
      state.reconnectAttempt = 0;
      setConnectionStatus(t("연결됨"), "connected");
    });
    socket.addEventListener("message", (message) => {
      try {
        const payload = JSON.parse(message.data);
        (Array.isArray(payload) ? payload : [payload]).forEach(handleWebSocketEvent);
      } catch (_error) {
        setConnectionStatus(t("메시지 오류"), "error");
      }
    });
    socket.addEventListener("error", () => {
      if (state.ws === socket) setConnectionStatus(t("연결 오류"), "error");
    });
    socket.addEventListener("close", () => {
      if (state.ws !== socket) return;
      state.ws = null;
      scheduleReconnect();
    });
  }

  function handleBootstrap(payload) {
    const message = asObject(payload);
    if (message.type !== "bootstrap_response") return;
    const sessionId = String(message.session_id || "").trim();
    if (sessionId && !state.activeSessionId) state.activeSessionId = sessionId;
    const segments = Array.isArray(message.segments) ? message.segments : [];
    segments.forEach((raw) => {
      const segment = normalizeHistoricalSegment(raw);
      if (raw.time_display) segment.timeDisplay = String(raw.time_display);
      upsertSegment(segment.id, segment, { render: false });
    });
    const partial = asObject(message.partial);
    if (partial.active && partial.text) renderPartial(partial);
    renderSegments();
  }

  function requestMainWindowBootstrap() {
    if (!captionChannel) return;
    captionChannel.postMessage({
      type: "bootstrap_request",
      request_id: `${Date.now()}:${Math.random().toString(16).slice(2)}`,
    });
  }

  function bindEvents() {
    elements.viewModeSelect.addEventListener("change", (event) => {
      applyViewMode(event.target.value);
    });
    elements.transparencyRange.addEventListener("input", (event) => {
      applyTransparency(event.target.value);
    });
    elements.mediaWidthSelect.addEventListener("change", (event) => {
      applyMediaWidth(event.target.value);
    });
    elements.mediaFontSizeRange.addEventListener("input", (event) => {
      applyMediaFontSize(event.target.value);
    });
    elements.closeButton.addEventListener("click", () => {
      if (window.mltDesktop?.closeWindow) window.mltDesktop.closeWindow();
      else window.close();
    });
    window.addEventListener("storage", (event) => {
      const viewStorageKey = CAPTION_LAYOUT === "media"
        ? "mlt-media-caption-view-mode"
        : "mlt-caption-view-mode";
      if (event.key === viewStorageKey && event.newValue) {
        applyViewMode(event.newValue, { persist: false });
      }
      if (CAPTION_LAYOUT === "history" && event.key === "mlt-caption-font-size" && event.newValue) {
        const size = Math.max(16, Math.min(30, Number(event.newValue) || 24));
        document.documentElement.style.setProperty("--caption-size", `${size}px`);
      }
      if (CAPTION_LAYOUT === "media" && event.key === "mlt-media-caption-font-size" && event.newValue) {
        applyMediaFontSize(event.newValue, { persist: false });
      }
      if (CAPTION_LAYOUT === "media" && event.key === "mlt-media-caption-width" && event.newValue) {
        applyMediaWidth(event.newValue, { persist: false });
      }
    });
    window.addEventListener("resize", scheduleMediaFit);
    captionChannel?.addEventListener("message", (event) => handleBootstrap(event.data));
    window.addEventListener("beforeunload", () => {
      state.closing = true;
      if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
      if (state.fitFrame) window.cancelAnimationFrame(state.fitFrame);
      state.ws?.close(1000, "caption window closing");
      captionChannel?.close();
    });
  }

  function initialize() {
    if (window.mltDesktop?.isNativeOverlay) document.documentElement.dataset.nativeOverlay = "true";
    elements.autoViewOption.hidden = CAPTION_LAYOUT !== "media";
    elements.autoViewOption.disabled = CAPTION_LAYOUT !== "media";
    if (CAPTION_LAYOUT === "media") {
      document.title = t("미디어 자막 · Meeting Live Translator");
      elements.windowTitle.textContent = t("미디어 자막");
    }
    loadPreferences();
    bindEvents();
    connectWebSocket();
    requestMainWindowBootstrap();
  }

  initialize();
})();
