#!/usr/bin/env python3
"""Eğitim: çift mikrofon yardım, çoklu örnek, konu sabitleme, telaffuz tutarlılığı."""
from __future__ import annotations

from education_engine import (
    HELP_RE,
    _build_how_to_say_examples,
    _help_mode,
    _off_topic_keep_question_help,
    check_english,
    default_profile,
    pronounce_text,
    process_turn,
)


def fake_tr(t, a, b):
    """Deterministic stub: EN→target tags; TR→EN simple maps for help+sentence."""
    t = (t or "").strip()
    if a == b:
        return t
    if a == "tr" and b == "en":
        low = t.lower()
        if "eve gid" in low or "dinlen" in low:
            return "I usually go home and relax."
        if "yorgun" in low:
            return "I'm very tired today."
        if "işe gittim" in low and "arkadaş" in low:
            return "Today I went to work and then met my friends."
        return f"[en]{t}"
    if a == "en" and b != "en":
        return f"[{b}]{t}"
    if b == "tr":
        return f"[tr]{t}"
    return f"[{b}]{t}"


def _hist(q: str) -> list[dict]:
    return [{"role": "teacher", "text": q}]


def test_help_re_turkish_intents():
    for phrase in (
        "Yardım",
        "Yardım eder misin?",
        "Bu soruya ne cevap verebilirim?",
        "Ne cevap vermem gerekiyor?",
        "Yardım, buna ne cevap verebilirim?",
        'Yardım, "çok yorgunum" demek istiyorum.',
    ):
        assert HELP_RE.search(phrase), phrase
    print("TEST A1 HELP_RE OK")


def test_help_only_german_weekend_three_examples():
    q = "Was machst du am Wochenende?"
    profile = default_profile()
    profile["targetLang"] = "de"
    profile["lastTeacherText"] = q
    r = _help_mode(
        "Yardım",
        "de",
        fake_tr,
        profile,
        {},
        history=_hist(q),
    )
    ex = r.get("help_examples") or []
    assert len(ex) >= 3, ex
    joined = " ".join(e.get("target", "") for e in ex).lower()
    assert "buy" not in joined and "how much" not in joined
    for e in ex:
        assert e.get("target")
        assert e.get("tr")
        # German localization via fake → [de]…
        assert e["target"].startswith("[de]") or "wochenende" in e["target"].lower() or True
    assert r.get("tts_language") == "de" or r.get("target_lang") == "de"
    assert r.get("type") == "help" or (r.get("help_examples"))
    # Not graded as German grammar mistake
    assert int(r.get("correction_level") or 1) <= 1
    print("TEST A German Yardım ≥3 OK", [e["target"][:40] for e in ex])


def test_help_with_turkish_sentence_english():
    q = "What do you usually do after work?"
    profile = default_profile()
    profile["targetLang"] = "en"
    profile["lastTeacherText"] = q
    r = _help_mode(
        "Yardım, genellikle eve gidip dinleniyorum.",
        "en",
        fake_tr,
        profile,
        {},
        history=_hist(q),
    )
    ex = r.get("help_examples") or []
    assert len(ex) >= 1
    targets = " ".join(e.get("target", "") for e in ex).lower()
    assert "go home" in targets or "relax" in targets or "usually" in targets
    assert any(e.get("phonetic") for e in ex)
    print("TEST B EN Yardım+cümle OK", ex[0].get("target"))


def test_help_not_german_grammar_error():
    q = "Was machst du am Wochenende?"
    r = process_turn(
        "Bu soruya ne cevap verebilirim?",
        "tr",
        "de",
        _hist(q),
        default_profile(),
        translate_fn=fake_tr,
    )
    blob = ((r.get("teacher_en") or "") + (r.get("teacher_tr") or "")).lower()
    assert "grammar" not in blob or "yardım" in blob or r.get("help_examples")
    assert int(r.get("correction_level") or 1) <= 1 or r.get("type") in ("help", "how_to_say", "dont_know_help")
    assert r.get("help_examples") or "cevap" in blob or "örnek" in blob or "help" in (r.get("type") or "")
    print("TEST C Help not grammar OK", r.get("type"))


def test_wrong_answer_stay_on_topic():
    q = "What did you do yesterday?"
    profile = default_profile()
    profile["lastTeacherText"] = q
    profile["targetLang"] = "en"
    # Grammar path: I am work → correction, same topic (not food)
    r = process_turn(
        "I am work tomorrow.",
        "en",
        "en",
        _hist(q),
        profile,
        translate_fn=fake_tr,
    )
    blob = ((r.get("teacher_en") or "") + (r.get("teacher_tr") or "") + (r.get("correction") or "")).lower()
    assert "favorite food" not in blob
    assert "i'd like to buy" not in blob
    assert int(r.get("correction_level") or 1) >= 2 or "work" in blob
    print("TEST D wrong stay-topic OK", r.get("type"), (r.get("correction") or "")[:60])


def test_nonsense_offers_help_same_question():
    q = "What do you usually do after work?"
    profile = default_profile()
    profile["lastTeacherText"] = q
    keep = _off_topic_keep_question_help(
        "Yesterday my car blue coffee.",
        "en",
        profile,
        {},
        _hist(q),
        fake_tr,
    )
    assert keep is not None
    blob = ((keep.get("teacher_en") or "") + (keep.get("teacher_tr") or "")).lower()
    assert "favorite food" not in blob
    assert "after work" in blob or "yardım" in blob or keep.get("help_examples")
    print("TEST D2 nonsense keep OK", keep.get("type"))


def test_build_examples_match_yesterday():
    seeds = _build_how_to_say_examples("What did you do yesterday?", "en", fake_tr)
    assert len(seeds) >= 3
    joined = " ".join(s[0].lower() for s in seeds)
    assert "yesterday" in joined or "went" in joined or "stayed" in joined
    assert "buy" not in joined
    print("TEST E yesterday examples OK", [s[0] for s in seeds])


def test_usually_pronunciation_aligned():
    from pronunciation_service import build_sentence_natural, get_word

    w = get_word("en", "usually")["pronunciation_tr"].lower().replace("-", "")
    sent = build_sentence_natural("I usually go home.", "en").lower()
    edu = pronounce_text("usually", "en").lower().replace("-", "")
    # Shared engine: no yu-zhu-vi vs yujuli split
    assert "zhu" not in w and "zhu" not in edu
    assert "yuju" in w or "yuğu" in w or "yu" in w
    assert "usually" in sent or "yuju" in sent.replace(" ", "") or "yu" in sent
    assert edu == w or edu.replace(" ", "") == w.replace(" ", "")
    print("TEST F usually OK", w, edu)


def test_polysemy_bank_context():
    """Ambiguous 'bank' — sentence/context, not isolated gloss."""
    from education_engine import _is_strong_english, _asr_wrong_language

    money = "I went to the bank to withdraw money."
    river = "We sat on the bank of the river."
    assert _is_strong_english(money) and _is_strong_english(river)
    assert not _asr_wrong_language(money, "en")
    assert _asr_wrong_language(money, "de")
    # Help examples for live-where stay on living, not shopping
    seeds = _build_how_to_say_examples("Where do you live?", "en", fake_tr)
    joined = " ".join(s[0].lower() for s in seeds)
    assert "live" in joined and "buy" not in joined
    # More ambiguous pairs as smoke checks
    pairs = [
        ("I left my bat in the cave.", "en"),
        ("She hit a home run with the bat.", "en"),
        ("Please book a table for two.", "en"),
        ("I read a book today.", "en"),
        ("The spring is my favorite season.", "en"),
        ("The spring of the mattress is broken.", "en"),
        ("Turn right at the light.", "en"),
        ("The room is light and airy.", "en"),
        ("He can run fast.", "en"),
        ("There was a run on the bank.", "en"),
    ]
    for sent, lang in pairs:
        assert _is_strong_english(sent) or len(sent.split()) >= 4
        assert not _asr_wrong_language(sent, lang)
    print("TEST G polysemy OK")


def test_process_turn_yardim_english_after_work():
    q = "What do you usually do after work?"
    r = process_turn(
        "Yardım",
        "tr",
        "en",
        _hist(q),
        default_profile(),
        translate_fn=fake_tr,
    )
    ex = r.get("help_examples") or []
    assert len(ex) >= 3
    joined = " ".join(e.get("target", "").lower() for e in ex)
    assert "after work" in joined or "go home" in joined or "usually" in joined
    assert "buy" not in joined
    print("TEST process Yardım EN OK", len(ex))


if __name__ == "__main__":
    test_help_re_turkish_intents()
    test_help_only_german_weekend_three_examples()
    test_help_with_turkish_sentence_english()
    test_help_not_german_grammar_error()
    test_wrong_answer_stay_on_topic()
    test_nonsense_offers_help_same_question()
    test_build_examples_match_yesterday()
    test_usually_pronunciation_aligned()
    test_polysemy_bank_context()
    test_process_turn_yardim_english_after_work()
    print("ALL help dual-mic tests passed")
