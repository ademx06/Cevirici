"""Merkezi telaffuz sözlüğü — Cümle Kur modülü için tutarlı okunuş."""
from __future__ import annotations

import re
from typing import Any

from education_engine import _simple_en_phonetic, pronounce_text, safe_str

# Oturum önbelleği: (lang, kelime) → {pronunciation_tr, ipa}
_SESSION: dict[tuple[str, str], dict[str, str]] = {}

# İngilizce temel kelime telaffuzları — ses temelli, tek standart
EN_CANONICAL: dict[str, str] = {
    "i": "ay",
    "i'm": "aym",
    "you": "yu",
    "your": "yor",
    "we": "vi",
    "they": "dey",
    "he": "hi",
    "she": "şi",
    "it": "it",
    "me": "mi",
    "my": "may",
    "the": "dı",
    "a": "e",
    "an": "en",
    "and": "end",
    "or": "or",
    "to": "tu",
    "of": "ov",
    "in": "in",
    "on": "on",
    "at": "et",
    "for": "for",
    "with": "with",
    "do": "du",
    "does": "daz",
    "don't": "dont",
    "doesn't": "dazent",
    "did": "did",
    "didn't": "didint",
    "can": "ken",
    "can't": "kant",
    "will": "vil",
    "won't": "vont",
    "would": "vud",
    "could": "kud",
    "should": "şud",
    "shall": "şal",
    "have": "hev",
    "has": "hez",
    "had": "hed",
    "haven't": "hevint",
    "is": "iz",
    "are": "ar",
    "am": "em",
    "was": "vaz",
    "were": "ver",
    "be": "bi",
    "love": "lav",
    "like": "layk",
    "want": "vant",
    "need": "nid",
    "get": "get",
    "make": "meyk",
    "take": "teyk",
    "give": "giv",
    "go": "gou",
    "come": "kam",
    "call": "kol",
    "carry": "keri",
    "drink": "drink",
    "eat": "iit",
    "work": "vork",
    "play": "pley",
    "coffee": "kofi",
    "tea": "ti",
    "water": "votır",
    "milk": "milk",
    "bag": "beg",
    "taxi": "tek-si",
    "menu": "men-yu",
    "music": "myu-zik",
    "kitchen": "ki-çın",
    "because": "bikoz",
    "nothing": "nathing",
    "need": "ni:d",
    "cook": "kuk",
    "market": "markit",
    "home": "houm",
    "there": "der",
    "book": "buk",
    "soda": "sou-da",
    "corn": "korn",
    "sweetcorn": "korn",
    "cola": "kou-la",
    "diet": "day-ıt",
    "can": "ken",
    "bottle": "bat-ıl",
    "regular": "reg-yu-lır",
    "usually": "yu-zhu-ali",
    "meal": "miil",
    "please": "pliz",
    "put": "put",
    "cups": "kaps",
    "clean": "klin",
    "move": "muv",
    "sat": "set",
    "waiting": "veyting",
    "bought": "bot",
    "where": "ver",
    "black": "blek",
    "tonight": "tunayt",
    "would": "vud",
    "like": "layk",
    "every": "evri",
    "morning": "mor-ning",
    "making": "meyking",
    "had": "hed",
    "two": "tu",
    "today": "tudey",
    "every": "evri",
    "day": "dey",
    "some": "sam",
    "please": "pliz",
    "thank": "thenk",
    "thanks": "thenks",
    "yes": "yes",
    "no": "nou",
    "not": "not",
    "very": "veri",
    "really": "rili",
    "good": "gud",
    "bad": "bed",
    "hot": "hat",
    "cold": "kould",
    "coming": "ka-ming",
    "aren't": "arent",
    "faucet": "fô-sıt",
    "tap": "tep",
    "leak": "li:k",
    "leaking": "li-king",
    "turn": "törn",
    "off": "of",
    "on": "on",
    "bathroom": "bat-rum",
    "kitchen": "ki-çın",
    "repair": "ri-per",
    "repaired": "ri-perd",
    "install": "in-stol",
    "replace": "ri-pleys",
    "fix": "fiks",
    "buy": "bay",
    "new": "nü",
    "car": "kar",
    "drive": "drayv",
    "park": "park",
    "garage": "ga-raj",
    "broken": "brou-kın",
    "happy": "hepi",
    "sad": "sed",
    "feel": "fiil",
    "seem": "siim",
    "looks": "luks",
    "harder": "hardır",
    "sundays": "san-deyz",
    "why": "vay",
    "could": "kud",
    "open": "open",
    "close": "klouz",
    "door": "dor",
    "window": "window",
    "help": "help",
    "bring": "bring",
    "show": "şou",
    "this": "dis",
    "pen": "pen",
    "here": "hir",
    "wait": "weyt",
    "minute": "minıt",
    "explain": "ikspleyn",
    "reservation": "rezervayşın",
    "reading": "ri-ding",
    "riding": "ray-ding",
    "shelf": "şelf",
    "ringing": "ring-ing",
    "locked": "lokt",
    "interesting": "intıresting",
    "finished": "finişt",
    "charge": "çarç",
    "answer": "ensır",
    "knock": "nok",
    "comfortable": "komfıtıbıl",
    "shoes": "şuz",
    "shoe": "şu",
    "forget": "for-get",
    "pair": "per",
    "wet": "vet",
    "rain": "reyn",
    "small": "smol",
    "feel": "fiil",
    "clear": "klir",
    "wipe": "wayp",
    "sit": "sit",
    "glass": "glaas",
    "glasses": "glaasız",
    "empty": "empti",
    "accidentally": "eksidentıli",
    "broke": "broyk",
    "fill": "fil",
    "washing": "voşing",
    "pour": "por",
    "collect": "kolekt",
    "broken": "browkın",
    "cold": "kold",
    "meal": "miil",
    "every": "evri",
    "dinner": "dinır",
}

EN_IPA: dict[str, str] = {
    "i": "/aɪ/",
    "love": "/lʌv/",
    "like": "/laɪk/",
    "don't": "/doʊnt/",
    "do": "/duː/",
    "you": "/juː/",
    "want": "/wɑːnt/",
    "can": "/kæn/",
    "have": "/hæv/",
    "a": "/ə/",
    "shall": "/ʃæl/",
    "get": "/ɡet/",
    "make": "/meɪk/",
    "call": "/kɔːl/",
    "carry": "/ˈkæri/",
    "coffee": "/ˈkɔːfi/",
    "water": "/ˈwɔːtər/",
    "some": "/sʌm/",
    "tea": "/tiː/",
    "bag": "/bæɡ/",
    "taxi": "/ˈtæksi/",
    "morning": "/ˈmɔːnɪŋ/",
    "drink": "/drɪŋk/",
    "music": "/ˈmjuːzɪk/",
    "menu": "/ˈmenjuː/",
    "milk": "/mɪlk/",
    "of": "/əv/",
    "with": "/wɪð/",
    "every": "/ˈevri/",
    "meal": "/miːl/",
    "soda": "/ˈsoʊ.də/",
    "corn": "/kɔːrn/",
    "glass": "/ɡlæs/",
    "the": "/ðə/",
    "eat": "/iːt/",
    "order": "/ˈɔːrdər/",
}

# Kalıp örnekleri için sabit kelime anlamları
EN_WORD_MEANINGS: dict[str, str] = {
    "some": "biraz / bazı",
    "water": "su",
    "make": "yapmak",
    "get": "almak / getirmek",
    "call": "aramak / çağırmak",
    "carry": "taşımak",
    "bag": "çanta",
    "taxi": "taksi",
    "tea": "çay",
    "music": "müzik",
    "milk": "süt",
    "menu": "menü",
    "soda": "gazoz",
    "corn": "mısır",
    "sweetcorn": "mısır",
    "maize": "mısır",
    "glass": "bardak / cam",
    "glasses": "bardaklar / gözlük",
    "empty": "boş",
    "cola": "kola",
    "diet": "diyet / light",
    "can": "kutu",
    "bottle": "şişe",
    "regular": "normal",
    "usually": "genellikle",
    "meal": "yemek",
    "cold": "soğuk",
    "morning": "sabah",
    "faucet": "musluk",
    "bathroom": "banyo",
    "leaking": "sızdırıyor",
    "leak": "sızmak / sızdırmak",
    "turn": "çevirmek",
    "repair": "tamir etmek",
    "fix": "tamir etmek / düzeltmek",
    "car": "araba",
    "garage": "garaj",
    "happy": "mutlu",
    "because": "çünkü",
    "nothing": "hiçbir şey",
    "cook": "pişirmek / yemek yapmak",
    "market": "market / pazar",
    "home": "ev",
    "window": "pencere",
    "door": "kapı",
    "book": "kitap",
    "phone": "telefon",
    "reading": "okumak",
    "riding": "binmek / sürmek",
    "open": "açmak",
    "close": "kapatmak",
    "shelf": "raf",
    "locked": "kilitli",
    "interesting": "ilginç",
    "ringing": "çalıyor",
    "charge": "şarj etmek",
    "answer": "cevaplamak / açmak",
    "knock": "çalmak",
    # Zamirler ve artikeller
    "i": "ben",
    "i'm": "ben …-yım",
    "you": "sen / siz",
    "your": "senin / sizin",
    "we": "biz",
    "they": "onlar",
    "he": "o (erkek)",
    "she": "o (kadın)",
    "it": "o (nesne)",
    "me": "beni / bana",
    "my": "benim",
    "his": "onun",
    "her": "onun (kadın)",
    "our": "bizim",
    "their": "onların",
    "the": "belirli artikel (the)",
    "a": "bir (belirsiz artikel)",
    "an": "bir (sesli harf öncesi)",
    # Yardımcı fiiller ve olumsuzluk
    "is": "dır / dir / -iyor",
    "am": "ım / -yim",
    "are": "dır / dir / -lar",
    "was": "idi / -dı",
    "were": "idiler / -diler",
    "be": "olmak",
    "isn't": "değil / yok",
    "aren't": "değiller / değil",
    "wasn't": "değildi",
    "weren't": "değillerdi",
    "don't": "…-mıyorum / …-mez",
    "doesn't": "…-miyor",
    "didn't": "…-medi",
    "can't": "…-emem / …-amaz",
    "won't": "…-meyecek",
    "haven't": "…-medim / yok",
    "not": "değil",
    # Edatlar ve bağlaçlar
    "of": "-ın / -nin (aitlik)",
    "with": "ile / birlikte",
    "in": "içinde / -de",
    "on": "üzerinde / -de",
    "at": "-de / -da",
    "to": "-e / -a",
    "for": "için",
    "from": "-den / -dan",
    "by": "tarafından / ile",
    "about": "hakkında",
    "into": "içine",
    "out": "dışarı / out of",
    "up": "yukarı",
    "down": "aşağı",
    "and": "ve",
    "or": "veya / ya da",
    "but": "ama",
    "because": "çünkü",
    "if": "eğer / -se",
    "so": "bu yüzden / öyle",
    # Sıklık ve zaman
    "every": "her",
    "usually": "genellikle",
    "always": "her zaman",
    "sometimes": "bazen",
    "never": "asla / hiç",
    "often": "sık sık",
    "today": "bugün",
    "yesterday": "dün",
    "tomorrow": "yarın",
    "now": "şimdi",
    "later": "sonra",
    "tonight": "bu gece",
    "morning": "sabah",
    "evening": "akşam",
    "night": "gece",
    "day": "gün",
    "week": "hafta",
    "year": "yıl",
    "meal": "yemek (öğün)",
    "dinner": "akşam yemeği",
    "lunch": "öğle yemeği",
    "breakfast": "kahvaltı",
    # Temel fiiller
    "drink": "içmek",
    "eat": "yemek",
    "have": "sahip olmak / almak",
    "has": "sahip / var (tekil)",
    "had": "vardı / aldı",
    "get": "almak / elde etmek",
    "go": "gitmek",
    "come": "gelmek",
    "do": "yapmak",
    "does": "yapar (tekil)",
    "did": "yaptı",
    "make": "yapmak",
    "take": "almak",
    "give": "vermek",
    "see": "görmek",
    "know": "bilmek",
    "think": "düşünmek",
    "say": "söylemek",
    "tell": "anlatmak / söylemek",
    "ask": "sormak",
    "use": "kullanmak",
    "find": "bulmak",
    "put": "koymak",
    "keep": "tutmak / saklamak",
    "let": "izin vermek",
    "try": "denemek",
    "leave": "ayrılmak / bırakmak",
    "call": "aramak / çağırmak",
    "bring": "getirmek",
    "buy": "satın almak",
    "bought": "aldı",
    "sell": "satmak",
    "pay": "ödemek",
    "work": "çalışmak",
    "play": "oynamak",
    "run": "koşmak",
    "walk": "yürümek",
    "sit": "oturmak",
    "sat": "oturdu",
    "stand": "ayakta durmak",
    "sleep": "uyumak",
    "wake": "uyanmak",
    "open": "açmak",
    "close": "kapatmak",
    "start": "başlamak",
    "stop": "durmak",
    "help": "yardım etmek",
    "wait": "beklemek",
    "look": "bakmak",
    "watch": "izlemek",
    "listen": "dinlemek",
    "speak": "konuşmak",
    "talk": "konuşmak",
    "read": "okumak",
    "write": "yazmak",
    "learn": "öğrenmek",
    "teach": "öğretmek",
    "love": "sevmek",
    "like": "sevmek / hoşlanmak",
    "want": "istemek",
    "need": "ihtiyaç duymak / gerekmek",
    "can": "-ebilmek",
    "could": "-ebilirdi / -ebilir mi",
    "will": "-ecek / -acak",
    "would": "-erdi / kibar kalıp",
    "should": "-meli / -malı",
    "shall": "-elim mi / -eceğim",
    "may": "-ebilir (izin)",
    "might": "olabilir / -ebilir",
    "must": "zorunda / -meli",
    # Bardak / soda bağlamı
    "fill": "doldurmak",
    "pour": "dökmek",
    "wash": "yıkamak",
    "washing": "yıkıyor",
    "dry": "kurulamak",
    "break": "kırmak",
    "broke": "kırdı",
    "broken": "kırık",
    "breaks": "kırılır",
    "raise": "kaldırmak",
    "hold": "tutmak",
    "collect": "toplamak",
    "accidentally": "yanlışlıkla / kazara",
    "empty": "boş",
    "full": "dolu",
    "careful": "dikkatli",
    "sparkling": "maden suyu (köpüklü)",
    "mineral": "mineral (sıfat: maden suyu)",
    "club": "kulüp / club soda",
    "baking": "pişirme / yemek",
    "soft": "yumuşak / gazlı (soft drink)",
    "pop": "gazlı içecek (US)",
    # Diğer sık kelimeler
    "there": "orada / var",
    "here": "burada",
    "this": "bu",
    "that": "şu / o",
    "these": "bunlar",
    "those": "şunlar / onlar",
    "what": "ne",
    "where": "nerede",
    "when": "ne zaman",
    "why": "neden",
    "who": "kim",
    "how": "nasıl",
    "how many": "kaç tane",
    "many": "çok / birçok",
    "much": "çok (sayılamaz)",
    "some": "biraz / bazı",
    "any": "herhangi / hiç",
    "all": "hepsi / tüm",
    "no": "hayır / hiç",
    "yes": "evet",
    "please": "lütfen",
    "thanks": "teşekkürler",
    "thank": "teşekkür",
    "sorry": "özür dilerim",
    "hello": "merhaba",
    "good": "iyi",
    "bad": "kötü",
    "new": "yeni",
    "old": "eski",
    "big": "büyük",
    "small": "küçük",
    "hot": "sıcak",
    "cold": "soğuk",
    "table": "masa",
    "kitchen": "mutfak",
    "living": "yaşam",
    "room": "oda",
    "another": "başka",
    "other": "diğer",
    "one": "bir",
    "two": "iki",
    "three": "üç",
    "first": "ilk / birinci",
    "last": "son",
    "again": "tekrar",
    "still": "hâlâ",
    "already": "zaten",
    "just": "sadece / az önce",
    "very": "çok",
    "really": "gerçekten",
    "also": "ayrıca",
    "too": "de / fazla",
    "only": "sadece",
    "more": "daha fazla",
    "less": "daha az",
    "than": "-den daha",
    "then": "sonra / o zaman",
    "well": "iyi / peki",
    "right": "doğru / sağ",
    "left": "sol",
    "up": "yukarı",
    "down": "aşağı",
    "off": "kapalı / -den uzak",
    "away": "uzak",
    "back": "geri",
    "over": "üzerinde / bitmiş",
    "under": "altında",
    "between": "arasında",
    "after": "sonra",
    "before": "önce",
    "during": "sırasında",
    "while": "iken / -ken",
    "until": "-e kadar",
    "since": "-den beri",
    "without": "-siz / olmadan",
    "through": "içinden / boyunca",
    "across": "karşısında / boyunca",
    "around": "etrafında",
    "near": "yakın",
    "far": "uzak",
    "inside": "içinde",
    "outside": "dışında",
    "together": "birlikte",
    "alone": "yalnız",
    "ready": "hazır",
    "sure": "emin",
    "maybe": "belki",
    "perhaps": "belki",
    "enough": "yeterli",
    "own": "kendi",
    "same": "aynı",
    "different": "farklı",
    "such": "böyle",
    "each": "her biri",
    "both": "her ikisi",
    "few": "birkaç",
    "little": "az / küçük",
    "lot": "çok",
    "things": "şeyler",
    "thing": "şey",
    "people": "insanlar",
    "person": "kişi",
    "man": "adam",
    "woman": "kadın",
    "child": "çocuk",
    "children": "çocuklar",
    "friend": "arkadaş",
    "family": "aile",
    "house": "ev",
    "home": "ev",
    "school": "okul",
    "store": "mağaza",
    "shop": "dükkan",
    "restaurant": "restoran",
    "office": "ofis",
    "park": "park",
    "street": "sokak",
    "city": "şehir",
    "country": "ülke",
    "world": "dünya",
    "time": "zaman",
    "money": "para",
    "job": "iş",
    "life": "hayat",
    "way": "yol / şekil",
    "place": "yer",
    "part": "parça",
    "kind": "tür / çeşit",
    "name": "isim",
    "number": "sayı",
    "problem": "problem",
    "question": "soru",
    "answer": "cevap",
    "idea": "fikir",
    "story": "hikaye",
    "game": "oyun",
    "food": "yemek",
    "fruit": "meyve",
    "vegetable": "sebze",
    "meat": "et",
    "bread": "ekmek",
    "cheese": "peynir",
    "egg": "yumurta",
    "rice": "pilav / pirinç",
    "sugar": "şeker",
    "salt": "tuz",
    "oil": "yağ",
    "butter": "tereyağı",
    "juice": "meyve suyu",
    "wine": "şarap",
    "beer": "bira",
    "ice": "buz",
    "cream": "krema",
    "chicken": "tavuk",
    "fish": "balık",
    "beef": "sığır eti",
    "pork": "domuz eti",
    "salad": "salata",
    "soup": "çorba",
    "cake": "pasta / kek",
    "cookie": "kurabiye",
    "chocolate": "çikolata",
    "candy": "şekerleme",
    "snack": "atıştırmalık",
    "party": "parti",
    "gift": "hediye",
    "price": "fiyat",
    "cost": "maliyet",
    "free": "ücretsiz",
    "cheap": "ucuz",
    "expensive": "pahalı",
    "fast": "hızlı",
    "slow": "yavaş",
    "easy": "kolay",
    "hard": "zor / sert",
    "important": "önemli",
    "interesting": "ilginç",
    "beautiful": "güzel",
    "nice": "güzel / hoş",
    "great": "harika",
    "fine": "iyi / tamam",
    "okay": "tamam",
    "ok": "tamam",
    "wrong": "yanlış",
    "true": "doğru",
    "false": "yanlış",
    "possible": "mümkün",
    "impossible": "imkansız",
    "available": "mevcut / uygun",
    "busy": "meşgul",
    "tired": "yorgun",
    "hungry": "aç",
    "thirsty": "susuz",
    "sick": "hasta",
    "healthy": "sağlıklı",
    "young": "genç",
    "strong": "güçlü",
    "weak": "zayıf",
    "clean": "temiz",
    "dirty": "kirli",
    "quiet": "sessiz",
    "loud": "yüksek sesli",
    "dark": "karanlık",
    "light": "ışık / hafif",
    "warm": "ılık",
    "cool": "serin / havalı",
    "rain": "yağmur",
    "snow": "kar",
    "sun": "güneş",
    "wind": "rüzgar",
    "weather": "hava",
    "dog": "köpek",
    "cat": "kedi",
    "bird": "kuş",
    "horse": "at",
    "color": "renk",
    "red": "kırmızı",
    "blue": "mavi",
    "green": "yeşil",
    "yellow": "sarı",
    "black": "siyah",
    "white": "beyaz",
    "brown": "kahverengi",
    "gray": "gri",
    "grey": "gri",
    "pink": "pembe",
    "orange": "turuncu",
    "purple": "mor",
    "head": "kafa",
    "hand": "el",
    "hands": "eller",
    "eye": "göz",
    "eyes": "gözler",
    "face": "yüz",
    "body": "vücut",
    "heart": "kalp",
    "hair": "saç",
    "clothes": "kıyafet",
    "shirt": "gömlek",
    "pants": "pantolon",
    "dress": "elbise",
    "coat": "mont",
    "hat": "şapka",
    "bag": "çanta",
    "key": "anahtar",
    "keys": "anahtarlar",
    "money": "para",
    "card": "kart",
    "ticket": "bilet",
    "photo": "fotoğraf",
    "picture": "resim",
    "video": "video",
    "computer": "bilgisayar",
    "internet": "internet",
    "email": "e-posta",
    "message": "mesaj",
    "news": "haber",
    "movie": "film",
    "song": "şarkı",
    "sport": "spor",
    "team": "takım",
    "ball": "top",
    "test": "sınav / test",
    "class": "sınıf / ders",
    "teacher": "öğretmen",
    "student": "öğrenci",
    "doctor": "doktor",
    "hospital": "hastane",
    "medicine": "ilaç",
    "pain": "ağrı",
    "accident": "kaza",
    "fire": "ateş / yangın",
    "water": "su",
    "air": "hava",
    "earth": "dünya / toprak",
    "tree": "ağaç",
    "flower": "çiçek",
    "garden": "bahçe",
    "sea": "deniz",
    "beach": "plaj",
    "mountain": "dağ",
    "river": "nehir",
    "lake": "göl",
    "island": "ada",
    "road": "yol",
    "bridge": "köprü",
    "building": "bina",
    "floor": "kat / zemin",
    "wall": "duvar",
    "ceiling": "tavan",
    "stairs": "merdiven",
    "elevator": "asansör",
    "bathroom": "banyo",
    "bedroom": "yatak odası",
    "bed": "yatak",
    "sofa": "kanepe",
    "chair": "sandalye",
    "desk": "çalışma masası",
    "lamp": "lamba",
    "light": "ışık",
    "clock": "saat",
    "watch": "kol saati",
    "calendar": "takvim",
    "map": "harita",
    "language": "dil",
    "word": "kelime",
    "sentence": "cümle",
    "letter": "harf / mektup",
    "page": "sayfa",
    "line": "satır / çizgi",
    "point": "nokta / puan",
    "end": "son",
    "begin": "başlamak",
    "beginning": "başlangıç",
    "middle": "orta",
    "side": "yan",
    "top": "üst",
    "bottom": "alt",
    "front": "ön",
    "next": "sonraki",
    "previous": "önceki",
    "early": "erken",
    "late": "geç",
    "soon": "yakında",
    "ago": "önce",
    "once": "bir kez",
    "twice": "iki kez",
    "ever": "hiç (soru)",
    "yet": "henüz",
    "even": "bile",
    "quite": "oldukça",
    "almost": "neredeyse",
}

WORD_ROLE_TR: dict[str, str] = {
    "i": "özne", "you": "özne", "he": "özne", "she": "özne", "we": "özne", "they": "özne", "it": "özne",
    "a": "artikel", "an": "artikel", "the": "artikel",
    "is": "yardımcı fiil", "am": "yardımcı fiil", "are": "yardımcı fiil", "was": "yardımcı fiil", "were": "yardımcı fiil",
    "don't": "olumsuz", "doesn't": "olumsuz", "didn't": "olumsuz", "not": "olumsuz", "isn't": "olumsuz",
    "of": "edat", "with": "edat", "in": "edat", "on": "edat", "at": "edat", "to": "edat", "for": "edat",
    "from": "edat", "by": "edat", "about": "edat",
    "can": "yardımcı fiil", "could": "yardımcı fiil", "will": "yardımcı fiil", "would": "yardımcı fiil",
    "should": "yardımcı fiil", "may": "yardımcı fiil", "might": "yardımcı fiil", "must": "yardımcı fiil",
    "every": "sıfat/zarf", "some": "sıfat", "many": "sıfat", "much": "sıfat", "cold": "sıfat", "hot": "sıfat",
    "please": "kibarlık", "yes": "cevap", "no": "cevap",
    "drink": "fiil", "eat": "fiil", "have": "fiil", "get": "fiil", "make": "fiil", "order": "fiil",
    "glass": "isim", "water": "isim", "meal": "isim", "coffee": "isim", "soda": "isim",
}

TEACHING_HEADER_RE = re.compile(
    r"^[\s🧠]*Nasıl kuruldu\??[\s:—-]*\n?",
    re.I,
)


def tokenize_en(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def _article_pron(next_word: str) -> str:
    """a/an — sonraki kelimenin sesine göre."""
    if not next_word:
        return "e"
    first = next_word.lower()[0]
    if first in "aeiou":
        return "ey"
    return "e"


def register_word(
    lang: str,
    word: str,
    pronunciation_tr: str,
    ipa: str = "",
) -> None:
    w = safe_str(word).strip()
    p = safe_str(pronunciation_tr).strip()
    if not w or not p:
        return
    _SESSION[(lang, w.lower())] = {
        "pronunciation_tr": p,
        "ipa": safe_str(ipa).strip(),
    }


def get_word(lang: str, word: str) -> dict[str, str]:
    """Tek kelime telaffuzu — oturum → sözlük → yedek."""
    raw = safe_str(word).strip()
    if not raw:
        return {"word": word, "pronunciation_tr": "", "ipa": ""}

    low = raw.lower()
    key = (lang, low)
    if key in _SESSION:
        cached = _SESSION[key]
        return {"word": raw, "pronunciation_tr": cached["pronunciation_tr"], "ipa": cached.get("ipa", "")}

    if lang == "en":
        pron = EN_CANONICAL.get(low)
        if not pron:
            fallback = _simple_en_phonetic(raw)
            pron = fallback.split()[0] if fallback else low
        ipa = EN_IPA.get(low, "")
        return {"word": raw, "pronunciation_tr": pron, "ipa": ipa}

    fb = pronounce_text(raw, lang)
    return {"word": raw, "pronunciation_tr": fb, "ipa": ""}


def build_sentence(
    text: str,
    lang: str = "en",
    focus_words: list[str] | None = None,
) -> dict[str, Any]:
    """Cümle telaffuzu — kelime sözlüğünden birleştirilir (LLM kullanılmaz)."""
    text = safe_str(text).strip()
    if not text:
        return {"pronunciation_tr": "", "ipa": "", "word_pronunciations": []}

    if lang != "en":
        fb = pronounce_text(text, lang)
        return {"pronunciation_tr": fb, "ipa": "", "word_pronunciations": []}

    tokens = tokenize_en(text)
    word_parts: list[dict[str, str]] = []
    pron_words: list[str] = []
    ipa_parts: list[str] = []

    for i, tok in enumerate(tokens):
        low = tok.lower()
        if low == "a" and i + 1 < len(tokens):
            pron = _article_pron(tokens[i + 1])
        elif low == "an" and i + 1 < len(tokens):
            pron = "en"
        else:
            info = get_word(lang, tok)
            pron = info["pronunciation_tr"]
        pron_words.append(pron)
        info = get_word(lang, tok)
        word_parts.append({
            "word": tok,
            "pronunciation_tr": pron if low in ("a", "an") else info["pronunciation_tr"],
            "ipa": info.get("ipa", ""),
        })
        if info.get("ipa"):
            ipa_parts.append(info["ipa"])

    sentence_pron = " ".join(pron_words)
    sentence_pron = (
        sentence_pron
        .replace("du yu", "du-yu")
        .replace("dont layk", "dont-layk")
        .replace("ken ay", "ken-ay")
    )
    if text and text[0].isupper() and sentence_pron:
        sentence_pron = sentence_pron[0].upper() + sentence_pron[1:]

    sentence_ipa = " ".join(ipa_parts) if ipa_parts else ""
    return {
        "pronunciation_tr": sentence_pron[:160],
        "ipa": sentence_ipa[:120],
        "word_pronunciations": word_parts,
    }


# Doğal konuşma telaffuzu — kelime kelime birleştirmeden (linking, weak forms)
SENTENCE_NATURAL_EN: dict[str, str] = {
    "the faucet is in the kitchen.": "Dı fô-sıt iz in dı ki-çın.",
    "the faucet is leaking.": "Dı fô-sıt iz li-king.",
    "turn off the faucet.": "Törn of dı fô-sıt.",
    "could you turn off the faucet?": "Kud yu törn of dı fô-sıt?",
    "why is the faucet leaking?": "Vay iz dı fô-sıt li-king?",
    "i need to buy a new kitchen faucet.": "Ay ni:d-tı bay e nü ki-çın fô-sıt.",
    "i need to have the faucet repaired.": "Ay ni:d-tı hev dı fô-sıt ri-perd.",
    "the bathroom faucet is leaking.": "Dı bat-rum fô-sıt iz li-king.",
    "the table is in the kitchen.": "Dı tey-bıl iz in dı ki-çın.",
    "i need to go to the market because i have nothing to cook at home.": (
        "Ay ni:d-tı gou tı dı markit bikoz ay hev nathing tı kuk ət houm."
    ),
    "i drink coffee every morning.": "Ay drink kofi evri mor-ning.",
    "can i have a coffee?": "Ken ay hev e kofi?",
    "can you bring me a coffee?": "Ken yu bring mi e kofi",
    "can you open the door?": "Ken yu open dı door",
    "can you help me?": "Ken yu help mi",
    "can you close the window?": "Ken yu klouz dı window",
    "can you bring me some water?": "Ken yu bring mi sam wotır",
    "can you show me this?": "Ken yu şou mi dis",
    "can you give me a pen?": "Ken yu giv mi e pen",
    "can you come here?": "Ken yu kam hir",
    "can you wait a minute?": "Ken yu weyt e minıt",
    "can you explain this to me?": "Ken yu ikspleyn dis tu mi",
    "can you make a reservation?": "Ken yu meyk e rezervayşın",
    "could you open the door?": "Kud yu open dı door",
}


def _sentence_key(text: str) -> str:
    return re.sub(r"\s+", " ", safe_str(text).strip().lower())


def build_sentence_natural(text: str, lang: str = "en") -> str:
    """Cümle telaffuzu — doğal bağlantılar; kelime tablosundan ayrı."""
    text = safe_str(text).strip()
    if not text:
        return ""
    if lang == "en":
        key = _sentence_key(text)
        if key in SENTENCE_NATURAL_EN:
            pron = SENTENCE_NATURAL_EN[key]
            if text[0].isupper():
                return pron[0].upper() + pron[1:]
            return pron
    base = build_sentence(text, lang)["pronunciation_tr"]
    links = (
        ("turn of", "törn-of"),
        ("törn of", "törn-of"),
        ("ni:d tu", "ni:d-tı"),
        ("nid tu", "ni:d-tı"),
        ("hev tu", "hev-tı"),
        ("tu bay", "tı-bay"),
        ("tı gou", "tı-gou"),
        ("gou tu", "gou-tu"),
        ("tu dı", "tu-dı"),
        ("iz li-king", "iz-li-king"),
        ("iz in", "iz-in"),
        ("kud yu", "kud-yu"),
        ("vay iz", "vay-iz"),
        ("dont layk", "dont-layk"),
        ("du yu", "du-yu"),
    )
    pron = base.lower()
    for a, b in links:
        pron = pron.replace(a, b)
    if text[0].isupper():
        pron = pron[0].upper() + pron[1:]
    return pron[:160]


def build_pronunciation_bundle(
    text: str,
    lang: str = "en",
    focus_words: list[str] | None = None,
) -> dict[str, Any]:
    """Kelime tablosu + doğal cümle telaffuzu birlikte."""
    words_bundle = build_sentence(text, lang, focus_words)
    return {
        "pronunciation_tr": build_sentence_natural(text, lang),
        "ipa": words_bundle.get("ipa", ""),
        "word_pronunciations": words_bundle.get("word_pronunciations") or [],
    }


def strip_teaching_header(text: str) -> str:
    """UI'da tekrarlanan 🧠 Nasıl kuruldu? başlığını metinden çıkar."""
    t = safe_str(text).strip()
    return TEACHING_HEADER_RE.sub("", t).strip()


def word_meaning_tr(word: str) -> str:
    return EN_WORD_MEANINGS.get(word.lower(), "")


def word_role_tr(word: str) -> str:
    return WORD_ROLE_TR.get(word.lower(), "")


def detect_new_words(
    target_sentence: str,
    focus_words: list[str],
    known_words: set[str] | None = None,
) -> list[dict[str, str]]:
    """Cümledeki odak dışı önemli kelimeleri bul."""
    known = {w.lower() for w in (known_words or set())}
    known.update(w.lower() for w in focus_words)
    # Temel gramer kelimeleri — açıklama gerektirmez
    skip = {
        "i", "you", "we", "they", "he", "she", "it", "a", "an", "the",
        "do", "does", "did", "can", "will", "would", "shall", "is", "are",
        "am", "was", "were", "in", "on", "at", "to", "of", "for", "with",
        "don't", "doesn't", "didn't", "not", "the", "and", "or",
    }
    tokens = tokenize_en(target_sentence)
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for tok in tokens:
        low = tok.lower()
        if low in skip or low in known or low in seen:
            continue
        meaning = word_meaning_tr(low)
        if not meaning and low not in EN_CANONICAL:
            continue
        if not meaning:
            meaning = EN_WORD_MEANINGS.get(low, "")
        if not meaning:
            continue
        info = get_word("en", tok)
        result.append({
            "word": tok,
            "meaning_tr": meaning,
            "pronunciation_tr": info["pronunciation_tr"],
            "ipa": info.get("ipa", ""),
        })
        seen.add(low)
    return result[:6]


def enrich_pattern_card(
    card: dict[str, Any] | str,
    lang: str,
    focus_words: list[str],
    known_words: set[str] | None = None,
) -> dict[str, Any]:
    """Kalıp örneğini mini öğrenme kartına dönüştür."""
    if isinstance(card, str):
        card = {"target": card.strip()}
    if not isinstance(card, dict):
        return {"target": safe_str(card)}

    target = safe_str(card.get("target")).strip()
    if not target:
        return dict(card)

    bundle = build_pronunciation_bundle(target, lang, focus_words)
    out: dict[str, Any] = {
        "target": target,
        "tr": safe_str(card.get("tr")).strip(),
        "pronunciation_tr": bundle["pronunciation_tr"],
        "ipa": bundle.get("ipa") or "",
        "word_pronunciations": bundle.get("word_pronunciations") or [],
    }

    new_words = card.get("new_words")
    if isinstance(new_words, list) and new_words:
        enriched_nw: list[dict[str, str]] = []
        for nw in new_words:
            if not isinstance(nw, dict):
                continue
            w = safe_str(nw.get("word")).strip()
            if not w:
                continue
            info = get_word(lang, w)
            enriched_nw.append({
                "word": w,
                "meaning_tr": safe_str(nw.get("meaning_tr")).strip() or word_meaning_tr(w),
                "pronunciation_tr": info["pronunciation_tr"],
                "ipa": info.get("ipa", ""),
                "example_target": safe_str(nw.get("example_target")).strip(),
                "example_tr": safe_str(nw.get("example_tr")).strip(),
            })
        out["new_words"] = enriched_nw
    else:
        out["new_words"] = detect_new_words(target, focus_words, known_words)

    return out


def enrich_pattern_examples(
    examples: list[Any],
    lang: str,
    focus_words: list[str],
    known_words: set[str] | None = None,
    max_examples: int = 4,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ex in (examples or [])[:max_examples]:
        card = enrich_pattern_card(ex, lang, focus_words, known_words)
        if card.get("target"):
            result.append(card)
    return result


def apply_pronunciation_to_example(
    ex: dict[str, Any],
    lang: str,
    focus_words: list[str] | None = None,
) -> dict[str, Any]:
    """Örnek cümleye merkezi telaffuz uygula — LLM değerlerinin üzerine yazar."""
    target = safe_str(ex.get("target")).strip()
    if not target:
        return ex
    bundle = build_pronunciation_bundle(target, lang, focus_words)
    ex["pronunciation_tr"] = bundle["pronunciation_tr"]
    ex["ipa"] = bundle.get("ipa") or ex.get("ipa") or ""
    ex["word_pronunciations"] = bundle["word_pronunciations"]
    if ex.get("how_it_is_formed_tr"):
        ex["how_it_is_formed_tr"] = strip_teaching_header(ex["how_it_is_formed_tr"])
    return ex
