export function evidenceTargetId(segmentId) {
  return `replay-segment-${segmentId}`;
}

export function emptyReplayState() {
  return { segments: [], radarItems: [] };
}

export function snapshotAt(fixture, elapsedMs) {
  const segments = new Map();
  const radarItems = new Map();

  for (const event of fixture.events ?? []) {
    if (Number(event.at_ms) > elapsedMs) break;
    if (event.type === "final_transcript") {
      segments.set(event.segment_id, {
        segment_id: event.segment_id,
        language: event.language,
        original_text: event.text,
        normalized_text: event.text,
        context_changed: false,
        context_matches: [],
        translated_text: "",
        translation_status: "pending",
        final_at_ms: Number(event.at_ms),
        translation_at_ms: null,
        translation_latency_ms: null,
      });
      continue;
    }
    if (event.type === "context_normalization") {
      const segment = segments.get(event.segment_id);
      if (!segment) continue;
      segments.set(event.segment_id, {
        ...segment,
        normalized_text: event.normalized_text || segment.original_text,
        context_changed: Boolean(event.changed),
        context_matches: Array.isArray(event.matches) ? event.matches : [],
      });
      continue;
    }
    if (event.type === "translation") {
      const segment = segments.get(event.segment_id);
      if (!segment) continue;
      segments.set(event.segment_id, {
        ...segment,
        translated_text: event.text,
        translation_status: "success",
        translation_at_ms: Number(event.at_ms),
        translation_latency_ms: Number(event.latency_ms),
      });
      continue;
    }
    if (event.type === "radar_update") {
      for (const item of event.items ?? []) radarItems.set(item.item_id, item);
    }
  }

  return {
    segments: [...segments.values()],
    radarItems: [...radarItems.values()],
  };
}

export function clampReplayTime(fixture, elapsedMs) {
  const duration = Math.max(0, Number(fixture.duration_ms) || 0);
  return Math.min(duration, Math.max(0, Number(elapsedMs) || 0));
}

export function validateReplayFixture(fixture) {
  if (!fixture || fixture.schema_version !== 1 || !Array.isArray(fixture.events)) return false;
  if (!["ja", "en", "ko"].includes(fixture.source?.language)) return false;
  if (!["ja", "en", "ko"].includes(fixture.source?.target_language)) return false;
  if (fixture.audio) {
    if (typeof fixture.audio.url !== "string" || !fixture.audio.url.startsWith("/")) return false;
    if (fixture.audio.url.includes("://")) return false;
    if (!Number.isFinite(fixture.audio.duration_ms) || fixture.audio.duration_ms <= 0) return false;
    if (!/^[a-f0-9]{64}$/.test(fixture.audio.sha256 ?? "")) return false;
    if (fixture.audio.kind !== "consented_scripted_demo") return false;
    if (fixture.audio.private_meeting_audio !== false) return false;
  }
  const segmentIds = new Set(
    fixture.events
      .filter((event) => event.type === "final_transcript")
      .map((event) => event.segment_id),
  );
  if (!segmentIds.size) return false;
  return fixture.events.every((event) => {
    if (event.type !== "radar_update") return true;
    return (event.items ?? []).every(
      (item) => Array.isArray(item.evidence_segment_ids)
        && item.evidence_segment_ids.length > 0
        && item.evidence_segment_ids.every((segmentId) => segmentIds.has(segmentId)),
    );
  });
}
