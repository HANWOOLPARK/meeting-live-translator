CREATE TABLE `share_rooms` (
	`room_id` text PRIMARY KEY NOT NULL,
	`host_token_hash` text NOT NULL,
	`state_json` text DEFAULT '{}' NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	`last_activity_at` integer NOT NULL,
	`expires_at` integer NOT NULL,
	`ended_at` integer,
	`retention_policy` text DEFAULT 'delete_on_stop' NOT NULL,
	`idle_ttl_seconds` integer DEFAULT 900 NOT NULL
);
