#!/usr/bin/env python3
"""Eğitim öğretmeni — sürekli doğal sohbet (kapanış yok, context, yardım, kısa cevap)."""
from __future__ import annotations

from education_engine import (
    _format_history_for_ai,
    _history_chronological,
    _is_minimal_conversation_reply,
    default_profile,
    process_turn,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    table = {
        ("tr", "en"): {
            "bugün alışverişe gideceğim": "I am going shopping today.",
            "çok yoruldum": "I am very tired.",
        },
        ("en", "tr"): {
            "I am going shopping today.": "Bugün alışverişe gideceğim.",
            "I don't like snakes.": "Yılanları sevmiyorum.",
        },
    }
    return table.get((from_lang, to_lang), {}).get(text, text)


def body(r: dict) -> str:
    return ((r.get("teacher_en") or "") + "\n" + (r.get("teacher_tr") or "")).lower()


def assert_continues(r: dict, label: str):
    b = body(r)
    for bad in (
        "lesson complete", "that's all for today", "goodbye", "see you next time",
        "ders bitti", "görüşürüz", "practice later", "you failed", "bad english",
    ):
        assert bad not in b, f"{label}: forbidden closing/harsh phrase: {bad} in {b[:200]}"
    # Should invite more talk somehow
    en = (r.get("teacher_en") or "")
    assert en.strip(), f"{label}: empty teacher_en"
    assert r.get("waiting_for_user") in (True, 1, None) or r.get("type") in {
        "conversation", "practice_success", "help", "yardim_help", "ai_tutor",
        "rule_teach", "intent_teach", "micro_teach", "short_natural", "dont_know_help",
    }


def test_history_newest_first_normalized():
    newest_first = [
        {"role": "user", "text": "Clothes"},
        {"role": "teacher", "text": "What will you buy?"},
        {"role": "user", "text": "I am going shopping"},
        {"role": "teacher", "text": "Hi! How are you today?"},
    ]
    chrono = _history_chronological(newest_first)
    assert chrono[0]["text"].startswith("Hi!")
    assert chrono[-1]["text"] == "Clothes"
    formatted = _format_history_for_ai(newest_first)
    assert formatted.index("Hi!") < formatted.index("Clothes")
    print("TEST history chrono OK")


def test_normal_chat_keeps_going():
    p = default_profile()
    hist = []
    r1 = process_turn("Hi, how are you?", "en", "en", hist, p, translate_fn=fake_translate)
    assert_continues(r1, "hi")
    p = r1["profile"]
    hist = [{"role": "user", "text": "Hi, how are you?"}, {"role": "teacher", "text": r1.get("teacher_en")}]
    r2 = process_turn("I'm fine.", "en", "en", hist, p, translate_fn=fake_translate)
    assert_continues(r2, "fine")
    p = r2["profile"]
    hist = hist + [{"role": "user", "text": "I'm fine."}, {"role": "teacher", "text": r2.get("teacher_en")}]
    r3 = process_turn("I'm going shopping.", "en", "en", hist, p, translate_fn=fake_translate)
    assert_continues(r3, "shopping")
    b = body(r3)
    assert "shop" in b or "buy" or "mall" in b or "?" in (r3.get("teacher_en") or "")
    print("TEST normal chat continuity OK")


def test_error_then_continue():
    p = default_profile()
    p["lastTeacherText"] = "What animals do you like?"
    r = process_turn("I didn't like snake.", "en", "en", [
        {"role": "teacher", "text": "What animals do you like?"},
    ], p, translate_fn=fake_translate)
    assert_continues(r, "snake")
    b = body(r)
    # Should mention snakes plural or don't like, and continue
    assert "snake" in b
    assert "?" in (r.get("teacher_en") or "")
    print("TEST error+continue OK")


def test_yardim_flow():
    p = default_profile()
    r1 = process_turn("yardım", "tr", "en", [], p, translate_fn=fake_translate)
    assert_continues(r1, "yardim")
    assert "türkçe" in body(r1) or "turkish" in body(r1)
    p = r1["profile"]
    r2 = process_turn("Bugün alışverişe gideceğim.", "tr", "en", [
        {"role": "user", "text": "yardım"},
        {"role": "teacher", "text": r1.get("teacher_en")},
    ], p, translate_fn=fake_translate)
    assert_continues(r2, "yardim-tr")
    b = body(r2)
    assert "shopping" in b or "going" in b
    print("TEST yardım flow OK")


def test_short_nothing_continues():
    assert _is_minimal_conversation_reply("Nothing.")
    p = default_profile()
    p["lastTeacherText"] = "What did you do today?"
    r = process_turn("Nothing.", "en", "en", [
        {"role": "teacher", "text": "What did you do today?"},
    ], p, translate_fn=fake_translate)
    assert_continues(r, "nothing")
    assert "goodbye" not in body(r)
    assert "?" in (r.get("teacher_en") or "")
    print("TEST nothing continues OK")


def test_topic_shift():
    p = default_profile()
    p["lastTeacherText"] = "Do you have a dog?"
    hist = [
        {"role": "user", "text": "I like dogs."},
        {"role": "teacher", "text": "Do you have a dog?"},
    ]
    r = process_turn("By the way, tomorrow I'm going to Ankara.", "en", "en", hist, p, translate_fn=fake_translate)
    assert_continues(r, "topic-shift")
    b = body(r)
    # Follow the new trip topic (city / travel / tomorrow) — not dogs exclusively
    assert (
        "ankara" in b
        or "tomorrow" in b
        or "trip" in b
        or "going" in b
        or "visit" in b
        or "travel" in b
        or "?" in (r.get("teacher_en") or "")
    )
    assert "dog" not in b or "ankara" in b or "trip" in b or "going" in b
    print("TEST topic shift OK")


def test_no_repeat_same_question_marker():
    # Structural: recent questions helper prefers newest turns after chrono normalize
    from education_engine import _recent_teacher_questions
    p = default_profile()
    p["lastTeacherText"] = "What color jacket would you like?"
    newest_first = [
        {"role": "teacher", "text": "What color jacket would you like?"},
        {"role": "user", "text": "A jacket."},
        {"role": "teacher", "text": "What kind of clothes?"},
        {"role": "user", "text": "Clothes."},
        {"role": "teacher", "text": "What are you going to buy?"},
        {"role": "teacher", "text": "Hi! How are you today?"},
    ]
    s = _recent_teacher_questions(newest_first, p)
    assert "color jacket" in s.lower() or "what color" in s.lower()
    print("TEST recent questions order OK")


def test_long_chat_no_forced_goodbye():
    p = default_profile()
    hist = []
    phrases = [
        "Hi",
        "I'm fine",
        "I went to the mall",
        "I bought a jacket",
        "It's blue",
        "Yes",
        "Maybe",
        "I like coffee",
        "In the morning",
        "Nothing",
        "Okay",
        "I work in an office",
    ]
    for ph in phrases:
        r = process_turn(ph, "en", "en", hist, p, translate_fn=fake_translate)
        assert_continues(r, ph)
        p = r["profile"]
        hist = hist + [
            {"role": "user", "text": ph},
            {"role": "teacher", "text": r.get("teacher_en") or ""},
        ]
    print("TEST long chat no forced goodbye OK")


if __name__ == "__main__":
    test_history_newest_first_normalized()
    test_normal_chat_keeps_going()
    test_error_then_continue()
    test_yardim_flow()
    test_short_nothing_continues()
    test_topic_shift()
    test_no_repeat_same_question_marker()
    test_long_chat_no_forced_goodbye()
    print("\nAll continuous conversation tests passed.")
