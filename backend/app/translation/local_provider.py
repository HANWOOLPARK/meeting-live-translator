"""Local-only, installation-detecting M2M100/CTranslate2 provider."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from .base import TranslationProvider
from .exceptions import TranslationErrorCode, normalize_provider_error, translation_error
from .glossary import (
    DEFAULT_GLOSSARY_TERMS,
    merge_glossary_terms,
    protect_glossary_terms,
    restore_glossary_terms,
)
from .models import (
    ProviderHealth,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    iso_now,
)


TranslatorFactory = Callable[[str, Path], Callable[[str], Any]]
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


class _M2M100CTranslate2Translator:
    """Minimal adapter for a locally converted M2M100 model directory."""

    def __init__(self, source_language: str, model_path: Path) -> None:
        import ctranslate2
        from transformers import M2M100Tokenizer

        self.source_language = source_language
        self.tokenizer = M2M100Tokenizer.from_pretrained(
            str(model_path),
            local_files_only=True,
        )
        self.translator = ctranslate2.Translator(
            str(model_path),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=2,
        )

    def __call__(self, text: str) -> str:
        language = "ja" if self.source_language == "ja" else "en"
        self.tokenizer.src_lang = language
        source_ids = self.tokenizer.encode(text)
        source_tokens = self.tokenizer.convert_ids_to_tokens(source_ids)
        target_id = self.tokenizer.get_lang_id("ko")
        target_token = self.tokenizer.convert_ids_to_tokens([target_id])[0]
        result = self.translator.translate_batch(
            [source_tokens],
            target_prefix=[[target_token]],
            beam_size=1,
        )[0]
        target_tokens = list(result.hypotheses[0])
        if target_tokens and target_tokens[0] == target_token:
            target_tokens.pop(0)
        target_ids = self.tokenizer.convert_tokens_to_ids(target_tokens)
        return self.tokenizer.decode(target_ids, skip_special_tokens=True)


def _default_translator_factory(language: str, model_path: Path) -> Callable[[str], str]:
    return _M2M100CTranslate2Translator(language, model_path)


class LocalTranslationProvider(TranslationProvider):
    provider_name = "local"
    display_name = "로컬 번역"
    external = False

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        ja_model_path: str | Path | None = None,
        en_model_path: str | Path | None = None,
        translator_factory: TranslatorFactory | None = None,
    ) -> None:
        common = self._path(model_path)
        self._model_paths = {
            "ja": self._path(ja_model_path) or common,
            "en": self._path(en_model_path) or common,
        }
        self._translator_factory = translator_factory or _default_translator_factory
        self._factory_injected = translator_factory is not None
        self._translators: dict[str, Callable[[str], Any]] = {}
        self._load_locks = {"ja": asyncio.Lock(), "en": asyncio.Lock()}
        self._closed = False

    @staticmethod
    def _path(value: str | Path | None) -> Path | None:
        if value is None or not str(value).strip():
            return None
        return Path(value).expanduser()

    @staticmethod
    def _model_installed(path: Path | None) -> bool:
        if path is None or not path.is_dir():
            return False
        required = (
            "model.bin",
            "config.json",
            "shared_vocabulary.json",
            "vocab.json",
        )
        return all((path / filename).is_file() for filename in required) and any(
            (path / filename).is_file()
            for filename in ("sentencepiece.bpe.model", "sentencepiece.model")
        )

    def _dependencies_installed(self) -> bool:
        if self._factory_injected:
            return True
        try:
            return all(
                importlib.util.find_spec(module) is not None
                for module in ("ctranslate2", "transformers", "sentencepiece")
            )
        except (ImportError, ValueError):
            return False

    async def health_check(self) -> ProviderHealth:
        paths_ready = all(self._model_installed(path) for path in self._model_paths.values())
        dependencies_ready = self._dependencies_installed()
        available = paths_ready and dependencies_ready and not self._closed
        if self._closed:
            reason = "번역 Provider가 종료되었습니다."
        elif not paths_ready:
            reason = "로컬 번역 모델이 설치되지 않았습니다. 원문 전사는 계속 사용할 수 있습니다."
        elif not dependencies_ready:
            reason = "로컬 번역 선택 의존성이 설치되지 않았습니다."
        else:
            reason = None
        model_names = sorted({path.name for path in self._model_paths.values() if path})
        return ProviderHealth(
            provider_id=self.provider_name,
            name=self.display_name,
            available=available,
            external=False,
            reason=reason,
            model=" / ".join(model_names) or None,
        )

    @staticmethod
    def _route_language(request: TranslationRequest) -> str:
        if request.source_language in {"ja", "en"}:
            return request.source_language
        if request.source_language == "mixed":
            return "ja" if _JAPANESE_RE.search(request.source_text) else "en"
        raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)

    async def _translator(self, language: str) -> Callable[[str], Any]:
        existing = self._translators.get(language)
        if existing is not None:
            return existing
        async with self._load_locks[language]:
            existing = self._translators.get(language)
            if existing is not None:
                return existing
            path = self._model_paths[language]
            if (
                self._closed
                or not self._model_installed(path)
                or not self._dependencies_installed()
            ):
                raise translation_error(TranslationErrorCode.PROVIDER_UNAVAILABLE)
            assert path is not None
            try:
                translator = await asyncio.to_thread(self._translator_factory, language, path)
            except Exception as error:
                raise normalize_provider_error(error) from error
            self._translators[language] = translator
            return translator

    @staticmethod
    def _translated_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            text = value.get("translation_text") or value.get("generated_text")
            return text.strip() if isinstance(text, str) else ""
        if isinstance(value, list) and value:
            return LocalTranslationProvider._translated_text(value[0])
        return ""

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if request.target_language != "ko":
            raise translation_error(TranslationErrorCode.UNSUPPORTED_LANGUAGE)
        language = self._route_language(request)
        translator = await self._translator(language)
        glossary = merge_glossary_terms(DEFAULT_GLOSSARY_TERMS, request.glossary_terms)
        protected_text, replacements = protect_glossary_terms(request.source_text, glossary)
        started = perf_counter()
        try:
            raw_result = await asyncio.to_thread(translator, protected_text)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
        except Exception as error:
            raise normalize_provider_error(error) from error
        translated = restore_glossary_terms(
            self._translated_text(raw_result),
            replacements,
        ).strip()
        if not translated:
            raise translation_error(TranslationErrorCode.INVALID_RESPONSE)
        path = self._model_paths[language]
        return TranslationResult(
            segment_id=request.segment_id,
            session_id=request.session_id,
            source_text=request.source_text,
            translated_text=translated,
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.provider_name,
            model=path.name if path else None,
            status=TranslationStatus.COMPLETED,
            requested_at=request.requested_at,
            completed_at=iso_now(),
            latency_ms=max(0, round((perf_counter() - started) * 1_000)),
        )

    async def close(self) -> None:
        self._closed = True
        translators, self._translators = list(self._translators.values()), {}
        for translator in translators:
            closer = getattr(translator, "close", None)
            if closer is None:
                continue
            result = closer()
            if inspect.isawaitable(result):
                await result


__all__ = ["LocalTranslationProvider"]
