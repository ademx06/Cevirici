"""Robot öğretmen — STT + düzeltme + Türkçe yardım."""
from __future__ import annotations

import difflib
import re

LANG_NAMES = {
    "tr": "Türkçe", "en": "English", "ru": "Русский", "ka": "ქართული",
    "de": "Deutsch", "fr": "Français", "es": "Español", "ar": "العربية",
    "it": "Italiano", "zh": "中文",
}

HELP_RE = re.compile(
    r"(nasıl\s+(?:söylerim|derim|denir|diyebilirim)|"
    r"ingilizcede|i̇ngilizcede|rusçada|gürcücede|fransızca|almanca|"
    r"ne\s+demek|çevirir\s+misin|yardım|söylemek\s+istiyorum|"
    r"bana\s+yardım|bunu\s+nasıl|how\s+do\s+i\s+say)",
    re.I,
)

LESSONS = {
    "how_are_you": {
        "en": ("How are you?", "Nasılsın? sorusu — karşılık: I'm fine, thank you. And you?"),
        "ru": ("Как дела?", "Nasılsın? — Как дела? diye sorarsın."),
        "ka": ("როგორ ხარ?", "Nasılsın? — როგორ ხარ?"),
        "fr": ("Comment allez-vous ?", "Nasılsın? — Comment allez-vous ?"),
        "de": ("Wie geht es dir?", "Nasılsın? — Wie geht es dir?"),
        "es": ("¿Cómo estás?", "Nasılsın? — ¿Cómo estás?"),
    },
    "how_was_vacation": {
        "en": ("How was your vacation?", "Tatilin nasıldı? — How was your vacation?"),
        "ru": ("Как прошли каникулы?", "Tatilin nasıldı? — Как прошли каникулы?"),
        "ka": ("როგორ გაატარე შვებულება?", "Tatil — როგორ გაატარე შვებულება?"),
        "fr": ("Comment s'est passée ta/vos vacances ?", "Tatil — Comment s'est passée tes vacances ?"),
        "de": ("Wie war dein Urlaub?", "Tatil — Wie war dein Urlaub?"),
        "es": ("¿Cómo estuvieron tus vacaciones?", "Tatil — ¿Cómo estuvieron tus vacaciones?"),
    },
    "thank_you": {
        "en": ("Thank you very much.", "Teşekkürler — Thank you very much."),
        "ru": ("Большое спасибо.", "Teşekkür — Большое спасибо."),
        "ka": ("დიდი მადლობა.", "Teşekkür — დიდი მადლობა."),
        "fr": ("Merci beaucoup.", "Teşekkür — Merci beaucoup."),
        "de": ("Vielen Dank.", "Teşekkür — Vielen Dank."),
        "es": ("Muchas gracias.", "Teşekkür — Muchas gracias."),
    },
}

PHRASES: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("I'm fine, thank you. And you?", "Nasılsın sorusuna cevap"),
        ("How are you?", "Nasılsın?"),
        ("How was your vacation?", "Tatilin nasıldı?"),
        ("I'm going to school today.", "Bugün okula gideceğim"),
        ("Nice to meet you.", "Tanıştığıma memnun oldum"),
        ("What is your name?", "Adın ne?"),
        ("Where are you from?", "Nerelisin?"),
        ("I don't understand.", "Anlamıyorum"),
        ("Can you help me?", "Yardım eder misin?"),
        ("Thank you very much.", "Çok teşekkürler"),
    ],
    "ru": [
        ("Как дела?", "Nasılsın?"),
        ("Меня зовут...", "Adım ..."),
        ("Я не понимаю.", "Anlamıyorum"),
        ("Спасибо большое.", "Çok teşekkürler"),
        ("Как прошли каникулы?", "Tatilin nasıldı?"),
    ],
    "ka": [
        ("როგორ ხარ?", "Nasılsın?"),
        ("მადლობა.", "Teşekkürler"),
        ("არ გავიგე.", "Anlamıyorum"),
    ],
    "fr": [
        ("Comment allez-vous ?", "Nasılsın?"),
        ("Je ne comprends pas.", "Anlamıyorum"),
        ("Merci beaucoup.", "Çok teşekkürler"),
    ],
    "de": [
        ("Wie geht es dir?", "Nasılsın?"),
        ("Ich verstehe nicht.", "Anlamıyorum"),
        ("Vielen Dank.", "Çok teşekkürler"),
    ],
    "es": [
        ("¿Cómo estás?", "Nasılsın?"),
        ("No entiendo.", "Anlamıyorum"),
        ("Muchas gracias.", "Çok teşekkürler"),
    ],
}

CORRECTIONS: dict[str, list[tuple[re.Pattern, str, str]]] = {
    "en": [
        (re.compile(r"\bin fine you\b", re.I), "I'm fine, thank you. And you?",
         "Hayır — 'in fine you' değil. 'I'm fine, thank you' demelisin."),
        (re.compile(r"\bi'?m?\s*fine\s*you\b", re.I), "I'm fine, thank you. And you?",
         "'I'm fine, thank you. And you?' — nazik bir cevap."),
        (re.compile(r"\bhow was ver\b", re.I), "How was your vacation?",
         "'How was your vacation?' — tatil sorusu böyle kurulur."),
        (re.compile(r"\bhow is your\b", re.I), "How is your day?",
         "'How is your ...?' kalıbı — örn. 'How is your day?'"),
        (re.compile(r"\bwhat is you name\b", re.I), "What is your name?",
         "'What is your name?' — you değil your."),
    ],
    "ru": [
        (re.compile(r"\bkak dela\b", re.I), "Как дела?", "Doğru kalıp: Как дела?"),
    ],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _extract_turkish_phrase(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^\s*yardım\b[,\s!:.-]*", "", t, flags=re.I).strip()
    for pat in (
        r"(.+?)\s+kısmını\s+söyle(?:y)?emiyorum",
        r"(.+?)\s+nasıl\s+söylerim",
        r"bunu\s+nasıl\s+söylerim.*?[:\s]+(.+)",
        r"söylemek\s+istiyorum[:\s]+(.+)",
        r"demek\s+istiyorum[:\s]+(.+)",
        r"ingilizcede\s+(.+?)(?:\s+nasıl|\s*\.|$)",
        r"rusçada\s+(.+?)(?:\s+nasıl|\s*\.|$)",
        r"gürcücede\s+(.+?)(?:\s+nasıl|\s*\.|$)",
        r"fransızca(?:da|)?\s+(.+?)(?:\s+nasıl|\s*\.|$)",
        r"nasıl\s+(?:söylerim|derim|denir)[:\s]+(.+)",
        r"(?:bana\s+)?(.+?)\s+nasıl\s+(?:söylerim|derim)",
    ):
        m = re.search(pat, t, re.I)
        if m:
            phrase = m.group(1).strip(" ?.!")
            phrase = re.sub(
                r"^(?:ben\s+)?(?:şunu|bunu|onu)\s+", "", phrase, flags=re.I,
            ).strip()
            if len(phrase) > 2:
                return phrase
    cleaned = re.sub(
        r"(?:ingilizcede|rusçada|gürcücede|fransızca|almanca|nasıl\s+söylerim|"
        r"nasıl\s+derim|yardım|lütfen|bana|bir|şey|söylemek\s+istiyorum|"
        r"söyleyemiyorum|anlatır\s+mısın|bunu|şunu|kısmını)",
        " ",
        t,
        flags=re.I,
    )
    cleaned = _norm(cleaned)
    return cleaned if len(cleaned) > 2 else t


def _closest_phrase(text: str, lang: str) -> tuple[str, str] | None:
    phrases = PHRASES.get(lang, [])
    if not phrases:
        return None
    low = text.lower()
    best = None
    best_ratio = 0.0
    for phrase, hint in phrases:
        r = difflib.SequenceMatcher(None, low, phrase.lower()).ratio()
        if r > best_ratio:
            best_ratio = r
            best = (phrase, hint)
    if best and best_ratio >= 0.55 and best_ratio < 0.95:
        return best
    return None


def _check_correction(text: str, lang: str) -> tuple[str, str] | None:
    for pattern, correct, hint in CORRECTIONS.get(lang, []):
        if pattern.search(text):
            if _norm(text.lower()) == _norm(correct.lower()):
                return None
            return correct, hint
    return None


def get_lesson(lesson_id: str, lang: str) -> dict | None:
    block = LESSONS.get(lesson_id, {}).get(lang)
    if not block:
        return None
    phrase, explain = block
    lang_name = LANG_NAMES.get(lang, lang)
    return {
        "type": "lesson",
        "user_text": "",
        "user_lang": "tr",
        "robot_tr": f"📚 {explain}",
        "robot_target": phrase,
        "correct_phrase": phrase,
        "needs_correction": False,
        "target_lang": lang,
        "target_lang_name": lang_name,
    }


def tutor_reply(
    text: str,
    detected_lang: str,
    target_lang: str,
    translate_fn,
    looks_like_lang_fn,
) -> dict:
    text = _norm(text)
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    is_help = (
        detected_lang == "tr"
        or looks_like_lang_fn(text, "tr")
        or bool(HELP_RE.search(text))
    )

    if is_help and (
        HELP_RE.search(text)
        or looks_like_lang_fn(text, "tr")
        or detected_lang == "tr"
    ):
        phrase_tr = _extract_turkish_phrase(text)
        translated = translate_fn(phrase_tr, "tr", target_lang)
        return {
            "type": "help",
            "user_text": text,
            "user_lang": "tr",
            "robot_tr": (
                f"Tabii! Türkçe: \"{phrase_tr}\"\n"
                f"{lang_name} karşılığı: \"{translated}\"\n"
                f"Tekrar et ve birlikte çalışalım. 🎯"
            ),
            "robot_target": translated,
            "correct_phrase": translated,
            "needs_correction": False,
            "target_lang": target_lang,
            "target_lang_name": lang_name,
        }

    if looks_like_lang_fn(text, target_lang) or detected_lang == target_lang:
        fix = _check_correction(text, target_lang)
        if fix:
            correct, hint = fix
            return {
                "type": "correction",
                "user_text": text,
                "user_lang": target_lang,
                "robot_tr": f"❌ {hint}\n✅ Doğrusu: \"{correct}\"",
                "robot_target": correct,
                "correct_phrase": correct,
                "needs_correction": True,
                "target_lang": target_lang,
                "target_lang_name": lang_name,
            }

        close = _closest_phrase(text, target_lang)
        if close:
            phrase, hint = close
            return {
                "type": "suggest",
                "user_text": text,
                "user_lang": target_lang,
                "robot_tr": (
                    f"Şunu mu demek istedin? ({hint})\n"
                    f"✅ \"{phrase}\""
                ),
                "robot_target": phrase,
                "correct_phrase": phrase,
                "needs_correction": True,
                "target_lang": target_lang,
                "target_lang_name": lang_name,
            }

        tr_meaning = translate_fn(text, target_lang, "tr")
        return {
            "type": "practice",
            "user_text": text,
            "user_lang": target_lang,
            "robot_tr": (
                f"Güzel! 👍 Anladım: \"{tr_meaning}\"\n"
                f"Doğru söyledin — devam et!"
            ),
            "robot_target": text,
            "correct_phrase": text,
            "needs_correction": False,
            "target_lang": target_lang,
            "target_lang_name": lang_name,
        }

    translated = translate_fn(text, detected_lang if detected_lang in LANG_NAMES else "tr", target_lang)
    tr_back = translate_fn(translated, target_lang, "tr")
    return {
        "type": "mixed",
        "user_text": text,
        "user_lang": detected_lang,
        "robot_tr": (
            f"Anladım. {lang_name}: \"{translated}\"\n"
            f"(Türkçe: {tr_back})"
        ),
        "robot_target": translated,
        "correct_phrase": translated,
        "needs_correction": False,
        "target_lang": target_lang,
        "target_lang_name": lang_name,
    }
