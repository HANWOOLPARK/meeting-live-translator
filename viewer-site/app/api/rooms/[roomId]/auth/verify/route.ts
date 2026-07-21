import {
  ACCESS_LOG_RETENTION_DAYS,
  otpSigningSecret,
  writeAccessLog,
} from "../../../../../../lib/access-auth";
import {
  constantTimeEqual,
  validVerificationCode,
  verificationCodeHash,
  viewerSessionCookie,
} from "../../../../../../lib/access-auth-core";
import {
  database,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  hashToken,
  jsonResponse,
  parseJsonBody,
  randomToken,
  validRoomId,
} from "../../../../../../lib/relay";

type RouteContext = { params: Promise<{ roomId: string }> };
type ChallengeRow = {
  challenge_id: string;
  room_id: string;
  email: string;
  code_hash: string;
  status: string;
  attempts: number;
  max_attempts: number;
  expires_at: number;
};

export async function POST(request: Request, context: RouteContext) {
  try {
    await ensureSchema();
    const { roomId } = await context.params;
    if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
    const found = await getRoom(roomId);
    if (!found) return jsonResponse({ code: "room_not_found" }, 404);
    const room = await expireIfNeeded(found);
    if (room.status !== "active") return jsonResponse({ code: "room_ended" }, 410);
    const payload = await parseJsonBody(request, 5_000);
    const challengeId = String(payload.challenge_id ?? "").trim();
    const code = validVerificationCode(payload.code);
    if (!/^[A-Za-z0-9_-]{20,64}$/.test(challengeId) || !code) {
      return jsonResponse({ code: "invalid_or_expired_code" }, 400);
    }
    const db = database();
    const challenge = await db
      .prepare("SELECT * FROM share_access_challenges WHERE challenge_id = ? AND room_id = ? LIMIT 1")
      .bind(challengeId, roomId)
      .first<ChallengeRow>();
    const now = Date.now();
    if (!challenge || challenge.status !== "pending" || challenge.expires_at <= now || challenge.attempts >= challenge.max_attempts) {
      return jsonResponse({ code: "invalid_or_expired_code" }, 400);
    }
    const expected = await verificationCodeHash(
      otpSigningSecret(),
      roomId,
      challengeId,
      challenge.email,
      code,
    );
    if (!constantTimeEqual(expected, challenge.code_hash)) {
      const nextAttempts = challenge.attempts + 1;
      await db
        .prepare("UPDATE share_access_challenges SET attempts = ?, status = CASE WHEN ? >= max_attempts THEN 'locked' ELSE status END WHERE challenge_id = ? AND status = 'pending'")
        .bind(nextAttempts, nextAttempts, challengeId)
        .run();
      await writeAccessLog(
        roomId,
        challenge.email,
        "verification_code_rejected",
        request,
        nextAttempts >= challenge.max_attempts ? "attempt_limit" : "invalid_code",
      );
      return jsonResponse({
        code: "invalid_or_expired_code",
        attempts_remaining: Math.max(0, challenge.max_attempts - nextAttempts),
      }, 400);
    }
    const consumed = await db
      .prepare(
        "UPDATE share_access_challenges SET status = 'consumed', attempts = attempts + 1, consumed_at = ? WHERE challenge_id = ? AND room_id = ? AND status = 'pending' AND expires_at > ? RETURNING email",
      )
      .bind(now, challengeId, roomId, now)
      .first<{ email: string }>();
    if (!consumed) return jsonResponse({ code: "invalid_or_expired_code" }, 400);

    const token = randomToken(32);
    const expiresAt = Math.min(room.expires_at, now + 8 * 60 * 60 * 1_000);
    const retainUntil = now + ACCESS_LOG_RETENTION_DAYS * 24 * 60 * 60 * 1_000;
    await db
      .prepare(
        "INSERT INTO share_viewer_sessions (session_token_hash, room_id, email, created_at, expires_at, last_seen_at, view_started_at, view_count, revoked_at, retain_until) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?)",
      )
      .bind(await hashToken(token), roomId, consumed.email, now, expiresAt, now, retainUntil)
      .run();
    await writeAccessLog(roomId, consumed.email, "access_granted", request);
    return jsonResponse(
      {
        authenticated: true,
        expires_at: new Date(expiresAt).toISOString(),
      },
      200,
      { "Set-Cookie": viewerSessionCookie(roomId, token, (expiresAt - now) / 1_000) },
    );
  } catch (error) {
    const code = error instanceof Error && error.message === "payload_too_large"
      ? "payload_too_large"
      : "verification_failed";
    return jsonResponse({ code }, code === "payload_too_large" ? 413 : 500);
  }
}
