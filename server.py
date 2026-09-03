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
)
from builder_engine import (
    generate_word_lesson,
    analyze_sentence_for_builder,
    grade_word_answer,
    grade_sentence_answer,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "2026.09.03-v70"
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


def google_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    url = (
        f"https://translate.google.com/m?sl={quote(from_lang)}&tl={quote(to_lang)}"
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


def mymemory_translate(text: str, from_lang: str, to_lang: str) -> str:
    url = (
        "https://api.mymemory.translated.net/get?"
        f"q={quote(text)}&langpair={quote(from_lang)}|{quote(to_lang)}"
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


def smart_translate_text(text: str, from_lang: str, to_lang: str) -> str:
    """Hızlı + doğru çeviri — önbellek, Groq/Gemini, Google yedek."""
    if from_lang == to_lang:
        return text
    src = text.strip()
    if not src:
        return ""
    key = (from_lang, to_lang, src.lower())
    cached = _cache_get(_TRANSLATE_CACHE, key)
    if cached:
        return cached

    primary_pair = {from_lang, to_lang} <= {"tr", "en"}
    use_llm_first = llm_available() and not primary_pair
    result: str | None = None

    if use_llm_first:
        try:
            result = llm_translate(src, from_lang, to_lang)
        except Exception:
            result = None

    if not result:
        result = google_translate(src, from_lang, to_lang)

    if not result:
        try:
            result = mymemory_translate(src, from_lang, to_lang)
        except Exception:
            result = None

    if not result and llm_available():
        try:
            result = llm_translate(src, from_lang, to_lang)
        except Exception:
            result = None

    if not result:
        raise ValueError("translation failed")

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

    translated = translate_text(src, from_lang, to_lang)

    # Hedef Türkçe ama sonuç hâlâ İngilizce görünüyorsa yönü düzeltip tekrar dene
    if to_lang == "tr" and is_likely_english(translated, "tr", "en") and not is_likely_turkish(translated):
        if is_likely_english(src, "tr", "en"):
            from_lang, to_lang = "en", "tr"
            translated = translate_text(src, "en", "tr")
        elif from_lang == "tr":
            # Belki STT İngilizce yazdı ama tr sandık
            alt = translate_text(src, "en", "tr")
            if is_likely_turkish(alt) or not is_likely_english(alt, "tr", "en"):
                from_lang, to_lang = "en", "tr"
                translated = alt

    # Hedef İngilizce ama sonuç Türkçe kaldıysa
    if to_lang == "en" and is_likely_turkish(translated) and not is_likely_english(translated, "tr", "en"):
        if is_likely_turkish(src):
            from_lang, to_lang = "tr", "en"
            translated = translate_text(src, "tr", "en")

    return translated, from_lang, to_lang


def translate_phonetic(text: str, lang: str) -> str:
    """Kelime dersindeki gibi Türkçe fonetik okunuş — TTS ile uyumlu, LLM yok (hızlı)."""
    if not text or lang == "tr":
        return ""
    try:
        from pronunciation_service import build_sentence_natural
        return safe_str(build_sentence_natural(text, lang)).strip()[:160]
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
        filters = ("volume=2.2,apad=pad_dur=0.5", "volume=2.2", None)
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
            ("response_format", "json"),
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
        text = (payload.get("text") or "").strip()
        if len(text) < 2 or is_hallucination(text):
            return None
        detected = short
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
    """Çeviri modu — Groq Whisper önce (doğru telaffuz), Google yedek, local whisper son şans."""
    groq = groq_stt(wav, lang, translate_mode=True)
    if groq and groq[0].strip() and not is_hallucination(groq[0]):
        return groq

    google = google_stt(wav, lang)
    if google and google[0].strip():
        text = google[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 28

    if not DISABLE_WHISPER:
        w = whisper_stt(wav, lang)
        if w and w[0].strip() and not is_hallucination(w[0]):
            return w
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
        r"\b(merhaba|nasılsın|nasilsin|teşekkür|evet|hayır|tamam|iyiyim|günaydın|"
        r"neler|yapıyorum|yaptım|gittim|yorgunum|kitap|okudum|bugün|yarın|"
        r"koştum|kosdum|koşuyorum|yürüdüm|izledim|çalıştım|evde|parka|işe)\b",
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


def transcribe_dual(data: bytes, my: str, other: str, last_from: str | None = None) -> tuple[str, str]:
    wav = prepare_wav(data, fast=True)
    try:
        # Sessizlik kontrolünü atla — boş STT zaten hata verir; ekstra ffmpeg ~0.5-1s kazandırır
        candidates: list[tuple[str, str, float, str]] = []
        predicted = None
        if last_from in (my, other):
            predicted = other if last_from == my else my

        def add(r: tuple[str, str, float] | None, source: str) -> None:
            if r and r[0].strip() and not is_hallucination(r[0]):
                candidates.append((r[0].strip(), r[1], r[2], source))

        if predicted:
            add(stt_for_translate(wav, predicted), f"pred_{predicted}")
            # Sıra tahmini doğruysa ek STT çağrılarını atla (büyük hız kazancı)
            if candidates:
                text, stt_lang, _score, _src = candidates[0]
                guessed = detect_speech_lang(text, my, other, stt_lang, last_from)
                strong = (
                    guessed == predicted
                    and (
                        (predicted == "en" and is_likely_english(text, my, other) and not is_likely_turkish(text))
                        or (predicted == "tr" and is_likely_turkish(text) and not is_likely_english(text, my, other))
                    )
                )
                if strong:
                    return text, guessed

        tasks = {
            "auto": lambda: groq_stt_auto(wav),
            f"lang_{my}": lambda: stt_for_translate(wav, my),
            f"lang_{other}": lambda: stt_for_translate(wav, other),
        }
        if predicted:
            tasks.pop(f"lang_{predicted}", None)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fn): key for key, fn in tasks.items()}
            for fut in as_completed(futures):
                try:
                    add(fut.result(), futures[fut])
                except Exception:
                    continue

        if not candidates:
            for lang in (my, other):
                r = stt_for_lang(wav, lang, allow_whisper=not DISABLE_WHISPER)
                add(r, f"fallback_{lang}")

        # Son şans: auto dil ile whisper dene (kısa kelimeler için)
        if not candidates:
            try:
                r = whisper_stt(wav, "auto")
                add(r, "fallback_whisper_auto")
            except Exception:
                pass

        if not candidates:
            raise ValueError("speech not recognized")

        def rank(item: tuple[str, str, float, str]) -> float:
            text, stt_lang, score, _source = item
            from_lang = detect_speech_lang(text, my, other, stt_lang, last_from)
            alt = other if from_lang == my else my
            s = score
            if from_lang == stt_lang:
                s += 18
            if from_lang == other and is_likely_english(text, my, other):
                s += 35
            if from_lang == my and is_likely_turkish(text):
                s += 35
            if looks_like_lang(text, from_lang) or (
                from_lang == "en" and is_likely_english(text, my, other)
            ):
                s += 22
            if from_lang == alt and is_likely_english(text, my, other) and other == "en":
                s -= 50
            if from_lang == alt and is_likely_turkish(text) and my == "tr":
                s -= 50
            if last_from == from_lang:
                s += 8
            elif last_from == alt:
                s -= 6
            return s

        best = max(candidates, key=rank)
        text = best[0]
        from_lang = detect_speech_lang(text, my, other, best[1], last_from)
        # Metin içeriğine göre dili kilitle — İngilizce konuşma Türkçe balona düşmesin
        if {my, other} == {"tr", "en"}:
            if is_likely_english(text, my, other) and not is_likely_turkish(text):
                from_lang = "en"
            elif is_likely_turkish(text) and not is_likely_english(text, my, other):
                from_lang = "tr"
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
        try:
            original, from_lang = transcribe_dual(data, my, other, last_from)
            to_lang = other if from_lang == my else my
            translated, from_lang, to_lang = translate_pair_safe(
                original, from_lang, to_lang, my, other,
            )
            phonetic = translate_phonetic(translated, to_lang)
            body = json.dumps({
                "original": original,
                "translated": translated,
                "from": from_lang,
                "to": to_lang,
                "phonetic": phonetic,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
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
            data = synthesize(text[:500], lang, slow=slow)
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
        if not text:
            self.send_json_error(400, "Metin gerekli")
            return
        try:
            translated = translate_text(text, from_lang, to_lang)
            body = json.dumps({"text": translated}).encode()
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
