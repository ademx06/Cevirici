#!/usr/bin/env python3
"""Canlı çeviri speech intelligence — dil güveni + kanal tercihi + stabilite."""
from __future__ import annotations

from server import (
    _LANG_STABILITY,
    is_likely_english,
    is_likely_turkish,
    language_confidence,
    pick_speech_hypothesis,
)


def setup_function():
    _LANG_STABILITY.clear()


def test_en_channel_beats_turkish_garbage():
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("hava iyi", "tr", 40.0, "lang_tr"),
            ("Hello, how are you today?", "en", 60.0, "lang_en"),
            ("Hello how are you today", "en", 50.0, "auto"),
        ],
        "tr",
        "en",
        None,
    )
    assert lang == "en"
    assert "hello" in text.lower()
    assert conf >= 0.7
    print("TEST EN channel beats TR garbage OK")


def test_ka_mkhedruli_wins():
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("merhaba nasilsin", "tr", 35.0, "lang_tr"),
            ("გამარჯობა როგორ ხარ", "ka", 70.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "ka"
    assert "გამარჯობა" in text
    assert conf >= 0.9
    print("TEST KA Mkhedruli wins OK")


def test_tr_ortho_wins():
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("Merhaba, bugün nasılsın?", "tr", 70.0, "lang_tr"),
            ("Merhaba bugun nasilsin", "en", 25.0, "lang_en"),
        ],
        "tr",
        "en",
        None,
    )
    assert lang == "tr"
    assert "nasılsın" in text.lower() or "nasılsın" in text
    assert conf >= 0.7
    print("TEST TR ortho wins OK")


def test_ascii_turkish_not_english():
    assert not is_likely_english("hava iyi", "tr", "en")
    assert is_likely_turkish("hava iyi")
    assert language_confidence("hava iyi", "en", "tr", "en") < 0.5
    print("TEST ASCII Turkish not English OK")


def test_weak_segment_does_not_flip_language():
    setup_function()
    pick_speech_hypothesis(
        [("Nasılsın bugün?", "tr", 80.0, "lang_tr")],
        "tr",
        "en",
        None,
    )
    _, lang, conf = pick_speech_hypothesis(
        [("ok", "en", 15.0, "auto")],
        "tr",
        "en",
        "tr",
    )
    assert lang == "tr"
    assert conf < 0.8
    print("TEST weak segment stability OK")


def test_strong_english_can_switch():
    setup_function()
    pick_speech_hypothesis(
        [("Merhaba nasılsın?", "tr", 80.0, "lang_tr")],
        "tr",
        "en",
        None,
    )
    # High-confidence English should be allowed to become source
    _, lang1, conf1 = pick_speech_hypothesis(
        [("What is your name?", "en", 85.0, "lang_en")],
        "tr",
        "en",
        "tr",
    )
    assert lang1 == "en"
    assert conf1 >= 0.7
    print("TEST strong English switch OK")


def test_ka_channel_beats_turkish_hallucination():
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("Sanırım her şeyi bıraksak bu yiyecek gibi.", "tr", 55.0, "lang_tr"),
            ("გამარჯობა, როგორ ხარ?", "ka", 50.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "ka"
    assert "გამარჯობა" in text
    print("TEST KA channel beats Turkish hallucination OK")


def test_ka_latin_channel_still_preferred_over_tr_garbage():
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("Sanırım her şeyi bıraksak bu yiyecek gibi.", "tr", 55.0, "lang_tr"),
            ("gamarjoba rogor khar", "ka", 40.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "ka"
    assert "gamarjoba" in text.lower()
    print("TEST KA latin channel preferred over TR garbage OK")


def test_turkish_not_misclassified_as_georgian_greeting():
    """Kök bug: Türkçe selam → Gürcüce kutusuna gitmesin."""
    setup_function()
    text, lang, conf = pick_speech_hypothesis(
        [
            ("Merhaba, bugün nasılsın?", "tr", 70.0, "lang_tr"),
            ("გამარჯობა, როგორ ხარ?", "ka", 50.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "tr", f"Türkçe konuşma KA sanıldı: {lang} {text!r}"
    assert "nasılsın" in text.lower() or "Nasılsın" in text
    assert conf >= 0.7
    print("TEST Turkish not misclassified as Georgian OK")


def test_turkish_beats_long_georgian_weather_hallucination():
    setup_function()
    text, lang, _ = pick_speech_hypothesis(
        [
            ("Merhaba, bugün çok mutluyum.", "tr", 72.0, "lang_tr"),
            ("დღეს ამინდი ძალიან კარგია", "ka", 55.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "tr"
    assert "mutluyum" in text.lower()
    print("TEST Turkish beats long KA weather halluc OK")


def test_real_georgian_with_auto_mkhedruli_beats_turkish_greeting():
    setup_function()
    text, lang, _ = pick_speech_hypothesis(
        [
            ("გამარჯობა, როგორ ხარ?", "ka", 80.0, "auto"),
            ("Merhaba, bugün nasılsın?", "tr", 55.0, "lang_tr"),
            ("გამარჯობა, როგორ ხარ?", "ka", 50.0, "lang_ka"),
        ],
        "tr",
        "ka",
        None,
    )
    assert lang == "ka"
    assert "გამარჯობა" in text
    print("TEST real Georgian auto Mkhedruli OK")


def test_reciprocal_tr_en_tr_ka_switches():
    """Önceki dil yeni konuşmaya zorla uygulanmamalı."""
    setup_function()
    sequence = [
        ([("Merhaba, bugün nasılsın?", "tr", 80.0, "lang_tr")], "tr", "en", "tr"),
        ([("Hello, how are you today?", "en", 85.0, "lang_en"), ("hava iyi", "tr", 30.0, "lang_tr")], "tr", "en", "en"),
        ([("İyiyim, teşekkür ederim.", "tr", 80.0, "lang_tr")], "tr", "en", "tr"),
    ]
    last = None
    for cands, my, other, expect in sequence:
        setup_function()  # segment bağımsız kanıt; last yalnızca yardımcı
        _, lang, _ = pick_speech_hypothesis(cands, my, other, last)
        assert lang == expect, f"expected {expect} got {lang}"
        last = lang
    # TR↔KA
    setup_function()
    _, lang, _ = pick_speech_hypothesis(
        [("Merhaba, bugün nasılsın?", "tr", 75.0, "lang_tr"), ("გამარჯობა", "ka", 35.0, "lang_ka")],
        "tr",
        "ka",
        None,
    )
    assert lang == "tr"
    _, lang, _ = pick_speech_hypothesis(
        [
            ("Sanırım her şeyi bıraksak bu yiyecek gibi.", "tr", 40.0, "lang_tr"),
            ("მინდა სასტუმროში წავიდე ხვალ", "ka", 70.0, "lang_ka"),
        ],
        "tr",
        "ka",
        "tr",
    )
    assert lang == "ka"
    print("TEST reciprocal language switches OK")


def test_ru_and_es_source_detection():
    setup_function()
    _, lang, _ = pick_speech_hypothesis(
        [
            ("hava iyi", "tr", 30.0, "lang_tr"),
            ("Здравствуйте, как дела?", "ru", 60.0, "lang_ru"),
        ],
        "tr",
        "ru",
        None,
    )
    assert lang == "ru"
    setup_function()
    _, lang, _ = pick_speech_hypothesis(
        [
            ("hava iyi", "tr", 30.0, "lang_tr"),
            ("Hola, cómo estás hoy?", "es", 55.0, "lang_es"),
        ],
        "tr",
        "es",
        None,
    )
    assert lang == "es"
    print("TEST RU and ES source detection OK")


if __name__ == "__main__":
    test_en_channel_beats_turkish_garbage()
    test_ka_mkhedruli_wins()
    test_tr_ortho_wins()
    test_ascii_turkish_not_english()
    test_weak_segment_does_not_flip_language()
    test_strong_english_can_switch()
    test_ka_channel_beats_turkish_hallucination()
    test_ka_latin_channel_still_preferred_over_tr_garbage()
    test_turkish_not_misclassified_as_georgian_greeting()
    test_turkish_beats_long_georgian_weather_hallucination()
    test_real_georgian_with_auto_mkhedruli_beats_turkish_greeting()
    test_reciprocal_tr_en_tr_ka_switches()
    test_ru_and_es_source_detection()
    print("\nAll speech intelligence tests passed.")
