"""Conservative, non-generative multilingual meeting signal extraction."""

from __future__ import annotations

import re
import unicodedata

from .base import AnalysisProvider
from .models import (
    ActionItem,
    AnalysisProviderHealth,
    AnalysisRequest,
    AnalysisStatus,
    EvidenceItem,
    MeetingAnalysis,
    UNDECIDED,
)


_DECISION = re.compile(
    r"(?:\bdecided\b|\bagreed\b|決定しました|決まりました|合意しました|"
    r"결정했습니다|합의했습니다|하기로\s*했습니다)",
    re.IGNORECASE,
)
_NEGATED_DECISION = re.compile(
    r"(?:\b(?:not|never|haven['’]t|hasn['’]t|hadn['’]t|didn['’]t)\b"
    r"|\b(?:have|has|had|did)\s+not\b)"
    r"[^.!?？。]{0,48}\b(?:decided|agreed)\b",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"(?:\baction\s*item\b|\btodo\b|\b[A-Z][a-z]{1,30}\s+will\b|"
    r"\bplease\b|担当\s*[:：]|期限\s*[:：]|までに|お願いします|対応します|"
    r"確認します|확인하겠습니다|대응하겠습니다|담당\s*[:：]|까지\s+.*(?:합니다|하겠습니다))",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"(?:[?？]\s*$|\b(?:who|what|when|where|why|how)\b.*[?？]?\s*$|"
    r"(?:いつ|誰|どのように|どうしますか)|(?:누가|언제|어떻게|무엇을).*(?:까|나요))",
    re.IGNORECASE,
)
_NEXT_MEETING = re.compile(r"(?:\bnext\s+meeting\b|次回(?:会議)?|다음\s*회의)", re.IGNORECASE)
_DUE_DATE = re.compile(r"\b20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b")
_LOCALIZED_DUE_DATES = (
    re.compile(
        r"(?:20\d{2}年)?(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
        r"(?:\s*(?:までに?|迄に?))?"
    ),
    re.compile(
        r"(?:20\d{2}년\s*)?(?:0?[1-9]|1[0-2])월\s*"
        r"(?:0?[1-9]|[12]\d|3[01])일(?:\s*까지)?"
    ),
    re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(?:0?[1-9]|[12]\d|3[01])"
        r"(?:,\s*20\d{2})?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:0?[1-9]|[12]\d|3[01])\s+"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)(?:\s+20\d{2})?\b",
        re.IGNORECASE,
    ),
)
_RELATIVE_DUE = re.compile(
    r"(?:\bby\s+(?:next|this)\s+(?:week|month|monday|tuesday|wednesday|thursday|friday)|"
    r"(?:다음|이번)\s*(?:주|달)까지|来週まで|今週まで)",
    re.IGNORECASE,
)
_ASSIGNEE_PATTERNS = (
    re.compile(r"(?:assignee|owner|담당|担当)\s*[:：]\s*([A-Za-z가-힣ぁ-んァ-ヶ一-龠]{2,30})", re.IGNORECASE),
    re.compile(r"\b([A-Z][a-z]{1,30})\s+will\b"),
    re.compile(r"([가-힣]{2,4})(?:님|씨)(?:이|가|은|는)\s"),
    re.compile(r"([ぁ-んァ-ヶ一-龠]{2,12})さん(?:が|は)"),
)
_AMBIGUOUS = {
    "we",
    "they",
    "team",
    "ourteam",
    "theteam",
    "우리",
    "우리팀",
    "저희",
    "저희팀",
    "담당팀",
    "私たち",
    "我々",
    "担当チーム",
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
}


def _normalized(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def _assignee(text: str) -> str:
    for pattern in _ASSIGNEE_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if _normalized(candidate) not in {_normalized(value) for value in _AMBIGUOUS}:
                return candidate
    return UNDECIDED


def _due_date(text: str) -> str:
    match = _DUE_DATE.search(text)
    if match:
        return match.group(0)
    for pattern in _LOCALIZED_DUE_DATES:
        match = pattern.search(text)
        if match:
            return match.group(0)
    relative = _RELATIVE_DUE.search(text)
    return relative.group(0) if relative else UNDECIDED


def _deduplicate(items: list[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[EvidenceItem] = []
    for item in items:
        key = (_normalized(item.text), item.evidence_segment_ids)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


class RuleBasedAnalysisProvider(AnalysisProvider):
    provider_name = "rule_based"
    display_name = "보수적 규칙 기반 분석"
    external = False

    async def analyze(self, request: AnalysisRequest) -> MeetingAnalysis:
        decisions: list[EvidenceItem] = []
        actions: list[ActionItem] = []
        questions: list[EvidenceItem] = []
        next_checks: list[EvidenceItem] = []

        for segment in request.segments:
            # Original has priority. Korean is used only when the original was
            # intentionally not stored; the two are never concatenated into a
            # potentially conflicting synthetic statement.
            text = segment.preferred_text.strip()
            evidence = (segment.segment_id,)
            is_question = _QUESTION.search(text) is not None
            if _DECISION.search(text) and not _NEGATED_DECISION.search(text):
                decisions.append(EvidenceItem(text, evidence))
            if _ACTION.search(text) and not is_question:
                actions.append(
                    ActionItem(
                        task=text,
                        assignee=_assignee(text),
                        due_date=_due_date(text),
                        evidence_segment_ids=evidence,
                    )
                )
            if is_question:
                questions.append(EvidenceItem(text, evidence))
            if _NEXT_MEETING.search(text):
                next_checks.append(EvidenceItem(text, evidence))

        return MeetingAnalysis(
            session_id=request.session_id,
            provider=self.provider_name,
            model=None,
            status=AnalysisStatus.COMPLETED,
            meeting_purpose=EvidenceItem(UNDECIDED),
            key_discussions=(),
            decisions=_deduplicate(decisions),
            action_items=tuple(actions),
            open_questions=_deduplicate(questions),
            next_meeting_checks=_deduplicate(next_checks),
            warnings=("rule_based_does_not_generate_summary",),
        )

    async def health_check(self) -> AnalysisProviderHealth:
        return AnalysisProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=True,
            external=False,
        )

    async def close(self) -> None:
        return None


__all__ = ["RuleBasedAnalysisProvider"]
