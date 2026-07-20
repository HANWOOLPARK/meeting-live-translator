from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.transcription.engine import FasterWhisperEngine


@dataclass
class FakeSegment:
    text: str
    start: float
    end: float


@dataclass
class FakeInfo:
    language: str
    language_probability: float


class ScriptedModel:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.languages = []

    def transcribe(self, samples, *, language):
        assert samples.dtype == np.float32
        self.languages.append(language)
        segments, info = self.scripts.pop(0)

        # faster-whisper returns a lazy segment iterator; using a generator here
        # ensures the adapter really consumes it before returning.
        def generate():
            yield from segments

        return generate(), info


def test_engine_is_lazy_and_falls_back_from_cuda_construction_to_cpu_int8():
    calls = []
    cpu_model = ScriptedModel(
        [([FakeSegment(" hello", 0.2, 0.7), FakeSegment("world ", 0.8, 1.4)], FakeInfo("en", 0.94))]
    )

    def factory(model_name, *, device, compute_type):
        calls.append((model_name, device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA driver unavailable")
        return cpu_model

    engine = FasterWhisperEngine(model_factory=factory)
    assert calls == []
    assert engine.model_info()["loaded"] is False

    result = engine.transcribe(np.ones(16_000, dtype=np.float32))

    assert calls == [("small", "cuda", "float16"), ("small", "cpu", "int8")]
    assert result.text == "hello world"
    assert result.detected_language == "en"
    assert result.language_probability == 0.94
    assert result.started_offset == 0.2
    assert result.ended_offset == 1.4
    assert result.inference_seconds >= 0.0
    assert cpu_model.languages == [None]
    assert engine.model_info() | {} == {
        "model_name": "small",
        "loaded": True,
        "device": "cpu",
        "compute_type": "int8",
        "prefer_cuda": True,
        "cuda_fallback": True,
        "cuda_error": "RuntimeError: CUDA driver unavailable",
    }


def test_engine_redetects_language_for_every_utterance():
    model = ScriptedModel(
        [
            ([FakeSegment("こんにちは", 0.0, 0.5)], FakeInfo("ja", 0.99)),
            ([FakeSegment("Good morning", 0.0, 0.6)], FakeInfo("en", 0.97)),
        ]
    )
    engine = FasterWhisperEngine(
        model_factory=lambda *args, **kwargs: model,
        prefer_cuda=False,
    )

    first = engine.transcribe(np.zeros(8_000, dtype=np.float32))
    second = engine.transcribe(np.zeros(9_600, dtype=np.float32))

    assert (first.detected_language, second.detected_language) == ("ja", "en")
    assert model.languages == [None, None]


def test_engine_does_not_insert_spaces_between_japanese_segments():
    model = ScriptedModel(
        [
            (
                [FakeSegment("現在", 0.0, 0.2), FakeSegment("確認しています", 0.2, 0.7)],
                FakeInfo("ja", 0.98),
            )
        ]
    )
    engine = FasterWhisperEngine(
        model_factory=lambda *args, **kwargs: model,
        prefer_cuda=False,
    )
    result = engine.transcribe(np.zeros(11_200, dtype=np.float32))
    assert result.text == "現在確認しています"


def test_cuda_lazy_iterator_failure_rebuilds_on_cpu_and_retries_once():
    class BrokenCudaModel:
        def transcribe(self, samples, *, language):
            def fail_during_consumption():
                raise RuntimeError("cuBLAS initialization failed")
                yield  # pragma: no cover - makes this a generator

            return fail_during_consumption(), FakeInfo("en", 1.0)

    cpu_model = ScriptedModel(
        [([FakeSegment("Recovered", 0.0, 0.4)], FakeInfo("en", 0.91))]
    )
    calls = []

    def factory(model_name, *, device, compute_type):
        calls.append((device, compute_type))
        return BrokenCudaModel() if device == "cuda" else cpu_model

    engine = FasterWhisperEngine(model_name="base", model_factory=factory)
    result = engine.transcribe(np.ones(1_600, dtype=np.float32))

    assert result.text == "Recovered"
    assert calls == [("cuda", "float16"), ("cpu", "int8")]
    assert engine.model_info()["device"] == "cpu"


def test_empty_audio_does_not_load_a_model():
    engine = FasterWhisperEngine(model_factory=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = engine.transcribe(np.empty(0, dtype=np.float32))
    assert result.text == ""
    assert result.detected_language == "unknown"
    assert engine.model_info()["loaded"] is False


def test_selective_recheck_uses_local_cache_forced_language_and_fast_beam() -> None:
    calls = []

    class RecheckModel:
        def transcribe(self, samples, **kwargs):
            calls.append((samples.copy(), kwargs))
            return iter([FakeSegment("本日の会議です。", 0.0, 0.5)]), FakeInfo("ja", 0.99)

    factory_calls = []

    def factory(model_name, **kwargs):
        factory_calls.append((model_name, kwargs))
        return RecheckModel()

    engine = FasterWhisperEngine(
        model_name="small",
        model_factory=factory,
        prefer_cuda=False,
        local_files_only=True,
    )
    result = engine.transcribe(
        np.zeros(8_000, dtype=np.float32),
        language="ja",
        initial_prompt="山田太郎, Fit & Gap",
        beam_size=1,
    )

    assert result.text == "本日の会議です。"
    assert factory_calls == [
        (
            "small",
            {"device": "cpu", "compute_type": "int8", "local_files_only": True},
        )
    ]
    assert calls[0][1] == {
        "language": "ja",
        "initial_prompt": "山田太郎, Fit & Gap",
        "beam_size": 1,
        "condition_on_previous_text": False,
    }
