"""Cümle Kur + Kendini Test Et — kelime/cümle üretimi, yapılandırılmış analiz, telaffuz."""
from __future__ import annotations

APP_VERSION = "2026.09.02-v40"

import difflib
import json
import re
from typing import Any, Callable

from education_engine import (
    LANG_NAMES,
    _analyze_for_teaching,
    _llm_json,
    _rule_natural_translate_tr,
    check_english,
    llm_available,
    safe_str,
)
from pronunciation_service import (
    apply_pronunciation_to_example,
    build_pronunciation_bundle,
    enrich_pattern_examples,
    get_word,
    register_word,
    strip_teaching_header,
)
from word_teaching_engine import (
    ENGLISH_VARIANT,
    SENTENCE_TEACHING_V3_PROMPT,
    ai_only_lesson_enabled,
    analyze_word_profile,
    build_rule_examples_for_word,
    build_usage_from_profile,
    collect_lesson_quality_issues,
    detect_category,
    generate_examples_from_profile,
    rule_sentence_teaching,
    build_rich_word_explanation,
    resolve_target_word,
    sanitize_word_examples,
    validate_lesson_quality,
    word_icon_for,
    guarantee_word_lesson,
    try_ai_word_lesson,
    templates_allowed,
    upgrade_word_lesson_teaching,
    _rule_word_profile,
)
# ── Yasak / şablon açıklamalar ──
GENERIC_BANNED_RE = re.compile(
    r"günlük konuşmada kullan|kelime(?:yi)? günlük|bu cümlede .+ kelimesini|"
    r"anlamsız tekrar|template|placeholder",
    re.I,
)

WORD_LESSON_V2_PROMPT = """DEPRECATED — word_teaching_engine kullanılır."""

SENTENCE_ANALYSIS_V2_PROMPT = """DEPRECATED — SENTENCE_TEACHING_V3_PROMPT kullanılır."""

PRONUNCIATION_JSON_PROMPT = """You are a pronunciation coach for Turkish speakers learning {lang_name}.
Analyze SPOKEN sound — NOT English spelling letter-by-letter.

Text: "{text}"

Rules for pronunciation_tr (Turkish Latin letters, readable by Turks):
- Base on actual sounds: don't→dont, like→layk, coffee→kofi/kawfi, I→ay, you→yu
- Do NOT produce: du u vant kofii, du dont layk kofee
- Natural connected speech, not robotic spelling
- Silent letters omitted in pronunciation_tr

Return JSON only:
{{
  "pronunciation_tr": "full sentence",
  "ipa": "IPA with slashes",
  "words": [{{"word":"...","pronunciation_tr":"...","ipa":"..."}}]
}}"""

GRADE_WORD_JSON_PROMPT = """Grade a language learner's spoken answer for a WORD practice task.
Target language: {lang_name} ({target_lang})
Turkish word prompt: "{word_tr}"
Expected focus word: "{target_word}"
Student said (from STT): "{user_answer}"

IMPORTANT — PRONUNCIATION:
STT only shows if words were recognized, NOT perfect pronunciation.
If you cannot verify real phonetic scoring, set pronunciation_ok=null or use cautious wording.
In feedback_tr mention when pronunciation assessment is limited: "Cümle doğru algılandı; telaffuz değerlendirmesi sınırlı olabilir."

Evaluate MEANING, GRAMMAR, VOCABULARY, NATURALNESS. Score weights: meaning 30%, grammar 25%, vocabulary 15%, pronunciation 20%, naturalness 10%.
Accept natural alternatives.

Return JSON with score, feedback_tr, why_tr, pronunciation_note_tr (honest about STT limits)."""

GRADE_SENTENCE_JSON_PROMPT = """Grade spoken translation. STT text: "{user_answer}"
Turkish: "{tr_sentence}" Expected: "{expected_target}" Alternatives: {alternatives}

PRONUNCIATION: Do not claim perfect pronunciation from STT match alone. Be honest in pronunciation_note_tr.

Score weights: meaning 30%, grammar 25%, vocabulary 15%, pronunciation 20%, naturalness 10%.
Return JSON with scores and Turkish feedback."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", safe_str(text).strip().lower())


def _word_in_sentence(word: str, sentence: str) -> bool:
    w = _norm(word)
    s = _norm(sentence)
    if not w or not s:
        return False
    return w in s.split() or w in s


def _compute_weighted_score(scores: dict[str, int]) -> int:
    weights = {"meaning": 0.30, "grammar": 0.25, "vocabulary": 0.15, "pronunciation": 0.20, "naturalness": 0.10}
    total = sum((scores.get(k, 0) / 100.0) * w for k, w in weights.items())
    return max(0, min(100, round(total * 100)))


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _is_generic_explanation(text: str) -> bool:
    t = safe_str(text).strip()
    if len(t) < 20:
        return True
    if GENERIC_BANNED_RE.search(t):
        return True
    return False


def _dedupe_explanations(examples: list[dict[str, Any]]) -> bool:
    """True if explanations are sufficiently unique."""
    texts = [_norm(ex.get("how_it_is_formed_tr") or ex.get("explanation_tr") or "") for ex in examples]
    texts = [t for t in texts if t]
    if len(texts) < 2:
        return len(texts) == 1
    unique = len(set(texts))
    return unique >= max(2, len(texts) * 0.7)


def _rule_pronunciation_en(text: str) -> dict[str, Any]:
    """Geriye dönük uyumluluk."""
    return build_pronunciation_bundle(text, "en")


def _pronunciation_bundle(
    text: str,
    target_lang: str,
    focus_words: list[str] | None = None,
) -> dict[str, Any]:
    text = safe_str(text).strip()
    if not text:
        return {"pronunciation_tr": "", "ipa": "", "word_pronunciations": []}
    return build_pronunciation_bundle(text, target_lang, focus_words)


# ── Can you + fiil + nesne kalıbı — zengin örnek kütüphanesi ──
CAN_YOU_PATTERN_EXAMPLES: list[dict[str, str]] = [
    {"tr": "Kapıyı açabilir misin?", "target": "Can you open the door?"},
    {"tr": "Bana yardım edebilir misin?", "target": "Can you help me?"},
    {"tr": "Pencereyi kapatabilir misin?", "target": "Can you close the window?"},
    {"tr": "Bana biraz su getirebilir misin?", "target": "Can you bring me some water?"},
    {"tr": "Bana bunu gösterebilir misin?", "target": "Can you show me this?"},
    {"tr": "Bana bir kalem verebilir misin?", "target": "Can you give me a pen?"},
    {"tr": "Buraya gelebilir misin?", "target": "Can you come here?"},
    {"tr": "Bir dakika bekleyebilir misin?", "target": "Can you wait a minute?"},
    {"tr": "Bana bunu açıklayabilir misin?", "target": "Can you explain this to me?"},
    {"tr": "Rezervasyon yapabilir misin?", "target": "Can you make a reservation?"},
    {"tr": "Kapıyı açabilir misiniz?", "target": "Could you open the door?"},
    {"tr": "Bana bir kahve getirebilir misin?", "target": "Can you bring me a coffee?"},
]


def _is_can_you_pattern(parsed: dict[str, Any], tr_sentence: str) -> bool:
    target = safe_str(parsed.get("target_sentence")).lower()
    pattern = safe_str(parsed.get("pattern_tr")).lower()
    tr = safe_str(tr_sentence).lower()
    if target.startswith("can you") or target.startswith("could you"):
        return True
    if "can you" in pattern or "could you" in pattern:
        return True
    if re.search(r"(?:ebilir|abilir)\s+misin", tr):
        return True
    return False


def _supplement_can_you_patterns(
    parsed: dict[str, Any],
    tr_sentence: str,
    target_lang: str,
) -> None:
    if target_lang != "en" or not _is_can_you_pattern(parsed, tr_sentence):
        return
    if not safe_str(parsed.get("pattern_tr")).strip():
        parsed["pattern_tr"] = "Can you + verb + object?"
    existing = parsed.get("pattern_examples") or []
    if isinstance(existing, list) and len(existing) >= 8:
        return
    seen = {_norm(safe_str(e.get("target") if isinstance(e, dict) else e)) for e in existing}
    merged: list[dict[str, str]] = []
    for item in existing:
        if isinstance(item, dict) and item.get("target"):
            merged.append({"tr": safe_str(item.get("tr")), "target": safe_str(item["target"])})
        elif isinstance(item, str) and item.strip():
            merged.append({"tr": "", "target": item.strip()})
    for ex in CAN_YOU_PATTERN_EXAMPLES:
        key = _norm(ex["target"])
        if key not in seen:
            merged.append(dict(ex))
            seen.add(key)
    parsed["pattern_examples"] = merged[:12]


def _merge_teaching_fields(ex: dict[str, Any]) -> dict[str, Any]:
    """Eski alan adlarını yeni şemaya map et."""
    out = dict(ex)
    if not out.get("how_it_is_formed_tr"):
        out["how_it_is_formed_tr"] = safe_str(out.get("explanation_tr")).strip()
    out["how_it_is_formed_tr"] = strip_teaching_header(out.get("how_it_is_formed_tr") or "")
    if not out.get("structure_tr") and out.get("structure"):
        out["structure_tr"] = out["structure"]
    parts = out.get("word_breakdown") or out.get("parts") or []
    if isinstance(parts, list):
        clean: list[dict[str, str]] = []
        for p in parts:
            if not isinstance(p, dict):
                continue
            token = safe_str(p.get("token") or p.get("tr")).strip()
            if token:
                clean.append({
                    "token": token,
                    "role_tr": safe_str(p.get("role_tr")).strip(),
                    "meaning_tr": safe_str(p.get("meaning_tr")).strip(),
                })
        out["word_breakdown"] = clean
    return out


def _enrich_example(
    ex: dict[str, Any],
    target_lang: str,
    focus_words: list[str] | None = None,
    known_words: set[str] | None = None,
) -> dict[str, Any]:
    ex = _merge_teaching_fields(ex)
    focus = [w for w in (focus_words or []) if safe_str(w).strip()]
    ex = apply_pronunciation_to_example(ex, target_lang, focus)
    pats = ex.get("pattern_examples") or []
    if pats:
        ex["pattern_examples"] = enrich_pattern_examples(pats, target_lang, focus, known_words)
    return ex


def _validate_example(ex: dict[str, Any]) -> bool:
    target = safe_str(ex.get("target")).strip()
    how = safe_str(ex.get("how_it_is_formed_tr")).strip()
    if not target or not how:
        return False
    if _is_generic_explanation(how):
        return False
    if not ex.get("structure_tr") and not ex.get("word_breakdown"):
        return False
    return True


def _rule_based_word_lesson(
    word_tr: str,
    target_word: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> list[dict[str, Any]]:
    """Kelime profiline göre doğal örnekler — şablon kopyalama yok."""
    profile = analyze_word_profile(word_tr, target_word, target_lang, translate_fn)
    raw = build_rule_examples_for_word(word_tr, target_word, profile)
    known: set[str] = {target_word.lower()}
    examples: list[dict[str, Any]] = []
    for ex in raw:
        enriched = _enrich_example(ex, target_lang, [target_word], known)
        if _validate_example(enriched):
            examples.append(enriched)
    return examples


def _apply_quality_word_lesson_fallbacks(
    word_tr: str,
    target_word: str,
    target_lang: str,
    profile: dict[str, Any],
    examples: list[dict[str, Any]],
    translate_fn: Callable[[str, str, str], str] | None,
    known_words: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """AI yetersiz veya API kapalıyken doğal kategori kalıplarıyla dersi tamamla."""
    category = detect_category(word_tr, target_word)

    if len(examples) < 13:
        raw_examples = generate_examples_from_profile(profile, word_tr, target_word, target_lang)
        for ex in raw_examples:
            enriched = _enrich_example(ex, target_lang, [target_word], known_words)
            if _validate_example(enriched):
                examples.append(enriched)

    if not validate_lesson_quality(examples, word_tr, target_word, profile):
        rule_examples = _rule_based_word_lesson(word_tr, target_word, target_lang, translate_fn)
        if len(rule_examples) > len(examples):
            examples = rule_examples

    examples = sanitize_word_examples(examples, word_tr, target_word, profile, translate_fn)

    if len(examples) < 13:
        category = detect_category(word_tr, target_word)
        profile = _rule_word_profile(word_tr, target_word, target_lang, category)
        fallback = sanitize_word_examples(
            build_rule_examples_for_word(word_tr, target_word, profile),
            word_tr,
            target_word,
            profile,
            translate_fn,
        )
        if len(fallback) > len(examples):
            examples = fallback

    profile, examples, category = guarantee_word_lesson(
        word_tr, target_word, target_lang, profile, examples, translate_fn, ai_only=False,
    )
    return profile, examples, category


def generate_word_lesson(
    word_tr: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    word_tr = safe_str(word_tr).strip()
    if len(word_tr) < 2:
        return {"ok": False, "error_tr": "En az 2 harfli bir kelime gir."}

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    target_word = ""
    if translate_fn:
        try:
            target_word = translate_fn(word_tr, "tr", target_lang).strip()
        except Exception:
            target_word = ""
    if not target_word and translate_fn:
        try:
            target_word = translate_fn(word_tr, "tr", target_lang).strip()
        except Exception:
            target_word = word_tr
    target_word = safe_str(target_word).strip() or word_tr
    target_word = resolve_target_word(word_tr, target_word, target_lang)
    if target_lang == "en":
        target_word = target_word.lower()

    if target_lang == "en":
        tw_info = get_word("en", target_word)
        register_word("en", target_word, tw_info["pronunciation_tr"], tw_info.get("ipa", ""))

    profile = analyze_word_profile(word_tr, target_word, target_lang, translate_fn)
    known_words = {target_word.lower()}
    examples: list[dict[str, Any]] = []
    category = detect_category(word_tr, target_word)
    ai_only = ai_only_lesson_enabled(target_lang)
    ai_issues: list[str] = []

    if llm_available() and target_lang == "en":
        ai_profile, ai_examples, ai_issues = try_ai_word_lesson(
            word_tr, target_word, target_lang, profile,
        )
        if ai_examples:
            profile = ai_profile
            for ex in ai_examples:
                enriched = _enrich_example(ex, target_lang, [target_word], known_words)
                if _validate_example(enriched):
                    examples.append(enriched)
            examples = sanitize_word_examples(examples, word_tr, target_word, profile, translate_fn)

    if ai_only:
        profile, examples, category = guarantee_word_lesson(
            word_tr, target_word, target_lang, profile, examples, translate_fn, ai_only=True,
        )
        quality_issues = collect_lesson_quality_issues(examples, word_tr, target_word, profile)
        if len(examples) < 11 or quality_issues:
            if len(examples) < 11 or quality_issues:
                profile, examples, category = _apply_quality_word_lesson_fallbacks(
                    word_tr, target_word, target_lang, profile, examples, translate_fn, known_words,
                )
                quality_issues = collect_lesson_quality_issues(examples, word_tr, target_word, profile)
            if templates_allowed() and (len(examples) < 11 or quality_issues):
                profile, examples, category = _apply_quality_word_lesson_fallbacks(
                    word_tr, target_word, target_lang, profile, examples, translate_fn, known_words,
                )
            elif len(examples) < 7:
                issue_hint = quality_issues[0] if quality_issues else "yetersiz örnek"
                return {
                    "ok": False,
                    "error_tr": (
                        f"«{word_tr}» için AI dersi şu an tamamlanamadı. "
                        "Lütfen birkaç saniye sonra tekrar dene."
                    ),
                    "ai_retry": True,
                    "debug_issue": issue_hint[:120],
                }
    else:
        profile, examples, category = _apply_quality_word_lesson_fallbacks(
            word_tr, target_word, target_lang, profile, examples, translate_fn, known_words,
        )

    examples = upgrade_word_lesson_teaching(examples, word_tr, target_word, profile)

    tw_pron = get_word(target_lang, target_word)
    usage = build_usage_from_profile(profile, target_lang, target_word, word_tr)
    if profile.get("regional_variants"):
        usage["regional_variants"] = profile["regional_variants"]
    word_explanation = build_rich_word_explanation(word_tr, target_word, profile)

    return {
        "ok": True,
        "word_tr": word_tr,
        "target_lang": target_lang,
        "target_word": target_word,
        "word_icon": word_icon_for(word_tr, target_word, category),
        "app_version": APP_VERSION,
        "pronunciation_tr": tw_pron["pronunciation_tr"],
        "ipa": tw_pron.get("ipa", ""),
        "word_profile": {
            "part_of_speech": profile.get("part_of_speech"),
            "countability": profile.get("countability"),
            "semantic_category": profile.get("semantic_category"),
            "meaning_tr": profile.get("meaning_tr"),
        },
        "word_explanation_tr": word_explanation,
        "english_variant": ENGLISH_VARIANT,
        "usage": usage,
        "examples": examples[:13],
    }


def _analyze_sentence_structured(
    tr_sentence: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    lang_name = LANG_NAMES.get(target_lang, target_lang)

    parsed: dict[str, Any] | None = None
    if llm_available():
        system = SENTENCE_TEACHING_V3_PROMPT.format(
            tr_sentence=tr_sentence[:400],
            lang_name=lang_name,
            target_lang=target_lang,
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=1400)

    if not parsed or not parsed.get("target_sentence"):
        parsed = rule_sentence_teaching(tr_sentence, target_lang, translate_fn)

    if not parsed or not parsed.get("target_sentence"):
        return None

    how = strip_teaching_header(safe_str(parsed.get("how_it_is_formed_tr")).strip())
    if _is_generic_explanation(how) and len(how) < 80:
        return None

    target = safe_str(parsed["target_sentence"]).strip()
    bundle = _pronunciation_bundle(target, target_lang)
    parsed["target_sentence"] = target
    parsed["how_it_is_formed_tr"] = how
    parsed["pronunciation_tr"] = bundle["pronunciation_tr"]
    parsed["ipa"] = bundle.get("ipa") or parsed.get("ipa") or ""
    parsed["word_pronunciations"] = bundle["word_pronunciations"]
    focus = [w.get("token", "") for w in (parsed.get("word_breakdown") or []) if isinstance(w, dict)]
    _supplement_can_you_patterns(parsed, tr_sentence, target_lang)
    pat_max = 12 if _is_can_you_pattern(parsed, tr_sentence) else 4
    parsed["pattern_examples"] = enrich_pattern_examples(
        parsed.get("pattern_examples") or [], target_lang, focus, max_examples=pat_max,
    )
    # new_words telaffuz zenginleştir
    nw = parsed.get("new_words") or []
    if isinstance(nw, list):
        enriched_nw: list[dict[str, str]] = []
        for item in nw:
            if isinstance(item, dict) and item.get("word"):
                info = get_word(target_lang, item["word"])
                enriched_nw.append({
                    **item,
                    "pronunciation_tr": info.get("pronunciation_tr", ""),
                    "ipa": info.get("ipa", ""),
                })
        parsed["new_words"] = enriched_nw
    parsed["grammar_explanation_tr"] = how
    parsed["why_tr"] = safe_str(parsed.get("why_this_structure_tr")).strip() or how
    return parsed


def analyze_sentence_for_builder(
    tr_sentence: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    tr_sentence = safe_str(tr_sentence).strip()
    if len(tr_sentence) < 4:
        return {"ok": False, "error_tr": "En az 4 karakterli bir cümle gir."}

    structured = _analyze_sentence_structured(tr_sentence, target_lang, translate_fn)
    if structured:
        chunks = structured.get("pronunciation_chunks") or []
        if not chunks and structured.get("target_sentence"):
            target = structured["target_sentence"]
            parts = re.split(r"([,;])", target)
            buf = ""
            for p in parts:
                buf += p
                if len(buf.split()) >= 3 or p.strip() in (",", ";"):
                    seg = buf.strip(" ,;")
                    if seg:
                        b = _pronunciation_bundle(seg, target_lang)
                        chunks.append({
                            "target": seg,
                            "pronunciation_tr": b["pronunciation_tr"],
                            "ipa": b.get("ipa", ""),
                        })
                    buf = ""
        return {
            "ok": True,
            "tr_sentence": tr_sentence,
            "target_lang": target_lang,
            **structured,
            "phrase_pairs": [
                {"tr": w.get("meaning_tr", ""), "en": w.get("token", "")}
                for w in (structured.get("word_breakdown") or [])
                if isinstance(w, dict)
            ],
            "structure_tr": structured.get("structure_tr") or structured.get("structure_label_tr", ""),
            "pronunciation_chunks": chunks,
        }

    analysis = _analyze_for_teaching(tr_sentence, target_lang, translate_fn)
    natural = safe_str(analysis.get("natural_target")).strip()
    if not natural:
        natural = _rule_natural_translate_tr(tr_sentence, target_lang, translate_fn)

    bundle = _pronunciation_bundle(natural, target_lang)
    pairs = analysis.get("phrase_pairs") or []
    structure = safe_str(analysis.get("important_structure_tr")).strip()
    analysis_tr = strip_teaching_header(safe_str(analysis.get("analysis_tr")).strip())

    return {
        "ok": True,
        "tr_sentence": tr_sentence,
        "target_lang": target_lang,
        "target_sentence": natural,
        "pronunciation_tr": bundle["pronunciation_tr"],
        "ipa": bundle["ipa"],
        "word_pronunciations": bundle["word_pronunciations"],
        "alternatives": (analysis.get("alternatives") or [])[:3],
        "grammar_explanation_tr": analysis_tr,
        "how_it_is_formed_tr": analysis_tr,
        "structure_tr": structure,
        "phrase_pairs": pairs,
        "why_tr": analysis_tr,
        "pronunciation_chunks": [],
    }


def _apply_honest_pronunciation(result: dict[str, Any]) -> dict[str, Any]:
    """STT tabanlı değerlendirmede telaffuz iddiasını yumuşat."""
    note = safe_str(result.get("pronunciation_note_tr")).strip()
    if not note:
        result["pronunciation_note_tr"] = (
            "Cümle metin olarak algılandı. Telaffuz değerlendirmesi sınırlı olabilir — "
            "🔊 butonundan doğru telaffuzu dinleyerek karşılaştır."
        )
    if result.get("pronunciation_ok") is True and not result.get("pronunciation_verified"):
        result["pronunciation_ok"] = None
        result["pronunciation_cautious"] = True
    return result


def _rule_grade(
    user_answer: str,
    correct_answer: str,
    target_word: str | None = None,
    alternatives: list[str] | None = None,
    target_lang: str = "en",
) -> dict[str, Any]:
    user = safe_str(user_answer).strip()
    correct = safe_str(correct_answer).strip()
    alts = [a for a in (alternatives or []) if safe_str(a).strip()]
    all_valid = [correct] + alts

    best_sim = max((_similarity(user, v) for v in all_valid if v), default=0.0)
    meaning_ok = best_sim >= 0.72
    grammar_ok = True
    vocab_ok = True
    why_tr = ""

    if target_word and not _word_in_sentence(target_word, user):
        vocab_ok = False
        why_tr = f"Cümlende '{target_word}' kelimesini kullanmalısın."

    if target_lang == "en":
        checked = check_english(user)
        level = checked[0] if checked else 1
        fixed = checked[1] if len(checked) > 1 else None
        cat = checked[2] if len(checked) > 2 else None
        ex_tr = checked[4] if len(checked) > 4 else None
        if level >= 2 and fixed:
            grammar_ok = False
            if not why_tr:
                why_tr = ex_tr or f"Gramer hatası: {cat or 'düzeltme gerekli'}. Doğrusu: {fixed}"

    scores = {
        "meaning": 95 if meaning_ok else max(20, int(best_sim * 100)),
        "grammar": 90 if grammar_ok else 40,
        "vocabulary": 90 if vocab_ok else 35,
        "pronunciation": 70,
        "naturalness": 85 if meaning_ok else 50,
    }
    score = _compute_weighted_score(scores)

    result = {
        "sentence_ok": meaning_ok and grammar_ok,
        "grammar_ok": grammar_ok,
        "vocabulary_ok": vocab_ok,
        "pronunciation_ok": None,
        "naturalness_ok": meaning_ok,
        "meaning_score": scores["meaning"],
        "grammar_score": scores["grammar"],
        "vocabulary_score": scores["vocabulary"],
        "pronunciation_score": scores["pronunciation"],
        "naturalness_score": scores["naturalness"],
        "score": score,
        "user_answer": user,
        "correct_answer": correct,
        "alternatives_accepted": alts[:2],
        "feedback_tr": "✅ İyi gidiyorsun!" if score >= 80 else "⚠️ Biraz daha pratik yap.",
        "why_tr": why_tr or ("Cümlen anlam olarak doğru." if meaning_ok else "Anlam biraz farklı veya eksik."),
        "pronunciation_issues": [],
        "pronunciation_note_tr": "Telaffuz değerlendirmesi sınırlı — STT yalnızca kelime algısını gösterir.",
    }
    return _apply_honest_pronunciation(result)


def grade_word_answer(
    word_tr: str,
    target_word: str,
    user_answer: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    user_answer = safe_str(user_answer).strip()
    if len(user_answer) < 2:
        return {"ok": False, "error_tr": "Konuşman algılanamadı — tekrar dene."}

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    if llm_available():
        system = GRADE_WORD_JSON_PROMPT.format(
            lang_name=lang_name,
            target_lang=target_lang,
            word_tr=word_tr[:80],
            target_word=target_word[:80],
            user_answer=user_answer[:300],
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=520)
        if parsed and "score" in parsed:
            scores = {
                "meaning": int(parsed.get("meaning_score") or 0),
                "grammar": int(parsed.get("grammar_score") or 0),
                "vocabulary": int(parsed.get("vocabulary_score") or 0),
                "pronunciation": int(parsed.get("pronunciation_score") or 0),
                "naturalness": int(parsed.get("naturalness_score") or 0),
            }
            parsed["score"] = parsed.get("score") or _compute_weighted_score(scores)
            parsed["ok"] = True
            return _apply_honest_pronunciation(parsed)

    example_correct = f"I love {target_word}."
    if translate_fn:
        try:
            example_correct = translate_fn(f"{word_tr} seviyorum.", "tr", target_lang)
        except Exception:
            pass

    result = _rule_grade(user_answer, example_correct, target_word=target_word, target_lang=target_lang)
    result["ok"] = True
    return result


def grade_sentence_answer(
    tr_sentence: str,
    expected_target: str,
    user_answer: str,
    target_lang: str,
    alternatives: list[str] | None = None,
) -> dict[str, Any]:
    user_answer = safe_str(user_answer).strip()
    if len(user_answer) < 2:
        return {"ok": False, "error_tr": "Konuşman algılanamadı — tekrar dene."}

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    alts = alternatives or []

    if llm_available():
        system = GRADE_SENTENCE_JSON_PROMPT.format(
            lang_name=lang_name,
            target_lang=target_lang,
            tr_sentence=tr_sentence[:300],
            expected_target=expected_target[:300],
            alternatives=json.dumps(alts[:5], ensure_ascii=False),
            user_answer=user_answer[:300],
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=520)
        if parsed and "score" in parsed:
            scores = {
                "meaning": int(parsed.get("meaning_score") or 0),
                "grammar": int(parsed.get("grammar_score") or 0),
                "vocabulary": int(parsed.get("vocabulary_score") or 0),
                "pronunciation": int(parsed.get("pronunciation_score") or 0),
                "naturalness": int(parsed.get("naturalness_score") or 0),
            }
            parsed["score"] = parsed.get("score") or _compute_weighted_score(scores)
            parsed["ok"] = True
            return _apply_honest_pronunciation(parsed)

    result = _rule_grade(user_answer, expected_target, alternatives=alts, target_lang=target_lang)
    result["ok"] = True
    return result


def learning_level_from_stats(stats: dict[str, Any]) -> str:
    attempts = int(stats.get("attempts") or 0)
    if attempts < 2:
        return "🟡 Geliştirilmeli"
    avg = float(stats.get("avgScore") or 0)
    if avg >= 85:
        return "🟢 İyi"
    if avg >= 60:
        return "🟡 Geliştirilmeli"
    return "🔴 Tekrar edilmeli"


def srs_weight(stats: dict[str, Any]) -> float:
    attempts = int(stats.get("attempts") or 0)
    wrong = int(stats.get("wrong") or 0)
    avg = float(stats.get("avgScore") or 50)
    pron = float(stats.get("pronunciationAvg") or 70)
    if attempts == 0:
        return 2.0
    error_rate = wrong / max(attempts, 1)
    weight = 1.0 + error_rate * 2.0 + (100 - avg) / 50.0 + (100 - pron) / 80.0
    if avg >= 90 and attempts >= 5:
        weight *= 0.4
    return max(0.2, weight)
