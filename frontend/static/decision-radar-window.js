(() => {
  "use strict";

  const i18n = window.MLTI18n;
  if (!i18n) throw new Error("UI internationalization module is unavailable.");
  const { t } = i18n;
  i18n.bindLanguageControls(document);

  const RECONNECT_MAX_MS = 15_000;
  const CHANNEL_NAME = "mlt-decision-radar-window-v1";
  const STATUS_LABELS = {
    disabled: t("사용 안 함"),
    idle: t("준비됨"),
    buffering: t("근거 수집 중"),
    running: t("Radar 분석 중"),
    error: t("Radar 오류"),
    closed: t("중지됨"),
  };

  const state = {
    provider: "none",
    status: "disabled",
    model: "",
    sessionId: "",
    queueSize: 0,
    queueMaxSize: 0,
    items: [],
    editingId: "",
    mutating: false,
    transparency: 10,
    ws: null,
    reconnectAttempt: 0,
    reconnectTimer: null,
    closing: false,
  };

  const elements = {
    connectionDot: document.querySelector("#radarConnectionDot"),
    connectionStatus: document.querySelector("#radarConnectionStatus"),
    statusBadge: document.querySelector("#radarStatusBadge"),
    providerModel: document.querySelector("#radarProviderModel"),
    session: document.querySelector("#radarSession"),
    queue: document.querySelector("#radarQueue"),
    feedback: document.querySelector("#radarFeedback"),
    error: document.querySelector("#radarError"),
    scroll: document.querySelector("#radarScroll"),
    empty: document.querySelector("#radarEmpty"),
    transparencyRange: document.querySelector("#radarBackgroundOpacityRange"),
    transparencyValue: document.querySelector("#radarBackgroundOpacityValue"),
    closeButton: document.querySelector("#closeRadarWindowButton"),
    historyDetails: document.querySelector("#radarHistoryDetails"),
    historyCount: document.querySelector("#radarHistoryCount"),
    history: document.querySelector("#radarHistory"),
    groups: {
      decision: [document.querySelector("#radarDecisionsGroup"), document.querySelector("#radarDecisions"), document.querySelector("#radarDecisionsCount")],
      action_item: [document.querySelector("#radarActionsGroup"), document.querySelector("#radarActions"), document.querySelector("#radarActionsCount")],
      open_question: [document.querySelector("#radarQuestionsGroup"), document.querySelector("#radarQuestions"), document.querySelector("#radarQuestionsCount")],
      needs_confirmation: [document.querySelector("#radarConfirmationsGroup"), document.querySelector("#radarConfirmations"), document.querySelector("#radarConfirmationsCount")],
    },
  };

  let radarChannel = null;
  try {
    if (typeof BroadcastChannel === "function") radarChannel = new BroadcastChannel(CHANNEL_NAME);
  } catch (_error) {
    radarChannel = null;
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null);
  }

  function eventType(value) {
    return String(firstDefined(value.type, value.event, value.kind, ""))
      .trim()
      .toLowerCase()
      .replace(/[\s.:-]+/g, "_");
  }

  function unwrapRadar(value) {
    const root = asObject(value);
    return asObject(firstDefined(root.decision_radar, asObject(root.data).decision_radar, root.data, root));
  }

  function providerId(value) {
    const raw = String(value || "none").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["openai", "openai_api"].includes(raw)) return "openai";
    if (["gemini", "gemini_api", "google", "google_gemini"].includes(raw)) return "gemini";
    return "none";
  }

  function radarStatus(value, provider = state.provider) {
    if (providerId(provider) === "none") return "disabled";
    const raw = String(value || "idle").trim().toLowerCase().replace(/[\s.-]+/g, "_");
    if (["queued", "pending", "collecting", "buffering"].includes(raw)) return "buffering";
    if (["running", "processing", "analyzing", "in_progress"].includes(raw)) return "running";
    if (["failed", "failure", "unavailable", "error"].includes(raw)) return "error";
    if (["closed", "stopped"].includes(raw)) return "closed";
    return "idle";
  }

  function normalizeEvidence(value) {
    const values = Array.isArray(value) ? value : [];
    return [...new Set(values.map((item) => String(item || "").trim()).filter(Boolean))];
  }

  function normalizeItem(value) {
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
      evidence: normalizeEvidence(firstDefined(item.evidence_segment_ids, item.evidence, [])),
      reviewStatus: String(firstDefined(item.review_status, "suggested")) === "approved" ? "approved" : "suggested",
      userEdited: Boolean(firstDefined(item.user_edited, item.userEdited, false)),
      lifecycleStatus: ["active", "superseded", "resolved", "retracted"].includes(String(firstDefined(item.lifecycle_status, "active")))
        ? String(firstDefined(item.lifecycle_status, "active"))
        : "active",
      lifecycleReason: String(firstDefined(item.lifecycle_reason, "")).trim(),
    };
  }

  function setConnectionStatus(message, status) {
    elements.connectionStatus.textContent = message;
    elements.connectionDot.dataset.state = status;
  }

  function setFeedback(message = "") {
    elements.feedback.textContent = message;
    elements.feedback.hidden = !message;
  }

  function setError(message = "") {
    elements.error.textContent = message;
    elements.error.hidden = !message;
  }

  function kindLabel(item) {
    if (item.category === "needs_confirmation") {
      return { person: t("사람 이름"), term: t("용어"), translation: t("번역") }[item.confirmationKind]
        || t("확인 필요");
    }
    return { decision: t("결정"), action_item: "Action", open_question: t("질문") }[item.category]
      || item.category;
  }

  function evidenceButtons(item) {
    const container = document.createElement("div");
    container.className = "analysis-evidence";
    item.evidence.forEach((segmentId, index) => {
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

  function editForm(item) {
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

  function itemCard(item, { historical = false } = {}) {
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
    kind.textContent = kindLabel(item);
    head.append(review, kind);
    if (historical) review.textContent = ({ superseded: "대체됨", resolved: "해결됨", retracted: "철회됨" }[item.lifecycleStatus] || "변경됨");
    const text = document.createElement("p");
    text.className = "decision-radar-item-copy";
    text.textContent = item.text;
    card.append(head, text);
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
    card.append(evidenceButtons(item));
    if (historical) return card;
    if (state.editingId === item.id) {
      card.append(editForm(item));
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

  function render() {
    elements.statusBadge.dataset.status = state.status;
    elements.statusBadge.textContent = STATUS_LABELS[state.status] || state.status;
    const providerLabel = { none: t("사용 안 함"), openai: "OpenAI API", gemini: "Gemini API" }[state.provider];
    elements.providerModel.textContent = `${providerLabel} · model ${state.model || "—"}`;
    elements.session.textContent = state.sessionId
      ? t("세션 {session}", { session: state.sessionId })
      : t("세션 대기 중");
    elements.queue.textContent = state.queueMaxSize
      ? t("대기열 {size}/{max}", { size: state.queueSize, max: state.queueMaxSize })
      : t("대기열 {size}", { size: state.queueSize });
    let total = 0;
    Object.entries(elements.groups).forEach(([category, [group, container, count]]) => {
      const items = state.items.filter((item) => item.lifecycleStatus === "active" && item.category === category);
      total += items.length;
      count.textContent = String(items.length);
      group.hidden = items.length === 0;
      container.replaceChildren(...items.map(itemCard));
    });
    const historyItems = state.items.filter((item) => item.lifecycleStatus !== "active");
    elements.historyDetails.hidden = historyItems.length === 0;
    elements.historyCount.textContent = String(historyItems.length);
    elements.history.replaceChildren(...historyItems.slice().reverse().map((item) => itemCard(item, { historical: true })));
    elements.empty.hidden = total > 0;
    elements.scroll.querySelectorAll("button, input, textarea").forEach((control) => {
      control.disabled = state.mutating;
    });
  }

  function applySnapshot(value) {
    const root = unwrapRadar(value);
    state.provider = providerId(firstDefined(root.provider, root.selected_provider, state.provider));
    state.status = radarStatus(firstDefined(root.status, root.state), state.provider);
    state.model = String(firstDefined(root.model, root.provider_model, state.model, ""));
    state.sessionId = String(firstDefined(root.session_id, root.sessionId, state.sessionId, ""));
    state.queueSize = Math.max(0, Number(firstDefined(root.queue_size, root.queueSize, state.queueSize, 0)) || 0);
    state.queueMaxSize = Math.max(0, Number(firstDefined(root.queue_max_size, root.queueMaxSize, state.queueMaxSize, 0)) || 0);
    if (Array.isArray(root.items)) {
      state.items = root.items.map(normalizeItem).filter((item) => item.id && item.text && item.evidence.length);
      if (state.editingId && !state.items.some((item) => item.id === state.editingId)) state.editingId = "";
    }
    render();
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const detail = asObject(payload.detail);
      throw new Error(String(firstDefined(detail.message, payload.message, payload.code, response.statusText, response.status)));
    }
    return payload;
  }

  async function loadState() {
    setFeedback(t("결과를 불러오는 중입니다…"));
    try {
      applySnapshot(await apiRequest("/api/decision-radar"));
      setFeedback();
    } catch (error) {
      setFeedback();
      setError(t("결과를 불러오지 못했습니다: {message}", { message: error.message }));
    }
  }

  async function mutateItem(itemId, body) {
    state.mutating = true;
    setError();
    render();
    try {
      const payload = await apiRequest(`/api/decision-radar/items/${encodeURIComponent(itemId)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      state.editingId = "";
      applySnapshot(payload);
      setFeedback(t("Radar 항목을 반영했습니다."));
    } catch (error) {
      setError(t("Radar 항목 반영 실패: {message}", { message: error.message }));
    } finally {
      state.mutating = false;
      render();
    }
  }

  async function deleteItem(itemId) {
    if (!window.confirm(t("이 Radar 항목을 삭제할까요? 같은 내용은 이 세션에서 다시 자동 제안되지 않습니다."))) return;
    state.mutating = true;
    setError();
    render();
    try {
      const payload = await apiRequest(`/api/decision-radar/items/${encodeURIComponent(itemId)}`, { method: "DELETE" });
      state.editingId = "";
      applySnapshot(payload);
      setFeedback(t("Radar 항목을 삭제했습니다."));
    } catch (error) {
      setError(t("Radar 항목 삭제 실패: {message}", { message: error.message }));
    } finally {
      state.mutating = false;
      render();
    }
  }

  function navigateEvidence(segmentId) {
    radarChannel?.postMessage({
      type: "navigate_evidence",
      segment_id: segmentId,
      session_id: state.sessionId,
    });
    window.opener?.focus();
    window.mltDesktop?.focusMainWindow?.();
    setFeedback(t("메인 창에서 근거를 확인합니다."));
  }

  function websocketUrl() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/ws/live`;
  }

  function handleWebSocketMessage(payload) {
    const root = asObject(payload);
    const type = eventType(root);
    if (type === "snapshot") {
      if (root.decision_radar) applySnapshot(root.decision_radar);
      return;
    }
    if (type === "decision_radar_updated") {
      applySnapshot(root.decision_radar || root);
      setError();
      return;
    }
    if (type === "decision_radar_status") {
      state.provider = providerId(firstDefined(root.provider, state.provider));
      state.status = radarStatus(root.status, state.provider);
      state.queueSize = Math.max(0, Number(root.queue_size || 0));
      if (root.session_id) state.sessionId = String(root.session_id);
      render();
      return;
    }
    if (type === "decision_radar_error") {
      state.status = "error";
      setError(t("Decision Radar 분석에 실패했습니다. 자막과 번역은 계속 동작합니다."));
      render();
    }
  }

  function scheduleReconnect() {
    if (state.closing || state.reconnectTimer) return;
    const delay = Math.min(RECONNECT_MAX_MS, 600 * (2 ** state.reconnectAttempt));
    state.reconnectAttempt = Math.min(state.reconnectAttempt + 1, 8);
    setConnectionStatus(t("{seconds}초 후 재연결", { seconds: Math.max(1, Math.ceil(delay / 1000)) }), "error");
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
        (Array.isArray(payload) ? payload : [payload]).forEach(handleWebSocketMessage);
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

  function applyTransparency(value, { persist = true } = {}) {
    const transparency = Math.max(0, Math.min(85, Number(value) || 0));
    state.transparency = transparency;
    document.documentElement.style.setProperty("--radar-surface-opacity", ((100 - transparency) / 100).toFixed(2));
    elements.transparencyRange.value = String(transparency);
    elements.transparencyValue.value = `${transparency}%`;
    elements.transparencyValue.textContent = `${transparency}%`;
    if (!persist) return;
    try {
      localStorage.setItem("mlt-radar-background-transparency", String(transparency));
    } catch (_error) {
      // The window remains usable without persistent browser storage.
    }
  }

  function loadPreferences() {
    let transparency = 10;
    try {
      const saved = Number(localStorage.getItem("mlt-radar-background-transparency"));
      if (Number.isFinite(saved)) transparency = saved;
    } catch (_error) {
      // Defaults are safe when storage is unavailable.
    }
    applyTransparency(transparency, { persist: false });
  }

  function bindEvents() {
    elements.transparencyRange.addEventListener("input", (event) => applyTransparency(event.target.value));
    elements.closeButton.addEventListener("click", () => {
      if (window.mltDesktop?.closeWindow) window.mltDesktop.closeWindow();
      else window.close();
    });
    elements.scroll.addEventListener("click", (event) => {
      const evidence = event.target.closest("[data-evidence-segment-id]");
      if (evidence) {
        navigateEvidence(evidence.dataset.evidenceSegmentId);
        return;
      }
      const action = event.target.closest("[data-radar-action]");
      const card = action?.closest("[data-radar-item-id]");
      if (!action || !card) return;
      const itemId = card.dataset.radarItemId;
      if (action.dataset.radarAction === "approve") mutateItem(itemId, { review_status: "approved" });
      if (action.dataset.radarAction === "edit") {
        state.editingId = itemId;
        render();
        elements.scroll.querySelector(`[data-radar-item-id="${CSS.escape(itemId)}"] textarea`)?.focus();
      }
      if (action.dataset.radarAction === "cancel-edit") {
        state.editingId = "";
        render();
      }
      if (action.dataset.radarAction === "delete") deleteItem(itemId);
    });
    elements.scroll.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-radar-edit-form]");
      if (!form) return;
      event.preventDefault();
      const item = state.items.find((candidate) => candidate.id === form.dataset.radarEditForm);
      if (!item) return;
      const data = new FormData(form);
      const body = { text: String(data.get("text") || "").trim() };
      if (item.category === "action_item") {
        body.assignee = String(data.get("assignee") || "").trim();
        body.due_date = String(data.get("due_date") || "").trim();
      }
      mutateItem(item.id, body);
    });
    radarChannel?.addEventListener("message", (event) => {
      const message = asObject(event.data);
      if (message.type === "bootstrap_response") applySnapshot(message);
    });
    window.addEventListener("beforeunload", () => {
      state.closing = true;
      if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
      state.ws?.close(1000, "radar window closing");
      radarChannel?.close();
    });
  }

  function initialize() {
    if (window.mltDesktop?.isNativeOverlay) document.documentElement.dataset.nativeOverlay = "true";
    loadPreferences();
    bindEvents();
    render();
    connectWebSocket();
    loadState();
    radarChannel?.postMessage({
      type: "bootstrap_request",
      request_id: `${Date.now()}:${Math.random().toString(16).slice(2)}`,
    });
  }

  initialize();
})();
