"""Single source of truth for OpenAI meeting analysis prompts and schema."""

from __future__ import annotations

import json

from ..translation.glossary import DEFAULT_GLOSSARY_TERMS
from .models import AnalysisRequest


ANALYSIS_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "meeting_purpose": {"$ref": "#/$defs/evidence_item"},
        "key_discussions": {
            "type": "array",
            "items": {"$ref": "#/$defs/evidence_item"},
        },
        "decisions": {
            "type": "array",
            "items": {"$ref": "#/$defs/evidence_item"},
        },
        "action_items": {
            "type": "array",
            "items": {"$ref": "#/$defs/action_item"},
        },
        "open_questions": {
            "type": "array",
            "items": {"$ref": "#/$defs/evidence_item"},
        },
        "next_meeting_checks": {
            "type": "array",
            "items": {"$ref": "#/$defs/evidence_item"},
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "meeting_purpose",
        "key_discussions",
        "decisions",
        "action_items",
        "open_questions",
        "next_meeting_checks",
        "warnings",
    ],
    "$defs": {
        "evidence_item": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "evidence_segment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["text", "evidence_segment_ids"],
        },
        "action_item": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task": {"type": "string", "minLength": 1},
                "assignee": {"type": "string"},
                "due_date": {"type": "string"},
                "evidence_segment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["task", "assignee", "due_date", "evidence_segment_ids"],
        },
    },
}


def build_analysis_instructions() -> str:
    glossary = "\n".join(f"- {term}" for term in DEFAULT_GLOSSARY_TERMS)
    return (
        "Analyze only the supplied finalized meeting segments. Do not use outside "
        "knowledge or guess missing facts. Distinguish discussion, proposals, confirmed "
        "decisions, questions, and action items. If an assignee or due date is not explicit, "
        "write exactly '미정'. Ambiguous actors such as we, they, 우리, 담당팀, or 担当チーム "
        "must be '미정'. Do not convert relative dates such as next week, 다음 주, or 来週 "
        "into an absolute date. Use normalized_text for approved terminology, but keep "
        "evidence grounded in original_text. Prefer original_text when it conflicts with the Korean "
        "translation. Preserve numbers, dates, times, companies, people, products, and these "
        "terms exactly:\n"
        f"{glossary}\n"
        "Every factual item must cite only segment_id values present in the input. If there "
        "is no evidence, omit the item. If the meeting purpose is unclear, use text '미정' "
        "with an empty evidence list. Return only the requested JSON structure, with no "
        "greeting, explanation, or Markdown code fence."
    )


def build_analysis_input(request: AnalysisRequest) -> str:
    return json.dumps(
        {
            "session_id": request.session_id,
            "segments": [segment.to_prompt_dict() for segment in request.segments],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "ANALYSIS_RESPONSE_JSON_SCHEMA",
    "build_analysis_input",
    "build_analysis_instructions",
]
