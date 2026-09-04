#!/usr/bin/env python3
"""Sesli Çevirmen — statik dosya + TTS/çeviri API sunucusu."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
import asyncio
import html
import json
import os
import re
import subprocess
import tempfile
import time

from tutor import get_lesson, tutor_reply
from education_engine import (
    process_turn, greeting, session_report, daily_lesson, default_profile,
    finalize_session, weekly_progress, merge_profile, llm_available, ai_provider_info,
    pronounce_text, safe_str, llm_translate, groq_api_key_status,
    llm_rewrite_georgian, llm_verify_and_fix_translation,
)
from builder_engine import (
    generate_word_lesson,
    analyze_sentence_for_builder,
    grade_word_answer,
    grade_sentence_answer,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "2026.09.04-v72.2"
TARGET_APP_VERSION = APP_VERSION
PORT = int(os.environ.get("PORT", "8780"))


def _version_number(version: str) -> int:
    m = re.search(r"-v(\d+)$", safe_str(version).strip(), re.I)
    return int(m.group(1)) if m else 0


def _deploy_hook_url() -> str:
    return safe_str(os.environ.get("RENDER_DEPLOY_HOOK") or os.environ.get("DEPLOY_HOOK_URL")).strip()


def _trigger_render_deploy() -> tuple[bool, str]:
    hook = _deploy_hook_url()
    if not hook:
        return False, "Deploy bağlantısı yapılandırılmamış."
    try:
        req = Request(hook, data=b"", method="POST", headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=45) as resp:
            if 200 <= resp.status < 300:
                return True, "Güncelleme başlatıldı."
            return False, f"Deploy isteği başarısız (HTTP {resp.status})."
    except Exception as exc:
        return False, f"Deploy isteği gönderilemedi: {exc}"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
DISABLE_WHISPER = os.environ.get("DISABLE_WHISPER", "1").lower() in ("1", "true", "yes")
EDU_STATE_MARKER = b"\n--EDU_STATE_END--\n"

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"

STT_LANG = {
    "tr": "tr-TR", "en": "en-US", "de": "de-DE", "fr": "fr-FR",
    "es": "es-ES", "ka": "ka-GE", "ar": "ar-SA", "ru": "ru-RU",
    "it": "it-IT", "zh": "zh-CN",
}

EDGE_VOICES = {
    "tr": "tr-TR-AhmetNeural",
    "en": "en-US-JennyNeural",
    "ka": "ka-GE-EkaNeural",
    "de": "de-DE-KatjaNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
    "ar": "ar-SA-ZariyahNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "it": "it-IT-ElsaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
}


def is_mp3(data: bytes) -> bool:
    if len(data) < 100:
        return False
    if data[:3] == b"ID3":
        return True
    return data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def google_tts(text: str, lang: str) -> bytes | None:
    url = (
        "https://translate.google.com/translate_tts?"
        f"client=tw-ob&tl={quote(lang)}&q={quote(text)}"
    )
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=15) as resp:
            data = resp.read()
        return data if is_mp3(data) else None
    except Exception:
        return None


def edge_tts(text: str, lang: str, rate: str = "+0%") -> bytes:
    import edge_tts

    voice = EDGE_VOICES.get(lang, EDGE_VOICES["en"])

    async def _run() -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = tmp.name
        try:
            await communicate.save(path)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.unlink(path)

    return asyncio.run(_run())


def synthesize(text: str, lang: str, slow: bool = False) -> bytes:
    if slow:
        return edge_tts(text, lang, rate="-15%")
    data = google_tts(text, lang)
    if data:
        return data
    return edge_tts(text, lang, rate="+18%")


GOOGLE_TL = {
    "tr": "tr", "en": "en", "de": "de", "fr": "fr", "es": "es",
    "ka": "ka", "ar": "ar", "ru": "ru", "it": "it", "zh": "zh-CN",
}


def google_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    sl = GOOGLE_TL.get(from_lang, from_lang)
    tl = GOOGLE_TL.get(to_lang, to_lang)
    url = (
        f"https://translate.google.com/m?sl={quote(sl)}&tl={quote(tl)}"
        f"&q={quote(text)}"
    )
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=8) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
        match = re.search(r'class="result-container">([^<]+)', page)
        if not match:
            match = re.search(r'<div class="t0">([^<]+)', page)
        if match:
            return html.unescape(match.group(1).strip())
    except Exception:
        pass
    return None


def _chunk_for_translate(text: str, max_len: int = 220) -> list[str]:
    """Uzun metni kelime sınırında parçala — Google URL limiti / hız."""
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) <= max_len:
        return [t]
    # Cümle sonu varsa tercih et
    parts = re.split(r"(?<=[.!?…;:])\s+", t)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not buf:
            buf = part
        elif len(buf) + 1 + len(part) <= max_len:
            buf = f"{buf} {part}"
        else:
            chunks.append(buf)
            buf = part
    if buf:
        chunks.append(buf)
    # Hâlâ çok uzun parçalar → kelime kes
    out: list[str] = []
    for ch in chunks:
        if len(ch) <= max_len:
            out.append(ch)
            continue
        words = ch.split()
        cur: list[str] = []
        for w in words:
            trial = " ".join(cur + [w])
            if cur and len(trial) > max_len:
                out.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        if cur:
            out.append(" ".join(cur))
    return out or [t]


def google_translate_fast(text: str, from_lang: str, to_lang: str) -> str | None:
    """Google çeviri — uzun metinde paralel parça (hızlı)."""
    src = text.strip()
    if not src:
        return ""
    chunks = _chunk_for_translate(src)
    if len(chunks) == 1:
        return google_translate(chunks[0], from_lang, to_lang)

    results: list[str | None] = [None] * len(chunks)

    def _one(i: int, piece: str) -> None:
        results[i] = google_translate(piece, from_lang, to_lang)

    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        futs = [pool.submit(_one, i, c) for i, c in enumerate(chunks)]
        for fut in futs:
            try:
                fut.result(timeout=8)
            except Exception:
                pass
    if any(not r for r in results):
        # Parça başarısızsa tek seferde dene
        return google_translate(src[:4500], from_lang, to_lang)
    return " ".join(r.strip() for r in results if r)


def mymemory_translate(text: str, from_lang: str, to_lang: str) -> str:
    url = (
        "https://api.mymemory.translated.net/get?"
        f"q={quote(text[:450])}&langpair={quote(from_lang)}|{quote(to_lang)}"
    )
    with urlopen(url, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    translated = data.get("responseData", {}).get("translatedText", "").strip()
    if not translated:
        raise ValueError("empty translation")
    return translated


_TRANSLATE_CACHE: dict[tuple[str, str, str], str] = {}
_WORD_LESSON_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_CACHE_TTL_SEC = 3600


def _cache_get(cache: dict, key: tuple, ttl: float = _CACHE_TTL_SEC):
    hit = cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.monotonic() - ts > ttl:
        cache.pop(key, None)
        return None
    return val


def _cache_set(cache: dict, key: tuple, val, max_size: int = 400) -> None:
    if len(cache) >= max_size:
        cache.clear()
    cache[key] = (time.monotonic(), val)


def _is_short_simple_utterance(text: str) -> bool:
    """Günlük kısa söz — hikâye / çok cümle / karmaşık yapı değil."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return True
    if re.search(
        r"\b\w+(?:nın|nin|nun|nün|ın|in|un|ün)\s+\d+\s+yaşında\b",
        t,
        re.I,
    ):
        return False
    if re.search(r"bir\s+varm[ıi][şs]\s+bir\s+yokmu[şs]", t, re.I):
        return False
    if re.search(r"\b(çünkü|fakat|ancak|rağmen|eğer|although|because)\b", t, re.I):
        return False
    sentences = [s for s in re.split(r"[.!?…]+", t) if s.strip()]
    if len(sentences) > 1:
        return False
    words = t.split()
    if len(words) > 8 or len(t) > 80:
        return False
    return True


def _needs_quality_translate(text: str, from_lang: str = "tr", to_lang: str = "en") -> bool:
    """Uzun / çok cümle / anlatı / zamir bağlamı — tüm dil çiftlerinde LLM kalite yolu."""
    t = text.strip()
    if re.search(
        r"\b\w+(?:nın|nin|nun|nün|ın|in|un|ün)\s+\d+\s+yaşında\b",
        t,
        re.I,
    ):
        return True
    if re.search(r"bir\s+varm[ıi][şs]\s+bir\s+yokmu[şs]", t, re.I):
        return True
    sentences = [s for s in re.split(r"[.!?…]+", t) if s.strip()]
    if len(sentences) > 1:
        return True
    words = t.split()
    if len(words) >= 14 or len(t) >= 90:
        return True
    # Anlatı / zamir bağlama riski (kısa sohbet hariç)
    if len(words) >= 8 and re.search(
        r"\b(she|he|they|her|his|their|them|felt|began|was|were|had|girl|boy|"
        r"o|onun|kendini|hissetti|hissediyordu|başladı)\b",
        t,
        re.I,
    ):
        return True
    # Kısa günlük ifade → Google hızı (tüm diller)
    if _is_short_simple_utterance(t):
        return False
    # Orta uzunluk / karmaşık yapı → kalite (EN hedef dahil)
    return True


def _looks_like_literal_calque(src: str, translated: str, to_lang: str) -> bool:
    """Kelime-kelime / yapay çeviri izleri — QC tetikle."""
    if not translated:
        return True
    src_l = (src or "").lower()
    tr = translated
    if to_lang == "tr":
        if re.search(r"hiç olmadığı kadar daha\b", tr, re.I):
            return True
        if re.search(r"\bo\s+hiç olmadığı kadar\b", tr, re.I) and re.search(
            r"\bfelt\b|\bfreer\b|\bfree\b", src_l
        ):
            return True
        if re.search(r"\b(daha özgür hissetti|özgür hissetti)\b", tr, re.I) and re.search(
            r"\bfelt freer|freer than ever\b", src_l
        ):
            return True
    # Genel: kaynak ile birebir aynı kelime sırası şüphesi (aynı token sayısı + Latin kalıntı)
    if to_lang in ("tr", "ka", "ru", "ar", "zh") and re.search(
        r"\b(the|and|of|to|was|were|felt|than|ever)\b", tr, re.I
    ):
        return True
    return False


def _should_run_translate_qc(src: str, translated: str, from_lang: str, to_lang: str) -> bool:
    if not translated or not llm_available():
        return False
    if _needs_quality_translate(src, from_lang, to_lang):
        return True
    if _looks_like_literal_calque(src, translated, to_lang):
        return True
    if _translation_has_age_possession_bug(src, translated):
        return True
    if _translation_is_garbled(src, translated, to_lang):
        return True
    return False


def _apply_translate_qc(src: str, result: str, from_lang: str, to_lang: str) -> str:
    """Çeviri sonrası ikinci kontrol — kullanıcıya göstermeden düzelt."""
    if not result or not _should_run_translate_qc(src, result, from_lang, to_lang):
        return result
    try:
        fixed = llm_verify_and_fix_translation(src, result, from_lang, to_lang)
    except Exception:
        fixed = None
    if not fixed:
        return result
    if not _script_matches_lang(fixed, to_lang):
        return result
    if _translation_has_age_possession_bug(src, fixed):
        return result
    if _translation_is_garbled(src, fixed, to_lang):
        return result
    return fixed


def _script_matches_lang(text: str, lang: str) -> bool:
    """Hedef dilin yazısı yoksa çeviri geçersiz (zh→İngilizce sızıntısı)."""
    t = (text or "").strip()
    if not t:
        return False
    if lang == "ka":
        return bool(re.search(r"[\u10A0-\u10FF]", t))
    if lang == "ar":
        return bool(re.search(r"[\u0600-\u06FF]", t))
    if lang == "ru":
        return bool(re.search(r"[\u0400-\u04FF]", t))
    if lang == "zh":
        return bool(re.search(r"[\u4e00-\u9fff]", t))
    if lang in ("de", "fr", "es", "it", "en", "tr"):
        if re.search(r"[\u10A0-\u10FF\u0600-\u06FF\u0400-\u04FF\u4e00-\u9fff]", t):
            return False
        return True
    return True


def _translation_has_age_possession_bug(src: str, translated: str) -> bool:
    """'X'in N yaşında oğlu' → 'X N yaşındaydı' hatasını yakala."""
    if not src or not translated:
        return False
    if not re.search(
        r"\b\w+(?:nın|nin|nun|nün|ın|in|un|ün)\s+\d+\s+yaşında\s+(?:bir\s+)?(?:oğlu|kızı|çocuğu|oglu|kizi|cocugu)\b",
        src,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:was|is|were|are)\s+\d+\s+years?\s+old\b|"
            r"\b(?:avait|avait|a)\s+\d+\s+ans\b(?!\s+(?:et|,|\.|fils|fille|enfant|garçon))|"
            r"\b(?:had|has)\s+\d+\s+años\b|"
            r"\b(?:aveva|ha)\s+\d+\s+anni\b|"
            r"\b(?:war|ist)\s+\d+\s+Jahre(?:\s+alt)?\b|"
            r"\bбыло\s+\d+\s+года\b|"
            r"\b\d+\s+წლის\s+(?:იყო|არის)\b|"
            r"\bكان\s+(?:هذا\s+)?(?:الرجل|الرجل)\s+يبلغ\b|"
            r"\b(?:男人|这(?:个)?人).{0,6}(?:岁|歲)\b",
            translated,
            re.I,
        )
    ) and not bool(
        re.search(
            r"\b(?:had|has)\s+(?:a\s+)?\d+[- ]year[- ]old|"
            r"fils de \d+|hijo de \d+|figlio di \d+|"
            r"\d+-jährigen Sohn|\d+ Jahre alten Sohn|"
            r"четырёхлетн|четырехлетн|"
            r"ოთხი წლის|ოთხწლ|"
            r"ابن.{0,12}الرابعة|四岁",
            translated,
            re.I,
        )
    )


def _polish_georgian(src: str, text: str) -> str:
    """Yalnız yanlış calque/gramer düzelt — kaynak anlamını değiştirme (köy≠kasaba, canlan≠gerçeğe dönüş)."""
    t = text or ""
    src_l = (src or "").lower()

    # Gramer (anlam aynı)
    t = t.replace("მცირე გოგონ", "პატარა გოგონ")
    t = t.replace("სუნთქვაშეკრული პატარა გოგონამ", "სუნთქვაშეკრულმა პატარა გოგონამ")
    t = t.replace("სუნთქვაშეკრული გოგონამ", "სუნთქვაშეკრულმა გოგონამ")
    t = t.replace("სუნთქვა შეკრული, პატარა გოგონამ", "პატარა გოგონამ სუნთქვა შეიკრა და")
    t = t.replace("სუნთქვა შეკრული პატარა გოგონამ", "პატარა გოგონამ სუნთქვა შეიკრა და")
    t = t.replace("სუნთქვა შეიკრა პატარა გოგონას და", "პატარა გოგონამ სუნთქვა შეიკრა და")
    t = t.replace("სუნთქვა შეიკრა პატარა გოგონას", "პატარა გოგონამ სუნთქვა შეიკრა")

    # Yanlış sözlük (çınar ≠ düzlem / mantar)
    if "çınar" in src_l or "plane tree" in src_l or "platan" in src_l:
        t = t.replace("ბებერ სიბრტყესთან", "ძველ ჭადართან")
        t = t.replace("ძველ სიბრტყემდე", "ძველ ჭადარამდე")
        t = t.replace("სიბრტყესთან", "ჭადართან")
        t = t.replace("სიბრტყემდე", "ჭადარამდე")
        t = t.replace("სიბრტყეზე", "ჭადარაზე")
        t = t.replace("სიბრტყე", "ჭადარა")
        t = t.replace("სოკოსთან", "ჭადართან")
        t = t.replace("სოკო", "ჭადარა")
    if re.search(r"kovu|hollow|дупло", src_l):
        t = t.replace("ხის ღრუში", "ხის ფუღუროში")
        t = t.replace("ხის ღრმულში", "ხის ფუღუროში")
        if "bardak" not in src_l and "fincan" not in src_l and "cup" not in src_l:
            t = t.replace("ჭიქაში", "ფუღუროში")

    # Yer: köy / kasaba / şehir ayrı — birbirine çevirme
    has_koy = bool(re.search(r"köy|village", src_l))
    has_kasaba = bool(re.search(r"kasaba|\btown\b", src_l))
    has_city = bool(re.search(r"şehir|\bcity\b|\bstadt\b", src_l)) and not has_koy and not has_kasaba
    if has_koy and not has_kasaba:
        t = t.replace("ქალაქის ბოლოში მდებარე", "სოფლის პირას მდებარე")
        t = t.replace("ქალაქის ბოლოში", "სოფლის პირას")
        t = t.replace("ქალაქის პირას", "სოფლის პირას")
        t = t.replace("დაბის პირას", "სოფლის პირას")
        t = t.replace("დაბის ბოლოში", "სოფლის პირას")
    elif has_kasaba and not has_koy:
        t = t.replace("სოფლის პირას მდებარე", "დაბის პირას მდებარე")
        t = t.replace("სოფლის პირას", "დაბის პირას")
        t = t.replace("სოფლის ბოლოში", "დაბის პირას")
        t = t.replace("სოფლის ბოლოს", "დაბის ბოლოს")
        t = t.replace("ქალაქის ბოლოში მდებარე", "დაბის პირას მდებარე")
        t = t.replace("ქალაქის ბოლოში", "დაბის პირას")
        t = t.replace("ქალაქის პირას", "დაბის პირას")
    elif has_city:
        t = t.replace("სოფლის პირას", "ქალაქის პირას")
        t = t.replace("დაბის პირას", "ქალაქის პირას")

    if re.search(r"eline ald|picked up|kitabı eline|picked the book", src_l):
        t = t.replace("ხელში აიყვანა", "ხელში აიღო")
        t = t.replace("ხელში აიყვან", "ხელში აიღ")
    if re.search(r"omzuna kon|omzuna indi|omzuna otur|landed on (?:her |his )?shoulder|perched", src_l):
        t = t.replace("მხარზე დაეშვა", "მხარზე ჩამოჯდა")
        t = t.replace("მხარზე დასხა", "მხარზე ჩამოჯდა")
        t = t.replace("მხარზე დაიკაშა", "მხარზე ჩამოჯდა")
    # Başını yana eğdi ≠ omza eğdi
    if re.search(r"yana eğ|ba[sş]ını.*eğ|tilted.{0,20}head|head.{0,12}side", src_l):
        t = t.replace("თავი ოდნავ მხარზე დახარა", "თავი ოდნავ გვერდზე დახარა")
        t = t.replace("თავი მხარზე დახარა", "თავი გვერდზე დახარა")

    # Ahşaptan oymak / yontmak
    if re.search(r"ahşap|oyuncak|carve|from wood|oyma", src_l) and re.search(
        r"yap|oy|kazı|carve|will make|yapaca[gğ]", src_l
    ):
        t = t.replace("ხისგან გააკეთებს", "ხისგან გამოთლის")
        t = t.replace("ხისგან გააკეთა", "ხისგან გამოთალა")

    # canlandı ≠ gerçeğe dönüştü — ayrı tut
    if re.search(r"\bcanland[ıi]|came to life|come to life|gacocxld|ცოცხლ", src_l) and not re.search(
        r"gerçeğe dönüş|became real|turned into reality|came true", src_l
    ):
        t = t.replace("რეალობად იქცა", "ცოცხლდებოდა")
        t = t.replace("რეალობად იქცევა", "ცოცხლდება")
    if re.search(r"gerçeğe dönüş|became real|turned into reality|came true", src_l) and not re.search(
        r"\bcanland[ıi]|came to life|come to life", src_l
    ):
        t = t.replace("ცოცხლდებოდა", "რეალობად იქცა")
        t = t.replace("ცოცხლდება", "რეალობად იქცევა")
        t = t.replace("გაცოცხლდა", "რეალობად იქცა")

    if re.search(r"dolmay[ıi]|dolars|doldurul|to be filled|waiting to be filled", src_l):
        t = t.replace("გაივსოს", "აივსოს")
    if re.search(r"kelebek|butterfl", src_l):
        t = t.replace("მწვანეები", "პეპლები")
    if re.search(r"cıvılda|cikcik|chirp", src_l):
        t = t.replace("ჩივლით", "ჭიკჭიკით")
    if re.search(r"takip et|follow", src_l):
        t = t.replace("გაჰყვანა", "გაჰყოლოდა")
        t = t.replace("გაჰყოლოდას", "გაჰყოლოდა")
    return t


def _georgian_fidelity_broken(src: str, translated: str) -> bool:
    """Kaynak anlamını değiştiren KA çeviriyi reddet."""
    if not src or not translated:
        return False
    src_l = src.lower()
    # kasaba/town → village
    if re.search(r"kasaba|\btown\b", src_l) and not re.search(r"köy|village", src_l):
        if "სოფლ" in translated:
            return True
    # köy/village → city/town
    if re.search(r"köy|village", src_l) and not re.search(r"kasaba|\btown\b|şehir|\bcity\b", src_l):
        if "ქალაქ" in translated or re.search(r"დაბ[აის]", translated):
            return True
    # gerçeğe dönüş ≠ canlan
    if re.search(r"gerçeğe dönüş|became real|turned into reality|came true", src_l):
        if "ცოცხლდებოდა" in translated or "გაცოცხლდა" in translated or "ცოცხლდებ" in translated:
            return True
    if re.search(r"\bcanland[ıi]|came to life|come to life", src_l) and not re.search(
        r"gerçeğe dönüş|became real", src_l
    ):
        if "რეალობად იქცა" in translated or "რეალობად" in translated:
            return True
    # başını yana eğdi ≠ omza
    if re.search(r"yana eğ|tilted.{0,20}head|head.{0,12}side", src_l):
        if "თავი" in translated and "მხარზე დახარა" in translated:
            return True
    return False


def _georgian_rewrite_ok(src: str, draft: str, rewritten: str) -> bool:
    if not rewritten or not _script_matches_lang(rewritten, "ka"):
        return False
    if _translation_is_garbled(src, rewritten, "ka"):
        return False
    if _georgian_fidelity_broken(src, rewritten):
        return False
    if draft and len(rewritten) < max(24, int(len(draft) * 0.5)):
        return False
    return True


def _translation_is_garbled(src: str, translated: str, lang: str) -> bool:
    """Edebi TR kelimelerin hedef dilde saçma karşılığı (Gürcüce sökü/kelebek vb.)."""
    if not translated:
        return True
    src_l = src.lower()
    if lang == "ka":
        if _georgian_fidelity_broken(src, translated):
            return True
        if "სოკო" in translated and "çınar" in src_l:
            return True
        if "მწვანეები" in translated and "kelebek" in src_l:
            return True
        if "ჭიქა" in translated and "kovuk" in src_l:
            return True
        if "სასოფლო" in translated and "sihirli" in src_l:
            return True
        if "მცირე გოგონ" in translated:
            return True
        if "სიბრტყე" in translated and "çınar" in src_l:
            return True
        if "დახრიла" in translated or "ჩივლით" in translated:
            return True
        if "თანხლებით დაიწყო" in translated or "იმედს აცოცხლებს" in translated:
            return True
        if "ზრდასრულ ჭადარ" in translated:
            return True
        if "მხარზე დასხა" in translated or "მხარზე დაიკაშა" in translated:
            return True
        if "აიყვანა" in translated and re.search(r"eline ald|picked up", src_l):
            return True
    if lang == "es" and re.search(r"\bcedro", translated, re.I) and "çınar" in src_l:
        return True
    if lang == "zh" and "樟树" in translated and "çınar" in src_l:
        return True
    # KA→TR/EN: village/köy korunmalı
    if lang in ("tr", "en") and re.search(r"სოფლ", src):
        if lang == "tr" and re.search(r"\bkasaba\b", translated, re.I) and not re.search(r"\bköy\b", translated, re.I):
            return True
        if lang == "en" and re.search(r"\btown\b", translated, re.I) and not re.search(r"\bvillage\b", translated, re.I):
            return True
    if lang in ("tr", "en") and re.search(r"ცოცხლდებ", src):
        if lang == "tr" and re.search(r"gerçeğe dönüş", translated, re.I):
            return True
        if lang == "en" and re.search(r"became real|turned into reality|came true", translated, re.I):
            return True
    return False


def _pick_translation(src: str, to_lang: str, llm_r: str | None, g_r: str | None) -> str | None:
    """LLM'i tercih et; Gürcüce'de yerli yeniden yazım (llm_r) Google taslağından önce."""
    if to_lang == "ka":
        if g_r:
            g_r = _polish_georgian(src, g_r)
        if llm_r:
            llm_r = _polish_georgian(src, llm_r)

    def _ok(val: str | None) -> bool:
        if not val:
            return False
        if not _script_matches_lang(val, to_lang):
            return False
        if _translation_has_age_possession_bug(src, val):
            return False
        if _translation_is_garbled(src, val, to_lang):
            return False
        return True

    if to_lang == "ka":
        if _ok(llm_r):
            return llm_r
        if _ok(g_r):
            return g_r
        if llm_r and _script_matches_lang(llm_r, "ka"):
            return llm_r
        if g_r and _script_matches_lang(g_r, "ka"):
            return g_r
        return llm_r or g_r

    if _ok(llm_r):
        return llm_r
    if _ok(g_r):
        return g_r
    if llm_r and _script_matches_lang(llm_r, to_lang) and not _translation_is_garbled(src, llm_r, to_lang):
        return llm_r
    if g_r and _script_matches_lang(g_r, to_lang):
        return g_r
    return llm_r or g_r


def _translate_georgian_native(src: str, from_lang: str) -> str | None:
    """TR/EN → KA: Google taslak + anlam + yerli yeniden yazım. EN çeviri yoluna dokunmaz."""
    g_ka: str | None = None
    meaning_en: str | None = src if from_lang == "en" else None

    def _gka() -> str | None:
        try:
            return google_translate_fast(src, from_lang, "ka")
        except Exception:
            return None

    def _en() -> str | None:
        if from_lang == "en":
            return src
        try:
            return google_translate_fast(src, from_lang, "en")
        except Exception:
            return None

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        f_ka = pool.submit(_gka)
        f_en = pool.submit(_en)
        try:
            g_ka = f_ka.result(timeout=2.5)
        except Exception:
            g_ka = None
        try:
            meaning_en = f_en.result(timeout=2.5)
        except Exception:
            if from_lang == "en":
                meaning_en = src
            else:
                meaning_en = None
    finally:
        pool.shutdown(wait=False, cancel_futures=False)

    if g_ka:
        g_ka = _polish_georgian(src, g_ka)

    rewritten: str | None = None
    if llm_available() and g_ka:
        try:
            rewritten = llm_rewrite_georgian(src, meaning_en or "", g_ka)
        except Exception:
            rewritten = None
        if rewritten:
            rewritten = _polish_georgian(src, rewritten)
            if not _georgian_rewrite_ok(src, g_ka, rewritten):
                rewritten = None

    if not g_ka and llm_available():
        try:
            rewritten = llm_translate(src, from_lang, "ka")
        except Exception:
            rewritten = None
        if rewritten:
            rewritten = _polish_georgian(src, rewritten)

    return _pick_translation(src, "ka", rewritten, g_ka)


def smart_translate_text(text: str, from_lang: str, to_lang: str) -> str:
    """Profesyonel çeviri: kısa sohbet = Google; uzun/anlatı = LLM+QC (tüm diller)."""
    if from_lang == to_lang:
        return text
    src = text.strip()
    if not src:
        return ""
    key = (from_lang, to_lang, src.lower())
    cached = _cache_get(_TRANSLATE_CACHE, key)
    if cached:
        return cached

    result: str | None = None
    quality = _needs_quality_translate(src, from_lang, to_lang) and llm_available()
    quality_wait = min(14.0, max(3.5, 2.5 + len(src) / 120.0))

    if quality:
        if to_lang == "ka":
            result = _translate_georgian_native(src, from_lang)
        else:
            llm_r: str | None = None
            g_r: str | None = None

            def _llm() -> str | None:
                try:
                    return llm_translate(src, from_lang, to_lang)
                except Exception:
                    return None

            def _google() -> str | None:
                try:
                    return google_translate_fast(src, from_lang, to_lang)
                except Exception:
                    return None

            pool = ThreadPoolExecutor(max_workers=2)
            try:
                f_llm = pool.submit(_llm)
                f_g = pool.submit(_google)
                llm_r = g_r = None
                try:
                    for fut in as_completed((f_llm, f_g), timeout=quality_wait):
                        try:
                            val = fut.result()
                        except Exception:
                            val = None
                        if fut is f_llm:
                            llm_r = val
                            picked = _pick_translation(src, to_lang, llm_r, None)
                            if picked:
                                result = picked
                                break
                        else:
                            g_r = val
                except Exception:
                    pass
                if result is None:
                    if llm_r is None:
                        try:
                            llm_r = f_llm.result(timeout=0.05)
                        except Exception:
                            llm_r = None
                    if g_r is None:
                        try:
                            g_r = f_g.result(timeout=0.05)
                        except Exception:
                            g_r = None
                    result = _pick_translation(src, to_lang, llm_r, g_r)
            finally:
                pool.shutdown(wait=False, cancel_futures=False)
    else:
        result = google_translate_fast(src, from_lang, to_lang)
        if result and (
            _translation_has_age_possession_bug(src, result)
            or not _script_matches_lang(result, to_lang)
            or _looks_like_literal_calque(src, result, to_lang)
        ) and llm_available():
            alt = llm_translate(src, from_lang, to_lang)
            if alt and _script_matches_lang(alt, to_lang):
                result = alt

    if result and not _script_matches_lang(result, to_lang):
        result = None

    if not result:
        try:
            result = mymemory_translate(src, from_lang, to_lang)
        except Exception:
            result = None

    if (not result or not _script_matches_lang(result, to_lang)) and llm_available():
        try:
            alt = llm_translate(src, from_lang, to_lang)
            if alt and _script_matches_lang(alt, to_lang):
                result = alt
        except Exception:
            pass

    if not result:
        raise ValueError("translation failed")

    if to_lang == "ka":
        result = _polish_georgian(src, result)

    # Çeviri sonrası kalite kontrolü (kullanıcıya göstermeden)
    result = _apply_translate_qc(src, result, from_lang, to_lang)
    if to_lang == "ka":
        result = _polish_georgian(src, result)

    _cache_set(_TRANSLATE_CACHE, key, result)
    return result


def translate_text(text: str, from_lang: str, to_lang: str) -> str:
    return smart_translate_text(text, from_lang, to_lang)


def translate_pair_safe(
    original: str,
    from_lang: str,
    to_lang: str,
    my: str = "tr",
    other: str = "en",
) -> tuple[str, str, str]:
    """Çeviri yönünü metne göre düzelt — yabancı kelime Türkçe tarafa sızmasın."""
    src = safe_str(original).strip()
    if not src:
        return "", from_lang, to_lang

    if {my, other} == {"tr", "en"} or {from_lang, to_lang} == {"tr", "en"}:
        if is_likely_english(src, "tr", "en") and not is_likely_turkish(src):
            from_lang, to_lang = "en", "tr"
        elif is_likely_turkish(src) and not is_likely_english(src, "tr", "en"):
            from_lang, to_lang = "tr", "en"
    else:
        my_like = looks_like_lang(src, my) or (my == "tr" and is_likely_turkish(src))
        other_like = looks_like_lang(src, other) or (
            other == "en" and is_likely_english(src, "tr", "en")
        )
        if my_like and not other_like:
            from_lang, to_lang = my, other
        elif other_like and not my_like:
            from_lang, to_lang = other, my
        elif "tr" in (my, other) and is_likely_turkish(src) and not other_like:
            from_lang = "tr"
            to_lang = other if my == "tr" else my

    first_from, first_to = from_lang, to_lang
    translated = translate_text(src, from_lang, to_lang)

    retry_from, retry_to = from_lang, to_lang
    if (
        to_lang == "tr"
        and is_likely_english(translated, "tr", "en")
        and not is_likely_turkish(translated)
        and from_lang == "tr"
        and is_likely_english(src, "tr", "en")
    ):
        retry_from, retry_to = "en", "tr"
    elif (
        to_lang == "en"
        and is_likely_turkish(translated)
        and not is_likely_english(translated, "tr", "en")
        and from_lang == "en"
        and is_likely_turkish(src)
    ):
        retry_from, retry_to = "tr", "en"

    if (retry_from, retry_to) != (first_from, first_to):
        translated = translate_text(src, retry_from, retry_to)
        from_lang, to_lang = retry_from, retry_to

    return translated, from_lang, to_lang


def translate_phonetic(text: str, lang: str) -> str:
    """Hedef dil metninin Türkçe okunuşu — çeviri metni değil, yalnızca hedef dil sesi."""
    if not text or lang == "tr":
        return ""
    # Telaffuz ASLA Türkçe anlam üzerinden üretilmez; verilen metin hedef dil olmalıdır.
    snippet = re.sub(r"\s+", " ", text.strip())
    try:
        from pronunciation_service import build_sentence_natural
        return safe_str(build_sentence_natural(snippet, lang)).strip()[:2500]
    except Exception:
        return ""


_whisper_model = None

WHISPER_PROMPTS: dict[str, str] = {
    "en": (
        "English lesson conversation. Student may say single words or short phrases. "
        "Common words: one two three four five head long short yes no go run eat, "
        "I run, I ran today, I read a book, I went to work, "
        "I am tired, what did you do today."
    ),
    "tr": (
        "Türkçe konuşma. Tek kelime de olabilir. Öğrenci Türkçe cevap veriyor: "
        "bugün koştum, kitap okudum, işe gittim, yorgunum, evde kaldım."
    ),
}

TRANSLATE_WHISPER_PROMPT_GENERIC = (
    "Multilingual spoken conversation. Even single words must be transcribed exactly."
)

TRANSLATE_WHISPER_PROMPTS: dict[str, str] = {
    "tr": "Doğal Türkçe konuşma. Tek kelime de olabilir. Tam olarak söyleneni yaz.",
    "en": (
        "Natural spoken English. Even single words must be transcribed. "
        "Common short words: one two three four five six seven eight nine ten, "
        "head bed red bad bet set met let get long short tall big small, "
        "yes no hi bye hello please thanks sorry okay stop go run eat drink, "
        "what where when why how who."
    ),
    "de": "Natürliches gesprochenes Deutsch. Wörtlich transkribieren.",
    "fr": "Conversation française naturelle. Transcrire exactement ce qui est dit.",
    "es": "Conversación en español natural. Transcribir exactamente lo dicho.",
    "ka": "ბუნებრივი ქართული საუბარი.",
    "ar": "محادثة عربية طبيعية.",
    "ru": "Естественная русская речь.",
    "it": "Conversazione italiana naturale.",
    "zh": "自然的中文对话。",
}


def decode_education_state(raw: str) -> dict:
    """JSON veya base64/base64url ile gelen eğitim oturum durumu."""
    if not raw or not raw.strip():
        return {}
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    import base64

    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            pad = "=" * (-len(raw) % 4)
            parsed = json.loads(decoder(raw + pad).decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            continue
    return {}


def get_whisper():
    if DISABLE_WHISPER:
        raise RuntimeError("whisper disabled")
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper_model


def prepare_wav(data: bytes, *, fast: bool = False) -> str:
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp.write(data)
        inp = tmp.name
    wav = inp + ".wav"
    if fast:
        filters = ("volume=2.2", None)
    else:
        filters = (
            "highpass=f=80,lowpass=f=7500,apad=pad_dur=1.2,dynaudnorm,volume=3.5",
            "highpass=f=80,lowpass=f=7500,apad=pad_dur=1.2,volume=3.0",
            "volume=2.5",
            None,
        )
    for af in filters:
        cmd = ["ffmpeg", "-y", "-i", inp, "-ar", "16000", "-ac", "1", wav]
        if af:
            cmd[4:4] = ["-af", af]
        timeout = 10 if fast else 20
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode == 0 and os.path.exists(wav) and os.path.getsize(wav) > 100:
            os.unlink(inp)
            return wav
    os.unlink(inp)
    if os.path.exists(wav):
        os.unlink(wav)
    raise ValueError("audio conversion failed")


def audio_has_speech(wav: str) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-i", wav, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = (result.stderr or "") + (result.stdout or "")
    mean = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", output)
    maxv = re.search(r"max_volume:\s*([-\d.]+)\s*dB", output)
    if mean and maxv:
        return float(maxv.group(1)) > -55 and float(mean.group(1)) > -60
    return True


HALLUCINATION_RE = re.compile(
    r"^(?:teşekkür(?:ler| ederim)?|thank(?:s| you)|subs by|subtitles|"
    r"izlediğiniz için teşekkür|abone ol(?:mayı)?(?: unutmayın)?)"
    r"(?:\s*(?:teşekkür(?:ler| ederim)?|thank(?:s| you)?|\.)?\s*)*$",
    re.I,
)


def is_hallucination(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if HALLUCINATION_RE.match(t):
        return True
    low = t.lower()
    if low in {"teşekkür", "teşekkürler", "teşekkür ederim", "thank you", "thanks"}:
        return True
    return False


_WHISPER_LANG_ALIASES = {
    "turkish": "tr", "tr": "tr",
    "english": "en", "en": "en",
    "german": "de", "de": "de",
    "french": "fr", "fr": "fr",
    "spanish": "es", "es": "es",
    "georgian": "ka", "ka": "ka",
    "arabic": "ar", "ar": "ar",
    "russian": "ru", "ru": "ru",
    "italian": "it", "it": "it",
    "chinese": "zh", "zh": "zh", "mandarin": "zh",
}


def normalize_whisper_lang(raw: str | None) -> str | None:
    if not raw:
        return None
    key = safe_str(raw).strip().lower()
    return _WHISPER_LANG_ALIASES.get(key)


def clean_stt_text(text: str) -> str:
    """Whisper tekrarlarını temizle: 'merhaba merhaba', çift cümle."""
    t = re.sub(r"\s+", " ", safe_str(text)).strip()
    if not t:
        return ""
    words = t.split()
    out: list[str] = []
    for w in words:
        if out and out[-1].casefold() == w.casefold():
            continue
        out.append(w)
    # 2'li tekrar: "çok iyi çok iyi"
    i = 0
    deduped: list[str] = []
    while i < len(out):
        if i + 3 < len(out) and out[i].casefold() == out[i + 2].casefold() and out[i + 1].casefold() == out[i + 3].casefold():
            deduped.extend(out[i:i + 2])
            i += 4
            continue
        deduped.append(out[i])
        i += 1
    out = deduped
    # Tüm metin iki kez: "A B C A B C"
    if len(out) >= 4 and len(out) % 2 == 0:
        half = len(out) // 2
        if [w.casefold() for w in out[:half]] == [w.casefold() for w in out[half:]]:
            out = out[:half]
    return " ".join(out).strip()


def google_stt(wav: str, lang_code: str) -> tuple[str, str, float] | None:
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 150
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.4

    with sr.AudioFile(wav) as src:
        audio = recognizer.record(src)

    if lang_code == "auto":
        tries = [("tr-TR", "tr"), ("en-US", "en")]
    elif lang_code in STT_LANG:
        tries = [(STT_LANG[lang_code], lang_code)]
    else:
        tries = [("tr-TR", "tr"), ("en-US", "en")]

    for code, short in tries:
        try:
            text = recognizer.recognize_google(audio, language=code)
            text = text.strip()
            if text:
                return text, short, 0.88
        except sr.UnknownValueError:
            continue
        except sr.RequestError:
            return None
    return None


def _groq_stt_request(
    wav: str,
    *,
    lang_code: str | None,
    prompt: str,
    timeout_sec: int = 18,
) -> tuple[str, str, float] | None:
    from education_engine import groq_api_key_valid

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key or not groq_api_key_valid():
        return None
    short = lang_code if lang_code in STT_LANG else None
    # json yeterli — dil metinden + (varsa) language alanından
    response_format = "json"
    try:
        import uuid

        with open(wav, "rb") as f:
            audio_data = f.read()
        if len(audio_data) < 800:
            return None

        boundary = f"----GroqStt{uuid.uuid4().hex}"
        parts: list[bytes] = []
        fields: list[tuple[str, str]] = [
            ("model", "whisper-large-v3-turbo"),
            ("response_format", response_format),
            ("temperature", "0"),
        ]
        if short:
            fields.insert(1, ("language", short))
        for name, value in fields:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        if prompt:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="prompt"\r\n\r\n{prompt[:220]}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n".encode()
        )
        parts.append(audio_data)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        req = Request(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = clean_stt_text(payload.get("text") or "")
        if len(text) < 2 or is_hallucination(text):
            return None
        detected = short or normalize_whisper_lang(payload.get("language"))
        if not detected:
            for candidate in STT_LANG:
                if looks_like_lang(text, candidate):
                    detected = candidate
                    break
            detected = detected or "en"
        return text, detected, score_text(text, detected) + 52
    except Exception:
        return None


def groq_stt(wav: str, lang_code: str, *, translate_mode: bool = False) -> tuple[str, str, float] | None:
    """Groq Whisper — eğitim veya çeviri modu."""
    short = lang_code if lang_code in STT_LANG else "en"
    if translate_mode:
        prompt = TRANSLATE_WHISPER_PROMPTS.get(short, TRANSLATE_WHISPER_PROMPT_GENERIC)
    else:
        prompt = WHISPER_PROMPTS.get(short, "")
    return _groq_stt_request(wav, lang_code=short, prompt=prompt)


def groq_stt_auto(wav: str) -> tuple[str, str, float] | None:
    """Groq Whisper — otomatik dil algılama (çeviri modu)."""
    return _groq_stt_request(wav, lang_code=None, prompt=TRANSLATE_WHISPER_PROMPT_GENERIC)


def whisper_stt(wav: str, lang_code: str) -> tuple[str, str, float] | None:
    wlang = None if lang_code == "auto" else (
        lang_code if lang_code in ("tr", "en", "de", "fr", "es", "ka", "ar", "ru", "it", "zh") else None
    )
    prompt = WHISPER_PROMPTS.get(lang_code, "") if lang_code != "auto" else ""
    try:
        model = get_whisper()
        segments, info = model.transcribe(
            wav,
            language=wlang,
            beam_size=1 if WHISPER_MODEL == "tiny" else 3,
            best_of=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=prompt or None,
        )
        text = "".join(s.text for s in segments).strip()
        if text:
            prob = getattr(info, "language_probability", 0.0) or 0.0
            detected = getattr(info, "language", None) or wlang or "tr"
            return text, detected, prob
    except Exception:
        pass
    return None


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
            r"run|ran|running|very|so|just|only|also|then|well|now|"
            r"two|to|too|one|three|four|five|bad|bed|bet|red|head|bread|hello|hi|bye|"
            r"sorry|please|thanks|okay|ok|great|nice|love|help|stop|wait|come|go)\b",
            t,
            re.I,
        )) or (len(t.split()) <= 3 and is_ascii_latin(t) and not _stt_has_turkish_markers(t))
    if lang == "ka":
        return bool(re.search(r"[\u10A0-\u10FF]", t))
    if lang == "ru":
        return bool(re.search(r"[\u0400-\u04FF]", t))
    if lang == "de":
        if re.search(r"[äöüÄÖÜß]", t):
            return True
        return bool(re.search(
            r"\b(hallo|guten|danke|bitte|ja|nein|wie|geht|ich|sie|und|nicht|heute|morgen|schön|bitte)\b",
            t,
            re.I,
        ))
    if lang == "fr":
        if re.search(r"[àâçéèêëîïôùûüœæÀÂÇÉÈÊËÎÏÔÙÛÜŒÆ]", t):
            return True
        return bool(re.search(r"\b(bonjour|merci|oui|non|comment|je|vous|avec|pour|aujourd)\b", t, re.I))
    if lang == "es":
        if re.search(r"[áéíóúñ¿¡ÁÉÍÓÚÑ]", t):
            return True
        return bool(re.search(r"\b(hola|gracias|buenos|sí|si|no|cómo|como|usted|por|favor)\b", t, re.I))
    if lang == "ar":
        return bool(re.search(r"[\u0600-\u06FF]", t))
    if lang == "it":
        if re.search(r"[àèéìòùÀÈÉÌÒÙ]", t):
            return True
        return bool(re.search(r"\b(ciao|grazie|buongiorno|si|no|come|per|favore|oggi)\b", t, re.I))
    if lang == "zh":
        return bool(re.search(r"[\u4e00-\u9fff]", t))
    return False


def score_text(text: str, lang: str) -> float:
    t = text.strip()
    if len(t) < 1:
        return -100.0
    score = 5.0
    if lang == "tr":
        if re.search(r"[ğüşıöçĞÜŞİÖÇ]", t):
            score += 45
        if re.search(
            r"merhaba|nasılsın|nasilsin|neler|yapıyor|teşekkür|teşekkürler|evet|hayır|tamam|"
            r"günaydın|iyiyim|naber|lütfen|güzel|neden|nasıl|sen nasılsın|tatil|muğla|mugla|geçti",
            t,
            re.I,
        ):
            score += 35
        if re.search(r"\b(the|what|hello|how are|thanks you)\b", t, re.I) and not re.search(
            r"[ğüşıöç]|merhaba|nasıl", t, re.I
        ):
            score -= 40
    elif lang == "en":
        if re.search(
            r"\b(hello|how|what|thanks|you|doing|good|morning|please|yes|no|fine|are)\b",
            t,
            re.I,
        ):
            score += 35
        if re.search(r"[ğüşıöç]|merhaba|nasılsın", t, re.I) and not re.search(
            r"\b(hello|how|what|thanks)\b", t, re.I
        ):
            score -= 40
    score += min(len(t.split()), 12) * 2.0
    return score


def stt_for_lang(
    wav: str,
    lang: str,
    allow_whisper: bool = True,
    allow_groq: bool = True,
) -> tuple[str, str, float] | None:
    """Eğitim modu — Google önce (hızlı), Groq yedek."""
    google = google_stt(wav, lang)
    if google and google[0].strip():
        text = google[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 40

    if allow_groq:
        groq = groq_stt(wav, lang, translate_mode=False)
        if groq and groq[0].strip():
            text = groq[0].strip()
            if is_hallucination(text):
                return None
            return text, groq[1], groq[2]

    if not allow_whisper or DISABLE_WHISPER:
        return None

    whisper = whisper_stt(wav, lang)
    if whisper and whisper[0].strip():
        text = whisper[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 5
    return None


def stt_for_translate(wav: str, lang: str) -> tuple[str, str, float] | None:
    """Çeviri modu — Groq Whisper önce, Google yedek. Hızlı: local whisper yok."""
    groq = groq_stt(wav, lang, translate_mode=True)
    if groq and groq[0].strip() and not is_hallucination(groq[0]):
        return groq

    google = google_stt(wav, lang)
    if google and google[0].strip():
        text = google[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 28
    return None


def is_ascii_latin(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return bool(re.match(r"^[a-zA-Z0-9',.\-!?]+(?:\s+[a-zA-Z0-9',.\-!?]+)*$", t))


def is_likely_english(text: str, my: str = "tr", other: str = "en") -> bool:
    """Tek/ kısa İngilizce sözcükler — looks_like_lang kaçırmasın."""
    t = text.strip()
    if not t:
        return False
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", t):
        return False
    if _stt_has_turkish_markers(t):
        return False
    # Bilinen Türkçe (ben/evet/kitap…) ASCII olsa da İngilizce sayma
    if looks_like_lang(t, "tr"):
        return False
    if looks_like_lang(t, "en"):
        return True
    if other != "en" and my != "en":
        return False
    if is_ascii_latin(t):
        return True
    return False


def is_likely_turkish(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", t):
        return True
    return looks_like_lang(t, "tr") or _stt_has_turkish_markers(t)


def detect_speech_lang(
    text: str,
    my: str,
    other: str,
    stt_lang: str,
    last_from: str | None = None,
) -> str:
    """Konuşulan metinden kaynak dili belirle — tek kelimeler dahil."""
    t = text.strip()
    if not t:
        return stt_lang if stt_lang in (my, other) else my

    my_like = is_likely_turkish(t) if my == "tr" else looks_like_lang(t, my)
    other_like = is_likely_english(t, my, other) if other == "en" else looks_like_lang(t, other)

    if other_like and not my_like:
        return other
    if my_like and not other_like:
        return my

    if {my, other} == {"tr", "en"}:
        if is_likely_english(t, my, other) and not is_likely_turkish(t):
            return "en"
        if is_likely_turkish(t) and not is_likely_english(t, my, other):
            return "tr"
        if is_ascii_latin(t) and not is_likely_turkish(t):
            return "en"

    if last_from in (my, other):
        alt = other if last_from == my else my
        if last_from == my and is_likely_english(t, my, other):
            return other
        if last_from == other and is_likely_turkish(t):
            return my
        if is_ascii_latin(t) and not is_likely_turkish(t) and other == "en":
            return other

    return resolve_lang_from_text(t, my, other, stt_lang)


def resolve_lang_from_text(text: str, my: str, other: str, stt_lang: str) -> str:
    t = text.strip()
    my_like = looks_like_lang(t, my) or (my == "tr" and is_likely_turkish(t))
    other_like = looks_like_lang(t, other) or (other == "en" and is_likely_english(t, my, other))

    if other_like and not my_like:
        return other
    if my_like and not other_like:
        return my

    if other == "en" and my == "tr":
        if is_likely_english(t, my, other) and not is_likely_turkish(t):
            return "en"
        en_hits = len(re.findall(
            r"\b(how|was|your|holiday|fine|thank|thanks|you|are|hello|what|where|when|"
            r"who|why|good|morning|please|yes|no|i'm|im|two|bad|bed|red|one|three)\b",
            t,
            re.I,
        ))
        tr_hits = len(re.findall(
            r"\b(merhaba|nasılsın|nasilsin|teşekkür|iyiyim|naber|evet|hayır|günaydın)\b",
            t,
            re.I,
        ))
        if en_hits >= 1 and tr_hits == 0 and re.search(r"\b[a-zA-Z]{2,}\b", t):
            return "en"
        if en_hits >= 2 and en_hits > tr_hits:
            return "en"
        if tr_hits >= 1 and en_hits == 0:
            return "tr"
        if is_ascii_latin(t) and not is_likely_turkish(t):
            return "en"

    if other == "ka" and re.search(r"[\u10A0-\u10FF]", t):
        return "ka"
    if my == "ka" and re.search(r"[\u10A0-\u10FF]", t):
        return "ka"
    if other == "ru" and re.search(r"[\u0400-\u04FF]", t):
        return "ru"
    if my == "ru" and re.search(r"[\u0400-\u04FF]", t):
        return "ru"

    return stt_lang if stt_lang in (my, other) else my


def _stt_has_turkish_markers(text: str) -> bool:
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", text):
        return True
    return bool(re.search(
        r"\b(merhaba|nasılsın|nasilsin|teşekkür|tesekkur|evet|hayır|hayir|tamam|iyiyim|günaydın|gunaydin|"
        r"neler|yapıyorum|yapiyorum|yaptım|yaptim|gittim|yorgunum|kitap|okudum|bugün|bugun|yarın|yarin|"
        r"koştum|kosdum|koşuyorum|yürüdüm|izledim|çalıştım|calistim|evde|parka|işe|ise|"
        r"ben|sen|biz|siz|bunu|şunu|sunu|neden|niye|lütfen|lutfen|güzel|guzel|çok|cok|"
        r"değil|degil|vardır|var|yok|için|icin|gibi|şimdi|simdi|sonra|önce|once)\b",
        text,
        re.I,
    ))


def _education_context(history: list[dict] | None) -> str:
    if not history:
        return ""
    parts: list[str] = []
    for h in history[:6]:
        if isinstance(h, dict) and h.get("text"):
            parts.append(str(h["text"]))
    return " ".join(parts).lower()


def fix_education_stt(text: str, history: list[dict] | None = None) -> str:
    """Eğitim modunda sık STT hatalarını düzelt (I will→I run, ayran vb.)."""
    t = text.strip()
    if not t:
        return t
    tl = t.lower()
    ctx = _education_context(history)
    daily = bool(re.search(
        r"what did you do|what do you do|tell me about your day|what happened|"
        r"how was your day|bugün ne|neler yapt",
        ctx,
    ))

    exact_fixes = {
        "ayran": "I run",
        "i will": "I run",
        "i'll": "I run",
        "iron": "I run",
        "i iron": "I run",
        "i wool": "I run",
        "i wall": "I run",
        "i well": "I run",
        "i wheal": "I run",
        "ay run": "I run",
        "hey run": "I run",
        "i ren": "I run",
        "airen": "I run",
        "ay book": "a book",
        "i book": "I read a book",
        "read book": "I read a book",
        "eye run": "I run",
        "i ran": "I ran",
        "arm run": "I am run",
        "im run": "I am run",
        "am run": "I am run",
        "slipping": "sleeping",
        "slip": "sleeping",
        "slipin": "sleeping",
        "sleepin": "sleeping",
        "will": "I run",
        "run": "I run",
    }
    if tl in exact_fixes:
        fixed = exact_fixes[tl]
        if tl == "will" and not daily:
            return t
        if tl == "run" and not daily and ctx:
            return t
        return fixed

    if daily or not ctx:
        if re.fullmatch(r"i will", tl):
            return "I run"
        if re.fullmatch(r"(ayran|iron|run|will)", tl):
            return "I run"
        if re.fullmatch(r"i run", tl):
            return "I run"
        if re.fullmatch(r"book|a book", tl):
            return "I read a book"

    t = re.sub(r"\bay book\b", "a book", t, flags=re.I)
    t = re.sub(r"\bi book\b", "I read a book", t, flags=re.I)
    if daily or re.search(r"\b(run|ran|jog|exercise)\b", ctx):
        t = re.sub(r"\bi will\b", "I run", t, flags=re.I)
        t = re.sub(r"\beye run\b", "I run", t, flags=re.I)
        t = re.sub(r"\b(i wool|i wall|i well|ay run|hey run)\b", "I run", t, flags=re.I)
        t = re.sub(r"\b(ayran|iron|airen)\b", "I run", t, flags=re.I)
    return t.strip()


def _rank_education_stt(
    text: str,
    raw: str,
    stt_lang: str,
    base_score: float,
    history: list[dict] | None,
) -> tuple[str, str, float]:
    """EN/TR adaylarını eğitim bağlamında puanla."""
    fixed = fix_education_stt(text, history)
    score = base_score
    raw_l = raw.lower().strip()
    ctx = _education_context(history)
    daily = bool(re.search(
        r"what did you do|what do you do|tell me about your day|what happened|"
        r"how was your day|bugün ne|neler yapt",
        ctx,
    ))

    if stt_lang == "tr" and _stt_has_turkish_markers(raw):
        return raw.strip(), "tr", score + 45

    if looks_like_lang(fixed, "en"):
        score += 32
        if stt_lang == "en":
            score += 8
        if daily and raw_l in ("i will", "i'll", "ayran", "iron", "will", "run"):
            score += 28
        return fixed, "en", score

    if stt_lang == "tr" and raw_l in ("ayran", "iron", "i will", "will", "run"):
        return fix_education_stt(raw, history), "en", score + 35

    if looks_like_lang(raw, "tr"):
        return raw.strip(), "tr", score + 20

    return fixed or raw.strip(), stt_lang if stt_lang in ("en", "tr") else "en", score


def transcribe_education(
    data: bytes,
    target_lang: str = "en",
    last_from: str | None = None,
    history: list[dict] | None = None,
) -> tuple[str, str]:
    """Eğitim modu — EN ve TR STT adaylarını bağlamla birleştir."""
    if len(data) < 50:
        raise ValueError("audio too short")
    wav = prepare_wav(data)
    try:
        # Kısa kelimeler (head, one, two) sessiz sanılmasın — VAD atla

        primary = target_lang if target_lang in STT_LANG else "en"
        langs: list[str] = [primary]
        if "tr" not in langs:
            langs.append("tr")

        candidates: list[tuple[str, str, float]] = []
        for lang in langs[:1]:
            result = stt_for_lang(wav, lang, allow_whisper=False)
            if not result or not result[0].strip():
                continue
            raw = result[0].strip()
            text, detected, score = _rank_education_stt(
                raw, raw, lang, result[2], history,
            )
            if text:
                candidates.append((text, detected, score))
                break

        if not candidates:
            for lang in langs:
                result = stt_for_lang(wav, lang, allow_whisper=False)
                if not result or not result[0].strip():
                    continue
                raw = result[0].strip()
                text, detected, score = _rank_education_stt(
                    raw, raw, lang, result[2], history,
                )
                if text:
                    candidates.append((text, detected, score))

        if not candidates:
            result = stt_for_lang(wav, primary, allow_whisper=True)
            if result and result[0].strip():
                raw = result[0].strip()
                text, detected, score = _rank_education_stt(
                    raw, raw, primary, result[2], history,
                )
                if text:
                    candidates.append((text, detected, score))

        if not candidates:
            raise ValueError("speech not recognized")

        candidates.sort(key=lambda x: x[2], reverse=True)
        text, detected, _ = candidates[0]

        if detected == "en" and text:
            text = fix_education_stt(text, history)

        if last_from == "tr" and detected == "en" and not looks_like_lang(text, "en"):
            for alt_text, alt_lang, alt_score in candidates[1:]:
                if alt_lang == "tr" and alt_score >= candidates[0][2] - 12:
                    return alt_text, "tr"

        return text, detected
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


def _stt_early_lang(text: str, my: str, other: str) -> str | None:
    """İlk Whisper sonucu yeterince net mi? Şüphede None → diğer çağrıları bekle."""
    t = clean_stt_text(text)
    if not t or is_hallucination(t):
        return None
    words = t.split()
    tr_clear = is_likely_turkish(t) and not is_likely_english(t, my, other)
    en_clear = is_likely_english(t, my, other) and not is_likely_turkish(t)
    if tr_clear and en_clear:
        return None
    if len(words) <= 1:
        if re.search(r"[ğüşıöçĞÜŞİÖÇ]", t) and "tr" in (my, other):
            return "tr"
        if looks_like_lang(t, "tr") and "tr" in (my, other) and not en_clear:
            return "tr"
        for lang in (my, other):
            if lang in ("ka", "ru", "ar", "zh") and looks_like_lang(t, lang):
                return lang
        return None
    if tr_clear and "tr" in (my, other):
        return "tr"
    if en_clear and "en" in (my, other):
        return "en"
    for lang in (my, other):
        if lang not in ("tr", "en") and looks_like_lang(t, lang):
            other_lang = other if lang == my else my
            if not looks_like_lang(t, other_lang):
                return lang
    if looks_like_lang(t, my) and not looks_like_lang(t, other):
        return my
    if looks_like_lang(t, other) and not looks_like_lang(t, my):
        return other
    return None


def transcribe_dual(
    data: bytes,
    my: str,
    other: str,
    last_from: str | None = None,
    timings: dict | None = None,
) -> tuple[str, str]:
    """Çeviri STT — paralel auto+my+other; net sonuçta erken çıkış."""
    t_ffmpeg = time.perf_counter()
    wav = prepare_wav(data, fast=True)
    if timings is not None:
        timings["ffmpeg_ms"] = int((time.perf_counter() - t_ffmpeg) * 1000)
    t_stt = time.perf_counter()
    try:
        candidates: list[tuple[str, str, float, str]] = []
        long_audio = os.path.getsize(wav) >= 96_000

        def add(r: tuple[str, str, float] | None, source: str) -> None:
            if not r or not r[0].strip():
                return
            text = clean_stt_text(r[0])
            if text and not is_hallucination(text):
                candidates.append((text, r[1], r[2], source))

        if long_audio:
            # Uzun konuşma: tek hızlı auto STT — yazı hızına yaklaş
            tasks = {
                "auto": lambda: groq_stt_auto(wav),
            }
        else:
            tasks = {
                "auto": lambda: groq_stt_auto(wav),
                f"lang_{my}": lambda: stt_for_translate(wav, my),
                f"lang_{other}": lambda: stt_for_translate(wav, other),
            }

        early: tuple[str, str] | None = None
        pool = ThreadPoolExecutor(max_workers=min(3, len(tasks)))
        try:
            futures = {pool.submit(fn): key for key, fn in tasks.items()}
            try:
                for fut in as_completed(futures, timeout=2.8 if long_audio else 2.8):
                    try:
                        add(fut.result(), futures[fut])
                    except Exception:
                        continue
                    if not candidates:
                        continue
                    last = candidates[-1]
                    lang = _stt_early_lang(last[0], my, other)
                    if lang:
                        early = (last[0], lang)
                        break
            except Exception:
                pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if early:
            if timings is not None:
                timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                timings["stt_early"] = True
            return early

        if not candidates:
            for lang in (my, other):
                add(stt_for_lang(wav, lang, allow_whisper=not DISABLE_WHISPER), f"fallback_{lang}")

        if not candidates:
            raise ValueError("speech not recognized")

        def rank(item: tuple[str, str, float, str]) -> float:
            text, stt_lang, score, source = item
            from_lang = detect_speech_lang(text, my, other, stt_lang, last_from)
            s = float(score)
            if from_lang == stt_lang:
                s += 18
            if is_likely_turkish(text) and not is_likely_english(text, my, other):
                s += 45
                if stt_lang == "tr" or source == "auto":
                    s += 30
            if is_likely_english(text, my, other) and not is_likely_turkish(text):
                s += 45
                if stt_lang == "en" or source == "auto":
                    s += 30
            if re.search(r"[ğüşıöçĞÜŞİÖÇ]", text):
                s += 70
            if _stt_has_turkish_markers(text):
                s += 25
            if source == "auto":
                s += 20
            if looks_like_lang(text, from_lang):
                s += 15
            if last_from and from_lang == last_from:
                s += 2
            return s

        if {my, other} == {"tr", "en"}:
            strong_tr = [
                c for c in candidates
                if is_likely_turkish(c[0]) and not is_likely_english(c[0], my, other)
            ]
            strong_en = [
                c for c in candidates
                if is_likely_english(c[0], my, other) and not is_likely_turkish(c[0])
            ]
            auto = [c for c in candidates if c[3] == "auto"]

            if auto:
                at = max(auto, key=rank)[0]
                if is_likely_english(at, my, other) and not is_likely_turkish(at):
                    if timings is not None:
                        timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                    return at, "en"
                if is_likely_turkish(at) and not is_likely_english(at, my, other):
                    if strong_tr:
                        if timings is not None:
                            timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                        return max(strong_tr, key=rank)[0], "tr"
                    if timings is not None:
                        timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                    return at, "tr"

            if strong_tr and not strong_en:
                if timings is not None:
                    timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                return max(strong_tr, key=rank)[0], "tr"
            if strong_en and not strong_tr:
                if timings is not None:
                    timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                return max(strong_en, key=rank)[0], "en"

            if strong_tr and strong_en:
                ortho = [c for c in strong_tr if re.search(r"[ğüşıöçĞÜŞİÖÇ]", c[0])]
                auto_clear_en = bool(
                    auto and is_likely_english(auto[0][0], my, other) and not is_likely_turkish(auto[0][0])
                )
                if ortho and not auto_clear_en:
                    if timings is not None:
                        timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                    return max(ortho, key=rank)[0], "tr"
                pick = max(strong_tr + strong_en, key=rank)
                if timings is not None:
                    timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
                return pick[0], ("tr" if pick in strong_tr else "en")

        best = max(candidates, key=rank)
        text = best[0]
        from_lang = detect_speech_lang(text, my, other, best[1], last_from)
        if {my, other} == {"tr", "en"}:
            if is_likely_turkish(text) and not is_likely_english(text, my, other):
                from_lang = "tr"
            elif is_likely_english(text, my, other) and not is_likely_turkish(text):
                from_lang = "en"
        if from_lang not in (my, other):
            from_lang = my
        if timings is not None:
            timings["stt_ms"] = int((time.perf_counter() - t_stt) * 1000)
        return text, from_lang
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


def transcribe_audio(data: bytes, lang_code: str) -> tuple[str, str, float]:
    if len(data) < 50:
        raise ValueError("audio too short")
    wav = prepare_wav(data)
    try:
        result = google_stt(wav, lang_code)
        if result:
            return result
        result = whisper_stt(wav, lang_code)
        if result:
            return result
        raise ValueError("speech not recognized")
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def send_json_error(self, code: int, message: str):
        body = json.dumps({"error": message}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_error_message(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "speech not recognized" in msg or "not recognized" in msg:
            return "Konuşma anlaşılamadı — tekrar deneyin"
        if "no speech" in msg:
            return "Konuşma algılanmadı — basılı tutup konuşun"
        if "audio conversion" in msg or "ffmpeg" in msg:
            return "Ses dosyası işlenemedi — tekrar deneyin"
        if "too short" in msg:
            return "Kayıt çok kısa — basılı tutup konuşun"
        return "Bir hata oluştu — tekrar deneyin"

    def end_headers(self):
        path = urlparse(self.path).path
        if path.endswith((".js", ".html", ".css")):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/stt":
            return self.handle_stt(parse_qs(parsed.query))
        if parsed.path == "/api/process":
            return self.handle_process(parse_qs(parsed.query))
        if parsed.path == "/api/listen":
            return self.handle_listen(parse_qs(parsed.query))
        if parsed.path == "/api/tutor":
            return self.handle_tutor(parse_qs(parsed.query))
        if parsed.path == "/api/education/voice":
            return self.handle_education_voice(parse_qs(parsed.query))
        if parsed.path == "/api/education/chat":
            return self.handle_education_chat(parse_qs(parsed.query))
        if parsed.path == "/api/education/session-end":
            return self.handle_education_session_end(parse_qs(parsed.query))
        if parsed.path == "/api/builder/word":
            return self.handle_builder_word()
        if parsed.path == "/api/builder/sentence":
            return self.handle_builder_sentence()
        if parsed.path == "/api/builder/grade-word":
            return self.handle_builder_grade_word()
        if parsed.path == "/api/builder/grade-sentence":
            return self.handle_builder_grade_sentence()
        if parsed.path == "/api/pronounce/batch":
            return self.handle_pronounce_batch()
        if parsed.path == "/api/deploy-update":
            return self.handle_deploy_update()
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/converse":
            return self.handle_converse(parse_qs(parsed.query))
        if parsed.path == "/api/tts":
            return self.handle_tts(parse_qs(parsed.query))
        if parsed.path == "/api/translate":
            return self.handle_translate(parse_qs(parsed.query))
        if parsed.path == "/api/pronounce":
            return self.handle_pronounce(parse_qs(parsed.query))
        if parsed.path == "/api/tutor/lesson":
            return self.handle_tutor_lesson(parse_qs(parsed.query))
        if parsed.path == "/api/education/greeting":
            return self.handle_education_greeting(parse_qs(parsed.query))
        if parsed.path == "/api/education/lesson-plan":
            return self.handle_education_lesson_plan(parse_qs(parsed.query))
        if parsed.path == "/api/education/progress":
            return self.handle_education_progress(parse_qs(parsed.query))
        if parsed.path == "/api/status":
            return self.handle_status()
        if parsed.path == "/api/ping":
            return self.handle_ping()
        if parsed.path == "/api/deploy-update":
            return self.handle_deploy_update_info()
        return super().do_GET()

    def handle_ping(self):
        """Hafif canlılık — keepalive/cron; AI isteği sırasında da yanıt verir."""
        body = b'{"ok":true,"pong":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_status(self):
        host = self.headers.get("Host", "")
        forwarded = self.headers.get("X-Forwarded-Proto", "")
        if forwarded:
            proto = forwarded.split(",")[0].strip()
        elif host.endswith(".trycloudflare.com"):
            proto = "https"
        else:
            proto = "http"
        origin = f"{proto}://{host}" if host else ""
        info = ai_provider_info()
        groq_status = groq_api_key_status()
        body = json.dumps(
            {
                "ok": True,
                "origin": origin,
                "port": PORT,
                "app_version": APP_VERSION,
                "target_app_version": TARGET_APP_VERSION,
                "version_number": _version_number(APP_VERSION),
                "target_version_number": _version_number(TARGET_APP_VERSION),
                "update_available": _version_number(APP_VERSION) < _version_number(TARGET_APP_VERSION),
                "deploy_hook_configured": bool(_deploy_hook_url()),
                "git_commit": (os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or "")[:12],
                "ai_enabled": llm_available(),
                "ai_provider": info.get("provider"),
                "ai_provider_label": info.get("label"),
                "ai_model": info.get("model"),
                "ai_providers": info.get("providers") or [],
                "ai_fallback_enabled": bool(info.get("fallback_enabled")),
                "groq_key_configured": groq_status.get("configured"),
                "groq_key_valid": groq_status.get("valid_format"),
                "groq_key_hint_tr": groq_status.get("hint_tr"),
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_deploy_update_info(self):
        body = json.dumps(
            {
                "ok": True,
                "app_version": APP_VERSION,
                "target_app_version": TARGET_APP_VERSION,
                "update_available": _version_number(APP_VERSION) < _version_number(TARGET_APP_VERSION),
                "deploy_hook_configured": bool(_deploy_hook_url()),
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_deploy_update(self):
        started, message = _trigger_render_deploy()
        body = json.dumps(
            {
                "ok": started,
                "message_tr": message if started else (
                    message + " GitHub main dalına push sonrası Render otomatik günceller."
                ),
                "app_version": APP_VERSION,
                "target_app_version": TARGET_APP_VERSION,
                "deploy_hook_configured": bool(_deploy_hook_url()),
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200 if started or not _deploy_hook_url() else 502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_stt(self, params):
        lang = (params.get("lang") or ["tr"])[0]
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self.send_error(400, "empty body")
            return
        data = self.rfile.read(length)
        try:
            text, _, _ = transcribe_audio(data, lang)
            body = json.dumps({"text": text}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_listen(self, params):
        """STT only — çeviri modunda metni hemen göstermek için (çeviri ayrı istek)."""
        my = (params.get("my") or ["tr"])[0]
        other = (params.get("other") or ["en"])[0]
        last_from = (params.get("last") or [""])[0].strip() or None
        if last_from not in (my, other):
            last_from = None
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self.send_error(400, "empty body")
            return
        data = self.rfile.read(length)
        try:
            original, from_lang = transcribe_dual(data, my, other, last_from)
            to_lang = other if from_lang == my else my
            body = json.dumps({
                "original": original,
                "from": from_lang,
                "to": to_lang,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_process(self, params):
        my = (params.get("my") or ["tr"])[0]
        other = (params.get("other") or ["en"])[0]
        last_from = (params.get("last") or [""])[0].strip() or None
        if last_from not in (my, other):
            last_from = None
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self.send_error(400, "empty body")
            return
        data = self.rfile.read(length)
        t0 = time.perf_counter()
        timings: dict = {}
        pid = f"p{int(t0 * 1000) % 100000000}"
        try:
            original, from_lang = transcribe_dual(data, my, other, last_from, timings)
            to_lang = other if from_lang == my else my
            t_tr = time.perf_counter()
            translated, from_lang, to_lang = translate_pair_safe(
                original, from_lang, to_lang, my, other,
            )
            timings["translation_ms"] = int((time.perf_counter() - t_tr) * 1000)
            timings["process_total_ms"] = int((time.perf_counter() - t0) * 1000)
            print(
                f"process {pid} ffmpeg_ms={timings.get('ffmpeg_ms', '-')} "
                f"stt_ms={timings.get('stt_ms', '-')} "
                f"stt_early={timings.get('stt_early', False)} "
                f"translation_ms={timings.get('translation_ms', '-')} "
                f"process_total_ms={timings['process_total_ms']}",
                flush=True,
            )
            # Fonetik istemci /api/pronounce — çeviri JSON'unu bekletme
            body = json.dumps({
                "original": original,
                "translated": translated,
                "from": from_lang,
                "to": to_lang,
                "phonetic": "",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            timings["process_total_ms"] = int((time.perf_counter() - t0) * 1000)
            print(
                f"process {pid} FAIL total_ms={timings.get('process_total_ms')} err={e}",
                flush=True,
            )
            self.send_json_error(422, self.api_error_message(e))

    def handle_tutor(self, params):
        import base64

        target = (params.get("lang") or ["en"])[0]
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self.send_error(400, "empty body")
            return
        data = self.rfile.read(length)
        try:
            original, detected = transcribe_dual(data, "tr", target, None)
            result = tutor_reply(
                original, detected, target, translate_text, looks_like_lang
            )
            phrase = result.get("correct_phrase") or result.get("robot_target") or ""
            if phrase:
                audio = synthesize(phrase[:500], target)
                result["audio"] = base64.b64encode(audio).decode("ascii")
            else:
                result["audio"] = ""
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def _education_tts(self, result: dict, lang: str) -> dict:
        """Metin hemen döner; ses istemci /api/tts ile arka planda alır (daha hızlı)."""
        result["audio"] = ""
        return result

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_builder_word(self):
        payload = self._read_json_body()
        word_tr = (payload.get("word") or "").strip()
        lang = (payload.get("lang") or "en").strip()
        cache_key = (word_tr.lower(), lang)
        cached = _cache_get(_WORD_LESSON_CACHE, cache_key)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            self._send_json(cached)
            return
        t0 = time.monotonic()
        try:
            result = generate_word_lesson(word_tr, lang, translate_fn=translate_text)
            elapsed = round(time.monotonic() - t0, 2)
            if isinstance(result, dict):
                result["generation_sec"] = elapsed
                if result.get("ok"):
                    _cache_set(_WORD_LESSON_CACHE, cache_key, dict(result))
            print(f"[word-lesson] {word_tr!r} → {elapsed}s ok={result.get('ok') if isinstance(result, dict) else '?'}")
            self._send_json(result)
        except Exception as e:
            elapsed = round(time.monotonic() - t0, 2)
            print(f"[word-lesson] {word_tr!r} → {elapsed}s ERROR: {e}")
            self.send_json_error(422, self.api_error_message(e))

    def handle_builder_sentence(self):
        payload = self._read_json_body()
        tr_sentence = (payload.get("sentence") or "").strip()
        lang = (payload.get("lang") or "en").strip()
        try:
            result = analyze_sentence_for_builder(tr_sentence, lang, translate_fn=translate_text)
            self._send_json(result)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_builder_grade_word(self):
        payload = self._read_json_body()
        try:
            result = grade_word_answer(
                (payload.get("word_tr") or "").strip(),
                (payload.get("target_word") or "").strip(),
                (payload.get("user_answer") or "").strip(),
                (payload.get("lang") or "en").strip(),
                translate_fn=translate_text,
            )
            self._send_json(result)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_builder_grade_sentence(self):
        payload = self._read_json_body()
        try:
            result = grade_sentence_answer(
                (payload.get("tr_sentence") or "").strip(),
                (payload.get("expected_target") or "").strip(),
                (payload.get("user_answer") or "").strip(),
                (payload.get("lang") or "en").strip(),
                alternatives=payload.get("alternatives") or [],
            )
            self._send_json(result)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_progress(self, params):
        profile_raw = (params.get("profile") or ["{}"])[0]
        try:
            profile = json.loads(profile_raw) if profile_raw else default_profile()
        except Exception:
            profile = default_profile()
        try:
            body = json.dumps({
                "weeklyProgress": weekly_progress(profile),
                "sessionLog": profile.get("sessionLog", [])[:10],
                "dailyLesson": daily_lesson(profile),
            }, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_session_end(self, params):
        payload = self._read_json_body()
        profile = payload.get("profile") or default_profile()
        minutes = float(payload.get("minutes") or 0)
        topic = (payload.get("topic") or "Daily conversation").strip()
        try:
            patch = finalize_session(profile, minutes, topic)
            merged = {**profile, **patch}
            report = session_report(merged, minutes)
            report["profile"] = merged
            body = json.dumps(report, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_greeting(self, params):
        lang = (params.get("lang") or ["en"])[0]
        profile_raw = (params.get("profile") or ["{}"])[0]
        try:
            profile = json.loads(profile_raw) if profile_raw else {}
        except Exception:
            profile = {}
        try:
            result = greeting(lang, profile, translate_fn=translate_text)
            result = self._education_tts(result, lang)
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_lesson_plan(self, params):
        profile_raw = (params.get("profile") or ["{}"])[0]
        try:
            profile = json.loads(profile_raw) if profile_raw else default_profile()
        except Exception:
            profile = default_profile()
        try:
            plan = daily_lesson(profile)
            body = json.dumps(plan, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_chat(self, params):
        lang = (params.get("lang") or ["en"])[0]
        payload = self._read_json_body()
        user_text = (payload.get("text") or "").strip()
        profile = payload.get("profile") or default_profile(lang)
        history = payload.get("history") or []
        roleplay = payload.get("roleplay")
        speak_slow = bool(payload.get("speak_slow"))
        user_lang = payload.get("user_lang") or lang
        try:
            result = process_turn(
                user_text, user_lang, lang, history, profile,
                roleplay=roleplay, speak_slow=speak_slow, translate_fn=translate_text,
            )
            result = self._education_tts(result, lang)
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_education_voice(self, params):
        lang = (params.get("lang") or ["en"])[0]
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return self.send_json_error(400, "Ses kaydı boş — tekrar dene")
        data = self.rfile.read(length)

        state: dict = {}
        state_raw = self.headers.get("X-Education-State", "").strip()
        if state_raw:
            state = decode_education_state(state_raw)

        if not state:
            state_b64 = (params.get("state") or [""])[0].strip()
            if state_b64:
                state = decode_education_state(state_b64)

        if EDU_STATE_MARKER in data:
            idx = data.index(EDU_STATE_MARKER)
            if not state and idx > 0:
                try:
                    state = json.loads(data[:idx].decode("utf-8"))
                except Exception:
                    pass
            data = data[idx + len(EDU_STATE_MARKER):]

        if len(data) < 50:
            return self.send_json_error(400, "Kayıt çok kısa — butona basılı tutup konuşun")

        profile = merge_profile(state.get("profile"), None)
        if profile.get("targetLang") != lang:
            profile["targetLang"] = lang
        history = state.get("history") or []
        if not isinstance(history, list):
            history = []
        history = [
            {"role": h.get("role", "user"), "text": str(h.get("text", ""))[:500]}
            for h in history if isinstance(h, dict) and h.get("text")
        ][:24]
        roleplay = state.get("roleplay")
        speak_slow = bool(state.get("speak_slow"))
        last_lang = state.get("last_lang") or lang
        try:
            original, detected = transcribe_dual(data, "tr", lang, last_lang)
            result = process_turn(
                original, detected, lang, history, profile,
                roleplay=roleplay, speak_slow=speak_slow, translate_fn=translate_text,
            )
            result["user_text"] = original
            result["user_lang"] = detected
            result = self._education_tts(result, lang)
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_tutor_lesson(self, params):
        import base64

        lesson_id = (params.get("id") or [""])[0].strip()
        lang = (params.get("lang") or ["en"])[0]
        if not lesson_id:
            self.send_error(400, "id required")
            return
        try:
            result = get_lesson(lesson_id, lang)
            if not result:
                self.send_json_error(404, "Ders bulunamadı")
                return
            phrase = result.get("correct_phrase") or ""
            if phrase:
                audio = synthesize(phrase[:500], lang)
                result["audio"] = base64.b64encode(audio).decode("ascii")
            else:
                result["audio"] = ""
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_converse(self, params):
        text = (params.get("q") or [""])[0].strip()
        from_lang = (params.get("from") or ["tr"])[0]
        to_lang = (params.get("to") or ["en"])[0]
        if not text:
            self.send_error(400, "q required")
            return
        try:
            translated = translate_text(text[:500], from_lang, to_lang)
            audio_b64 = ""
            try:
                audio = synthesize(translated[:500], to_lang)
                import base64
                audio_b64 = base64.b64encode(audio).decode("ascii")
            except Exception:
                pass

            body = json.dumps(
                {"translated": translated, "audio": audio_b64}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_tts(self, params):
        text = (params.get("q") or [""])[0].strip()
        lang = (params.get("tl") or ["tr"])[0].strip()
        slow = (params.get("slow") or ["0"])[0].lower() in ("1", "true", "yes")
        if not text:
            self.send_json_error(400, "Metin gerekli")
            return
        try:
            data = synthesize(text[:2500], lang, slow=slow)
            if not data:
                raise ValueError("Ses oluşturulamadı")
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_translate(self, params):
        text = (params.get("q") or [""])[0].strip()
        from_lang = (params.get("from") or ["tr"])[0]
        to_lang = (params.get("to") or ["en"])[0]
        my = (params.get("my") or [from_lang])[0]
        other = (params.get("other") or [to_lang])[0]
        if not text:
            self.send_json_error(400, "Metin gerekli")
            return
        try:
            # Yazı çevirisinde yönü metne göre düzelt — karşı dil Türkçe tarafa yazılmasın
            translated, from_lang, to_lang = translate_pair_safe(
                text, from_lang, to_lang, my, other,
            )
            body = json.dumps({
                "text": translated,
                "from": from_lang,
                "to": to_lang,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))

    def handle_pronounce_batch(self):
        """Hızlı telaffuz yenileme — kayıtlı dersler için (LLM yok)."""
        from pronunciation_service import build_pronunciation_bundle

        payload = self._read_json_body()
        texts = payload.get("texts") or []
        lang = safe_str(payload.get("lang") or "en").strip() or "en"
        bundles: dict[str, dict] = {}
        for raw in texts[:24]:
            text = safe_str(raw).strip()
            if not text or text in bundles:
                continue
            bundles[text] = build_pronunciation_bundle(text, lang)
        self._send_json({"ok": True, "bundles": bundles})

    def handle_pronounce(self, params):
        text = (params.get("q") or [""])[0].strip()
        lang = (params.get("lang") or params.get("tl") or ["en"])[0]
        if not text:
            self.send_json_error(400, "Metin gerekli")
            return
        try:
            # Kelime modülüyle aynı profesyonel Türkçe fonetik (LLM yok → hızlı)
            phonetic = translate_phonetic(text, lang) or pronounce_text(text, lang)
            body = json.dumps({"phonetic": phonetic}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_json_error(422, self.api_error_message(e))


if __name__ == "__main__":
    import threading

    from public_url import persist_public_url, resolve_public_url
    from telegram_bot import start_telegram_bot, maybe_notify_startup, _load_env as _tg_env

    print(f"Serving {ROOT} on port {PORT}")

    def _warm_whisper() -> None:
        if DISABLE_WHISPER:
            print("Whisper kapalı — Google STT + Groq Whisper STT.")
            return
        print(f"Whisper lazy-load ({WHISPER_MODEL}) — ilk gerektiğinde yüklenecek.")

    threading.Thread(target=_warm_whisper, name="whisper-warmup", daemon=True).start()

    _tg_env()
    url = resolve_public_url()
    if url:
        persist_public_url(url)
        print(f"Genel adres: {url}")
    bot = start_telegram_bot()
    if bot:
        print("Telegram bot aktif — /link ile adres alınır (otomatik bildirim kapalı)")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if chat_id and url:
            maybe_notify_startup(chat_id, url)
    print("Hazır (çoklu istek destekli).")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
