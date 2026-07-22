import {
  HARD_TTL_SECONDS,
  IDLE_TIMEOUT_SECONDS,
  bearerToken,
  cleanupTombstones,
  createSecret,
  database,
  emptyState,
  ensureSchema,
  hashToken,
  jsonResponse,
  parseJsonBody,
  randomToken,
} from "../../../lib/relay";
import { cleanupAccessRecords } from "../../../lib/access-auth";
import { supabaseAuthConfigured } from "../../../lib/supabase-auth";

export async function POST(request: Request) {
  try {
    await ensureSchema();
    const expected = createSecret();
    if (!expected || bearerToken(request) !== expected) {
      return jsonResponse({ code: "unauthorized" }, 401);
    }
    if (!supabaseAuthConfigured()) {
      return jsonResponse({ code: "viewer_supabase_auth_not_configured" }, 503);
    }
    const payload = await parseJsonBody(request, 10_000);
    if (payload.retention_policy !== "delete_on_stop") {
      return jsonResponse({ code: "unsupported_retention_policy" }, 400);
    }
    const idleSeconds = Math.min(
      IDLE_TIMEOUT_SECONDS,
      Math.max(60, Number(payload.idle_ttl_seconds) || IDLE_TIMEOUT_SECONDS),
    );
    const hardSeconds = Math.min(
      HARD_TTL_SECONDS,
      Math.max(15 * 60, Number(payload.hard_ttl_seconds) || HARD_TTL_SECONDS),
    );
    const roomId = randomToken(18);
    const hostToken = randomToken(32);
    const now = Date.now();
    const expiresAt = now + hardSeconds * 1_000;
    await Promise.all([cleanupTombstones(), cleanupAccessRecords()]);
    await database()
      .prepare(
        "INSERT INTO share_rooms (room_id, host_token_hash, state_json, revision, status, created_at, updated_at, last_activity_at, expires_at, ended_at, retention_policy, idle_ttl_seconds) VALUES (?, ?, ?, 0, 'active', ?, ?, ?, ?, NULL, 'delete_on_stop', ?)",
      )
      .bind(
        roomId,
        await hashToken(hostToken),
        JSON.stringify(emptyState()),
        now,
        now,
        now,
        expiresAt,
        idleSeconds,
      )
      .run();
    const origin = new URL(request.url).origin;
    return jsonResponse(
      {
        room_id: roomId,
        host_token: hostToken,
        viewer_url: `${origin}/room/${roomId}`,
        expires_at: new Date(expiresAt).toISOString(),
        retention_policy: "delete_on_stop",
        idle_timeout_seconds: idleSeconds,
        access_control: "supabase_identity",
        access_log_retention_days: 30,
      },
      201,
    );
  } catch (error) {
    const code = error instanceof Error && error.message === "payload_too_large"
      ? "payload_too_large"
      : "room_create_failed";
    return jsonResponse({ code }, code === "payload_too_large" ? 413 : 500);
  }
}
