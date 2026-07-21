import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";
import {
  evidenceTargetId,
  snapshotAt,
  validateReplayFixture,
} from "../lib/replay-model.mjs";

const templateRoot = new URL("../", import.meta.url);
const previewRoot = new URL("../app/_sites-preview/", import.meta.url);

async function collectFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
    if (entry.isDirectory()) files.push(...await collectFiles(target));
    else files.push(target);
  }
  return files;
}

test("build output and public verified replay landing are present", async () => {
  const [page, layout] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
  ]);
  await access(new URL("../dist/server/index.js", import.meta.url));
  assert.match(page, /Open verified API Replay/);
  assert.match(page, /href="\/demo"/);
  assert.match(page, /Decision Radar/);
  assert.match(page, /data-testid="viewer-home"/);
  assert.match(layout, /WhyKaigi/);
  assert.doesNotMatch(page + layout, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("published bundles contain no local Windows user path", async () => {
  const distRoot = new URL("../dist/", import.meta.url);
  const candidates = (await collectFiles(distRoot)).filter((url) => /\.(?:css|html|js|json|txt)$/i.test(url.pathname));
  for (const candidate of candidates) {
    const content = await readFile(candidate, "utf8");
    assert.doesNotMatch(content, /[A-Z]:[\\/]Users[\\/]/i, `local user path leaked in ${candidate.pathname}`);
  }
});

test("viewer room is read-only and keeps the privacy notice visible", async () => {
  const [page, viewer] = await Promise.all([
    readFile(new URL("../app/room/[roomId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/room/[roomId]/viewer-room.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /ViewerRoom/);
  assert.match(viewer, /data-testid="viewer-room"/);
  assert.match(viewer, /data-testid="viewer-access-gate"/);
  assert.match(viewer, /\/auth\/status/);
  assert.match(viewer, /\/auth\/supabase/);
  assert.match(viewer, /signInWithOAuth/);
  assert.match(viewer, /provider: "google"/);
  assert.match(viewer, /Google.*Supabase/s);
  assert.match(viewer, /30일/);
  assert.match(viewer, /Shared meeting view/);
  assert.match(viewer, /API keys/);
  assert.match(viewer, /RadarTab/);
  assert.match(viewer, /radar-latest/);
  assert.match(viewer, /radarPinnedRef/);
  assert.match(viewer, /captionSegments/);
  assert.match(viewer, /\[\.\.\.\(payload\?\.state\.segments \?\? \[\]\)\]\.reverse\(\)/);
  assert.match(viewer, /scrollTo\(\{ top: 0, behavior: "smooth" \}\)/);
  assert.match(viewer, /open_question", "needs_confirmation/);
  assert.doesNotMatch(viewer, /audio_url|api_key|provider_settings/);
});

test("room state API exchanges a verified Supabase Google identity for a room-scoped session", async () => {
  const [roomRoute, supabaseRoute, supabaseAuth, migration, accessAuth] = await Promise.all([
    readFile(new URL("../app/api/rooms/[roomId]/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/rooms/[roomId]/auth/supabase/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/supabase-auth.ts", import.meta.url), "utf8"),
    readFile(new URL("../supabase/whykaigi_attendee_auth.sql", import.meta.url), "utf8"),
    readFile(new URL("../lib/access-auth.ts", import.meta.url), "utf8"),
  ]);
  assert.match(roomRoute, /authorizeViewer/);
  assert.match(roomRoute, /google_identity_required/);
  assert.match(supabaseRoute, /verifySupabaseGoogleIdentity/);
  assert.match(supabaseRoute, /recordSupabaseRoomAccess/);
  assert.match(supabaseRoute, /Set-Cookie/);
  assert.match(supabaseAuth, /\/auth\/v1\/user/);
  assert.match(supabaseAuth, /email_confirmed_at/);
  assert.match(supabaseAuth, /identityUsesGoogle/);
  assert.match(supabaseAuth, /MLT_ACCESS_SIGNING_SECRET/);
  assert.match(migration, /enable row level security/);
  assert.match(migration, /auth\.uid\(\)/);
  assert.match(migration, /revoke all.*from anon/is);
  assert.match(migration, /interval '30 days'/);
  assert.match(accessAuth, /ACCESS_LOG_RETENTION_DAYS = 30/);
  assert.doesNotMatch(roomRoute + supabaseRoute + supabaseAuth, /RESEND_API_KEY|one-time-code/i);
});

test("removes the disposable starter and keeps relay boundaries explicit", async () => {
  const [page, layout, viewer, relay, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/room/[roomId]/viewer-room.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/relay.ts", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /Live rooms require a host invite link/);
  assert.match(layout, /WhyKaigi/);
  assert.match(viewer, /450/);
  assert.match(viewer, /evidence_segment_ids/);
  assert.match(relay, /MAX_SEGMENTS = 80/);
  assert.match(relay, /pending_translations/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);

  assert.deepEqual(await readdir(previewRoot), []);
  await assert.rejects(access(new URL("public/_sites-preview", templateRoot)));
});

test("public replay fixture is sanitized and schema-valid", async () => {
  const [raw, audio] = await Promise.all([
    readFile(new URL("../public/demo/verified-session.json", import.meta.url), "utf8"),
    readFile(new URL("../public/demo/verified-session-audio.mp3", import.meta.url)),
  ]);
  const fixture = JSON.parse(raw);
  assert.equal(validateReplayFixture(fixture), true);
  assert.equal(fixture.schema_version, 1);
  assert.equal(fixture.replay_id, "build-week-verified-replay");
  assert.equal(fixture.source.audio_retained, false);
  assert.equal(fixture.source.language, "ko");
  assert.equal(fixture.source.target_language, "en");
  assert.equal(fixture.metrics.final_segments, 5);
  assert.equal(fixture.metrics.translated_segments, 5);
  assert.equal(fixture.metrics.evidence_valid, true);
  assert.equal(fixture.metrics.translation_latency_ms.median, 1078);
  assert.equal(fixture.metrics.radar_items, 12);
  assert.equal(fixture.pipeline.at(-1).model, "GPT-5.6 Luna");
  assert.equal(fixture.audio.url, "/demo/verified-session-audio.mp3");
  assert.equal(fixture.audio.duration_ms, 76610);
  assert.equal(createHash("sha256").update(audio).digest("hex"), fixture.audio.sha256);
  assert.doesNotMatch(raw, /\b\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[0-9a-f]{6,}\b|session_id|api_key|host_token|relay_secret/i);
  assert.doesNotMatch(raw, /[A-Z]:\\|\/Users\//);
});

test("replay state advances from recorded events and restarts cleanly", async () => {
  const fixture = JSON.parse(await readFile(new URL("../public/demo/verified-session.json", import.meta.url), "utf8"));
  const initial = snapshotAt(fixture, 0);
  const halfway = snapshotAt(fixture, Math.floor(fixture.duration_ms / 2));
  const completed = snapshotAt(fixture, fixture.duration_ms);
  const restarted = snapshotAt(fixture, 0);
  assert.deepEqual(initial, { segments: [], radarItems: [] });
  assert.ok(halfway.segments.length > 0 && halfway.segments.length < completed.segments.length);
  assert.equal(completed.segments.length, fixture.metrics.final_segments);
  assert.equal(completed.radarItems.length, fixture.metrics.radar_items);
  assert.deepEqual(restarted, initial);
});

test("every replay Radar evidence link resolves to a public transcript target", async () => {
  const fixture = JSON.parse(await readFile(new URL("../public/demo/verified-session.json", import.meta.url), "utf8"));
  const completed = snapshotAt(fixture, fixture.duration_ms);
  const segmentIds = new Set(completed.segments.map((segment) => segment.segment_id));
  const evidence = completed.radarItems.flatMap((item) => item.evidence_segment_ids);
  assert.equal(evidence.length, fixture.metrics.evidence_references);
  for (const segmentId of evidence) {
    assert.equal(segmentIds.has(segmentId), true);
    assert.match(evidenceTargetId(segmentId), /^replay-segment-segment-\d{3}$/);
  }
});

test("demo exposes replay, speed, restart, and evidence navigation controls", async () => {
  const [page, demo] = await Promise.all([
    readFile(new URL("../app/demo/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/demo/demo-replay.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /Verified API Replay/);
  assert.match(demo, /data-testid="verified-replay"/);
  assert.match(demo, /startPlayback\(0\)/);
  assert.match(demo, /changeSpeed\(2\)/);
  assert.match(demo, /type="range"/);
  assert.match(demo, /audioRef/);
  assert.match(demo, /audio\.play\(\)/);
  assert.match(demo, /fixture\.audio\.url/);
  assert.match(demo, /Audio volume/);
  assert.match(demo, /scrollIntoView/);
  assert.match(demo, /evidenceTargetId/);
});
