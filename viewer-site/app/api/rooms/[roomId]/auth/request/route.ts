import {
  OTP_CHALLENGE_RETENTION_SECONDS,
  OTP_MAX_ATTEMPTS,
  OTP_RESEND_SECONDS,
  OTP_TTL_SECONDS,
  cleanupAccessRecords,
  emailDeliveryConfigured,
  otpSigningSecret,
  requestIpHash,
  sendVerificationEmail,
  writeAccessLog,
} from "../../../../../../lib/access-auth";
import {
  generateVerificationCode,
  hmacHex,
  normalizeEmail,
  verificationCodeHash,
} from "../../../../../../lib/access-auth-core";
import {
  database,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  parseJsonBody,
  randomToken,
  validRoomId,
} from "../../../../../../lib/relay";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function POST(request: Request, context: RouteContext) {
  try {
    await ensureSchema();
    const { roomId } = await context.params;
    if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
    const found = await getRoom(roomId);
    if (!found) return jsonResponse({ code: "room_not_found" }, 404);
    const room = await expireIfNeeded(found);
    if (room.status !== "active") return jsonResponse({ code: "room_ended" }, 410);
    if (!emailDeliveryConfigured()) {
      return jsonResponse({ code: "email_delivery_unavailable" }, 503);
    }
    const payload = await parseJsonBody(request, 5_000);
    const email = normalizeEmail(payload.email);
    if (!email) return jsonResponse({ code: "invalid_email" }, 400);

    await cleanupAccessRecords();
    const db = database();
    const now = Date.now();
    const windowStart = now - 15 * 60 * 1_000;
    const ipHash = await requestIpHash(request);
    const emailHash = await hmacHex(otpSigningSecret(), `mlt-email-v1\n${email}`);
    const latest = await db
      .prepare(
        "SELECT created_at FROM share_access_challenges WHERE room_id = ? AND email_hash = ? ORDER BY created_at DESC LIMIT 1",
      )
      .bind(roomId, emailHash)
      .first<{ created_at: number }>();
    if (latest && now - latest.created_at < OTP_RESEND_SECONDS * 1_000) {
      const retryAfter = Math.max(1, Math.ceil((OTP_RESEND_SECONDS * 1_000 - (now - latest.created_at)) / 1_000));
      return jsonResponse(
        { code: "verification_code_rate_limited", retry_after_seconds: retryAfter },
        429,
        { "Retry-After": String(retryAfter) },
      );
    }
    const emailCount = await db
      .prepare(
        "SELECT COUNT(*) AS total FROM share_access_challenges WHERE room_id = ? AND email_hash = ? AND created_at >= ?",
      )
      .bind(roomId, emailHash, windowStart)
      .first<{ total: number }>();
    const ipCount = await db
      .prepare(
        "SELECT COUNT(*) AS total FROM share_access_challenges WHERE ip_hash = ? AND created_at >= ?",
      )
      .bind(ipHash, windowStart)
      .first<{ total: number }>();
    if (Number(emailCount?.total ?? 0) >= 5 || Number(ipCount?.total ?? 0) >= 20) {
      return jsonResponse(
        { code: "verification_code_rate_limited", retry_after_seconds: 15 * 60 },
        429,
        { "Retry-After": String(15 * 60) },
      );
    }

    const challengeId = randomToken(18);
    const code = generateVerificationCode();
    const expiresAt = now + OTP_TTL_SECONDS * 1_000;
    const retainUntil = now + OTP_CHALLENGE_RETENTION_SECONDS * 1_000;
    await db
      .prepare(
        "UPDATE share_access_challenges SET status = 'superseded' WHERE room_id = ? AND email_hash = ? AND status IN ('pending', 'sending')",
      )
      .bind(roomId, emailHash)
      .run();
    await db
      .prepare(
        "INSERT INTO share_access_challenges (challenge_id, room_id, email, email_hash, code_hash, ip_hash, status, attempts, max_attempts, created_at, expires_at, consumed_at, retain_until) VALUES (?, ?, ?, ?, ?, ?, 'sending', 0, ?, ?, ?, NULL, ?)",
      )
      .bind(
        challengeId,
        roomId,
        email,
        emailHash,
        await verificationCodeHash(otpSigningSecret(), roomId, challengeId, email, code),
        ipHash,
        OTP_MAX_ATTEMPTS,
        now,
        expiresAt,
        retainUntil,
      )
      .run();

    try {
      await sendVerificationEmail(email, code, challengeId);
    } catch {
      await db
        .prepare("UPDATE share_access_challenges SET status = 'delivery_failed' WHERE challenge_id = ?")
        .bind(challengeId)
        .run();
      await writeAccessLog(roomId, email, "email_delivery_failed", request);
      return jsonResponse({ code: "email_delivery_failed" }, 503);
    }
    await db
      .prepare("UPDATE share_access_challenges SET status = 'pending' WHERE challenge_id = ? AND status = 'sending'")
      .bind(challengeId)
      .run();
    await writeAccessLog(roomId, email, "verification_code_sent", request);
    return jsonResponse(
      {
        challenge_id: challengeId,
        expires_at: new Date(expiresAt).toISOString(),
        retry_after_seconds: OTP_RESEND_SECONDS,
      },
      202,
    );
  } catch (error) {
    const code = error instanceof Error && error.message === "payload_too_large"
      ? "payload_too_large"
      : "verification_request_failed";
    return jsonResponse({ code }, code === "payload_too_large" ? 413 : 500);
  }
}
