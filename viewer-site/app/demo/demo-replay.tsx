"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import fixtureData from "../../public/demo/verified-session.json";
import {
  clampReplayTime,
  evidenceTargetId,
  snapshotAt,
  type ReplayFixture,
  type ReplayRadarItem,
} from "../../lib/replay-model.mjs";

type Language = "en" | "ko";
type RadarTab = "core" | "decision" | "action" | "issues";
type ViewMode = "both" | "translation";

const fixture = fixtureData as ReplayFixture & typeof fixtureData;

const languageNames = {
  en: { ja: "Japanese", en: "English", ko: "Korean" },
  ko: { ja: "일본어", en: "영어", ko: "한국어" },
} as const;

const copy = {
  en: {
    replay: "Verified API Replay",
    realRun: "REAL API RUN · NO KEY REQUIRED",
    title: fixture.title.en,
    disclosure: fixture.disclosure.en,
    privacy: "Includes a consented scripted demo recording. No private meeting audio, API keys, local paths, or original session identifiers are included.",
    captions: "Original → context → translation",
    radar: "Evidence-linked Decision Radar",
    both: "Original + translation",
    translation: "Translation only",
    waiting: "Waiting for the first finalized caption…",
    translationWaiting: "Gemini translation pending…",
    context: "APPROVED CONTEXT CORRECTION",
    play: "Play",
    pause: "Pause",
    restart: "Restart",
    speed: "Speed",
    audio: "Scripted demo audio",
    mute: "Mute",
    unmute: "Unmute",
    volume: "Audio volume",
    audioError: "Audio could not be played in this browser.",
    core: "Key items",
    decisions: "Decisions",
    actions: "Actions",
    issues: "Open",
    noRadar: "Radar items will appear as the real analysis completes.",
    suggested: "Suggested",
    assignee: "Owner",
    due: "Due",
    evidence: "Evidence",
    median: "Median translation",
    upper: "95th percentile",
    verified: "Evidence links verified",
    original: `ORIGINAL · ${fixture.source.language.toUpperCase()}`,
    translated: `TRANSLATION · ${fixture.source.target_language.toUpperCase()}`,
    back: "Overview",
  },
  ko: {
    replay: "검증된 API Replay",
    realRun: "실제 API 실행 · 키 불필요",
    title: fixture.title.ko,
    disclosure: fixture.disclosure.ko,
    privacy: "동의받은 대본 녹음을 포함합니다. 비공개 회의 음성·API 키·내부 경로·원래 세션 식별자는 포함하지 않습니다.",
    captions: "원문 → 문맥 보정 → 번역",
    radar: "근거 연결형 Decision Radar",
    both: "원문 + 번역",
    translation: "번역만",
    waiting: "첫 확정 자막을 기다리는 중입니다…",
    translationWaiting: "Gemini 번역 대기 중…",
    context: "승인된 문맥 보정",
    play: "재생",
    pause: "일시정지",
    restart: "처음부터",
    speed: "속도",
    audio: "데모 대본 음성",
    mute: "음소거",
    unmute: "소리 켜기",
    volume: "오디오 음량",
    audioError: "이 브라우저에서 오디오를 재생할 수 없습니다.",
    core: "핵심",
    decisions: "결정",
    actions: "Action",
    issues: "미해결",
    noRadar: "실제 분석이 완료된 시점에 Radar 항목이 표시됩니다.",
    suggested: "제안",
    assignee: "담당",
    due: "기한",
    evidence: "근거",
    median: "번역 중앙값",
    upper: "상위 95%",
    verified: "근거 링크 검증",
    original: `원문 · ${languageNames.ko[fixture.source.language]}`,
    translated: `번역 · ${languageNames.ko[fixture.source.target_language]}`,
    back: "소개",
  },
} as const;

const tabCategories: Record<RadarTab, ReplayRadarItem["category"][]> = {
  core: ["decision", "action_item"],
  decision: ["decision"],
  action: ["action_item"],
  issues: ["open_question", "needs_confirmation"],
};

function formatClock(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1_000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function DemoReplay() {
  const [language, setLanguage] = useState<Language>("en");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2>(1);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(0.85);
  const [audioError, setAudioError] = useState(false);
  const [radarTab, setRadarTab] = useState<RadarTab>("core");
  const [viewMode, setViewMode] = useState<ViewMode>("both");
  const lastTickRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const captionScrollRef = useRef<HTMLDivElement>(null);
  const radarScrollRef = useRef<HTMLDivElement>(null);
  const labels = copy[language];
  const state = useMemo(() => snapshotAt(fixture, elapsedMs), [elapsedMs]);
  const latestSegments = useMemo(() => [...state.segments].reverse(), [state.segments]);
  const activeRadarItems = useMemo(
    () => state.radarItems.filter((item) => item.lifecycle_status === "active"),
    [state.radarItems],
  );
  const visibleRadarItems = useMemo(
    () => activeRadarItems.filter((item) => tabCategories[radarTab].includes(item.category)).reverse(),
    [activeRadarItems, radarTab],
  );
  const radarCounts = useMemo(() => ({
    core: activeRadarItems.filter((item) => tabCategories.core.includes(item.category)).length,
    decision: activeRadarItems.filter((item) => item.category === "decision").length,
    action: activeRadarItems.filter((item) => item.category === "action_item").length,
    issues: activeRadarItems.filter((item) => tabCategories.issues.includes(item.category)).length,
  }), [activeRadarItems]);

  useEffect(() => {
    if (!playing) return;
    lastTickRef.current = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = (now - lastTickRef.current) * speed;
      lastTickRef.current = now;
      setElapsedMs((current) => {
        const audio = audioRef.current;
        if (fixture.audio && audio && current < fixture.audio.duration_ms && !audio.ended) {
          if (audio.paused) return current;
          return clampReplayTime(fixture, audio.currentTime * 1_000);
        }
        const next = clampReplayTime(fixture, current + delta);
        if (next >= fixture.duration_ms) window.setTimeout(() => setPlaying(false), 0);
        return next;
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, speed]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = speed;
    audio.volume = volume;
    audio.muted = muted;
  }, [muted, speed, volume]);

  useEffect(() => {
    captionScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [state.segments.length]);

  useEffect(() => {
    radarScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [state.radarItems.length, radarTab]);

  const startPlayback = async (positionMs: number) => {
    const position = clampReplayTime(fixture, positionMs);
    setElapsedMs(position);
    const audio = audioRef.current;
    if (fixture.audio && audio && position < fixture.audio.duration_ms) {
      audio.currentTime = position / 1_000;
      audio.playbackRate = speed;
      try {
        await audio.play();
        setAudioError(false);
      } catch {
        setAudioError(true);
        setPlaying(false);
        return;
      }
    }
    lastTickRef.current = performance.now();
    setPlaying(true);
  };

  const togglePlayback = () => {
    if (playing) {
      audioRef.current?.pause();
      setPlaying(false);
      return;
    }
    void startPlayback(elapsedMs >= fixture.duration_ms ? 0 : elapsedMs);
  };

  const restart = () => {
    setRadarTab("core");
    if (audioRef.current) audioRef.current.currentTime = 0;
    void startPlayback(0);
  };

  const seekTo = (positionMs: number) => {
    const position = clampReplayTime(fixture, positionMs);
    setElapsedMs(position);
    const audio = audioRef.current;
    if (!fixture.audio || !audio) return;
    if (position < fixture.audio.duration_ms) {
      audio.currentTime = position / 1_000;
      if (playing) void audio.play().catch(() => {
        setAudioError(true);
        setPlaying(false);
      });
    } else {
      audio.pause();
    }
    lastTickRef.current = performance.now();
  };

  const changeSpeed = (nextSpeed: 1 | 2) => {
    if (audioRef.current) audioRef.current.playbackRate = nextSpeed;
    setSpeed(nextSpeed);
  };

  const jumpToEvidence = (segmentId: string) => {
    const target = document.getElementById(evidenceTargetId(segmentId));
    if (!target) return;
    setViewMode("both");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("evidence-highlight");
    window.requestAnimationFrame(() => target.classList.add("evidence-highlight"));
  };

  const tabTitle = (tab: RadarTab) => tab === "core"
    ? labels.core
    : tab === "decision"
      ? labels.decisions
      : tab === "action"
        ? labels.actions
        : labels.issues;

  return (
    <main className="demo-shell" data-testid="verified-replay">
      <header className="demo-header">
        <div className="viewer-brand">
          <span className="brand-signal whykaigi-mark" aria-hidden="true" />
          <div><p>WHYKAIGI</p><h1>{labels.replay}</h1></div>
        </div>
        <div className="demo-header-actions">
          <Link className="demo-back" href="/">← {labels.back}</Link>
          <div className="language-toggle" aria-label="Language">
            <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>English</button>
            <button className={language === "ko" ? "active" : ""} onClick={() => setLanguage("ko")}>한국어</button>
          </div>
        </div>
      </header>

      <section className="demo-intro">
        <div>
          <p className="demo-kicker"><i />{labels.realRun}</p>
          <h2>{labels.title}</h2>
          <p>{labels.disclosure}</p>
        </div>
        <div className="demo-metrics" aria-label="Measured replay metrics">
          <article><strong>{fixture.metrics.translation_latency_ms.median}ms</strong><span>{labels.median}</span></article>
          <article><strong>{fixture.metrics.translation_latency_ms.p95_nearest}ms</strong><span>{labels.upper}</span></article>
          <article><strong>{fixture.metrics.evidence_references}/{fixture.metrics.evidence_references}</strong><span>{labels.verified}</span></article>
        </div>
      </section>

      <section className="pipeline-strip" aria-label="API pipeline">
        {fixture.pipeline.map((item, index) => <article key={item.stage}>
          <span>{index + 1}</span><div><small>{item.stage}</small><strong>{item.model}</strong></div>
        </article>)}
      </section>

      <section className="replay-controls" aria-label="Replay controls">
        {fixture.audio && <audio
          ref={audioRef}
          className="demo-audio"
          src={fixture.audio.url}
          preload="metadata"
          onTimeUpdate={(event) => {
            if (!event.currentTarget.ended) {
              setElapsedMs(clampReplayTime(fixture, event.currentTarget.currentTime * 1_000));
            }
          }}
          onEnded={() => {
            setElapsedMs(fixture.audio?.duration_ms ?? fixture.duration_ms);
            lastTickRef.current = performance.now();
          }}
          onError={() => {
            setAudioError(true);
            setPlaying(false);
          }}
        />}
        <button className="replay-primary" onClick={togglePlayback}>{playing ? "Ⅱ" : "▶"}<span>{playing ? labels.pause : labels.play}</span></button>
        <button onClick={restart}>↺ <span>{labels.restart}</span></button>
        <div className="replay-progress">
          <input
            aria-label="Replay position"
            type="range"
            min="0"
            max={fixture.duration_ms}
            step="100"
            value={Math.round(elapsedMs)}
            onChange={(event) => seekTo(Number(event.target.value))}
          />
          <time>{formatClock(elapsedMs)} / {formatClock(fixture.duration_ms)}</time>
        </div>
        <div className="speed-toggle" aria-label={labels.speed}>
          <button className={speed === 1 ? "active" : ""} onClick={() => changeSpeed(1)}>1×</button>
          <button className={speed === 2 ? "active" : ""} onClick={() => changeSpeed(2)}>2×</button>
        </div>
        {fixture.audio && <div className="audio-volume">
          <span>♪ {labels.audio}</span>
          <button aria-label={muted ? labels.unmute : labels.mute} onClick={() => setMuted((current) => !current)}>{muted ? "×" : "◖"}</button>
          <input
            aria-label={labels.volume}
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={muted ? 0 : volume}
            onChange={(event) => {
              const nextVolume = Number(event.target.value);
              setVolume(nextVolume);
              setMuted(nextVolume === 0);
            }}
          />
        </div>}
      </section>

      {audioError && <p className="audio-error" role="alert">{labels.audioError}</p>}

      <aside className="demo-privacy">{labels.privacy}</aside>

      <div className="viewer-grid demo-grid">
        <section className="viewer-panel caption-viewer" aria-labelledby="demo-caption-title">
          <div className="viewer-section-heading">
            <div><p>REPLAY · VERIFIED EVENTS</p><h2 id="demo-caption-title">{labels.captions}</h2></div>
            <div className="view-mode" aria-label="Caption view">
              <button className={viewMode === "both" ? "active" : ""} onClick={() => setViewMode("both")}>{labels.both}</button>
              <button className={viewMode === "translation" ? "active" : ""} onClick={() => setViewMode("translation")}>{labels.translation}</button>
            </div>
          </div>
          <div className="viewer-transcript-scroll demo-transcript-scroll" ref={captionScrollRef}>
            {latestSegments.length === 0 ? <div className="viewer-empty"><span className="empty-wave"><i /><i /><i /><i /><i /></span><p>{labels.waiting}</p></div> : (
              <ol className="viewer-transcripts">
                {latestSegments.map((segment) => <li key={segment.segment_id} id={evidenceTargetId(segment.segment_id)} className="viewer-segment replay-segment">
                  {viewMode === "both" && <>
                    <div className="segment-meta"><span>{labels.original}</span><time>{formatClock(segment.final_at_ms)}</time></div>
                    <p className="viewer-original">{segment.original_text}</p>
                    {segment.context_changed && <div className="context-correction">
                      <small>{labels.context}</small><p>{segment.normalized_text}</p>
                      <div>{segment.context_matches.map((match) => <span key={`${match.from}-${match.to}`}>{match.from} → <strong>{match.to}</strong></span>)}</div>
                    </div>}
                  </>}
                  <div className={`viewer-translation ${segment.translation_status}`}>
                    <small>{labels.translated}{segment.translation_latency_ms ? ` · ${segment.translation_latency_ms}ms` : ""}</small>
                    <p>{segment.translated_text || labels.translationWaiting}</p>
                  </div>
                </li>)}
              </ol>
            )}
          </div>
        </section>

        <section className="viewer-panel radar-viewer" aria-labelledby="demo-radar-title">
          <div className="viewer-section-heading">
            <div><p>GPT-5.6 LUNA · EVIDENCE-LINKED</p><h2 id="demo-radar-title">{labels.radar}</h2></div>
            <span className="radar-pill ready">Replay</span>
          </div>
          <nav className="radar-tabs" aria-label="Radar views">
            {(["core", "decision", "action", "issues"] as RadarTab[]).map((tab) => <button key={tab} className={radarTab === tab ? "active" : ""} onClick={() => setRadarTab(tab)}><span>{tabTitle(tab)}</span><strong>{radarCounts[tab]}</strong><i aria-hidden="true" /></button>)}
          </nav>
          <div className="radar-scroll demo-radar-scroll" ref={radarScrollRef}>
            {visibleRadarItems.length === 0 ? <div className="radar-empty"><span>⌁</span><p>{labels.noRadar}</p></div> : visibleRadarItems.map((item) => {
              const category = item.category === "decision" ? labels.decisions : item.category === "action_item" ? labels.actions : labels.issues;
              return <article className="radar-item" key={item.item_id}>
                <div className="radar-item-top"><span>{labels.suggested}</span><em>{category}</em></div>
                <p>{item.text}</p>
                {(item.assignee || item.due_date) && <dl>
                  {item.assignee && <div><dt>{labels.assignee}</dt><dd>{item.assignee}</dd></div>}
                  {item.due_date && <div><dt>{labels.due}</dt><dd>{item.due_date}</dd></div>}
                </dl>}
                <div className="evidence-links">{item.evidence_segment_ids.map((segmentId, index) => <button key={segmentId} onClick={() => jumpToEvidence(segmentId)}>{labels.evidence} {index + 1}</button>)}</div>
              </article>;
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
