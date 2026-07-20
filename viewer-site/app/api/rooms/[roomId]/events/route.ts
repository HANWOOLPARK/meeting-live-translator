import {
  applyEvents,
  authorizeHost,
  database,
  ensureSchema,
  expireIfNeeded,
  getRoom,
  jsonResponse,
  parseJsonBody,
  parseState,
  validRoomId,
} from "../../../../../lib/relay";

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
    if (!(await authorizeHost(request, room))) {
      return jsonResponse({ code: "unauthorized" }, 401);
    }
    const payload = await parseJsonBody(request);
    if (!Array.isArray(payload.events) || payload.events.length > 25) {
      return jsonResponse({ code: "invalid_events" }, 400);
    }
    const state = applyEvents(parseState(room.state_json), payload.events);
    const now = Date.now();
    const result = await database()
      .prepare(
        "UPDATE share_rooms SET state_json = ?, revision = revision + 1, updated_at = ?, last_activity_at = ? WHERE room_id = ? AND status = 'active' RETURNING revision",
      )
      .bind(JSON.stringify(state), now, now, roomId)
      .first<{ revision: number }>();
    return jsonResponse({ accepted: payload.events.length, revision: result?.revision ?? room.revision + 1 });
  } catch (error) {
    const code = error instanceof Error && error.message === "payload_too_large"
      ? "payload_too_large"
      : "event_update_failed";
    return jsonResponse({ code }, code === "payload_too_large" ? 413 : 500);
  }
}
