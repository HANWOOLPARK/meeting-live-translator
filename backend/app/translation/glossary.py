"""One central glossary shared by every translation provider."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_GLOSSARY_TERMS: tuple[str, ...] = (
    "MK119",
    "DC OS",
    "Fit & Gap",
    "BMS",
    "RMS",
    "Data Center",
    "Requirements Definition",
    "Basic Design",
    "Detailed Design",
    "System Test",
    "Operation Test",
    "PrimeDrive",
    "SoftBank",
    "Fuji IT",
    "ONION Technology",
)
MAX_PROMPT_GLOSSARY_TERMS = 10


def merge_glossary_terms(*groups: Iterable[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw_term in group:
            term = str(raw_term).strip()
            key = term.casefold()
            if term and key not in seen:
                seen.add(key)
                merged.append(term)
    return tuple(merged)


def select_relevant_glossary_terms(
    terms: Iterable[str],
    texts: Iterable[str],
    *,
    limit: int = MAX_PROMPT_GLOSSARY_TERMS,
) -> tuple[str, ...]:
    """Select only terms that occur in the current bounded text context."""

    if limit <= 0:
        return ()
    normalized_texts = tuple(
        unicodedata.normalize("NFKC", str(text)).casefold()
        for text in texts
        if str(text).strip()
    )
    if not normalized_texts:
        return ()
    selected: list[str] = []
    for term in merge_glossary_terms(terms):
        normalized_term = unicodedata.normalize("NFKC", term).casefold()
        if not normalized_term:
            continue
        if normalized_term[0].isascii() and normalized_term[-1].isascii() and (
            normalized_term[0].isalnum() and normalized_term[-1].isalnum()
        ):
            pattern = re.compile(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
            )
            matched = any(pattern.search(text) for text in normalized_texts)
        else:
            matched = any(normalized_term in text for text in normalized_texts)
        if matched:
            selected.append(term)
            if len(selected) >= limit:
                break
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class TranslationGlossary:
    terms: tuple[str, ...] = DEFAULT_GLOSSARY_TERMS

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms", merge_glossary_terms(self.terms))

    def extend(self, custom_terms: Iterable[str]) -> "TranslationGlossary":
        return TranslationGlossary(merge_glossary_terms(self.terms, custom_terms))

    def prompt_block(self) -> str:
        return "\n".join(f"- {term}" for term in self.terms)


def load_glossary_file(path: str | Path | None) -> TranslationGlossary:
    """Load optional user terms from a local JSON list or ``{"terms": [...]}``."""

    if path is None:
        return TranslationGlossary()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("terms")
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("Translation glossary must contain a JSON string list")
    return TranslationGlossary().extend(payload)


def protect_glossary_terms(
    text: str,
    terms: Iterable[str],
) -> tuple[str, dict[str, str]]:
    """Replace glossary matches with stable placeholders for local models."""

    protected = str(text)
    replacements: dict[str, str] = {}
    ordered = sorted(merge_glossary_terms(terms), key=len, reverse=True)
    for term in ordered:
        pattern = re.compile(re.escape(term), re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            marker = f"__MLT_TERM_{len(replacements)}__"
            replacements[marker] = match.group(0)
            return marker

        protected = pattern.sub(replace, protected)
    return protected, replacements


def restore_glossary_terms(text: str, replacements: dict[str, str]) -> str:
    restored = str(text)
    for placeholder, original in replacements.items():
        marker = re.fullmatch(r"__MLT_TERM_(\d+)__", placeholder, flags=re.IGNORECASE)
        if marker:
            # SentencePiece models can collapse one of the surrounding underscores
            # or insert spaces around marker components.  Match only markers that
            # this function injected, while accepting those deterministic changes.
            index = re.escape(marker.group(1))
            pattern = rf"_*\s*MLT\s*_\s*TERM\s*_\s*{index}\s*_*"
        else:
            pattern = re.escape(placeholder)
        restored = re.sub(pattern, original, restored, flags=re.IGNORECASE)
    return restored


__all__ = [
    "DEFAULT_GLOSSARY_TERMS",
    "TranslationGlossary",
    "merge_glossary_terms",
    "select_relevant_glossary_terms",
    "load_glossary_file",
    "protect_glossary_terms",
    "restore_glossary_terms",
]
