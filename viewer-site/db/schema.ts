import { index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const shareRooms = sqliteTable(
  "share_rooms",
  {
    roomId: text("room_id").primaryKey(),
    hostTokenHash: text("host_token_hash").notNull(),
    stateJson: text("state_json").notNull().default("{}"),
    revision: integer("revision").notNull().default(0),
    status: text("status").notNull().default("active"),
    createdAt: integer("created_at").notNull(),
    updatedAt: integer("updated_at").notNull(),
    lastActivityAt: integer("last_activity_at").notNull(),
    expiresAt: integer("expires_at").notNull(),
    endedAt: integer("ended_at"),
    retentionPolicy: text("retention_policy").notNull().default("delete_on_stop"),
    idleTtlSeconds: integer("idle_ttl_seconds").notNull().default(900),
  },
  (table) => [
    index("share_rooms_expiry_idx").on(
      table.status,
      table.expiresAt,
      table.lastActivityAt,
    ),
  ],
);

export const shareAccessChallenges = sqliteTable(
  "share_access_challenges",
  {
    challengeId: text("challenge_id").primaryKey(),
    roomId: text("room_id").notNull(),
    email: text("email").notNull(),
    emailHash: text("email_hash").notNull(),
    codeHash: text("code_hash").notNull(),
    ipHash: text("ip_hash").notNull(),
    status: text("status").notNull().default("pending"),
    attempts: integer("attempts").notNull().default(0),
    maxAttempts: integer("max_attempts").notNull().default(5),
    createdAt: integer("created_at").notNull(),
    expiresAt: integer("expires_at").notNull(),
    consumedAt: integer("consumed_at"),
    retainUntil: integer("retain_until").notNull(),
  },
  (table) => [
    index("share_access_challenges_room_email_idx").on(
      table.roomId,
      table.emailHash,
      table.createdAt,
    ),
    index("share_access_challenges_ip_idx").on(table.ipHash, table.createdAt),
    index("share_access_challenges_retention_idx").on(table.retainUntil),
  ],
);

export const shareViewerSessions = sqliteTable(
  "share_viewer_sessions",
  {
    sessionTokenHash: text("session_token_hash").primaryKey(),
    roomId: text("room_id").notNull(),
    email: text("email").notNull(),
    createdAt: integer("created_at").notNull(),
    expiresAt: integer("expires_at").notNull(),
    lastSeenAt: integer("last_seen_at").notNull(),
    viewStartedAt: integer("view_started_at"),
    viewCount: integer("view_count").notNull().default(0),
    revokedAt: integer("revoked_at"),
    retainUntil: integer("retain_until").notNull(),
  },
  (table) => [
    index("share_viewer_sessions_room_email_idx").on(
      table.roomId,
      table.email,
      table.createdAt,
    ),
    index("share_viewer_sessions_retention_idx").on(table.retainUntil),
  ],
);

export const shareAccessLogs = sqliteTable(
  "share_access_logs",
  {
    eventId: text("event_id").primaryKey(),
    roomId: text("room_id").notNull(),
    email: text("email").notNull(),
    eventType: text("event_type").notNull(),
    occurredAt: integer("occurred_at").notNull(),
    ipHash: text("ip_hash").notNull(),
    detailCode: text("detail_code").notNull().default(""),
    retainUntil: integer("retain_until").notNull(),
  },
  (table) => [
    index("share_access_logs_room_time_idx").on(table.roomId, table.occurredAt),
    index("share_access_logs_retention_idx").on(table.retainUntil),
  ],
);
