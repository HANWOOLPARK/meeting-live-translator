import { cleanupAccessRecords, hostAccessSnapshot } from "../../../../../lib/access-auth";
import {
  authorizeHost,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  validRoomId,
} from "../../../../../lib/relay";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function GET(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  const found = await getRoom(roomId);
  if (!found) return jsonResponse({ code: "room_not_found" }, 404);
  if (!(await authorizeHost(request, found))) return jsonResponse({ code: "unauthorized" }, 401);
  const room = await expireIfNeeded(found);
  await cleanupAccessRecords();
  return jsonResponse(await hostAccessSnapshot(room));
}
