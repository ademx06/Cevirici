#!/usr/bin/env python3
"""Gemini Live kurulum mesajları — canlıda doğrulanan biçimler bozulmasın."""
import edu_live as el


def test_tutor_setup_shape():
    s = el.tutor_setup("gemini-3.8-live", "de", "A2", "cafe", ["Ich habe gegangen → Ich bin gegangen"])
    assert s["model"] == "models/gemini-3.8-live"
    assert s["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert "thinkingConfig" not in s["generationConfig"]  # canlıda 1007 ile reddedildi
    assert s["realtimeInputConfig"]["automaticActivityDetection"]["disabled"] is True
    assert "inputAudioTranscription" in s and "outputAudioTranscription" in s
    txt = s["systemInstruction"]["parts"][0]["text"]
    assert "German" in txt and "A2" in txt and "ROLEPLAY" in txt and "[BAŞLA]" in txt and "TURKISH" in txt


def test_translate_setup_valid_variant_default():
    s = el.translate_setup("gemini-3.5-live-translate-preview", "zh")
    assert s["generationConfig"]["translationConfig"] == {"targetLanguageCode": "zh-Hans", "echoTargetLanguage": False}
    # canlıda çalışan biçim: transkripsiyon ayarları üst düzeyde
    assert "inputAudioTranscription" in s and "inputAudioTranscription" not in s["generationConfig"]


if __name__ == "__main__":
    test_tutor_setup_shape(); test_translate_setup_valid_variant_default(); print("ok")
