"""Cümle Kur + Kendini Test Et — kelime/cümle üretimi ve değerlendirme motoru."""
from __future__ import annotations

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
    pronounce_text,
    safe_str,
)

WORD_LESSON_JSON_PROMPT = """You are a Turkish-speaking language teacher helping a student learn {lang_name}.
The student entered a Turkish WORD: "{word_tr}"
Create a rich lesson in JSON only.

Requirements:
- Generate 6-10 example sentences using the word in DIFFERENT contexts (question, negative, request, daily talk, past/present/future where natural).
- Do NOT repeat the same sentence pattern.
- Explain like the student knows ZERO {lang_name}.
- Turkish phonetic pronunciation for each target sentence (readable with Turkish letters, NOT IPA).
- For each example include: tr, target, pronunciation_tr, sentence_type, explanation_tr, structure_tr, parts (array of {{tr, meaning_tr}}).

Return JSON:
{{
  "target_word": "word in {lang_name}",
  "word_explanation_tr": "brief Turkish explanation of the word",
  "usage": {{
    "noun_tr": "...", "verb_tr": null or "...", "adjective_tr": null or "...",
    "formal_tr": "...", "informal_tr": "...",
    "patterns": ["have coffee", "drink coffee"],
    "common_mistakes_tr": "..."
  }},
  "examples": [
    {{
      "tr": "Turkish sentence",
      "target": "{lang_name} sentence",
      "pronunciation_tr": "Turkish-style phonetic",
      "sentence_type": "question|negative|request|daily|past|present|future",
      "explanation_tr": "why and how, for zero-knowledge learner",
      "structure_tr": "Can + I + have + a coffee?",
      "parts": [{{"tr": "Can", "meaning_tr": "-ebilir miyim?"}}]
    }}
  ]
}}"""

GRADE_WORD_JSON_PROMPT = """Grade a language learner's spoken answer for a WORD practice task.
Target language: {lang_name} ({target_lang})
Turkish word prompt: "{word_tr}"
Expected focus word in {lang_name}: "{target_word}"
Student said: "{user_answer}"

Evaluate MEANING, GRAMMAR, VOCABULARY (word used correctly), PRONUNCIATION (guess from spelling/STT), NATURALNESS.
Accept natural alternatives — not exact string match.
If grammar correct but pronunciation likely wrong, flag pronunciation separately.

Score weights: meaning 30%, grammar 25%, vocabulary 15%, pronunciation 20%, naturalness 10%.
Return integer score 0-100 computed from these.

Return JSON:
{{
  "sentence_ok": bool, "grammar_ok": bool, "vocabulary_ok": bool,
  "pronunciation_ok": bool, "naturalness_ok": bool,
  "meaning_score": 0-100, "grammar_score": 0-100, "vocabulary_score": 0-100,
  "pronunciation_score": 0-100, "naturalness_score": 0-100, "score": 0-100,
  "user_answer": "...", "correct_answer": "best natural sentence",
  "alternatives_accepted": ["..."],
  "feedback_tr": "teacher-style Turkish feedback",
  "why_tr": "explain errors simply in Turkish",
  "pronunciation_issues": [{{"word": "...", "hint_tr": "Turkish phonetic"}}]
}}"""

GRADE_SENTENCE_JSON_PROMPT = """Grade a language learner's spoken translation.
Target language: {lang_name} ({target_lang})
Turkish source: "{tr_sentence}"
Expected translation: "{expected_target}"
Known alternatives: {alternatives}
Student said: "{user_answer}"

Accept semantically equivalent natural alternatives. Compare tense, meaning, grammar.
Explain mistakes like a patient teacher in Turkish.

Score weights: meaning 30%, grammar 25%, vocabulary 15%, pronunciation 20%, naturalness 10%.

Return JSON:
{{
  "sentence_ok": bool, "grammar_ok": bool, "vocabulary_ok": bool,
  "pronunciation_ok": bool, "naturalness_ok": bool,
  "meaning_score": 0-100, "grammar_score": 0-100, "vocabulary_score": 0-100,
  "pronunciation_score": 0-100, "naturalness_score": 0-100, "score": 0-100,
  "user_answer": "...", "correct_answer": "...",
  "alternatives_accepted": ["..."],
  "feedback_tr": "...",
  "why_tr": "...",
  "pronunciation_issues": [{{"word": "...", "hint_tr": "..."}}],
  "tense_note_tr": "optional note about tense mismatch"
}}"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", safe_str(text).strip().lower())


def _word_in_sentence(word: str, sentence: str) -> bool:
    w = _norm(word)
    s = _norm(sentence)
    if not w or not s:
        return False
    if w in s.split():
        return True
    return w in s


def _compute_weighted_score(scores: dict[str, int]) -> int:
    weights = {
        "meaning": 0.30,
        "grammar": 0.25,
        "vocabulary": 0.15,
        "pronunciation": 0.20,
        "naturalness": 0.10,
    }
    total = 0.0
    for key, w in weights.items():
        total += (scores.get(key, 0) / 100.0) * w
    return max(0, min(100, round(total * 100)))


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _enrich_example(example: dict[str, Any], target_lang: str) -> dict[str, Any]:
    target = safe_str(example.get("target")).strip()
    if target and not example.get("pronunciation_tr"):
        example["pronunciation_tr"] = pronounce_text(target, target_lang)
    parts = example.get("parts")
    if not isinstance(parts, list):
        example["parts"] = []
    return example


def _fallback_word_examples(
    word_tr: str,
    target_word: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> list[dict[str, Any]]:
    """LLM yokken basit örnek cümle şablonları."""
    templates = [
        ("{w} seviyorum.", "positive"),
        ("{w} sevmiyorum.", "negative"),
        ("{w} ister misin?", "question"),
        ("Bir {w} alabilir miyim?", "request"),
        ("Her gün {w} içerim.", "daily"),
        ("{w} içmek istiyorum.", "request"),
    ]
    examples: list[dict[str, Any]] = []
    for tpl_tr, stype in templates:
        tr_sent = tpl_tr.format(w=word_tr)
        target = ""
        if translate_fn:
            try:
                target = translate_fn(tr_sent, "tr", target_lang)
            except Exception:
                target = ""
        if not target:
            target = f"... {target_word} ..."
        examples.append({
            "tr": tr_sent,
            "target": target,
            "pronunciation_tr": pronounce_text(target, target_lang),
            "sentence_type": stype,
            "explanation_tr": f"Bu cümlede '{word_tr}' kelimesini günlük konuşmada kullanıyorsun.",
            "structure_tr": "",
            "parts": [{"tr": target_word, "meaning_tr": word_tr}],
        })
        if len(examples) >= 6:
            break
    return examples


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

    if llm_available():
        system = WORD_LESSON_JSON_PROMPT.format(
            lang_name=lang_name,
            word_tr=word_tr[:80],
        )
        parsed = _llm_json(system, "Return JSON only.", max_tokens=900)
        if parsed and isinstance(parsed.get("examples"), list) and parsed["examples"]:
            examples = [_enrich_example(ex, target_lang) for ex in parsed["examples"][:10]]
            if len(examples) < 5:
                fallback = _fallback_word_examples(word_tr, target_word, target_lang, translate_fn)
                seen = {_norm(ex.get("tr")) for ex in examples}
                for fb in fallback:
                    if _norm(fb.get("tr")) not in seen:
                        examples.append(fb)
                        seen.add(_norm(fb.get("tr")))
                    if len(examples) >= 6:
                        break
            return {
                "ok": True,
                "word_tr": word_tr,
                "target_lang": target_lang,
                "target_word": safe_str(parsed.get("target_word")).strip() or target_word,
                "word_explanation_tr": safe_str(parsed.get("word_explanation_tr")).strip(),
                "usage": parsed.get("usage") or {},
                "examples": examples,
            }

    if not target_word and translate_fn:
        try:
            target_word = translate_fn(word_tr, "tr", target_lang)
        except Exception:
            target_word = word_tr

    examples = _fallback_word_examples(word_tr, target_word, target_lang, translate_fn)
    return {
        "ok": True,
        "word_tr": word_tr,
        "target_lang": target_lang,
        "target_word": target_word,
        "word_explanation_tr": f"'{word_tr}' kelimesinin {lang_name} karşılığı: {target_word}",
        "usage": {
            "noun_tr": f"İsim olarak: {target_word}",
            "patterns": [target_word],
            "common_mistakes_tr": "Kelimeyi cümle içinde doğal kullanmaya dikkat et.",
        },
        "examples": examples,
    }


def analyze_sentence_for_builder(
    tr_sentence: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    tr_sentence = safe_str(tr_sentence).strip()
    if len(tr_sentence) < 4:
        return {"ok": False, "error_tr": "En az 4 karakterli bir cümle gir."}

    analysis = _analyze_for_teaching(tr_sentence, target_lang, translate_fn)
    natural = safe_str(analysis.get("natural_target")).strip()
    if not natural:
        natural = _rule_natural_translate_tr(tr_sentence, target_lang, translate_fn)

    pronunciation = pronounce_text(natural, target_lang)
    pairs = analysis.get("phrase_pairs") or []
    structure = safe_str(analysis.get("important_structure_tr")).strip()
    analysis_tr = safe_str(analysis.get("analysis_tr")).strip()
    alts = analysis.get("alternatives") or []

    pronunciation_chunks: list[dict[str, str]] = []
    if natural and target_lang == "en":
        chunks = re.split(r"([,.!?])", natural)
        phrase = ""
        for part in chunks:
            phrase += part
            if part.strip() in (".", "!", "?", ",") or len(phrase.split()) >= 3:
                p = phrase.strip(" ,.")
                if p:
                    pronunciation_chunks.append({
                        "target": p,
                        "pronunciation_tr": pronounce_text(p, target_lang),
                    })
                phrase = ""

    return {
        "ok": True,
        "tr_sentence": tr_sentence,
        "target_lang": target_lang,
        "target_sentence": natural,
        "pronunciation_tr": pronunciation,
        "alternatives": alts[:3],
        "grammar_explanation_tr": analysis_tr,
        "structure_tr": structure,
        "phrase_pairs": pairs,
        "why_tr": analysis_tr,
        "pronunciation_chunks": pronunciation_chunks,
    }


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

    sim_to_correct = _similarity(user, correct)
    if sim_to_correct >= 0.85:
        meaning_ok = True
        grammar_ok = grammar_ok and True

    scores = {
        "meaning": 95 if meaning_ok else max(20, int(best_sim * 100)),
        "grammar": 90 if grammar_ok else 40,
        "vocabulary": 90 if vocab_ok else 35,
        "pronunciation": 75,
        "naturalness": 85 if meaning_ok else 50,
    }
    score = _compute_weighted_score(scores)

    return {
        "sentence_ok": meaning_ok and grammar_ok,
        "grammar_ok": grammar_ok,
        "vocabulary_ok": vocab_ok,
        "pronunciation_ok": True,
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
    }


def grade_word_answer(
    word_tr: str,
    target_word: str,
    user_answer: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    user_answer = safe_str(user_answer).strip()
    if len(user_answer) < 2:
        return {
            "ok": False,
            "error_tr": "Konuşman algılanamadı — tekrar dene.",
        }

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
            return parsed

    example_correct = f"I love {target_word}."
    if translate_fn:
        try:
            example_correct = translate_fn(f"{word_tr} seviyorum.", "tr", target_lang)
        except Exception:
            pass

    result = _rule_grade(
        user_answer, example_correct, target_word=target_word, target_lang=target_lang,
    )
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
            return parsed

    result = _rule_grade(
        user_answer, expected_target, alternatives=alts, target_lang=target_lang,
    )
    result["ok"] = True
    return result


def learning_level_from_stats(stats: dict[str, Any]) -> str:
    """Öğrenme seviyesi etiketi."""
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
    """Yüksek ağırlık = daha sık göster."""
    attempts = int(stats.get("attempts") or 0)
    wrong = int(stats.get("wrong") or 0)
    avg = float(stats.get("avgScore") or 50)
    pron = float(stats.get("pronunciationAvg") or 70)
    base = 1.0
    if attempts == 0:
        return 2.0
    error_rate = wrong / max(attempts, 1)
    weight = base + error_rate * 2.0 + (100 - avg) / 50.0 + (100 - pron) / 80.0
    if avg >= 90 and attempts >= 5:
        weight *= 0.4
    return max(0.2, weight)
