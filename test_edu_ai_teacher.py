#!/usr/bin/env python3
"""AI teacher: scenario greeting, I am fine, rich context."""
from __future__ import annotations

from education_engine import (
    ROLEPLAYS,
    _is_likely_correct_english,
    _only_contraction_or_style_diff,
    _sanitize_ai_correction,
    get_active_scenario_context,
    greeting,
    process_turn,
    scenario_opener,
    default_profile,
)


def fake(t, a, b):
    t = (t or "").strip()
    if a == b:
        return t
    if a == "en" and b != "en":
        return f"[{b}]{t}"
    if b == "tr":
        return f"[tr]{t}"
    return f"[{b}]{t}"


def test_catalog_size():
    assert len(ROLEPLAYS) >= 30
    for key in ("restaurant", "hotel", "doctor", "interview", "cafe", "taxi"):
        assert key in ROLEPLAYS
        assert ROLEPLAYS[key].get("teacherRole")
        assert ROLEPLAYS[key].get("goal")
    print("TEST catalog OK", len(ROLEPLAYS))


def test_restaurant_greeting_not_how_are_you():
    r = greeting("en", default_profile(), translate_fn=fake, roleplay="restaurant")
    te = (r.get("teacher_en") or "").lower()
    assert "how are you today" not in te
    assert "welcome" in te or "party" in te or "people" in te
    assert r.get("active_scenario") == "restaurant"
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    print("TEST restaurant greeting OK", r.get("teacher_en"))


def test_hotel_greeting():
    r = greeting("en", default_profile(), translate_fn=fake, roleplay="hotel")
    te = (r.get("teacher_en") or "").lower()
    assert "reservation" in te or "welcome" in te
    assert "how are you today" not in te
    print("TEST hotel greeting OK", r.get("teacher_en"))


def test_free_conversation_greeting():
    r = greeting("en", default_profile(), translate_fn=fake, roleplay=None)
    assert "how are you" in (r.get("teacher_en") or "").lower()
    print("TEST free greeting OK")


def test_i_am_fine_not_corrected():
    assert _is_likely_correct_english("I am fine.")
    assert _is_likely_correct_english("I am fine, thank you.")
    assert _only_contraction_or_style_diff("I am fine", "I'm fine")
    parsed = {
        "teacher_en": "Almost! Say: I'm fine.",
        "teacher_tr": "Kısaltma kullan.",
        "correction_level": 2,
        "correct_phrase": "I'm fine.",
        "grammar_tr": "Yanlış: I am fine deme.",
    }
    out = _sanitize_ai_correction("I am fine.", parsed, target_lang="en")
    assert int(out.get("correction_level") or 1) == 1
    assert not out.get("correct_phrase")
    print("TEST I am fine OK")


def test_scenario_context_rich():
    ctx = get_active_scenario_context("restaurant", None, "en")
    assert "TEACHER ROLE" in ctx
    assert "Waiter" in ctx or "waiter" in ctx.lower() or "host" in ctx.lower()
    assert "NOT a fixed" in ctx or "NOT a fixed list" in ctx
    assert scenario_opener("restaurant", "en").startswith("Good evening")
    print("TEST scenario context OK")


def test_two_people_accepted():
    assert _is_likely_correct_english("Two people.")
    hist = [{"role": "teacher", "text": "Good evening! Welcome. How many people are in your party?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "restaurant"
    r = process_turn("Two people.", "en", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    assert int(r.get("correction_level") or 1) <= 2  # may continue chat
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    print("TEST two people OK", r.get("type"), (r.get("teacher_en") or "")[:80])


if __name__ == "__main__":
    test_catalog_size()
    test_restaurant_greeting_not_how_are_you()
    test_hotel_greeting()
    test_free_conversation_greeting()
    test_i_am_fine_not_corrected()
    test_scenario_context_rich()
    test_two_people_accepted()
    print("ALL AI-teacher tests passed")
