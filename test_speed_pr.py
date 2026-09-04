"""Hız PR birim testleri — STT early-exit kuralları ve çeviri kalite yolu."""
from server import (
    _stt_early_lang,
    _is_short_simple_utterance,
    _needs_quality_translate,
    _looks_like_literal_calque,
)


def test_stt_early_clear_turkish():
    assert _stt_early_lang("Merhaba, nasılsın bugün?", "tr", "en") == "tr"
    assert _stt_early_lang("Teşekkür ederim çok güzel", "tr", "en") == "tr"


def test_stt_early_clear_english():
    assert _stt_early_lang("How are you today?", "tr", "en") == "en"
    assert _stt_early_lang("Hello, thank you very much", "tr", "en") == "en"


def test_stt_early_single_ambiguous_waits():
    assert _stt_early_lang("to", "tr", "en") is None
    assert _stt_early_lang("book", "tr", "en") is None
    assert _stt_early_lang("ok", "tr", "en") is None


def test_stt_early_single_clear_turkish():
    assert _stt_early_lang("merhaba", "tr", "en") == "tr"
    assert _stt_early_lang("nasılsın", "tr", "en") == "tr"


def test_stt_early_empty_and_hallucination():
    assert _stt_early_lang("", "tr", "en") is None
    assert _stt_early_lang("teşekkürler", "tr", "en") is None


def test_short_simple_google_first():
    assert _is_short_simple_utterance("Merhaba")
    assert _is_short_simple_utterance("Nasılsın?")
    assert _is_short_simple_utterance("Teşekkür ederim.")
    assert _is_short_simple_utterance("Bunu istiyorum.")
    assert _is_short_simple_utterance("Nerede?")
    assert not _needs_quality_translate("Merhaba, nasılsın?", "tr", "de")
    assert not _needs_quality_translate("Merhaba, nasılsın?", "tr", "en")
    assert not _needs_quality_translate("Nasılsın?", "tr", "ka")


def test_long_and_story_still_quality():
    story = (
        "Küçük kız, nefesini tutarak mavi kuşa doğru bir adım attı. "
        "Kuş kaçmak yerine başını eğdi."
    )
    # Çok cümle / anlatı → tüm dillerde kalite (EN dahil)
    assert _needs_quality_translate(story, "tr", "en")
    assert _needs_quality_translate(story, "tr", "ka")
    assert _needs_quality_translate("Bir varmış bir yokmuş uzak bir ülkede", "tr", "en")
    assert _needs_quality_translate("Bir varmış bir yokmuş uzak bir ülkede", "tr", "ka")
    assert _needs_quality_translate("Ali'nin 4 yaşında oğlu var", "tr", "en")
    # Zamir + anlatı cümlesi
    assert _needs_quality_translate(
        "The girl spread her arms out; she felt freer than ever.",
        "en",
        "tr",
    )


def test_literal_calque_detector():
    assert _looks_like_literal_calque(
        "he felt freer than ever",
        "o hiç olmadığı kadar daha özgür hissetti",
        "tr",
    )
    assert not _looks_like_literal_calque(
        "he felt freer than ever",
        "Kendini hiç olmadığı kadar özgür hissediyordu.",
        "tr",
    )


if __name__ == "__main__":
    test_stt_early_clear_turkish()
    test_stt_early_clear_english()
    test_stt_early_single_ambiguous_waits()
    test_stt_early_single_clear_turkish()
    test_stt_early_empty_and_hallucination()
    test_short_simple_google_first()
    test_long_and_story_still_quality()
    test_literal_calque_detector()
    print("speed-pr unit tests passed")
