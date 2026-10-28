"""Türkçe okunuş — yabancı dildeki metnin Türkçe harflerle nasıl okunduğu.

Kural tabanlı (anında, LLM yok): İspanyolca, İtalyanca, Almanca, Fransızca,
Rusça, Gürcüce. İngilizce / Arapça / Çince yazımdan sese kurala dökülemediği
için okunuşu yapay zekâ üretir (eğitimde yanıtla aynı çağrıda gelir); burada
yalnızca önbellek ve yedekler bulunur.

Kural: okunuş HER ZAMAN seslendirilen metnin kendisinden üretilir — çeviriden
değil. Böylece ekranda yazan okunuş ile duyulan ses birebir aynı cümledir.
"""
from __future__ import annotations

import re
import threading
import unicodedata

RULE_LANGS = {"es", "it", "de", "fr", "ru", "ka", "id"}
LLM_LANGS = {"en", "ar", "zh"}

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def _strip_accents(s: str, keep: str = "") -> str:
    out = []
    for ch in s:
        if ch in keep:
            out.append(ch)
            continue
        dec = unicodedata.normalize("NFD", ch)
        out.append("".join(c for c in dec if unicodedata.category(c) != "Mn"))
    return "".join(out)


def _map_words(text: str, fn) -> str:
    """Apply fn to every word (lower-cased); keep punctuation and spacing."""
    def repl(m: re.Match) -> str:
        w = m.group(0)
        out = fn(w.lower())
        if w[:1].isupper() and out:
            out = out[:1].upper() + out[1:]
        return out
    return _WORD_RE.sub(repl, text)


def _tidy(s: str) -> str:
    s = re.sub(r"[¡¿]", "", s)
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _apply(w: str, rules) -> str:
    """Rules write UPPERCASE output so later rules never re-read it."""
    for a, b in rules:
        w = re.sub(a, b, w)
    return w


def _fin(w: str) -> str:
    # dotless ı is written as Ɨ inside rules
    return w.replace("Ɨ", "ı").lower().replace("i̇", "i")


# ---------------------------------------------------------------- Spanish

_ES = [
    (r"ch", "Ç"),
    (r"h", ""),
    (r"ü", "U"),
    (r"ll", "Y"), (r"ñ", "NY"), (r"rr", "R"),
    (r"qu(?=[eiéí])", "K"), (r"gu(?=[eiéí])", "G"),
    (r"c(?=[eiéí])", "S"), (r"c", "K"), (r"z", "S"),
    (r"g(?=[eiéí])", "H"), (r"j", "H"), (r"g", "G"),
    (r"v", "B"), (r"x", "KS"), (r"w", "U"),
    (r"(?<=[aeou])y$", "Y"), (r"y$", "I"), (r"^y$", "I"), (r"y", "Y"),
]


def _glide_i(s: str) -> str:
    """Ünsüzden sonra, ünlüden önce gelen i → y (gracias→grasyas, chiamo→kyamo, estación→estasyon). í/ì (vurgulu) korunur."""
    return re.sub(r"(?<=[bcçdfghjklmnprstvyzğş])i(?=[aeou])", "y", s)


def _es_word(w: str) -> str:
    w = _strip_accents(w.replace("ü", "w"), keep="ñí").replace("w", "ü")
    return _glide_i(_fin(_apply(w, _ES))).replace("í", "i")


# ---------------------------------------------------------------- Italian

_IT = [
    (r"sch", "SK"), (r"sci(?=[aouàòù])", "Ş"), (r"sc(?=[eiéèì])", "Ş"),
    (r"cch(?=[eiéèì])", "KK"), (r"ch(?=[eiéèì])", "K"),
    (r"ggh(?=[eiéèì])", "GG"), (r"gh(?=[eiéèì])", "G"),
    (r"gli(?=[aeouàèòù])", "LY"), (r"^gli$", "LYI"), (r"gli", "LYI"), (r"gn", "NY"),
    (r"cci(?=[aouàòù])", "Ç"), (r"ci(?=[aouàòù])", "Ç"), (r"cc(?=[eiéèì])", "Ç"), (r"c(?=[eiéèì])", "Ç"),
    (r"ggi(?=[aouàòù])", "C"), (r"gi(?=[aouàòù])", "C"), (r"gg(?=[eiéèì])", "C"), (r"g(?=[eiéèì])", "C"),
    (r"qu", "KV"), (r"zz", "TS"), (r"z", "TS"), (r"c", "K"), (r"h", ""),
    (r"j", "Y"), (r"x", "KS"), (r"w", "V"), (r"y", "I"), (r"K+", "K"),
]


def _it_word(w: str) -> str:
    return _glide_i(_fin(_apply(_strip_accents(w, keep="ìí"), _IT))).replace("ì", "i").replace("í", "i")


# ---------------------------------------------------------------- German

_DE_SPECIAL = {
    "ich": "ih", "mich": "mih", "dich": "dih", "sich": "zih", "nicht": "niht",
    "auch": "auh", "noch": "noh", "doch": "doh", "ja": "ya", "und": "unt",
    "sind": "zint", "die": "di", "sie": "zi", "wie": "vi", "bitte": "bite",
    "danke": "danke", "hallo": "halo", "tschüss": "çüs", "tschüs": "çüs",
}
_DE = [
    (r"^ch", "K"),
    (r"tsch", "Ç"), (r"sch", "Ş"),
    (r"^sp", "ŞP"), (r"^st", "ŞT"),
    (r"chs(?=[aeiouäöü]|$)", "KS"),
    (r"ch", "H"),
    (r"ig$", "IH"),
    (r"ie", "I"), (r"ee", "E"), (r"aa", "A"), (r"oo", "O"), (r"ei|ai", "AY"), (r"eu|äu", "OY"), (r"au", "AU"),
    (r"ä", "E"), (r"ph", "F"), (r"th", "T"), (r"dt", "T"),
    (r"qu", "KV"), (r"tz", "TS"), (r"z", "TS"),
    (r"^s(?=[aeiouäöüy])", "Z"), (r"(?<=[aeiouäöüyrlnAEIOUYRLN])s(?=[aeiouäöüy])", "Z"),
    (r"v", "F"), (r"w", "V"), (r"j", "Y"), (r"y", "Ü"), (r"x", "KS"), (r"ck", "K"), (r"c", "K"),
    (r"(?<=[aeiouöüAEIOUÖÜ])h(?![aeiouöü])", ""),
    (r"ss", "S"),
    (r"(?<=[aeiouöüAEIOUÖÜ])b$", "P"), (r"(?<=[aeiouöürlnAEIOUÖÜRLN])d$", "T"),
    (r"(?<=[aeiouöürlnAEIOUÖÜRLN])g$", "K"),
    (r"(?<=.)er$", "ƗR"),
]


def _de_word(w: str) -> str:
    w = w.replace("ß", "ss")
    if w in _DE_SPECIAL:
        return _DE_SPECIAL[w]
    w = _fin(_apply(w, _DE))
    return re.sub(r"([bcdfgklmnprstvz])\1", r"\1", w)


# ---------------------------------------------------------------- French

_FR_SHORT = {
    "le": "lö", "je": "jö", "de": "dö", "ce": "sö", "me": "mö", "te": "tö",
    "se": "sö", "ne": "nö", "que": "kö", "les": "le", "des": "de", "mes": "me",
    "tes": "te", "ses": "se", "ces": "se", "et": "e", "est": "e", "es": "e",
    "un": "en", "une": "ün", "vous": "vu", "nous": "nu", "ils": "il", "elles": "el",
    "très": "tre", "plus": "plü", "oui": "vi", "non": "non", "bien": "biyen",
    "monsieur": "mösyö", "madame": "madam", "femme": "fam", "ville": "vil",
    "mille": "mil", "fils": "fis", "pays": "pei", "aujourd'hui": "ojurdüi",
    "eau": "o", "au": "o", "aux": "o", "ou": "u", "où": "u", "y": "i",
    "a": "a", "à": "a", "en": "an", "on": "on", "dans": "dan", "avec": "avek",
    "pour": "pur", "merci": "mersi", "bonjour": "bonjur", "bonsoir": "bonsuar",
    "ça": "sa", "comment": "koman", "suis": "süi", "fait": "fe", "fais": "fe",
    "est-ce": "es", "qu'est": "kes", "n'est": "ne", "c'est": "se", "s'il": "sil", "j'ai": "je",
    "tu": "tü", "il": "il", "elle": "el", "du": "dü", "au revoir": "orvuar",
    "parce": "pars", "quand": "kan", "sont": "son", "ont": "on", "vont": "von",
    "font": "fon", "aime": "em", "aimes": "em", "aiment": "em",
}
_FR_ENT_KEEP = {
    "moment", "comment", "souvent", "parent", "client", "accident", "argent", "présent",
    "absent", "content", "président", "différent", "excellent", "urgent", "agent",
    "talent", "serpent", "cent", "dent", "lent", "vent", "gent", "évident", "lentement",
    "seulement", "vraiment", "rapidement", "maintenant", "appartement", "restaurant",
}
_FR = [
    (r"tion", "SIYON"), (r"eaux?$", "O"), (r"eau", "O"), (r"aux?$", "O"), (r"au", "O"),
    (r"oin(?![aeiouy])", "UEN"), (r"oi", "UA"), (r"ou|où|oû", "U"),
    (r"(?<=[aeiou])ill", "Y"), (r"ille", "IY"), (r"(?<=[aeiou])il$", "Y"),
    (r"(?:ain|aim|ein|eim)(?![aeiouyn])", "EN"),
    (r"in(?![aeiouyn])|im(?![aeiouymn])|yn(?![aeiouy])", "EN"),
    (r"un(?![aeiouyn])|um(?![aeiouym])", "EN"),
    (r"ien(?![aeiouyn])", "IYEN"),
    (r"(?:an|am|en|em)(?![aeiouyn m])", "AN"),
    (r"on(?![aeiouyn])|om(?![aeiouym])", "ON"),
    (r"aî|ai|ei|ê|è|é|ë", "E"), (r"eu|œu|œ", "Ö"),
    (r"ch", "Ş"), (r"gn", "NY"), (r"qu", "K"), (r"ph", "F"), (r"th", "T"),
    (r"ç", "S"), (r"c(?=[eiyéèê])", "S"), (r"c", "K"),
    (r"ge(?=[aou])", "J"), (r"g(?=[eiyéèê])", "J"), (r"j", "J"),
    (r"(?<=[aeiouyAEIOUYÖÜ])s(?=[aeiouyéèê])", "Z"),
    (r"h", ""), (r"x", "KS"), (r"w", "V"),
    (r"u|û|ù", "Ü"), (r"y", "I"), (r"â|à", "A"), (r"î|ï", "I"), (r"ô", "O"),
]


def _fr_word(w: str) -> str:
    w = w.replace("’", "'")
    if w in _FR_SHORT:
        return _FR_SHORT[w]
    if "'" in w:
        head, _, tail = w.partition("'")
        pre = {"l": "l", "d": "d", "j": "j", "m": "m", "t": "t", "s": "s", "n": "n", "c": "s", "qu": "k", "jusqu": "jüsk", "lorsqu": "lorsk", "puisqu": "püisk"}.get(head, "")
        return pre + _fr_word(tail)
    if "-" in w:
        return "-".join(_fr_word(p) for p in w.split("-"))
    # silent endings
    if w.endswith("ent") and len(w) > 5 and w not in _FR_ENT_KEEP and not w.endswith("ment"):
        w = w[:-3] + "e"
    if len(w) > 3:
        w = re.sub(r"(?<=[^aeiouyéèê])es$", "e", w)
        w = re.sub(r"(er|ez)$", "é", w)
        w = re.sub(r"et$", "è", w)
    if len(w) > 2:
        w = re.sub(r"(?<=[^s])s$", "", w)
    for _ in range(2):
        w = re.sub(r"(?<=[aeiouyéèêîôûnmr])(s|t|d|x|z|p)$", "", w)
    w = re.sub(r"ge$", "J", w)
    w = re.sub(r"ce$", "S", w)
    if len(w) > 2:
        w = re.sub(r"e$", "", w)
    w = _fin(_apply(w, _FR)).replace("i̇", "i")
    return re.sub(r"([bcdfgklmnprstvz])\1", r"\1", w)


# ---------------------------------------------------------------- Russian

_RU_BASE = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h",
    "ц": "ts", "ч": "ç", "ш": "ş", "щ": "şç", "ъ": "", "ы": "ı", "ь": "", "э": "e",
}
_RU_IOTATED = {"е": ("ye", "e"), "ё": ("yo", "yo"), "ю": ("yu", "yu"), "я": ("ya", "ya")}
_RU_HUSH = set("жшщчц")
_RU_VOWELS = set("аеёиоуыэюя")


def _ru_word(w: str) -> str:
    w = re.sub(r"(?<=[ое])го$", "во", w)  # его, сегодня-type genitive ending
    if w == "сегодня":
        w = "севодня"
    if w == "что":
        w = "што"
    out: list[str] = []
    prev = ""
    for ch in w:
        if ch in _RU_IOTATED:
            initial = (not prev) or prev in _RU_VOWELS or prev in "ьъ"
            val = _RU_IOTATED[ch][0 if initial else 1]
            if ch == "ё" and prev in _RU_HUSH:
                val = "o"
            out.append(val)
        else:
            out.append(_RU_BASE.get(ch, ch))
        prev = ch
    return "".join(out)


# ---------------------------------------------------------------- Georgian

_KA = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "j", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "ğ", "ყ": "k", "შ": "ş", "ჩ": "ç", "ც": "ts", "ძ": "dz",
    "წ": "ts", "ჭ": "ç", "ხ": "h", "ჯ": "c", "ჰ": "h",
}
_KA_MTAVRULI_OFF = 0x1C90 - 0x10D0


def _ka_text(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 0x1C90 <= o <= 0x1CBF:
            ch = chr(o - _KA_MTAVRULI_OFF)
        out.append(_KA.get(ch, ch))
    s = "".join(out)
    # sentence-initial capital for readability
    return re.sub(r"(^|[.!?]\s+)([a-zçğış])", lambda m: m.group(1) + m.group(2).upper(), s)


# ---------------------------------------------------------------- Indonesian

_ID_SHORT = {
    "yang": "yang", "dengan": "dıngan", "ke": "kı", "se": "sı", "de": "dı", "te": "tı", "be": "bı", "me": "mı", "pe": "pı",
    "kamu": "kamu", "anda": "anda", "saya": "saya", "aku": "aku", "apa": "apa", "kabar": "kabar", "baik": "bayk",
    "terima": "tırima", "kasih": "kasih", "selamat": "sılamat", "tidak": "tidak", "bagaimana": "bagaymana",
    "ada": "ada", "dan": "dan", "di": "di", "dari": "dari", "ini": "ini", "itu": "itu", "juga": "cuga", "jadi": "cadi",
    "enak": "enak", "ember": "ember", "teh": "te", "sate": "sate", "tempe": "tempe", "kopi": "kopi", "es": "es",
    "enam": "ınam", "empat": "ımpat", "engkau": "ıngkau", "untuk": "untuk", "orang": "orang", "bisa": "bisa",
}
_ID_E_KEEP = {"bebek", "lele", "indonesia", "restoran", "menu", "hotel", "telepon", "besok", "bensin", "sate", "tempe",
              "komputer", "internet", "televisi", "energi", "teknologi", "kopi", "ekonomi", "negeri", "gereja"}
_ID = [
    (r"ngg", "NGG"), (r"ng", "NG"), (r"ny", "NY"), (r"sy", "Ş"), (r"kh", "H"), (r"gh", "Ğ"),
    (r"ai", "AY"), (r"au", "AV"), (r"oi", "OY"),
    (r"c", "Ç"), (r"j", "C"), (r"q", "K"), (r"x", "KS"), (r"w", "V"),
]


def _id_word(w: str) -> str:
    if w in _ID_SHORT:
        return _ID_SHORT[w]
    w = _strip_accents(w)
    last = max((i for i, ch in enumerate(w) if ch in "aeiou"), default=-1)
    # Yerli sözcüklerde 'e' çoğunlukla belirsiz ünlü (ı): ilk/orta hecelerde ı; son hecede ve sözcük başında e
    chars = []
    for i, ch in enumerate(w):
        if ch == "e" and i != 0 and i != last and w not in _ID_E_KEEP:
            chars.append("Ɨ")
        else:
            chars.append(ch)
    w = "".join(chars)
    w = re.sub(r"^e(?=[mn][bcdfgjklmnprstvz])", "Ɨ", w)  # empat, enam, engkau
    return _fin(_apply(w, _ID))


_WORD_FNS = {"id": _id_word, "es": _es_word, "it": _it_word, "de": _de_word, "fr": _fr_word, "ru": _ru_word}


def rule_okunus(text: str, lang: str) -> str:
    """Kural tabanlı okunuş; desteklenmeyen dilde boş döner."""
    text = (text or "").strip()
    if not text:
        return ""
    lang = (lang or "").split("-")[0].lower()
    try:
        if lang == "ka":
            return _tidy(_ka_text(text))
        fn = _WORD_FNS.get(lang)
        if fn:
            return _tidy(_map_words(text, fn))
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------- cache + LLM path

_CACHE: dict[tuple[str, str], str] = {}
_LOCK = threading.Lock()


def remember(text: str, lang: str, okunus: str) -> None:
    text, okunus = (text or "").strip(), (okunus or "").strip()
    if not text or not okunus:
        return
    with _LOCK:
        if len(_CACHE) > 3000:
            _CACHE.clear()
        _CACHE[(lang, text)] = okunus


def cached(text: str, lang: str) -> str:
    with _LOCK:
        return _CACHE.get((lang, (text or "").strip()), "")


_TR_ALLOWED = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ0-9\s.,!?;:'’\"“”«»()\-–—…/]+$")


_TRANSLIT_MAP = str.maketrans({
    "ā": "â", "ī": "î", "ū": "û", "Ā": "Â", "Ī": "Î", "Ū": "Û", "ē": "e", "ō": "o",
    "ḥ": "h", "Ḥ": "H", "ḫ": "h", "ṣ": "s", "Ṣ": "S", "ḍ": "d", "Ḍ": "D", "ṭ": "t", "Ṭ": "T",
    "ẓ": "z", "Ẓ": "Z", "ḏ": "z", "ṯ": "s", "ġ": "ğ", "Ġ": "Ğ", "ž": "j", "š": "ş", "č": "ç",
    "ʿ": "'", "ʾ": "'", "ʼ": "'", "‘": "'", "`": "'", "é": "e", "è": "e", "á": "a", "à": "a",
    "ó": "o", "ò": "o", "í": "i", "ì": "i", "ú": "u", "ù": "u", "ñ": "ny", "q": "k", "Q": "K",
    "w": "v", "W": "V", "x": "h", "X": "H",
})


def normalize_okunus(text: str) -> str:
    """Model çıktısındaki transliterasyon harflerini Türk alfabesine çevir (ā→â, ḥ→h, q→k, w→v…)."""
    t = (text or "").translate(_TRANSLIT_MAP)
    t = re.sub(r"\bth", "t", t)
    t = re.sub(r"dh", "z", t)
    return re.sub(r"\s+", " ", t).strip()


def looks_valid(okunus: str, source: str, lang: str) -> bool:
    """LLM okunuşu kontrolü: yalnız Türk alfabesi (IPA yok), kaynak yazı değil, makul uzunluk."""
    o = (okunus or "").strip()
    if not o or len(o) < 2:
        return False
    if not _TR_ALLOWED.match(o) or re.search(r"[qwx]", o.lower()):
        return False
    if re.search(r"[؀-ۿ一-鿿Ⴀ-ჿЀ-ӿ]", o):
        return False
    if lang != "en" and o.lower() == (source or "").strip().lower():
        return False
    ratio = len(o) / max(1, len(source))
    if lang == "zh":
        return 0.8 <= ratio <= 12
    return 0.35 <= ratio <= 3.5


def okunus(text: str, lang: str, llm_fn=None) -> str:
    """En iyi okunuş: kural → önbellek → (isteğe bağlı) LLM → İngilizce sözlük yedeği."""
    text = (text or "").strip()
    lang = (lang or "").split("-")[0].lower()
    if not text or lang == "tr":
        return ""
    if lang in RULE_LANGS:
        return rule_okunus(text, lang)
    hit = cached(text, lang)
    if hit:
        return hit
    if lang == "zh":
        # LLM'siz, anında ve tutarlı: pypinyin varsa pinyin → Türkçe okunuş
        try:
            from pypinyin import Style, lazy_pinyin
            py = " ".join(lazy_pinyin(text, style=Style.TONE, errors=lambda x: [x]))
            py = py.translate(str.maketrans("，。？！；：、", ",.?!;:,"))
            py = re.sub(r"\s+([,.?!;:])", lambda m: m.group(1), py)
            got = pinyin_okunus(py)
            if got.strip():
                remember(text, lang, got)
                return got
        except Exception:
            pass
    if llm_fn is not None:
        try:
            got = (llm_fn(text, lang) or "").strip()
        except Exception:
            got = ""
        if looks_valid(got, text, lang):
            remember(text, lang, got)
            return got
    if lang == "fr":
        return rule_okunus(text, lang)
    if lang == "en":
        try:
            from pronunciation_service import build_sentence_natural
            return (build_sentence_natural(text, "en") or "").strip()
        except Exception:
            return ""
    return ""


# ---------------------------------------------------------------- Chinese (pinyin → Türkçe)

_PY_INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w"]
_PY_FINALS = ["iang", "iong", "uang", "ueng", "ang", "eng", "ing", "ong", "iao", "ian", "uai", "uan", "üan", "ai", "ei", "ao", "ou",
              "an", "en", "in", "un", "ün", "ia", "ie", "iu", "ua", "uo", "ui", "üe", "ue", "er", "a", "o", "e", "i", "u", "ü", "v"]
_PY_INI_TR = {"zh": "c", "ch": "ç", "sh": "ş", "j": "c", "q": "ç", "x": "ş", "r": "j", "z": "dz", "c": "ts", "w": "v"}
_PY_FIN_TR = {
    "a": "a", "o": "o", "e": "ı", "ai": "ay", "ei": "ey", "ao": "au", "ou": "ou", "an": "an", "en": "ın", "ang": "ang",
    "eng": "ıng", "ong": "ung", "er": "ır", "i": "i", "ia": "ya", "ie": "ye", "iao": "yau", "iu": "yu", "ian": "yen",
    "in": "in", "iang": "yang", "ing": "ing", "iong": "yung", "u": "u", "ua": "ua", "uo": "uo", "uai": "uay", "ui": "uey",
    "uan": "uan", "un": "un", "uang": "uang", "ueng": "ung", "ü": "ü", "v": "ü", "üe": "üe", "ue": "üe", "üan": "üen", "ün": "ün",
}
_PY_SPECIAL = {
    "yi": "i", "ya": "ya", "ye": "ye", "yao": "yau", "you": "yo", "yan": "yen", "yin": "in", "yang": "yang", "ying": "ing",
    "yong": "yung", "yu": "yü", "yue": "yüe", "yuan": "yüen", "yun": "yün", "wu": "u", "wa": "va", "wo": "vo", "wai": "vay",
    "wei": "vey", "wan": "van", "wen": "vın", "wang": "vang", "weng": "vıng", "a": "a", "o": "o", "e": "ı", "ai": "ay",
    "ei": "ey", "ao": "au", "ou": "ou", "an": "an", "en": "ın", "ang": "ang", "eng": "ıng", "er": "ır",
}


def _py_syllables() -> set[str]:
    out = set(_PY_SPECIAL)
    for ini in _PY_INITIALS:
        if ini in ("y", "w"):
            continue
        for fin in _PY_FINALS:
            out.add(ini + fin)
    return out


_PY_SET = _py_syllables()
_PY_MAX = max(len(s) for s in _PY_SET)


def _py_strip_tones(s: str) -> str:
    s = unicodedata.normalize("NFD", s).replace("ü", "\0").replace("Ü", "\1")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("\0", "ü").replace("\1", "Ü")


def _py_syl_tr(syl: str) -> str:
    if syl in _PY_SPECIAL:
        return _PY_SPECIAL[syl]
    for ini in _PY_INITIALS:
        if syl.startswith(ini):
            fin = syl[len(ini):]
            if ini in ("j", "q", "x"):
                fin = {"u": "ü", "ue": "üe", "uan": "üan", "un": "ün"}.get(fin, fin)
            ini_tr = _PY_INI_TR.get(ini, ini)
            if fin == "i" and ini in ("zh", "ch", "sh", "r", "z", "c", "s"):
                return ini_tr + "ı"
            fin_tr = _PY_FIN_TR.get(fin, fin)
            if ini in ("j", "q", "x") and fin_tr.startswith("y"):
                fin_tr = "i" + fin_tr[1:]  # jiao → ciau (cyau değil)
            return ini_tr + fin_tr
    return syl


def _py_segment(word: str) -> list[str] | None:
    """Greedy-with-backtracking split of a joined pinyin word ('xihuan' → xi, huan)."""
    memo: dict[int, list[str] | None] = {}

    def go(i: int) -> list[str] | None:
        if i == len(word):
            return []
        if i in memo:
            return memo[i]
        for L in range(min(_PY_MAX, len(word) - i), 0, -1):
            piece = word[i:i + L]
            if piece in _PY_SET:
                rest = go(i + L)
                if rest is not None:
                    memo[i] = [piece] + rest
                    return memo[i]
        memo[i] = None
        return None

    return go(0)


def pinyin_okunus(pinyin: str) -> str:
    """'Wǒ yě xǐhuan hē kāfēi.' → 'Vo ye şihuan hı kafey.'"""
    text = re.sub(r"(?<=[A-Za-zÜü])[1-5]", "", _py_strip_tones(pinyin or "")).strip()
    if not text:
        return ""

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        parts = []
        for chunk in re.split(r"['’]", raw.lower()):
            segs = _py_segment(chunk.replace("v", "ü")) if chunk else []
            if segs is None:
                parts.append(chunk)
            else:
                parts.append("".join(_py_syl_tr(s) for s in segs))
        out = "".join(parts)
        return out[:1].upper() + out[1:] if raw[:1].isupper() else out

    out = _tidy(re.sub(r"[A-Za-zÜü'’]+", repl, text))
    return re.sub(r"(^|[.!?]\s+)([a-zçğışöü])", lambda m: m.group(1) + m.group(2).upper(), out)
