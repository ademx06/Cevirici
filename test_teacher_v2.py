#!/usr/bin/env python3
"""Teacher Engine V2 — 10 senaryo testi."""
from __future__ import annotations

from education_engine import (
    _is_garbled_stt,
    _is_progress_confirmation,
    _is_simple_acknowledgment,
    _try_children_plural_teaching,
    _try_okay_guidance_turn,
    _try_progress_confirm_turn,
    _try_reading_fragment_teaching,
    _try_repeated_weakness_turn,
    _try_students_correct_extend,
    _try_stt_clarify_turn,
    check_english,
    default_profile,
    process_turn,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    return text


def test_1_hello_chain():
    profile = default_profile()
    profile["microStep"] = 2
    r = process_turn("I'm fine", "en", "en", [], profile, translate_fn=fake_translate)
    assert r.get("type") in ("micro_teach", "ai_tutor", "build_forward", "practice_success")
    print("TEST 1 hello chain OK:", r.get("type"))


def test_2_okay_not_wrong():
    assert _is_simple_acknowledgment("okay")
    profile = default_profile()
    profile["pendingPracticePhrase"] = "And you?"
    profile["awaitingTargetPhrase"] = "And you?"
    r = _try_okay_guidance_turn("okay", "en", profile, {}, fake_translate)
    assert r is not None
    assert r.get("correction_level", 1) == 1
    body = (r.get("teacher_en") or "").lower()
    assert "and you" in body
    assert "wrong" not in body and "❌" not in (r.get("teacher_tr") or "")
    print("TEST 2 okay guidance OK")


def test_3_reading_fragment():
    profile = default_profile()
    r = _try_reading_fragment_teaching(
        "today is reading book maybe", "en", profile, {}, fake_translate,
    )
    assert r is not None
    assert "I am reading a book today" in (r.get("teacher_en") or "")
    print("TEST 3 reading fragment OK")


def test_4_progress_confirm():
    assert _is_progress_confirmation("Evet onu söylemek istedim")
    profile = default_profile()
    profile["lastMasteredPhrase"] = "I am reading a book."
    r = _try_progress_confirm_turn(
        "Evet onu söylemek istedim", "en", profile, {}, fake_translate,
    )
    assert r is not None
    body = r.get("teacher_en") or ""
    assert "Exactly" in body or "build" in body.lower()
    assert "go back to basics" not in body.lower()
    print("TEST 4 progress confirm OK")


def test_5_children_plural():
    profile = default_profile()
    r = _try_children_plural_teaching(
        "children's are reading a book", "en", profile, {}, fake_translate,
    )
    assert r is not None
    body = (r.get("teacher_en") or "") + (r.get("teacher_tr") or "")
    assert "children" in body.lower()
    assert "The children are reading" in (r.get("teacher_en") or "")
    print("TEST 5 children plural OK")


def test_6_students_correct():
    profile = default_profile()
    r = _try_students_correct_extend(
        "the students are reading a book", "en", profile, {}, fake_translate,
    )
    assert r is not None
    assert r.get("correction_level", 1) == 1
    assert "Excellent" in (r.get("teacher_en") or "") or "correct" in (r.get("teacher_en") or "").lower()
    print("TEST 6 students correct OK")


def test_7_how_to_say():
    r = process_turn("nasıl söyleyeceğimi bilmiyorum", "tr", "en", [], default_profile(), translate_fn=fake_translate)
    assert "don't know" in (r.get("teacher_en") or "").lower()
    print("TEST 7 how-to-say OK")


def test_8_garbled_stt():
    assert _is_garbled_stt("yes English law film or dizzy")
    r = _try_stt_clarify_turn("yes English law film or dizzy", "en", default_profile(), {}, [], fake_translate)
    assert r.get("type") == "stt_clarify"
    assert "demek istedin" not in (r.get("teacher_en") or "").lower() or "?" in (r.get("teacher_en") or "")
    print("TEST 8 garbled STT OK")


def test_9_correct_sentence():
    level, correct, _, _, _ = check_english("I want to drink coffee.")
    assert level == 1 and not correct
    print("TEST 9 correct sentence OK")


def test_10_repeated_want_go():
    profile = default_profile()
    profile["weakAreas"] = ["grammar"]
    r = _try_repeated_weakness_turn("I want go home.", "en", profile, {}, fake_translate)
    assert r is not None
    assert "want" in (r.get("teacher_en") or "").lower() and "to" in (r.get("teacher_en") or "").lower()
    print("TEST 10 repeated want go OK")


if __name__ == "__main__":
    test_1_hello_chain()
    test_2_okay_not_wrong()
    test_3_reading_fragment()
    test_4_progress_confirm()
    test_5_children_plural()
    test_6_students_correct()
    test_7_how_to_say()
    test_8_garbled_stt()
    test_9_correct_sentence()
    test_10_repeated_want_go()
    print("\nAll Teacher Engine V2 tests passed.")
