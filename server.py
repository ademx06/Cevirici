#!/usr/bin/env python3
"""Sesli Çevirmen — statik dosya + TTS/çeviri API sunucusu."""
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
import asyncio
import html
import json
import os
import re
import subprocess
import tempfile

from tutor import get_lesson, tutor_reply
from education_engine import (
    process_turn, greeting, session_report, daily_lesson, default_profile,
    finalize_session, weekly_progress, merge_profile,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8780

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
        return edge_tts(text, lang, rate="-25%")
    data = google_tts(text, lang)
    if data:
        return data
    return edge_tts(text, lang)


def google_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    url = (
        f"https://translate.google.com/m?sl={quote(from_lang)}&tl={quote(to_lang)}"
        f"&q={quote(text)}"
    )
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=15) as resp:
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
    with urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    translated = data.get("responseData", {}).get("translatedText", "").strip()
    if not translated:
        raise ValueError("empty translation")
    return translated


def translate_text(text: str, from_lang: str, to_lang: str) -> str:
    if from_lang == to_lang:
        return text
    translated = google_translate(text, from_lang, to_lang)
    if translated:
        return translated
    return mymemory_translate(text, from_lang, to_lang)


_whisper_model = None

WHISPER_PROMPTS: dict[str, str] = {}


def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


def prepare_wav(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp.write(data)
        inp = tmp.name
    wav = inp + ".wav"
    for af in ("highpass=f=80,lowpass=f=7500,apad=pad_dur=1.2,volume=2.0", "volume=2.0", None):
        cmd = ["ffmpeg", "-y", "-i", inp, "-ar", "16000", "-ac", "1", wav]
        if af:
            cmd[4:4] = ["-af", af]
        result = subprocess.run(cmd, capture_output=True, timeout=20)
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
        return float(maxv.group(1)) > -38 and float(mean.group(1)) > -45
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
    recognizer.energy_threshold = 280
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.6

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
            if len(text) >= 2:
                return text, short, 0.88
        except sr.UnknownValueError:
            continue
        except sr.RequestError:
            return None
    return None


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
            beam_size=5,
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
            r"where|when|who|why|the|this|that|is|are|was|were|your|holiday|i'm|im)\b",
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


def score_text(text: str, lang: str) -> float:
    t = text.strip()
    if len(t) < 2:
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


def stt_for_lang(wav: str, lang: str, allow_whisper: bool = True) -> tuple[str, str, float] | None:
    google = google_stt(wav, lang)
    if google and google[0].strip():
        text = google[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 40

    if not allow_whisper:
        return None

    whisper = whisper_stt(wav, lang)
    if whisper and whisper[0].strip():
        text = whisper[0].strip()
        if is_hallucination(text):
            return None
        return text, lang, score_text(text, lang) + 5
    return None


def resolve_lang_from_text(text: str, my: str, other: str, stt_lang: str) -> str:
    t = text.strip()
    my_like = looks_like_lang(t, my)
    other_like = looks_like_lang(t, other)

    if other_like and not my_like:
        return other
    if my_like and not other_like:
        return my

    if other == "en" and my == "tr":
        en_hits = len(re.findall(
            r"\b(how|was|your|holiday|fine|thank|thanks|you|are|hello|what|where|when|"
            r"who|why|good|morning|please|yes|no|i'm|im)\b",
            t,
            re.I,
        ))
        tr_hits = len(re.findall(
            r"\b(merhaba|nasılsın|nasilsin|teşekkür|iyiyim|naber|evet|hayır|günaydın)\b",
            t,
            re.I,
        ))
        if en_hits >= 2 and en_hits > tr_hits:
            return "en"
        if tr_hits >= 1 and en_hits == 0:
            return "tr"

    if other == "ka" and re.search(r"[\u10A0-\u10FF]", t):
        return "ka"
    if my == "ka" and re.search(r"[\u10A0-\u10FF]", t):
        return "ka"
    if other == "ru" and re.search(r"[\u0400-\u04FF]", t):
        return "ru"
    if my == "ru" and re.search(r"[\u0400-\u04FF]", t):
        return "ru"

    return stt_lang if stt_lang in (my, other) else my


def transcribe_dual(data: bytes, my: str, other: str, last_from: str | None = None) -> tuple[str, str]:
    wav = prepare_wav(data)
    try:
        if not audio_has_speech(wav):
            raise ValueError("no speech detected")

        candidates: list[tuple[str, str, float]] = []
        for lang in (my, other):
            r = stt_for_lang(wav, lang)
            if r:
                candidates.append(r)

        if not candidates:
            raise ValueError("speech not recognized")

        def rank(item: tuple[str, str, float]) -> float:
            text, lang, score = item
            alt = other if lang == my else my
            s = score
            if looks_like_lang(text, lang):
                s += 22
            if looks_like_lang(text, alt) and not looks_like_lang(text, lang):
                s -= 35
            if last_from == lang and looks_like_lang(text, lang):
                s += 4
            elif last_from == alt and looks_like_lang(text, alt):
                s -= 8
            return s

        best = max(candidates, key=rank)
        text = best[0]
        from_lang = resolve_lang_from_text(text, my, other, best[1])
        return text, from_lang
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


def transcribe_audio(data: bytes, lang_code: str) -> tuple[str, str, float]:
    if len(data) < 200:
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
            return "Konuşma anlaşılamadı — daha net ve biraz daha uzun konuşun"
        if "no speech" in msg:
            return "Konuşma algılanmadı — basılı tutup konuşun"
        if "audio conversion" in msg or "ffmpeg" in msg:
            return "Ses dosyası işlenemedi — tekrar deneyin"
        if "too short" in msg:
            return "Kayıt çok kısa — butona basılı tutup konuşun"
        return "Bir hata oluştu — tekrar deneyin"

    def end_headers(self):
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
        if parsed.path == "/api/tutor":
            return self.handle_tutor(parse_qs(parsed.query))
        if parsed.path == "/api/education/voice":
            return self.handle_education_voice(parse_qs(parsed.query))
        if parsed.path == "/api/education/chat":
            return self.handle_education_chat(parse_qs(parsed.query))
        if parsed.path == "/api/education/session-end":
            return self.handle_education_session_end(parse_qs(parsed.query))
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/converse":
            return self.handle_converse(parse_qs(parsed.query))
        if parsed.path == "/api/tts":
            return self.handle_tts(parse_qs(parsed.query))
        if parsed.path == "/api/translate":
            return self.handle_translate(parse_qs(parsed.query))
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
        return super().do_GET()

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
        body = json.dumps(
            {"ok": True, "origin": origin, "port": PORT},
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
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

    def handle_process(self, params):
        import base64

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
            translated = translate_text(original, from_lang, to_lang)
            audio = synthesize(translated[:500], to_lang)
            body = json.dumps({
                "original": original,
                "translated": translated,
                "from": from_lang,
                "to": to_lang,
                "audio": base64.b64encode(audio).decode("ascii"),
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
        import base64

        speak = (result.get("speak_text") or result.get("teacher_text") or "")[:500]
        slow = bool(result.get("speak_slow"))
        if speak:
            audio = synthesize(speak, lang, slow=slow)
            result["audio"] = base64.b64encode(audio).decode("ascii")
        else:
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
            self.send_error(400, "empty body")
            return
        data = self.rfile.read(length)
        state_raw = self.headers.get("X-Education-State", "")
        try:
            state = json.loads(state_raw) if state_raw else {}
        except Exception:
            state = {}
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
            original, detected = transcribe_dual(data, lang, "tr", last_lang)
            result = process_turn(
                original, detected, lang, history, profile,
                roleplay=roleplay, speak_slow=speak_slow, translate_fn=translate_text,
            )
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
            audio = synthesize(translated[:500], to_lang)
            import base64

            body = json.dumps(
                {"translated": translated, "audio": base64.b64encode(audio).decode("ascii")}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(502, str(e))

    def handle_tts(self, params):
        text = (params.get("q") or [""])[0].strip()
        lang = (params.get("tl") or ["tr"])[0].strip()
        if not text:
            self.send_error(400, "q required")
            return
        try:
            data = synthesize(text[:500], lang)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(502, str(e))

    def handle_translate(self, params):
        text = (params.get("q") or [""])[0].strip()
        from_lang = (params.get("from") or ["tr"])[0]
        to_lang = (params.get("to") or ["en"])[0]
        if not text:
            self.send_error(400, "q required")
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
            self.send_error(502, str(e))


if __name__ == "__main__":
    print(f"Serving {ROOT} on port {PORT}")
    print("Whisper modeli yükleniyor...")
    get_whisper()
    print("Hazır.")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
