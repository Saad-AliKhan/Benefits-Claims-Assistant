"""Urdu text normalisation and a 'sounds-like' key.

Whisper (and people) write the same Urdu word in several ways: Arabic vs Urdu forms of ی ک ہ,
optional diacritics, Urdu vs Latin digits, words joined or split ("ملکر" / "مل کر"). `normalize`
makes these identical. `sound_key` goes further and merges letters that sound the same in Urdu
(س ص ث, ز ذ ض ظ, ت ط, ح ہ ...), which is what speech recognition confuses.
"""
from __future__ import annotations

import re
import unicodedata

# Arabic-script variants -> the Urdu letter
_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ", "ة": "ہ", "ۀ": "ہ", "ۃ": "ہ",
    "أ": "ا", "إ": "ا", "ٱ": "ا",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭـ]")  # harakat, superscript alef, tatweel
_PUNCT = re.compile(r"[؟?!۔.,،؛;:\"'«»()\[\]{}\-_/\\|…]+")
_SPACES = re.compile(r"\s+")

# Words Whisper often writes joined; split them so they match the way questions are written.
JOINED = {
    "ملکر": "مل کر", "کرکے": "کر کے", "ہوگیا": "ہو گیا", "ہوگئی": "ہو گئی", "ہوگئے": "ہو گئے",
    "جائیگا": "جائے گا", "جائیگی": "جائے گی", "ملیگا": "ملے گا", "ملیگی": "ملے گی", "ملینگے": "ملیں گے",
    "کرینگے": "کریں گے", "ہونگے": "ہوں گے", "آئیگی": "آئے گی", "آئیگا": "آئے گا", "کیلئے": "کے لیے",
    "کیلیے": "کے لیے", "چاہئیے": "چاہیے", "چاہئے": "چاہیے",
}


def normalize(text: str) -> str:
    """Canonical spelling for comparison and display; keeps the words, removes spelling noise."""
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("ۓ", "ئے").replace("‌", "").replace("‍", "")
    t = t.translate(_CHAR_MAP)
    t = _DIACRITICS.sub("", t)
    t = _PUNCT.sub(" ", t)
    t = _SPACES.sub(" ", t).strip().lower()
    return " ".join(JOINED.get(w, w) for w in t.split())


# Letters that sound alike in Urdu speech -> one representative. Used only for matching.
_SOUND_MAP = str.maketrans({
    "ث": "س", "ص": "س",
    "ذ": "ز", "ض": "ز", "ظ": "ز", "ژ": "ز",
    "ط": "ت",
    "ح": "ہ", "ۃ": "ہ",
    "ق": "ک",
    "آ": "ا", "ع": "ا",
    "ئ": "ی", "ے": "ی",
    "ؤ": "و",
    "ں": "ن",
    "ء": None, "ھ": None, " ": None,
})


_LATIN = re.compile(r"[a-z]")
_ROMAN_DIGRAPHS = (("ph", "f"), ("kh", "k"), ("gh", "g"), ("sh", "s"), ("ch", "c"), ("th", "t"), ("dh", "d"),
                   ("bh", "b"), ("jh", "j"), ("q", "k"), ("w", "v"), ("z", "j"))
# Short, very common Roman Urdu words written many ways: one spelling each, so they never collide
# ('kyun' must not become the same key as 'ka' or 'kya').
ROMAN_SYNONYMS = {
    "nahin": "nahi", "nai": "nahi", "nhi": "nahi", "nahee": "nahi", "nae": "nahi",
    "hain": "hai", "hy": "hai", "he": "hai", "hay": "hai",
    "kyon": "kyun", "kiyon": "kyun", "kiun": "kyun", "kyoon": "kyun", "q": "kyun",
    "kia": "kya", "kiya": "kya", "mein": "main", "men": "main", "me": "main",
    "kon": "kaun", "kaon": "kaun", "kb": "kab", "ap": "aap", "ji": "jee",
}


def roman_key(word: str) -> str:
    """Roman Urdu is written many ways ('paise', 'paisay', 'pesay'). Fix the common short words, merge
    aspirated pairs, drop 'h', turn every vowel run into one 'a' (a 'y' before a vowel stays a consonant),
    collapse doubles."""
    w = ROMAN_SYNONYMS.get(word, word)
    if w in ROMAN_SYNONYMS.values() and len(w) <= 4:
        return w  # protected short word
    for a, b in _ROMAN_DIGRAPHS:
        w = w.replace(a, b)
    w = w.replace("h", "")
    w = re.sub(r"y(?=[aeiou])", "Y", w)
    w = re.sub(r"[aeiouy]+", "a", w).replace("Y", "y")
    return re.sub(r"(.)\1+", r"\1", w)


def sound_key(text: str) -> str:
    """'How it sounds' key: normalised, alike-sounding letters merged, spaces and h-aspiration
    dropped, doubled letters collapsed. 'درخواست', 'درخاست' and 'در خواست' end up very close.
    Roman Urdu words (Latin letters) get roman_key(), so typed WhatsApp-style questions match too."""
    words = [roman_key(w) if _LATIN.search(w) else w for w in normalize(text).split()]
    k = " ".join(words).translate(_SOUND_MAP)
    return re.sub(r"(.)\1+", r"\1", k)


def edit_distance(a: str, b: str, limit: int = 99) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def fuzzy_contains(haystack: str, needle: str, max_edits: int) -> bool:
    """Is `needle` inside `haystack` with at most `max_edits` edits? (approximate substring search)"""
    if not needle:
        return False
    if needle in haystack:
        return True
    if max_edits == 0:
        return False
    n = len(needle)
    prev = [0] * (len(haystack) + 1)  # free start anywhere in the haystack
    for i in range(1, n + 1):
        cur = [i] + [0] * len(haystack)
        for j in range(1, len(haystack) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (needle[i - 1] != haystack[j - 1]))
        prev = cur
    return min(prev) <= max_edits
