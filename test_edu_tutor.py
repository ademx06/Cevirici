#!/usr/bin/env python3
"""Yeni eğitim motoru (edu_tutor) + okunuş testleri — yapay zekâ taklit edilir."""
from __future__ import annotations

import json

import edu_tutor as et
import okunus as ok


def _fake_llm(payload: dict, captured: dict | None = None):
    def fn(system, user, max_tokens=700, **kw):
        if captured is not None:
            captured["system"] = system
            captured["user"] = user
        return payload, "groq"
    return fn


def test_rule_okunus_languages():
    assert ok.rule_okunus("¡Hola! ¿Cómo estás hoy?", "es") == "Ola! Komo estas oi?"
    assert ok.rule_okunus("Ciao! Come stai oggi?", "it") == "Çao! Kome stai oci?"
    assert ok.rule_okunus("Wie geht es dir heute?", "de") == "Vi get es dir hoyte?"
    assert ok.rule_okunus("Привет! Как дела сегодня?", "ru") == "Privet! Kak dela sevodnya?"
    assert ok.rule_okunus("გამარჯობა! როგორ ხარ?", "ka") == "Gamarcoba! Rogor har?"
    assert ok.rule_okunus("Je voudrais un café.", "fr") == "Jö vudre en kafe."
    for lang, text in [("de", "Guten Morgen"), ("es", "Buenos días"), ("it", "Buongiorno"), ("fr", "Merci beaucoup")]:
        assert ok.okunus(text, lang), lang  # never empty for rule languages


def test_okunus_validation():
    assert ok.looks_valid("Hav ar yu?", "How are you?", "en")
    assert not ok.looks_valid("你好", "你好", "zh")
    assert not ok.looks_valid("", "Hello", "en")


def test_speak_turn_with_fix():
    cap: dict = {}
    et._call_llm = _fake_llm({
        "reply": "That sounds fun! What did you eat?",
        "reply_tr": "Kulağa eğlenceli geliyor! Ne yedin?",
        "okunus": "Det saunds fan! Vat did yu it?",  # ignored now: fast model makes okunus
        "fix": {"status": "fix", "fixed": "I went to the cinema yesterday.", "fixed_tr": "Dün sinemaya gittim.",
                "fixed_okunus": "Ay vent tu dı sinema yestırdey.", "explain_tr": "Geçmiş zaman: go → went."},
        "words": [{"word": "fun", "tr": "eğlenceli"}],
        "user_level": "A2",
    }, cap)
    res = et.tutor_turn("I go to cinema yesterday", "en", level="A2", history=[
        {"role": "tutor", "text": "What did you do yesterday?"}])
    assert res["reply"].startswith("That sounds fun")
    assert res["okunus"] == "Det saunds fan! Vat did yu it?"
    assert res["fix"]["fixed"] == "I went to the cinema yesterday."
    assert res["fix"]["okunus"]
    assert res["user_level"] == "A2"
    # speak plan: corrected sentence first, then reply — target language only
    assert [s["text"] for s in res["speak"]] == ["I went to the cinema yesterday.", "That sounds fun! What did you eat?"]
    assert all(s["lang"] == "en" for s in res["speak"])
    assert "LEARNER LEVEL: A2" in cap["system"]
    assert "What did you do yesterday?" in cap["user"]


def test_rule_language_okunus_comes_from_rules_not_llm():
    cap: dict = {}
    et._call_llm = _fake_llm({"reply": "¡Muy bien! ¿Y tú qué haces?", "reply_tr": "Çok iyi! Peki sen ne yapıyorsun?",
                              "fix": None, "words": [], "user_level": "A1"}, cap)
    res = et.tutor_turn("Yo estoy bien", "es", level="A1")
    assert res["okunus"] == "Mui bien! I tu ke ases?"
    assert '"okunus"' not in cap["system"]  # no wasted tokens for rule languages


def test_fix_identical_to_user_is_dropped():
    et._call_llm = _fake_llm({"reply": "Great!", "reply_tr": "Harika!", "okunus": "Greyt!",
                              "fix": {"status": "fix", "fixed": "I am fine.", "explain_tr": "x"}})
    res = et.tutor_turn("i am fine", "en")
    assert res["fix"] is None
    assert [s["text"] for s in res["speak"]] == ["Great!"]


def test_help_mode_examples():
    cap: dict = {}
    et._call_llm = _fake_llm({
        "reply": "Versuch es!", "reply_tr": "Dene!",
        "examples": [{"text": "Ich möchte einen Kaffee.", "tr": "Bir kahve istiyorum."},
                     {"text": "Einen Kaffee, bitte.", "tr": "Bir kahve lütfen."}],
        "explain_tr": "'möchte' = isterim (kibar).", "fix": None, "words": [],
    }, cap)
    res = et.tutor_turn("kahve istiyorum nasıl derim", "de", mode="help", scenario="cafe")
    assert res["mode"] == "help"
    assert res["examples"][0]["okunus"] == "Ih möhte aynen Kafe."
    assert res["speak"] == [{"text": "Ich möchte einen Kaffee.", "lang": "de"}]
    assert "HELP" in cap["system"] and "ROLEPLAY" in cap["system"]


def test_ai_unavailable_falls_back_to_rules():
    et._call_llm = lambda *a, **k: (None, "")
    res = et.tutor_turn("I am tired today", "en", level="A1")
    assert res["provider"] == "rules"
    assert res["reply"]
    assert res["speak"]


def test_help_fallback_uses_translation():
    et._call_llm = lambda *a, **k: (None, "")
    res = et.tutor_turn("bir kahve istiyorum nasıl derim", "de", mode="help",
                        translate_fn=lambda t, a, b: "Ich möchte einen Kaffee." if t == "bir kahve istiyorum" else "?")
    assert res["examples"][0]["text"] == "Ich möchte einen Kaffee.", res
    assert res["reply"] == "Versuch es mal!"
    res = et.tutor_turn("Ich bin müde", "de")
    assert res["reply"] and res["okunus"] and not any(c in res["reply"] for c in "🇹")


def test_chinese_okunus_from_pinyin():
    cap: dict = {}
    et._call_llm = _fake_llm({"reply": "我也喜欢喝咖啡。", "reply_tr": "Ben de kahve içmeyi severim.",
                              "pinyin": "Wǒ yě xǐhuan hē kāfēi.", "fix": None, "words": []}, cap)
    res = et.tutor_turn("我喜欢咖啡", "zh")
    assert res["okunus"] == "Vo ye şihuan hı kafey.", res["okunus"]
    assert '"pinyin"' in cap["system"]
    assert ok.pinyin_okunus("Nǚ péngyou, xièxie! Zhōngguó") == "Nü pıngyo, şyeşye! Cungguo"


def test_strict_grammar_instruction():
    cap: dict = {}
    et._call_llm = _fake_llm({"reply": "Super!", "reply_tr": "Süper!", "fix": None}, cap)
    et.tutor_turn("Ich habe gestern ins Kino gegangen", "de")
    assert "auxiliary" in cap["system"]


def test_okunus_from_fast_model_and_validated():
    et._call_llm = _fake_llm({"reply": "That's great! How was your day?", "reply_tr": "Harika! Günün nasıldı?",
                              "fix": {"status": "fix", "fixed": "Yesterday I went to the park.", "fixed_tr": "Dün parka gittim."}})
    calls = []
    def fake_batch(texts, lang):
        calls.append(list(texts))
        return ["Harika! Günün nasıldı?", "Yestırdey ay vent tu dı park."]  # 1st is a translation → reject
    et.llm_okunus_batch = fake_batch
    spoken = []
    res = et.tutor_turn("Yesterday I go to the park", "en", on_speak=lambda items: spoken.extend(items))
    assert calls == [["That's great! How was your day?", "Yesterday I went to the park."]]
    assert res["fix"]["okunus"] == "Yestırdey ay vent tu dı park."
    assert res["okunus"] and "Günün" not in res["okunus"]
    assert spoken and spoken[0]["text"] == "Yesterday I went to the park."
    assert not ok.looks_valid("Wot dıd yu", "What did you", "en")
    assert not ok.looks_valid("Glad tu hir ðæt", "Glad to hear that", "en")


def test_greeting_is_instant_and_has_okunus():
    for lang in ["en", "de", "fr", "es", "it", "ru", "ar", "zh", "ka"]:
        g = et.greeting_turn(lang, "A1")
        assert g["reply"] and g["okunus"], lang
        assert g["speak"][0]["lang"] == lang
    g = et.greeting_turn("en", "C1")
    assert g["reply"] != et.greeting_turn("en", "A1")["reply"]


if __name__ == "__main__":
    import inspect, sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:
                fails += 1
                print("FAIL", name, repr(e))
    sys.exit(1 if fails else 0)
