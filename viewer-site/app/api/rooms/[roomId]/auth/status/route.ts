import {
  ACCESS_LOG_RETENTION_DAYS,
  authorizeViewer,
} from "../../../../../../lib/access-auth";
import {
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  validRoomId,
} from "../../../../../../lib/relay";
import { supabaseAuthConfigured } from "../../../../../../lib/supabase-auth";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function GET(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  const found = await getRoom(roomId);
  if (!found) return jsonResponse({ code: "room_not_found" }, 404);
  const room = await expireIfNeeded(found);
  if (room.status !== "active") return jsonResponse({ code: "room_ended" }, 410);
  const session = await authorizeViewer(request, roomId);
  return jsonResponse({
    authenticated: Boolean(session),
    email: session?.email ?? null,
    auth_provider: session ? "supabase_identity" : null,
    supabase_auth_configured: supabaseAuthConfigured(),
    access_log_retention_days: ACCESS_LOG_RETENTION_DAYS,
  });
}
