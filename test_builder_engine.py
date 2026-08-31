#!/usr/bin/env python3
"""Cümle Kur motor testleri — analiz kalitesi + telaffuz."""
from __future__ import annotations

from builder_engine import (
    GENERIC_BANNED_RE,
    _compute_weighted_score,
    _dedupe_explanations,
    _is_generic_explanation,
    _rule_pronunciation_en,
    _similarity,
    analyze_sentence_for_builder,
    generate_word_lesson,
    grade_sentence_answer,
    grade_word_answer,
    learning_level_from_stats,
    srs_weight,
)
from pronunciation_service import build_sentence, get_word


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    mapping = {
        "kahve": "coffee",
        "kahve seviyorum.": "I love coffee.",
        "kahve sevmiyorum.": "I don't like coffee.",
        "kahve ister misin?": "Do you want coffee?",
        "bir kahve alabilir miyim?": "Can I have a coffee?",
        "sana bir kahve alayım mı?": "Shall I get you a coffee?",
        "sabahları kahve içmezsin, öyle değil mi?": "You don't drink coffee in the morning, do you?",
        "her gün kahve içerim.": "I drink coffee every day.",
        "kahve içmek istiyorum.": "I want to drink coffee.",
        "bugün iş yerinde çok yoruldum.": "today at work very tired I",
        "eve gitmek istiyorum.": "I want to go home.",
    }
    low = text.lower().strip()
    if low in mapping:
        return mapping[low]
    if from_lang == "tr" and to_lang == "en":
        return " ".join(mapping.get(w, w) for w in low.split())
    return text


def test_word_lesson_quality():
    result = generate_word_lesson("kahve", "en", fake_translate)
    assert result["ok"], result
    examples = result["examples"]
    assert len(examples) >= 5

    for ex in examples:
        how = ex.get("how_it_is_formed_tr") or ""
        assert not _is_generic_explanation(how), f"Generic: {how[:80]}"
        assert "günlük konuşmada kullan" not in how.lower()
        assert ex.get("structure_tr") or ex.get("word_breakdown")
        assert ex.get("pronunciation_tr")
        # dont/layk/kofi tarzı — du u vant olmamalı
        pron = ex.get("pronunciation_tr", "").lower()
        assert "du u vant" not in pron
        assert "kofii" not in pron

    assert _dedupe_explanations(examples), "Explanations must be unique"
    types = {ex.get("sentence_type") for ex in examples}
    assert len(types) >= 4, types

    # Olumsuz cümle don't açıklaması içermeli
    neg = next((e for e in examples if e.get("sentence_type") == "negative"), None)
    assert neg and "don't" in (neg.get("how_it_is_formed_tr") or "").lower()

    # Tag question
    tag = next((e for e in examples if e.get("sentence_type") == "tag_question"), None)
    assert tag and "tag" in (tag.get("how_it_is_formed_tr") or "").lower()

    print("TEST word lesson quality OK:", len(examples), "examples,", len(types), "types")


def test_pronunciation_consistency():
    """Aynı kelime her yerde aynı okunuş."""
    result = generate_word_lesson("kahve", "en", fake_translate)
    coffee_pron = get_word("en", "coffee")["pronunciation_tr"]
    assert coffee_pron == "kofi"

    shall_pron = get_word("en", "shall")["pronunciation_tr"]
    assert shall_pron == "şal"

    for ex in result["examples"]:
        pron = (ex.get("pronunciation_tr") or "").lower()
        if "coffee" in (ex.get("target") or "").lower():
            assert "kofii" not in pron
            assert "kah-fi" not in pron
            assert "kofi" in pron or coffee_pron in pron
        words = {w["word"].lower(): w["pronunciation_tr"] for w in (ex.get("word_pronunciations") or [])}
        if "coffee" in words:
            assert words["coffee"] == "kofi"

    offer = next((e for e in result["examples"] if e.get("sentence_type") == "offer"), None)
    assert offer, "offer example missing"
    assert "şal" in offer["pronunciation_tr"].lower()
    pats = offer.get("pattern_examples") or []
    assert pats and isinstance(pats[0], dict)
    assert pats[0].get("tr")
    assert pats[0].get("pronunciation_tr")
    water_pat = next((p for p in pats if "water" in (p.get("target") or "").lower()), None)
    if water_pat:
        assert water_pat.get("new_words")

    # Cümle analizi aynı sözlüğü kullanmalı
    sent = build_sentence("I don't like coffee.", "en")
    w = {x["word"].lower(): x["pronunciation_tr"] for x in sent["word_pronunciations"]}
    assert w.get("coffee") == "kofi"
    assert "dont" in sent["pronunciation_tr"].lower()

    print("TEST pronunciation consistency OK")


def test_no_duplicate_teaching_header():
    result = generate_word_lesson("kahve", "en", fake_translate)
    for ex in result["examples"]:
        how = ex.get("how_it_is_formed_tr") or ""
        assert how.count("Nasıl kuruldu") == 0, f"Duplicate header in: {how[:60]}"
    print("TEST no duplicate header OK")


def test_pronunciation_rules():
    p = _rule_pronunciation_en("I don't like coffee.")
    pron = p["pronunciation_tr"].lower()
    assert "dont" in pron or "don't" in pron.replace("'", "")
    assert "layk" in pron or "like" not in pron
    assert "du u" not in pron
    words = {w["word"].lower(): w["pronunciation_tr"] for w in p["word_pronunciations"]}
    assert words.get("coffee") == "kofi"
    print("TEST pronunciation OK:", p["pronunciation_tr"])


def test_sentence_analysis():
    tr = "Eve gitmek istiyorum."
    result = analyze_sentence_for_builder(tr, "en", fake_translate)
    assert result["ok"], result
    assert "want" in result["target_sentence"].lower()
    assert result.get("pronunciation_tr")
    print("TEST sentence analysis OK:", result["target_sentence"])


def test_grade_word_correct():
    result = grade_word_answer("kahve", "coffee", "I love coffee.", "en", fake_translate)
    assert result["ok"], result
    assert result["score"] >= 60
    print("TEST grade word OK:", result["score"])


def test_grade_honest_pronunciation():
    result = grade_word_answer("kahve", "coffee", "I love coffee.", "en", fake_translate)
    assert result.get("pronunciation_note_tr") or result.get("pronunciation_ok") is None
    print("TEST honest pronunciation OK")


def test_similarity_and_srs():
    assert _similarity("I love coffee", "I love coffee.") > 0.9
    scores = {"meaning": 90, "grammar": 80, "vocabulary": 85, "pronunciation": 70, "naturalness": 88}
    total = _compute_weighted_score(scores)
    assert 75 <= total <= 90, total
    w = srs_weight({"attempts": 5, "wrong": 3, "avgScore": 55, "pronunciationAvg": 60})
    assert w > 1.5
    level = learning_level_from_stats({"attempts": 5, "avgScore": 90})
    assert "İyi" in level
    print("TEST utils OK")


if __name__ == "__main__":
    test_word_lesson_quality()
    test_pronunciation_consistency()
    test_no_duplicate_teaching_header()
    test_pronunciation_rules()
    test_sentence_analysis()
    test_grade_word_correct()
    test_grade_honest_pronunciation()
    test_similarity_and_srs()
    print("\nAll builder tests passed.")
