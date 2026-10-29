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
    "ar": "Arabic", "zh": "Mandarin Chinese", "ka": "Georgian", "id": "Indonesian", "tr": "Turkish",
}
BCP47 = {"en": "en", "de": "de", "fr": "fr", "es": "es", "it": "it", "ru": "ru", "ar": "ar", "zh": "zh-Hans", "ka": "ka", "id": "id", "tr": "tr"}

LEVEL_STYLE = {
    "A1": "Use very short, simple sentences (max ~8 words), very common words, present tense. Speak a little slowly and clearly.",
    "A2": "Use short simple sentences and everyday words. Speak clearly, slightly slower than normal.",
    "B1": "Use natural everyday sentences with some connectors. Normal pace.",
    "B2": "Speak fluently and naturally with varied tenses and some idioms.",
    "C1": "Speak rich, idiomatic native language at natural speed.",
    "C2": "Speak fully natively, sophisticated and nuanced.",
}

LADDERS = {
    "A1": [
        "hello / goodbye / good morning", "'my name is…' and 'what is your name?'", "'how are you?' and 'I am fine, thank you'",
        "'I am from Turkey' and 'where are you from?'", "numbers 1-10 and 'I am … years old'", "please, thank you, sorry, yes, no, 'I do not understand'",
        "'I want / I would like…' + food and drink", "'I like… / I do not like…'", "family: 'this is my…'", "'I have…' (a car, a brother, a dog)",
        "'how much is it?' and numbers up to 100", "'where is…?' (toilet, station, hotel)", "days of the week and 'today / tomorrow'",
        "colours and 'it is big / small / good'", "mini dialogue: ordering a coffee",
    ],
    "A2": [
        "daily routine (I wake up, I work, I go home)", "past events: 'yesterday I…'", "plans: 'tomorrow I will… / I am going to…'",
        "shopping, sizes and prices", "travel, tickets and directions", "weather and seasons", "jobs and hobbies", "health and feelings: 'I have a headache'",
        "restaurant: ordering and asking for the bill", "describing people and places", "comparing: bigger, better, the best", "can / must / want to: abilities and rules",
    ],
    "B1": [
        "talking about your life story with past tenses and time words", "experiences: 'have you ever…?' (perfect tenses)", "giving reasons: because, so, although",
        "future plans and predictions", "advice and obligations: should, must, have to", "comparing and describing in detail",
        "conditionals (real): 'if it rains, I will…'", "opinions: 'I think… / in my opinion…', agreeing and disagreeing", "telling a story in order (first, then, finally)",
        "work, study and technology topics", "travel problems and complaints (polite requests)", "describing a process or a habit",
    ],
    "B2": [
        "tenses in contrast: narrating past events with background and sequence", "hypothetical situations: 'if I were… I would…'", "arguing a point: for and against, concession",
        "reported speech: 'he said that…'", "passive voice and describing processes", "news, society and environment: discussing issues",
        "idioms and collocations for everyday life", "formal vs informal register: emails and phone calls", "regrets and wishes about the past",
        "summarising an article or a film", "negotiating and persuading", "abstract topics: success, happiness, culture",
    ],
    "C1": [
        "developing a long, well-structured argument", "nuance: hedging and softening ('it seems that…', 'I would tend to say…')", "advanced connectors and discourse markers",
        "idiomatic and figurative language", "debating: counter-arguments and rebuttals", "summarising and paraphrasing complex ideas",
        "register shifts: academic, professional, colloquial", "humour, irony and implication", "speculating about the past and present with precision", "storytelling with rhetorical effect",
    ],
    "C2": [
        "precise, nuanced expression of subtle differences in meaning", "rhetoric, emphasis and inversion for effect", "rare idioms, proverbs and cultural references",
        "abstract and philosophical discussion", "paraphrasing and re-registering the same idea three ways", "irony, understatement and wordplay",
        "persuasive speech and structured improvisation", "native-like fluency: fillers, reformulation, ellipsis", "critical analysis of a text or an argument", "dialect, slang and regional variation (explained)",
    ],
}
LANG_NOTES = {
    "de": "GENDER: always teach every noun WITH its article (der/die/das) and say it that way.",
    "fr": "GENDER: always teach every noun WITH its article (le/la/un/une).",
    "es": "GENDER: teach nouns with their article (el/la) so the learner hears the gender.",
    "it": "GENDER: teach nouns with their article (il/la/un/una) so the learner hears the gender.",
    "ru": "Pronounce with correct stress; teach short whole phrases; Cyrillic is shown to the learner with a Turkish reading.",
    "ar": "Use clear Modern Standard Arabic, fully vowelled in your pronunciation, simple and slow at A1-A2.",
    "zh": "Say each phrase slowly with clear tones; teach whole phrases, never single characters out of context.",
    "ka": "Say each phrase slowly with clear Georgian pronunciation (ejective consonants); teach whole phrases.",
    "id": "Indonesian has no verb conjugation: teach simple patterns and affixes gradually.",
    "en": "",
}


def _step(level: str, step: int) -> tuple[int, int, str]:
    lad = LADDERS.get(level) or LADDERS["A1"]
    i = max(0, int(step or 0)) % len(lad)
    return i + 1, len(lad), lad[i]


BEGINNER_METHOD = (
    "BEGINNER LESSON MODE (only while the learner really is a beginner: if they clearly speak above A2 — full fluent sentences, complex grammar — drop the lesson mode at once, say a brief Turkish remark, and converse naturally at THEIR real level): you LEAD a step-by-step lesson; say the Turkish sentence and the {name} phrase in ONE continuous turn without stopping or pausing between them; never wait for the learner to know what to say. Every turn follows this loop: "
    "(a) in ONE short Turkish sentence say what we learn now and its meaning; (b) say the COMPLETE {name} phrase slowly and clearly as its own separate sentence (never inside a Turkish sentence; if you also break it into parts, always finish by saying the whole phrase once more); "
    "(c) invite the learner (in Turkish, e.g. 'Şimdi sen söyle') to repeat it, and STOP and wait. "
    "When the learner repeats it, FIRST compare word by word what you actually heard with the phrase you taught. If it is a different phrase or meaning, NEVER praise it and NEVER move on: say in Turkish what you heard and which phrase you wanted, then ask again. Only if it matches: praise in a few Turkish words, then add ONE tiny variation (swap one word) or move to the next step; "
    "if it is wrong or unclear, say it again slowly, point to the one hard word, and ask again (at most 2 tries, then move on kindly). "
    "Every 3-4 phrases, do a quick review: ask in Turkish how to say a phrase you taught earlier. "
    "If the learner says they do not understand or do not know, simplify: a shorter phrase, word by word with Turkish meanings. "
    "BUILD TURN: every second phrase, do a BUILD turn: give a sentence frame with ONE new word (e.g. the frame you just taught + a new noun) and ask the learner to make their OWN new sentence with it; teach words only inside phrases, at most 2 new words per turn. "
    "LESSON LADDER (follow in order, never restart; the app tracks progress): {ladder}. CURRENT STEP: {cur}. "
)
ADV_METHOD = (
    "CEFR COURSE ({level}): you LEAD a structured course, not random chat. Current focus (step {n} of {m}): {focus}. "
    "Every turn: (1) react in ONE short sentence to what the learner said; (2) teach or elicit ONE item of the focus (a structure, a connector or 2-3 useful words/collocations) "
    "- say it in {name} first, add its Turkish meaning in a few Turkish words only if the learner struggles; "
    "(3) ask ONE question that makes the learner PRODUCE that item in a full sentence (B1: 1-2 sentences; B2: 2-3 sentences with a reason; C1: a developed argument; C2: a precise, nuanced answer). "
    "Never accept one-word answers: ask for a full sentence. When the learner has used the item correctly twice, say briefly that you move on and bring in the next focus naturally; "
    "re-use earlier items so they stick. If the learner is clearly above this level, raise the complexity at once."
)
_DEAD_MODELS: dict[str, float] = {}
_KEY_COOLDOWN: dict[str, float] = {}


def tutor_instructions(lang: str, level: str, scenario: str | None = None, weak: list[str] | None = None,
                       history: list[dict] | None = None, step: int = 0) -> str:
    name = LANG_NAMES.get(lang, "English")
    level = level if level in LEVEL_STYLE else "A1"
    beginner = level in ("A1", "A2") and not scenario
    sn, sm, sf = _step(level, step)
    parts = [
        f"You are a warm, encouraging {name} conversation tutor talking by voice with a Turkish native speaker.",
        f"Learner level: CEFR {level}. {LEVEL_STYLE[level]}",
        (f"You are TEACHING a learner who may know ZERO {name}. Use Turkish for short explanations and {name} for the phrases being taught."
         if beginner else f"Speak {name} only, except very short Turkish explanations when the learner needs help."),
        "Keep every reply SHORT (max 3 sentences) so the dialogue flows, but make every turn TEACH something:",
        (BEGINNER_METHOD.format(name=name, ladder="; ".join(f"{k + 1} {v}" for k, v in enumerate(LADDERS[level])), cur=f"step {sn} of {sm}: {sf}") if beginner else "") +
        ("" if beginner or scenario else ADV_METHOD.format(name=name, level=level, n=sn, m=sm, focus=sf) + " ") +
        ("" if beginner or not scenario else (f"Keep your own lines at CEFR {level}; make the learner answer in full sentences (not single words); "
                                             f"whenever natural, steer the role-play toward this course focus: {sf}. ")) +
        ("" if beginner else (f"TEACHING METHOD: (1) react briefly to what the learner said; (2) when it fits, introduce ONE useful new {name} word or "
        "phrase from your own sentence and give its Turkish meaning in a few Turkish words; (3) end with ONE easy question or a "
        "small task the learner can answer with the new phrase (but when you are correcting a mistake, follow the CORRECTION RULE instead and ask no new question). Vary the tasks (answer a question, say it another way, "
        "describe something, make a sentence with the new word). Do not repeat a phrase you already taught.")),
        "TURKISH SUPPORT: Turkish explanations must be natural, correct Turkish. "
        + ("A1-A2: give a Turkish tip nearly every turn. " if level in ("A1", "A2") else
           "B1-B2: give a Turkish tip only when the learner struggles or makes a mistake. " if level in ("B1", "B2") else
           "C1-C2: use almost no Turkish. ")
        + "Always say the target-language sentence BEFORE its Turkish explanation, never mix both languages in one sentence.",
        "If the learner's sentence has a grammar or word mistake: first say the corrected sentence naturally "
        f"(for example start with the {name} equivalent of 'You mean:'), then add ONE very short Turkish hint about the rule, "
        "then give ONE short correct example with the same pattern. CORRECTION RULE: in this turn do NOT ask any new question and do NOT "
        f"continue the topic — say the corrected {name} sentence slowly once more, then ask the learner (in {name}, e.g. 'Now you say it') to "
        "repeat it, and STOP and wait. When the learner repeats it, praise briefly (and gently correct once more if it is still wrong), "
        "and only then continue the conversation with your next question. "
        f"LISTENING RULE: before you praise, check that what you heard is a meaningful {name} sentence that fits what you asked; if it is unrelated, nonsensical or sounds like a misheard word, do NOT say it is correct: say in Turkish that you did not catch it clearly and ask the learner to say it again. "
        "If the sentence is correct, praise it in a few words (not every time) and suggest one more natural way to say it when there is one. "
        "Do not correct pronunciation accents or tiny slips that don't change grammar.",
        f"If the learner speaks TURKISH, they need help: tell them in one short Turkish sentence how to say it, then say the {name} "
        f"sentence clearly, say it once more slowly, and invite them (in {name}) to repeat it.",
        "Never read out emojis, lists or symbols. Never mention that you are an AI model."
        + ((" " + LANG_NOTES.get(lang, "")) if LANG_NOTES.get(lang) else ""),
        f"PRONUNCIATION: speak every Turkish sentence with native Turkish pronunciation and every {name} sentence with native "
        f"{name} pronunciation — never read Turkish with a foreign accent or {name} with a Turkish accent.",
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
        parts.append(
            ("When you receive the text '[BAŞLA]', welcome the learner back in ONE short Turkish sentence, quickly review the last phrase "
             "you taught (ask them to say it), then continue the lesson at the CURRENT STEP of the ladder."
             if beginner else
             f"When you receive the text '[BAŞLA]', welcome the learner back in {name} in one short sentence and "
             "continue from where you left off with one question."))
    else:
        parts.append(
            ("When you receive the text '[BAŞLA]', greet the learner warmly in ONE short Turkish sentence, say you will teach from the very "
             "beginning step by step, then teach the first phrase of the CURRENT STEP of the lesson ladder and ask them to repeat it."
             if beginner else
             f"When you receive the text '[BAŞLA]', greet the learner warmly in {name} in one short sentence and ask one easy question.")
        )
    return "\n".join(parts)


def tutor_setup(model: str, lang: str, level: str, scenario: str | None, weak: list[str] | None, voice: str = "",
                vad: bool = False, history: list[dict] | None = None, step: int = 0) -> dict:
    gen: dict = {"responseModalities": ["AUDIO"], "temperature": 0.7}
    if voice:
        gen["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    return {
        "model": f"models/{model}",
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": tutor_instructions(lang, level, scenario, weak, history, step)}]},
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
    rules = (
        "Translate faithfully in first person with the same meaning, tone and politeness. Speak naturally and clearly. "
        "Never answer questions, never comment, never greet, never explain, never add or drop information. "
        "If a question is asked, translate the question itself. "
        "Ignore background noise, music, TV and distant or overlapping voices: translate only the clear, close main speaker. "
        "If the audio is silence, only noise, or too unclear to understand, say NOTHING — "
        "do not invent fillers like '¿Qué?', 'What?', 'Huh?', 'Hmm', or random words."
    )
    if both:
        return (
            f"You are a professional two-way interpreter between {a} and {b}. You are NOT a chatbot or assistant. "
            f"When you hear {a}, speak ONLY its {b} translation. When you hear {b}, speak ONLY its {a} translation. "
            f"Treat each language as a native language: do not force English. " + rules
        )
    return (
        f"You are a professional interpreter. You are NOT a chatbot or assistant. "
        f"The speaker's language is {a} — treat {a} as their primary/native language for recognition. "
        f"Speak ONLY the {b} translation of what they say "
        f"(if they briefly mix another language, still produce only {b}). "
        f"Do not reply in {a}. Do not default to English unless {b} is English. " + rules
    )


def interpret_setup(model: str, source: str, target: str, both: bool = False, vad: bool = False) -> dict:
    """Canlı tercüman — eğitimdeki aynı Live model + aynı VAD hassasiyeti.

    Önceki HIGH + 700 ms İngilizce dışı dillerde cümleyi yarıda kesiyordu.
    Eğitim (tutor) ile aynı: END_SENSITIVITY_LOW + 1600 ms → tüm dillerde akıcı.
    """
    ric = ({"automaticActivityDetection": {
        "disabled": False, "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
        "endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "prefixPaddingMs": 120, "silenceDurationMs": 1600}}
        if vad else {"automaticActivityDetection": {"disabled": True}})
    return {
        "model": f"models/{model}",
        # 0.2 yerel ses modelinde ~2 sn sonra SESSİZLİK üretiyordu (yazı tam, ses kesik) → eğitimle aynı 0.7
        "generationConfig": {"responseModalities": ["AUDIO"], "temperature": 0.7},
        "systemInstruction": {"parts": [{"text": interpret_instructions(source, target, both)}]},
        "realtimeInputConfig": ric,
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "sessionResumption": {},
    }


def camera_instructions(target: str) -> str:
    tgt = LANG_NAMES.get(target, "Turkish")
    return (
        f"You are a real-time camera translator. You receive camera frames and the cue text '[ÇEVİR]'. "
        f"Every time you get '[ÇEVİR]', look at the LATEST camera frame, read ALL legible text in it (subtitles, captions, signs, screens, documents) "
        f"and say ONLY its faithful translation into {tgt}, in natural spoken {tgt}, as fast as possible. "
        "No greeting, no preface, no comment, no description of the image, never mention the frame. "
        f"If the text is already in {tgt}, read it aloud unchanged. Keep names, numbers and prices exact. "
        "If the visible text is the same as what you already translated, or nothing is legible, answer with a single dot and nothing else. "
        "Never invent text that is not visible."
    )


def camera_setup(model: str, target: str) -> dict:
    return {
        "model": f"models/{model}",
        "generationConfig": {"responseModalities": ["AUDIO"], "temperature": 0.2},
        "systemInstruction": {"parts": [{"text": camera_instructions(target)}]},
        "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
        "outputAudioTranscription": {},
        "sessionResumption": {},
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
                 history: list[dict] | None = None, step: int = 0) -> dict:
    """Jeton + kurulum mesajı + WebSocket adresi (istemci doğrudan Google'a bağlanır)."""
    if kind == "translate":
        models = [model] if model else TRANSLATE_MODELS
        build = lambda m: translate_setup(m, target, variant)  # noqa: E731
    elif kind == "camera":
        models = [model] if model else TUTOR_MODELS
        build = lambda m: camera_setup(m, target)  # noqa: E731
    elif kind == "interpret":
        models = [model] if model else TUTOR_MODELS
        build = lambda m: interpret_setup(m, source, target, both, vad)  # noqa: E731
    else:
        models = [model] if model else TUTOR_MODELS
        build = lambda m: tutor_setup(m, lang, level, scenario, weak, voice, vad, history, step)  # noqa: E731
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
        "instructions": setup.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "") if kind in ("tutor", "camera") else "",
    }


def mark_model_dead(model: str) -> None:
    _DEAD_MODELS[model] = time.time() + 1800
