import { revokeViewerSession } from "../../../../../../lib/access-auth";
import { clearViewerSessionCookie } from "../../../../../../lib/access-auth-core";
import { ensureSchema, jsonResponse, validRoomId } from "../../../../../../lib/relay";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function POST(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  await revokeViewerSession(request, roomId);
  return jsonResponse(
    { authenticated: false },
    200,
    { "Set-Cookie": clearViewerSessionCookie(roomId) },
  );
}
