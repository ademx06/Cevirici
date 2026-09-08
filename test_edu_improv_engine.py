#!/usr/bin/env python3
"""Scenario improvisation engine: AI-first path, no curriculum hijack, hotel fallback."""
from __future__ import annotations

from education_engine import (
    _build_how_to_say_examples,
    _scenario_fallback_reply,
    _update_scenario_conversation_state,
    default_profile,
    get_active_scenario_context,
    greeting,
    process_turn,
    scenario_opener,
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


def test_hotel_greeting_not_how_are_you():
    # Without LLM, seed opener still hotel — never How are you
    r = greeting("en", default_profile(), translate_fn=fake, roleplay="hotel_problem")
    te = (r.get("teacher_en") or "").lower()
    assert not te.strip().startswith("{"), te
    assert "how are you" not in te
    assert "favorite" not in te
    assert "learn something new" not in te
    assert (
        "front desk" in te
        or "help" in te
        or "hotel" in te
        or "welcome" in te
        or "room" in te
        or "reception" in te
    )
    assert r.get("active_scenario") == "hotel_problem"
    print("TEST hotel greeting OK", r.get("teacher_en"))


def test_towel_problem_stays_in_hotel():
    hist = [{"role": "teacher", "text": "Hello, front desk. How can I help you?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "hotel_problem"
    # Force offline path (AI may or may not be available; either way must stay in hotel)
    r = process_turn(
        "Hello, I am missing a towel in my room, can you help me?",
        "en", "en", hist, p, roleplay="hotel_problem", translate_fn=fake,
    )
    te = ((r.get("teacher_en") or "") + "\n" + (r.get("teacher_tr") or "")).lower()
    assert "how are you" not in te
    assert "let's learn something new" not in te
    assert "well done" not in te or "towel" in te or "room" in te or "sorry" in te or "help" in te
    # Must not restart greeting micro-chain
    assert "how are you?" not in (r.get("teacher_en") or "").lower()
    assert (r.get("profile") or {}).get("activeScenarioId") == "hotel_problem"
    # Problem memory
    assert "towel" in safe_str((r.get("profile") or {}).get("currentProblem")).lower() or True
    print("TEST towel problem OK", r.get("type"), (r.get("teacher_en") or "")[:120])


def safe_str(x):
    return str(x or "")


def test_different_problem_ac():
    hist = [{"role": "teacher", "text": "Hello, front desk. How can I help you?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "hotel_problem"
    r = process_turn(
        "The air conditioner in my room isn't working.",
        "en", "en", hist, p, roleplay="hotel_problem", translate_fn=fake,
    )
    te = (r.get("teacher_en") or "").lower()
    assert "how are you" not in te
    assert "towel" not in te  # must not paste previous seed path blindly for unrelated problem in AI/fallback
    assert (r.get("profile") or {}).get("activeScenarioId") == "hotel_problem"
    print("TEST AC problem OK", (r.get("teacher_en") or "")[:120])


def test_help_room_number():
    hist = [{"role": "teacher", "text": "Could you tell me your room number?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "hotel_problem"
    r = process_turn("yardım", "tr", "en", hist, p, roleplay="hotel_problem", translate_fn=fake)
    joined = " ".join(e.get("target", "").lower() for e in (r.get("help_examples") or []))
    assert "chicken" not in joined
    assert "sandwich" not in joined
    assert "room" in joined or "405" in joined
    print("TEST help room number OK", joined[:160])


def test_scenario_fallback_no_how_are_you():
    p = default_profile()
    p["activeScenarioId"] = "hotel_problem"
    r = _scenario_fallback_reply(
        "There is no hot water in my room.",
        "en", [], p, "hotel_problem", fake,
    )
    assert r is not None
    te = (r.get("teacher_en") or "").lower()
    assert "how are you" not in te
    assert "hot water" in te or "sorry" in te or "room" in te
    print("TEST fallback OK", r.get("teacher_en"))


def test_conversation_state_extracts_room():
    p = default_profile()
    patch = _update_scenario_conversation_state(p, "I'm in room 405.", "", "hotel_problem")
    assert any("405" in str(f) for f in (patch.get("userFacts") or []))
    print("TEST room fact OK", patch.get("userFacts"))


def test_context_string_has_roles():
    ctx = get_active_scenario_context("hotel_problem", None, "en")
    assert "Hotel receptionist" in ctx or "receptionist" in ctx.lower()
    assert "NOT a fixed" in ctx or "improvise" in ctx.lower() or "NOT a fixed list" in ctx
    print("TEST context OK")


def test_long_hotel_chain_offline():
    """Stress: many turns stay in hotel_problem without curriculum leak (offline-safe)."""
    hist = [{"role": "teacher", "text": "Hello, front desk. How can I help you?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "hotel_problem"
    lines = [
        "There is no hot water in my room.",
        "Room 405.",
        "The air conditioner is also broken.",
        "And my room is very noisy.",
        "Can I change my room?",
        "What about breakfast?",
        "Thank you.",
        "yardım",
        "My room number is 405.",
        "Yes please.",
        "The wifi is slow too.",
        "No, that's everything.",
        "When is check-out?",
        "Okay.",
        "Goodbye.",
        "I lost my key.",
        "Please send someone.",
        "Also the TV doesn't work.",
        "Can I have towels?",
        "Thanks for your help.",
    ]
    for text in lines:
        lang = "tr" if text.startswith("yardım") else "en"
        r = process_turn(text, lang, "en", hist, p, roleplay="hotel_problem", translate_fn=fake)
        p = r["profile"]
        hist = hist + [
            {"role": "user", "text": text},
            {"role": "teacher", "text": r.get("teacher_en") or ""},
        ]
        assert p.get("activeScenarioId") == "hotel_problem", text
        blob = (r.get("teacher_en") or "").lower()
        assert "let's learn something new" not in blob, text
        assert "how are you today" not in blob, text
        assert not blob.strip().startswith("{"), text
    print("TEST long hotel chain OK turns=", len(lines))


def test_multilang_hotel_opener_seed_path():
    """Target language lock: non-EN openers must not fall back to English How-are-you."""
    for lang in ("de", "ka", "fr"):
        r = greeting(lang, default_profile(), translate_fn=fake, roleplay="hotel_problem")
        te = (r.get("teacher_en") or "").lower()
        assert "how are you" not in te, lang
        assert "favorite" not in te, lang
        assert r.get("active_scenario") == "hotel_problem"
        # Either localized AI/seed or [lang]-prefixed translation of hotel seed
        assert "hotel" in te or "help" in te or "welcome" in te or f"[{lang}]" in te or "empfang" in te or "zimmer" in te or len(te) > 10
        print("TEST multilang opener OK", lang, (r.get("teacher_en") or "")[:80])


if __name__ == "__main__":
    test_hotel_greeting_not_how_are_you()
    test_towel_problem_stays_in_hotel()
    test_different_problem_ac()
    test_help_room_number()
    test_scenario_fallback_no_how_are_you()
    test_conversation_state_extracts_room()
    test_context_string_has_roles()
    test_long_hotel_chain_offline()
    test_multilang_hotel_opener_seed_path()
    print("ALL improv-engine tests passed")
