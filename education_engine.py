"""Profesyonel dil eğitimi motoru — doğal konuşma, SRS, profil, kelime."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen

LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "ru": "Russian", "ka": "Georgian", "it": "Italian", "ar": "Arabic", "zh": "Chinese",
}

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
SRS_INTERVALS_DAYS = [1, 3, 7, 14, 30]

SYSTEM_PROMPT = """You are a professional personal language tutor for a Turkish-speaking student.
Speak primarily in the TARGET LANGUAGE (English etc.) for natural conversation.
The student's native language is Turkish — provide Turkish explanations for errors and grammar.
Do not behave like a translation app during conversation.
Maintain natural conversation and drive it forward with follow-up questions.
Adapt to the user's level. Correct important mistakes clearly.
When correcting: show wrong sentence, correct sentence, brief Turkish explanation, then continue.
Behave like a patient human teacher sitting across from the student.
Keep target-language responses concise (2-4 sentences). Always end with a question when appropriate.
Wait for the user to respond — do not answer your own questions."""

GREETINGS_TR = [
    "Merhaba! Ben senin robot öğretmeninim. Hadi birlikte konuşalım — sen konuş, ben dinlerim ve hatalarını Türkçe açıklarım.",
    "Selam! Bugün hedef dilde pratik yapalım. Yanlış yaparsan endişelenme, birlikte düzeltiriz.",
    "Hoş geldin! Karşımda bir öğrenci varmış gibi sohbet edeceğiz. Hazır mısın?",
]

CONVERSATION_TR = [
    "Güzel, devam et!",
    "Anladım, anlat bakalım.",
    "Harika, dinliyorum.",
    "Çok iyi gidiyorsun!",
]

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

# category -> review prompts for spaced repetition
SRS_PROMPTS: dict[str, list[str]] = {
    "past_tense": [
        "What did you do yesterday?",
        "What did you eat last night?",
        "Where did you go last weekend?",
        "Tell me about something you did last week.",
    ],
    "be_verb": [
        "How are you feeling right now?",
        "How was your day today?",
        "Are you busy this week?",
    ],
    "present_continuous": [
        "What are you doing now?",
        "What are you working on these days?",
    ],
    "question": [
        "Can you ask me about my hobbies?",
        "Ask me where I'm from.",
    ],
    "possessive": [
        "Tell me about your family.",
        "Describe your job.",
    ],
}

VOCAB_LIBRARY: dict[str, list[dict[str, str]]] = {
    "A1": [
        {"word": "tired", "meaningTr": "yorgun", "example": "I am tired today."},
        {"word": "happy", "meaningTr": "mutlu", "example": "I feel happy."},
    ],
    "A2": [
        {"word": "exhausted", "meaningTr": "çok yorgun, bitkin", "example": "I was exhausted after work."},
        {"word": "delicious", "meaningTr": "lezzetli", "example": "The food was delicious."},
        {"word": "comfortable", "meaningTr": "rahat", "example": "This chair is comfortable."},
    ],
    "B1": [
        {"word": "overwhelmed", "meaningTr": "bunalmış", "example": "I felt overwhelmed at work."},
        {"word": "remarkable", "meaningTr": "dikkat çekici", "example": "That was a remarkable trip."},
        {"word": "negotiate", "meaningTr": "müzakere etmek", "example": "We need to negotiate the price."},
    ],
    "B2": [
        {"word": "sustainable", "meaningTr": "sürdürülebilir", "example": "We need sustainable solutions."},
        {"word": "ambiguous", "meaningTr": "belirsiz", "example": "The answer was ambiguous."},
    ],
}

HELP_RE = re.compile(
    r"(nasıl\s+(?:söylerim|derim|denir)|ingilizcede|ne\s+demek|çevirir\s+misin|"
    r"how\s+do\s+i\s+say|what\s+is\s+.+\s+in\s+english)",
    re.I,
)

BREAKDOWN_RE = re.compile(
    r"(cümle\s+yapısı|break\s+down|gramer\s+açıkla|explain\s+(?:the\s+)?grammar|"
    r"neden\s+böyle|why\s+this\s+way|yapısını\s+açıkla)",
    re.I,
)

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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_add(days: int) -> str:
    d = datetime.now(timezone.utc).date() + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def default_profile(lang: str = "en") -> dict[str, Any]:
    today = _today()
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
        "srsItems": [],
        "vocabularyBank": [],
        "dailyStats": [],
        "sessionLog": [],
        "sessions": [],
        "dailyGoalMinutes": 10,
        "todayMinutes": 0,
        "todayDate": today,
        "totalSentences": 0,
        "correctSentences": 0,
        "totalCorrections": 0,
        "sessionCorrections": 0,
        "yesterdayCorrections": 0,
        "newWords": [],
        "lastTeacherText": "",
        "waitingForUser": True,
        "sessionStartAt": None,
        "lastSessionDate": None,
        "pendingSrsId": None,
        "pendingVocabWord": None,
    }


def merge_profile(profile: dict | None, delta: dict | None) -> dict:
    base = default_profile()
    if profile:
        base.update({k: v for k, v in profile.items() if v is not None})
    if not delta:
        return base
    list_keys = (
        "grammarErrors", "repeatedMistakes", "weakAreas", "strongAreas", "newWords",
        "sessions", "srsItems", "vocabularyBank", "dailyStats", "sessionLog",
    )
    for key in list_keys:
        if key in delta and isinstance(delta[key], list):
            base[key] = delta[key]
    scalar_keys = (
        "currentLevel", "todayMinutes", "totalSentences", "correctSentences",
        "totalCorrections", "sessionCorrections", "yesterdayCorrections",
        "lastTeacherText", "waitingForUser", "targetLang", "todayDate",
        "sessionStartAt", "lastSessionDate", "pendingSrsId", "pendingVocabWord",
    )
    for key in scalar_keys:
        if key in delta:
            base[key] = delta[key]
    return base


def reset_daily_if_needed(profile: dict) -> dict:
    today = _today()
    if profile.get("todayDate") != today:
        profile["yesterdayCorrections"] = profile.get("sessionCorrections", 0) or profile.get("totalCorrections", 0)
        profile["todayDate"] = today
        profile["todayMinutes"] = 0
        profile["sessionCorrections"] = 0
    return profile


def estimate_level(profile: dict) -> str:
    total = profile.get("totalSentences", 0) or 1
    correct = profile.get("correctSentences", 0)
    ratio = correct / total
    errors = len(profile.get("grammarErrors", []))
    if total < 5:
        return "A1"
    if ratio > 0.88 and errors < 2 and total > 40:
        return "B2"
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
    srs_patch = sync_srs_from_mistake(profile, category, correct, wrong)
    return {"grammarErrors": errors[-50:], "weakAreas": weak[:12], **srs_patch}


def sync_srs_from_mistake(profile: dict, category: str, correct: str, wrong: str) -> dict:
    items = list(profile.get("srsItems", []))
    item_id = f"{category}_{hash(correct) % 10000}"
    found = next((i for i in items if i.get("id") == item_id), None)
    import random
    prompts = SRS_PROMPTS.get(category, ["Tell me more about that."])
    if found:
        found["mistakeCount"] = found.get("mistakeCount", 0) + 1
        found["mastery"] = max(0, found.get("mastery", 0) - 15)
        found["nextReviewAt"] = _today()
    else:
        items.append({
            "id": item_id,
            "type": "grammar",
            "category": category,
            "prompt": random.choice(prompts),
            "targetAnswer": correct,
            "intervalIndex": 0,
            "nextReviewAt": _date_add(1),
            "mastery": 0,
            "reviewCount": 0,
            "lastReviewAt": None,
            "mistakeCount": 1,
        })
    return {"srsItems": items[-40:]}


def get_due_srs(profile: dict) -> list[dict]:
    today = _today()
    items = profile.get("srsItems", [])
    due = [i for i in items if i.get("nextReviewAt", "") <= today and i.get("mastery", 0) < 80]
    due.sort(key=lambda x: (x.get("mastery", 0), x.get("mistakeCount", 0)), reverse=True)
    return due[:3]


def get_due_vocab(profile: dict) -> list[dict]:
    today = _today()
    bank = profile.get("vocabularyBank", [])
    return [v for v in bank if v.get("nextReviewAt", "") <= today and v.get("mastery", 0) < 85]


def record_srs_success(profile: dict, item_id: str) -> dict:
    items = list(profile.get("srsItems", []))
    for item in items:
        if item.get("id") != item_id:
            continue
        idx = min(item.get("intervalIndex", 0) + 1, len(SRS_INTERVALS_DAYS) - 1)
        item["intervalIndex"] = idx
        item["nextReviewAt"] = _date_add(SRS_INTERVALS_DAYS[idx])
        item["mastery"] = min(100, item.get("mastery", 0) + 20)
        item["reviewCount"] = item.get("reviewCount", 0) + 1
        item["lastReviewAt"] = _now_iso()
        if item["mastery"] >= 80:
            mastered = list(set(profile.get("masteredTopics", []) + [item.get("category", "")]))
            return {"srsItems": items, "masteredTopics": mastered[:20], "pendingSrsId": None}
    return {"srsItems": items, "pendingSrsId": None}


def record_srs_failure(profile: dict, item_id: str) -> dict:
    items = list(profile.get("srsItems", []))
    for item in items:
        if item.get("id") != item_id:
            continue
        item["intervalIndex"] = 0
        item["nextReviewAt"] = _date_add(1)
        item["mastery"] = max(0, item.get("mastery", 0) - 10)
        item["lastReviewAt"] = _now_iso()
    return {"srsItems": items, "pendingSrsId": item_id}


def pick_srs_prompt(profile: dict) -> tuple[str | None, str | None]:
    due = get_due_srs(profile)
    if not due:
        return None, None
    item = due[0]
    return item.get("prompt"), item.get("id")


def suggest_new_vocab(profile: dict, user_text: str) -> dict | None:
    level = profile.get("currentLevel", "A1")
    bank = {v.get("word", "").lower() for v in profile.get("vocabularyBank", [])}
    ul = user_text.lower()
    if re.search(r"\b(tired|yorgun|exhausted|busy)\b", ul):
        candidates = VOCAB_LIBRARY.get("A2", []) + VOCAB_LIBRARY.get("B1", [])
        for c in candidates:
            if c["word"].lower() not in bank and c["word"].lower() not in ul:
                return c
    pool = VOCAB_LIBRARY.get(level, []) + VOCAB_LIBRARY.get("A2", [])
    for c in pool:
        if c["word"].lower() not in bank:
            return c
    return None


def add_vocab_to_bank(profile: dict, entry: dict) -> dict:
    bank = list(profile.get("vocabularyBank", []))
    word = entry.get("word", "")
    if any(v.get("word", "").lower() == word.lower() for v in bank):
        return {}
    bank.append({
        "word": word,
        "meaningTr": entry.get("meaningTr", ""),
        "example": entry.get("example", ""),
        "introducedAt": _now_iso(),
        "nextReviewAt": _date_add(1),
        "intervalIndex": 0,
        "mastery": 0,
        "usedCorrectly": False,
    })
    new_words = list(profile.get("newWords", []))
    if word not in new_words:
        new_words.append(word)
    return {"vocabularyBank": bank[-60:], "newWords": new_words[-40:]}


def record_vocab_used(profile: dict, word: str, correct: bool) -> dict:
    bank = list(profile.get("vocabularyBank", []))
    for v in bank:
        if v.get("word", "").lower() != word.lower():
            continue
        if correct:
            idx = min(v.get("intervalIndex", 0) + 1, len(SRS_INTERVALS_DAYS) - 1)
            v["intervalIndex"] = idx
            v["nextReviewAt"] = _date_add(SRS_INTERVALS_DAYS[idx])
            v["mastery"] = min(100, v.get("mastery", 0) + 25)
            v["usedCorrectly"] = True
        else:
            v["intervalIndex"] = 0
            v["nextReviewAt"] = _date_add(1)
            v["mastery"] = max(0, v.get("mastery", 0) - 10)
        return {"vocabularyBank": bank, "pendingVocabWord": None}
    return {}


def check_english(text: str) -> tuple[int, str | None, str | None, str | None, str | None]:
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


def grammar_breakdown(sentence: str, level: str) -> str:
    s = sentence.strip()
    if not s:
        return "No sentence to explain."
    if re.search(r"\bhave been \w+ing\b", s, re.I):
        if level in ("A1", "A2"):
            return (
                f"Cümle: \"{s}\"\n\n"
                "have been + fiil-ing = geçmişte başlayıp hâlâ devam eden eylem.\n"
                "Türkçe: '... yapmaktayım / yapmış bulunuyorum'"
            )
        return (
            f"Let's break it down:\n\"{s}\"\n\n"
            "have been + verb-ing = present perfect continuous\n"
            "The action started in the past and continues now."
        )
    if re.search(r"\b(went|swam|did|ate)\b", s, re.I):
        return (
            f"Cümle: \"{s}\"\n\n"
            "Geçmiş zaman (past simple) kullanılmış.\n"
            "Düzensiz fiillerde V2 formu gerekir (go→went, swim→swam)."
        )
    if re.search(r"\b(I'm|I am|he is|she is|they are)\b", s, re.I):
        return (
            f"Cümle: \"{s}\"\n\n"
            "am/is/are + sıfat veya isim = durum bildirme.\n"
            "Örnek: I'm tired = Yorgunum."
        )
    words = s.split()
    if level in ("A1", "A2"):
        return f"Cümle: \"{s}\"\n\nBasit yapı: özne + fiil + (nesne/zarf)."
    return f"Sentence: \"{s}\"\n\nSubject + verb + complements. Ask me about a specific part."


def motivation_message(profile: dict) -> str | None:
    yesterday = profile.get("yesterdayCorrections", 0)
    today = profile.get("sessionCorrections", 0)
    if yesterday > 0 and today < yesterday:
        diff = yesterday - today
        return f"Yesterday you made {yesterday} grammar mistakes. Today only {today}. Great improvement!"
    mastered = profile.get("masteredTopics", [])
    if mastered and profile.get("totalSentences", 0) > 10:
        topic = mastered[-1].replace("_", " ")
        return f"You've been doing well with {topic} lately. Keep it up!"
    return None


def _llm(messages: list[dict], target_lang: str, level: str, roleplay: str | None = None,
           extra: str = "") -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    sys = SYSTEM_PROMPT + f"\nTarget language: {LANG_NAMES.get(target_lang, target_lang)}. User level: {level}."
    if roleplay and roleplay in ROLEPLAYS:
        rp = ROLEPLAYS[roleplay].get(target_lang) or ROLEPLAYS[roleplay].get("en", "")
        if rp:
            sys += f"\nRoleplay scenario: {rp}"
    if extra:
        sys += f"\n{extra}"
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
    srs_prompt: str | None = None,
    vocab_hint: dict | None = None,
) -> str:
    if correction and correction[0] >= 2:
        correct, ex_en = correction[1], correction[3]
        if correct:
            parts = [f"Almost! A more natural sentence is:\n'{correct}'"]
            if ex_en:
                parts.append(ex_en)
            if correction[0] >= 3:
                parts.append("Now you try saying it correctly, then we'll keep chatting.")
            else:
                parts.append("So, tell me more — what happened?")
            return "\n\n".join(parts)

    ul = user_text.lower()
    if re.search(r"\b(hello|hi|hey|good morning|good evening|merhaba|selam)\b", ul):
        return "Hello! I'm glad we're chatting. How are you today?"
    if re.search(r"\b(how are you|how're you|nasılsın|nasilsin)\b", ul):
        return "I'm doing well, thank you! How about you? What's new?"
    if re.search(r"\b(i'?m|i am) (fine|good|ok|well|great)\b", ul):
        return "That's great to hear! What did you do today?"
    if re.search(r"\b(tired|exhausted|busy|yorgun)\b", ul):
        if vocab_hint and vocab_hint.get("word", "").lower() not in ul:
            w = vocab_hint["word"]
            return (
                f"I understand — that sounds tough. Try a stronger word next time: '{w}'. "
                f"Why do you feel tired today?"
            )
        return "I understand. That sounds tough. Why do you feel tired today?"
    if re.search(r"\b(work|office|job)\b", ul):
        return "Work can be demanding. What do you do at work? Tell me about your day."
    if re.search(r"\b(yesterday|last week|last weekend)\b", ul):
        return "Interesting! Can you tell me more about that?"
    if re.search(r"\b(antalya|istanbul|london|paris|travel|trip|vacation|holiday)\b", ul):
        return "That sounds wonderful! What did you enjoy most there?"

    if srs_prompt:
        return srs_prompt

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
    teacher_en = f"Try saying: \"{translated}\""
    explain = f"🇹🇷 \"{phrase_tr}\"\n\n🇬🇧 {lang_name}: \"{translated}\"\n\nTekrar et ve birlikte çalışalım."
    return {
        "type": "help",
        "user_text": user_text,
        "teacher_text": explain,
        "teacher_en": translated,
        "teacher_tr": f"Türkçe: \"{phrase_tr}\"\n{lang_name}: \"{translated}\"",
        "explain_tr": explain,
        "correction": translated,
        "correction_level": 1,
        "speak_text": translated,
        "waiting_for_user": True,
    }


def _turkish_to_practice(
    user_text: str, target_lang: str, profile: dict, session_delta: dict,
    translate_fn: Callable[[str, str, str], str],
) -> dict[str, Any]:
    """Türkçe konuşuldu — çeviri uygulaması gibi davranma, İngilizce pratik yaptır."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    en_phrase = translate_fn(user_text, "tr", target_lang)
    teacher_tr = (
        f"Anladım! 🇹🇷 \"{user_text}\"\n\n"
        f"Bunu {lang_name} denemek için:\n\"{en_phrase}\"\n\n"
        f"Şimdi sen {lang_name} söyle — dinliyorum!"
    )
    teacher_en = (
        f"I understand what you mean!\n"
        f"In English, try saying:\n\"{en_phrase}\"\n\n"
        f"Now you say it in English — I'm listening!"
    )
    display = f"{teacher_tr}\n\n———\n{teacher_en}"
    delta = {**session_delta, "lastTeacherText": en_phrase}
    return _pack(
        profile, delta, display, teacher_tr, en_phrase, 1, "coach_tr",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=en_phrase,
    )


def _build_correction_tr(
    user_text: str, correct: str | None, explain_tr: str | None, explain_en: str | None,
    corr_level: int,
) -> str:
    parts = []
    if corr_level >= 2:
        parts.append(f"❌ Senin cümlen:\n\"{user_text}\"")
        if correct:
            parts.append(f"✅ Doğrusu (İngilizce):\n\"{correct}\"")
        if explain_tr:
            parts.append(f"💡 Türkçe açıklama:\n{explain_tr}")
        elif explain_en:
            parts.append(f"💡 Açıklama:\n{explain_en}")
        if corr_level >= 3:
            parts.append("🔄 Şimdi sen dene — doğru cümleyi söyle, sonra devam ederiz.")
    return "\n\n".join(parts)


def _conversation_tr_hint() -> str:
    import random
    return random.choice(CONVERSATION_TR)


def greeting(lang: str, profile: dict | None = None) -> dict[str, Any]:
    import random
    profile = merge_profile(profile, None)
    profile = reset_daily_if_needed(profile)
    text_en = random.choice(GREETINGS.get(lang, GREETINGS["en"]))
    text_tr = random.choice(GREETINGS_TR)
    motiv = motivation_message(profile)
    if motiv:
        text_tr = f"{motiv}\n\n{text_tr}"
    srs_prompt, srs_id = pick_srs_prompt(profile)
    if srs_prompt:
        text_en = f"{text_en}\n\n{srs_prompt}"
    teacher_en = text_en
    teacher_tr = text_tr
    display = f"{text_tr}\n\n———\n🇬🇧 {text_en}" if lang == "en" else f"{text_tr}\n\n———\n{text_en}"
    delta = {
        "lastTeacherText": text_en,
        "waitingForUser": True,
        "sessionStartAt": _now_iso(),
        "pendingSrsId": srs_id,
    }
    result = _pack(
        profile, delta, display, text_tr, None, 1, "greeting",
        waiting=True, teacher_en=teacher_en, speak_text=text_en,
    )
    result["daily_lesson"] = daily_lesson(profile)
    result["motivation"] = motiv
    result["weekly_progress"] = weekly_progress(profile)
    return result


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
            tr = (
                f"🇹🇷 Son İngilizce cümlem:\n\"{last_teacher}\"\n\n"
                f"Anlamadıysan tekrar sorabilir veya 'tekrar et' diyebilirsin."
            )
            return _pack(
                profile, session_delta, f"{last_teacher}\n\n———\n{tr}", tr,
                None, 1, "explain_tr", waiting=True, user_text=user_text, teacher_en=last_teacher,
            )
        if re.search(r"repeat|tekrar", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "repeat", waiting=True, user_text=user_text)
        if re.search(r"slow|yavaş", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "slow", waiting=True, user_text=user_text, speak_slow=True)

    if BREAKDOWN_RE.search(user_text):
        breakdown = grammar_breakdown(last_teacher, profile.get("currentLevel", "A1"))
        return _pack(profile, session_delta, breakdown, breakdown, None, 1, "breakdown", waiting=True, user_text=user_text)

    # Yalnızca açık yardım isteğinde çeviri modu (Türkçe konuşmak ≠ çeviri)
    if translate_fn and HELP_RE.search(user_text):
        help_result = _help_mode(user_text, target_lang, translate_fn)
        p = merge_profile(profile, session_delta)
        p["lastTeacherText"] = help_result["speak_text"]
        help_result["profile"] = p
        help_result["current_level"] = p.get("currentLevel", "A1")
        help_result["target_lang"] = target_lang
        help_result["user_lang"] = user_lang
        return help_result

    # Kullanıcı Türkçe konuştu — çevirme, öğret ve İngilizceye yönlendir
    if user_lang == "tr" and translate_fn:
        return _turkish_to_practice(user_text, target_lang, profile, session_delta, translate_fn)

    correction_level = 1
    correct_phrase = None
    category = None
    explain_en = None
    explain_tr = None
    profile_patch: dict = {}

    if target_lang == "en":
        correction_level, correct_phrase, category, explain_en, explain_tr = check_english(user_text)

    pending_srs = profile.get("pendingSrsId")
    if pending_srs:
        if correction_level == 1:
            profile_patch.update(record_srs_success(profile, pending_srs))
        elif correction_level >= 2:
            profile_patch.update(record_srs_failure(profile, pending_srs))

    pending_vocab = profile.get("pendingVocabWord")
    if pending_vocab and pending_vocab.lower() in user_text.lower():
        profile_patch.update(record_vocab_used(profile, pending_vocab, correction_level == 1))

    if correction_level >= 2 and correct_phrase:
        profile_patch.update(_record_mistake(profile, user_text, correct_phrase, category or "grammar"))
        session_delta["totalCorrections"] = profile.get("totalCorrections", 0) + 1
        session_delta["sessionCorrections"] = profile.get("sessionCorrections", 0) + 1
    elif correction_level == 1:
        session_delta["correctSentences"] = profile.get("correctSentences", 0) + 1

    merged = merge_profile(profile, {**session_delta, **profile_patch})
    merged["currentLevel"] = estimate_level(merged)

    corr_tuple = (correction_level, correct_phrase, category, explain_en, explain_tr) if correction_level >= 2 else None

    vocab_new = None
    new_word_card = None
    if correction_level == 1 and merged.get("totalSentences", 0) % 5 == 0:
        vocab_new = suggest_new_vocab(merged, user_text)
        if vocab_new:
            merged = merge_profile(merged, add_vocab_to_bank(merged, vocab_new))
            new_word_card = vocab_new

    due_vocab = get_due_vocab(merged)
    vocab_hint = due_vocab[0] if due_vocab else vocab_new

    srs_prompt, srs_id = pick_srs_prompt(merged)
    if srs_prompt and not pending_srs and correction_level == 1 and merged.get("totalSentences", 0) % 4 == 0:
        merged["pendingSrsId"] = srs_id
    else:
        srs_prompt = None

    llm_msgs = []
    for h in history[-12:]:
        role = "assistant" if h.get("role") == "teacher" else "user"
        llm_msgs.append({"role": role, "content": h.get("text", "")})
    llm_msgs.append({"role": "user", "content": user_text})

    extra = ""
    if srs_prompt:
        extra += f"End your response by naturally asking: {srs_prompt}"
    if vocab_hint and isinstance(vocab_hint, dict):
        extra += f" Try to introduce the word '{vocab_hint.get('word')}' naturally."

    teacher = _llm(llm_msgs, target_lang, merged["currentLevel"], roleplay, extra)
    if not teacher:
        teacher = _fallback_reply(
            user_text, target_lang, history, merged, roleplay, corr_tuple,
            srs_prompt, vocab_hint if isinstance(vocab_hint, dict) else None,
        )

    explain = None
    correction_tr_block = None
    if correction_level >= 2:
        correction_tr_block = _build_correction_tr(
            user_text, correct_phrase, explain_tr, explain_en, correction_level,
        )
        explain = correction_tr_block

    teacher_en = teacher
    teacher_tr = correction_tr_block or _conversation_tr_hint()
    if correction_level == 1 and not correction_tr_block:
        teacher_tr = f"{_conversation_tr_hint()}\n(Hedef dilde sohbet ediyoruz — devam et!)"

    display_teacher = teacher_en
    if correction_tr_block:
        display_teacher = f"{teacher_en}\n\n———\n{correction_tr_block}"

    result = _pack(
        merged, session_delta, display_teacher, teacher_tr, correct_phrase, correction_level,
        "correction" if correction_level >= 2 else "conversation",
        waiting=True, user_text=user_text, speak_slow=speak_slow,
        teacher_en=teacher_en,
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct_phrase,
            "explainTr": explain_tr,
            "explainEn": explain_en,
            "category": category,
            "level": correction_level,
        } if correction_level >= 2 else None,
    )
    if new_word_card:
        result["new_word"] = {
            "word": new_word_card["word"],
            "meaningTr": new_word_card.get("meaningTr", ""),
            "example": new_word_card.get("example", ""),
        }
        result["explain_tr"] = (
            (result.get("explain_tr") or "")
            + f"\n\n📚 Yeni kelime: {new_word_card['word']} = {new_word_card.get('meaningTr', '')}"
            + f"\nÖrnek: \"{new_word_card.get('example', '')}\""
        ).strip()
        merged["pendingVocabWord"] = new_word_card["word"]
        result["profile"] = merge_profile(merged, {"pendingVocabWord": new_word_card["word"]})
    result["weekly_progress"] = weekly_progress(result["profile"])
    return result


def _pack(
    profile: dict, delta: dict, teacher: str, explain_tr: str | None,
    correction: str | None, corr_level: int, msg_type: str,
    waiting: bool = True, user_text: str = "", speak_slow: bool = False,
    teacher_en: str | None = None, speak_text: str | None = None,
    correction_detail: dict | None = None,
) -> dict:
    p = merge_profile(profile, delta)
    en = teacher_en or teacher
    p["lastTeacherText"] = en
    p["waitingForUser"] = waiting
    speak = speak_text or (correction if corr_level >= 3 and correction else en)
    return {
        "type": msg_type,
        "user_text": user_text,
        "user_lang": profile.get("targetLang", "en"),
        "teacher_text": teacher,
        "teacher_en": en,
        "teacher_tr": explain_tr or "",
        "robot_tr": explain_tr or "",
        "robot_target": en,
        "explain_tr": explain_tr,
        "correction": correction,
        "correction_level": corr_level,
        "correction_detail": correction_detail,
        "target_lang": profile.get("targetLang", "en"),
        "current_level": p.get("currentLevel", "A1"),
        "profile": p,
        "waiting_for_user": waiting,
        "speak_text": speak,
        "speak_slow": speak_slow,
    }


def _score_for_day(sentences: int, correct: int, minutes: float, corrections: int) -> dict:
    total = max(sentences, 1)
    grammar = min(100, int(100 * correct / total))
    vocabulary = min(100, 50 + correct // 2)
    fluency = min(100, int(40 + minutes * 3 + correct))
    return {"grammar": grammar, "vocabulary": vocabulary, "fluency": fluency}


def update_daily_stat(profile: dict, minutes: float, sentences_delta: int = 0) -> dict:
    stats = list(profile.get("dailyStats", []))
    today = _today()
    total = profile.get("totalSentences", 0)
    correct = profile.get("correctSentences", 0)
    corrections = profile.get("totalCorrections", 0)
    scores = _score_for_day(total, correct, minutes, corrections)
    entry = next((s for s in stats if s.get("date") == today), None)
    if entry:
        entry["minutes"] = round(entry.get("minutes", 0) + minutes, 1)
        entry["sentences"] = total
        entry["correct"] = correct
        entry["corrections"] = corrections
        entry["grammar"] = scores["grammar"]
        entry["vocabulary"] = scores["vocabulary"]
        entry["fluency"] = scores["fluency"]
        entry["level"] = profile.get("currentLevel", "A1")
    else:
        stats.append({
            "date": today,
            "minutes": round(minutes, 1),
            "sentences": total,
            "correct": correct,
            "corrections": corrections,
            **scores,
            "level": profile.get("currentLevel", "A1"),
        })
    stats = sorted(stats, key=lambda x: x.get("date", ""))[-14:]
    return {"dailyStats": stats}


def finalize_session(profile: dict, minutes: float, topic: str = "Daily conversation") -> dict:
    profile = merge_profile(profile, None)
    weak = (profile.get("weakAreas") or ["conversation"])[0]
    log = list(profile.get("sessionLog", []))
    log.insert(0, {
        "date": _today(),
        "minutes": round(minutes, 1),
        "level": profile.get("currentLevel", "A1"),
        "topic": topic.replace("_", " ").title(),
        "weakArea": weak,
        "sentences": profile.get("totalSentences", 0),
        "corrections": profile.get("sessionCorrections", 0),
    })
    stat_patch = update_daily_stat(profile, minutes)
    return {
        "sessionLog": log[:30],
        "lastSessionDate": _today(),
        "todayMinutes": (profile.get("todayMinutes", 0) or 0) + minutes,
        **stat_patch,
    }


def weekly_progress(profile: dict) -> dict:
    stats = profile.get("dailyStats", [])
    today = datetime.now(timezone.utc).date()
    days = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        entry = next((s for s in stats if s.get("date") == d), None)
        if entry:
            days.append(entry)
        else:
            days.append({
                "date": d, "minutes": 0, "sentences": 0, "correct": 0,
                "corrections": 0, "grammar": 0, "vocabulary": 0, "fluency": 0,
                "level": profile.get("currentLevel", "A1"),
            })
    def avg(key: str) -> int:
        vals = [d.get(key, 0) for d in days if d.get("minutes", 0) > 0 or d.get("sentences", 0) > 0]
        return int(sum(vals) / len(vals)) if vals else 0
    return {
        "days": days,
        "speaking": min(100, int(sum(d.get("minutes", 0) for d in days) / 70 * 100)),
        "grammar": avg("grammar"),
        "vocabulary": avg("vocabulary"),
        "fluency": avg("fluency"),
    }


def session_report(profile: dict, minutes: float) -> dict:
    total = max(profile.get("totalSentences", 0), 1)
    correct = profile.get("correctSentences", 0)
    scores = _score_for_day(total, correct, minutes, profile.get("totalCorrections", 0))
    strong = profile.get("strongAreas", []) or []
    if correct / total > 0.7:
        strong = list(set(strong + ["Basic conversation"]))[:5]
    return {
        "speakingMinutes": round(minutes, 1),
        "sentences": total,
        "correctSentences": correct,
        "corrections": profile.get("sessionCorrections", profile.get("totalCorrections", 0)),
        "newWords": len(profile.get("newWords", [])),
        "grammarScore": scores["grammar"],
        "vocabularyScore": scores["vocabulary"],
        "fluencyScore": scores["fluency"],
        "estimatedLevel": profile.get("currentLevel", "A1"),
        "weakAreas": profile.get("weakAreas", [])[:5],
        "strongAreas": strong or ["Willingness to speak"],
        "weeklyProgress": weekly_progress(profile),
        "motivation": motivation_message(profile),
        "srsDue": len(get_due_srs(profile)),
        "vocabDue": len(get_due_vocab(profile)),
    }


def daily_lesson(profile: dict) -> dict:
    level = profile.get("currentLevel", "A1")
    weak = (profile.get("weakAreas") or ["conversation"])[0]
    topics = TOPICS_BY_LEVEL.get(level, TOPICS_BY_LEVEL["A1"])
    import random
    topic = random.choice(topics)
    due_srs = get_due_srs(profile)
    practice = "Past tense questions" if weak == "past_tense" else weak.replace("_", " ").title()
    return {
        "mainWeakness": weak.replace("_", " ").title(),
        "vocabulary": topic.title(),
        "conversation": topic,
        "practice": practice,
        "practiceMinutes": profile.get("dailyGoalMinutes", 10),
        "estimatedLevel": level,
        "srsReviewsDue": len(due_srs),
        "vocabReviewsDue": len(get_due_vocab(profile)),
    }
