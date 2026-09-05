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


if __name__ == "__main__":

    test_en_channel_beats_turkish_garbage()
    test_ka_mkhedruli_wins()
    test_tr_ortho_wins()
    test_ascii_turkish_not_english()
    test_weak_segment_does_not_flip_language()
    test_strong_english_can_switch()
    test_ka_channel_beats_turkish_hallucination()
    test_ka_latin_channel_still_preferred_over_tr_garbage()
    print("\nAll speech intelligence tests passed.")
