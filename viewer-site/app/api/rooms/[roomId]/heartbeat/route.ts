import {
  authorizeHost,
  database,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  validRoomId,
} from "../../../../../lib/relay";

type RouteContext = { params: Promise<{ roomId: string }> };

export async function POST(request: Request, context: RouteContext) {
  await ensureSchema();
  const { roomId } = await context.params;
  if (!validRoomId(roomId)) return jsonResponse({ code: "room_not_found" }, 404);
  const found = await getRoom(roomId);
  if (!found) return jsonResponse({ code: "room_not_found" }, 404);
  const room = await expireIfNeeded(found);
  if (room.status !== "active") return jsonResponse({ code: "room_ended" }, 410);
  if (!(await authorizeHost(request, room))) {
    return jsonResponse({ code: "unauthorized" }, 401);
  }
  const now = Date.now();
  await database()
    .prepare("UPDATE share_rooms SET last_activity_at = ?, updated_at = ? WHERE room_id = ?")
    .bind(now, now, roomId)
    .run();
  return jsonResponse({ ok: true });
}
