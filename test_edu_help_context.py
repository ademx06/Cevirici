#!/usr/bin/env python3
"""Help context: anything-else must not return chicken sandwich; yardım+TR intent."""
from __future__ import annotations

from education_engine import (
    _build_how_to_say_examples,
    _example_fits_active_question,
    _help_mode,
    default_profile,
    process_turn,
)


def fake(t, a, b):
    t = (t or "").strip()
    if a == b:
        return t
    if a == "tr" and b == "en":
        low = t.lower()
        if "başka ne" in low or "ne var" in low:
            return "What else is there?"
        if "kahve" in low:
            return "I usually drink coffee."
        return f"[en]{t}"
    if a == "en" and b != "en":
        return f"[{b}]{t}"
    if b == "tr":
        return f"[tr]{t}"
    return f"[{b}]{t}"


def test_anything_else_seeds():
    q = "Would you like anything else, or is that all?"
    seeds = _build_how_to_say_examples(q, "en", fake, roleplay="restaurant")
    joined = " ".join(e for e, _ in seeds).lower()
    assert "chicken" not in joined
    assert "sandwich" not in joined
    assert "that's all" in joined or "thank you" in joined or "dessert" in joined
    for e, _ in seeds:
        assert _example_fits_active_question(e, q)
    print("TEST anything-else seeds OK", [e for e, _ in seeds])


def test_yardim_baska_ne_var():
    hist = [{"role": "teacher", "text": "Would you like anything else, or is that all?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "restaurant"
    p["activeTeacherQuestion"] = {
        "originalText": hist[0]["text"],
        "language": "en",
        "scenarioId": "restaurant",
    }
    r = process_turn(
        "yardım Başka ne var", "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake,
    )
    ex = r.get("help_examples") or []
    assert len(ex) >= 2
    joined = " ".join(e.get("target", "").lower() for e in ex)
    assert "chicken sandwich" not in joined
    # Should include phrase translation and/or closing answers
    assert (
        "else" in joined
        or "that's all" in joined
        or "thank you" in joined
        or "dessert" in joined
    )
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    aq = ((r.get("profile") or {}).get("activeTeacherQuestion") or {}).get("originalText", "")
    assert "anything else" in aq.lower()
    print("TEST yardım başka ne var OK", [e["target"] for e in ex])


def test_bare_yardim_anything_else():
    hist = [{"role": "teacher", "text": "Would you like anything else, or is that all?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    r = _help_mode("yardım", "en", fake, p, {}, history=hist, roleplay="restaurant")
    joined = " ".join(e.get("target", "").lower() for e in (r.get("help_examples") or []))
    assert "chicken" not in joined
    assert "all" in joined or "thank" in joined or "dessert" in joined
    print("TEST bare yardım OK", joined[:120])


def test_order_question_still_food():
    q = "What would you like to order?"
    seeds = _build_how_to_say_examples(q, "en", fake, roleplay="restaurant")
    joined = " ".join(e for e, _ in seeds).lower()
    assert "chicken" in joined or "pasta" in joined or "like" in joined
    print("TEST order seeds OK", [e for e, _ in seeds][:2])


def test_help_then_answer_keeps_scenario():
    hist = [{"role": "teacher", "text": "Would you like anything else, or is that all?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    r0 = process_turn("yardım", "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    p = r0["profile"]
    r1 = process_turn(
        "No, that's all, thank you.", "en", "en", hist, p, roleplay="restaurant", translate_fn=fake,
    )
    assert (r1.get("profile") or {}).get("activeScenarioId") == "restaurant"
    assert r1.get("type") != "help_idle"
    print("TEST help then continue OK", r1.get("type"))


if __name__ == "__main__":
    test_anything_else_seeds()
    test_yardim_baska_ne_var()
    test_bare_yardim_anything_else()
    test_order_question_still_food()
    test_help_then_answer_keeps_scenario()
    print("ALL help-context tests passed")
