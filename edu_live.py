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


def tutor_instructions(lang: str, level: str, scenario: str | None = None, weak: list[str] | None = None) -> str:
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
    parts.append(
        f"When you receive the text '[BAŞLA]', greet the learner warmly in {name} in one short sentence and ask one easy question."
    )
    return "\n".join(parts)


def tutor_setup(model: str, lang: str, level: str, scenario: str | None, weak: list[str] | None, voice: str = "") -> dict:
    gen: dict = {"responseModalities": ["AUDIO"], "temperature": 0.7}
    if voice:
        gen["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    return {
        "model": f"models/{model}",
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": tutor_instructions(lang, level, scenario, weak)}]},
        # Bas-konuş: sesi biz başlatıp bitiriyoruz → bıraktığın anda cevap başlar
        "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "sessionResumption": {},
    }


def translate_setup(model: str, target: str, variant: int = 0) -> dict:
    tc = {"targetLanguageCode": BCP47.get(target, target), "echoTargetLanguage": False}
    if variant == 0:  # dokümandaki biçim
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
                 variant: int = 0) -> dict:
    """Jeton + kurulum mesajı + WebSocket adresi (istemci doğrudan Google'a bağlanır)."""
    if kind == "translate":
        models = [model] if model else TRANSLATE_MODELS
        build = lambda m: translate_setup(m, target, variant)  # noqa: E731
    else:
        models = [model] if model else TUTOR_MODELS
        build = lambda m: tutor_setup(m, lang, level, scenario, weak, voice)  # noqa: E731
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
        "instructions": setup.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "") if kind != "translate" else "",
    }


def mark_model_dead(model: str) -> None:
    _DEAD_MODELS[model] = time.time() + 1800
