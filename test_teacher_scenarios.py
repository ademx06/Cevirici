#!/usr/bin/env python3
"""AI öğretmen senaryo testleri — kullanıcı tarafından istenen örnekler."""
from __future__ import annotations

from education_engine import (
    _detect_tr_meaning_mismatch,
    _extract_phrase_from_how_to_say_stuck,
    _fix_greeting_duplicate_you,
    _how_to_say_stuck_short_mode,
    _is_garbled_stt,
    _is_how_to_say_stuck,
    _meaning_error_help_mode,
    _try_rule_greeting_fix,
    _try_stt_clarify_turn,
    check_english,
    default_profile,
    merge_profile,
    process_turn,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    return text


def test_greeting_duplicate_you():
    correct, reason = _fix_greeting_duplicate_you("hey I'm fine thank you you how are you")
    assert correct and "How are you" in correct
    assert reason and "you" in reason.lower()
    profile = default_profile()
    result = _try_rule_greeting_fix(
        "hey I'm fine thank you you how are you", "en", profile, {}, fake_translate,
    )
    assert result is not None
    assert result.get("correction_level", result.get("type")) or result.get("type") == "ai_correction"
    print("TEST greeting duplicate you OK")


def test_garbled_stt():
    assert _is_garbled_stt("yes English law film or dizzy")
    profile = default_profile()
    result = _try_stt_clarify_turn(
        "yes English law film or dizzy", "en", profile, {}, [], fake_translate,
    )
    assert result is not None
    assert result.get("type") == "stt_clarify"
    tr = result.get("teacher_tr") or ""
    assert "net" in tr.lower() or "ses" in tr.lower() or "tekrar" in tr.lower()
    print("TEST garbled STT OK")


def test_how_to_say_bare():
    assert _is_how_to_say_stuck("nasıl söyleyeceğimi bilmiyorum")
    profile = default_profile()
    result = _how_to_say_stuck_short_mode("en", profile, {}, fake_translate, "nasıl söyleyeceğimi bilmiyorum")
    tr = result.get("teacher_tr") or ""
    en = result.get("teacher_en") or ""
    assert "don't know how to say" in en.lower()
    assert "tekrar" in tr.lower() or "🗣️" in tr
    assert "CÜMLENİN ANALİZİ" not in tr
    print("TEST bare how-to-say OK")


def test_season_month_mismatch():
    tr = "En sevdiğim mevsim Eylül ama nasıl söyleyeceğimi bilmiyorum"
    phrase = _extract_phrase_from_how_to_say_stuck(tr)
    assert phrase and "eylül" in phrase.lower()
    mismatch = _detect_tr_meaning_mismatch(phrase)
    assert mismatch and mismatch["month_en"] == "September"
    profile = default_profile()
    result = _meaning_error_help_mode(phrase, mismatch, "en", profile, {}, fake_translate)
    body = (result.get("teacher_tr") or "") + (result.get("teacher_en") or "")
    assert "month" in body.lower()
    assert "season" in body.lower()
    assert "September" in body
    print("TEST season/month mismatch OK")


def test_want_drink_correct():
    level, correct, _, _, _ = check_english("I want to drink coffee.")
    assert level == 1 and not correct
    print("TEST want drink correct OK")


def test_process_turn_how_to_say():
    profile = default_profile()
    r = process_turn(
        "nasıl söyleyeceğimi bilmiyorum",
        "tr", "en", [], profile, translate_fn=fake_translate,
    )
    assert r.get("type") == "help"
    assert "don't know" in (r.get("teacher_en") or "").lower()
    print("TEST process_turn how-to-say OK")


if __name__ == "__main__":
    test_greeting_duplicate_you()
    test_garbled_stt()
    test_how_to_say_bare()
    test_season_month_mismatch()
    test_want_drink_correct()
    test_process_turn_how_to_say()
    print("\nAll teacher scenario tests passed.")
