"""Conservative Japanese/English language presentation policy."""

from __future__ import annotations

import math
import re


_JAPANESE_CHARACTER_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]"
)
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


def classify_language(
    raw_language: str | None,
    probability: float | None,
    text: str,
    *,
    minimum_probability: float = 0.60,
) -> str:
    """Map model output to ``ja``, ``en``, ``mixed`` or ``unknown``.

    The model language is authoritative for the supported-language gate.  A
    low-confidence or unsupported model result is never guessed from Unicode
    characters.  ``mixed`` requires substantial evidence from both scripts;
    a Japanese sentence containing one or two English technical terms remains
    Japanese, as required by the Phase 1 product policy.
    """

    language = (raw_language or "").strip().lower().replace("_", "-")
    if language.startswith("ja-"):
        language = "ja"
    elif language.startswith("en-"):
        language = "en"

    try:
        confidence = float(probability) if probability is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0

    if (
        language not in {"ja", "en"}
        or not math.isfinite(confidence)
        or confidence < minimum_probability
        or not text.strip()
    ):
        return "unknown"

    japanese_count = len(_JAPANESE_CHARACTER_RE.findall(text))
    english_words = _ENGLISH_WORD_RE.findall(text)
    latin_count = sum(len(word.replace("-", "").replace("'", "")) for word in english_words)

    # Three English lexical words avoids treating common tokens such as API,
    # Zoom, or Python as a language switch.  The ratio check also prevents a
    # long sentence with a tiny foreign fragment from being labelled mixed.
    if japanese_count >= 3 and len(english_words) >= 3:
        script_total = japanese_count + latin_count
        minority_ratio = min(japanese_count, latin_count) / script_total if script_total else 0.0
        if minority_ratio >= 0.20:
            return "mixed"

    return language
