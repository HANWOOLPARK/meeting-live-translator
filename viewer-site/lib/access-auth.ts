import { env } from "cloudflare:workers";
import {
  VIEWER_SESSION_COOKIE,
  cookieValue,
  hmacHex,
  normalizeEmail,
} from "./access-auth-core";
import {
  createSecret,
  database,
  hashToken,
  randomToken,
  type RoomRow,
} from "./relay";

export const OTP_TTL_SECONDS = 10 * 60;
export const OTP_RESEND_SECONDS = 45;
export const OTP_MAX_ATTEMPTS = 5;
export const OTP_CHALLENGE_RETENTION_SECONDS = 24 * 60 * 60;
export const VIEWER_SESSION_TOUCH_SECONDS = 20;
export const ACCESS_LOG_RETENTION_DAYS = 30;
const ACCESS_LOG_RETENTION_MS = ACCESS_LOG_RETENTION_DAYS * 24 * 60 * 60 * 1_000;

type RuntimeEnv = typeof env & {
  RESEND_API_KEY?: string;
  MLT_OTP_FROM_EMAIL?: string;
  MLT_OTP_SIGNING_SECRET?: string;
};

export type ViewerSessionRow = {
  session_token_hash: string;
  room_id: string;
  email: string;
  created_at: number;
  expires_at: number;
  last_seen_at: number;
  view_started_at: number | null;
  view_count: number;
  revoked_at: number | null;
  retain_until: number;
};

export type AccessLogRow = {
  event_id: string;
  room_id: string;
  email: string;
  event_type: string;
  occurred_at: number;
  ip_hash: string;
  detail_code: string;
  retain_until: number;
};

function runtime() {
  return env as RuntimeEnv;
}

export function otpSigningSecret() {
  return (runtime().MLT_OTP_SIGNING_SECRET ?? createSecret()).trim();
}

export function emailDeliveryConfigured() {
  const signingSecret = otpSigningSecret();
  const from = (runtime().MLT_OTP_FROM_EMAIL ?? "").trim();
  const bracketed = from.match(/<([^<>]+)>\s*$/)?.[1] ?? from;
  return Boolean(
    (runtime().RESEND_API_KEY ?? "").trim()
      && normalizeEmail(bracketed)
      && signingSecret.length >= 32,
  );
}

export async function requestIpHash(request: Request) {
  const rawIp = (request.headers.get("cf-connecting-ip") ?? "unknown").trim().slice(0, 128);
  return hmacHex(otpSigningSecret(), `mlt-ip-v1\n${rawIp}`);
}

export async function writeAccessLog(
  roomId: string,
  email: string,
  eventType: string,
  request: Request,
  detailCode = "",
) {
  const now = Date.now();
  await database()
    .prepare(
      "INSERT INTO share_access_logs (event_id, room_id, email, event_type, occurred_at, ip_hash, detail_code, retain_until) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(
      randomToken(18),
      roomId,
      email.slice(0, 254),
      eventType.slice(0, 40),
      now,
      await requestIpHash(request),
      detailCode.slice(0, 80),
      now + ACCESS_LOG_RETENTION_MS,
    )
    .run();
}

export async function cleanupAccessRecords() {
  const now = Date.now();
  const db = database();
  await db.batch([
    db.prepare("DELETE FROM share_access_challenges WHERE retain_until <= ?").bind(now),
    db.prepare("DELETE FROM share_viewer_sessions WHERE retain_until <= ?").bind(now),
    db.prepare("DELETE FROM share_access_logs WHERE retain_until <= ?").bind(now),
  ]);
}

export async function sendVerificationEmail(email: string, code: string, challengeId: string) {
  const apiKey = (runtime().RESEND_API_KEY ?? "").trim();
  const from = (runtime().MLT_OTP_FROM_EMAIL ?? "").trim();
  if (!apiKey || !from) throw new Error("email_delivery_unconfigured");
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `mlt-otp-${challengeId}`,
    },
    body: JSON.stringify({
      from,
      to: [email],
      subject: "WhyKaigi verification code",
      text: `Your verification code is ${code}. It expires in 10 minutes. If you did not request this code, ignore this email.`,
      html: `<div style="font-family:Arial,sans-serif;line-height:1.6;color:#12202f"><h2 style="margin:0 0 16px">WhyKaigi</h2><p>Enter this code to open the shared meeting view.</p><p style="font-size:32px;font-weight:700;letter-spacing:8px;margin:20px 0">${code}</p><p style="color:#5d6978">This code expires in 10 minutes. If you did not request it, ignore this email.</p></div>`,
      tags: [{ name: "category", value: "viewer_otp" }],
    }),
  });
  if (!response.ok) {
    throw new Error(`email_delivery_failed_${response.status}`);
  }
}

export async function authorizeViewer(request: Request, roomId: string) {
  const token = cookieValue(request, VIEWER_SESSION_COOKIE);
  if (!token) return null;
  const now = Date.now();
  const session = await database()
    .prepare(
      "SELECT * FROM share_viewer_sessions WHERE session_token_hash = ? AND room_id = ? AND revoked_at IS NULL AND expires_at > ? LIMIT 1",
    )
    .bind(await hashToken(token), roomId, now)
    .first<ViewerSessionRow>();
  return session ?? null;
}

export async function touchViewerSession(
  request: Request,
  session: ViewerSessionRow,
) {
  const now = Date.now();
  if (session.view_started_at === null) {
    const entered = await database()
      .prepare(
        "UPDATE share_viewer_sessions SET last_seen_at = ?, view_started_at = ?, view_count = view_count + 1 WHERE session_token_hash = ? AND revoked_at IS NULL AND view_started_at IS NULL RETURNING session_token_hash",
      )
      .bind(now, now, session.session_token_hash)
      .first<{ session_token_hash: string }>();
    if (entered) {
      await writeAccessLog(session.room_id, session.email, "viewer_entered", request);
      return;
    }
  }
  if (now - session.last_seen_at < VIEWER_SESSION_TOUCH_SECONDS * 1_000) return;
  await database()
    .prepare(
      "UPDATE share_viewer_sessions SET last_seen_at = ?, view_started_at = COALESCE(view_started_at, ?), view_count = view_count + 1 WHERE session_token_hash = ? AND revoked_at IS NULL",
    )
    .bind(now, now, session.session_token_hash)
    .run();
}

export async function revokeViewerSession(request: Request, roomId: string) {
  const session = await authorizeViewer(request, roomId);
  if (!session) return;
  const now = Date.now();
  await database()
    .prepare("UPDATE share_viewer_sessions SET revoked_at = ?, last_seen_at = ? WHERE session_token_hash = ?")
    .bind(now, now, session.session_token_hash)
    .run();
  await writeAccessLog(roomId, session.email, "signed_out", request);
}

export async function revokeRoomSessions(roomId: string) {
  const now = Date.now();
  await database()
    .prepare("UPDATE share_viewer_sessions SET revoked_at = COALESCE(revoked_at, ?), last_seen_at = ? WHERE room_id = ?")
    .bind(now, now, roomId)
    .run();
}

export async function hostAccessSnapshot(room: RoomRow) {
  const db = database();
  const now = Date.now();
  const [attendeesResult, eventsResult] = await Promise.all([
    db.prepare(
      `SELECT email,
        MIN(created_at) AS first_verified_at,
        MAX(last_seen_at) AS last_seen_at,
        SUM(view_count) AS view_count,
        MAX(CASE WHEN revoked_at IS NULL AND expires_at > ? AND last_seen_at >= ? THEN 1 ELSE 0 END) AS active
       FROM share_viewer_sessions
       WHERE room_id = ?
       GROUP BY email
       ORDER BY first_verified_at DESC
       LIMIT 200`,
    ).bind(now, now - 60_000, room.room_id).all<{
      email: string;
      first_verified_at: number;
      last_seen_at: number;
      view_count: number;
      active: number;
    }>(),
    db.prepare(
      `SELECT event_id, email, event_type, occurred_at, detail_code
       FROM share_access_logs
       WHERE room_id = ?
       ORDER BY occurred_at DESC
       LIMIT 300`,
    ).bind(room.room_id).all<Pick<AccessLogRow, "event_id" | "email" | "event_type" | "occurred_at" | "detail_code">>(),
  ]);
  const attendees = attendeesResult.results.map((item) => ({
    email: item.email,
    first_verified_at: new Date(item.first_verified_at).toISOString(),
    last_seen_at: new Date(item.last_seen_at).toISOString(),
    view_count: Number(item.view_count) || 0,
    active: room.status === "active" && Boolean(item.active),
  }));
  const events = eventsResult.results.map((item) => ({
    event_id: item.event_id,
    email: item.email,
    event_type: item.event_type,
    occurred_at: new Date(item.occurred_at).toISOString(),
    detail_code: item.detail_code,
  }));
  return {
    room_id: room.room_id,
    status: room.status,
    created_at: new Date(room.created_at).toISOString(),
    ended_at: room.ended_at ? new Date(room.ended_at).toISOString() : null,
    retention_days: ACCESS_LOG_RETENTION_DAYS,
    verified_attendee_count: attendees.length,
    attendees,
    events,
    retained_until: new Date(room.created_at + ACCESS_LOG_RETENTION_MS).toISOString(),
  };
}
