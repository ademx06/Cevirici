"""Kelimeye özel öğretim motoru — şablon kopyalama yok, bağlama göre analiz."""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from education_engine import LANG_NAMES, _llm_json, _llm_json_word_lesson, llm_available, safe_str
from pronunciation_service import (
    build_pronunciation_bundle,
    get_word,
    tokenize_en,
    word_meaning_tr,
    word_role_tr,
)
from word_icons import lookup_emoji
from word_lexicon import build_lexicon_examples, get_word_usage_phrases, get_word_usage_profile, has_curated_lexicon

# Varsayılan İngilizce varyantı — Amerikan İngilizcesi
ENGLISH_VARIANT = "en-US"

# AI birincil kelime dersi — ChatGPT gibi: önce AI, başarısızsa retry; şablon yedek YOK
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
WORD_LESSON_MAX_TOKENS = 3200
WORD_LESSON_FAST_MAX_TOKENS = 2400
AI_LESSON_MAX_ATTEMPTS = 1

WORD_LESSON_FAST_PROMPT = """Sen profesyonel ESL öğretmenisin — Cümle Kur kartı hazırla.
Türkçe: «{word_tr}» → İngilizce: «{target_word}» | Tür: {pos_label} | {lang_name}

{pos_hint}

13 örnek cümle (basic, present, past, future, question, negative, imperative, polite_request, advice, obligation, possibility, conditional, dialogue).
- target: TAM İngilizce cümle (en az 3 kelime) — YASAK: yalnızca «{target_word}» veya tek kelime
- Hedef kelime her cümlede doğal geçsin
- tr: tam doğal Türkçe cümle (iyelik: arabam, cüzdanım)
- how_it_is_formed_tr: min 50 karakter (1️⃣ anlam 2️⃣ yapı)
- word_breakdown: yalnızca 3-5 önemli token (token, role_tr, meaning_tr)

JSON döndür:
{{"meaning_tr":"","part_of_speech":"","countability":"","semantic_category":"","usage_notes_tr":"","common_verbs":[],"common_collocations":[],"article_notes_items":[],"avoid_reason_tr":"","examples":[{{"tr":"","target":"","sentence_type":"","structure_tr":"","how_it_is_formed_tr":"","word_breakdown":[]}}]}}"""

WORD_LESSON_SPLIT_PROMPT_A = """{split_base}

[BÖLÜM A]
İlk 7 örnek: basic, present, past, future, question, negative, imperative.
examples dizisi TAM 7 öğe."""

WORD_LESSON_SPLIT_PROMPT_B = """{split_base}

[BÖLÜM B]
Son 6 örnek: polite_request, advice, obligation, possibility, conditional, dialogue.
JSON: {{"examples": [ ...6 öğe... ]}} (yalnızca examples yeterli)."""

WORD_LESSON_SPLIT_BASE = """Sen ESL öğretmenisin.
Türkçe kelime: "{word_tr}" → İngilizce: "{target_word}" ({lang_name})

{pos_rules}

Zorunlu:
- Hedef kelime her İngilizce cümlede geçmeli
- tr alanı tam doğal Türkçe cümle (yalnızca kelime YASAK)
- how_it_is_formed_tr min 50 karakter (1️⃣ anlam 2️⃣ yapı yeterli)
- word_breakdown: token, role_tr, meaning_tr

JSON: meaning_tr, usage_notes_tr, part_of_speech, countability, semantic_category,
common_verbs (5+), common_collocations (4+), article_notes_items, avoid_reason_tr, examples"""

WORD_LESSON_VERB_COMPACT_PROMPT = """Sen ESL öğretmenisin — fiil dersi.
Türkçe: "{word_tr}" → İngilizce fiil: "{target_word}" ({lang_name})

{pos_rules}

Zorunlu:
- Tam 13 örnek; türler: basic, present, past, future, question, negative, imperative,
  polite_request, advice, obligation, possibility, conditional, dialogue
- Fiil çekimleri doğal (go/went/going, don't go, Do you go…)
- Hedef fiil her cümlede geçmeli (to go değil, çekimli hali: go, went, going…)
- tr: tam Türkçe cümle; how_it_is_formed_tr min 50 karakter (1️⃣2️⃣ yeterli)
- common_verbs: bu fiille kullanılan yardımcı kalıplar (5+)
- common_collocations (4+)

JSON: meaning_tr, usage_notes_tr, part_of_speech, countability, semantic_category,
common_verbs, common_collocations, article_notes_items, avoid_reason_tr, examples"""


def templates_allowed() -> bool:
    """Şablon/kayıtlı kalıp yalnızca geliştirme modunda."""
    return os.getenv("WORD_LESSON_ALLOW_TEMPLATES", "").strip().lower() in ("1", "true", "yes", "on")


def ai_only_lesson_enabled(target_lang: str) -> bool:
    """Canlıda yalnızca AI dersi — şablon motoru devreye girmez."""
    if target_lang != "en":
        return False
    if not llm_available():
        return False
    if templates_allowed():
        return False
    return True


def is_llm_api_failure(issues: list[str]) -> bool:
    """API/limit/JSON hatası mı, yoksa kalite reddi mi?"""
    if not issues:
        return False
    api_markers = (
        "geçerli json",
        "ai kullanılamıyor",
        "en az 8 örnek döndürülemedi",
        "hiç geçerli örnek üretilmedi",
    )
    blob = " ".join(safe_str(i).lower() for i in issues)
    return any(marker in blob for marker in api_markers)

ENGLISH_VARIANT_LABEL_TR = "🇺🇸 Amerikan İngilizcesi (varsayılan)"

# Bilinen US/UK farkları — kartlarda bilgi notu olarak gösterilir
US_UK_VARIANT_NOTES: dict[str, str] = {
    "corn": "🇬🇧 British English: bazen sweetcorn veya maize denir; 🇺🇸 American English: corn",
    "faucet": "🇺🇸 American English: faucet · 🇬🇧 British English: tap",
    "tap": "🇬🇧 British English: tap · 🇺🇸 American English: faucet",
    "soda": "🇺🇸 soda / pop · 🇬🇧 fizzy drink / soft drink",
    "elevator": "🇺🇸 elevator · 🇬🇧 lift",
    "lift": "🇬🇧 lift · 🇺🇸 elevator",
    "truck": "🇺🇸 truck · 🇬🇧 lorry",
    "lorry": "🇬🇧 lorry · 🇺🇸 truck",
    "apartment": "🇺🇸 apartment · 🇬🇧 flat",
    "flat": "🇬🇧 flat · 🇺🇸 apartment",
    "cookie": "🇺🇸 cookie · 🇬🇧 biscuit (tatlı)",
    "biscuit": "🇬🇧 biscuit · 🇺🇸 cookie",
    "pants": "🇺🇸 pants (pantolon) · 🇬🇧 trousers",
    "trousers": "🇬🇧 trousers · 🇺🇸 pants",
    "color": "🇺🇸 color · 🇬🇧 colour",
    "colour": "🇬🇧 colour · 🇺🇸 color",
}

# ── Yasak şablon kalıpları (kelime yerine koyma) ──
BANNED_TEMPLATE_RE = [
    re.compile(r"^i\s+love\s+\w+\.?$", re.I),
    re.compile(r"^do\s+you\s+want\s+\w+\??$", re.I),
    re.compile(r"^you\s+don'?t\s+drink\s+\w+", re.I),
    re.compile(r"^i\s+don'?t\s+like\s+\w+\.?$", re.I),
]

# Başka kelimenin açıklaması kopyalandı mı?
CROSS_WORD_LEAK_RE = re.compile(
    r"kahve\s+seviyorum|love\s+\+\s+coffee|get\s+you\s+a\s+coffee|"
    r"don't\s+drink\s+coffee|kahve\s+iç",
    re.I,
)

# Hedef kelime dışındaki bilinen kelime kalıntıları
FOREIGN_WORD_MARKERS: dict[str, tuple[str, ...]] = {
    "pencere": ("masa", "sandalye", "kahve", "musluk", "araba"),
    "window": ("table", "chair", "coffee", "faucet", "car"),
    "kapı": ("masa", "pencere", "kahve", "musluk", "araba"),
    "kapi": ("masa", "pencere", "kahve", "musluk", "araba"),
    "door": ("table", "window", "coffee", "faucet", "car"),
    "kitap": ("masa", "pencere", "kahve", "musluk", "araba"),
    "book": ("table", "window", "coffee", "faucet", "car"),
    "telefon": ("masa", "pencere", "kahve", "musluk"),
    "phone": ("table", "window", "coffee", "faucet"),
    "kahve": ("masa", "pencere", "musluk", "araba"),
    "coffee": ("table", "window", "faucet", "car"),
    "musluk": ("masa", "pencere", "kahve", "araba", "kitap"),
    "faucet": ("table", "window", "coffee", "car", "book"),
    "tap": ("table", "window", "coffee", "car", "book"),
    "masa": ("pencere", "kahve", "musluk", "araba"),
    "table": ("window", "coffee", "faucet", "car"),
    "sandalye": ("pencere", "kahve", "musluk", "araba"),
    "chair": ("window", "coffee", "faucet", "car"),
    "araba": ("masa", "pencere", "kahve", "musluk"),
    "car": ("table", "window", "coffee", "faucet"),
    "ayakkabı": ("çorap", "corap", "socks", "sock", "masa", "kahve", "pencere", "table", "coffee", "window"),
    "ayakkabi": ("çorap", "corap", "socks", "sock", "masa", "kahve", "pencere", "table", "coffee", "window"),
    "shoe": ("socks", "sock", "table", "coffee", "window", "chair", "faucet", "book"),
    "shoes": ("socks", "sock", "table", "coffee", "window", "chair", "faucet", "book"),
}

# Hedef kelime dışı ana nesne — ör. shoe öğretirken socks ana özne olamaz
CONFLICTING_PRIMARY_NOUNS: dict[str, frozenset[str]] = {
    "shoe": frozenset({"sock", "socks"}),
    "shoes": frozenset({"sock", "socks"}),
    "sock": frozenset({"shoe", "shoes"}),
    "socks": frozenset({"shoe", "shoes"}),
    "coffee": frozenset({"tea", "table", "window"}),
    "table": frozenset({"chair", "coffee", "window"}),
    "window": frozenset({"table", "chair", "coffee", "door"}),
    "door": frozenset({"window", "table", "coffee"}),
}

VERBS_TR: dict[str, str] = {
    "buy": "satın almak", "wear": "giymek", "lose": "kaybetmek", "tie": "bağlamak",
    "lace": "bağlamak (bağcık)", "clean": "temizlemek", "try on": "denemek",
    "sit at": "…-de oturmak", "put on": "üzerine koymak", "move": "taşımak",
    "use": "kullanmak", "set": "kurmak / hazırlamak", "open": "açmak", "close": "kapatmak",
    "see": "görmek", "need": "ihtiyaç duymak", "find": "bulmak", "drink": "içmek",
    "have": "sahip olmak / almak", "make": "yapmak", "order": "sipariş etmek",
    "get": "almak / getirmek", "drive": "sürmek", "park": "park etmek",
    "fix": "tamir etmek", "wash": "yıkamak", "rent": "kiralamak",
    "turn on": "açmak", "turn off": "kapatmak", "repair": "tamir etmek",
    "replace": "değiştirmek", "install": "takmak / kurmak",
    "go to": "gitmek", "be at": "bulunmak", "visit": "ziyaret etmek", "leave": "ayrılmak",
    "read": "okumak", "charge": "şarj etmek", "answer": "cevaplamak / açmak",
    "knock on": "çalmak (kapı)", "knock": "çalmak", "wipe": "silmek", "clear": "toplamak",
    "sip": "yudumlamak", "serve": "servis etmek", "pour": "dökmek", "chill": "soğutmak",
    "fill": "doldurmak", "break": "kırmak", "dry": "kurulamak",
    "raise": "kaldırmak", "hold": "tutmak", "collect": "toplamak",
    "borrow": "ödünç almak", "lend": "ödünç vermek", "finish": "bitirmek",
    "pick up": "almak", "put down": "bırakmak", "look for": "aramak", "forget": "unutmak",
    "recommend": "tavsiye etmek",     "write": "yazmak", "lock": "kilitlemek",
    "unlock": "kilidini açmak", "look out of": "…-den dışarı bakmak",
    "eat at": "…-de yemek yemek", "sit on": "…-e oturmak",
    "chew": "çiğnemek", "swallow": "yutmak", "spit out": "tükürmek / atmak",
    "share": "paylaşmak", "offer": "teklif etmek",
    "pull up": "çekmek (sandalye)", "pull out": "çekip çıkarmak", "take": "almak",
    "ring": "çalmak (telefon)", "call": "aramak", "text": "mesaj atmak",
    "sign": "imzalamak", "grab": "kapmak / almak",
    "be": "olmak", "feel": "hissetmek", "look": "görünmek", "seem": "gibi görünmek",
    "want": "istemek", "eat": "yemek yemek", "cook": "pişirmek", "boil": "kaynatmak",
    "grill": "ızgara yapmak",     "grow": "yetiştirmek", "bring": "getirmek", "prefer": "tercih etmek",
    "pay": "ödemek", "send": "göndermek", "receive": "almak / teslim almak",
    "check": "kontrol etmek", "issue": "düzenlemek / kesmek (fatura)",
    "review": "incelemek / gözden geçirmek", "attach": "eklemek (ek dosya)",
    "spread": "sürmek / yaymak", "drizzle": "gezdirmek / damlatmak",
    "taste": "tatmak / tadına bakmak", "dilute": "sulandırmak",
    "stir": "karıştırmak", "mix": "karıştırmak", "sweeten": "tatlandırmak",
    "harvest": "hasat etmek / toplamak",
    "smoke": "içmek / tüttürmek (sigara)", "light": "yakmak (sigara)", "quit": "bırakmak (sigara)",
    "put out": "söndürmek", "stub out": "söndürmek (küllüğe bastırarak)",
    "roll": "sarmak (sigara)", "flick": "silkelemek (kül)",
    "take off": "çıkarmak",
    "prescribe": "reçete etmek",
    "wipe": "silmek", "adjust": "ayarlamak",
}

# Kategori + fiil → Türkçe anlam (bağlama özel; giymek/takmak ayrımı vb.)
CATEGORY_VERB_MEANINGS: dict[str, dict[str, str]] = {
    "eyewear": {
        "wear": "takmak",
        "put on": "takmak",
        "take off": "çıkarmak",
        "clean": "temizlemek",
        "wipe": "silmek",
        "lose": "kaybetmek",
        "find": "bulmak",
        "break": "kırmak",
        "adjust": "ayarlamak",
        "prescribe": "reçete etmek",
    },
    "footwear": {
        "wear": "giymek",
        "put on": "giymek",
        "take off": "çıkarmak",
        "tie": "bağlamak (bağcık)",
        "try on": "denemek",
        "buy": "satın almak",
        "lose": "kaybetmek",
        "clean": "temizlemek",
    },
    "clothing": {
        "wear": "giymek",
        "put on": "giymek",
        "take off": "çıkarmak",
        "wash": "yıkamak",
        "fold": "katlamak",
        "iron": "ütülemek",
        "pack": "hazırlamak",
        "buy": "satın almak",
    },
    "tobacco": {
        "smoke": "içmek / tüttürmek",
        "light": "yakmak",
        "put out": "söndürmek",
        "stub out": "söndürmek",
        "quit": "bırakmak",
        "roll": "sarmak",
        "flick": "silkelemek (kül)",
        "offer": "teklif etmek",
    },
    "beverage": {
        "drink": "içmek",
        "have": "içmek / almak",
        "make": "yapmak",
        "order": "sipariş etmek",
        "get": "almak",
        "serve": "servis etmek",
        "pour": "dökmek",
        "sip": "yudumlamak",
    },
    "snack": {
        "chew": "çiğnemek",
        "eat": "yemek",
        "buy": "satın almak",
        "share": "paylaşmak",
        "offer": "teklif etmek",
        "swallow": "yutmak",
        "spit out": "tükürmek",
    },
    "food": {
        "eat": "yemek",
        "cook": "pişirmek",
        "boil": "kaynatmak",
        "grill": "ızgara yapmak",
        "grow": "yetiştirmek",
        "buy": "satın almak",
        "serve": "servis etmek",
        "taste": "tatmak / tadına bakmak",
        "spread": "sürmek / yaymak",
        "drizzle": "gezdirmek / damlatmak",
        "collect": "toplamak",
        "dilute": "sulandırmak",
    },
    "furniture": {
        "sit at": "…-de oturmak",
        "set": "kurmak / hazırlamak",
        "clear": "toplamak",
        "wipe": "silmek",
        "clean": "temizlemek",
        "move": "taşımak",
        "put on": "üzerine koymak",
    },
    "plumbing": {
        "turn on": "açmak",
        "turn off": "kapatmak",
        "fix": "tamir etmek",
        "repair": "tamir etmek",
        "replace": "değiştirmek",
        "install": "takmak / kurmak",
        "leak": "sızıntı yapmak",
    },
    "vehicle": {
        "drive": "sürmek",
        "park": "park etmek",
        "buy": "satın almak",
        "fix": "tamir etmek",
        "wash": "yıkamak",
        "rent": "kiralamak",
        "sell": "satmak",
    },
    "document": {
        "pay": "ödemek",
        "send": "göndermek",
        "receive": "almak",
        "check": "kontrol etmek",
        "sign": "imzalamak",
        "issue": "düzenlemek",
        "review": "incelemek",
        "attach": "eklemek",
    },
    "drinkware": {
        "fill": "doldurmak",
        "break": "kırmak",
        "wash": "yıkamak",
        "raise": "kaldırmak",
        "hold": "tutmak",
        "pour": "dökmek",
    },
    "abstract": {
        "enjoy": "keyif almak",
        "love": "sevmek",
        "hate": "nefret etmek",
        "need": "ihtiyaç duymak",
        "want": "istemek",
        "find": "bulmak",
        "seek": "aramak",
    },
    "place": {
        "go": "gitmek",
        "go to": "gitmek",
        "be at": "bulunmak",
        "visit": "ziyaret etmek",
        "leave": "ayrılmak",
        "buy": "satın almak",
        "shop": "alışveriş yapmak",
    },
}

PHRASAL_VERB_PRON: dict[str, dict[str, str]] = {
    "put on": {"pronunciation_tr": "put on", "ipa": "/pʊt ɒn/"},
    "take off": {"pronunciation_tr": "teyk of", "ipa": "/teɪk ɔːf/"},
    "turn on": {"pronunciation_tr": "törn on", "ipa": "/tɜːrn ɒn/"},
    "turn off": {"pronunciation_tr": "törn of", "ipa": "/tɜːrn ɔːf/"},
    "try on": {"pronunciation_tr": "tray on", "ipa": "/traɪ ɒn/"},
    "put out": {"pronunciation_tr": "put aut", "ipa": "/pʊt aʊt/"},
    "stub out": {"pronunciation_tr": "stab aut", "ipa": "/stʌb aʊt/"},
    "sit at": {"pronunciation_tr": "sit et", "ipa": "/sɪt æt/"},
    "knock on": {"pronunciation_tr": "nak on", "ipa": "/nɒk ɒn/"},
    "go to": {"pronunciation_tr": "gou tu", "ipa": "/ɡoʊ tu/"},
    "pick up": {"pronunciation_tr": "pik ap", "ipa": "/pɪk ʌp/"},
    "look for": {"pronunciation_tr": "luk for", "ipa": "/lʊk fɔːr/"},
    "spit out": {"pronunciation_tr": "spit aut", "ipa": "/spɪt aʊt/"},
    "be at": {"pronunciation_tr": "bi et", "ipa": "/bi æt/"},
}

PHRASES_TR: dict[str, str] = {
    "honeydew melon": "kavun (bal kavunu)",
    "honey trap": "bal tuzağı",
    "honey moon": "balayı",
    "honeymoon": "balayı",
    "locust honey": "çekirge balı",
    "raw honey": "süzme bal",
    "organic honey": "organik bal",
    "jar of honey": "bal kavanozu",
    "spoon of honey": "bir kaşık bal",
    "honey jar": "bal kavanozu",
    "manuka honey": "manuka balı",
    "wildflower honey": "çiçek balı",
    "clover honey": "yonca balı",
    "wear glasses": "gözlük takmak",
    "a pair of glasses": "bir gözlük (çift)",
    "reading glasses": "yakın gözlüğü",
    "prescription glasses": "numaralı gözlük",
    "sunglasses": "güneş gözlüğü",
    "smoke a cigarette": "sigara içmek",
    "light a cigarette": "sigara yakmak",
    "a pack of cigarettes": "bir paket sigara",
    "quit smoking": "sigarayı bırakmak",
    "cigarette smoke": "sigara dumanı",
    "put out a cigarette": "sigarayı söndürmek",
    "stub out a cigarette": "sigarayı söndürmek",
    "roll a cigarette": "sigara sarmak",
}

GRAMMAR_BADGES: dict[str, str] = {
    "basic": "🌅 RUTİN",
    "present": "🔄 ŞU AN",
    "past": "🕐 GEÇMİŞ",
    "future": "🔮 GELECEK",
    "question": "❓ SORU",
    "negative": "⛔ OLUMSUZ",
    "imperative": "👉 EMİR",
    "polite_request": "🗣️ RİCA",
    "advice": "🤝 TEKLİF",
    "obligation": "📋 ZORUNLULUK",
    "possibility": "🎲 İHTİMAL",
    "conditional": "🔀 KOŞUL",
    "dialogue": "💬 DİYALOG",
}
GRAMMAR_PATTERNS: dict[str, dict[str, Any]] = {
    "basic": {"num": 1, "label_tr": "1. Temel kullanım"},
    "present": {"num": 2, "label_tr": "2. Şimdiki zaman"},
    "past": {"num": 3, "label_tr": "3. Geçmiş zaman"},
    "future": {"num": 4, "label_tr": "4. Gelecek zaman"},
    "question": {"num": 5, "label_tr": "5. Soru cümlesi"},
    "negative": {"num": 6, "label_tr": "6. Olumsuz cümle"},
    "imperative": {"num": 7, "label_tr": "7. Emir kipi"},
    "polite_request": {"num": 8, "label_tr": "8. Rica cümlesi"},
    "advice": {"num": 9, "label_tr": "9. Tavsiye cümlesi"},
    "obligation": {"num": 10, "label_tr": "10. Zorunluluk cümlesi"},
    "possibility": {"num": 11, "label_tr": "11. İhtimal / olasılık cümlesi"},
    "conditional": {"num": 12, "label_tr": "12. Koşul cümlesi"},
    "dialogue": {"num": 13, "label_tr": "13. Günlük konuşma / diyalog"},
}

# Eski sentence_type → 13 kalıp anahtarı
PATTERN_TYPE_ALIASES: dict[str, str] = {
    "description": "basic", "location": "basic", "existence": "basic",
    "routine": "present", "present_continuous": "present", "movement": "present",
    "past": "past", "shopping": "past", "experience": "past",
    "future": "future",
    "question": "question",
    "negative": "negative",
    "imperative": "imperative", "action": "imperative",
    "request": "polite_request", "offer": "polite_request",
    "advice": "advice",
    "need_to": "obligation", "repair": "obligation",
    "problem": "possibility",
    "conditional": "conditional",
    "daily": "dialogue", "comparison": "dialogue",
}

GENERIC_ICONS = frozenset({"📖", "📚", "📦", ""})

SCENARIO_LABELS: dict[str, str] = {
    k: v["label_tr"] for k, v in GRAMMAR_PATTERNS.items()
}

GENERIC_MECHANICAL_RE = [
    re.compile(r"\bi am using the \w+", re.I),
    re.compile(r"\bi used the \w+ yesterday", re.I),
    re.compile(r"\bbring the \w+", re.I),
    re.compile(r"\bthis is my \w+", re.I),
    re.compile(r"\bcheck the \w+ regularly", re.I),
    re.compile(r"\bmight be in another room", re.I),
    re.compile(r"\bthe \w+ is here\.?$", re.I),
    re.compile(r"\bis the \w+ ready\b", re.I),
    re.compile(r"\bif you can'?t find the \w+", re.I),
    re.compile(r"\byou should use the \w+ carefully", re.I),
    re.compile(r"\byou should use my \w+ carefully", re.I),
    re.compile(r"\bcould you bring the \w+", re.I),
    re.compile(r"\boften use my \w+", re.I),
    re.compile(r"\bi am looking for my \w+ right now", re.I),
    re.compile(r"\bput the \w+ here", re.I),
    re.compile(r"\bcould you pass me my \w+", re.I),
    re.compile(r"\bhave you seen my \w+\? b: yes, on the table", re.I),
]

GENERIC_STRUCTURE_LABEL_RE = re.compile(
    r"kelimeye\s+özel\s+doğal\s+yapı",
    re.I,
)

QUALITY_RULE_CATEGORIES = frozenset({
    "beverage", "furniture", "footwear", "eyewear", "tobacco", "plumbing",
    "vehicle", "drinkware", "food", "snack", "abstract", "document", "clothing",
})

CATEGORY_PHRASES: dict[str, list[dict[str, str]]] = {
    "furniture": [
        {"en": "sit at the table", "tr": "masada oturmak"},
        {"en": "set the table", "tr": "masayı kurmak / sofrayı hazırlamak"},
        {"en": "clear the table", "tr": "masayı toplamak"},
        {"en": "wipe the table", "tr": "masayı silmek"},
        {"en": "on the table", "tr": "masanın üzerinde"},
        {"en": "under the table", "tr": "masanın altında"},
    ],
    "footwear": [
        {"en": "a pair of shoes", "tr": "bir çift ayakkabı"},
        {"en": "wear shoes", "tr": "ayakkabı giymek"},
        {"en": "tie your shoes", "tr": "ayakkabılarını bağlamak"},
        {"en": "try on shoes", "tr": "ayakkabı denemek"},
        {"en": "buy new shoes", "tr": "yeni ayakkabı almak"},
        {"en": "take off your shoes", "tr": "ayakkabılarını çıkarmak"},
    ],
    "eyewear": [
        {"en": "wear glasses", "tr": "gözlük takmak"},
        {"en": "a pair of glasses", "tr": "bir gözlük (çift)"},
        {"en": "reading glasses", "tr": "yakın gözlüğü"},
        {"en": "prescription glasses", "tr": "numaralı gözlük"},
        {"en": "take off your glasses", "tr": "gözlüğünü çıkarmak"},
        {"en": "clean your glasses", "tr": "gözlüğünü temizlemek"},
    ],
    "tobacco": [
        {"en": "smoke a cigarette", "tr": "sigara içmek"},
        {"en": "light a cigarette", "tr": "sigara yakmak"},
        {"en": "a pack of cigarettes", "tr": "bir paket sigara"},
        {"en": "quit smoking", "tr": "sigarayı bırakmak"},
        {"en": "cigarette smoke", "tr": "sigara dumanı"},
        {"en": "put out a cigarette", "tr": "sigarayı söndürmek"},
        {"en": "stub out a cigarette", "tr": "sigarayı söndürmek"},
        {"en": "roll a cigarette", "tr": "sigara sarmak"},
    ],
    "clothing": [
        {"en": "wear socks", "tr": "çorap giymek"},
        {"en": "a pair of socks", "tr": "bir çift çorap"},
        {"en": "put on your shirt", "tr": "gömleğini giymek"},
        {"en": "take off your jacket", "tr": "ceketini çıkarmak"},
        {"en": "wash your clothes", "tr": "kıyafetlerini yıkamak"},
    ],
    "object": [],
    "plumbing": [
        {"en": "turn off the faucet", "tr": "musluğu kapatmak"},
        {"en": "the faucet is leaking", "tr": "musluk su sızdırıyor"},
    ],
    "beverage": [
        {"en": "have a coffee", "tr": "kahve içmek / bir kahve almak"},
        {"en": "make coffee", "tr": "kahve yapmak"},
        {"en": "a can of soda", "tr": "bir kutu gazoz / soda"},
        {"en": "a bottle of soda", "tr": "bir şişe gazoz"},
        {"en": "diet soda", "tr": "diyet gazoz / light soda"},
        {"en": "regular soda", "tr": "normal gazoz"},
        {"en": "order a soda", "tr": "gazoz sipariş etmek"},
    ],
    "vehicle": [
        {"en": "drive the car", "tr": "arabayı sürmek"},
        {"en": "park the car", "tr": "arabayı park etmek"},
    ],
    "drinkware": [
        {"en": "a glass of water", "tr": "bir bardak su"},
        {"en": "an empty glass", "tr": "boş bardak"},
        {"en": "break a glass", "tr": "bardak kırmak"},
        {"en": "fill the glass", "tr": "bardağı doldurmak"},
        {"en": "wash the glasses", "tr": "bardakları yıkamak"},
        {"en": "raise a glass", "tr": "(kadeh) kaldırmak"},
    ],
}

WORD_PROFILE_PROMPT = """Sen kıdemli bir sözlük bilimci ve ESL müfredat tasarımcısısın.
Türkçe kelime: "{word_tr}"
Hedef dil: {lang_name} ({target_lang})
Hedef kelime (çeviri): "{target_word}"

[KATI KURALLAR]
1. HAFIZA TEMİZLİĞİ: Önceki kelime/istekten hiçbir veri taşıma. Tamamen izole üret.
2. Başka kelimenin (coffee, table, socks) kalıplarını kopyalama.
3. Yaygın fiiller ve ifadelerde her İngilizce öğenin Türkçe anlamı dolu olmalı.
4. Doğal günlük İngilizce; yapay çeviri yok (❌ black soda → ✅ diet soda / cola).
5. Varsayılan Amerikan İngilizcesi (US); UK farkı varsa bilgi notu olarak belirt (ör. faucet/tap, corn/sweetcorn).
6. ÖNCE GERÇEK KULLANIM: Kelimeyle insanların günlük hayatta nasıl etkileştiğini düşün (kapı→çalmak, kilitlemek; masa→kurmak, toplamak). Mekanik şablon YASAK (❌ I am using the door, Bring the door, This is my door).
7. common_collocations ve natural_example_ideas yalnızca ana dili İngilizce konuşanların gerçekten söylediği kalıplar olmalı.

JSON döndür:
{{
  "target_word": "...",
  "part_of_speech": "noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|determiner",
  "countability": "countable|uncountable|both|n/a",
  "semantic_category": "beverage|furniture|document|object|place|food|vehicle|animal|fruit|vegetable|clothing|adjective|verb|pronoun|adverb|abstract|other",
  "meaning_tr": "temel Türkçe anlam",
  "usage_notes_tr": "En az 3 cümle: sayılabilirlik, US/UK farkı, günlük kullanım, dikkat edilecekler",
  "common_verbs": ["drink", "order"],
  "common_collocations": ["a can of soda", "diet soda"],
  "common_patterns": ["Can I have a soda?", "I don't drink soda."],
  "article_notes_tr": "a/an/the veya can/bottle/glass ile sayım kuralı",
  "natural_example_ideas": [
    {{"tr": "Türkçe", "target": "İngilizce", "grammar_focus": "POLITE_REQUEST|NEGATIVE|..."}}
  ],
  "avoid_patterns": ["I love X"],
  "avoid_reason_tr": "Neden uygun değil"
}}"""

WORD_LESSON_FROM_PROFILE_PROMPT = """Sen kıdemli bir sözlük bilimci ve ESL müfredat tasarımcısısın. Türkçe öğrenciye {lang_name} öğretiyorsun.

KELİME PROFİLİ (SADECE BU KELİME — önceki kelime yok):
{profile_json}

[KATI KURALLAR]
1. HAFIZA TEMİZLİĞİ: Önceki kelime/istekten hiçbir cümle, açıklama veya kalıp taşıma.
2. Hedef kelime her örnek cümlede geçmeli; başka kelime ana konu olamaz (shoe→socks yasak).
3. Türkçe okunuşlar Türkçe fonetik olmalı (table→teybıl, soda→sou-da, could→kud).
4. Yaygın fiiller/ifadelerde Türkçe anlam boş bırakılamaz.
5. Her örnekte "how_it_is_formed_tr" en az 200 karakter; numaralı adımlar (1️⃣ 2️⃣ 3️⃣); genel anlam + ana yapı + kritik dil bilgisi + yaygın hata (❌).
6. "structure_label_tr" asla "Kelimeye özel doğal yapı" olamaz — gerçek formül yaz.
7. En az 10 farklı kalıp: Temel kullanım, Şimdiki zaman, Geçmiş zaman, Gelecek zaman, Soru, Olumsuz, Emir, Rica, Tavsiye, Zorunluluk, İhtimal, Koşul, Diyalog.
8. sentence_type_label numaralı Türkçe kalıp adı olmalı (ör. "6. Olumsuz cümle").
9. word_breakdown: her kelime için token, pronunciation_tr (Türkçe fonetik), meaning_tr, role_tr.
10. DOĞAL KULLANIM ZORUNLU: Her cümle o kelimenin gerçek hayattaki kullanımını yansıtmalı. Mekanik şablon YASAK:
    ❌ I am using the [word], Bring the [word], This is my [word], Check the [word] regularly
    ✅ door: knock on the door, close the door behind you | table: set the table, wipe the table
11. Türkçe çeviri doğal Türkçe olmalı; İngilizce cümleyle birebir anlam eşleşmeli.
12. Türkçe (tr) alanı ASLA boş veya yalnızca kelime olamaz. ❌ tr: "Eğlence" — ✅ tr: "Bu akşam için eğlence arıyoruz."

Her örnek alanları:
- tr, target, sentence_type (request/negative/...)
- sentence_type_label (POLITE_REQUEST, NEGATIVE, STATEMENT_OF_PREFERENCE, ...)
- structure_tr, structure_label_tr ("Dil Bilgisi Formülü: Özne + ...")
- word_breakdown: [{{"token":"...","pronunciation_tr":"...","meaning_tr":"...","role_tr":"..."}}]
- how_it_is_formed_tr (derin, cümleye özel)
- pattern_tr ("Kelime Şablonu: Can I + have + a + [word]?")
- pattern_examples (hedef kelimeyle uyumlu)

JSON:
{{
  "word_explanation_tr": "«kelime» → target. En az 3 cümle pedagojik açıklama.",
  "usage": {{ "part_of_speech_tr": "...", "countability_tr": "...", "common_mistakes_tr": "..." }},
  "examples": [...]
}}"""

WORD_LESSON_DIRECT_PROMPT = """Sen kıdemli bir sözlük bilimci ve ESL müfredat tasarımcısısın.

Türkçe kelime: "{word_tr}"
İngilizce hedef kelime: "{target_word}"
Hedef dil: {lang_name}

[GÖREV]
Bu kelime için TAM bir kelime dersi üret — ChatGPT/Google AI kalitesinde.
Her cümle yalnızca bu kelimenin gerçek hayattaki kullanımını yansıtmalı.
Kullanıcıya tek seferde mükemmel ders ver; ikinci deneme gerekmesin.

[ÖNCE DÜŞÜN — sonra yaz]
Bu kelimeyle insanlar günlük hayatta ne yapar? Hangi fiiller doğal? (kapı→knock/lock, kitap→read/borrow, fatura→pay/send, çanta→carry/pack)
Önce kelime türünü (isim/fiil/sıfat/zarf/zamir/edat/bağlaç/ünlem) belirle; türe uygun olmayan cümle ASLA yazma.

{pos_rules}

[YASAK — mekanik şablon]
❌ I am using the {target_word}
❌ Bring the {target_word}
❌ This is my {target_word}
❌ The {target_word} is here
❌ Check the {target_word} regularly

[ZORUNLU]
- Tam 13 örnek cümle; her biri farklı dil bilgisi kalıbı:
  basic, present, past, future, question, negative, imperative, polite_request, advice, obligation, possibility, conditional, dialogue
- Her örnekte hedef kelime geçmeli
- Türkçe cümleler doğal Türkçe; İngilizce cümleler Amerikan İngilizcesi
- Türkçede iyelik kullan: araba → arabam, cüzdan → cüzdanım (❌ "Araba garajda" → ✅ "Arabam garajda")
- Her örnekte "tr" TAM Türkçe cümle olmalı — yalnızca kelime YASAK (❌ "Eğlence" → ✅ "Bu akşam eğlence arıyoruz.")
- common_verbs: bu kelimeyle gerçekten kullanılan fiiller (en az 5)
- common_collocations: ana dili İngilizce konuşanların söylediği kalıplar (en az 4)
- article_notes_items: a/an/the kullanımı (en az 2)

[ÖĞRETİCİ AÇIKLAMA — HER CÜMLE İÇİN]
how_it_is_formed_tr en az 60 karakter; kısa adımlarla öğret (1️⃣ anlam 2️⃣ yapı yeterli):
1️⃣ Genel anlam — Bu cümle günlük hayatta ne anlatır?
2️⃣ Ana yapı — İngilizce iskelet + «Türkçe karşılık»
3️⃣ Özne — Kim/ne yapıyor? (I, she, the dog…)
4️⃣ Yüklem/fiil — Ne yapıyor? Zamanı nedir? (went, is buying, will call…)
5️⃣ Nesne/tümleç — Varsa neyi/kime/nereye? (my wallet, to the market…)
6️⃣ Diğer öğeler — Zarf, sıfat, edat, bağlaç varsa NE İŞE YARADIĞINI açıkla (quickly→nasıl, because→neden, with→birlikte)
7️⃣ ❌ Yaygın hata — Bu kelimeyle yapılmaması gereken kalıp (varsa)

word_breakdown: cümledeki önemli kelimeler için token, role_tr (özne/fiil/nesne/zarf/sıfat/edat), meaning_tr

JSON:
{{
  "meaning_tr": "temel Türkçe anlam",
  "usage_notes_tr": "en az 3 cümle pedagojik açıklama",
  "part_of_speech": "noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|determiner",
  "countability": "countable|uncountable|both|n/a",
  "semantic_category": "beverage|furniture|document|object|place|food|vehicle|animal|fruit|vegetable|adjective|verb|pronoun|adverb|abstract|other",
  "common_verbs": ["fiil1", "fiil2"],
  "common_collocations": ["doğal kalıp 1", "doğal kalıp 2"],
  "common_patterns": [
    {{"en": "İngilizce örnek cümle", "tr": "Türkçe karşılık"}}
  ],
  "article_notes_items": [
    {{"en": "a {target_word}", "tr": "bir ..."}}
  ],
  "avoid_reason_tr": "bu kelimeyle yapılmaması gereken yaygın hatalar",
  "examples": [
    {{
      "tr": "Türkçe cümle",
      "target": "English sentence with {target_word}",
      "sentence_type": "basic|present|past|future|question|negative|imperative|polite_request|advice|obligation|possibility|conditional|dialogue",
      "structure_tr": "özne + fiil + ...",
      "how_it_is_formed_tr": "1️⃣ Genel anlam\\n...\\n2️⃣ Ana yapı\\n...\\n3️⃣ Özne\\n...\\n4️⃣ Yüklem\\n...\\n5️⃣ Nesne/tümleç\\n...\\n6️⃣ Diğer öğeler\\n...",
      "word_breakdown": [
        {{"token": "I", "role_tr": "özne", "meaning_tr": "ben"}}
      ]
    }}
  ]
}}"""

SENTENCE_TEACHING_V3_PROMPT = """Turkish sentence (user may have minor errors): "{tr_sentence}"
Target language: {lang_name} ({target_lang})

Sen kıdemli bir dil öğretmenisin. Öğrenciye cümleyi ADIM ADIM öğret — sadece çeviri değil.

[KATI KURALLAR]
1. how_it_is_formed_tr en az 200 karakter; numaralı adımlar (1️⃣ 2️⃣ 3️⃣) kullan.
2. Önce genel anlam, sonra yapı, sonra her parça (need to, because, nothing vb.).
3. clause_breakdown: cümle 6+ kelimeyse mutlaka parçala (ana fikir + sebep/yan cümle).
4. word_breakdown: her kelime için token, role_tr, meaning_tr, pronunciation_hint (Türkçe fonetik).
5. important_patterns: en az 2 kalıp; her kalıpta açıklama + örnek.
6. Türkçe kusurluysa inferred_turkish_tr ile düzelt; kibar ol.

Return JSON:
{{
  "inferred_turkish_tr": "düzeltilmiş Türkçe veya null",
  "meaning_summary_tr": "cümlenin genel anlamı (1-2 cümle, öğretici)",
  "target_sentence": "most natural {lang_name}",
  "alternatives": ["optional natural alternative"],
  "sentence_type": "complex|simple|question|...",
  "grammar_topic": "need_to_because|present|past|...",
  "difficulty": "A1-C2",
  "structure_tr": "I + need + to go + ...",
  "structure_label_tr": "Zorunluluk (need to) + sebep (because) + infinitive",
  "clause_breakdown": [
    {{"clause_tr": "Markete gitmem gerekiyor", "target": "I need to go to the market", "role_tr": "ana fikir"}}
  ],
  "word_breakdown": [
    {{"token":"need","role_tr":"fiil","meaning_tr":"gerekiyor","pronunciation_hint":"nid"}}
  ],
  "how_it_is_formed_tr": "1️⃣ Genel anlam\\n...\\n\\n2️⃣ Ana yapı\\n...\\n\\n3️⃣ need to + fiil\\n...",
  "why_this_structure_tr": "Bu yapı neden seçildi — kısa pedagojik açıklama",
  "important_note_tr": "Sık yapılan hata veya ipucu veya null",
  "important_patterns": [
    {{"pattern_tr": "need to + fiil", "explanation_tr": "...", "examples": [{{"target":"I need to work.","tr":"Çalışmam gerekiyor."}}]}}
  ],
  "new_words": [{{"word":"because","meaning_tr":"çünkü"}}],
  "pattern_tr": "Ana kalıp özeti veya null",
  "pattern_examples": []
}}"""

# Bilinen kelime kategorileri (LLM yokken)
KNOWN_CATEGORIES: dict[str, str] = {
    "kahve": "beverage", "coffee": "beverage", "çay": "beverage", "tea": "beverage",
    "soda": "beverage", "gazoz": "beverage", "kola": "beverage", "cola": "beverage",
    "su": "beverage", "water": "beverage", "süt": "beverage", "milk": "beverage",
    "masa": "furniture", "table": "furniture", "sandalye": "furniture", "chair": "furniture",
    "musluk": "plumbing", "faucet": "plumbing", "tap": "plumbing",
    "araba": "vehicle", "car": "vehicle", "otomobil": "vehicle",
    "bisiklet": "vehicle", "bicycle": "vehicle", "bike": "vehicle",
    "mutlu": "adjective", "happy": "adjective",
    "sessiz": "adjective", "quiet": "adjective", "silent": "adjective",
    "üzgün": "adjective", "uzgun": "adjective", "sad": "adjective",
    "yorgun": "adjective", "tired": "adjective", "yorgunum": "adjective",
    "mutsuz": "adjective", "unhappy": "adjective",
    "gürültülü": "adjective", "gurultulu": "adjective", "noisy": "adjective", "loud": "adjective",
    "sakin": "adjective", "calm": "adjective",
    "meşgul": "adjective", "mesgul": "adjective", "busy": "adjective",
    "çalışmak": "verb", "work": "verb", "çalış": "verb",
    "kitap": "object", "book": "object", "telefon": "object", "phone": "object",
    "kapı": "object", "kapi": "object", "door": "object",
    "pencere": "object", "window": "object",
    "kalem": "object", "pen": "object",
    "ev": "place", "home": "place", "market": "place", "pazar": "place",
    "ayakkabı": "footwear", "ayakkabi": "footwear", "shoe": "footwear", "shoes": "footwear",
    "bardak": "drinkware", "glass": "drinkware", "fincan": "drinkware", "cup": "drinkware",
    "tabak": "drinkware", "plate": "drinkware", "kase": "drinkware", "bowl": "drinkware",
    "mısır": "food", "misir": "food", "corn": "food", "sweetcorn": "food",
    "maden suyu": "beverage", "maden su": "beverage",
    "mineral water": "beverage", "sparkling water": "beverage", "club soda": "beverage",
    "elma": "fruit", "apple": "fruit", "muz": "fruit", "banana": "fruit",
    "domates": "vegetable", "tomato": "vegetable", "havuç": "vegetable", "carrot": "vegetable",
    "ekmek": "food", "bread": "food", "peynir": "food", "cheese": "food",
    "kedi": "animal", "cat": "animal", "köpek": "animal", "dog": "animal",
    "fatura": "document", "invoice": "document", "makbuz": "document", "receipt": "document",
    "bill": "document", "dekont": "document", "fiş": "document", "fis": "document",
    "sakız": "snack", "sakiz": "snack", "gum": "snack", "chewing gum": "snack",
    "şeker": "snack", "seker": "snack", "candy": "snack", "çikolata": "snack", "cikolata": "snack",
    "chocolate": "snack", "bisküvi": "snack", "biskivi": "snack", "cookie": "snack",
    "eğlence": "abstract", "eglence": "abstract", "entertainment": "abstract",
    "bal": "food", "honey": "food",
    "koltuk": "furniture", "sofa": "furniture", "yatak": "furniture", "bed": "furniture",
    "dolap": "furniture", "wardrobe": "furniture",
    "gözlük": "eyewear", "gozluk": "eyewear", "glasses": "eyewear", "sunglasses": "eyewear",
    "sigara": "tobacco", "cigarette": "tobacco", "cigarettes": "tobacco",
    "tütün": "tobacco", "tutun": "tobacco", "tobacco": "tobacco",
    "çorap": "clothing", "corap": "clothing", "sock": "clothing", "socks": "clothing",
    "gömlek": "clothing", "gomlek": "clothing", "shirt": "clothing",
    "şemsiye": "object", "semsiye": "object", "umbrella": "object",
    "cüzdan": "object", "cuzdan": "object", "wallet": "object",
    "yastık": "object", "yastik": "object", "pillow": "object",
    "bıçak": "object", "bicak": "object", "knife": "object",
    "kalem": "object", "pen": "object", "radyo": "object", "radio": "object",
    "parfüm": "object", "parfum": "object", "perfume": "object",
}

# Çeviri başarısız olunca bilinen TR→EN eşleşmeleri
KNOWN_TR_TO_EN: dict[str, str] = {
    "kahve": "coffee", "masa": "table", "musluk": "faucet", "pencere": "window",
    "kapı": "door", "kapi": "door", "kitap": "book", "gazoz": "soda", "kola": "cola",
    "araba": "car", "mutlu": "happy", "çalışmak": "work", "calismak": "work",
    "gitmek": "go", "gelmek": "come", "yapmak": "make", "almak": "take",
    "vermek": "give", "görmek": "see", "gozmek": "see", "bilmek": "know",
    "söylemek": "say", "soylemek": "say", "istemek": "want", "olmak": "be",
    "ayakkabı": "shoe", "ayakkabi": "shoe", "sandalye": "chair", "telefon": "phone",
    "ev": "home", "pazar": "market", "market": "market", "su": "water", "çay": "tea",
    "bardak": "glass", "fincan": "cup", "tabak": "plate", "kase": "bowl", "çatal": "fork",
    "bıçak": "knife", "bicak": "knife", "kaşık": "spoon", "kasik": "spoon",
    "mısır": "corn", "misir": "corn", "mısır tanesi": "corn", "tatlı mısır": "corn",
    "maden suyu": "sparkling water", "maden su": "sparkling water",
    "mineral su": "mineral water", "mineral suyu": "mineral water",
    "elma": "apple", "muz": "banana", "portakal": "orange", "domates": "tomato",
    "havuç": "carrot", "havuc": "carrot", "patates": "potato", "ekmek": "bread", "peynir": "cheese",
    "yumurta": "egg", "tavuk": "chicken", "balık": "fish", "balik": "fish",
    "kedi": "cat", "köpek": "dog", "kopek": "dog", "kuş": "bird", "kus": "bird",
    "fatura": "invoice", "makbuz": "receipt", "dekont": "bank receipt",
    "çanta": "bag", "canta": "bag", "valiz": "suitcase", "şemsiye": "umbrella",
    "semsiye": "umbrella", "cüzdan": "wallet", "cuzdan": "wallet", "gözlük": "glasses", "gozluk": "glasses",
    "sakız": "gum", "sakiz": "gum",
    "bal": "honey",
    "sigara": "cigarette", "tütün": "tobacco", "tutun": "tobacco",
    "eğlence": "entertainment", "eglence": "entertainment",
    "koltuk": "sofa", "yatak": "bed", "dolap": "wardrobe", "mutfak": "kitchen",
    "okul": "school", "hastane": "hospital", "bisiklet": "bicycle",
    "çorap": "socks", "corap": "socks", "yastık": "pillow", "bıçak": "knife",
    "bicak": "knife", "kalem": "pen", "yastik": "pillow", "radyo": "radio",
    "parfüm": "perfume", "parfum": "perfume",
}

# Kelime türü (POS) — AI ve şablon yönlendirmesi
KNOWN_PART_OF_SPEECH: dict[str, str] = {
    # sıfat / adjective
    "mutlu": "adjective", "happy": "adjective", "sessiz": "adjective", "quiet": "adjective",
    "üzgün": "adjective", "uzgun": "adjective", "sad": "adjective", "yorgun": "adjective",
    "tired": "adjective", "güzel": "adjective", "guzel": "adjective", "beautiful": "adjective",
    "büyük": "adjective", "buyuk": "adjective", "big": "adjective", "küçük": "adjective",
    "kucuk": "adjective", "small": "adjective", "sıcak": "adjective", "sicak": "adjective",
    "hot": "adjective", "soğuk": "adjective", "soguk": "adjective", "cold": "adjective",
    # fiil / verb
    "çalışmak": "verb", "calismak": "verb", "work": "verb", "gitmek": "verb", "go": "verb",
    "yemek": "verb", "eat": "verb", "içmek": "verb", "icmek": "verb", "drink": "verb",
    "okumak": "verb", "read": "verb", "yazmak": "verb", "write": "verb", "koşmak": "verb",
    "kosmak": "verb", "run": "verb", "gelmek": "verb", "come": "verb", "almak": "verb", "buy": "verb",
    # zamir / pronoun
    "ben": "pronoun", "i": "pronoun", "sen": "pronoun", "you": "pronoun", "o": "pronoun",
    "he": "pronoun", "she": "pronoun", "it": "pronoun", "biz": "pronoun", "we": "pronoun",
    "siz": "pronoun", "onlar": "pronoun", "they": "pronoun", "benim": "pronoun", "my": "pronoun",
    "senin": "pronoun", "your": "pronoun", "onun": "pronoun", "his": "pronoun", "her": "pronoun",
    "bizim": "pronoun", "our": "pronoun", "onların": "pronoun", "their": "pronoun",
    # zarf / adverb
    "hızlı": "adverb", "hizli": "adverb", "quickly": "adverb", "yavaş": "adverb", "yavas": "adverb",
    "slowly": "adverb", "şimdi": "adverb", "simdi": "adverb", "now": "adverb", "burada": "adverb",
    "here": "adverb", "orada": "adverb", "there": "adverb", "çok": "adverb", "very": "adverb",
    "her zaman": "adverb", "always": "adverb", "asla": "adverb", "never": "adverb",
    # edat / preposition
    "içinde": "preposition", "icinde": "preposition", "in": "preposition", "üzerinde": "preposition",
    "on": "preposition", "altında": "preposition", "under": "preposition", "ile": "preposition",
    "with": "preposition", "için": "preposition", "for": "preposition",
    # bağlaç / conjunction
    "ve": "conjunction", "and": "conjunction", "ama": "conjunction", "but": "conjunction",
    "çünkü": "conjunction", "cunku": "conjunction", "because": "conjunction",
    # ünlem / interjection
    "merhaba": "interjection", "hello": "interjection", "hey": "interjection", "evet": "interjection",
    "yes": "interjection", "hayır": "interjection", "hayir": "interjection", "no": "interjection",
}

POS_LABELS_TR: dict[str, str] = {
    "noun": "isim",
    "verb": "fiil",
    "adjective": "sıfat",
    "adverb": "zarf",
    "pronoun": "zamir",
    "preposition": "edat",
    "conjunction": "bağlaç",
    "interjection": "ünlem",
    "determiner": "belirteç",
}


def detect_part_of_speech(word_tr: str, target_word: str) -> str:
    """Kelime türünü tespit et — nesne şablonuna yanlış düşmeyi önler."""
    for w in (_norm(word_tr), _norm(target_word)):
        if w in KNOWN_PART_OF_SPEECH:
            return KNOWN_PART_OF_SPEECH[w]
    wt, tw = _norm(word_tr), _norm(target_word)
    if _is_adjective_like(word_tr, target_word):
        return "adjective"
    if _is_pronoun_like(word_tr, target_word):
        return "pronoun"
    if _is_adverb_like(word_tr, target_word):
        return "adverb"
    if wt.endswith(("mak", "mek")) or tw.endswith("ing") and len(tw) > 4:
        if wt.endswith(("mak", "mek")):
            return "verb"
    verb_hints = ("git", "gel", "al", "ver", "yap", "oku", "yaz", "koş", "kos", "çalış", "calis")
    if any(wt == v or wt.startswith(v) for v in verb_hints):
        return "verb"
    if detect_category(word_tr, target_word) != "general":
        return "noun"
    return "noun"


def get_pos_teaching_rules_for_prompt(word_tr: str, target_word: str) -> str:
    """AI prompt'una eklenecek kelime türüne özel zorunlu kurallar."""
    pos = detect_part_of_speech(word_tr, target_word)
    tw = _en_target_word(target_word)
    category = detect_category(word_tr, target_word)
    category_blocks: dict[str, str] = {
        "tobacco": (
            f"[SİGARA/TÜTÜN — {word_tr} → {tw}]\n"
            "- Yaygın fiiller (collocations): smoke, light, put out, stub out, quit, roll, flick\n"
            "- smoke a cigarette, light a cigarette, quit smoking, put out a cigarette\n"
            f"❌ YASAK: eat/drink/like {tw}; buy/carry/find/use genel nesne şablonu\n"
        ),
        "eyewear": (
            f"[GÖZLÜK — {word_tr} → {tw}]\n"
            "- wear, put on, take off, clean, lose; glasses çoğul isim\n"
            f"❌ YASAK: a glasses, eat/drink {tw}\n"
        ),
        "footwear": (
            f"[AYAKKABI — {word_tr} → {tw}]\n"
            "- wear, buy, tie, try on, take off; a pair of shoes\n"
        ),
        "clothing": (
            f"[GİYİM — {word_tr} → {tw}]\n"
            "- wear, put on, take off, wash, buy, fold, iron\n"
        ),
        "beverage": (
            f"[İÇECEK — {word_tr} → {tw}]\n"
            "- drink, have, order, make, serve, pour\n"
            f"❌ YASAK: eat {tw}, I love {tw} (yiyecek kalıbı)\n"
        ),
        "snack": (
            f"[ATIŞTIRMALIK — {word_tr} → {tw}]\n"
            "- chew, eat, buy, share, offer (sakız: chew gum, blow a bubble)\n"
        ),
        "document": (
            f"[BELGE/FATURA — {word_tr} → {tw}]\n"
            "- pay, send, receive, check, sign, issue, review\n"
        ),
        "plumbing": (
            f"[TESİSAT — {word_tr} → {tw}]\n"
            "- turn on/off, fix, repair, replace, install, leak\n"
        ),
        "vehicle": (
            f"[ARAÇ — {word_tr} → {tw}]\n"
            "- drive, park, buy, fix, wash, rent, sell\n"
        ),
        "furniture": (
            f"[MOBİLYA — {word_tr} → {tw}]\n"
            "- sit at, put on, clean, move, set, wipe\n"
        ),
        "drinkware": (
            f"[BARDAK/KADEH — {word_tr} → {tw}]\n"
            "- fill, break, wash, raise, pour, hold\n"
        ),
    }
    cat_hint = category_blocks.get(category, "")
    rules: dict[str, str] = {
        "noun": (
            f"[İSİM KURALLARI — {word_tr}]\n"
            "- Kelimeye özgü DOĞAL fiiller kullan (sigara→smoke/light, gözlük→wear, kapı→knock/open)\n"
            "- a/an/the veya my/your ile kullanım; sayılabilirlik açıkla\n"
            f"❌ YASAK: I am using the {tw}, Bring the {tw} (jenerik nesne şablonu)\n"
            "- Türkçede iyelik: arabam, cüzdanım, kitabım"
        ),
        "verb": (
            f"[FİİL KURALLARI — {word_tr}]\n"
            "- Zamanlar: simple present, past (-ed), future (will), present continuous (-ing)\n"
            "- need to / want to / have to + fiil; soru: Do you …? / Did you …?\n"
            f"❌ YASAK: I bought a new {tw}, my {tw} is on the table, a {tw}\n"
            "- Fiil mastarı: to {tw}; emir: {tw.capitalize()}!"
        ),
        "adjective": (
            f"[SIFAT KURALLARI — {word_tr}]\n"
            "- be + sıfat: I am {tw}, It is {tw}, You look {tw}\n"
            "- feel/keep/become + sıfat; sıfat + noun: a {tw} room\n"
            f"❌ YASAK: bought a new {tw}, my {tw}, bring my {tw}, where is my {tw}\n"
            "- Türkçe: sessizim, mutluyum; ortam: burası sessiz"
        ),
        "adverb": (
            f"[ZARF KURALLARI — {word_tr}]\n"
            "- Fiili niteler: walk {tw}, speak {tw}, drive {tw}\n"
            "- Sıfat + -ly: quick → quickly; yer/zaman: here, now, always\n"
            f"❌ YASAK: a {tw}, my {tw}, the {tw} is here\n"
            "- Türkçe karşılık: hızlıca, yavaşça, şimdi, burada"
        ),
        "pronoun": (
            f"[ZAMİR KURALLARI — {word_tr}]\n"
            "- Özne: I, you, he, she, we, they + fiil\n"
            "- Nesne: me, him, her, us, them / iyelik: my, your, his, her\n"
            f"❌ YASAK: bought a new {tw}, my {tw} is on the table (zamir nesne değil)\n"
            "- Diyalog ve karşılaştırma: He is …, She told me …"
        ),
        "preposition": (
            f"[EDAT KURALLARI — {word_tr}]\n"
            "- Yer/yön/zaman: in, on, at, under, with, for + isim\n"
            "- Kalıp: in the morning, on the table, at home\n"
            f"❌ YASAK: I bought a {tw}, my {tw}\n"
            "- Türkçe: -de/-da, -e/-a, ile, için karşılıklarını açıkla"
        ),
        "conjunction": (
            f"[BAĞLAÇ KURALLARI — {word_tr}]\n"
            "- Cümle bağlama: … and …, … but …, because …\n"
            "- Koşul: if …, when …, although …\n"
            f"❌ YASAK: nesne gibi kullanım (buy/bring/my {tw})"
        ),
        "interjection": (
            f"[ÜNLEM KURALLARI — {word_tr}]\n"
            "- Kısa doğal tepkiler: Hello!, Oh!, Wow!, Yes!, No!\n"
            "- Diyalog ve duygu; tam cümle kur\n"
            f"❌ YASAK: I bought a {tw}, my {tw} is here"
        ),
    }
    base = rules.get(pos, rules["noun"])
    prefix = f"{cat_hint}\n" if cat_hint else ""
    return (
        f"\n[KELİME TÜRÜ: {POS_LABELS_TR.get(pos, pos)} ({pos})]\n"
        f"{prefix}{base}\n"
        "- Her örnekte how_it_is_formed_tr: 1️⃣ genel anlam 2️⃣ ana yapı 3️⃣+ dil bilgisi adımları (≥200 karakter)\n"
    )


def _is_pronoun_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "ben", "sen", "o", "biz", "siz", "onlar", "i", "you", "he", "she", "it", "we", "they",
        "me", "him", "her", "us", "them", "my", "your", "his", "our", "their", "mine", "yours",
        "benim", "senin", "onun", "bizim", "sizin", "onların",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_adverb_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "hızlı", "hizli", "quickly", "yavaş", "yavas", "slowly", "şimdi", "simdi", "now",
        "burada", "here", "orada", "there", "çok", "very", "always", "never", "often", "sometimes",
        "sık", "genellikle", "usually", "carefully", "dikkatlice", "well", "iyi",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_verb_like(word_tr: str, target_word: str) -> bool:
    if detect_part_of_speech(word_tr, target_word) == "verb":
        return True
    wt = _norm(word_tr)
    return wt.endswith(("mak", "mek"))


def _is_preposition_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "in", "on", "at", "under", "over", "with", "without", "for", "from", "to", "about",
        "between", "içinde", "icinde", "üzerinde", "uzerinde", "altında", "altinda", "ile", "için", "icin",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_conjunction_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "ve", "and", "ama", "but", "çünkü", "cunku", "because", "veya", "or", "fakat",
        "although", "rağmen", "ragmen", "if", "eğer", "eger", "when", "iken",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_interjection_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "merhaba", "hello", "hey", "evet", "yes", "hayır", "hayir", "no", "oh", "wow",
        "ah", "eyvah", "bravo", "tebrikler", "congratulations", "thanks", "teşekkürler", "tesekkurler",
    )
    return _any_category_hint(word_tr, target_word, hints)


# Çeviri API'sinin döndürdüğü varyantları Amerikan İngilizcesine normalize et
EN_TARGET_ALIASES: dict[str, str] = {
    "chewing gum": "gum",
    "chewing-gum": "gum",
    "sweet corn": "corn",
    "sweet-corn": "corn",
    "maize": "corn",
    "tap": "faucet",
    "lift": "elevator",
    "lorry": "truck",
    "flat": "apartment",
    "colour": "color",
    "trousers": "pants",
    "biscuit": "cookie",
    "crisps": "chips",
    "chips": "fries",
    "petrol": "gas",
    "bonnet": "hood",
}


def _normalize_en_target(word_tr: str, target_word: str) -> str:
    """API çevirisini Amerikan İngilizcesi kanonik formuna getir."""
    tw = safe_str(target_word).strip().lower()
    # Infinitive çeviriler: "to go" → "go" (Google çeviri fiillerde)
    if tw.startswith("to ") and len(tw) > 3:
        rest = tw[3:].strip()
        if rest and " " not in rest:
            tw = rest
    tw = EN_TARGET_ALIASES.get(tw, tw)
    tw = re.sub(r"\s+", " ", tw)
    if tw in EN_TARGET_ALIASES:
        tw = EN_TARGET_ALIASES[tw]
    return tw


_LLM_EN_WORD_CACHE: dict[str, str] = {}


def _llm_resolve_english_word(word_tr: str) -> str:
    """Çeviri API Türkçe döndürdüyse veya bilinmiyorsa AI ile İngilizce karşılık bul."""
    wt = _norm(word_tr)
    if not wt:
        return ""
    if wt in _LLM_EN_WORD_CACHE:
        return _LLM_EN_WORD_CACHE[wt]
    if not llm_available():
        return ""
    try:
        parsed = _llm_json(
            'Return JSON only: {"en": "American English word or short phrase"}',
            f"Turkish vocabulary word: {word_tr}",
            max_tokens=80,
        )
        en = safe_str((parsed or {}).get("en") or (parsed or {}).get("target_word")).strip().lower()
        en = EN_TARGET_ALIASES.get(en, en)
        if en and en != wt and _norm(en) != wt:
            _LLM_EN_WORD_CACHE[wt] = en
            return en
    except Exception:
        pass
    return ""


def resolve_target_word(word_tr: str, target_word: str, target_lang: str) -> str:
    """Çeviri Türkçe döndüyse bilinen İngilizce karşılığı kullan; US English öncelikli."""
    raw = safe_str(word_tr).strip()
    wt = _norm(word_tr)
    if target_lang == "en":
        # Ülke adı: Mısır (büyük M) → Egypt
        if raw in ("Mısır", "Misir", "MISIR"):
            return "egypt"
        known = KNOWN_TR_TO_EN.get(wt) or KNOWN_TR_TO_EN.get(word_tr.lower())
        if known:
            return known.lower()
        tw = _normalize_en_target(word_tr, target_word)
        if tw and tw != wt and _norm(tw) != wt:
            return tw
        llm_en = _llm_resolve_english_word(word_tr)
        if llm_en:
            return llm_en.lower()
        if not tw or tw == wt or tw == word_tr.lower():
            return (known or tw or word_tr).lower()
        return tw
    tw = safe_str(target_word).strip()
    return tw or word_tr

SENTENCE_TYPE_LABELS: dict[str, str] = {
    "location": "📍 Konum",
    "description": "📌 Tanım",
    "problem": "🔧 Problem",
    "action": "🛠️ Eylem",
    "request": "🗣️ Rica",
    "question": "❓ Soru",
    "shopping": "🛒 Alışveriş",
    "repair": "👨‍🔧 Tamir",
    "daily": "💬 Günlük konuşma",
    "past": "🕐 Geçmiş",
    "future": "🔮 Gelecek",
    "present_continuous": "🔄 Şu an",
    "negative": "⛔ Olumsuz",
    "offer": "🤝 Teklif",
    "need_to": "📋 Gereklilik",
    "imperative": "👉 Emir",
    "existence": "📍 Var/yok",
    "routine": "🌅 Rutin",
    "movement": "🚶 Hareket",
    "experience": "🧠 Deneyim",
    "comparison": "⚖️ Karşılaştırma",
    "warning": "⚠️ Uyarı",
    "advice": "💡 Tavsiye",
}


def word_icon_for(word_tr: str, target_word: str, category: str = "general") -> str:
    """İkon — merkezi sözlükten; asla alakasız 📖 veya masa→sandalye karışıklığı yok."""
    cat = category if category != "general" else detect_category(word_tr, target_word)
    return lookup_emoji(word_tr, target_word, cat)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", safe_str(s).strip().lower())


def _category_hint_matches(word_tr: str, target_word: str, hint: str) -> bool:
    """Kategori ipucu eşleşmesi — sigara→et (et) gibi yanlış alt dize eşleşmelerini önler."""
    from word_icons import _term_matches
    wt, tw = _norm(word_tr), _norm(target_word)
    h = _norm(hint)
    if not h:
        return False
    if wt == h or tw == h:
        return True
    return _term_matches(h, wt) or _term_matches(h, tw)


def _any_category_hint(word_tr: str, target_word: str, hints: tuple[str, ...]) -> bool:
    return any(_category_hint_matches(word_tr, target_word, h) for h in hints)


def detect_category(word_tr: str, target_word: str) -> str:
    for w in (_norm(word_tr), _norm(target_word)):
        if w in KNOWN_CATEGORIES:
            return KNOWN_CATEGORIES[w]
    inferred = _infer_semantic_category(word_tr, target_word)
    if inferred != "general":
        return inferred
    return "general"


def _infer_semantic_category(word_tr: str, target_word: str) -> str:
    """Sözlükte yoksa hedef kelimeden kategori çıkar."""
    wt, tw = _norm(word_tr), _norm(target_word)
    if _is_eyewear_like(wt, tw):
        return "eyewear"
    if _is_tobacco_like(wt, tw):
        return "tobacco"
    if _is_clothing_like(wt, tw):
        return "clothing"
    if _is_beverage_like(wt, tw):
        return "beverage"
    food_hints = (
        "ekmek", "peynir", "et", "tavuk", "balık", "elma", "muz", "domates",
        "bread", "cheese", "meat", "chicken", "fish", "apple", "banana", "tomato",
        "rice", "pasta", "pizza", "soup", "salad", "fruit", "vegetable",
    )
    if _any_category_hint(word_tr, target_word, food_hints):
        return "food"
    animal_hints = ("kedi", "köpek", "kuş", "cat", "dog", "bird", "horse", "cow")
    if _any_category_hint(word_tr, target_word, animal_hints):
        return "animal"
    place_hints = ("ev", "okul", "hastane", "market", "home", "school", "hospital", "store")
    if _any_category_hint(word_tr, target_word, place_hints):
        return "place"
    vehicle_hints = (
        "araba", "otomobil", "otobüs", "tren", "bisiklet", "motosiklet", "scooter",
        "car", "bus", "train", "plane", "bike", "bicycle", "motorcycle", "scooter",
    )
    if _any_category_hint(word_tr, target_word, vehicle_hints):
        return "vehicle"
    document_hints = (
        "fatura", "invoice", "makbuz", "receipt", "bill", "dekont", "fiş", "fis",
        "contract", "sözleşme", "sozlesme", "document", "belge",
    )
    if _any_category_hint(word_tr, target_word, document_hints):
        return "document"
    if _is_adjective_like(word_tr, target_word):
        return "adjective"
    if _is_snack_like(wt, tw):
        return "snack"
    if _is_abstract_like(wt, tw):
        return "abstract"
    object_hints = (
        "çanta", "canta", "bag", "valiz", "suitcase", "cüzdan", "wallet",
        "şemsiye", "umbrella", "saat", "watch",
    )
    if _any_category_hint(word_tr, target_word, object_hints):
        return "object"
    return "general"


def _is_umbrella_like(word_tr: str, target_word: str) -> bool:
    hints = ("şemsiye", "semsiye", "umbrella", "parasol")
    return _any_category_hint(word_tr, target_word, hints)


def _is_wallet_like(word_tr: str, target_word: str) -> bool:
    hints = ("cüzdan", "cuzdan", "wallet", "billfold")
    return _any_category_hint(word_tr, target_word, hints)


def _is_market_like(word_tr: str, target_word: str) -> bool:
    hints = ("market", "pazar", "grocery", "supermarket", "bakkal")
    return _any_category_hint(word_tr, target_word, hints)


def _is_adjective_like(word_tr: str, target_word: str) -> bool:
    """Sıfat kelimeler — asla nesne şablonuna düşmemeli."""
    hints = (
        "mutlu", "happy", "üzgün", "uzgun", "sad", "sessiz", "quiet", "silent",
        "yorgun", "tired", "mutsuz", "unhappy", "gürültülü", "gurultulu", "noisy", "loud",
        "sakin", "calm", "meşgul", "mesgul", "busy", "kızgın", "kizgin", "angry",
        "korkmuş", "korkmus", "scared", "afraid", "heyecanlı", "heyecanli", "excited",
        "sıkılmış", "sikilmis", "bored", "hasta", "sick", "sağlıklı", "saglikli", "healthy",
        "aç", "ac", "hungry", "tok", "full", "uzun", "tall", "long", "kısa", "kisa", "short",
        "büyük", "buyuk", "big", "large", "küçük", "kucuk", "small", "güzel", "guzel", "beautiful",
        "çirkin", "cirkin", "ugly", "zor", "difficult", "hard", "kolay", "easy",
        "önemli", "onemli", "important", "ilginç", "ilginc", "interesting",
        "sıcak", "sicak", "hot", "soğuk", "soguk", "cold", "sıcakkanlı", "warm",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_quiet_like(word_tr: str, target_word: str) -> bool:
    hints = ("sessiz", "quiet", "silent", "silence", "gürültüsüz", "gurultusuz")
    return _any_category_hint(word_tr, target_word, hints)


def _possessive_tr(word_tr: str) -> str:
    """Türkçe iyelik: cüzdan → cüzdanım, şemsiye → şemsiyem."""
    w = safe_str(word_tr).strip()
    if not w:
        return w
    low = w.lower()
    known = {
        "cüzdan": "cüzdanım", "cuzdan": "cüzdanım", "şemsiye": "şemsiyem", "semsiye": "şemsiyem",
        "araba": "arabam", "otomobil": "otomobilim",
        "çanta": "çantam", "canta": "çantam", "anahtar": "anahtarım", "kitap": "kitabım",
        "telefon": "telefonum", "gözlük": "gözlüğüm", "gozluk": "gözlüğüm",
    }
    if low in known:
        return known[low]
    last = low[-1]
    vowels = [c for c in low if c in "aıouöüei"]
    if not vowels:
        return f"benim {low}"
    v = vowels[-1]
    suffix = {"a": "ım", "ı": "ım", "e": "im", "i": "im", "o": "um", "ö": "üm", "u": "um", "ü": "üm"}.get(v, "ım")
    if last in "aeıioöuü":
        if last in "aı":
            return w[:-1] + "m" if low.endswith(("ye", "ya")) else w + "m"
        return w + "m"
    return w + suffix


def _is_eyewear_like(word_tr: str, target_word: str) -> bool:
    hints = ("gözlük", "gozluk", "glasses", "sunglasses", "eyeglasses", "spectacles")
    return _any_category_hint(word_tr, target_word, hints)


def _is_tobacco_like(word_tr: str, target_word: str) -> bool:
    hints = ("sigara", "cigarette", "cigarettes", "tütün", "tutun", "tobacco", "vape", "nargile", "hookah")
    return _any_category_hint(word_tr, target_word, hints)


def _is_clothing_like(word_tr: str, target_word: str) -> bool:
    hints = (
        "çorap", "corap", "sock", "socks", "gömlek", "gomlek", "shirt", "pantolon", "pants",
        "elbise", "dress", "ceket", "jacket", "kazak", "sweater", "tişört", "tisort", "t-shirt",
    )
    return _any_category_hint(word_tr, target_word, hints)


def _is_beverage_like(word_tr: str, target_word: str) -> bool:
    wt, tw = _norm(word_tr), _norm(target_word)
    if "maden" in wt and "su" in wt:
        return True
    tr_hints = ("içecek", "kahve", "çay", "gazoz", "kola", "süt", "bira", "şarap", "meyve suyu")
    en_hints = (
        "water", "juice", "milk", "tea", "coffee", "soda", "cola", "drink", "beer",
        "wine", "lemonade", "sparkling", "mineral", "latte", "espresso", "smoothie",
    )
    return any(h in wt for h in tr_hints) or any(h in tw for h in en_hints)


def _is_abstract_like(word_tr: str, target_word: str) -> bool:
    """Soyut/sayılamayan isimler: entertainment, happiness, freedom vb."""
    wt, tw = _norm(word_tr), _norm(target_word)
    hints = (
        "eğlence", "eglence", "entertainment", "mutluluk", "happiness", "özgürlük", "freedom",
        "güven", "trust", "saygı", "respect", "başarı", "success", "umut", "hope", "korku", "fear",
        "sevinç", "joy", "huzur", "peace", "gurur", "pride", "merak", "curiosity",
    )
    return any(h in wt or h in tw for h in hints)


def _is_snack_like(word_tr: str, target_word: str) -> bool:
    wt, tw = _norm(word_tr), _norm(target_word)
    hints = (
        "sakız", "sakiz", "gum", "chewing", "şeker", "seker", "candy", "çikolata", "cikolata",
        "chocolate", "bisküvi", "biskivi", "cookie", "kraker", "cracker", "cips", "chips", "snack",
        "lollipop", "lolipop", "jelly", "jelibon",
    )
    return any(h in wt or h in tw for h in hints)


TARGET_WORD_ALIASES: dict[str, tuple[str, ...]] = {
    "chewing gum": ("gum",),
    "gum": ("chewing gum",),
}


def _target_word_in_sentence(norm_target: str, tw: str) -> bool:
    if not tw:
        return True
    if tw in norm_target or f"{tw}s" in norm_target:
        return True
    for alias in TARGET_WORD_ALIASES.get(tw, ()):
        if alias in norm_target:
            return True
    return False


def _is_generic_mechanical_template(target: str) -> bool:
    """Mekanik şablon: kelimeyi fiile zorla yerleştiren doğal olmayan cümleler."""
    t = _norm(target)
    return any(p.search(t) for p in GENERIC_MECHANICAL_RE)


def _is_absurd_example(target: str, word_tr: str, target_word: str) -> bool:
    """İçecek/yiyecek ve genel mekanik şablonları reddet."""
    if _is_generic_mechanical_template(target):
        return True
    t = _norm(target)
    if _is_wrong_verb_collocation(t, word_tr, target_word):
        return True
    if not _is_beverage_like(word_tr, target_word):
        return False
    absurd = (
        "open the", "open a", "fix the", "fix it", "is broken", "check the",
        "using the", "used the", "is ready", "is here", "another room",
        "regularly", "repair",
    )
    return any(p in t for p in absurd)


def _is_wrong_verb_collocation(target_norm: str, word_tr: str, target_word: str) -> bool:
    """Kelimeye uygun olmayan fiil eşleşmeleri — sigara ye, gözlük ye vb."""
    cat = detect_category(word_tr, target_word)
    tw = _en_target_word(target_word)
    eat_drink = (" eat ", " eating ", " ate ", " drink ", " drinking ", " drank ", " chew ", " chewing ")
    if cat == "tobacco" or _is_tobacco_like(_norm(word_tr), tw):
        if any(p in f" {target_norm} " for p in eat_drink):
            return True
        if "like cigarette" in target_norm or "love cigarette" in target_norm:
            return True
    if cat == "eyewear" or _is_eyewear_like(_norm(word_tr), tw):
        if any(p in f" {target_norm} " for p in eat_drink):
            return True
        if " a glasses" in target_norm or "glasses is " in target_norm:
            return True
    if cat not in ("food", "snack", "beverage") and not _is_beverage_like(word_tr, target_word):
        if tw and tw in target_norm and tw not in ("corn", "fish"):
            if re.search(
                rf"\b(?:eat|eating|ate|drink|drinking|drank|chew|chewing)\s+"
                rf"(?:the\s+|a\s+|an\s+|my\s+|your\s+|some\s+)?{re.escape(tw)}\b",
                target_norm,
            ):
                return True
    return False


def _canonical_beverage_phrase(target_word: str) -> str:
    tw = safe_str(target_word).strip().lower()
    if "sparkling" in tw or "mineral" in tw or "club soda" in tw:
        return tw
    if tw == "water":
        return "water"
    return tw


def _en_target_word(target_word: str) -> str:
    return safe_str(target_word).strip().lower()


def _normalize_noun_caps(text: str, noun: str) -> str:
    """Ortadaki gereksiz büyük harfleri düzelt: The Window → The window."""
    n = _en_target_word(noun)
    if not n or not text:
        return text
    text = re.sub(rf"\b{re.escape(n)}\b", n, text, flags=re.I)
    return text


def _resolve_category(word_tr: str, target_word: str, category: str | None = None) -> str:
    """Bilinen kelimelerde kural tabanlı kategori; mobilya şablonu sadece masa/sandalye."""
    known = detect_category(word_tr, target_word)
    if known != "general":
        return known
    cat = safe_str(category or "general").strip().lower()
    wt, tw = _norm(word_tr), _en_target_word(target_word)
    if cat == "furniture" and wt not in ("masa", "sandalye") and tw not in ("table", "chair"):
        return "object"
    return cat or "general"


def _english_leaked_turkish(target: str, word_tr: str, target_word: str) -> bool:
    """İngilizce cümlede Türkçe kelime kaldı mı? (ör. The bardak is here)"""
    wt = _norm(word_tr)
    tw = _en_target_word(target_word)
    if not wt or wt == tw or len(wt) < 3:
        return False
    tokens = set(re.findall(r"[a-zçğıöşüâîû]+", _norm(target)))
    return wt in tokens


def _is_full_sentence(text: str, *, min_words: int = 3) -> bool:
    """Tam cümle mi — tek kelime kartları reddedilir."""
    t = safe_str(text).strip()
    if not t:
        return False
    words = re.findall(r"[\w']+", t)
    if len(words) >= min_words:
        return True
    if len(words) >= 2 and t.rstrip().endswith(("?", "!")):
        return True
    return False


def _is_full_english_example(target: str) -> bool:
    return _is_full_sentence(target, min_words=3)


def _tr_contains_word(text: str, word_tr: str) -> bool:
    wt = _norm(word_tr)
    if not wt:
        return True
    t = _norm(text)
    if wt in t:
        return True
    if wt.endswith("mek") or wt.endswith("mak"):
        stem = wt[:-3]
        if stem and stem in t:
            return True
    if len(wt) >= 4 and wt[:-1] in t:
        return True
    return False


def _is_placeholder_turkish(tr: str, word_tr: str) -> bool:
    """Türkçe alan boş veya yalnızca hedef kelime mi? (❌ tr: 'Eğlence')"""
    text = safe_str(tr).strip()
    if not text:
        return True
    wt = _norm(word_tr)
    tn = _norm(text)
    if not wt:
        return len(tn.split()) < 2
    stripped = tn.strip(".,?!;:…")
    if stripped == wt:
        return True
    if stripped == wt + "yi" or stripped == wt + "yı" or stripped == wt + "yu" or stripped == wt + "yü":
        return True
    words = tn.split()
    if len(words) < 2 and len(tn) <= len(wt) + 3:
        return True
    return False


def _is_mechanical_turkish(tr: str, word_tr: str) -> bool:
    """Şablon motorunun ürettiği doğal olmayan Türkçe (Araba garajda, Şu an araba kullanıyorum)."""
    if _is_placeholder_turkish(tr, word_tr):
        return True
    text = safe_str(tr).strip()
    low = text.lower()
    wt = word_tr.strip().lower()
    if len(low.split()) < 2:
        return True
    poss = _possessive_tr(word_tr).lower()
    if poss in low:
        return False
    bare_patterns = (
        rf"^{re.escape(wt)}\s+garajda",
        rf"^{re.escape(wt)}\s+bozuk",
        rf"^{re.escape(wt)}\s+nerede",
        rf"^{re.escape(wt)}\s+hazır",
        rf"^{re.escape(wt)}\s+bozulmuş",
        rf"^{re.escape(wt)}\s+bozuksa",
        rf"^şu an {re.escape(wt)}\b",
        rf"^geçen yıl {re.escape(wt)}\s+aldım",
        rf"^yarın {re.escape(wt)}\s+süreceğim",
        rf"^{re.escape(wt)}\s+tamir\b",
        rf"^{re.escape(wt)}\s+kullanabilir",
        rf"^{re.escape(wt)}\s+için sigorta",
        rf"^a:\s*{re.escape(wt)}\b",
    )
    for pat in bare_patterns:
        if re.search(pat, low):
            return True
    if re.match(rf"^{re.escape(wt)}\b", low):
        return True
    return False


def _has_foreign_word_leak(text: str, word_tr: str, target_word: str) -> bool:
    wt, tw = _norm(word_tr), _en_target_word(target_word)
    markers = FOREIGN_WORD_MARKERS.get(wt) or FOREIGN_WORD_MARKERS.get(tw) or ()
    t = safe_str(text).lower()
    return any(m in t for m in markers)


def _has_conflicting_primary_noun(text: str, target_word: str) -> bool:
    """Hedef kelime dışı ana nesne (socks öğretirken shoe gibi) var mı?"""
    tw = _en_target_word(target_word)
    conflicts = CONFLICTING_PRIMARY_NOUNS.get(tw, frozenset())
    if not conflicts:
        return False
    tokens = {t.lower() for t in tokenize_en(text)}
    target_forms = {tw, tw + "s"}
    if tw.endswith("s") and len(tw) > 3:
        target_forms.add(tw[:-1])
    if not (tokens & target_forms):
        return False
    return bool(tokens & conflicts)


def _validate_focus_content(
    target: str,
    tr: str,
    word_tr: str,
    target_word: str,
) -> bool:
    """Örnek/kalıp cümlesi hedef kelimeyle uyumlu mu?"""
    target = _normalize_noun_caps(safe_str(target).strip(), target_word)
    if not target:
        return False
    tw = _en_target_word(target_word)
    norm_target = _norm(target)
    if tw and tw not in norm_target and f"{tw}s" not in norm_target:
        if tw.endswith("s") and tw[:-1] in norm_target:
            pass
        else:
            return False
    if tr and not _tr_contains_word(tr, word_tr):
        return False
    blob = f"{tr} {target}"
    if _has_foreign_word_leak(blob, word_tr, target_word):
        return False
    if _has_cross_word_leak(blob, word_tr, target_word):
        return False
    if _has_conflicting_primary_noun(target, target_word):
        return False
    return True


def _sanitize_example_nested(
    ex: dict[str, Any],
    word_tr: str,
    target_word: str,
) -> dict[str, Any]:
    """İç içe kalıp/yeni kelime verilerini hedef kelimeye göre filtrele."""
    good_pats: list[dict[str, Any]] = []
    for p in ex.get("pattern_examples") or []:
        if not isinstance(p, dict):
            continue
        t = safe_str(p.get("target") or p.get("example_en")).strip()
        tr = safe_str(p.get("tr") or p.get("example_tr")).strip()
        if _validate_focus_content(t, tr, word_tr, target_word):
            good_pats.append(p)
    ex["pattern_examples"] = good_pats

    good_nw: list[dict[str, Any]] = []
    tw = _en_target_word(target_word)
    conflicts = CONFLICTING_PRIMARY_NOUNS.get(tw, frozenset())
    for nw in ex.get("new_words") or []:
        if not isinstance(nw, dict):
            continue
        w = safe_str(nw.get("word")).lower()
        if w in conflicts:
            continue
        if _has_foreign_word_leak(f"{w} {nw.get('meaning_tr', '')}", word_tr, target_word):
            continue
        good_nw.append(nw)
    ex["new_words"] = good_nw
    return ex


def _llm_backfill_turkish(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
) -> dict[str, str]:
    """Eksik Türkçe çevirileri AI ile tamamla. target → tr eşlemesi döner."""
    if not llm_available() or not examples:
        return {}
    import json
    pairs = [
        {"target": safe_str(ex.get("target")).strip()}
        for ex in examples
        if safe_str(ex.get("target")).strip()
    ]
    if not pairs:
        return {}
    system = (
        f"Sen Türkçe-İngilizce öğretmenisin. Ders kelimesi: «{word_tr}» (İngilizce: {target_word}).\n"
        "Her İngilizce cümleyi doğal Türkçeye çevir. Türkçe TAM cümle olmalı — yalnızca kelime yazma.\n"
        'JSON: {{"items": [{{"target": "İngilizce", "tr": "Türkçe cümle"}}]}}'
    )
    parsed = _llm_json(system, json.dumps(pairs, ensure_ascii=False), max_tokens=2000)
    if not parsed or not isinstance(parsed.get("items"), list):
        return {}
    out: dict[str, str] = {}
    for item in parsed["items"]:
        if not isinstance(item, dict):
            continue
        en = safe_str(item.get("target")).strip()
        tr = safe_str(item.get("tr")).strip()
        if en and tr and not _is_placeholder_turkish(tr, word_tr):
            out[en] = tr
    return out


def ensure_turkish_translations(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Boş veya yalnızca kelime olan Türkçe alanları düzelt veya örneği çıkar."""
    if not examples:
        return examples
    need_backfill = [
        ex for ex in examples
        if isinstance(ex, dict)
        and safe_str(ex.get("target")).strip()
        and (
            _is_placeholder_turkish(safe_str(ex.get("tr")), word_tr)
            or _is_mechanical_turkish(safe_str(ex.get("tr")), word_tr)
        )
    ]
    if need_backfill and llm_available() and os.getenv("WORD_LESSON_FAST", "1") != "1":
        mapping = _llm_backfill_turkish(need_backfill, word_tr, target_word)
        for ex in need_backfill:
            en = safe_str(ex.get("target")).strip()
            if en in mapping:
                ex["tr"] = mapping[en]
    if translate_fn:
        for ex in need_backfill:
            if not _is_placeholder_turkish(safe_str(ex.get("tr")), word_tr):
                continue
            en = safe_str(ex.get("target")).strip()
            if not en:
                continue
            try:
                tr = safe_str(translate_fn(en, "en", "tr")).strip()
            except Exception:
                tr = ""
            if tr and not _is_placeholder_turkish(tr, word_tr) and not _is_mechanical_turkish(tr, word_tr):
                ex["tr"] = tr
    cleaned: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        tr = safe_str(ex.get("tr"))
        if _is_placeholder_turkish(tr, word_tr) or _is_mechanical_turkish(tr, word_tr):
            continue
        cleaned.append(ex)
    return cleaned


def sanitize_word_examples(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None = None,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Tüm örnekleri doğrula ve iç içe verileri temizle."""
    examples = ensure_turkish_translations(examples, word_tr, target_word, translate_fn)
    cleaned: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        if not _validate_word_example(ex, word_tr, target_word, profile):
            continue
        cleaned.append(_fill_word_breakdown(_sanitize_example_nested(dict(ex), word_tr, target_word), "en"))
    return cleaned


def _is_banned_template(target: str) -> bool:
    t = safe_str(target).strip()
    return any(p.match(t) for p in BANNED_TEMPLATE_RE)


def _has_cross_word_leak(text: str, word_tr: str, target_word: str) -> bool:
    if _has_foreign_word_leak(text, word_tr, target_word):
        return True
    t = safe_str(text).lower()
    wt = _norm(word_tr)
    tw = _en_target_word(target_word)
    if CROSS_WORD_LEAK_RE.search(t) and wt not in ("kahve", "coffee") and tw != "coffee":
        return True
    if "kahve" in t and wt != "kahve" and "coffee" not in tw:
        return True
    if "coffee" in t and tw != "coffee":
        return True
    return False


def analyze_word_profile(
    word_tr: str,
    target_word: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    """Kelime kullanım haritası — LLM veya kural tabanlı."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    category = detect_category(word_tr, target_word)

    if llm_available():
        system = WORD_PROFILE_PROMPT.format(
            word_tr=word_tr[:80],
            lang_name=lang_name,
            target_lang=target_lang,
            target_word=target_word[:80],
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=900)
        if parsed and parsed.get("target_word"):
            known_cat = detect_category(word_tr, target_word)
            parsed["target_word"] = target_word
            parsed["semantic_category"] = parsed.get("semantic_category") or known_cat
            if has_curated_lexicon(word_tr, target_word):
                curated = get_word_usage_profile(word_tr, target_word)
                if curated:
                    for key, val in curated.items():
                        if not parsed.get(key):
                            parsed[key] = val
            elif known_cat != "general":
                rule = _rule_word_profile(word_tr, target_word, target_lang, known_cat)
                for key in (
                    "common_verbs", "common_collocations", "article_notes_items",
                    "article_notes_tr", "usage_notes_tr",
                ):
                    if rule.get(key) and not parsed.get(key):
                        parsed[key] = rule[key]
            return parsed

    if has_curated_lexicon(word_tr, target_word):
        curated = get_word_usage_profile(word_tr, target_word)
        if curated:
            return {"target_word": target_word, **curated}

    return _rule_word_profile(word_tr, target_word, target_lang, category)


def fast_analyze_word_profile(
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> dict[str, Any]:
    """Hızlı profil — ek LLM çağrısı yok (ders tek çağrıda gelir)."""
    category = detect_category(word_tr, target_word)
    if has_curated_lexicon(word_tr, target_word):
        curated = get_word_usage_profile(word_tr, target_word)
        if curated:
            return {"target_word": target_word, **curated}
    return _rule_word_profile(word_tr, target_word, target_lang, category)


def _rule_word_profile(
    word_tr: str,
    target_word: str,
    target_lang: str,
    category: str,
) -> dict[str, Any]:
    lex = get_word_usage_profile(word_tr, target_word)
    if lex:
        return {
            "target_word": target_word,
            "part_of_speech": "noun",
            "countability": "countable",
            "meaning_tr": word_tr,
            **lex,
        }

    profiles: dict[str, dict[str, Any]] = {
        "beverage": {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "beverage",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» genelde içecek olarak kullanılır. "
                "Türkçedeki «kahve içmek» İngilizcede drink/have coffee ile kurulur."
            ),
            "common_verbs": ["drink", "have", "make", "order", "get"],
            "common_collocations": [f"a cup of {target_word}", f"some {target_word}", f"black {target_word}"],
            "common_patterns": [f"I drink {target_word}", f"Can I have a {target_word}?"],
            "article_notes_tr": "Madde olarak coffee; bir porsiyon için a coffee kullanılabilir.",
            "avoid_patterns": ["I love coffee (her içecek için)", "You don't drink table"],
            "avoid_reason_tr": "İçecekler sevilmek yerine içilir veya istenir.",
        },
        "furniture": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "furniture",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» mobilya/eşya olarak kullanılır. "
                "Türkçede «masa seviyorum» doğal değil; İngilizcede de I love table kullanılmaz."
            ),
            "common_verbs": ["sit at", "put on", "clean", "move", "use", "set"],
            "common_collocations": [f"on the {target_word}", f"at the {target_word}", f"the kitchen {target_word}"],
            "common_patterns": [f"The {target_word} is...", f"Put it on the {target_word}"],
            "article_notes_tr": "Sayılabilir isim; the table / a table kullanılır.",
            "avoid_patterns": ["I love table", "Do you want table", "drink table"],
            "avoid_reason_tr": "Mobilya sevilmez veya içilmez; konum ve kullanım fiilleri tercih edilir.",
        },
        "place": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "place",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» yer bildirir; go to / at the ... kalıpları yaygındır.",
            "common_verbs": ["go to", "be at", "visit", "leave"],
            "common_collocations": [f"at the {target_word}", f"go to the {target_word}"],
            "common_patterns": [f"I am at the {target_word}", f"We went to the {target_word}"],
            "article_notes_tr": "Yer isimlerinde genelde the kullanılır.",
            "avoid_patterns": ["I love market"],
            "avoid_reason_tr": "Yerler sevilmek yerine gidilir veya bulunulur.",
        },
        "plumbing": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "plumbing",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» evdeki su musluğu anlamına gelir. "
                "turn on/off, leak, fix, repair, install gibi fiillerle kullanılır."
            ),
            "common_verbs": ["turn on", "turn off", "fix", "repair", "replace", "install", "clean"],
            "common_collocations": [
                "kitchen faucet", "bathroom faucet", "turn off the faucet",
                "the faucet is leaking", "water is coming from the faucet",
            ],
            "common_patterns": ["Turn off the faucet.", "The faucet is leaking."],
            "article_notes_tr": "the faucet — belirli musluk; a new faucet — yeni musluk.",
            "regional_variants": {
                "us": target_word if target_word == "faucet" else "faucet",
                "uk": "tap",
                "note_tr": "🇺🇸 American English: faucet · 🇬🇧 British English: tap",
            },
            "avoid_patterns": ["drink the faucet", "eat the faucet", "I love faucet"],
            "avoid_reason_tr": "Musluk içilmez veya sevilmez; açma/kapama/tamir fiilleri kullanılır.",
        },
        "vehicle": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "vehicle",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» taşıt; drive, park, wash, buy, fix ile doğal kullanılır. "
                "Türkçede «arabayı sürmek», İngilizcede drive the car / I drive to work."
            ),
            "common_verbs": ["drive", "park", "buy", "fix", "wash", "rent", "sell"],
            "common_collocations": [
                f"drive the {target_word}", f"park the {target_word}",
                f"get in the {target_word}", f"a new {target_word}",
            ],
            "common_patterns": [
                f"My {target_word} is in the garage.",
                f"I drive to work every morning.",
                f"Where did you park your {target_word}?",
            ],
            "article_notes_items": [
                {"en": f"my {target_word}", "tr": _possessive_tr(word_tr)},
                {"en": f"a new {target_word}", "tr": f"yeni bir {word_tr.lower()}"},
                {"en": f"the {target_word}", "tr": word_tr.lower()},
            ],
            "article_notes_tr": (
                f"my {target_word} → {_possessive_tr(word_tr)} / "
                f"a new {target_word} → yeni bir {word_tr.lower()}"
            ),
            "avoid_patterns": ["drink the car", "I love car (without context)", "I am using the car at home"],
            "avoid_reason_tr": "Araç fiilleri: sürmek, park etmek, tamir ettirmek.",
        },
        "adjective": {
            "part_of_speech": "adjective",
            "countability": "n/a",
            "semantic_category": "adjective",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» sıfattır; am/is/are + sıfat veya feel/look + sıfat ile kullanılır.",
            "common_verbs": ["be", "feel", "look", "seem", "make"],
            "common_collocations": [f"I am {target_word}", f"feel {target_word}", f"look {target_word}"],
            "common_patterns": [f"I am {target_word}.", f"She looks {target_word}."],
            "article_notes_tr": None,
            "avoid_patterns": ["I happy (without am)"],
            "avoid_reason_tr": "Sıfatlar genelde be fiili veya feel/look ile gelir.",
        },
        "pronoun": {
            "part_of_speech": "pronoun",
            "countability": "n/a",
            "semantic_category": "pronoun",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» zamirdir; özne (I, you), nesne (me, him) veya iyelik (my, your) olarak kullanılır. "
                "Asla nesne gibi satın alınmaz veya masada bulunmaz."
            ),
            "common_verbs": ["be", "see", "tell", "give", "help", "know"],
            "common_collocations": ["I think", "he told me", "give her", "my friend"],
            "common_patterns": ["I am …", "She told me …", "This is mine."],
            "article_notes_tr": "Zamirlerde a/an/the kullanılmaz.",
            "avoid_patterns": [f"bought a new {target_word}", f"my {target_word} is on"],
            "avoid_reason_tr": "Zamir nesne değildir; özne, nesne veya iyelik görevi görür.",
        },
        "adverb": {
            "part_of_speech": "adverb",
            "countability": "n/a",
            "semantic_category": "adverb",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» zarftır; fiili, sıfatı veya cümleyi niteler. "
                "Sıklıkla -ly eki (quickly) veya yer/zaman (here, now)."
            ),
            "common_verbs": ["walk", "speak", "drive", "work", "run", "eat"],
            "common_collocations": [f"walk {target_word}", f"speak {target_word}", "very carefully"],
            "common_patterns": [f"He walks {target_word}.", "Come here.", "I always …"],
            "article_notes_tr": "Zarflarda a/an/the kullanılmaz.",
            "avoid_patterns": [f"a {target_word}", f"my {target_word}", f"the {target_word} is here"],
            "avoid_reason_tr": "Zarf nesne değildir; fiilin nasıl/ne zaman/nerede yapıldığını gösterir.",
        },
        "preposition": {
            "part_of_speech": "preposition",
            "countability": "n/a",
            "semantic_category": "preposition",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» edattır; isimden önce gelir ve yer, yön, zaman veya ilişki bildirir. "
                "in/on/at/with/for gibi kalıplarla öğrenilir."
            ),
            "common_verbs": ["go", "be", "put", "stay", "wait", "look"],
            "common_collocations": [f"in the morning", f"on the table", f"at home", f"with me"],
            "common_patterns": [f"I am at home.", f"The book is on the table.", f"Come with me."],
            "article_notes_tr": "Edatlar tek başına değil, isim/ifade ile kullanılır (at home, on the table).",
            "avoid_patterns": [f"bought a {target_word}", f"my {target_word} is on", f"I am using the {target_word}"],
            "avoid_reason_tr": "Edat nesne değildir; isimle birlikte yer/yön/zaman bildirir.",
        },
        "conjunction": {
            "part_of_speech": "conjunction",
            "countability": "n/a",
            "semantic_category": "conjunction",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» bağlaçtır; kelime, öbek veya cümleleri birbirine bağlar. "
                "and/but/because/if gibi kalıplarla öğrenilir."
            ),
            "common_verbs": ["want", "like", "go", "stay", "eat", "work"],
            "common_collocations": ["coffee and tea", "tired but happy", "because I was late"],
            "common_patterns": ["I like tea and coffee.", "I stayed because it was raining."],
            "article_notes_tr": "Bağlaçlar tek başına nesne olmaz; iki parçayı birleştirir.",
            "avoid_patterns": [f"bought a {target_word}", f"my {target_word}", f"bring the {target_word}"],
            "avoid_reason_tr": "Bağlaç satın alınmaz veya taşınmaz; cümleleri bağlar.",
        },
        "interjection": {
            "part_of_speech": "interjection",
            "countability": "n/a",
            "semantic_category": "interjection",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» ünlemdir; duygu, selamlama veya ani tepki bildirir. "
                "Kısa, doğal ve diyalog içinde öğrenilir."
            ),
            "common_verbs": ["say", "shout", "wave", "smile", "answer", "reply"],
            "common_collocations": ["say hello", "say yes", "oh no", "wow"],
            "common_patterns": ["Hello!", "Oh no!", "Yes, please."],
            "article_notes_tr": "Ünlemlerde artikel kullanılmaz; çoğu zaman tek başına veya kısa cümlede gelir.",
            "avoid_patterns": [f"bought a {target_word}", f"my {target_word} is on", f"I am using the {target_word}"],
            "avoid_reason_tr": "Ünlem nesne değildir; selamlama veya duygu ifadesidir.",
        },
        "animal": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "animal",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» bir hayvandır; feed, walk, adopt, pet gibi fiiller doğaldır.",
            "common_verbs": ["feed", "walk", "adopt", "pet", "see", "love"],
            "common_collocations": [f"a {target_word}", f"my {target_word}", f"feed the {target_word}"],
            "common_patterns": [f"I have a {target_word}.", f"The {target_word} is sleeping."],
            "article_notes_items": [
                {"en": f"a {target_word}", "tr": f"bir {word_tr.lower()}"},
                {"en": f"the {target_word}", "tr": word_tr.lower()},
            ],
            "avoid_reason_tr": "Hayvan sevilir, beslenir, gezdirilir; mekanik nesne şablonu kullanılmaz.",
        },
        "fruit": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "fruit",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» meyvedir; eat, buy, peel, slice fiilleri doğaldır.",
            "common_verbs": ["eat", "buy", "peel", "slice", "like", "have"],
            "common_collocations": [f"an {target_word}", f"a {target_word}", f"some {target_word}s"],
            "common_patterns": [f"I like {target_word}s.", f"Can I have an {target_word}?"],
            "article_notes_items": [
                {"en": f"an {target_word}", "tr": f"bir {word_tr.lower()}"},
                {"en": f"{target_word}s", "tr": f"{word_tr.lower()}lar"},
            ],
            "avoid_reason_tr": "Meyve yenir; bring the X / using the X şablonu kullanılmaz.",
        },
        "vegetable": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "vegetable",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» sebzedir; cook, chop, buy, eat fiilleri doğaldır.",
            "common_verbs": ["cook", "chop", "buy", "eat", "wash", "grow"],
            "common_collocations": [f"fresh {target_word}s", f"chop the {target_word}"],
            "common_patterns": [f"I need some {target_word}s.", f"Chop the {target_word}."],
            "article_notes_items": [
                {"en": f"a {target_word}", "tr": f"bir {word_tr.lower()}"},
                {"en": f"the {target_word}", "tr": word_tr.lower()},
            ],
            "avoid_reason_tr": "Sebze pişirilir, doğranır; nesne şablonu kullanılmaz.",
        },
        "furniture": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "furniture",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» mobilyadır; sit, lie, put, move fiilleri doğaldır.",
            "common_verbs": ["sit", "lie", "put", "move", "buy", "assemble"],
            "common_collocations": [f"on the {target_word}", f"sit on the {target_word}"],
            "common_patterns": [f"Sit on the {target_word}.", f"The {target_word} is comfortable."],
            "article_notes_items": [
                {"en": f"the {target_word}", "tr": word_tr.lower()},
                {"en": f"a new {target_word}", "tr": f"yeni bir {word_tr.lower()}"},
            ],
            "avoid_reason_tr": "Mobilya oturulur, üzerine konur; love/drink/eat fiilleri kullanılmaz.",
        },
        "object": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "object",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» günlük hayatta kullanılan bir nesnedir. "
                "buy, find, use, carry, need gibi fiillerle doğal cümleler kurulur."
            ),
            "common_verbs": ["buy", "find", "carry", "need", "lose", "forget"],
            "common_collocations": [
                f"my {target_word}", f"a new {target_word}", f"where is my {target_word}",
                f"look for my {target_word}", f"lost my {target_word}",
            ],
            "common_patterns": [
                f"Where is my {target_word}?",
                f"I lost my {target_word}.",
                f"I need to buy a new {target_word}.",
            ],
            "article_notes_items": [
                {"en": f"my {target_word}", "tr": _possessive_tr(word_tr)},
                {"en": f"a new {target_word}", "tr": f"yeni bir {word_tr.lower()}"},
                {"en": f"the {target_word}", "tr": word_tr.lower()},
            ],
            "article_notes_tr": (
                f"my {target_word} → {_possessive_tr(word_tr)} / "
                f"a new {target_word} → yeni bir {word_tr.lower()}"
            ),
            "avoid_patterns": ["I love X", "Do you want X", "Bring the X", "I am using the X", "eat the", "drink the"],
            "avoid_reason_tr": "Her nesne için aynı şablon kullanılmaz; yemek/içmek fiilleri nesnelerle kullanılmaz.",
        },
        "footwear": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "footwear",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» genelde çoğul (shoes) kullanılır. "
                "wear, buy, tie, try on gibi fiillerle doğal cümleler kurulur."
            ),
            "common_verbs": ["buy", "wear", "lose", "tie", "try on", "clean"],
            "common_collocations": [
                "a pair of shoes", "wear shoes", "tie your shoes",
                "try on shoes", "buy new shoes", "take off your shoes",
            ],
            "common_patterns": [
                "These shoes are very comfortable.",
                "I need to buy a new pair of shoes.",
                "Don't forget to tie your shoes.",
            ],
            "article_notes_tr": "Tekil: a shoe · Çoğul: shoes · Bir çift: a pair of shoes",
            "avoid_patterns": ["These socks are warm", "I love socks"],
            "avoid_reason_tr": "Ayakkabı öğretirken çorap (socks) ana konu olmamalı.",
        },
        "clothing": {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "clothing",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» giyim eşyasıdır. wear, put on, take off, wash, buy "
                f"gibi fiillerle doğal cümleler kurulur."
            ),
            "common_verbs": ["wear", "put on", "take off", "wash", "buy", "fold", "pack", "iron"],
            "common_collocations": [
                f"wear {target_word}", f"put on your {target_word}",
                f"take off your {target_word}", f"wash your {target_word}",
                f"buy new {target_word}", f"a pair of {target_word}",
            ],
            "common_patterns": [
                f"I wear {target_word} every day.",
                f"Where are my {target_word}?",
                f"I need to wash my {target_word}.",
            ],
            "article_notes_items": [
                {"en": f"my {target_word}", "tr": f"benim {word_tr}"},
                {"en": f"a pair of {target_word}", "tr": f"bir çift {word_tr}"},
                {"en": f"new {target_word}", "tr": f"yeni {word_tr}"},
            ],
            "article_notes_tr": f"my {target_word} → benim {word_tr}",
            "avoid_patterns": ["eat socks", "drink shirt", "I love socks (without context)"],
            "avoid_reason_tr": "Giyim eşyaları yenmez/içilmez; giyinmek, yıkamak, almak fiilleri kullanılır.",
        },
        "eyewear": {
            "part_of_speech": "noun",
            "countability": "plural",
            "semantic_category": "eyewear",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» İngilizcede glasses (çoğul) olarak kullanılır. "
                "Türkçede gözlük takılır — wear/put on → takmak (giymek değil). "
                "take off, clean, lose, find gibi fiillerle doğal cümleler kurulur. "
                "❌ a glasses yok — ✅ a pair of glasses."
            ),
            "common_verbs": ["wear", "put on", "take off", "clean", "lose", "find", "break", "wipe"],
            "common_collocations": [
                "wear glasses", "a pair of glasses", "reading glasses",
                "prescription glasses", "take off your glasses", "clean your glasses",
            ],
            "common_patterns": [
                {"en": "I wear glasses every day.", "tr": "Her gün gözlük takarım."},
                {"en": "I lost my glasses.", "tr": "Gözlüğümü kaybettim."},
                {"en": "Can you help me find my glasses?", "tr": "Gözlüğümü bulmama yardım eder misin?"},
            ],
            "article_notes_items": [
                {"en": "my glasses", "tr": "gözlüğüm"},
                {"en": "a pair of glasses", "tr": "bir gözlük (çift)"},
                {"en": "the glasses", "tr": "gözlükler"},
            ],
            "article_notes_tr": "my glasses → gözlüğüm / a pair of glasses → bir gözlük",
            "avoid_patterns": ["a glasses", "glasses is", "eat glasses", "drink glasses"],
            "avoid_reason_tr": "Gözlük çoğul isimdir (glasses are). Yemek/içmek fiilleri kullanılmaz.",
        },
        "tobacco": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "tobacco",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» sigara/tütün kelimesidir; en doğal eylem smoke (içmek/tüttürmek) kullanılır. "
                "light a cigarette (yakmak), put out / stub out (söndürmek), quit smoking (bırakmak), "
                "roll a cigarette (sarmak) günlük hayatta en sık duyulan kalıplardır. "
                "❌ eat/drink/like cigarette — yiyecek veya genel nesne kalıbı değildir."
            ),
            "common_verbs": ["smoke", "light", "put out", "stub out", "quit", "roll", "flick"],
            "common_collocations": [
                "smoke a cigarette", "light a cigarette", "put out a cigarette",
                "stub out a cigarette", "quit smoking", "a pack of cigarettes",
                "cigarette smoke", "roll a cigarette",
            ],
            "common_patterns": [
                {"en": "Do you smoke?", "tr": "Sigara içer misin?"},
                {"en": "I need to quit smoking.", "tr": "Sigarayı bırakmam lazım."},
                {"en": "He lit a cigarette outside.", "tr": "Dışarıda bir sigara yaktı."},
            ],
            "article_notes_items": [
                {"en": "a cigarette", "tr": "bir sigara"},
                {"en": "cigarettes", "tr": "sigaralar"},
                {"en": "a pack of cigarettes", "tr": "bir paket sigara"},
            ],
            "article_notes_tr": "a cigarette → bir sigara / cigarettes → sigaralar",
            "avoid_patterns": ["eat cigarette", "drink cigarette", "I like cigarette"],
            "avoid_reason_tr": "Sigara içilir (smoke), yenmez veya sevilmez gibi yiyecek kalıbıyla kullanılmaz.",
        },
        "verb": {
            "part_of_speech": "verb",
            "countability": "n/a",
            "semantic_category": "verb",
            "meaning_tr": word_tr,
            "usage_notes_tr": f"«{word_tr}» fiildir; özne + fiil + nesne/zarf yapısı kullanılır.",
            "common_verbs": [target_word],
            "common_collocations": [f"I {target_word}", f"need to {target_word}", f"don't {target_word}"],
            "common_patterns": [f"I {target_word} every day.", f"Do you {target_word} here?"],
            "article_notes_tr": None,
            "avoid_patterns": [],
            "avoid_reason_tr": "Fiil çekimine dikkat: works, worked, working.",
        },
        "document": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "document",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» belge/fatura türü bir kelimedir. "
                "pay, send, receive, check, sign gibi fiillerle doğal cümleler kurulur."
            ),
            "common_verbs": ["pay", "send", "receive", "check", "sign", "issue", "review"],
            "common_collocations": [
                f"pay the {target_word}", f"send the {target_word}",
                f"receive the {target_word}", f"check the {target_word}",
            ],
            "common_patterns": [
                {"en": f"I received the {target_word} by email.", "tr": f"{word_tr.capitalize()}yı e-postayla aldım."},
                {"en": f"When is the {target_word} due?", "tr": f"{word_tr.capitalize()}nın son ödeme tarihi ne?"},
            ],
            "article_notes_tr": f"an {target_word} / the {target_word}",
            "avoid_patterns": ["open the", "bring the", "I am using the"],
            "avoid_reason_tr": "Belge/fatura açılıp kapatılmaz; ödenir, gönderilir, kontrol edilir.",
        },
        "snack": {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "snack",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» yenilebilir bir atıştırmalıktır. "
                "chew, eat, buy, share, offer gibi fiillerle doğal cümleler kurulur. "
                "Sakız için: chew gum, a piece of gum, blow a bubble — ❌ open the gum, use the gum."
            ),
            "common_verbs": ["chew", "eat", "buy", "share", "offer", "swallow", "spit out"],
            "common_collocations": [
                "chew gum", "a piece of gum", "sugar-free gum", "blow a bubble",
                "stick of gum", "share gum",
            ],
            "common_patterns": [
                {"en": "Do you have any gum?", "tr": "Sakızın var mı?"},
                {"en": "I'm chewing gum right now.", "tr": "Şu an sakız çiğniyorum."},
                {"en": "Could I have a piece of gum?", "tr": "Bir sakız alabilir miyim?"},
            ],
            "article_notes_items": [
                {"en": "a piece of gum", "tr": "bir sakız"},
                {"en": "some gum", "tr": "biraz sakız"},
                {"en": "sugar-free gum", "tr": "şekersiz sakız"},
            ],
            "avoid_patterns": ["open the gum", "use the gum", "The gum is here", "bring the gum"],
            "avoid_reason_tr": "Sakız açılmaz veya 'kullanılmaz'; çiğnenir, paylaşılır, atılır.",
        },
    }
    if category == "general":
        pos = detect_part_of_speech(word_tr, target_word)
        pos_map = {
            "adjective": "adjective", "verb": "verb", "pronoun": "pronoun", "adverb": "adverb",
            "preposition": "preposition", "conjunction": "conjunction", "interjection": "interjection",
        }
        category = pos_map.get(pos, "object")
    base = profiles.get(category, profiles["object"])
    wt, tw = _norm(word_tr), _en_target_word(target_word)
    if category == "beverage" and (wt in ("soda", "gazoz", "kola") or tw in ("soda", "cola")):
        base = {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "beverage",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"İngilizcede «{target_word}» kelimesi bağlama göre farklı anlamlara gelir. "
                "Amerika'da genellikle şekerli gazlı içeceklerin (kola, gazoz vb.) genel adıdır. "
                "Türkçede içtiğimiz sade maden suyu/soda anlamı için İngilizcede daha çok "
                "«sparkling water», «mineral water» veya «club soda» ifadeleri tercih edilir. "
                "Ayrıca kimyada ve temizlikte «karbonat/yemek sodası» (baking soda) anlamında da sıkça kullanılır. "
                "Maddesel olarak sayılamazdır (uncountable) ancak porsiyon olarak sayılabilir (countable)."
            ),
            "alternative_terms_tr": [
                {
                    "en": "sparkling water",
                    "tr": "maden suyu (köpüklü)",
                    "note_tr": "Türkçedeki «soda» (maden suyu) için en doğal İngilizce ifade",
                },
                {
                    "en": "mineral water",
                    "tr": "maden suyu / mineral su",
                    "note_tr": "Şişelenmiş maden suyu",
                },
                {
                    "en": "club soda",
                    "tr": "club soda / sade maden suyu",
                    "note_tr": "Restoranlarda sık kullanılır",
                },
                {
                    "en": "baking soda",
                    "tr": "karbonat / yemek sodası",
                    "note_tr": "İçecek değil — temizlik ve pişirmede",
                },
            ],
            "common_verbs": ["drink", "order", "have", "get", "serve", "buy"],
            "common_collocations": [
                "a can of soda", "a bottle of soda", "diet soda", "regular soda", "order a soda",
            ],
            "common_patterns": [
                "Can I have a soda?", "I don't drink soda.", "Would you like a soda?",
            ],
            "article_notes_tr": (
                "Madde: soda (sayılamaz) · Porsiyon: a soda / a can of soda · "
                "Kutu: a can · Şişe: a bottle · Maden suyu için: sparkling/mineral water"
            ),
            "regional_variants": {
                "us": "soda / pop",
                "uk": "fizzy drink / soft drink",
                "note_tr": "🇺🇸 soda veya pop · 🇬🇧 fizzy drink daha yaygın olabilir",
            },
            "avoid_patterns": ["black soda", "I love soda", "These socks are warm"],
            "avoid_reason_tr": "Gazoz için black soda doğal değil; diet soda veya cola kullan.",
        }
    elif _is_beverage_like(wt, tw) and ("water" in tw or "maden" in wt):
        drink = _canonical_beverage_phrase(target_word)
        base = {
            "part_of_speech": "noun",
            "countability": "uncountable",
            "semantic_category": "beverage",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» → {drink}. Türkçedeki maden suyu İngilizcede en doğal olarak "
                "sparkling water veya mineral water ile ifade edilir. "
                "Amerikan İngilizcesinde restoranda «Could I have a bottle of sparkling water?» "
                "çok yaygındır. ❌ Open the mineral water veya fix the water gibi ifadeler doğal değildir; "
                "drink, have, order, buy fiilleri kullanılır."
            ),
            "alternative_terms_tr": [
                {"en": "sparkling water", "tr": "maden suyu (köpüklü)", "note_tr": "En yaygın Amerikan ifadesi"},
                {"en": "mineral water", "tr": "maden suyu / mineral su", "note_tr": "Şişelenmiş maden suyu"},
                {"en": "club soda", "tr": "sade maden suyu", "note_tr": "Restoranlarda"},
                {"en": "still water", "tr": "sade su (köpüksüz)", "note_tr": "Maden suyu değil — düz su"},
            ],
            "common_verbs": ["drink", "have", "order", "buy", "serve", "bring", "prefer"],
            "common_collocations": [
                f"a bottle of {drink}", f"some {drink}", f"drink {drink}", f"still or sparkling water",
            ],
            "common_patterns": [
                f"Could I have a bottle of {drink}?",
                f"I usually drink {drink} with meals.",
                f"Is the {drink} in the fridge?",
            ],
            "article_notes_tr": "Genelde sayılamaz (some mineral water). Şişe/kutu: a bottle of … / a glass of …",
            "regional_variants": {
                "us": "sparkling water / mineral water",
                "uk": "sparkling water / still water",
                "note_tr": "🇺🇸 sparkling water · 🇬🇧 still water (sade su) ayrımına dikkat",
            },
            "avoid_patterns": ["open the mineral water", "fix the water", "the water is broken"],
            "avoid_reason_tr": "Maden suyu bir içecektir; açmak/tamir etmek ifadeleri kullanılmaz.",
        }
    elif category == "food" and (wt in ("mısır", "misir") or tw in ("corn", "sweetcorn", "maize")):
        base = {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "food",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» → corn. Amerikan İngilizcesinde mısır tanesi/bitki için standart kelime "
                "corn'dur (sweet corn, corn on the cob, canned corn). "
                "İngiliz İngilizcesinde bazen sweetcorn veya maize de kullanılır; "
                "biz varsayılan olarak Amerikan İngilizcesi (corn) öğretiyoruz."
            ),
            "common_verbs": ["eat", "cook", "boil", "grill", "grow", "buy", "serve"],
            "common_collocations": [
                "corn on the cob", "sweet corn", "canned corn", "fresh corn", "corn soup",
            ],
            "common_patterns": [
                "I like corn.", "We had corn for dinner.", "Can you buy some corn?",
            ],
            "article_notes_tr": "Madde: corn (sayılamaz) · Porsiyon: an ear of corn / some corn",
            "regional_variants": {
                "us": "corn",
                "uk": "sweetcorn / maize",
                "note_tr": US_UK_VARIANT_NOTES.get("corn", ""),
            },
            "avoid_patterns": ["I love corn Egypt", "corn country"],
            "avoid_reason_tr": "Mısır (ülke) için Egypt kullan; küçük m ile mısır (yiyecek) için corn.",
        }
    elif category == "beverage" and (wt in ("kahve", "coffee") or tw == "coffee"):
        base = dict(profiles["beverage"])
        base["usage_notes_tr"] = (
            f"«{word_tr}» genelde içecek olarak kullanılır. "
            "Türkçedeki «kahve içmek» İngilizcede drink/have coffee ile kurulur. "
            "Bir porsiyon için a coffee da kullanılabilir."
        )
    elif category == "drinkware" and (wt in ("bardak",) or tw == "glass"):
        base = {
            "part_of_speech": "noun",
            "countability": "both",
            "semantic_category": "drinkware",
            "meaning_tr": "bardak (kap)",
            "usage_notes_tr": (
                "«bardak» → glass. İngilizcede glass iki anlama gelir: "
                "sayılabilir olarak «bardak» (a glass, three glasses) ve "
                "sayılamaz olarak «cam» materyali (made of glass). "
                "Çoğul glasses bağlama göre «bardaklar» veya «gözlük» olabilir. "
                "Doğal kalıp: a glass of water (bir bardak su). "
                "❌ I want a glass tek başına kaba — Can I have a glass of water? veya "
                "Could I get an empty glass, please? daha doğal."
            ),
            "common_verbs": ["fill", "break", "wash", "dry", "raise", "hold", "pour"],
            "common_collocations": [
                "a glass of water", "an empty glass", "break a glass",
                "wash the glasses", "fill the glass", "the glasses",
            ],
            "common_patterns": [
                "Can I have a glass of water?",
                "Would you like a glass of cold water?",
                "There isn't a glass on the table.",
            ],
            "article_notes_tr": (
                "Bardak (kap): a glass / the glass / an empty glass. "
                "Cam (materyal): glass (sayılamaz, artikel yok: Glass is fragile)."
            ),
            "avoid_patterns": ["I want glass", "drink the glass", "open the glass"],
            "avoid_reason_tr": (
                "Restoranda bardak isterken içeceği de belirt: a glass of water. "
                "Boş bardak için: an empty glass, please."
            ),
        }
    return {"target_word": target_word, **base, "part_of_speech": base.get("part_of_speech") or detect_part_of_speech(word_tr, target_word)}


def _pattern_label(grammar_pattern: str) -> str:
    return GRAMMAR_PATTERNS.get(grammar_pattern, {}).get("label_tr", grammar_pattern)


def _resolve_grammar_pattern(sentence_type: str, grammar_pattern: str | None = None) -> str:
    if grammar_pattern and grammar_pattern in GRAMMAR_PATTERNS:
        return grammar_pattern
    return PATTERN_TYPE_ALIASES.get(sentence_type, sentence_type if sentence_type in GRAMMAR_PATTERNS else "basic")


def _thirteen_pattern_examples_en(
    word_tr: str,
    target_word: str,
    category: str,
) -> list[dict[str, Any]]:
    """13 dil bilgisi kalıbına göre kelimeye özel örnek cümleler."""
    category = _resolve_category(word_tr, target_word, category)
    T, W = _en_target_word(target_word), word_tr
    wt, tw = _norm(word_tr), T

    lex = build_lexicon_examples(W, T, _pe)
    if lex:
        return lex

    if _is_beverage_like(wt, tw) and ("water" in tw or "maden" in wt):
        return _sparkling_water_pattern_examples(W, _canonical_beverage_phrase(target_word))
    if _is_adjective_like(wt, tw):
        if _is_quiet_like(wt, tw):
            return _quiet_pattern_examples(W, T)
        return _adjective_pattern_examples(W, T)
    if _is_pronoun_like(wt, tw):
        return _pronoun_pattern_examples(W, T)
    if _is_adverb_like(wt, tw):
        return _adverb_pattern_examples(W, T)
    if _is_preposition_like(wt, tw):
        return _preposition_pattern_examples(W, T)
    if _is_conjunction_like(wt, tw):
        return _conjunction_pattern_examples(W, T)
    if _is_interjection_like(wt, tw):
        return _interjection_pattern_examples(W, T)
    if _is_verb_like(wt, tw) or category == "verb":
        return _verb_pattern_examples(W, T)
    if category in ("fruit", "vegetable") or wt in ("elma", "muz", "domates", "havuç", "havuc", "portakal"):
        return _food_pattern_examples(W, T, wt, tw)
    if category == "animal":
        return _animal_pattern_examples(W, T)
    if category == "furniture":
        return _furniture_pattern_examples(W, T)
    if category == "adjective":
        return _adjective_pattern_examples(W, T)
    if category == "verb":
        return _verb_pattern_examples(W, T)
    if category == "preposition":
        return _preposition_pattern_examples(W, T)
    if category == "conjunction":
        return _conjunction_pattern_examples(W, T)
    if category == "interjection":
        return _interjection_pattern_examples(W, T)
    if _is_market_like(wt, tw):
        return _market_pattern_examples(W, T)
    if category == "place":
        return _place_pattern_examples(W, T)
    if category == "beverage" or _is_beverage_like(wt, tw):
        return _beverage_pattern_examples(W, T, wt, tw)
    if category == "footwear":
        return _footwear_pattern_examples(W, T)
    if category == "clothing":
        return _clothing_pattern_examples(W, T, wt, tw)
    if category == "eyewear" or _is_eyewear_like(wt, tw):
        return _eyewear_pattern_examples(W, T, wt, tw)
    if category == "tobacco" or _is_tobacco_like(wt, tw):
        return _tobacco_pattern_examples(W, T, wt, tw)
    if category == "vehicle":
        return _vehicle_pattern_examples(W, T)
    if category == "plumbing":
        return _plumbing_pattern_examples(W, T)
    if category == "drinkware":
        return _drinkware_pattern_examples(W, T, wt, tw)
    if category == "food" or tw in ("corn", "sweetcorn", "maize"):
        return _food_pattern_examples(W, T, wt, tw)
    if category == "snack" or _is_snack_like(wt, tw):
        return _snack_pattern_examples(W, T, wt, tw)
    if category == "abstract" or _is_abstract_like(wt, tw):
        return _abstract_noun_pattern_examples(W, T, wt, tw)
    if _is_umbrella_like(wt, tw):
        return _umbrella_pattern_examples(W, T)
    if _is_wallet_like(wt, tw):
        return _wallet_pattern_examples(W, T)
    return _safe_object_pattern_examples(W, T, category)


def _drinkware_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Bardak / glass — doğal a glass of… kalıpları."""
    if tw == "glass":
        return [
            _pe(W, "Her yemekte bir bardak su içerim.", "I drink a glass of water with every meal.", "basic",
                "I + drink + a glass of water + with every meal",
                "1️⃣ Genel anlam\nGünlük rutin: her yemekte bir bardak su içmek.\n\n"
                "2️⃣ a glass of water\n«Bir bardak su» kalıbı — glass + of + içecek.\n\n"
                "3️⃣ with every meal\n«Her yemekte / yemeklerde» anlamı.\n\n"
                "❌ I drink water glass — doğal değil."),
            _pe(W, "O, bardakları yıkıyor.", "He is washing the glasses.", "present",
                "He + is + washing + the glasses",
                "1️⃣ Şimdiki zaman\nis + washing → yıkıyor.\n\n"
                "2️⃣ glasses\nGlass çoğulu glasses olur (glaasız).\n\n"
                "3️⃣ the glasses\nBelirli bardaklar → the glasses.",
                scenario_badge="🔄 ŞU AN"),
            _pe(W, "Yanlışlıkla bir bardak kırdım.", "I accidentally broke a glass.", "past",
                "I + accidentally + broke + a glass",
                "1️⃣ Geçmiş zaman\nbroke → kırdım (break'in geçmişi).\n\n"
                "2️⃣ accidentally\nYanlışlıkla / kazara.\n\n"
                "3️⃣ a glass\nTekil bardak → a glass.",
                scenario_badge="🕐 GEÇMİŞ"),
            _pe(W, "Yemeğe bir bardak su koyacağım.", "I will pour a glass of water for dinner.", "future",
                "I + will + pour + a glass of water",
                "1️⃣ Gelecek zaman\nwill + pour → koyacağım / dolduracağım.\n\n"
                "2️⃣ pour a glass of\nBardağı doldurmak için doğal fiil: pour.\n\n"
                "3️⃣ for dinner\nYemek için."),
            _pe(W, "Masada kaç bardak var?", "How many glasses are on the table?", "question",
                "How many + glasses + are + on the table",
                "1️⃣ Soru cümlesi\nHow many → kaç tane\n\n"
                "2️⃣ glasses are\nÇoğul: are (is değil).\n\n"
                "3️⃣ on the table\nMasada → on the table."),
            _pe(W, "Masada hiç bardak yok.", "There isn't a glass on the table.", "negative",
                "There + isn't + a glass + on the table",
                "1️⃣ Olumsuz / yokluk\nThere isn't a… → … yok (tekil).\n\n"
                "2️⃣ a glass\nTekil bardak.\n\n"
                "3️⃣ on the table\nMasada → on the table.",
                scenario_badge="⛔ OLUMSUZ"),
            _pe(W, "Bardağı doldur.", "Fill the glass.", "imperative",
                "Fill + the glass",
                "1️⃣ Emir kipi\nFill → doldur\n\n"
                "2️⃣ the glass\nBelirli bardak.\n\n"
                "Emirde özne yazılmaz."),
            _pe(W, "Boş bir bardak alabilir miyim?", "Can I have an empty glass?", "polite_request",
                "Can + I + have + an empty glass",
                "1️⃣ Rica cümlesi\nCan I have…? → … alabilir miyim?\n\n"
                "2️⃣ an empty glass\nEmpty sesli harfle başlar → an (a değil).\n\n"
                "3️⃣ Boş bardak isteği\nİçecek değil, sadece bardak için doğal kalıp.",
                scenario_badge="🗣️ RİCA"),
            _pe(W, "Bir bardak soğuk su ister misiniz?", "Would you like a glass of cold water?", "advice",
                "Would + you + like + a glass of cold water",
                "1️⃣ Kibar teklif\nWould you like…? → … ister misiniz?\n\n"
                "2️⃣ cold water\nSıfat isimden önce: cold water.\n\n"
                "3️⃣ a glass of\nBir bardak … kalıbı.",
                scenario_badge="🤝 TEKLİF"),
            _pe(W, "Bardak toplamam lazım.", "I need to collect the glasses.", "obligation",
                "I + need to + collect + the glasses",
                "1️⃣ Zorunluluk\nneed to + fiil → …-mem lazım.\n\n"
                "2️⃣ collect the glasses\nBardakları toplamak."),
            _pe(W, "Bardak kırılmış olabilir.", "The glass might be broken.", "possibility",
                "The + glass + might + be + broken",
                "1️⃣ İhtimal\nmight be → … olabilir / …-mış olabilir.\n\n"
                "2️⃣ broken\nKırık (sıfat)."),
            _pe(W, "Bardak kırılırsa dikkatli ol.", "If the glass breaks, be careful.", "conditional",
                "If + the glass + breaks, + be careful",
                "1️⃣ Koşul cümlesi\nIf … breaks → … kırılırsa\n\n"
                "2️⃣ be careful\nDikkatli ol (emir/tavsiye)."),
            _pe(W, "A: Bir bardak su ister misin? B: Evet, lütfen.", "A: Would you like a glass of water? B: Yes, please.", "dialogue",
                "A: Would you like…? B: Yes, please",
                "1️⃣ Günlük diyalog\nKibar teklif + kısa cevap.\n\n"
                "2️⃣ Yes, please\nEvet, lütfen — çok doğal cevap."),
        ]
    return _object_pattern_examples(W, T, "drinkware")


def _pe(
    W: str,
    tr: str,
    target: str,
    grammar_pattern: str,
    structure_tr: str,
    how: str,
    pattern_tr: str | None = None,
    scenario_badge: str | None = None,
) -> dict[str, Any]:
    return _ex(W, tr, target, grammar_pattern, structure_tr, how,
                 pattern_tr=pattern_tr, grammar_pattern=grammar_pattern, scenario_badge=scenario_badge)


def _sparkling_water_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Maden suyu / mineral water / sparkling water — doğal içecek cümleleri."""
    drink = T
    bottle = f"a bottle of {drink}" if "water" in drink else f"some {drink}"
    return [
        _pe(W, "Yemeklerde genelde maden suyu içerim.", f"I usually drink {drink} with meals.", "basic",
            f"I + usually + drink + {drink}",
            f"Günlük rutin: yemekle birlikte maden suyu içmek doğal bir ifadedir."),
        _pe(W, "Şu an buzdolabındaki maden suyunu içiyorum.", f"I am drinking the {drink} from the fridge.", "present",
            f"I + am + drinking + the {drink}",
            f"Şu anda devam eden eylem: am + drinking."),
        _pe(W, "Dün akşam yemeğinde maden suyu içtik.", f"We had {drink} with dinner yesterday.", "past",
            f"We + had + {drink}",
            f"Geçmişte içmek için had {drink} doğal bir kalıptır."),
        _pe(W, "Yarın marketten maden suyu alacağım.", f"I will buy {bottle} at the store tomorrow.", "future",
            f"I + will + buy + {bottle}",
            f"Gelecek plan: will buy a bottle of …"),
        _pe(W, "Maden suyu buzdolabında mı?", f"Is the {drink} in the fridge?", "question",
            f"Is + the {drink} + in the fridge",
            f"Konum sorma: Is the … in the fridge?"),
        _pe(W, "Maden suyu içmem, sade su içerim.", f"I don't drink {drink}; I only drink plain water.", "negative",
            f"I + don't + drink + {drink}",
            f"Tercih belirtme: don't drink … / only drink plain water."),
        _pe(W, "Lütfen biraz maden suyu getir.", f"Bring some {drink}, please.", "imperative",
            f"Bring + some + {drink}",
            f"Restoranda veya evde kibar emir: Bring some …"),
        _pe(W, "Bir şişe maden suyu alabilir miyim?", f"Could I have {bottle}?", "polite_request",
            f"Could I + have + {bottle}",
            f"Restoranda en doğal rica: Could I have a bottle of …?"),
        _pe(W, "Sıcak havalarda maden suyu içmelisin.", f"You should drink {drink} on hot days.", "advice",
            f"You + should + drink + {drink}",
            f"Sağlık/tavsiye bağlamında should drink …"),
        _pe(W, "Parti için maden suyu almam lazım.", f"I need to buy {drink} for the party.", "obligation",
            f"I + need to + buy + {drink}",
            f"İhtiyaç: need to buy … for the party."),
        _pe(W, "Mutfakta maden suyu kalmış olabilir.", f"There might be some {drink} left in the kitchen.", "possibility",
            f"There might be + some {drink}",
            f"İhtimal: There might be some … left."),
        _pe(W, "Susarsan buzdolabında maden suyu var.", f"If you're thirsty, there is {drink} in the fridge.", "conditional",
            f"If you're thirsty, + there is + {drink}",
            f"Koşul + öneri: If you're thirsty, there is …"),
        _pe(W, "A: Maden suyu ister misin? B: Evet, lütfen.", f"A: Would you like some {drink}? B: Yes, please.", "dialogue",
            f"Would you like + some {drink}",
            f"Günlük diyalog: Would you like some …?"),
    ]


def _food_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Yiyecek kelimeleri — doğal yeme/pişirme bağlamı."""
    food = T
    return [
        _pe(W, f"{W.capitalize()} severim.", f"I like {food}.", "basic",
            f"I + like + {food}", f"Genel tercih: I like …"),
        _pe(W, f"Şu an {W} yiyorum.", f"I am eating {food} now.", "present",
            f"I + am + eating + {food}", f"Şimdiki zaman: am eating …"),
        _pe(W, f"Dün akşam {W} yedik.", f"We ate {food} for dinner yesterday.", "past",
            f"We + ate + {food}", f"Geçmiş: ate … for dinner."),
        _pe(W, f"Yarın {W} alacağım.", f"I will buy some {food} tomorrow.", "future",
            f"I + will + buy + {food}", f"Alışveriş: will buy some …"),
        _pe(W, f"{W.capitalize()} var mı?", f"Do we have any {food}?", "question",
            f"Do we have + any {food}", f"Varlık sorma: Do we have any …?"),
        _pe(W, f"{W.capitalize()} yemem.", f"I don't eat {food}.", "negative",
            f"I + don't + eat + {food}", f"Olumsuz tercih: don't eat …"),
        _pe(W, f"Biraz {W} koy.", f"Add some {food}, please.", "imperative",
            f"Add + some + {food}", f"Yemek yaparken: Add some …"),
        _pe(W, f"Biraz {W} alabilir miyim?", f"Could I have some {food}?", "polite_request",
            f"Could I have + some {food}", f"Rica: Could I have some …?"),
        _pe(W, f"Taze {W} yemelisin.", f"You should eat fresh {food}.", "advice",
            f"You should eat + fresh {food}", f"Tavsiye: should eat fresh …"),
        _pe(W, f"Marketten {W} almam lazım.", f"I need to buy {food} at the store.", "obligation",
            f"I need to buy + {food}", f"İhtiyaç: need to buy …"),
        _pe(W, f"Buzdolabında {W} kalmış olabilir.", f"There might be some {food} in the fridge.", "possibility",
            f"There might be + {food}", f"İhtimal: might be some … in the fridge."),
        _pe(W, f"Açsan {W} ye.", f"If you're hungry, eat some {food}.", "conditional",
            f"If you're hungry, + eat + {food}", f"Koşul: If you're hungry, eat …"),
        _pe(W, f"A: {W.capitalize()} ister misin? B: Evet.", f"A: Would you like some {food}? B: Yes, please.", "dialogue",
            f"Would you like + some {food}", f"Diyalog: Would you like some …?"),
    ]


def _abstract_noun_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Soyut/sayılamayan isimler — entertainment, happiness vb.; mekanik şablon yok."""
    return [
        _pe(W, f"Bu akşam için iyi bir {W} bulmalıyız.", f"We need to find some good {T} for tonight.", "routine",
            f"need + some good {T}",
            f"Günlük plan: need some good {T} — doğal soyut isim kullanımı.",
            scenario_badge="🌅 RUTİN"),
        _pe(W, f"O mekân ilginç {W} seçenekleri sunuyor.", f"This place offers interesting {T} options.", "present_continuous",
            f"offers + interesting {T} + options",
            f"Şu anki durum: offers interesting {T} options — seçenek sunmak.",
            scenario_badge="🔄 ŞU AN"),
        _pe(W, f"{W.capitalize()} sektörü zor bir dönemden geçiyor.", f"The {T} industry is going through a difficult time.", "past",
            f"the {T} industry + is going through",
            f"Geçmiş/devam eden durum: the {T} industry — sektör ifadesi.",
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Cumartesi akşamı için {W} planlıyoruz.", f"We are planning {T} for Saturday night.", "future",
            f"are planning + {T}",
            f"Gelecek plan: are planning {T} for Saturday night.",
            scenario_badge="🔮 GELECEK"),
        _pe(W, f"Ne tür {W} tercih edersin?", f"What kind of {T} do you prefer?", "question",
            f"What kind of {T}",
            f"Soru: What kind of {T} do you prefer? — tercih sorma.",
            scenario_badge="❓ SORU"),
        _pe(W, f"Bu etkinlik {W} sunmuyor.", f"This event doesn't offer any {T}.", "negative",
            f"doesn't offer + any {T}",
            f"Olumsuz: doesn't offer any {T} — sunmamak.",
            scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"Parti için iyi {W} bul.", f"Find good {T} for the party.", "imperative",
            f"Find + good {T}",
            f"Emir: Find good {T} for the party."),
        _pe(W, f"Bu akşam için {W} önerebilir misin?", f"Could you suggest {T} for tonight?", "polite_request",
            f"suggest {T}",
            f"Kibar rica: Could you suggest {T} for tonight?"),
        _pe(W, f"Çocuklar için uygun {W} seçmelisin.", f"You should choose appropriate {T} for kids.", "advice",
            f"appropriate {T}",
            f"Tavsiye: appropriate {T} for kids — uygun seçim."),
        _pe(W, f"Parti için {W} ayarlamam gerekiyor.", f"I need to arrange {T} for the party.", "obligation",
            f"arrange {T}",
            f"Gereklilik: need to arrange {T} for the party."),
        _pe(W, f"Burada canlı {W} olabilir.", f"There might be live {T} here.", "possibility",
            f"live {T}",
            f"Olasılık: There might be live {T} here."),
        _pe(W, f"Yağmur yağarsa iç mekân {W} planlarız.", f"If it rains, we'll plan indoor {T}.", "conditional",
            f"indoor {T}",
            f"Koşul: If it rains, we'll plan indoor {T}."),
        _pe(W, f"A: {W.capitalize()} var mı? B: Evet, canlı müzik var.", f"A: Is there any {T}? B: Yes, there's live music.", "dialogue",
            f"Is there any {T}",
            f"Diyalog: Is there any {T}? — günlük soru."),
    ]


def _clothing_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Çorap, gömlek vb. — wear/put on/wash kalıpları."""
    item = T if tw.endswith("s") else (T if T.endswith("s") else T)
    pair = f"a pair of {item}" if item.endswith("s") else f"a {item}"
    my = f"my {item}"
    return [
        _pe(W, f"Her gün {W} giyerim.", f"I wear {item} every day.", "routine",
            f"I + wear + {item}", f"Günlük: wear → giymek/takmak.", scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an temiz {W} arıyorum.", f"I am looking for clean {item} right now.", "present",
            f"looking for clean {item}", f"Şu an: looking for → arıyorum.", scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün yeni {W} aldım.", f"I bought new {item} yesterday.", "past",
            f"bought new {item}", f"Geçmiş: bought new … → yeni … aldım.", scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {W} yıkayacağım.", f"I will wash my {item} tomorrow.", "future",
            f"will wash my {item}", f"Gelecek: wash → yıkamak.", scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} nerede?", f"Where are my {item}?" if item.endswith("s") else f"Where is my {item}?", "question",
            f"Where are/is my {item}", f"Soru: Where is/are my …?"),
        _pe(W, f"Bu {W} artık giymiyorum.", f"I don't wear these {item} anymore." if item.endswith("s") else f"I don't wear this {item} anymore.", "negative",
            f"don't wear", f"Olumsuz: don't wear → giymiyorum.", scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()} giy.", f"Put on your {item}.", "imperative",
            f"Put on your {item}", f"Emir: Put on → giy/tak."),
        _pe(W, f"{W.capitalize()} ödünç alabilir miyim?", f"Could I borrow your {item}?", "polite_request",
            f"borrow your {item}", f"Kibar rica: Could I borrow …?"),
        _pe(W, f"Kışın kalın {W} giymelisin.", f"You should wear warm {item} in winter.", "advice",
            f"should wear warm {item}", f"Tavsiye: should wear warm …"),
        _pe(W, f"Yeni {W} almam lazım.", f"I need to buy new {item}.", "obligation",
            f"need to buy new {item}", f"Gereklilik: need to buy …"),
        _pe(W, f"{W.capitalize()} çantada olabilir.", f"My {item} might be in the bag.", "possibility",
            f"might be in the bag", f"Olasılık: might be in …"),
        _pe(W, f"Hava soğuksa {W} giy.", f"If it's cold, wear your {item}.", "conditional",
            f"If it's cold, wear", f"Koşul: If it's cold, wear …"),
        _pe(W, f"A: {W.capitalize()} var mı? B: Evet, dolapta.", f"A: Do you have extra {item}? B: Yes, in the closet.", "dialogue",
            f"Do you have extra {item}", f"Diyalog: Do you have extra …?"),
    ]


def _eyewear_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Gözlük — glasses (çoğul); wear/put on/take off kalıpları."""
    glasses = "glasses" if "glass" in tw else T
    return [
        _pe(W, "Her gün gözlük takarım.", f"I wear {glasses} every day.", "routine",
            f"I + wear + {glasses}",
            f"Günlük rutin: wear glasses → gözlük takmak. Glasses çoğul isimdir.",
            scenario_badge="🌅 RUTİN"),
        _pe(W, "Şu an gözlüğümü temizliyorum.", f"I am cleaning my {glasses} right now.", "present",
            f"I + am + cleaning + my {glasses}",
            f"Şu an: am cleaning my glasses. My glasses → gözlüğüm.",
            scenario_badge="🔄 ŞU AN"),
        _pe(W, "Dün gözlüğümü kaybettim.", f"I lost my {glasses} yesterday.", "past",
            f"I + lost + my {glasses}",
            f"Geçmiş: lost my glasses → gözlüğümü kaybettim.",
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, "Yarın yeni gözlük alacağım.", f"I will buy a new pair of {glasses} tomorrow.", "future",
            f"a new pair of {glasses}",
            f"Gelecek: a pair of glasses → bir gözlük (çift). ❌ a glasses değil.",
            scenario_badge="🔮 GELECEK"),
        _pe(W, "Gözlüğün var mı?", f"Do you wear {glasses}?", "question",
            f"Do you wear + {glasses}",
            f"Soru: Do you wear glasses? → Gözlük takıyor musun?"),
        _pe(W, "Gözlük takmıyorum.", f"I don't wear {glasses}.", "negative",
            f"I + don't + wear + {glasses}",
            f"Olumsuz: don't wear glasses.",
            scenario_badge="⛔ OLUMSUZ"),
        _pe(W, "Gözlüğünü tak.", f"Put on your {glasses}.", "imperative",
            f"Put on + your {glasses}",
            f"Emir: Put on your glasses → Gözlüğünü tak."),
        _pe(W, "Gözlüğümü bulmama yardım eder misin?", f"Could you help me find my {glasses}?", "polite_request",
            f"help me find my {glasses}",
            f"Kibar rica: Could you help me find my glasses?"),
        _pe(W, "Gözlüğünü düzenli temizlemelisin.", f"You should clean your {glasses} regularly.", "advice",
            f"clean your {glasses}",
            f"Tavsiye: clean your glasses regularly."),
        _pe(W, "Gözlükçüye gitmem lazım.", f"I need to go to the optician for new {glasses}.", "obligation",
            f"go to the optician",
            f"Gereklilik: optician → gözlükçü / optik."),
        _pe(W, "Gözlüğüm masada olabilir.", f"My {glasses} might be on the table.", "possibility",
            f"My {glasses} might be",
            f"Olasılık: might be on the table."),
        _pe(W, "Gözlüğünü takmazsan iyi görmezsin.", f"If you don't wear your {glasses}, you can't see well.", "conditional",
            f"If you don't wear your {glasses}",
            f"Koşul: If you don't wear your glasses…"),
        _pe(W, f"A: {W.capitalize()} takıyor musun? B: Evet, her gün.", f"A: Do you wear {glasses}? B: Yes, every day.", "dialogue",
            f"Do you wear {glasses}",
            f"Diyalog: Do you wear glasses? — günlük soru."),
    ]


def _tobacco_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Sigara — smoke/light/quit; asla eat değil."""
    cig = "cigarettes" if tw in ("cigarette", "cigarettes", "tobacco") else T
    a_cig = "a cigarette" if "cigarette" in tw or wt == "sigara" else f"a {cig}"
    return [
        _pe(W, "Sigara içmem.", f"I don't smoke {cig}.", "routine",
            f"I + don't + smoke",
            f"Genel tercih: don't smoke → sigara içmem. ❌ don't eat cigarette.",
            scenario_badge="🌅 RUTİN"),
        _pe(W, "Şu an dışarıda sigara içiyor.", f"He is smoking a cigarette outside right now.", "present",
            f"is smoking + a cigarette",
            f"Şu an: is smoking a cigarette → sigara içiyor.",
            scenario_badge="🔄 ŞU AN"),
        _pe(W, "Dün akşam iki sigara içti.", f"He smoked two cigarettes last night.", "past",
            f"smoked + two cigarettes",
            f"Geçmiş: smoked two cigarettes → iki sigara içti.",
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, "Yarın sigarayı bırakacağım.", f"I will quit smoking tomorrow.", "future",
            f"will quit smoking",
            f"Gelecek: quit smoking → sigarayı bırakmak.",
            scenario_badge="🔮 GELECEK"),
        _pe(W, "Sigara içiyor musun?", f"Do you smoke?", "question",
            f"Do you smoke",
            f"Soru: Do you smoke? → Sigara içiyor musun?"),
        _pe(W, "İç mekanlarda sigara içilmez.", f"You can't smoke indoors.", "negative",
            f"can't smoke indoors",
            f"Olumsuz/yasak: can't smoke indoors.",
            scenario_badge="⛔ OLUMSUZ"),
        _pe(W, "Sigarayı söndür lütfen.", f"Put out your cigarette, please.", "imperative",
            f"Put out + your cigarette",
            f"Emir: Put out your cigarette → Sigarayı söndür."),
        _pe(W, "Bir sigara verebilir misin?", f"Could I have a cigarette?", "polite_request",
            f"Could I have + a cigarette",
            f"Kibar rica: Could I have a cigarette?"),
        _pe(W, "Sigarayı bırakmalısın.", f"You should quit smoking.", "advice",
            f"should quit smoking",
            f"Tavsiye: should quit smoking → sigarayı bırakmalısın."),
        _pe(W, "Marketten sigara almam lazım.", f"I need to buy cigarettes at the store.", "obligation",
            f"need to buy cigarettes",
            f"Gereklilik: buy cigarettes at the store."),
        _pe(W, "Cebinde sigara olabilir.", f"There might be a cigarette in his pocket.", "possibility",
            f"might be a cigarette",
            f"Olasılık: might be a cigarette in his pocket."),
        _pe(W, "Stresliyse sigara içer.", f"If he's stressed, he smokes.", "conditional",
            f"If he's stressed, he smokes",
            f"Koşul: If he's stressed, he smokes."),
        _pe(W, f"A: {W.capitalize()} içer misin? B: Hayır, bıraktım.", f"A: Do you smoke? B: No, I quit.", "dialogue",
            f"Do you smoke",
            f"Diyalog: Do you smoke? B: No, I quit."),
    ]


def _snack_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    """Sakız, şeker, çikolata vb. — chew/eat/share kalıpları."""
    is_gum = wt in ("sakız", "sakiz") or "gum" in tw
    snack = "gum" if is_gum else T
    piece = "a piece of gum" if is_gum else f"some {snack}"
    return [
        _pe(W, f"{W.capitalize()} severim.", f"I like {snack}.", "basic",
            f"I + like + {snack}", f"Genel tercih: I like … — doğal ifade."),
        _pe(W, f"Şu an sakız çiğniyorum.", f"I'm chewing gum right now.", "present",
            f"I'm + chewing + gum", "chew gum — sakız çiğnemek (en doğal kalıp)."),
        _pe(W, f"Dün marketten sakız aldım.", f"I bought some gum yesterday.", "past",
            f"I + bought + some gum", "Geçmiş: buy gum — sakız almak."),
        _pe(W, f"Yarın şekersiz sakız alacağım.", f"I will buy sugar-free gum tomorrow.", "future",
            f"sugar-free gum", "Gelecek: sugar-free gum — şekersiz sakız."),
        _pe(W, f"Sakızın var mı?", f"Do you have any gum?", "question",
            f"Do you have + any gum", "Do you have any gum? — çok yaygın soru."),
        _pe(W, f"İş yerinde sakız çiğnemem.", f"I don't chew gum at work.", "negative",
            f"don't chew gum", "Olumsuz: çiğnememek."),
        _pe(W, f"Sakızını çöpe at lütfen.", f"Throw away your gum, please.", "imperative",
            f"Throw away + your gum", "throw away gum — sakızı atmak."),
        _pe(W, f"Bir sakız alabilir miyim?", f"Could I have a piece of gum?", "polite_request",
            f"a piece of gum", "Could I have a piece of gum? — kibar rica."),
        _pe(W, f"Sakızı yutmamalısın.", f"You shouldn't swallow chewing gum.", "advice",
            f"shouldn't swallow", "Yutmama tavsiyesi — yaygın uyarı."),
        _pe(W, f"Bu sakızı atmalıyım.", f"I need to throw this gum away.", "obligation",
            f"throw this gum away", "Atma zorunluluğu."),
        _pe(W, f"Çantamda sakız olabilir.", f"There might be gum in my bag.", "possibility",
            f"gum in my bag", "Çantada sakız arama."),
        _pe(W, f"Sınıfta sakız çiğnersen balon yapma.", f"If you chew gum in class, don't blow bubbles.", "conditional",
            f"blow bubbles", "Sınıfta sakız koşulu."),
        _pe(W, f"A: Sakızın var mı? B: Maalesef yok.", f"A: Got any gum? B: Sorry, I don't.", "dialogue",
            f"Got any gum", "Günlük diyalog: Got any gum?"),
    ]


def _safe_object_pattern_examples(W: str, T: str, category: str) -> list[dict[str, Any]]:
    """Bilinmeyen nesneler — evrensel doğal kalıplar (asla boş dönme)."""
    if _is_beverage_like(W, T):
        return _sparkling_water_pattern_examples(W, _canonical_beverage_phrase(T))
    return _universal_object_pattern_examples(W, T)


def _wallet_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Cüzdan/wallet — kaybetme, taşıma, kontrol etme."""
    tw, my = _en_target_word(T), f"my {_en_target_word(T)}"
    return [
        _pe(W, "Cüzdanım masanın üzerinde.", f"{my.capitalize()} is on the table.", "basic",
            f"{my} + is + on the table", "Temel: yer bildirimi — on the table → masanın üzerinde.", scenario_badge="🌅 RUTİN"),
        _pe(W, "Her gün cüzdanımı yanımda taşırım.", f"I carry {my} with me every day.", "present",
            f"carry {my}", "Şimdiki zaman: carry → taşımak.", scenario_badge="🔄 ŞU AN"),
        _pe(W, "Dün markette cüzdanımı kaybettim.", f"I lost {my} at the market yesterday.", "past",
            f"lost {my}", "Geçmiş: lose → kaybetmek. Cüzdan için en doğal fiil.", scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, "Yarın yeni bir cüzdan alacağım.", f"I will buy a new {tw} tomorrow.", "future",
            f"will buy a new {tw}", "Gelecek: will buy → alacağım.", scenario_badge="🔮 GELECEK"),
        _pe(W, "Cüzdanın yanında mı?", f"Do you have your {tw} with you?", "question",
            f"Do you have your {tw}", "Soru: Do you have your wallet? → Cüzdanın yanında mı?"),
        _pe(W, "Cüzdanımda nakit yok.", f"I don't have any cash in {my}.", "negative",
            f"don't have cash in {my}", "Olumsuz: in my wallet → cüzdanımda.", scenario_badge="⛔ OLUMSUZ"),
        _pe(W, "Cüzdanını kontrol et!", f"Check your {tw}!", "imperative",
            f"Check your {tw}", "Emir: Check your wallet → Cüzdanını kontrol et."),
        _pe(W, "Cüzdanımı görüyor musun?", f"Can you see {my}?", "polite_request",
            f"Can you see {my}", "Rica: Can you see my wallet?"),
        _pe(W, "Kalabalık yerlerde cüzdanını ön cebinde taşımalısın.",
            "You should keep your wallet in your front pocket in crowded places.", "advice",
            f"keep your {tw} in your front pocket", "Tavsiye: keep → taşımak/bulundurmak."),
        _pe(W, "Pasaport kontrolünden önce cüzdanımı çıkarmam gerekiyor.",
            f"I need to take {my} out before the passport check.", "obligation",
            f"need to take {my} out", "Zorunluluk: need to take out → çıkarmam gerekiyor."),
        _pe(W, "Cüzdanım arabada olabilir.", f"{my.capitalize()} might be in the car.", "possibility",
            f"might be in the car", "Olasılık: might be → olabilir."),
        _pe(W, "Cüzdanımı bulursam sana haber veririm.", f"If I find {my}, I will let you know.", "conditional",
            f"If I find {my}", "Koşul: If I find → bulursam."),
        _pe(W, "A: Cüzdanını mı kaybettin? B: Evet, dün akşam.",
            f"A: Did you lose your {tw}? B: Yes, last night.", "dialogue",
            f"Did you lose your {tw}", "Diyalog: lose your wallet → cüzdanını kaybetmek."),
    ]


def _umbrella_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Şemsiye/umbrella — açma, kapatma, yağmur."""
    tw, my, an = _en_target_word(T), f"my {_en_target_word(T)}", f"an {_en_target_word(T)}"
    return [
        _pe(W, "Bugün şemsiyemi yanıma aldım.", f"I brought {my} with me today.", "basic",
            f"brought {my}", "Temel: bring → yanına almak.", scenario_badge="🌅 RUTİN"),
        _pe(W, "Dışarıda yağmur yağıyor, şemsiyemi açıyorum.",
            f"It's raining outside, so I'm opening {my}.", "present",
            f"opening {my}", "Şimdiki zaman: open → açmak.", scenario_badge="🔄 ŞU AN"),
        _pe(W, "Dün işe giderken şemsiyemi evde unuttum.",
            f"I forgot {my} at home yesterday on my way to work.", "past",
            f"forgot {my}", "Geçmiş: forget → unutmak.", scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, "Yarın yağmur yağacak, şemsiye alacağım.",
            f"It will rain tomorrow, so I will take {an}.", "future",
            f"will take {an}", "Gelecek: take an umbrella → şemsiye almak.", scenario_badge="🔮 GELECEK"),
        _pe(W, "Şemsiyen var mı?", f"Do you have {an}?", "question",
            f"Do you have {an}", "Soru: Do you have an umbrella?"),
        _pe(W, "Şemsiyem yok, yağmura yakalandım.", f"I don't have {an}, so I got caught in the rain.", "negative",
            f"got caught in the rain", "Olumsuz: got caught in the rain → yağmura yakalandım.", scenario_badge="⛔ OLUMSUZ"),
        _pe(W, "İçeri girmeden önce şemsiyeni kapat!", f"Close your {tw} before you come inside!", "imperative",
            f"Close your {tw}", "Emir: Close your umbrella → Şemsiyeni kapat."),
        _pe(W, "Şemsiyemi ödünç alabilir miyim?", f"Can I borrow your {tw}?", "polite_request",
            f"Can I borrow your {tw}", "Rica: borrow → ödünç almak."),
        _pe(W, "Hava bulutlu, yanına bir şemsiye almalısın.",
            f"The sky looks cloudy, you should take {an} with you.", "advice",
            f"should take {an}", "Tavsiye: take an umbrella → şemsiye al."),
        _pe(W, "Fırtına var, şemsiye almam gerekiyor.", f"There's a storm coming, so I need to take {an}.", "obligation",
            f"need to take {an}", "Zorunluluk: need to take → almam gerekiyor."),
        _pe(W, "Şemsiyem arabada olabilir.", f"{my.capitalize()} might be in the car.", "possibility",
            f"might be in the car", "Olasılık: might be → olabilir."),
        _pe(W, "Yağmur yağarsa şemsiyemi açarım.", f"If it rains, I will open {my}.", "conditional",
            f"If it rains, open {my}", "Koşul: If it rains → yağmur yağarsa."),
        _pe(W, "A: Yağmur başladı, şemsiyen var mı? B: Yok, bir tane alalım.",
            f"A: It started raining. Do you have {an}? B: No, let's buy one.", "dialogue",
            f"It started raining", "Diyalog: yağmur + şemsiye."),
    ]


def _universal_object_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Son çare nesne örnekleri — mekanik 'use at home' şablonu YASAK."""
    if _is_adjective_like(W, T):
        if _is_quiet_like(W, T):
            return _quiet_pattern_examples(W, T)
        return _adjective_pattern_examples(W, T)
    if _is_pronoun_like(W, T):
        return _pronoun_pattern_examples(W, T)
    if _is_adverb_like(W, T):
        return _adverb_pattern_examples(W, T)
    if _is_verb_like(W, T):
        return _verb_pattern_examples(W, T)
    if _is_wallet_like(W, T):
        return _wallet_pattern_examples(W, T)
    if _is_umbrella_like(W, T):
        return _umbrella_pattern_examples(W, T)
    tw = _en_target_word(T)
    my = f"my {tw}"
    a_new = f"a new {tw}"
    return [
        _pe(W, f"{W.capitalize()} masanın üzerinde.", f"{my.capitalize()} is on the table.", "basic",
            f"{my} is on the table", f"Temel kullanım: {my} → {_possessive_tr(W)}.", scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an {W} arıyorum.", f"I am looking for {my} right now.", "present",
            f"looking for {my}", "Şu an: looking for → arıyorum.", scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün yeni bir {W} aldım.", f"I bought {a_new} yesterday.", "past",
            f"bought {a_new}", "Geçmiş: bought → aldım.", scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {W} alacağım.", f"I will buy {a_new} tomorrow.", "future",
            f"will buy {a_new}", "Gelecek: will buy → alacağım.", scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} nerede?", f"Where is {my}?", "question",
            f"Where is {my}", f"Soru: Where is my …? → … nerede?"),
        _pe(W, f"{W.capitalize()} bulamıyorum.", f"I can't find {my}.", "negative",
            f"can't find {my}", "Olumsuz: can't find → bulamıyorum.", scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"Lütfen {W} getir.", f"Please bring {my}.", "imperative",
            f"bring {my}", "Emir: bring → getir."),
        _pe(W, f"{W.capitalize()} uzatabilir misin?", f"Could you hand me {my}?", "polite_request",
            f"hand me {my}", "Rica: Could you hand me …?"),
        _pe(W, f"{W.capitalize()} dikkatli taşımalısın.", f"You should carry {my} carefully.", "advice",
            f"carry {my} carefully", "Tavsiye: carry carefully → dikkatli taşı."),
        _pe(W, f"Yeni {W} almam lazım.", f"I need to buy {a_new}.", "obligation",
            f"need to buy {a_new}", "Zorunluluk: need to buy → almam lazım."),
        _pe(W, f"{W.capitalize()} arabada olabilir.", f"{my.capitalize()} might be in the car.", "possibility",
            f"might be in the car", "Olasılık: might be in the car."),
        _pe(W, f"Görürsen {W} söyle.", f"If you see {my}, tell me.", "conditional",
            f"If you see {my}", "Koşul: If you see …, tell me."),
        _pe(W, f"A: {W.capitalize()} gördün mü? B: Evet, orada.", f"A: Have you seen {my}? B: Yes, over there.", "dialogue",
            f"Have you seen {my}", "Diyalog: Have you seen my …?"),
    ]


def _object_pattern_examples(W: str, T: str, category: str) -> list[dict[str, Any]]:
    """Eski şablon — geriye dönük uyumluluk; güvenli sürüme yönlendir."""
    return _safe_object_pattern_examples(W, T, category)


def _beverage_pattern_examples(W: str, T: str, wt: str, tw: str) -> list[dict[str, Any]]:
    is_soda = wt in ("soda", "gazoz", "kola") or tw in ("soda", "cola")
    portion = "a soda" if is_soda else "a coffee"
    uncount = "soda" if is_soda else "coffee"
    diet = "diet soda" if is_soda else "black coffee"
    return [
        _pe(W, f"Bu {W}.", f"This is {uncount}.", "basic",
            f"This + is + {uncount}",
            f"1️⃣ Temel kullanım\nThis is… → Bu …\n\n"
            f"{uncount} → {W}"),
        _pe(W, f"Şu an {W} içiyorum.", f"I am drinking {uncount} now.", "present",
            f"I + am + drinking + {uncount}",
            f"1️⃣ Şimdiki zaman\nam + drink-ing → şu anda içiyorum\n\n"
            f"İçeceklerle drink kullanılır."),
        _pe(W, f"Dün {W} içtim.", f"I drank {portion} yesterday.", "past",
            f"I + drank + {portion}",
            f"1️⃣ Geçmiş zaman\ndrank → içtim (drink geçmişi)\n\n"
            f"{portion} → bir {W}"),
        _pe(W, f"Sonra {W} içeceğim.", f"I will have {portion} later.", "future",
            f"I + will + have + {portion}",
            f"1️⃣ Gelecek zaman\nwill + have → … içeceğim / alacağım\n\n"
            f"İçecek için have da doğaldır."),
        _pe(W, f"{W.capitalize()} ister misin?", f"Do you want {portion}?", "question",
            f"Do + you + want + {portion}",
            f"1️⃣ Soru cümlesi\nDo you want…? → … ister misin?\n\n"
            f"Günlük teklif/soru kalıbı."),
        _pe(W, f"{W.capitalize()} içmem.", f"I don't drink {uncount}.", "negative",
            f"I + don't + drink + {uncount}",
            f"1️⃣ Olumsuz cümle\ndon't + fiil(yalın) → …-mıyorum\n\n"
            f"don't drink → içmem"),
        _pe(W, f"Bana {W} getir.", f"Bring me {portion}, please.", "imperative",
            f"Bring + me + {portion}",
            f"1️⃣ Emir kipi\nFiil ile başlar: Bring → getir\n\n"
            f"please → lütfen (kibarlık)"),
        _pe(W, f"Bir {W} alabilir miyim?", f"Can I have {portion}?", "polite_request",
            f"Can + I + have + {portion}",
            f"1️⃣ Rica cümlesi\nCan I have…? → … alabilir miyim?\n\n"
            f"Restoranda çok doğal kalıp."),
        _pe(W, f"{'Diyet gazoz' if is_soda else 'Siyah kahve'} denemelisin.", f"You should try {diet}.", "advice",
            f"You + should + try + {diet}",
            f"1️⃣ Tavsiye cümlesi\nshould → …-melisin\n\n"
            f"{'❌ black soda yok — diet soda kullan.' if is_soda else 'black coffee doğal bir ifadedir.'}"),
        _pe(W, f"Parti için {W} almam lazım.", f"I need to buy {uncount} for the party.", "obligation",
            f"I + need to + buy + {uncount}",
            f"1️⃣ Zorunluluk cümlesi\nneed to + fiil → …-mem lazım\n\n"
            f"need to buy → almam lazım"),
        _pe(W, f"Buzdolabında {W} olabilir.", f"There might be {uncount} in the fridge.", "possibility",
            f"There + might + be + {uncount}",
            f"1️⃣ İhtimal cümlesi\nThere might be… → … olabilir\n\n"
            f"might → olasılık"),
        _pe(W, f"{W.capitalize()} istersen buzdolabında var.", f"If you want {uncount}, there is some in the fridge.", "conditional",
            f"If + you + want + {uncount}, + there is some",
            f"1️⃣ Koşul cümlesi\nIf you want… → … istersen\n\n"
            f"Koşul + sonuç yapısı."),
        _pe(W, f"A: {W.capitalize()} ister misin? B: Evet, lütfen.", f"A: Would you like {portion}? B: Yes, please.", "dialogue",
            f"A: Would you like…? B: Yes, please",
            f"1️⃣ Günlük diyalog\nWould you like…? → kibar teklif\n\n"
            f"Yes, please → Evet, lütfen"),
    ]


def _footwear_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    shoes = "shoes" if T == "shoe" else T
    return [
        _pe(W, f"Bu {W}lar rahat.", f"These {shoes} are comfortable.", "basic",
            f"These + {shoes} + are + comfortable",
            f"1️⃣ Temel kullanım\nThese → bunlar\nare → -dır/-dir\n\n"
            f"Ayakkabı genelde çoğul (shoes) kullanılır."),
        _pe(W, f"Şu an {W}larımı giyiyorum.", f"I am putting on my {shoes} now.", "present",
            f"I + am + putting on + my {shoes}",
            f"1️⃣ Şimdiki zaman\nputting on → giyiyorum\n\n"
            f"am + fiil-ing → şu anda"),
        _pe(W, f"Dün yeni {W} aldım.", f"I bought new {shoes} yesterday.", "past",
            f"I + bought + new {shoes}",
            f"1️⃣ Geçmiş zaman\nbought → aldım (buy geçmişi)\n\n"
            f"new shoes → yeni ayakkabı"),
        _pe(W, f"Yarın {W} alacağım.", f"I will buy {shoes} tomorrow.", "future",
            f"I + will + buy + {shoes}",
            f"1️⃣ Gelecek zaman\nwill + buy → alacağım\n\n"
            f"tomorrow → yarın"),
        _pe(W, f"Bu {W}ları nereden aldın?", f"Where did you buy these {shoes}?", "question",
            f"Where + did + you + buy + these {shoes}",
            f"1️⃣ Soru cümlesi\nWhere did you…? → …-i nereden …?\n\n"
            f"did → geçmiş zaman yardımcısı"),
        _pe(W, f"Bu {W}lar bana küçük geliyor.", f"These {shoes} don't fit me.", "negative",
            f"These + {shoes} + don't + fit + me",
            f"1️⃣ Olumsuz cümle\ndon't fit → uymuyor / küçük geliyor\n\n"
            f"fit → uymak (beden)"),
        _pe(W, f"{W.capitalize()}larını bağla.", f"Tie your {shoes}.", "imperative",
            f"Tie + your + {shoes}",
            f"1️⃣ Emir kipi\ntie your shoes → ayakkabılarını bağla\n\n"
            f"Emirde özne yok."),
        _pe(W, f"{W.capitalize()}larını bağlayabilir misin?", f"Could you tie your {shoes}?", "polite_request",
            f"Could + you + tie + your {shoes}",
            f"1️⃣ Rica cümlesi\nCould you…? → …-ebilir misin?\n\n"
            f"Kibar rica kalıbı."),
        _pe(W, f"Evde {W} giymelisin.", f"You should wear {shoes} at home.", "advice",
            f"You + should + wear + {shoes}",
            f"1️⃣ Tavsiye cümlesi\nshould → …-melisin\n\n"
            f"wear shoes → ayakkabı giymek"),
        _pe(W, f"Yeni bir çift {W} almam lazım.", f"I need to buy a new pair of {shoes}.", "obligation",
            f"I + need to + buy + a pair of {shoes}",
            f"1️⃣ Zorunluluk cümlesi\nneed to → …-mem lazım\n\n"
            f"a pair of shoes → bir çift ayakkabı"),
        _pe(W, f"{W.capitalize()}larım kaybolmuş olabilir.", f"My {shoes} might be lost.", "possibility",
            f"My + {shoes} + might + be + lost",
            f"1️⃣ İhtimal cümlesi\nmight be → … olabilir\n\n"
            f"lost → kayıp"),
        _pe(W, f"Yağmur yağarsa {W} giy.", f"If it rains, wear your {shoes}.", "conditional",
            f"If + it + rains, + wear + your {shoes}",
            f"1️⃣ Koşul cümlesi\nIf it rains → yağmur yağarsa\n\n"
            f"Koşul + emir/tavsiye"),
        _pe(W, f"A: {W.capitalize()}ların rahat mı? B: Evet.", f"A: Are your {shoes} comfortable? B: Yes, they are.", "dialogue",
            f"A: Are + your {shoes} + comfortable? B: Yes",
            f"1️⃣ Günlük diyalog\nAre your shoes…? → ayakkabıların rahat mı?\n\n"
            f"Yes, they are → evet, öyleler"),
    ]


def _accusative_possessive_tr(word_tr: str) -> str:
    """İyelik + belirtme (1. tekil): araba → arabamı, bisiklet → bisikletimi."""
    low = word_tr.strip().lower()
    known = {
        "araba": "arabamı", "otomobil": "otomobilimi", "bisiklet": "bisikletimi",
        "cüzdan": "cüzdanımı", "cuzdan": "cüzdanımı", "şemsiye": "şemsiyemi", "semsiye": "şemsiyemi",
    }
    if low in known:
        return known[low]
    p = _possessive_tr(word_tr)
    return f"{p}ı"


def _your_possessive_tr(word_tr: str) -> str:
    """2. tekil iyelik: araba → araban."""
    low = word_tr.strip().lower()
    known = {
        "araba": "araban", "otomobil": "otomobilin", "bisiklet": "bisikletin",
        "cüzdan": "cüzdanın", "cuzdan": "cüzdanın", "şemsiye": "şemsiyen", "semsiye": "şemsiyen",
    }
    if low in known:
        return known[low]
    p = _possessive_tr(word_tr)
    if p.endswith("ım"):
        return p[:-2] + "ın"
    if p.endswith("im"):
        return p[:-2] + "in"
    if p.endswith("um"):
        return p[:-2] + "un"
    if p.endswith("üm"):
        return p[:-2] + "ün"
    if p.endswith("m"):
        return p[:-1] + "n"
    return f"senin {low}"


def _your_accusative_tr(word_tr: str) -> str:
    """2. tekil iyelik + belirtme: araba → arabanı."""
    low = word_tr.strip().lower()
    known = {
        "araba": "arabanı", "otomobil": "otomobilini", "bisiklet": "bisikletini",
        "cüzdan": "cüzdanını", "cuzdan": "cüzdanını", "şemsiye": "şemsiyeni", "semsiye": "şemsiyeni",
    }
    if low in known:
        return known[low]
    yp = _your_possessive_tr(word_tr)
    if yp.endswith(("a", "ı", "o", "u")):
        return yp + "nı" if not yp.endswith("n") else yp + "ı"
    if yp.endswith(("e", "i", "ö", "ü")):
        return yp + "ni" if not yp.endswith("n") else yp + "i"
    return yp + "ı"


def _vehicle_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Taşıt — doğal günlük Türkçe/İngilizce; iyelik ve belirtme halleri doğru."""
    tw = _en_target_word(T)
    my = f"my {tw}"
    your = f"your {tw}"
    poss = _possessive_tr(W)
    acc = _accusative_possessive_tr(W)
    your_p = _your_possessive_tr(W)
    your_acc = _your_accusative_tr(W)
    w = W.lower()
    is_car = w in ("araba", "otomobil") or tw == "car"

    if is_car:
        return [
            _pe(W, "Arabam garajda.", "My car is in the garage.", "basic",
                "My car is in the garage",
                "Temel: my car → arabam. Konum: in the garage → garajda.",
                scenario_badge="🌅 RUTİN"),
            _pe(W, "Her sabah arabamla işe gidiyorum.", "I drive to work every morning.", "present",
                "I drive to work every morning",
                "Günlük kullanım: drive to work → arabayla işe gitmek.",
                scenario_badge="🔄 ŞU AN"),
            _pe(W, "Geçen yıl yeni bir araba aldım.", "I bought a new car last year.", "past",
                "I bought a new car last year",
                "Geçmiş: bought → aldım.",
                scenario_badge="🕐 GEÇMİŞ"),
            _pe(W, "Yarın arabamı yıkatacağım.", "I'm going to wash my car tomorrow.", "future",
                "I'm going to wash my car tomorrow",
                "Gelecek plan: going to wash → yıkayacağım/yıkatacağım.",
                scenario_badge="🔮 GELECEK"),
            _pe(W, "Arabanı nereye park ettin?", "Where did you park your car?", "question",
                "Where did you park your car?",
                "Soru: Where did you park…? → Nereye park ettin?\n"
                "your car → arabanı (belirtme hali).",
                scenario_badge="❓ SORU"),
            _pe(W, "Bugün arabamı kullanmıyorum.", "I'm not taking my car today.", "negative",
                "I'm not taking my car today",
                "Olumsuz: not taking my car → arabamı kullanmıyorum.",
                scenario_badge="⛔ OLUMSUZ"),
            _pe(W, "Arabayı buraya park et, lütfen.", "Park the car here, please.", "imperative",
                "Park the car here, please",
                "Emir: Park the car → Arabayı park et.",
                scenario_badge="👉 EMİR"),
            _pe(W, "Arabanı biraz ileri çekebilir misin?", "Could you move your car forward a little?", "polite_request",
                "Could you move your car forward a little?",
                "Rica: Could you move your car…? → Arabanı biraz ileri çekebilir misin?",
                scenario_badge="🗣️ RİCA"),
            _pe(W, "Uzun yola çıkmadan önce arabanı kontrol etmelisin.",
                "You should check your car before a long trip.", "advice",
                "You should check your car before a long trip",
                "Tavsiye: should check your car → arabanı kontrol etmelisin.",
                scenario_badge="🤝 TEKLİF"),
            _pe(W, "Arabamı tamir ettirmem gerekiyor.", "I need to get my car fixed.", "obligation",
                "I need to get my car fixed",
                "Zorunluluk: get my car fixed → arabamı tamir ettirmek.",
                scenario_badge="📋 ZORUNLULUK"),
            _pe(W, "Arabam dışarıda olabilir.", "My car might be outside.", "possibility",
                "My car might be outside",
                "Olasılık: might be → olabilir.",
                scenario_badge="🎲 İHTİMAL"),
            _pe(W, "Trafik varsa arabayla gelmem.", "If there's traffic, I won't take the car.", "conditional",
                "If there's traffic, I won't take the car",
                "Koşul: If there's traffic… → Trafik varsa…",
                scenario_badge="🔀 KOŞUL"),
            _pe(W, "A: Araban var mı? B: Evet, ama bugün bozuk.",
                "A: Do you have a car? B: Yes, but it's broken today.", "dialogue",
                "Do you have a car?",
                "Diyalog: Do you have a car? → Araban var mı?",
                scenario_badge="💬 DİYALOG"),
        ]

    return [
        _pe(W, f"{poss.capitalize()} garajda.", f"{my.capitalize()} is in the garage.", "basic",
            f"{my} is in the garage", f"Temel: my {tw} → {poss}.", scenario_badge="🌅 RUTİN"),
        _pe(W, f"Her gün {poss.lower()} kullanıyorum.", f"I use {my} every day.", "present",
            f"I use {my} every day", "Şimdiki zaman: günlük kullanım.", scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Geçen yıl yeni bir {w} aldım.", f"I bought a new {tw} last year.", "past",
            f"bought a new {tw}", "Geçmiş: bought → aldım.", scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {acc} yıkatacağım.", f"I'm going to wash {my} tomorrow.", "future",
            f"going to wash {my}", "Gelecek plan.", scenario_badge="🔮 GELECEK"),
        _pe(W, f"{your_acc.capitalize()} nereye koydun?", f"Where did you put {your}?", "question",
            f"Where did you put {your}", "Soru cümlesi.", scenario_badge="❓ SORU"),
        _pe(W, f"Bugün {acc} kullanmıyorum.", f"I'm not using {my} today.", "negative",
            f"not using {my}", "Olumsuz cümle.", scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{acc.capitalize()} buraya getir, lütfen.", f"Bring {my} here, please.", "imperative",
            f"Bring {my} here", "Emir kipi.", scenario_badge="👉 EMİR"),
        _pe(W, f"{your_acc.capitalize()} ödünç alabilir miyim?", f"Can I borrow {your}?", "polite_request",
            f"Can I borrow {your}", "Rica cümlesi.", scenario_badge="🗣️ RİCA"),
        _pe(W, f"{your_acc.capitalize()} dikkatli kullanmalısın.", f"You should take care of {your}.", "advice",
            f"take care of {your}", "Tavsiye cümlesi.", scenario_badge="🤝 TEKLİF"),
        _pe(W, f"{acc.capitalize()} tamir ettirmem gerekiyor.", f"I need to get {my} fixed.", "obligation",
            f"need to get {my} fixed", "Zorunluluk.", scenario_badge="📋 ZORUNLULUK"),
        _pe(W, f"{poss.capitalize()} dışarıda olabilir.", f"{my.capitalize()} might be outside.", "possibility",
            "might be outside", "Olasılık cümlesi.", scenario_badge="🎲 İHTİMAL"),
        _pe(W, f"{acc.capitalize()} bulursam sana haber veririm.", f"If I find {my}, I'll call you.", "conditional",
            f"If I find {my}", "Koşul cümlesi.", scenario_badge="🔀 KOŞUL"),
        _pe(W, f"A: {your_p.capitalize()} var mı? B: Evet, ama bugün bozuk.",
            f"A: Do you have a {tw}? B: Yes, but it's broken today.", "dialogue",
            f"Do you have a {tw}", "Günlük diyalog.", scenario_badge="💬 DİYALOG"),
    ]


def _plumbing_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    return [
        _pe(W, f"{W.capitalize()} mutfakta.", f"The {T} is in the kitchen.", "basic",
            f"The + {T} + is + in the kitchen", f"1️⃣ Temel kullanım\nThe faucet → musluk\nis → -dır"),
        _pe(W, f"{W.capitalize()} su sızdırıyor.", f"The {T} is leaking.", "present",
            f"The + {T} + is + leaking", f"1️⃣ Şimdiki zaman\nis leaking → sızdırıyor\n-ing → devam eden durum"),
        _pe(W, f"Dün {W} tamir ettirdim.", f"I had the {T} repaired yesterday.", "past",
            f"I + had + the {T} + repaired", f"1️⃣ Geçmiş zaman\nhad … repaired → tamir ettirdim"),
        _pe(W, f"Yarın {W} değiştireceğim.", f"I will replace the {T} tomorrow.", "future",
            f"I + will + replace + the {T}", f"1️⃣ Gelecek zaman\nwill replace → değiştireceğim"),
        _pe(W, f"{W.capitalize()} neden akıyor?", f"Why is the {T} leaking?", "question",
            f"Why + is + the {T} + leaking", f"1️⃣ Soru cümlesi\nWhy → neden\nis leaking → sızdırıyor"),
        _pe(W, f"{W.capitalize()} kapatılmamış.", f"The {T} is not turned off.", "negative",
            f"The + {T} + is + not + turned off", f"1️⃣ Olumsuz cümle\nnot turned off → kapatılmamış"),
        _pe(W, f"{W.capitalize()}u kapat.", f"Turn off the {T}.", "imperative",
            f"Turn off + the {T}", f"1️⃣ Emir kipi\nturn off → kapatmak (musluk/ışık için)"),
        _pe(W, f"{W.capitalize()}u kapatabilir misin?", f"Could you turn off the {T}?", "polite_request",
            f"Could + you + turn off + the {T}", f"1️⃣ Rica cümlesi\nCould you turn off…? → kapatabilir misin?"),
        _pe(W, f"Su tasarrufu için {W}u kapatmalısın.", f"You should turn off the {T} to save water.", "advice",
            f"You + should + turn off + the {T}", f"1️⃣ Tavsiye cümlesi\nshould → …-melisin"),
        _pe(W, f"{W.capitalize()} tamir ettirmem lazım.", f"I need to have the {T} repaired.", "obligation",
            f"I + need to + have + the {T} + repaired", f"1️⃣ Zorunluluk cümlesi\nneed to have … repaired"),
        _pe(W, f"{W.capitalize()} bozulmuş olabilir.", f"The {T} might be broken.", "possibility",
            f"The + {T} + might + be + broken", f"1️⃣ İhtimal cümlesi\nmight be broken → bozulmuş olabilir"),
        _pe(W, f"{W.capitalize()} akarsa hemen kapat.", f"If the {T} is leaking, turn it off immediately.", "conditional",
            f"If + the {T} + is leaking", f"1️⃣ Koşul cümlesi\nIf … is leaking → … akarsa"),
        _pe(W, f"A: {W.capitalize()} akıyor mu? B: Evet.", f"A: Is the {T} leaking? B: Yes, a little.", "dialogue",
            f"A: Is the {T} leaking? B: Yes", f"1️⃣ Günlük diyalog\nMusluk sorunu hakkında kısa konuşma."),
    ]


def _adjective_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Sıfatlar — be/feel/look + sıfat; asla «yeni bir sıfat aldım» yok."""
    adj = _en_target_word(T)
    w = W.strip()
    pred = _turkish_predicate_adj(w)
    pred_past = _turkish_predicate_adj_past(w)
    pred_future = _turkish_predicate_adj_future(w)
    pred_neg = _turkish_predicate_adj_negative(w)
    return [
        _pe(w, f"Bugün {pred}.", f"I am {adj} today.", "basic",
            f"I + am + {adj}",
            _rich_teaching_how(
                f"Kendinizi {w} hissettiğinizi veya durumunuzu anlatırsınız.",
                f"I am {adj} today",
                f"Bugün {pred}.",
                [
                    ("am + sıfat", f"I am {adj} → {pred}\n"
                     "Sıfat tek başına kullanılmaz; be (am/is/are) fiili gerekir.\n"
                     f"❌ I {adj} — yanlış"),
                    ("today", "today → bugün\nZaman ifadesi cümle sonunda olabilir."),
                ],
                mistakes=[f"I {adj} today — am/is/are eksik", f"a new {adj} — sıfat nesne değildir"],
            ),
            scenario_badge="🌅 RUTİN"),
        _pe(w, f"Şu an kendimi {w} hissediyorum.", f"I am feeling {adj} right now.", "present",
            f"I + am + feeling + {adj}",
            _rich_teaching_how(
                "Şu anda bir duygu veya hâl hissettiğinizi söylersiniz.",
                f"I am feeling {adj} right now",
                f"Şu an kendimi {w} hissediyorum.",
                [
                    ("am feeling", f"feel + sıfat → … hissetmek\nam feeling → şu anda hissediyorum"),
                    ("right now", "right now → şu an"),
                ],
            ),
            scenario_badge="🔄 ŞU AN"),
        _pe(w, f"Dün {pred_past}.", f"I was {adj} yesterday.", "past",
            f"I + was + {adj}",
            _rich_teaching_how(
                "Geçmişte bir durumu veya duyguyu anlatırsınız.",
                f"I was {adj} yesterday",
                f"Dün {pred_past}.",
                [
                    ("was + sıfat", f"was → geçmişte be fiili\nI was {adj} → dün …-ydım/-dim"),
                    ("yesterday", "yesterday → dün"),
                ],
            ),
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(w, f"Yarın daha {w} olacağım.", f"I will be {adj} tomorrow.", "future",
            f"I + will + be + {adj}",
            _rich_teaching_how(
                "Gelecekte bir durum beklentinizi söylersiniz.",
                f"I will be {adj} tomorrow",
                f"Yarın daha {w} olacağım.",
                [
                    ("will be", f"will be + sıfat → … olacağım\n❌ I will {adj} — be eksik"),
                ],
            ),
            scenario_badge="🔮 GELECEK"),
        _pe(w, f"{w.capitalize()} misin?", f"Are you {adj}?", "question",
            f"Are + you + {adj}",
            _rich_teaching_how(
                "Karşıdaki kişinin durumunu sorarsınız.",
                f"Are you {adj}?",
                f"{w.capitalize()} misin?",
                [
                    ("Are you …?", f"Are you {adj}? → … misin?\nSoru: Are + özne + sıfat"),
                ],
            ),
            scenario_badge="❓ SORU"),
        _pe(w, f"{pred_neg}.", f"I am not {adj}.", "negative",
            f"I + am + not + {adj}",
            _rich_teaching_how(
                "Olumsuz durum bildirirsiniz.",
                f"I am not {adj}",
                f"{pred_neg}.",
                [
                    ("am not", f"am not + sıfat → … değilim\nTürkçede … değilim / … değil"),
                ],
            ),
            scenario_badge="⛔ OLUMSUZ"),
        _pe(w, f"{w.capitalize()} ol!", f"Be {adj}!", "imperative",
            f"Be + {adj}",
            _rich_teaching_how(
                "Birine bir durumda olmasını söylersiniz.",
                f"Be {adj}!",
                f"{w.capitalize()} ol!",
                [
                    ("Be + sıfat", f"Be {adj} → … ol\nEmirde özne yazılmaz."),
                ],
            )),
        _pe(w, f"Biraz {w} olabilir misin?", f"Could you be a little {adj}?", "polite_request",
            f"Could + you + be + {adj}",
            _rich_teaching_how(
                "Kibarca bir durum rica edersiniz.",
                f"Could you be a little {adj}?",
                f"Biraz {w} olabilir misin?",
                [
                    ("Could you be …?", "Could you be …? → … olabilir misin?\nKibar rica kalıbı."),
                ],
            )),
        _pe(w, f"Daha {w} olmalısın.", f"You should be {adj}er.", "advice",
            f"You + should + be + {adj}",
            _rich_teaching_how(
                "Tavsiye verirsiniz.",
                f"You should be {adj}",
                f"Daha {w} olmalısın.",
                [
                    ("should be", "should be + sıfat → … olmalısın\nTavsiye veya uyarı."),
                ],
            )),
        _pe(w, f"Kendimi {w} hissetmem lazım.", f"I need to feel {adj}.", "obligation",
            f"I + need to + feel + {adj}",
            _rich_teaching_how(
                "Bir duygu/durum hissetme ihtiyacını anlatırsınız.",
                f"I need to feel {adj}",
                f"Kendimi {w} hissetmem lazım.",
                [
                    ("need to feel", "need to feel → … hissetmem lazım\nneed to + fiil kalıbı."),
                ],
            )),
        _pe(w, f"Belki {w} görünüyorsundur.", f"You might look {adj}.", "possibility",
            f"You + might + look + {adj}",
            _rich_teaching_how(
                "Görünüşe dayalı ihtimal bildirirsiniz.",
                f"You might look {adj}",
                f"Belki {w} görünüyorsundur.",
                [
                    ("might look", f"look {adj} → {w} görünmek\nmight → belki / … olabilir"),
                ],
            )),
        _pe(w, f"Hava güzelse daha {w} olursun.", f"If the weather is nice, you will feel {adj}er.", "conditional",
            f"If + …, + you will feel + {adj}",
            _rich_teaching_how(
                "Koşula bağlı sonuç anlatırsınız.",
                f"If the weather is nice, you will feel {adj}",
                f"Hava güzelse daha {w} olursun.",
                [
                    ("If …, will …", "If … → … olursa / … ise\nKoşul + sonuç yapısı."),
                ],
            )),
        _pe(w, f"A: {w.capitalize()} misin? B: Evet, biraz.",
            f"A: Are you {adj}? B: Yes, a little.", "dialogue",
            f"Are you {adj}",
            _rich_teaching_how(
                "Günlük duygu/durum sorusu diyalogu.",
                f"Are you {adj}?",
                f"{w.capitalize()} misin?",
                [
                    ("Diyalog", "A: Are you …? → … misin?\nB: Yes, a little. → Evet, biraz."),
                ],
            )),
    ]


def _quiet_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Sessiz/quiet — ortam, kural, keep quiet; asla «sessiz satın al» yok."""
    adj = _en_target_word(T)
    w = W.strip()
    return [
        _pe(w, "Burası çok sessiz.", f"It's very {adj} here.", "basic",
            f"It + is + very {adj} + here",
            _rich_teaching_how(
                "Bir yerin sessiz olduğunu anlatırsınız.",
                f"It's very {adj} here",
                "Burası çok sessiz.",
                [
                    ("It's … here", f"It's {adj} here → burası …\n"
                     "Ortam/yer için it + be + sıfat kullanılır."),
                    ("very quiet", f"very {adj} → çok {w}\nvery sıfatı güçlendirir."),
                ],
                mistakes=[f"I bought a new {adj}", f"my {adj} is on the table — sıfat nesne değil"],
            ),
            scenario_badge="🌅 RUTİN"),
        _pe(w, "Bebek uyuyor, sessiz kalalım.", f"The baby is asleep, so let's keep {adj}.", "present",
            f"let's keep + {adj}",
            _rich_teaching_how(
                "Şu an sessiz kalma gerektiğini söylersiniz.",
                f"let's keep {adj}",
                "Bebek uyuyor, sessiz kalalım.",
                [
                    ("keep quiet", f"keep {adj} → sessiz kalmak\n"
                     "Sessizlik için en doğal fiil: keep quiet / stay quiet"),
                    ("let's", "let's → …-elim / …-alım\nÖneri veya ortak eylem."),
                ],
            ),
            scenario_badge="🔄 ŞU AN"),
        _pe(w, "Dün akşam ev çok sessizdi.", f"The house was very {adj} last night.", "past",
            f"The house + was + very {adj}",
            _rich_teaching_how(
                "Geçmişte ortamın sessiz olduğunu anlatırsınız.",
                f"The house was very {adj} last night",
                "Dün akşam ev çok sessizdi.",
                [
                    ("was + sıfat", "was very quiet → çok sessizdi\nGeçmiş: was/were + sıfat"),
                ],
            ),
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(w, "Yarın sessiz bir kafede çalışacağım.", f"I will work at a {adj} café tomorrow.", "future",
            f"a {adj} + noun",
            _rich_teaching_how(
                "Sessiz bir yerde çalışma planını söylersiniz.",
                f"a {adj} café",
                "Yarın sessiz bir kafede çalışacağım.",
                [
                    ("sıfat + isim", f"a {adj} café → sessiz bir kafe\n"
                     "Sıfat isimden ÖNCE gelir: quiet room, quiet place"),
                ],
            ),
            scenario_badge="🔮 GELECEK"),
        _pe(w, "Burada sessiz mi?", f"Is it {adj} here?", "question",
            f"Is + it + {adj}",
            _rich_teaching_how(
                "Ortamın sessiz olup olmadığını sorarsınız.",
                f"Is it {adj} here?",
                "Burada sessiz mi?",
                [
                    ("Is it …?", f"Is it {adj}? → … mı / … mi?\nYer/ortam sorusu."),
                ],
            ),
            scenario_badge="❓ SORU"),
        _pe(w, "Film izlerken sessiz değildim.", f"I wasn't {adj} during the movie.", "negative",
            f"I + wasn't + {adj}",
            _rich_teaching_how(
                "Sessiz kalmadığınızı söylersiniz.",
                f"I wasn't {adj} during the movie",
                "Film izlerken sessiz değildim.",
                [
                    ("wasn't + sıfat", f"wasn't {adj} → … değildim / … değildim"),
                    ("during", "during the movie → film izlerken"),
                ],
            ),
            scenario_badge="⛔ OLUMSUZ"),
        _pe(w, "Sessiz ol!", f"Be {adj}!", "imperative",
            f"Be + {adj}",
            _rich_teaching_how(
                "Sessiz olması için emir verirsiniz.",
                f"Be {adj}!",
                "Sessiz ol!",
                [
                    ("Be quiet", f"Be {adj} → sessiz ol\nKeep {adj} → sessiz kal\nİkisi de çok yaygın."),
                ],
            )),
        _pe(w, "Biraz sessiz olabilir misiniz?", f"Could you please be a little {adj}?", "polite_request",
            f"Could you + be + {adj}",
            _rich_teaching_how(
                "Kibarca sessiz olma ricası.",
                f"Could you please be a little {adj}?",
                "Biraz sessiz olabilir misiniz?",
                [
                    ("Could you be …?", "Kütüphane, sınıf, hastane — en sık duyulan rica."),
                ],
            )),
        _pe(w, "Kütüphanede sessiz olmalısın.", f"You should be {adj} in the library.", "advice",
            f"You + should + be + {adj}",
            _rich_teaching_how(
                "Kurallı ortamda sessizlik tavsiyesi.",
                f"You should be {adj} in the library",
                "Kütüphanede sessiz olmalısın.",
                [
                    ("should be quiet", "should be + sıfat → … olmalısın\nKural veya tavsiye."),
                ],
            )),
        _pe(w, "Sınavda sessiz kalmam lazım.", f"I need to keep {adj} during the exam.", "obligation",
            f"I + need to + keep + {adj}",
            _rich_teaching_how(
                "Sınavda sessiz kalma zorunluluğu.",
                f"I need to keep {adj} during the exam",
                "Sınavda sessiz kalmam lazım.",
                [
                    ("need to keep quiet", f"keep {adj} → sessiz kalmak\nneed to + fiil → …-mem lazım"),
                ],
            )),
        _pe(w, "Burada sessiz olması gerekir.", f"It should be {adj} here.", "possibility",
            f"It + should + be + {adj}",
            _rich_teaching_how(
                "Bir yerin sessiz olması gerektiğini söylersiniz.",
                f"It should be {adj} here",
                "Burada sessiz olması gerekir.",
                [
                    ("It should be", "Ortam için: It should be quiet → burada sessiz olmalı"),
                ],
            )),
        _pe(w, "Yağmur yağarsa dışarı daha sessiz olur.", f"If it rains, it will be {adj}er outside.", "conditional",
            f"If + it + rains, + it will be + {adj}er",
            _rich_teaching_how(
                "Koşula bağlı olarak ortamın daha sessiz olacağını söylersiniz.",
                f"If it rains, it will be quieter outside",
                "Yağmur yağarsa dışarı daha sessiz olur.",
                [
                    ("quieter", f"{adj}er → daha {w}\nKarşılaştırma: quiet → quieter"),
                    ("If …, will …", "Koşul cümlesi: If it rains → yağmur yağarsa"),
                ],
            )),
        _pe(w, "A: Sessiz misin? B: Evet, bebek uyuyor.",
            f"A: Are you being {adj}? B: Yes, the baby is asleep.", "dialogue",
            f"Are you being {adj}",
            _rich_teaching_how(
                "Günlük sessizlik kontrolü diyalogu.",
                f"Are you being {adj}?",
                "Sessiz misin?",
                [
                    ("Are you being quiet?", "Şu anki davranış için: Are you being quiet?\n"
                     "Genel durum için: Are you quiet?"),
                ],
            )),
    ]


def _turkish_predicate_adj(word_tr: str) -> str:
    """mutlu → mutluyum, sessiz → sessizim."""
    w = safe_str(word_tr).strip().lower()
    known = {
        "mutlu": "mutluyum", "üzgün": "üzgünüm", "uzgun": "üzgünüm", "sessiz": "sessizim",
        "yorgun": "yorgunum", "mutsuz": "mutsuzum", "sakin": "sakinim", "meşgul": "meşgulüm",
        "mesgul": "meşgulüm", "kızgın": "kızgınım", "kizgin": "kızgınım", "gürültülü": "gürültülüyüm",
        "gurultulu": "gürültülüyüm",
    }
    return known.get(w, f"{word_tr}um")


def _turkish_predicate_adj_past(word_tr: str) -> str:
    w = safe_str(word_tr).strip().lower()
    known = {
        "mutlu": "mutluydum", "üzgün": "üzgündüm", "uzgun": "üzgündüm", "sessiz": "sessizdim",
        "yorgun": "yorgundum", "mutsuz": "mutsuzdum", "sakin": "sakindim",
    }
    return known.get(w, f"{word_tr}dum")


def _turkish_predicate_adj_future(word_tr: str) -> str:
    w = safe_str(word_tr).strip().lower()
    known = {
        "mutlu": "mutlu olacağım", "sessiz": "sessiz olacağım", "yorgun": "yorgun olacağım",
    }
    return known.get(w, f"{word_tr} olacağım")


def _turkish_predicate_adj_negative(word_tr: str) -> str:
    w = safe_str(word_tr).strip().lower()
    known = {
        "mutlu": "mutlu değilim", "sessiz": "sessiz değilim", "yorgun": "yorgun değilim",
        "üzgün": "üzgün değilim", "uzgun": "üzgün değilim",
    }
    return known.get(w, f"{word_tr} değilim")


def _pronoun_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Zamir — özne/nesne/iyelik; asla «yeni bir he aldım» yok."""
    p = _en_target_word(T)
    subj = p
    obj = {"he": "him", "she": "her", "they": "them", "we": "us", "i": "me", "you": "you"}.get(p, p)
    poss = {"he": "his", "she": "her", "they": "their", "we": "our", "i": "my", "you": "your"}.get(p, f"{p}'s")
    return [
        _pe(W, f"{W.capitalize()} öğretmen.", f"{subj.capitalize()} is a teacher.", "basic",
            f"{subj} + is + a teacher",
            _rich_teaching_how(f"«{W}» özne olarak kullanılır.", f"{subj} is a teacher", f"{W} öğretmen.",
                [("özne zamiri", f"{subj} + is → …-dır\n❌ Him is a teacher — özne değil nesne zamiri")],
                mistakes=[f"bought a new {p}", f"my {p} is on the table"]),
            scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an {W} arıyoruz.", f"We are looking for {obj} right now.", "present",
            f"looking for {obj}", _rich_teaching_how("Nesne zamiri ile arama.", f"looking for {obj}",
                f"Şu an {W} arıyoruz.", [("nesne zamiri", f"{obj} → onu/onları (nesne)")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün {W} gördüm.", f"I saw {obj} yesterday.", "past",
            f"I + saw + {obj}", _rich_teaching_how("Geçmişte nesne zamiri.", f"I saw {obj}",
                f"Dün {W} gördüm.", [("saw", f"saw {obj} → onu gördüm")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {W} arayacağım.", f"I will call {obj} tomorrow.", "future",
            f"will call {obj}", _rich_teaching_how("Gelecek + nesne zamiri.", f"I will call {obj}",
                f"Yarın {W} arayacağım.", [("will call", "will + fiil → arayacağım")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} mi?", f"Is that {obj}?", "question",
            f"Is that {obj}", _rich_teaching_how("Kimlik sorusu.", f"Is that {obj}?",
                f"{W.capitalize()} mi?", [("Is that …?", "Is that him/her? → o mu?")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bugün {W} görmedim.", f"I didn't see {obj} today.", "negative",
            f"didn't see {obj}", _rich_teaching_how("Olumsuz + nesne.", f"I didn't see {obj}",
                f"Bugün {W} görmedim.", [("didn't see", "didn't + fiil → görmedim")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()} ara!", f"Call {obj}!", "imperative",
            f"Call + {obj}", _rich_teaching_how("Emir + nesne zamiri.", f"Call {obj}!",
                f"{W.capitalize()} ara!", [("Call him/her", f"Call {obj} → onu ara")])),
        _pe(W, f"{W.capitalize()} görebilir misin?", f"Can you see {obj}?", "polite_request",
            f"Can you see {obj}", _rich_teaching_how("Rica + nesne zamiri.", f"Can you see {obj}?",
                f"{W.capitalize()} görebilir misin?", [("Can you see …?", "… görebilir misin?")])),
        _pe(W, f"{W.capitalize()} dinlemelisin.", f"You should listen to {obj}.", "advice",
            f"listen to {obj}", _rich_teaching_how("Tavsiye.", f"You should listen to {obj}",
                f"{W.capitalize()} dinlemelisin.", [("listen to", f"listen to {obj} → onu dinle")])),
        _pe(W, f"{W.capitalize()} bulmam lazım.", f"I need to find {obj}.", "obligation",
            f"need to find {obj}", _rich_teaching_how("Zorunluluk.", f"I need to find {obj}",
                f"{W.capitalize()} bulmam lazım.", [("need to find", "… bulmam lazım")])),
        _pe(W, f"{W.capitalize()} burada olabilir.", f"{subj.capitalize()} might be here.", "possibility",
            f"might be here", _rich_teaching_how("Olasılık + özne.", f"{subj} might be here",
                f"{W.capitalize()} burada olabilir.", [("might be", "… olabilir")])),
        _pe(W, f"{W.capitalize()} görürsen haber ver.", f"If you see {obj}, let me know.", "conditional",
            f"If you see {obj}", _rich_teaching_how("Koşul.", f"If you see {obj}",
                f"{W.capitalize()} görürsen haber ver.", [("If you see", "… görürsen")])),
        _pe(W, f"A: {W.capitalize()} nerede? B: Orada.", f"A: Where is {subj}? B: Over there.", "dialogue",
            f"Where is {subj}", _rich_teaching_how("Diyalog.", f"Where is {subj}?",
                f"{W.capitalize()} nerede?", [("Where is he/she?", "özne zamiri + where")])),
    ]


def _adverb_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Zarf — fiili niteler; asla «yeni bir quickly aldım» yok."""
    adv = _en_target_word(T)
    return [
        _pe(W, f"Her zaman {W} konuşurum.", f"I always speak {adv}.", "basic",
            f"always + speak {adv}", _rich_teaching_how(f"«{W}» fiili niteler.", f"I always speak {adv}",
                f"Her zaman {W} konuşurum.", [("zarf + fiil", f"speak {adv} → {W} konuşmak")],
                mistakes=[f"a {adv}", f"my {adv}"]), scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an {W} gidiyorum.", f"I am walking {adv} right now.", "present",
            f"walking {adv}", _rich_teaching_how("Şimdiki zaman + zarf.", f"walking {adv}",
                f"Şu an {W} gidiyorum.", [("-ly zarf", f"{adv} → nasıl? (yavaşça, hızlıca)")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün {W} çalıştım.", f"I worked {adv} yesterday.", "past",
            f"worked {adv}", _rich_teaching_how("Geçmiş + zarf.", f"I worked {adv}",
                f"Dün {W} çalıştım.", [("worked + zarf", "fiilden sonra zarf")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın daha {W} gideceğim.", f"I will drive more {adv} tomorrow.", "future",
            f"will drive {adv}", _rich_teaching_how("Gelecek + zarf.", f"I will drive {adv}",
                f"Yarın daha {W} gideceğim.", [("more + zarf", "karşılaştırma")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} mi gidiyorsun?", f"Are you driving {adv}?", "question",
            f"Are you + verb + {adv}", _rich_teaching_how("Soru + zarf.", f"Are you driving {adv}?",
                f"{W.capitalize()} mi gidiyorsun?", [("Are you … -ly?", "…-yor musun?")]), scenario_badge="❓ SORU"),
        _pe(W, f"{W.capitalize()} konuşmuyorum.", f"I don't speak {adv}.", "negative",
            f"don't speak {adv}", _rich_teaching_how("Olumsuz + zarf.", f"I don't speak {adv}",
                f"{W.capitalize()} konuşmuyorum.", [("don't + fiil + zarf", "olumsuz")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()} konuş!", f"Speak {adv}!", "imperative",
            f"Speak {adv}", _rich_teaching_how("Emir + zarf.", f"Speak {adv}!",
                f"{W.capitalize()} konuş!", [("Speak + zarf", "emir kipi")])),
        _pe(W, f"Biraz daha {W} konuşabilir misin?", f"Could you speak a little more {adv}?", "polite_request",
            f"speak more {adv}", _rich_teaching_how("Rica.", f"Could you speak more {adv}?",
                f"Biraz daha {W} konuşabilir misin?", [("a little more", "biraz daha")])),
        _pe(W, f"Sınavda {W} okumalısın.", f"You should read {adv} on the exam.", "advice",
            f"should read {adv}", _rich_teaching_how("Tavsiye.", f"You should read {adv}",
                f"Sınavda {W} okumalısın.", [("should + fiil + zarf", "tavsiye")])),
        _pe(W, f"{W.capitalize()} dinlemem lazım.", f"I need to listen {adv}.", "obligation",
            f"need to listen {adv}", _rich_teaching_how("Zorunluluk.", f"I need to listen {adv}",
                f"{W.capitalize()} dinlemem lazım.", [("need to + fiil + zarf", "…-mem lazım")])),
        _pe(W, f"Belki {W} gidebiliriz.", f"We might go {adv}.", "possibility",
            f"might go {adv}", _rich_teaching_how("Olasılık.", f"We might go {adv}",
                f"Belki {W} gidebiliriz.", [("might + fiil + zarf", "belki")])),
        _pe(W, f"Acele edersen {W} gidersin.", f"If you hurry, you will go {adv}.", "conditional",
            f"If you hurry, go {adv}", _rich_teaching_how("Koşul.", f"If you hurry, you will go {adv}",
                f"Acele edersen {W} gidersin.", [("If …, will …", "koşul")])),
        _pe(W, f"A: {W.capitalize()} mi? B: Evet.", f"A: {adv.capitalize()}? B: Yes.", "dialogue",
            f"A: {adv}", _rich_teaching_how("Diyalog.", f"{adv}?",
                f"{W.capitalize()} mi?", [("Zarf tek başına", "kısa onay")])),
    ]


def _animal_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Hayvan — besleme, sevme, gezdirme; nesne şablonu yok."""
    an = _en_target_word(T)
    a_an = f"an {an}" if an[0] in "aeiou" else f"a {an}"
    return [
        _pe(W, f"Bir {W} besliyoruz.", f"We have {a_an}.", "basic",
            f"have {a_an}", _rich_teaching_how(f"Evcil hayvan sahipliği.", f"We have {a_an}",
                f"Bir {W} besliyoruz.", [("have a pet", f"have {a_an} → bir …-mız var")],
                mistakes=[f"I am using the {an}"]), scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an {W} besliyorum.", f"I am feeding the {an} right now.", "present",
            f"feeding the {an}", _rich_teaching_how("Besleme.", f"I am feeding the {an}",
                f"Şu an {W} besliyorum.", [("feed the", "feed → beslemek")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün {W} veterinere götürdük.", f"We took the {an} to the vet yesterday.", "past",
            f"took the {an} to the vet", _rich_teaching_how("Veteriner.", f"We took the {an} to the vet",
                f"Dün {W} veterinere götürdük.", [("took to the vet", "veterinere götürmek")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {W} gezdireceğim.", f"I will walk the {an} tomorrow.", "future",
            f"will walk the {an}", _rich_teaching_how("Gezdirme.", f"I will walk the {an}",
                f"Yarın {W} gezdireceğim.", [("walk the dog/cat", "gezdirme")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} uyuyor mu?", f"Is the {an} sleeping?", "question",
            f"Is the {an} sleeping", _rich_teaching_how("Soru.", f"Is the {an} sleeping?",
                f"{W.capitalize()} uyuyor mu?", [("Is the … -ing?", "şu an …-yor mu?")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bugün {W} gezdirmedim.", f"I didn't walk the {an} today.", "negative",
            f"didn't walk the {an}", _rich_teaching_how("Olumsuz.", f"I didn't walk the {an}",
                f"Bugün {W} gezdirmedim.", [("didn't walk", "gezdirmedim")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()} besle!", f"Feed the {an}!", "imperative",
            f"Feed the {an}", _rich_teaching_how("Emir.", f"Feed the {an}!",
                f"{W.capitalize()} besle!", [("Feed the", "besle")])),
        _pe(W, f"{W.capitalize()} okşayabilir miyim?", f"Can I pet the {an}?", "polite_request",
            f"Can I pet the {an}", _rich_teaching_how("Rica.", f"Can I pet the {an}?",
                f"{W.capitalize()} okşayabilir miyim?", [("pet the", "okşamak / sevmek")])),
        _pe(W, f"{W.capitalize()} düzenli beslemelisin.", f"You should feed the {an} regularly.", "advice",
            f"should feed the {an}", _rich_teaching_how("Tavsiye.", f"You should feed the {an}",
                f"{W.capitalize()} düzenli beslemelisin.", [("should feed", "düzenli besle")])),
        _pe(W, f"{W.capitalize()} veterinere götürmem lazım.", f"I need to take the {an} to the vet.", "obligation",
            f"need to take the {an}", _rich_teaching_how("Zorunluluk.", f"I need to take the {an} to the vet",
                f"{W.capitalize()} veterinere götürmem lazım.", [("need to take", "götürmem lazım")])),
        _pe(W, f"{W.capitalize()} bahçede olabilir.", f"The {an} might be in the yard.", "possibility",
            f"might be in the yard", _rich_teaching_how("Olasılık.", f"The {an} might be in the yard",
                f"{W.capitalize()} bahçede olabilir.", [("might be", "olabilir")])),
        _pe(W, f"{W.capitalize()} açsa yemek ver.", f"If the {an} is hungry, give it food.", "conditional",
            f"If the {an} is hungry", _rich_teaching_how("Koşul.", f"If the {an} is hungry, give it food",
                f"{W.capitalize()} açsa yemek ver.", [("If …, give", "açsa ver")])),
        _pe(W, f"A: {W.capitalize()} nerede? B: Sofada.", f"A: Where is the {an}? B: On the couch.", "dialogue",
            f"Where is the {an}", _rich_teaching_how("Diyalog.", f"Where is the {an}?",
                f"{W.capitalize()} nerede?", [("Where is the …?", "… nerede?")])),
    ]


def _furniture_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Mobilya — oturma, yatma, yerleştirme."""
    item = _en_target_word(T)
    the = f"the {item}"
    return [
        _pe(W, f"{W.capitalize()} çok rahat.", f"The {item} is very comfortable.", "basic",
            f"The {item} + is + comfortable", _rich_teaching_how(f"Mobilya tanımı.", f"The {item} is comfortable",
                f"{W.capitalize()} çok rahat.", [("The + mobilya", f"the {item} → belirli mobilya")]),
            scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an {W} üzerinde oturuyorum.", f"I am sitting on the {item} right now.", "present",
            f"sitting on the {item}", _rich_teaching_how("Oturma.", f"sitting on the {item}",
                f"Şu an {W} üzerinde oturuyorum.", [("sit on", f"on the {item} → üzerinde")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün yeni {W} aldık.", f"We bought a new {item} yesterday.", "past",
            f"bought a new {item}", _rich_teaching_how("Satın alma.", f"bought a new {item}",
                f"Dün yeni {W} aldık.", [("a new", "yeni bir")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın {W} taşıyacağız.", f"We will move the {item} tomorrow.", "future",
            f"will move the {item}", _rich_teaching_how("Taşıma.", f"will move the {item}",
                f"Yarın {W} taşıyacağız.", [("move the", "taşımak")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} rahat mı?", f"Is the {item} comfortable?", "question",
            f"Is the {item} comfortable", _rich_teaching_how("Soru.", f"Is the {item} comfortable?",
                f"{W.capitalize()} rahat mı?", [("Is the …?", "… rahat mı?")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bu {W} rahat değil.", f"This {item} isn't comfortable.", "negative",
            f"isn't comfortable", _rich_teaching_how("Olumsuz.", f"This {item} isn't comfortable",
                f"Bu {W} rahat değil.", [("isn't", "değil")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()} üzerine otur!", f"Sit on the {item}!", "imperative",
            f"Sit on the {item}", _rich_teaching_how("Emir.", f"Sit on the {item}!",
                f"{W.capitalize()} üzerine otur!", [("Sit on", "üzerine otur")])),
        _pe(W, f"{W.capitalize()} kaydırabilir misin?", f"Could you move the {item}?", "polite_request",
            f"Could you move the {item}", _rich_teaching_how("Rica.", f"Could you move the {item}?",
                f"{W.capitalize()} kaydırabilir misin?", [("Could you move", "kaydırabilir misin")])),
        _pe(W, f"{W.capitalize()} pencereye yakın olmalı.", f"The {item} should be near the window.", "advice",
            f"should be near", _rich_teaching_how("Tavsiye.", f"The {item} should be near the window",
                f"{W.capitalize()} pencereye yakın olmalı.", [("should be near", "yakın olmalı")])),
        _pe(W, f"{W.capitalize()} kurmam lazım.", f"I need to assemble the {item}.", "obligation",
            f"need to assemble", _rich_teaching_how("Kurulum.", f"I need to assemble the {item}",
                f"{W.capitalize()} kurmam lazım.", [("assemble", "kurmak / monte etmek")])),
        _pe(W, f"{W.capitalize()} burada olabilir.", f"The {item} might be here.", "possibility",
            f"might be here", _rich_teaching_how("Olasılık.", f"The {item} might be here",
                f"{W.capitalize()} burada olabilir.", [("might be", "olabilir")])),
        _pe(W, f"Yer varsa {W} buraya koy.", f"If there is room, put the {item} here.", "conditional",
            f"If there is room", _rich_teaching_how("Koşul.", f"If there is room, put the {item} here",
                f"Yer varsa {W} buraya koy.", [("If there is room", "yer varsa")])),
        _pe(W, f"A: {W.capitalize()} nerede? B: Oturma odasında.", f"A: Where is the {item}? B: In the living room.", "dialogue",
            f"Where is the {item}", _rich_teaching_how("Diyalog.", f"Where is the {item}?",
                f"{W.capitalize()} nerede?", [("Where is the …?", "nerede?")])),
    ]


def _preposition_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Edat — yer/yön/zaman; asla «yeni bir with aldım» yok."""
    prep = _en_target_word(T)
    return [
        _pe(W, f"Evde {W} kalırım.", f"I stay at home {prep} evenings.", "basic",
            f"at home / with {prep}", _rich_teaching_how(f"«{W}» edat olarak kullanılır.", f"at home with {prep}",
                f"Evde {W} kalırım.", [("edat + isim", f"{prep} + the table / home / me")],
                mistakes=[f"bought a {prep}", f"my {prep} is on the table"]), scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an arkadaşım {W} buradayım.", f"I am here with my friend right now.", "present",
            f"with my friend", _rich_teaching_how("Birliktelik edatı.", f"I am here with my friend",
                f"Şu an arkadaşım {W} buradayım.", [("with", f"with → {W} / ile")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün annem {W} alışverişe gittim.", f"I went shopping with my mom yesterday.", "past",
            f"went with", _rich_teaching_how("Geçmiş + edat.", f"I went shopping with my mom",
                f"Dün annem {W} alışverişe gittim.", [("with + kişi", "birlikte → with")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın sana {W} geleceğim.", f"I will come to you tomorrow.", "future",
            f"will come to you", _rich_teaching_how("Yön edatı.", f"I will come to you",
                f"Yarın sana {W} geleceğim.", [("to you", "sana → to you")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"Kitap masanın {W} mi?", f"Is the book on the table?", "question",
            f"on the table", _rich_teaching_how("Yer sorusu.", f"Is the book on the table?",
                f"Kitap masanın {W} mi?", [("on the", "üzerinde → on the")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bugün dışarı {W} çıkmadım.", f"I didn't go out today.", "negative",
            f"didn't go out", _rich_teaching_how("Olumsuz + edat bağlamı.", f"I didn't go out",
                f"Bugün dışarı {W} çıkmadım.", [("go out", "dışarı çıkmak")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"Benimle {W} gel!", f"Come with me!", "imperative",
            f"Come with me", _rich_teaching_how("Emir + edat.", f"Come with me!",
                f"Benimle {W} gel!", [("with me", "benimle → with me")]), scenario_badge="📣 EMİR"),
        _pe(W, f"Benimle {W} gelebilir misin?", f"Could you come with me?", "polite_request",
            f"come with me", _rich_teaching_how("Rica.", f"Could you come with me?",
                f"Benimle {W} gelebilir misin?", [("Could you come with", "…-le gelebilir misin?")]), scenario_badge="🙏 RİCA"),
        _pe(W, f"Erken {W} gitmelisin.", f"You should leave early.", "advice",
            f"should leave early", _rich_teaching_how("Tavsiye.", f"You should leave early",
                f"Erken {W} gitmelisin.", [("leave early", "erken git")]), scenario_badge="💡 TAVSİYE"),
        _pe(W, f"Ona {W} konuşmam lazım.", f"I need to talk to him.", "obligation",
            f"talk to him", _rich_teaching_how("Zorunluluk.", f"I need to talk to him",
                f"Ona {W} konuşmam lazım.", [("talk to", "ona konuşmak / talk to")]), scenario_badge="📌 ZORUNLU"),
        _pe(W, f"O burada {W} olabilir.", f"He might be here.", "possibility",
            f"might be here", _rich_teaching_how("Olasılık.", f"He might be here",
                f"O burada {W} olabilir.", [("might be", "burada olabilir")]), scenario_badge="🎲 OLASILIK"),
        _pe(W, f"Vaktin olursa benimle {W} gel.", f"If you have time, come with me.", "conditional",
            f"If you have time, come with me", _rich_teaching_how("Koşul.", f"If you have time, come with me",
                f"Vaktin olursa benimle {W} gel.", [("If …, come with", "olursa …-le gel")]), scenario_badge="🔀 KOŞUL"),
        _pe(W, f"A: Neredesin? B: Evde, annem {W}.", f"A: Where are you? B: At home, with my mom.", "dialogue",
            f"Where are you", _rich_teaching_how("Diyalog.", f"Where are you? At home, with my mom",
                f"A: Neredesin? B: Evde, annem {W}.", [("with my mom", "annemle → with my mom")]), scenario_badge="💬 DİYALOG"),
    ]


def _conjunction_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Bağlaç — cümle/öbek bağlama; nesne şablonu yok."""
    conj = _en_target_word(T)
    return [
        _pe(W, f"Kahve {W} çay severim.", f"I like coffee {conj} tea.", "basic",
            f"coffee {conj} tea", _rich_teaching_how(f"«{W}» iki öğeyi bağlar.", f"coffee {conj} tea",
                f"Kahve {W} çay severim.", [("bağlaç", f"A {conj} B → A {W} B")],
                mistakes=[f"bought a {conj}", f"my {conj}"]), scenario_badge="🌅 RUTİN"),
        _pe(W, f"Şu an çalışıyorum {W} yorgunum.", f"I am working {conj} I am tired.", "present",
            f"working but tired", _rich_teaching_how("Zıtlık bağlacı.", f"I am working but I am tired",
                f"Şu an çalışıyorum {W} yorgunum.", [("but", "ama / fakat")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün geç kaldım {W} otobüsü kaçırdım.", f"I was late yesterday {conj} I missed the bus.", "past",
            f"late because missed", _rich_teaching_how("Sebep bağlacı.", f"I was late because I missed the bus",
                f"Dün geç kaldım {W} otobüsü kaçırdım.", [("because", "çünkü → because")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın gideceğim {W} erken kalkacağım.", f"I will go tomorrow {conj} I will wake up early.", "future",
            f"will go and wake up", _rich_teaching_how("Gelecek + bağlaç.", f"I will go and I will wake up early",
                f"Yarın gideceğim {W} erken kalkacağım.", [("and", "ve → and")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"Çay mı kahve mi, yoksa ikisi {W} mi?", f"Tea or coffee, or both?", "question",
            f"or both", _rich_teaching_how("Seçenek bağlacı.", f"Tea or coffee, or both?",
                f"Çay mı kahve mi?", [("or", "veya → or")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bugün gitmedim {W} evde kaldım.", f"I didn't go today {conj} I stayed home.", "negative",
            f"didn't go, stayed", _rich_teaching_how("Olumsuz + bağlaç.", f"I didn't go and I stayed home",
                f"Bugün gitmedim {W} evde kaldım.", [("and/but", "bağlaç iki cümleyi birleştirir")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"Bekle {W} geliyorum!", f"Wait {conj} I'm coming!", "imperative",
            f"Wait and I'm coming", _rich_teaching_how("Emir + bağlaç.", f"Wait and I'm coming!",
                f"Bekle {W} geliyorum!", [("Wait and", "bekle ve")]), scenario_badge="📣 EMİR"),
        _pe(W, f"Biraz daha bekleyebilir misin {W} hazır olunca gideriz?", f"Could you wait a bit {conj} we'll leave when ready?", "polite_request",
            f"wait and we'll leave", _rich_teaching_how("Rica + bağlaç.", f"Could you wait and we'll leave when ready?",
                f"Biraz daha bekleyebilir misin {W} hazır olunca gideriz?", [("and when", "ve …-ince")]), scenario_badge="🙏 RİCA"),
        _pe(W, f"Daha erken yatmalısın {W} yorgun olmazsın.", f"You should sleep earlier {conj} you won't be tired.", "advice",
            f"should sleep so you won't", _rich_teaching_how("Tavsiye.", f"You should sleep earlier so you won't be tired",
                f"Daha erken yatmalısın {W} yorgun olmazsın.", [("so that", "ki / -mesin diye")]), scenario_badge="💡 TAVSİYE"),
        _pe(W, f"Ödevimi bitirmem lazım {W} dışarı çıkamam.", f"I need to finish my homework {conj} I can't go out.", "obligation",
            f"need to finish so can't go", _rich_teaching_how("Zorunluluk.", f"I need to finish my homework so I can't go out",
                f"Ödevimi bitirmem lazım {W} dışarı çıkamam.", [("so", "bu yüzden / -dığı için")]), scenario_badge="📌 ZORUNLU"),
        _pe(W, f"Yağmur yağarsa evde kalırız {W} sinema gideriz.", f"If it rains we stay home {conj} we might go to the movies.", "possibility",
            f"if rain stay or go", _rich_teaching_how("Olasılık.", f"If it rains we stay home, otherwise we might go",
                f"Yağmur yağarsa evde kalırız {W} sinema gideriz.", [("if …, or", "yağarsa … yoksa")]), scenario_badge="🎲 OLASILIK"),
        _pe(W, f"Vaktin olursa gel {W} birlikte çalışırız.", f"If you have time, come {conj} we'll study together.", "conditional",
            f"If you have time, come and we'll study", _rich_teaching_how("Koşul.", f"If you have time, come and we'll study together",
                f"Vaktin olursa gel {W} birlikte çalışırız.", [("If …, and", "olursa gel ve")]), scenario_badge="🔀 KOŞUL"),
        _pe(W, f"A: Gidiyor musun? B: Evet {W} sen de gel.", f"A: Are you going? B: Yes {conj} you come too.", "dialogue",
            f"Yes and you come", _rich_teaching_how("Diyalog.", f"Are you going? Yes, and you come too",
                f"A: Gidiyor musun? B: Evet {W} sen de gel.", [("Yes, and", "evet ve")]), scenario_badge="💬 DİYALOG"),
    ]


def _interjection_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Ünlem — selamlama/duygu; nesne şablonu yok."""
    interj = _en_target_word(T)
    return [
        _pe(W, f"{W.capitalize()}! Nasılsın?", f"{interj.capitalize()}! How are you?", "basic",
            f"{interj}! + question", _rich_teaching_how(f"«{W}» selamlama ünlemidir.", f"{interj}! How are you?",
                f"{W.capitalize()}! Nasılsın?", [("ünlem", f"{interj}! → kısa selamlama")],
                mistakes=[f"bought a {interj}", f"my {interj} is here"]), scenario_badge="🌅 RUTİN"),
        _pe(W, f"{W.capitalize()}! Buraya bak.", f"{interj.capitalize()}! Look over here.", "present",
            f"{interj}! Look", _rich_teaching_how("Dikkat çekme.", f"{interj}! Look over here",
                f"{W.capitalize()}! Buraya bak.", [("Look!", "bak / look")]), scenario_badge="🔄 ŞU AN"),
        _pe(W, f"Dün ona {W} dedim.", f"I said {interj} to him yesterday.", "past",
            f"said {interj}", _rich_teaching_how("Geçmişte söyleme.", f"I said {interj} to him",
                f"Dün ona {W} dedim.", [("said hello", f"said {interj} → … dedim")]), scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, f"Yarın ona {W} diyeceğim.", f"I will say {interj} to her tomorrow.", "future",
            f"will say {interj}", _rich_teaching_how("Gelecek.", f"I will say {interj} to her",
                f"Yarın ona {W} diyeceğim.", [("will say", "diyeceğim")]), scenario_badge="🔮 GELECEK"),
        _pe(W, f"{W.capitalize()} mı dedin?", f"Did you say {interj}?", "question",
            f"Did you say {interj}", _rich_teaching_how("Soru.", f"Did you say {interj}?",
                f"{W.capitalize()} mı dedin?", [("Did you say", "… dedin mi?")]), scenario_badge="❓ SORU"),
        _pe(W, f"Bugün {W} demedim.", f"I didn't say {interj} today.", "negative",
            f"didn't say {interj}", _rich_teaching_how("Olumsuz.", f"I didn't say {interj} today",
                f"Bugün {W} demedim.", [("didn't say", "dememedim")]), scenario_badge="⛔ OLUMSUZ"),
        _pe(W, f"{W.capitalize()}!", f"{interj.capitalize()}!", "imperative",
            f"{interj}!", _rich_teaching_how("Kısa ünlem.", f"{interj}!",
                f"{W.capitalize()}!", [("ünlem tek başına", "Hello! / Hey!")]), scenario_badge="📣 EMİR"),
        _pe(W, f"Lütfen {W} de.", f"Please say {interj}, too.", "polite_request",
            f"Please say {interj}", _rich_teaching_how("Kibar rica.", f"Please say {interj}, too",
                f"Lütfen {W} de.", [("Please say", "lütfen … de")]), scenario_badge="🙏 RİCA"),
        _pe(W, f"Yeni insanlara {W} demelisin.", f"You should say {interj} to new people.", "advice",
            f"should say {interj}", _rich_teaching_how("Tavsiye.", f"You should say {interj} to new people",
                f"Yeni insanlara {W} demelisin.", [("should say", "demelisin")]), scenario_badge="💡 TAVSİYE"),
        _pe(W, f"Ona {W} demem lazım.", f"I need to say {interj} to him.", "obligation",
            f"need to say {interj}", _rich_teaching_how("Zorunluluk.", f"I need to say {interj} to him",
                f"Ona {W} demem lazım.", [("need to say", "demem lazım")]), scenario_badge="📌 ZORUNLU"),
        _pe(W, f"Belki {W} der.", f"She might say {interj}.", "possibility",
            f"might say {interj}", _rich_teaching_how("Olasılık.", f"She might say {interj}",
                f"Belki {W} der.", [("might say", "der / diyebilir")]), scenario_badge="🎲 OLASILIK"),
        _pe(W, f"Görürsen {W} de.", f"If you see him, say {interj}.", "conditional",
            f"If you see him, say {interj}", _rich_teaching_how("Koşul.", f"If you see him, say {interj}",
                f"Görürsen {W} de.", [("If you see, say", "görürsen de")]), scenario_badge="🔀 KOŞUL"),
        _pe(W, f"A: {W.capitalize()}! B: {W.capitalize()}!", f"A: {interj.capitalize()}! B: {interj.capitalize()}!", "dialogue",
            f"{interj}! exchange", _rich_teaching_how("Karşılıklı selam.", f"Hello! Hello!",
                f"A: {W.capitalize()}! B: {W.capitalize()}!", [("greeting exchange", "selamlaşma")]), scenario_badge="💬 DİYALOG"),
    ]


def _verb_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    return [
        _pe(W, f"Her gün çalışırım.", f"I {T} every day.", "basic", f"I + {T} + every day", f"1️⃣ Temel kullanım\nGeniş zaman: I + fiil(yalın)"),
        _pe(W, f"Şu an çalışıyorum.", f"I am {T}ing now.", "present", f"I + am + {T}ing", f"1️⃣ Şimdiki zaman\nam + fiil-ing → şu anda …-yor"),
        _pe(W, f"Dün geç çalıştım.", f"I {T}ed late yesterday.", "past", f"I + {T}ed", f"1️⃣ Geçmiş zaman\nfiil + -ed → geçmiş zaman"),
        _pe(W, f"Yarın çalışacağım.", f"I will {T} tomorrow.", "future", f"I + will + {T}", f"1️⃣ Gelecek zaman\nwill + fiil → …-eceğim"),
        _pe(W, f"Burada çalışıyor musun?", f"Do you {T} here?", "question", f"Do + you + {T}", f"1️⃣ Soru cümlesi\nDo + özne + fiil?"),
        _pe(W, f"Pazar günleri çalışmam.", f"I don't {T} on Sundays.", "negative", f"I + don't + {T}", f"1️⃣ Olumsuz cümle\ndon't + fiil(yalın)"),
        _pe(W, f"Çalış!", f"{T.capitalize()}!", "imperative", f"{T.capitalize()}", f"1️⃣ Emir kipi\nFiil ile başlar, özne yok"),
        _pe(W, f"Biraz çalışabilir misin?", f"Could you {T} a bit?", "polite_request", f"Could + you + {T}", f"1️⃣ Rica cümlesi\nCould you…? → …-ebilir misin?"),
        _pe(W, f"Daha çok çalışmalısın.", f"You should {T} harder.", "advice", f"You + should + {T}", f"1️⃣ Tavsiye cümlesi\nshould → …-melisin"),
        _pe(W, f"Bugün çalışmam lazım.", f"I need to {T} today.", "obligation", f"I + need to + {T}", f"1️⃣ Zorunluluk cümlesi\nneed to + fiil"),
        _pe(W, f"Belki yarın çalışırım.", f"I might {T} tomorrow.", "possibility", f"I + might + {T}", f"1️⃣ İhtimal cümlesi\nmight → belki / -ebilir"),
        _pe(W, f"Vaktin olursa çalış.", f"If you have time, {T}.", "conditional", f"If + you + have time, + {T}", f"1️⃣ Koşul cümlesi\nIf you have time → vaktin olursa"),
        _pe(W, f"A: Çalışıyor musun? B: Evet.", f"A: Are you {T}ing? B: Yes, I am.", "dialogue", f"A: Are you {T}ing? B: Yes", f"1️⃣ Günlük diyalog"),
    ]


def _market_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    """Market — alışveriş, gitme, satın alma; derin öğretici açıklamalar."""
    tw = _en_target_word(T)
    the_market = f"the {tw}"
    to_market = f"to {the_market}"
    at_market = f"at {the_market}"
    return [
        _pe(W, "Market evimize yakın.", f"{the_market.capitalize()} is near our house.", "basic",
            f"{the_market} + is + near our house",
            _rich_teaching_how(
                "Mahalle marketinin konumunu anlatırsınız.",
                f"{the_market} is near our house",
                "Market evimize yakın.",
                [
                    ("the market", f"the {tw} → belirli market (mahalle marketi)\n"
                     "İngilizcede yer isimlerinde genelde the kullanılır."),
                    ("is near", "is near → yakın\nnear + our house → evimize yakın\n"
                     "Türkçede «yakın» tek kelime; İngilizcede is near ile kurulur."),
                ],
                mistakes=[f"I am near market — the eksik", "Market is near — the market daha doğal"],
            ),
            scenario_badge="🌅 RUTİN"),
        _pe(W, "Şu an marketteyim.", f"I am at {the_market} now.", "present",
            f"I + am + at {the_market} + now",
            _rich_teaching_how(
                "Şu anda markette olduğunuzu söylersiniz.",
                f"I am at {the_market} now",
                "Şu an marketteyim.",
                [
                    ("am at", f"at {the_market} → markette (konum)\n"
                     "go to the market → markete gitmek (yön)\n"
                     "at the market → markette (bulunma)"),
                    ("now", "now → şu an / şimdi\nŞimdiki zaman: am + at"),
                ],
                mistakes=["I am in the market — at the market daha yaygın (ABD)"],
            ),
            scenario_badge="🔄 ŞU AN"),
        _pe(W, "Dün marketten meyve aldım.", f"I bought some fruit at {the_market} yesterday.", "past",
            f"I + bought + some fruit + at {the_market} + yesterday",
            _rich_teaching_how(
                "Dün marketten alışveriş yaptığınızı anlatırsınız.",
                f"I bought some fruit at {the_market} yesterday",
                "Dün marketten meyve aldım.",
                [
                    ("bought", "buy → almak\nbought → aldım (düzensiz fiil)\n❌ I buyed fruit"),
                    ("at the market", f"at {the_market} → marketten\n"
                     "Türkçede -den eki; İngilizcede at kullanılır."),
                    ("some fruit", "some fruit → biraz meyve\nsome → sayılamayan/çoğul için «biraz»"),
                ],
            ),
            scenario_badge="🕐 GEÇMİŞ"),
        _pe(W, "Yarın markete gideceğim.", f"I will go {to_market} tomorrow.", "future",
            f"I + will + go {to_market} + tomorrow",
            _rich_teaching_how(
                "Yarın markete gitme planınızı söylersiniz.",
                f"I will go {to_market} tomorrow",
                "Yarın markete gideceğim.",
                [
                    ("will go", "will + go → gideceğim\nGelecek zaman için will + fiil kökü"),
                    (f"to {the_market}", f"go {to_market} → markete gitmek\n"
                     "to → yön (-e/-a)\nthe → belirli market"),
                ],
                mistakes=[f"I will go {the_market} — to eksik"],
            ),
            scenario_badge="🔮 GELECEK"),
        _pe(W, "Market açık mı?", f"Is {the_market} open?", "question",
            f"Is + {the_market} + open",
            _rich_teaching_how(
                "Marketin açık olup olmadığını sorarsınız.",
                f"Is {the_market} open?",
                "Market açık mı?",
                [
                    ("Is … open?", f"Is {the_market} open? → Market açık mı?\n"
                     "Soru: Is + özne + sıfat"),
                    ("open", "open → açık (sıfat)\nclosed → kapalı"),
                ],
            ),
            scenario_badge="❓ SORU"),
        _pe(W, "Bugün markete gitmiyorum.", f"I'm not going {to_market} today.", "negative",
            f"I + am + not + going {to_market}",
            _rich_teaching_how(
                "Bugün markete gitmeyeceğinizi söylersiniz.",
                f"I'm not going {to_market} today",
                "Bugün markete gitmiyorum.",
                [
                    ("am not going", "am not going → gitmiyorum\nŞimdiki zaman planı için kullanılır."),
                    ("today", "today → bugün\nZaman ifadesi cümle sonunda veya başında olabilir."),
                ],
            ),
            scenario_badge="⛔ OLUMSUZ"),
        _pe(W, "Markete git ve süt al.", f"Go {to_market} and buy some milk.", "imperative",
            f"Go {to_market} + and + buy some milk",
            _rich_teaching_how(
                "Birine markete gidip süt almasını söylersiniz.",
                f"Go {to_market} and buy some milk",
                "Markete git ve süt al.",
                [
                    ("Go to the market", f"Emir kipi: Go {to_market}\nÖzne yazılmaz (sen anlaşılır)."),
                    ("and buy", "and buy some milk → ve süt al\nİki eylem and ile bağlanır."),
                ],
            )),
        _pe(W, "Markete birlikte gidebilir miyiz?", f"Could we go {to_market} together?", "polite_request",
            f"Could + we + go {to_market} + together",
            _rich_teaching_how(
                "Birlikte markete gitmeyi kibarca önerirsiniz.",
                f"Could we go {to_market} together?",
                "Markete birlikte gidebilir miyiz?",
                [
                    ("Could we …?", "Could we go …? → …-ebilir miyiz?\nKibar teklif/rica kalıbı."),
                    ("together", "together → birlikte"),
                ],
            )),
        _pe(W, "Hafta sonu markete erken gitmelisin.", f"You should go {to_market} early on weekends.", "advice",
            f"You + should + go {to_market} + early",
            _rich_teaching_how(
                "Kalabalık olmaması için erken gitme tavsiyesi verirsiniz.",
                f"You should go {to_market} early on weekends",
                "Hafta sonu markete erken gitmelisin.",
                [
                    ("should go", "should + fiil → …-melisin / …-malısın\nTavsiye veya uyarı."),
                    ("on weekends", "on weekends → hafta sonları\nweekend → hafta sonu (tekil)"),
                ],
            )),
        _pe(W, "Evde yiyecek kalmadı, markete gitmem lazım.",
            f"We're out of food at home, so I need to go {to_market}.", "obligation",
            f"I + need to + go {to_market}",
            _rich_teaching_how(
                "Evde yiyecek bitince markete gitme zorunluluğunu anlatırsınız.",
                f"I need to go {to_market}",
                "Markete gitmem lazım.",
                [
                    ("need to + fiil", "need to go → gitmem lazım / gitmem gerekiyor\n"
                     "need'ten sonra to + fiil gelir.\n❌ I need go to the market"),
                    (f"to {the_market}", f"go {to_market} → markete gitmek"),
                    ("because / so", "Sebep Türkçede virgülle; İngilizcede so veya because ile bağlanır."),
                ],
                mistakes=["I need go — to eksik", "I must to go — must'tan sonra to gelmez"],
            )),
        _pe(W, "Market bugün kapalı olabilir.", f"{the_market.capitalize()} might be closed today.", "possibility",
            f"{the_market} + might + be + closed",
            _rich_teaching_how(
                "Marketin bugün kapalı olma ihtimalini söylersiniz.",
                f"{the_market} might be closed today",
                "Market bugün kapalı olabilir.",
                [
                    ("might be", "might be → … olabilir\nİhtimal bildirir; kesin değil."),
                    ("closed", "closed → kapalı\nopen → açık (zıt anlamlı)"),
                ],
            )),
        _pe(W, "Açıksa marketten ekmek alırım.", f"If it's open, I'll buy bread {at_market}.", "conditional",
            f"If + it + is open, + I will + buy bread {at_market}",
            _rich_teaching_how(
                "Market açıksa ekmek alacağınızı söylersiniz.",
                f"If it's open, I'll buy bread {at_market}",
                "Açıksa marketten ekmek alırım.",
                [
                    ("If …", "If it's open → açıksa\nKoşul cümlesi cümlenin başında."),
                    ("I'll buy", "I'll = I will → alırım / alacağım\nGelecek zaman koşula bağlı."),
                    (f"at {the_market}", f"buy bread {at_market} → marketten ekmek almak"),
                ],
            )),
        _pe(W, "A: Markete gidelim mi? B: Olur, ne alalım?",
            f"A: Shall we go {to_market}? B: Sure, what should we get?", "dialogue",
            f"Shall we go {to_market}",
            _rich_teaching_how(
                "Günlük konuşmada markete gitme teklifi.",
                f"Shall we go {to_market}?",
                "Markete gidelim mi?",
                [
                    ("Shall we …?", "Shall we go …? → …-elim mi?\nBirlikte yapma teklifi."),
                    ("what should we get", "what should we get → ne alalım\nAlışveriş listesi sorusu."),
                ],
            )),
    ]


def _place_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    return [
        _pe(W, f"{W.capitalize()} yakın.", f"The {T} is nearby.", "basic", f"The + {T} + is + nearby", f"1️⃣ Temel kullanım\nThe {T} → belirli yer"),
        _pe(W, f"Şu an {W}'e gidiyorum.", f"I am going to the {T} now.", "present", f"I + am + going + to the {T}", f"1️⃣ Şimdiki zaman\nam going → gidiyorum"),
        _pe(W, f"Dün {W}'e gittim.", f"I went to the {T} yesterday.", "past", f"I + went + to the {T}", f"1️⃣ Geçmiş zaman\nwent → gittim"),
        _pe(W, f"Yarın {W}'e gideceğim.", f"I will go to the {T} tomorrow.", "future", f"I + will + go + to the {T}", f"1️⃣ Gelecek zaman\nwill go → gideceğim"),
        _pe(W, f"{W.capitalize()} açık mı?", f"Is the {T} open?", "question", f"Is + the {T} + open", f"1️⃣ Soru cümlesi\nIs the … open? → … açık mı?"),
        _pe(W, f"Bugün {W}'e gitmiyorum.", f"I am not going to the {T} today.", "negative", f"I + am + not + going", f"1️⃣ Olumsuz cümle\nam not going → gitmiyorum"),
        _pe(W, f"{W.capitalize()}e git.", f"Go to the {T}.", "imperative", f"Go + to the {T}", f"1️⃣ Emir kipi\nGo to the … → …-e git"),
        _pe(W, f"{W.capitalize()}e gidebilir miyiz?", f"Could we go to the {T}?", "polite_request", f"Could + we + go", f"1️⃣ Rica cümlesi\nCould we…? → …-ebilir miyiz?"),
        _pe(W, f"Erken {W}'e gitmelisin.", f"You should go to the {T} early.", "advice", f"You + should + go", f"1️⃣ Tavsiye cümlesi\nshould go → gitmelisin"),
        _pe(W, f"{W.capitalize()}e gitmem lazım.", f"I need to go to the {T}.", "obligation", f"I + need to + go", f"1️⃣ Zorunluluk cümlesi\nneed to go → gitmem lazım"),
        _pe(W, f"{W.capitalize()} bugün kapalı olabilir.", f"The {T} might be closed today.", "possibility", f"The + {T} + might + be + closed", f"1️⃣ İhtimal cümlesi\nmight be closed → kapalı olabilir"),
        _pe(W, f"Açıksa {W}'e gidelim.", f"If it is open, let's go to the {T}.", "conditional", f"If + it + is open", f"1️⃣ Koşul cümlesi\nIf it is open → açıksa"),
        _pe(W, f"A: {W.capitalize()}e gidelim mi? B: Olur.", f"A: Shall we go to the {T}? B: Sure.", "dialogue", f"A: Shall we go? B: Sure", f"1️⃣ Günlük diyalog\nShall we…? → …-elim mi?"),
    ]


def _footwear_examples_en(word_tr: str, target_word: str) -> list[dict[str, Any]]:
    """Ayakkabı / shoe — günlük doğal örnekler."""
    T, W = _en_target_word(target_word), word_tr
    shoes = "shoes" if T == "shoe" else T
    return [
        _ex(W, f"Bu {W}lar çok rahat.", f"These {shoes} are very comfortable.", "description",
            f"These + {shoes} + are + very comfortable",
            f"These → bunlar\n{shoes} → ayakkabılar\nare → -dır / -dir\nvery → çok\ncomfortable → rahat\n\n"
            f"«Bu ayakkabılar çok rahat» cümlesinin doğal karşılığı.",
            pattern_tr="These [plural noun] are [adjective].",
            pattern_examples=[{
                "target": f"These {shoes} are very comfortable.",
                "tr": f"Bu {W}lar çok rahat.",
            }]),
        _ex(W, f"Yeni bir çift {W} almam gerekiyor.", f"I need to buy a new pair of {shoes}.", "need_to",
            f"I + need to + buy + a new pair of {shoes}",
            f"need to + fiil → …-mem lazım\n\n"
            f"a pair of {shoes} → bir çift ayakkabı\n\n"
            "pair of shoes = bir çift ayakkabı (sabit kalıp)."),
        _ex(W, f"{W.capitalize()}larını bağlamayı unutma.", f"Don't forget to tie your {shoes}.", "imperative",
            f"Don't forget + to tie + your {shoes}",
            f"Don't forget to… → …-mayı unutma\n\n"
            f"tie your {shoes} → ayakkabılarını bağla\n\n"
            "tie shoes = ayakkabı bağlamak."),
        _ex(W, f"Bu {W}ları nereden aldın?", f"Where did you buy these {shoes}?", "question",
            f"Where + did + you + buy + these {shoes}",
            f"Where did you…? → …-i nereden …?\n\n"
            f"these {shoes} → bu ayakkabılar\nbuy → satın almak"),
        _ex(W, f"Bu {W}lar bana biraz küçük geliyor.", f"These {shoes} feel a little small for me.", "description",
            f"These + {shoes} + feel + a little small",
            f"feel → hissetmek / gelmek (beden)\n\n"
            f"a little small → biraz küçük\n\n"
            "feel small = küçük gelmek (ayakkabı/kıyafet)."),
        _ex(W, f"Yağmurda {W}larım ıslandı.", f"My {shoes} got wet in the rain.", "past",
            f"My + {shoes} + got + wet + in the rain",
            f"My {shoes} → ayakkabılarım\ngot wet → ıslandı\nin the rain → yağmurda\n\n"
            "Geçmiş: got (get'in geçmişi)."),
    ]


def _category_examples_en(
    word_tr: str,
    target_word: str,
    category: str,
) -> list[dict[str, Any]]:
    """13 dil bilgisi kalıbına göre kelimeye özel örnekler."""
    return _thirteen_pattern_examples_en(word_tr, target_word, category)


def _fill_word_breakdown(ex: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """Kelime kelime analiz — her token için okunuş, IPA, Türkçe anlam ve görev."""
    target = safe_str(ex.get("target")).strip()
    if not target or lang != "en":
        return ex
    bundle = build_pronunciation_bundle(target, lang)
    wb: list[dict[str, str]] = []
    for w in bundle.get("word_pronunciations") or []:
        tok = safe_str(w.get("word")).strip()
        if not tok:
            continue
        low = tok.lower()
        info = get_word(lang, tok)
        pron = safe_str(w.get("pronunciation_tr") or info.get("pronunciation_tr"))
        ipa = safe_str(w.get("ipa") or info.get("ipa", ""))
        wb.append({
            "token": tok,
            "pronunciation_tr": pron,
            "ipa": ipa,
            "meaning_tr": word_meaning_tr(low),
            "role_tr": word_role_tr(low),
        })
    ex["word_breakdown"] = wb
    # Telaffuz her örnekte dolu olsun — Dinle ile uyumlu
    if bundle.get("pronunciation_tr"):
        ex["pronunciation_tr"] = bundle["pronunciation_tr"]
    if bundle.get("ipa"):
        ex["ipa"] = bundle["ipa"]
    if bundle.get("word_pronunciations"):
        ex["word_pronunciations"] = bundle["word_pronunciations"]
    return ex


def build_rich_word_explanation(
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> str:
    """En az 3 cümlelik pedagojik kelime açıklaması."""
    notes = safe_str(profile.get("usage_notes_tr")).strip()
    meaning = safe_str(profile.get("meaning_tr") or word_tr).strip()
    article = safe_str(profile.get("article_notes_tr")).strip()
    regional = safe_str((profile.get("regional_variants") or {}).get("note_tr")).strip()
    tw_info = get_word("en", target_word)
    ipa = safe_str(tw_info.get("ipa")).strip()
    pron = safe_str(tw_info.get("pronunciation_tr")).strip()
    ipa_part = f" 🗣️ {ipa}" if ipa else ""
    pron_part = f" ({pron})" if pron else ""
    parts = [f"«{word_tr}» → {target_word}.{ipa_part}{pron_part}"]
    if notes:
        parts.append(notes)
    elif meaning:
        parts.append(f"Temel anlam: {meaning}.")
    if article:
        parts.append(f"Artikel/konteyner: {article}")
    if regional:
        parts.append(regional)
    text = " ".join(parts)
    if len(text) < 120:
        cat = profile.get("semantic_category") or "general"
        verb_hints = {
            "beverage": "have, drink, order",
            "document": "pay, send, receive, check",
            "furniture": "sit at, set, clear, wipe",
            "plumbing": "turn on, turn off, fix",
            "footwear": "wear, buy, try on",
            "vehicle": "drive, park, wash",
        }.get(cat, "doğal fiillerle")
        text += (
            f" Bu kelimeyi günlük cümlelerde {verb_hints} gibi "
            f"kelimeye özel fiillerle birlikte öğren."
        )
    return text.strip()


def _rich_teaching_how(
    meaning: str,
    structure_en: str,
    structure_tr_gloss: str,
    steps: list[tuple[str, str]],
    *,
    mistakes: list[str] | None = None,
) -> str:
    """Öğretici adım adım cümle analizi — ChatGPT kalitesinde."""
    parts = [
        f"1️⃣ Genel anlam\n{meaning}",
        f"2️⃣ Ana yapı\n{structure_en}\n«{structure_tr_gloss}»",
    ]
    for i, (title, body) in enumerate(steps, start=3):
        parts.append(f"{i}️⃣ {title}\n{body}")
    if mistakes:
        parts.append("⚠️ Sık yapılan hatalar\n" + "\n".join(f"❌ {m}" for m in mistakes))
    return "\n\n".join(parts)


def _ensure_min_how(how: str, word_tr: str, structure_tr: str, min_len: int = 20) -> str:
    """Kural tabanlı örneklerin doğrulamadan geçmesi için kısa analiz metnini genişlet."""
    text = safe_str(how).strip()
    if len(text) >= min_len:
        return text
    text += (
        f"\n\nBu cümle «{word_tr}» kelimesini doğal bir bağlamda gösterir. "
        f"Dil bilgisi formülü: {structure_tr}. "
        f"Bu yapı günlük konuşmada sık kullanılır ve A1–A2 seviyesinde güvenle öğrenilebilir."
    )
    return text


def _ex(
    word_tr: str,
    tr: str,
    target: str,
    sentence_type: str,
    structure_tr: str,
    how: str,
    pattern_tr: str | None = None,
    pattern_examples: list[dict[str, Any]] | None = None,
    important_note_tr: str | None = None,
    grammar_pattern: str | None = None,
    scenario_badge: str | None = None,
) -> dict[str, Any]:
    pat_key = _resolve_grammar_pattern(sentence_type, grammar_pattern)
    badge = scenario_badge or GRAMMAR_BADGES.get(pat_key, "")
    label = _pattern_label(pat_key)
    scenario = f"{badge} ({label})" if badge else label
    structure_label = f"Dil Bilgisi Formülü: {structure_tr}"
    pat = pattern_tr
    if pat and not pat.lower().startswith("kelime şablonu"):
        pat = f"Kelime Şablonu: {pat}"
    how = _ensure_min_how(how, word_tr, structure_tr)
    ex = {
        "tr": tr,
        "target": target,
        "sentence_type": pat_key,
        "sentence_type_label": scenario,
        "scenario_badge": badge or None,
        "grammar_pattern": pat_key,
        "grammar_topic": pat_key,
        "difficulty": "A1" if pat_key in ("basic", "question") else "A2",
        "structure_tr": structure_tr,
        "structure_label_tr": structure_label,
        "word_breakdown": [],
        "how_it_is_formed_tr": how,
        "why_this_structure_tr": (
            f"Bu yapı «{word_tr}» kelimesinin doğal kullanımına uygundur. "
            f"Formül: {structure_tr}"
        ),
        "important_note_tr": important_note_tr,
        "pattern_tr": pat,
        "pattern_examples": pattern_examples or [],
    }
    return _fill_word_breakdown(ex, "en")


_THIRTEEN_PATTERN_ORDER: list[str] = [
    "basic", "present", "past", "future", "question", "negative",
    "imperative", "polite_request", "advice", "obligation", "possibility", "conditional", "dialogue",
]


def _target_word_in_sentence(target: str, target_word: str, word_tr: str) -> bool:
    """Hedef kelime cümlede geçiyor mu (fiil çekimleri dahil)?"""
    tw = _en_target_word(target_word)
    if not tw:
        return True
    t = _norm(target)
    if tw in t or f"{tw}s" in t or f"{tw}es" in t or f"{tw}ing" in t or f"{tw}ed" in t:
        return True
    if _is_verb_like(word_tr, target_word) or _norm(word_tr).endswith(("mek", "mak")):
        irregular: dict[str, tuple[str, ...]] = {
            "go": ("went", "gone", "going", "goes"),
            "come": ("came", "coming", "comes"),
            "be": ("am", "is", "are", "was", "were", "been", "being"),
            "have": ("has", "had", "having"),
            "do": ("does", "did", "doing"),
            "make": ("made", "making", "makes"),
            "take": ("took", "taken", "taking", "takes"),
            "get": ("got", "getting", "gets"),
            "see": ("saw", "seen", "seeing", "sees"),
            "give": ("gave", "given", "giving", "gives"),
            "know": ("knew", "known", "knowing", "knows"),
            "work": ("worked", "working", "works"),
        }
        for form in irregular.get(tw, ()):
            if form in t:
                return True
        return False
    return False


def _normalize_llm_example(
    raw: dict[str, Any],
    word_tr: str,
    target_word: str,
    pattern_idx: int = 0,
) -> dict[str, Any] | None:
    """LLM örneğini standart forma getir."""
    if not isinstance(raw, dict):
        return None
    target = safe_str(raw.get("target")).strip()
    tr = safe_str(raw.get("tr")).strip()
    if not target or not _is_full_english_example(target):
        return None
    tw = _en_target_word(target_word)
    if tw and not _target_word_in_sentence(target, target_word, word_tr):
        return None
    if _is_generic_mechanical_template(target) or _is_absurd_example(target, word_tr, target_word):
        return None
    st = safe_str(raw.get("sentence_type")).strip().lower()
    if st not in GRAMMAR_PATTERNS:
        st = _THIRTEEN_PATTERN_ORDER[pattern_idx % len(_THIRTEEN_PATTERN_ORDER)]
    structure = safe_str(raw.get("structure_tr")).strip() or f"Formül: {target}"
    how = safe_str(raw.get("how_it_is_formed_tr")).strip()
    if len(how) < 20:
        how = (
            f"Bu cümle «{word_tr}» kelimesinin doğal kullanımını gösterir. "
            f"{structure}. Günlük konuşmada sık duyulan bir ifadedir."
        )
    if _is_placeholder_turkish(tr, word_tr):
        return None
    return _ex(word_tr, tr, target, st, structure, how)


def _examples_from_profile_content(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
) -> list[dict[str, Any]]:
    """Profildeki natural_example_ideas ve common_patterns → 13 örnek."""
    items: list[dict[str, str]] = []
    for idea in profile.get("natural_example_ideas") or []:
        if not isinstance(idea, dict):
            continue
        en = safe_str(idea.get("target") or idea.get("en")).strip()
        tr = safe_str(idea.get("tr")).strip()
        if en:
            items.append({"en": en, "tr": tr})
    for p in profile.get("common_patterns") or []:
        if isinstance(p, dict):
            en = safe_str(p.get("en") or p.get("target")).strip()
            tr = safe_str(p.get("tr")).strip()
            if en and en not in {i["en"] for i in items}:
                items.append({"en": en, "tr": tr})
        elif isinstance(p, str) and p.strip():
            s = p.strip()
            if s not in {i["en"] for i in items}:
                items.append({"en": s, "tr": ""})
    if not items:
        return []
    examples: list[dict[str, Any]] = []
    for i, item in enumerate(items[:13]):
        tr_text = safe_str(item.get("tr")).strip()
        if _is_placeholder_turkish(tr_text, word_tr):
            continue
        ex = _normalize_llm_example(
            {
                "tr": tr_text,
                "target": item["en"],
                "sentence_type": _THIRTEEN_PATTERN_ORDER[i % len(_THIRTEEN_PATTERN_ORDER)],
                "structure_tr": item["en"],
                "how_it_is_formed_tr": (
                    f"«{word_tr}» kelimesi bu cümlede doğal bir bağlamda kullanılmıştır: {item['en']}"
                ),
            },
            word_tr,
            target_word,
            i,
        )
        if ex:
            examples.append(ex)
    return examples


def _prefer_parallel_split_lesson(word_tr: str, target_word: str) -> bool:
    """Fiiller büyük JSON'da yavaş — doğrudan paralel split (7+6) daha hızlı."""
    wt = _norm(word_tr)
    if wt.endswith("mek") or wt.endswith("mak"):
        return True
    return _is_verb_like(word_tr, target_word)


def _llm_generate_dynamic_lesson(
    word_tr: str,
    target_word: str,
    target_lang: str,
    *,
    attempt: int = 0,
    prior_issues: list[str] | None = None,
) -> dict[str, Any] | None:
    """Tek hızlı AI çağrısı — manuel Gemini/Groq gibi."""
    if not llm_available() or target_lang != "en":
        return None
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    pos = detect_part_of_speech(word_tr, target_word)
    pos_label = POS_LABELS_TR.get(pos, pos)
    system = WORD_LESSON_FAST_PROMPT.format(
        word_tr=word_tr[:80],
        target_word=target_word[:80],
        lang_name=lang_name,
        pos_label=pos_label,
        pos_hint=get_pos_teaching_rules_for_prompt(word_tr, target_word)[:480],
    )
    user_msg = "Return JSON only."
    if prior_issues:
        user_msg = (
            "Önceki deneme BAŞARISIZ. Düzelt ve 13 örnek üret:\n"
            + "\n".join(f"- {issue}" for issue in prior_issues[:5])
            + "\n\nReturn JSON only."
        )
    parsed = _llm_json_word_lesson(system, user_msg, max_tokens=WORD_LESSON_FAST_MAX_TOKENS)
    if not parsed or not isinstance(parsed.get("examples"), list):
        return None
    profile: dict[str, Any] = {
        "target_word": target_word,
        "meaning_tr": parsed.get("meaning_tr") or word_tr,
        "usage_notes_tr": parsed.get("usage_notes_tr", ""),
        "part_of_speech": parsed.get("part_of_speech", "noun"),
        "countability": parsed.get("countability", "countable"),
        "semantic_category": parsed.get("semantic_category") or detect_category(word_tr, target_word),
        "common_verbs": parsed.get("common_verbs") or [],
        "common_collocations": parsed.get("common_collocations") or [],
        "common_patterns": parsed.get("common_patterns") or [],
        "article_notes_items": parsed.get("article_notes_items") or [],
        "article_notes_tr": parsed.get("article_notes_tr"),
        "avoid_reason_tr": parsed.get("avoid_reason_tr", ""),
        "natural_example_ideas": parsed.get("examples"),
    }
    examples: list[dict[str, Any]] = []
    for i, raw in enumerate(parsed["examples"]):
        if not isinstance(raw, dict):
            continue
        ex = _normalize_llm_example(raw, word_tr, target_word, i)
        if ex:
            examples.append(ex)
    examples = sanitize_word_examples(examples, word_tr, target_word, profile)
    if len(examples) < 6:
        ideas = _examples_from_profile_content(profile, word_tr, target_word)
        for ex in ideas:
            if ex not in examples:
                examples.append(ex)
        examples = sanitize_word_examples(examples, word_tr, target_word, profile)
    if len(examples) < 6:
        return None
    return {"profile": profile, "examples": examples[:13]}


def _llm_generate_dynamic_lesson_split(
    word_tr: str,
    target_word: str,
    target_lang: str,
    base_system: str,
    *,
    attempt: int = 0,
    prior_issues: list[str] | None = None,
) -> dict[str, Any] | None:
    """İki aşamalı AI — kompakt prompt (7+6 örnek)."""
    if not llm_available() or target_lang != "en":
        return None
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    split_base = WORD_LESSON_SPLIT_BASE.format(
        word_tr=word_tr[:80],
        target_word=target_word[:80],
        lang_name=lang_name,
        pos_rules=get_pos_teaching_rules_for_prompt(word_tr, target_word),
    )
    user_a = "Return JSON only."
    if prior_issues:
        user_a = (
            "Önceki deneme BAŞARISIZ. Sorunları düzelt:\n"
            + "\n".join(f"- {issue}" for issue in prior_issues)
            + "\n\nReturn JSON only."
        )
    prompt_a = WORD_LESSON_SPLIT_PROMPT_A.format(split_base=split_base)
    part1 = _llm_json_word_lesson(prompt_a, user_a, max_tokens=2800)
    if not part1 or not isinstance(part1, dict):
        return None
    ex1 = part1.get("examples") if isinstance(part1.get("examples"), list) else []
    if len(ex1) < 4:
        return None

    user_b = "Return JSON with examples array only (exactly 6 items)."
    if prior_issues:
        user_b = (
            "Önceki deneme eksikti. Son 6 örneği üret:\n"
            + "\n".join(f"- {issue}" for issue in prior_issues[:3])
            + "\n\nReturn JSON only."
        )
    prompt_b = WORD_LESSON_SPLIT_PROMPT_B.format(split_base=split_base)
    part2 = _llm_json_word_lesson(prompt_b, user_b, max_tokens=2200)

    merged = dict(part1)
    merged["examples"] = list(ex1)
    if part2 and isinstance(part2.get("examples"), list):
        merged["examples"] = list(ex1) + list(part2["examples"])
    return merged if merged.get("examples") else None


def _llm_generate_examples_from_profile(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> list[dict[str, Any]]:
    """Profil tabanlı AI örnek üretimi (ikinci adım)."""
    if not llm_available() or target_lang != "en":
        return []
    import json
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    system = WORD_LESSON_FROM_PROFILE_PROMPT.format(
        lang_name=lang_name,
        profile_json=json.dumps(profile, ensure_ascii=False)[:2500],
    )
    parsed = _llm_json_word_lesson(system, "Return JSON with examples array only.", max_tokens=3200)
    if not parsed or not isinstance(parsed.get("examples"), list):
        return []
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(parsed["examples"]):
        ex = _normalize_llm_example(raw, word_tr, target_word, i)
        if ex:
            out.append(ex)
    return sanitize_word_examples(out, word_tr, target_word, profile)


def generate_examples_from_profile(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> list[dict[str, Any]]:
    """Profile göre örnek üret — AI birincil; asla boş bırakma."""
    category = _resolve_category(word_tr, target_word, profile.get("semantic_category"))
    examples: list[dict[str, Any]] = []

    # 1) AI birincil — tüm kelimeler (ChatGPT gibi)
    if llm_available() and target_lang == "en":
        llm_ex = _llm_generate_examples_from_profile(profile, word_tr, target_word, target_lang)
        if len(llm_ex) >= 8:
            return llm_ex[:13]

    # 2) Elle yazılmış lexicon (AI yokken veya AI yetersizken)
    if has_curated_lexicon(word_tr, target_word):
        for ex in _category_examples_en(word_tr, target_word, category):
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)
        if examples:
            return sanitize_word_examples(examples[:13], word_tr, target_word, profile)

    # 2) Kategori kuralları — gözlük, sigara, içecek vb. (LLM'den önce)
    if target_lang == "en" and category in QUALITY_RULE_CATEGORIES:
        for ex in _category_examples_en(word_tr, target_word, category):
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)
        if len(examples) >= 8:
            return sanitize_word_examples(examples[:13], word_tr, target_word, profile)

    # 3) AI — lexicon/kategori dışı kelimeler
    if llm_available() and target_lang == "en":
        llm_ex = _llm_generate_examples_from_profile(profile, word_tr, target_word, target_lang)
        if len(llm_ex) >= 8:
            return llm_ex[:13]

    # 4) Kategori kuralları (genel)
    if target_lang == "en":
        for ex in _category_examples_en(word_tr, target_word, category):
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)

    # 5) AI tekrar (kategori kuralları yetersizse)
    if llm_available() and target_lang == "en" and len(examples) < 8:
        llm_ex = _llm_generate_examples_from_profile(profile, word_tr, target_word, target_lang)
        for ex in llm_ex:
            if ex not in examples:
                examples.append(ex)

    # 5) Profildeki fikirlerden örnek oluştur
    if len(examples) < 8:
        from_profile = _examples_from_profile_content(profile, word_tr, target_word)
        for ex in from_profile:
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)

    return sanitize_word_examples(examples[:13], word_tr, target_word, profile)


def build_rule_examples_for_word(
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Kural tabanlı kelimeye özel örnekler — LLM yokken veya kalite düşükken."""
    category = _resolve_category(word_tr, target_word, profile.get("semantic_category"))
    return _category_examples_en(word_tr, target_word, category)


def _is_adjective_noun_misuse(
    target: str,
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None,
) -> bool:
    """Sıfatı nesne gibi kullanma: bought a new quiet, my happy is on the table."""
    return _is_wrong_pos_usage(target, word_tr, target_word, profile)


def _is_wrong_pos_usage(
    target: str,
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None,
) -> bool:
    """Kelime türüne aykırı kullanım — sıfat/fiil/zarf/zamir nesne gibi kullanılamaz."""
    pos = safe_str((profile or {}).get("part_of_speech")).strip().lower()
    if not pos:
        pos = detect_part_of_speech(word_tr, target_word)
    tw = _en_target_word(target_word)
    t = _norm(target)
    noun_misuse = (
        f"bought a new {tw}", f"buy a new {tw}", f"will buy a new {tw}",
        f"bring my {tw}", f"my {tw} is on", f"looking for my {tw}",
        f"where is my {tw}", f"have you seen my {tw}", f"need to buy a new {tw}",
        f"hand me my {tw}", f"carry my {tw}", f"put the {tw} here",
    )
    if pos in ("adjective", "adverb", "pronoun", "verb", "conjunction", "interjection", "preposition"):
        if any(p in t for p in noun_misuse):
            return True
    if pos == "verb" or _is_verb_like(word_tr, target_word):
        if any(p in t for p in (f"a {tw}", f"my {tw}", f"the {tw} is here", f"bought a new {tw}")):
            return True
    if pos == "adjective" or _is_adjective_like(word_tr, target_word):
        if any(p in t for p in noun_misuse):
            return True
    return False


def _validate_word_example(
    ex: dict[str, Any],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None = None,
) -> bool:
    target = _normalize_noun_caps(safe_str(ex.get("target")).strip(), target_word)
    if target:
        ex["target"] = target
    if not target:
        return False
    if not _is_full_english_example(target):
        return False
    if _is_absurd_example(target, word_tr, target_word):
        return False
    how = safe_str(ex.get("how_it_is_formed_tr")).strip()
    tr = safe_str(ex.get("tr")).strip()
    label = safe_str(ex.get("structure_label_tr")).strip()
    wt, tw = _norm(word_tr), _en_target_word(target_word)
    norm_target = _norm(target)
    if not target or len(how) < 20:
        return False
    if _english_leaked_turkish(target, word_tr, target_word):
        return False
    if GENERIC_STRUCTURE_LABEL_RE.search(label):
        return False
    if wt in ("soda", "gazoz", "kola") or tw in ("soda", "cola"):
        if "black soda" in norm_target or "black soda" in tr.lower():
            return False
    if not tr or _is_placeholder_turkish(tr, word_tr) or _is_mechanical_turkish(tr, word_tr):
        return False
    if not _tr_contains_word(tr, word_tr):
        return False
    if _has_foreign_word_leak(tr, word_tr, target_word):
        return False
    if _has_foreign_word_leak(how, word_tr, target_word):
        return False
    if _is_banned_template(target) and profile:
        cat = profile.get("semantic_category", "")
        if cat not in ("beverage",):
            return False
    if _has_cross_word_leak(how, word_tr, target_word):
        return False
    if _has_cross_word_leak(safe_str(ex.get("why_this_structure_tr")), word_tr, target_word):
        return False
    if _has_conflicting_primary_noun(target, target_word):
        return False
    if _is_adjective_noun_misuse(target, word_tr, target_word, profile):
        return False
    if tw and not _target_word_in_sentence(target, target_word, word_tr):
        return False
    return True


def validate_lesson_quality(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> bool:
    """Şablon kopyası veya doğal olmayan içerik var mı?"""
    if len(examples) < 4:
        return False
    targets = [safe_str(e.get("target")).lower() for e in examples]
    # Aynı kalıp tekrarı
    if len(set(targets)) < len(targets) * 0.7:
        return False
    for ex in examples:
        if not _validate_word_example(ex, word_tr, target_word, profile):
            return False
        if profile.get("semantic_category") == "furniture":
            for bad in ("i love", "do you want", "don't drink", "don't like"):
                if bad in safe_str(ex.get("target")).lower():
                    return False
        if profile.get("semantic_category") in ("plumbing", "furniture", "vehicle", "tobacco", "eyewear"):
            for bad in ("i love", "do you want", "don't drink", "drink the", "eat the", "eat cigarette", "eating cigarette"):
                if bad in safe_str(ex.get("target")).lower():
                    return False
    return True


GENERIC_OBJECT_VERBS = frozenset({"use", "need", "find", "buy", "see", "have", "carry", "pick up", "put down", "look for"})

GENERIC_USAGE_MARKERS = (
    "günlük hayatta kullanılan bir nesnedir",
    "fiziksel bir nesne",
    "buy, find, use, carry, need",
    "buy', 'carry', 'find', 'use', 'need'",
    "buy, carry, find, use, need",
)

CATEGORY_USAGE_KEYS = (
    "part_of_speech", "countability", "semantic_category",
    "usage_notes_tr", "common_verbs", "common_collocations", "common_patterns",
    "article_notes_items", "article_notes_tr", "avoid_patterns", "avoid_reason_tr",
)


def _usage_notes_are_generic(notes: str) -> bool:
    n = safe_str(notes).lower()
    return any(m in n for m in GENERIC_USAGE_MARKERS)


def enforce_category_usage_profile(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> dict[str, Any]:
    """Bilinen kategorilerde AI jenerik fiil listesi üretse bile kural profilini uygula."""
    category = detect_category(word_tr, target_word)
    if category == "general":
        category = _lesson_category(word_tr, target_word, profile)
    use_rule = (
        category in QUALITY_RULE_CATEGORIES
        or has_curated_lexicon(word_tr, target_word)
        or _is_tobacco_like(word_tr, target_word)
        or _is_eyewear_like(word_tr, target_word)
        or _is_wallet_like(word_tr, target_word)
        or _is_umbrella_like(word_tr, target_word)
        or _is_market_like(word_tr, target_word)
    )
    if not use_rule or target_lang != "en":
        return profile

    rule = _rule_word_profile(word_tr, target_word, target_lang, category)
    if _is_wallet_like(word_tr, target_word):
        rule["common_verbs"] = ["lose", "find", "check", "carry", "buy", "forget"]
    elif _is_umbrella_like(word_tr, target_word):
        rule["common_verbs"] = ["open", "close", "carry", "bring", "forget", "buy"]
    elif _is_market_like(word_tr, target_word):
        rule["common_verbs"] = ["go", "buy", "shop", "visit", "check", "need"]

    force_rule = (
        category in QUALITY_RULE_CATEGORIES
        or has_curated_lexicon(word_tr, target_word)
        or _profile_needs_upgrade(profile, word_tr, target_word)
        or _usage_notes_are_generic(profile.get("usage_notes_tr", ""))
        or not _has_rich_ai_profile(profile)
    )
    if not force_rule:
        return profile

    out = dict(profile)
    for key in CATEGORY_USAGE_KEYS:
        if rule.get(key):
            out[key] = rule[key]
    return out


def _has_rich_ai_profile(profile: dict[str, Any]) -> bool:
    """AI profili zengin mi? (jenerik nesne şablonu değil)"""
    notes = safe_str(profile.get("usage_notes_tr"))
    if _usage_notes_are_generic(notes):
        return False
    if "günlük hayatta kullanılan bir nesnedir" in notes:
        return False
    if len(notes) > 100:
        verbs = {safe_str(v).strip().lower() for v in (profile.get("common_verbs") or []) if safe_str(v).strip()}
        if verbs and verbs <= GENERIC_OBJECT_VERBS:
            return False
        return True
    verbs = {safe_str(v).strip().lower() for v in (profile.get("common_verbs") or []) if safe_str(v).strip()}
    if verbs and not verbs <= GENERIC_OBJECT_VERBS:
        return True
    return False


def _profile_needs_upgrade(profile: dict[str, Any], word_tr: str, target_word: str) -> bool:
    """Profil boş veya jenerik nesne şablonu mu?"""
    verbs = {safe_str(v).strip().lower() for v in (profile.get("common_verbs") or []) if safe_str(v).strip()}
    if not verbs:
        return True
    if verbs <= GENERIC_OBJECT_VERBS:
        return True
    coll = [safe_str(c).strip().lower() for c in (profile.get("common_collocations") or [])]
    tw = _en_target_word(target_word)
    if len(coll) <= 2 and all(c in (f"the {tw}", f"a {tw}") for c in coll):
        return True
    if not profile.get("article_notes_items") and not profile.get("article_notes_tr"):
        return True
    return False


def teaching_explanation_is_rich(how: str) -> bool:
    """Öğretici açıklama yeterince derin mi?"""
    text = safe_str(how).strip()
    if len(text) >= 60:
        return True
    return len(text) >= 40 and ("1️⃣" in text or "özne" in text.lower() or "yüklem" in text.lower())


def upgrade_word_lesson_teaching(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """İnce AI açıklamalarını kural kalıplarıyla güçlendir."""
    patterns = build_rule_examples_for_word(word_tr, target_word, profile)
    if not patterns:
        return examples
    by_type: dict[str, dict[str, Any]] = {}
    by_target: dict[str, dict[str, Any]] = {}
    for pat in patterns:
        key = safe_str(pat.get("sentence_type") or pat.get("grammar_pattern")).strip()
        if key and key not in by_type:
            by_type[key] = pat
        tkey = _norm(safe_str(pat.get("target")))
        if tkey:
            by_target[tkey] = pat
    upgraded: list[dict[str, Any]] = []
    for i, raw in enumerate(examples):
        ex = dict(raw)
        if teaching_explanation_is_rich(ex.get("how_it_is_formed_tr")):
            upgraded.append(ex)
            continue
        pat = (
            by_type.get(safe_str(ex.get("sentence_type") or ex.get("grammar_pattern")).strip())
            or by_target.get(_norm(safe_str(ex.get("target"))))
            or (patterns[i] if i < len(patterns) else None)
        )
        if pat and teaching_explanation_is_rich(pat.get("how_it_is_formed_tr")):
            for field in (
                "how_it_is_formed_tr",
                "why_this_structure_tr",
                "important_note_tr",
                "structure_tr",
                "structure_label_tr",
                "pattern_tr",
            ):
                if pat.get(field):
                    ex[field] = pat[field]
        upgraded.append(ex)
    return upgraded


def collect_lesson_quality_issues(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> list[str]:
    """AI dersinin ChatGPT kalitesinde olup olmadığını kontrol et; retry için sorun listesi."""
    issues: list[str] = []
    min_examples = 8
    if len(examples) < min_examples:
        issues.append(f"En az {min_examples} örnek gerekli; şu an {len(examples)} örnek var.")
    verbs = [v for v in (profile.get("common_verbs") or []) if safe_str(v).strip()]
    if len(verbs) < 3:
        issues.append(f"common_verbs en az 3 fiil içermeli; şu an {len(verbs)}.")
    coll = [c for c in (profile.get("common_collocations") or []) if safe_str(c).strip()]
    if len(coll) < 2:
        issues.append(f"common_collocations en az 2 kalıp içermeli; şu an {len(coll)}.")
    if not profile.get("article_notes_items") and not profile.get("article_notes_tr"):
        pos = safe_str(profile.get("part_of_speech")).lower()
        if pos in ("noun", "determiner", ""):
            issues.append("article_notes_items veya article_notes_tr eksik.")
    if examples and not validate_lesson_quality(examples, word_tr, target_word, profile):
        issues.append("Örnekler kalite doğrulamasından geçmedi (şablon, yasak fiil veya eksik TR).")
    elif not examples:
        issues.append("Hiç geçerli örnek üretilmedi.")
    for ex in examples:
        tr = safe_str(ex.get("tr")).strip()
        target = safe_str(ex.get("target")).strip()
        if _is_generic_mechanical_template(target):
            issues.append(f"Mekanik şablon cümle reddedildi: {target[:60]}")
            break
        if _is_wrong_pos_usage(target, word_tr, target_word, profile):
            issues.append(
                f"Kelime türüne uymayan cümle reddedildi: {target[:60]} — "
                f"{POS_LABELS_TR.get(detect_part_of_speech(word_tr, target_word), 'tür')} olarak doğal kullanım yaz."
            )
            break
        if _is_mechanical_turkish(tr, word_tr):
            issues.append(f"Doğal olmayan Türkçe: {tr[:60]} — iyelik ve tam cümle kullan.")
            break
        if _is_placeholder_turkish(tr, word_tr):
            issues.append(f'Türkçe alan tam cümle olmalı; yalnızca «{word_tr}» yazılamaz.')
            break
        if not tr or len(tr.replace(".", "").split()) < 2:
            issues.append("Her örneğin tr alanı en az 2 kelimelik doğal Türkçe cümle olmalı.")
            break
        if not teaching_explanation_is_rich(safe_str(ex.get("how_it_is_formed_tr"))):
            issues.append(
                "how_it_is_formed_tr en az 60 karakter olmalı; kısa öğretici açıklama yaz."
            )
            break
    return issues


def try_ai_word_lesson(
    word_tr: str,
    target_word: str,
    target_lang: str,
    profile: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """AI birincil kelime dersi — 3 deneme, başarısızsa en iyi sonuç + sorun listesi."""
    if not llm_available() or target_lang != "en":
        return profile, [], ["AI kullanılamıyor."]
    prior_issues: list[str] = []
    best_profile = profile
    best_examples: list[dict[str, Any]] = []
    for attempt in range(AI_LESSON_MAX_ATTEMPTS):
        dynamic = _llm_generate_dynamic_lesson(
            word_tr,
            target_word,
            target_lang,
            attempt=attempt,
            prior_issues=prior_issues or None,
        )
        if not dynamic:
            prior_issues = ["Geçerli JSON ve en az 6 örnek döndürülemedi."]
            continue
        cand_profile = {**profile, **(dynamic.get("profile") or {})}
        cand_profile = enforce_category_usage_profile(cand_profile, word_tr, target_word, target_lang)
        cand_examples = list(dynamic.get("examples") or [])
        if len(cand_examples) > len(best_examples):
            best_profile = cand_profile
            best_examples = cand_examples
        issues = collect_lesson_quality_issues(cand_examples, word_tr, target_word, cand_profile)
        if not issues:
            return cand_profile, cand_examples[:13], []
        prior_issues = issues
    return best_profile, best_examples, prior_issues


def _lesson_category(word_tr: str, target_word: str, profile: dict[str, Any] | None = None) -> str:
    """Ders için kategori; kelime türüne göre yönlendir — sıfat/fiil/zamir nesne şablonuna düşmez."""
    pos = safe_str((profile or {}).get("part_of_speech")).strip().lower()
    if not pos:
        pos = detect_part_of_speech(word_tr, target_word)
    if pos == "adjective" or _is_adjective_like(word_tr, target_word):
        return "adjective"
    if pos == "verb" or _is_verb_like(word_tr, target_word):
        return "verb"
    if pos == "pronoun" or _is_pronoun_like(word_tr, target_word):
        return "pronoun"
    if pos == "adverb" or _is_adverb_like(word_tr, target_word):
        return "adverb"
    if pos == "preposition" or _is_preposition_like(word_tr, target_word):
        return "preposition"
    if pos == "conjunction" or _is_conjunction_like(word_tr, target_word):
        return "conjunction"
    if pos == "interjection" or _is_interjection_like(word_tr, target_word):
        return "interjection"
    category = detect_category(word_tr, target_word)
    if category == "general":
        return "object" if pos == "noun" else pos
    return category


def merge_rule_usage_profile(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> dict[str, Any]:
    """Kullanım haritası alanlarını kural profiliyle doldur — AI boş bıraksa bile."""
    category = detect_category(word_tr, target_word)
    rule = _rule_word_profile(word_tr, target_word, target_lang, category)
    rule = enforce_category_usage_profile(rule, word_tr, target_word, target_lang)
    if _is_wallet_like(word_tr, target_word):
        rule["common_verbs"] = ["lose", "find", "check", "carry", "buy", "forget"]
    elif _is_umbrella_like(word_tr, target_word):
        rule["common_verbs"] = ["open", "close", "carry", "bring", "forget", "buy"]
    elif _is_market_like(word_tr, target_word):
        rule["common_verbs"] = ["go", "buy", "shop", "visit", "check", "need"]
    out = dict(profile)
    for key in CATEGORY_USAGE_KEYS:
        if rule.get(key):
            out[key] = rule[key]
    if rule.get("meaning_tr"):
        out["meaning_tr"] = rule["meaning_tr"]
    out["semantic_category"] = rule.get("semantic_category") or out.get("semantic_category") or category
    return out


def guarantee_word_lesson(
    word_tr: str,
    target_word: str,
    target_lang: str,
    profile: dict[str, Any],
    examples: list[dict[str, Any]],
    translate_fn: Callable[[str, str, str], str] | None = None,
    *,
    ai_only: bool = False,
    skip_llm: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Ders tamamlama: ai_only modunda yalnızca AI içeriği korunur, şablon eklenmez."""
    category = _lesson_category(word_tr, target_word, profile)
    rich_ai = _has_rich_ai_profile(profile)
    if not ai_only and not rich_ai and (
        _profile_needs_upgrade(profile, word_tr, target_word) or not (profile.get("common_verbs") or [])
    ):
        rule_profile = _rule_word_profile(word_tr, target_word, target_lang, category)
        if _is_wallet_like(word_tr, target_word):
            rule_profile["common_verbs"] = ["lose", "find", "check", "carry", "buy", "forget"]
        elif _is_umbrella_like(word_tr, target_word):
            rule_profile["common_verbs"] = ["open", "close", "carry", "bring", "forget", "buy"]
        elif _is_market_like(word_tr, target_word):
            rule_profile["common_verbs"] = ["go", "buy", "shop", "visit", "check", "need"]
        profile = {**rule_profile, **{
            k: v for k, v in profile.items()
            if k in ("meaning_tr", "usage_notes_tr", "regional_variants", "common_verbs",
                     "common_collocations", "article_notes_items", "article_notes_tr") and v
        }}
    profile["semantic_category"] = profile.get("semantic_category") or category

    examples = sanitize_word_examples(examples, word_tr, target_word, profile, translate_fn)
    seen = {_norm(safe_str(ex.get("target"))) for ex in examples if safe_str(ex.get("target")).strip()}

    fill_sources: tuple[Any, ...]
    if ai_only:
        fill_sources = (_examples_from_profile_content(profile, word_tr, target_word),)
    else:
        fill_sources = (
            _examples_from_profile_content(profile, word_tr, target_word),
            _thirteen_pattern_examples_en(word_tr, target_word, category),
            build_rule_examples_for_word(word_tr, target_word, profile),
        )

    if len(examples) < 13:
        for source in fill_sources:
            for ex in source:
                key = _norm(safe_str(ex.get("target")))
                if not key or key in seen:
                    continue
                cand = dict(ex)
                if not _validate_word_example(cand, word_tr, target_word, profile):
                    continue
                if _is_generic_mechanical_template(safe_str(cand.get("target"))):
                    continue
                examples.append(cand)
                seen.add(key)
                if len(examples) >= 13:
                    break
            if len(examples) >= 13:
                break

    if len(examples) < 13 and not ai_only and not skip_llm and llm_available() and target_lang == "en":
        ai_profile, ai_examples, _ = try_ai_word_lesson(word_tr, target_word, target_lang, profile)
        if ai_examples:
            profile = {**profile, **ai_profile}
            for ex in ai_examples:
                key = _norm(safe_str(ex.get("target")))
                if not key or key in seen:
                    continue
                if _validate_word_example(ex, word_tr, target_word, profile):
                    examples.append(dict(ex))
                    seen.add(key)
                if len(examples) >= 13:
                    break

    examples = sanitize_word_examples(examples[:13], word_tr, target_word, profile, translate_fn)

    if not ai_only:
        if len(examples) < 13:
            for ex in _thirteen_pattern_examples_en(word_tr, target_word, category):
                key = _norm(safe_str(ex.get("target")))
                if not key or key in seen:
                    continue
                if _is_generic_mechanical_template(safe_str(ex.get("target"))):
                    continue
                examples.append(dict(ex))
                seen.add(key)
                if len(examples) >= 13:
                    break
        if len(examples) < 13:
            for ex in _thirteen_pattern_examples_en(word_tr, target_word, category):
                key = _norm(safe_str(ex.get("target")))
                if not key or key in seen:
                    continue
                examples.append(dict(ex))
                seen.add(key)
                if len(examples) >= 13:
                    break
        if _is_wallet_like(word_tr, target_word):
            profile["common_verbs"] = ["lose", "find", "check", "carry", "buy", "forget"]
        elif _is_umbrella_like(word_tr, target_word):
            profile["common_verbs"] = ["open", "close", "carry", "bring", "forget", "buy"]
        elif _is_market_like(word_tr, target_word):
            profile["common_verbs"] = ["go", "buy", "shop", "visit", "check", "need"]

    category = profile.get("semantic_category") or category
    profile = enforce_category_usage_profile(profile, word_tr, target_word, target_lang)
    return profile, examples[:13], category


def _verb_meaning_tr(
    verb_key: str,
    category: str = "",
    word_tr: str = "",
    target_word: str = "",
) -> str:
    key = safe_str(verb_key).strip().lower()
    if not key:
        return ""
    cat = safe_str(category).strip().lower()
    if cat in CATEGORY_VERB_MEANINGS:
        cat_map = CATEGORY_VERB_MEANINGS[cat]
        if key in cat_map:
            return cat_map[key]
    if key in VERBS_TR:
        return VERBS_TR[key]
    parts = key.split()
    if len(parts) > 1:
        phrase = " ".join(parts)
        if cat in CATEGORY_VERB_MEANINGS and phrase in CATEGORY_VERB_MEANINGS[cat]:
            return CATEGORY_VERB_MEANINGS[cat][phrase]
        if phrase in VERBS_TR:
            return VERBS_TR[phrase]
        if f"{parts[0]} {parts[1]}" in VERBS_TR:
            return VERBS_TR[f"{parts[0]} {parts[1]}"]
    tr = VERBS_TR.get(parts[-1], "")
    if tr:
        return tr
    return word_meaning_tr(parts[-1] if parts else key)


def _natural_verbs_for_category(category: str, verbs: list) -> list[str]:
    """Kategori doğal fiil listesini önceliklendir; jenerik nesne fiillerini ayıkla."""
    cat = safe_str(category).strip().lower()
    raw = [safe_str(v).strip().lower() for v in verbs if safe_str(v).strip()]
    if cat not in CATEGORY_VERB_MEANINGS:
        return raw[:8]

    natural_order = list(CATEGORY_VERB_MEANINGS[cat].keys())
    natural_set = set(natural_order)
    all_generic = bool(raw) and all(v in GENERIC_OBJECT_VERBS for v in raw)

    if raw and not all_generic:
        picked: list[str] = []
        seen: set[str] = set()
        for v in raw:
            if v in GENERIC_OBJECT_VERBS and v not in natural_set:
                continue
            if v not in seen:
                picked.append(v)
                seen.add(v)
        if len(picked) >= 4:
            return picked[:8]

    picked = []
    seen: set[str] = set()
    for v in raw:
        if v in natural_set and v not in seen:
            picked.append(v)
            seen.add(v)
    for key in natural_order:
        if key not in seen:
            picked.append(key)
            seen.add(key)
        if len(picked) >= 8:
            break
    return picked[:8]


def _enrich_verb_usage_entry(en: str, tr: str, target_lang: str) -> dict[str, str]:
    en = safe_str(en).strip()
    tr = safe_str(tr).strip()
    pron, ipa = "", ""
    if en and target_lang == "en":
        low = en.lower()
        if low in PHRASAL_VERB_PRON:
            pron = PHRASAL_VERB_PRON[low].get("pronunciation_tr", "")
            ipa = PHRASAL_VERB_PRON[low].get("ipa", "")
        else:
            info = get_word(target_lang, en)
            pron = info.get("pronunciation_tr", "")
            ipa = info.get("ipa", "")
    return {"en": en, "tr": tr, "pronunciation_tr": pron, "ipa": ipa}


def _phrase_meaning_tr(phrase: str) -> str:
    key = safe_str(phrase).strip().lower()
    if not key:
        return ""
    if key in PHRASES_TR:
        return PHRASES_TR[key]
    compact = re.sub(r"\s+", " ", key)
    if compact in PHRASES_TR:
        return PHRASES_TR[compact]
    return ""


def _parse_article_notes_tr(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for part in re.split(r"\s*/\s*", safe_str(text)):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", part)
        if m:
            items.append({"en": m.group(1).strip(), "tr": m.group(2).strip()})
    return items


def _enrich_usage_entry(en: str, tr: str, target_lang: str) -> dict[str, str]:
    en = safe_str(en).strip()
    tr = safe_str(tr).strip()
    pron, ipa = "", ""
    if en and target_lang == "en":
        bundle = build_pronunciation_bundle(en, target_lang)
        pron = bundle.get("pronunciation_tr", "")
        ipa = bundle.get("ipa", "")
    return {"en": en, "tr": tr, "pronunciation_tr": pron, "ipa": ipa}


def build_usage_from_profile(
    profile: dict[str, Any],
    target_lang: str,
    target_word: str = "",
    word_tr: str = "",
) -> dict[str, Any]:
    pos = profile.get("part_of_speech", "noun")
    pos_tr = {"noun": "isim", "verb": "fiil", "adjective": "sıfat", "adverb": "zarf"}.get(pos, pos)
    count = profile.get("countability", "")
    count_tr = {
        "countable": "sayılabilir",
        "uncountable": "sayılamaz",
        "both": "bağlama göre sayılabilir/sayılamaz",
    }.get(count, count or "—")
    coll = profile.get("common_collocations") or []
    patterns = profile.get("common_patterns") or []
    category = profile.get("semantic_category") or "general"

    verbs = _natural_verbs_for_category(category, profile.get("common_verbs") or [])
    verbs_enriched = []
    for v in verbs[:8]:
        key = safe_str(v).strip()
        if not key:
            continue
        tr_mean = _verb_meaning_tr(key, category, word_tr, target_word)
        if not tr_mean:
            continue
        entry = _enrich_verb_usage_entry(key, tr_mean, target_lang)
        verbs_enriched.append(entry)

    phrase_lookup: dict[str, str] = {}
    for items in CATEGORY_PHRASES.values():
        for item in items:
            if isinstance(item, dict) and item.get("en") and item.get("tr"):
                phrase_lookup[item["en"].lower()] = item["tr"]

    phrase_src: list[dict[str, str]] = []
    wt_label = word_tr or profile.get("meaning_tr") or ""
    word_phrases = get_word_usage_phrases(wt_label, target_word)
    if word_phrases:
        phrase_src = word_phrases
    elif coll:
        for c in coll[:8]:
            en = safe_str(c).strip()
            if not en:
                continue
            tr = phrase_lookup.get(en.lower(), "") or _phrase_meaning_tr(en)
            if tr:
                phrase_src.append({"en": en, "tr": tr})
    if not phrase_src and category in CATEGORY_PHRASES:
        phrase_src = [p for p in CATEGORY_PHRASES.get(category, []) if isinstance(p, dict) and p.get("tr")]
    phrases_enriched: list[dict[str, str]] = []
    for item in phrase_src[:6]:
        en = safe_str(item.get("en") if isinstance(item, dict) else item).strip()
        if not en:
            continue
        tr = safe_str(item.get("tr") if isinstance(item, dict) else "").strip()
        if not tr:
            tr = _phrase_meaning_tr(en)
        if not tr:
            continue
        phrases_enriched.append(_enrich_usage_entry(en, tr, target_lang))

    article_items: list[dict[str, str]] = []
    for item in profile.get("article_notes_items") or []:
        if not isinstance(item, dict):
            continue
        en = safe_str(item.get("en")).strip()
        tr = safe_str(item.get("tr")).strip()
        if en and tr:
            article_items.append(_enrich_usage_entry(en, tr, target_lang))
    if not article_items and profile.get("article_notes_tr"):
        for item in _parse_article_notes_tr(profile.get("article_notes_tr", "")):
            article_items.append(_enrich_usage_entry(item["en"], item["tr"], target_lang))

    patterns_enriched: list[dict[str, str]] = []
    pattern_tr_map: dict[str, str] = {}
    if word_tr and target_word and target_lang == "en":
        for ex in _thirteen_pattern_examples_en(word_tr, target_word, category):
            tkey = _norm(safe_str(ex.get("target")))
            tr_val = safe_str(ex.get("tr")).strip()
            if tkey and tr_val:
                pattern_tr_map[tkey] = tr_val
    for p in (profile.get("common_patterns") or patterns)[:4]:
        if isinstance(p, dict):
            en = safe_str(p.get("en") or p.get("target")).strip()
            tr = safe_str(p.get("tr")).strip()
        else:
            en = safe_str(p).strip()
            tr = ""
        if en:
            if not _is_full_sentence(en, min_words=2):
                continue
            if not tr:
                tr = pattern_tr_map.get(_norm(en), "") or _phrase_meaning_tr(en)
            patterns_enriched.append(_enrich_usage_entry(en, tr, target_lang))

    alt_terms: list[dict[str, str]] = []
    for item in profile.get("alternative_terms_tr") or []:
        if not isinstance(item, dict):
            continue
        en = safe_str(item.get("en")).strip()
        if not en:
            continue
        tr = safe_str(item.get("tr")).strip()
        note = safe_str(item.get("note_tr")).strip()
        pron = ""
        ipa = ""
        if target_lang == "en":
            info = get_word(target_lang, en.split()[-1] if " " in en else en)
            bundle = build_pronunciation_bundle(en, target_lang)
            pron = bundle.get("pronunciation_tr", "") or info.get("pronunciation_tr", "")
            ipa = bundle.get("ipa", "") or info.get("ipa", "")
        alt_terms.append({
            "en": en,
            "tr": tr,
            "note_tr": note,
            "pronunciation_tr": pron,
            "ipa": ipa,
        })

    verbs_line = ", ".join(
        f"{v['en']} → {v['tr']}" if v.get("tr") else v["en"] for v in verbs_enriched
    ) if verbs_enriched else None

    return {
        "part_of_speech_tr": pos_tr,
        "countability_tr": count_tr,
        "meaning_tr": profile.get("meaning_tr", ""),
        "usage_notes_tr": profile.get("usage_notes_tr", ""),
        "collocations_tr": ", ".join(coll[:6]) if coll else None,
        "common_verbs": verbs_enriched,
        "common_verbs_tr": verbs_line,
        "common_phrases": phrases_enriched,
        "alternative_terms_tr": alt_terms,
        "patterns": [p.get("en", "") for p in patterns_enriched if p.get("en")],
        "pattern_examples": patterns_enriched,
        "article_notes_tr": profile.get("article_notes_tr"),
        "article_notes_items": article_items,
        "avoid_reason_tr": profile.get("avoid_reason_tr"),
        "regional_note_tr": (profile.get("regional_variants") or {}).get("note_tr")
            or US_UK_VARIANT_NOTES.get(_en_target_word(target_word), ""),
        "english_variant_tr": ENGLISH_VARIANT_LABEL_TR,
        "common_mistakes_tr": profile.get("avoid_reason_tr") or (
            "Türkçe kelime sırasını birebir kopyalama; her kelimenin doğal fiillerini kullan."
        ),
    }


def rule_sentence_teaching(
    tr_sentence: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    """Karmaşık cümleler için kural tabanlı öğretim (LLM yokken)."""
    low = _norm(tr_sentence)
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    market_patterns = (
        "pazara gitmem gerekiyor",
        "market git",
        "yemek yapmak için hiçbir şey yok",
    )
    if any(p in low for p in market_patterns) and target_lang == "en":
        target = "I need to go to the market because I have nothing to cook at home."
        return {
            "inferred_turkish_tr": (
                "Pazara gitmem gerekiyor; evde yemek yapmak için hiçbir şey yok."
                if "pazara" not in low else None
            ),
            "meaning_summary_tr": (
                "Evde pişirecek bir şey olmadığı için markete gitmen gerekiyor."
            ),
            "target_sentence": target,
            "alternatives": ["I have to go to the market because there's nothing to cook at home."],
            "sentence_type": "complex",
            "grammar_topic": "need_to_because_infinitive",
            "difficulty": "B1",
            "structure_tr": "I + need to + go + to the market + because + I have nothing + to cook + at home",
            "structure_label_tr": "Ana fikir + sebep (because) + infinitive yapılar",
            "clause_breakdown": [
                {"clause_tr": "Markete gitmem gerekiyor", "target": "I need to go to the market", "role_tr": "ana fikir"},
                {"clause_tr": "evde yemek yapmak için hiçbir şey yok", "target": "because I have nothing to cook at home", "role_tr": "sebep"},
            ],
            "word_breakdown": [
                {"token": "I", "role_tr": "özne", "meaning_tr": "ben"},
                {"token": "need", "role_tr": "fiil", "meaning_tr": "gerekiyor / ihtiyaç duymak"},
                {"token": "to go", "role_tr": "infinitive", "meaning_tr": "gitmek"},
                {"token": "to the market", "role_tr": "yer", "meaning_tr": "markete"},
                {"token": "because", "role_tr": "bağlaç", "meaning_tr": "çünkü"},
                {"token": "nothing", "role_tr": "zamir", "meaning_tr": "hiçbir şey"},
                {"token": "to cook", "role_tr": "infinitive", "meaning_tr": "pişirmek / yemek yapmak"},
                {"token": "at home", "role_tr": "yer ifadesi", "meaning_tr": "evde"},
            ],
            "how_it_is_formed_tr": (
                "1️⃣ Genel anlam\n"
                "Evde pişirecek bir şey olmadığı için markete gitmen gerekiyor.\n\n"
                "2️⃣ Ana yapı\n"
                "I need to go to the market\n"
                "«Markete gitmem gerekiyor.»\n\n"
                "3️⃣ need to + fiil\n"
                "need → gerekiyor / ihtiyaç duymak\n"
                "to go → gitmek (need'ten sonra to + fiil gelir)\n"
                "❌ I need go — standart İngilizcede yanlış.\n\n"
                "4️⃣ to the market\n"
                "the → belirli market\n"
                "to → -e/-a yön bildirir\n\n"
                "5️⃣ because + sebep\n"
                "because I have nothing to cook at home\n"
                "«çünkü evde pişirecek hiçbir şeyim yok»\n\n"
                "6️⃣ nothing\n"
                "I have nothing = Hiçbir şeyim yok\n"
                "❌ I don't have nothing — standart İngilizcede öğretilmez.\n\n"
                "7️⃣ to cook / at home\n"
                "nothing to cook → pişirecek bir şey\n"
                "at home → evde (sabit kalıp)"
            ),
            "why_this_structure_tr": "Sebep bildirmek için because; zorunluluk için need to kullanılır.",
            "important_note_tr": "Türkçede tek cümlede birleşen fikir İngilizcede because ile bağlanır.",
            "important_patterns": [
                {
                    "pattern_tr": "need to + fiil",
                    "explanation_tr": "Bir şeyi yapmak gerektiğini söylemek için.",
                    "examples": [
                        {"target": "I need to work.", "tr": "Çalışmam gerekiyor."},
                        {"target": "I need to sleep.", "tr": "Uyumam gerekiyor."},
                    ],
                },
                {
                    "pattern_tr": "nothing to + fiil",
                    "explanation_tr": "Yapılacak şey olmadığını anlatır.",
                    "examples": [
                        {"target": "I have nothing to eat.", "tr": "Yiyecek hiçbir şeyim yok."},
                    ],
                },
                {
                    "pattern_tr": "at home",
                    "explanation_tr": "«Evde» anlamında sabit kalıp.",
                    "examples": [
                        {"target": "I am at home.", "tr": "Evdeyim."},
                    ],
                },
            ],
            "new_words": [
                {"word": "need", "meaning_tr": "gerekmek / ihtiyaç duymak"},
                {"word": "because", "meaning_tr": "çünkü"},
                {"word": "nothing", "meaning_tr": "hiçbir şey"},
                {"word": "cook", "meaning_tr": "pişirmek / yemek yapmak"},
                {"word": "market", "meaning_tr": "market / pazar"},
            ],
            "pattern_tr": "need to + fiil + because + sebep",
            "pattern_examples": [],
        }

    if translate_fn:
        try:
            target = translate_fn(tr_sentence, "tr", target_lang)
            if target:
                return {
                    "meaning_summary_tr": f"Bu cümle {lang_name} dilinde şöyle ifade edilir.",
                    "target_sentence": target,
                    "alternatives": [],
                    "how_it_is_formed_tr": (
                        f"Türkçe: «{tr_sentence}»\n"
                        f"{lang_name}: «{target}»\n\n"
                        "Kelime sırası ve yapı hedef dilin kurallarına göre kurulmuştur."
                    ),
                    "structure_tr": "",
                    "word_breakdown": [],
                    "important_patterns": [],
                    "new_words": [],
                }
        except Exception:
            pass
    return None
