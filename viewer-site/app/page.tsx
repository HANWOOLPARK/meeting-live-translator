import Link from "next/link";

export default function Home() {
  return (
    <main className="landing-shell" data-testid="viewer-home">
      <div className="landing-orb landing-orb-one" />
      <div className="landing-orb landing-orb-two" />
      <section className="landing-card">
        <div className="brand-lockup">
          <span className="brand-signal whykaigi-mark" aria-hidden="true" />
          <span>WHYKAIGI</span>
        </div>
        <p className="landing-kicker">LIVE TRANSLATION · EVIDENCE-LINKED DECISIONS</p>
        <h1>Understand the meeting.<br /><em>Verify every decision.</em></h1>
        <p className="landing-lead">
          Preserve the original words, apply only approved context, translate in real time,
          and connect every decision or action back to the exact transcript evidence.
        </p>
        <div className="landing-actions">
          <Link className="landing-primary" href="/demo">Open verified API Replay <span>→</span></Link>
          <span>No login or API key required</span>
        </div>
        <div className="landing-features">
          <article><strong>Preserve</strong><span>Original captions remain available before and after deterministic context correction.</span></article>
          <article><strong>Translate</strong><span>Gemini translation is isolated so provider delays never block the original transcript.</span></article>
          <article><strong>Verify</strong><span>GPT-5.6 Luna Decision Radar links decisions, actions, and questions to exact source segments.</span></article>
        </div>
        <div className="landing-privacy">
          The public Replay contains a fictional meeting recorded through the real API pipeline.
          It includes a consented scripted demo recording, but no private meeting audio, API keys,
          local paths, or original session identifiers.
        </div>
        <p className="landing-help">초대 링크로 실시간 공유 화면도 설치 없이 볼 수 있습니다. · Live rooms require a host invite link.</p>
      </section>
    </main>
  );
}
