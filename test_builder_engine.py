#!/usr/bin/env python3
"""Cümle Kur motor testleri — kelimeye özel öğretim + telaffuz."""
from __future__ import annotations

from builder_engine import (
    _compute_weighted_score,
    _dedupe_explanations,
    _is_generic_explanation,
    _norm,
    _rule_pronunciation_en,
    _similarity,
    analyze_sentence_for_builder,
    generate_word_lesson,
    grade_sentence_answer,
    grade_word_answer,
    learning_level_from_stats,
    srs_weight,
)
from pronunciation_service import build_pronunciation_bundle, get_word
from word_teaching_engine import detect_category, validate_lesson_quality


def fake_translate(text: str, from_lang: str, to_lang: str) -> str:
    mapping = {
        "kahve": "coffee",
        "masa": "table",
        "musluk": "faucet",
        "pencere": "window",
        "kapı": "door",
        "kitap": "book",
        "araba": "car",
        "mutlu": "happy",
        "çalışmak": "work",
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
        "pazara gitmem gerekiyor evde yemek yapmak için hiçbir şey yok.": (
            "I need to go to the market because I have nothing to cook at home."
        ),
    }
    low = text.lower().strip()
    if low in mapping:
        return mapping[low]
    if from_lang == "tr" and to_lang == "en":
        return " ".join(mapping.get(w, w) for w in low.split())
    return text


def test_coffee_lesson_natural():
    result = generate_word_lesson("kahve", "en", fake_translate)
    assert result["ok"], result
    examples = result["examples"]
    assert len(examples) >= 5
    assert detect_category("kahve", "coffee") == "beverage"

    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "drink" in targets or "have" in targets or "making" in targets

    for ex in examples:
        how = ex.get("how_it_is_formed_tr") or ""
        assert not _is_generic_explanation(how), f"Generic: {how[:80]}"
        assert "kofii" not in (ex.get("pronunciation_tr") or "").lower()

    assert _dedupe_explanations(examples), "Explanations must be unique"
    print("TEST coffee lesson OK:", len(examples), "examples")


def test_table_lesson_no_template_copy():
    """masa/table için I love table gibi şablonlar YASAK."""
    result = generate_word_lesson("masa", "en", fake_translate)
    assert result["ok"], result
    examples = result["examples"]
    assert len(examples) >= 5
    assert detect_category("masa", "table") == "furniture"

    banned = ("i love table", "do you want table", "don't drink table", "you don't drink table")
    for ex in examples:
        t = safe_str(ex.get("target")).lower()
        for b in banned:
            assert b not in t, f"Banned template found: {t}"
        how = ex.get("how_it_is_formed_tr") or ""
        assert "kahve seviyorum" not in how.lower()
        assert "love + coffee" not in how.lower()

    targets = [safe_str(ex.get("target")).lower() for ex in examples]
    assert any("on the table" in t or "the table is" in t or "at the table" in t for t in targets)
    print("TEST table lesson OK — no template copy:", len(examples), "examples")


def test_pronunciation_consistency():
    coffee_pron = get_word("en", "coffee")["pronunciation_tr"]
    assert coffee_pron == "kofi"
    result = generate_word_lesson("kahve", "en", fake_translate)
    for ex in result["examples"]:
        words = {w["word"].lower(): w["pronunciation_tr"] for w in (ex.get("word_pronunciations") or [])}
        if "coffee" in words:
            assert words["coffee"] == "kofi"
    sent = build_pronunciation_bundle("I don't like coffee.", "en")
    w = {x["word"].lower(): x["pronunciation_tr"] for x in sent["word_pronunciations"]}
    assert w.get("coffee") == "kofi"
    print("TEST pronunciation consistency OK")


def test_faucet_lesson():
    result = generate_word_lesson("musluk", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🚰"
    examples = result["examples"]
    assert len(examples) >= 5
    banned = ("i love faucet", "do you want faucet", "drink the faucet")
    for ex in examples:
        t = safe_str(ex.get("target")).lower()
        for b in banned:
            assert b not in t
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "leak" in targets or "turn off" in targets
    # Doğal cümle telaffuzu kelime birleştirmeden farklı olabilir
    leak_ex = next((e for e in examples if "leaking" in safe_str(e.get("target")).lower()), None)
    if leak_ex:
        assert leak_ex.get("pronunciation_tr")
    print("TEST faucet lesson OK")


def test_car_happy_work_distinct():
    for word_tr, tw, icon in (
        ("araba", "car", "🚗"),
        ("mutlu", "happy", "😊"),
        ("çalışmak", "work", "💼"),
    ):
        result = generate_word_lesson(word_tr, "en", fake_translate)
        assert result["ok"], result
        assert result.get("word_icon") == icon, f"{word_tr} icon"
        targets = [safe_str(e.get("target")).lower() for e in result["examples"]]
        assert not any("i love " + tw in t for t in targets), f"template on {word_tr}"
    print("TEST car/happy/work distinct OK")


def test_no_duplicate_teaching_header():
    for word in ("kahve", "masa"):
        result = generate_word_lesson(word, "en", fake_translate)
        for ex in result["examples"]:
            how = ex.get("how_it_is_formed_tr") or ""
            assert how.count("Nasıl kuruldu") == 0, f"Duplicate header in: {how[:60]}"
    print("TEST no duplicate header OK")


def test_pronunciation_rules():
    p = _rule_pronunciation_en("I don't like coffee.")
    pron = p["pronunciation_tr"].lower()
    assert "dont" in pron
    assert "du u" not in pron
    words = {w["word"].lower(): w["pronunciation_tr"] for w in p["word_pronunciations"]}
    assert words.get("coffee") == "kofi"
    print("TEST pronunciation OK:", p["pronunciation_tr"])


def test_market_sentence_teaching():
    tr = "Pazara gitmem gerekiyor evde yemek yapmak için hiçbir şey yok."
    result = analyze_sentence_for_builder(tr, "en", fake_translate)
    assert result["ok"], result
    target = result["target_sentence"].lower()
    assert "need" in target and "market" in target
    how = result.get("how_it_is_formed_tr") or ""
    assert "need to" in how.lower() or "need" in how.lower()
    assert result.get("meaning_summary_tr") or len(how) > 100
    patterns = result.get("important_patterns") or []
    assert patterns or "because" in how.lower()
    print("TEST market sentence OK:", result["target_sentence"][:60])


def test_sentence_analysis():
    tr = "Eve gitmek istiyorum."
    result = analyze_sentence_for_builder(tr, "en", fake_translate)
    assert result["ok"], result
    assert "want" in result["target_sentence"].lower()
    assert result.get("pronunciation_tr")
    print("TEST sentence analysis OK:", result["target_sentence"])


def test_can_you_pattern_examples():
    tr = "Bana bir kahve getirebilir misin?"
    result = analyze_sentence_for_builder(tr, "en", fake_translate)
    assert result["ok"], result
    examples = result.get("pattern_examples") or []
    assert len(examples) >= 10, f"expected 10+ examples, got {len(examples)}"
    targets = {_norm(safe_str(e.get("target"))) for e in examples}
    assert "can you open the door?" in targets
    assert "can you help me?" in targets
    assert "can you close the window?" in targets
    for ex in examples:
        assert safe_str(ex.get("tr")).strip(), f"missing TR: {ex.get('target')}"
        assert safe_str(ex.get("pronunciation_tr")).strip(), f"missing pron: {ex.get('target')}"
    print("TEST can-you pattern examples OK:", len(examples))


def test_window_no_cross_word_leak():
    result = generate_word_lesson("pencere", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🪟"
    assert result.get("target_word") == "window"
    examples = result.get("examples") or []
    assert len(examples) >= 4, f"expected examples, got {len(examples)}"
    forbidden = ("masa", "kahve", "musluk", "table", "coffee", "faucet")
    for ex in examples:
        tr = safe_str(ex.get("tr")).lower()
        tg = safe_str(ex.get("target")).lower()
        how = safe_str(ex.get("how_it_is_formed_tr")).lower()
        assert "pencere" in tr or "pencer" in tr, f"TR missing pencere: {tr}"
        assert "window" in tg, f"EN missing window: {tg}"
        assert "window" in tg and " window" in f" {tg}", f"bad caps: {tg}"
        for bad in forbidden:
            assert bad not in how, f"leak in how for {bad}: {how[:80]}"
            assert bad not in tr, f"leak in tr for {bad}: {tr}"
    print("TEST window isolation OK:", len(examples))


def test_word_sequence_isolation():
  words = ("kahve", "pencere", "musluk", "kapı", "araba", "kitap", "pencere")
  markers = {
      "kahve": ("coffee", "☕", ("masa", "pencere", "window")),
      "pencere": ("window", "🪟", ("kahve", "coffee", "masa", "table")),
      "musluk": ("faucet", "🚰", ("pencere", "window", "kahve", "coffee")),
      "kapı": ("door", "🚪", ("masa", "table", "kahve", "coffee")),
      "araba": ("car", "🚗", ("masa", "pencere", "kahve")),
      "kitap": ("book", "📚", ("masa", "pencere", "kahve", "coffee")),
  }
  for w in words:
      result = generate_word_lesson(w, "en", fake_translate)
      assert result["ok"], result
      tw, icon, forbidden = markers[w]
      assert result.get("target_word") == tw, w
      assert result.get("word_icon") == icon, w
      for ex in result.get("examples") or []:
          blob = " ".join([
              safe_str(ex.get("tr")),
              safe_str(ex.get("target")),
              safe_str(ex.get("how_it_is_formed_tr")),
          ]).lower()
          for bad in forbidden:
              assert bad not in blob, f"{w} leaked {bad}: {blob[:100]}"
  print("TEST word sequence isolation OK")


def test_door_icon():
    result = generate_word_lesson("kapı", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🚪"
    print("TEST door icon OK")


def test_grade_word_correct():
    result = grade_word_answer("kahve", "coffee", "I drink coffee every morning.", "en", fake_translate)
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


def safe_str(s):
    return str(s or "")


if __name__ == "__main__":
    test_coffee_lesson_natural()
    test_table_lesson_no_template_copy()
    test_pronunciation_consistency()
    test_faucet_lesson()
    test_car_happy_work_distinct()
    test_no_duplicate_teaching_header()
    test_pronunciation_rules()
    test_market_sentence_teaching()
    test_sentence_analysis()
    test_can_you_pattern_examples()
    test_window_no_cross_word_leak()
    test_word_sequence_isolation()
    test_door_icon()
    test_grade_word_correct()
    test_grade_honest_pronunciation()
    test_similarity_and_srs()
    print("\nAll builder tests passed.")
