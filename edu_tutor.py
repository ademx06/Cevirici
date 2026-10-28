"""Eğitim — hızlı yapay zekâ öğretmen (tur başına tek çağrı).

Her tur tek bir JSON yanıtı üretir:
  • hedef dilde doğal, seviyeye uygun cevap + Türkçe anlamı + Türkçe okunuşu
  • öğrencinin cümlesi için düzeltme / daha doğal hali + Türkçe açıklama
  • (Yardım modunda) söylenmek istenen şeyin hedef dilde 2-3 kolay örneği
  • öğrencinin cümlesinin tahmini CEFR seviyesi (istemci seviyeyi buna göre ayarlar)

Yapay zekâ yoksa eski kural motoru yedek olarak kullanılır.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

import education_engine as ee
import okunus as ok

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "ru": "Russian", "ar": "Arabic", "zh": "Chinese (Mandarin, simplified)", "ka": "Georgian",
    "id": "Indonesian (Bahasa Indonesia)",
}

LEVEL_GUIDE = {
    "A1": "Very short sentences (max ~8 words), only the most common words, present tense. One simple question.",
    "A2": "Short simple sentences, everyday vocabulary, present/past/future basics. One clear question.",
    "B1": "Natural everyday sentences, some connectors (because, but, so), common idioms rarely. One open question.",
    "B2": "Fluent natural speech, varied tenses and connectors, some idioms. Ask an open follow-up.",
    "C1": "Rich, nuanced, idiomatic native speech. Challenge the learner with a thoughtful question.",
    "C2": "Fully native, sophisticated register, subtle idioms. Discuss in depth.",
}

SCRIPT_RULE = {
    "ka": "Write target-language text ONLY in Georgian Mkhedruli script.",
    "ru": "Write target-language text ONLY in Cyrillic.",
    "ar": "Write target-language text in Arabic script WITH full harakat (short-vowel marks).",
    "zh": "Write target-language text in simplified Chinese characters.",
}

# Languages whose Turkish reading the model must produce (no reliable rules)
LLM_OKUNUS = {"en", "ar"}
# Chinese: the model writes pinyin (very reliable) → we convert to Turkish letters by rule
PINYIN_LANGS = {"zh"}

OKUNUS_RULE = (
    "OKUNUS = how a Turkish speaker should read the exact target text aloud, written ONLY with the Turkish "
    "alphabet (a b c ç d e f g ğ h ı i j k l m n o ö p r s ş t u ü v y z). It is NOT a translation. "
    "NEVER use IPA or other symbols (ð θ æ ə ɪ ʃ ʒ ŋ ː), never the letters q w x, never 'th'/'dh' (the -> dı, think -> tink). "
    "Follow real native pronunciation (silent letters dropped, linking, weak vowels as ı). "
    "Examples: English 'How are you today?' -> 'Hav ar yu tıdey?'; 'I would like a coffee.' -> 'Ay vud layk ı kofi.'; "
    "'The weather is nice.' -> 'Dı vedır iz nays.'; 'Thank you very much!' -> 'Tenk yu veri maç!'; "
    "Arabic 'كَيْفَ حَالُكَ؟' -> 'Keyfe hâlük?'; Arabic 'أُحِبُّ الْقَهْوَةَ' -> 'Uhibbu'l-kahve.'"
)


def _scenario_text(sid: str | None, lang: str) -> str:
    if not sid:
        return ""
    rp = ee.ROLEPLAYS.get(sid) or {}
    if not rp:
        return ""
    desc = rp.get(lang) or rp.get("*") or rp.get("en") or ""
    parts = [f"ROLEPLAY: {rp.get('title') or sid}."]
    if rp.get("teacherRole"):
        parts.append(f"You play: {rp['teacherRole']}.")
    if rp.get("userRole"):
        parts.append(f"Learner plays: {rp['userRole']}.")
    if rp.get("goal"):
        parts.append(f"Goal: {rp['goal']}")
    if desc:
        parts.append(desc)
    parts.append("Stay in role; improvise from what the learner says; never break character except in 'tip_tr'.")
    return " ".join(parts)


def _history_text(history: list[dict]) -> str:
    lines = []
    for h in (history or [])[-12:]:
        if not isinstance(h, dict):
            continue
        txt = ee.safe_str(h.get("text")).strip().replace("\n", " ")[:300]
        if not txt:
            continue
        who = "Learner" if h.get("role") == "user" else "Tutor"
        lines.append(f"{who}: {txt}")
    return "\n".join(lines) or "(conversation just started)"


def _system_prompt(lang: str, level: str, mode: str, scenario: str, weak: list[str]) -> str:
    name = LANG_NAMES.get(lang, lang)
    need_ok = False  # en/ar okunuşu ayrı, hızlı ve özel bir çağrıyla üretilir (_repair_okunus)
    need_py = lang in PINYIN_LANGS
    ok_field = ', "okunus": "<Turkish reading of reply>"' if need_ok else ', "pinyin": "<pinyin of reply with tone marks>"' if need_py else ""
    ok_fix = ', "fixed_okunus": "<Turkish reading of fixed>"' if need_ok else ', "fixed_pinyin": "<pinyin with tone marks>"' if need_py else ""
    ok_ex = ', "okunus": "<Turkish reading>"' if need_ok else ', "pinyin": "<pinyin with tone marks>"' if need_py else ""
    weak_line = f"Learner's known weak points: {', '.join(weak[:5])}." if weak else ""
    if mode == "help":
        task = (
            f"The learner pressed HELP and spoke TURKISH. They want to know how to say something in {name}, "
            f"or how to answer the tutor's last question. Give 2-3 short, natural {name} sentences they can say "
            f"right now (easy -> more natural), fitting the conversation. Put them in 'examples'. "
            f"'explain_tr' = 1-2 short Turkish sentences teaching the key structure. "
            f"'reply' = one short {name} line encouraging them to try (e.g. 'Try saying it!'). 'fix' = null."
        )
        schema = (
            '{"reply": "<short target-language line>", "reply_tr": "<Turkish meaning>"' + ok_field + ', '
            '"examples": [{"text": "<target sentence>", "tr": "<Turkish meaning>"' + ok_ex + '}], '
            '"explain_tr": "<Turkish teaching note>", "fix": null, "words": [], "user_level": "A1"}'
        )
    else:
        task = (
            f"The learner spoke {name} (may contain mistakes or speech-recognition noise). "
            f"1) Understand what they MEANT. 2) Check the sentence like a strict native teacher: verb forms and "
            f"tense, auxiliary verbs, articles, gender, case, agreement, prepositions, word order. If there is ANY real "
            f"grammar or word error (write your analysis in 'check' FIRST), put the corrected sentence in "
            f"'fix.fixed' with status 'fix' and explain the rule in 1-2 simple Turkish sentences in 'fix.explain_tr'. "
            f"If it is correct but unnatural, use status 'better' with a more natural version. If it is fine, "
            f"'fix' = null. Never 'fix' punctuation or capitalization only. "
            f"3) Reply naturally in {name}: react to what they said, then ask ONE follow-up question so the "
            f"conversation continues. 4) 'words': 0-2 useful words from your reply that are likely new at this "
            f"level (word in {name} + Turkish meaning). "
            + ("BEGINNER (A1/A2): act as a step-by-step teacher — teach ONE short phrase per turn (say what it means in 'reply_tr'), "
               "and END 'reply' by inviting the learner to repeat or use that phrase instead of asking an open question. " if level in ("A1", "A2") else "")
        )
        schema = (
            '{"check": "<one short English line: quote each wrong word/form in the learner sentence and the rule, or OK>", '
            '"reply": "<target-language reply>", "reply_tr": "<Turkish meaning>"' + ok_field + ', '
            '"fix": {"status": "fix|better", "fixed": "<corrected learner sentence>", "fixed_tr": "<Turkish>"'
            + ok_fix + ', "explain_tr": "<why, in Turkish>"} or null, '
            '"words": [{"word": "<target word>", "tr": "<Turkish>"}], "user_level": "A1|A2|B1|B2|C1|C2"}'
        )
    return "\n".join(filter(None, [
        f"You are a warm, encouraging {name} tutor for a Turkish native speaker.",
        f"LEARNER LEVEL: {level}. Style for this level: {LEVEL_GUIDE.get(level, LEVEL_GUIDE['A1'])}",
        weak_line,
        scenario,
        SCRIPT_RULE.get(lang, ""),
        "Keep 'reply' short (1-3 sentences) so it can be spoken instantly. No emojis in target-language text.",
        "All Turkish fields must be natural Turkish.",
        "TASK: " + task,
        "Return ONLY this JSON (no markdown):",
        schema,
    ]))


def _strip_think(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    return m.group(0) if m else raw


_GROQ_JSON_OK: dict[str, bool] = {}
_GROQ_DEAD: dict[str, float] = {}
# Eğitim için en doğru düzeltmeyi yapan hızlı model (Groq). Yoksa GROQ_MODEL, sonra Gemini.
EDU_GROQ_DEFAULT = "openai/gpt-oss-120b"


def _groq_models(model_override: str = "") -> list[str]:
    out: list[str] = []
    for m in (model_override, os.environ.get("EDU_GROQ_MODEL", "").strip(), EDU_GROQ_DEFAULT,
              os.environ.get("GROQ_MODEL", "").strip()):
        if m and m not in out and _GROQ_DEAD.get(m, 0) < time.time():
            out.append(m)
    return out


def _groq(messages: list[dict], model: str, max_tokens: int, json_mode: bool, timeout: float) -> tuple[str | None, int]:
    """Returns (text, http_status). status 0 = network/timeout."""
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    if not ee.groq_api_key_valid():
        return None, 0
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.4, "max_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max_tokens + 500  # reasoning tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        req = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers=ee._api_headers({"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '').strip()}"}),
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return (data["choices"][0]["message"].get("content") or "").strip() or None, 200
    except HTTPError as exc:
        return None, exc.code
    except Exception:
        return None, 0


def _call_llm(system: str, user: str, max_tokens: int = 700, *, engine: str = "", model_override: str = "",
              require: str = "reply") -> tuple[dict | None, str]:
    """Groq (doğru + hızlı model) → Groq yedek model → Gemini. Returns (json, provider)."""
    providers = ee._llm_providers_in_order()
    engine = engine or os.environ.get("EDU_ENGINE", "").strip().lower()
    if engine in providers:
        providers = [engine] + [p for p in providers if p != engine]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for prov in providers:
        if prov == "groq":
            for model in _groq_models(model_override):
                use_json = _GROQ_JSON_OK.get(model, True)
                raw, status = _groq(messages, model, max_tokens, use_json, 10)
                if not raw and status == 400 and use_json:
                    raw, status = _groq(messages, model, max_tokens, False, 10)
                    if raw:
                        _GROQ_JSON_OK[model] = False
                if not raw and status in (404, 403):
                    _GROQ_DEAD[model] = time.time() + 1800  # model yok / izin yok — yarım saat atla
                if not raw and status == 429:
                    _GROQ_DEAD[model] = time.time() + 60
                if raw:
                    parsed = ee._parse_json_object(_strip_think(raw))
                    if parsed and (parsed.get(require) is not None and str(parsed.get(require)).strip() != ""):
                        return parsed, "groq"
            continue
        raw = None
        if prov == "gemini":
            raw = ee._gemini_api_request({
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4,
                                     "maxOutputTokens": max_tokens},
            }, max_tokens, timeout_sec=14)
        elif prov == "openai":
            raw = ee._openai_chat(messages, json_mode=True, max_tokens=max_tokens)
        if not raw:
            continue
        parsed = ee._parse_json_object(_strip_think(raw))
        if parsed and (parsed.get(require) is not None and str(parsed.get(require)).strip() != ""):
            return parsed, prov
    return None, ""


def llm_okunus(text: str, lang: str) -> str:
    """Sadece okunuş üret (İngilizce/Fransızca/Arapça/Çince için) — kısa, hızlı çağrı."""
    name = LANG_NAMES.get(lang, lang)
    if lang in PINYIN_LANGS:
        parsed, _ = _call_llm_simple('Write the Hanyu pinyin (with tone marks, words spaced) of the Chinese text. Return ONLY JSON: {"pinyin": "..."}', text[:500])
        return ok.pinyin_okunus(_s((parsed or {}).get("pinyin"), 900))
    got = llm_okunus_batch([text[:500]], lang)
    return got[0] if got else ""


def llm_okunus_batch(texts: list[str], lang: str) -> list[str]:
    """Birden çok cümlenin okunuşu tek hızlı çağrıda (sıra korunur)."""
    if not texts:
        return []
    name = LANG_NAMES.get(lang, lang)
    system = (
        f"You convert {name} sentences into their Turkish reading. {OKUNUS_RULE} "
        "Keep EVERY word of the source, in the same order; do not translate. "
        'Return ONLY JSON: {"okunus": ["<reading of line 1>", "<reading of line 2>", ...]}'
    )
    if lang == "en":
        # Aynı kelime her yerde aynı okunsun: sözlük okunuşlarını referans ver (model yalnızca açıkça yanlışsa değiştirir)
        try:
            import pronunciation_service as _ps
            words = list(dict.fromkeys(re.findall(r"[A-Za-z']{3,}", " ".join(texts))))[:40]
            hints = "; ".join(f"{w}={_ps._resolve_en_phonetic(w).replace('-', '')}" for w in words)
            system += " REFERENCE dictionary readings (use them; change one only if clearly wrong): " + hints + "."
        except Exception:
            pass
    user = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    parsed, _ = _call_llm_simple(system, user)
    arr = (parsed or {}).get("okunus")
    if isinstance(arr, str):
        arr = [arr]
    if not isinstance(arr, list):
        return [""] * len(texts)
    out = [ok.normalize_okunus(re.sub(r"^\s*\d+[.)]\s*", "", _s(x, 900))) for x in arr[: len(texts)]]
    return out + [""] * (len(texts) - len(out))


def _call_llm_simple(system: str, user: str) -> tuple[dict | None, str]:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for prov in ee._llm_providers_in_order():
        raw = None
        if prov == "groq":
            raw = ee._groq_chat(messages, max_tokens=400, json_mode=True, timeout_sec=8,
                                model=os.environ.get("EDU_GROQ_MODEL") or os.environ.get("GROQ_MODEL") or None,
                                temperature=0.0)
        elif prov == "gemini":
            raw = ee._gemini_api_request({
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0,
                                     "maxOutputTokens": 400},
            }, 400, timeout_sec=10)
        if raw:
            parsed = ee._parse_json_object(_strip_think(raw))
            if parsed:
                return parsed, prov
    return None, ""


def _s(v: Any, n: int = 600) -> str:
    return re.sub(r"\s+", " ", ee.safe_str(v)).strip()[:n]


def _clean_target(text: str) -> str:
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿️]", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _okunus_for(text: str, lang: str, llm_value: str = "", pinyin: str = "") -> str:
    if not text:
        return ""
    if lang in PINYIN_LANGS:
        got = ok.pinyin_okunus(pinyin) if pinyin else ""
        if got and ok.looks_valid(got, text, lang):
            ok.remember(text, lang, got)
            return got
        return ok.cached(text, lang)
    if lang in LLM_OKUNUS:
        if ok.looks_valid(llm_value, text, lang):
            ok.remember(text, lang, llm_value)
            return llm_value.strip()
        return ok.cached(text, lang)
    return ok.okunus(text, lang)


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[^\w]+", " ", (s or "").lower()).strip()
    return norm(a) == norm(b)


def _normalize(parsed: dict, lang: str, mode: str, user_text: str) -> dict:
    reply = _clean_target(_s(parsed.get("reply"), 500))
    out: dict[str, Any] = {
        "reply": reply,
        "reply_tr": _s(parsed.get("reply_tr"), 500),
        "okunus": _okunus_for(reply, lang, _s(parsed.get("okunus"), 700), _s(parsed.get("pinyin"), 700)),
        "fix": None,
        "examples": [],
        "explain_tr": _s(parsed.get("explain_tr"), 500),
        "words": [],
        "user_level": _s(parsed.get("user_level"), 4).upper() if _s(parsed.get("user_level"), 4).upper() in LEVELS else "",
    }
    fix = parsed.get("fix")
    if mode != "help" and isinstance(fix, dict):
        fixed = _clean_target(_s(fix.get("fixed"), 400))
        status = _s(fix.get("status"), 10).lower()
        if fixed and not _same(fixed, user_text):
            out["fix"] = {
                "status": "better" if status == "better" else "fix",
                "fixed": fixed,
                "fixed_tr": _s(fix.get("fixed_tr"), 400),
                "okunus": _okunus_for(fixed, lang, _s(fix.get("fixed_okunus"), 600), _s(fix.get("fixed_pinyin"), 600)),
                "explain_tr": _s(fix.get("explain_tr"), 500),
            }
    for ex in (parsed.get("examples") or [])[:3]:
        if not isinstance(ex, dict):
            continue
        t = _clean_target(_s(ex.get("text"), 300))
        if t:
            out["examples"].append({
                "text": t, "tr": _s(ex.get("tr"), 300),
                "okunus": _okunus_for(t, lang, _s(ex.get("okunus"), 500), _s(ex.get("pinyin"), 500)),
            })
    for w in (parsed.get("words") or [])[:3]:
        if not isinstance(w, dict):
            continue
        word = _clean_target(_s(w.get("word"), 60))
        if word and len(word) <= 40:
            out["words"].append({"word": word, "tr": _s(w.get("tr"), 80), "okunus": ok.okunus(word, lang) if lang not in LLM_OKUNUS else ""})
    return out


def _okunus_ok(okn: str, text: str, lang: str, tr: str = "") -> bool:
    if not ok.looks_valid(okn, text, lang):
        return False
    import unicodedata
    bare = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    src_words = len(re.findall(r"\w+", bare))
    ok_words = len(re.findall(r"\w+", okn))
    if src_words >= 3 and not (0.6 <= ok_words / src_words <= 1.7):
        return False
    if tr:
        a = set(re.findall(r"\w+", okn.lower()))
        b = set(re.findall(r"\w+", tr.lower()))
        if a and len(a & b) / len(a) >= 0.5:
            return False  # okunuş değil, Türkçe çeviri
    return True


def _repair_okunus(res: dict, lang: str) -> None:
    """İngilizce/Arapça: okunuşu hızlı modelle tek çağrıda üret; denetle; olmazsa yedek kurallar."""
    if lang not in LLM_OKUNUS:
        return
    targets: list[tuple[dict, str, str]] = []
    if res.get("reply") and not res.get("okunus"):
        targets.append((res, res["reply"], res.get("reply_tr", "")))
    if res.get("fix") and not res["fix"].get("okunus"):
        targets.append((res["fix"], res["fix"]["fixed"], res["fix"].get("fixed_tr", "")))
    for ex in res.get("examples") or []:
        if not ex.get("okunus"):
            targets.append((ex, ex["text"], ex.get("tr", "")))
    if not targets:
        return
    outs = llm_okunus_batch([t[1] for t in targets], lang)
    for (obj, text, tr), got in zip(targets, outs):
        if _okunus_ok(got, text, lang, tr):
            ok.remember(text, lang, got)
            obj["okunus"] = got
        else:
            obj["okunus"] = ok.okunus(text, lang) if lang == "en" else ""


def _speak_plan(res: dict, lang: str) -> list[dict]:
    """What to say aloud, in order (target language only — fast and clear)."""
    plan: list[str] = []
    if res.get("examples"):
        plan.append(res["examples"][0]["text"])
    else:
        if res.get("fix") and res["fix"].get("status") == "fix":
            plan.append(res["fix"]["fixed"])
        if res.get("reply"):
            plan.append(res["reply"])
    return [{"text": t[:480], "lang": lang} for t in plan if t]


_FALLBACK_REPLIES = {
    "en": [("I see! Tell me more.", "Anlıyorum! Biraz daha anlat."), ("Nice! And what about you?", "Güzel! Peki ya sen?")],
    "de": [("Ich verstehe! Erzähl mir mehr.", "Anlıyorum! Bana daha fazla anlat."), ("Schön! Und was machst du gern?", "Güzel! Peki ne yapmayı seversin?")],
    "fr": [("Je vois ! Raconte-moi plus.", "Anlıyorum! Bana daha fazla anlat."), ("Super ! Et toi, qu'est-ce que tu aimes faire ?", "Harika! Peki sen ne yapmayı seversin?")],
    "es": [("¡Entiendo! Cuéntame más.", "Anlıyorum! Bana daha fazla anlat."), ("¡Qué bien! ¿Y qué te gusta hacer?", "Ne güzel! Peki ne yapmayı seversin?")],
    "it": [("Capisco! Raccontami di più.", "Anlıyorum! Bana daha fazla anlat."), ("Che bello! E cosa ti piace fare?", "Ne güzel! Peki ne yapmayı seversin?")],
    "ru": [("Понятно! Расскажи мне больше.", "Anlıyorum! Bana daha fazla anlat."), ("Здорово! А что ты любишь делать?", "Harika! Peki ne yapmayı seversin?")],
    "ar": [("فَهِمْتُ! أَخْبِرْنِي الْمَزِيدَ.", "Anladım! Bana daha fazla anlat.")],
    "zh": [("我明白了！再多说一点。", "Anladım! Biraz daha anlat.")],
    "id": [("Saya mengerti! Ceritakan lebih banyak.", "Anlıyorum! Biraz daha anlat."), ("Bagus! Dan kamu suka melakukan apa?", "Güzel! Peki sen ne yapmayı seversin?")],
    "ka": [("გასაგებია! მეტი მომიყევი.", "Anlaşıldı! Bana daha fazla anlat."), ("კარგია! შენ რა გიყვარს?", "Güzel! Sen neyi seversin?")],
}
_TRY_IT = {"en": "Try saying it!", "de": "Versuch es mal!", "fr": "Essaie de le dire !", "es": "¡Inténtalo!",
           "it": "Prova a dirlo!", "ru": "Попробуй сказать!", "ar": "حَاوِلْ أَنْ تَقُولَهَا!", "zh": "试着说一说！",
           "ka": "სცადე თქვა!", "id": "Coba katakan!"}
_HELP_FILLER = re.compile(
    r"\b(yardım|yardim|nasıl\s+(derim|denir|söylerim|söylenir)|ne\s+demeliyim|ne\s+diyeyim|"
    r"(ingilizce|almanca|fransızca|ispanyolca|italyanca|rusça|arapça|çince|gürcüce)\s*(de|da|olarak)?|"
    r"demek\s+istiyorum|söylemek\s+istiyorum|bunu|şunu|lütfen)\b", re.I)


def _fallback_turn(user_text: str, lang: str, level: str, mode: str,
                   history: list[dict], scenario: str | None,
                   translate_fn: Callable[[str, str, str], str] | None) -> dict:
    """Yapay zekâ erişilemezse: çeviri tabanlı yardım + basit doğal devam."""
    res: dict[str, Any] = {"reply": "", "reply_tr": "", "okunus": "", "fix": None, "examples": [],
                           "explain_tr": "", "words": [], "user_level": ""}
    if mode == "help":
        phrase = re.sub(r"\s+", " ", _HELP_FILLER.sub(" ", user_text)).strip(" ,.?!")
        target = ""
        if phrase and translate_fn:
            try:
                target = _clean_target(translate_fn(phrase, "tr", lang) or "")
            except Exception:
                target = ""
        if target:
            res["examples"].append({"text": target, "tr": phrase, "okunus": ok.okunus(target, lang)})
            res["explain_tr"] = "Bu cümleyi Konuş düğmesine basılı tutup söyle."
        else:
            res["explain_tr"] = "Söylemek istediğin cümleyi Türkçe olarak tam söyle, sana karşılığını vereyim."
        res["reply"] = _TRY_IT.get(lang, "Try it!")
        res["reply_tr"] = "Söylemeyi dene!"
    else:
        if lang == "en":
            try:
                profile = ee.default_profile(lang)
                profile["currentLevel"] = level
                hist = [{"role": "user" if h.get("role") == "user" else "teacher", "text": ee.safe_str(h.get("text"))}
                        for h in (history or []) if isinstance(h, dict)]
                d = ee.process_turn(user_text, "en", "en", hist, profile, roleplay=scenario, translate_fn=translate_fn)
                res["reply"] = _clean_target(_s(d.get("teacher_en") or d.get("speak_text"), 400)).split(" 🇹🇷")[0]
                res["reply_tr"] = _s(d.get("teacher_tr"), 400)
                corr = _clean_target(_s(d.get("correction"), 300))
                if corr and not _same(corr, user_text):
                    res["fix"] = {"status": "fix", "fixed": corr, "fixed_tr": "", "okunus": ok.okunus(corr, lang),
                                  "explain_tr": _s((d.get("correction_detail") or {}).get("explainTr"), 300)}
            except Exception:
                pass
        if not res["reply"]:
            pool = _FALLBACK_REPLIES.get(lang) or _FALLBACK_REPLIES["en"]
            turn = sum(1 for h in history or [] if isinstance(h, dict) and h.get("role") == "user")
            res["reply"], res["reply_tr"] = pool[turn % len(pool)]
    res["okunus"] = ok.okunus(res["reply"], lang)
    return res


def tutor_turn(
    user_text: str,
    lang: str,
    *,
    level: str = "A1",
    mode: str = "speak",
    history: list[dict] | None = None,
    scenario: str | None = None,
    weak: list[str] | None = None,
    translate_fn: Callable[[str, str, str], str] | None = None,
    engine: str = "",
    model_override: str = "",
    on_speak: Callable[[list[dict]], None] | None = None,
) -> dict:
    t0 = time.perf_counter()
    lang = (lang or "en").split("-")[0].lower()
    if lang not in LANG_NAMES:
        lang = "en"
    level = level if level in LEVELS else "A1"
    mode = "help" if mode == "help" else "speak"
    user_text = _s(user_text, 500)
    scenario = scenario if scenario in ee.ROLEPLAYS else None
    history = history or []

    system = _system_prompt(lang, level, mode, _scenario_text(scenario, lang), weak or [])
    user_block = (
        f"CONVERSATION SO FAR:\n{_history_text(history)}\n\n"
        f"LEARNER NOW ({'Turkish, asking for help' if mode == 'help' else LANG_NAMES[lang]}): {user_text}"
    )
    parsed, provider = _call_llm(system, user_block, max_tokens=750 if lang in LLM_OKUNUS | PINYIN_LANGS else 560,
                                 engine=engine, model_override=model_override)
    if parsed:
        res = _normalize(parsed, lang, mode, user_text)
        if not res["reply"] and not res["examples"]:
            parsed = None
        else:
            if on_speak:
                try:
                    on_speak(_speak_plan(res, lang))  # sesi okunuşu beklemeden hazırlamaya başla
                except Exception:
                    pass
            _repair_okunus(res, lang)
    if not parsed:
        res = _fallback_turn(user_text, lang, level, mode, history, scenario, translate_fn)
        provider = "rules"
    res["speak"] = _speak_plan(res, lang)
    res["lang"] = lang
    res["mode"] = mode
    res["user_text"] = user_text
    res["provider"] = provider
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res


OPENERS = {
    "en": {"A1": "Hi! How are you today?", "B1": "Hey! How's your day going so far?", "C1": "Hello! What's been on your mind lately?"},
    "de": {"A1": "Hallo! Wie geht es dir heute?", "B1": "Hallo! Wie läuft dein Tag bisher?", "C1": "Hallo! Was beschäftigt dich in letzter Zeit?"},
    "fr": {"A1": "Bonjour ! Comment ça va aujourd'hui ?", "B1": "Salut ! Comment se passe ta journée ?", "C1": "Bonjour ! Qu'est-ce qui t'occupe l'esprit ces temps-ci ?"},
    "es": {"A1": "¡Hola! ¿Cómo estás hoy?", "B1": "¡Hola! ¿Qué tal va tu día?", "C1": "¡Hola! ¿Qué te ronda por la cabeza últimamente?"},
    "it": {"A1": "Ciao! Come stai oggi?", "B1": "Ciao! Come sta andando la tua giornata?", "C1": "Ciao! A cosa stai pensando ultimamente?"},
    "ru": {"A1": "Привет! Как дела?", "B1": "Привет! Как проходит твой день?", "C1": "Привет! О чём ты в последнее время думаешь?"},
    "ar": {"A1": "مَرْحَبًا! كَيْفَ حَالُكَ الْيَوْمَ؟", "B1": "أَهْلًا! كَيْفَ يَسِيرُ يَوْمُكَ؟", "C1": "أَهْلًا! مَا الَّذِي يَشْغَلُ بَالَكَ هَذِهِ الْأَيَّامَ؟"},
    "zh": {"A1": "你好！你今天好吗？", "B1": "你好！你今天过得怎么样？", "C1": "你好！最近你在想些什么呢？"},
    "id": {"A1": "Halo! Apa kabar hari ini?", "B1": "Halo! Bagaimana harimu sejauh ini?", "C1": "Halo! Apa yang sedang kamu pikirkan akhir-akhir ini?"},
    "ka": {"A1": "გამარჯობა! როგორ ხარ დღეს?", "B1": "გამარჯობა! როგორ მიდის შენი დღე?", "C1": "გამარჯობა! რაზე ფიქრობ ბოლო დროს?"},
}
OPENERS_TR = {"A1": "Merhaba! Bugün nasılsın?", "B1": "Merhaba! Günün nasıl geçiyor?", "C1": "Merhaba! Son zamanlarda aklını meşgul eden ne?"}


def greeting_turn(lang: str, level: str = "A1", scenario: str | None = None) -> dict:
    """Instant opener (no AI call)."""
    lang = (lang or "en").split("-")[0].lower()
    if lang not in LANG_NAMES:
        lang = "en"
    band = "A1" if level in ("A1", "A2") else "B1" if level in ("B1", "B2") else "C1"
    reply = OPENERS[lang][band]
    reply_tr = OPENERS_TR[band]
    rp = ee.ROLEPLAYS.get(scenario or "") if scenario else None
    if rp:
        opener = (rp.get("opener") or {}).get(lang)
        if opener:
            reply = opener
            reply_tr = f"Senaryo: {rp.get('title') or scenario}"
    okn = ok.okunus(reply, lang)
    if not okn and lang in LLM_OKUNUS:
        okn = _GREETING_OKUNUS.get(reply, "")
    res = {
        "reply": reply, "reply_tr": reply_tr, "okunus": okn,
        "fix": None, "examples": [], "explain_tr": "", "words": [], "user_level": "",
        "lang": lang, "mode": "greeting", "user_text": "", "provider": "local", "ms": 0,
    }
    res["speak"] = [{"text": reply, "lang": lang}]
    return res


_GREETING_OKUNUS = {
    "Hi! How are you today?": "Hay! Hav ar yu tıdey?",
    "Hey! How's your day going so far?": "Hey! Havz yor dey going so far?",
    "Hello! What's been on your mind lately?": "Hılou! Vats bin on yor maynd leytli?",
    "Bonjour ! Comment ça va aujourd'hui ?": "Bonjur! Koman sa va ojurdüi?",
    "Salut ! Comment se passe ta journée ?": "Salü! Koman sö pas ta jurne?",
    "Bonjour ! Qu'est-ce qui t'occupe l'esprit ces temps-ci ?": "Bonjur! Keski tokküp lespri se tan si?",
    "مَرْحَبًا! كَيْفَ حَالُكَ الْيَوْمَ؟": "Merhaben! Keyfe hâlüke'l-yevm?",
    "أَهْلًا! كَيْفَ يَسِيرُ يَوْمُكَ؟": "Ehlen! Keyfe yesîru yevmük?",
    "أَهْلًا! مَا الَّذِي يَشْغَلُ بَالَكَ هَذِهِ الْأَيَّامَ؟": "Ehlen! Me'llezî yeşğalu bâleke hâzihi'l-eyyâm?",
    "你好！你今天好吗？": ok.pinyin_okunus("Nǐ hǎo! Nǐ jīntiān hǎo ma?"),
    "你好！你今天过得怎么样？": ok.pinyin_okunus("Nǐ hǎo! Nǐ jīntiān guò de zěnmeyàng?"),
    "你好！最近你在想些什么呢？": ok.pinyin_okunus("Nǐ hǎo! Zuìjìn nǐ zài xiǎng xiē shénme ne?"),
}
for _k, _v in _GREETING_OKUNUS.items():
    for _lg in ("en", "fr", "ar", "zh"):
        ok.remember(_k, _lg, _v)



def annotate(lang: str, tutor_text: str, user_text: str = "", *, level: str = "A1", mode: str = "speak",
             translate_fn: Callable[[str, str, str], str] | None = None) -> dict:
    """Canlı (sesli) turdan sonra ekrana: öğretmen cümlesinin okunuşu + Türkçesi, öğrenci cümlesinin düzeltmesi.

    Ses zaten çalmıştır; bu bilgiler bir an sonra karta eklenir (kullanıcıyı bekletmez).
    """
    from concurrent.futures import ThreadPoolExecutor
    lang = (lang or "en").split("-")[0].lower()
    full_text = _clean_target(_s(tutor_text, 800))
    user_text = _s(user_text, 400)
    target_parts, tr_parts = split_turkish(full_text, lang)
    tutor_text = " ".join(target_parts).strip()
    hint_tr = " ".join(tr_parts).strip()
    # Sesli tekrar için sıralı parçalar: Türkçe ipucu Türkçe sesle, hedef dil kendi sesiyle
    segments = [{"text": x, "lang": "tr" if _is_turkish_sentence(x, lang) else lang}
                for x in (y.strip() for y in re.findall(r"[^.!?。！？؟]+[.!?。！？؟]*", full_text or "")) if x]
    out: dict[str, Any] = {"segments": segments, "okunus": "", "tr": "", "hint_tr": hint_tr, "target": tutor_text, "fix": None,
                           "user_level": "", "words": [], "checked": False}

    def okunus_of(text: str) -> str:
        if not text:
            return ""
        if lang in PINYIN_LANGS:
            return llm_okunus(text, lang)
        if lang in LLM_OKUNUS:
            got = llm_okunus_batch([text], lang)[0]
            return got if _okunus_ok(got, text, lang) else (ok.okunus(text, lang) if lang == "en" else "")
        return ok.okunus(text, lang)

    def do_okunus() -> str:
        return okunus_of(tutor_text)

    # Öğrencinin söylediği (hedef dilde ise) okunuşu
    user_target = " ".join(split_turkish(user_text, lang)[0]).strip() if user_text and mode != "help" else ""
    if user_target and _is_turkish_sentence(user_target, lang):
        user_target = ""

    def do_user_okunus() -> str:
        return okunus_of(user_target) if user_target else ""

    def do_tr() -> str:
        if not tutor_text or not translate_fn:
            return ""
        try:
            return _s(translate_fn(tutor_text, lang, "tr"), 800)
        except Exception:
            return ""

    def do_check() -> dict | None:
        if mode == "help" or not user_text or len(user_text) < 2:
            return None
        name = LANG_NAMES.get(lang, lang)
        system = (
            f"You are a strict but kind {name} teacher for a Turkish learner (level {level}). Check the learner sentence: "
            "verb forms/tense, auxiliaries, articles, gender, case, agreement, prepositions, word order. Ignore punctuation, "
            "capitalisation and speech-recognition filler. SPEECH-RECOGNITION RULE: the learner text comes from speech recognition. If it contains non-existent words, stray letters or fragments (e.g. 'srg') or does not form a meaningful sentence, set garbled=true, ok=true and fixed=empty (do NOT treat it as correct and do NOT invent a fix). LEVEL RULE: 'user_level' is the CEFR level the learner's OWN sentence shows (vocabulary range, tenses, subordinate clauses, idioms, fluency), NOT the lesson level and NOT correctness: a short simple phrase = A1/A2; everyday connected speech with some tenses = B1; fluent, varied, well-structured speech with connectors and abstract topics = B2/C1; sophisticated, precise, idiomatic or nuanced speech with complex clauses = C2. Never default to A1 for a fluent sentence. LANGUAGE RULE: 'explain_tr' and 'fixed_tr' MUST be written in TURKISH "
            f"(never in {name}); only the one example sentence inside explain_tr is in {name}. Write the rule itself ONLY with Turkish words "
            f"(fiil, özne, nesne, zaman, ek...), NEVER with {name} words, in the form: 'Kural cümlesi. Örnek: <example> (Türkçesi).' Return ONLY JSON: "
            '{"check": "<short analysis>", "ok": true|false, "garbled": true|false, "fixed": "<corrected sentence or empty>", '
            '"fixed_tr": "<Turkish meaning>", "how_tr": "<how to BUILD this sentence like a teacher: the pieces in order joined by ' + ', each with a Turkish label and its target-language words, e.g. Özne (Ich) + fiil (gehe) + yer (zur Schule)>", "explain_tr": "<2 short Turkish sentences: the rule, then one more correct example in the target language with its Turkish meaning in parentheses>", '
            '"user_level": "A1|A2|B1|B2|C1|C2", "words": [{"word": "<useful word from the tutor reply>", "tr": "<Turkish>"}]}'
        )
        parsed, _ = _call_llm(system, f"Tutor said: {tutor_text}\nLearner sentence: {user_text}", max_tokens=320,
                              require="ok")
        return parsed

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_ok, f_tr, f_ck = pool.submit(do_okunus), pool.submit(do_tr), pool.submit(do_check)
        f_uo = pool.submit(do_user_okunus)
        out["okunus"] = f_ok.result() or ""
        out["user_okunus"] = f_uo.result() or ""
        out["tr"] = f_tr.result() or ""
        ck = f_ck.result()
    garbled = bool(isinstance(ck, dict) and ck.get("garbled"))
    if user_target and lang in ("en", "de", "fr", "es", "it", "id"):
        # Sesli tanıma çöpü: ünlüsüz "kelime" (srg, ktb…) → doğru kabul etme
        for tok in re.findall(r"[^\W\d_]{3,}", user_target, re.U):
            if not re.search(r"[aeiouyáàâäéèêëíìîïóòôöúùûüœ]", tok.lower()):
                garbled = True
                break
    if garbled:
        out["unclear"] = True
        ck = None
    if isinstance(ck, dict):
        out["checked"] = True
        lv = _s(ck.get("user_level"), 4).upper()
        out["user_level"] = lv if lv in LEVELS else ""
        fixed = _clean_target(_s(ck.get("fixed"), 400))
        if lang == "ka" and ck.get("ok") is False and translate_fn and _s(ck.get("fixed_tr"), 300):
            # Gürcüce: modelin yazdığı cümle sık hatalı → Türkçe anlamı güvenilir çeviri hattından (yerel Gürcüce) geçir
            try:
                g = _s(translate_fn(_s(ck.get("fixed_tr"), 300), "tr", "ka"), 400)
                if g and re.search(r"[\u10A0-\u10FF]", g):
                    fixed = _clean_target(g)
            except Exception:
                pass
        if ck.get("ok") is False and fixed and not _same(fixed, user_text):
            out["fix"] = {"status": "fix", "fixed": fixed, "fixed_tr": _s(ck.get("fixed_tr"), 400),
                          "okunus": ok.okunus(fixed, lang) if lang in RULE_LANGS_LOCAL else "",
                          "explain_tr": _s(ck.get("explain_tr"), 400), "how_tr": _s(ck.get("how_tr"), 220)}
        for w in (ck.get("words") or [])[:2]:
            if isinstance(w, dict) and _s(w.get("word"), 40):
                out["words"].append({"word": _clean_target(_s(w.get("word"), 40)), "tr": _s(w.get("tr"), 60)})
    if out["fix"] and lang == "ka":
        # Gürcüce: modelin ürettiği örnek/iskelet güvenilmez → kuralı koru, örnek olarak doğrulanmış cümleyi göster
        rule = re.split(r"\s*Örnek\s*:", out["fix"].get("explain_tr") or "")[0].strip()
        ex = out["fix"]["fixed"] + (f" ({out['fix']['fixed_tr']})" if out["fix"].get("fixed_tr") else "")
        out["fix"]["explain_tr"] = (rule + " " if rule else "") + "Örnek: " + ex
        out["fix"]["how_tr"] = ""
    if out["fix"] and not out["fix"]["okunus"] and lang in LLM_OKUNUS | PINYIN_LANGS:
        out["fix"]["okunus"] = (llm_okunus_batch([out["fix"]["fixed"]], lang)[0] if lang in LLM_OKUNUS
                                else llm_okunus(out["fix"]["fixed"], lang))
        if lang in LLM_OKUNUS and not _okunus_ok(out["fix"]["okunus"], out["fix"]["fixed"], lang, out["fix"]["fixed_tr"]):
            out["fix"]["okunus"] = ok.okunus(out["fix"]["fixed"], lang) if lang == "en" else ""
    return out


RULE_LANGS_LOCAL = {"es", "it", "de", "fr", "ru", "ka", "id"}

_TR_WORDS = re.compile(
    r"\b(ve|bir|bu|şu|için|yerine|kullan\w*|geçmiş|zaman\w*|fiil\w*|cümle\w*|demek|diyoruz|söyle\w*|olur|değil|"
    r"çünkü|yani|şöyle|doğru\w*|türkçe\w*|kelime\w*|anlam\w*|ile|gibi|ama|daha|sonra|şimdi|tekrar|sonuna|başına|"
    r"ekle\w*|ekliyoruz|burada|evet|hayır|çok|iyi|güzel|harika|aferin|bravo|dikkat|kural\w*|örne\w*|hatırla\w*|bak|"
    r"mesela|sadece|başına|ifade\w*|gerek\w*|şekl\w*|nasıl|neden|niye|mı|mü|yok|sona|gelir|gider|lazım|olmalı|olarak|oluyor|"
    r"söylenir|denir|kullanılır|kullanılmaz|soru\w*|cevap\w*|dene|tekrarla|haydi|hadi|şimdiki|gelecek|çoğul|tekil|"
    r"artikel\w*|isim\w*|sıfat\w*|zamir\w*|eki|ekini|harf\w*|okunuş\w*|sesli|sessiz)\b", re.I)
_TR_SUFFIX = re.compile(r"^\w{2,}(yor|yoruz|yorsun|yorum|mak|mek|ması|mesi|ları|leri|dır|dur|dür|tır|tur|tür|sınız|siniz|"
                        r"ıyla|iyle|ndan|nden|ması|lım|lim)$", re.I)
_EN_COMMON = {"i", "you", "he", "she", "it", "we", "they", "a", "an", "the", "is", "am", "are", "was", "were", "do", "does",
              "did", "to", "of", "in", "on", "at", "for", "and", "or", "but", "what", "how", "where", "when", "why", "who",
              "my", "your", "me", "mean", "like", "have", "has", "can", "nice", "good", "great", "fine", "thank", "thanks",
              "yes", "no", "not", "with", "this", "that", "there", "here", "so", "very", "today", "go", "went", "be"}


def _is_turkish_sentence(snt: str, lang: str) -> bool:
    core = re.sub(r"[\"“”'‘’«»][^\"“”'‘’«»]{0,60}[\"“”'‘’«»]", " ", snt)  # tırnak içindeki hedef-dil örneklerini sayma
    if re.search(r"[ğışİĞŞ]", core):
        return True
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüÄÖÜäöüßéèêàâçñáíóú]+", core)
    if not words:
        return False
    if lang in ("ru", "ar", "zh", "ka"):
        latin = len(re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü]", "", core))
        allw = len(re.sub(r"\W", "", core)) or 1
        if latin < 0.6 * allw:
            return False
    tr = sum(1 for w in words if _TR_WORDS.fullmatch(w) or _TR_SUFFIX.match(w) or re.search(r"[çöüÇÖÜ]", w) and lang != "de")
    en = sum(1 for w in words if w.lower() in _EN_COMMON) if lang == "en" else 0
    return tr >= 1 and tr >= en and tr / len(words) >= 0.3


def split_turkish(text: str, lang: str) -> tuple[list[str], list[str]]:
    """Öğretmenin sesli cevabındaki Türkçe ipucu cümlelerini hedef dil cümlelerinden ayır."""
    sents = [x.strip() for x in re.findall(r"[^.!?。！？؟]+[.!?。！？؟]*", text or "") if x.strip()]
    target, tr = [], []
    for snt in sents:
        (tr if _is_turkish_sentence(snt, lang) else target).append(snt)
    if not target:
        return [text], []
    return target, tr
