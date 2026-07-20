"""Isolated CTranslate2 M2M100 worker used only by the translation PoC.

The worker owns every optional local-translation dependency.  It reads one
JSON object per line from stdin and writes one JSON object per line to stdout.
This keeps Transformers and SentencePiece out of the main project virtualenv.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


PROCESS_STARTED = perf_counter()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.translation.glossary import (  # noqa: E402
    DEFAULT_GLOSSARY_TERMS,
    merge_glossary_terms,
    protect_glossary_terms,
    restore_glossary_terms,
)


REQUIRED_MODEL_FILES = (
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "sentencepiece.bpe.model",
    "vocab.json",
)
MODEL_REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _memory_snapshot(psutil_module: Any, process: Any) -> dict[str, float | int]:
    virtual = psutil_module.virtual_memory()
    return {
        "process_rss_bytes": int(process.memory_info().rss),
        "system_total_bytes": int(virtual.total),
        "system_available_bytes": int(virtual.available),
        "system_used_percent": round(float(virtual.percent), 3),
    }


class M2M100Runtime:
    def __init__(self, model_path: Path) -> None:
        missing = [name for name in REQUIRED_MODEL_FILES if not (model_path / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Incomplete CT2 model: missing {', '.join(missing)}")

        import ctranslate2
        import psutil
        from transformers import M2M100Tokenizer

        self.psutil = psutil
        self.process = psutil.Process(os.getpid())
        self.priority = "unchanged"
        if os.name == "nt":
            try:
                self.process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                self.priority = "below_normal"
            except (psutil.AccessDenied, OSError):
                self.priority = "unchanged_access_denied"

        self.model_path = model_path
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
        self.process.cpu_percent(None)
        psutil.cpu_percent(None)
        self.ready = {
            "type": "ready",
            "pid": os.getpid(),
            "model_path": str(model_path),
            "model_revision": MODEL_REVISION,
            "device": "cpu",
            "compute_type": "int8",
            "inter_threads": 1,
            "intra_threads": 2,
            "translation_concurrency": 1,
            "beam_size": 1,
            "process_priority": self.priority,
            "cold_start_ms": round((perf_counter() - PROCESS_STARTED) * 1000, 3),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "ctranslate2",
                    "transformers",
                    "sentencepiece",
                    "huggingface-hub",
                    "tokenizers",
                    "sacremoses",
                    "psutil",
                )
            },
            **_memory_snapshot(psutil, self.process),
        }

    def translate(
        self,
        text: str,
        source_language: str,
        glossary_terms: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        if source_language not in {"ja", "en"}:
            raise ValueError("source_language must be ja or en")
        source = str(text).strip()
        if not source:
            raise ValueError("text must not be empty")

        glossary = merge_glossary_terms(DEFAULT_GLOSSARY_TERMS, glossary_terms)
        protected, replacements = protect_glossary_terms(source, glossary)
        self.tokenizer.src_lang = source_language
        source_ids = self.tokenizer.encode(protected)
        source_tokens = self.tokenizer.convert_ids_to_tokens(source_ids)
        target_id = self.tokenizer.get_lang_id("ko")
        target_token = self.tokenizer.convert_ids_to_tokens([target_id])[0]

        self.process.cpu_percent(None)
        self.psutil.cpu_percent(None)
        started = perf_counter()
        result = self.translator.translate_batch(
            [source_tokens],
            target_prefix=[[target_token]],
            beam_size=1,
        )[0]
        completed = perf_counter()

        target_tokens = list(result.hypotheses[0])
        if target_tokens and target_tokens[0] == target_token:
            target_tokens.pop(0)
        target_ids = self.tokenizer.convert_tokens_to_ids(target_tokens)
        model_text = self.tokenizer.decode(target_ids, skip_special_tokens=True).strip()
        translated = restore_glossary_terms(model_text, replacements).strip()
        if not translated:
            raise RuntimeError("Model returned an empty translation")

        source_terms = [term for term in glossary if term.casefold() in source.casefold()]
        missing_terms = [term for term in source_terms if term.casefold() not in translated.casefold()]
        return {
            "translation": translated,
            "raw_model_text": model_text,
            "protected_source": protected,
            "source_language": source_language,
            "target_language": "ko",
            "latency_ms": round((completed - started) * 1000, 3),
            "process_cpu_percent": round(float(self.process.cpu_percent(None)), 3),
            "system_cpu_percent": round(float(self.psutil.cpu_percent(None)), 3),
            "source_glossary_terms": source_terms,
            "missing_glossary_terms": missing_terms,
            **_memory_snapshot(self.psutil, self.process),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translation PoC M2M100 JSONL worker")
    parser.add_argument("--model", required=True, type=Path)
    return parser


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    args = _parser().parse_args()
    try:
        runtime = M2M100Runtime(args.model.resolve())
    except Exception as error:
        _emit({"type": "startup_error", "error_type": type(error).__name__, "message": str(error)})
        return 2

    _emit(runtime.ready)
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            command = request.get("command")
            request_id = str(request.get("id", ""))
            if command == "shutdown":
                _emit({"type": "shutdown", "id": request_id, "pid": os.getpid()})
                return 0
            if command == "ping":
                _emit({"type": "pong", "id": request_id, "pid": os.getpid()})
                continue
            if command != "translate":
                raise ValueError("Unsupported command")
            payload = runtime.translate(
                request.get("text", ""),
                request.get("source_language", ""),
                request.get("glossary_terms", []),
            )
            _emit({"type": "translation", "id": request_id, **payload})
        except Exception as error:
            _emit(
                {
                    "type": "error",
                    "id": str(locals().get("request", {}).get("id", "")),
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
