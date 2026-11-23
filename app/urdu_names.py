"""Names in Urdu and English script: one person, two spellings.

A CNIC prints the name in both scripts (the old green card only in Urdu), a registry or a sign-up form may hold
it in either, and Latin spellings vary (Rukhsana / Ruksana, Muhammad / Mohammad). So:

* `to_urdu("Rukhsana Bibi")` -> "رخسانہ بی بی": the registration converted into Urdu, from a list of common
  names first and letter rules for the rest. Used to show and speak a name in an Urdu conversation.
* `same_name_score(a, b)` -> 0..1 for two names in any mix of scripts: the English one is converted into
  Urdu, then both are compared with letters that sound alike merged (س ص ث, ز ذ ض ظ, ت ط, ح ہ, ق ک ...).

Pure functions, no database. name_match.py uses same_name_score when either name is in Urdu script.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

# Common Pakistani names: Latin (canonical spelling, see name_match._VARIANTS) -> Urdu. Add freely.
URDU = {
    "muhammad": "محمد", "ahmad": "احمد", "ahmed": "احمد", "ali": "علی", "abbas": "عباس", "abdul": "عبدال",
    "akhtar": "اختر", "akram": "اکرم", "allah": "اللہ", "amjad": "امجد", "anwar": "انور", "arif": "عارف",
    "arshad": "ارشد", "asif": "آصف", "aslam": "اسلم", "ayesha": "عائشہ", "barkat": "برکت", "bashir": "بشیر",
    "begum": "بیگم", "bibi": "بی بی", "bilal": "بلال", "bushra": "بشریٰ", "din": "دین", "ditta": "دتہ",
    "faisal": "فیصل", "farooq": "فاروق", "fatima": "فاطمہ", "fazal": "فضل", "ghafoor": "غفور",
    "ghulam": "غلام", "gul": "گل", "gulshan": "گلشن", "habib": "حبیب", "hameed": "حمید", "hussain": "حسین",
    "hasan": "حسن", "imran": "عمران", "iqbal": "اقبال", "javed": "جاوید", "kamran": "کامران", "karim": "کریم",
    "kausar": "کوثر", "khalid": "خالد", "khan": "خان", "kulsoom": "کلثوم", "liaquat": "لیاقت", "malik": "ملک",
    "mahmood": "محمود", "mehmood": "محمود", "majeed": "مجید", "mehwish": "مہوش", "mushtaq": "مشتاق",
    "nabi": "نبی", "nadeem": "ندیم", "nargis": "نرگس", "naseem": "نسیم", "nasreen": "نسرین", "naveed": "نوید",
    "nazir": "نذیر", "noor": "نور", "nusrat": "نصرت", "parveen": "پروین", "qureshi": "قریشی",
    "rashid": "راشد", "rasool": "رسول", "raza": "رضا", "razia": "رضیہ", "rehmat": "رحمت", "rehman": "رحمان",
    "riaz": "ریاض", "rubina": "روبینہ", "rukhsana": "رخسانہ", "ruksana": "رخسانہ", "sadia": "سعدیہ",
    "saima": "صائمہ", "sajjad": "سجاد", "saleem": "سلیم", "samina": "ثمینہ", "sarfraz": "سرفراز",
    "shabana": "شبانہ", "shazia": "شازیہ", "sher": "شیر", "siddique": "صدیق", "tahira": "طاہرہ",
    "tanveer": "تنویر", "tariq": "طارق", "waseem": "وسیم", "yousuf": "یوسف", "zahid": "زاہد",
    "zubaida": "زبیدہ", "zainab": "زینب", "khadija": "خدیجہ", "aisha": "عائشہ", "amina": "آمنہ",
    "sughra": "صغریٰ", "kaneez": "کنیز", "sakina": "سکینہ", "maryam": "مریم", "naila": "نائلہ",
    "shamim": "شمیم", "usman": "عثمان", "umar": "عمر", "yasmin": "یاسمین", "zahida": "زاہدہ", "nazia": "نازیہ",
    "rani": "رانی", "mai": "مائی", "sultana": "سلطانہ", "ismail": "اسماعیل", "ibrahim": "ابراہیم",
    "yousaf": "یوسف", "naeem": "نعیم", "shaikh": "شیخ", "qadir": "قادر", "rafiq": "رفیق", "latif": "لطیف",
    # more women's names
    "sumaira": "سمیرا", "rizwana": "رضوانہ", "shaheen": "شاہین", "saba": "صبا", "noreen": "نورین",
    "asma": "عاصمہ", "robina": "روبینہ", "hina": "حنا", "batool": "بتول", "kanwal": "کنول", "nazia": "نازیہ",
    "shahnaz": "شہناز", "farzana": "فرزانہ", "rehana": "ریحانہ", "shamshad": "شمشاد", "shagufta": "شگفتہ",
    "ishrat": "عشرت", "iffat": "عفت", "ghazala": "غزالہ", "tasneem": "تسنیم", "yasmeen": "یاسمین",
    "zareena": "زرینہ", "safia": "صفیہ", "sabira": "صابرہ", "jamila": "جمیلہ", "rasheeda": "رشیدہ",
    "hameeda": "حمیدہ", "saeeda": "سعیدہ", "zahra": "زہرا", "aliya": "عالیہ", "sidra": "سدرہ",
    "mehnaz": "مہناز", "uzma": "عظمیٰ", "kiran": "کرن", "nida": "ندا", "ambreen": "عنبرین", "sobia": "صوبیہ",
    "shumaila": "شمائلہ", "fouzia": "فوزیہ", "naheed": "ناہید", "nighat": "نگہت", "tahmina": "تہمینہ",
    "misbah": "مصباح", "rafia": "رافعہ", "abida": "عابدہ", "bilqees": "بلقیس", "jannat": "جنت",
    "mumtaz": "ممتاز", "suraiya": "ثریا", "khurshid": "خورشید", "anwari": "انوری", "maqsood": "مقصود",
    # more men's names and family names
    "irfan": "عرفان", "imtiaz": "امتیاز", "ijaz": "اعجاز", "ejaz": "اعجاز", "aftab": "آفتاب", "shahid": "شاہد",
    "sajid": "ساجد", "majid": "ماجد", "wajid": "واجد", "hamid": "حامد", "abid": "عابد", "nasir": "ناصر",
    "zafar": "ظفر", "ashraf": "اشرف", "akbar": "اکبر", "younas": "یونس", "ilyas": "الیاس", "idrees": "ادریس",
    "ishaq": "اسحاق", "yaqoob": "یعقوب", "ayub": "ایوب", "saeed": "سعید", "rasheed": "رشید", "waheed": "وحید",
    "khurram": "خرم", "kashif": "کاشف", "adnan": "عدنان", "ahsan": "احسن", "shahbaz": "شہباز", "nawaz": "نواز",
    "sharif": "شریف", "haq": "حق", "ullah": "اللہ", "butt": "بٹ", "chaudhry": "چوہدری", "rana": "رانا",
    "mian": "میاں", "syed": "سید", "shah": "شاہ", "bukhari": "بخاری", "gillani": "گیلانی", "abbasi": "عباسی",
    "awan": "اعوان", "jatt": "جٹ", "ghaffar": "غفار", "sattar": "ستار", "jabbar": "جبار", "rauf": "رؤف",
}

_URDU_LETTERS = re.compile(r"[؀-ۿ]")
_LATIN_RULES = [  # longest first; for names not in URDU
    ("kh", "خ"), ("gh", "غ"), ("sh", "ش"), ("ch", "چ"), ("th", "تھ"), ("ph", "ف"), ("bh", "بھ"), ("dh", "دھ"),
    ("jh", "جھ"), ("aa", "ا"), ("ee", "ی"), ("oo", "و"), ("ai", "ے"), ("ay", "ے"), ("ei", "ی"), ("ou", "و"),
    ("b", "ب"), ("p", "پ"), ("t", "ت"), ("j", "ج"), ("h", "ہ"), ("d", "د"), ("r", "ر"), ("z", "ز"), ("s", "س"),
    ("f", "ف"), ("q", "ق"), ("k", "ک"), ("c", "ک"), ("g", "گ"), ("l", "ل"), ("m", "م"), ("n", "ن"), ("w", "و"),
    ("v", "و"), ("y", "ی"), ("x", "کس"), ("i", "ی"), ("o", "و"), ("u", "و"), ("e", "ی"),
]


def has_urdu(text: str | None) -> bool:
    return bool(_URDU_LETTERS.search(text or ""))


def _latin_words(name: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", " ", folded.lower()).split()


def _canon(word: str) -> str:
    from app.name_match import CANON   # Mohammad -> muhammad, Fatimah -> fatima ...
    return CANON.get(word, word)


def _word_to_urdu(word: str) -> str:
    w = _canon(word)
    if w in URDU:
        return URDU[w]
    if word in URDU:
        return URDU[word]
    out, i = [], 0
    while i < len(w):
        if w.startswith("aa", i):
            out.append("ا")
            i += 2
            continue
        if w[i] == "a":   # 'a' is unwritten inside a word, alif at the start, ہ at the end (Shazia -> شازیہ)
            out.append("ا" if i == 0 else ("ہ" if i == len(w) - 1 else ""))
            i += 1
            continue
        for lat, ur in _LATIN_RULES:
            if w.startswith(lat, i):
                if lat in ("i", "u", "o", "e") and 0 < i < len(w) - 1:
                    ur = ""   # a short vowel inside a word is usually unwritten (Hina حنا, Kulsoom کلثوم)
                out.append(ur)
                i += len(lat)
                break
        else:
            i += 1
    return "".join(out) or word


def to_urdu(name: str | None) -> str | None:
    """A name in Urdu script. Already Urdu: returned as it is."""
    if not name or has_urdu(name):
        return name
    words = _latin_words(name)
    return " ".join(_word_to_urdu(w) for w in words) or name


# ---- comparing: both names in Urdu script, letters that sound alike merged
_MERGE = {}
for letters, to in (("ثص", "س"), ("ذضظ", "ز"), ("ط", "ت"), ("حھ", "ہ"), ("ق", "ک"), ("عآءئأ", "ا"), ("ے", "ی"),
                    ("ں", "ن"), ("ؤ", "و"), ("ٹ", "ت"), ("ڈ", "د"), ("ڑ", "ر"), ("ة", "ہ")):
    for ch in letters:
        _MERGE[ch] = to


def urdu_key(name: str | None) -> list[str]:
    """Words of the name in Urdu script with alike-sounding letters merged and a final ہ / ا dropped:
    'رخسانہ بی بی' -> ['رخسان', 'بیبی'] ('بی بی' is one name written as two words)."""
    u = to_urdu(name) or ""
    u = unicodedata.normalize("NFC", u)
    u = re.sub(r"[\u064b-\u065f\u0670]", "", u)                 # diacritics
    u = re.sub(r"بی\s+بی", "بیبی", u)
    words = re.sub(r"[^\u0600-\u06ff ]+", " ", u).split()
    out = []
    for w in words:
        w = "".join(_MERGE.get(ch, ch) for ch in w)
        w = re.sub(r"(.)\1+", r"\1", w)
        if len(w) > 2 and w[-1] in "ہا":   # Rukhsana رخسانہ, Hina حنا: the final -a is ہ or ا
            w = w[:-1]
        out.append(w)
    return [w for w in out if w]


COMMON_URDU = {"محمد", "بیبی", "بیگم"}   # Muhammad, Bibi, Begum: must not make two people look alike


def same_name_score(a: str | None, b: str | None) -> float:
    """0..1 for two names in any mix of scripts: the English one is converted into Urdu first (to_urdu), then
    the two are compared: the stricter of 'whole name' and 'each distinctive word has a close partner'."""
    ka, kb = urdu_key(a), urdu_key(b)
    if not ka or not kb:
        return 0.0
    full = fuzz.token_sort_ratio(" ".join(ka), " ".join(kb)) / 100
    da = [w for w in ka if w not in COMMON_URDU] or ka
    db = [w for w in kb if w not in COMMON_URDU] or kb
    # every distinctive word must have a close partner on the other side ('ارشد' is not 'راشد' just because
    # both men are 'محمود')
    sim = lambda x, y: fuzz.ratio(x, y) / 100
    words = min(min(max(sim(x, y) for y in db) for x in da), min(max(sim(y, x) for x in da) for y in db))
    return round(min(full, words), 4)
