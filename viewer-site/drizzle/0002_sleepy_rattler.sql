CREATE TABLE `share_access_challenges` (
	`challenge_id` text PRIMARY KEY NOT NULL,
	`room_id` text NOT NULL,
	`email` text NOT NULL,
	`email_hash` text NOT NULL,
	`code_hash` text NOT NULL,
	`ip_hash` text NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`attempts` integer DEFAULT 0 NOT NULL,
	`max_attempts` integer DEFAULT 5 NOT NULL,
	`created_at` integer NOT NULL,
	`expires_at` integer NOT NULL,
	`consumed_at` integer,
	`retain_until` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `share_access_challenges_room_email_idx` ON `share_access_challenges` (`room_id`,`email_hash`,`created_at`);--> statement-breakpoint
CREATE INDEX `share_access_challenges_ip_idx` ON `share_access_challenges` (`ip_hash`,`created_at`);--> statement-breakpoint
CREATE INDEX `share_access_challenges_retention_idx` ON `share_access_challenges` (`retain_until`);--> statement-breakpoint
CREATE TABLE `share_access_logs` (
	`event_id` text PRIMARY KEY NOT NULL,
	`room_id` text NOT NULL,
	`email` text NOT NULL,
	`event_type` text NOT NULL,
	`occurred_at` integer NOT NULL,
	`ip_hash` text NOT NULL,
	`detail_code` text DEFAULT '' NOT NULL,
	`retain_until` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `share_access_logs_room_time_idx` ON `share_access_logs` (`room_id`,`occurred_at`);--> statement-breakpoint
CREATE INDEX `share_access_logs_retention_idx` ON `share_access_logs` (`retain_until`);--> statement-breakpoint
CREATE TABLE `share_viewer_sessions` (
	`session_token_hash` text PRIMARY KEY NOT NULL,
	`room_id` text NOT NULL,
	`email` text NOT NULL,
	`created_at` integer NOT NULL,
	`expires_at` integer NOT NULL,
	`last_seen_at` integer NOT NULL,
	`view_started_at` integer,
	`view_count` integer DEFAULT 0 NOT NULL,
	`revoked_at` integer,
	`retain_until` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `share_viewer_sessions_room_email_idx` ON `share_viewer_sessions` (`room_id`,`email`,`created_at`);--> statement-breakpoint
CREATE INDEX `share_viewer_sessions_retention_idx` ON `share_viewer_sessions` (`retain_until`);