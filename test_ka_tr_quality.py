#!/usr/bin/env python3
"""Gürcüce → Türkçe sesli çeviri kalitesi (STT seçimi + kalite yolu)."""
from __future__ import annotations

from server import (
    _needs_quality_translate,
    _stt_early_lang,
    _has_mkhedruli,
    _polish_turkish_from_georgian,
    looks_like_lang,
    detect_speech_lang,
)


def test_ka_tr_always_quality():
    assert _needs_quality_translate("გამარჯობა", "ka", "tr") is True
    assert _needs_quality_translate("როგორ ხარ?", "ka", "tr") is True
    # TR→KA kısa hâlâ eski davranış (kısa = False olabilir)
    assert _needs_quality_translate("Merhaba", "tr", "en") is False
    print("TEST ka→tr quality gate OK")


def test_mkhedruli_helpers():
    assert _has_mkhedruli("გამარჯობა")
    assert not _has_mkhedruli("Merhaba")
    assert looks_like_lang("გამარჯობა როგორ ხარ", "ka")
    print("TEST mkhedruli helpers OK")


def test_stt_early_no_latin_for_tr_ka():
    # Latin auto hallucination: erken çıkma
    assert _stt_early_lang("hello how are you", "tr", "ka") is None
    assert _stt_early_lang("bugun hava guzel", "tr", "ka") is None
    # True Turkish orthography may early-exit
    assert _stt_early_lang("Nasılsın bugün?", "tr", "ka") == "tr"
    # Mkhedruli → ka
    assert _stt_early_lang("გამარჯობა", "tr", "ka") == "ka"
    assert _stt_early_lang("გამარჯობა როგორ ხარ", "tr", "ka") == "ka"
    print("TEST stt early tr-ka OK")


def test_detect_prefers_ka_script():
    assert detect_speech_lang("გამარჯობა", "tr", "ka", "auto", None) == "ka"
    print("TEST detect speech ka OK")


def test_polish_greeting():
    out = _polish_turkish_from_georgian("გამარჯობა, როგორ ხარ?", "nasılsın")
    assert "Merhaba" in out and "nasılsın" in out.lower()
    print("TEST polish greeting OK")


if __name__ == "__main__":
    test_ka_tr_always_quality()
    test_mkhedruli_helpers()
    test_stt_early_no_latin_for_tr_ka()
    test_detect_prefers_ka_script()
    test_polish_greeting()
    print("\nAll ka→tr quality tests passed.")
