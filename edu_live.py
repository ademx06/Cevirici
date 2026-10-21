"""Gemini Live API — iki yönlü anlık ses (WebSocket) için sunucu tarafı.

Telefon Google'a doğrudan bağlanır (en düşük gecikme); API anahtarı sunucuda kalır.
Sunucu yalnızca kısa ömürlü (ephemeral) bir jeton ve oturum kurulum mesajını üretir.

• Öğretmen   : LIVE_MODEL (varsayılan gemini-3.8-live) — yerel ses, sistem talimatı ile ders
• Çeviri     : LIVE_TRANSLATE_MODEL (varsayılan gemini-3.5-live-translate-preview) — konuşurken çevirir
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import education_engine as ee

WS_BASE = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService"
WS_TOKEN_URL = WS_BASE + ".BidiGenerateContentConstrained?access_token="
TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"

TUTOR_MODELS = [m for m in (os.environ.get("LIVE_MODEL", "").strip(), "gemini-3.8-live", "gemini-3.1-flash-live-preview") if m]
TRANSLATE_MODELS = [m for m in (os.environ.get("LIVE_TRANSLATE_MODEL", "").strip(), "gemini-3.5-live-translate-preview") if m]

LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "ru": "Russian",
    "ar": "Arabic", "zh": "Mandarin Chinese", "ka": "Georgian", "tr": "Turkish",
}
BCP47 = {"en": "en", "de": "de", "fr": "fr", "es": "es", "it": "it", "ru": "ru", "ar": "ar", "zh": "zh-Hans", "ka": "ka", "tr": "tr"}

LEVEL_STYLE = {
    "A1": "Use very short, simple sentences (max ~8 words), very common words, present tense. Speak a little slowly and clearly.",
    "A2": "Use short simple sentences and everyday words. Speak clearly, slightly slower than normal.",
    "B1": "Use natural everyday sentences with some connectors. Normal pace.",
    "B2": "Speak fluently and naturally with varied tenses and some idioms.",
    "C1": "Speak rich, idiomatic native language at natural speed.",
    "C2": "Speak fully natively, sophisticated and nuanced.",
}

_DEAD_MODELS: dict[str, float] = {}
_KEY_COOLDOWN: dict[str, float] = {}


def tutor_instructions(lang: str, level: str, scenario: str | None = None, weak: list[str] | None = None,
                       history: list[dict] | None = None) -> str:
    name = LANG_NAMES.get(lang, "English")
    level = level if level in LEVEL_STYLE else "A1"
    parts = [
        f"You are a warm, encouraging {name} conversation tutor talking by voice with a Turkish native speaker.",
        f"Learner level: CEFR {level}. {LEVEL_STYLE[level]}",
        f"Speak {name} only, except very short Turkish explanations when the learner needs help.",
        "Keep every reply SHORT: one reaction plus ONE follow-up question (max 2 sentences), so the dialogue flows.",
        "If the learner's sentence has a grammar or word mistake: first say the corrected sentence naturally "
        f"(for example start with the {name} equivalent of 'You mean:'), then add ONE very short Turkish hint about the rule, "
        "then continue the conversation. Do not correct pronunciation accents or tiny slips that don't change grammar.",
        f"If the learner speaks TURKISH, they need help: tell them in one short Turkish sentence how to say it, then say the {name} "
        f"sentence clearly, say it once more slowly, and invite them (in {name}) to repeat it.",
        "Never read out emojis, lists or symbols. Never mention that you are an AI model.",
    ]
    if scenario:
        rp = ee.ROLEPLAYS.get(scenario) or {}
        if rp:
            parts.append(
                f"ROLEPLAY: {rp.get('title') or scenario}. You play: {rp.get('teacherRole') or 'the other person'}. "
                f"Learner plays: {rp.get('userRole') or 'themselves'}. Goal: {rp.get('goal') or ''} "
                "Stay in role and improvise naturally from what the learner says."
            )
    if weak:
        parts.append("Learner's recent mistakes (gently practise these): " + "; ".join(w[:80] for w in weak[:4]))
    hist = [h for h in (history or []) if isinstance(h, dict) and str(h.get("text") or "").strip()][-12:]
    if hist:
        lines = [("Learner" if h.get("role") == "user" else "You") + ": " + str(h.get("text"))[:240].replace("\n", " ") for h in hist]
        parts.append("CONVERSATION SO FAR (continue it naturally, remember what the learner told you, do not restart):\n"
                     + "\n".join(lines))
        parts.append(f"When you receive the text '[BAŞLA]', welcome the learner back in {name} in one short sentence and "
                     "continue from where you left off with one question.")
    else:
        parts.append(
            f"When you receive the text '[BAŞLA]', greet the learner warmly in {name} in one short sentence and ask one easy question."
        )
    return "\n".join(parts)


def tutor_setup(model: str, lang: str, level: str, scenario: str | None, weak: list[str] | None, voice: str = "",
                vad: bool = False, history: list[dict] | None = None) -> dict:
    gen: dict = {"responseModalities": ["AUDIO"], "temperature": 0.7}
    if voice:
        gen["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    return {
        "model": f"models/{model}",
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": tutor_instructions(lang, level, scenario, weak, history)}]},
        # vad=True: ses yalnızca basılıyken gönderilir, Google konuşmayı kendisi algılar → yazı konuşurken akar;
        #           bırakınca audioStreamEnd ile cevap hemen başlar. vad=False: activityStart/End elle.
        "realtimeInputConfig": ({"automaticActivityDetection": {
            "disabled": False, "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
            "endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "prefixPaddingMs": 120, "silenceDurationMs": 1600}}
            if vad else {"automaticActivityDetection": {"disabled": True}}),
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "sessionResumption": {},
    }


def interpret_instructions(source: str, target: str, both: bool) -> str:
    a, b = LANG_NAMES.get(source, source), LANG_NAMES.get(target, target)
    rules = ("Translate faithfully in first person with the same meaning, tone and politeness. Speak naturally and clearly. "
             "Never answer questions, never comment, never greet, never explain, never add or drop information. "
             "If a question is asked, translate the question itself. If the audio is only noise or unclear, say nothing.")
    if both:
        return (f"You are a professional two-way interpreter between {a} and {b}. You are NOT a chatbot or assistant. "
                f"When you hear {a}, speak ONLY its {b} translation. When you hear {b}, speak ONLY its {a} translation. " + rules)
    return (f"You are a professional interpreter. You are NOT a chatbot or assistant. The speaker speaks {a}. "
            f"Speak ONLY the {b} translation of what they say (if they use another language, still translate into {b}). " + rules)


def interpret_setup(model: str, source: str, target: str, both: bool = False, vad: bool = False) -> dict:
    """Canlı tercüman — eğitimdeki aynı Live model; bas-konuş (elle) ya da eller serbest (otomatik algılama)."""
    ric = ({"automaticActivityDetection": {
        "disabled": False, "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
        "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH", "prefixPaddingMs": 100, "silenceDurationMs": 700}}
        if vad else {"automaticActivityDetection": {"disabled": True}})
    return {
        "model": f"models/{model}",
        "generationConfig": {"responseModalities": ["AUDIO"], "temperature": 0.2},
        "systemInstruction": {"parts": [{"text": interpret_instructions(source, target, both)}]},
        "realtimeInputConfig": ric,
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }


def translate_setup(model: str, target: str, variant: int = 0) -> dict:
    tc = {"targetLanguageCode": BCP47.get(target, target), "echoTargetLanguage": False}
    if variant == 1:  # dokümandaki biçim (canlıda reddedildi — yedek)
        return {"model": f"models/{model}", "generationConfig": {
            "responseModalities": ["AUDIO"], "inputAudioTranscription": {}, "outputAudioTranscription": {},
            "translationConfig": tc}}
    return {"model": f"models/{model}", "generationConfig": {"responseModalities": ["AUDIO"], "translationConfig": tc},
            "inputAudioTranscription": {}, "outputAudioTranscription": {}}


def _iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _post(key: str, body: dict, timeout: float = 10) -> tuple[int, dict]:
    req = Request(TOKEN_URL, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode() or "{}")
        except Exception:
            detail = {}
        return exc.code, detail
    except Exception as exc:  # network
        return 0, {"error": {"message": str(exc)[:200]}}


def create_token(setup: dict, minutes: int = 30) -> dict:
    """Ephemeral token. Önce kurulumu jetona kilitlemeyi dener (talimat sunucuda kalır), olmazsa açık jeton."""
    keys = [k for k in ee._gemini_keys() if _KEY_COOLDOWN.get(k, 0) < time.time()] or ee._gemini_keys()
    if not keys:
        return {"ok": False, "error": "GEMINI_API_KEY tanımlı değil"}
    now = _dt.datetime.now(_dt.timezone.utc)
    base = {
        "uses": 1,
        "expireTime": _iso(now + _dt.timedelta(minutes=minutes)),
        "newSessionExpireTime": _iso(now + _dt.timedelta(minutes=2)),
    }
    variants = [
        ("locked", {**base, "bidiGenerateContentSetup": {"setup": setup}}),
        ("open", base),
    ]
    last_err = ""
    for key in keys:
        for mode, body in variants:
            status, data = _post(key, body)
            if status == 200 and data.get("name"):
                return {"ok": True, "token": data["name"], "lock": mode}
            msg = ((data.get("error") or {}).get("message") or "")[:300]
            last_err = f"{status} {msg}"
            if status in (401, 403, 429):
                _KEY_COOLDOWN[key] = time.time() + (60 if status == 429 else 600)
                break  # next key
    return {"ok": False, "error": last_err or "jeton alınamadı"}


def live_session(kind: str, *, lang: str = "en", level: str = "A1", scenario: str | None = None,
                 weak: list[str] | None = None, target: str = "en", voice: str = "", model: str = "",
                 variant: int = 0, vad: bool = False, source: str = "tr", both: bool = False,
                 history: list[dict] | None = None) -> dict:
    """Jeton + kurulum mesajı + WebSocket adresi (istemci doğrudan Google'a bağlanır)."""
    if kind == "translate":
        models = [model] if model else TRANSLATE_MODELS
        build = lambda m: translate_setup(m, target, variant)  # noqa: E731
    elif kind == "interpret":
        models = [model] if model else TUTOR_MODELS
        build = lambda m: interpret_setup(m, source, target, both, vad)  # noqa: E731
    else:
        models = [model] if model else TUTOR_MODELS
        build = lambda m: tutor_setup(m, lang, level, scenario, weak, voice, vad, history)  # noqa: E731
    models = [m for m in models if _DEAD_MODELS.get(m, 0) < time.time()] or models
    m = models[0]
    setup = build(m)
    tok = create_token(setup)
    if not tok.get("ok"):
        return {"ok": False, "error": tok.get("error"), "model": m}
    return {
        "ok": True,
        "ws": WS_TOKEN_URL + tok["token"],
        "setup": setup,
        "lock": tok["lock"],
        "model": m,
        "fallback_models": models[1:],
        # Bazı sürümlerde jetonla gelen sistem talimatı yok sayılabiliyor → istemci ayrıca ilk mesajda gönderir
        "instructions": setup.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "") if kind == "tutor" else "",
    }


def mark_model_dead(model: str) -> None:
    _DEAD_MODELS[model] = time.time() + 1800
