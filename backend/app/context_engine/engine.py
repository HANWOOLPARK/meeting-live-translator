from __future__ import annotations

import json
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4


SCHEMA_VERSION = 1
ENTRY_CATEGORIES = frozenset({"term", "person"})
SUGGESTION_STATUSES = frozenset({"pending", "accepted", "ignored"})
MAX_KEYTERMS = 100
MAX_ENTRY_LENGTH = 120
MAX_VARIANTS = 20


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _clean_text(value: Any, *, maximum: int = MAX_ENTRY_LENGTH) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise ContextEngineError("invalid_context_value", "입력한 용어를 확인하세요.")
    return text


def _clean_variants(values: Iterable[Any], canonical: str) -> list[str]:
    variants: list[str] = []
    seen = {canonical.casefold()}
    for raw in values:
        value = _clean_text(raw)
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        variants.append(value)
        if len(variants) >= MAX_VARIANTS:
            break
    return variants


class ContextEngineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    original_text: str
    normalized_text: str
    matches: tuple[dict[str, str], ...]

    @property
    def changed(self) -> bool:
        return self.original_text != self.normalized_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "changed": self.changed,
            "matches": [dict(item) for item in self.matches],
        }


def _default_state() -> dict[str, Any]:
    now = _iso_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "active_profile_id": "general",
        "profiles": [
            {
                "id": "general",
                "name": "일반",
                "description": "추가 현장 용어 없이 사용하는 기본 프로필",
                "created_at": now,
                "entries": [],
            },
            {
                "id": "onion-data-center",
                "name": "ONION Data Center",
                "description": "데이터센터 회의에서 자주 쓰는 기본 용어",
                "created_at": now,
                "entries": [
                    {
                        "id": f"seed-{index}",
                        "category": "term",
                        "canonical": term,
                        "variants": [],
                        "created_at": now,
                    }
                    for index, term in enumerate(
                        (
                            "MK119",
                            "DC OS",
                            "Fit & Gap",
                            "BMS",
                            "RMS",
                            "Data Center",
                            "PrimeDrive",
                            "SoftBank",
                            "Fuji IT",
                            "ONION Technology",
                        )
                    )
                ],
            },
        ],
        "suggestions": [],
    }


class ContextEngine:
    """Persistent, user-controlled context profiles.

    The engine never edits a transcript. It returns a derived normalized value
    and only changes a profile when the user explicitly creates or accepts an
    entry.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            state = _default_state()
            self._write(state)
            return state
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("state must be an object")
            self._validate_state(payload)
            return payload
        except ContextEngineError:
            raise
        except Exception as error:
            raise ContextEngineError(
                "context_storage_invalid",
                "Context Engine 설정 파일을 읽을 수 없습니다.",
            ) from error

    def _write(self, state: Mapping[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(state), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _validate_state(state: Mapping[str, Any]) -> None:
        profiles = state.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            raise ContextEngineError("context_storage_invalid", "Context Engine 프로필이 없습니다.")
        ids: set[str] = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ContextEngineError("context_storage_invalid", "Context Engine 프로필이 올바르지 않습니다.")
            profile_id = str(profile.get("id", "")).strip()
            if not profile_id or profile_id in ids:
                raise ContextEngineError("context_storage_invalid", "Context Engine 프로필 ID가 올바르지 않습니다.")
            ids.add(profile_id)
            if not isinstance(profile.get("entries", []), list):
                raise ContextEngineError("context_storage_invalid", "Context Engine 용어 목록이 올바르지 않습니다.")
        if str(state.get("active_profile_id", "")) not in ids:
            raise ContextEngineError("context_storage_invalid", "활성 Context Engine 프로필이 올바르지 않습니다.")
        if not isinstance(state.get("suggestions", []), list):
            raise ContextEngineError("context_storage_invalid", "Context Engine 추천 목록이 올바르지 않습니다.")

    def _profile(self, profile_id: str | None = None) -> dict[str, Any]:
        wanted = str(profile_id or self._state["active_profile_id"]).strip()
        for profile in self._state["profiles"]:
            if profile["id"] == wanted:
                return profile
        raise ContextEngineError("context_profile_not_found", "Context 프로필을 찾을 수 없습니다.")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active_id = str(self._state["active_profile_id"])
            profiles = json.loads(json.dumps(self._state["profiles"], ensure_ascii=False))
            suggestions = [
                dict(item)
                for item in self._state["suggestions"]
                if item.get("profile_id") == active_id and item.get("status") == "pending"
            ]
            return {
                "schema_version": SCHEMA_VERSION,
                "active_profile_id": active_id,
                "profiles": profiles,
                "suggestions": suggestions,
                "keyterm_limit": MAX_KEYTERMS,
                "keyterm_count": len(self.keyterms()),
                "consent_required": True,
            }

    def create_profile(self, name: str, description: str = "") -> dict[str, Any]:
        with self._lock:
            cleaned_name = _clean_text(name, maximum=60)
            if any(item["name"].casefold() == cleaned_name.casefold() for item in self._state["profiles"]):
                raise ContextEngineError("context_profile_exists", "같은 이름의 프로필이 이미 있습니다.")
            profile = {
                "id": f"profile-{uuid4().hex[:12]}",
                "name": cleaned_name,
                "description": " ".join(str(description or "").split())[:240],
                "created_at": _iso_now(),
                "entries": [],
            }
            self._state["profiles"].append(profile)
            self._state["active_profile_id"] = profile["id"]
            self._write(self._state)
            return dict(profile)

    def activate_profile(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            profile = self._profile(profile_id)
            self._state["active_profile_id"] = profile["id"]
            self._write(self._state)
            return self.snapshot()

    def add_entry(
        self,
        profile_id: str,
        *,
        category: str,
        canonical: str,
        variants: Iterable[str] = (),
    ) -> dict[str, Any]:
        with self._lock:
            profile = self._profile(profile_id)
            normalized_category = str(category).strip().lower()
            if normalized_category not in ENTRY_CATEGORIES:
                raise ContextEngineError("invalid_context_category", "용어 종류를 확인하세요.")
            cleaned_canonical = _clean_text(canonical)
            cleaned_variants = _clean_variants(variants, cleaned_canonical)
            requested_values = {cleaned_canonical.casefold(), *(value.casefold() for value in cleaned_variants)}
            for entry in profile["entries"]:
                values = [entry.get("canonical", ""), *entry.get("variants", [])]
                if requested_values.intersection(str(value).casefold() for value in values):
                    raise ContextEngineError("context_entry_exists", "이미 등록된 용어 또는 이름입니다.")
            entry = {
                "id": f"entry-{uuid4().hex[:12]}",
                "category": normalized_category,
                "canonical": cleaned_canonical,
                "variants": cleaned_variants,
                "created_at": _iso_now(),
            }
            profile["entries"].append(entry)
            self._write(self._state)
            return dict(entry)

    def delete_entry(self, profile_id: str, entry_id: str) -> dict[str, Any]:
        with self._lock:
            profile = self._profile(profile_id)
            before = len(profile["entries"])
            profile["entries"] = [item for item in profile["entries"] if item.get("id") != entry_id]
            if len(profile["entries"]) == before:
                raise ContextEngineError("context_entry_not_found", "삭제할 용어를 찾을 수 없습니다.")
            self._write(self._state)
            return self.snapshot()

    def _active_entries(self) -> list[dict[str, Any]]:
        return list(self._profile()["entries"])

    def glossary_terms(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(dict.fromkeys(str(item["canonical"]) for item in self._active_entries()))

    def keyterms(self) -> tuple[str, ...]:
        with self._lock:
            values: list[str] = []
            seen: set[str] = set()
            for entry in self._active_entries():
                for raw in [entry["canonical"], *entry.get("variants", [])]:
                    value = str(raw).strip()
                    key = value.casefold()
                    if value and key not in seen:
                        seen.add(key)
                        values.append(value)
                    if len(values) >= MAX_KEYTERMS:
                        return tuple(values)
            return tuple(values)

    def normalize(self, text: str) -> NormalizationResult:
        original = str(text).strip()
        matches: list[dict[str, str]] = []
        matched_entry_ids: set[str] = set()
        with self._lock:
            candidates: list[tuple[str, dict[str, Any]]] = []
            for entry in self._active_entries():
                for variant in [entry.get("canonical", ""), *entry.get("variants", [])]:
                    if str(variant).strip():
                        candidates.append((str(variant), entry))
            candidates.sort(key=lambda item: len(item[0]), reverse=True)
            lookup = {variant.casefold(): (variant, entry) for variant, entry in candidates}
            alternatives: list[str] = []
            for variant, _ in candidates:
                escaped = re.escape(variant)
                if variant[0].isascii() and variant[-1].isascii() and (
                    variant[0].isalnum() and variant[-1].isalnum()
                ):
                    escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
                alternatives.append(escaped)
            if not alternatives:
                return NormalizationResult(original, original, ())
            pattern = re.compile("|".join(f"(?:{value})" for value in alternatives), re.IGNORECASE)

            def replace(match: re.Match[str]) -> str:
                matched = match.group(0)
                variant, entry = lookup[matched.casefold()]
                canonical = str(entry["canonical"])
                entry_id = str(entry["id"])
                if entry_id not in matched_entry_ids:
                    matched_entry_ids.add(entry_id)
                    matches.append(
                        {
                            "entry_id": entry_id,
                            "category": str(entry["category"]),
                            "from": matched,
                            "to": canonical,
                            "canonical": canonical,
                        }
                    )
                if matched == canonical:
                    return matched
                return canonical

            normalized = pattern.sub(replace, original)
        return NormalizationResult(original, normalized, tuple(matches))

    @staticmethod
    def _candidate_occurrences(
        segments: Iterable[Mapping[str, Any]],
    ) -> tuple[Counter[tuple[str, str]], dict[tuple[str, str], list[str]], dict[tuple[str, str], str]]:
        counts: Counter[tuple[str, str]] = Counter()
        evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
        reasons: dict[tuple[str, str], str] = {}
        honorific = re.compile(r"([一-龯々ぁ-んァ-ヶー가-힣]{2,12})(?:さん|様|氏|님|씨)")
        acronym = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9&.-]{1,15})(?![A-Za-z0-9])")
        camel = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][a-z0-9]+){2,}(?![A-Za-z0-9])")
        katakana = re.compile(r"[ァ-ヶー]{3,20}")
        for segment in segments:
            text = str(segment.get("original_text", segment.get("text", "")) or "")
            segment_id = str(segment.get("segment_id", "")).strip()
            found: set[tuple[str, str]] = set()
            for match in honorific.finditer(text):
                found.add(("person", match.group(1)))
                reasons[("person", match.group(1))] = "이름 호칭과 함께 반복된 표현"
            for pattern, reason in (
                (acronym, "영문 약어 또는 고유 표기"),
                (camel, "제품명 또는 고유 표기"),
                (katakana, "가타카나 고유어 후보"),
            ):
                for match in pattern.finditer(text):
                    value = match.group(0).strip(".-")
                    if len(value) >= 2:
                        found.add(("term", value))
                        reasons[("term", value)] = reason
            for key in found:
                counts[key] += 1
                if segment_id and segment_id not in evidence[key] and len(evidence[key]) < 5:
                    evidence[key].append(segment_id)
        return counts, evidence, reasons

    def generate_suggestions(
        self,
        session_id: str,
        segments: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        with self._lock:
            profile = self._profile()
            known = {
                str(value).casefold()
                for entry in profile["entries"]
                for value in [entry.get("canonical", ""), *entry.get("variants", [])]
                if str(value).strip()
            }
            existing = {
                (str(item.get("profile_id")), str(item.get("canonical", "")).casefold())
                for item in self._state["suggestions"]
                if item.get("status") in SUGGESTION_STATUSES
            }
            counts, evidence, reasons = self._candidate_occurrences(segments)
            created: list[dict[str, Any]] = []
            for (category, canonical), occurrences in counts.most_common(30):
                key = canonical.casefold()
                if key in known or (profile["id"], key) in existing:
                    continue
                suggestion = {
                    "id": f"suggestion-{uuid4().hex[:12]}",
                    "profile_id": profile["id"],
                    "session_id": str(session_id),
                    "category": category,
                    "canonical": canonical,
                    "variants": [],
                    "occurrences": occurrences,
                    "evidence_segment_ids": evidence[(category, canonical)],
                    "reason": reasons.get((category, canonical), "회의에서 발견된 고유 표현"),
                    "status": "pending",
                    "created_at": _iso_now(),
                }
                self._state["suggestions"].append(suggestion)
                created.append(dict(suggestion))
            if created:
                self._write(self._state)
            return created

    def decide_suggestion(
        self,
        suggestion_id: str,
        *,
        accept: bool,
        canonical: str | None = None,
        category: str | None = None,
        variants: Iterable[str] = (),
    ) -> dict[str, Any]:
        with self._lock:
            suggestion = next(
                (item for item in self._state["suggestions"] if item.get("id") == suggestion_id),
                None,
            )
            if suggestion is None:
                raise ContextEngineError("context_suggestion_not_found", "추천 항목을 찾을 수 없습니다.")
            if suggestion.get("status") != "pending":
                raise ContextEngineError("context_suggestion_resolved", "이미 처리한 추천 항목입니다.")
            if accept:
                entry = self.add_entry(
                    str(suggestion["profile_id"]),
                    category=category or str(suggestion["category"]),
                    canonical=canonical or str(suggestion["canonical"]),
                    variants=[*suggestion.get("variants", []), *variants],
                )
                suggestion["status"] = "accepted"
                suggestion["resolved_at"] = _iso_now()
                suggestion["entry_id"] = entry["id"]
            else:
                suggestion["status"] = "ignored"
                suggestion["resolved_at"] = _iso_now()
                entry = None
            self._write(self._state)
            return {"suggestion": dict(suggestion), "entry": entry, "context": self.snapshot()}


__all__ = ["ContextEngine", "ContextEngineError", "NormalizationResult"]
