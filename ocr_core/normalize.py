"""Turn raw OCR text into clean values: CNIC numbers, dates, names, genders, relations.

Every function returns None when the text cannot be read as the requested kind; it never guesses.
Name corrections are limited to a single cheap print confusion (l/i, o/a ...) that turns the word
into a name from names.txt, and they are always reported back so the audit trail shows them.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Letters the OCR often reads in place of digits on printed documents.
DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "U": "0", "l": "1", "I": "1",
                                  "i": "1", "|": "1", "!": "1", "j": "1", "J": "1", "S": "5", "s": "5",
                                  "B": "8", "Z": "2", "z": "2", "g": "9", "q": "9", "~": "", "_": "-"})

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
               "october", "november", "december"]


# ---------------------------------------------------------------------------------------------
# CNIC
# ---------------------------------------------------------------------------------------------
def cnic_digits(text: str | None) -> str:
    """All digits in the text after fixing letter look-alikes (O->0, l->1 ...)."""
    return re.sub(r"\D", "", (text or "").translate(DIGIT_LOOKALIKES))


def format_cnic(digits: str) -> str | None:
    return f"{digits[:5]}-{digits[5:12]}-{digits[12]}" if re.fullmatch(r"\d{13}", digits or "") else None


def parse_cnic(text: str | None) -> str | None:
    """'35202-0858542-8', '3520208585428', '35202 O858542 8' -> '35202-0858542-8'."""
    t = (text or "").strip()
    m = re.search(r"[0-9OolIDQSBZ|]{5}\s*[-~_.\s]\s*[0-9OolIDQSBZ|]{7}\s*[-~_.\s]\s*[0-9OolIDQSBZ|~]", t)
    if m:
        d = cnic_digits(m.group(0))
        if len(d) == 13:
            return format_cnic(d)
    if re.search(r"\d[-~_.\s]+\d", t):
        return None  # separators present but not in the 5-7-1 places: a digit was lost or added
    return format_cnic(cnic_digits(t))


def cnic_gender(cnic: str | None) -> str | None:
    """NADRA numbers end in an odd digit for men and an even digit for women."""
    d = cnic_digits(cnic)
    if len(d) != 13:
        return None
    return "Male" if int(d[-1]) % 2 else "Female"


# Province / region from the first digit of a CNIC.
CNIC_REGIONS = {"1": "Khyber Pakhtunkhwa", "2": "FATA (merged districts)", "3": "Punjab", "4": "Sindh",
                "5": "Balochistan", "6": "Islamabad", "7": "Gilgit-Baltistan", "8": "Azad Kashmir"}


def cnic_problems(cnic: str | None) -> list[str]:
    d = cnic_digits(cnic)
    if len(d) != 13:
        return ["not 13 digits"]
    out = []
    if d[0] not in CNIC_REGIONS:
        out.append(f"first digit {d[0]} is not a known province code")
    if len(set(d)) == 1:
        out.append("all digits identical")
    return out


# ---------------------------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------------------------
def _month_from_word(word: str) -> tuple[int, float] | None:
    """Best month for a word, or None when no month is close or two months are equally close
    ('Ju' could be June or July)."""
    w = word.lower()
    per_month = []
    for i, (abbr, full) in enumerate(zip(MONTHS, MONTH_NAMES)):
        s = max(difflib.SequenceMatcher(None, w, cand).ratio() for cand in (abbr, full))
        if len(w) >= 3 and full.startswith(w):
            s = 1.0
        per_month.append((s, i + 1))
    per_month.sort(reverse=True)
    (score, best), (second, _) = per_month[0], per_month[1]
    if score < 0.72 or score - second < 0.05:
        return None
    return best, score


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d) if 1880 <= y <= 2100 else None
    except ValueError:
        return None


def parse_date(text: str | None) -> date | None:
    """Read '14-Jun-2015', '04-ul-2025', 'O1-Jan-1954', 'July 13, 1986', '29-11-2012', '29.11.2012'."""
    t = (text or "").strip()
    if not t:
        return None
    # digits misread inside a month name: '07-0ct-1967' (zero for O), 'Ju1' (one for l)
    t = re.sub(r"(?<=[-./\s])0(?=[A-Za-z]{2})", "O", t)
    t = re.sub(r"(?<=[A-Za-z]{2})1(?=[-./\s,])", "l", t)
    # 1. a month written as a word
    best = None
    for m in re.finditer(r"[A-Za-z]{2,9}", t):
        word = m.group(0)
        if re.fullmatch(r"[OoDQlIiSsBZzgq]+", word) and len(word) <= 2:
            continue  # probably a misread digit, not a month
        found = _month_from_word(word)
        if found and (best is None or found[1] > best[1]):
            best = (found[0], found[1], m.start(), m.end())
    if best:
        month, _, a, b = best
        left = t[:a].translate(DIGIT_LOOKALIKES)
        right = t[b:].translate(DIGIT_LOOKALIKES)
        day = re.search(r"(\d{1,2})\D{0,3}$", left)
        year = re.match(r"\D{0,3}(\d{4})", right)
        if day and year:                                      # 14-Jun-2015
            return _safe_date(int(year.group(1)), month, int(day.group(1)))
        if not left.strip(" -./"):
            m = re.match(r"\D{0,3}(\d{1,2})\D{1,3}(\d{4})", right)   # July 13, 1986
            if m:
                return _safe_date(int(m.group(2)), month, int(m.group(1)))
        return None
    # 2. all digits: DD-MM-YYYY
    fixed = t.translate(DIGIT_LOOKALIKES)
    m = re.search(r"(\d{1,2})\s*[-./\s]\s*(\d{1,2})\s*[-./\s]\s*(\d{4})", fixed)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def parse_card_date(text: str | None) -> str | None:
    """A date as printed on a CNIC, returned as text: 'YYYY-MM-DD'; 'lifetime' for cards issued
    without expiry (older holders); or 'YYYY' when only the year of birth is printed."""
    t = (text or "").strip()
    letters = re.sub(r"[^a-z]", "", t.lower())
    if len(letters) >= 5 and difflib.SequenceMatcher(None, letters, "lifetime").ratio() >= 0.75:
        return "lifetime"
    d = parse_date(t)
    if d:
        return d.isoformat()
    digits = cnic_digits(t)
    if len(digits) == 8 and not re.search(r"[A-Za-z]{2}", t):
        # cards always print DD.MM.YYYY; separators are often misread (01:01.1973, 01011973)
        d = _safe_date(int(digits[4:]), int(digits[2:4]), int(digits[:2]))
        if d:
            return d.isoformat()
    m = re.fullmatch(r"\D{0,2}((?:19|20)\d\d)\D{0,2}", t.translate(DIGIT_LOOKALIKES).strip())
    return m.group(1) if m else None


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def known_names() -> frozenset[str]:
    lines = (HERE / "names.txt").read_text(encoding="utf-8").splitlines()
    return frozenset(w.lower() for ln in lines if not ln.lstrip().startswith("#") for w in ln.split())


# Printed-text OCR confusions: (read, real) -> cost. Anything else costs 1.
_CHEAP = {("l", "i"): .3, ("i", "l"): .3, ("1", "l"): .3, ("1", "i"): .3, ("0", "o"): .3, ("o", "a"): .5,
          ("a", "o"): .5, ("c", "e"): .5, ("e", "c"): .5, ("u", "a"): .6, ("n", "h"): .6, ("h", "n"): .6,
          ("t", "f"): .6, ("f", "t"): .6, ("y", "v"): .6, ("v", "y"): .6, ("5", "s"): .4, ("8", "b"): .5,
          ("t", "l"): .5, ("g", "q"): .4, ("q", "g"): .4, ("c", "k"): .6, ("j", "n"): .6, ("o", "n"): .6}


def _wdist(a: str, b: str) -> float:
    n, m = len(a), len(b)
    if abs(n - m) > 2:
        return 9.0
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = float(i)
    for j in range(1, m + 1):
        dp[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = 0.0 if a[i - 1] == b[j - 1] else _CHEAP.get((a[i - 1], b[j - 1]), 1.0)
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + sub)
    return dp[n][m]


def correct_name_word(word: str) -> tuple[str, str | None]:
    """Return (word, note). A word is replaced only when exactly one known name is within one
    cheap print confusion of it."""
    low = word.lower()
    if len(low) < 3 or low in known_names() or not low.isalpha():
        return word, None
    ranked = sorted((_wdist(low, n), n) for n in known_names() if abs(len(n) - len(low)) <= 1)[:2]
    if ranked and ranked[0][0] <= 0.5 and (len(ranked) < 2 or ranked[1][0] - ranked[0][0] >= 0.4):
        fixed = ranked[0][1].capitalize()
        return fixed, f"'{word}' read as the name '{fixed}'"
    return word, None


def split_camel(text: str) -> str:
    """'BasheerAhmad' -> 'Basheer Ahmad' (the OCR sometimes drops the space between words)."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)


def split_joined_name(word: str) -> list[str] | None:
    """'Muhammadaslam' -> ['Muhammad', 'aslam'] when both halves are known names and the whole is not."""
    low, names = word.lower(), known_names()
    if len(low) < 7 or low in names:
        return None
    for i in range(3, len(low) - 2):
        if low[:i] in names and low[i:] in names:
            return [word[:i], word[i:]]
    return None


def clean_name(text: str | None) -> tuple[str | None, list[str], bool]:
    """Return (name, notes, unknown_words). unknown_words is True when a word is neither a known
    name nor confidently corrected; such names are still returned but get a lower confidence."""
    t = re.sub(r"[^A-Za-z.' \-]", " ", split_camel(text or ""))
    t = re.sub(r"\s+", " ", t).strip(" .-'")
    if not t or len(re.sub(r"[^A-Za-z]", "", t)) < 2:
        return None, [], False
    out, notes, unknown = [], [], False
    words = []
    for w in t.split():   # 'MUHAMMADASLAM': capitals hide the joined words, so split on two known names
        words.extend(split_joined_name(w.strip(".'-")) or [w])
    for w in words:
        core = w.strip(".'-")
        if len(core) <= 2:
            out.append(core.upper() if len(core) == 1 else core.capitalize())
            continue
        fixed, note = correct_name_word(core)
        if note:
            notes.append(note)
        elif fixed.lower() not in known_names():
            unknown = True
        out.append(fixed.capitalize())
    return " ".join(out), notes, unknown


# ---------------------------------------------------------------------------------------------
# Small vocabularies
# ---------------------------------------------------------------------------------------------
def best_choice(text: str | None, choices: dict[str, str], cutoff: float = 0.72) -> str | None:
    """Fuzzy-match text against {spelling: canonical value}."""
    t = re.sub(r"[^a-z\- ]", "", (text or "").lower()).strip()
    if not t:
        return None
    if t in choices:
        return choices[t]
    match = difflib.get_close_matches(t, list(choices), n=1, cutoff=cutoff)
    return choices[match[0]] if match else None


GENDERS = {"male": "Male", "female": "Female", "m": "Male", "f": "Female", "man": "Male", "woman": "Female",
           "transgender": "Transgender", "x": "Transgender"}

RELATIONS = {r: r.title() for r in [
    "wife", "husband", "widow", "widower", "son", "daughter", "father", "mother", "brother", "sister",
    "grandson", "granddaughter", "grandfather", "grandmother", "nephew", "niece", "uncle", "aunt",
    "cousin", "guardian", "self", "son-in-law", "daughter-in-law", "father-in-law", "mother-in-law",
    "brother-in-law", "sister-in-law", "spouse", "relative", "other"]}


NATIONALITIES = {"pakistani": "Pakistani", "afghan": "Afghan", "indian": "Indian", "bangladeshi": "Bangladeshi",
                 "other": "Other"}
RELIGIONS = {"islam": "Islam", "muslim": "Islam", "christianity": "Christianity", "christian": "Christianity",
             "hinduism": "Hinduism", "hindu": "Hinduism", "sikhism": "Sikhism", "sikh": "Sikhism",
             "ahmadi": "Ahmadi", "parsi": "Parsi", "other": "Other"}
ADDRESS_WORDS = ["house", "street", "block", "city", "town", "model", "colony", "road", "mohallah", "muhallah",
                 "village", "sector", "phase", "lane", "gali", "chak", "near", "tehsil", "district", "flat",
                 "plot", "society", "scheme", "garden", "nagar", "abad", "bazar", "cantt", "post", "office"]


def clean_address(text: str | None) -> str | None:
    """Fix single cheap misreads in common address words ('Clty' -> 'City') and restore spaces."""
    t = clean_text(split_camel(text or ""))
    if not t:
        return None

    def fix(m: re.Match) -> str:
        w = m.group(0)
        low = w.lower()
        if low in ADDRESS_WORDS or len(low) < 4:
            return w
        best = min(ADDRESS_WORDS, key=lambda c: _wdist(low, c))
        if _wdist(low, best) <= 0.3:
            return best.upper() if w.isupper() else best.capitalize()
        return w
    return re.sub(r"[A-Za-z]+", fix, t)


URDU_GENDERS = {"عورت": "Female", "خاتون": "Female", "مرد": "Male", "خواجہ سرا": "Transgender"}


def normalize_gender(text: str | None) -> str | None:
    """'F', 'Female', and newer cards' bilingual 'F / عورت' (the Urdu half often misread, e.g. 'F/1S')."""
    if not text:
        return None
    for urdu, value in URDU_GENDERS.items():
        if urdu in text:
            return value
    first = re.split(r"[/|\\]", text)[0].strip()
    return best_choice(first, GENDERS, cutoff=0.75) or best_choice(text, GENDERS, cutoff=0.75)


def normalize_relation(text: str | None) -> str | None:
    return best_choice(text, RELATIONS, cutoff=0.75)


def clean_text(text: str | None) -> str | None:
    t = re.sub(r"\s+", " ", (text or "")).strip(" :;,.!-_")
    return t or None
