#!/usr/bin/env python3
"""Cümle Kur motor testleri — kelimeye özel öğretim + telaffuz."""
from __future__ import annotations

import os
os.environ.setdefault("WORD_LESSON_ALLOW_TEMPLATES", "1")

import re

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
        "ayakkabı": "shoe",
        "ayakkabi": "shoe",
        "soda": "soda",
        "maden suyu": "mineral water",
        "misir": "sweet corn",
        "bardak": "glass",
        "fatura": "invoice",
    "sakız": "gum",
    "sakiz": "gum",
    "bal": "honey",
    "sigara": "cigarette",
    "gözlük": "glasses",
    "çorap": "socks",
    "şemsiye": "umbrella",
    "cüzdan": "wallet", "cuzdan": "wallet",
    "bıçak": "knife",
    "yastık": "pillow",
    "bisiklet": "bicycle",
    "radyo": "radio",
    "parfüm": "perfume",
    "eğlence": "entertainment",
    "eglence": "entertainment",
        "sessiz": "quiet",
        "hızlı": "quickly", "hizli": "quickly",
        "kedi": "cat",
        "elma": "apple",
        "çalışmak": "work", "calismak": "work",
        "ben": "I",
        "ile": "with",
        "ve": "and",
        "merhaba": "hello",
        "mutlu": "happy",
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


def _blob_contains_word(blob: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word.lower())}\b", blob.lower()))


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
  words = ("kahve", "ayakkabı", "pencere", "masa", "musluk", "kapı", "araba", "kitap", "pencere")
  markers = {
      "kahve": ("coffee", "☕", ("masa", "pencere", "window")),
      "masa": ("table", "🍽️", ("kahve", "coffee", "pencere", "window", "socks", "sock")),
      "pencere": ("window", "🪟", ("kahve", "coffee", "masa", "table")),
      "musluk": ("faucet", "🚰", ("pencere", "window", "kahve", "coffee")),
      "kapı": ("door", "🚪", ("masa", "table", "kahve", "coffee")),
      "araba": ("car", "🚗", ("masa", "pencere", "kahve")),
      "kitap": ("book", "📚", ("masa", "pencere", "kahve", "coffee")),
      "ayakkabı": ("shoe", "👟", ("socks", "sock", "çorap", "kahve", "coffee", "masa", "table")),
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
              assert not _blob_contains_word(blob, bad), f"{w} leaked {bad}: {blob[:100]}"
  print("TEST word sequence isolation OK")


def test_shoe_no_socks_leak():
    result = generate_word_lesson("ayakkabı", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "👟"
    assert result.get("target_word") == "shoe"
    examples = result.get("examples") or []
    assert len(examples) >= 4, f"expected 4+ examples, got {len(examples)}"
    forbidden = ("socks", "sock", "çorap", "table", "coffee", "window", "chair")
    for ex in examples:
        blob = " ".join([
            safe_str(ex.get("tr")),
            safe_str(ex.get("target")),
            safe_str(ex.get("how_it_is_formed_tr")),
        ]).lower()
        for bad in forbidden:
            assert not _blob_contains_word(blob, bad), (
                f"socks/leak in shoe lesson: {bad} in {blob[:80]}"
            )
        assert "shoe" in safe_str(ex.get("target")).lower()
        for p in ex.get("pattern_examples") or []:
            pt = safe_str(p.get("target")).lower()
            assert "sock" not in pt, f"socks in pattern: {pt}"
            assert "shoe" in pt
    usage = result.get("usage") or {}
    assert usage.get("common_verbs")
    assert usage.get("common_phrases")
    print("TEST shoe isolation OK:", len(examples))


def test_soda_lesson():
    result = generate_word_lesson("gazoz", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🥤"
    assert result.get("target_word") == "soda"
    examples = result.get("examples") or []
    assert len(examples) >= 4
    for ex in examples:
        tg = safe_str(ex.get("target")).lower()
        assert "soda" in tg or "cola" in tg
        assert "sock" not in tg
        assert "black soda" not in tg
        how = safe_str(ex.get("how_it_is_formed_tr"))
        assert len(how) >= 20
        assert "kelimeye özel doğal yapı" not in how.lower()
        label = safe_str(ex.get("structure_label_tr"))
        assert "Dil Bilgisi Formülü" in label
        assert any(str(i) in safe_str(ex.get("sentence_type_label")) for i in range(1, 14)), (
            f"missing numbered pattern label: {ex.get('sentence_type_label')}"
        )
    usage = result.get("usage") or {}
    for v in usage.get("common_verbs") or []:
        assert v.get("tr"), f"empty verb tr: {v}"
    for p in usage.get("common_phrases") or []:
        assert p.get("tr") and p.get("pronunciation_tr")
    alts = usage.get("alternative_terms_tr") or []
    assert len(alts) >= 3, "soda should have alternative TR terms"
    assert any("sparkling water" in safe_str(a.get("en")).lower() for a in alts)
    assert any("maden suyu" in safe_str(a.get("tr")).lower() for a in alts)
    expl = safe_str(result.get("word_explanation_tr"))
    assert "maden suyu" in expl.lower() or "sparkling water" in expl.lower()
    assert "/ˈsoʊ.də/" in expl or "sou-da" in expl.lower()
    print("TEST soda lesson OK:", len(examples))


def test_word_breakdown_turkish_meanings():
    """Kelime analizinde her token için Türkçe anlam ve IPA dolu olmalı."""
    result = generate_word_lesson("bardak", "en", fake_translate)
    assert result["ok"], result
    examples = result.get("examples") or []
    assert examples
    sample = None
    for ex in examples:
        wb = ex.get("word_breakdown") or []
        keys = {safe_str(w.get("token")).lower() for w in wb if isinstance(w, dict)}
        if "glass" in keys or "glasses" in keys:
            sample = wb
            break
    if not sample:
        for ex in examples:
            wb = ex.get("word_breakdown") or []
            if len(wb) >= 5:
                sample = wb
                break
    if not sample:
        sample = examples[0].get("word_breakdown") or []
    assert sample, "word_breakdown missing"
    tokens = {safe_str(w.get("token")).lower(): w for w in sample if isinstance(w, dict)}
    for key in ("i", "drink", "a", "glass", "of", "water", "with", "every", "meal"):
        if key not in tokens:
            continue
        entry = tokens[key]
        assert safe_str(entry.get("meaning_tr")).strip(), f"missing TR meaning for {key}"
        assert safe_str(entry.get("pronunciation_tr")).strip(), f"missing pronunciation for {key}"
    glass_entry = tokens.get("glass") or tokens.get("glasses")
    assert glass_entry and safe_str(glass_entry.get("meaning_tr"))
    if "water" in tokens:
        assert safe_str(tokens.get("water", {}).get("meaning_tr"))
    print("TEST word breakdown TR meanings OK:", len(sample), "tokens")


def test_thirteen_grammar_patterns():
    """Kelime dersinde 13 dil bilgisi kalıbı olmalı."""
    result = generate_word_lesson("masa", "en", fake_translate)
    assert result["ok"], result
    examples = result.get("examples") or []
    assert len(examples) >= 13, f"expected 13 examples, got {len(examples)}"
    labels = {safe_str(ex.get("sentence_type_label")) for ex in examples}
    assert any("Temel kullanım" in l for l in labels)
    assert any("Olumsuz" in l for l in labels)
    assert any("Rica" in l for l in labels)
    assert result.get("word_icon") == "🍽️"
    assert result.get("word_icon") != "📖"
    assert result.get("word_icon") != "🪑", "masa should not use chair emoji"
    print("TEST thirteen patterns OK:", len(examples), "examples")


def test_bardak_glass_lesson():
    result = generate_word_lesson("bardak", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🥛"
    assert result.get("target_word") == "glass"
    examples = result.get("examples") or []
    assert len(examples) >= 10
    for ex in examples:
        tg = safe_str(ex.get("target")).lower()
        tr = safe_str(ex.get("tr")).lower()
        assert "bardak" not in tg, f"Turkish leaked in EN: {tg}"
        assert "glass" in tg or "glasses" in tg, f"missing glass: {tg}"
        assert "bardak" in tr or "bardakları" in tr or "bardağı" in tr
    targets = " ".join(safe_str(e.get("target")).lower() for e in examples)
    assert "glass of water" in targets or "empty glass" in targets
    usage = result.get("usage") or {}
    for v in usage.get("common_verbs") or []:
        assert v.get("tr"), f"empty verb: {v}"
    for p in usage.get("common_phrases") or []:
        assert p.get("tr"), f"empty phrase: {p}"
    print("TEST bardak/glass lesson OK:", len(examples))


def test_maden_suyu_natural_lesson():
    """Maden suyu — doğal içecek cümleleri, saçma kalıp yok."""
    result = generate_word_lesson("maden suyu", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") in ("sparkling water", "mineral water")
    assert result.get("word_icon") == "🫧"
    examples = result.get("examples") or []
    assert len(examples) >= 10
    targets = " ".join(safe_str(e.get("target")).lower() for e in examples)
    assert "open the" not in targets
    assert "is broken" not in targets
    assert "fix" not in targets or "find" in targets
    assert "drink" in targets or "have" in targets or "bottle" in targets
    for ex in examples:
        tg = safe_str(ex.get("target")).lower()
        assert "sparkling water" in tg or "mineral water" in tg
        assert "open the" not in tg
    print("TEST maden suyu natural OK:", len(examples))


def test_misir_corn_american():
    """mısır → corn (Amerikan İngilizcesi), sweetcorn değil."""
    for word in ("mısır", "misir"):
        result = generate_word_lesson(word, "en", fake_translate)
        assert result["ok"], result
        assert result.get("target_word") == "corn", f"{word} → {result.get('target_word')}"
        assert result.get("word_icon") == "🌽", f"{word} icon"
        usage = result.get("usage") or {}
        assert usage.get("english_variant_tr")
        assert "corn" in (usage.get("regional_note_tr") or "").lower() or "sweetcorn" in (usage.get("regional_note_tr") or "").lower()
    print("TEST mısır/corn American OK")


def test_word_icons_module():
    from word_icons import lookup_emoji
    assert lookup_emoji("masa", "table") == "🍽️"
    assert lookup_emoji("sandalye", "chair") == "💺"
    assert lookup_emoji("mısır", "corn") == "🌽"
    assert lookup_emoji("mısır", "sweetcorn") == "🌽"
    assert lookup_emoji("maden suyu", "sparkling water") == "🫧"
    assert lookup_emoji("bilinmeyenkelime", "unknownword") == "🏷️"
    print("TEST word_icons OK")


def test_profile_ideas_fallback_examples():
    """Lexicon dışı kelime — profil fikirlerinden örnek üretimi (AI yokken yedek)."""
    from word_teaching_engine import _examples_from_profile_content, sanitize_word_examples
    profile = {
        "common_patterns": [
            {"en": "I carry my bag everywhere.", "tr": "Çantamı her yere taşırım."},
            {"en": "My bag is heavy today.", "tr": "Çantam bugün ağır."},
            {"en": "Did you pack your bag?", "tr": "Çantanı hazırladın mı?"},
            {"en": "She left her bag on the bus.", "tr": "Çantasını otobüste unuttu."},
            {"en": "Can you hold my bag for a minute?", "tr": "Çantamı bir dakika tutar mısın?"},
            {"en": "I don't have a bag with me.", "tr": "Yanımda çanta yok."},
            {"en": "Put it in the bag, please.", "tr": "Lütfen çantaya koy."},
            {"en": "Could you zip up my bag?", "tr": "Çantamın fermuarını çeker misin?"},
            {"en": "You should label your bag at the airport.", "tr": "Havalimanında çantanı etiketlemelisin."},
            {"en": "I need to find a bag for the trip.", "tr": "Gezi için bir çanta bulmam lazım."},
            {"en": "The bag might be in the car.", "tr": "Çanta arabada olabilir."},
            {"en": "If the bag is too heavy, take something out.", "tr": "Çanta çok ağırsa bir şey çıkar."},
            {"en": "A: Where is your bag? B: On the chair.", "tr": "A: Çantan nerede? B: Sandalyede."},
        ],
    }
    raw = _examples_from_profile_content(profile, "çanta", "bag")
    examples = sanitize_word_examples(raw, "çanta", "bag", profile)
    assert len(examples) >= 10, f"Got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "bag" in targets
    assert "bring the bag" not in targets
    print("TEST profile ideas fallback OK:", len(examples))


def test_ai_first_pipeline_without_llm():
    """AI yokken şablon modu (geliştirme) ile 13 örnek döndürür."""
    from word_teaching_engine import AI_LESSON_MAX_ATTEMPTS, try_ai_word_lesson

    assert AI_LESSON_MAX_ATTEMPTS >= 5
    profile = {"common_verbs": ["wear"], "semantic_category": "clothing"}
    _, examples, issues = try_ai_word_lesson("çorap", "socks", "en", profile)
    assert issues, "LLM yokken sorun listesi beklenir"
    old = os.environ.get("WORD_LESSON_ALLOW_TEMPLATES")
    os.environ["WORD_LESSON_ALLOW_TEMPLATES"] = "1"
    try:
        r = generate_word_lesson("çorap", "en", fake_translate)
        assert r["ok"], r
        assert len(r.get("examples") or []) >= 13
    finally:
        if old is None:
            os.environ.pop("WORD_LESSON_ALLOW_TEMPLATES", None)
        else:
            os.environ["WORD_LESSON_ALLOW_TEMPLATES"] = old
    print("TEST AI-first fallback OK:", len(r.get("examples") or []))


def test_ai_only_mode_no_template_fallback():
    """Canlı modda API kapalıyken şablon yerine hata döner."""
    import education_engine
    from unittest.mock import patch
    from word_teaching_engine import ai_only_lesson_enabled

    old_flag = os.environ.pop("WORD_LESSON_ALLOW_TEMPLATES", None)
    old_groq = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = "test-key"
    try:
        with patch.object(education_engine, "_llm_json", return_value=None):
            assert ai_only_lesson_enabled("en")
            r = generate_word_lesson("araba", "en", fake_translate)
            assert not r["ok"], f"Şablon yedek beklenmiyor: {r}"
            assert r.get("ai_retry"), r
        print("TEST ai-only no template fallback OK")
    finally:
        if old_flag is not None:
            os.environ["WORD_LESSON_ALLOW_TEMPLATES"] = old_flag
        if old_groq is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = old_groq


def test_market_rich_teaching():
    """market → doğal cümleler + derin öğretici açıklamalar."""
    result = generate_word_lesson("market", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "market"
    examples = result["examples"]
    assert len(examples) >= 13
    for ex in examples:
        how = safe_str(ex.get("how_it_is_formed_tr"))
        assert len(how) >= 120, f"Explanation too short for: {ex.get('target')}"
        assert "1️⃣" in how and "2️⃣" in how, f"Missing steps for: {ex.get('target')}"
    usage = result.get("usage") or {}
    verbs = {v["en"] for v in (usage.get("common_verbs") or [])}
    assert "go" in verbs or "buy" in verbs
    print("TEST market rich teaching OK:", len(examples))


def test_sessiz_quiet_natural_lesson():
    """sessiz → quiet; sıfat olarak doğal kullanım, nesne şablonu yok."""
    result = generate_word_lesson("sessiz", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "quiet"
    assert result.get("word_profile", {}).get("semantic_category") == "adjective"
    examples = result["examples"]
    assert len(examples) >= 13
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    trs = " ".join(safe_str(ex.get("tr")).lower() for ex in examples)
    banned = (
        "bought a new quiet", "buy a new quiet", "bring my quiet",
        "where is my quiet", "yeni bir sessiz aldım", "sessiz getir",
    )
    for b in banned:
        assert b not in targets and b not in trs, f"Banned pattern: {b}"
    assert any(k in targets for k in ("quiet", "keep quiet", "be quiet", "very quiet"))
    for ex in examples:
        how = safe_str(ex.get("how_it_is_formed_tr"))
        assert len(how) >= 120, f"Short how for: {ex.get('target')}"
    print("TEST sessiz quiet natural OK:", len(examples))


def test_pos_mandatory_lessons():
    """Tüm kelime türleri nesne şablonuna düşmemeli."""
    cases = [
        ("sessiz", ("bought a new quiet", "yeni bir sessiz aldım", "bring my quiet")),
        ("hızlı", ("bought a new quickly", "my quickly", "the quickly is here")),
        ("kedi", ("i am using the cat", "bring the cat", "check the cat regularly")),
        ("elma", ("i am using the apple", "bring the apple", "check the apple regularly")),
        ("çalışmak", ("bought a new work", "my work is on the table", "a work is here")),
        ("ben", ("bought a new i", "my i is on", "bring my i")),
        ("ile", ("bought a with", "my with is on", "i am using the with")),
        ("ve", ("bought a and", "my and is on", "bring the and")),
        ("merhaba", ("bought a hello", "my hello is on", "i am using the hello")),
    ]
    for word_tr, banned in cases:
        r = generate_word_lesson(word_tr, "en", fake_translate)
        assert r["ok"], f"{word_tr}: {r}"
        targets = " ".join(safe_str(ex.get("target")).lower() for ex in (r.get("examples") or []))
        trs = " ".join(safe_str(ex.get("tr")).lower() for ex in (r.get("examples") or []))
        for b in banned:
            assert b not in targets and b not in trs, f"{word_tr} banned '{b}' found"
    print("TEST pos mandatory lessons OK")


def test_upgrade_thin_teaching_explanations():
    """Kısa AI açıklamaları zengin kalıp açıklamalarıyla güçlendirilir."""
    from word_teaching_engine import upgrade_word_lesson_teaching, teaching_explanation_is_rich

    thin = [{
        "tr": "Dün markete gittim.",
        "target": "I went to the market yesterday.",
        "sentence_type": "past",
        "how_it_is_formed_tr": "1️⃣ Geçmiş zaman\nwent → gittim",
        "structure_tr": "I + went + to the market",
    }]
    profile = {"semantic_category": "place"}
    out = upgrade_word_lesson_teaching(thin, "market", "market", profile)
    assert teaching_explanation_is_rich(out[0].get("how_it_is_formed_tr")), out[0].get("how_it_is_formed_tr")
    print("TEST upgrade thin teaching OK")


def test_has_curated_lexicon():
    from word_lexicon import has_curated_lexicon
    assert has_curated_lexicon("kitap", "book")
    assert has_curated_lexicon("fatura", "invoice")
    assert not has_curated_lexicon("çanta", "bag")
    assert not has_curated_lexicon("kedi", "cat")
    print("TEST has_curated_lexicon OK")


def test_sakiz_natural_lesson():
    """sakız → gum; mekanik şablon yok; 13 doğal cümle."""
    result = generate_word_lesson("sakız", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "gum", result.get("target_word")
    assert result.get("word_icon") == "🍬"
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ examples, got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "the gum is here" not in targets
    assert "bring the gum" not in targets
    assert "using the gum" not in targets
    assert any(k in targets for k in ("chew", "gum", "bubble", "piece of gum"))
    usage = result.get("usage") or {}
    verbs = {v["en"] for v in (usage.get("common_verbs") or [])}
    assert "chew" in verbs or "eat" in verbs
    for ex in examples:
        assert safe_str(ex.get("tr")).strip(), f"Missing TR: {ex.get('target')}"
    print("TEST sakız natural lesson OK:", len(examples))


def test_fatura_invoice_lesson():
    """fatura → invoice; at emoji sızıntısı yok; doğal fatura cümleleri."""
    result = generate_word_lesson("fatura", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "invoice", result.get("target_word")
    assert result.get("word_icon") == "🧾", result.get("word_icon")
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ examples, got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "pay" in targets or "send" in targets or "due" in targets
    banned = ("the invoice is here", "i am using the invoice", "bring the invoice")
    for b in banned:
        assert b not in targets, f"Banned: {b}"
    usage = result.get("usage") or {}
    verb_map = {v["en"]: v["tr"] for v in (usage.get("common_verbs") or [])}
    assert verb_map.get("pay") == "ödemek"
    assert verb_map.get("send") == "göndermek"
    phrases_blob = " ".join(safe_str(p.get("en")).lower() for p in (usage.get("common_phrases") or []))
    assert "pay the invoice" in phrases_blob
    assert "window" not in phrases_blob and "door" not in phrases_blob
    expl = result.get("word_explanation_tr") or ""
    assert "drink" not in expl.lower() or "pay" in expl.lower()
    print("TEST fatura/invoice lesson OK:", len(examples), "examples")


def test_fatura_not_horse_icon():
    from word_icons import lookup_emoji
    assert lookup_emoji("fatura", "invoice") == "🧾"
    assert lookup_emoji("fatura", "fatura") == "🧾"
    assert lookup_emoji("at", "horse") == "🐴"
    print("TEST fatura icon not horse OK")


def test_kitap_usage_verbs_and_pronunciation():
    """kitap — fiil Türkçeleri doğru; okunuş/IPA ve kalıp çevirileri dolu."""
    result = generate_word_lesson("kitap", "en", fake_translate)
    assert result["ok"], result
    usage = result.get("usage") or {}
    verb_map = {v["en"]: v["tr"] for v in (usage.get("common_verbs") or [])}
    assert verb_map.get("borrow") == "ödünç almak", verb_map
    assert verb_map.get("finish") == "bitirmek", verb_map
    assert verb_map.get("recommend") == "tavsiye etmek", verb_map
    assert verb_map.get("lend") == "ödünç vermek", verb_map
    assert verb_map.get("write") == "yazmak", verb_map
    for v in usage.get("common_verbs") or []:
        assert v.get("pronunciation_tr"), f"Missing verb pron: {v.get('en')}"
    articles = usage.get("article_notes_items") or []
    assert len(articles) >= 3
    for a in articles:
        assert a.get("tr") and a.get("pronunciation_tr"), a
    patterns = usage.get("pattern_examples") or []
    assert len(patterns) >= 3
    for p in patterns:
        assert p.get("tr") and p.get("pronunciation_tr"), p
    print("TEST kitap usage verbs/pron OK")


def test_kitap_no_cross_word_leak():
    """kitap dersinde pencere/kapı ifadeleri YASAK."""
    result = generate_word_lesson("kitap", "en", fake_translate)
    assert result["ok"], result
    usage = result.get("usage") or {}
    phrases = usage.get("common_phrases") or []
    assert len(phrases) >= 3, phrases
    blob = " ".join(
        safe_str(p.get("en")).lower() + " " + safe_str(p.get("tr")).lower()
        for p in phrases
    )
    assert "window" not in blob, f"Window leak in kitap phrases: {phrases}"
    assert "pencere" not in blob, f"Pencere leak in kitap phrases: {phrases}"
    assert "door" not in blob, f"Door leak in kitap phrases: {phrases}"
    assert "kapı" not in blob, f"Kapı leak in kitap phrases: {phrases}"
    assert "open/close" not in (usage.get("usage_notes_tr") or "").lower()
    assert any("read" in safe_str(p.get("en")).lower() for p in phrases)
    print("TEST kitap no cross-word leak OK:", len(phrases), "phrases")


def test_door_natural_lesson():
    """kapı/door — mekanik şablon yok; gerçek kullanım kalıpları."""
    result = generate_word_lesson("kapı", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "door"
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ natural examples, got {len(examples)}"

    banned = (
        "bring the door", "using the door", "this is my door",
        "i am using the door", "check the door regularly",
    )
    for ex in examples:
        t = safe_str(ex.get("target")).lower()
        for b in banned:
            assert b not in t, f"Banned mechanical template: {t}"
        pron = safe_str(ex.get("pronunciation_tr")).lower()
        assert "window" not in pron, f"Pronunciation leak: {pron}"

    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert any(k in targets for k in ("knock", "locked", "close the door", "at the door"))
    print("TEST door natural lesson OK:", len(examples), "examples")


def test_masa_icon():
    result = generate_word_lesson("masa", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🍽️"
    print("TEST masa icon OK")


def test_door_icon():
    result = generate_word_lesson("kapı", "en", fake_translate)
    assert result["ok"], result
    assert result.get("word_icon") == "🚪"
    print("TEST door icon OK")


def test_placeholder_turkish_rejected():
    """Yalnızca kelime olan Türkçe (❌ 'Eğlence') örnekler elenmeli."""
    from word_teaching_engine import (
        _is_placeholder_turkish,
        _validate_word_example,
        sanitize_word_examples,
    )

    assert _is_placeholder_turkish("Eğlence", "eğlence")
    assert _is_placeholder_turkish("", "eğlence")
    assert not _is_placeholder_turkish("Bu akşam için iyi bir eğlence bulmalıyız.", "eğlence")

    bad = {
        "tr": "Eğlence",
        "target": "What kind of entertainment do you prefer?",
        "sentence_type": "question",
        "structure_tr": "What kind of entertainment",
        "how_it_is_formed_tr": "Bu cümle eğlence kelimesinin doğal kullanımını gösterir. Soru kalıbı.",
        "structure_label_tr": "Dil Bilgisi Formülü: What kind of entertainment",
    }
    assert not _validate_word_example(dict(bad), "eğlence", "entertainment")

    good = {
        "tr": "Ne tür eğlence tercih edersin?",
        "target": "What kind of entertainment do you prefer?",
        "sentence_type": "question",
        "structure_tr": "What kind of entertainment",
        "how_it_is_formed_tr": "Bu cümle eğlence kelimesinin doğal kullanımını gösterir. Soru kalıbı.",
        "structure_label_tr": "Dil Bilgisi Formülü: What kind of entertainment",
    }
    assert _validate_word_example(dict(good), "eğlence", "entertainment")

    mixed = [
        good,
        bad,
        {
            "tr": "Parti için eğlence ayarlamam gerekiyor.",
            "target": "I need to arrange entertainment for the party.",
            "sentence_type": "obligation",
            "structure_tr": "arrange entertainment",
            "how_it_is_formed_tr": "Bu cümle eğlence kelimesinin doğal kullanımını gösterir. Gereklilik kalıbı.",
            "structure_label_tr": "Dil Bilgisi Formülü: arrange entertainment",
        },
    ]
    cleaned = sanitize_word_examples(mixed, "eğlence", "entertainment")
    assert len(cleaned) == 2
    for ex in cleaned:
        assert not _is_placeholder_turkish(ex.get("tr"), "eğlence")
    print("TEST placeholder turkish rejected OK")


def test_eglence_natural_lesson():
    """eğlence → entertainment; tüm örneklerde tam Türkçe cümle olmalı."""
    from word_teaching_engine import _is_placeholder_turkish

    result = generate_word_lesson("eğlence", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "entertainment", result.get("target_word")
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ examples, got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "entertainment" in targets
    banned = ("the entertainment is here", "bring the entertainment", "i am using the entertainment")
    for b in banned:
        assert b not in targets, f"Banned: {b}"
    for ex in examples:
        tr = safe_str(ex.get("tr")).strip()
        assert tr, f"Missing TR: {ex.get('target')}"
        assert not _is_placeholder_turkish(tr, "eğlence"), f"Placeholder TR: {tr!r} for {ex.get('target')}"
        assert len(tr.split()) >= 3, f"TR too short: {tr!r}"
    print("TEST eğlence natural lesson OK:", len(examples))


def test_sigara_not_food_patterns():
    """sigara → cigarette; yemek kalıbı YASAK; smoke/light/quit fiilleri."""
    from word_teaching_engine import detect_category, _is_wrong_verb_collocation

    assert detect_category("sigara", "cigarette") == "tobacco"
    assert _is_wrong_verb_collocation("i am eating cigarette now", "sigara", "cigarette")
    result = generate_word_lesson("sigara", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "cigarette"
    assert result.get("word_icon") == "🚬"
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ examples, got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "eat" not in targets and "eating" not in targets
    assert "smoke" in targets or "smoking" in targets or "quit" in targets
    usage = result.get("usage") or {}
    verb_map = {v["en"]: v["tr"] for v in (usage.get("common_verbs") or [])}
    assert "smoke" in verb_map
    assert "kullanmak" not in verb_map.values()
    phrases = usage.get("common_phrases") or []
    assert len(phrases) >= 3, phrases
    for p in phrases:
        assert p.get("tr"), f"missing tr: {p.get('en')}"
    articles = usage.get("article_notes_items") or []
    assert articles and all(a.get("tr") for a in articles)
    print("TEST sigara tobacco lesson OK:", len(examples))


def test_gozluk_eyewear_lesson():
    """gözlük → glasses; wear/put on; çoğul isim; mekanik şablon yok."""
    from word_teaching_engine import detect_category

    assert detect_category("gözlük", "glasses") == "eyewear"
    assert detect_category("sigara", "cigarette") != "food"
    result = generate_word_lesson("gözlük", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "glasses"
    assert result.get("word_icon") == "👓"
    examples = result["examples"]
    assert len(examples) >= 10, f"Expected 10+ examples, got {len(examples)}"
    targets = " ".join(safe_str(ex.get("target")).lower() for ex in examples)
    assert "glasses is" not in targets
    assert "a glasses" not in targets
    assert "wear" in targets or "put on" in targets
    banned = ("i am using the glasses", "bring the glasses", "the glasses is here")
    for b in banned:
        assert b not in targets, f"Banned: {b}"
    usage = result.get("usage") or {}
    verbs = {v["en"] for v in (usage.get("common_verbs") or [])}
    assert "wear" in verbs
    assert "use" not in verbs or len(verbs) > 1
    phrases = usage.get("common_phrases") or []
    assert len(phrases) >= 3
    for p in phrases:
        assert p.get("tr") and p.get("pronunciation_tr")
    articles = usage.get("article_notes_items") or []
    assert articles and all(a.get("tr") for a in articles)
    for ex in examples:
        tr = safe_str(ex.get("tr")).strip()
        assert tr and len(tr.replace(".", "").split()) >= 2, f"Short TR: {tr!r}"
    print("TEST gözlük eyewear lesson OK:", len(examples))


def test_universal_guarantee_many_words():
    """Her kelime: >=13 örnek, yasak kalıp yok, artikel TR dolu."""
    from word_teaching_engine import _is_wrong_verb_collocation, _norm

    words = [
        "çorap", "şemsiye", "bıçak", "yastık", "kalem", "parfüm", "bisiklet",
        "çanta", "anahtar", "radyo", "gözlük", "sigara", "bal", "kitap",
        "kapı", "masa", "sakız", "fatura", "eğlence", "telefon",
    ]
    banned = ("is here", "bring the", "using the", " a glasses", "glasses is")
    word_banned: dict[str, tuple[str, ...]] = {
        "sigara": ("eat cigarette", "eating cigarette"),
    }
    for w in words:
        r = generate_word_lesson(w, "en", fake_translate)
        assert r["ok"], f"{w} failed: {r}"
        ex = r.get("examples") or []
        assert len(ex) >= 13, f"{w}: only {len(ex)} examples"
        targets = " ".join(safe_str(e.get("target")).lower() for e in ex)
        for b in banned + word_banned.get(w, ()):
            assert b not in targets, f"{w} banned {b!r} in {targets[:80]}"
        usage = r.get("usage") or {}
        verbs = usage.get("common_verbs") or []
        assert len(verbs) >= 3, f"{w}: too few verbs {verbs}"
        assert all(v.get("tr") for v in verbs), f"{w}: verb missing tr"
        phrases = usage.get("common_phrases") or []
        if phrases:
            assert all(p.get("tr") for p in phrases), f"{w}: phrase missing tr"
        articles = usage.get("article_notes_items") or []
        if articles:
            assert all(a.get("tr") for a in articles), f"{w}: article missing tr"
        for e in ex:
            tr = safe_str(e.get("tr")).strip()
            assert tr and not tr.lower() == w.lower(), f"{w}: placeholder tr {tr!r}"
            assert not _is_wrong_verb_collocation(
                _norm(safe_str(e.get("target"))), w, r.get("target_word", ""),
            ), f"{w}: wrong verb in {e.get('target')}"
        assert r.get("word_icon") and r.get("word_icon") != "📦", f"{w}: bad icon {r.get('word_icon')}"
    print("TEST universal guarantee OK:", len(words), "words")


def test_araba_car_natural():
    """araba → car: doğal Türkçe, iyelik, mekanik şablon yok."""
    from word_teaching_engine import _is_mechanical_turkish

    r = generate_word_lesson("araba", "en", fake_translate)
    assert r["ok"], r
    targets = " ".join(safe_str(e.get("target")).lower() for e in (r.get("examples") or []))
    assert "often use my car at home" not in targets
    assert "drive to work" in targets or "park" in targets
    articles = (r.get("usage") or {}).get("article_notes_items") or []
    assert articles, "article notes missing"
    assert any("arabam" in safe_str(a.get("tr")).lower() for a in articles)
    for e in r.get("examples") or []:
        tr = safe_str(e.get("tr"))
        assert not _is_mechanical_turkish(tr, "araba"), f"mechanical TR: {tr!r}"
        assert len(tr.split()) >= 2
    print("TEST araba car natural OK")


def test_cuzdan_wallet_natural():
    """cüzdan → wallet: mekanik şablon yok, doğal fiiller."""
    from word_teaching_engine import _is_generic_mechanical_template

    r = generate_word_lesson("cüzdan", "en", fake_translate)
    assert r["ok"], r
    targets = " ".join(safe_str(e.get("target")).lower() for e in (r.get("examples") or []))
    assert "often use my wallet at home" not in targets
    assert "put the wallet here" not in targets
    assert "you should use my wallet carefully" not in targets
    assert "lost my wallet" in targets or "lose your wallet" in targets
    verbs = {v.get("en", "").lower() for v in (r.get("usage") or {}).get("common_verbs") or []}
    assert verbs & {"lose", "check", "carry", "find"}, f"bad verbs: {verbs}"
    articles = (r.get("usage") or {}).get("article_notes_items") or []
    assert any("cüzdanım" in safe_str(a.get("tr")).lower() for a in articles)
    for e in r.get("examples") or []:
        assert not _is_generic_mechanical_template(safe_str(e.get("target")))
    print("TEST cüzdan wallet natural OK")


def test_semsiye_umbrella_natural():
    """şemsiye → umbrella: aç/kapat, yağmur — evde kullanırım yok."""
    from word_teaching_engine import _is_generic_mechanical_template

    r = generate_word_lesson("şemsiye", "en", fake_translate)
    assert r["ok"], r
    targets = " ".join(safe_str(e.get("target")).lower() for e in (r.get("examples") or []))
    assert "often use my umbrella at home" not in targets
    assert "put the umbrella here" not in targets
    assert "open" in targets or "close" in targets or "rain" in targets
    verbs = {v.get("en", "").lower() for v in (r.get("usage") or {}).get("common_verbs") or []}
    assert verbs & {"open", "close", "carry", "bring", "forget"}, f"bad verbs: {verbs}"
    articles = (r.get("usage") or {}).get("article_notes_items") or []
    assert any("şemsiyem" in safe_str(a.get("tr")).lower() for a in articles)
    for e in r.get("examples") or []:
        assert not _is_generic_mechanical_template(safe_str(e.get("target")))
    print("TEST şemsiye umbrella natural OK")


def test_bal_honey_usage_and_icon():
    """bal → honey: doğru ikon, fiil çevirileri ve ifade TR/IPA."""
    from word_icons import lookup_emoji
    from word_teaching_engine import build_usage_from_profile, _phrase_meaning_tr

    assert lookup_emoji("bal", "honey", "food") == "🍯"
    assert lookup_emoji("bal", "honey") == "🍯"

    profile = {
        "part_of_speech": "noun",
        "countability": "uncountable",
        "semantic_category": "food",
        "meaning_tr": "bal",
        "common_verbs": ["spread", "drizzle", "collect", "taste", "dilute"],
        "common_collocations": ["honeydew melon", "honey trap", "honey moon", "locust honey"],
    }
    usage = build_usage_from_profile(profile, "en", "honey", "bal")
    verb_map = {v["en"]: v["tr"] for v in (usage.get("common_verbs") or [])}
    assert verb_map.get("spread") == "sürmek / yaymak"
    assert verb_map.get("drizzle") == "gezdirmek / damlatmak"
    assert verb_map.get("collect") == "toplamak"
    assert verb_map.get("taste") == "tatmak / tadına bakmak"
    assert verb_map.get("dilute") == "sulandırmak"
    assert "kullanmak" not in verb_map.values()

    phrases = usage.get("common_phrases") or []
    assert len(phrases) >= 4, phrases
    phrase_map = {p["en"]: p for p in phrases}
    assert phrase_map["honeydew melon"]["tr"] == "kavun (bal kavunu)"
    assert phrase_map["honey trap"]["tr"] == "bal tuzağı"
    assert phrase_map["honey moon"]["tr"] == "balayı"
    assert phrase_map["locust honey"]["tr"] == "çekirge balı"
    for p in phrases:
        assert p.get("tr"), p
        assert p.get("pronunciation_tr"), f"missing pron: {p['en']}"
        assert p.get("ipa"), f"missing ipa: {p['en']}"

    for v in usage.get("common_verbs") or []:
        assert v.get("ipa"), f"missing verb ipa: {v['en']}"

    result = generate_word_lesson("bal", "en", fake_translate)
    assert result["ok"], result
    assert result.get("target_word") == "honey"
    assert result.get("word_icon") == "🍯"
    print("TEST bal/honey usage and icon OK")


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
    test_shoe_no_socks_leak()
    test_soda_lesson()
    test_word_breakdown_turkish_meanings()
    test_maden_suyu_natural_lesson()
    test_misir_corn_american()
    test_word_icons_module()
    test_bardak_glass_lesson()
    test_word_sequence_isolation()
    test_door_natural_lesson()
    test_kitap_usage_verbs_and_pronunciation()
    test_kitap_no_cross_word_leak()
    test_fatura_invoice_lesson()
    test_fatura_not_horse_icon()
    test_sakiz_natural_lesson()
    test_placeholder_turkish_rejected()
    test_eglence_natural_lesson()
    test_bal_honey_usage_and_icon()
    test_gozluk_eyewear_lesson()
    test_sigara_not_food_patterns()
    test_universal_guarantee_many_words()
    test_cuzdan_wallet_natural()
    test_araba_car_natural()
    test_semsiye_umbrella_natural()
    test_ai_first_pipeline_without_llm()
    test_ai_only_mode_no_template_fallback()
    test_market_rich_teaching()
    test_sessiz_quiet_natural_lesson()
    test_pos_mandatory_lessons()
    test_upgrade_thin_teaching_explanations()
    test_has_curated_lexicon()
    test_profile_ideas_fallback_examples()
    test_masa_icon()
    test_door_icon()
    test_grade_word_correct()
    test_grade_honest_pronunciation()
    test_similarity_and_srs()
    print("\nAll builder tests passed.")
