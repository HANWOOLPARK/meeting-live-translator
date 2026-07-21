"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SharedRadarItem, SharedSegment } from "../../../lib/relay";

type ViewerState = {
  capture_status: string;
  partial: { utterance_id: string; text: string; language: string; timestamp: string | null } | null;
  segments: SharedSegment[];
  radar: {
    status: string;
    revision: number;
    updated_at: string | null;
    queue_size: number;
    message: string | null;
    items: SharedRadarItem[];
  };
};

type RoomPayload = {
  status: string;
  revision: number;
  expires_at: string;
  presenter_online: boolean;
  retention_policy: string;
  state: ViewerState;
};

type Language = "ko" | "en";
type ViewMode = "both" | "translation";
type RadarTab = "core" | "decision" | "action" | "issues";
type AccessStage = "checking" | "email" | "code" | "authenticated";

const copy = {
  ko: {
    live: "실시간 공유 중",
    reconnecting: "연결 다시 확인 중",
    ended: "공유가 종료되었습니다",
    unavailable: "회의방을 확인할 수 없습니다",
    captions: "실시간 자막",
    radar: "Decision Radar",
    interim: "임시 원문",
    waiting: "확정 자막을 기다리고 있습니다.",
    translationWaiting: "번역을 기다리는 중…",
    translationError: "번역을 표시하지 못했습니다. 원문은 계속 공유됩니다.",
    both: "원문 + 번역",
    translation: "번역만",
    privacy: "오디오·API 키·Provider 설정·과거 세션은 공유되지 않습니다.",
    retention: "공유 종료 시 중계 텍스트 즉시 삭제 · 비정상 종료 시 15분 유휴 만료 · 최대 8시간",
    decisions: "결정 사항",
    actions: "할 일",
    questions: "미해결 질문",
    confirmations: "확인 필요",
    core: "핵심",
    issues: "미해결",
    newItems: "개 새 항목",
    latest: "최신으로",
    noRadar: "아직 포착한 항목이 없습니다.",
    suggested: "제안",
    approved: "승인됨",
    assignee: "담당",
    due: "기한",
    evidence: "근거",
    evidenceUnavailable: "해당 근거는 현재 자막 표시 범위를 벗어났습니다.",
    presenterOffline: "진행자 연결 확인 중",
    radarDelayed: "Radar 분석이 지연 중이지만 자막은 계속 표시됩니다.",
    expired: "진행자가 공유를 종료했거나 보관 기간이 만료되었습니다.",
    accessTitle: "이메일 인증 후 입장",
    accessLead: "초대 링크를 받은 본인의 이메일로 6자리 인증번호를 받아 입력하세요.",
    emailLabel: "이메일",
    emailPlaceholder: "name@example.com",
    sendCode: "인증번호 받기",
    codeLabel: "6자리 인증번호",
    codePlaceholder: "000000",
    verifyCode: "인증하고 입장",
    resendCode: "인증번호 다시 받기",
    changeEmail: "이메일 변경",
    sending: "전송 중…",
    verifying: "확인 중…",
    codeSent: "인증번호를 이메일로 보냈습니다. 10분 안에 입력하세요.",
    invalidEmail: "올바른 이메일 주소를 입력하세요.",
    invalidCode: "인증번호가 올바르지 않거나 만료되었습니다.",
    rateLimited: "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
    deliveryUnavailable: "인증 메일 서비스가 아직 설정되지 않았습니다. 진행자에게 알려주세요.",
    accessError: "인증을 처리하지 못했습니다. 잠시 후 다시 시도하세요.",
    accessPrivacy: "이메일과 링크 접속 기록은 보안 감사 목적으로 30일 보관 후 자동 삭제됩니다. 인증 메일 전송을 위해 이메일 주소가 Resend로 전달됩니다.",
    contentPrivacy: "회의 중계 텍스트는 공유 종료 시 즉시 삭제됩니다.",
    signOut: "나가기",
  },
  en: {
    live: "Live sharing",
    reconnecting: "Reconnecting",
    ended: "Sharing has ended",
    unavailable: "This meeting room is unavailable",
    captions: "Live captions",
    radar: "Decision Radar",
    interim: "Interim original",
    waiting: "Waiting for finalized captions.",
    translationWaiting: "Waiting for translation…",
    translationError: "Translation is unavailable. The original continues.",
    both: "Original + translation",
    translation: "Translation only",
    privacy: "Audio, API keys, provider settings, and past sessions are not shared.",
    retention: "Relay text is deleted when sharing ends · 15-minute idle expiry · 8-hour maximum",
    decisions: "Decisions",
    actions: "Action items",
    questions: "Open questions",
    confirmations: "Needs confirmation",
    core: "Key items",
    issues: "Open",
    newItems: "new items",
    latest: "Jump to latest",
    noRadar: "No evidence-linked items yet.",
    suggested: "Suggested",
    approved: "Approved",
    assignee: "Owner",
    due: "Due",
    evidence: "Evidence",
    evidenceUnavailable: "That evidence is outside the current caption window.",
    presenterOffline: "Checking presenter connection",
    radarDelayed: "Radar analysis is delayed. Captions continue.",
    expired: "The host ended sharing or the retention period expired.",
    accessTitle: "Verify your email to enter",
    accessLead: "Receive a six-digit code at your own email address before opening this invite.",
    emailLabel: "Email",
    emailPlaceholder: "name@example.com",
    sendCode: "Send verification code",
    codeLabel: "Six-digit verification code",
    codePlaceholder: "000000",
    verifyCode: "Verify and enter",
    resendCode: "Send a new code",
    changeEmail: "Use another email",
    sending: "Sending…",
    verifying: "Verifying…",
    codeSent: "A verification code was sent. Enter it within 10 minutes.",
    invalidEmail: "Enter a valid email address.",
    invalidCode: "The verification code is invalid or expired.",
    rateLimited: "Too many requests. Please wait and try again.",
    deliveryUnavailable: "Email verification is not configured yet. Contact the host.",
    accessError: "Verification could not be completed. Try again shortly.",
    accessPrivacy: "Your email and invite access records are retained for security auditing and automatically deleted after 30 days. Your email is sent to Resend to deliver the code.",
    contentPrivacy: "Relayed meeting text is deleted when sharing ends.",
    signOut: "Sign out",
  },
} as const;

const radarTabCategories: Record<RadarTab, SharedRadarItem["category"][]> = {
  core: ["decision", "action_item"],
  decision: ["decision"],
  action: ["action_item"],
  issues: ["open_question", "needs_confirmation"],
};

function tabsForRadarCategory(category: SharedRadarItem["category"]): RadarTab[] {
  if (category === "decision") return ["core", "decision"];
  if (category === "action_item") return ["core", "action"];
  return ["issues"];
}

function displayTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

export function ViewerRoom({ roomId }: { roomId: string }) {
  const [payload, setPayload] = useState<RoomPayload | null>(null);
  const [connection, setConnection] = useState<"connecting" | "live" | "reconnecting" | "ended" | "missing">("connecting");
  const [language, setLanguage] = useState<Language>("ko");
  const [viewMode, setViewMode] = useState<ViewMode>("both");
  const [radarTab, setRadarTab] = useState<RadarTab>("core");
  const [radarUnread, setRadarUnread] = useState<Record<RadarTab, number>>({ core: 0, decision: 0, action: 0, issues: 0 });
  const [evidenceNotice, setEvidenceNotice] = useState("");
  const [accessStage, setAccessStage] = useState<AccessStage>("checking");
  const [authEmail, setAuthEmail] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [authError, setAuthError] = useState("");
  const [emailDeliveryConfigured, setEmailDeliveryConfigured] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const radarScrollRef = useRef<HTMLDivElement>(null);
  const radarPinnedRef = useRef(true);
  const radarKnownIdsRef = useRef(new Set<string>());
  const radarInitializedRef = useRef(false);
  const lastRevision = useRef(-1);
  const labels = copy[language];
  const captionSegments = useMemo(
    () => [...(payload?.state.segments ?? [])].reverse(),
    [payload?.state.segments],
  );
  const radarItems = useMemo(() => payload?.state.radar.items ?? [], [payload?.state.radar.items]);

  useEffect(() => {
    const stored = window.localStorage.getItem("mlt-viewer-language");
    if (stored !== "ko" && stored !== "en") return;
    const timer = window.setTimeout(() => setLanguage(stored), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const checkAccess = async () => {
      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/status`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (cancelled) return;
        if (response.status === 410) {
          setConnection("ended");
          return;
        }
        if (response.status === 404) {
          setConnection("missing");
          return;
        }
        if (!response.ok) throw new Error("access_status_failed");
        const status = await response.json() as {
          authenticated?: boolean;
          email_delivery_configured?: boolean;
        };
        setEmailDeliveryConfigured(status.email_delivery_configured !== false);
        setAccessStage(status.authenticated ? "authenticated" : "email");
      } catch {
        if (!cancelled) {
          setAccessStage("email");
          setAuthError(labels.accessError);
        }
      }
    };
    void checkAccess();
    return () => { cancelled = true; };
  }, [roomId, labels.accessError]);

  useEffect(() => {
    if (accessStage !== "authenticated") return;
    let cancelled = false;
    let terminal = false;
    let timer = 0;
    const poll = async () => {
      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (cancelled) return;
        if (response.status === 410) {
          terminal = true;
          setPayload(null);
          setConnection("ended");
          return;
        }
        if (response.status === 404) {
          terminal = true;
          setPayload(null);
          setConnection("missing");
          return;
        }
        if (response.status === 401) {
          terminal = true;
          setPayload(null);
          setAccessStage("email");
          setAuthError("");
          return;
        }
        if (!response.ok) throw new Error("room_fetch_failed");
        const next = (await response.json()) as RoomPayload;
        setPayload(next);
        setConnection(next.presenter_online ? "live" : "reconnecting");
      } catch {
        if (!cancelled) setConnection((current) => current === "connecting" ? "reconnecting" : current);
      } finally {
        if (!cancelled && !terminal) {
          timer = window.setTimeout(poll, document.hidden ? 1_500 : 450);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [roomId, accessStage]);

  const authFailureMessage = (code: string) => {
    if (code === "invalid_email") return labels.invalidEmail;
    if (code === "invalid_or_expired_code") return labels.invalidCode;
    if (code === "verification_code_rate_limited") return labels.rateLimited;
    if (["email_delivery_unavailable", "email_delivery_failed"].includes(code)) return labels.deliveryUnavailable;
    return labels.accessError;
  };

  const requestVerificationCode = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (authBusy) return;
    setAuthBusy(true);
    setAuthError("");
    setAuthMessage("");
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email: authEmail }),
      });
      const result = await response.json().catch(() => ({})) as { code?: string; challenge_id?: string };
      if (response.status === 410) {
        setConnection("ended");
        return;
      }
      if (!response.ok || !result.challenge_id) throw new Error(result.code || "verification_request_failed");
      setChallengeId(result.challenge_id);
      setAuthCode("");
      setAccessStage("code");
      setAuthMessage(labels.codeSent);
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      setAuthError(authFailureMessage(code));
    } finally {
      setAuthBusy(false);
    }
  };

  const verifyAccessCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (authBusy || !challengeId) return;
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ challenge_id: challengeId, code: authCode }),
      });
      const result = await response.json().catch(() => ({})) as { code?: string };
      if (response.status === 410) {
        setConnection("ended");
        return;
      }
      if (!response.ok) throw new Error(result.code || "verification_failed");
      setAuthMessage("");
      setAuthCode("");
      setAccessStage("authenticated");
      setConnection("connecting");
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      setAuthError(authFailureMessage(code));
    } finally {
      setAuthBusy(false);
    }
  };

  const signOut = async () => {
    await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/logout`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }).catch(() => undefined);
    setPayload(null);
    setChallengeId("");
    setAuthCode("");
    setAccessStage("email");
    setConnection("connecting");
  };

  useEffect(() => {
    if (!payload || payload.revision === lastRevision.current) return;
    lastRevision.current = payload.revision;
    const container = scrollRef.current;
    if (container) container.scrollTo({ top: 0, behavior: "smooth" });
  }, [payload]);

  const activeRadarItems = useMemo(
    () => radarItems.filter((item) => item.lifecycle_status === "active"),
    [radarItems],
  );
  const radarHistoryItems = useMemo(
    () => radarItems.filter((item) => item.lifecycle_status !== "active").slice().reverse(),
    [radarItems],
  );
  const radarCounts = useMemo(() => ({
    core: activeRadarItems.filter((item) => radarTabCategories.core.includes(item.category)).length,
    decision: activeRadarItems.filter((item) => item.category === "decision").length,
    action: activeRadarItems.filter((item) => item.category === "action_item").length,
    issues: activeRadarItems.filter((item) => radarTabCategories.issues.includes(item.category)).length,
  }), [activeRadarItems]);

  const visibleRadarItems = useMemo(
    () => activeRadarItems.filter((item) => radarTabCategories[radarTab].includes(item.category)),
    [activeRadarItems, radarTab],
  );

  useEffect(() => {
    const nextIds = new Set(activeRadarItems.map((item) => item.item_id));
    if (!radarInitializedRef.current) {
      radarKnownIdsRef.current = nextIds;
      radarInitializedRef.current = true;
    } else {
      const added = activeRadarItems.filter((item) => !radarKnownIdsRef.current.has(item.item_id));
      if (added.length) {
        setRadarUnread((current) => {
          const next = { ...current };
          added.forEach((item) => {
            tabsForRadarCategory(item.category).forEach((tab) => {
              if (tab !== radarTab || !radarPinnedRef.current) next[tab] += 1;
            });
          });
          return next;
        });
      }
      radarKnownIdsRef.current = nextIds;
    }
    if (radarPinnedRef.current) {
      window.requestAnimationFrame(() => {
        const container = radarScrollRef.current;
        if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      });
    }
  }, [activeRadarItems, radarTab]);

  const chooseLanguage = (next: Language) => {
    setLanguage(next);
    window.localStorage.setItem("mlt-viewer-language", next);
  };

  const chooseRadarTab = (next: RadarTab) => {
    setRadarTab(next);
    setRadarUnread((current) => ({ ...current, [next]: 0 }));
    radarPinnedRef.current = true;
    window.requestAnimationFrame(() => {
      const container = radarScrollRef.current;
      if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    });
  };

  const handleRadarScroll = () => {
    const container = radarScrollRef.current;
    if (!container) return;
    const atLatest = container.scrollHeight - container.scrollTop - container.clientHeight <= 36;
    radarPinnedRef.current = atLatest;
    if (atLatest && radarUnread[radarTab]) {
      setRadarUnread((current) => ({ ...current, [radarTab]: 0 }));
    }
  };

  const jumpToLatestRadar = () => {
    radarPinnedRef.current = true;
    setRadarUnread((current) => ({ ...current, [radarTab]: 0 }));
    const container = radarScrollRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  };

  const jumpToEvidence = (segmentId: string) => {
    const target = document.getElementById(`segment-${segmentId}`);
    if (!target) {
      setEvidenceNotice(labels.evidenceUnavailable);
      return;
    }
    setEvidenceNotice("");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("evidence-highlight");
    window.requestAnimationFrame(() => target.classList.add("evidence-highlight"));
  };

  const connectionLabel = connection === "live"
    ? labels.live
    : connection === "ended"
      ? labels.ended
      : connection === "missing"
        ? labels.unavailable
        : labels.reconnecting;

  if (connection === "ended" || connection === "missing") {
    return (
      <main className="viewer-ended" data-testid="room-ended">
        <div className="ended-mark" aria-hidden="true">×</div>
        <p className="viewer-eyebrow">VERBARADAR</p>
        <h1>{connectionLabel}</h1>
        <p>{labels.expired}</p>
        <div className="privacy-chip">{labels.retention}</div>
      </main>
    );
  }

  if (accessStage !== "authenticated") {
    return (
      <main className="viewer-access" data-testid="viewer-access-gate">
        <section className="access-card" aria-busy={authBusy}>
          <header className="access-header">
            <div className="viewer-brand">
              <span className="brand-signal verbaradar-mark" aria-hidden="true" />
              <div><p>VERBARADAR</p><h1>Secure shared meeting</h1></div>
            </div>
            <div className="language-toggle" aria-label="Language">
              <button type="button" className={language === "ko" ? "active" : ""} onClick={() => chooseLanguage("ko")}>한국어</button>
              <button type="button" className={language === "en" ? "active" : ""} onClick={() => chooseLanguage("en")}>English</button>
            </div>
          </header>
          <div className="access-lock" aria-hidden="true">✦</div>
          <p className="viewer-eyebrow">EMAIL · ONE-TIME CODE</p>
          <h2>{labels.accessTitle}</h2>
          <p className="access-lead">{labels.accessLead}</p>
          {accessStage === "checking" ? (
            <div className="access-checking"><i />{language === "ko" ? "초대 링크 확인 중…" : "Checking invite…"}</div>
          ) : accessStage === "email" ? (
            <form className="access-form" onSubmit={requestVerificationCode}>
              <label htmlFor="viewer-email">{labels.emailLabel}</label>
              <input
                id="viewer-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                maxLength={254}
                value={authEmail}
                placeholder={labels.emailPlaceholder}
                onChange={(event) => setAuthEmail(event.target.value)}
              />
              <button type="submit" disabled={authBusy || !emailDeliveryConfigured}>
                {authBusy ? labels.sending : labels.sendCode}
              </button>
            </form>
          ) : (
            <form className="access-form" onSubmit={verifyAccessCode}>
              <div className="access-email-row"><span>{authEmail}</span><button type="button" onClick={() => { setAccessStage("email"); setAuthError(""); setAuthMessage(""); }}>{labels.changeEmail}</button></div>
              <label htmlFor="viewer-code">{labels.codeLabel}</label>
              <input
                id="viewer-code"
                className="access-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={authCode}
                placeholder={labels.codePlaceholder}
                onChange={(event) => setAuthCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              />
              <button type="submit" disabled={authBusy || authCode.length !== 6}>
                {authBusy ? labels.verifying : labels.verifyCode}
              </button>
              <button className="access-secondary" type="button" disabled={authBusy} onClick={() => void requestVerificationCode()}>{labels.resendCode}</button>
            </form>
          )}
          {!emailDeliveryConfigured && <p className="access-error" role="alert">{labels.deliveryUnavailable}</p>}
          {authMessage && <p className="access-message" role="status">{authMessage}</p>}
          {authError && <p className="access-error" role="alert">{authError}</p>}
          <aside className="access-privacy"><strong>{labels.contentPrivacy}</strong><span>{labels.accessPrivacy}</span></aside>
        </section>
      </main>
    );
  }

  return (
    <main className="viewer-shell" data-testid="viewer-room">
      <header className="viewer-header">
        <div className="viewer-brand">
          <span className="brand-signal verbaradar-mark" aria-hidden="true" />
          <div><p>VERBARADAR</p><h1>Shared meeting view</h1></div>
        </div>
        <div className="viewer-header-actions">
          <div className="language-toggle" aria-label="Language">
            <button className={language === "ko" ? "active" : ""} onClick={() => chooseLanguage("ko")}>한국어</button>
            <button className={language === "en" ? "active" : ""} onClick={() => chooseLanguage("en")}>English</button>
          </div>
          <button className="viewer-sign-out" type="button" onClick={() => void signOut()}>{labels.signOut}</button>
          <span className={`connection-pill ${connection}`}><i />{connectionLabel}</span>
        </div>
      </header>

      <aside className="privacy-strip">
        <span>{labels.privacy}</span>
        <strong>{labels.retention}</strong>
      </aside>

      <div className="viewer-grid">
        <section className="viewer-panel caption-viewer" aria-labelledby="captions-title">
          <div className="viewer-section-heading">
            <div><p>LIVE · CAPTIONS</p><h2 id="captions-title">{labels.captions}</h2></div>
            <div className="view-mode" aria-label="Caption view">
              <button className={viewMode === "both" ? "active" : ""} onClick={() => setViewMode("both")}>{labels.both}</button>
              <button className={viewMode === "translation" ? "active" : ""} onClick={() => setViewMode("translation")}>{labels.translation}</button>
            </div>
          </div>

          <div className={`viewer-partial ${payload?.state.partial ? "active" : ""}`}>
            <div><span><i />{labels.interim}</span><em>{payload?.state.partial?.language?.toUpperCase() ?? "—"}</em></div>
            <p>{payload?.state.partial?.text ?? labels.waiting}</p>
          </div>

          <div className="viewer-transcript-scroll" ref={scrollRef}>
            {captionSegments.length === 0 ? (
              <div className="viewer-empty"><span className="empty-wave"><i /><i /><i /><i /><i /></span><p>{labels.waiting}</p></div>
            ) : (
              <ol className="viewer-transcripts">
                {captionSegments.map((segment) => (
                  <li key={segment.segment_id} id={`segment-${segment.segment_id}`} className="viewer-segment">
                    <div className="segment-meta"><time>{displayTime(segment.ended_at ?? segment.timestamp)}</time><span>{segment.language.toUpperCase()}</span></div>
                    {viewMode === "both" && <p className="viewer-original">{segment.original_text}</p>}
                    <div className={`viewer-translation ${segment.translation_status}`}>
                      <small>{segment.translation_status === "success" ? "TRANSLATION" : segment.translation_status.toUpperCase()}</small>
                      <p>{segment.translated_text || (segment.translation_status === "error" ? labels.translationError : labels.translationWaiting)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <section className="viewer-panel radar-viewer" aria-labelledby="radar-title">
          <div className="viewer-section-heading">
            <div><p>LIVE · EVIDENCE-LINKED</p><h2 id="radar-title">{labels.radar}</h2></div>
            <span className={`radar-pill ${payload?.state.radar.status ?? "disabled"}`}>{payload?.state.radar.status ?? "—"}</span>
          </div>
          {connection === "reconnecting" && <p className="radar-advisory">{labels.presenterOffline}</p>}
          {payload?.state.radar.status === "error" && <p className="radar-advisory danger">{labels.radarDelayed}</p>}
          {evidenceNotice && <p className="radar-advisory">{evidenceNotice}</p>}
          <nav className="radar-tabs" aria-label="Radar views">
            {(["core", "decision", "action", "issues"] as RadarTab[]).map((tab) => {
              const title = tab === "core" ? labels.core : tab === "decision" ? labels.decisions : tab === "action" ? labels.actions : labels.issues;
              return <button key={tab} className={radarTab === tab ? "active" : ""} data-unread={radarUnread[tab] > 0} onClick={() => chooseRadarTab(tab)}><span>{title}</span><strong>{radarCounts[tab]}</strong><i aria-hidden="true" /></button>;
            })}
          </nav>
          {radarUnread[radarTab] > 0 && <button className="radar-latest" onClick={jumpToLatestRadar}>{radarUnread[radarTab]} {labels.newItems} · {labels.latest}</button>}
          <div className="radar-scroll" ref={radarScrollRef} onScroll={handleRadarScroll}>
            {visibleRadarItems.length === 0 ? (
              <div className="radar-empty"><span>⌁</span><p>{labels.noRadar}</p></div>
            ) : visibleRadarItems.map((item) => {
              const categoryTitle = item.category === "decision" ? labels.decisions : item.category === "action_item" ? labels.actions : item.category === "open_question" ? labels.questions : labels.confirmations;
              return <article className="radar-item" key={item.item_id}>
                <div className="radar-item-top"><span>{item.review_status === "approved" ? labels.approved : labels.suggested}</span><em>{categoryTitle}</em></div>
                <p>{item.text}</p>
                {(item.assignee || item.due_date) && <dl>
                  {item.assignee && <div><dt>{labels.assignee}</dt><dd>{item.assignee}</dd></div>}
                  {item.due_date && <div><dt>{labels.due}</dt><dd>{item.due_date}</dd></div>}
                </dl>}
                <div className="evidence-links">
                  {item.evidence_segment_ids.map((segmentId, index) => <button key={segmentId} onClick={() => jumpToEvidence(segmentId)}>{labels.evidence} {index + 1}</button>)}
                </div>
              </article>;
            })}
            {radarHistoryItems.length > 0 && <details className="radar-history">
              <summary>{language === "ko" ? "변경 기록" : "Change history"} <strong>{radarHistoryItems.length}</strong></summary>
              {radarHistoryItems.map((item) => <article className="radar-item historical" key={item.item_id}>
                <div className="radar-item-top"><span>{language === "ko" ? ({ superseded: "대체됨", resolved: "해결됨", retracted: "철회됨" }[item.lifecycle_status] ?? "변경됨") : item.lifecycle_status}</span></div>
                <p>{item.text}</p>
                {item.lifecycle_reason && <small>{item.lifecycle_reason}</small>}
                <div className="evidence-links">
                  {item.evidence_segment_ids.map((segmentId, index) => <button key={segmentId} onClick={() => jumpToEvidence(segmentId)}>{labels.evidence} {index + 1}</button>)}
                </div>
              </article>)}
            </details>}
          </div>
        </section>
      </div>
    </main>
  );
}
