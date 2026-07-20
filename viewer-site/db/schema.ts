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
