#!/usr/bin/env python3
"""Cümle Kur + Kendini Test Et motor testleri."""
from __future__ import annotations

from builder_engine import (
    _compute_weighted_score,
    _similarity,
    analyze_sentence_for_builder,
    generate_word_lesson,
    grade_sentence_answer,
    grade_word_answer,
    learning_level_from_stats,
    srs_weight,
)


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    mapping = {
        "kahve": "coffee",
        "kahve seviyorum.": "I love coffee.",
        "kahve sevmiyorum.": "I don't like coffee.",
        "kahve ister misin?": "Do you want coffee?",
        "bir kahve alabilir miyim?": "Can I have a coffee?",
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


def test_word_lesson_fallback():
    result = generate_word_lesson("kahve", "en", fake_translate)
    assert result["ok"], result
    assert result["word_tr"] == "kahve"
    assert "coffee" in result["target_word"].lower()
    assert len(result["examples"]) >= 5
    types = {ex.get("sentence_type") for ex in result["examples"]}
    assert len(types) >= 3
    print("TEST word lesson OK:", len(result["examples"]), "examples")


def test_sentence_analysis():
    tr = "Eve gitmek istiyorum."
    result = analyze_sentence_for_builder(tr, "en", fake_translate)
    assert result["ok"], result
    assert result["tr_sentence"] == tr
    assert "want" in result["target_sentence"].lower()
    assert result["pronunciation_tr"]
    print("TEST sentence analysis OK:", result["target_sentence"])


def test_grade_word_correct():
    result = grade_word_answer("kahve", "coffee", "I love coffee.", "en", fake_translate)
    assert result["ok"], result
    assert result["score"] >= 60
    print("TEST grade word OK:", result["score"])


def test_grade_word_wrong_order():
    result = grade_word_answer("kahve", "coffee", "I coffee love.", "en", fake_translate)
    assert result["ok"], result
    assert result["score"] < 90 or not result.get("grammar_ok")
    print("TEST grade wrong order OK:", result["score"], result.get("why_tr", "")[:60])


def test_grade_sentence_alternative():
    result = grade_sentence_answer(
        "Kahve istiyorum.",
        "I want a coffee.",
        "I'd like some coffee.",
        "en",
        alternatives=["I want coffee."],
    )
    assert result["ok"], result
    assert result["score"] >= 50
    print("TEST grade sentence alt OK:", result["score"])


def test_similarity_and_srs():
    assert _similarity("I love coffee", "I love coffee.") > 0.9
    scores = {"meaning": 90, "grammar": 80, "vocabulary": 85, "pronunciation": 70, "naturalness": 88}
    total = _compute_weighted_score(scores)
    assert 75 <= total <= 90, total
    w = srs_weight({"attempts": 5, "wrong": 3, "avgScore": 55, "pronunciationAvg": 60})
    assert w > 1.5
    level = learning_level_from_stats({"attempts": 5, "avgScore": 90})
    assert "İyi" in level
    print("TEST utils OK: score=", total, "srs=", round(w, 2))


if __name__ == "__main__":
    test_word_lesson_fallback()
    test_sentence_analysis()
    test_grade_word_correct()
    test_grade_word_wrong_order()
    test_grade_sentence_alternative()
    test_similarity_and_srs()
    print("\nAll builder tests passed.")
