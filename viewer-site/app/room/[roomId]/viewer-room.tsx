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
  }, [roomId]);

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
        <p className="viewer-eyebrow">MEETING LIVE TRANSLATOR</p>
        <h1>{connectionLabel}</h1>
        <p>{labels.expired}</p>
        <div className="privacy-chip">{labels.retention}</div>
      </main>
    );
  }

  return (
    <main className="viewer-shell" data-testid="viewer-room">
      <header className="viewer-header">
        <div className="viewer-brand">
          <span className="brand-signal" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          <div><p>MEETING LIVE TRANSLATOR</p><h1>Shared meeting view</h1></div>
        </div>
        <div className="viewer-header-actions">
          <div className="language-toggle" aria-label="Language">
            <button className={language === "ko" ? "active" : ""} onClick={() => chooseLanguage("ko")}>한국어</button>
            <button className={language === "en" ? "active" : ""} onClick={() => chooseLanguage("en")}>English</button>
          </div>
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
