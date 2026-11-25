# -*- coding: utf-8 -*-
"""Spoken numbers -> digits.

Indic-Transcribe Core writes numbers the way they are spoken ("تین پانچ دو صفر دو"), not as digits (it has no
inverse text normalisation). A CNIC or a mobile number said aloud therefore arrives as a run of number words.
`spoken_digits()` turns such runs into digits, so the rest of the app (CNIC by voice, amounts) sees "35202".

Only runs of two or more number words are changed: a single "ایک" is usually the article "a/one"
("ایک افسر سے بات" = talk to an officer) and stays a word.

Handles: digit words (صفر ... نو), the irregular Urdu words for 10-99, "سو" (hundred) and "ہزار" (thousand) inside
a group ("دو سو دو" -> 202, "بارہ سو چونتیس" -> 1234), English digit words in English mode (zero ... nine, oh),
and Urdu/Arabic-Indic digits. Each spoken group is written out in full and groups are joined, which is how people
read a CNIC aloud: "پینتیس دو سو دو" -> "35202".
"""
from __future__ import annotations

import re

_UNITS = ["صفر", "ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو"]
_TENS_TO_99 = (
    "دس گیارہ بارہ تیرہ چودہ پندرہ سولہ سترہ اٹھارہ انیس "
    "بیس اکیس بائیس تئیس چوبیس پچیس چھبیس ستائیس اٹھائیس انتیس "
    "تیس اکتیس بتیس تینتیس چونتیس پینتیس چھتیس سینتیس اڑتیس انتالیس "
    "چالیس اکتالیس بیالیس تینتالیس چوالیس پینتالیس چھیالیس سینتالیس اڑتالیس انچاس "
    "پچاس اکاون باون ترپن چون پچپن چھپن ستاون اٹھاون انسٹھ "
    "ساٹھ اکسٹھ باسٹھ تریسٹھ چونسٹھ پینسٹھ چھیاسٹھ سڑسٹھ اڑسٹھ انہتر "
    "ستر اکہتر بہتر تہتر چوہتر پچھتر چھہتر ستتر اٹھہتر اناسی "
    "اسی اکاسی بیاسی تراسی چوراسی پچاسی چھیاسی ستاسی اٹھاسی نواسی "
    "نوے اکانوے بانوے ترانوے چورانوے پچانوے چھیانوے ستانوے اٹھانوے ننانوے"
).split()

WORDS: dict[str, int] = {w: i for i, w in enumerate(_UNITS)}
WORDS.update({w: i + 10 for i, w in enumerate(_TENS_TO_99)})
# common other spellings (with and without the nasal / hamza, as speech recognisers write them)
WORDS.update({"چھے": 6, "چھہ": 6, "آٹھ": 8, "اٹھ": 8, "زیرو": 0, "سیفر": 0, "تئیس": 23, "تیئیس": 23, "باییس": 22,
              "چھبّیس": 26, "انّیس": 19, "پچّیس": 25, "اکیاون": 51, "ترپّن": 53, "چوّن": 54, "اناسی": 79, "اسّی": 80})
EN_WORDS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9}
HUNDRED, THOUSAND = {"سو", "hundred"}, {"ہزار", "thousand"}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _value(tok: str) -> int | str | None:
    """A number word -> int; a written number ('35202', '۳۵۲۰۲') -> its digits as str; else None."""
    t = tok.translate(_DIGITS)
    if t.isdigit():
        return t
    low = t.lower()
    if low in EN_WORDS:
        return EN_WORDS[low]
    return WORDS.get(t)


def _is_number_token(tok: str) -> bool:
    return _value(tok) is not None or tok in HUNDRED or tok.lower() in HUNDRED or tok in THOUSAND \
        or tok.lower() in THOUSAND


def _group(tokens: list[str]) -> str:
    """One run of number words -> digits. 'X سو Y' and 'X ہزار Y' combine; everything else is concatenated."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        v = _value(tokens[i])
        nxt = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
        if isinstance(v, int) and (nxt in HUNDRED or nxt in THOUSAND):
            mult, width = (100, 2) if nxt in HUNDRED else (1000, 3)
            total, i = v * mult, i + 2
            # an optional remainder: 'دو سو دو' (202), 'دو ہزار پانچ' (2005), 'دو ہزار دو سو' (2200)
            if i < len(tokens) and isinstance(_value(tokens[i]), int):
                r = _value(tokens[i])
                after = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
                if mult == 1000 and after in HUNDRED:
                    total += r * 100
                    i += 2
                    if i < len(tokens) and isinstance(_value(tokens[i]), int) and _value(tokens[i]) < 100:
                        total += _value(tokens[i])
                        i += 1
                elif r < 10 ** width:
                    total += r
                    i += 1
            out.append(str(total))
            continue
        if tokens[i].lower() in HUNDRED:          # 'سو' alone = 100
            out.append("100")
        elif tokens[i].lower() in THOUSAND:
            out.append("1000")
        else:
            out.append(str(v))
        i += 1
    return "".join(out)


def spoken_digits(text: str, min_run: int = 2) -> str:
    """Replace every run of `min_run` or more number words with its digits. Other words are untouched."""
    if not text:
        return text
    tokens = re.split(r"(\s+|[-،,۔.])", text)
    words = [(i, t) for i, t in enumerate(tokens) if t and not t.isspace() and t not in "-،,۔."]
    out = list(tokens)
    run: list[tuple[int, str]] = []

    def flush():
        if len(run) >= min_run and any(_value(t) is not None for _, t in run):
            first, last = run[0][0], run[-1][0]
            out[first] = _group([t for _, t in run])
            for k in range(first + 1, last + 1):
                out[k] = ""
        run.clear()

    for i, t in words:
        if _is_number_token(t):
            run.append((i, t))
        else:
            flush()
    flush()
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()
