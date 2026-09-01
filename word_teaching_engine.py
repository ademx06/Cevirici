"""Kelimeye özel öğretim motoru — şablon kopyalama yok, bağlama göre analiz."""
from __future__ import annotations

import re
from typing import Any, Callable

from education_engine import LANG_NAMES, _llm_json, llm_available, safe_str
from pronunciation_service import build_pronunciation_bundle, tokenize_en

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
    "go to": "gitmek", "be at": "bulunmak", "visit": "ziyaret etmek",
    "read": "okumak", "charge": "şarj etmek", "answer": "cevaplamak / açmak",
    "knock": "çalmak", "wipe": "silmek", "clear": "toplamak",
}

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
    "object": [
        {"en": "open the window", "tr": "pencereyi açmak"},
        {"en": "close the door", "tr": "kapıyı kapatmak"},
    ],
    "plumbing": [
        {"en": "turn off the faucet", "tr": "musluğu kapatmak"},
        {"en": "the faucet is leaking", "tr": "musluk su sızdırıyor"},
    ],
    "beverage": [
        {"en": "have a coffee", "tr": "kahve içmek / bir kahve almak"},
        {"en": "make coffee", "tr": "kahve yapmak"},
    ],
    "vehicle": [
        {"en": "drive the car", "tr": "arabayı sürmek"},
        {"en": "park the car", "tr": "arabayı park etmek"},
    ],
}

WORD_PROFILE_PROMPT = """Sen uzman bir dil öğretmenisin.
Türkçe kelime: "{word_tr}"
Hedef dil: {lang_name} ({target_lang})
Hedef kelime (çeviri): "{target_word}"

GÖREV: Bu kelimenin hedef dildeki GERÇEK kullanımını analiz et.
Şablon cümle üretme. Başka kelimelerin (coffee, love, want) kalıplarını kopyalama.

JSON döndür:
{{
  "target_word": "...",
  "part_of_speech": "noun|verb|adjective|adverb|phrase|...",
  "countability": "countable|uncountable|both|n/a",
  "semantic_category": "beverage|furniture|food|place|person|action|abstract|other",
  "meaning_tr": "temel Türkçe anlam",
  "usage_notes_tr": "Türkçeden farklar, dikkat edilecekler",
  "common_verbs": ["drink", "have"],
  "common_collocations": ["a cup of coffee", "black coffee"],
  "common_patterns": ["have a coffee", "make coffee"],
  "article_notes_tr": "a/the kullanımı açıklaması veya null",
  "natural_example_ideas": [
    {{"tr": "Türkçe örnek fikir", "target": "Doğal hedef dil cümlesi", "grammar_focus": "kısa not"}}
  ],
  "avoid_patterns": ["I love X", "Do you want X"],
  "avoid_reason_tr": "Bu kalıplar neden uygun değil"
}}"""

WORD_LESSON_FROM_PROFILE_PROMPT = """Sen Türkçe konuşan bir öğrenciye {lang_name} öğreten uzman öğretmensin.

KELİME PROFİLİ:
{profile_json}

GÖREV: Bu profile göre 6-8 TAMAMEN YENİ ve DOĞAL örnek cümle oluştur.
KESİNLİKLE YASAK:
- I love [kelime], Do you want [kelime], You don't drink [kelime] gibi şablonları kelimeye yapıştırmak
- coffee/table gibi başka kelimelerin açıklamalarını kopyalamak
- Türkçeyi kelime kelime İngilizceye çevirmek (ör. masa → I love table)

Her örnek için (Türkçe açıklamalar):
- tr: Türkçe anlam (doğal Türkçe)
- target: hedef dilde doğal cümle
- sentence_type, grammar_topic, difficulty (A1-C1)
- structure_tr, structure_label_tr
- word_breakdown: [{{"token":"...","role_tr":"...","meaning_tr":"..."}}]
- how_it_is_formed_tr: BU cümleye özel, parça parça, neden bu yapı
- why_this_structure_tr
- important_note_tr veya null
- pattern_tr veya null
- pattern_examples: [{{"target":"...","tr":"...","new_words":[{{"word":"...","meaning_tr":"..."}}]}}]

JSON:
{{
  "word_explanation_tr": "...",
  "usage": {{
    "part_of_speech_tr": "...",
    "countability_tr": "...",
    "collocations_tr": "...",
    "common_mistakes_tr": "..."
  }},
  "examples": [...]
}}"""

SENTENCE_TEACHING_V3_PROMPT = """Turkish sentence (user may have minor errors): "{tr_sentence}"
Target language: {lang_name} ({target_lang})

Teach HOW to build this sentence — not just translate.
If Turkish is imperfect, infer intent politely in inferred_turkish_tr.

Return JSON:
{{
  "inferred_turkish_tr": "düzeltilmiş Türkçe veya null",
  "meaning_summary_tr": "cümlenin genel anlamı (1-2 cümle)",
  "target_sentence": "most natural {lang_name}",
  "alternatives": ["optional natural alternative"],
  "sentence_type": "...",
  "grammar_topic": "...",
  "difficulty": "A1-C2",
  "structure_tr": "I + need + to go + ...",
  "structure_label_tr": "Ana yapı özeti",
  "clause_breakdown": [
    {{"clause_tr": "Markete gitmem gerekiyor", "target": "I need to go to the market", "role_tr": "ana fikir"}}
  ],
  "word_breakdown": [
    {{"token":"need","role_tr":"fiil","meaning_tr":"gerekiyor","pronunciation_hint":"ni:d","mini_example_tr":"I need water.","mini_example_target":"..."}}
  ],
  "how_it_is_formed_tr": "Adım adım öğretim: önce genel anlam, sonra yapı, sonra need to / because / nothing / at home gibi parçalar",
  "why_this_structure_tr": "...",
  "important_note_tr": "... or null",
  "important_patterns": [
    {{"pattern_tr": "need to + fiil", "explanation_tr": "...", "examples": [{{"target":"I need to work.","tr":"Çalışmam gerekiyor."}}]}}
  ],
  "new_words": [{{"word":"because","meaning_tr":"çünkü","example_target":"...","example_tr":"..."}}],
  "pattern_tr": "... or null",
  "pattern_examples": []
}}"""

# Bilinen kelime kategorileri (LLM yokken)
KNOWN_CATEGORIES: dict[str, str] = {
    "kahve": "beverage", "coffee": "beverage", "çay": "beverage", "tea": "beverage",
    "su": "beverage", "water": "beverage", "süt": "beverage", "milk": "beverage",
    "masa": "furniture", "table": "furniture", "sandalye": "furniture", "chair": "furniture",
    "musluk": "plumbing", "faucet": "plumbing", "tap": "plumbing",
    "araba": "vehicle", "car": "vehicle", "otomobil": "vehicle",
    "mutlu": "adjective", "happy": "adjective",
    "çalışmak": "verb", "work": "verb", "çalış": "verb",
    "kitap": "object", "book": "object", "telefon": "object", "phone": "object",
    "kapı": "object", "kapi": "object", "door": "object",
    "pencere": "object", "window": "object",
    "kalem": "object", "pen": "object",
    "ev": "place", "home": "place", "market": "place", "pazar": "place",
    "ayakkabı": "footwear", "ayakkabi": "footwear", "shoe": "footwear", "shoes": "footwear",
}

WORD_ICONS: dict[str, str] = {
    "kahve": "☕", "coffee": "☕", "çay": "🍵", "tea": "🍵",
    "masa": "🪑", "table": "🪑", "sandalye": "💺", "chair": "💺",
    "musluk": "🚰", "faucet": "🚰", "tap": "🚰",
    "araba": "🚗", "car": "🚗", "otomobil": "🚗",
    "mutlu": "😊", "happy": "😊",
    "çalışmak": "💼", "work": "💼", "çalış": "💼",
    "ev": "🏠", "home": "🏠", "kitap": "📚", "book": "📚",
    "su": "💧", "water": "💧", "market": "🛒", "pazar": "🛒",
    "kapı": "🚪", "kapi": "🚪", "door": "🚪",
    "pencere": "🪟", "window": "🪟",
    "telefon": "📱", "phone": "📱",
    "kalem": "✏️", "pen": "✏️",
    "ayakkabı": "👟", "ayakkabi": "👟", "shoe": "👟", "shoes": "👟",
}

CATEGORY_ICONS: dict[str, str] = {
    "beverage": "☕", "furniture": "🪑", "plumbing": "🚰", "vehicle": "🚗",
    "adjective": "😊", "verb": "💼", "place": "📍", "object": "📦", "general": "📖",
    "footwear": "👟",
}

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
    """İkon — kelime sözlüğü öncelikli; kategori LLM'den değil kural tabanlı."""
    for w in (_norm(word_tr), _norm(target_word)):
        if w in WORD_ICONS:
            return WORD_ICONS[w]
    cat = detect_category(word_tr, target_word)
    return CATEGORY_ICONS.get(cat, "📖")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", safe_str(s).strip().lower())


def detect_category(word_tr: str, target_word: str) -> str:
    for w in (_norm(word_tr), _norm(target_word)):
        if w in KNOWN_CATEGORIES:
            return KNOWN_CATEGORIES[w]
    return "general"


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


def _tr_contains_word(text: str, word_tr: str) -> bool:
    wt = _norm(word_tr)
    if not wt:
        return True
    t = _norm(text)
    if wt in t:
        return True
    if len(wt) >= 4 and wt[:-1] in t:
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


def sanitize_word_examples(
    examples: list[dict[str, Any]],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Tüm örnekleri doğrula ve iç içe verileri temizle."""
    cleaned: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        if not _validate_word_example(ex, word_tr, target_word, profile):
            continue
        cleaned.append(_sanitize_example_nested(dict(ex), word_tr, target_word))
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
            if known_cat != "general":
                parsed["semantic_category"] = known_cat
            else:
                parsed["semantic_category"] = parsed.get("semantic_category") or known_cat
            return parsed

    return _rule_word_profile(word_tr, target_word, target_lang, category)


def _rule_word_profile(
    word_tr: str,
    target_word: str,
    target_lang: str,
    category: str,
) -> dict[str, Any]:
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
            "usage_notes_tr": f"«{word_tr}» taşıt; drive, park, fix, buy ile doğal kullanılır.",
            "common_verbs": ["drive", "park", "buy", "fix", "wash", "rent"],
            "common_collocations": [f"drive the {target_word}", f"park the {target_word}", "new car"],
            "common_patterns": [f"The {target_word} is...", f"I drive a {target_word}"],
            "article_notes_tr": "a car / the car",
            "avoid_patterns": ["drink the car", "I love car (without context)"],
            "avoid_reason_tr": "Araç fiilleri: sürmek, park etmek, tamir etmek.",
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
        "object": {
            "part_of_speech": "noun",
            "countability": "countable",
            "semantic_category": "object",
            "meaning_tr": word_tr,
            "usage_notes_tr": (
                f"«{word_tr}» sayılabilir bir nesnedir. "
                "open/close, use, need, see gibi fiillerle doğal cümleler kurulur."
            ),
            "common_verbs": ["open", "close", "use", "see", "need", "find", "buy"],
            "common_collocations": [f"the {target_word}", f"a {target_word}", f"open the {target_word}"],
            "common_patterns": [f"The {target_word} is...", f"Can you open the {target_word}?"],
            "article_notes_tr": f"the {target_word.lower()} / a {target_word.lower()}",
            "avoid_patterns": ["I love X", "Do you want X"],
            "avoid_reason_tr": "Her nesne için aynı şablon kullanılmaz; bağlama göre fiil seçilir.",
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
    }
    base = profiles.get(category, {
        "part_of_speech": "noun",
        "countability": "countable",
        "semantic_category": category,
        "meaning_tr": word_tr,
        "usage_notes_tr": f"«{word_tr}» kelimesinin doğal kullanımına göre cümle kurulmalı.",
        "common_verbs": ["use", "have", "need", "want"],
        "common_collocations": [f"the {target_word}", f"a {target_word}"],
        "common_patterns": [f"The {target_word} is here."],
        "article_notes_tr": None,
        "avoid_patterns": ["I love X", "Do you want X"],
        "avoid_reason_tr": "Her kelimeye aynı kalıp uygulanmaz.",
    })
    return {"target_word": target_word, **base}


def _object_examples_en(word_tr: str, target_word: str) -> list[dict[str, Any]]:
    """Nesne kelimeleri — pencere, kapı, kitap, telefon vb. için kelimeye özel örnekler."""
    T, W = _en_target_word(target_word), word_tr
    wt, tw = _norm(word_tr), T

    if wt in ("pencere",) or tw == "window":
        return [
            _ex(W, f"{W.capitalize()} oturma odasında.", f"The {T} is in the living room.", "location",
                f"The + {T} + is + in the living room",
                f"Bu cümlede «{W}» özne.\n\n"
                f"The {T} → belirli pencere\nis → tekil «be» fiili\nin the living room → oturma odasında\n\n"
                f"Türkçede «{W} oturma odasında» — İngilizcede the + is gerekir."),
            _ex(W, f"{W.capitalize()}yi açar mısın?", f"Can you open the {T}?", "request",
                f"Can + you + open + the {T}",
                f"Can you…? → …-ebilir misin?\n\n"
                f"open the {T} → pencereyi açmak\n\n"
                "open + the window çok yaygın bir kalıptır."),
            _ex(W, f"{W.capitalize()}yi kapat lütfen.", f"Please close the {T}.", "action",
                f"Please + close + the {T}",
                f"Emir/kibar rica: Please + fiil\n\n"
                f"close the {T} → pencereyi kapatmak\n\n"
                "close the window = pencereyi kapat."),
            _ex(W, f"{W.capitalize()}den dışarı bak.", f"Look out of the {T}.", "action",
                f"Look + out of + the {T}",
                f"look out of → …-den dışarı bakmak\n\n"
                f"the {T} → pencere\n\n"
                "out of the window = pencereden dışarı."),
            _ex(W, f"{W.capitalize()} temiz mi?", f"Is the {T} clean?", "question",
                f"Is + the {T} + clean",
                f"Soru: Is + özne + sıfat?\n\n"
                f"clean → temiz\n\n"
                f"«{W.capitalize()} temiz mi?» sorusunun karşılığı."),
            _ex(W, f"{W.capitalize()}yi açtım çünkü hava sıcaktı.", f"I opened the {T} because it was hot.", "past",
                f"I + opened + the {T} + because + it was hot",
                f"Geçmiş: opened\n\n"
                f"open the {T} → pencereyi açmak\nbecause → çünkü\n\n"
                "Sebep bildirmek için because kullanılır."),
        ]

    if wt in ("kapı", "kapi") or tw == "door":
        return [
            _ex(W, f"{W.capitalize()} ön tarafta.", f"The {T} is at the front.", "location",
                f"The + {T} + is + at the front",
                f"The {T} → belirli kapı\nat the front → ön tarafta\n\n"
                f"«{W.capitalize()} ön tarafta» anlamını verir."),
            _ex(W, f"{W.capitalize()}yi açar mısın?", f"Can you open the {T}?", "request",
                f"Can + you + open + the {T}",
                f"open the {T} → kapıyı açmak\n\n"
                "Can you open the door? çok yaygın bir rica cümlesidir."),
            _ex(W, f"{W.capitalize()}yi kapat lütfen.", f"Please close the {T}.", "action",
                f"Please + close + the {T}",
                f"close the {T} → kapıyı kapatmak"),
            _ex(W, f"{W.capitalize()}yı çal.", f"Knock on the {T}.", "action",
                f"Knock + on + the {T}",
                f"knock on the {T} → kapıyı çalmak\n\n"
                "knock on the door sabit bir kalıptır."),
            _ex(W, f"{W.capitalize()} kilitli mi?", f"Is the {T} locked?", "question",
                f"Is + the {T} + locked",
                f"locked → kilitli\n\n"
                f"«{W.capitalize()} kilitli mi?» sorusu."),
            _ex(W, f"{W.capitalize()}dan içeri girdik.", f"We came in through the {T}.", "past",
                f"We + came in + through + the {T}",
                f"through the {T} → kapıdan / kapı aracılığıyla\n\n"
                f"came in → içeri girmek"),
        ]

    if wt == "kitap" or tw == "book":
        return [
            _ex(W, f"{W.capitalize()} rafta.", f"The {T} is on the shelf.", "location",
                f"The + {T} + is + on the shelf",
                f"The {T} → belirli kitap\non the shelf → rafta\n\n"
                f"«{W.capitalize()} rafta» anlamını verir."),
            _ex(W, f"Bir {W} okuyorum.", f"I am reading a {T}.", "present_continuous",
                f"I + am + reading + a {T}",
                f"reading → okumak (fiil)\n\n"
                f"a {T} → bir kitap\n\n"
                "❌ riding değil — reading = okumak."),
            _ex(W, f"Bu {W} çok ilginç.", f"This {T} is very interesting.", "description",
                f"This + {T} + is + very interesting",
                f"This {T} → bu kitap\ninteresting → ilginç"),
            _ex(W, f"{W.capitalize()} okumayı seviyorum.", f"I like reading {T}s.", "routine",
                f"I + like + reading + {T}s",
                f"like + fiil-ing → … yapmayı sevmek\n\n"
                f"reading → okumak"),
            _ex(W, f"{W.capitalize()} nerede?", f"Where is the {T}?", "question",
                f"Where + is + the {T}",
                f"Where is…? → … nerede?\n\n"
                f"the {T} → belirli kitap"),
            _ex(W, f"Dün bir {W} bitirdim.", f"I finished a {T} yesterday.", "past",
                f"I + finished + a {T} + yesterday",
                f"finished → bitirdim\n\n"
                f"a {T} → bir kitap"),
        ]

    if wt == "telefon" or tw == "phone":
        return [
            _ex(W, f"{W.capitalize()} cebimde.", f"The {T} is in my pocket.", "location",
                f"The + {T} + is + in my pocket",
                f"The {T} → telefon\nin my pocket → cebimde"),
            _ex(W, f"{W.capitalize()}u şarj et.", f"Charge the {T}.", "action",
                f"Charge + the {T}",
                f"charge the {T} → telefonu şarj etmek"),
            _ex(W, f"{W.capitalize()} çalıyor.", f"The {T} is ringing.", "present_continuous",
                f"The + {T} + is + ringing",
                f"ringing → çalıyor\n\n"
                f"is ringing → şu anda çalıyor"),
            _ex(W, f"{W.capitalize()}u nerede bıraktın?", f"Where did you leave the {T}?", "question",
                f"Where + did + you + leave + the {T}",
                f"leave the {T} → telefonu bırakmak"),
            _ex(W, f"{W.capitalize()}um bozuk.", f"My {T} is broken.", "problem",
                f"My {T} → benim telefonum\nbroken → bozuk"),
            _ex(W, f"{W.capitalize()}u açar mısın?", f"Can you answer the {T}?", "request",
                f"Can + you + answer + the {T}",
                f"answer the {T} → telefonu açmak / cevaplamak"),
        ]

    return [
        _ex(W, f"{W.capitalize()} burada.", f"The {T} is here.", "description",
            f"The + {T} + is + here",
            f"The {T} → belirli {W}\nis → -dir/-dır\nhere → burada\n\n"
            f"«{W.capitalize()} burada» anlamını verir."),
        _ex(W, f"Bir {W} aldım.", f"I bought a {T}.", "past",
            f"I + bought + a {T}",
            f"a {T} → bir {W}\nbought → aldım (buy geçmişi)"),
        _ex(W, f"{W.capitalize()} nerede?", f"Where is the {T}?", "question",
            f"Where + is + the {T}?",
            f"Where is…? → … nerede?\n\n"
            f"the {T} → belirli {W}"),
        _ex(W, f"{W.capitalize()}yi kullanıyorum.", f"I use the {T}.", "routine",
            f"I + use + the {T}",
            f"use the {T} → {W}yi kullanmak"),
        _ex(W, f"{W.capitalize()} lazım.", f"I need the {T}.", "need_to",
            f"I + need + the {T}",
            f"need the {T} → {W}ye ihtiyacım var"),
        _ex(W, f"{W.capitalize()}yi görebiliyor musun?", f"Can you see the {T}?", "question",
            f"Can + you + see + the {T}",
            f"see the {T} → {W}yi görebilmek"),
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
    """Kategori bazlı doğal örnekler — şablon değil, anlama göre."""
    category = _resolve_category(word_tr, target_word, category)
    T, W = _en_target_word(target_word), word_tr
    wt, tw = _norm(word_tr), T

    if category == "furniture" and (wt in ("masa", "sandalye") or tw in ("table", "chair")):
        examples = [
            _ex(W, f"{W.capitalize()} mutfakta.", f"The {T} is in the kitchen.", "location",
                f"The + {T} + is + in the kitchen",
                f"Bu cümlede «{W}» özne.\n\n"
                f"The {T} → belirli {W}\nis → tekil «be» fiili\nin the kitchen → mutfakta\n\n"
                f"Türkçede «{W} mutfakta» — İngilizcede the + is gerekir."),
            _ex(W, f"{W.capitalize()}nın üzerinde kitap var.", f"There is a book on the {T}.", "existence",
                f"There is + a book + on the {T}",
                f"Var/yok: There is…\n\n"
                f"on the {T} → {W}nın üzerinde\n\n"
                "on edatı «üzerinde» anlamı verir."),
            _ex(W, f"Bardakları {W}ya koy.", f"Please put the cups on the {T}.", "action",
                f"Put + the cups + on the {T}",
                f"Emir: fiil ile başlar (Please opsiyonel)\n\n"
                f"put … on the {T} → … {W}nın üzerine koy\n\n"
                "put + nesne + on + yer kalıbı çok yaygın.",
                pattern_tr="Put + nesne + on the [şey]",
                pattern_examples=[{
                    "target": f"Put the book on the {T}.",
                    "tr": f"Kitabı {W}nın üzerine koy.",
                    "new_words": [{"word": "book", "meaning_tr": "kitap"}],
                }]),
            _ex(W, f"{W.capitalize()}da oturduk.", f"We sat at the {T}.", "past",
                f"We + sat + at the {T}",
                f"Geçmiş: sat (sit'in geçmişi)\n\n"
                f"at the {T} → {W}da (oturma bağlamı)\n\n"
                f"«{W.capitalize()}» için at kullanılır, on değil (oturma)."),
            _ex(W, f"{W.capitalize()}yı temizlemem lazım.", f"I need to clean the {T}.", "need_to",
                f"I + need to + clean + the {T}",
                f"need to + fiil → …-mem lazım\n\n"
                f"clean the {T} → {W}yı temizlemek\n\n"
                "❌ I need clean — need to gerekli."),
            _ex(W, f"{W.capitalize()}yı taşıyabilir misin?", f"Can you move the {T}?", "request",
                f"Can + you + move + the {T}",
                f"Can you…? → …-ebilir misin?\n\n"
                f"move the {T} → {W}yı taşımak\n\n"
                f"«{W}» için move doğal bir fiildir."),
        ]
        return examples

    if category == "footwear":
        return _footwear_examples_en(word_tr, target_word)

    if category == "object":
        return _object_examples_en(word_tr, target_word)

    if category == "beverage":
        return [
            _ex(W, f"Sabahları {W} içerim.", f"I drink {T} every morning.", "routine",
                f"I + drink + {T} + every morning",
                f"İçeceklerle drink veya have kullanılır.\n\n"
                f"I → ben\ndrink → içmek\n{T} → {W}\nevery morning → her sabah\n\n"
                "Türkçede «sabahları kahve içerim» — İngilizcede özne I ile başlar."),
            _ex(W, f"Akşam {W} içmek ister misin?", f"Would you like some {T} tonight?", "offer",
                f"Would + you + like + some {T}",
                f"Kibar teklif: Would you like…?\n\n"
                f"some {T} → biraz {W} / {W} (bağlama göre)\n\n"
                "❌ Do you want coffee? daha doğrudan; Would you like daha kibar."),
            _ex(W, f"Bir {W} alabilir miyim?", f"Can I have a {T}?", "request",
                f"Can + I + have + a {T}",
                "Can I have…? kibarca bir şey istemek için.\n\n"
                f"a {T} → bir {W} (porsiyon olarak)\n\n"
                "have burada «almak/istemek» anlamında."),
            _ex(W, f"Siyah {W} sevmem.", f"I don't like black {T}.", "negative",
                f"I + don't + like + black {T}",
                f"Olumsuz: don't + fiil(yalın)\n\n"
                f"black {T} → siyah {W}\n\n"
                "like içecek tatları için kullanılabilir; love değil."),
            _ex(W, f"O {W} yapıyor.", f"She is making {T}.", "present_continuous",
                f"She + is + making + {T}",
                f"Şimdiki zaman: is + fiil-ing\n\n"
                f"making {T} → {W} yapıyor/hazırlıyor\n\n"
                "make coffee çok yaygın bir kalıptır."),
            _ex(W, f"İki {W} içtim.", f"I had two {T}s.", "past",
                f"I + had + two {T}s",
                f"Geçmiş: had\n\n"
                f"two {T}s → iki {W} (sayılabilir porsiyon)\n\n"
                "İçecek madde olarak sayılamaz ama «iki kahve» porsiyon olarak sayılabilir."),
        ]

    if category == "plumbing":
        return [
            _ex(W, f"{W.capitalize()} mutfakta.", f"The {T} is in the kitchen.", "location",
                f"The + {T} + is + in the kitchen",
                f"The → belirli musluk\n{T} → {W}\nis → tekil be fiili\nin the kitchen → mutfakta"),
            _ex(W, f"{W.capitalize()} su sızdırıyor.", f"The {T} is leaking.", "problem",
                f"The + {T} + is + leaking",
                f"1️⃣ Genel anlam: Musluk şu anda su sızdırıyor.\n\n"
                f"The → belirli musluk\nis → tekil yardımcı fiil\nleaking → sızdırıyor (is + fiil-ing)\n\n"
                "❓ Neden -ing? Devam eden durum için Present Continuous yapısı.\n\n"
                "Genel yapı: Subject + is/are + verb-ing",
                pattern_tr="The [place] faucet is [verb-ing].",
                pattern_examples=[{
                    "target": "The bathroom faucet is leaking.",
                    "tr": "Banyo musluğu su sızdırıyor.",
                    "new_words": [
                        {"word": "bathroom", "meaning_tr": "banyo"},
                        {"word": "leaking", "meaning_tr": "sızdırıyor"},
                    ],
                }]),
            _ex(W, f"Musluğu kapat.", f"Turn off the {T}.", "action",
                f"Turn off + the {T}",
                f"turn off → kapatmak (musluk, ışık, cihaz için çok yaygın)\n\n"
                f"❓ Neden turn off? İngilizcede musluk/ışık kapatırken bu phrasal verb kullanılır.\n\n"
                f"the {T} → belirli musluk"),
            _ex(W, f"Musluğu kapatabilir misin?", f"Could you turn off the {T}?", "request",
                f"Could + you + turn off + the {T}",
                f"Could you…? → kibar rica\n\n"
                "turn off the faucet = musluğu kapatmak"),
            _ex(W, f"{W.capitalize()} neden akıyor?", f"Why is the {T} leaking?", "question",
                f"Why + is + the {T} + leaking",
                f"Soru: Why + is + özne + fiil-ing?\n\n"
                f"Why → neden\nleaking → sızdırıyor"),
            _ex(W, f"Yeni bir mutfak musluğu almam gerekiyor.", f"I need to buy a new kitchen {T}.", "shopping",
                f"I + need to + buy + a new kitchen {T}",
                f"need to + fiil → …-mem lazım\n\n"
                f"a new kitchen {T} → yeni mutfak musluğu\n\n"
                "kitchen faucet = mutfak musluğu (sıfat + isim)"),
            _ex(W, f"Musluğu tamir ettirmem gerekiyor.", f"I need to have the {T} repaired.", "repair",
                f"I + need to + have + the {T} + repaired",
                f"have something repaired → bir şeyi tamir ettirmek\n\n"
                f"Bu yapı «musluğu tamir ettirmem lazım» anlamını verir."),
        ]

    if category == "vehicle":
        return [
            _ex(W, f"{W.capitalize()} garajda.", f"The {T} is in the garage.", "location",
                f"The + {T} + is + in the garage", f"The {T} → araba\ngarage → garaj"),
            _ex(W, f"Yeni bir {W} aldım.", f"I bought a new {T}.", "shopping",
                f"I + bought + a new {T}", f"a new {T} → yeni araba\nbought → aldım"),
            _ex(W, f"{W.capitalize()} bozuk.", f"The {T} is broken.", "problem",
                f"The + {T} + is + broken", f"broken → bozuk (sıfat)\nis broken → bozuk durumda"),
            _ex(W, f"{W} kullanabilir misin?", f"Can you drive the {T}?", "request",
                f"Can + you + drive + the {T}", f"drive the {T} → arabayı sürmek"),
            _ex(W, f"{W} tamir etmem lazım.", f"I need to fix the {T}.", "repair",
                f"I + need to + fix + the {T}", f"fix the {T} → arabayı tamir etmek"),
            _ex(W, f"{W} nereye park ettin?", f"Where did you park the {T}?", "question",
                f"Where + did + you + park + the {T}", f"park → park etmek\nWhere did you…? → nereye…?"),
        ]

    if category == "adjective":
        return [
            _ex(W, f"Mutluyum.", f"I am {T}.", "description",
                f"I + am + {T}", f"am + sıfat → …-yım/-ım\n\n❌ I happy — am gerekli"),
            _ex(W, f"Mutlu görünüyor.", f"She looks {T}.", "description",
                f"She + looks + {T}", f"look + sıfat → … gibi görünmek"),
            _ex(W, f"Mutlu musun?", f"Are you {T}?", "question",
                f"Are + you + {T}", f"Soru: Are + özne + sıfat?"),
            _ex(W, f"Bu beni mutlu ediyor.", f"This makes me {T}.", "action",
                f"This + makes + me + {T}", f"make + kişi + sıfat → …-i mutlu etmek"),
            _ex(W, f"Dün mutluydum.", f"I was {T} yesterday.", "past",
                f"I + was + {T}", f"was → geçmişte be fiili"),
            _ex(W, f"Mutlu görünüyorlar.", f"They seem {T}.", "description",
                f"They + seem + {T}", f"seem + sıfat → … gibi görünmek"),
        ]

    if category == "verb":
        return [
            _ex(W, f"Her gün çalışırım.", f"I {T} every day.", "routine",
                f"I + {T} + every day", f"Geniş zaman: I + fiil(yalın)"),
            _ex(W, f"Pazar günleri çalışmam.", f"I don't {T} on Sundays.", "negative",
                f"I + don't + {T}", f"don't + fiil(yalın) → …-mıyorum"),
            _ex(W, f"Burada çalışıyor musun?", f"Do you {T} here?", "question",
                f"Do + you + {T}", f"Soru: Do + özne + fiil?"),
            _ex(W, f"Daha çok çalışmam lazım.", f"I need to {T} harder.", "need_to",
                f"I + need to + {T}", f"need to + fiil → …-mem lazım"),
            _ex(W, f"Şu an çalışıyor.", f"She is {T}ing now.", "present_continuous",
                f"She + is + {T}ing", f"is + fiil-ing → şu anda …-yor"),
            _ex(W, f"Dün geç saate kadar çalıştım.", f"I {T}ed late yesterday.", "past",
                f"I + {T}ed + late", f"Geçmiş zaman: fiil + -ed (düzenli fiiller)"),
        ]

    if category == "place":
        return [
            _ex(W, f"{W.capitalize()}e gidiyorum.", f"I am going to the {T}.", "movement",
                f"I + am going + to the {T}",
                f"go to the {T} → {W}'e gitmek\n\n"
                "Yer isimlerinde genelde the kullanılır."),
            _ex(W, f"{W.capitalize()}te bekliyorum.", f"I am waiting at the {T}.", "location",
                f"I + am waiting + at the {T}",
                f"at the {T} → {W}'te/-da\n\n"
                "Beklemek için at + yer."),
        ]

    # Genel sayılabilir isim
    return [
        _ex(W, f"{W.capitalize()} burada.", f"The {T} is here.", "description",
            f"The + {T} + is + here", f"The {T} → belirli {W}\nis → -dir/-dır\nhere → burada"),
        _ex(W, f"Bir {W} aldım.", f"I bought a {T}.", "past",
            f"I + bought + a {T}", f"a {T} → bir {W}\nbought → aldım (buy geçmişi)"),
        _ex(W, f"{W.capitalize()} nerede?", f"Where is the {T}?", "question",
            f"Where + is + the {T}?", "Soru: Where + is + özne?"),
    ]


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
) -> dict[str, Any]:
    return {
        "tr": tr,
        "target": target,
        "sentence_type": sentence_type,
        "sentence_type_label": SENTENCE_TYPE_LABELS.get(sentence_type, sentence_type),
        "grammar_topic": sentence_type,
        "difficulty": "A1" if sentence_type in ("description", "question", "location") else "A2",
        "structure_tr": structure_tr,
        "structure_label_tr": "Kelimeye özel doğal yapı",
        "word_breakdown": [],
        "how_it_is_formed_tr": how,
        "why_this_structure_tr": f"Bu yapı «{word_tr}» kelimesinin doğal kullanımına uygundur.",
        "important_note_tr": important_note_tr,
        "pattern_tr": pattern_tr,
        "pattern_examples": pattern_examples or [],
    }


def generate_examples_from_profile(
    profile: dict[str, Any],
    word_tr: str,
    target_word: str,
    target_lang: str,
) -> list[dict[str, Any]]:
    """Profile göre örnek üret — LLM veya kategori şablonları."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    category = _resolve_category(word_tr, target_word, profile.get("semantic_category"))

    examples: list[dict[str, Any]] = []

    if llm_available():
        import json
        system = WORD_LESSON_FROM_PROFILE_PROMPT.format(
            lang_name=lang_name,
            profile_json=json.dumps(profile, ensure_ascii=False)[:2000],
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=2800)
        if parsed and isinstance(parsed.get("examples"), list):
            for ex in parsed["examples"]:
                if isinstance(ex, dict) and _validate_word_example(ex, word_tr, target_word, profile):
                    examples.append(ex)

    if len(examples) < 5 and target_lang == "en":
        for ex in _category_examples_en(word_tr, target_word, category):
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)

    return sanitize_word_examples(examples[:8], word_tr, target_word, profile)


def build_rule_examples_for_word(
    word_tr: str,
    target_word: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Kural tabanlı kelimeye özel örnekler — LLM yokken veya kalite düşükken."""
    category = _resolve_category(word_tr, target_word, profile.get("semantic_category"))
    return _category_examples_en(word_tr, target_word, category)


def _validate_word_example(
    ex: dict[str, Any],
    word_tr: str,
    target_word: str,
    profile: dict[str, Any] | None = None,
) -> bool:
    target = _normalize_noun_caps(safe_str(ex.get("target")).strip(), target_word)
    if target:
        ex["target"] = target
    how = safe_str(ex.get("how_it_is_formed_tr")).strip()
    tr = safe_str(ex.get("tr")).strip()
    if not target or len(how) < 40:
        return False
    if tr and not _tr_contains_word(tr, word_tr):
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
    tw = _en_target_word(target_word)
    norm_target = _norm(target)
    if tw and tw not in norm_target and f"{tw}s" not in norm_target:
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
        if profile.get("semantic_category") in ("plumbing", "furniture", "vehicle"):
            for bad in ("i love", "do you want", "don't drink", "drink the", "eat the"):
                if bad in safe_str(ex.get("target")).lower():
                    return False
    return True


def build_usage_from_profile(profile: dict[str, Any], target_lang: str) -> dict[str, Any]:
    pos = profile.get("part_of_speech", "noun")
    pos_tr = {"noun": "isim", "verb": "fiil", "adjective": "sıfat", "adverb": "zarf"}.get(pos, pos)
    count = profile.get("countability", "")
    count_tr = {
        "countable": "sayılabilir",
        "uncountable": "sayılamaz",
        "both": "bağlama göre sayılabilir/sayılamaz",
    }.get(count, count or "—")
    verbs = profile.get("common_verbs") or []
    coll = profile.get("common_collocations") or []
    patterns = profile.get("common_patterns") or []
    category = profile.get("semantic_category") or "general"

    verbs_enriched = [
        {"en": v, "tr": VERBS_TR.get(v.lower(), VERBS_TR.get(v.split()[-1].lower(), ""))}
        for v in verbs[:8]
    ]
    verbs_enriched = [v for v in verbs_enriched if v["en"]]

    phrase_src = CATEGORY_PHRASES.get(category, [])
    if not phrase_src and coll:
        phrase_src = [{"en": c, "tr": ""} for c in coll[:6]]
    phrases_enriched: list[dict[str, str]] = []
    for item in phrase_src[:6]:
        en = safe_str(item.get("en") if isinstance(item, dict) else item).strip()
        if not en:
            continue
        tr = safe_str(item.get("tr") if isinstance(item, dict) else "").strip()
        pron = ""
        if target_lang == "en":
            pron = build_pronunciation_bundle(en, target_lang).get("pronunciation_tr", "")
        phrases_enriched.append({"en": en, "tr": tr, "pronunciation_tr": pron})

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
        "patterns": patterns[:4],
        "article_notes_tr": profile.get("article_notes_tr"),
        "avoid_reason_tr": profile.get("avoid_reason_tr"),
        "regional_note_tr": (profile.get("regional_variants") or {}).get("note_tr"),
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
