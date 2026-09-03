"""Jenny TTS ile aynı okunuş + Gürcüce yerli düzeltme (ezber cümle yok)."""
from pronunciation_service import (
    build_sentence_natural,
    romanize_for_tr_reader,
    _resolve_en_phonetic,
    _normalize_pron_tr,
)
from server import _polish_georgian


STORY_EN = (
    "The little girl held her breath and took a step toward the blue bird. "
    "Instead of flying away, the bird tilted its head slightly to the side and, "
    "as if inviting her to follow, chirped and soared into the sky. "
    "Forgetting the colorful butterflies, the girl began to chase after these mysterious wings. "
    "The bird led her to an old plane tree at the very edge of the village. "
    "In a hollow in the tree stood an old fairy-tale storybook, sparkling brightly. "
    "When the little girl picked up the book, the bird landed on her shoulder and whispered in her ear: "
    '"This book is waiting to be filled with the new fairy tales your mother will tell you '
    'and the new toys your father will carve from wood." '
    "From that day on, every picture the little girl drew came to life on the pages of this magical book."
)

STORY_TR = (
    "Küçük kız, nefesini tutarak mavi kuşa doğru bir adım attı. "
    "Kuş, kaçmak yerine başını hafifçe yana eğdi ve sanki onu takip etmesini ister gibi "
    "cıvıldayarak gökyüzüne doğru havalandı. Kız, rengarenk kelebekleri unutup bu gizemli "
    "kanatların peşinden koşmaya başladı. Kuş onu, kasabanın hemen bitimindeki yaşlı çınar "
    "ağacının yanına getirdi. Ağacın kovuğunda, parıl parıl parlayan eski bir masal kitabı duruyordu. "
    "Küçük kız kitabı eline aldığında, kuş omzuna kondu ve kulağına fısıldadı: "
    '"Bu kitap, annenin sana anlatacağı yeni masallarla ve babanın ahşaptan yapacağı yeni oyuncaklarla '
    'dolmayı bekliyor." O günden sonra küçük kızın çizdiği her resim, bu sihirli kitabın sayfalarında '
    "gerçeğe dönüştü."
)


def test_normalize_keeps_o_umlaut():
    assert _normalize_pron_tr("börd") == "börd"
    assert _normalize_pron_tr("törn") == "törn"
    assert "ö" in _normalize_pron_tr("görl")


def test_jenny_core_words():
    assert _resolve_en_phonetic("bird") == "börd"
    assert _resolve_en_phonetic("girl") == "görl"
    assert _resolve_en_phonetic("her") == "hör"
    assert _resolve_en_phonetic("blue") == "blu"
    assert _resolve_en_phonetic("took") == "tuk"
    assert _resolve_en_phonetic("were") == "vör"
    assert _resolve_en_phonetic("work") == "vörk"
    assert _resolve_en_phonetic("turn") == "törn"
    assert _resolve_en_phonetic("chirped") == "çörpt"
    assert _resolve_en_phonetic("first") == "först"


def test_g2p_unknown_nurse_vowel():
    # Sözlükte olmayan NURSE kelimesi de ör olmalı — tek hikâye ezberi değil
    assert "ö" in _resolve_en_phonetic("twirl")
    assert _resolve_en_phonetic("twirl") != "twirl"


def test_story_phonetic_matches_jenny_not_spelling():
    pron = build_sentence_natural(STORY_EN, "en").lower()
    assert "börd" in pron
    assert "görl" in pron
    assert "hör" in pron
    assert "blu" in pron
    assert "tuk" in pron
    assert "çörpt" in pron
    assert not re_search_word(pron, "bird")
    assert not re_search_word(pron, "girl")
    assert "whispered" not in pron
    assert len(pron) > 500


def re_search_word(text: str, word: str) -> bool:
    import re
    return bool(re.search(rf"\b{word}\b", text))


def test_georgian_romanization_matches_eka():
    # ხ = kh (hışırtı), ყ = q — Eka'nın sesi
    assert "khis" in romanize_for_tr_reader("ხის ფუღუროში", "ka")
    assert "qurşi" in romanize_for_tr_reader("ყურში", "ka")
    assert "mkharze" in romanize_for_tr_reader("მხარზე", "ka")
    roma = romanize_for_tr_reader("სთხოვდა", "ka")
    assert "kh" in roma


def test_polish_georgian_is_source_conditioned():
    googleish = (
        "სუნთქვაშეკრული პატარა გოგონამ ნაბიჯი გადადგა. "
        "ჩიტმა იგი ქალაქის ბოლოში მდებარე ძველ ჭადართან მიიყვანა. "
        "ხის ფუღუროში იდგა წიგნი. პატარა გოგონამ წიგნი ხელში აიყვანა, "
        "ჩიტი მხარზე დაეშვა. მამაშენი ხისგან გააკეთებს. "
        "ყველა სურათი რეალობად იქცა."
    )
    out = _polish_georgian(STORY_TR, googleish)
    assert "სუნთქვაშეკრულმა" in out
    assert "სოფლის პირას" in out
    assert "ქალაქის ბოლოში" not in out
    assert "ხელში აიღო" in out
    assert "აიყვანა" not in out
    assert "ჩამოჯდა" in out
    assert "გამოთლის" in out
    assert "ცოცხლდებოდა" in out
    assert "ჭადარ" in out


def test_polish_does_not_rewrite_unrelated_city():
    src = "İstanbul şehrinin merkezine gittim."
    ka = "ქალაქის ბოლოში დავდექი."
    out = _polish_georgian(src, ka)
    assert "ქალაქის ბოლოში" in out


if __name__ == "__main__":
    test_normalize_keeps_o_umlaut()
    test_jenny_core_words()
    test_g2p_unknown_nurse_vowel()
    test_story_phonetic_matches_jenny_not_spelling()
    test_georgian_romanization_matches_eka()
    test_polish_georgian_is_source_conditioned()
    test_polish_does_not_rewrite_unrelated_city()
    print("All pronunciation/TTS tests passed.")
