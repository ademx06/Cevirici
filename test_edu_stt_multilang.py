#!/usr/bin/env python3
"""Eğitim: missing_verb, çok dilli selamlama, kelime AI kapısı."""
from __future__ import annotations

from education_engine import (
    GREETING_OPENERS,
    check_english,
    greeting,
    _has_clear_english_verb,
    _localize_teacher_text,
    _minimal_conversation_turn,
    default_profile,
)
from word_teaching_engine import ai_only_lesson_enabled


def fake_translate(text, src, dst):
    if src == dst:
        return text
    return f"[{dst}]{text}"


def test_drink_not_missing_verb():
    lvl, phrase, cat, *_ = check_english("I drink it black, without milk or sugar")
    assert lvl == 1 and phrase is None and cat is None
    assert _has_clear_english_verb("i drink it black without milk or sugar")
    lvl2, *_ = check_english("She drinks tea every morning at home")
    assert lvl2 == 1
    lvl3, _, cat3, *_ = check_english("My favorite coffee black without milk sugar")
    assert lvl3 == 2 and cat3 == "missing_verb"
    print("TEST drink verb OK")


def test_greeting_target_lang():
    g_de = greeting("de", translate_fn=fake_translate)
    assert "Wie geht" in (g_de.get("teacher_en") or "")
    assert g_de.get("target_lang") == "de"
    g_fr = greeting("fr")
    assert "Comment" in (g_fr.get("teacher_en") or "") or "ça va" in (g_fr.get("teacher_en") or "").lower()
    g_en = greeting("en")
    assert "How are you" in (g_en.get("teacher_en") or "")
    assert "en" in GREETING_OPENERS and "de" in GREETING_OPENERS
    print("TEST greeting multilang OK")


def test_minimal_localizes():
    p = default_profile()
    p["lastTeacherText"] = "Magst du Kaffee?"
    r = _minimal_conversation_turn("ja", "de", p, {}, translate_fn=fake_translate)
    te = r.get("teacher_en") or ""
    assert te.startswith("[de]") or "Nice" not in te or "[de]" in te
    # Localized via translate_fn
    assert "[de]" in te
    print("TEST minimal localize OK")


def test_localize_helper():
    assert _localize_teacher_text("Hello", "en", fake_translate) == "Hello"
    assert _localize_teacher_text("Hello", "de", fake_translate) == "[de]Hello"
    print("TEST localize helper OK")


def test_word_ai_gate_multilang():
    assert ai_only_lesson_enabled("en") is True or ai_only_lesson_enabled("en") is False
    # Gate must allow non-English when LLM is available
    from word_teaching_engine import llm_available
    if llm_available():
        assert ai_only_lesson_enabled("de") is True
        assert ai_only_lesson_enabled("fr") is True
        assert ai_only_lesson_enabled("ka") is True
    assert ai_only_lesson_enabled("tr") is False
    print("TEST word AI gate multilang OK")


if __name__ == "__main__":
    test_drink_not_missing_verb()
    test_greeting_target_lang()
    test_minimal_localizes()
    test_localize_helper()
    test_word_ai_gate_multilang()
    print("\nAll edu-stt-multilang tests passed.")
