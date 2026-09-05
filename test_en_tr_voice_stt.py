#!/usr/bin/env python3
"""EN/KA → TR voice STT language detection must not treat Turkish ASCII as English."""
from server import (
    is_likely_english, is_likely_turkish, looks_like_lang,
    _english_signal_strength, _needs_quality_translate, smart_translate_text,
)

def test_ascii_turkish_not_english():
    for s in ["hava iyi", "bugun hava guzel", "ne var", "tamam tamam"]:
        assert not is_likely_english(s, "tr", "en"), s
        assert is_likely_turkish(s), s
    print("TEST ascii Turkish not English OK")

def test_real_english():
    for s in ["How are you?", "What is your name?", "I want coffee", "hello how are you"]:
        assert is_likely_english(s, "tr", "en"), s
        assert not is_likely_turkish(s), s
        assert _english_signal_strength(s) >= 2, s
    print("TEST real English OK")

def test_en_tr_translate():
    assert _needs_quality_translate("How are you?", "en", "tr")
    r = smart_translate_text("How are you?", "en", "tr")
    assert r and "nasıl" in r.lower()
    # Garbage must NOT be translated as English→Turkish into nonsense direction logic
    assert not is_likely_english("hava iyi", "tr", "en")
    print("TEST en→tr translate OK:", r)

if __name__ == "__main__":
    test_ascii_turkish_not_english()
    test_real_english()
    test_en_tr_translate()
    print("\nAll voice STT language tests passed.")
