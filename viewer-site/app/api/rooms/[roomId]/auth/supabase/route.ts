import { writeAccessLog } from "../../../../../../lib/access-auth";
import { viewerSessionCookie } from "../../../../../../lib/access-auth-core";
import {
  database,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  hashToken,
  jsonResponse,
  randomToken,
  validRoomId,
} from "../../../../../../lib/relay";
import {
  supabaseAuthConfigured,
  verifySupabaseGoogleIdentity,
} from "../../../../../../lib/supabase-auth";

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
    if (!supabaseAuthConfigured()) {
      return jsonResponse({ code: "supabase_auth_unavailable" }, 503);
    }

    const identity = await verifySupabaseGoogleIdentity(request);
    if (!identity) return jsonResponse({ code: "google_identity_required" }, 401);

    const now = Date.now();
    const recent = await database()
      .prepare(
        "SELECT COUNT(*) AS total FROM share_viewer_sessions WHERE room_id = ? AND email = ? AND created_at >= ?",
      )
      .bind(roomId, identity.email, now - 15 * 60 * 1_000)
      .first<{ total: number }>();
    if (Number(recent?.total ?? 0) >= 10) {
      return jsonResponse({ code: "authentication_rate_limited" }, 429, {
        "Retry-After": "900",
      });
    }

    const token = randomToken(32);
    const expiresAt = Math.min(room.expires_at, now + 8 * 60 * 60 * 1_000);
    // Relay identity rows live only through the room. The host's sanitized final
    // audit snapshot has its own local, maximum-30-day retention policy.
    const retainUntil = expiresAt;
    await database()
      .prepare(
        "INSERT INTO share_viewer_sessions (session_token_hash, room_id, email, created_at, expires_at, last_seen_at, view_started_at, view_count, revoked_at, retain_until) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?)",
      )
      .bind(
        await hashToken(token),
        roomId,
        identity.email,
        now,
        expiresAt,
        now,
        retainUntil,
      )
      .run();
    await writeAccessLog(
      roomId,
      identity.email,
      "access_granted",
      request,
      "supabase_google",
      expiresAt,
    );
    return jsonResponse(
      {
        authenticated: true,
        email: identity.email,
        display_name: identity.displayName,
        provider: identity.provider,
        expires_at: new Date(expiresAt).toISOString(),
      },
      200,
      { "Set-Cookie": viewerSessionCookie(roomId, token, (expiresAt - now) / 1_000) },
    );
  } catch (error) {
    const code = error instanceof DOMException && error.name === "TimeoutError"
      ? "supabase_auth_timeout"
      : "supabase_auth_failed";
    return jsonResponse({ code }, code === "supabase_auth_timeout" ? 504 : 500);
  }
}
