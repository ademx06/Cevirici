"""Kelimeye özel doğal örnek cümleler — mekanik şablon yok, gerçek kullanım senaryoları."""
from __future__ import annotations

from typing import Any, Callable


def build_lexicon_examples(
    word_tr: str,
    target_word: str,
    pe: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bilinen kelimeler için 13 doğal örnek; yoksa boş liste."""
    W = word_tr
    T = target_word.lower().strip()
    wt = word_tr.lower().strip()

    if wt in ("kapı", "kapi") or T == "door":
        return _door_examples(W, T, pe)
    if wt == "pencere" or T == "window":
        return _window_examples(W, T, pe)
    if wt in ("masa",) or T == "table":
        return _table_examples(W, T, pe)
    if wt == "sandalye" or T == "chair":
        return _chair_examples(W, T, pe)
    if wt == "kitap" or T == "book":
        return _book_examples(W, T, pe)
    if wt == "telefon" or T == "phone":
        return _phone_examples(W, T, pe)
    if wt == "kalem" or T == "pen":
        return _pen_examples(W, T, pe)
    if wt in ("anahtar",) or T == "key":
        return _key_examples(W, T, pe)
    return []


def _door_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Ön kapı ahşaptan yapılmış.", f"The front {T} is made of wood.", "basic",
           f"The + front {T} + is + made of wood",
           "Kapıyla ilgili doğal tanım: malzeme ve konum belirtmek yaygındır."),
        pe(W, "Şu an biri kapıyı çalıyor.", f"Someone is knocking on the {T} right now.", "present",
           f"Someone + is + knocking on + the {T}",
           "Kapıyla en doğal şimdiki zaman: knock on the door — kapıyı çalmak."),
        pe(W, "Çıkarken kapıyı kilitledim.", f"I locked the {T} when I left.", "past",
           f"I + locked + the {T} + when I left",
           "Geçmiş: lock the door — kapıyı kilitlemek."),
        pe(W, "Gelecek hafta ön kapıyı boyayacağız.", f"We will paint the front {T} next week.", "future",
           f"We + will + paint + the front {T}",
           "Gelecek: kapı bakımı/tadilat bağlamı doğaldır."),
        pe(W, "Arka kapı kilitli mi?", f"Is the back {T} locked?", "question",
           f"Is + the back {T} + locked",
           "Soru: Is the door locked? — kapı kilitli mi?"),
        pe(W, "Kapı tam kapanmamış.", f"The {T} isn't fully closed.", "negative",
           f"The {T} + isn't + fully closed",
           "Olumsuz: kapının düzgün kapanmadığını belirtmek doğal bir ifadedir."),
        pe(W, "Lütfen arkandan kapıyı kapat.", f"Please close the {T} behind you.", "imperative",
           f"Please + close + the {T} + behind you",
           "Emir: close the door behind you — arkandan kapıyı kapat (çok yaygın)."),
        pe(W, "Kapıyı benim için açar mısın?", f"Could you open the {T} for me?", "polite_request",
           f"Could you + open + the {T} + for me",
           "Rica: Could you open the door? — kapıyı açar mısın?"),
        pe(W, "Gece kapıyı kilitlemelisin.", f"You should lock the {T} at night.", "advice",
           f"You + should + lock + the {T}",
           "Tavsiye: güvenlik için kapıyı kilitlemek."),
        pe(W, "Kapı kolunu tamir etmem lazım.", f"I need to fix the {T} handle.", "obligation",
           f"I + need to + fix + the {T} + handle",
           "Zorunluluk: kapı kolu/tamir bağlamı doğaldır."),
        pe(W, "Kapıda biri olabilir.", f"There might be someone at the {T}.", "possibility",
           f"There might be + someone + at the {T}",
           "İhtimal: at the door — kapıda (birisi)."),
        pe(W, "Kapı sıkışırsa daha sert it.", f"If the {T} is stuck, push it harder.", "conditional",
           f"If + the {T} + is stuck, + push it harder",
           "Koşul: sıkışmış kapı senaryosu günlük hayatta sık görülür."),
        pe(W, "A: Kapıda kim var? B: Kurye.", f"A: Who's at the {T}? B: It's the delivery driver.", "dialogue",
           f"Who's at + the {T}",
           "Diyalog: Who's at the door? — Kapıda kim var?"),
    ]


def _window_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Oturma odasındaki pencere büyük.", f"The {T} in the living room is large.", "basic",
           f"The {T} + in the living room + is + large", "Konum + tanım doğal bir açılıştır."),
        pe(W, "Şu an pencereden dışarı bakıyor.", f"She is looking out of the {T} right now.", "present",
           f"look out of + the {T}", "look out of the window — pencereden dışarı bakmak."),
        pe(W, "Sıcak olduğu için pencereyi açtım.", f"I opened the {T} because it was hot.", "past",
           f"I + opened + the {T}", "open the window — pencereyi açmak."),
        pe(W, "Yarın pencereyi temizleyeceğim.", f"I will clean the {T} tomorrow.", "future",
           f"I + will + clean + the {T}", "Pencere temizliği doğal bir gelecek eylemidir."),
        pe(W, "Pencere açık mı?", f"Is the {T} open?", "question",
           f"Is + the {T} + open", "Is the window open? — Pencere açık mı?"),
        pe(W, "Pencere tam kapanmıyor.", f"The {T} won't close properly.", "negative",
           f"The {T} + won't close", "won't close — düzgün kapanmıyor."),
        pe(W, "Pencereyi kapat lütfen.", f"Please close the {T}.", "imperative",
           f"Please + close + the {T}", "close the window — pencereyi kapat."),
        pe(W, "Pencereyi açabilir misin?", f"Could you open the {T}?", "polite_request",
           f"Could you + open + the {T}", "Could you open the window? — çok yaygın rica."),
        pe(W, "Hava güzelken pencereyi açmalısın.", f"You should open the {T} when the weather is nice.", "advice",
           f"You should + open + the {T}", "Hava güzelken pencere açmak doğal tavsiye."),
        pe(W, "Pencere camını değiştirmem lazım.", f"I need to replace the {T} glass.", "obligation",
           f"I need to + replace + the {T} glass", "Cam değişimi pencere bağlamında doğaldır."),
        pe(W, "Pencereden ses geliyor olabilir.", f"There might be noise coming from the {T}.", "possibility",
           f"noise + from the {T}", "Dışarıdan gelen ses pencere bağlamında."),
        pe(W, "Yağmur yağarsa pencereyi kapat.", f"If it rains, close the {T}.", "conditional",
           f"If it rains, + close + the {T}", "Yağmurda pencere kapatma doğal koşul."),
        pe(W, "A: Pencereyi açayım mı? B: Evet.", f"A: Should I open the {T}? B: Yes, please.", "dialogue",
           f"Should I open + the {T}", "Günlük diyalog: pencere açma teklifi."),
    ]


def _table_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Her akşam masada yemek yeriz.", f"We eat dinner at the {T} every night.", "basic",
           f"eat + at the {T}", "at the table — masada oturmak/yemek yemek."),
        pe(W, "Çocuklar şu an masanın üzerinde resim yapıyor.", f"The kids are drawing on the {T} right now.", "present",
           f"drawing on + the {T}", "on the table — masanın üzerinde."),
        pe(W, "Dün akşam masayı kurdum.", f"I set the {T} for dinner yesterday.", "past",
           f"set + the {T}", "set the table — masayı/sofrayı kurmak."),
        pe(W, "Öğleden sonra masayı toplayacağım.", f"I will clear the {T} after lunch.", "future",
           f"clear + the {T}", "clear the table — masayı toplamak."),
        pe(W, "Masa temiz mi?", f"Is the {T} clean?", "question",
           f"Is + the {T} + clean", "Masa temizliği doğal soru."),
        pe(W, "Masada yeterli yer yok.", f"There isn't enough room on the {T}.", "negative",
           f"not enough room + on the {T}", "Yer yokluğu masada doğal ifade."),
        pe(W, "Masayı sil lütfen.", f"Please wipe the {T}.", "imperative",
           f"wipe + the {T}", "wipe the table — masayı silmek."),
        pe(W, "Masayı kurar mısın?", f"Could you set the {T} for me?", "polite_request",
           f"set + the {T}", "set the table — sofrayı kurar mısın?"),
        pe(W, "Masaya bir örtü sermelisin.", f"You should put a tablecloth on the {T}.", "advice",
           f"tablecloth + on the {T}", "Masa örtüsü doğal tavsiye."),
        pe(W, "Daha büyük bir masa almam lazım.", f"I need to buy a bigger {T}.", "obligation",
           f"buy + a bigger {T}", "Masa satın alma ihtiyacı."),
        pe(W, "Anahtarlar masada olabilir.", f"The keys might be on the {T}.", "possibility",
           f"on the {T}", "on the table — masada (bir şey olabilir)."),
        pe(W, "Masa doluysa tezgahı kullan.", f"If the {T} is full, use the counter.", "conditional",
           f"If the {T} is full", "Dolu masa senaryosu doğal."),
        pe(W, "A: Masa hazır mı? B: Evet, kurdum.", f"A: Is the {T} set? B: Yes, I just set it.", "dialogue",
           f"Is the {T} set", "Is the table set? — Masa/sofra hazır mı?"),
    ]


def _chair_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Bu sandalye çok rahat.", f"This {T} is very comfortable.", "basic",
           f"This {T} + is + comfortable", "Sandalye rahatlığı doğal tanım."),
        pe(W, "Şu an masadaki sandalyede oturuyor.", f"He is sitting in the {T} at the table.", "present",
           f"sitting in + the {T}", "sit in a chair — sandalyede oturmak."),
        pe(W, "Dün yeni bir sandalye aldım.", f"I bought a new {T} yesterday.", "past",
           f"bought + a new {T}", "Sandalye satın alma."),
        pe(W, "Yarın sandalyeyi salona taşıyacağım.", f"I will move the {T} to the living room tomorrow.", "future",
           f"move + the {T}", "Sandalye taşıma doğal eylem."),
        pe(W, "Bu sandalye boş mu?", f"Is this {T} taken?", "question",
           f"Is this {T} + taken", "Is this chair taken? — Bu sandalye dolu mu?"),
        pe(W, "Bu sandalye çok alçak.", f"This {T} isn't high enough.", "negative",
           f"isn't high enough", "Yükseklik şikayeti doğal."),
        pe(W, "Lütfen sandalyeni çek.", f"Please pull up your {T}.", "imperative",
           f"pull up + your {T}", "pull up a chair — sandalyeni çek/otur."),
        pe(W, "Yanıma bir sandalye çeker misin?", f"Could you pull up a {T} next to me?", "polite_request",
           f"pull up + a {T}", "Oturma daveti için doğal rica."),
        pe(W, "Sırtın için iyi bir sandalye seçmelisin.", f"You should choose a good {T} for your back.", "advice",
           f"good {T} + for your back", "Ergonomi tavsiyesi."),
        pe(W, "Ofis için yeni sandalye almam lazım.", f"I need to get a new office {T}.", "obligation",
           f"office {T}", "Ofis sandalyesi ihtiyacı."),
        pe(W, "Sandalye arkaya devrilmiş olabilir.", f"The {T} might have tipped over.", "possibility",
           f"tipped over", "Devrilme ihtimali."),
        pe(W, "Sandalye kırıksa başka birine otur.", f"If the {T} is broken, sit somewhere else.", "conditional",
           f"If the {T} is broken", "Kırık sandalye senaryosu."),
        pe(W, "A: Bu sandalye rahat mı? B: Evet.", f"A: Is this {T} comfortable? B: Yes, it is.", "dialogue",
           f"Is this {T} comfortable", "Rahatlık sorma diyalogu."),
    ]


def _book_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    books = f"{T}s" if not T.endswith("s") else T
    return [
        pe(W, "Raftaki kitap çok kalın.", f"The {T} on the shelf is very thick.", "basic",
           f"The {T} + on the shelf", "Kitap konumu ve tanımı."),
        pe(W, "Şu an kitap okuyorum.", f"I am reading a {T} right now.", "present",
           f"reading + a {T}", "read a book — kitap okumak (❌ riding değil)."),
        pe(W, "Geçen ay harika bir kitap bitirdim.", f"I finished a great {T} last month.", "past",
           f"finished + a {T}", "finish a book — kitabı bitirmek."),
        pe(W, "Yarın kütüphaneden kitap alacağım.", f"I will borrow a {T} from the library tomorrow.", "future",
           f"borrow + a {T}", "Kitap ödünç alma."),
        pe(W, "Bu kitabı okudun mu?", f"Have you read this {T}?", "question",
           f"Have you read + this {T}", "Have you read…? — Okudun mu?"),
        pe(W, "Bu kitabı henüz bitirmedim.", f"I haven't finished this {T} yet.", "negative",
           f"haven't finished + this {T}", "Henüz bitirmeme."),
        pe(W, "Kitabı bana ver.", f"Hand me the {T}, please.", "imperative",
           f"Hand me + the {T}", "Kitap uzatma/verme."),
        pe(W, "Bu kitabı ödünç alabilir miyim?", f"Could I borrow this {T}?", "polite_request",
           f"borrow + this {T}", "Ödünç alma ricası."),
        pe(W, "Yatmadan önce kitap okumalısın.", f"You should read a {T} before bed.", "advice",
           f"read + a {T} + before bed", "Uyku öncesi okuma tavsiyesi."),
        pe(W, "Sınav için bu kitabı okumam lazım.", f"I need to read this {T} for the exam.", "obligation",
           f"read + for the exam", "Sınav hazırlığı."),
        pe(W, "Kitap çantamda olabilir.", f"The {T} might be in my bag.", "possibility",
           f"in my bag", "Kitabı kaybetme/arama."),
        pe(W, "Kitap ilginçse bitirirsin.", f"If the {T} is interesting, you'll finish it.", "conditional",
           f"If the {T} is interesting", "İlgi koşulu."),
        pe(W, "A: Bu kitabı okudun mu? B: Henüz değil.", f"A: Have you read this {T}? B: Not yet.", "dialogue",
           f"Have you read + this {T}", "Kitap hakkında diyalog."),
    ]


def _phone_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Telefonum cebimde.", f"My {T} is in my pocket.", "basic",
           f"My {T} + is in my pocket", "Telefon konumu."),
        pe(W, "Şu an telefon çalıyor.", f"The {T} is ringing right now.", "present",
           f"The {T} + is ringing", "is ringing — telefon çalıyor."),
        pe(W, "Dün telefonumu evde unuttum.", f"I left my {T} at home yesterday.", "past",
           f"left + my {T}", "Telefonu unutma — çok yaygın."),
        pe(W, "Yarın yeni telefon alacağım.", f"I will buy a new {T} tomorrow.", "future",
           f"buy + a new {T}", "Yeni telefon alma."),
        pe(W, "Telefonun şarjı bitti mi?", f"Is your {T} dead?", "question",
           f"Is your {T} + dead", "dead = şarjı bitti (telefon için)."),
        pe(W, "Telefonum çekmiyor.", f"My {T} has no signal.", "negative",
           f"has no signal", "Çekim yok — no signal."),
        pe(W, "Telefonu sessize al.", f"Put your {T} on silent.", "imperative",
           f"on silent", "sessize al — put on silent."),
        pe(W, "Telefonu açar mısın?", f"Could you answer the {T}?", "polite_request",
           f"answer + the {T}", "answer the phone — telefonu açmak."),
        pe(W, "Araba kullanırken telefon kullanmamalısın.", f"You shouldn't use your {T} while driving.", "advice",
           f"shouldn't use + while driving", "Güvenlik tavsiyesi."),
        pe(W, "Telefonumu şarj etmem lazım.", f"I need to charge my {T}.", "obligation",
           f"charge + my {T}", "charge the phone — şarj etmek."),
        pe(W, "Telefon masada olabilir.", f"My {T} might be on the table.", "possibility",
           f"on the table", "Kayıp telefon arama."),
        pe(W, "Telefon çalarsa aç.", f"If the {T} rings, answer it.", "conditional",
           f"If the {T} rings", "Çalma koşulu."),
        pe(W, "A: Telefonun nerede? B: Masada.", f"A: Where's your {T}? B: On the table.", "dialogue",
           f"Where's your {T}", "Telefon konumu diyalogu."),
    ]


def _pen_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pe(W, "Mavi bir kalem kullanıyorum.", f"I use a blue {T}.", "basic",
           f"use + a blue {T}", "Kalem rengi/türü belirtmek doğal."),
        pe(W, "Şu an kalemle not alıyor.", f"She is taking notes with a {T}.", "present",
           f"taking notes + with a {T}", "write/take notes with a pen."),
        pe(W, "Kalemini bana ödünç verdin.", f"You lent me your {T}.", "past",
           f"lent + your {T}", "Kalem ödünç verme."),
        pe(W, "Yarın yeni kalem alacağım.", f"I will buy a new {T} tomorrow.", "future",
           f"buy + a new {T}", "Kalem satın alma."),
        pe(W, "Kalemin var mı?", f"Do you have a {T}?", "question",
           f"Do you have + a {T}", "Do you have a pen? — Kalemin var mı?"),
        pe(W, "Kalemin mürekkebi bitti.", f"My {T} ran out of ink.", "negative",
           f"ran out of ink", "Mürekkep bitmesi."),
        pe(W, "Buraya imza at.", f"Sign here with the {T}.", "imperative",
           f"Sign + with the {T}", "İmza atmak için kalem."),
        pe(W, "Kalemini ödünç alabilir miyim?", f"Could I borrow your {T}?", "polite_request",
           f"borrow + your {T}", "Kalem ödünç alma."),
        pe(W, "Önemli notlar için iyi kalem kullanmalısın.", f"You should use a good {T} for important notes.", "advice",
           f"use a good {T}", "Kalem kalitesi tavsiyesi."),
        pe(W, "Sınavda mavi kalem lazım.", f"I need a blue {T} for the exam.", "obligation",
           f"blue {T} + for the exam", "Sınav kalemi gereksinimi."),
        pe(W, "Kalem çantamda olabilir.", f"The {T} might be in my bag.", "possibility",
           f"in my bag", "Kayıp kalem arama."),
        pe(W, "Kalem yazmıyorsa başka birini al.", f"If the {T} doesn't write, get another one.", "conditional",
           f"doesn't write", "Yazmayan kalem senaryosu."),
        pe(W, "A: Kalemin var mı? B: Evet, al.", f"A: Do you have a {T}? B: Yes, here you go.", "dialogue",
           f"Do you have + a {T}", "Kalem isteme diyalogu."),
    ]


def _key_examples(W: str, T: str, pe: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    keys = f"{T}s" if T == "key" else T
    return [
        pe(W, "Ev anahtarım kayıp.", f"My house {keys} are missing.", "basic",
           f"My house {keys}", "Kayıp anahtar — çok yaygın senaryo."),
        pe(W, "Şu an kapıyı anahtarla açıyor.", f"He is unlocking the door with the {T}.", "present",
           f"unlocking + with the {T}", "unlock with a key."),
        pe(W, "Anahtarı masada unuttum.", f"I left the {keys} on the table.", "past",
           f"left + the {keys}", "Anahtarı unutmak."),
        pe(W, "Yarın yedek anahtar yaptıracağım.", f"I will make a spare {T} tomorrow.", "future",
           f"spare {T}", "Yedek anahtar yaptırma."),
        pe(W, "Anahtarları buldun mu?", f"Did you find the {keys}?", "question",
           f"find + the {keys}", "Anahtar arama sorusu."),
        pe(W, "Anahtarlarım yanımda değil.", f"I don't have my {keys} on me.", "negative",
           f"don't have + my {keys}", "Üzerinde anahtar olmama."),
        pe(W, "Anahtarları al.", f"Grab the {keys}, please.", "imperative",
           f"Grab + the {keys}", "Anahtarları al — grab the keys."),
        pe(W, "Anahtarları ödünç alabilir miyim?", f"Could I borrow your {keys}?", "polite_request",
           f"borrow + your {keys}", "Anahtar ödünç alma."),
        pe(W, "Her zaman yedek anahtar bulundurmalısın.", f"You should always have a spare {T}.", "advice",
           f"spare {T}", "Yedek anahtar tavsiyesi."),
        pe(W, "Kilidi değiştirmem lazım, anahtar işe yaramıyor.", f"I need to change the lock; the {T} doesn't work.", "obligation",
           f"the {T} doesn't work", "Anahtar/kilit sorunu."),
        pe(W, "Anahtar cebimde olabilir.", f"The {keys} might be in my pocket.", "possibility",
           f"in my pocket", "Anahtar arama."),
        pe(W, "Anahtar yoksa kapıyı çal.", f"If you don't have the {keys}, knock on the door.", "conditional",
           f"If you don't have + the {keys}", "Anahtarsız giriş senaryosu."),
        pe(W, "A: Anahtarlar nerede? B: Masada.", f"A: Where are the {keys}? B: On the table.", "dialogue",
           f"Where are + the {keys}", "Anahtar konumu diyalogu."),
    ]
