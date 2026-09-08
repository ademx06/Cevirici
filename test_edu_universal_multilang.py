#!/usr/bin/env python3
"""Eğitim çoklu dil: dil kilidi, ASR≠hata, EN fallback yasağı, soru alanları."""
from __future__ import annotations

from education_engine import (
    _asr_wrong_language,
    _extract_teacher_question,
    _is_strong_english,
    _sanitize_ai_correction,
    _teacher_response_wrong_language,
    check_english,
    default_profile,
    greeting,
    process_turn,
)


def fake(t, a, b):
    return t if a == b else f"[{b}]{t}"


def test_en_grammar_are():
    lvl, phrase, *_ = check_english("I are 28 years old")
    assert lvl >= 2 and phrase and "i am" in phrase.lower()
    print("TEST1 I are OK")


def test_en_am_ok():
    assert check_english("I am 28 years old")[0] == 1
    print("TEST2 I am OK")


def test_from_no_froming():
    r = process_turn("I am from Bursa", "en", "en", [], default_profile(), translate_fn=fake)
    assert "froming" not in ((r.get("teacher_en") or "") + (r.get("correction") or "")).lower()
    print("TEST3 from OK")


def test_german_no_english_curriculum():
    assert not _asr_wrong_language("Hallo, wie geht's? Gut, wie geht es dir?", "de")
    r = process_turn(
        "Hallo, wie geht's? Gut, wie geht es dir?",
        "de", "de", [], default_profile(), translate_fn=fake,
    )
    te = (r.get("teacher_en") or "").lower()
    assert r.get("target_lang") == "de"
    assert "i'd like to buy" not in te
    assert "how much" not in te
    assert int(r.get("correction_level") or 1) == 1 or r.get("type") in (
        "ai_tutor", "conversation", "greeting", "stt_clarify",
    )
    # Prefer German reply (or localized)
    assert (
        "wie" in te or "gut" in te or "heute" in te or "machst" in te
        or te.startswith("[de]")
        or r.get("type") == "stt_clarify"
    )
    print("TEST4 German OK", (r.get("teacher_en") or "")[:100])


def test_german_tts_fields():
    g = greeting("de", translate_fn=fake)
    assert g.get("tts_language") == "de" or g.get("target_lang") == "de"
    assert g.get("has_question") or "?" in (g.get("teacher_en") or "")
    assert g.get("message_id")
    q = g.get("question_text") or _extract_teacher_question(g.get("teacher_en") or "")
    assert q and "?" in q
    print("TEST5 German TTS fields OK")


def test_multiple_meaning_bank():
    # Context disambiguation helpers: strong English bank sentences not forced as DE errors
    money = "I went to the bank to withdraw money."
    river = "We sat on the bank of the river."
    assert _is_strong_english(money) and _is_strong_english(river)
    # When learning EN, these are valid learner sentences (not ASR mismatch)
    assert not _asr_wrong_language(money, "en")
    assert not _asr_wrong_language(river, "en")
    # When learning DE, English ASR of bank sentences is mismatch
    assert _asr_wrong_language(money, "de")
    assert _asr_wrong_language(river, "de")
    # Spanish / Russian / French markers
    assert not _asr_wrong_language("Hola, ¿cómo estás?", "es")
    assert _asr_wrong_language("I'd like to buy a coffee", "es")
    assert not _asr_wrong_language("Привет, как дела?", "ru")
    assert _asr_wrong_language("What did you do yesterday?", "ru")
    assert not _asr_wrong_language("Bonjour, comment ça va?", "fr")
    print("TEST6 multi-meaning / lang detect OK")


def test_asr_mismatch_not_grammar_error():
    r = process_turn(
        "I'd like to buy a jacket please",
        "en", "de", [], default_profile(), translate_fn=fake,
    )
    assert r.get("type") == "stt_clarify"
    assert int(r.get("correction_level") or 1) == 1
    assert not r.get("correction")
    te = (r.get("teacher_en") or "").lower()
    assert "buy" not in te or "klar" in te or "verstanden" in te or "wieder" in te
    print("TEST7 ASR mismatch OK")


def test_sanitize_blocks_en_for_de():
    p = _sanitize_ai_correction(
        "Ich bin müde",
        {
            "teacher_en": "I'd like to buy something. How much is it?",
            "correction_level": 2,
            "correct_phrase": "I would like to buy",
            "suggested_practice": "I'd like to buy",
        },
        target_lang="de",
    )
    assert not p.get("correct_phrase")
    assert not p.get("suggested_practice")
    assert _teacher_response_wrong_language(
        "I'd like to buy something. How much is it?", "de",
    )
    print("TEST sanitize EN leak OK")


def test_topic_and_meta():
    p = default_profile()
    p["completedTopics"] = ["coffee"]
    p["lastTeacherText"] = "Do you like coffee?"
    r = process_turn(
        "We already talked about that.",
        "en", "en",
        [{"role": "teacher", "text": "Do you like coffee?"}],
        p,
        translate_fn=fake,
    )
    # Should continue without forcing coffee buy curriculum
    body = ((r.get("teacher_en") or "") + (r.get("teacher_tr") or "")).lower()
    assert "i'd like to buy" not in body
    print("TEST8/9 meta/topic OK", (r.get("teacher_en") or "")[:80])


def test_user_changes_topic():
    p = default_profile()
    p["lastTeacherText"] = "What do you do for work?"
    r = process_turn(
        "I have another question.",
        "en", "en",
        [{"role": "teacher", "text": "What do you do for work?"}],
        p,
        translate_fn=fake,
    )
    assert r.get("teacher_en")
    assert int(r.get("correction_level") or 1) <= 2
    print("TEST10 topic change OK")


def test_spanish_russian_greetings():
    for code, needle in (("es", "Cómo"), ("ru", "Как"), ("fr", "Comment")):
        g = greeting(code, translate_fn=fake)
        te = g.get("teacher_en") or ""
        assert g.get("target_lang") == code
        assert needle.lower() in te.lower() or te.startswith(f"[{code}]") or "?" in te
    print("TEST ES/RU/FR greetings OK")


if __name__ == "__main__":
    test_en_grammar_are()
    test_en_am_ok()
    test_from_no_froming()
    test_german_no_english_curriculum()
    test_german_tts_fields()
    test_multiple_meaning_bank()
    test_asr_mismatch_not_grammar_error()
    test_sanitize_blocks_en_for_de()
    test_topic_and_meta()
    test_user_changes_topic()
    test_spanish_russian_greetings()
    print("\nAll edu universal multilang tests passed.")
