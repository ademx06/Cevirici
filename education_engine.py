"""Profesyonel dil eğitimi motoru — doğal konuşma, düzeltme, profil."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen

LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "ru": "Russian", "ka": "Georgian", "it": "Italian", "ar": "Arabic", "zh": "Chinese",
}

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

SYSTEM_PROMPT = """You are a professional personal language tutor.
Speak primarily in the target language. Do not behave like a translation app.
Maintain natural conversation. Adapt to the user's level.
Correct important mistakes without killing the flow.
When correcting: give natural sentence, brief explanation if useful, then continue.
Use Turkish ONLY when user asks for Turkish explanation or seems confused.
Behave like a patient human teacher, not a translator.
Keep responses concise (2-4 sentences max unless explaining grammar).
Wait for the user to respond — do not answer your own questions."""

GREETINGS = {
    "en": [
        "Hi! Good evening. How was your day?",
        "Hello! It's great to see you. What did you do today?",
        "Good morning! What are you going to do today?",
        "Hey! How are you feeling today?",
    ],
    "de": ["Hallo! Wie war dein Tag?", "Guten Abend! Was hast du heute gemacht?"],
    "fr": ["Bonjour ! Comment s'est passée ta journée ?", "Salut ! Qu'as-tu fait aujourd'hui ?"],
    "es": ["¡Hola! ¿Cómo estuvo tu día?", "¡Buenas tardes! ¿Qué hiciste hoy?"],
    "ru": ["Привет! Как прошёл твой день?", "Здравствуй! Что ты делал сегодня?"],
    "ka": ["გამარჯობა! როგორ გაატარე დღე?", "გამარჯობა! რა გააკეთე დღეს?"],
    "it": ["Ciao! Com'è andata la giornata?", "Buonasera! Cosa hai fatto oggi?"],
}

ROLEPLAYS = {
    "friend": {"en": "You are chatting with a friendly local. Keep it casual."},
    "hotel": {"en": "You are a hotel receptionist in London. The user is checking in."},
    "restaurant": {"en": "You are a waiter. Help the user order food."},
    "airport": {"en": "You are an airport officer. Ask about travel documents."},
    "shop": {"en": "You are a shop assistant. Help the user buy something."},
    "interview": {"en": "You are a job interviewer. Ask professional questions."},
    "teacher": {"en": "You are an English teacher in a classroom."},
}

TOPICS_BY_LEVEL = {
    "A1": ["daily life", "food", "family", "weather", "hobbies"],
    "A2": ["work", "travel", "shopping", "restaurant", "weekend plans"],
    "B1": ["stress", "remote work", "movies", "health", "friendship"],
    "B2": ["culture", "technology", "career goals", "social media"],
    "C1": ["global issues", "abstract ideas", "professional debates"],
}

HELP_RE = re.compile(
    r"(nasıl\s+(?:söylerim|derim|denir)|ingilizcede|ne\s+demek|çevirir\s+misin|"
    r"how\s+do\s+i\s+say|what\s+is\s+.+\s+in\s+english)",
    re.I,
)

# (pattern, correct, category, explanation_en, explain_tr)
EN_RULES: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r"\bi very tired\b", re.I), "I'm very tired today.",
     "be_verb", "We need 'I'm' before adjectives.", "'Tired' sıfatından önce 'I'm' gerekir."),
    (re.compile(r"\bi am go\b", re.I), "I am going.", "present_continuous",
     "Use 'am going' for now.", "Şu an için 'am going' kullanılır."),
    (re.compile(r"\bi go to work yesterday\b", re.I), "I went to work yesterday.", "past_tense",
     "'Go' is irregular: go → went.", "'Go' düzensiz fiil: went."),
    (re.compile(r"\bi goed\b", re.I), "I went", "past_tense", "'Goed' is wrong. Past of 'go' is 'went'.",
     "'Goed' yanlış. 'Go' geçmişi 'went'."),
    (re.compile(r"\bi go yesterday\b", re.I), "I went yesterday.", "past_tense",
     "Use past tense for yesterday.", "Dün için geçmiş zaman."),
    (re.compile(r"\bi swim in the sea\b", re.I), "I swam in the sea.", "past_tense",
     "Past of 'swim' is 'swam'.", "'Swim' geçmişi 'swam'."),
    (re.compile(r"\bin fine you\b", re.I), "I'm fine, thank you. And you?", "be_verb",
     "Say 'I'm fine, thank you.'", "'I'm fine, thank you' de."),
    (re.compile(r"\bwhat is you name\b", re.I), "What is your name?", "possessive",
     "Use 'your' not 'you'.", "'You' değil 'your'."),
    (re.compile(r"\bhow was ver\b", re.I), "How was your vacation?", "question",
     "Use 'your vacation'.", "'Your vacation' kullan."),
]

FOLLOWUPS = {
    "en": [
        "That's interesting! Tell me more.",
        "Oh really? What happened next?",
        "I see. Why do you think that?",
        "Nice! How did that make you feel?",
        "Got it. What are you planning for tomorrow?",
        "Sounds good. What did you do after that?",
    ],
}

SPECIAL_TR = re.compile(
    r"(türkçe\s+açıkla|anlamadım|tekrar(?:\s+et|\s+söyle)?|repeat|speak\s+slowly|yavaş\s+konuş|slow)",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_profile(lang: str = "en") -> dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "targetLang": lang,
        "currentLevel": "A1",
        "targetLevel": "B1",
        "grammarErrors": [],
        "vocabularyWeaknesses": [],
        "repeatedMistakes": [],
        "masteredTopics": [],
        "weakAreas": [],
        "strongAreas": [],
        "sessions": [],
        "dailyGoalMinutes": 10,
        "todayMinutes": 0,
        "todayDate": today,
        "totalSentences": 0,
        "correctSentences": 0,
        "totalCorrections": 0,
        "newWords": [],
        "lastTeacherText": "",
        "waitingForUser": True,
        "sessionStartAt": None,
        "lastSessionDate": None,
    }


def merge_profile(profile: dict | None, delta: dict | None) -> dict:
    base = default_profile()
    if profile:
        base.update({k: v for k, v in profile.items() if v is not None})
    if not delta:
        return base
    for key in ("grammarErrors", "repeatedMistakes", "weakAreas", "strongAreas", "newWords", "sessions"):
        if key in delta and isinstance(delta[key], list):
            base[key] = delta[key]
    for key in (
        "currentLevel", "todayMinutes", "totalSentences", "correctSentences",
        "totalCorrections", "lastTeacherText", "waitingForUser", "targetLang",
        "todayDate", "sessionStartAt", "lastSessionDate",
    ):
        if key in delta:
            base[key] = delta[key]
    return base


def reset_daily_if_needed(profile: dict) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if profile.get("todayDate") != today:
        profile["todayDate"] = today
        profile["todayMinutes"] = 0
    return profile


def estimate_level(profile: dict) -> str:
    total = profile.get("totalSentences", 0) or 1
    correct = profile.get("correctSentences", 0)
    ratio = correct / total
    errors = len(profile.get("grammarErrors", []))
    if total < 5:
        return "A1"
    if ratio > 0.85 and errors < 3 and total > 30:
        return "B1"
    if ratio > 0.75 and total > 15:
        return "A2"
    if ratio > 0.6:
        return "A2"
    return "A1"


def _record_mistake(profile: dict, wrong: str, correct: str, category: str) -> dict:
    errors = list(profile.get("grammarErrors", []))
    found = None
    for e in errors:
        if e.get("category") == category and e.get("correct") == correct:
            found = e
            break
    if found:
        found["mistakeCount"] = found.get("mistakeCount", 0) + 1
        found["lastAt"] = _now_iso()
        found["mastery"] = max(0, found.get("mastery", 0) - 10)
    else:
        errors.append({
            "mistake": wrong[:120], "correct": correct, "category": category,
            "mistakeCount": 1, "lastAt": _now_iso(), "mastery": 0,
        })
    weak = list(set(profile.get("weakAreas", []) + [category]))
    return {"grammarErrors": errors[-50:], "weakAreas": weak[:12]}


def check_english(text: str) -> tuple[int, str | None, str | None, str | None, str | None]:
    """Returns (level 1-3, correct, category, explain_en, explain_tr). Level 1 = OK."""
    t = text.strip()
    if len(t) < 2:
        return 3, None, None, None, None
    for pat, correct, cat, ex_en, ex_tr in EN_RULES:
        if pat.search(t):
            if _norm(t) == _norm(correct):
                return 1, None, None, None, None
            return 3, correct, cat, ex_en, ex_tr
    if re.search(r"\b(goed|go yesterday|am go|is you|in fine you)\b", t, re.I):
        return 3, None, "grammar", "Let's fix the grammar.", "Gramer hatası var."
    if len(t.split()) >= 3 and not re.search(r"\b(is|are|am|was|were|have|has|do|does|did|will|can)\b", t, re.I):
        if re.search(r"\b(tired|happy|sad|good|bad|busy|ready)\b", t, re.I):
            return 2, None, "be_verb", "Remember to use 'am/is/are' with adjectives.", None
    return 1, None, None, None, None


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s']", "", s.lower()).strip()


def _llm(messages: list[dict], target_lang: str, level: str, roleplay: str | None = None) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    sys = SYSTEM_PROMPT + f"\nTarget language: {LANG_NAMES.get(target_lang, target_lang)}. User level: {level}."
    if roleplay and roleplay in ROLEPLAYS:
        rp = ROLEPLAYS[roleplay].get(target_lang) or ROLEPLAYS[roleplay].get("en", "")
        if rp:
            sys += f"\nRoleplay scenario: {rp}"
    weak = []
    body = json.dumps({
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [{"role": "system", "content": sys}] + messages,
        "temperature": 0.65,
        "max_tokens": 280,
    }).encode()
    try:
        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _fallback_reply(
    user_text: str, lang: str, history: list[dict], profile: dict,
    roleplay: str | None, correction: tuple | None,
) -> str:
    if correction and correction[0] >= 2:
        correct, ex_en = correction[1], correction[3]
        if correct:
            parts = [f"Almost! A more natural sentence is:\n'{correct}'"]
            if ex_en:
                parts.append(ex_en)
            if correction[0] >= 3:
                parts.append("Now you try, then we'll continue.")
            else:
                parts.append("So, what else happened?")
            return "\n\n".join(parts)

    ul = user_text.lower()
    if re.search(r"\b(hello|hi|hey|good morning|good evening)\b", ul):
        return "Hello! I'm good, thank you. How are you today?"
    if re.search(r"\b(how are you|how're you)\b", ul):
        return "I'm doing well, thank you! How about you?"
    if re.search(r"\b(i'?m|i am) (fine|good|ok|well|great)\b", ul):
        return "That's great to hear! What did you do today?"
    if re.search(r"\b(tired|exhausted|busy)\b", ul):
        return "I understand. Why do you feel tired today?"
    if re.search(r"\b(work|office|job)\b", ul):
        return "Work can be demanding. What do you do at work?"
    if re.search(r"\b(yesterday|last week|last weekend)\b", ul):
        return "Interesting! Can you tell me more about that?"
    if re.search(r"\b(antalya|istanbul|london|paris|travel|trip|vacation|holiday)\b", ul):
        return "That sounds wonderful! What did you enjoy most there?"

    # Spaced repetition: weak area prompts
    weak = profile.get("weakAreas") or []
    if "past_tense" in weak:
        return "By the way — what did you do yesterday?"
    if "be_verb" in weak:
        return "How are you feeling right now?"

    import random
    pool = FOLLOWUPS.get(lang, FOLLOWUPS["en"])
    return random.choice(pool)


def _help_mode(
    user_text: str, target_lang: str, translate_fn: Callable[[str, str, str], str],
) -> dict[str, Any]:
    from tutor import _extract_turkish_phrase

    phrase_tr = _extract_turkish_phrase(user_text)
    translated = translate_fn(phrase_tr, "tr", target_lang)
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    teacher = f"Try saying: \"{translated}\""
    explain = f"🇹🇷 \"{phrase_tr}\" → {lang_name}: \"{translated}\""
    return {
        "type": "help",
        "user_text": user_text,
        "teacher_text": teacher,
        "explain_tr": explain,
        "correction": translated,
        "correction_level": 1,
        "speak_text": translated,
        "waiting_for_user": True,
    }


def greeting(lang: str, profile: dict | None = None) -> dict[str, Any]:
    import random
    profile = merge_profile(profile, None)
    profile = reset_daily_if_needed(profile)
    opts = GREETINGS.get(lang, GREETINGS["en"])
    text = random.choice(opts)
    delta = {"lastTeacherText": text, "waitingForUser": True, "sessionStartAt": _now_iso()}
    return _pack(profile, delta, text, None, None, 1, "greeting", waiting=True)


def process_turn(
    user_text: str,
    user_lang: str,
    target_lang: str,
    history: list[dict],
    profile: dict | None,
    roleplay: str | None = None,
    speak_slow: bool = False,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    profile = merge_profile(profile, None)
    profile = reset_daily_if_needed(profile)
    user_text = user_text.strip()
    session_delta: dict[str, Any] = {
        "totalSentences": profile.get("totalSentences", 0) + (1 if user_text else 0),
    }

    last_teacher = profile.get("lastTeacherText") or ""
    if not user_text:
        return greeting(target_lang, profile)

    if SPECIAL_TR.search(user_text):
        low = user_text.lower()
        if re.search(r"türkçe|anlamadım", low):
            tr = f"Son cümlem: \"{last_teacher}\"\nPratik için tekrar deneyebilirsin."
            return _pack(profile, session_delta, last_teacher, tr, None, 1, "explain_tr", waiting=True, user_text=user_text)
        if re.search(r"repeat|tekrar", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "repeat", waiting=True, user_text=user_text)
        if re.search(r"slow|yavaş", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "slow", waiting=True, user_text=user_text, speak_slow=True)

    # Teaching help mode — only when clearly asking how to say something in Turkish
    if translate_fn and (user_lang == "tr" or HELP_RE.search(user_text)):
        help_result = _help_mode(user_text, target_lang, translate_fn)
        p = merge_profile(profile, session_delta)
        p["lastTeacherText"] = help_result["speak_text"]
        help_result["profile"] = p
        help_result["current_level"] = p.get("currentLevel", "A1")
        help_result["target_lang"] = target_lang
        help_result["user_lang"] = user_lang
        return help_result

    correction_level = 1
    correct_phrase = None
    category = None
    explain_en = None
    explain_tr = None
    profile_patch: dict = {}

    if target_lang == "en":
        correction_level, correct_phrase, category, explain_en, explain_tr = check_english(user_text)
    if correction_level >= 2 and correct_phrase:
        profile_patch = _record_mistake(profile, user_text, correct_phrase, category or "grammar")
        session_delta["totalCorrections"] = profile.get("totalCorrections", 0) + 1
    elif correction_level == 1:
        session_delta["correctSentences"] = profile.get("correctSentences", 0) + 1

    merged = merge_profile(profile, {**session_delta, **profile_patch})
    merged["currentLevel"] = estimate_level(merged)

    corr_tuple = (correction_level, correct_phrase, category, explain_en, explain_tr) if correction_level >= 2 else None

    llm_msgs = []
    for h in history[-12:]:
        role = "assistant" if h.get("role") == "teacher" else "user"
        llm_msgs.append({"role": role, "content": h.get("text", "")})
    llm_msgs.append({"role": "user", "content": user_text})

    teacher = _llm(llm_msgs, target_lang, merged["currentLevel"], roleplay)
    if not teacher:
        teacher = _fallback_reply(user_text, target_lang, history, merged, roleplay, corr_tuple)

    explain = None
    if correction_level >= 2 and explain_tr:
        explain = explain_tr
    elif correction_level >= 2 and explain_en:
        explain = explain_en

    return _pack(
        merged, session_delta, teacher, explain, correct_phrase, correction_level,
        "correction" if correction_level >= 2 else "conversation",
        waiting=True, user_text=user_text, speak_slow=speak_slow,
    )


def _pack(
    profile: dict, delta: dict, teacher: str, explain_tr: str | None,
    correction: str | None, corr_level: int, msg_type: str,
    waiting: bool = True, user_text: str = "", speak_slow: bool = False,
) -> dict:
    p = merge_profile(profile, delta)
    p["lastTeacherText"] = teacher
    p["waitingForUser"] = waiting
    speak = correction if corr_level >= 3 and correction else teacher
    return {
        "type": msg_type,
        "user_text": user_text,
        "user_lang": profile.get("targetLang", "en"),
        "teacher_text": teacher,
        "robot_tr": explain_tr or "",
        "robot_target": teacher,
        "explain_tr": explain_tr,
        "correction": correction,
        "correction_level": corr_level,
        "target_lang": profile.get("targetLang", "en"),
        "current_level": p.get("currentLevel", "A1"),
        "profile": p,
        "waiting_for_user": waiting,
        "speak_text": speak,
        "speak_slow": speak_slow,
    }


def session_report(profile: dict, minutes: float) -> dict:
    total = max(profile.get("totalSentences", 0), 1)
    correct = profile.get("correctSentences", 0)
    return {
        "speakingMinutes": round(minutes, 1),
        "sentences": total,
        "correctSentences": correct,
        "corrections": profile.get("totalCorrections", 0),
        "newWords": len(profile.get("newWords", [])),
        "grammarScore": min(100, int(100 * correct / total)),
        "vocabularyScore": min(100, 50 + len(profile.get("newWords", [])) * 5),
        "fluencyScore": min(100, int(60 + minutes * 2)),
        "estimatedLevel": profile.get("currentLevel", "A1"),
        "weakAreas": profile.get("weakAreas", [])[:5],
        "strongAreas": profile.get("strongAreas", []) or ["Basic conversation"],
    }


def daily_lesson(profile: dict) -> dict:
    level = profile.get("currentLevel", "A1")
    weak = (profile.get("weakAreas") or ["conversation"])[0]
    topics = TOPICS_BY_LEVEL.get(level, TOPICS_BY_LEVEL["A1"])
    import random
    topic = random.choice(topics)
    return {
        "mainWeakness": weak.replace("_", " ").title(),
        "vocabulary": topic.title(),
        "conversation": topic,
        "practiceMinutes": profile.get("dailyGoalMinutes", 10),
        "estimatedLevel": level,
    }
