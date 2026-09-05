#!/usr/bin/env python3
"""Bas Konuş forced SOURCE language — buton dili = STT dili (auto detect yok)."""
from __future__ import annotations

from unittest.mock import patch

import server
from server import process_speech_segment, STT_LANG


def test_forced_source_uses_button_language_not_detection():
    """TR butonu → STT tr; çift kanal / auto detect çağrılmaz."""
    fake_audio = b"RIFF" + b"\x00" * 200

    def fake_forced(data, source_lang, timings=None):
        assert source_lang == "tr"
        if timings is not None:
            timings["stt_language"] = source_lang
            timings["language_confidence"] = 1.0
        return "Merhaba, bugün nasılsın?", "tr"

    with patch.object(server, "transcribe_forced", side_effect=fake_forced) as m_forced, \
         patch.object(server, "transcribe_dual") as m_dual, \
         patch.object(server, "translate_text", return_value="Hello, how are you today?") as m_tr, \
         patch.object(server, "translate_pair_safe") as m_safe:
        result = process_speech_segment(
            fake_audio, "tr", "en", None, {}, forced_source="tr",
        )
        assert m_forced.called
        assert not m_dual.called
        assert not m_safe.called
        assert m_tr.called
        assert m_tr.call_args[0][1:] == ("tr", "en")
        assert result["from"] == "tr"
        assert result["to"] == "en"
        assert result["original"] == "Merhaba, bugün nasılsın?"
        assert result["translated"] == "Hello, how are you today?"
        assert result["forced_source"] is True
        assert result["stt_language"] == "tr"
    print("TEST forced TR button OK")


def test_forced_ka_source_not_turkish():
    fake_audio = b"RIFF" + b"\x00" * 200

    def fake_forced(data, source_lang, timings=None):
        assert source_lang == "ka"
        return "გამარჯობა, როგორ ხარ?", "ka"

    with patch.object(server, "transcribe_forced", side_effect=fake_forced), \
         patch.object(server, "transcribe_dual") as m_dual, \
         patch.object(server, "translate_text", return_value="Merhaba, nasılsın?") as m_tr:
        result = process_speech_segment(
            fake_audio, "tr", "ka", None, {}, forced_source="ka",
        )
        assert not m_dual.called
        assert result["from"] == "ka"
        assert result["to"] == "tr"
        assert "გამარჯობა" in result["original"]
        assert result["translated"] == "Merhaba, nasılsın?"
        assert result["stt_language"] == "ka"
        assert m_tr.call_args[0][1:] == ("ka", "tr")
    print("TEST forced KA button OK")


def test_forced_en_source_not_turkish():
    fake_audio = b"RIFF" + b"\x00" * 200

    def fake_forced(data, source_lang, timings=None):
        assert source_lang == "en"
        return "Hello, how are you today?", "en"

    with patch.object(server, "transcribe_forced", side_effect=fake_forced), \
         patch.object(server, "translate_text", return_value="Merhaba, bugün nasılsın?"):
        result = process_speech_segment(
            fake_audio, "tr", "en", None, {}, forced_source="en",
        )
        assert result["from"] == "en"
        assert result["to"] == "tr"
        assert result["original"].startswith("Hello")
        assert "Merhaba" in result["translated"]
    print("TEST forced EN button OK")


def test_forced_es_and_ru():
    fake_audio = b"RIFF" + b"\x00" * 200
    for code, transcript, translated in (
        ("es", "Hola, cómo estás?", "Merhaba, nasılsın?"),
        ("ru", "Здравствуйте, как дела?", "Merhaba, nasılsın?"),
    ):
        def fake_forced(data, source_lang, timings=None, _code=code, _t=transcript):
            assert source_lang == _code
            return _t, _code

        with patch.object(server, "transcribe_forced", side_effect=fake_forced), \
             patch.object(server, "translate_text", return_value=translated):
            result = process_speech_segment(
                fake_audio, "tr", code, None, {}, forced_source=code,
            )
            assert result["from"] == code
            assert result["to"] == "tr"
            assert result["original"] == transcript
    print("TEST forced ES/RU buttons OK")


def test_language_switch_does_not_carry_previous():
    """Önceki dil yeni butona taşınmaz."""
    fake_audio = b"RIFF" + b"\x00" * 200
    calls = []

    def fake_forced(data, source_lang, timings=None):
        calls.append(source_lang)
        return {
            "tr": ("Merhaba", "tr"),
            "en": ("Hello", "en"),
            "ka": ("გამარჯობა", "ka"),
        }[source_lang]

    with patch.object(server, "transcribe_forced", side_effect=fake_forced), \
         patch.object(server, "translate_text", side_effect=lambda t, f, to: f"T[{f}->{to}] {t}"):
        r1 = process_speech_segment(fake_audio, "tr", "en", "en", {}, forced_source="tr")
        r2 = process_speech_segment(fake_audio, "tr", "en", "tr", {}, forced_source="en")
        r3 = process_speech_segment(fake_audio, "tr", "ka", "en", {}, forced_source="ka")
        assert calls == ["tr", "en", "ka"]
        assert r1["from"] == "tr" and r1["to"] == "en"
        assert r2["from"] == "en" and r2["to"] == "tr"
        assert r3["from"] == "ka" and r3["to"] == "tr"
    print("TEST language switch no carry OK")


def test_unsupported_forced_source_errors():
    try:
        process_speech_segment(b"x", "tr", "en", None, {}, forced_source="xx")
        assert False, "expected error"
    except ValueError as e:
        assert "dil çiftinde yok" in str(e).lower() or "yapılandırma" in str(e).lower()
    print("TEST unsupported source error OK")


def test_all_pair_langs_have_stt_config():
    for code in ("tr", "en", "ka", "es", "ru"):
        assert code in STT_LANG, code
    print("TEST STT_LANG covers TR/EN/KA/ES/RU OK")


if __name__ == "__main__":
    test_forced_source_uses_button_language_not_detection()
    test_forced_ka_source_not_turkish()
    test_forced_en_source_not_turkish()
    test_forced_es_and_ru()
    test_language_switch_does_not_carry_previous()
    test_unsupported_forced_source_errors()
    test_all_pair_langs_have_stt_config()
    print("\nAll forced-source Bas Konuş tests passed.")
