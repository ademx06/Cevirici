#!/usr/bin/env python3
"""Gemini key rotation / model hedging, accent voices, orchestrator meta."""
from __future__ import annotations

import io
import json
import threading
import time
from urllib.error import HTTPError

import education_engine as ee
from server import accent_voice


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(text: str) -> _Resp:
    return _Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())


def _http_err(code: int, body: str = "") -> HTTPError:
    return HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


def _setup(monkeypatch, fake_urlopen, keys=("bad-key", "good-key")):
    monkeypatch.setattr(ee, "urlopen", fake_urlopen)
    monkeypatch.setattr(ee, "_GEMINI_KEY_COOLDOWN", {})
    monkeypatch.setattr(ee, "_GEMINI_MODEL_COOLDOWN", {})
    monkeypatch.setattr(ee, "_GEMINI_HEDGE_SEC", 0.3)
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEYS", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", keys[0])
    if len(keys) > 1:
        monkeypatch.setenv("GEMINI_API_KEY_2", keys[1])


def _key(req) -> str:
    return dict((k.lower(), v) for k, v in req.header_items())["x-goog-api-key"]


def _body(text="hi"):
    return {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"maxOutputTokens": 20}}


def test_gemini_keys_order_and_dedupe(monkeypatch):
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", " a ")
    monkeypatch.setenv("GEMINI_API_KEY_3", "c")
    monkeypatch.setenv("GEMINI_API_KEYS", "a, d,,")
    assert ee._gemini_keys() == ["a", "c", "d"]


def test_invalid_key_rotates_to_second(monkeypatch):
    calls = []

    def fake(req, timeout=0):
        calls.append(_key(req))
        if _key(req) == "bad-key":
            raise _http_err(400, '{"error":{"status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}')
        return _ok("OK")

    _setup(monkeypatch, fake)
    assert ee._gemini_api_request(_body(), 40, timeout_sec=5) == "OK"
    assert "bad-key" in ee._GEMINI_KEY_COOLDOWN
    assert calls[-1] == "good-key"


def test_quota_429_rotates(monkeypatch):
    def fake(req, timeout=0):
        if _key(req) == "bad-key":
            raise _http_err(429, "RESOURCE_EXHAUSTED")
        return _ok("second")

    _setup(monkeypatch, fake)
    assert ee._gemini_api_request(_body(), 40, timeout_sec=5) == "second"
    assert ee._GEMINI_KEY_COOLDOWN["bad-key"] - time.time() <= 61


def test_overloaded_model_falls_back(monkeypatch):
    models = []

    def fake(req, timeout=0):
        model = req.full_url.split("/models/")[1].split(":")[0]
        models.append(model)
        if "lite" in model:
            raise _http_err(503, "UNAVAILABLE")
        payload = json.loads(req.data.decode())
        assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
        return _ok("from flash")

    _setup(monkeypatch, fake, keys=("good-key",))
    assert ee._gemini_api_request(_body(), 40, timeout_sec=5) == "from flash"
    assert models[0] == "gemini-3.5-flash-lite"
    assert "gemini-3.5-flash-lite" in ee._GEMINI_MODEL_COOLDOWN


def test_hung_model_is_hedged(monkeypatch):
    release = threading.Event()

    def fake(req, timeout=0):
        if "lite" in req.full_url:
            release.wait(5)
            return _ok("late lite")
        return _ok("fast flash")

    _setup(monkeypatch, fake, keys=("good-key",))
    t = time.time()
    try:
        assert ee._gemini_api_request(_body(), 40, timeout_sec=8) == "fast flash"
        assert time.time() - t < 2.5
        assert "gemini-3.5-flash-lite" in ee._GEMINI_MODEL_COOLDOWN
    finally:
        release.set()


def test_all_keys_fail_returns_none(monkeypatch):
    def fake(req, timeout=0):
        raise _http_err(403, "PERMISSION_DENIED")

    _setup(monkeypatch, fake)
    assert ee._gemini_api_request(_body(), 40, timeout_sec=5) is None


def test_accent_voice_matches_language_only():
    assert accent_voice("en", "en-GB") == "en-GB-SoniaNeural"
    assert accent_voice("es", "es-mx") == "es-MX-DaliaNeural"
    assert accent_voice("fr", "en-GB") is None
    assert accent_voice("en", "") is None
    assert accent_voice("en", "en-XX") is None


def test_orchestrator_meta_sanitizes():
    parsed = {
        "analysis": {"learner_level": "around b1 maybe", "emotion": "Heyecanlı{x}", "intent": "hack"},
        "voice": {"tone": "warm <b>mentor</b>"},
        "alternatives": ["I want a coffee", "I would like a coffee please", "Quiero un café, por favor.", "Me gustaría un café.", "¿Me pone un café?"],
    }
    meta = ee._orchestrator_meta(parsed, "I want a coffee", "¡Claro!", "es", "A1")
    assert meta["level"] == "B1"
    assert meta["emotion"] == "Heyecanlıx"
    assert meta["intent"] == "education"
    assert "<" not in meta["tone"]
    assert meta["alternatives"] == ["Quiero un café, por favor.", "Me gustaría un café."]


def _fake_tr(t, a, b):
    return t if a == b else f"[{b}]{t}"


def test_free_talk_is_mentor_first_when_ai_configured(monkeypatch):
    calls = []

    def fake_ai(text, *a, **k):
        calls.append(text)
        return {"teacher_en": "AI mentor reply", "profile": ee.default_profile()}

    monkeypatch.setattr(ee, "_llm_providers_in_order", lambda: ["gemini"])
    monkeypatch.setattr(ee, "_try_ai_tutor_turn", fake_ai)
    r = ee.process_turn("Yesterday I go to school", "en", "en", [], ee.default_profile(), translate_fn=_fake_tr)
    assert r["teacher_en"] == "AI mentor reply"
    assert calls == ["Yesterday I go to school"]


def test_free_talk_rules_when_ai_fails(monkeypatch):
    calls = []

    def failing_ai(text, *a, **k):
        calls.append(text)
        return None

    monkeypatch.setattr(ee, "_llm_providers_in_order", lambda: ["gemini"])
    monkeypatch.setattr(ee, "_try_ai_tutor_turn", failing_ai)
    r = ee.process_turn("Yesterday I go to school", "en", "en", [], ee.default_profile(), translate_fn=_fake_tr)
    assert "went" in (r.get("teacher_en") or "") + (r.get("correction") or "")
    assert len(calls) == 1


def test_ai_one_word_correction_is_kept():
    parsed = {
        "teacher_en": "Oh, the cinema! What did you watch?",
        "correct_phrase": "Yesterday I went to the cinema.",
        "correction_level": 2,
    }
    out = ee._sanitize_ai_correction("Yesterday I go to the cinema", parsed, "en")
    assert out["correct_phrase"] == "Yesterday I went to the cinema."
    assert out["correction_level"] >= 2
    assert out["teacher_en"] == "Oh, the cinema! What did you watch?"


def test_identical_ai_correction_is_dropped():
    parsed = {"teacher_en": "Nice!", "correct_phrase": "I live in Bursa.", "correction_level": 2}
    out = ee._sanitize_ai_correction("I live in Bursa", parsed, "en")
    assert out["correct_phrase"] is None
    assert out["correction_level"] == 1


def test_missed_error_gets_gentle_fix_not_template():
    parsed = {"teacher_en": "Oh, the cinema! What did you watch?", "correction_level": 1}
    out = ee._sanitize_ai_correction("Yesterday I go to the cinema", parsed, "en")
    assert out["correction_level"] >= 2
    assert out["teacher_en"].startswith("Small fix: **")
    assert "What did you watch?" in out["teacher_en"]
    assert "There is a mistake" not in out["teacher_en"]


def test_orchestrator_meta_defaults():
    meta = ee._orchestrator_meta({}, "hi", "Hello!", "en", "A2")
    assert meta == {"level": "A2", "emotion": "", "intent": "education", "tone": "", "alternatives": []}
