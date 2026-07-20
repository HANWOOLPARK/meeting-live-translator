from __future__ import annotations

from backend.app.transcription.deduplicator import TranscriptDeduplicator
from backend.app.transcription.language import classify_language


def test_language_policy_supports_ja_en_mixed_and_unknown():
    assert classify_language("ja", 0.96, "現在確認しています") == "ja"
    assert classify_language("en", 0.93, "We are checking now") == "en"
    assert (
        classify_language("ja", 0.90, "今日は product release plan and schedule を確認します")
        == "mixed"
    )
    assert classify_language("ja", 0.59, "日本語です") == "unknown"
    assert classify_language("fr", 0.99, "This looks English") == "unknown"
    assert classify_language("en", float("nan"), "English") == "unknown"
    assert classify_language("en", 0.99, "") == "unknown"


def test_japanese_with_a_few_technical_terms_stays_japanese():
    assert classify_language("ja", 0.91, "Zoom API の設定を確認します") == "ja"


def test_deduplicator_ignores_spacing_case_width_and_punctuation():
    deduplicator = TranscriptDeduplicator()
    assert deduplicator.accept("Hello, world!") is True
    assert deduplicator.accept(" hello WORLD。 ") is False
    assert deduplicator.accept("Ｈｅｌｌｏ　Ｗｏｒｌｄ") is False
    assert deduplicator.history == ("Hello, world!",)


def test_deduplicator_handles_partial_repeats_conservatively():
    deduplicator = TranscriptDeduplicator()
    original = "We will review the deployment checklist tomorrow"
    assert deduplicator.accept(original)

    # A candidate that is almost entirely a repeated buffer tail is suppressed.
    assert not deduplicator.accept("will review the deployment checklist tomorrow")

    # An extension and a related but distinct statement both carry information.
    assert deduplicator.accept(f"{original} with the operations team")
    assert deduplicator.accept("We will review the security checklist tomorrow")


def test_deduplicator_filter_and_reset():
    deduplicator = TranscriptDeduplicator(max_history=2)
    assert deduplicator.filter("  First result  ") == "First result"
    assert deduplicator.filter("First result.") is None
    assert deduplicator.filter("Second distinct result") == "Second distinct result"
    deduplicator.reset()
    assert deduplicator.history == ()
    assert deduplicator.accept("First result")


def test_deduplicator_allows_a_legitimate_repeat_after_time_window():
    now = 100.0

    def clock() -> float:
        return now

    deduplicator = TranscriptDeduplicator(
        duplicate_window_seconds=2.0,
        clock=clock,
    )
    assert deduplicator.accept("確認しました") is True
    assert deduplicator.accept("確認しました") is False

    now += 2.1
    assert deduplicator.accept("確認しました") is True
