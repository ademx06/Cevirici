"""Kelimeye özel öğretim motoru — şablon kopyalama yok, bağlama göre analiz."""
from __future__ import annotations

import re
from typing import Any, Callable

from education_engine import LANG_NAMES, _llm_json, llm_available, safe_str
from pronunciation_service import (
    build_pronunciation_bundle,
    get_word,
    tokenize_en,
    word_meaning_tr,
    word_role_tr,
)
from word_icons import lookup_emoji
from word_lexicon import build_lexicon_examples, get_word_usage_phrases, get_word_usage_profile

# Varsayılan İngilizce varyantı — Amerikan İngilizcesi
ENGLISH_VARIANT = "en-US"
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
    "go to": "gitmek", "be at": "bulunmak", "visit": "ziyaret etmek",
    "read": "okumak", "charge": "şarj etmek", "answer": "cevaplamak / açmak",
    "knock": "çalmak", "wipe": "silmek", "clear": "toplamak",
    "order": "sipariş etmek", "sip": "yudumlamak", "serve": "servis etmek",
    "pour": "dökmek", "chill": "soğutmak",
    "fill": "doldurmak", "break": "kırmak", "wash": "yıkamak", "dry": "kurulamak",
    "raise": "kaldırmak", "hold": "tutmak", "collect": "toplamak",
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
    re.compile(r"\bcould you bring the \w+", re.I),
]

GENERIC_STRUCTURE_LABEL_RE = re.compile(
    r"kelimeye\s+özel\s+doğal\s+yapı",
    re.I,
)

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
  "part_of_speech": "noun|verb|adjective|...",
  "countability": "countable|uncountable|both|n/a",
  "semantic_category": "beverage|furniture|footwear|plumbing|vehicle|object|place|other",
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
5. Her örnekte "how_it_is_formed_tr" en az 40 karakter; cümleye özel, doğal kullanım açıklaması.
6. "structure_label_tr" asla "Kelimeye özel doğal yapı" olamaz — gerçek formül yaz.
7. En az 10 farklı kalıp: Temel kullanım, Şimdiki zaman, Geçmiş zaman, Gelecek zaman, Soru, Olumsuz, Emir, Rica, Tavsiye, Zorunluluk, İhtimal, Koşul, Diyalog.
8. sentence_type_label numaralı Türkçe kalıp adı olmalı (ör. "6. Olumsuz cümle").
9. word_breakdown: her kelime için token, pronunciation_tr (Türkçe fonetik), meaning_tr, role_tr.
10. DOĞAL KULLANIM ZORUNLU: Her cümle o kelimenin gerçek hayattaki kullanımını yansıtmalı. Mekanik şablon YASAK:
    ❌ I am using the [word], Bring the [word], This is my [word], Check the [word] regularly
    ✅ door: knock on the door, close the door behind you | table: set the table, wipe the table
11. Türkçe çeviri doğal Türkçe olmalı; İngilizce cümleyle birebir anlam eşleşmeli.

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
    "mutlu": "adjective", "happy": "adjective",
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
}

# Çeviri başarısız olunca bilinen TR→EN eşleşmeleri
KNOWN_TR_TO_EN: dict[str, str] = {
    "kahve": "coffee", "masa": "table", "musluk": "faucet", "pencere": "window",
    "kapı": "door", "kapi": "door", "kitap": "book", "gazoz": "soda", "kola": "cola",
    "araba": "car", "mutlu": "happy", "çalışmak": "work", "calismak": "work",
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
    "koltuk": "sofa", "yatak": "bed", "dolap": "wardrobe", "mutfak": "kitchen",
    "okul": "school", "hastane": "hospital", "bisiklet": "bicycle",
}

# Çeviri API'sinin döndürdüğü varyantları Amerikan İngilizcesine normalize et
EN_TARGET_ALIASES: dict[str, str] = {
    "sweetcorn": "corn",
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
    tw = EN_TARGET_ALIASES.get(tw, tw)
    tw = re.sub(r"\s+", " ", tw)
    if tw in EN_TARGET_ALIASES:
        tw = EN_TARGET_ALIASES[tw]
    return tw


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
    if _is_beverage_like(wt, tw):
        return "beverage"
    food_hints = (
        "ekmek", "peynir", "et", "tavuk", "balık", "elma", "muz", "domates",
        "bread", "cheese", "meat", "chicken", "fish", "apple", "banana", "tomato",
        "rice", "pasta", "pizza", "soup", "salad", "fruit", "vegetable",
    )
    if any(h in wt or h in tw for h in food_hints):
        return "food"
    animal_hints = ("kedi", "köpek", "kuş", "cat", "dog", "bird", "horse", "cow")
    if any(h in wt or h in tw for h in animal_hints):
        return "animal"
    place_hints = ("ev", "okul", "hastane", "market", "home", "school", "hospital", "store")
    if any(h in wt or h in tw for h in place_hints):
        return "place"
    vehicle_hints = ("araba", "otobüs", "tren", "car", "bus", "train", "plane", "bike")
    if any(h in wt or h in tw for h in vehicle_hints):
        return "vehicle"
    return "general"


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


def _is_generic_mechanical_template(target: str) -> bool:
    """Mekanik şablon: kelimeyi fiile zorla yerleştiren doğal olmayan cümleler."""
    t = _norm(target)
    return any(p.search(t) for p in GENERIC_MECHANICAL_RE)


def _is_absurd_example(target: str, word_tr: str, target_word: str) -> bool:
    """İçecek/yiyecek ve genel mekanik şablonları reddet."""
    if _is_generic_mechanical_template(target):
        return True
    t = _norm(target)
    if not _is_beverage_like(word_tr, target_word):
        return False
    absurd = (
        "open the", "open a", "fix the", "fix it", "is broken", "check the",
        "using the", "used the", "is ready", "is here", "another room",
        "regularly", "repair",
    )
    return any(p in t for p in absurd)


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
            if known_cat != "general":
                return _rule_word_profile(word_tr, target_word, target_lang, known_cat)
            parsed["semantic_category"] = parsed.get("semantic_category") or known_cat
            return parsed

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
                "Bağlama göre doğal fiiller seçilir; her nesne için aynı kalıp kullanılmaz."
            ),
            "common_verbs": ["use", "need", "find", "buy", "see", "have"],
            "common_collocations": [f"the {target_word}", f"a {target_word}"],
            "common_patterns": [f"The {target_word} is...", f"I need the {target_word}."],
            "article_notes_tr": f"the {target_word.lower()} / a {target_word.lower()}",
            "avoid_patterns": ["I love X", "Do you want X", "Bring the X", "I am using the X"],
            "avoid_reason_tr": "Her nesne için aynı şablon kullanılmaz; kelimenin gerçek kullanımına göre fiil seçilir.",
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
    return {"target_word": target_word, **base}


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
    if category == "adjective":
        return _adjective_pattern_examples(W, T)
    if category == "verb":
        return _verb_pattern_examples(W, T)
    if category == "place":
        return _place_pattern_examples(W, T)
    if category == "beverage" or _is_beverage_like(wt, tw):
        return _beverage_pattern_examples(W, T, wt, tw)
    if category == "footwear":
        return _footwear_pattern_examples(W, T)
    if category == "vehicle":
        return _vehicle_pattern_examples(W, T)
    if category == "plumbing":
        return _plumbing_pattern_examples(W, T)
    if category == "drinkware":
        return _drinkware_pattern_examples(W, T, wt, tw)
    if category == "food" or tw in ("corn", "sweetcorn", "maize"):
        return _food_pattern_examples(W, T, wt, tw)
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


def _safe_object_pattern_examples(W: str, T: str, category: str) -> list[dict[str, Any]]:
    """Bilinmeyen nesneler — mekanik şablon YOK; boş döner, LLM doldurur."""
    if _is_beverage_like(W, T):
        return _sparkling_water_pattern_examples(W, _canonical_beverage_phrase(T))
    return []


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


def _vehicle_pattern_examples(W: str, T: str) -> list[dict[str, Any]]:
    return [
        _pe(W, f"{W.capitalize()} garajda.", f"The {T} is in the garage.", "basic",
            f"The + {T} + is + in the garage", f"1️⃣ Temel kullanım\nThe {T} → araba\nis → -dır\ngarage → garaj"),
        _pe(W, f"Şu an {W} kullanıyorum.", f"I am driving the {T} now.", "present",
            f"I + am + driving + the {T}", f"1️⃣ Şimdiki zaman\ndriving → sürüyorum\nam + -ing → şu anda"),
        _pe(W, f"Geçen yıl {W} aldım.", f"I bought a {T} last year.", "past",
            f"I + bought + a {T}", f"1️⃣ Geçmiş zaman\nbought → aldım\nlast year → geçen yıl"),
        _pe(W, f"Yarın {W} süreceğim.", f"I will drive the {T} tomorrow.", "future",
            f"I + will + drive + the {T}", f"1️⃣ Gelecek zaman\nwill drive → süreceğim"),
        _pe(W, f"{W.capitalize()} nerede park ettin?", f"Where did you park the {T}?", "question",
            f"Where + did + you + park", f"1️⃣ Soru cümlesi\nWhere did you park…? → nereye park ettin?"),
        _pe(W, f"{W.capitalize()} bozuk değil.", f"The {T} is not broken.", "negative",
            f"The + {T} + is + not + broken", f"1️⃣ Olumsuz cümle\nis not broken → bozuk değil"),
        _pe(W, f"{W.capitalize()}yı yavaş sür.", f"Drive the {T} slowly.", "imperative",
            f"Drive + the {T} + slowly", f"1️⃣ Emir kipi\nDrive → sür\nslowly → yavaşça"),
        _pe(W, f"{W} kullanabilir miyim?", f"Could I use the {T}?", "polite_request",
            f"Could + I + use + the {T}", f"1️⃣ Rica cümlesi\nCould I…? → …-ebilir miyim?"),
        _pe(W, f"{W} için sigorta yaptırmalısın.", f"You should get insurance for the {T}.", "advice",
            f"You + should + get + insurance", f"1️⃣ Tavsiye cümlesi\nshould → …-melisin"),
        _pe(W, f"{W} tamir etmem lazım.", f"I need to fix the {T}.", "obligation",
            f"I + need to + fix + the {T}", f"1️⃣ Zorunluluk cümlesi\nneed to fix → tamir etmem lazım"),
        _pe(W, f"{W.capitalize()} bozulmuş olabilir.", f"The {T} might be broken.", "possibility",
            f"The + {T} + might + be + broken", f"1️⃣ İhtimal cümlesi\nmight be → … olabilir"),
        _pe(W, f"{W.capitalize()} bozuksa tamir ettir.", f"If the {T} is broken, get it fixed.", "conditional",
            f"If + the {T} + is broken", f"1️⃣ Koşul cümlesi\nIf … is broken → … bozuksa"),
        _pe(W, f"A: {W.capitalize()} hazır mı? B: Evet.", f"A: Is the {T} ready? B: Yes, the keys are inside.", "dialogue",
            f"A: Is the {T} ready? B: Yes", f"1️⃣ Günlük diyalog\nAraç hazırlığı hakkında kısa konuşma."),
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
    return [
        _pe(W, f"Mutluyum.", f"I am {T}.", "basic", f"I + am + {T}", f"1️⃣ Temel kullanım\nam + sıfat → …-yım\n❌ I happy — am gerekli"),
        _pe(W, f"Şu an mutluyum.", f"I am feeling {T} right now.", "present", f"I + am + feeling + {T}", f"1️⃣ Şimdiki zaman\nfeeling → hissediyorum"),
        _pe(W, f"Dün mutluydum.", f"I was {T} yesterday.", "past", f"I + was + {T}", f"1️⃣ Geçmiş zaman\nwas → geçmişte be fiili"),
        _pe(W, f"Yarın mutlu olacağım.", f"I will be {T} tomorrow.", "future", f"I + will + be + {T}", f"1️⃣ Gelecek zaman\nwill be → … olacağım"),
        _pe(W, f"Mutlu musun?", f"Are you {T}?", "question", f"Are + you + {T}", f"1️⃣ Soru cümlesi\nAre + özne + sıfat?"),
        _pe(W, f"Mutlu değilim.", f"I am not {T}.", "negative", f"I + am + not + {T}", f"1️⃣ Olumsuz cümle\nam not → değilim"),
        _pe(W, f"Mutlu ol!", f"Be {T}!", "imperative", f"Be + {T}", f"1️⃣ Emir kipi\nBe + sıfat → … ol"),
        _pe(W, f"Mutlu olabilir misin?", f"Could you be {T}?", "polite_request", f"Could + you + be + {T}", f"1️⃣ Rica cümlesi\nCould you be…? → … olabilir misin?"),
        _pe(W, f"Daha mutlu olmalısın.", f"You should be {T}er.", "advice", f"You + should + be + {T}", f"1️⃣ Tavsiye cümlesi\nshould be → … olmalısın"),
        _pe(W, f"Mutlu hissetmem lazım.", f"I need to feel {T}.", "obligation", f"I + need to + feel + {T}", f"1️⃣ Zorunluluk cümlesi\nneed to feel → hissetmem lazım"),
        _pe(W, f"Mutlu olabilirsin.", f"You might be {T}.", "possibility", f"You + might + be + {T}", f"1️⃣ İhtimal cümlesi\nmight be → … olabilirsin"),
        _pe(W, f"Güzel hava olursa mutlu olursun.", f"If the weather is nice, you will be {T}.", "conditional", f"If + …, + you will be + {T}", f"1️⃣ Koşul cümlesi\nIf … → … olursa"),
        _pe(W, f"A: Mutlu musun? B: Evet.", f"A: Are you {T}? B: Yes, I am.", "dialogue", f"A: Are you {T}? B: Yes", f"1️⃣ Günlük diyalog\nDuygu sorma kalıbı."),
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
        wb.append({
            "token": tok,
            "pronunciation_tr": safe_str(w.get("pronunciation_tr") or info.get("pronunciation_tr")),
            "ipa": safe_str(w.get("ipa") or info.get("ipa", "")),
            "meaning_tr": word_meaning_tr(low),
            "role_tr": word_role_tr(low),
        })
    ex["word_breakdown"] = wb
    if not ex.get("pronunciation_tr"):
        ex["pronunciation_tr"] = bundle.get("pronunciation_tr", "")
    if not ex.get("ipa"):
        ex["ipa"] = bundle.get("ipa", "")
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
        text += (
            f" Bu kelimeyi günlük cümlelerde doğal fiillerle "
            f"(have, drink, order vb.) birlikte öğren."
        )
    return text.strip()


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

    if target_lang == "en":
        for ex in _category_examples_en(word_tr, target_word, category):
            if _validate_word_example(ex, word_tr, target_word, profile):
                examples.append(ex)

    if llm_available() and len(examples) < 8:
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

    return sanitize_word_examples(examples[:13], word_tr, target_word, profile)


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
    if not target:
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
    verbs = profile.get("common_verbs") or []
    coll = profile.get("common_collocations") or []
    patterns = profile.get("common_patterns") or []
    category = profile.get("semantic_category") or "general"

    verbs_enriched = []
    for v in verbs[:8]:
        key = safe_str(v).strip()
        if not key:
            continue
        tr_mean = VERBS_TR.get(key.lower()) or VERBS_TR.get(key.split()[-1].lower(), "")
        if not tr_mean:
            tr_mean = "kullanmak"
        verbs_enriched.append({"en": key, "tr": tr_mean})

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
        for c in coll[:6]:
            en = safe_str(c).strip()
            if not en:
                continue
            tr = phrase_lookup.get(en.lower(), "")
            if tr:
                phrase_src.append({"en": en, "tr": tr})
    if not phrase_src and category != "object":
        phrase_src = [p for p in CATEGORY_PHRASES.get(category, []) if isinstance(p, dict) and p.get("tr")]
    phrases_enriched: list[dict[str, str]] = []
    for item in phrase_src[:6]:
        en = safe_str(item.get("en") if isinstance(item, dict) else item).strip()
        if not en:
            continue
        tr = safe_str(item.get("tr") if isinstance(item, dict) else "").strip()
        if not tr:
            continue
        pron = ""
        ipa = ""
        if target_lang == "en":
            bundle = build_pronunciation_bundle(en, target_lang)
            pron = bundle.get("pronunciation_tr", "")
            ipa = bundle.get("ipa", "")
        phrases_enriched.append({"en": en, "tr": tr, "pronunciation_tr": pron, "ipa": ipa})

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
        "patterns": patterns[:4],
        "article_notes_tr": profile.get("article_notes_tr"),
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
