"""Kelime → emoji eşlemesi — tek kaynak (backend)."""
from __future__ import annotations

import re
from typing import Iterable

from education_engine import safe_str

# Doğrudan eşleşme: Türkçe veya İngilizce kelime → emoji
EMOJI_BY_WORD: dict[str, str] = {
    # İçecekler
    "kahve": "☕", "coffee": "☕", "çay": "🍵", "tea": "🍵", "cay": "🍵",
    "soda": "🥤", "gazoz": "🥤", "kola": "🥤", "cola": "🥤", "pop": "🥤",
    "su": "💧", "water": "💧", "süt": "🥛", "milk": "🥛", "juice": "🧃",
    "maden suyu": "🫧", "maden su": "🫧", "mineral water": "🫧", "sparkling water": "🫧",
    "club soda": "🫧", "soda water": "🫧",
    "meyve suyu": "🧃", "bira": "🍺", "beer": "🍺", "şarap": "🍷", "wine": "🍷",
    # Yiyecekler
    "mısır": "🌽", "misir": "🌽", "corn": "🌽", "sweetcorn": "🌽", "sweet corn": "🌽", "maize": "🌽",
    "ekmek": "🍞", "bread": "🍞", "peynir": "🧀", "cheese": "🧀", "yumurta": "🥚", "egg": "🥚", "eggs": "🥚",
    "et": "🥩", "meat": "🥩", "tavuk": "🍗", "chicken": "🍗", "balık": "🐟", "fish": "🐟",
    "elma": "🍎", "apple": "🍎", "muz": "🍌", "banana": "🍌", "portakal": "🍊", "orange": "🍊",
    "çilek": "🍓", "strawberry": "🍓", "üzüm": "🍇", "grape": "🍇", "grapes": "🍇",
    "domates": "🍅", "tomato": "🍅", "salatalık": "🥒", "cucumber": "🥒",
    "havuç": "🥕", "havuc": "🥕", "carrot": "🥕", "patates": "🥔", "potato": "🥔", "potatoes": "🥔",
    "soğan": "🧅", "sogan": "🧅", "onion": "🧅", "biber": "🌶️", "pepper": "🌶️",
    "pizza": "🍕", "hamburger": "🍔", "burger": "🍔", "patlamış mısır": "🍿", "popcorn": "🍿",
    "çikolata": "🍫", "chocolate": "🍫", "pasta": "🍰", "cake": "🍰", "kurabiye": "🍪", "cookie": "🍪",
    "yemek": "🍽️", "food": "🍽️", "meal": "🍽️", "kahvaltı": "🥐", "breakfast": "🥐",
    "öğle yemeği": "🍱", "lunch": "🍱", "akşam yemeği": "🍽️", "dinner": "🍽️",
    # Mobilya — masa ≠ sandalye (🪑 Unicode'da CHAIR'dir)
    "masa": "🍽️", "table": "🍽️", "desk": "🖥️", "çalışma masası": "🖥️",
    "sandalye": "💺", "chair": "💺", "koltuk": "🛋️", "sofa": "🛋️", "couch": "🛋️",
    "yatak": "🛏️", "bed": "🛏️", "dolap": "🗄️", "wardrobe": "🗄️", "closet": "🗄️",
    "raf": "📚", "shelf": "📚", "lamba": "💡", "lamp": "💡",
    # Ev / banyo
    "musluk": "🚰", "faucet": "🚰", "tap": "🚰", "lavabo": "🚰", "sink": "🚰",
    "banyo": "🛁", "bathroom": "🛁", "duş": "🚿", "shower": "🚿", "tuvalet": "🚽", "toilet": "🚽",
    "kapı": "🚪", "kapi": "🚪", "door": "🚪", "pencere": "🪟", "window": "🪟",
    "ev": "🏠", "home": "🏠", "house": "🏠", "mutfak": "🍳", "kitchen": "🍳",
    "oda": "🛋️", "room": "🛋️", "salon": "🛋️", "living room": "🛋️",
    # Taşıt
    "araba": "🚗", "car": "🚗", "otomobil": "🚗", "taksi": "🚕", "taxi": "🚕",
    "otobüs": "🚌", "bus": "🚌", "tren": "🚆", "train": "🚆", "uçak": "✈️", "plane": "✈️", "airplane": "✈️",
    "bisiklet": "🚲", "bicycle": "🚲", "bike": "🚲", "motor": "🏍️", "motorcycle": "🏍️",
    # Giyim / ayakkabı
    "ayakkabı": "👟", "ayakkabi": "👟", "shoe": "👟", "shoes": "👟", "bot": "🥾", "boot": "🥾", "boots": "🥾",
    "çorap": "🧦", "corap": "🧦", "sock": "🧦", "socks": "🧦", "gömlek": "👔", "shirt": "👔",
    "pantolon": "👖", "pants": "👖", "elbise": "👗", "dress": "👗", "ceket": "🧥", "jacket": "🧥",
    "şapka": "🧢", "sapka": "🧢", "hat": "🧢", "gözlük": "👓", "glasses": "👓",
    # Eşyalar
    "kitap": "📚", "book": "📚", "defter": "📓", "notebook": "📓", "kalem": "✏️", "pen": "✏️", "pencil": "✏️",
    "telefon": "📱", "phone": "📱", "bilgisayar": "💻", "computer": "💻", "laptop": "💻", "tablet": "📱",
    "televizyon": "📺", "tv": "📺", "television": "📺", "kamera": "📷", "camera": "📷",
    "çanta": "👜", "bag": "👜", "cüzdan": "👛", "wallet": "👛", "anahtar": "🔑", "key": "🔑", "keys": "🔑",
    "bardak": "🥛", "glass": "🥛", "fincan": "☕", "cup": "☕", "mug": "☕",
    "tabak": "🍽️", "plate": "🍽️", "kase": "🥣", "bowl": "🥣", "çatal": "🍴", "fork": "🍴",
    "bıçak": "🔪", "bicak": "🔪", "knife": "🔪", "kaşık": "🥄", "kasik": "🥄", "spoon": "🥄",
    "saat": "⌚", "watch": "⌚", "clock": "🕐",
    "fatura": "🧾", "invoice": "🧾", "makbuz": "🧾", "receipt": "🧾", "bill": "🧾",
    "dekont": "🧾", "fiş": "🧾", "çanta": "👜", "canta": "👜", "bag": "👜",
    # Hayvanlar
    "kedi": "🐱", "cat": "🐱", "köpek": "🐶", "kopek": "🐶", "dog": "🐶",
    "kuş": "🐦", "kus": "🐦", "bird": "🐦", "at": "🐴", "horse": "🐴",
    "inek": "🐄", "cow": "🐄", "koyun": "🐑", "sheep": "🐑", "tavşan": "🐰", "rabbit": "🐰",
    "fare": "🐭", "mouse": "🐭", "aslan": "🦁", "lion": "🦁", "fil": "🐘", "elephant": "🐘",
    # Doğa / yer
    "güneş": "☀️", "gunes": "☀️", "sun": "☀️", "ay": "🌙", "moon": "🌙",
    "yağmur": "🌧️", "yagmur": "🌧️", "rain": "🌧️", "kar": "❄️", "snow": "❄️",
    "ağaç": "🌳", "agac": "🌳", "tree": "🌳", "çiçek": "🌸", "cicek": "🌸", "flower": "🌸", "flowers": "🌸",
    "deniz": "🌊", "sea": "🌊", "okyanus": "🌊", "ocean": "🌊", "dağ": "⛰️", "dag": "⛰️", "mountain": "⛰️",
    "park": "🌳", "bahçe": "🌻", "bahce": "🌻", "garden": "🌻",
    "okul": "🏫", "school": "🏫", "hastane": "🏥", "hospital": "🏥",
    "market": "🛒", "pazar": "🛒", "shop": "🛒", "store": "🛒", "mağaza": "🛍️", "magaza": "🛍️",
    "mısır ülke": "🇪🇬", "egypt": "🇪🇬",
    # Duygu / fiil
    "mutlu": "😊", "happy": "😊", "üzgün": "😢", "uzgun": "😢", "sad": "😢",
    "yorgun": "😴", "tired": "😴", "kızgın": "😠", "kizgin": "😠", "angry": "😠",
    "çalışmak": "💼", "calismak": "💼", "work": "💼", "çalış": "💼", "calis": "💼",
    "koşmak": "🏃", "kosmak": "🏃", "run": "🏃", "yürümek": "🚶", "yurumek": "🚶", "walk": "🚶",
    "uyumak": "😴", "sleep": "😴", "okumak": "📖", "read": "📖", "yazmak": "✍️", "write": "✍️",
    "öğrenmek": "📚", "ogrenmek": "📚", "learn": "📚", "study": "📚",
    # Müzik / spor
    "müzik": "🎵", "muzik": "🎵", "music": "🎵", "şarkı": "🎵", "sarki": "🎵", "song": "🎵",
    "futbol": "⚽", "football": "⚽", "soccer": "⚽", "basketbol": "🏀", "basketball": "🏀",
}

CATEGORY_EMOJI: dict[str, str] = {
    "beverage": "🥤",
    "food": "🍽️",
    "vegetable": "🥕",
    "fruit": "🍎",
    "furniture": "🛋️",
    "plumbing": "🚰",
    "vehicle": "🚗",
    "adjective": "😊",
    "verb": "💼",
    "place": "📍",
    "object": "📦",
    "footwear": "👟",
    "drinkware": "🥛",
    "animal": "🐾",
    "weather": "🌤️",
    "clothing": "👕",
    "document": "🧾",
}

_SHORT_TERM_MIN_LEN = 4


def _term_matches(term: str, text: str) -> bool:
    """Kısa anahtarlar (at, ay) yalnızca tam kelime olarak eşleşir — fatura→at hatası önlenir."""
    term = _norm(term)
    text = _norm(text)
    if not term or not text:
        return False
    if term == text:
        return True
    if len(term) < _SHORT_TERM_MIN_LEN:
        return bool(re.search(rf"(?<![a-zçğıöşüâîû]){re.escape(term)}(?![a-zçğıöşüâîû])", text))
    return term in text

# Uzun anahtarlar önce — yanlış kısmi eşleşmeyi önler
KEYWORD_EMOJI: tuple[tuple[str, ...], str] = (
    (("patlamış mısır", "popcorn"), "🍿"),
    (("sweet corn", "sweetcorn"), "🌽"),
    (("mısır", "misir", "corn", "maize"), "🌽"),
    (("çalışma masası",), "🖥️"),
    (("masa", "table"), "🍽️"),
    (("sandalye", "chair"), "💺"),
    (("maden suyu", "maden su", "mineral water", "sparkling water", "club soda"), "🫧"),
    (("kahve", "coffee", "çay", "tea", "gazoz", "soda", "kola", "cola", "su", "water", "süt", "milk"), "🥤"),
    (("ayakkabı", "ayakkabi", "shoe", "shoes", "bot", "boot"), "👟"),
    (("araba", "car", "otomobil", "taksi", "taxi", "otobüs", "bus"), "🚗"),
    (("musluk", "faucet", "tap", "lavabo", "sink", "banyo", "bathroom"), "🚰"),
    (("kapı", "kapi", "door", "pencere", "window"), "🪟"),
    (("fatura", "invoice", "makbuz", "receipt", "bill", "dekont", "fiş", "fis"), "🧾"),
    (("kitap", "book", "defter", "notebook", "gazete", "newspaper"), "📚"),
    (("telefon", "phone", "bilgisayar", "computer", "laptop", "tablet"), "📱"),
    (("kedi", "cat", "köpek", "kopek", "dog", "kuş", "bird"), "🐾"),
    (("elma", "apple", "muz", "banana", "portakal", "orange", "çilek", "strawberry"), "🍎"),
    (("domates", "tomato", "havuç", "carrot", "patates", "potato", "soğan", "onion"), "🥕"),
    (("ekmek", "bread", "peynir", "cheese", "yumurta", "egg", "et", "meat", "tavuk", "chicken"), "🍽️"),
    (("mutlu", "happy", "üzgün", "sad", "yorgun", "tired", "kızgın", "angry"), "😊"),
    (("çalış", "calis", "work", "koş", "kos", "run", "yürü", "walk"), "💼"),
    (("ev", "home", "house", "okul", "school", "hastane", "hospital", "market", "pazar"), "📍"),
    (("bardak", "glass", "fincan", "cup", "tabak", "plate", "kase", "bowl"), "🥛"),
    (("güneş", "sun", "yağmur", "rain", "kar", "snow", "bulut", "cloud"), "🌤️"),
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", safe_str(s).strip().lower())


_ICON_CACHE: dict[str, str] = {}

# İngilizce hedef kelimeden semantik emoji tahmini
_TARGET_HINT_EMOJI: tuple[tuple[str, ...], str] = (
    (("sparkling", "mineral", "soda water", "club soda"), "🫧"),
    (("water", "juice", "lemonade", "smoothie"), "💧"),
    (("coffee", "tea", "latte", "espresso"), "☕"),
    (("beer", "wine", "whiskey", "vodka"), "🍷"),
    (("bread", "cake", "cookie", "pizza", "burger"), "🍽️"),
    (("apple", "banana", "orange", "fruit"), "🍎"),
    (("carrot", "tomato", "vegetable", "onion"), "🥕"),
    (("dog", "cat", "bird", "fish", "animal"), "🐾"),
    (("phone", "computer", "laptop", "tablet"), "📱"),
    (("book", "novel", "magazine"), "📚"),
    (("invoice", "receipt", "bill", "fatura"), "🧾"),
    (("chair", "sofa", "bed", "desk"), "🛋️"),
    (("door", "window", "wall"), "🪟"),
    (("car", "bus", "train", "plane", "bike"), "🚗"),
    (("shoe", "boot", "sandal"), "👟"),
    (("hospital", "school", "church", "museum"), "📍"),
    (("happy", "sad", "angry", "tired"), "😊"),
    (("music", "song", "guitar", "piano"), "🎵"),
    (("money", "dollar", "euro", "price"), "💰"),
    (("time", "clock", "hour", "minute"), "🕐"),
    (("weather", "rain", "snow", "sun", "cloud"), "🌤️"),
)


def _infer_target_emoji(target_word: str, word_tr: str) -> str:
    tw, wt = _norm(target_word), _norm(word_tr)
    for hints, emoji in _TARGET_HINT_EMOJI:
        if any(h in tw for h in hints) or any(h in wt for h in hints):
            return emoji
    return ""


def _llm_resolve_emoji(word_tr: str, target_word: str) -> str:
    """Sözlükte yoksa LLM ile tek emoji seç (önbellekli)."""
    key = f"{_norm(word_tr)}|{_norm(target_word)}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        from education_engine import _llm_json, llm_available
        if not llm_available():
            return ""
        parsed = _llm_json(
            "Pick exactly ONE emoji that best represents this vocabulary word for a language app. "
            "Return JSON only: {\"emoji\": \"🌽\"}. No text, no explanation.",
            f"Turkish word: {word_tr}\nEnglish word: {target_word}",
            max_tokens=60,
        )
        emoji = safe_str((parsed or {}).get("emoji")).strip()
        if emoji and emoji not in ("🏷️", "❓", "⁉️", "❔"):
            _ICON_CACHE[key] = emoji
            return emoji
    except Exception:
        pass
    return ""


def lookup_emoji(word_tr: str, target_word: str, category: str = "general") -> str:
    """Kelimeye en uygun emoji — sözlük → çıkarım → kategori → LLM → 🏷️."""
    keys: list[str] = []
    for raw in (word_tr, target_word):
        n = _norm(raw)
        if n:
            keys.append(n)
    # Tam eşleşme
    for key in keys:
        if key in EMOJI_BY_WORD:
            return EMOJI_BY_WORD[key]
    # Çok kelimeli ifadeler
    for key in keys:
        for dict_key, emoji in sorted(EMOJI_BY_WORD.items(), key=lambda x: -len(x[0])):
            if _term_matches(dict_key, key) or _term_matches(key, dict_key):
                return emoji
    # Anahtar kelime (Türkçe girdi)
    wt = _norm(word_tr)
    for group, emoji in KEYWORD_EMOJI:
        if any(_term_matches(k, wt) for k in group):
            return emoji
    # İngilizce hedef
    tw = _norm(target_word)
    for group, emoji in KEYWORD_EMOJI:
        if any(_term_matches(k, tw) for k in group):
            return emoji
    # Kategori
    cat = _norm(category)
    if cat in CATEGORY_EMOJI:
        return CATEGORY_EMOJI[cat]
    inferred = _infer_target_emoji(target_word, word_tr)
    if inferred:
        return inferred
    llm_icon = _llm_resolve_emoji(word_tr, target_word)
    if llm_icon:
        return llm_icon
    return "🏷️"
