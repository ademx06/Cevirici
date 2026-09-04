"""Profesyonel dil eğitimi motoru — doğal konuşma, SRS, profil, kelime."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tutor import _extract_turkish_phrase

_ENGINE_DIR = Path(__file__).resolve().parent
HTTP_UA = "Mozilla/5.0 (compatible; SesliCevirmen/1.0)"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def _api_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {"User-Agent": HTTP_UA, "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _load_dotenv() -> None:
    """OPENAI_API_KEY vb. — .env dosyasından yükle (ortamda yoksa)."""
    for path in (_ENGINE_DIR / ".env", Path.home() / ".sesli-cevirmen.env"):
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except OSError:
            continue


_load_dotenv()

LANG_NAMES = {
    "tr": "Turkish",
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "ru": "Russian", "ka": "Georgian", "it": "Italian", "ar": "Arabic", "zh": "Chinese",
}

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
SRS_INTERVALS_DAYS = [1, 3, 7, 14, 30]

SYSTEM_PROMPT = """You are a professional personal language tutor for a Turkish-speaking student.
Speak primarily in the TARGET LANGUAGE (English etc.) for natural conversation.
The student's native language is Turkish — provide Turkish explanations for errors and grammar.
Do not behave like a translation app during conversation.
You are sitting across from the student having a real conversation — like a friendly human, not a robot.
ALWAYS respond to what they just said (answer their question, react to their news, acknowledge their feeling).
Then ask ONE natural follow-up question to keep the dialogue flowing.
Adapt to the user's level. Correct important mistakes clearly, then continue chatting.
When correcting: show wrong sentence, correct sentence, brief Turkish explanation, then continue the conversation.
Keep target-language responses concise (2-4 sentences). Almost every turn MUST end with a question.
Wait for the user to respond — do not answer your own questions."""

AI_TUTOR_JSON_PROMPT = """You are a PROFESSIONAL personal {lang_name} tutor for a Turkish-speaking student. Level: {level}.
You are NOT a chatbot, NOT a translation app, NOT a Q&A bot. You are a real teacher sitting across the table.

Weak areas (review naturally when relevant): {weak_areas}
Repeated mistakes to watch: {repeated_mistakes}
Roleplay: {roleplay}

{curriculum_block}

CONVERSATION HISTORY:
{history_text}

LAST THING YOU SAID:
"{last_teacher}"

RECENT QUESTIONS (do NOT repeat):
{recent_questions}

STUDENT JUST SAID ({input_lang}) — raw speech-to-text:
"{user_text}"

{stt_note}

TEACHING LOOP — every turn:
TALK → UNDERSTAND → EVALUATE → CORRECT → TEACH → REPEAT → DEVELOP → NEW TOPIC

Evaluate on THREE axes separately (do not mix):
1. MEANING — what did student mean?
2. GRAMMAR — real grammar error?
3. NATURALNESS — correct but stiff?

{micro_chain_block}

DECISION CHECKLIST (internal, before responding):
1. What did student mean? 2. Is their English correct? 3. STT garble possible?
4. Real error? 5. What are they learning now? 6. What did they learn before?
7. Repeated mistake to review? 8. ONE small new thing to teach now?
9. How to keep them talking? 10. How to continue naturally WITHOUT resetting progress?

NEVER RESET PROGRESS:
- If student confirmed understanding ("yes that's what I meant" / "evet onu söylemek istedim"), BUILD FORWARD.
- NEVER say "Let's go back to basics. Say Hello."
- Use SHORT → LONGER → NATURAL: I'm fine → I'm fine thank you → And you? → I'm pretty good → I'm reading → I'm reading a book today.

"OKAY" IS NOT WRONG:
- If student says "okay" but you wanted "And you?" — do NOT mark wrong (correction_level 1).
- Say: "Okay! Now practice: 'And you?' Can you say it?"

VARIED TEACHING (not every turn ends with "Repeat after me"):
- Sometimes ask a question, sometimes free talk, sometimes fill-in, sometimes mini quiz, sometimes review old error.

TEACHER_TR RULE — Turkish panel is SUPPORT only:
- Max 1-3 short lines. NEVER repeat the full English answer in Turkish.
- Use for: brief error note, key word meaning, encouragement. null if not needed.

STT / GARBLED TEXT:
- Never claim certainty. Ask: "Did you mean English films or TV series?"

SPECIFIC TEACHING:
- "today is reading book maybe" → I am reading a book today. (I + am + reading = now)
- "children's are reading" → child/children/children's explained correctly, then "The children are reading a book."
- "the students are reading a book" → CORRECT (level 1), then extend: "...in the classroom today."
- Pronunciation complaint → slow down, say phrase clearly, optional word-by-word.

Return ONLY valid JSON:
{{
  "teacher_en": "main {lang_name} reply — short, natural, ends with question or practice prompt",
  "teacher_tr": "brief Turkish support or null",
  "phonetic_en": "string or null",
  "correction_level": 1,
  "correct_phrase": "string or null",
  "suggested_practice": "phrase for student to repeat or null",
  "teach_new_phrase": "one new phrase/pattern to teach this turn or null",
  "teach_new_phrase_tr": "Turkish meaning of new phrase or null",
  "grammar_tr": "max 2 short Turkish sentences about REAL mistake or null",
  "word_breakdown_tr": "null unless explicitly asked — keep responses short",
  "speak_tr": "Turkish TTS for correction, max 25 words, or null",
  "category": "grammar|word_choice|naturalness|greeting|lesson or null",
  "inferred_meaning": "brief summary of what student meant or null",
  "stt_uncertain": false,
  "build_on_phrase": "next longer sentence in build chain or null",
  "lesson_advance": false,
  "micro_advance": false
}}"""

SENTENCE_ANALYSIS_JSON_PROMPT = """You are an expert personal language tutor. Student is Turkish; target language is {lang_name} ({target_lang}).

STUDENT TURKISH SENTENCE:
"{phrase_tr}"
{attempt_block}

YOUR TASK: Understand what the student MEANS, then teach how to say it naturally in {lang_name}.

CRITICAL RULES — NEVER VIOLATE:
1. ONLY analyze words and phrases that ACTUALLY appear in the student's Turkish sentence.
2. NEVER invent examples the student did not say (e.g. do NOT add "gitmek istemiyorum" if they didn't say it).
3. NEVER split Turkish idioms word-by-word ("iş yerinde" = "at work", NOT "iş"=work + "yerinde"=in place).
4. Preserve ALL meanings from Turkish — do not change what they said (tired + wants coffee = both must appear).
5. Prefer natural daily speech an native speaker would use, not literal word-for-word translation.
6. For Turkish input without an English attempt: error_class = "N_A", correction_needed = false.
7. phrase_pairs: 2-6 items, each "tr" must be a phrase FROM the student's sentence (whole chunks like "iş yerinde", not split words).
8. alternatives: max 2 optional natural phrasings. Empty array if none needed.
9. Do NOT force past tense in English for Turkish "-dım" if present state fits ("yoruldum" → "I'm tired" is OK).

Return ONLY valid JSON:
{{
  "natural_target": "most natural {lang_name} sentence preserving all meanings",
  "alternatives": ["optional alt 1", "optional alt 2"],
  "error_class": "N_A|CORRECT|GRAMMAR_ERROR|WORD_CHOICE|NATURALNESS|CONTEXT",
  "analysis_tr": "2-4 Turkish sentences: what the sentence means, is the structure natural in {lang_name}",
  "correction_needed": false,
  "wrong_phrase": null,
  "correct_phrase": null,
  "correction_reason_tr": null,
  "important_structure_tr": "simple grammar tip from THIS sentence only, or null",
  "phrase_pairs": [{{"tr": "Turkish chunk from sentence", "en": "natural {lang_name}"}}],
  "practice_prompt_tr": "short Turkish prompt asking student to repeat the target sentence aloud"
}}"""

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

# Doğal ders akışı — rastgele sohbet değil, zincir halinde ilerler
LESSON_CURRICULUM: list[dict[str, str]] = [
    {"id": "greetings", "title": "Selamlaşma", "focus": "Hello / Hi, How are you?, I'm fine thank you"},
    {"id": "intro_long", "title": "Uzun selamlaşma", "focus": "I'm fine, thank you. How are you? / I'm pretty good"},
    {"id": "intro_name", "title": "Kendini tanıtma", "focus": "My name is..., Nice to meet you"},
    {"id": "origin", "title": "Nereli", "focus": "I'm from..., I live in..."},
    {"id": "age_job", "title": "Yaş ve meslek", "focus": "I'm ... years old, I work as..."},
    {"id": "family", "title": "Aile", "focus": "I have..., My family is..."},
    {"id": "daily_routine", "title": "Günlük rutin", "focus": "I usually..., Every day I..."},
    {"id": "likes", "title": "Sevdiği şeyler", "focus": "I like..., I love..., My favorite..."},
    {"id": "food_drink", "title": "Yemek içecek", "focus": "I want..., I'd like..., food and drinks"},
    {"id": "shopping", "title": "Alışveriş", "focus": "How much?, I'd like to buy..."},
    {"id": "directions", "title": "Yol tarifi", "focus": "Where is?, Turn left/right"},
    {"id": "restaurant", "title": "Restoran", "focus": "Can I have..., The bill please"},
    {"id": "hotel", "title": "Otel", "focus": "I have a reservation, check-in"},
    {"id": "travel", "title": "Seyahat", "focus": "I'm going to..., I visited..."},
]

# Mikro öğrenme zinciri — SHORT → LONGER → NATURAL (V2)
GREETING_MICRO_CHAIN: list[dict[str, str]] = [
    {"id": "hello", "en": "Hello.", "tr": "Merhaba.", "teach_next": "How are you?"},
    {"id": "how_are_you", "en": "How are you?", "tr": "Nasılsın?", "teach_next": "I'm fine."},
    {"id": "im_fine", "en": "I'm fine.", "tr": "İyiyim.", "teach_next": "I'm fine, thank you."},
    {"id": "im_fine_thanks", "en": "I'm fine, thank you.", "tr": "İyiyim, teşekkürler.", "teach_next": "And you?"},
    {"id": "and_you", "en": "And you?", "tr": "Sen nasılsın?", "teach_next": "I'm pretty good."},
    {"id": "pretty_good", "en": "I'm pretty good.", "tr": "Oldukça iyiyim.", "teach_next": "I'm doing great."},
    {"id": "doing_great", "en": "I'm doing great.", "tr": "Harika gidiyor.", "teach_next": "What are you doing?"},
]

READING_BUILD_CHAIN: list[str] = [
    "I read.",
    "I read a book.",
    "I am reading a book.",
    "I am reading a book today.",
    "I am reading a book at home today.",
    "I am reading a book at home because I have some free time.",
]

PRONUNCIATION_FEEDBACK_RE = re.compile(
    r"yanlış\s+telaffuz|telaffuz.*yanlış|wrong\s+pronunciation|say\s+it\s+(?:more\s+)?slow",
    re.I,
)

TR_MONTHS = {
    "ocak": "January", "şubat": "February", "mart": "March", "nisan": "April",
    "mayıs": "May", "haziran": "June", "temmuz": "July", "ağustos": "August",
    "eylül": "September", "ekim": "October", "kasım": "November", "kasim": "November",
    "aralık": "December",
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
    r"(^\s*yardım\b|nasıl\s+(?:söylerim|derim|denir|söyleyeceğim)|ingilizcede|ne\s+demek|çevirir\s+misin|"
    r"kısmını\s+söyle(?:y)?emiyorum|how\s+do\s+i\s+say|what\s+is\s+.+\s+in\s+english|"
    r"bunu\s+nasıl\s+söylerim|anlatır\s+mısın|ne\s+söyleyeceğimi|cümleyi\s+nasıl\s+kur)",
    re.I,
)

HOW_TO_SAY_STUCK_RE = re.compile(
    r"(nasıl\s+söyleyeceğim(?:i)?\s+bilmiyorum|ne\s+söyleyeceğimi\s+bilmiyorum|"
    r"ne\s+demem\s+lazım|ne\s+desem\s+bilemedim|nasıl\s+söylesem\s+bilemedim|"
    r"cümleyi\s+nasıl\s+kur(?:acağım|abilirim|arım)|nasıl\s+söyleyebilirim|"
    r"söyleyemiyorum\s*$|don'?t\s+know\s+how\s+to\s+say|don'?t\s+know\s+what\s+to\s+say|"
    r"i\s+don'?t\s+know\s+(?:how|what)\s+(?:to\s+)?say|how\s+(?:can|do|should)\s+i\s+say\s+(?:this|it))",
    re.I,
)

YARDIM_PREFIX_RE = re.compile(r"^\s*yardım\b[,\s!:.-]*", re.I)

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
    (re.compile(r"\bi want not\b", re.I), "I don't want to.", "negative",
     "Negative comes before the verb: I don't want (not 'I want not').",
     "Olumsuzluk fiilden önce gelir: I don't want — 'I want not' yanlış."),
    (re.compile(r"\bi (tomorrow|today|yesterday) (go|went|will go)\b", re.I), "I will go tomorrow.", "word_order",
     "Time usually goes at the end in English: I will go to work tomorrow.",
     "Zaman kelimesi genelde sonda: I will go to work tomorrow."),
    (re.compile(r"\bi go work\b", re.I), "I go to work.", "grammar",
     "Add 'to': go to work.", "'To' ekle: go to work."),
    (re.compile(r"\bi am go to\b", re.I), "I am going to ...", "present_continuous",
     "Use 'am going to' for near future.", "Yakın gelecek: am going to."),
    (re.compile(r"\bi don't want go\b", re.I), "I don't want to go.", "negative",
     "After 'want', use 'to + verb': want to go.", "Want'tan sonra to + fiil: want to go."),
    (re.compile(r"\bi book\b", re.I), "I read a book today.", "intent_fragment",
     "You said 'book' — sounds like you wanted to say you read a book.",
     "Kitap okudum demeye çalıştın — tam cümle: I read a book."),
    (re.compile(r"\b(read book|a book)\b", re.I), "I read a book today.", "intent_fragment",
     "Use a full sentence: I read a book today.",
     "Tam cümle kur: I read a book today = Bugün bir kitap okudum."),
    (re.compile(r"\bi am run\b", re.I), "I went for a run today.", "learner_grammar",
     "'I am run' is wrong — use past tense 'I ran' or 'I went for a run'.",
     "'I am run' yanlış. Geçmiş: I ran today veya I went for a run."),
    (re.compile(r"\bi sleeping\b", re.I), "I was sleeping.", "learner_grammar",
     "Use 'I was sleeping' (past) or 'I'm going to sleep' (plan).",
     "'I sleeping' yanlış — 'I was sleeping' (uyuyordum) veya 'I'm going to sleep' (uyuyacağım)."),
    (re.compile(r"\bi very tired today\b", re.I), "I'm very tired today.", "be_verb",
     "Use 'I'm' before adjectives.", "'I'm very tired today' de."),
    (re.compile(r"\bi want go\b", re.I), "I want to go home.", "grammar",
     "After 'want', use 'to + verb': want to go.", "Want'tan sonra to + fiil: want to go."),
    (re.compile(r"\bi want drink\b", re.I), "I want to drink coffee.", "grammar",
     "After 'want', use 'to + verb': want to drink.", "Want'tan sonra to + fiil kullan."),
    (re.compile(r"\bi am boring\b", re.I), "I am bored.", "word_choice",
     "'Boring' = sıkıcı (thing). 'Bored' = sıkılmış (feeling).", "'Boring' değil 'bored' — sıkıldım demek için."),
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
    r"(türkçe\s+açıkla|anlamadım|anlamıyorum|tekrar(?:\s+et|\s+söyle)?|repeat|speak\s+slowly|yavaş\s+konuş|slow)",
    re.I,
)

CONFUSION_RE = re.compile(
    r"(?:^|\b)(?:i\s+)?(?:(?:don't|do not|didn't)\s+understand(?:\s+(?:it|you|this|that))?|"
    r"(?:don't|do not)\s+get\s+it|what\s+do\s+you\s+mean|what\s+does\s+(?:that|this|it)\s+mean|"
    r"(?:i'm|i am)\s+confused|(?:it's|its|this\s+is)\s+confusing|not\s+clear|can\s+you\s+explain|"
    r"anlamadım|anlamıyorum|ne\s+demek|ne\s+diyorsun|açıklar\s+mısın|"
    r"tekrar\s+(?:eder|edebilir)\s+misin|(?:^|\b)what\?(?:\s|$)|(?:^|\b)huh\?(?:\s|$)|"
    r"pardon|excuse\s+me\?)(?:\s|$|[.!?,])",
    re.I,
)

_POLITE_WORDS = frozenset({
    "yes", "yeah", "yep", "yup", "ok", "okay", "nice", "good", "great", "fine", "sure",
    "thanks", "thank", "you", "welcome", "please", "no", "well", "alright", "right",
    "cool", "awesome", "perfect", "lovely", "dear", "sorry", "excuse", "me",
})


def _is_polite_acknowledgment(text: str) -> bool:
    """Teşekkür, tamam, güzel — gramer hatası sayma."""
    t = text.strip().lower()
    if not t:
        return False
    if re.search(
        r"\b(thank you|thanks|thank|you're welcome|you are welcome|no problem|"
        r"sounds good|that's nice|that is nice|that's ok|that is ok|nice one)\b",
        t,
    ):
        return True
    words = re.findall(r"[a-z']+", t)
    if not words or len(words) > 8:
        return False
    return all(w in _POLITE_WORDS for w in words)


def _is_greeting_or_small_talk(text: str) -> bool:
    """Selamlaşma / hal hatır — pratik modunda bile düzeltme yapma."""
    ul = text.strip().lower()
    if not ul:
        return False
    if re.search(
        r"\b(hello|hi|hey|good morning|good afternoon|good evening|good night|"
        r"how are you|how're you|how are you doing|how is it going|what's up|whats up|"
        r"nice to meet|pleased to meet|how was your day|how's your day|"
        r"merhaba|selam|nasılsın|nasilsin|naber|günaydın|iyi akşamlar)\b",
        ul,
    ):
        return True
    return _is_polite_acknowledgment(text)


def _should_exit_practice_mode(user_text: str, pending: str) -> bool:
    """Bekleyen pratik varken öğrenci başka konuya geçtiyse pratiği bırak."""
    if not pending:
        return False
    if _practice_phrase_match(user_text, pending):
        return False
    if _is_greeting_or_small_talk(user_text):
        return True
    if len(user_text.split()) >= 3 and not _is_fragment_attempt(user_text):
        if _phrase_similar(user_text, pending):
            return False
        if looks_like_lang(user_text, "en") or looks_like_lang(user_text, "tr"):
            return True
    return False


def _sanitize_ai_correction(user_text: str, parsed: dict) -> dict:
    """AI bazen gereksiz düzeltme üretir — selam/teşekkür ve doğru cümleleri temizle."""
    if _is_polite_acknowledgment(user_text) or _is_greeting_or_small_talk(user_text):
        out = dict(parsed)
        out["correction_level"] = 1
        out["correct_phrase"] = None
        out["suggested_practice"] = None
        out["grammar_tr"] = None
        out["word_breakdown_tr"] = None
        out["speak_tr"] = None
        out["category"] = None
        return out

    correct = safe_str(parsed.get("correct_phrase")).strip()
    if correct and _phrase_similar(user_text, correct):
        out = dict(parsed)
        out["correction_level"] = 1
        out["correct_phrase"] = None
        out["suggested_practice"] = None
        out["grammar_tr"] = None
        out["word_breakdown_tr"] = None
        out["speak_tr"] = None
        return out

    if _is_likely_correct_english(user_text):
        out = dict(parsed)
        out["correction_level"] = 1
        out["correct_phrase"] = None
        out["suggested_practice"] = None
        if out.get("grammar_tr") and re.search(r"yanlış|hatalı|wrong", safe_str(out.get("grammar_tr")), re.I):
            out["grammar_tr"] = None
            out["speak_tr"] = None
        return out

    return parsed


def _is_likely_correct_english(text: str) -> bool:
    """Gramer olarak doğru bilinen kalıplar — gereksiz düzeltmeyi engelle."""
    ul = re.sub(r"[^\w\s'-]", "", text.lower()).strip()
    ok_patterns = (
        r"^i'?m very tired today$",
        r"^i am very tired today$",
        r"^i'?m really tired today$",
        r"^i want to drink coffee$",
        r"^i want to have some coffee$",
        r"^i want to go home$",
        r"^i went to work today$",
        r"^i'?m fine thanks$",
        r"^i'?m good thanks$",
    )
    return any(re.match(p, ul) for p in ok_patterns)


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
        "pendingPracticePhrase": None,
        "pendingPracticeTr": None,
        "pendingIntentConfirm": None,
        "pendingIntentUserSaid": None,
        "pendingIntentReason": None,
        "lessonStep": 0,
        "microStep": 0,
        "masteredLessonTopics": [],
        "taughtPatterns": [],
        "lastMasteredPhrase": "",
        "sentenceBuildBase": "",
        "awaitingTargetPhrase": "",
    }


def merge_profile(profile: dict | None, delta: dict | None) -> dict:
    base = default_profile()
    list_keys = (
        "grammarErrors", "repeatedMistakes", "weakAreas", "strongAreas", "newWords",
        "sessions", "srsItems", "vocabularyBank", "dailyStats", "sessionLog",
        "vocabularyWeaknesses", "masteredTopics", "masteredLessonTopics", "taughtPatterns",
    )
    if profile:
        for k, v in profile.items():
            if v is None:
                continue
            if k in list_keys:
                if isinstance(v, list):
                    base[k] = v
                elif isinstance(v, str) and v.strip():
                    base[k] = [v.strip()]
                else:
                    base[k] = []
            else:
                base[k] = v
    if not delta:
        return base
    for key in list_keys:
        if key in delta and isinstance(delta[key], list):
            base[key] = delta[key]
    scalar_keys = (
        "currentLevel", "todayMinutes", "totalSentences", "correctSentences",
        "totalCorrections", "sessionCorrections", "yesterdayCorrections",
        "lastTeacherText", "waitingForUser", "targetLang", "todayDate",
        "sessionStartAt", "lastSessionDate", "pendingSrsId", "pendingVocabWord",
        "pendingPracticePhrase", "pendingPracticeTr",
        "lessonStep", "masteredLessonTopics", "taughtPatterns",
        "microStep", "lastMasteredPhrase", "sentenceBuildBase", "awaitingTargetPhrase",
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
            if correct and _norm(t) == _norm(correct):
                return 1, None, None, None, None
            return 3, correct, cat, ex_en, ex_tr
    if re.search(r"\b(goed|go yesterday|am go|is you|in fine you)\b", t, re.I):
        return 3, None, "grammar", "Let's fix the grammar.", "Gramer hatası var."
    ul = t.lower()
    if re.search(r"\bdon't want go\b|\bwant not\b|\bi want not\b", ul):
        return 3, "I don't want to go.", "negative",
        "Use: I don't want to + verb.", "Olumsuz: I don't want to + fiil."
    am_m = re.search(r"\bi am (\w+)\b", ul)
    if am_m:
        v = am_m.group(1).lower()
        am_fixes: dict[str, tuple[str, str, str]] = {
            "run": ("I went for a run today.", "'I am run' is wrong — say 'I ran' or 'I went for a run'.",
                    "'I am run' yanlış. Koştum demek için: I ran today."),
            "ran": ("I ran today.", "Don't say 'I am ran' — just 'I ran today'.", "'I am ran' yanlış — I ran today de."),
            "go": ("I went to work today.", "'I am go' is wrong — past tense: I went.", "'I am go' yanlış — I went de."),
            "read": ("I read a book today.", "'I am read' is wrong — say 'I read a book'.", "'I am read' yanlış — I read a book de."),
            "walk": ("I walked today.", "Use past tense: I walked.", "Geçmiş: I walked today."),
            "play": ("I played today.", "Use past tense: I played.", "Geçmiş: I played today."),
            "eat": ("I ate today.", "Use past tense: I ate.", "Geçmiş: I ate today."),
            "work": ("I worked today.", "Use past tense: I worked.", "Geçmiş: I worked today."),
            "swim": ("I swam today.", "Use past tense: I swam.", "Geçmiş: I swam today — swim→swam."),
            "watch": ("I watched TV today.", "Use past tense: I watched.", "Geçmiş: I watched TV today."),
        }
        if v in am_fixes and not v.endswith("ing"):
            c, en, tr = am_fixes[v]
            return 3, c, "learner_grammar", en, tr
    if re.search(r"\bi (run|walk|play|eat|swim)\b", ul) and "went" not in ul and "am" not in ul:
        short_fixes = {
            "run": ("I ran today.", "Use past tense 'ran' for completed actions.", "Geçmiş: I ran today."),
            "walk": ("I walked today.", "Use past tense 'walked'.", "Geçmiş: I walked today."),
            "play": ("I played today.", "Use past tense 'played'.", "Geçmiş: I played today."),
            "eat": ("I ate today.", "Use past tense 'ate'.", "Geçmiş: I ate today."),
            "swim": ("I swam today.", "Use past tense 'swam'.", "Geçmiş: I swam today."),
        }
        for kw, (c, en, tr) in short_fixes.items():
            if re.search(rf"\bi {kw}\b", ul):
                return 3, c, "learner_grammar", en, tr
    if re.search(r"\bi (very|so|really) (tired|happy|sad|busy)\b", ul) and not re.search(r"\bi'?m\b|\bi am\b", ul):
        mood = re.search(r"\b(tired|happy|sad|busy)\b", ul)
        m = mood.group(1) if mood else "tired"
        return 2, f"I'm very {m} today.", "be_verb",
        "Before adjectives, use I'm / I am: I'm very tired.", "Sıfattan önce I'm kullan."
    if len(t.split()) >= 4 and not re.search(
        r"\b(is|are|am|was|were|have|has|do|does|did|will|can|want|went|go|going|don't|didn't)\b", ul
    ):
        return 2, None, "missing_verb",
        "Your sentence needs a clear verb (am, go, want, did...).",
        "Cümlede net bir fiil olmalı (am, go, want, did...)."
    if re.search(r"\b(me english|english me|turkish i|i turkish)\b", ul):
        return 2, None, "word_order",
        "Check word order — subject first, then verb.", "Kelime sırasını kontrol et — önce özne, sonra fiil."
    if len(t.split()) >= 3 and not re.search(r"\b(is|are|am|was|were|have|has|do|does|did|will|can)\b", t, re.I):
        if re.search(r"\b(tired|happy|sad|good|bad|busy|ready)\b", t, re.I):
            return 2, None, "be_verb", "Remember to use 'am/is/are' with adjectives.", None
    return 1, None, None, None, None


def _build_conversation_teach(
    user_text: str,
    correct_phrase: str | None,
    category: str | None,
    explain_en: str | None,
    explain_tr: str | None,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> tuple[str, str]:
    """Sohbette hata yapıldığında öğretici düzeltme — yardım modu kalitesinde."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    suggested = correct_phrase
    if not suggested and translate_fn and re.search(r"[ğüşıöçĞÜŞİÖÇ]", user_text):
        try:
            suggested = translate_fn(user_text, "tr", target_lang)
        except Exception:
            pass
    if not suggested and explain_en:
        m = re.search(r'"([^"]+)"', explain_en)
        if m:
            suggested = m.group(1)

    cat_labels = {
        "negative": ("Olumsuz cümle hatası", "Negative sentence error"),
        "be_verb": ("'am/is/are' eksik veya yanlış", "Missing or wrong 'am/is/are'"),
        "past_tense": ("Geçmiş zaman hatası", "Past tense error"),
        "word_order": ("Kelime sırası hatası", "Word order error"),
        "missing_verb": ("Fiil eksik", "Missing verb"),
        "intent_fragment": ("Eksik cümle — tam cümle kur", "Incomplete sentence"),
        "learner_grammar": ("Tipik öğrenici hatası", "Typical learner mistake"),
        "grammar": ("Gramer hatası", "Grammar error"),
    }
    cat_tr, cat_en = cat_labels.get(category or "grammar", ("Dil hatası", "Language error"))

    teach_tr_parts = [
        f"⚠️ Küçük bir düzeltme — öğrenelim:",
        f"❌ Senin cümlen:\n\"{user_text}\"",
        f"📋 Hata türü: {cat_tr}",
    ]
    if category == "intent_fragment":
        teach_tr_parts[0] = "🤔 Sanırım ne demek istediğini anlıyorum:"
    if category == "learner_grammar":
        teach_tr_parts[0] = "🤔 Bunu mu demeye çalıştın? Küçük bir gramer düzeltmesi:"
    if explain_tr:
        teach_tr_parts.append(f"💡 Neden: {explain_tr}")
    elif explain_en:
        teach_tr_parts.append(f"💡 Neden: {explain_en}")
    if suggested:
        teach_tr_parts.append(f"✅ Böyle söylemelisin:\n\"{suggested}\"")
        if translate_fn and target_lang == "en":
            try:
                tr_sug = translate_fn(suggested, "en", "tr")
                if tr_sug:
                    teach_tr_parts.append(f"🇹🇷 Anlamı: {tr_sug}")
            except Exception:
                pass
        word_help = _build_intent_word_help(suggested, "")
        if word_help:
            teach_tr_parts.insert(-2, f"📖 Kelimeler:\n{word_help}")
        struct = grammar_breakdown(suggested, "A1")
        if struct:
            teach_tr_parts.insert(-2, f"🧩 Cümle yapısı:\n{struct}")
    teach_tr_parts.append("🔄 Şimdi doğru cümleyi söyle, sonra sohbete devam ederiz.")

    teach_en_parts = [
        f"Let me help you with that — small correction:",
        f"❌ You said: \"{user_text}\"",
        f"📋 Issue: {cat_en}",
    ]
    if explain_en:
        teach_en_parts.append(f"💡 Why: {explain_en}")
    if suggested:
        teach_en_parts.append(f"✅ Say it like this: \"{suggested}\"")
    teach_en_parts.append("🔄 Try the correct sentence, then we'll keep chatting.")

    return "\n\n".join(teach_en_parts), "\n\n".join(teach_tr_parts)


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s']", "", s.lower()).strip()


def _token_set(s: str) -> set[str]:
    return {w for w in _norm(s).split() if len(w) > 1}


_PRACTICE_STOP = frozenset({
    "i", "im", "i'm", "am", "is", "are", "was", "were", "be", "been",
    "a", "an", "the", "to", "at", "in", "on", "for", "of", "and", "or",
    "going", "go", "will", "would", "can", "do", "does", "did",
    "today", "tomorrow", "yesterday", "now", "very", "so", "just",
})


def _content_tokens(s: str) -> set[str]:
    return {w for w in _token_set(s) if w not in _PRACTICE_STOP}


_PRACTICE_PAST = frozenset({
    "went", "was", "were", "did", "had", "ran", "walked", "worked", "read", "played", "got",
    "ate", "drank", "slept", "came", "took", "made", "said", "told", "saw", "bought",
})
_PRACTICE_FUTURE = frozenset({"will", "ll", "going", "gonna", "shall"})


def _practice_phrase_match(user: str, pending: str) -> bool:
    """Pratik cümlesi eşleşmesi — 'I went' ≠ 'I will go' (gevşek eşleşme yasak)."""
    if not user or not pending:
        return False
    nu, np = _norm(user), _norm(pending)
    if nu == np:
        return True
    tu, tp = _token_set(user), _token_set(pending)
    if not tp or not tu:
        return False
    if tu == tp:
        return True
    # Gelecek zaman beklenirken geçmiş zaman kabul etme
    pending_future = bool(tp & _PRACTICE_FUTURE) or "going to" in np or "gonna" in np
    user_past = bool(tu & _PRACTICE_PAST)
    if pending_future and user_past:
        return False
    # Tüm kelimeler üzerinden overlap
    overlap = len(tu & tp) / max(len(tp), 1)
    user_future = bool(tu & _PRACTICE_FUTURE) or "going" in tu
    if pending_future and user_future:
        # "I will go…" ≈ "I'm going to go…"
        skip = _PRACTICE_FUTURE | {"going", "am", "are", "is", "be", "to", "gonna"}
        cu = {w for w in tu if w not in skip}
        cp = {w for w in tp if w not in skip}
        if cp and len(cu & cp) / len(cp) >= 0.75:
            return True
    if overlap < 0.78:
        return False
    cu, cp = _content_tokens(user), _content_tokens(pending)
    if cp and cu:
        if len(cu & cp) / len(cp) < 0.75:
            return False
    return True


def _phrase_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if _practice_phrase_match(a, b):
        return True
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= 0.75


TR_WORD_GLOSS: dict[str, tuple[str, str]] = {
    "ben": ("I", "özne — cümlenin kimin hakkında olduğunu söyler"),
    "sen": ("you", "karşıdaki kişi"),
    "bugün": ("today", "zaman zarfı — genelde cümlenin sonunda"),
    "yarın": ("tomorrow", "gelecek gün"),
    "dün": ("yesterday", "geçmiş gün — geçmiş zaman fiili gerekir"),
    "işe": ("to work", "iş + -e hali = yönelme (to work)"),
    "okula": ("to school", "okul + -a/-e = to school"),
    "eve": ("home", "eve = home (yönelme)"),
    "gideceğim": ("I will go", "gitmek fiilinin gelecek zamanı (yakın plan)"),
    "gideceksin": ("you will go", "gitmek — sen formu"),
    "yapacağım": ("I will do", "yapmak fiilinin gelecek zamanı"),
    "edeceğim": ("I will do", "etmek fiilinin gelecek zamanı"),
    "çok": ("very", "sıfat/fiilden önce gelir: very tired"),
    "yorgun": ("tired", "yorgun — I'm tired = yorgunum"),
    "mutlu": ("happy", "mutlu — I'm happy"),
    "aç": ("hungry", "aç — I'm hungry"),
    "içeceğim": ("I will drink", "içmek fiilinin gelecek zamanı"),
    "yiyeceğim": ("I will eat", "yemek fiilinin gelecek zamanı"),
    "konuşacağım": ("I will speak", "konuşmak fiilinin gelecek zamanı"),
    "istiyorum": ("I want", "istemek — I want to ..."),
    "istemiyorum": ("I don't want", "olumsuz istek — don't want to ..."),
    "istemiyor": ("doesn't want", "olumsuz istek (3. tekil)"),
    "yoruldum": ("I got tired / I'm tired", "yorulmak geçmişi — bugün yoruldum = I'm tired today"),
    "gitmek": ("to go", "mastar — gitmek istemiyorum = I don't want to go"),
    "gelmek": ("to come", "mastar fiil"),
    "yapmak": ("to do / to make", "mastar fiil"),
    "konuşmak": ("to speak", "mastar fiil"),
    "çalışmak": ("to work", "mastar — çalışmak = to work"),
    "değil": ("not", "olumsuzluk"),
    "değilim": ("I am not", "olumsuz — ben ... değilim"),
    "hiç": ("at all / never", "hiç istemiyorum = I don't want at all"),
    "fazla": ("too much", "çok fazla = too much"),
    "biraz": ("a little", "biraz yorgun = a little tired"),
    "her": ("every", "her gün = every day"),
    "gün": ("day", "zaman"),
    "hafta": ("week", "zaman"),
    "akşam": ("evening", "zaman — in the evening"),
    "sabah": ("morning", "zaman — in the morning"),
    "gece": ("night", "zaman — at night"),
    "çünkü": ("because", "sebep bağlacı"),
    "ama": ("but", "zıtlık bağlacı"),
    "ve": ("and", "bağlaç — iki cümleyi birleştirir"),
}

# Türkçe birleşik ifadeler — kelime kelime parçalanmaz
TR_PHRASE_GLOSS: list[tuple[str, str, str]] = [
    ("iş yerinde", "at work", "işte / çalıştığın yerde"),
    ("işe gittim", "I went to work", "geçmiş zaman"),
    ("bugün çok yorgunum", "I'm very tired today", "durum bildirme"),
    ("çok yoruldum", "I'm really tired / I got very tired", "yorulmak"),
    ("kahve içmek istiyorum", "I want to have some coffee", "have some coffee doğal"),
    ("kahve içmek", "to have/drink coffee", "içmek → drink veya have"),
    ("eve gitmek istiyorum", "I want to go home", "want + to + go home"),
    ("eve gitmek", "to go home", "eve = home yönelme"),
    ("okula gittim", "I went to school", "geçmiş zaman"),
    ("bugün", "today", "zaman — genelde sonda"),
    ("yarın", "tomorrow", "gelecek"),
    ("dün", "yesterday", "geçmiş"),
    ("istiyorum", "I want", "want + to + fiil"),
    ("istemiyorum", "I don't want", "don't want to + fiil"),
    ("yorgunum", "I'm tired", "I'm + sıfat"),
    ("çok yorgunum", "I'm very tired", "very + sıfat"),
    ("kahve", "coffee", ""),
    ("içmek", "to drink / to have", "have some ... daha doğal olabilir"),
]


def _phrase_vocab_breakdown(
    phrase_tr: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> list[dict[str, str]]:
    """Bağlamsal ifade eşleştirmesi — kelime kelime parçalama yapmaz."""
    text = phrase_tr.lower()
    pairs: list[dict[str, str]] = []
    covered: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in covered)

    for tr_phrase, en_phrase, _note in sorted(TR_PHRASE_GLOSS, key=lambda x: -len(x[0])):
        idx = text.find(tr_phrase)
        while idx >= 0:
            end = idx + len(tr_phrase)
            if not _overlaps(idx, end):
                pairs.append({"tr": phrase_tr[idx:end] if idx < len(phrase_tr) else tr_phrase, "en": en_phrase})
                covered.append((idx, end))
            idx = text.find(tr_phrase, idx + 1)

    if len(pairs) < 2:
        chunks = re.split(r"\s*[,;]\s*|\s+(?:ve|ama|fakat|çünkü)\s+", phrase_tr)
        for ch in chunks:
            ch = ch.strip()
            if len(ch) < 4:
                continue
            if any(ch.lower() in p["tr"].lower() or p["tr"].lower() in ch.lower() for p in pairs):
                continue
            en = ""
            if translate_fn and target_lang:
                try:
                    en = translate_fn(ch, "tr", target_lang)
                except Exception:
                    en = ""
            if en:
                pairs.append({"tr": ch, "en": en})

    dedup: list[dict[str, str]] = []
    seen_tr: set[str] = set()
    for p in pairs:
        key = p["tr"].lower().strip()
        if key in seen_tr:
            continue
        seen_tr.add(key)
        dedup.append(p)
    return dedup[:6]


def _rule_natural_translate_tr(
    phrase_tr: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> str:
    """Bağlama göre doğal çeviri — kelime kelime değil."""
    if target_lang != "en" or not translate_fn:
        return translate_fn(phrase_tr, "tr", target_lang) if translate_fn else phrase_tr

    low = phrase_tr.lower().strip()
    known: dict[str, str] = {
        "bugün iş yerinde çok yoruldum, kahve içmek istiyorum.": (
            "I'm really tired from work today. I want to have some coffee."
        ),
        "bugün iş yerinde çok yoruldum kahve içmek istiyorum": (
            "I'm really tired from work today. I want to have some coffee."
        ),
        "eve gitmek istiyorum": "I want to go home.",
        "eve gitmek istiyorum.": "I want to go home.",
        "bugün çok yorgunum": "I'm very tired today.",
        "bugün çok yorgunum.": "I'm very tired today.",
    }
    if low in known:
        return known[low]

    if re.search(r"iş yerinde", low) and re.search(r"yoruldum", low) and re.search(r"kahve.*içmek istiyorum", low):
        return "I'm really tired from work today. I want to have some coffee."
    if re.search(r"eve gitmek istiyorum", low):
        return "I want to go home."
    if re.search(r"bugün.*yorgun", low):
        return "I'm very tired today."

    chunks = re.split(r"\s*[,;]\s*|\s+(?:ve|ama)\s+", phrase_tr)
    if len(chunks) > 1:
        parts: list[str] = []
        for ch in chunks:
            ch = ch.strip()
            if not ch:
                continue
            sub = _rule_natural_translate_tr(ch, target_lang, translate_fn)
            if sub:
                parts.append(sub.rstrip("."))
        if parts:
            return ". ".join(parts) + "."

    try:
        return translate_fn(phrase_tr, "tr", target_lang)
    except Exception:
        return phrase_tr


def _build_rule_analysis_tr(
    phrase_tr: str,
    natural_target: str,
    phrase_pairs: list[dict[str, str]],
    lang_name: str,
) -> str:
    """Kural tabanlı kısa analiz — uydurma örnek yok."""
    low = phrase_tr.lower()
    parts = [f"Demek istediğin: \"{phrase_tr}\""]
    if re.search(r"istiyorum", low) and re.search(r"\w+mek\b", low):
        parts.append(
            f"Türkçede \"-mek istiyorum\" → {lang_name}'de want + to + fiil kullanılır "
            f"(örnek: I want to go / I want to have some coffee)."
        )
    if re.search(r"yoruldum|yorgun", low):
        parts.append(
            "\"Yoruldum\" hem geçmiş eylemi hem bugünkü yorgun hali anlatabilir — "
            f"{lang_name}'de I'm tired / I got tired from work gibi doğal seçenekler var."
        )
    if re.search(r"iş yerinde", low):
        parts.append("\"İş yerinde\" kelime kelime çevrilmez — doğal karşılık: at work.")
    if len(re.split(r"[,;]| ve ", phrase_tr)) > 1:
        parts.append("İki düşünce var — hedef dilde iki cümle veya and ile birleştir.")
    if not len(parts) > 1:
        parts.append(f"Cümleni {lang_name}'de doğal şekilde: \"{natural_target}\"")
    return " ".join(parts)


def _rule_structure_tr(phrase_tr: str, lang_name: str) -> str | None:
    low = phrase_tr.lower()
    if re.search(r"istiyorum", low) and re.search(r"\w+mek\b", low):
        return (
            f"want + to + fiil\n"
            f"Örnek: I want to eat. / I want to sleep. / I want to go home."
        )
    if re.search(r"istemiyorum", low):
        return "I don't want to + fiil\nÖrnek: I don't want to go."
    if re.search(r"yorgunum|yoruldum", low):
        return "I'm + sıfat (tired, happy...)\nÖrnek: I'm very tired today."
    return None


def _rule_based_sentence_analysis(
    phrase_tr: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
    user_en_attempt: str | None = None,
) -> dict[str, Any]:
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    natural = _rule_natural_translate_tr(phrase_tr, target_lang, translate_fn)
    phrase_pairs = _phrase_vocab_breakdown(phrase_tr, target_lang, translate_fn)
    analysis_tr = _build_rule_analysis_tr(phrase_tr, natural, phrase_pairs, lang_name)
    structure = _rule_structure_tr(phrase_tr, lang_name)

    result: dict[str, Any] = {
        "natural_target": natural,
        "alternatives": [],
        "error_class": "N_A",
        "analysis_tr": analysis_tr,
        "correction_needed": False,
        "wrong_phrase": None,
        "correct_phrase": None,
        "correction_reason_tr": None,
        "important_structure_tr": structure,
        "phrase_pairs": phrase_pairs,
        "practice_prompt_tr": f"Şimdi yüksek sesle söyle: \"{natural}\"",
    }

    if user_en_attempt and target_lang == "en":
        level, correct, cat, ex_en, ex_tr = check_english(user_en_attempt)
        if level >= 2 and correct:
            result["correction_needed"] = True
            result["wrong_phrase"] = user_en_attempt.strip()
            result["correct_phrase"] = correct
            result["correction_reason_tr"] = ex_tr or ex_en or ""
            result["error_class"] = "GRAMMAR_ERROR" if cat == "grammar" else (cat or "GRAMMAR_ERROR").upper()
        elif level == 1 and re.search(r"\bi want to drink coffee\b", user_en_attempt, re.I):
            result["error_class"] = "CORRECT"
            result["alternatives"] = ["I want to have some coffee."]
            result["analysis_tr"] = (
                "Cümlen gramer olarak doğru. Günlük konuşmada "
                "'I want to have some coffee' de çok doğal kullanılır."
            )
        elif level == 1:
            result["error_class"] = "CORRECT"
            result["analysis_tr"] = "Cümlen doğru ve doğal görünüyor."

    if natural and target_lang == "en":
        if "have some coffee" in natural.lower():
            alt = natural.replace("have some coffee", "drink coffee")
            if alt != natural:
                result["alternatives"] = [alt]
        if "I'm really tired from work" in natural:
            result["alternatives"] = ["I got very tired at work today. I want to have some coffee."]

    return result


def _try_llm_sentence_analysis(
    phrase_tr: str,
    target_lang: str,
    user_en_attempt: str | None = None,
) -> dict[str, Any] | None:
    if not llm_available():
        return None
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    attempt_block = ""
    if user_en_attempt:
        attempt_block = f'\nSTUDENT {lang_name.upper()} ATTEMPT:\n"{user_en_attempt[:300]}"'
    system = SENTENCE_ANALYSIS_JSON_PROMPT.format(
        lang_name=lang_name,
        target_lang=target_lang,
        phrase_tr=phrase_tr[:400],
        attempt_block=attempt_block,
    )
    parsed = _llm_json(system, "Return the JSON object only.", max_tokens=520)
    if not parsed:
        return None
    natural = safe_str(parsed.get("natural_target")).strip()
    if not natural:
        return None
    pairs = parsed.get("phrase_pairs")
    if not isinstance(pairs, list):
        pairs = []
    clean_pairs: list[dict[str, str]] = []
    phrase_low = phrase_tr.lower()
    for item in pairs[:6]:
        if not isinstance(item, dict):
            continue
        tr = safe_str(item.get("tr")).strip()
        en = safe_str(item.get("en")).strip()
        if tr and en and tr.lower() in phrase_low:
            clean_pairs.append({"tr": tr, "en": en})
    if len(clean_pairs) < 2:
        clean_pairs = _phrase_vocab_breakdown(phrase_tr, target_lang, None) or clean_pairs

    alts = parsed.get("alternatives")
    alternatives = [safe_str(a).strip() for a in alts[:2]] if isinstance(alts, list) else []

    return {
        "natural_target": natural,
        "alternatives": [a for a in alternatives if a and a != natural][:2],
        "error_class": safe_str(parsed.get("error_class")).strip() or "N_A",
        "analysis_tr": safe_str(parsed.get("analysis_tr")).strip() or _build_rule_analysis_tr(
            phrase_tr, natural, clean_pairs, lang_name,
        ),
        "correction_needed": bool(parsed.get("correction_needed")),
        "wrong_phrase": safe_str(parsed.get("wrong_phrase")).strip() or None,
        "correct_phrase": safe_str(parsed.get("correct_phrase")).strip() or None,
        "correction_reason_tr": safe_str(parsed.get("correction_reason_tr")).strip() or None,
        "important_structure_tr": safe_str(parsed.get("important_structure_tr")).strip() or None,
        "phrase_pairs": clean_pairs,
        "practice_prompt_tr": safe_str(parsed.get("practice_prompt_tr")).strip()
        or f"Şimdi yüksek sesle söyle: \"{natural}\"",
    }


def _analyze_for_teaching(
    phrase_tr: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
    user_en_attempt: str | None = None,
) -> dict[str, Any]:
    llm = _try_llm_sentence_analysis(phrase_tr, target_lang, user_en_attempt)
    if llm:
        if not llm.get("phrase_pairs"):
            llm["phrase_pairs"] = _phrase_vocab_breakdown(phrase_tr, target_lang, translate_fn)
        if not llm.get("important_structure_tr"):
            llm["important_structure_tr"] = _rule_structure_tr(phrase_tr, LANG_NAMES.get(target_lang, target_lang))
        return llm
    return _rule_based_sentence_analysis(phrase_tr, target_lang, translate_fn, user_en_attempt)


def _format_teaching_response_tr(
    phrase_tr: str,
    analysis: dict[str, Any],
    lang_name: str,
) -> str:
    """Eğitim modülü standart analiz formatı."""
    parts: list[str] = []
    parts.append(f"🇹🇷 TÜRKÇE\n{phrase_tr.strip()}")

    natural = safe_str(analysis.get("natural_target")).strip()
    parts.append(f"\n🇬🇧 DOĞAL {lang_name.upper()}\n{natural}")

    alts = analysis.get("alternatives") or []
    if alts:
        alt_lines = "\n".join(f"• {a}" for a in alts[:2])
        parts.append(f"\nAlternatif:\n{alt_lines}")

    analysis_tr = safe_str(analysis.get("analysis_tr")).strip()
    if analysis_tr:
        parts.append(f"\n📝 CÜMLENİN ANALİZİ\n{analysis_tr}")

    parts.append("\n🔍 DÜZELTME")
    if analysis.get("correction_needed") and analysis.get("wrong_phrase"):
        parts.append(f"❌ {analysis['wrong_phrase']}")
        if analysis.get("correct_phrase"):
            parts.append(f"✅ {analysis['correct_phrase']}")
        if analysis.get("correction_reason_tr"):
            parts.append(safe_str(analysis["correction_reason_tr"]))
    else:
        err_cls = safe_str(analysis.get("error_class")).upper()
        if err_cls == "CORRECT" or err_cls == "N_A":
            parts.append("✅ Cümlen için doğal bir ifade hazırladım.")
            if alts:
                parts.append(f"Günlük konuşmada \"{alts[0]}\" de diyebilirsin.")
        elif err_cls == "NATURALNESS" and alts:
            parts.append("✅ Cümlen gramer olarak doğru.")
            parts.append(f"Daha doğal alternatif: \"{alts[0]}\"")
        else:
            parts.append("✅ Hedef cümle yukarıda.")

    structure = safe_str(analysis.get("important_structure_tr")).strip()
    if structure:
        parts.append(f"\n📚 ÖNEMLİ YAPI\n{structure}")

    pairs = analysis.get("phrase_pairs") or []
    if pairs:
        parts.append("\n🔤 KELİME VE İFADELER")
        for p in pairs:
            tr = safe_str(p.get("tr")).strip()
            en = safe_str(p.get("en")).strip()
            if tr and en:
                parts.append(f"• {tr} → {en}")

    practice = safe_str(analysis.get("practice_prompt_tr")).strip()
    parts.append(f"\n🗣️ ŞİMDİ SEN DENE\n{practice or 'Yukarıdaki cümleyi yüksek sesle söyle!'}")

    return "\n".join(parts)


def _vocab_breakdown_tr(phrase_tr: str, translate_fn: Callable[[str, str, str], str] | None = None) -> str:
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", phrase_tr.lower())
    lines: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in seen or len(w) < 2:
            continue
        seen.add(w)
        entry = TR_WORD_GLOSS.get(w)
        if entry:
            en, note = entry
            lines.append(f"  • \"{w}\" → {en} — {note}")
        elif translate_fn:
            try:
                en = translate_fn(w, "tr", "en")
                if en and en.lower() != w:
                    lines.append(f"  • \"{w}\" → {en}")
            except Exception:
                pass
    return "\n".join(lines) if lines else ""


def _vocab_breakdown_en(phrase_tr: str, phrase_en: str) -> str:
    words = re.findall(r"[\w']+", phrase_en)
    tr_map = {en: tr for tr, (en, _) in TR_WORD_GLOSS.items()}
    lines: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in ("i", "a", "the", "to", "in", "on", "at", "and", "is", "am", "will"):
            gloss = {
                "i": "I (subject)", "a": "a (indefinite article)", "the": "the (definite article)",
                "to": "to (direction / infinitive)", "will": "will (future tense marker)",
                "am": "am (present tense of 'be')", "is": "is (present tense of 'be')",
            }.get(lw, lw)
            lines.append(f"  • \"{w}\" — {gloss}")
        elif lw in tr_map:
            lines.append(f"  • \"{w}\" — Turkish: \"{tr_map[lw]}\"")
    if not lines:
        lines.append(f"  • Full sentence: \"{phrase_en}\"")
    return "\n".join(lines[:8])


def _recent_teacher_texts(history: list[dict], n: int = 4) -> list[str]:
    out: list[str] = []
    for h in history:
        if h.get("role") == "teacher":
            t = (h.get("text") or "").strip()
            if t:
                out.append(t)
        if len(out) >= n:
            break
    return out


def _recent_user_texts(history: list[dict], n: int = 4) -> list[str]:
    out: list[str] = []
    for h in history:
        if h.get("role") == "user":
            t = (h.get("text") or "").strip()
            if t:
                out.append(t)
        if len(out) >= n:
            break
    return out


def _is_yardim_request(text: str) -> bool:
    return bool(YARDIM_PREFIX_RE.search(text))


def _is_how_to_say_stuck(text: str) -> bool:
    """Öğrenci ne söyleyeceğini / nasıl kuracağını bilmiyor."""
    t = text.strip()
    if not t:
        return False
    if HOW_TO_SAY_STUCK_RE.search(t):
        return True
    low = t.lower()
    if re.search(r"nasıl\s+söyleyeceğim|ne\s+söyleyeceğim|cümleyi\s+nasıl", low):
        if re.search(r"bilmiyorum|bilemedim|bilemiyorum|kararsız|yardım", low):
            return True
    return False


HOW_TO_SAY_PREFIX_RE = re.compile(
    r"^(?:nasıl\s+söyleyeceğim(?:i)?\s+bilmiyorum|ne\s+söyleyeceğimi\s+bilmiyorum|"
    r"ne\s+demem\s+lazım|ne\s+desem\s+bilemedim|nasıl\s+söylesem\s+bilemedim|"
    r"cümleyi\s+nasıl\s+kur(?:acağım|abilirim|arım)|nasıl\s+söyleyebilirim|"
    r"söyleyemiyorum|don'?t\s+know\s+how\s+to\s+say|don'?t\s+know\s+what\s+to\s+say|"
    r"i\s+don'?t\s+know\s+(?:how|what)\s+(?:to\s+)?say|how\s+(?:can|do|should)\s+i\s+say\s+(?:this|it)?)"
    r"[,\s!:.-]*",
    re.I,
)


def _extract_phrase_from_how_to_say_stuck(text: str) -> str | None:
    """'Nasıl söyleyeceğimi bilmiyorum bugün okula gittim...' → Türkçe cümle parçası."""
    t = text.strip()
    if not t:
        return None
    m = re.search(
        r"(?:nasıl\s+söyleyeceğim(?:i)?\s+bilmiyorum|ne\s+söyleyeceğimi\s+bilmiyorum|"
        r"ne\s+demem\s+lazım|ne\s+desem\s+bilemedim|nasıl\s+söylesem\s+bilemedim|"
        r"cümleyi\s+nasıl\s+kur(?:acağım|abilirim|arım)|nasıl\s+söyleyebilirim|"
        r"don'?t\s+know\s+how\s+to\s+say|don'?t\s+know\s+what\s+to\s+say|"
        r"i\s+don'?t\s+know\s+(?:how|what)\s+(?:to\s+)?say)"
        r"[,\s!:.-]+(.+)$",
        t,
        re.I,
    )
    phrase = ""
    if m:
        phrase = m.group(1).strip(" ?.!")
    else:
        phrase = HOW_TO_SAY_PREFIX_RE.sub("", t).strip(" ?.!")
    if len(phrase) < 4:
        return None
    if not _is_real_turkish(phrase):
        return None
    return phrase


def _build_how_to_say_examples(
    teacher_q: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> list[tuple[str, str]]:
    """Son soruya göre söyleyebileceği örnek cümleler."""
    tq = teacher_q.lower()
    time_word = "yesterday" if "yesterday" in tq else "today"
    defaults_tr = {
        "I was tired today.": "Bugün yorgundum.",
        "I went to work today.": "Bugün işe gittim.",
        "I stayed at home today.": "Bugün evde kaldım.",
        "I read a book today.": "Bugün kitap okudum.",
    }

    if _is_daily_activity_question(tq) or re.search(
        r"what did you do|what do you do|how was your day|tell me about your day", tq,
    ):
        candidates = [
            (f"I was tired {time_word}.", defaults_tr["I was tired today."]),
            (f"I went to work {time_word}.", defaults_tr["I went to work today."]),
            (f"I stayed at home {time_word}.", defaults_tr["I stayed at home today."]),
            (f"I read a book {time_word}.", defaults_tr["I read a book today."]),
            ("It was good, thanks.", "İyiydi, teşekkürler."),
        ]
    elif re.search(r"book|read|reading", tq):
        candidates = [
            ("Yes, I like reading books.", "Evet, kitap okumayı seviyorum."),
            ("I read a book today.", "Bugün bir kitap okudum."),
            ("My favorite book is Harry Potter.", "En sevdiğim kitap Harry Potter."),
        ]
    elif re.search(r"how are you|how do you feel|how'?s it going", tq):
        candidates = [
            ("I'm fine, thanks. And you?", "İyiyim, teşekkürler. Sen nasılsın?"),
            ("I'm good.", "İyiyim."),
            ("I'm a bit tired today.", "Bugün biraz yorgunum."),
        ]
    elif re.search(r"what are you|what will you|plan|going to do", tq):
        candidates = [
            ("I'm going to work tomorrow.", "Yarın işe gideceğim."),
            ("I will stay at home.", "Evde kalacağım."),
            ("I want to rest.", "Dinlenmek istiyorum."),
        ]
    elif re.search(r"understand|mean", tq):
        candidates = [
            ("Yes, I understand.", "Evet, anlıyorum."),
            ("No, I don't understand.", "Hayır, anlamıyorum."),
            ("Can you explain again?", "Tekrar açıklar mısın?"),
        ]
    else:
        candidates = [
            ("Yes.", "Evet."),
            ("No, not really.", "Hayır, pek sayılmaz."),
            ("I think so.", "Sanırım öyle."),
            ("Can you repeat, please?", "Tekrar eder misin?"),
        ]

    out: list[tuple[str, str]] = []
    for en, tr_default in candidates[:5]:
        tr = tr_default
        if translate_fn:
            tr = _to_tr(en, translate_fn, target_lang) or tr_default
        out.append((en, tr))
    return out


def _curriculum_block(profile: dict) -> str:
    step = int(profile.get("lessonStep") or 0)
    step = max(0, min(step, len(LESSON_CURRICULUM) - 1))
    cur = LESSON_CURRICULUM[step]
    nxt = LESSON_CURRICULUM[min(step + 1, len(LESSON_CURRICULUM) - 1)]
    mastered = profile.get("masteredLessonTopics") or []
    if not isinstance(mastered, list):
        mastered = []
    taught = profile.get("taughtPatterns") or []
    if not isinstance(taught, list):
        taught = []
    return (
        f"LESSON STEP {step + 1}/{len(LESSON_CURRICULUM)}: {cur['title']}\n"
        f"Current focus: {cur['focus']}\n"
        f"Next step when ready: {nxt['title']} — {nxt['focus']}\n"
        f"Mastered topics: {', '.join(str(m) for m in mastered[-6:]) or 'none yet'}\n"
        f"Recently taught patterns: {', '.join(str(t) for t in taught[-4:]) or 'none yet'}"
    )


def _repeated_mistakes_summary(profile: dict, limit: int = 4) -> str:
    mistakes = profile.get("repeatedMistakes") or []
    if not isinstance(mistakes, list):
        return "none tracked yet"
    parts: list[str] = []
    for m in mistakes[-limit:]:
        if isinstance(m, dict):
            cat = safe_str(m.get("category") or m.get("type")).strip()
            if cat:
                parts.append(cat)
        elif isinstance(m, str) and m.strip():
            parts.append(m.strip())
    return ", ".join(parts) or "none tracked yet"


def _is_garbled_stt(text: str) -> bool:
    """STT anlamsız/bozuk — kullanıcı hatası sanma."""
    if not text or len(text.strip()) < 6:
        return False
    ul = text.lower().strip()
    if re.search(r"\b(law film|or dizzy|english law)\b", ul):
        return True
    if re.search(r"\b(dizzy|law)\b", ul) and re.search(r"\b(film|english|yes)\b", ul):
        if not re.search(r"\b(i|i'm|i am|love|like|watch)\b", ul):
            return True
    words = re.findall(r"[a-z']+", ul)
    if len(words) >= 4 and not re.search(
        r"\b(i|i'm|am|is|are|was|were|have|has|do|did|will|can|want|like|love|went|go)\b", ul,
    ):
        if re.search(r"\b(yes|english|law|film|or|dizzy|and|the|a)\b", ul):
            return True
    return False


def _detect_tr_meaning_mismatch(phrase_tr: str) -> dict[str, str] | None:
    """Ay/mevsim gibi anlam tutarsızlıkları."""
    low = phrase_tr.lower()
    if not re.search(r"mevsim", low):
        return None
    for tr_m, en_m in TR_MONTHS.items():
        if tr_m in low:
            season = "autumn" if tr_m in ("eylül", "ekim", "kasım", "kasim") else "summer"
            if tr_m in ("aralık", "ocak", "şubat"):
                season = "winter"
            if tr_m in ("mart", "nisan", "mayıs"):
                season = "spring"
            return {
                "month_tr": tr_m,
                "month_en": en_m,
                "season_en": season,
            }
    return None


def _fix_greeting_duplicate_you(text: str) -> tuple[str | None, str | None]:
    ul = text.lower()
    if re.search(r"(fine|good|great|ok|okay).{0,40}thank\s+you\s+you", ul):
        return (
            "Hey, I'm fine, thank you. How are you?",
            "Küçük düzeltme: \"How are you?\" sorusundan önce tekrar \"you\" demiyoruz.",
        )
    if re.search(r"thank\s+you\s+you\s+how", ul):
        return (
            "I'm fine, thank you. How are you?",
            "Küçük düzeltme: \"How are you?\" sorusundan önce tekrar \"you\" demiyoruz.",
        )
    return None, None


def _try_rule_greeting_fix(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Kural tabanlı selamlaşma düzeltmesi — AI yokken veya hızlı yol."""
    if target_lang != "en":
        return None
    correct, reason_tr = _fix_greeting_duplicate_you(user_text)
    if not correct:
        return None
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    teacher_en = (
        f"I'm good too, thank you!\n\n"
        f"I understood you well. Let's make it a bit more natural:\n\n"
        f"✅ \"{correct}\"\n\n"
        f"Now try saying it again 😊"
    )
    teacher_tr = (
        f"Seni gayet iyi anladım. Küçük bir düzeltme:\n\n"
        f"🇬🇧 {correct}\n\n"
        f"💡 {reason_tr}\n\n"
        f"🗣️ Şimdi tekrar söyle:\n\"{correct}\""
    )
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingPracticePhrase": correct,
        "pendingPracticeTr": "İyiyim, teşekkürler. Sen nasılsın?",
    }
    profile_patch = _record_mistake(profile, user_text, correct, "greeting")
    merged = merge_profile(profile, {**session_delta, **profile_patch})
    return _pack(
        merged, delta, teacher_en, teacher_tr, correct, 2, "ai_correction",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=correct,
        speak_tr=reason_tr or "",
        speak_tr_first=True,
        grammar_tr=reason_tr,
        phonetic_en=pronounce_text(correct, target_lang),
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct,
            "explainTr": reason_tr,
            "grammarTr": reason_tr,
            "category": "greeting",
            "level": 2,
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_stt_clarify_turn(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    history: list[dict],
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Bozuk STT — kesin cümle uydurma, kısa doğrulama sor."""
    if not _is_garbled_stt(user_text):
        return None
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    last_q = profile.get("lastTeacherText") or _last_teacher_question(history, profile) or ""
    hint = ""
    if re.search(r"\b(film|movie|series|english)\b", last_q, re.I) or re.search(
        r"\b(film|english|series)\b", user_text, re.I,
    ):
        hint = "English films and series"
    teacher_en = (
        "I think you said something about "
        + (hint or f"{lang_name}")
        + ", but the audio wasn't very clear.\n\n"
        "Did you mean something like: \"Yes, I love English films and series\"?\n\n"
        "Try saying it again slowly, or type it if you prefer."
    )
    teacher_tr = (
        "Ses tam net gelmedi — emin olmak istiyorum.\n\n"
        "Filmler/diziler hakkında mı konuşuyordun?\n"
        "Tekrar yavaşça söyleyebilir misin?"
    )
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingIntentConfirm": hint or "unclear speech",
        "pendingIntentUserSaid": user_text,
        "pendingIntentReason": "STT belirsiz — doğrulama bekleniyor",
    }
    merged = merge_profile(profile, delta)
    return _pack(
        merged, delta, teacher_en, teacher_tr, None, 1, "stt_clarify",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=teacher_en,
        speak_tr="Ses net gelmedi. Tekrar yavaşça söyler misin?",
        speak_tr_first=True,
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _meaning_error_help_mode(
    phrase_tr: str,
    mismatch: dict[str, str],
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any]:
    """Mevsim/ay karışıklığı — kısa öğretmen açıklaması."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    month_en = mismatch["month_en"]
    season_en = mismatch["season_en"]
    teacher_tr = (
        f"Küçük bir not 😊\n\n"
        f"{month_en} bir mevsim değil, bir aydır.\n\n"
        f"Eğer \"En sevdiğim ay {mismatch['month_tr'].title()}.\" demek istiyorsan:\n"
        f"🇬🇧 My favorite month is {month_en}.\n\n"
        f"Gerçekten bir mevsim söylemek istiyorsan:\n"
        f"🇬🇧 My favorite season is {season_en}.\n\n"
        f"Hangisini söylemek istedin?"
    )
    practice = f"My favorite month is {month_en}."
    teacher_en = practice
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingPracticePhrase": practice,
        "pendingPracticeTr": phrase_tr,
    }
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "help",
        waiting=True, user_text=phrase_tr, teacher_en=teacher_en, speak_text=practice,
        phonetic_en=pronounce_text(practice, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _how_to_say_stuck_short_mode(
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
    user_text: str = "",
) -> dict[str, Any]:
    """Sadece 'nasıl söyleyeceğimi bilmiyorum' — kısa yardım, uzun analiz yok."""
    phrases = {
        "en": "I don't know how to say it.",
        "de": "Ich weiß nicht, wie man das sagt.",
        "fr": "Je ne sais pas comment le dire.",
        "es": "No sé cómo decirlo.",
        "ru": "Я не знаю, как это сказать.",
        "ka": "არ ვიცი როგორ ვთქვა.",
        "it": "Non so come dirlo.",
    }
    phrase_en = phrases.get(target_lang, phrases["en"])
    tr_meaning = "Bunu nasıl söyleyeceğimi bilmiyorum."
    teacher_en = phrase_en
    teacher_tr = (
        f"No problem! 😊 Tell me in Turkish — I'll help you say it in English.\n\n"
        f"🇬🇧 You can say:\n\"{phrase_en}\"\n\n"
        f"🇹🇷 {tr_meaning}\n\n"
        f"🗣️ Şimdi benimle tekrar et:\n\"{phrase_en}\""
    )
    delta = {
        **session_delta,
        "lastTeacherText": phrase_en,
        "pendingPracticePhrase": phrase_en,
        "pendingPracticeTr": tr_meaning,
    }
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "help",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=phrase_en,
        phonetic_en=pronounce_text(phrase_en, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _turkish_help_coach_mode(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any]:
    """Türkçe yardım niyeti — kısa rehber, uzun analiz değil."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    teacher_tr = (
        f"Tabii 😊\n\n"
        f"{lang_name} konuşurken aklına Türkçe bir şey gelirse bana Türkçe söyleyebilirsin.\n\n"
        f"Ben sana:\n"
        f"1. {lang_name} karşılığını söyleyeceğim\n"
        f"2. Doğal kullanımını öğreteceğim\n"
        f"3. Tekrar etmeni isteyeceğim\n"
        f"4. Sonra sohbete devam edeceğiz\n\n"
        f"Söylemek istediğin cümleyi Türkçe söyle — birlikte {lang_name}'ye çevirelim."
    )
    teacher_en = (
        f"Sure! If a Turkish sentence comes to mind, tell me in Turkish.\n"
        f"I'll give you the natural {lang_name} version, help you practice it, "
        f"and then we'll keep chatting."
    )
    delta = {**session_delta, "lastTeacherText": teacher_en}
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "coach_tr",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=teacher_en,
        speak_tr="Türkçe söyle, birlikte çevirelim.",
        speak_tr_first=True,
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _format_compact_help(
    phrase_tr: str,
    natural: str,
    lang_name: str,
    note_tr: str | None = None,
) -> str:
    """Kısa öğretmen formatı — uzun analiz raporu değil."""
    parts: list[str] = []
    if note_tr:
        parts.append(note_tr)
    parts.append(f"🇬🇧 {natural}")
    parts.append(f"\n🇹🇷 {phrase_tr.strip()}")
    parts.append(f"\n🗣️ Şimdi benimle tekrar et:\n\"{natural}\"")
    return "\n".join(parts)


def _advance_lesson_on_success(profile: dict, user_text: str, corr_level: int) -> dict[str, Any]:
    """Başarılı pratik sonrası ders adımını ilerlet."""
    patch: dict[str, Any] = {}
    step = int(profile.get("lessonStep") or 0)
    if corr_level == 1 and len(user_text.split()) >= 3:
        mastered = list(profile.get("masteredLessonTopics") or [])
        if step < len(LESSON_CURRICULUM):
            topic_id = LESSON_CURRICULUM[step]["id"]
            if topic_id not in mastered:
                mastered.append(topic_id)
            patch["masteredLessonTopics"] = mastered[-20:]
            if step < len(LESSON_CURRICULUM) - 1:
                patch["lessonStep"] = step + 1
    return patch


def _micro_chain_block(profile: dict) -> str:
    step = int(profile.get("microStep") or 0)
    step = max(0, min(step, len(GREETING_MICRO_CHAIN) - 1))
    cur = GREETING_MICRO_CHAIN[step]
    last = safe_str(profile.get("lastMasteredPhrase")).strip()
    build = safe_str(profile.get("sentenceBuildBase")).strip()
    lines = [
        f"MICRO CHAIN step {step + 1}/{len(GREETING_MICRO_CHAIN)}: target \"{cur['en']}\"",
        f"Next to teach when ready: {cur.get('teach_next') or '(continue conversation)'}",
    ]
    if last:
        lines.append(f"Last mastered phrase: \"{last}\" — BUILD ON THIS, do not reset.")
    if build:
        lines.append(f"Sentence build base: \"{build}\" — extend with SHORT → LONGER.")
    return "\n".join(lines)


def _is_simple_acknowledgment(text: str) -> bool:
    ul = re.sub(r"[^\w\s']", "", text.lower()).strip()
    if ul in ("okay", "ok", "k", "yes", "yeah", "yep", "sure", "alright", "yup", "fine"):
        return True
    return bool(re.match(r"^(tamam|evet|olur|peki)$", ul))


def _is_progress_confirmation(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(
        r"evet.*söylemek\s+istedim|onu\s+söylemek\s+istedim|aynen\s+öyle|tam\s+olarak|"
        r"that'?s\s+what\s+i\s+meant|exactly|yes\s+that'?s\s+right",
        t,
        re.I,
    ):
        return True
    return bool(re.search(r"^evet[,\s]", t.lower()) and re.search(r"istedim|demek istedim", t.lower()))


def _next_reading_build(base: str) -> str | None:
    b = base.strip().rstrip(".")
    for i, phrase in enumerate(READING_BUILD_CHAIN):
        if _norm(phrase.rstrip(".")) == _norm(b) and i + 1 < len(READING_BUILD_CHAIN):
            return READING_BUILD_CHAIN[i + 1]
    for i, phrase in enumerate(READING_BUILD_CHAIN):
        if b.lower() in phrase.lower() or phrase.lower() in b.lower():
            if i + 1 < len(READING_BUILD_CHAIN):
                return READING_BUILD_CHAIN[i + 1]
    return None


def _try_okay_guidance_turn(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """'Okay' yanlış değil — hedef ifadeyi henüz söylemedi, yönlendir."""
    if not _is_simple_acknowledgment(user_text):
        return None
    target = (
        safe_str(profile.get("awaitingTargetPhrase")).strip()
        or safe_str(profile.get("pendingPracticePhrase")).strip()
    )
    if not target:
        return None
    teacher_en = (
        f"Okay! 😊 Now let's practice the phrase I taught you:\n\n"
        f"\"{target}\"\n\n"
        f"Can you say it?"
    )
    teacher_tr = f"Tamam! Şimdi öğrettiğim ifadeyi dene: \"{target}\""
    delta = {**session_delta, "lastTeacherText": teacher_en, "awaitingTargetPhrase": target}
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "practice_prompt",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=target,
        speak_tr=f"Şimdi söyle: {target}"[:120],
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_progress_confirm_turn(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Öğrenci anladığını onayladı — geriye dönme, üzerine inşa et."""
    if not _is_progress_confirmation(user_text):
        return None
    base = (
        safe_str(profile.get("lastMasteredPhrase")).strip()
        or safe_str(profile.get("sentenceBuildBase")).strip()
        or "I am reading a book."
    )
    extended = _next_reading_build(base) or "I am reading a book today."
    teacher_en = (
        f"Exactly! That's what you meant. Great!\n\n"
        f"Now let's build on it:\n\"{extended}\"\n\n"
        f"Try saying it."
    )
    teacher_tr = f"Aynen! Şimdi cümleyi biraz uzatalım: \"{extended}\""
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "sentenceBuildBase": base,
        "pendingPracticePhrase": extended,
        "pendingPracticeTr": "Bugün evde kitap okuyorum.",
        "awaitingTargetPhrase": extended,
    }
    patch = _advance_lesson_on_success(profile, extended, 1)
    merged = merge_profile(profile, {**session_delta, **delta, **patch})
    return _pack(
        merged, delta, teacher_en, teacher_tr, None, 1, "build_forward",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=extended,
        phonetic_en=pronounce_text(extended, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_reading_fragment_teaching(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    if target_lang != "en":
        return None
    ul = user_text.lower()
    if not re.search(r"today.*read|read.*book|reading book", ul):
        return None
    if re.search(r"\bi am reading a book today\b", ul):
        return None
    correct = "I am reading a book today."
    teacher_en = (
        "Yes, I understand what you mean. 😊\n\n"
        "You want to say you are reading a book today, maybe.\n\n"
        f"✅ \"{correct}\"\n\n"
        "Notice: I + am + reading — because you're talking about now.\n\n"
        f"Now you try: \"{correct}\""
    )
    teacher_tr = "Anladım. Şimdi olan biten için: I + am + reading kullan."
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingPracticePhrase": correct,
        "sentenceBuildBase": correct,
        "lastMasteredPhrase": correct,
        "awaitingTargetPhrase": correct,
    }
    return _pack(
        profile, delta, teacher_en, teacher_tr, correct, 2, "ai_correction",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=correct,
        speak_tr="I am reading a book today — şimdi dene.",
        grammar_tr="Şu an için: I + am + fiil-ing",
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct,
            "grammarTr": "I + am + reading (şu an)",
            "inferredMeaning": "Bugün kitap okuyorum demek istedin.",
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_children_plural_teaching(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    if target_lang != "en":
        return None
    if not re.search(r"children'?s?\s+are?\s+read", user_text, re.I):
        return None
    correct = "The children are reading a book."
    teacher_en = (
        "Almost! 😊\n\n"
        "• child = one child\n"
        "• children = two or more\n"
        "• children's = belongs to children (not what we need here)\n\n"
        f"✅ \"{correct}\"\n\n"
        "Now you try."
    )
    teacher_tr = (
        "child = bir çocuk, children = çocuklar. "
        "children's = çocukların (sahiplik). Burada: The children are..."
    )
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingPracticePhrase": correct,
        "awaitingTargetPhrase": correct,
    }
    profile_patch = _record_mistake(profile, user_text, correct, "word_choice")
    merged = merge_profile(profile, {**session_delta, **profile_patch})
    return _pack(
        merged, delta, teacher_en, teacher_tr, correct, 2, "ai_correction",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=correct,
        speak_tr="The children are reading a book — tekrar dene.",
        grammar_tr=teacher_tr,
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct,
            "grammarTr": teacher_tr,
            "category": "word_choice",
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_students_correct_extend(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    if target_lang != "en":
        return None
    ul = user_text.lower().strip()
    if not re.search(r"\bstudents?\s+are\s+reading\s+a?\s*book", ul):
        return None
    extended = "The students are reading a book in the classroom today."
    teacher_en = (
        f"Excellent! That's correct. ✅\n\n"
        f"\"{user_text.strip()}\"\n\n"
        f"Let's make it a bit longer:\n\"{extended}\"\n\n"
        f"Where are they reading?"
    )
    teacher_tr = "Doğru! Şimdi cümleyi uzatalım."
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "lastMasteredPhrase": user_text.strip(),
        "sentenceBuildBase": user_text.strip().rstrip("."),
        "pendingPracticePhrase": extended,
        "awaitingTargetPhrase": extended,
        "correctSentences": profile.get("correctSentences", 0) + 1,
    }
    merged = merge_profile(profile, delta)
    return _pack(
        merged, delta, teacher_en, teacher_tr, None, 1, "build_forward",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=extended,
        phonetic_en=pronounce_text(extended, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_pronunciation_feedback_turn(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    history: list[dict],
    speak_slow: bool,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    if not PRONUNCIATION_FEEDBACK_RE.search(user_text):
        return None
    phrase = (
        safe_str(profile.get("pendingPracticePhrase")).strip()
        or safe_str(profile.get("lastMasteredPhrase")).strip()
        or "I'm fine, thank you."
    )
    teacher_en = (
        "Thanks for telling me! I'll say it more slowly and clearly.\n\n"
        f"\"{phrase}\"\n\n"
        "Listen: I'm / fine / thank / you."
    )
    teacher_tr = "Daha yavaş ve net söylüyorum — dinle ve tekrar et."
    delta = {**session_delta, "lastTeacherText": teacher_en}
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "slow",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=phrase,
        speak_slow=True,
        phonetic_en=pronounce_text(phrase, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_repeated_weakness_turn(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    if target_lang != "en":
        return None
    if not re.search(r"\bi want go\b", user_text, re.I):
        return None
    correct = "I want to go home."
    if re.search(r"\bhome\b", user_text, re.I):
        correct = "I want to go home."
    elif re.search(r"\beat\b", user_text, re.I):
        correct = "I want to eat."
    teacher_en = (
        "Remember our little rule? 😊\n\n"
        "want + to + verb\n\n"
        f"✅ \"{correct}\"\n\n"
        "Try: \"I want to eat.\" — now your turn."
    )
    teacher_tr = "Hatırla: want + to + fiil. I want to go / I want to eat."
    profile_patch = _record_mistake(profile, user_text, correct, "grammar")
    merged = merge_profile(profile, {**session_delta, **profile_patch})
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "pendingPracticePhrase": correct,
        "awaitingTargetPhrase": correct,
    }
    return _pack(
        merged, delta, teacher_en, teacher_tr, correct, 2, "review_error",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=correct,
        speak_tr="want + to + fiil — tekrar dene.",
        grammar_tr="want + to + verb kuralını hatırla.",
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct,
            "grammarTr": "want + to + fiil",
            "category": "grammar",
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _try_hello_chain_success(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Selamlaşma zincirinde başarı — bir sonraki mikro ifadeyi öğret."""
    if target_lang != "en":
        return None
    ul = user_text.lower().strip()
    step = int(profile.get("microStep") or 0)
    step = max(0, min(step, len(GREETING_MICRO_CHAIN) - 1))
    cur = GREETING_MICRO_CHAIN[step]
    matched = _practice_phrase_match(user_text, cur["en"]) or _norm(ul) == _norm(cur["en"].rstrip("."))
    if not matched:
        if step == 2 and re.search(r"\bi'?m fine\b", ul) and "thank" not in ul:
            matched = True
        elif step == 3 and re.search(r"\bi'?m fine.*thank", ul):
            matched = True
    if not matched:
        return None
    nxt = cur.get("teach_next") or ""
    if not nxt:
        return None
    nxt_entry = next((m for m in GREETING_MICRO_CHAIN if m["en"].rstrip(".?") == nxt.rstrip(".?") or m["en"] == nxt), None)
    teach_tr = nxt_entry["tr"] if nxt_entry else ""
    teacher_en = (
        f"Great! \"{cur['en']}\" — well done.\n\n"
        f"Now let's learn something new:\n\"{nxt}\"\n\n"
        f"Try saying it."
    )
    teacher_tr = teach_tr or f"Yeni ifade: {nxt}"
    new_step = step + 1 if step + 1 < len(GREETING_MICRO_CHAIN) else step
    delta = {
        **session_delta,
        "lastTeacherText": teacher_en,
        "lastMasteredPhrase": cur["en"],
        "pendingPracticePhrase": nxt,
        "awaitingTargetPhrase": nxt,
        "microStep": new_step,
        "correctSentences": profile.get("correctSentences", 0) + 1,
    }
    merged = merge_profile(profile, delta)
    return _pack(
        merged, delta, teacher_en, teacher_tr, None, 1, "micro_teach",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=nxt,
        phonetic_en=pronounce_text(nxt, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _trim_teacher_tr(teacher_en: str, teacher_tr: str) -> str:
    """Türkçe panel İngilizce cevabı tekrar etmesin."""
    tr = teacher_tr.strip()
    if not tr or len(tr) < 120:
        return tr
    en_lines = [ln.strip() for ln in teacher_en.split("\n") if ln.strip() and not ln.strip().startswith("✅")]
    for ln in en_lines[:3]:
        if len(ln) > 15 and ln.lower()[:20] in tr.lower():
            return tr[:200] + ("..." if len(tr) > 200 else "")
    return tr


def _how_to_say_help_mode(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
    history: list[dict],
) -> dict[str, Any]:
    """Ne söyleyeceğini / nasıl kuracağını bilmiyor — bağlama göre örnek cümleler."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    last_teacher = profile.get("lastTeacherText") or _last_teacher_question(history, profile) or ""
    examples = _build_how_to_say_examples(last_teacher, target_lang, translate_fn)

    parts = ["🤔 Anladım — ne söyleyeceğini bulmak zor olabilir.\n"]
    if last_teacher:
        parts.append(f"💬 Son {lang_name} sorum:\n\"{last_teacher}\"")
        if translate_fn:
            tr_q = _to_tr(last_teacher, translate_fn, target_lang)
            if tr_q:
                parts.append(f"🇹🇷 {tr_q}")
        parts.append("")

    parts.append("📝 Söyleyebileceğin örnek cümleler:\n")
    for i, (en, tr) in enumerate(examples[:4], 1):
        parts.append(f"{i}️⃣ \"{en}\"\n   🇹🇷 {tr}")

    parts.append(
        "\n🧩 Cümle nasıl kurulur?\n"
        "• Özne (I) + fiil (am/was/went/read/like...) + detay\n"
        "• Zaman kelimesi genelde sonda: today, yesterday, tomorrow\n"
        "• Örnek kalıp: I + was/went/read + today"
    )
    parts.append(
        "\n\n💡 Kendi cümleni kurmak için Türkçe yaz:\n"
        "\"yardım ben bugün işe gittim\" — sana özel cümle kurarım.\n\n"
        "🔄 Yukarıdan birini dene veya yardım ile kendi cümleni sor!"
    )

    teacher_tr = "\n".join(parts)
    first_en = examples[0][0] if examples else ""
    clear = {
        "pendingPracticePhrase": None,
        "pendingPracticeTr": None,
        "pendingIntentConfirm": None,
        "pendingIntentUserSaid": None,
        "pendingIntentReason": None,
    }
    delta = {
        **session_delta,
        **clear,
        "lastTeacherText": first_en or last_teacher,
    }
    merged = merge_profile(profile, delta)
    result = _pack(
        merged, delta, first_en, teacher_tr, None, 1, "help",
        waiting=True, user_text=user_text, teacher_en=first_en,
        speak_text=first_en,
        speak_tr="",
        speak_tr_first=False,
        phonetic_en=_simple_en_phonetic(first_en) if first_en else "",
        translate_fn=translate_fn,
        target_lang=target_lang,
    )
    result["help_tts_pairs"] = [{"tr": tr, "en": en} for en, tr in examples[:4]]
    return result


def _normalize_stt_text(text: str) -> str:
    """Ses tanıma hatalarını düzelt — doğru cümleleri bozma."""
    t = text.strip()
    if not t:
        return t
    tl = t.lower()
    # Tek kelime / bariz STT hataları
    single_fixes = {
        "slipping": "sleeping", "slipin": "sleeping", "sleepin": "sleeping",
        "ayran": "I run", "iron": "I run", "airen": "I run",
        "eye run": "I run", "ay run": "I run", "hey run": "I run",
        "ay book": "a book", "i book": "I read a book",
    }
    if tl in single_fixes:
        return single_fixes[tl]
    fixes = (
        (r"\bslipping\b", "sleeping"),
        (r"\bslipin\b", "sleeping"),
        (r"\bsleepin\b", "sleeping"),
        (r"\btoday i\b", "today I"),
    )
    for pat, rep in fixes:
        t = re.sub(pat, rep, t, flags=re.I)
    return t.strip()


def _is_real_turkish(text: str) -> bool:
    """Gerçek Türkçe mi — kırık İngilizce parçalarını Türkçe sayma."""
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", text):
        return True
    if re.search(
        r"\b(merhaba|nasılsın|nasilsin|teşekkür|teşekkürler|evet|hayır|tamam|iyiyim|"
        r"günaydın|neler|yapıyorum|yapıyorsun|yaptım|gittim|yorgunum|istiyorum|"
        r"istemiyorum|bugün|yarın|dün|çünkü|için|lütfen|anlamadım|kitap|okudum|"
        r"geldim|konuştum|dedim|sandım|galiba|belki|çok|biraz|koştum|kosdum|"
        r"koşuyorum|yürüdüm|izledim|çalıştım|evde kaldım|parka gittim)\b",
        text,
        re.I,
    ):
        return True
    # Tek İngilizce kelime / kırık parça → Türkçe değil
    if re.search(r"\b(book|read|park|work|home|tired|hello|yes|no|today|yesterday|run|ran)\b", text, re.I):
        if not re.search(r"[ğüşıöçĞÜŞİÖÇ]", text):
            return False
    return bool(re.search(r"\b(ben|sen|biz|siz|onlar|için|ile|de|da|ki|mi|mı|mu|mü)\b", text, re.I))


def looks_like_lang(text: str, lang: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if lang == "tr":
        if re.search(r"[ğüşıöçĞÜŞİÖÇ]", t):
            return True
        return bool(re.search(
            r"neler|yapıyor|yapıyorsun|yapiyorsun|nasıl|merhaba|nasılsın|nasilsin|"
            r"teşekkür|evet|hayır|tamam|iyiyim|güzel|ben|sen|\bne\b|neden|günaydın",
            t,
            re.I,
        ))
    if lang == "en":
        return bool(re.search(
            r"\b(what|how|are|you|doing|hello|thanks|thank|yes|no|good|please|fine|"
            r"where|when|who|why|the|this|that|is|are|was|were|your|holiday|i'm|im|"
            r"i|a|an|book|read|went|work|tired|today|yesterday|park|home|ate|had|"
            r"played|watched|walked|studied|spoke|said|like|want|need|have|did|don't|"
            r"understand|run|ran|running|very|so|just|only|also|then|well|now)\b",
            t,
            re.I,
        ))
    if lang == "ka":
        return bool(re.search(r"[\u10A0-\u10FF]", t))
    if lang == "ru":
        return bool(re.search(r"[\u0400-\u04FF]", t))
    if lang == "de":
        return bool(re.search(r"\b(hallo|guten|danke|bitte|ja|nein)\b", t, re.I))
    if lang == "fr":
        return bool(re.search(r"\b(bonjour|merci|oui|non|comment)\b", t, re.I))
    if lang == "es":
        return bool(re.search(r"\b(hola|gracias|buenos|sí|si|no)\b", t, re.I))
    if lang == "ar":
        return bool(re.search(r"[\u0600-\u06FF]", t))
    if lang == "it":
        return bool(re.search(r"\b(ciao|grazie|buongiorno|si|no)\b", t, re.I))
    if lang == "zh":
        return bool(re.search(r"[\u4e00-\u9fff]", t))
    return False


def _last_teacher_question(history: list[dict], profile: dict) -> str:
    for h in history:
        if h.get("role") == "teacher":
            t = (h.get("text") or "").strip()
            if "?" in t:
                return t
    return (profile.get("lastTeacherText") or "").strip()


def _is_daily_activity_question(q: str) -> bool:
    ql = q.lower()
    return bool(re.search(
        r"what did you do|what do you do|what have you done|tell me about your day|"
        r"what happened|how was your day|what were you doing|did you do anything|"
        r"what are you planning|what will you|what are you going to|what else are you|"
        r"what do you want to do|plans for|bugün ne|neler yapt|ne planlıyorsun",
        ql,
    ))


def _question_time_mode(teacher_q: str) -> str:
    """Öğretmen sorusuna göre zaman: plan / geçmiş / şimdi."""
    ql = teacher_q.lower()
    if re.search(
        r"plan|planning|going to do|will you|what will|what are you going|what else|"
        r"want to do|plans for|tomorrow|later today",
        ql,
    ):
        return "plan"
    if re.search(
        r"did you do|what did|yesterday|last night|were you|what have you done|"
        r"how was your day|what happened",
        ql,
    ):
        return "past"
    if re.search(r"are you doing|right now|at the moment|\bnow\b", ql):
        return "present"
    return "default"


# Tek kelime / -ing / STT hataları → kök aktivite
ACTIVITY_ALIASES: dict[str, str] = {
    "sleeping": "sleep", "slept": "sleep", "sleepy": "sleep", "slipping": "sleep",
    "slip": "sleep", "slipin": "sleep", "sleepin": "sleep",
    "running": "run", "ran": "run", "jogging": "run", "jog": "run",
    "reading": "read", "readed": "read",
    "working": "work", "worked": "work",
    "studying": "study", "studied": "study",
    "eating": "eat", "ate": "eat", "eaten": "eat",
    "watching": "watch", "watched": "watch", "tv": "watch",
    "walking": "walk", "walked": "walk",
    "playing": "play", "played": "play",
    "resting": "rest", "rested": "rest", "relaxing": "relax", "relaxed": "relax",
    "shopping": "shop", "shopped": "shop",
    "cooking": "cook", "cooked": "cook",
    "cleaning": "clean", "cleaned": "clean",
    "swimming": "swim", "swam": "swim",
    "nothing": "nothing",
    "home": "home", "house": "home",
    "book": "read", "books": "read",
    "park": "park", "gym": "exercise", "exercising": "exercise", "exercise": "exercise",
    "tired": "tired", "exhausted": "tired",
}

ACTIVITY_INFERENCES: dict[str, dict[str, tuple[str, str]]] = {
    "sleep": {
        "plan": ("I'm going to sleep.", "Uyumayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I was sleeping.", "Uyuyordum demek istemiş olabilirsin."),
        "present": ("I'm sleeping.", "Uyuyorum demek istemiş olabilirsin."),
        "default": ("I slept.", "Uyudum demek istemiş olabilirsin."),
    },
    "run": {
        "plan": ("I'm going for a run.", "Koşuya çıkmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I went for a run today.", "Bugün koştum demek istemiş olabilirsin."),
        "present": ("I'm running.", "Koşuyorum demek istemiş olabilirsin."),
        "default": ("I ran today.", "Bugün koştum demek istemiş olabilirsin."),
    },
    "read": {
        "plan": ("I'm going to read a book.", "Kitap okumayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I read a book today.", "Bugün kitap okudum demek istemiş olabilirsin."),
        "present": ("I'm reading a book.", "Kitap okuyorum demek istemiş olabilirsin."),
        "default": ("I read a book today.", "Kitap okudum demek istemiş olabilirsin."),
    },
    "work": {
        "plan": ("I'm going to work.", "İşe gideceğim demek istemiş olabilirsin."),
        "past": ("I went to work today.", "Bugün işe gittim demek istemiş olabilirsin."),
        "present": ("I'm working.", "Çalışıyorum demek istemiş olabilirsin."),
        "default": ("I worked today.", "Bugün çalıştım demek istemiş olabilirsin."),
    },
    "study": {
        "plan": ("I'm going to study.", "Ders çalışmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I studied today.", "Bugün ders çalıştım demek istemiş olabilirsin."),
        "present": ("I'm studying.", "Ders çalışıyorum demek istemiş olabilirsin."),
        "default": ("I studied today.", "Ders çalıştım demek istemiş olabilirsin."),
    },
    "eat": {
        "plan": ("I'm going to eat.", "Yemek yemeyi planlıyorsun demek istemiş olabilirsin."),
        "past": ("I ate at home today.", "Bugün evde yemek yedim demek istemiş olabilirsin."),
        "present": ("I'm eating.", "Yemek yiyorum demek istemiş olabilirsin."),
        "default": ("I ate today.", "Yemek yedim demek istemiş olabilirsin."),
    },
    "watch": {
        "plan": ("I'm going to watch TV.", "Televizyon izlemeyi planlıyorsun demek istemiş olabilirsin."),
        "past": ("I watched TV today.", "Bugün televizyon izledim demek istemiş olabilirsin."),
        "present": ("I'm watching TV.", "Televizyon izliyorum demek istemiş olabilirsin."),
        "default": ("I watched TV today.", "Televizyon izledim demek istemiş olabilirsin."),
    },
    "walk": {
        "plan": ("I'm going for a walk.", "Yürüyüş yapmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I walked today.", "Bugün yürüdüm demek istemiş olabilirsin."),
        "present": ("I'm walking.", "Yürüyorum demek istemiş olabilirsin."),
        "default": ("I walked today.", "Yürüdüm demek istemiş olabilirsin."),
    },
    "play": {
        "plan": ("I'm going to play.", "Oynamayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I played today.", "Bugün oynadım demek istemiş olabilirsin."),
        "present": ("I'm playing.", "Oynuyorum demek istemiş olabilirsin."),
        "default": ("I played today.", "Oynadım demek istemiş olabilirsin."),
    },
    "rest": {
        "plan": ("I'm going to rest.", "Dinlenmeyi planlıyorsun demek istemiş olabilirsin."),
        "past": ("I rested today.", "Bugün dinlendim demek istemiş olabilirsin."),
        "present": ("I'm resting.", "Dinleniyorum demek istemiş olabilirsin."),
        "default": ("I rested today.", "Dinlendim demek istemiş olabilirsin."),
    },
    "relax": {
        "plan": ("I'm going to relax.", "Rahatlamayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I relaxed today.", "Bugün dinlendim demek istemiş olabilirsin."),
        "present": ("I'm relaxing.", "Rahatlıyorum demek istemiş olabilirsin."),
        "default": ("I relaxed today.", "Dinlendim demek istemiş olabilirsin."),
    },
    "shop": {
        "plan": ("I'm going shopping.", "Alışveriş yapmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I went shopping today.", "Bugün alışveriş yaptım demek istemiş olabilirsin."),
        "present": ("I'm shopping.", "Alışveriş yapıyorum demek istemiş olabilirsin."),
        "default": ("I went shopping today.", "Alışveriş yaptım demek istemiş olabilirsin."),
    },
    "home": {
        "plan": ("I'm going to stay home.", "Evde kalmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I stayed at home today.", "Bugün evde kaldım demek istemiş olabilirsin."),
        "present": ("I'm at home.", "Evdeyim demek istemiş olabilirsin."),
        "default": ("I stayed at home today.", "Evde kaldım demek istemiş olabilirsin."),
    },
    "park": {
        "plan": ("I'm going to the park.", "Parka gitmeyi planlıyorsun demek istemiş olabilirsin."),
        "past": ("I went to the park today.", "Bugün parka gittim demek istemiş olabilirsin."),
        "present": ("I'm at the park.", "Parktayım demek istemiş olabilirsin."),
        "default": ("I went to the park today.", "Parka gittim demek istemiş olabilirsin."),
    },
    "exercise": {
        "plan": ("I'm going to exercise.", "Spor yapmayı planlıyorsun demek istemiş olabilirsin."),
        "past": ("I exercised today.", "Bugün spor yaptım demek istemiş olabilirsin."),
        "present": ("I'm exercising.", "Spor yapıyorum demek istemiş olabilirsin."),
        "default": ("I exercised today.", "Spor yaptım demek istemiş olabilirsin."),
    },
    "tired": {
        "plan": ("I'm going to rest because I'm tired.", "Yorgunum, dinleneceğim demek istemiş olabilirsin."),
        "past": ("I was very tired today.", "Bugün çok yorgundum demek istemiş olabilirsin."),
        "present": ("I'm tired.", "Yorgunum demek istemiş olabilirsin."),
        "default": ("I was very tired today.", "Çok yorgundum demek istemiş olabilirsin."),
    },
    "nothing": {
        "plan": ("I'm not planning anything special.", "Özel bir planım yok demek istemiş olabilirsin."),
        "past": ("I didn't do much today.", "Bugün pek bir şey yapmadım demek istemiş olabilirsin."),
        "present": ("I'm not doing anything.", "Hiçbir şey yapmıyorum demek istemiş olabilirsin."),
        "default": ("I didn't do much today.", "Pek bir şey yapmadım demek istemiş olabilirsin."),
    },
}


def _extract_activity_token(text: str) -> str | None:
    """Tek kelime veya 'I sleeping' gibi kısa parçadan aktivite kökü çıkar."""
    ul = re.sub(r"[^\w\s']", "", text.lower().strip())
    words = ul.split()
    if not words:
        return None
    candidates: list[str] = []
    if len(words) == 1:
        candidates = [words[0]]
    elif len(words) == 2 and words[0] in ("i", "im", "i'm", "a", "the"):
        candidates = [words[1]]
    elif len(words) <= 3:
        candidates = [w for w in words if w not in ("i", "im", "i'm", "a", "an", "the", "am", "was")]
    else:
        return None
    for token in candidates:
        root = ACTIVITY_ALIASES.get(token, token)
        if root in ACTIVITY_INFERENCES:
            return root
    return None


def _infer_from_activity_token(user_text: str, teacher_q: str) -> tuple[str | None, str | None]:
    root = _extract_activity_token(user_text)
    if not root:
        return None, None
    mode = _question_time_mode(teacher_q)
    entries = ACTIVITY_INFERENCES[root]
    if mode in entries:
        return entries[mode]
    return entries.get("default", next(iter(entries.values())))


def _is_fragment_attempt(text: str) -> bool:
    t = text.strip()
    if len(t) < 2:
        return True
    words = t.split()
    if len(words) <= 2:
        return True
    ul = t.lower()
    has_verb = bool(re.search(
        r"\b(is|are|am|was|were|have|has|had|do|does|did|will|can|could|"
        r"went|go|going|read|played|ate|watched|walked|studied|spoke|said|"
        r"don't|didn't|wasn't|i'm|i've)\b",
        ul,
    ))
    has_noun_only = bool(re.search(
        r"\b(book|books|park|work|home|food|movie|tv|game|gym|school|friend)\b",
        ul,
    ))
    if has_noun_only and not has_verb:
        return True
    if re.search(r"^(i|a|an|the)\s+\w+$", ul) and len(words) <= 3:
        return True
    # Öğrenici hatası: I am run / I am go (yanlış yapı ama fiil var sanılıyor)
    if re.search(r"\bi am (run|ran|go|read|walk|play|eat|work|swim|watch|book)\b", ul):
        return True
    if re.search(r"\bi (run|ran|walk|read|play|eat|swim)\b", ul) and len(words) <= 4:
        return True
    if re.search(r"^(yes|yeah|yep|no|ok|okay)\s+(understand|like|read|want|have|know|love)", ul):
        return True
    if re.search(r"^(understand|like|read|want|have|know|love)\s+", ul):
        return True
    return False


def _is_broken_learner_english(text: str) -> bool:
    """Gramer olarak eksik/kırık öğrenici cümlesi — AI sohbete geçmeden önce yakala."""
    if not text or not looks_like_lang(text, "en"):
        return False
    if _is_greeting_or_small_talk(text) or _is_polite_acknowledgment(text):
        return False
    if _is_clear_activity_answer(text):
        return False
    return _is_fragment_attempt(text)


def _is_yes_reply(text: str) -> bool:
    ul = re.sub(r"[^\w\s']", "", text.strip().lower())
    if not ul:
        return False
    words = ul.split()
    if words[0] in ("yes", "yeah", "yep", "yup", "evet", "correct", "right", "aynen", "tamam", "dogru", "doğru"):
        return True
    return ul in ("e", "y")


def _is_no_reply(text: str) -> bool:
    ul = re.sub(r"[^\w\s']", "", text.strip().lower())
    if not ul:
        return False
    words = ul.split()
    if words[0] in ("no", "nope", "nah", "hayir", "hayır", "wrong", "degil", "değil", "yanlis", "yanlış"):
        return True
    return ul in ("n", "h")


def _is_clear_activity_answer(text: str) -> bool:
    """Günlük aktivite sorusuna net cevap — tekrar tahmin sorma."""
    ul = text.lower().strip()
    return bool(re.search(
        r"^(i (ran|run|running|walked|walk|read|played|worked|studied|watched|ate|"
        r"went|stayed|exercised|swam|slept|cooked|visited|shopped|cleaned|drank)|"
        r"i went for a run|i read a book|i went to (the )?(park|work|home|school|gym))",
        ul,
    ))


def _infer_meant_sentence(user_text: str, teacher_q: str) -> tuple[str | None, str | None]:
    """
    Kırık/eksik cümleden niyeti tahmin et.
    Returns (inferred_en, reason_tr) or (None, None).
    """
    ul = user_text.lower().strip()
    tq = teacher_q.lower()
    if re.search(r"\b(yes|yeah|yep)\b.*\b(understand|understood)\b", ul):
        return "Yes, I understand.", "Evet, anlıyorum demeye çalışmış olabilirsin."
    if re.search(r"\b(yes|yeah|yep)\b.*\b(like|love|enjoy)\b.*\b(book|books|reading|read)\b", ul):
        return "Yes, I like reading books.", "Evet, kitap okumayı seviyorum demeye çalışmış olabilirsin."

    activity = _infer_from_activity_token(user_text, teacher_q)
    if activity[0]:
        return activity

    daily = _is_daily_activity_question(tq)
    time_word = "yesterday" if "yesterday" in tq else "today"
    mode = _question_time_mode(teacher_q)

    patterns: list[tuple[re.Pattern, str, str]] = [
        (re.compile(r"\b(yes|yeah|yep)\b.*\b(understand|understood)\b", re.I),
         "Yes, I understand.",
         "Evet, anlıyorum demeye çalışmış olabilirsin."),
        (re.compile(r"\b(yes|yeah|yep)\b.*\b(like|love|enjoy)\b.*\b(book|books|reading|read)\b", re.I),
         "Yes, I like reading books.",
         "Evet, kitap okumayı seviyorum demeye çalışmış olabilirsin."),
        (re.compile(r"\b(book|books|a book|read)\b", re.I),
         f"I read a book {time_word}.",
         "Kitap okudum / bir kitap okudum demeye çalışmış olabilirsin."),
        (re.compile(r"\b(run|ran|running|jog|jogging|sport)\b", re.I),
         f"I went for a run {time_word}.",
         "Koşuya çıktım / koşmak demeye çalışmış olabilirsin."),
        (re.compile(r"\bi am run\b", re.I),
         f"I went for a run {time_word}.",
         "'I am run' demek istedin galiba — doğrusu 'I ran' veya 'I went for a run'."),
        (re.compile(r"\bi run\b", re.I),
         f"I went for a run {time_word}.",
         "Koştum demeye çalışmış olabilirsin — 'I ran today' de."),
        (re.compile(r"\bpark\b", re.I),
         f"I went to the park {time_word}.",
         "Parka gittim demeye çalışmış olabilirsin."),
        (re.compile(r"\b(work|office|job)\b", re.I),
         f"I went to work {time_word}.",
         "İşe gittim demeye çalışmış olabilirsin."),
        (re.compile(r"\b(sleep|sleeping|slept|slipping|slip)\b", re.I),
         "I'm going to sleep." if mode == "plan" else f"I was sleeping." if mode == "past" else "I slept.",
         "Uyumak / uyuyordum demeye çalışmış olabilirsin — 'sleep' = uyumak."),
        (re.compile(r"\b(home|house|rest)\b", re.I),
         f"I stayed at home {time_word}.",
         "Evde kaldım / dinlendim demeye çalışmış olabilirsin."),
        (re.compile(r"\b(tv|television|movie|film|netflix|series)\b", re.I),
         f"I watched TV {time_word}.",
         "Televizyon / film izledim demeye çalışmış olabilirsin."),
        (re.compile(r"\b(food|eat|ate|lunch|dinner|breakfast|cook|cooked)\b", re.I),
         f"I ate at home {time_word}.",
         "Yemek yedim demeye çalışmış olabilirsin."),
        (re.compile(r"\b(gym|sport|walk|walked|exercise|football|soccer)\b", re.I),
         f"I exercised {time_word}.",
         "Spor yaptım demeye çalışmış olabilirsin."),
        (re.compile(r"\b(friend|friends|visit|visited)\b", re.I),
         f"I visited a friend {time_word}.",
         "Arkadaş ziyareti yaptım demeye çalışmış olabilirsin."),
        (re.compile(r"\b(shop|shopping|bought|buy|market|store)\b", re.I),
         f"I went shopping {time_word}.",
         "Alışveriş yaptım demeye çalışmış olabilirsin."),
        (re.compile(r"\b(study|studied|homework|lesson|class|school)\b", re.I),
         f"I studied {time_word}.",
         "Ders çalıştım demeye çalışmış olabilirsin."),
        (re.compile(r"\b(tired|exhausted|sleepy)\b", re.I),
         f"I was very tired {time_word}.",
         "Çok yorgundum demeye çalışmış olabilirsin."),
    ]

    for pat, sentence, reason in patterns:
        if pat.search(ul):
            if daily or "today" in ul or "yesterday" in ul or len(ul.split()) <= 3:
                return sentence, reason

    if re.match(r"^(a |an |the )?\w+$", ul):
        word = ul.split()[-1]
        noun_map = {
            "book": (f"I read a book {time_word}.", "Kitap okudum demeye çalıştın."),
            "park": (f"I went to the park {time_word}.", "Parka gittim demeye çalıştın."),
            "work": (f"I went to work {time_word}.", "İşe gittim demeye çalıştın."),
            "sleep": ("I'm going to sleep." if mode == "plan" else "I was sleeping.",
                      "Uyumak demeye çalıştın — sleep = uyumak."),
            "sleeping": ("I'm going to sleep." if mode == "plan" else "I was sleeping.",
                         "Uyumak demeye çalıştın."),
        }
        mapped = noun_map.get(word) or noun_map.get(ACTIVITY_ALIASES.get(word, ""))
        if mapped:
            return mapped

    return None, None


def _build_intent_word_help(inferred: str, trigger_word: str) -> str:
    """Tahmin edilen cümledeki ana kelimeleri açıkla."""
    ul = inferred.lower()
    lines: list[str] = []
    if "read" in ul and "book" in ul:
        lines.append("  • read = okumak (geçmiş: read — düzensiz fiil, yazılışı aynı)")
        lines.append("  • a book = bir kitap")
        lines.append("  • I read a book = Bir kitap okudum")
    if "run" in ul or "ran" in inferred.lower():
        lines.append("  • run = koşmak (geçmiş: ran — düzensiz fiil)")
        lines.append("  • I went for a run = Koşuya çıktım")
        lines.append("  • I ran today = Bugün koştum")
        lines.append("  • ❌ 'I am run' YANLIŞ — 'am' + run olmaz")
    if re.search(r"\bsleep", ul):
        lines.append("  • sleep = uyumak (sleeping = uyuyor, slept = uyudu)")
        lines.append("  • I'm going to sleep = Uyuyacağım")
        lines.append("  • I was sleeping = Uyuyordum")
        lines.append("  • ❌ Sadece 'Sleeping' deme — tam cümle kur")
    if "went" in ul:
        lines.append("  • went = gitmek fiilinin geçmiş hali (go → went)")
    if "today" in ul:
        lines.append("  • today = bugün (zaman kelimesi genelde sonda)")
    if "yesterday" in ul:
        lines.append("  • yesterday = dün")
    if "work" in ul:
        lines.append("  • work = iş / to work = işe gitmek")
    if not lines and trigger_word:
        entry = TR_WORD_GLOSS.get(trigger_word.lower())
        if entry:
            lines.append(f"  • \"{trigger_word}\" → {entry[0]} — {entry[1]}")
    return "\n".join(lines)


def _intent_clarify_mode(
    user_text: str,
    inferred: str,
    reason_tr: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
    display_text: str | None = None,
) -> dict[str, Any]:
    """Kırık cümle — 'bunu mu demek istedin?' + evet/hayır."""
    shown = display_text or user_text
    meaning_tr = _to_tr(inferred, translate_fn, target_lang) if translate_fn else ""

    teacher_tr = (
        f"🤔 Sanırım bunu demek istedin:\n\"{inferred}\"\n\n"
        f"Sen dedin: \"{shown}\"\n"
    )
    if reason_tr:
        teacher_tr += f"\n💡 {reason_tr}\n"
    if meaning_tr:
        teacher_tr += f"\n🇹🇷 Türkçesi: {meaning_tr}\n"
    teacher_tr += "\n\n✅ Evet mi? — 'evet' veya 'hayır' de."

    teacher_en = inferred
    delta = {
        **session_delta,
        "lastTeacherText": inferred,
        "pendingIntentConfirm": inferred,
        "pendingIntentUserSaid": shown,
        "pendingIntentReason": reason_tr or meaning_tr or "",
        "pendingPracticePhrase": None,
        "pendingPracticeTr": None,
    }
    return _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "intent_guess",
        waiting=True, user_text=shown, teacher_en=teacher_en, speak_text=inferred,
        speak_tr="",
        speak_tr_first=False,
        phonetic_en=pronounce_text(inferred, target_lang),
        correction_detail={
            "userSaid": shown,
            "correctEn": inferred,
            "explainTr": reason_tr or meaning_tr,
            "inferredMeaning": meaning_tr or reason_tr,
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _intent_confirm_yes(
    profile: dict,
    session_delta: dict,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any]:
    inferred = safe_str(profile.get("pendingIntentConfirm")).strip()
    user_said = safe_str(profile.get("pendingIntentUserSaid")).strip()
    reason = safe_str(profile.get("pendingIntentReason")).strip()
    meaning_tr = _to_tr(inferred, translate_fn, target_lang) if translate_fn else reason
    clear = {
        "pendingIntentConfirm": None,
        "pendingIntentUserSaid": None,
        "pendingIntentReason": None,
    }
    grammar_tr = (
        "İngilizce'de tam cümle kur: özne (I) + fiil (understand / like / read...) + nesne.\n"
        f"Sen \"{user_said}\" dedin — eksik veya yanlış sıra.\n"
        f"Doğrusu: \"{inferred}\""
    )
    teacher_tr = (
        f"Harika! Evet, demek istediğin:\n\"{inferred}\"\n\n"
        f"📝 Cümleyi böyle kurmalısın:\n"
        f"❌ Senin dediğin: \"{user_said}\"\n"
        f"✅ Doğrusu: \"{inferred}\"\n"
    )
    if meaning_tr:
        teacher_tr += f"🇹🇷 Türkçesi: {meaning_tr}\n\n"
    teacher_tr += (
        f"💡 {grammar_tr}\n\n"
        f"🔄 Şimdi doğru cümleyi yüksek sesle söyle!"
    )
    delta = {
        **session_delta,
        **clear,
        "lastTeacherText": inferred,
        "pendingPracticePhrase": inferred,
        "pendingPracticeTr": meaning_tr or reason,
    }
    merged = merge_profile(profile, delta)
    return _pack(
        merged, delta, inferred, teacher_tr, inferred, 2, "intent_confirmed",
        waiting=True, teacher_en=inferred, speak_text=inferred,
        speak_tr=f"Doğrusu: {meaning_tr or inferred}"[:220],
        speak_tr_first=True,
        grammar_tr=grammar_tr,
        phonetic_en=pronounce_text(inferred, target_lang),
        correction_detail={
            "userSaid": user_said,
            "correctEn": inferred,
            "explainTr": grammar_tr,
            "grammarTr": grammar_tr,
            "inferredMeaning": meaning_tr,
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _intent_confirm_no(
    profile: dict,
    session_delta: dict,
) -> dict[str, Any]:
    clear = {
        "pendingIntentConfirm": None,
        "pendingIntentUserSaid": None,
        "pendingIntentReason": None,
        "pendingPracticePhrase": None,
        "pendingPracticeTr": None,
    }
    teacher_tr = (
        "Tamam — o zaman tekrar dene.\n\n"
        "Ne demek istediğini kendi cümlenle söyle.\n"
        "Takılırsan: yardım ben … diye Türkçe yazabilirsin."
    )
    teacher_en = "Okay — try again. Say what you mean in your own words."
    delta = {**session_delta, **clear, "lastTeacherText": teacher_en}
    merged = merge_profile(profile, delta)
    return _pack(
        merged, delta, teacher_en, teacher_tr, None, 1, "intent_retry",
        waiting=True, teacher_en=teacher_en, speak_text=teacher_en,
        speak_tr="Tamam, tekrar dene. Ne demek istediğini söyle.",
        speak_tr_first=True,
    )


def _intent_confirm_remind(
    profile: dict,
    session_delta: dict,
) -> dict[str, Any]:
    inferred = safe_str(profile.get("pendingIntentConfirm")).strip()
    shown = safe_str(profile.get("pendingIntentUserSaid")).strip()
    teacher_tr = (
        f"\"{inferred}\" demek istedin mi?\n\n"
        f"Sen dedin: \"{shown}\"\n\n"
        f"Lütfen 'evet' veya 'hayır' de."
    )
    return _pack(
        profile, session_delta, inferred, teacher_tr, None, 1, "intent_guess",
        waiting=True, teacher_en=inferred, speak_text=inferred,
        speak_tr=f"Bunu mu demek istedin: {inferred}? Evet mi hayır mı?",
    )


def _try_learner_clarify(
    original_text: str,
    history: list[dict],
    profile: dict,
    session_delta: dict,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """I am run gibi tipik öğrenici hataları — intent_guess modunda düzelt."""
    if target_lang != "en":
        return None
    ul = original_text.lower().strip()
    teacher_q = _last_teacher_question(history, profile)
    time_word = "yesterday" if "yesterday" in teacher_q.lower() else "today"

    am_m = re.search(r"\bi am (\w+)\b", ul)
    if am_m:
        v = am_m.group(1).lower()
        if v.endswith("ing") or v in ("a", "an", "the", "very", "so", "not", "going", "happy", "tired", "busy", "fine"):
            return None
        fixes: dict[str, tuple[str, str]] = {
            "run": (f"I went for a run {time_word}.",
                    "'I am run' yanlış. Koştum demek için: I ran today veya I went for a run."),
            "go": (f"I went to work {time_word}.", "'I am go' yanlış — geçmiş: I went."),
            "read": (f"I read a book {time_word}.", "'I am read' yanlış — I read a book de."),
            "walk": (f"I walked {time_word}.", "'I am walk' yanlış — geçmiş: I walked."),
            "play": (f"I played {time_word}.", "'I am play' yanlış — geçmiş: I played."),
            "work": (f"I worked {time_word}.", "'I am work' yanlış — geçmiş: I worked."),
        }
        if v in fixes:
            inferred, reason = fixes[v]
            return _intent_clarify_mode(
                original_text, inferred, reason, target_lang, profile, session_delta, translate_fn,
                display_text=original_text,
            )
    return None


def _try_intent_clarify(
    user_text: str,
    history: list[dict],
    profile: dict,
    session_delta: dict,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
    display_text: str | None = None,
) -> dict[str, Any] | None:
    if target_lang != "en" or not translate_fn:
        return None
    if _is_confusion_request(user_text):
        return None
    teacher_q = _last_teacher_question(history, profile)
    if not _is_fragment_attempt(user_text):
        return None
    if _is_daily_activity_question(teacher_q) and _is_clear_activity_answer(user_text):
        return None
    inferred, reason = _infer_meant_sentence(user_text, teacher_q)
    if not inferred:
        return None
    return _intent_clarify_mode(
        user_text, inferred, reason or "", target_lang, profile, session_delta, translate_fn,
        display_text=display_text,
    )


def _to_tr(text: str, translate_fn: Callable[[str, str, str], str], from_lang: str = "en") -> str:
    if not text or not translate_fn:
        return ""
    try:
        return translate_fn(text.strip(), from_lang, "tr")
    except Exception:
        return ""


def _teacher_tr_from_en(
    teacher_en: str,
    translate_fn: Callable[[str, str, str], str] | None,
    target_lang: str = "en",
    correction_tr: str | None = None,
    note_tr: str | None = None,
) -> str:
    """Türkçe blok = İngilizce cevabın tam çevirisi (+ varsa düzeltme/not)."""
    parts: list[str] = []
    if note_tr:
        parts.append(note_tr)
    if correction_tr:
        parts.append(correction_tr)
    if teacher_en and translate_fn:
        tr = _to_tr(teacher_en, translate_fn, target_lang)
        if tr:
            parts.append(tr)
    elif correction_tr:
        return correction_tr
    return "\n\n".join(p for p in parts if p)


def _personalized_help_analysis(
    phrase_tr: str,
    phrase_en: str,
    lang_name: str,
    translate_fn: Callable[[str, str, str], str] | None,
    include_steps: bool = True,
) -> tuple[str, str]:
    """Cümleye özel analiz — analiz motorunu kullanır."""
    target_lang = "en"
    for code, name in LANG_NAMES.items():
        if name == lang_name or code == lang_name:
            target_lang = code
            break
    analysis = _analyze_for_teaching(phrase_tr, target_lang, translate_fn)
    if phrase_en and analysis.get("natural_target") != phrase_en:
        analysis["natural_target"] = phrase_en
    teacher_tr = _format_teaching_response_tr(phrase_tr, analysis, lang_name)
    return teacher_tr, ""


def _explain_sentence_structure_tr(phrase_tr: str, phrase_en: str, lang_name: str) -> str:
    analysis_tr, _ = _personalized_help_analysis(phrase_tr, phrase_en, lang_name, None)
    return analysis_tr


def _explain_sentence_structure_en(phrase_tr: str, phrase_en: str) -> str:
    _, analysis_en = _personalized_help_analysis(phrase_tr, phrase_en, "English", None)
    return analysis_en


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


def groq_api_key_valid() -> bool:
    """Groq anahtarı gsk_ ile başlamalı — xAI Grok anahtarı çalışmaz."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    return bool(key) and key.startswith("gsk_")


def groq_api_key_status() -> dict[str, str | bool | None]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return {
            "configured": False,
            "valid_format": False,
            "hint_tr": (
                "Groq API anahtarı yok. iPhone Safari: console.groq.com → API Keys → "
                "Create → gsk_... anahtarını Render'da GROQ_API_KEY olarak kaydedin."
            ),
        }
    if key.startswith("gsk_"):
        return {"configured": True, "valid_format": True, "hint_tr": None}
    if key.startswith("xai-"):
        return {
            "configured": True,
            "valid_format": False,
            "hint_tr": (
                "Bu xAI Grok anahtarı (xai-...). Bu uygulama Groq kullanır — "
                "console.groq.com adresinden gsk_... ile başlayan ücretsiz anahtar alın. "
                "xAI Grok anahtarı burada çalışmaz."
            ),
        }
    return {
        "configured": True,
        "valid_format": False,
        "hint_tr": (
            "GROQ_API_KEY geçersiz format. Groq anahtarı gsk_ ile başlamalı "
            "(console.groq.com). xAI Grok anahtarı değil."
        ),
    }


def _active_llm_provider() -> str | None:
    """Öncelik: Groq/Gemini ücretsiz, sonra OpenAI."""
    if groq_api_key_valid():
        return "groq"
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai"
    return None


def llm_available() -> bool:
    return _active_llm_provider() is not None


def pronounce_text(text: str, lang: str = "en") -> str:
    """Turkish-style phonetic spelling for foreign text (display + fallback TTS hint)."""
    text = safe_str(text).strip()
    if not text or lang == "tr":
        return ""
    try:
        from pronunciation_service import romanize_for_tr_reader
        roma = romanize_for_tr_reader(text, lang)
        if roma:
            return roma[:2500]
    except Exception:
        pass
    lang_name = LANG_NAMES.get(lang, lang)
    if llm_available():
        sys_msg = (
            f"Convert this {lang_name} into Turkish-letter phonetics so a Turkish speaker can read it aloud. "
            "Do NOT translate into Turkish. Do NOT explain. Only the SOUND of the given words. "
            "One paragraph of Latin letters (Turkish alphabet). No IPA, no quotes."
        )
        user_msg = f"{lang_name} text (phoneticize, do not translate):\n{text[:500]}"
        provider = _active_llm_provider()
        raw = None
        for prov in _llm_providers_in_order() or ([provider] if provider else []):
            if prov == "groq":
                raw = _groq_chat(
                    [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
                    max_tokens=min(400, 80 + len(text) // 2),
                    timeout_sec=6,
                    temperature=0.0,
                )
            elif prov == "gemini":
                raw = _gemini_chat(sys_msg, user_msg, max_tokens=min(400, 80 + len(text) // 2))
            else:
                raw = _openai_chat(
                    [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
                    max_tokens=min(400, 80 + len(text) // 2),
                )
            if raw:
                break
        if raw:
            line = raw.strip().strip('"').replace("\n", " ").strip()
            # Türkçeye çeviri sızıntısını reddet
            if re.search(r"\b(küçük|kız|nefes|kuş|adım|kelebek|çınar|kitap)\b", line, re.I):
                line = ""
            if lang == "zh" and re.search(r"[ğüşıöç]", line) and not re.search(r"[a-z]{2,}", line, re.I):
                line = ""
            if line and len(line) > 2:
                return line[:500]
    if lang == "en":
        return _simple_en_phonetic(text)
    return ""


def _simple_en_phonetic(text: str) -> str:
    t = re.sub(r"[^\w\s'-]", "", text.lower())
    word_map = {
        "the": "dı", "you": "yu", "your": "yor", "are": "ar", "was": "vaz",
        "were": "vör", "have": "hev", "has": "hez", "had": "hed", "would": "vud",
        "could": "kud", "should": "şud", "because": "bikoz", "through": "thru",
        "though": "tho", "people": "pipıl", "really": "rili", "usually": "yuğuali",
        "beautiful": "byutiful", "comfortable": "kamftıbıl", "interesting": "intresting",
        "yesterday": "yestırdey", "today": "tudey", "tomorrow": "tumoro",
        "work": "vörk", "walk": "vok", "water": "votır", "where": "ver",
        "what": "vat", "when": "ven", "why": "vay", "who": "hu", "how": "hav",
        "good": "gud", "great": "greyt", "thanks": "thenks", "please": "pliz",
        "sorry": "sori", "hello": "helo", "friend": "frend", "family": "femili",
        "school": "skul", "coffee": "kofi", "tea": "ti", "book": "buk", "read": "rid",
        "tired": "tayırd", "happy": "hepi", "understand": "anderstand",
        "bird": "börd", "girl": "görl", "her": "hör", "blue": "blu", "took": "tuk",
        "with": "vid", "first": "först", "turn": "törn", "heard": "hörd",
    }
    words = t.split()
    out_words: list[str] = []
    for w in words:
        base = re.sub(r"'s$|'re$|'ve$|'ll$|'d$", "", w)
        if base in word_map:
            out_words.append(word_map[base])
            continue
        out_words.append(w)
    t = " ".join(out_words)
    repl = [
        (r"\btion\b", "şın"), (r"\bough\b", "of"), (r"\bight\b", "ayt"),
        (r"\bious\b", "iös"), (r"\bable\b", "ıbıl"), (r"\bment\b", "ment"),
        (r"ph", "f"), (r"wh", "v"), (r"th", "t"), (r"sh", "ş"), (r"ch", "ç"),
        (r"ck", "k"), (r"qu", "kv"), (r"wr", "r"), (r"kn", "n"),
        (r"oo(?!\w)", "u"), (r"ee", "i"), (r"ea", "i"), (r"ou", "au"), (r"ow", "au"),
        (r"ay", "ey"), (r"ey", "ey"), (r"ai", "ey"), (r"oi", "oy"), (r"oy", "oy"),
        (r"er(?=\b)", "ır"), (r"or(?=\b)", "or"), (r"ar(?=\b)", "ar"),
    ]
    for pat, rep in repl:
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()[:120]


def _parse_vocab_tts_pairs(vocab_tr: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for line in safe_str(vocab_tr).split("\n"):
        m = re.search(r'"([^"]+)"\s*→\s*([^—\n]+)', line)
        if not m:
            continue
        tr_w = m.group(1).strip()
        en_w = re.split(r"\s*—", m.group(2).strip())[0].strip().strip('"').strip("'")
        if tr_w and en_w and len(en_w) < 40:
            pairs.append({"tr": tr_w, "en": en_w})
    return pairs[:10]


def _gemini_api_request(
    body: dict[str, Any],
    max_tokens: int,
    *,
    timeout_sec: int | None = None,
) -> str | None:
    """Gemini generateContent — AIza ve yeni AQ. anahtar formatlarını destekler."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    configured = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    models: list[str] = []
    for candidate in (configured, "gemini-3.5-flash-lite"):
        if candidate and candidate not in models:
            models.append(candidate)
    headers = _api_headers({
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    })
    payload = json.dumps(body).encode()
    gemini_timeout = timeout_sec if timeout_sec is not None else _llm_request_timeout(max_tokens)
    if timeout_sec is not None and timeout_sec >= 50:
        models = models[:1]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            req = Request(url, data=payload, headers=headers, method="POST")
            with urlopen(req, timeout=gemini_timeout) as resp:
                data = json.loads(resp.read().decode())
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except HTTPError as exc:
            if exc.code in (404, 400, 429) and model != models[-1]:
                continue
            return None
        except Exception:
            return None
    return None


def ai_provider_info() -> dict[str, str | None]:
    providers = _llm_providers_in_order()
    primary = providers[0] if providers else None
    labels = {
        "groq": "Groq (ücretsiz)",
        "gemini": "Google Gemini (ücretsiz)",
        "openai": "OpenAI",
    }
    models = {
        "groq": os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
        "gemini": os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    }
    label = labels.get(primary or "", None)
    if len(providers) > 1:
        fallbacks = " → ".join(labels.get(p, p) for p in providers[1:])
        label = f"{label} (+ yedek: {fallbacks})" if label else fallbacks
    return {
        "provider": primary,
        "label": label,
        "model": models.get(primary or "", None),
        "providers": providers,
        "fallback_enabled": len(providers) > 1,
    }


def _llm(messages: list[dict], target_lang: str, level: str, roleplay: str | None = None,
           extra: str = "") -> str | None:
    if not _llm_providers_in_order():
        return None
    sys = SYSTEM_PROMPT + f"\nTarget language: {LANG_NAMES.get(target_lang, target_lang)}. User level: {level}."
    if roleplay and roleplay in ROLEPLAYS:
        rp = ROLEPLAYS[roleplay].get(target_lang) or ROLEPLAYS[roleplay].get("en", "")
        if rp:
            sys += f"\nRoleplay scenario: {rp}"
    if extra:
        sys += f"\n{extra}"
    full_messages = [{"role": "system", "content": sys}] + messages
    for provider in _llm_providers_in_order():
        if provider == "groq":
            raw = _groq_chat(full_messages, max_tokens=280)
        elif provider == "gemini":
            raw = _gemini_chat(sys, messages[-1]["content"] if messages else "", max_tokens=280)
        else:
            raw = _openai_chat(full_messages, json_mode=False, max_tokens=280)
        if raw:
            return raw
    return None


def _openai_chat(messages: list[dict], json_mode: bool = False, max_tokens: int = 520) -> str | None:
    body: dict[str, Any] = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": messages,
        "temperature": 0.65 if not json_mode else 0.72,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers=_api_headers({"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '').strip()}"}),
            method="POST",
        )
        with urlopen(req, timeout=_llm_request_timeout(max_tokens)) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _llm_request_timeout(max_tokens: int) -> int:
    """Büyük JSON yanıtları için yeterli süre; küçük isteklerde hızlı zaman aşımı."""
    return min(90, max(18, 12 + max_tokens // 120))


def _groq_chat(
    messages: list[dict],
    max_tokens: int = 520,
    json_mode: bool = False,
    *,
    timeout_sec: int | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> str | None:
    if not groq_api_key_valid():
        return None
    body: dict[str, Any] = {
        "model": model or os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
        "messages": messages,
        "temperature": 0.55 if temperature is None else temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        req = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers=_api_headers({"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '').strip()}"}),
            method="POST",
        )
        with urlopen(req, timeout=timeout_sec or _llm_request_timeout(max_tokens)) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _gemini_chat(system: str, user: str, max_tokens: int = 520) -> str | None:
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return None
    return _gemini_api_request({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.72, "maxOutputTokens": max_tokens},
    }, max_tokens)


def _llm_providers_in_order() -> list[str]:
    """Tüm yapılandırılmış sağlayıcılar — Groq başarısız olursa sıradaki denenir."""
    providers: list[str] = []
    if groq_api_key_valid():
        providers.append("groq")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        providers.append("gemini")
    if os.environ.get("OPENAI_API_KEY", "").strip():
        providers.append("openai")
    return providers


def _llm_chat_json_raw(
    provider: str,
    system: str,
    user: str,
    max_tokens: int,
) -> str | None:
    """Tek sağlayıcıdan ham JSON metin al."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if provider == "groq":
        word_lesson = max_tokens >= 2000
        groq_model = (
            os.environ.get("GROQ_WORD_LESSON_MODEL", "llama-3.1-8b-instant")
            if word_lesson
            else os.environ.get("GROQ_TRANSLATE_MODEL", "llama-3.1-8b-instant")
            if max_tokens <= 600
            else None
        )
        timeout = min(12, _llm_request_timeout(max_tokens)) if word_lesson else _llm_request_timeout(max_tokens)
        return _groq_chat(
            messages, max_tokens=max_tokens, json_mode=True, timeout_sec=timeout, model=groq_model,
        )
    if provider == "gemini":
        # Kelime dersi: yeterli süre — kesik JSON / sade şablon üretmesin
        word_lesson = max_tokens >= 2000
        timeout = 45 if word_lesson else None
        return _gemini_api_request({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.55,
                "maxOutputTokens": max_tokens,
            },
        }, max_tokens, timeout_sec=timeout)
    if provider == "openai":
        return _openai_chat(messages, json_mode=True, max_tokens=max_tokens)
    return None


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """JSON parse — kesilmiş yanıtları kısmen kurtarmayı dener."""
    text = safe_str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # Kesilmiş JSON: son tam } veya ] ile kapatmayı dene
    for end in range(len(text), max(0, len(text) - 8000), -1):
        chunk = text[:end].rstrip().rstrip(",")
        for suffix in ("", "}", "]}", "]}]", "}", "]}]}", "}"):
            try:
                parsed = json.loads(chunk + suffix)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _llm_json(
    system: str,
    user: str,
    max_tokens: int = 380,
    *,
    prefer: str | None = None,
) -> dict[str, Any] | None:
    """Yapılandırılmış JSON yanıt — Groq / Gemini / OpenAI (sırayla dener)."""
    providers = _llm_providers_in_order()
    if prefer and prefer in providers:
        providers = [prefer] + [p for p in providers if p != prefer]
    if not providers:
        return None
    for provider in providers:
        raw = _llm_chat_json_raw(provider, system, user, max_tokens)
        if not raw:
            continue
        parsed = _parse_json_object(raw)
        if parsed:
            return parsed
    return None


def _llm_json_word_lesson(system: str, user: str, max_tokens: int = 2400) -> dict[str, Any] | None:
    """Kelime dersi — Gemini birincil (kalite), Groq yedek. Sıralı dener."""
    prefer = os.environ.get("WORD_LESSON_PROVIDER", "gemini").strip().lower()
    providers: list[str] = []
    if prefer == "groq":
        if groq_api_key_valid():
            providers.append("groq")
        if os.environ.get("GEMINI_API_KEY", "").strip():
            providers.append("gemini")
    else:
        if os.environ.get("GEMINI_API_KEY", "").strip():
            providers.append("gemini")
        if groq_api_key_valid():
            providers.append("groq")
    for provider in providers:
        raw = _llm_chat_json_raw(provider, system, user, max_tokens)
        if raw:
            parsed = _parse_json_object(raw)
            # İnce/şablon yanıtları reddet — en az 8 örnek
            if parsed and isinstance(parsed.get("examples"), list) and len(parsed["examples"]) >= 8:
                return parsed
    return None


_FAIRY_OPENERS = {
    "en": "Once upon a time",
    "de": "Es war einmal",
    "fr": "Il était une fois",
    "es": "Érase una vez",
    "it": "C'era una volta",
    "ru": "Жили-были",
    "ka": "ერთხელ იყო",
    "ar": "كان يا ما كان",
    "zh": "从前",
    "tr": "Bir varmış bir yokmuş",
}

_SCRIPT_HINTS = {
    "ka": "Write 100% in Georgian Mkhedruli script. No Latin letters except names if needed.",
    "ar": "Write 100% in Arabic script.",
    "ru": "Write 100% in Russian Cyrillic.",
    "zh": "Write 100% in Simplified Chinese characters.",
    "de": "Write natural native German (not English).",
    "fr": "Write natural native French (not English).",
    "es": "Write natural native Spanish (not English).",
    "it": "Write natural native Italian (not English).",
    "en": "Write natural native English.",
    "tr": "Write natural native Turkish.",
}


_LITERARY_GLOSS = (
    "MEANING FIDELITY (mandatory — creative rewrite forbidden):\n"
    "- Preserve every subject, object, verb, tense, number, possessive, place, direction, and quote.\n"
    "- Add NOTHING that is not in the source. Remove NOTHING important from the source.\n"
    "- village/köy/სოფელი ≠ town/kasaba/დაბა ≠ city/şehir/ქალაქი — never swap these.\n"
    "- came to life/canlandı/ცოცხლდებოდა ≠ became real/gerçeğe dönüştü/რეალობად იქცა — never swap.\n"
    "- follow ≠ chase unless the source is clearly chase; shoulder ≠ side; edge ≠ center.\n"
    "- Do not upgrade adjectives (old≠ancient, small≠tiny) or invent magical/mysterious tone.\n"
    "Exact glossary:\n"
    "- küçük kız = little girl (a child), never 'minor girl'\n"
    "- kelebek = butterfly\n"
    "- çınar = plane tree (Platanus / platane / plátano / Platane / ჭადარა / платан), "
    "never cedar, camphor, mushroom, or 'plane' as flat surface\n"
    "- kovuk = hollow / cavity in a tree, never cup/glass\n"
    "- masal kitabı = fairy-tale storybook, never generic legend unless the source says so\n"
    "- sihirli = magical ONLY if the source says sihirli/magical\n"
    "- oyuncak = toy\n"
    "- cıvıldamak = to chirp\n"
)

_NATIVE_GLOSS = {
    "ka": (
        "Georgian: meaning-preserving native Mkhedruli — NOT creative children's rewrite.\n"
        "Lexicon only when source matches:\n"
        "- little girl → პატარა გოგონა (not მცირე)\n"
        "- small bird → ჩიტი (not ფრინველი unless poultry)\n"
        "- butterfly → პეპელა\n"
        "- plane tree/çınar → ჭადარა (never სიბრტყე/სოკო)\n"
        "- tree hollow/kovuk → ფუღურო\n"
        "- village/köy → სოფელი; town/kasaba → დაბა; city/şehir → ქალაქი "
        "(never village↔town↔city)\n"
        "- at the edge → პირას / კიდეზე\n"
        "- pick up object → აიღო (not აიყვანა for a book)\n"
        "- perch on shoulder → ჩამოჯდა; tilt head to the SIDE → გვერდზე დახარა "
        "(never მხარზე დახარა for 'to the side')\n"
        "- came to life/canlandı → ცოცხლდებოდა; became real/gerçeğe dönüştü → რეალობად იქცა "
        "(never swap)\n"
        "- carve from wood → გამოთლის; be filled → აივსოს; chirp → ჭიკჭიკი\n"
        "- magical → ჯადოსნური only if source is magical/sihirli; fairy tale → ზღაპარი; toy → სათამაშო\n"
        "- hold breath → სუნთქვა შეიკრა (ergative -მა when the subject acts)\n"
        "If naturalness conflicts with fidelity, keep fidelity.\n"
    ),
    "zh": "Chinese: 小女孩; 蝴蝶; 悬铃木/梧桐 for çınar (not 樟树 unless camphor); 树洞; 童话书; 魔法 only if source. village≠town≠city.\n",
    "es": "Spanish: niña; mariposas; plátano for çınar (not cedro); hueco; libro de cuentos; mágico only if source. village/pueblo vs town vs ciudad carefully.\n",
    "de": "German: kleines Mädchen; Schmetterlinge; Platane; Baumhöhle; Märchenbuch; zauberhaft only if source. Dorf≠Stadt≠Kleinstadt.\n",
    "fr": "French: petite fille; papillons; platane; creux; livre de contes; magique only if source. village≠ville.\n",
    "it": "Italian: bambina; farfalle; platano; cavità; libro di fiabe; magico only if source. villaggio≠città.\n",
    "ru": "Russian: маленькая девочка; бабочки; платан; дупло; сказка; волшебный only if source. деревня≠город≠посёлок.\n",
    "ar": "Arabic: الفتاة الصغيرة; فراشات; شجرة دلب/صنار for çınar; تجويف; كتاب حكايات; سحري only if source. قرية≠بلدة≠مدينة.\n",
}


def llm_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    """Anlamı koruyan çeviri — yaratıcı rewrite yok."""
    src = safe_str(text).strip()
    if not src or not llm_available():
        return None
    from_name = LANG_NAMES.get(from_lang, from_lang)
    to_name = LANG_NAMES.get(to_lang, to_lang)
    opener = _FAIRY_OPENERS.get(to_lang, "")
    script = _SCRIPT_HINTS.get(to_lang, f"Write only in {to_name}.")
    opener_line = (
        f"3) Fairy-tale opener 'Bir varmış bir yokmuş' → {opener} (only if the source has that opener).\n"
        if opener else
        "3) Keep the original narrative tone; do not embellish.\n"
    )
    native = _NATIVE_GLOSS.get(to_lang, "")
    ka_extra = ""
    if from_lang == "ka" or to_lang == "ka":
        ka_extra = (
            "GEORGIAN FIDELITY CHECK: After drafting, verify subject, verb, tense, possessives, "
            "place (სოფელი/დაბა/ქალაქი), motion, and modifiers match the source. "
            "If back-translated mentally, people/places/actions must match.\n"
        )
    system = (
        f"You are a professional meaning-preserving translator into {to_name} (from {from_name}).\n"
        f"NOT a creative rewriter. Prefer exact meaning over prettier wording.\n"
        f"{script}\n"
        f"{_LITERARY_GLOSS}"
        f"{native}"
        f"{ka_extra}"
        "Rules:\n"
        "1) Keep subjects/possessives exact. Do not mix who is who.\n"
        "2) Turkish 'X'in N yaşında oğlu/kızı/çocuğu' means 'X HAD an N-year-old son/daughter/child'. "
        "NEVER say X was N years old.\n"
        "   yaramaz=mischievous/naughty; uysal=gentle; oynamak=to play games.\n"
        f"{opener_line}"
        "4) Full sentences, natural punctuation, native word order. Do not drop clauses.\n"
        "5) Reply with ONLY the translation — no quotes, no notes, no transliteration, no explanations."
    )
    translate_model = (
        os.environ.get("GROQ_TRANSLATE_MODEL")
        or os.environ.get("GROQ_MODEL")
        or ""
    ).strip() or None
    max_tok = min(1800, 220 + len(src))
    user_src = src[:3500]
    for provider in _llm_providers_in_order():
        raw = None
        if provider == "groq":
            kwargs = {
                "max_tokens": max_tok,
                "timeout_sec": 8,
                "temperature": 0.05,
            }
            if translate_model:
                kwargs["model"] = translate_model
            raw = _groq_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user_src}],
                **kwargs,
            )
            if not raw and translate_model:
                raw = _groq_chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": user_src}],
                    max_tokens=max_tok,
                    timeout_sec=8,
                    temperature=0.05,
                )
        elif provider == "gemini":
            raw = _gemini_chat(system, user_src, max_tokens=max_tok)
        else:
            raw = _openai_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user_src}],
                max_tokens=max_tok,
            )
        if raw:
            out = raw.strip().strip('"').strip("'")
            out = re.sub(r"^translation\s*:\s*", "", out, flags=re.I).strip()
            if out.startswith("```"):
                out = re.sub(r"^```\w*\n?", "", out)
                out = re.sub(r"\n?```$", "", out).strip()
            if out and len(out) >= 1 and out.lower() != src.lower():
                return out
    return None


def llm_rewrite_georgian(src: str, meaning_en: str, draft_ka: str) -> str | None:
    """Google taslağını yerli Gürcüceye çek — anlamı değiştirmeden (yaratıcı rewrite yok)."""
    draft = safe_str(draft_ka).strip()
    if not draft or not llm_available():
        return None
    meaning = safe_str(meaning_en).strip() or safe_str(src).strip()
    system = (
        "You are a native Georgian editor for MEANING-PRESERVING translation.\n"
        "SOURCE + MEANING are the truth. DRAFT may have wrong words or calques — fix those only.\n"
        "Do NOT invent facts, adjectives, places, emotions, or plot.\n"
        "Do NOT swap village/town/city or came-to-life vs became-real.\n"
        "Write 100% Mkhedruli. No Latin, no notes.\n"
        "Grammar: ergative -მა when the subject acts; keep tense/number/possessives.\n"
        "Lexicon ONLY when the source matches:\n"
        "- little girl → პატარა გოგონა (never მცირე)\n"
        "- small bird → ჩიტი\n"
        "- butterfly → პეპელა\n"
        "- plane tree/çınar → ჭადარა (never სიბრტყე/სოკო)\n"
        "- hollow/kovuk → ფუღურო\n"
        "- village/köy → სოფელი; town/kasaba → დაბა; city → ქალაქი\n"
        "- pick up → აიღო; perch on shoulder → ჩამოჯდა\n"
        "- tilt head to the SIDE → გვერდზე დახარა (never მხარზე დახარა)\n"
        "- came to life → ცოცხლდებოდა; became real/gerçeğe dönüştü → რეალობად იქცა\n"
        "- carve wood → გამოთლის; fill → აივსოს; chirp → ჭიკჭიკი\n"
        "- magical → ჯადოსნური only if source says magical/sihirli\n"
        "Self-check: if reverse-translated, subject/place/verb/tense/possessive must match SOURCE.\n"
        "Reply with ONLY the Georgian text."
    )
    user_msg = (
        f"SOURCE:\n{safe_str(src).strip()[:3500]}\n\n"
        f"MEANING:\n{meaning[:3500]}\n\n"
        f"DRAFT Georgian:\n{draft[:3500]}"
    )
    translate_model = (
        os.environ.get("GROQ_TRANSLATE_MODEL")
        or os.environ.get("GROQ_MODEL")
        or ""
    ).strip() or None
    max_tok = min(1800, 220 + len(draft))
    for provider in _llm_providers_in_order():
        raw = None
        if provider == "groq":
            kwargs = {
                "max_tokens": max_tok,
                "timeout_sec": 8,
                "temperature": 0.05,
            }
            if translate_model:
                kwargs["model"] = translate_model
            raw = _groq_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                **kwargs,
            )
            if not raw and translate_model:
                raw = _groq_chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                    max_tokens=max_tok,
                    timeout_sec=8,
                    temperature=0.05,
                )
        elif provider == "gemini":
            raw = _gemini_chat(system, user_msg, max_tokens=max_tok)
        else:
            raw = _openai_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                max_tokens=max_tok,
            )
        if raw:
            out = raw.strip().strip('"').strip("'")
            out = re.sub(r"^translation\s*:\s*", "", out, flags=re.I).strip()
            if out.startswith("```"):
                out = re.sub(r"^```\w*\n?", "", out)
                out = re.sub(r"\n?```$", "", out).strip()
            if out and re.search(r"[\u10A0-\u10FF]", out):
                return out
    return None


def _recent_teacher_questions(history: list[dict], profile: dict, limit: int = 5) -> str:
    """Öğretmenin tekrar sormaması gereken son sorular."""
    seen: list[str] = []
    last = safe_str(profile.get("lastTeacherText")).strip()
    if last:
        seen.append(last)
    for h in reversed(history):
        if not isinstance(h, dict) or h.get("role") != "teacher":
            continue
        text = safe_str(h.get("text")).strip()
        if not text or text in seen:
            continue
        for line in text.split("\n"):
            line = line.strip()
            if "?" in line and len(line) > 8:
                seen.append(line)
                break
        if len(seen) >= limit:
            break
    if not seen:
        return "(none yet — ask a friendly opening question)"
    return "\n".join(f"- {q[:200]}" for q in seen[:limit])


def _try_ai_tutor_turn(
    user_text: str,
    user_lang: str,
    target_lang: str,
    history: list[dict],
    profile: dict,
    session_delta: dict,
    roleplay: str | None,
    speak_slow: bool,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """OpenAI ile düşünen öğretmen — kural listesi yerine bağlamdan anlar."""
    if not llm_available():
        return None

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    level = profile.get("currentLevel", "A1")
    weak_areas = profile.get("weakAreas") or []
    if not isinstance(weak_areas, list):
        weak_areas = [str(weak_areas)] if weak_areas else []
    weak = ", ".join(str(w) for w in weak_areas[:5]) or "general conversation"
    last_teacher = profile.get("lastTeacherText") or _last_teacher_question(history, profile) or ""
    input_lang = "Turkish" if user_lang == "tr" else f"{lang_name} (learner, may be incomplete, wrong, or STT garbled)"
    rp = (ROLEPLAYS.get(roleplay or "") or {}).get(target_lang) or "professional language tutor"
    pending = profile.get("pendingPracticePhrase") or ""
    pending_note = ""
    if pending:
        pending_note = (
            f"\nPENDING PRACTICE PHRASE (student was practicing this): \"{pending}\"\n"
            f"If student said something different, compare carefully — never say they said the practice phrase if they didn't."
        )

    stt_note = ""
    if _is_garbled_stt(user_text):
        stt_note = (
            "⚠️ STT WARNING: This input looks garbled/nonsensical from speech recognition. "
            "Set stt_uncertain=true. Ask brief confirmation. Do NOT invent a full sentence as certain."
        )

    system = AI_TUTOR_JSON_PROMPT.format(
        lang_name=lang_name,
        target_lang=target_lang,
        level=level,
        weak_areas=weak,
        repeated_mistakes=_repeated_mistakes_summary(profile),
        roleplay=rp,
        curriculum_block=_curriculum_block(profile),
        micro_chain_block=_micro_chain_block(profile),
        history_text=_format_history_for_ai(history),
        last_teacher=last_teacher[:500],
        recent_questions=_recent_teacher_questions(history, profile),
        input_lang=input_lang,
        user_text=user_text[:500],
        stt_note=stt_note,
    ) + pending_note
    parsed = _llm_json(system, "Respond with the JSON object only.", max_tokens=600)
    if not parsed:
        return None

    parsed = _sanitize_ai_correction(user_text, parsed)

    teacher_en = safe_str(parsed.get("teacher_en")).strip()
    teacher_tr = _trim_teacher_tr(teacher_en, safe_str(parsed.get("teacher_tr")).strip())
    if not teacher_en:
        return None

    corr_level = int(parsed.get("correction_level") or 1)
    corr_level = max(1, min(3, corr_level))
    correct_phrase = safe_str(parsed.get("correct_phrase")).strip() or None
    teach_new = safe_str(parsed.get("teach_new_phrase")).strip() or None
    teach_new_tr = safe_str(parsed.get("teach_new_phrase_tr")).strip() or None
    build_on = safe_str(parsed.get("build_on_phrase")).strip() or None
    suggested = safe_str(parsed.get("suggested_practice")).strip() or teach_new or build_on or correct_phrase
    category = safe_str(parsed.get("category")).strip() or None
    grammar_tr = safe_str(parsed.get("grammar_tr")).strip()
    word_breakdown_tr = safe_str(parsed.get("word_breakdown_tr")).strip() or None
    speak_tr = safe_str(parsed.get("speak_tr")).strip()
    inferred = safe_str(parsed.get("inferred_meaning")).strip()
    phonetic_en = safe_str(parsed.get("phonetic_en")).strip() or _simple_en_phonetic(teacher_en.split("\n")[0])

    if bool(parsed.get("stt_uncertain")) and not teacher_tr:
        teacher_tr = "Ses net gelmedi — emin olmak için kısa doğrulama sordum."

    if teach_new and corr_level == 1 and not correct_phrase:
        if teach_new_tr:
            teacher_tr = (teacher_tr + "\n\n" if teacher_tr else "") + f"🇹🇷 {teach_new_tr}"
        suggested = teach_new

    profile_patch: dict[str, Any] = {}
    if corr_level >= 2 and correct_phrase:
        profile_patch.update(_record_mistake(profile, user_text, correct_phrase, category or "grammar"))
        session_delta["totalCorrections"] = profile.get("totalCorrections", 0) + 1
        session_delta["sessionCorrections"] = profile.get("sessionCorrections", 0) + 1
    elif corr_level == 1:
        session_delta["correctSentences"] = profile.get("correctSentences", 0) + 1
        profile_patch.update(_advance_lesson_on_success(profile, user_text, corr_level))

    if teach_new:
        taught = list(profile.get("taughtPatterns") or [])
        if teach_new not in taught:
            taught.append(teach_new[:80])
        profile_patch["taughtPatterns"] = taught[-15:]

    if bool(parsed.get("lesson_advance")):
        step = int(profile.get("lessonStep") or 0)
        if step < len(LESSON_CURRICULUM) - 1:
            profile_patch["lessonStep"] = step + 1

    if bool(parsed.get("micro_advance")):
        mstep = int(profile.get("microStep") or 0)
        if mstep < len(GREETING_MICRO_CHAIN) - 1:
            profile_patch["microStep"] = mstep + 1

    if teach_new or build_on or (corr_level == 1 and correct_phrase):
        mastered = teach_new or build_on or correct_phrase or user_text.strip()
        if mastered and corr_level <= 2:
            profile_patch["lastMasteredPhrase"] = mastered[:120]
            if build_on:
                profile_patch["sentenceBuildBase"] = build_on[:120]

    delta: dict[str, Any] = {
        **session_delta,
        "lastTeacherText": teacher_en,
    }
    if suggested and (corr_level >= 2 or teach_new or build_on):
        delta["pendingPracticePhrase"] = suggested
        delta["awaitingTargetPhrase"] = suggested
        meaning = teach_new_tr or (_to_tr(suggested, translate_fn, target_lang) if translate_fn else "")
        delta["pendingPracticeTr"] = meaning or safe_str(parsed.get("inferred_meaning"))

    merged = merge_profile(profile, {**session_delta, **profile_patch})
    merged["currentLevel"] = estimate_level(merged)

    msg_type = "ai_tutor"
    if suggested and corr_level >= 2:
        msg_type = "ai_intent"
    elif corr_level >= 2:
        msg_type = "ai_correction"
    elif teach_new:
        msg_type = "ai_tutor"

    result = _pack(
        merged, delta, teacher_en, teacher_tr, correct_phrase, corr_level, msg_type,
        waiting=True, user_text=user_text, speak_slow=speak_slow,
        teacher_en=teacher_en, speak_text=suggested or teacher_en,
        speak_tr=speak_tr or None,
        grammar_tr=grammar_tr or None,
        word_breakdown_tr=word_breakdown_tr,
        speak_tr_first=corr_level >= 2,
        phonetic_en=phonetic_en,
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct_phrase,
            "explainTr": teacher_tr,
            "grammarTr": grammar_tr,
            "wordBreakdown": word_breakdown_tr,
            "category": category,
            "level": corr_level,
            "inferredMeaning": inferred or None,
        } if corr_level >= 2 else None,
        translate_fn=translate_fn,
        target_lang=target_lang,
    )
    result["ai_powered"] = True
    return result


def safe_str(val: Any) -> str:
    if val is None:
        return ""
    return val if isinstance(val, str) else str(val)


def _resume_after_help(
    user_text: str, target_lang: str, profile: dict, session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
    history: list[dict], roleplay: str | None,
) -> dict[str, Any] | None:
    pending = profile.get("pendingPracticePhrase") or ""
    pending_tr = profile.get("pendingPracticeTr") or ""
    if not pending:
        return None

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    practiced = _practice_phrase_match(user_text, pending)
    if not practiced and pending_tr and _practice_phrase_match(user_text, pending_tr):
        practiced = True
    if not practiced and pending_tr and translate_fn and re.search(r"[ğüşıöçĞÜŞİÖÇ]", user_text):
        meaning = translate_fn(user_text, "tr", target_lang)
        practiced = _practice_phrase_match(meaning, pending)

    if not practiced:
        return None

    clear_delta = {"pendingPracticePhrase": None, "pendingPracticeTr": None}
    teacher_en = (
        f"Excellent! You said it well:\n\"{user_text.strip()}\"\n\n"
        f"That's the sentence we practiced"
        + (f" (\"{pending}\")" if _norm(user_text) != _norm(pending) else "")
        + f". Now let's keep chatting in {lang_name} — what else are you planning today?"
    )
    teacher_tr = (
        f"🎉 Harika! Doğru söyledin:\n\"{user_text.strip()}\"\n\n"
        f"Çalıştığımız cümleydi. "
        f"Şimdi {lang_name} sohbete devam edelim — bugün başka ne planlıyorsun?"
    )
    if translate_fn:
        teacher_tr = (
            f"🎉 Harika! Doğru söyledin:\n\"{pending}\"\n\n"
            + _to_tr(
                f"That's exactly the sentence we practiced. "
                f"Now let's keep chatting — what else are you planning today?",
                translate_fn, target_lang,
            )
        )

    merged = merge_profile(profile, {**session_delta, **clear_delta, "correctSentences": profile.get("correctSentences", 0) + 1})
    return _pack(
        merged, {**session_delta, **clear_delta, "correctSentences": profile.get("correctSentences", 0) + 1},
        teacher_en, teacher_tr, None, 1, "practice_success",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=teacher_en,
    )


def _contextual_reply(
    user_text: str, lang: str, history: list[dict], profile: dict,
    roleplay: str | None, correction: tuple | None,
    srs_prompt: str | None = None,
    vocab_hint: dict | None = None,
) -> str:
    """Bağlama uygun cevap — LLM yokken doğal sohbet için."""
    if correction and correction[0] >= 2:
        correct, ex_en = correction[1], correction[3]
        if correct:
            parts = [f"Almost! A more natural sentence is:\n\"{correct}\""]
            if ex_en:
                parts.append(ex_en)
            if correction[0] >= 3:
                parts.append("Now you try saying it correctly, then we'll keep chatting.")
            else:
                parts.append("So, tell me more — what happened?")
            return "\n\n".join(parts)

    ul = user_text.lower()
    recent_teacher = _recent_teacher_texts(history)
    recent_user = _recent_user_texts(history)
    avoid = " ".join(recent_teacher[:2]).lower()

    def fresh(template: str) -> str:
        return template if template.lower()[:30] not in avoid else ""

    if re.search(r"\b(hello|hi|hey|good morning|good evening|merhaba|selam)\b", ul):
        r = fresh("Hello! I'm glad we're chatting. How are you today?")
        return r or "Hi again! What's on your mind today?"

    if re.search(r"\b(how are you|how're you|nasılsın|nasilsin)\b", ul):
        return "I'm doing well, thank you! How about you — how has your day been?"

    if re.search(r"\b(i'?m|i am) (fine|good|ok|well|great|tired|busy|happy|sad)\b", ul):
        mood = re.search(r"\b(fine|good|ok|well|great|tired|busy|happy|sad)\b", ul)
        m = mood.group(1) if mood else "fine"
        if m == "tired":
            return "I understand — being tired is tough. Did you sleep well last night? What made you tired today?"
        if m in ("happy", "good", "great", "fine", "well", "ok"):
            return "That's good to hear! What did you do today that made you feel that way?"
        if m == "busy":
            return "Busy days can be exhausting. What kept you busy today?"
        if m == "sad":
            return "I'm sorry to hear that. Do you want to talk about it?"

    if re.search(r"\b(run|ran|running|jog|jogging)\b", ul):
        return "Running is great exercise! How far did you run? Do you run often?"

    if re.search(r"\b(read|book|books)\b", ul):
        return "Nice! What kind of book was it? Do you enjoy reading in English?"

    if re.search(r"\b(sleep|sleeping|slept|slipping)\b", ul):
        return "Rest is important! Did you sleep well? Or are you planning to sleep soon?"

    if re.search(r"\b(park|beach|museum|cinema|restaurant|cafe|coffee)\b", ul):
        place = re.search(r"\b(park|beach|museum|cinema|restaurant|cafe|coffee)\b", ul).group(1)
        return f"The {place} sounds nice! What did you do there? Did you go alone or with someone?"

    if re.search(r"\b(yesterday|last week|last weekend|last night)\b", ul):
        when = re.search(r"\b(yesterday|last week|last weekend|last night)\b", ul).group(1)
        if "park" in ul or "work" in ul or "home" in ul:
            return f"Oh, you went there {when}? That sounds interesting. What was the best part?"
        return f"Tell me more about what you did {when}. Where did you go and who were you with?"

    if re.search(r"\b(will go|going to|gonna|i'll go|i will)\b", ul):
        if "work" in ul:
            return "Got it — you're heading to work. What time do you usually start? What do you do there?"
        if "school" in ul or "class" in ul:
            return "School days can be busy! What are you studying? Do you enjoy it?"
        return "That sounds like a plan! When are you going, and what will you do there?"

    if re.search(r"\b(start|begin|finish|end|leave)\b", ul) and re.search(
        r"\b(at|o'clock|\d|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|morning|evening)\b", ul
    ):
        return "That's a clear schedule! Do you commute to work, or is it close to home? What do you usually do first when you arrive?"

    if re.search(r"\b(hour|minute|time|clock|schedule|shift)\b", ul):
        return "Time management is important. Is that a typical schedule for you, or was today different?"

    if re.search(r"\b(work|office|job|colleague|boss|meeting)\b", ul):
        if "office" in ul and re.search(r"\b(in|at)\b", ul):
            return "Working in an office — do you enjoy it? What's a typical day like for you?"
        if recent_user and any("work" in u.lower() for u in recent_user[:1]):
            return "That sounds interesting! What's the most challenging part of your job?"
        return "Work can be demanding. What do you do at work? Tell me about a typical day."

    if re.search(r"\b(tired|exhausted|sleepy|yorgun)\b", ul):
        if vocab_hint and vocab_hint.get("word", "").lower() not in ul:
            w = vocab_hint["word"]
            return (
                f"I understand — that sounds tough. You could also say \"I'm {w}\" for a stronger word. "
                f"Why do you feel tired today?"
            )
        return "I understand. Rest is important. What made you feel tired — work, travel, or something else?"

    if re.search(r"\b(antalya|istanbul|london|paris|travel|trip|vacation|holiday|flight|hotel)\b", ul):
        return "That sounds wonderful! What did you enjoy most? Would you go back there?"

    if re.search(r"\b(food|eat|lunch|dinner|breakfast|cook|restaurant)\b", ul):
        return "Food is a great topic! What did you have? Do you like cooking at home?"

    if re.search(r"\b(family|mother|father|brother|sister|child|children|kids)\b", ul):
        return "Family is important. Tell me more — how big is your family? What do you like doing together?"

    if re.search(r"\b(weather|rain|sun|cold|hot|snow)\b", ul):
        return "The weather affects our mood, doesn't it? What's the weather like where you are today?"

    if re.search(r"\b(yes|yeah|yep|sure|ok|okay)\b", ul) and len(ul.split()) <= 4:
        if recent_teacher:
            last_q = recent_teacher[0]
            if "?" in last_q:
                return "Great! Can you tell me a bit more in detail? I'm listening."
        return "Okay! What would you like to talk about next?"

    if srs_prompt and srs_prompt.lower() not in avoid:
        return srs_prompt

    weak = profile.get("weakAreas") or []
    if "past_tense" in weak and "what did you" not in avoid:
        return "By the way — what did you do yesterday?"
    if "be_verb" in weak and "how are you feeling" not in avoid:
        return "How are you feeling right now?"

    import random
    if len(ul.split()) <= 2 and not re.search(r"\b(yes|yeah|no|ok|okay|hello|hi|hey)\b", ul):
        return (
            "I'd love to understand you better. Can you try a full sentence? "
            "For example, tell me what you did today or what you're planning."
        )

    pool = [p for p in FOLLOWUPS.get(lang, FOLLOWUPS["en"]) if p.lower()[:25] not in avoid]
    if not pool:
        pool = FOLLOWUPS.get(lang, FOLLOWUPS["en"])
    topic = random.choice(TOPICS_BY_LEVEL.get(profile.get("currentLevel", "A1"), TOPICS_BY_LEVEL["A1"]))
    return random.choice(pool) + f" Maybe we can talk about {topic}?"


def _fallback_reply(
    user_text: str, lang: str, history: list[dict], profile: dict,
    roleplay: str | None, correction: tuple | None,
    srs_prompt: str | None = None,
    vocab_hint: dict | None = None,
) -> str:
    return _contextual_reply(
        user_text, lang, history, profile, roleplay, correction, srs_prompt, vocab_hint,
    )


def _help_mode(
    user_text: str, target_lang: str, translate_fn: Callable[[str, str, str], str],
    profile: dict, session_delta: dict,
) -> dict[str, Any]:
    phrase_tr = _extract_turkish_phrase(user_text)
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    mismatch = _detect_tr_meaning_mismatch(phrase_tr)
    if mismatch:
        return _meaning_error_help_mode(
            phrase_tr, mismatch, target_lang, profile, session_delta, translate_fn,
        )

    analysis = _analyze_for_teaching(phrase_tr, target_lang, translate_fn)
    translated = safe_str(analysis.get("natural_target")).strip()
    if not translated:
        translated = _rule_natural_translate_tr(phrase_tr, target_lang, translate_fn)
        analysis["natural_target"] = translated

    teacher_en = translated
    teacher_tr = _format_compact_help(phrase_tr, translated, lang_name)
    delta = {
        **session_delta,
        "lastTeacherText": translated,
        "pendingPracticePhrase": translated,
        "pendingPracticeTr": phrase_tr,
    }
    pairs = analysis.get("phrase_pairs") or []
    help_tts = [{"tr": p["tr"], "en": p["en"]} for p in pairs[:3] if p.get("tr") and p.get("en")]
    if not help_tts:
        help_tts = [{"tr": phrase_tr, "en": translated}]
    result = _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "help",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=translated,
        speak_tr="",
        speak_tr_first=False,
        phonetic_en=pronounce_text(translated, target_lang),
        translate_fn=translate_fn,
        target_lang=target_lang,
    )
    result["help_tts_pairs"] = help_tts
    taught = list(profile.get("taughtPatterns") or [])
    if translated and translated not in taught:
        taught.append(translated[:80])
        result["profile"] = merge_profile(result.get("profile", profile), {"taughtPatterns": taught[-15:]})
    return result


def _is_confusion_request(text: str) -> bool:
    """Öğrenci anlamadığını söylüyor — pratik cevabı sanma."""
    t = text.strip()
    if not t:
        return False
    if CONFUSION_RE.search(t):
        return True
    low = t.lower()
    return bool(re.search(
        r"^(i\s+)?(don't|do not|didn't)\s+understand",
        low,
    ))


def _confusion_help_mode(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
    history: list[dict],
) -> dict[str, Any]:
    """Anlamadım / don't understand — Türkçe açıkla, pratik modunu kapat."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    last_teacher = profile.get("lastTeacherText") or _last_teacher_question(history, profile) or ""
    pending = safe_str(profile.get("pendingPracticePhrase")).strip()
    clear = {"pendingPracticePhrase": None, "pendingPracticeTr": None}

    teacher_tr_parts = ["Tamam — açıklayayım.\n"]
    teacher_en_parts: list[str] = ["No problem — let me explain.\n"]

    if pending:
        meaning_tr = safe_str(profile.get("pendingPracticeTr")).strip()
        if translate_fn and not meaning_tr:
            meaning_tr = _to_tr(pending, translate_fn, target_lang)
        teacher_tr_parts.append(f"📌 Çalıştığımız cümle:\n\"{pending}\"")
        if meaning_tr:
            teacher_tr_parts.append(f"Türkçesi: {meaning_tr}")
        teacher_en_parts.append(f"We were practicing: \"{pending}\"")

    if last_teacher and last_teacher != pending:
        teacher_tr_parts.append(f"\n💬 Son {lang_name} mesajım:\n\"{last_teacher}\"")
        if translate_fn:
            tr_line = _to_tr(last_teacher, translate_fn, target_lang)
            if tr_line:
                teacher_tr_parts.append(f"Türkçesi: {tr_line}")
        teacher_en_parts.append(f"My last message: \"{last_teacher}\"")

    teacher_tr_parts.append(
        "\nİstersen Türkçe 'yardım ben …' de, veya 'tekrar et' / 'yavaş' diyebilirsin."
    )
    teacher_en_parts.append(
        "\nYou can say 'repeat', 'slow', or ask in Turkish starting with 'yardım …'."
    )

    teacher_tr = "\n".join(teacher_tr_parts)
    teacher_en = "\n\n".join(teacher_en_parts)
    display_en = last_teacher or pending or teacher_en

    merged = merge_profile(profile, {**session_delta, **clear})
    speak_en = pending or last_teacher or ""
    result = _pack(
        merged, {**session_delta, **clear},
        display_en, teacher_tr, None, 1, "confusion_help",
        waiting=True, user_text=user_text, teacher_en=display_en,
        speak_text=speak_en,
        speak_tr=safe_str(profile.get("pendingPracticeTr")).strip()[:120],
        speak_tr_first=True,
        phonetic_en=pronounce_text(speak_en, target_lang) if speak_en else "",
    )
    return result


def _yardim_help_mode(
    user_text: str, target_lang: str, profile: dict, session_delta: dict,
    translate_fn: Callable[[str, str, str], str],
) -> dict[str, Any]:
    return _help_mode(user_text, target_lang, translate_fn, profile, session_delta)


def _turkish_in_conversation(
    user_text: str, target_lang: str, profile: dict, session_delta: dict,
    translate_fn: Callable[[str, str, str], str],
    history: list[dict], roleplay: str | None,
) -> dict[str, Any]:
    """Türkçe konuşuldu ama yardım istenmedi — hedef dilde sohbete devam et."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    meaning_en = translate_fn(user_text, "tr", target_lang)

    llm_msgs = []
    for h in history[-10:]:
        role = "assistant" if h.get("role") == "teacher" else "user"
        llm_msgs.append({"role": role, "content": h.get("text", "")})
    llm_msgs.append({
        "role": "user",
        "content": (
            f"[Student spoke Turkish: \"{user_text}\" — meaning roughly: \"{meaning_en}\"] "
            f"Reply naturally in {lang_name}. Acknowledge briefly, then continue the conversation "
            f"with a follow-up question. Encourage them to answer in {lang_name}."
        ),
    })
    teacher_en = _llm(
        llm_msgs, target_lang, profile.get("currentLevel", "A1"), roleplay,
        extra="Do not translate word-for-word. Be warm like a human tutor.",
    )
    if not teacher_en:
        teacher_en = (
            f"I understand — you said something like: \"{meaning_en}\". "
            f"Let's keep going in {lang_name}. Can you tell me more about that in {lang_name}?"
        )

    note = "💬 Türkçe konuştun — anladım. Hedef dilde devam edelim."
    teacher_tr = _teacher_tr_from_en(teacher_en, translate_fn, target_lang, note_tr=note)
    return _pack(
        profile, session_delta, teacher_en, teacher_tr, None, 1, "coach_tr",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=teacher_en,
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


def greeting(
    lang: str,
    profile: dict | None = None,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    profile = merge_profile(profile, None)
    profile = reset_daily_if_needed(profile)
    step = int(profile.get("lessonStep") or 0)
    step = max(0, min(step, len(LESSON_CURRICULUM) - 1))
    cur = LESSON_CURRICULUM[step]
    lang_name = LANG_NAMES.get(lang, lang)

    if step == 0:
        text_en = "Hey! How are you today?"
    elif step == 1:
        text_en = "Hi again! Last time we practiced greetings. Can you say: \"I'm fine, thank you. How are you?\""
    else:
        starters = GREETINGS.get(lang, GREETINGS["en"])
        text_en = starters[step % len(starters)]

    intro_tr = (
        f"Merhaba! Ben senin {lang_name} öğretmeninim. "
        f"Bugün: {cur['title']} — {cur['focus']}\n\n"
        f"Karşımda bir öğrenci varmış gibi konuşacağız. Hazır mısın?"
    )
    motiv = motivation_message(profile)
    if motiv:
        intro_tr = f"{motiv}\n\n{intro_tr}"
    srs_prompt, srs_id = pick_srs_prompt(profile)
    if srs_prompt:
        text_en = f"{text_en}\n\n{srs_prompt}"
    teacher_en = text_en
    teacher_tr = intro_tr
    delta = {
        "lastTeacherText": text_en,
        "waitingForUser": True,
        "sessionStartAt": _now_iso(),
        "pendingSrsId": srs_id,
        "microStep": 0,
        "lessonStep": 0,
    }
    result = _pack(
        profile, delta, teacher_en, teacher_tr, None, 1, "greeting",
        waiting=True, teacher_en=teacher_en, speak_text=text_en,
        phonetic_en=pronounce_text(text_en.split("\n")[0], lang),
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
    original_text = user_text.strip()
    session_delta: dict[str, Any] = {
        "totalSentences": profile.get("totalSentences", 0) + (1 if original_text else 0),
    }

    if translate_fn and target_lang == "en":
        learner = _try_learner_clarify(
            original_text, history, profile, session_delta, target_lang, translate_fn,
        )
        if learner:
            learner["weekly_progress"] = weekly_progress(learner["profile"])
            return learner

    user_text = _normalize_stt_text(original_text)
    if user_lang == "tr" and target_lang == "en" and not _is_real_turkish(user_text):
        user_lang = "en"

    last_teacher = profile.get("lastTeacherText") or ""
    if not user_text:
        return greeting(target_lang, profile, translate_fn=translate_fn)

    if SPECIAL_TR.search(user_text):
        low = user_text.lower()
        if re.search(r"türkçe|anlamadım", low):
            tr_explain = (
                f"Son {LANG_NAMES.get(target_lang, target_lang)} cümlem:\n\"{last_teacher}\"\n\n"
            )
            if translate_fn and last_teacher:
                tr_explain += _to_tr(last_teacher, translate_fn, target_lang)
            else:
                tr_explain += last_teacher
            tr_explain += "\n\nAnlamadıysan tekrar sorabilir veya 'tekrar et' diyebilirsin."
            return _pack(
                profile, session_delta, last_teacher, tr_explain,
                None, 1, "explain_tr", waiting=True, user_text=user_text, teacher_en=last_teacher,
            )
        if re.search(r"repeat|tekrar", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "repeat", waiting=True, user_text=user_text)
        if re.search(r"slow|yavaş", low) and last_teacher:
            return _pack(profile, session_delta, last_teacher, None, None, 1, "slow", waiting=True, user_text=user_text, speak_slow=True)

    if BREAKDOWN_RE.search(user_text):
        breakdown = grammar_breakdown(last_teacher, profile.get("currentLevel", "A1"))
        return _pack(profile, session_delta, breakdown, breakdown, None, 1, "breakdown", waiting=True, user_text=user_text)

    # Niyet onayı bekleniyor (evet/hayır)
    pending_intent = safe_str(profile.get("pendingIntentConfirm")).strip()
    if pending_intent:
        if _is_yes_reply(user_text):
            result = _intent_confirm_yes(profile, session_delta, target_lang, translate_fn)
            result["weekly_progress"] = weekly_progress(result["profile"])
            return result
        if _is_no_reply(user_text):
            result = _intent_confirm_no(profile, session_delta)
            result["weekly_progress"] = weekly_progress(result["profile"])
            return result
        if not _is_yardim_request(user_text) and not HELP_RE.search(user_text):
            result = _intent_confirm_remind(profile, session_delta)
            result["weekly_progress"] = weekly_progress(result["profile"])
            return result

    # Anlamadım / don't understand — pratik beklerken bile önce açıkla
    if _is_confusion_request(user_text):
        result = _confusion_help_mode(
            user_text, target_lang, profile, session_delta, translate_fn, history,
        )
        result["weekly_progress"] = weekly_progress(result["profile"])
        return result

    # Nasıl söyleyeceğimi bilmiyorum — kısa yardım veya kişisel cümle
    if _is_how_to_say_stuck(user_text):
        if re.search(
            r"başka\s+şey|söylemek\s+istiyorum.*bilmiyorum|türkçe\s+söyle",
            user_text,
            re.I,
        ) and not _extract_phrase_from_how_to_say_stuck(user_text):
            result = _turkish_help_coach_mode(
                user_text, target_lang, profile, session_delta, translate_fn,
            )
        else:
            phrase_tr = _extract_phrase_from_how_to_say_stuck(user_text)
            if phrase_tr:
                mismatch = _detect_tr_meaning_mismatch(phrase_tr)
                if mismatch:
                    result = _meaning_error_help_mode(
                        phrase_tr, mismatch, target_lang, profile, session_delta, translate_fn,
                    )
                else:
                    result = _help_mode(
                        f"yardım {phrase_tr}", target_lang, translate_fn, profile, session_delta,
                    )
            else:
                result = _how_to_say_stuck_short_mode(
                    target_lang, profile, session_delta, translate_fn, user_text,
                )
        result["weekly_progress"] = weekly_progress(result["profile"])
        return result

    # "yardım" ile başlayan istek → cümle kurma öğretimi
    if translate_fn and _is_yardim_request(user_text):
        return _yardim_help_mode(user_text, target_lang, profile, session_delta, translate_fn)

    # Açık yardım ifadeleri (nasıl söylerim, kısmını söyleyemiyorum…)
    if translate_fn and HELP_RE.search(user_text):
        return _help_mode(user_text, target_lang, translate_fn, profile, session_delta)

    pending = safe_str(profile.get("pendingPracticePhrase")).strip()
    if pending and _should_exit_practice_mode(user_text, pending):
        clear_practice = {"pendingPracticePhrase": None, "pendingPracticeTr": None, "awaitingTargetPhrase": None}
        session_delta = {**session_delta, **clear_practice}
        profile = merge_profile(profile, session_delta)
        pending = ""

    # Türkçe ilerleme onayı — geriye dönme
    if _is_progress_confirmation(user_text):
        result = _try_progress_confirm_turn(
            user_text, target_lang, profile, session_delta, translate_fn,
        )
        if result:
            result["weekly_progress"] = weekly_progress(result["profile"])
            return result

    # Telaffuz geri bildirimi
    if PRONUNCIATION_FEEDBACK_RE.search(user_text):
        result = _try_pronunciation_feedback_turn(
            user_text, target_lang, profile, session_delta, history, speak_slow, translate_fn,
        )
        if result:
            result["weekly_progress"] = weekly_progress(result["profile"])
            return result

    # "Okay" = yanlış değil, hedef ifadeyi yönlendir
    if pending or profile.get("awaitingTargetPhrase"):
        okay = _try_okay_guidance_turn(user_text, target_lang, profile, session_delta, translate_fn)
        if okay:
            okay["weekly_progress"] = weekly_progress(okay["profile"])
            return okay

    # Yardım sonrası pratik — sadece gerçekten doğru söylendiyse
    if pending and translate_fn:
        resumed = _resume_after_help(
            user_text, target_lang, profile, session_delta, translate_fn, history, roleplay,
        )
        if resumed:
            resumed["weekly_progress"] = weekly_progress(resumed["profile"])
            return resumed
        wrong = _wrong_practice_after_help(
            user_text, target_lang, profile, session_delta, translate_fn,
        )
        if wrong:
            wrong["weekly_progress"] = weekly_progress(wrong["profile"])
            return wrong

    # Pratik beklenirken — yalnızca hâlâ pratik modundaysa düzelt
    if pending:
        fallback = _wrong_practice_after_help(
            user_text, target_lang, profile, session_delta, translate_fn,
        )
        if fallback:
            fallback["weekly_progress"] = weekly_progress(fallback["profile"])
            return fallback

    # Kırık İngilizce — AI'dan önce niyet sor (yes understand books vb.)
    if translate_fn and target_lang == "en" and user_lang == "en":
        if _is_broken_learner_english(original_text):
            intent_early = _try_intent_clarify(
                user_text, history, profile, session_delta, target_lang, translate_fn,
                display_text=original_text,
            )
            if intent_early:
                intent_early["weekly_progress"] = weekly_progress(intent_early["profile"])
                return intent_early

    # Bozuk STT — kesin cümle uydurma
    if user_lang == "en" and _is_garbled_stt(original_text):
        stt_result = _try_stt_clarify_turn(
            original_text, target_lang, profile, session_delta, history, translate_fn,
        )
        if stt_result:
            stt_result["weekly_progress"] = weekly_progress(stt_result["profile"])
            return stt_result

    # Selamlaşma tekrar "you" hatası — hızlı kural düzeltmesi
    if target_lang == "en" and user_lang == "en":
        greet_fix = _try_rule_greeting_fix(
            original_text, target_lang, profile, session_delta, translate_fn,
        )
        if greet_fix:
            greet_fix["weekly_progress"] = weekly_progress(greet_fix["profile"])
            return greet_fix

    # V2 kural tabanlı öğretmen davranışları
    if target_lang == "en" and user_lang == "en":
        for handler in (
            lambda: _try_repeated_weakness_turn(original_text, target_lang, profile, session_delta, translate_fn),
            lambda: _try_children_plural_teaching(original_text, target_lang, profile, session_delta, translate_fn),
            lambda: _try_reading_fragment_teaching(original_text, target_lang, profile, session_delta, translate_fn),
            lambda: _try_students_correct_extend(original_text, target_lang, profile, session_delta, translate_fn),
            lambda: _try_hello_chain_success(original_text, target_lang, profile, session_delta, translate_fn),
        ):
            result = handler()
            if result:
                result["weekly_progress"] = weekly_progress(result["profile"])
                return result

    # AI öğretmen — ana beyin
    ai_result = _try_ai_tutor_turn(
        original_text, user_lang, target_lang, history, profile,
        session_delta, roleplay, speak_slow, translate_fn,
    )
    if ai_result:
        ai_result["weekly_progress"] = weekly_progress(ai_result["profile"])
        return ai_result

    # AI yoksa — kural tabanlı yedek
    if translate_fn:
        intent_result = _try_intent_clarify(
            user_text, history, profile, session_delta, target_lang, translate_fn,
            display_text=original_text,
        )
        if intent_result:
            intent_result["weekly_progress"] = weekly_progress(intent_result["profile"])
            return intent_result

    # Gerçek Türkçe konuşuldu → hedef dilde sohbet
    if user_lang == "tr" and translate_fn and _is_real_turkish(user_text):
        return _turkish_in_conversation(
            user_text, target_lang, profile, session_delta, translate_fn, history, roleplay,
        )

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
    elif correction_level >= 2:
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
    for h in history[-8:]:
        role = "assistant" if h.get("role") == "teacher" else "user"
        llm_msgs.append({"role": role, "content": h.get("text", "")})
    llm_msgs.append({"role": "user", "content": user_text})

    teacher_en = ""
    teacher_tr = ""
    correction_tr_block = None

    if correction_level >= 2:
        teacher_en, teacher_tr = _build_conversation_teach(
            user_text, correct_phrase, category, explain_en, explain_tr, target_lang, translate_fn,
        )
        correction_tr_block = teacher_tr
    else:
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
        teacher_en = teacher
        teacher_tr = _teacher_tr_from_en(teacher_en, translate_fn, target_lang)

    display_teacher = teacher_en

    result = _pack(
        merged, session_delta, display_teacher, teacher_tr, correct_phrase, correction_level,
        "correction" if correction_level >= 2 else "conversation",
        waiting=True, user_text=user_text, speak_slow=speak_slow,
        teacher_en=teacher_en,
        speak_text=correct_phrase if correction_level >= 3 and correct_phrase else teacher_en,
        speak_tr_first=correction_level >= 2,
        correction_detail={
            "userSaid": user_text,
            "correctEn": correct_phrase,
            "explainTr": explain_tr,
            "explainEn": explain_en,
            "category": category,
            "level": correction_level,
        } if correction_level >= 2 else None,
        translate_fn=translate_fn,
        target_lang=target_lang,
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


def _strip_for_tts(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\u2600-\u26FF\uFE0F]+", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _turkish_tts_text(text: str) -> str:
    """TTS için yalnızca Türkçe içerik — İngilizce cümleleri çıkar."""
    if not text:
        return ""
    text = _strip_for_tts(text)
    tr_lines: list[str] = []
    for line in re.split(r"[\n.]+", text):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'"[^"]*"', "", line)
        line = re.sub(r"'[^']*'", "", line).strip()
        if not line:
            continue
        has_tr = bool(re.search(r"[ğüşıöçĞÜŞİÖÇ]", line))
        en_words = len(re.findall(r"\b[a-zA-Z]{3,}\b", line))
        tr_hint = bool(re.search(
            r"\b(sanırım|demek|istedin|doğru|yanlış|kelime|cümle|fiil|neden|malısın|"
            r"değil|için|gibi|olarak|henüz|beklenen|tekrar|dene|açıklama|yapısı|anlamı|"
            r"demeye|çalıştın|hata|düzeltme|sen|ben|biz|bugün|işe|gitmek|koşmak|okumak|"
            r"uyumak|yorgun|tam|olmadı|beklenen|yüksek|sesle|sohbet|devam|harika|tabii|"
            r"öğrenelim|küçük|gramer|türkçe|ipucu|neden|olarak|şimdi|sonra|bir|çok|"
            r"evet|hayır|merhaba|lütfen|unutma|unut|demeli|söyle|söylemeli)\b",
            line,
            re.I,
        ))
        if has_tr or tr_hint:
            tr_lines.append(line)
        elif en_words <= 2:
            tr_lines.append(line)
    out = " ".join(tr_lines)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:550]


def _build_speak_tr(
    explain_tr: str,
    grammar_tr: str = "",
    word_breakdown_tr: str = "",
    corr_level: int = 1,
    inferred: str = "",
) -> str:
    """Düzeltme için kısa Türkçe sesli özet — tam açıklama değil."""
    if corr_level < 2:
        return ""
    parts: list[str] = []
    if inferred:
        parts.append(f"Sanırım bunu demek istedin: {inferred}")
    if grammar_tr:
        parts.append(_strip_for_tts(grammar_tr)[:120])
    elif word_breakdown_tr:
        parts.append(_strip_for_tts(word_breakdown_tr)[:120])
    return _turkish_tts_text(" ".join(p for p in parts if p))[:200]


def _wrong_practice_after_help(
    user_text: str,
    target_lang: str,
    profile: dict,
    session_delta: dict,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Yardım sonrası yanlış pratik — kontrollü düzeltme."""
    pending = safe_str(profile.get("pendingPracticePhrase")).strip()
    pending_tr = safe_str(profile.get("pendingPracticeTr")).strip()
    if not pending:
        return None
    if _is_greeting_or_small_talk(user_text):
        return None
    if _should_exit_practice_mode(user_text, pending):
        return None
    if _is_confusion_request(user_text):
        return None
    if _practice_phrase_match(user_text, pending):
        return None
    if pending_tr and _practice_phrase_match(user_text, pending_tr):
        return None
    if _is_simple_acknowledgment(user_text):
        return None

    meaning_tr = pending_tr or ""
    if translate_fn and pending:
        try:
            meaning_tr = translate_fn(pending, target_lang, "tr") or meaning_tr
        except Exception:
            pass

    teacher_tr = (
        f"Henüz tam olmadı.\n\n"
        f"Sen dedin: \"{user_text.strip()}\"\n\n"
        f"Beklenen cümle: \"{pending}\"\n"
        f"Türkçesi: {meaning_tr}\n\n"
        f"Tekrar dene — yüksek sesle doğru cümleyi söyle."
    )
    speak_tr = (
        f"Henüz tam olmadı. Doğrusu: {meaning_tr}. Tekrar dene."
    )
    teacher_en = (
        f"Not quite yet. You said: \"{user_text.strip()}\"\n\n"
        f"Try again: \"{pending}\"\n\n"
        f"Say it out loud — I'm listening!"
    )
    merged = merge_profile(profile, session_delta)
    return _pack(
        merged, session_delta, teacher_en, teacher_tr, pending, 2, "practice_retry",
        waiting=True, user_text=user_text, teacher_en=teacher_en, speak_text=pending,
        speak_tr=speak_tr, speak_tr_first=True,
        correction_detail={
            "userSaid": user_text,
            "correctEn": pending,
            "explainTr": teacher_tr,
            "inferredMeaning": meaning_tr,
        },
        translate_fn=translate_fn,
        target_lang=target_lang,
    )


def _pack(
    profile: dict, delta: dict, teacher: str, explain_tr: str | None,
    correction: str | None, corr_level: int, msg_type: str,
    waiting: bool = True, user_text: str = "", speak_slow: bool = False,
    teacher_en: str | None = None, speak_text: str | None = None,
    correction_detail: dict | None = None,
    speak_tr: str | None = None,
    grammar_tr: str | None = None,
    word_breakdown_tr: str | None = None,
    speak_tr_first: bool | None = None,
    translate_fn: Callable[[str, str, str], str] | None = None,
    target_lang: str = "en",
    phonetic_en: str | None = None,
) -> dict:
    p = merge_profile(profile, delta)
    en = teacher_en or teacher
    p["lastTeacherText"] = en
    p["waitingForUser"] = waiting
    speak = speak_text or (correction if corr_level >= 3 and correction else en)
    gtr = safe_str(grammar_tr or "")
    wtr = safe_str(word_breakdown_tr or "")
    inferred = ""
    if correction_detail and correction_detail.get("inferredMeaning"):
        inferred = safe_str(correction_detail.get("inferredMeaning"))
    explicit = _turkish_tts_text(_strip_for_tts(safe_str(speak_tr or "")))
    if explicit:
        str_speak = explicit[:220]
    elif corr_level >= 2:
        str_speak = (_build_speak_tr("", gtr, wtr, corr_level, inferred) or "")[:220]
    else:
        str_speak = ""
    tr_first = speak_tr_first if speak_tr_first is not None else (
        corr_level >= 2 and bool(str_speak)
    )
    if correction_detail is not None:
        if gtr:
            correction_detail = {**correction_detail, "grammarTr": gtr}
        if wtr:
            correction_detail = {**correction_detail, "wordBreakdown": wtr}
        en_fix = safe_str(correction_detail.get("correctEn") or correction).strip()
        if en_fix and translate_fn:
            correct_tr = _to_tr(en_fix, translate_fn, target_lang)
            if correct_tr:
                correction_detail = {**correction_detail, "correctTr": correct_tr}
                if corr_level >= 2 and not explicit:
                    str_speak = f"Doğrusu: {correct_tr}"[:220]
                ph = _simple_en_phonetic(en_fix)
                if ph:
                    correction_detail = {**correction_detail, "phoneticEn": ph}
    ph_main = safe_str(phonetic_en).strip()
    if not ph_main and en and target_lang != "tr":
        ph_main = _simple_en_phonetic(en.split("\n")[0])
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
        "speak_tr": str_speak,
        "grammar_tr": gtr,
        "word_breakdown_tr": wtr,
        "speak_tr_first": tr_first,
        "phonetic_en": ph_main,
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
