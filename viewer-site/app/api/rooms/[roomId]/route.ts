import {
  authorizeHost,
  endRoomAndPurgeAccess,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  parseState,
  publicState,
  validRoomId,
} from "../../../../lib/relay";
import {
  ACCESS_LOG_RETENTION_DAYS,
  authorizeViewer,
  hostAccessSnapshot,
  revokeRoomSessions,
  touchViewerSession,
} from "../../../../lib/access-auth";
import { supabaseAuthConfigured } from "../../../../lib/supabase-auth";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function GET(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  const found = await getRoom(roomId);
  if (!found) return jsonResponse({ code: "room_not_found" }, 404);
  const room = await expireIfNeeded(found);
  if (room.status !== "active") {
    return jsonResponse({ code: "room_ended", status: "ended" }, 410);
  }
  const hostAuthorized = await authorizeHost(request, room);
  const viewerSession = hostAuthorized ? null : await authorizeViewer(request, roomId);
  if (!hostAuthorized && !viewerSession) {
    return jsonResponse({
      code: "verified_identity_required",
      supabase_auth_configured: supabaseAuthConfigured(),
      access_log_retention_days: ACCESS_LOG_RETENTION_DAYS,
    }, 401);
  }
  if (viewerSession) await touchViewerSession(request, viewerSession);
  const now = Date.now();
  return jsonResponse({
    room_id: room.room_id,
    status: room.status,
    revision: room.revision,
    expires_at: new Date(room.expires_at).toISOString(),
    presenter_online: now - room.last_activity_at < 45_000,
    retention_policy: room.retention_policy,
    state: publicState(parseState(room.state_json)),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  const room = await getRoom(roomId);
  if (!room) return jsonResponse({ deleted: true });
  if (!(await authorizeHost(request, room))) {
    return jsonResponse({ code: "unauthorized" }, 401);
  }
  await revokeRoomSessions(roomId);
  const accessLog = await hostAccessSnapshot(room);
  const now = Date.now();
  await endRoomAndPurgeAccess(roomId, now);
  return jsonResponse({
    deleted: true,
    room_id: roomId,
    access_log: {
      ...accessLog,
      status: "ended",
      ended_at: new Date(now).toISOString(),
      attendees: accessLog.attendees.map((attendee) => ({ ...attendee, active: false })),
    },
  });
}
