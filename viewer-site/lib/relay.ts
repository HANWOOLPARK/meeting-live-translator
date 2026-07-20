import { env } from "cloudflare:workers";

export const IDLE_TIMEOUT_SECONDS = 15 * 60;
export const HARD_TTL_SECONDS = 8 * 60 * 60;
const ENDED_TOMBSTONE_MILLISECONDS = 5 * 60 * 1000;
const MAX_SEGMENTS = 80;
const MAX_RADAR_ITEMS = 100;

type RuntimeEnv = typeof env & {
  DB: D1Database;
  MLT_RELAY_CREATE_SECRET?: string;
};

export type SharedSegment = {
  segment_id: string;
  original_text: string;
  translated_text: string | null;
  translation_status: "pending" | "success" | "error" | "disabled";
  translation_message: string | null;
  language: string;
  started_at: string | null;
  ended_at: string | null;
  timestamp: string | null;
};

export type SharedRadarItem = {
  item_id: string;
  category: "decision" | "action_item" | "open_question" | "needs_confirmation";
  text: string;
  assignee: string | null;
  due_date: string | null;
  confirmation_kind: string | null;
  evidence_segment_ids: string[];
  review_status: "suggested" | "approved";
  lifecycle_status: "active" | "superseded" | "resolved" | "retracted";
  lifecycle_reason: string | null;
};

export type SharedRoomState = {
  capture_status: string;
  partial: {
    utterance_id: string;
    text: string;
    language: string;
    timestamp: string | null;
  } | null;
  segments: SharedSegment[];
  pending_translations: Record<
    string,
    {
      translated_text: string | null;
      status: "pending" | "success" | "error";
      message: string | null;
    }
  >;
  radar: {
    status: string;
    revision: number;
    updated_at: string | null;
    queue_size: number;
    message: string | null;
    items: SharedRadarItem[];
  };
};

export type RoomRow = {
  room_id: string;
  host_token_hash: string;
  state_json: string;
  revision: number;
  status: string;
  created_at: number;
  updated_at: number;
  last_activity_at: number;
  expires_at: number;
  ended_at: number | null;
  retention_policy: string;
  idle_ttl_seconds: number;
};

export function database() {
  return (env as RuntimeEnv).DB;
}

export function createSecret() {
  return ((env as RuntimeEnv).MLT_RELAY_CREATE_SECRET ?? "").trim();
}

export async function ensureSchema() {
  const db = database();
  await db.batch([
    db.prepare(`
      CREATE TABLE IF NOT EXISTS share_rooms (
        room_id TEXT PRIMARY KEY NOT NULL,
        host_token_hash TEXT NOT NULL,
        state_json TEXT NOT NULL DEFAULT '{}',
        revision INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_activity_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        ended_at INTEGER,
        retention_policy TEXT NOT NULL DEFAULT 'delete_on_stop',
        idle_ttl_seconds INTEGER NOT NULL DEFAULT 900
      )
    `),
    db.prepare(`
      CREATE INDEX IF NOT EXISTS share_rooms_expiry_idx
      ON share_rooms(status, expires_at, last_activity_at)
    `),
  ]);
}

export function emptyState(): SharedRoomState {
  return {
    capture_status: "idle",
    partial: null,
    segments: [],
    pending_translations: {},
    radar: {
      status: "disabled",
      revision: 0,
      updated_at: null,
      queue_size: 0,
      message: null,
      items: [],
    },
  };
}

function clean(value: unknown, maximum = 4_000) {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum).trim();
}

function identifier(value: unknown) {
  return clean(value, 128);
}

function timestamp(value: unknown) {
  return clean(value, 64) || null;
}

function language(value: unknown) {
  const normalized = clean(value, 16).toLowerCase();
  return ["ja", "en", "ko", "mixed", "unknown"].includes(normalized)
    ? normalized
    : "unknown";
}

export function parseState(value: string): SharedRoomState {
  try {
    const parsed = JSON.parse(value) as Partial<SharedRoomState>;
    const base = emptyState();
    return {
      ...base,
      ...parsed,
      segments: Array.isArray(parsed.segments) ? parsed.segments.slice(-MAX_SEGMENTS) : [],
      pending_translations:
        parsed.pending_translations && typeof parsed.pending_translations === "object"
          ? parsed.pending_translations
          : {},
      radar: { ...base.radar, ...(parsed.radar ?? {}) },
    };
  } catch {
    return emptyState();
  }
}

function radarItems(value: unknown): SharedRadarItem[] {
  if (!Array.isArray(value)) return [];
  const allowed = new Set([
    "decision",
    "action_item",
    "open_question",
    "needs_confirmation",
  ]);
  return value.slice(0, MAX_RADAR_ITEMS).flatMap((raw) => {
    if (!raw || typeof raw !== "object") return [];
    const source = raw as Record<string, unknown>;
    const item_id = identifier(source.item_id);
    const category = clean(source.category, 32);
    const text = clean(source.text);
    const evidence = Array.isArray(source.evidence_segment_ids)
      ? Array.from(
          new Set(source.evidence_segment_ids.slice(0, 20).map(identifier).filter(Boolean)),
        )
      : [];
    if (!item_id || !text || !allowed.has(category) || evidence.length === 0) return [];
    return [
      {
        item_id,
        category: category as SharedRadarItem["category"],
        text,
        assignee: clean(source.assignee, 240) || null,
        due_date: clean(source.due_date, 240) || null,
        confirmation_kind: clean(source.confirmation_kind, 32) || null,
        evidence_segment_ids: evidence,
        review_status: source.review_status === "approved" ? "approved" : "suggested",
        lifecycle_status: ["superseded", "resolved", "retracted"].includes(clean(source.lifecycle_status, 32))
          ? clean(source.lifecycle_status, 32) as SharedRadarItem["lifecycle_status"]
          : "active",
        lifecycle_reason: clean(source.lifecycle_reason, 500) || null,
      } satisfies SharedRadarItem,
    ];
  });
}

export function applyEvents(state: SharedRoomState, rawEvents: unknown[]) {
  for (const raw of rawEvents.slice(0, 25)) {
    if (!raw || typeof raw !== "object") continue;
    const event = raw as Record<string, unknown>;
    const type = clean(event.type, 48);

    if (type === "partial_transcript") {
      const text = clean(event.text);
      if (text) {
        state.partial = {
          utterance_id: identifier(event.utterance_id),
          text,
          language: language(event.language),
          timestamp: timestamp(event.timestamp),
        };
      }
      continue;
    }

    if (type === "partial_clear") {
      const utteranceId = identifier(event.utterance_id);
      if (!utteranceId || state.partial?.utterance_id === utteranceId) state.partial = null;
      continue;
    }

    if (type === "final_transcript") {
      const segmentId = identifier(event.segment_id);
      const text = clean(event.text);
      if (!segmentId || !text) continue;
      const existing = state.segments.find((segment) => segment.segment_id === segmentId);
      const pending = state.pending_translations[segmentId];
      if (!existing) {
        state.segments.push({
          segment_id: segmentId,
          original_text: text,
          translated_text: pending?.translated_text ?? null,
          translation_status: pending?.status ?? "pending",
          translation_message: pending?.message ?? null,
          language: language(event.language),
          started_at: timestamp(event.started_at),
          ended_at: timestamp(event.ended_at),
          timestamp: timestamp(event.timestamp),
        });
        state.segments = state.segments.slice(-MAX_SEGMENTS);
      }
      delete state.pending_translations[segmentId];
      state.partial = null;
      continue;
    }

    if (["translation_pending", "translation", "translation_error"].includes(type)) {
      const segmentId = identifier(event.segment_id);
      if (!segmentId) continue;
      const status =
        type === "translation" ? "success" : type === "translation_error" ? "error" : "pending";
      const translatedText = type === "translation" ? clean(event.translated_text) || null : null;
      const message = type === "translation_error" ? clean(event.message, 300) || null : null;
      const segment = state.segments.find((candidate) => candidate.segment_id === segmentId);
      if (segment) {
        segment.translation_status = status;
        segment.translated_text = translatedText ?? segment.translated_text;
        segment.translation_message = message;
      } else {
        state.pending_translations[segmentId] = {
          translated_text: translatedText,
          status,
          message,
        };
        const keys = Object.keys(state.pending_translations);
        for (const key of keys.slice(0, Math.max(0, keys.length - 20))) {
          delete state.pending_translations[key];
        }
      }
      continue;
    }

    if (type === "decision_radar_updated") {
      const radar = event.decision_radar;
      if (!radar || typeof radar !== "object") continue;
      const source = radar as Record<string, unknown>;
      state.radar = {
        ...state.radar,
        status: clean(source.status, 24) || "idle",
        revision: Math.max(0, Number(source.revision) || 0),
        updated_at: timestamp(source.updated_at),
        message: null,
        items: radarItems(source.items),
      };
      continue;
    }

    if (type === "decision_radar_status") {
      state.radar.status = clean(event.status, 24) || "idle";
      state.radar.queue_size = Math.max(0, Number(event.queue_size) || 0);
      continue;
    }

    if (type === "decision_radar_error") {
      state.radar.status = "error";
      state.radar.message = clean(event.message, 300) || null;
      continue;
    }

    if (type === "state") {
      state.capture_status = clean(event.status, 24) || state.capture_status;
    }
  }
  return state;
}

export function publicState(state: SharedRoomState) {
  const { pending_translations, ...safe } = state;
  void pending_translations;
  return safe;
}

export function bearerToken(request: Request) {
  const value = request.headers.get("authorization") ?? "";
  return value.startsWith("Bearer ") ? value.slice(7).trim() : "";
}

export function randomToken(byteLength: number) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export async function hashToken(token: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function validRoomId(value: string) {
  return /^[A-Za-z0-9_-]{20,64}$/.test(value);
}

export async function getRoom(roomId: string) {
  return database()
    .prepare("SELECT * FROM share_rooms WHERE room_id = ? LIMIT 1")
    .bind(roomId)
    .first<RoomRow>();
}

export async function expireIfNeeded(room: RoomRow) {
  if (room.status !== "active") return room;
  const now = Date.now();
  const idleDeadline = room.last_activity_at + room.idle_ttl_seconds * 1_000;
  if (now < room.expires_at && now < idleDeadline) return room;
  await database()
    .prepare(
      "UPDATE share_rooms SET state_json = '{}', host_token_hash = '', status = 'ended', revision = revision + 1, updated_at = ?, ended_at = ?, expires_at = ? WHERE room_id = ?",
    )
    .bind(now, now, now + ENDED_TOMBSTONE_MILLISECONDS, room.room_id)
    .run();
  return { ...room, state_json: "{}", host_token_hash: "", status: "ended", ended_at: now };
}

export async function authorizeHost(request: Request, room: RoomRow) {
  const token = bearerToken(request);
  return Boolean(token && room.host_token_hash && (await hashToken(token)) === room.host_token_hash);
}

export async function cleanupTombstones() {
  const now = Date.now();
  await database()
    .prepare("DELETE FROM share_rooms WHERE status != 'active' AND expires_at <= ?")
    .bind(now)
    .run();
}

export function jsonResponse(body: unknown, status = 200, headers: HeadersInit = {}) {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store, max-age=0",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
}

export async function parseJsonBody(request: Request, maximum = 200_000) {
  const text = await request.text();
  if (text.length > maximum) throw new Error("payload_too_large");
  return text ? (JSON.parse(text) as Record<string, unknown>) : {};
}
