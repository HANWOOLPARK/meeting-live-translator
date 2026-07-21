from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(serialized)
    atomic_write_text(path, serialized)


def _display_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "시간 미상"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%H:%M:%S")
    except ValueError:
        return "시간 미상"


def render_original_txt(session: Mapping[str, Any]) -> str:
    segments = list(session.get("segments", []))
    saved = [item for item in segments if item.get("original_saved") and item.get("original_text")]
    lines = [
        "WhyKaigi - 전체 원문",
        f"세션 ID: {session.get('session_id', '')}",
        f"전체 segment: {len(segments)} / 저장된 원문: {len(saved)}",
        "",
    ]
    for segment in saved:
        lines.append(f"[{_display_time(segment.get('started_at'))}] {segment['original_text']}")
    if not saved:
        lines.append("저장된 원문이 없습니다.")
    return "\n".join(lines).rstrip() + "\n"


def render_translation_txt(session: Mapping[str, Any]) -> str:
    segments = list(session.get("segments", []))
    translated = [item for item in segments if item.get("translation_status") == "success" and item.get("korean_translation")]
    lines = [
        "WhyKaigi - 전체 한국어 번역",
        f"세션 ID: {session.get('session_id', '')}",
        (
            f"전체 segment: {len(segments)} / 번역 성공: {len(translated)} / "
            f"미번역·실패: {len(segments) - len(translated)}"
        ),
        "",
    ]
    for segment in translated:
        lines.append(f"[{_display_time(segment.get('started_at'))}] {segment['korean_translation']}")
    if not translated:
        lines.append("성공한 한국어 번역이 없습니다.")
    return "\n".join(lines).rstrip() + "\n"


def _analysis_section(analysis: Mapping[str, Any] | None, key: str) -> list[str]:
    if not analysis:
        return ["분석이 아직 생성되지 않았습니다."]
    value = analysis.get(key)
    if isinstance(value, dict):
        text = str(value.get("text", "")).strip()
        return [text] if text else ["해당 항목이 없습니다."]
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("text", item.get("task", ""))).strip()
            else:
                text = str(item).strip()
            if text:
                lines.append(f"- {text}")
        return lines or ["해당 항목이 없습니다."]
    text = str(value or "").strip()
    return [text] if text else ["해당 항목이 없습니다."]


def render_markdown(session: Mapping[str, Any]) -> str:
    metadata = dict(session.get("metadata", {}))
    analysis = session.get("analysis") if isinstance(session.get("analysis"), dict) else None
    lines = [
        "# 회의 기록",
        "",
        "## 기본 정보",
        "",
        f"- 세션 ID: {session.get('session_id', '')}",
        f"- 시작: {metadata.get('started_at') or '미상'}",
        f"- 종료: {metadata.get('ended_at') or '미상'}",
        f"- 입력 소스: {metadata.get('source') or '미상'}",
        f"- Whisper 모델: {metadata.get('whisper_model') or '미상'}",
        f"- 번역 방식: {metadata.get('translation_provider') or 'none'}",
        f"- 분석 방식: {metadata.get('analysis_provider') or 'none'}",
        "",
        "## 1. 회의 목적",
        "",
        *_analysis_section(analysis, "meeting_purpose"),
        "",
        "## 2. 주요 논의 내용",
        "",
        *_analysis_section(analysis, "key_discussions"),
        "",
        "## 3. 결정사항",
        "",
        *_analysis_section(analysis, "decisions"),
        "",
        "## 4. Action Items",
        "",
    ]
    action_items = list(analysis.get("action_items", [])) if analysis else []
    if action_items:
        lines.extend(["| 작업 | 담당자 | 기한 | 근거 |", "|---|---|---|---|"])
        for item in action_items:
            evidence = ", ".join(str(value) for value in item.get("evidence_segment_ids", []))
            lines.append(
                "| {task} | {assignee} | {due} | {evidence} |".format(
                    task=str(item.get("task", "")).replace("|", "\\|"),
                    assignee=str(item.get("assignee", "미정")).replace("|", "\\|"),
                    due=str(item.get("due_date", "미정")).replace("|", "\\|"),
                    evidence=evidence.replace("|", "\\|"),
                )
            )
    else:
        lines.append("분석이 아직 생성되지 않았습니다." if not analysis else "해당 항목이 없습니다.")
    lines.extend(
        [
            "",
            "## 5. 미해결 질문",
            "",
            *_analysis_section(analysis, "open_questions"),
            "",
            "## 6. 다음 회의에서 확인할 내용",
            "",
            *_analysis_section(analysis, "next_meeting_checks"),
            "",
            "## 전체 회의 기록",
            "",
        ]
    )
    segments = list(session.get("segments", []))
    if not segments:
        lines.append("저장된 확정 자막이 없습니다.")
    for segment in segments:
        language = str(segment.get("language", "unknown"))
        lines.extend(
            [
                f"### {_display_time(segment.get('started_at'))}–{_display_time(segment.get('ended_at'))} · {language}",
                "",
                "**원문**",
                "",
                str(segment.get("original_text") or "원문 저장 안 함"),
                "",
                "**한국어**",
                "",
                str(segment.get("korean_translation") or "번역 없음"),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "render_markdown",
    "render_original_txt",
    "render_translation_txt",
]
