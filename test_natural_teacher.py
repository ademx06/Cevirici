#!/usr/bin/env python3
"""Doğal kişisel öğretmen — evet/hayır yok, özel isim, Tired, sohbet devamı."""
from __future__ import annotations

from education_engine import (
    _infer_meant_sentence,
    _is_short_natural_reply,
    _record_mistake,
    check_english,
    default_profile,
    greeting,
    merge_profile,
    process_turn,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    tr2en = {
        "çok yoruldum eve gitmek istiyorum": "I'm very tired. I want to go home.",
        "Samet'le konuşuyorum": "I'm talking to Samet.",
        "samet'le konuşuyorum": "I'm talking to Samet.",
        "Mehmet'le konuşuyorum": "I'm talking to Mehmet.",
    }
    en2tr = {
        "I'm going to buy a book.": "Kitap almaya gidiyorum.",
        "I went yesterday.": "Dün gittim.",
        "Yesterday I went home.": "Dün eve gittim.",
        "I'm talking to Samet.": "Samet'le konuşuyorum.",
        "I'm very tired. I want to go home.": "Çok yoruldum. Eve gitmek istiyorum.",
        "How are you?": "Nasılsın?",
        "I'm tired.": "Yorgunum.",
        "I worked today.": "Bugün çalıştım.",
        "Do you like coffee?": "Kahve sever misin?",
        "I'm very tired.": "Çok yorgunum.",
    }
    if from_lang == "tr" and to_lang == "en":
        return tr2en.get(text, tr2en.get(text.strip(), text))
    if from_lang == "en" and to_lang == "tr":
        return en2tr.get(text, text)
    return text


def body(r: dict) -> str:
    return ((r.get("teacher_en") or "") + "\n" + (r.get("teacher_tr") or "")).lower()


def test_no_yes_no_on_clear_intent():
    r = process_turn("I go book.", "en", "en", [], default_profile(), translate_fn=fake_translate)
    b = body(r)
    assert r.get("type") == "intent_teach"
    assert "buy a book" in b
    assert "evet mi" not in b and "evet veya hayır" not in b
    assert "?" in (r.get("teacher_en") or "")  # follow-up
    assert not (r.get("profile") or {}).get("pendingIntentConfirm")
    print("TEST no yes/no + follow-up OK")


def test_speak_samet_preserves_name():
    inferred, _ = _infer_meant_sentence("I speak samet", "")
    assert inferred and "Samet" in inferred and "sameness" not in inferred.lower()
    r = process_turn("I speak samet", "en", "en", [], default_profile(), translate_fn=fake_translate)
    b = body(r)
    assert "samet" in b
    assert "sameness" not in b
    assert "talking to" in b
    print("TEST I speak Samet OK")


def test_tired_not_wrong():
    assert _is_short_natural_reply("Tired", "How are you feeling?")
    p = default_profile()
    p["lastTeacherText"] = "How are you feeling today?"
    r = process_turn("Tired", "en", "en", [{"role": "teacher", "text": "How are you feeling today?"}], p, translate_fn=fake_translate)
    b = body(r)
    assert r.get("type") == "conversation"
    assert "❌" not in b
    assert "wrong" not in b
    assert "?" in (r.get("teacher_en") or "")
    print("TEST Tired natural OK")


def test_how_are_you_going():
    r = process_turn(
        "Hello how are you going",
        "en", "en",
        [{"role": "teacher", "text": "Hey! How are you today?"}],
        default_profile(),
        translate_fn=fake_translate,
    )
    b = body(r)
    assert "how are you?" in b
    assert "evet mi" not in b
    print("TEST how are you going OK")


def test_yardim_bare():
    r = process_turn("yardım", "tr", "en", [], default_profile(), translate_fn=fake_translate)
    assert "türkçe" in body(r)
    print("TEST yardım OK")


def test_yardim_turkish_and_name():
    r = process_turn(
        "yardım çok yoruldum eve gitmek istiyorum",
        "tr", "en", [], default_profile(), translate_fn=fake_translate,
    )
    b = body(r)
    assert "tired" in b and ("home" in b or "want" in b)
    r2 = process_turn("yardım Samet'le konuşuyorum", "tr", "en", [], default_profile(), translate_fn=fake_translate)
    b2 = body(r2)
    assert "samet" in b2 and "sameness" not in b2
    print("TEST yardım+tr / Samet OK")


def test_past_memory():
    p = default_profile()
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    r = process_turn(
        "Yesterday I go home.",
        "en", "en",
        [{"role": "teacher", "text": "What did you do yesterday?"}],
        p,
        translate_fn=fake_translate,
    )
    assert "went" in body(r)
    print("TEST past memory OK")


def test_correct_no_overfix():
    assert check_english("I am tired.")[0] == 1
    r = process_turn("I am tired.", "en", "en", [], default_profile(), translate_fn=fake_translate)
    assert r.get("type") not in ("intent_teach", "rule_teach", "intent_guess")
    print("TEST correct OK")


def test_you_like_coffee():
    r = process_turn("You like coffee?", "en", "en", [], default_profile(), translate_fn=fake_translate)
    b = body(r)
    assert "do you like coffee" in b
    assert "evet mi" not in b
    print("TEST You like coffee OK")


def test_greeting_natural():
    g = greeting("en", default_profile(), translate_fn=fake_translate)
    tr = (g.get("teacher_tr") or "").lower()
    assert "bugün: selamlaşma" not in tr
    assert "hazır mısın" not in tr
    assert "how are you" in (g.get("teacher_en") or "").lower()
    print("TEST greeting natural OK")


if __name__ == "__main__":
    test_no_yes_no_on_clear_intent()
    test_speak_samet_preserves_name()
    test_tired_not_wrong()
    test_how_are_you_going()
    test_yardim_bare()
    test_yardim_turkish_and_name()
    test_past_memory()
    test_correct_no_overfix()
    test_you_like_coffee()
    test_greeting_natural()
    print("\nAll natural teacher tests passed.")
