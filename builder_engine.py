"""Cümle Kur + Kendini Test Et — kelime/cümle üretimi, yapılandırılmış analiz, telaffuz."""
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
    safe_str,
)
from pronunciation_service import (
    apply_pronunciation_to_example,
    build_sentence,
    enrich_pattern_examples,
    get_word,
    register_word,
    strip_teaching_header,
)

# ── Yasak / şablon açıklamalar ──
GENERIC_BANNED_RE = re.compile(
    r"günlük konuşmada kullan|kelime(?:yi)? günlük|bu cümlede .+ kelimesini|"
    r"anlamsız tekrar|template|placeholder",
    re.I,
)

WORD_LESSON_V2_PROMPT = """Sen Türkçe konuşan bir öğrenciye {lang_name} öğreten uzman bir dil öğretmenisin.
Öğrenci Türkçe KELİME girdi: "{word_tr}"

GÖREV: Çeviri uygulaması DEĞİL — CÜMLE KURMAYI ÖĞRET.
Her örnek cümle FARKLI gramer yapısı kullanmalı (olumlu, olumsuz, soru, rica, teklif, tag question vb.).

YASAK:
- "Bu cümlede X kelimesini günlük konuşmada kullanıyorsun" gibi şablon cümleler
- Tüm örneklere aynı açıklamayı kopyalamak
- Kelime kelime çeviri listesi ile yetinmek
- Türkçe okunuşu İngilizce yazılışa göre harf harf uydurmak

Her örnek için ZORUNLU alanlar (hepsi Türkçe, öğrenci {lang_name} bilmiyor):
- how_it_is_formed_tr: 🧠 Nasıl kuruldu? — yapı, parçalar, neden bu sıra, Türkçeden fark
- why_this_structure_tr: Neden bu cümle böyle?
- important_note_tr: ⚠️ dikkat (yardımcı fiil, have bağlamı, don't + yalın fiil vb.) — yoksa null
- pattern_tr: 🎯 Bu kalıbı unutma
- pattern_examples: aynı kalıpla 2-3 örnek (hedef dilde)
- structure_tr: I + love + coffee formatında
- structure_label_tr: Özne + Fiil + Nesne gibi
- word_breakdown: [{{"token":"I","role_tr":"özne","meaning_tr":"ben"}}]
- sentence_type, grammar_topic, difficulty (A1-C1)
- pronunciation_tr: SES temelli Türkçe yaklaşık okunuş (dont, layk, kofi — du u vant DEĞİL)
- ipa: cümle IPA
- word_pronunciations: [{{"word":"coffee","pronunciation_tr":"kofi","ipa":"/ˈkɔːfi/"}}]

JSON:
{{
  "target_word": "...",
  "word_explanation_tr": "...",
  "usage": {{"noun_tr":"...","patterns":[],"common_mistakes_tr":"..."}},
  "examples": [ ... 6-8 örnek, her biri benzersiz analiz ... ]
}}"""

SENTENCE_ANALYSIS_V2_PROMPT = """Turkish sentence: "{tr_sentence}"
Target language: {lang_name} ({target_lang})

Teach HOW the sentence is built — not just translation.
Return JSON:
{{
  "target_sentence": "natural {lang_name}",
  "alternatives": ["..."],
  "sentence_type": "...",
  "grammar_topic": "...",
  "difficulty": "A1",
  "structure_tr": "I + was + tired",
  "structure_label_tr": "Özne + be geçmiş + sıfat",
  "word_breakdown": [{{"token":"I","role_tr":"özne","meaning_tr":"ben"}}],
  "how_it_is_formed_tr": "detailed Turkish teaching",
  "why_this_structure_tr": "...",
  "important_note_tr": "... or null",
  "pattern_tr": "... or null",
  "pattern_examples": [],
  "pronunciation_tr": "sound-based Turkish-readable",
  "ipa": "/.../",
  "word_pronunciations": [{{"word":"...","pronunciation_tr":"...","ipa":"..."}}],
  "pronunciation_chunks": [{{"target":"I was","pronunciation_tr":"ay vaz","ipa":"..."}}]
}}"""

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
    if len(t) < 60:
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
    """Geriye dönük uyumluluk — merkezi telaffuz servisini kullanır."""
    return build_sentence(text, "en")


def _pronunciation_bundle(
    text: str,
    target_lang: str,
    focus_words: list[str] | None = None,
) -> dict[str, Any]:
    """Merkezi telaffuz sözlüğü — LLM ile telaffuz üretilmez."""
    text = safe_str(text).strip()
    if not text:
        return {"pronunciation_tr": "", "ipa": "", "word_pronunciations": []}
    return build_sentence(text, target_lang, focus_words)


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


# ── Zengin kural tabanlı İngilizce ders şablonları ──
def _en_lesson_templates(word_tr: str, target_word: str) -> list[dict[str, Any]]:
    W, T = word_tr, target_word
    return [
        {
            "tr": f"{W} seviyorum.",
            "target": f"I love {T}.",
            "sentence_type": "positive",
            "grammar_topic": "simple_present_svo",
            "difficulty": "A1",
            "structure_tr": f"I + love + {T}",
            "structure_label_tr": "Özne + Fiil + Nesne",
            "word_breakdown": [
                {"token": "I", "role_tr": "özne", "meaning_tr": "ben"},
                {"token": "love", "role_tr": "fiil", "meaning_tr": "sevmek"},
                {"token": T, "role_tr": "nesne", "meaning_tr": W},
            ],
            "how_it_is_formed_tr": (
                "İngilizcede basit olumlu cümlede temel sıra:\n"
                "Özne + Fiil + Nesne\n\n"
                f"I → ben\nlove → sevmek\n{T} → {W}\n\n"
                f"Bu nedenle: I + love + {T}\n\n"
                "Türkçede «Kahve seviyorum» derken «ben»i söylemeyebilirsin; "
                "İngilizcede özne çoğu zaman açıkça yazılır: I love…"
            ),
            "why_this_structure_tr": "Basit geniş zaman; düzenli fiil love + nesne.",
            "important_note_tr": None,
            "pattern_tr": "I love + [şey]",
            "pattern_examples": [
                {"target": f"I love {T}.", "tr": f"{W} seviyorum."},
                {"target": "I love tea.", "tr": "Çayı seviyorum.", "new_words": [{"word": "tea", "meaning_tr": "çay"}]},
                {"target": "I love music.", "tr": "Müziği seviyorum.", "new_words": [{"word": "music", "meaning_tr": "müzik"}]},
            ],
        },
        {
            "tr": f"{W} sevmiyorum.",
            "target": f"I don't like {T}.",
            "sentence_type": "negative",
            "grammar_topic": "simple_present_negative",
            "difficulty": "A1",
            "structure_tr": f"I + don't + like + {T}",
            "structure_label_tr": "Özne + don't + fiil(yalın) + nesne",
            "word_breakdown": [
                {"token": "I", "role_tr": "özne", "meaning_tr": "ben"},
                {"token": "don't", "role_tr": "olumsuz yardımcı", "meaning_tr": "-mıyorum"},
                {"token": "like", "role_tr": "fiil (yalın)", "meaning_tr": "sevmek"},
                {"token": T, "role_tr": "nesne", "meaning_tr": W},
            ],
            "how_it_is_formed_tr": (
                "Bu olumsuz cümledir. Geniş zamanda like gibi fiillerle:\n"
                "Özne + do not/don't + fiilin yalın hali + nesne\n\n"
                f"I → ben\ndon't → -mıyorum\nlike → sevmek (liked/likes DEĞİL!)\n{T} → {W}\n\n"
                "⚠️ don't zaten olumsuzluğu taşır; like yalın kalır."
            ),
            "why_this_structure_tr": "Olumsuzluk için don't kullanılır; fiil çekimlenmez.",
            "important_note_tr": "❌ I don't liked / I don't likes — yanlış. ✅ I don't like",
            "pattern_tr": "I don't like + [şey]",
            "pattern_examples": [
                {"target": "I don't like tea.", "tr": "Çayı sevmiyorum.", "new_words": [{"word": "tea", "meaning_tr": "çay"}]},
                {"target": "I don't like milk.", "tr": "Sütü sevmiyorum.", "new_words": [{"word": "milk", "meaning_tr": "süt"}]},
                {"target": f"I don't like cold {T}.", "tr": f"Soğuk {W} sevmiyorum.", "new_words": [{"word": "cold", "meaning_tr": "soğuk"}]},
            ],
        },
        {
            "tr": f"{W} ister misin?",
            "target": f"Do you want {T}?",
            "sentence_type": "question",
            "grammar_topic": "yes_no_question_do",
            "difficulty": "A1",
            "structure_tr": f"Do + you + want + {T}?",
            "structure_label_tr": "Do + özne + fiil + nesne?",
            "word_breakdown": [
                {"token": "Do", "role_tr": "yardımcı fiil", "meaning_tr": "soru yapısı"},
                {"token": "you", "role_tr": "özne", "meaning_tr": "sen"},
                {"token": "want", "role_tr": "fiil", "meaning_tr": "istemek"},
                {"token": T, "role_tr": "nesne", "meaning_tr": W},
            ],
            "how_it_is_formed_tr": (
                "Geniş zamanda want ile soru:\n"
                "Do + Özne + Fiil + Nesne?\n\n"
                f"Do → soru oluşturur\nyou → sen\nwant → istemek\n{T} → {W}\n\n"
                "⚠️ Türkçe sırayla ❌ You want coffee? değil.\n"
                "✅ Do you want coffee?"
            ),
            "why_this_structure_tr": "Soru için cümle başına Do gelir; fiil yalın kalır.",
            "important_note_tr": "Türkçe «Kahve ister misin?» — İngilizcede kelime sırası değişir.",
            "pattern_tr": "Do you want + [şey]?",
            "pattern_examples": [
                {"target": f"Do you want {T}?", "tr": f"{W} ister misin?"},
                {"target": "Do you want tea?", "tr": "Çay ister misin?", "new_words": [{"word": "tea", "meaning_tr": "çay"}]},
                {"target": "Do you want some water?", "tr": "Biraz su ister misin?", "new_words": [
                    {"word": "some", "meaning_tr": "biraz / bazı"},
                    {"word": "water", "meaning_tr": "su"},
                ]},
            ],
        },
        {
            "tr": f"Bir {W} alabilir miyim?",
            "target": f"Can I have a {T}?",
            "sentence_type": "request",
            "grammar_topic": "modal_can_have",
            "difficulty": "A2",
            "structure_tr": f"Can + I + have + a {T}?",
            "structure_label_tr": "Can + özne + have + nesne?",
            "word_breakdown": [
                {"token": "Can", "role_tr": "modal", "meaning_tr": "-ebilir miyim?"},
                {"token": "I", "role_tr": "özne", "meaning_tr": "ben"},
                {"token": "have", "role_tr": "fiil", "meaning_tr": "almak/istemek (bağlam)"},
                {"token": f"a {T}", "role_tr": "nesne", "meaning_tr": f"bir {W}"},
            ],
            "how_it_is_formed_tr": (
                "Can I have…? kibarca bir şey istemek için çok kullanılır.\n"
                "Can + I + have + nesne?\n\n"
                f"Can → -ebilir miyim?\nI → ben\nhave → burada «almak/istemek»\na {T} → bir {W}\n\n"
                "⚠️ have sadece «sahip olmak» değil!\n"
                "Can I have some water? = Biraz su alabilir miyim?"
            ),
            "why_this_structure_tr": "Modal can + özne + have = rica/istek kalıbı.",
            "important_note_tr": "have kelimesi bağlama göre «istemek/almak» anlamına gelir.",
            "pattern_tr": "Can I have + [şey]?",
            "pattern_examples": [
                {"target": "Can I have some water?", "tr": "Biraz su alabilir miyim?", "new_words": [
                    {"word": "some", "meaning_tr": "biraz / bazı"},
                    {"word": "water", "meaning_tr": "su"},
                ]},
                {"target": "Can I have the menu?", "tr": "Menüyü alabilir miyim?", "new_words": [{"word": "menu", "meaning_tr": "menü"}]},
                {"target": f"Can I have a {T}?", "tr": f"Bir {W} alabilir miyim?"},
            ],
        },
        {
            "tr": f"Sana bir {W} alayım mı?",
            "target": f"Shall I get you a {T}?",
            "sentence_type": "offer",
            "grammar_topic": "shall_offer",
            "difficulty": "B1",
            "structure_tr": f"Shall + I + get + you + a {T}?",
            "structure_label_tr": "Shall I + fiil + you + nesne?",
            "word_breakdown": [
                {"token": "Shall I", "role_tr": "modal soru", "meaning_tr": "...ayım mı?"},
                {"token": "get", "role_tr": "fiil", "meaning_tr": "almak/getirmek"},
                {"token": "you", "role_tr": "dolaylı nesne", "meaning_tr": "sana"},
                {"token": f"a {T}", "role_tr": "nesne", "meaning_tr": f"bir {W}"},
            ],
            "how_it_is_formed_tr": (
                "Shall I…? birine teklif sunarken kullanılır.\n"
                f"Shall + I + get + you + a {T}?\n\n"
                "get → almak/getirmek\nyou → sana (Türkçedeki «sana» karşılığı)\n\n"
                "get you a coffee = sana bir kahve almak/getirmek"
            ),
            "why_this_structure_tr": "Teklif: Shall I + fiil + you + şey",
            "important_note_tr": "you burada «sana» anlamını verir; atlanmaz.",
            "pattern_tr": "Shall I + fiil + you + [şey]?",
            "pattern_examples": [
                {"target": "Shall I get you some water?", "tr": "Sana biraz su getireyim mi?", "new_words": [
                    {"word": "some", "meaning_tr": "biraz / bazı"},
                    {"word": "water", "meaning_tr": "su"},
                ]},
                {"target": f"Shall I make you a {T}?", "tr": f"Sana bir {W} yapayım mı?", "new_words": [
                    {"word": "make", "meaning_tr": "yapmak"},
                ]},
                {"target": "Shall I carry your bag?", "tr": "Çantanı taşıyayım mı?", "new_words": [
                    {"word": "carry", "meaning_tr": "taşımak"},
                    {"word": "bag", "meaning_tr": "çanta"},
                ]},
                {"target": "Shall I call a taxi?", "tr": "Taksi çağırayım mı?", "new_words": [
                    {"word": "call", "meaning_tr": "aramak / çağırmak", "example_target": "I will call you.", "example_tr": "Seni arayacağım."},
                    {"word": "taxi", "meaning_tr": "taksi"},
                ]},
            ],
        },
        {
            "tr": f"Sabahları {W} içmezsin, öyle değil mi?",
            "target": f"You don't drink {T} in the morning, do you?",
            "sentence_type": "tag_question",
            "grammar_topic": "tag_question",
            "difficulty": "B1",
            "structure_tr": f"You don't drink {T} in the morning + do you?",
            "structure_label_tr": "Olumsuz ana cümle + olumlu tag",
            "word_breakdown": [
                {"token": "You don't drink", "role_tr": "ana cümle", "meaning_tr": f"{W} içmiyorsun"},
                {"token": "in the morning", "role_tr": "zaman", "meaning_tr": "sabahları"},
                {"token": "do you?", "role_tr": "tag question", "meaning_tr": "değil mi?"},
            ],
            "how_it_is_formed_tr": (
                "Bu tag question yapısıdır — «… değil mi?» gibi onay bekler.\n\n"
                f"Ana cümle: You don't drink {T} in the morning\n"
                "Tag: do you?\n\n"
                "⚠️ Kural: Ana cümle olumsuzsa tag genelde olumlu olur.\n"
                "Ana olumlu → tag olumsuz (You're tired, aren't you?)"
            ),
            "why_this_structure_tr": "Konuşmacı bir şeyi biliyor varsayar ve onay ister.",
            "important_note_tr": "Tag question ileri seviye; önce basit soruları öğren.",
            "pattern_tr": "Olumsuz cümle, do/does you?",
            "pattern_examples": [
                {"target": "You're coming, aren't you?", "tr": "Geliyorsun, değil mi?", "new_words": [
                    {"word": "coming", "meaning_tr": "gelmek"},
                ]},
                {"target": "She doesn't like it, does she?", "tr": "O bunu sevmiyor, değil mi?"},
            ],
        },
    ]


def _rule_based_word_lesson(
    word_tr: str,
    target_word: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> list[dict[str, Any]]:
    """LLM yokken veya kalite düşükken zengin kural tabanlı ders."""
    if target_lang == "en":
        templates = _en_lesson_templates(word_tr, target_word)
    else:
        templates = []
        basic = [
            ("{w} seviyorum.", "positive"),
            ("{w} sevmiyorum.", "negative"),
            ("{w} ister misin?", "question"),
            ("Bir {w} alabilir miyim?", "request"),
        ]
        for tpl, st in basic:
            tr_sent = tpl.format(w=word_tr)
            target = ""
            if translate_fn:
                try:
                    target = translate_fn(tr_sent, "tr", target_lang)
                except Exception:
                    pass
            if not target:
                target = f"... {target_word} ..."
            templates.append({
                "tr": tr_sent,
                "target": target,
                "sentence_type": st,
                "grammar_topic": st,
                "difficulty": "A1",
                "structure_tr": "",
                "structure_label_tr": "",
                "word_breakdown": [{"token": target_word, "role_tr": "kelime", "meaning_tr": word_tr}],
                "how_it_is_formed_tr": (
                    f"Bu cümle «{tr_sent}» anlamını {LANG_NAMES.get(target_lang, target_lang)} "
                    f"dilinde «{target}» şeklinde verir.\n"
                    f"Yapı: {st} cümle tipi. {target_word} kelimesi cümlenin merkezindedir."
                ),
                "why_this_structure_tr": f"{word_tr} kelimesini {st} bağlamda kullanırsın.",
                "pattern_tr": None,
                "pattern_examples": [],
            })

    examples: list[dict[str, Any]] = []
    known: set[str] = set()
    for tpl in templates:
        ex = _enrich_example(tpl, target_lang, [target_word], known)
        examples.append(ex)
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
    if not target_word and translate_fn:
        try:
            target_word = translate_fn(word_tr, "tr", target_lang).strip()
        except Exception:
            target_word = word_tr
    target_word = safe_str(target_word).strip() or word_tr

    if target_lang == "en":
        tw_info = get_word("en", target_word)
        register_word("en", target_word, tw_info["pronunciation_tr"], tw_info.get("ipa", ""))

    known_words = {target_word.lower()}
    examples: list[dict[str, Any]] = []

    if llm_available():
        system = WORD_LESSON_V2_PROMPT.format(lang_name=lang_name, word_tr=word_tr[:80])
        parsed = _llm_json(system, "Return JSON only.", max_tokens=2200)
        if parsed and isinstance(parsed.get("examples"), list):
            raw_examples = parsed["examples"][:10]
            for ex in raw_examples:
                if not isinstance(ex, dict):
                    continue
                enriched = _enrich_example(ex, target_lang, [target_word], known_words)
                if _validate_example(enriched):
                    examples.append(enriched)
            if examples and not _dedupe_explanations(examples):
                examples = []

    if len(examples) < 5:
        rule_examples = _rule_based_word_lesson(word_tr, target_word, target_lang, translate_fn)
        seen = {_norm(ex.get("tr")) for ex in examples}
        for ex in rule_examples:
            if _norm(ex.get("tr")) not in seen:
                examples.append(ex)
                seen.add(_norm(ex.get("tr")))
            if len(examples) >= 8:
                break

    tw_pron = get_word(target_lang, target_word)

    return {
        "ok": True,
        "word_tr": word_tr,
        "target_lang": target_lang,
        "target_word": target_word,
        "pronunciation_tr": tw_pron["pronunciation_tr"],
        "ipa": tw_pron.get("ipa", ""),
        "word_explanation_tr": (
            f"«{word_tr}» kelimesi {lang_name} dilinde «{target_word}» karşılığına gelir. "
            "Aşağıdaki cümlelerde farklı gramer yapılarını öğreneceksin."
        ),
        "usage": {
            "noun_tr": f"Günlük {lang_name} dilinde «{target_word}» çoğunlukla isim olarak kullanılır.",
            "patterns": [f"I love {target_word}", f"Do you want {target_word}?"] if target_lang == "en" else [target_word],
            "common_mistakes_tr": "Kelime sırasını Türkçe gibi kurma; her cümle tipinin kendi yapısı var.",
        },
        "examples": examples[:10],
    }


def _analyze_sentence_structured(
    tr_sentence: str,
    target_lang: str,
    translate_fn: Callable[[str, str, str], str] | None,
) -> dict[str, Any] | None:
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    if not llm_available():
        return None
    system = SENTENCE_ANALYSIS_V2_PROMPT.format(
        tr_sentence=tr_sentence[:400],
        lang_name=lang_name,
        target_lang=target_lang,
    )
    parsed = _llm_json(system, "Return JSON only.", max_tokens=900)
    if not parsed or not parsed.get("target_sentence"):
        return None
    how = strip_teaching_header(safe_str(parsed.get("how_it_is_formed_tr")).strip())
    if _is_generic_explanation(how):
        return None
    target = safe_str(parsed["target_sentence"]).strip()
    bundle = _pronunciation_bundle(target, target_lang)
    parsed["target_sentence"] = target
    parsed["how_it_is_formed_tr"] = how
    parsed["pronunciation_tr"] = bundle["pronunciation_tr"]
    parsed["ipa"] = bundle.get("ipa") or parsed.get("ipa") or ""
    parsed["word_pronunciations"] = bundle["word_pronunciations"]
    focus = [w.get("token", "") for w in (parsed.get("word_breakdown") or []) if isinstance(w, dict)]
    parsed["pattern_examples"] = enrich_pattern_examples(
        parsed.get("pattern_examples") or [], target_lang, focus,
    )
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
