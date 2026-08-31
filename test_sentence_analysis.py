#!/usr/bin/env python3
"""Eğitim modülü cümle analiz motoru — senaryo testleri."""
from __future__ import annotations

from education_engine import (
    _analyze_for_teaching,
    _extract_phrase_from_how_to_say_stuck,
    _format_teaching_response_tr,
    _phrase_vocab_breakdown,
    _rule_natural_translate_tr,
    check_english,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    """Basit kelime kelime çeviri simülasyonu (kötü çeviri — motor bunu düzeltmeli)."""
    mapping = {
        "bugün": "today",
        "iş": "work",
        "yerinde": "in place",
        "çok": "very",
        "yoruldum": "I got tired",
        "kahve": "coffee",
        "içmek": "to drink",
        "istiyorum": "I want",
        "eve": "home",
        "gitmek": "to go",
        "eve gitmek istiyorum": "I want to go home",
        "bugün çok yorgunum": "today very tired I am",
    }
    low = text.lower().strip()
    if low in mapping:
        return mapping[low]
    if from_lang == "tr" and to_lang == "en":
        return " ".join(mapping.get(w, w) for w in low.split())
    return text


def test1_tired_at_work_coffee():
    tr = "Bugün iş yerinde çok yoruldum, kahve içmek istiyorum."
    natural = _rule_natural_translate_tr(tr, "en", fake_translate)
    assert "at work" in natural.lower() or "from work" in natural.lower(), natural
    assert "coffee" in natural.lower(), natural
    assert "gitmek istemiyorum" not in natural.lower()
    assert "go to work" not in natural.lower() or "from work" in natural.lower()

    pairs = _phrase_vocab_breakdown(tr, "en", fake_translate)
    pair_text = " ".join(p["tr"] for p in pairs).lower()
    assert "iş yerinde" in pair_text or "yoruldum" in pair_text
    assert "yerinde" not in pair_text or "iş yerinde" in pair_text
    print("TEST 1 OK:", natural)
    print("  pairs:", pairs)


def test2_go_home():
    tr = "Eve gitmek istiyorum."
    natural = _rule_natural_translate_tr(tr, "en", fake_translate)
    assert natural.strip().lower().startswith("i want to go home"), natural
    analysis = _analyze_for_teaching(tr, "en", fake_translate)
    formatted = _format_teaching_response_tr(tr, analysis, "English")
    assert "want" in formatted.lower() and "to" in formatted.lower()
    print("TEST 2 OK:", natural)


def test3_tired_today():
    tr = "Bugün çok yorgunum."
    natural = _rule_natural_translate_tr(tr, "en", fake_translate)
    assert "tired" in natural.lower(), natural
    print("TEST 3 OK:", natural)


def test4_want_go_grammar():
    level, correct, cat, _, ex_tr = check_english("I want go home.")
    assert level >= 2, (level, correct)
    assert correct and "to" in correct.lower(), correct
    assert ex_tr or cat
    print("TEST 4 OK:", correct, ex_tr)


def test5_boring_vs_bored():
    level, correct, cat, _, ex_tr = check_english("I am boring.")
    assert level >= 2, level
    assert correct and "bored" in correct.lower(), correct
    assert "boring" in (ex_tr or "").lower() or cat == "word_choice"
    print("TEST 5 OK:", correct, ex_tr)


def test6_want_drink_correct():
    level, correct, _, _, _ = check_english("I want to drink coffee.")
    assert level == 1, (level, correct)
    print("TEST 6 OK: correction_level=1 (correct)")


def test_how_to_say_extract():
    tr = "nasıl söyleyeceğimi bilmiyorum bugün okula gittim"
    phrase = _extract_phrase_from_how_to_say_stuck(tr)
    assert phrase and "okula" in phrase, phrase
    print("TEST extract OK:", phrase)


if __name__ == "__main__":
    test1_tired_at_work_coffee()
    test2_go_home()
    test3_tired_today()
    test4_want_go_grammar()
    test5_boring_vs_bored()
    test6_want_drink_correct()
    test_how_to_say_extract()
    print("\nAll sentence analysis tests passed.")
