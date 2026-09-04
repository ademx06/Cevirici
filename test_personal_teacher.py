#!/usr/bin/env python3
"""Kişisel İngilizce öğretmeni — 10 senaryo + hata hafızası."""
from __future__ import annotations

from education_engine import (
    _format_history_for_ai,
    _infer_meant_sentence,
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
        "çok yoruldum, eve gitmek istiyorum": "I'm very tired. I want to go home.",
        "Çok yoruldum, eve gitmek istiyorum": "I'm very tired. I want to go home.",
        "bugün çok yoruldum": "I'm very tired today.",
        "Bugün çok yoruldum.": "I'm very tired today.",
        "eve gitmek istiyorum": "I want to go home.",
        "çok yoruldum": "I'm very tired.",
    }
    en2tr = {
        "I'm going to buy a book.": "Kitap almaya gidiyorum.",
        "I went yesterday.": "Dün gittim.",
        "Yesterday I went.": "Dün gittim.",
        "Yesterday I went home.": "Dün eve gittim.",
        "I want to go home.": "Eve gitmek istiyorum.",
        "I'm very tired. I want to go home.": "Çok yoruldum. Eve gitmek istiyorum.",
        "I'm very tired.": "Çok yoruldum.",
        "I worked today.": "Bugün çalıştım.",
        "Do you like coffee?": "Kahve sever misin?",
        "I'm very tired today.": "Bugün çok yoruldum.",
        "I stayed at home yesterday.": "Dün evde kaldım.",
        "I went to work yesterday.": "Dün işe gittim.",
        "I watched a movie yesterday.": "Dün film izledim.",
    }
    if from_lang == "tr" and to_lang == "en":
        return tr2en.get(text, tr2en.get(text.strip().lower(), text))
    if from_lang == "en" and to_lang == "tr":
        return en2tr.get(text, text)
    return text


def _body(r: dict) -> str:
    return ((r.get("teacher_tr") or "") + "\n" + (r.get("teacher_en") or "")).lower()


def test_format_history_helper():
    assert "Student: hi" in _format_history_for_ai([{"role": "user", "text": "hi"}])
    print("TEST format_history OK")


def test_1_i_go_book():
    inferred, reason = _infer_meant_sentence("I go book.", "")
    assert inferred and "buy a book" in inferred.lower()
    assert reason and "kitap" in reason.lower()
    r = process_turn("I go book.", "en", "en", [], default_profile(), translate_fn=fake_translate)
    body = _body(r)
    assert "buy a book" in body or "buy a book" in (r.get("teacher_en") or "").lower()
    assert r.get("type") in ("intent_teach", "intent_guess", "rule_teach", "correction")
    assert "evet mi" not in body
    print("TEST 1 I go book OK")


def test_2_bare_yardim():
    r = process_turn("yardım", "tr", "en", [], default_profile(), translate_fn=fake_translate)
    body = _body(r)
    assert "türkçe" in body
    assert r.get("type") == "help"
    pending = (r.get("profile") or {}).get("pendingPracticePhrase")
    assert not pending or "türkçe" in body
    print("TEST 2 yardım OK")


def test_3_yardim_turkish():
    r = process_turn(
        "yardım çok yoruldum eve gitmek istiyorum",
        "tr", "en", [], default_profile(), translate_fn=fake_translate,
    )
    body = _body(r)
    assert "tired" in body or "want to go home" in body
    assert "söyle" in body or "dene" in body or "tekrar" in body or "devam" in body
    pending = (r.get("profile") or {}).get("pendingPracticePhrase") or ""
    assert "tired" in pending.lower() or "want" in pending.lower() or "home" in pending.lower()
    print("TEST 3 yardım+tr OK")


def test_4_i_go_yesterday_and_memory():
    p = default_profile()
    r = process_turn("I go yesterday.", "en", "en", [], p, translate_fn=fake_translate)
    assert "went" in (r.get("teacher_en") or "").lower()
    p = r["profile"]
    # Yeni davranış: doğrudan öğret (evet beklemeden) + hata kaydı
    if p.get("pendingIntentConfirm"):
        r = process_turn("evet", "tr", "en", [], p, translate_fn=fake_translate)
        p = r["profile"]
    body = _body(r)
    assert "went" in body
    errs = p.get("grammarErrors") or []
    assert any(
        (isinstance(e, dict) and e.get("category") == "past_tense")
        for e in errs
    ) or p.get("repeatedMistakes")
    print("TEST 4 I go yesterday + memory OK")


def test_5_recurring_past():
    p = default_profile()
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    assert any(int(m.get("times_repeated") or 0) >= 2 for m in (p.get("repeatedMistakes") or []))
    hist = [{"role": "teacher", "text": "What did you do yesterday?"}]
    r = process_turn("Yesterday I go home.", "en", "en", hist, p, translate_fn=fake_translate)
    body = _body(r)
    assert "went" in body
    assert "önce" in body or "before" in body or "pratik" in body or "went" in body
    print("TEST 5 recurring past OK")


def test_6_bilmiyorum():
    p = default_profile()
    p["lastTeacherText"] = "What did you do yesterday?"
    hist = [{"role": "teacher", "text": "What did you do yesterday?"}]
    r = process_turn("bilmiyorum", "tr", "en", hist, p, translate_fn=fake_translate)
    body = _body(r)
    assert r.get("type") == "dont_know_help"
    assert "seçenek" in body or "stayed" in body or "went" in body
    print("TEST 6 bilmiyorum OK")


def test_7_correct_no_overcorrect():
    level, correct, *_ = check_english("I am very tired today.")
    assert level == 1 and not correct
    r = process_turn("I am very tired today.", "en", "en", [], default_profile(), translate_fn=fake_translate)
    # Ağır kural düzeltmesi olmamalı
    assert r.get("type") not in ("rule_teach", "intent_guess", "intent_confirmed")
    print("TEST 7 correct tired OK")


def test_8_naturalness():
    level, correct, cat, *_ = check_english("I am very much tired.")
    assert level >= 2 and correct and "very tired" in correct.lower()
    r = process_turn("I am very much tired.", "en", "en", [], default_profile(), translate_fn=fake_translate)
    body = _body(r)
    assert "very tired" in body
    assert "doğal" in body or "natural" in body or "anlaşılır" in body
    print("TEST 8 naturalness OK")


def test_9_correct_question():
    level, correct, *_ = check_english("Do you like coffee?")
    assert level == 1 and not correct
    r = process_turn("Do you like coffee?", "en", "en", [], default_profile(), translate_fn=fake_translate)
    assert r.get("type") not in ("rule_teach", "intent_guess")
    print("TEST 9 Do you like coffee OK")


def test_10_you_like_coffee():
    inferred, reason = _infer_meant_sentence("You like coffee?", "")
    assert inferred and inferred.lower().startswith("do you like")
    r = process_turn("You like coffee?", "en", "en", [], default_profile(), translate_fn=fake_translate)
    body = _body(r)
    assert "do you like coffee" in body
    print("TEST 10 You like coffee? OK")


def test_greeting_resume_weakness():
    p = default_profile()
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    p = merge_profile(p, _record_mistake(p, "I go yesterday.", "I went yesterday.", "past_tense"))
    g = greeting("en", p, translate_fn=fake_translate)
    motiv = (g.get("motivation") or "") + (g.get("teacher_tr") or "")
    assert "past" in motiv.lower() or "went" in motiv.lower() or "zorlanmış" in motiv.lower()
    print("TEST greeting resume OK")


if __name__ == "__main__":
    test_format_history_helper()
    test_1_i_go_book()
    test_2_bare_yardim()
    test_3_yardim_turkish()
    test_4_i_go_yesterday_and_memory()
    test_5_recurring_past()
    test_6_bilmiyorum()
    test_7_correct_no_overcorrect()
    test_8_naturalness()
    test_9_correct_question()
    test_10_you_like_coffee()
    test_greeting_resume_weakness()
    print("\nAll personal teacher tests passed.")
