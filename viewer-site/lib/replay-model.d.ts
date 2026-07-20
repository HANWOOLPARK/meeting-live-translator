export type ReplayFixture = {
  schema_version: number;
  duration_ms: number;
  source: {
    kind: string;
    language: "ja" | "en" | "ko";
    target_language: "ja" | "en" | "ko";
    audio_retained: boolean;
    source_duration_ms: number;
  };
  events: Array<Record<string, unknown>>;
};

export type ReplaySegment = {
  segment_id: string;
  language: string;
  original_text: string;
  normalized_text: string;
  context_changed: boolean;
  context_matches: Array<{ category: string; from: string; to: string }>;
  translated_text: string;
  translation_status: "pending" | "success";
  final_at_ms: number;
  translation_at_ms: number | null;
  translation_latency_ms: number | null;
};

export type ReplayRadarItem = {
  item_id: string;
  category: "decision" | "action_item" | "open_question" | "needs_confirmation";
  text: string;
  assignee: string | null;
  due_date: string | null;
  review_status: string;
  lifecycle_status: string;
  evidence_segment_ids: string[];
};

export function evidenceTargetId(segmentId: string): string;
export function emptyReplayState(): { segments: ReplaySegment[]; radarItems: ReplayRadarItem[] };
export function snapshotAt(fixture: ReplayFixture, elapsedMs: number): { segments: ReplaySegment[]; radarItems: ReplayRadarItem[] };
export function clampReplayTime(fixture: ReplayFixture, elapsedMs: number): number;
export function validateReplayFixture(fixture: ReplayFixture): boolean;
