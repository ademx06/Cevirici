#!/usr/bin/env python3
"""Eğitim: ham metin gerçeği, froming yasağı, I are/IR, meta kaçış, kişi uyumu."""
from __future__ import annotations

from education_engine import (
    _detect_sentence_scaffold,
    _is_meta_conversation_reply,
    _lock_tr_person_for_english,
    check_english,
    default_profile,
    process_turn,
)


def fake(t, a, b):
    return t


def test_no_froming_scaffold():
    assert _detect_sentence_scaffold("I am from Bursa") is None
    assert _detect_sentence_scaffold("I am in Ankara") is None
    assert _detect_sentence_scaffold("I am at work") is None
    assert _detect_sentence_scaffold("I am tired") is None
    assert _detect_sentence_scaffold("I am 28 years old") is None
    sc = _detect_sentence_scaffold("I am read a book")
    assert sc and sc["target"] == "I am reading a book."
    r = process_turn("I am from Bursa", "en", "en", [], default_profile(), translate_fn=fake)
    body = ((r.get("teacher_en") or "") + (r.get("correction") or "")).lower()
    assert "froming" not in body
    assert r.get("type") != "scaffold_produce"
    print("TEST no froming OK")


def test_i_are_not_silently_accepted():
    lvl, phrase, cat, *_ = check_english("I are 28 years old")
    assert lvl >= 2 and phrase and "i am 28" in phrase.lower()
    r = process_turn("I are 28 years old", "en", "en", [], default_profile(), translate_fn=fake)
    assert int(r.get("correction_level") or 1) >= 2
    assert r.get("correction")
    assert "i am" in (r.get("correction") or "").lower()
    # Must not pretend Perfect without correction
    assert r.get("type") in ("rule_teach", "ai_correction", "correction", "intent_teach")
    print("TEST I are corrected OK")


def test_ir_age_not_perfect():
    lvl, phrase, *_ = check_english("IR 28 years old and I work as a dietitian")
    assert lvl >= 2 and phrase and "i am 28" in phrase.lower()
    r = process_turn(
        "IR 28 years old and I work as a dietitian",
        "en", "en", [], default_profile(), translate_fn=fake,
    )
    assert int(r.get("correction_level") or 1) >= 2
    assert r.get("correction")
    print("TEST IR age corrected OK")


def test_im_apostrophe_ok():
    lvl, phrase, *_ = check_english("I'm 28 years old")
    assert lvl == 1 and phrase is None
    print("TEST I'm age OK")


def test_froming_user_error():
    lvl, phrase, *_ = check_english("I am froming Bursa")
    assert lvl >= 2 and phrase and "froming" not in phrase.lower() and "from" in phrase.lower()
    print("TEST froming user error OK")


def test_meta_exits_practice():
    assert _is_meta_conversation_reply("You asked me about my work.")
    p = default_profile()
    p["pendingPracticePhrase"] = "I am reading a book."
    p["scaffoldMode"] = "produce"
    p["scaffoldTarget"] = "I am reading a book."
    r = process_turn(
        "You asked me about my work.",
        "en", "en",
        [{"role": "teacher", "text": "Say: I am reading a book."}],
        p,
        translate_fn=fake,
    )
    assert r.get("type") == "conversation"
    assert not (r.get("profile") or {}).get("pendingPracticePhrase")
    assert not (r.get("profile") or {}).get("scaffoldMode")
    assert "right" in (r.get("teacher_en") or "").lower()
    print("TEST meta exits practice OK")


def test_correct_sentence_exits_forced_practice():
    p = default_profile()
    p["pendingPracticePhrase"] = "I am reading a book."
    p["scaffoldMode"] = "produce"
    p["scaffoldTarget"] = "I am reading a book."
    r = process_turn(
        "I am from Bursa but I don't live in Warsaw. I live in Ankara and I work in Ankara.",
        "en", "en", [], p, translate_fn=fake,
    )
    body = (r.get("teacher_en") or "").lower()
    assert "froming" not in body
    assert not (r.get("profile") or {}).get("scaffoldMode")
    print("TEST correct sentence exits practice OK")


def test_tr_person_lock():
    assert "yaşındayım" in _lock_tr_person_for_english("I am 28 years old.", "28 yaşındasın.")
    assert "yaşındasın" in _lock_tr_person_for_english("How old are you?", "28 yaşındayım.")
    print("TEST TR person lock OK")


def test_drink_has_verb():
    lvl, phrase, cat, *_ = check_english("I drink it black, without milk or sugar")
    assert lvl == 1 and phrase is None and cat is None
    print("TEST drink verb OK")


if __name__ == "__main__":
    test_no_froming_scaffold()
    test_i_are_not_silently_accepted()
    test_ir_age_not_perfect()
    test_im_apostrophe_ok()
    test_froming_user_error()
    test_meta_exits_practice()
    test_correct_sentence_exits_forced_practice()
    test_tr_person_lock()
    test_drink_has_verb()
    print("\nAll grammar-truth tests passed.")
