#!/usr/bin/env python3
"""Scenario-first Education help: restaurant/DE/commands/structure/Turkish gloss."""
from __future__ import annotations

from education_engine import (
    _build_how_to_say_examples,
    _help_question_structure,
    _question_token_structure,
    default_profile,
    process_turn,
)


def fake(t, a, b):
    t = (t or "").strip()
    if a == b:
        return t
    if a == "tr" and b == "en":
        low = t.lower()
        if "eve gid" in low or "dinlen" in low:
            return "I usually go home and relax."
        if "kahve" in low:
            return "I usually drink coffee."
        return f"[en]{t}"
    if a == "en" and b != "en":
        return f"[{b}]{t}"
    if b == "tr":
        return f"[tr]{t}"
    return f"[{b}]{t}"


def _targets(r):
    return [e.get("target", "") for e in (r.get("help_examples") or [])]


def test_restaurant_help_en():
    hist = [{"role": "teacher", "text": "Welcome to our restaurant. What would you like to order?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    r = process_turn("yardım", "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    joined = " ".join(_targets(r)).lower()
    assert "chicken" in joined or "sandwich" in joined or "pasta" in joined or "water" in joined
    assert "are/is/am" not in ((r.get("help_structure") or {}).get("question") or {}).get("structure", "").lower()
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    aq = (r.get("profile") or {}).get("activeTeacherQuestion") or {}
    assert "order" in (aq.get("originalText") or "").lower()
    print("TEST restaurant EN OK", _targets(r)[:2])


def test_usually_eat_drink_structure_and_gloss():
    q = "What do you usually like to eat or drink?"
    struct = _question_token_structure(q)
    assert "What + do + you + usually + like + to eat or drink?" == struct
    hs = _help_question_structure(q, "en")
    assert "Are/Is/Am" not in hs.get("structure", "")
    assert "Are/Is/Am" not in (hs.get("explain_tr") or "")
    seeds = _build_how_to_say_examples(q, "en", fake, roleplay="restaurant")
    assert "pizza" in seeds[0][0].lower()
    for _, tr in seeds:
        assert "to eat" not in tr.lower()
        assert "to drink" not in tr.lower()
    hist = [{"role": "teacher", "text": q}]
    p = default_profile()
    p["lastTeacherText"] = q
    r = process_turn("yardım", "tr", "en", hist, p, translate_fn=fake)
    joined_tr = " ".join(e.get("tr", "") for e in (r.get("help_examples") or [])).lower()
    assert "to eat" not in joined_tr
    assert "pizza" in " ".join(_targets(r)).lower()
    print("TEST usually eat/drink OK", struct)


def test_german_restaurant_help():
    hist = [{"role": "teacher", "text": "Willkommen! Was möchten Sie bestellen?"}]
    p = default_profile("de")
    p["targetLang"] = "de"
    p["lastTeacherText"] = hist[0]["text"]
    r = process_turn("yardım", "tr", "de", hist, p, roleplay="restaurant", translate_fn=fake)
    ex = r.get("help_examples") or []
    assert len(ex) >= 3
    for e in ex:
        tgt = e.get("target", "")
        # Must not ship raw English curriculum lines as the only form
        assert tgt.startswith("[de]") or not tgt.lower().startswith("i usually")
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    print("TEST DE restaurant OK", _targets(r)[:1])


def test_help_plus_turkish_keeps_scenario():
    hist = [{"role": "teacher", "text": "What would you like to order?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    p["activeScenarioId"] = "restaurant"
    r = process_turn(
        "Yardım, genellikle kahve içerim.",
        "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake,
    )
    ex = r.get("help_examples") or []
    assert len(ex) >= 1
    assert "coffee" in ex[0]["target"].lower() or "[en]" in ex[0]["target"].lower()
    assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
    print("TEST Yardım+TR OK", ex[0]["target"])


def test_commands_stay_on_question():
    hist = [{"role": "teacher", "text": "What would you like to order?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    r0 = process_turn("yardım", "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    p = r0["profile"]
    for cmd in ("başka örnek", "daha kolay", "daha doğal"):
        r = process_turn(cmd, "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake)
        assert r.get("help_examples")
        assert (r.get("profile") or {}).get("activeScenarioId") == "restaurant"
        aq = ((r.get("help_structure") or {}).get("active_question") or "").lower()
        assert "order" in aq or "order" in ((r.get("profile") or {}).get("activeTeacherQuestion") or {}).get("originalText", "").lower()
        p = r["profile"]
    print("TEST commands OK")


def test_long_conversation_keeps_scenario():
    hist = [{"role": "teacher", "text": "Welcome! What would you like to order?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    replies = [
        "I'd like chicken.",
        "Water, please.",
        "yardım",
        "I'd like a bottle of water, please.",
        "No dessert.",
        "The bill, please.",
        "Thank you.",
        "başka örnek",
    ]
    for text in replies:
        r = process_turn(text, "tr" if text in ("yardım", "başka örnek") else "en", "en", hist, p, roleplay="restaurant", translate_fn=fake)
        p = r["profile"]
        hist = hist + [
            {"role": "user", "text": text},
            {"role": "teacher", "text": r.get("teacher_en") or r.get("teacher_tr") or ""},
        ]
        assert p.get("activeScenarioId") == "restaurant"
    print("TEST long convo OK turn=", len(replies))


def test_help_then_continue():
    hist = [{"role": "teacher", "text": "Would you like something to drink?"}]
    p = default_profile()
    p["lastTeacherText"] = hist[0]["text"]
    r_help = process_turn("yardım", "tr", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    joined = " ".join(_targets(r_help)).lower()
    assert "water" in joined or "drink" in joined or "sparkling" in joined
    p = r_help["profile"]
    # Answer with one of the examples — conversation must continue, not reset scenario
    r2 = process_turn("Yes, I'd like some water.", "en", "en", hist, p, roleplay="restaurant", translate_fn=fake)
    assert (r2.get("profile") or {}).get("activeScenarioId") == "restaurant"
    assert r2.get("type") != "help_idle"
    print("TEST help then continue OK", r2.get("type"))


if __name__ == "__main__":
    test_restaurant_help_en()
    test_usually_eat_drink_structure_and_gloss()
    test_german_restaurant_help()
    test_help_plus_turkish_keeps_scenario()
    test_commands_stay_on_question()
    test_long_conversation_keeps_scenario()
    test_help_then_continue()
    print("ALL scenario-help tests passed")
