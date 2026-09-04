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
    "called": "kold",
    "named": "neymd",
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
    "cook": "kuk",
    "market": "markit",
    "home": "houm",
    "there": "der",
    "book": "buk",
    "invoice": "invoyce",
    "gum": "gam",
    "honey": "hani",
    "spread": "sprid",
    "drizzle": "drizıl",
    "taste": "teyst",
    "dilute": "daylut",
    "collect": "kolekt",
    "melon": "melon",
    "trap": "trep",
    "locust": "loukıst",
    "moon": "mun",
    "honeydew": "hanid-yu",
    "raw": "ro",
    "organic": "organik",
    "jar": "car",
    "spoon": "spun",
    # Abstract / academic / common words
    "development": "divelopment",
    "personal": "pörsonıl",
    "support": "sıport",
    "promote": "proumout",
    "focus": "foukıs",
    "opportunity": "apırtuniti",
    "experience": "ikspiyriyıns",
    "progress": "prougrıs",
    "success": "sıkses",
    "happiness": "hepinıs",
    "invest": "in-vest",
    "industry": "indıstri",
    "appropriate": "ıproupriyıt",
    "suggest": "sıcest",
    "arrange": "ıreync",
    "professional": "prıfeşınıl",
    "environment": "invayırnmınt",
    "government": "gavırnmınt",
    "company": "kampıni",
    "important": "importınt",
    "information": "informeyşın",
    "technology": "teknolıci",
    "situation": "siçueyşın",
    "decision": "disijın",
    "relationship": "rileyşınşip",
    "community": "kımyuniti",
    "difference": "difrıns",
    "available": "ıveylıbıl",
    "necessary": "nesıseri",
    "possible": "pasıbıl",
    "beautiful": "byutifıl",
    "interesting": "intıresting",
    "especially": "ispeşıli",
    "absolutely": "ebsılutli",
    "wonderful": "vandırfıl",
    "understand": "andırstend",
    "remember": "rimembır",
    "consider": "kınsidır",
    "continue": "kıntinyu",
    "together": "tugeder",
    "comfortable": "kamfırtıbıl",
    "difficult": "difikılt",
    "different": "difrınt",
    "excellent": "eksılınt",
    "probably": "prabıbli",
    "actually": "ekçuıli",
    "question": "kvesçın",
    "answer": "ensır",
    "problem": "prablım",
    "family": "femıli",
    "children": "çildrın",
    "country": "kantri",
    "example": "igzempıl",
    "between": "bitvin",
    "through": "tru",
    "another": "ınader",
    "change": "çeync",
    "school": "skul",
    "people": "pipıl",
    "something": "samthing",
    "everything": "evrithing",
    "nothing": "nathing",
    "anything": "enithing",
    "someone": "samvan",
    "everyone": "evrivan",
    "already": "olredi",
    "always": "olveys",
    "sometimes": "samtaymz",
    "usually": "yujuıli",
    "quickly": "kvikli",
    "slowly": "slouli",
    "really": "rili",
    "finally": "faynıli",
    "head": "hed",
    "one": "van",
    "give": "giv",
    "chewing": "çiwing",
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
    "leak": "lik",
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
    "open": "ou-pın",
    "close": "klouz",
    "door": "dor",
    "window": "vin-dou",
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

# Kelime dersi kelimeleri — Türkçe fonetik (İngilizce yazım DEĞİL)
LESSON_VOCAB_CANONICAL: dict[str, str] = {
    "cigarette": "sigıret",
    "cigarettes": "sigırets",
    "smoke": "smouk",
    "smoking": "smou-king",
    "smoked": "smoukt",
    "tobacco": "tı-bekou",
    "lighter": "lay-tır",
    "regularly": "regyulırli",
    "optician": "optişın",
    "lost": "lost",
    "wear": "ver",
    "wearing": "ver-ing",
    "cleaning": "kli-ning",
    "pair": "per",
    "glasses": "gla-sız",
    "glass": "glaas",
    "umbrella": "ambre-lı",
    "wallet": "vol-lit",
    "socks": "soks",
    "sock": "sok",
    "knife": "nayf",
    "pillow": "pilou",
    "bicycle": "bay-sikıl",
    "bike": "bayk",
    "radio": "rey-di-ou",
    "perfume": "pır-fyum",
    "entertainment": "entır-teyn-mınt",
    "quiet": "kvay-ıt",
    "quickly": "kvik-li",
    "cat": "ket",
    "apple": "ep-ıl",
    "table": "tey-bıl",
    "chair": "çeır",
    "sofa": "sou-fı",
    "bed": "bed",
    "room": "rum",
    "kitchen": "ki-çın",
    "bathroom": "bath-rum",
    "bedroom": "bed-rum",
    "living": "li-ving",
    "television": "tele-vi-zhın",
    "phone": "foun",
    "computer": "kım-pyu-tır",
    "picture": "pik-çır",
    "photo": "fou-tou",
    "money": "ma-ni",
    "key": "ki",
    "keys": "kiiz",
    "lock": "lak",
    "shirt": "şört",
    "pants": "pents",
    "dress": "dres",
    "jacket": "cek-it",
    "coat": "kout",
    "hat": "het",
    "bag": "beg",
    "backpack": "bek-pek",
    "medicine": "medi-sın",
    "hospital": "has-pi-tıl",
    "doctor": "dok-tır",
    "nurse": "nörs",
    "school": "skul",
    "student": "styu-dınt",
    "teacher": "ti-çır",
    "lesson": "le-sın",
    "homework": "houm-vörk",
    "exam": "ig-zem",
    "question": "kves-çın",
    "answer": "en-sır",
    "problem": "prob-lım",
    "idea": "ay-di-ı",
    "story": "sto-ri",
    "movie": "mu-vi",
    "film": "film",
    "song": "song",
    "game": "geym",
    "sport": "sport",
    "football": "fut-bol",
    "basketball": "bas-ket-bol",
    "tennis": "te-nis",
    "swim": "svim",
    "swimming": "svi-ming",
    "travel": "tre-vıl",
    "trip": "trip",
    "vacation": "vey-key-şın",
    "holiday": "ha-li-dey",
    "passport": "pas-port",
    "ticket": "ti-kit",
    "airport": "er-port",
    "plane": "pleyn",
    "train": "treyn",
    "bus": "bas",
    "station": "stey-şın",
    "street": "strit",
    "city": "si-ti",
    "country": "kan-tri",
    "world": "vörld",
    "people": "pi-pıl",
    "person": "pör-sın",
    "man": "men",
    "woman": "vou-mın",
    "child": "çayld",
    "children": "çil-dren",
    "baby": "bey-bi",
    "family": "fem-i-li",
    "friend": "frend",
    "neighbor": "ney-bır",
    "boss": "bos",
    "colleague": "ka-lig",
    "customer": "kas-tı-mır",
    "price": "pray-s",
    "cheap": "çip",
    "expensive": "ik-spen-siv",
    "pay": "pey",
    "paid": "peyd",
    "sell": "sel",
    "sold": "sould",
    "shop": "şop",
    "store": "stor",
    "restaurant": "res-tı-rant",
    "menu": "men-yu",
    "bill": "bil",
    "tip": "tip",
    "delicious": "di-li-şıs",
    "tasty": "tey-sti",
    "sweet": "svit",
    "sour": "sau-ır",
    "salt": "solt",
    "sugar": "şu-gır",
    "bread": "bred",
    "cheese": "çiz",
    "butter": "ba-tır",
    "egg": "eg",
    "eggs": "egz",
    "meat": "mit",
    "chicken": "çi-kın",
    "fish": "fiş",
    "rice": "rays",
    "pasta": "pas-tı",
    "salad": "se-lıd",
    "soup": "sup",
    "fruit": "frut",
    "vegetable": "veç-tı-bıl",
    "banana": "bı-ne-nı",
    "orange": "o-rınc",
    "grape": "greyp",
    "strawberry": "stro-be-ri",
    "chocolate": "çok-lıt",
    "candy": "ken-di",
    "ice": "ays",
    "cream": "krim",
    "yogurt": "yog-ırt",
    "juice": "jus",
    "beer": "bir",
    "wine": "vayn",
    "indoor": "in-dor",
    "indoors": "in-dorz",
    "outdoor": "aut-dor",
    "outside": "aut-sayd",
    "inside": "in-sayd",
    "stress": "stres",
    "stressed": "strest",
    "pocket": "pak-it",
    "pack": "pek",
    "quit": "kvit",
    "lit": "lit",
    "light": "layt",
    "put": "put",
    "out": "aut",
    "indoor": "in-dor",
    "store": "stor",
    "two": "tu",
    "three": "thri",
    "four": "for",
    "five": "fayv",
    "six": "siks",
    "seven": "se-vın",
    "eight": "eyt",
    "nine": "nayn",
    "ten": "ten",
    "eleven": "i-lev-ın",
    "twelve": "tvelv",
    "twenty": "tven-ti",
    "hundred": "han-dır",
    "thousand": "thau-zınd",
    "million": "mil-yın",
    "half": "haf",
    "quarter": "kwo-rır",
    "minute": "mi-nit",
    "hour": "au-ır",
    "second": "se-kınd",
    "week": "vik",
    "month": "manth",
    "year": "yir",
    "monday": "man-dey",
    "tuesday": "tuz-dey",
    "wednesday": "venz-dey",
    "thursday": "thörz-dey",
    "friday": "fray-dey",
    "saturday": "setır-dey",
    "sunday": "san-dey",
    "january": "jan-yu-e-ri",
    "february": "fe-bru-e-ri",
    "march": "març",
    "april": "ey-prıl",
    "may": "mey",
    "june": "jun",
    "july": "ju-lay",
    "august": "o-gast",
    "september": "sep-tem-bır",
    "october": "ok-tou-bır",
    "november": "nou-vem-bır",
    "december": "di-sem-bır",
    "spring": "spring",
    "summer": "sa-mır",
    "autumn": "o-tım",
    "fall": "fol",
    "winter": "vin-tır",
    "weather": "ve-dır",
    "rain": "reyn",
    "snow": "snou",
    "wind": "vind",
    "cloud": "kloud",
    "sun": "san",
    "moon": "mun",
    "star": "star",
    "sky": "skay",
    "earth": "örth",
    "fire": "fay-ır",
    "water": "vo-tır",
    "air": "er",
    "tree": "tri",
    "flower": "flau-ır",
    "garden": "gar-dın",
    "beach": "bich",
    "mountain": "mau-ntın",
    "river": "ri-vır",
    "lake": "leyk",
    "sea": "si",
    "ocean": "ou-şın",
    "island": "ay-lınd",
    "bridge": "brij",
    "building": "bil-ding",
    "office": "o-fis",
    "company": "kam-pı-ni",
    "job": "cab",
    "work": "vörk",
    "working": "vör-king",
    "worker": "vör-kır",
    "meeting": "mii-ding",
    "project": "pra-jekt",
    "email": "i-meyl",
    "message": "me-sic",
    "letter": "le-tır",
    "news": "nyuz",
    "paper": "pey-pır",
    "magazine": "meg-ı-ziin",
    "newspaper": "nyuz-pey-pır",
    "internet": "in-tır-net",
    "website": "veb-sayt",
    "password": "pas-vörd",
    "account": "ı-kount",
    "login": "log-in",
    "download": "daun-loud",
    "upload": "ap-loud",
    "search": "sörç",
    "find": "faynd",
    "found": "faund",
    "lost": "lost",
    "lose": "luz",
    "win": "vin",
    "won": "van",
    "fail": "feyl",
    "pass": "pas",
    "failed": "feyld",
    "passed": "past",
    "try": "tray",
    "tried": "trayd",
    "start": "star-t",
    "started": "star-tid",
    "finish": "fi-niş",
    "finished": "fi-nişt",
    "continue": "kın-ti-nyu",
    "stop": "stop",
    "stopped": "stopt",
    "wait": "veyt",
    "waiting": "vey-ding",
    "stay": "stey",
    "leave": "liv",
    "left": "left",
    "arrive": "ı-rayv",
    "arrived": "ı-rayvd",
    "return": "ri-törn",
    "returned": "ri-törnd",
    "send": "send",
    "sent": "sent",
    "receive": "ri-siv",
    "received": "ri-sivd",
    "offer": "o-fır",
    "offered": "o-fırd",
    "accept": "ık-sept",
    "accepted": "ık-sep-tid",
    "refuse": "ri-fyuz",
    "refused": "ri-fyuzd",
    "agree": "ı-gri",
    "disagree": "dis-ı-gri",
    "believe": "bi-liv",
    "remember": "ri-mem-bır",
    "forget": "for-get",
    "forgot": "for-got",
    "understand": "an-dır-stend",
    "understood": "an-dır-stud",
    "explain": "iks-pleyn",
    "explained": "iks-pleynd",
    "mean": "min",
    "meant": "ment",
    "seem": "siim",
    "look": "luk",
    "looked": "lukt",
    "watch": "voç",
    "watched": "voçt",
    "listen": "lis-ın",
    "heard": "hörd",
    "hear": "hir",
    "speak": "spiik",
    "spoke": "spouk",
    "talk": "tok",
    "talked": "tokt",
    "tell": "tel",
    "told": "tould",
    "say": "sey",
    "said": "sed",
    "ask": "esk",
    "asked": "eskt",
    "answer": "en-sır",
    "answered": "en-sırd",
    "reply": "ri-play",
    "replied": "ri-playd",
    "shout": "şaut",
    "whisper": "vis-pır",
    "laugh": "laf",
    "cry": "kray",
    "smile": "smayl",
    "kiss": "kis",
    "hug": "hag",
    "touch": "taç",
    "hold": "hould",
    "held": "held",
    "carry": "ke-ri",
    "carried": "ke-rid",
    "push": "puş",
    "pull": "pul",
    "throw": "throu",
    "threw": "thru",
    "catch": "keç",
    "caught": "kot",
    "drop": "drop",
    "dropped": "dropt",
    "pick": "pik",
    "picked": "pikt",
    "choose": "çuz",
    "chose": "çouz",
    "change": "çeync",
    "changed": "çeyncd",
    "move": "muv",
    "moved": "muvd",
    "turn": "törn",
    "turned": "törnd",
    "follow": "fa-lou",
    "followed": "fa-loud",
    "lead": "lid",
    "led": "led",
    "grow": "grou",
    "grew": "gru",
    "build": "bild",
    "built": "bilt",
    "break": "breyk",
    "broke": "brouk",
    "fix": "fiks",
    "fixed": "fikst",
    "repair": "ri-per",
    "repaired": "ri-perd",
    "clean": "klin",
    "cleaned": "klind",
    "wash": "voş",
    "washed": "voşt",
    "dry": "dray",
    "dried": "drayd",
    "cook": "kuk",
    "cooked": "kukt",
    "boil": "boyl",
    "fried": "frayd",
    "cut": "kat",
    "mix": "miks",
    "mixed": "mikst",
    "add": "ed",
    "remove": "ri-muv",
    "cover": "ka-vır",
    "open": "ou-pın",
    "opened": "ou-pınd",
    "close": "klouz",
    "closed": "klouzd",
    "lock": "lak",
    "locked": "lakt",
    "unlock": "an-lak",
    "enter": "en-tır",
    "exit": "eg-zit",
    "join": "joyn",
    "meet": "miit",
    "met": "met",
    "visit": "vi-zit",
    "visited": "vi-zitid",
    "invite": "in-vayt",
    "invited": "in-vay-tid",
    "welcome": "vel-kım",
    "introduce": "in-trı-dyus",
    "name": "neym",
    "named": "neymd",
    "called": "kold",
    "live": "liv",
    "lived": "livd",
    "life": "layf",
    "die": "day",
    "died": "dayd",
    "death": "deth",
    "born": "born",
    "birth": "börth",
    "age": "eyc",
    "old": "ould",
    "young": "yang",
    "new": "nyu",
    "big": "big",
    "small": "smol",
    "large": "larj",
    "little": "li-tıl",
    "long": "long",
    "short": "şort",
    "tall": "tol",
    "high": "hay",
    "low": "lou",
    "wide": "vayd",
    "narrow": "ne-rou",
    "deep": "dip",
    "shallow": "she-lou",
    "thick": "thik",
    "thin": "thin",
    "heavy": "he-vi",
    "light": "layt",
    "fast": "fest",
    "slow": "slou",
    "quick": "kvik",
    "easy": "ii-zi",
    "hard": "hard",
    "difficult": "di-fi-kılt",
    "simple": "sim-pıl",
    "complex": "kam-pleks",
    "important": "im-por-tınt",
    "necessary": "ne-sı-se-ri",
    "possible": "pa-sı-bıl",
    "impossible": "im-pa-sı-bıl",
    "sure": "şur",
    "certain": "sör-tın",
    "maybe": "mey-bey",
    "probably": "pra-bı-bli",
    "definitely": "de-fi-nit-li",
    "always": "ol-weyz",
    "never": "ne-vır",
    "sometimes": "sam-taymz",
    "often": "o-fın",
    "usually": "yu-zhu-vi",
    "rarely": "rer-li",
    "already": "ol-re-di",
    "yet": "yet",
    "still": "stil",
    "again": "ı-gen",
    "once": "vans",
    "twice": "tvays",
    "more": "mor",
    "most": "moust",
    "less": "les",
    "least": "liist",
    "enough": "i-naf",
    "too": "tu",
    "also": "ol-sou",
    "only": "oun-li",
    "just": "cast",
    "even": "ii-vın",
    "almost": "ol-moust",
    "about": "ı-baut",
    "around": "ı-raund",
    "between": "bi-tviin",
    "among": "ı-mang",
    "through": "thru",
    "across": "ı-kros",
    "over": "ou-vır",
    "under": "an-dır",
    "above": "ı-bav",
    "below": "bi-lou",
    "behind": "bi-haynd",
    "front": "frant",
    "back": "bek",
    "next": "nekst",
    "last": "last",
    "first": "först",
    "second": "se-kınd",
    "third": "thörd",
    "other": "a-dır",
    "another": "ı-na-dır",
    "same": "seym",
    "different": "di-fı-rınt",
    "similar": "si-mı-lır",
    "own": "oun",
    "each": "iç",
    "every": "ev-ri",
    "all": "ol",
    "both": "bouth",
    "none": "nan",
    "nothing": "na-thing",
    "something": "sam-thing",
    "anything": "e-ni-thing",
    "everything": "ev-ri-thing",
    "someone": "sam-van",
    "anyone": "e-ni-van",
    "everyone": "ev-ri-van",
    "nobody": "nou-ba-di",
    "somebody": "sam-ba-di",
    "anybody": "e-ni-ba-di",
    "everybody": "ev-ri-ba-di",
    "somewhere": "sam-ver",
    "anywhere": "e-ni-ver",
    "everywhere": "ev-ri-ver",
    "nowhere": "nou-ver",
    "here": "hir",
    "there": "der",
    "where": "ver",
    "when": "ven",
    "why": "vay",
    "how": "hav",
    "what": "vat",
    "which": "viç",
    "who": "hu",
    "whom": "hum",
    "whose": "huz",
}

EN_CANONICAL.update(LESSON_VOCAB_CANONICAL)

# Edge TTS en-US-JennyNeural nasıl okuyorsa Türkçe harflerle birebir o ses.
# NURSE ünlüsü (/ɝ/ /ɚ/) → ö; oo/u → u; th → d/t. İngilizce yazımı olduğu gibi bırakma.
JENNY_TTS_CANONICAL: dict[str, str] = {
    "bird": "börd",
    "birds": "bördz",
    "girl": "görl",
    "girls": "görlz",
    "her": "hör",
    "were": "vör",
    "word": "vörd",
    "words": "vördz",
    "work": "vörk",
    "works": "vörks",
    "worked": "vörkt",
    "working": "vörking",
    "world": "vörld",
    "worse": "vörs",
    "worst": "vörst",
    "worth": "vörth",
    "first": "först",
    "third": "thörd",
    "thirty": "thörti",
    "birthday": "börthdey",
    "birth": "börth",
    "shirt": "şört",
    "church": "çörç",
    "turn": "törn",
    "turned": "törnd",
    "hurt": "hört",
    "heard": "hörd",
    "learn": "lörn",
    "learned": "lörnd",
    "learning": "lörning",
    "earth": "örth",
    "early": "örli",
    "search": "sörç",
    "person": "pörsın",
    "perfect": "pörfekt",
    "certain": "sörtın",
    "purpose": "pörpıs",
    "further": "fördır",
    "return": "ritörn",
    "nurse": "nörs",
    "purple": "pörpıl",
    "circle": "sörkıl",
    "chirp": "çörp",
    "chirped": "çörpt",
    "chirping": "çörping",
    "sir": "sör",
    "stir": "sör",
    "dirty": "dörti",
    "with": "vid",
    "blue": "blu",
    "took": "tuk",
    "breath": "breth",
    "toward": "tıword",
    "towards": "tıwordz",
    "instead": "insted",
    "fly": "flay",
    "flying": "flaying",
    "away": "evey",
    "tilt": "tilt",
    "tilted": "tiltid",
    "slight": "slayt",
    "slightly": "slaytli",
    "side": "sayd",
    "invite": "invayt",
    "inviting": "invayting",
    "soar": "sor",
    "soared": "sord",
    "into": "intu",
    "forget": "forget",
    "forgetting": "forgeting",
    "color": "kalar",
    "colour": "kalar",
    "colorful": "kalarfıl",
    "colourful": "kalarfıl",
    "butterfly": "baterflay",
    "butterflies": "baterflayz",
    "began": "bigen",
    "begin": "bigin",
    "chase": "çeys",
    "chased": "çeyst",
    "after": "aftır",
    "these": "diz",
    "those": "douz",
    "this": "dis",
    "that": "det",
    "mysterious": "mistirias",
    "wing": "ving",
    "wings": "vingz",
    "village": "vilic",
    "hollow": "halou",
    "stood": "stud",
    "fairy": "feri",
    "tale": "teyl",
    "tales": "teylz",
    "storybook": "storibuk",
    "sparkle": "sparkıl",
    "sparkling": "sparkling",
    "bright": "brayt",
    "brightly": "braytli",
    "land": "lend",
    "landed": "lendid",
    "shoulder": "şouldır",
    "whisper": "vispır",
    "whispered": "vispırd",
    "ear": "ir",
    "waiting": "veyting",
    "filled": "fild",
    "mother": "madır",
    "father": "fadır",
    "toy": "toy",
    "toys": "toyz",
    "carve": "karv",
    "carved": "karvd",
    "wood": "vud",
    "drew": "dru",
    "came": "keym",
    "page": "peyc",
    "pages": "peyciz",
    "magical": "mecikıl",
    "magic": "mecik",
    "edge": "ec",
    "from": "fram",
    "step": "step",
    "held": "held",
    "head": "hed",
    "little": "litıl",
    "old": "ould",
    "book": "buk",
    "sky": "skay",
    "follow": "falou",
    "followed": "faloud",
    "picture": "pikçır",
    "every": "evri",
    "life": "layf",
    "up": "ap",
    "on": "an",
    "of": "ov",
    "and": "end",
    "the": "dı",
    "a": "e",
    "an": "en",
    "to": "tu",
    "for": "for",
    "as": "ez",
    "if": "if",
    "its": "its",
    "in": "in",
    "at": "et",
    "very": "veri",
    "when": "ven",
    "picked": "pikt",
    "will": "vil",
    "tell": "tel",
    "your": "yor",
    "you": "yu",
    "this": "dis",
    "is": "iz",
    "be": "bi",
    "new": "nu",
    "day": "dey",
    "on": "an",
}
EN_CANONICAL.update(JENNY_TTS_CANONICAL)

PHONETIC_MAX = 2500

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
    "invoice": "/ˈɪnvɔɪs/",
    "honey": "/ˈhʌni/",
    "spread": "/spred/",
    "drizzle": "/ˈdrɪzəl/",
    "taste": "/teɪst/",
    "dilute": "/daɪˈluːt/",
    "collect": "/kəˈlekt/",
    "melon": "/ˈmelən/",
    "trap": "/træp/",
    "locust": "/ˈloʊkəst/",
    "moon": "/muːn/",
    "honeydew": "/ˈhʌniˌduː/",
    "raw": "/rɔː/",
    "organic": "/ɔːrˈɡænɪk/",
    "jar": "/dʒɑːr/",
    "spoon": "/spuːn/",
}

# Eksik kelimeler — EN_CANONICAL ile tutarlı IPA
EN_IPA.update({
    "i'm": "/aɪm/",
    "we": "/wiː/",
    "they": "/ðeɪ/",
    "he": "/hiː/",
    "she": "/ʃiː/",
    "it": "/ɪt/",
    "me": "/miː/",
    "my": "/maɪ/",
    "your": "/jɔːr/",
    "is": "/ɪz/",
    "are": "/ɑːr/",
    "am": "/æm/",
    "was": "/wʌz/",
    "were": "/wɜːr/",
    "be": "/biː/",
    "to": "/tuː/",
    "in": "/ɪn/",
    "on": "/ɒn/",
    "at": "/æt/",
    "for": "/fɔːr/",
    "and": "/ænd/",
    "or": "/ɔːr/",
    "not": "/nɒt/",
    "will": "/wɪl/",
    "would": "/wʊd/",
    "could": "/kʊd/",
    "should": "/ʃʊd/",
    "need": "/niːd/",
    "go": "/ɡoʊ/",
    "come": "/kʌm/",
    "book": "/bʊk/",
    "table": "/ˈteɪbəl/",
    "chair": "/tʃer/",
    "kitchen": "/ˈkɪtʃɪn/",
    "home": "/hoʊm/",
    "there": "/ðer/",
    "here": "/hɪr/",
    "this": "/ðɪs/",
    "that": "/ðæt/",
    "what": "/wʌt/",
    "where": "/wer/",
    "when": "/wen/",
    "why": "/waɪ/",
    "how": "/haʊ/",
    "who": "/huː/",
    "good": "/ɡʊd/",
    "bad": "/bæd/",
    "two": "/tuː/",
    "today": "/təˈdeɪ/",
    "please": "/pliːz/",
    "thanks": "/θæŋks/",
    "thank": "/θæŋk/",
    "yes": "/jes/",
    "no": "/noʊ/",
    "called": "/kɔːld/",
    "named": "/neɪmd/",
    "has": "/hæz/",
    "had": "/hæd/",
    "did": "/dɪd/",
    "does": "/dʌz/",
    "don't": "/doʊnt/",
    "can't": "/kænt/",
    "work": "/wɜːrk/",
    "play": "/pleɪ/",
    "read": "/riːd/",
    "write": "/raɪt/",
    "help": "/help/",
    "show": "/ʃoʊ/",
    "open": "/ˈoʊpən/",
    "close": "/kloʊz/",
    "door": "/dɔːr/",
    "window": "/ˈwɪndoʊ/",
    "market": "/ˈmɑːrkɪt/",
    "because": "/bɪˈkʌz/",
    "nothing": "/ˈnʌθɪŋ/",
    "cook": "/kʊk/",
    "faucet": "/ˈfɔːsɪt/",
    "leak": "/liːk/",
    "leaking": "/ˈliːkɪŋ/",
    "turn": "/tɜːrn/",
    "off": "/ɔːf/",
    "bought": "/bɔːt/",
    "buy": "/baɪ/",
    "new": "/nuː/",
    "car": "/kɑːr/",
    "happy": "/ˈhæpi/",
    "every": "/ˈevri/",
    "day": "/deɪ/",
    "morning": "/ˈmɔːrnɪŋ/",
    "night": "/naɪt/",
    "very": "/ˈveri/",
    "really": "/ˈrɪəli/",
    "hot": "/hɒt/",
    "cold": "/koʊld/",
    "bottle": "/ˈbɒtəl/",
    "cup": "/kʌp/",
    "cups": "/kʌps/",
    "phone": "/foʊn/",
    "called": "/kɔːld/",
})

LESSON_VOCAB_IPA: dict[str, str] = {
    "cigarette": "/ˌsɪɡəˈret/",
    "cigarettes": "/ˌsɪɡəˈrets/",
    "smoke": "/smoʊk/",
    "smoking": "/ˈsmoʊkɪŋ/",
    "smoked": "/smoʊkt/",
    "tobacco": "/təˈbækoʊ/",
    "glasses": "/ˈɡlæsɪz/",
    "umbrella": "/ʌmˈbrelə/",
    "wallet": "/ˈwɒlɪt/",
    "socks": "/sɒks/",
    "knife": "/naɪf/",
    "pillow": "/ˈpɪloʊ/",
    "bicycle": "/ˈbaɪsɪkəl/",
    "perfume": "/pərˈfjuːm/",
    "entertainment": "/ˌentərˈteɪnmənt/",
    "quiet": "/ˈkwaɪət/",
    "quickly": "/ˈkwɪkli/",
    "apple": "/ˈæpəl/",
    "table": "/ˈteɪbəl/",
    "chair": "/tʃer/",
    "window": "/ˈwɪndoʊ/",
    "picture": "/ˈpɪktʃər/",
    "restaurant": "/ˈrestrɒnt/",
    "chocolate": "/ˈtʃɔːklət/",
    "vegetable": "/ˈvedʒtəbəl/",
    "interesting": "/ˈɪntrəstɪŋ/",
    "comfortable": "/ˈkʌmftəbəl/",
    "beautiful": "/ˈbjuːtɪfəl/",
    "important": "/ɪmˈpɔːrtənt/",
    "different": "/ˈdɪfərənt/",
    "understand": "/ˌʌndərˈstænd/",
    "question": "/ˈkwestʃən/",
    "answer": "/ˈænsər/",
    "hospital": "/ˈhɒspɪtəl/",
    "computer": "/kəmˈpjuːtər/",
    "television": "/ˈtelɪvɪʒən/",
    "chicken": "/ˈtʃɪkɪn/",
    "chocolate": "/ˈtʃɔːklət/",
    "breakfast": "/ˈbrekfəst/",
    "dinner": "/ˈdɪnər/",
    "lunch": "/lʌntʃ/",
    "weather": "/ˈweðər/",
    "daughter": "/ˈdɔːtər/",
    "schedule": "/ˈskedʒuːl/",
    "queue": "/kjuː/",
    "laughter": "/ˈlæftər/",
    "through": "/θruː/",
    "thought": "/θɔːt/",
    "enough": "/ɪˈnʌf/",
    "cough": "/kɒf/",
    "laugh": "/læf/",
    "night": "/naɪt/",
    "language": "/ˈlæŋɡwɪdʒ/",
    "garage": "/ɡəˈrɑːʒ/",
    "education": "/ˌedʒuˈkeɪʃən/",
    "information": "/ˌɪnfərˈmeɪʃən/",
    "situation": "/ˌsɪtʃuˈeɪʃən/",
    "pronunciation": "/prəˌnʌnsiˈeɪʃən/",
    "quit": "/kwɪt/",
    "pocket": "/ˈpɒkɪt/",
    "indoors": "/ˌɪnˈdɔːrz/",
    "outdoors": "/ˌaʊtˈdɔːrz/",
    "lighter": "/ˈlaɪtər/",
    "pack": "/pæk/",
}

EN_IPA.update(LESSON_VOCAB_IPA)

# Soyut / akademik kelimeler — eksik IPA
EN_IPA.update({
    "development": "/dɪˈveləpmənt/",
    "personal": "/ˈpɜːrsənəl/",
    "support": "/səˈpɔːrt/",
    "promote": "/prəˈmoʊt/",
    "encourage": "/ɪnˈkɜːrɪdʒ/",
    "focus": "/ˈfoʊkəs/",
    "achieve": "/əˈtʃiːv/",
    "opportunity": "/ˌɑːpərˈtuːnəti/",
    "experience": "/ɪkˈspɪriəns/",
    "progress": "/ˈprɑːɡres/",
    "success": "/səkˈses/",
    "happiness": "/ˈhæpɪnəs/",
    "invest": "/ɪnˈvest/",
    "industry": "/ˈɪndəstri/",
    "appropriate": "/əˈproʊpriət/",
    "suggest": "/səˈdʒest/",
    "arrange": "/əˈreɪndʒ/",
    "professional": "/prəˈfeʃənəl/",
    "environment": "/ɪnˈvaɪrənmənt/",
    "government": "/ˈɡʌvərnmənt/",
    "company": "/ˈkʌmpəni/",
    "important": "/ɪmˈpɔːrtənt/",
    "information": "/ˌɪnfərˈmeɪʃən/",
    "technology": "/tekˈnɒlədʒi/",
    "decision": "/dɪˈsɪʒən/",
    "relationship": "/rɪˈleɪʃənʃɪp/",
    "community": "/kəˈmjuːnəti/",
    "difference": "/ˈdɪfrəns/",
    "available": "/əˈveɪləbəl/",
    "necessary": "/ˈnesəseri/",
    "beautiful": "/ˈbjuːtɪfəl/",
    "interesting": "/ˈɪntrəstɪŋ/",
    "understand": "/ˌʌndərˈstænd/",
    "remember": "/rɪˈmembər/",
    "consider": "/kənˈsɪdər/",
    "continue": "/kənˈtɪnjuː/",
    "together": "/təˈɡeðər/",
    "comfortable": "/ˈkʌmfərtəbəl/",
    "difficult": "/ˈdɪfɪkəlt/",
    "different": "/ˈdɪfrənt/",
    "excellent": "/ˈeksələnt/",
    "probably": "/ˈprɑːbəbli/",
    "actually": "/ˈæktʃuəli/",
    "question": "/ˈkwestʃən/",
    "answer": "/ˈænsər/",
    "problem": "/ˈprɑːbləm/",
    "family": "/ˈfæməli/",
    "children": "/ˈtʃɪldrən/",
    "country": "/ˈkʌntri/",
    "example": "/ɪɡˈzæmpəl/",
    "between": "/bɪˈtwiːn/",
    "through": "/θruː/",
    "another": "/əˈnʌðər/",
    "change": "/tʃeɪndʒ/",
    "school": "/skuːl/",
    "people": "/ˈpiːpəl/",
    "something": "/ˈsʌmθɪŋ/",
    "everything": "/ˈevriθɪŋ/",
    "anything": "/ˈeniθɪŋ/",
    "someone": "/ˈsʌmwʌn/",
    "everyone": "/ˈevriwʌn/",
    "already": "/ɔːlˈredi/",
    "always": "/ˈɔːlweɪz/",
    "sometimes": "/ˈsʌmtaɪmz/",
    "quickly": "/ˈkwɪkli/",
    "slowly": "/ˈsloʊli/",
    "finally": "/ˈfaɪnəli/",
    "head": "/hed/",
    "one": "/wʌn/",
})

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
    "invoice": "fatura",
    "gum": "sakız",
    "honey": "bal",
    "spread": "sürmek",
    "drizzle": "damlatmak",
    "taste": "tatmak",
    "dilute": "sulandırmak",
    "melon": "kavun",
    "trap": "tuzak",
    "locust": "çekirge",
    "moon": "ay",
    "wear": "takmak / giymek",
    "wearing": "takıyor / giyiyor",
    "worn": "takılmış / giyilmiş",
    "put": "koymak / takmak",
    "take": "almak / çıkarmak",
    "off": "çıkarmak / kapalı",
    "clean": "temizlemek",
    "cleaning": "temizlemek / temizlik",
    "lose": "kaybetmek",
    "lost": "kaybetti / kayıp",
    "find": "bulmak",
    "found": "buldu / bulundu",
    "break": "kırmak",
    "broke": "kırdı",
    "broken": "kırık",
    "wipe": "silmek",
    "pair": "çift",
    "regularly": "düzenli olarak",
    "optician": "gözlükçü",
    "smoke": "içmek (sigara) / duman",
    "smoking": "sigara içmek",
    "smoked": "içti (sigara)",
    "cigarette": "sigara",
    "cigarettes": "sigaralar",
    "light": "yakmak / ışık",
    "quit": "bırakmak",
    "every": "her",
    "day": "gün",
    "help": "yardım etmek",
    "please": "lütfen",
    "outside": "dışarıda",
    "should": "…-meli / -malı",
    "need": "ihtiyaç duymak",
    "buy": "satın almak",
    "bought": "satın aldı",
    "raw": "saf / işlenmemiş",
    "organic": "organik",
    "jar": "kavanoz",
    "spoon": "kaşık",
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
    "which": "hangi",
    "bus": "otobüs",
    "while": "iken / sırasında",
    "during": "sırasında",
    "through": "içinden / boyunca",
    "against": "karşı",
    "without": "olmadan",
    "between": "arasında",
    "among": "arasında",
    "until": "-e kadar",
    "since": "-den beri",
    "almost": "neredeyse",
    "already": "zaten",
    "still": "hâlâ",
    "even": "bile",
    "really": "gerçekten",
    "quite": "oldukça",
    "enough": "yeterince",
    "each": "her biri",
    "both": "ikisi de",
    "few": "birkaç",
    "many": "birçok",
    "most": "çoğu",
    "own": "kendi",
    "same": "aynı",
    "such": "böyle",
    "these": "bunlar",
    "those": "şunlar",
    "something": "bir şey",
    "anything": "herhangi bir şey",
    "nothing": "hiçbir şey",
    "everything": "her şey",
    "someone": "birisi",
    "anyone": "herhangi biri",
    "everyone": "herkes",
    "somewhere": "bir yerde",
    "anywhere": "herhangi bir yerde",
    "everywhere": "her yerde",
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


def _normalize_pron_tr(pron: str) -> str:
    """IPA'yı at; ö/ü/ş/ç/ı/ğ Jenny sesini yazmak için kalır (bird=börd)."""
    p = safe_str(pron).strip()
    if not p:
        return ""
    if re.search(r"[ɑæəɪʊɔʌθðʃʒŋˈˌː]", p):
        return ""
    return p.replace(":", "").strip()


def _pron_matches_english(pron: str, english: str) -> bool:
    """Okunuş İngilizce yazımla aynı mı (hatalı gösterim)."""
    p = re.sub(r"[^a-z]", "", pron.lower())
    e = re.sub(r"[^a-z]", "", english.lower())
    if not p or not e:
        return False
    return p == e


def _ed_pron(base: str) -> str:
    core = re.sub(r"[^a-zöüışçğ]", "", base.lower())
    if core.endswith(("t", "d")):
        return base + "id"
    if core.endswith(("k", "p", "s", "ş", "ç", "f")):
        return base + "t"
    return base + "d"


def _s_pron(base: str) -> str:
    core = re.sub(r"[^a-zöüışçğ]", "", base.lower())
    if core.endswith(("s", "z", "ş", "ç", "c", "x")):
        return base + "iz"
    if core.endswith(("k", "p", "t", "f")):
        return base + "s"
    return base + "z"


def _canon_pron(low: str) -> str:
    raw = EN_CANONICAL.get(low, "")
    return _normalize_pron_tr(raw) or raw


def _en_inflected_pron(low: str) -> str | None:
    """Sözlük kökünden -ed/-ing/-s — her yeni cümlede TTS ile aynı kalsın."""
    if low in EN_CANONICAL:
        return None
    if low.endswith("'s") and low[:-2] in EN_CANONICAL:
        return _s_pron(_canon_pron(low[:-2]))
    pairs: list[tuple[str, str]] = []
    if low.endswith("ing") and len(low) > 5:
        stem = low[:-3]
        pairs.extend(((stem, "ing"), (stem + "e", "ing")))
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            pairs.append((stem[:-1], "ing"))
    if low.endswith("ed") and len(low) > 3:
        stem = low[:-2]
        pairs.extend(((stem, "ed"), (stem + "e", "ed")))
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            pairs.append((stem[:-1], "ed"))
        if stem.endswith("i"):
            pairs.append((stem[:-1] + "y", "ed"))
    if low.endswith("ies") and len(low) > 4:
        pairs.append((low[:-3] + "y", "s"))
    if low.endswith("es") and len(low) > 3:
        pairs.append((low[:-2], "s"))
    if low.endswith("s") and not low.endswith("ss") and len(low) > 2:
        pairs.append((low[:-1], "s"))
    if low.endswith("ly") and len(low) > 4:
        pairs.append((low[:-2], "ly"))
    seen: set[str] = set()
    for stem, kind in pairs:
        if not stem or stem in seen or stem not in EN_CANONICAL:
            continue
        seen.add(stem)
        base = _canon_pron(stem)
        if not base:
            continue
        if kind == "ing":
            return base + "ing"
        if kind == "ed":
            return _ed_pron(base)
        if kind == "s":
            return _s_pron(base)
        if kind == "ly":
            return base + "li"
    return None


def _en_g2p_jenny(word: str) -> str:
    """Sözlükte yoksa bile Jenny sesine Türkçe harf — tek hikâyeye özel değil."""
    t = word.lower()
    if t in ("here", "hire", "fire", "tired", "iron"):
        t = t.replace("ire", "ayır").replace("ere", "ir")
    else:
        t = t.replace("earth", "örth").replace("heard", "hörd")
        t = t.replace("learn", "lörn").replace("early", "örli")
        t = t.replace("search", "sörç").replace("pearl", "pörl")
        t = t.replace("world", "vörld").replace("worth", "vörth")
        t = t.replace("worse", "vörs").replace("worst", "vörst")
        t = t.replace("word", "vörd").replace("work", "vörk")
        t = t.replace("earn", "örn")
        t = re.sub(r"ir(?=[dltpkmncs]|$)", "ör", t)
        t = re.sub(r"(?<![o])ur(?=[ntdkpbflmgcs]|$)", "ör", t)
    t = t.replace("through", "thru").replace("though", "dou")
    t = t.replace("tion", "şın").replace("sion", "jın")
    t = t.replace("ough", "of").replace("ight", "ayt").replace("eau", "ou")
    t = t.replace("wh", "v")
    t = t.replace("th", "t")
    t = t.replace("ph", "f").replace("qu", "kv")
    t = t.replace("ch", "ç").replace("sh", "ş").replace("ck", "k")
    t = re.sub(r"^c(?=[eiy])", "s", t)
    t = t.replace("kn", "n").replace("wr", "r")
    t = t.replace("oo", "u").replace("ee", "i")
    t = t.replace("ea", "i")
    t = t.replace("ay", "ey").replace("ai", "ey")
    t = t.replace("ow", "ou").replace("ou", "au")
    t = t.replace("oi", "oy")
    t = re.sub(r"a([bcdfgklmnprstv])e$", r"ey\1", t)
    t = re.sub(r"i([bcdfgklmnprstv])e$", r"ay\1", t)
    t = re.sub(r"o([bcdfgklmnprstv])e$", r"ou\1", t)
    if t.endswith("y") and len(t) > 1:
        vowels = re.findall(r"[aeiouö]", t[:-1])
        t = t[:-1] + ("ay" if len(vowels) <= 1 else "i")
    t = re.sub(r"le$", "ıl", t)
    t = re.sub(r"er$", "ır", t)
    t = t.replace("w", "v")
    t = t.replace("c", "k").replace("x", "ks")
    t = t.replace("q", "k")
    return t


def _resolve_en_phonetic(word: str) -> str:
    """Türkçe fonetik okunuş — TTS (Jenny) ile aynı ses; düz İngilizce yazım yok."""
    raw = safe_str(word).strip()
    low = raw.lower()
    if low in EN_CANONICAL:
        return _canon_pron(low) or EN_CANONICAL[low]

    inflected = _en_inflected_pron(low)
    if inflected:
        return inflected

    g2p = _en_g2p_jenny(low)
    if g2p and not _pron_matches_english(g2p, low):
        return g2p

    simple = _normalize_pron_tr(_simple_en_phonetic(raw))
    if simple and not _pron_matches_english(simple, low):
        return simple

    return g2p or simple or low


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
        pron = _resolve_en_phonetic(raw)
        ipa = EN_IPA.get(low, "")
        return {"word": raw, "pronunciation_tr": pron, "ipa": ipa}

    fb = pronounce_text(raw, lang)
    return {"word": raw, "pronunciation_tr": fb, "ipa": ""}


# Gürcüce / Kiril / Arapça → Türkçe okunuş (LLM yok, anında)
# EkaNeural nasıl okuyorsa Türkçe harf: ხ=kh (hışırtı), ყ=q (kalın k)
_KA_ROMA = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "j", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "ğ", "ყ": "q", "შ": "ş", "ჩ": "ç", "ც": "ts", "ძ": "dz",
    "წ": "ts", "ჭ": "ç", "ხ": "kh", "ჯ": "c", "ჰ": "h",
    " ": " ", ",": ",", ".": ".", "!": "!", "?": "?", ":": ":", ";": ";",
    "«": '"', "»": '"', "—": "—", "-": "-", "„": '"', "“": '"',
}
_KA_MTAVRULI_OFF = 0x1C90 - 0x10D0
_RU_ROMA = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "ye", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ç", "ш": "ş", "щ": "şç", "ъ": "",
    "ы": "ı", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_AR_ROMA = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "s", "ج": "c", "ح": "h", "خ": "h",
    "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "ş", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "ğ", "ف": "f", "ق": "k",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "u", "ي": "i",
    "ى": "a", "ة": "e", "أ": "e", "إ": "i", "آ": "a", "ء": "", "ئ": "i",
    "ؤ": "u", "َ": "e", "ِ": "i", "ُ": "u", "ً": "en", "ٌ": "un", "ٍ": "in",
    "ّ": "", "ْ": "", " ": " ", "،": ",", "؟": "?", "ـ": "",
}


def romanize_for_tr_reader(text: str, lang: str) -> str:
    """Yabancı yazıyı Türkçe harflerle oku — sözlük, LLM yok."""
    t = safe_str(text).strip()
    if not t:
        return ""
    if lang == "ka":
        out = []
        for ch in t:
            o = ord(ch)
            if 0x1C90 <= o <= 0x1CBF:
                ch = chr(o - _KA_MTAVRULI_OFF)
            if ch in _KA_ROMA:
                out.append(_KA_ROMA[ch])
            elif ch.isascii():
                out.append(ch)
        return re.sub(r"\s+", " ", "".join(out)).strip()[:PHONETIC_MAX]
    if lang == "ru":
        chars: list[str] = []
        for ch in t:
            low = ch.lower()
            mapped = _RU_ROMA.get(low, ch)
            if ch.isupper() and mapped:
                mapped = mapped[0].upper() + mapped[1:]
            chars.append(mapped)
        return re.sub(r"\s+", " ", "".join(chars)).strip()
    if lang == "ar":
        out = "".join(_AR_ROMA.get(ch, ch if ch.isascii() else "") for ch in t)
        return re.sub(r"\s+", " ", out).strip()
    return ""


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
        fb = romanize_for_tr_reader(text, lang)
        if not fb:
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
            "ipa": info.get("ipa") or EN_IPA.get(low, ""),
        })
        ipa_val = info.get("ipa") or EN_IPA.get(low, "")
        if ipa_val:
            ipa_parts.append(ipa_val.strip("/"))

    sentence_pron = " ".join(pron_words)
    sentence_pron = (
        sentence_pron
        .replace("du yu", "du-yu")
        .replace("dont layk", "dont-layk")
        .replace("ken ay", "ken-ay")
    )
    if text and text[0].isupper() and sentence_pron:
        sentence_pron = sentence_pron[0].upper() + sentence_pron[1:]

    sentence_ipa = " ".join(f"/{p}/" for p in ipa_parts if p) if ipa_parts else ""
    return {
        "pronunciation_tr": sentence_pron[:PHONETIC_MAX],
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
    return pron[:PHONETIC_MAX]


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
    low = safe_str(word).strip().lower()
    if not low:
        return ""
    if low in EN_WORD_MEANINGS:
        return EN_WORD_MEANINGS[low]
    # Basit çekim düşürme — cleaning→clean, lost→lose, regularly→regular
    for suf, repl in (
        ("ying", "y"),
        ("ing", ""),
        ("ied", "y"),
        ("ed", ""),
        ("ies", "y"),
        ("es", ""),
        ("s", ""),
        ("ly", ""),
    ):
        if low.endswith(suf) and len(low) > len(suf) + 2:
            stem = low[: -len(suf)] + repl
            if stem in EN_WORD_MEANINGS:
                return EN_WORD_MEANINGS[stem]
            if suf == "ed" and (low[:-2] + "e") in EN_WORD_MEANINGS:
                return EN_WORD_MEANINGS[low[:-2] + "e"]
            if suf == "ing" and (low[:-3] + "e") in EN_WORD_MEANINGS:
                return EN_WORD_MEANINGS[low[:-3] + "e"]
    return ""


_MEANING_BATCH_CACHE: dict[str, str] = {}


def batch_word_meanings_tr(words: list[str]) -> dict[str, str]:
    """Eksik Türkçe anlamları tek Google çağrısıyla doldur — LLM yok, hızlı."""
    from html import unescape
    from urllib.error import URLError
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    out: dict[str, str] = {}
    need: list[str] = []
    seen: set[str] = set()
    for raw in words:
        low = safe_str(raw).strip().lower()
        if not low or low in seen:
            continue
        seen.add(low)
        known = word_meaning_tr(low)
        if known:
            out[low] = known
            continue
        if low in _MEANING_BATCH_CACHE:
            out[low] = _MEANING_BATCH_CACHE[low]
            continue
        need.append(low)
    if not need:
        return out
    # En fazla 24 kelime — satır satır çevir
    chunk = need[:24]
    payload = "\n".join(chunk)
    try:
        url = (
            "https://translate.google.com/m?sl=en&tl=tr"
            f"&q={quote(payload)}"
        )
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=3.5) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
        match = re.search(r'class="result-container">([^<]+)', page)
        if not match:
            match = re.search(r'<div class="t0">([^<]+)', page)
        if match:
            lines = unescape(match.group(1)).replace("\r", "").split("\n")
            lines = [ln.strip() for ln in lines if ln.strip()]
            if len(lines) == len(chunk):
                for w, tr in zip(chunk, lines):
                    if tr and tr.lower() != w:
                        _MEANING_BATCH_CACHE[w] = tr
                        out[w] = tr
            elif len(lines) == 1 and len(chunk) == 1:
                tr = lines[0]
                if tr and tr.lower() != chunk[0]:
                    _MEANING_BATCH_CACHE[chunk[0]] = tr
                    out[chunk[0]] = tr
    except (URLError, TimeoutError, OSError, ValueError):
        pass
    return out


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
