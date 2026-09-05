#!/usr/bin/env python3
"""Karşı dil → Türkçe sesli çeviri kalitesi (en/ka)."""
from server import (
    _needs_quality_translate,
    _stt_early_lang,
    smart_translate_text,
)


def test_any_to_tr_quality_gate():
    assert _needs_quality_translate("How are you?", "en", "tr") is True
    assert _needs_quality_translate("გამარჯობა", "ka", "tr") is True
    assert _needs_quality_translate("Hello", "en", "tr") is True
    assert _needs_quality_translate("Merhaba", "tr", "en") is False
    print("TEST →tr quality gate OK")


def test_stt_early_en_tr():
    assert _stt_early_lang("How are you today?", "tr", "en") == "en"
    assert _stt_early_lang("hello how are you", "tr", "en") == "en"
    assert _stt_early_lang("Nasılsın bugün?", "tr", "en") == "tr"
    assert _stt_early_lang("გამარჯობა", "tr", "ka") == "ka"
    print("TEST stt early en/tr OK")


def test_en_tr_translate_smoke():
    r = smart_translate_text("What is your name?", "en", "tr")
    assert r and "ad" in r.lower()
    r2 = smart_translate_text("I want coffee.", "en", "tr")
    assert r2 and "kahve" in r2.lower()
    print("TEST en→tr smoke OK:", r, "|", r2)


if __name__ == "__main__":
    test_any_to_tr_quality_gate()
    test_stt_early_en_tr()
    test_en_tr_translate_smoke()
    print("\nAll →tr quality tests passed.")
