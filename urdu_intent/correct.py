"""Correct misheard words towards the claim vocabulary ('sound-alike' correction).

Three layers, applied in order, every change reported:
1. the sound-alike dictionary (sound_alikes.json): known mishearings -> the right word;
2. joining split words: 'در خاست' -> 'درخواست' when the joined form sounds like a domain word;
3. fuzzy by sound: a word that is not everyday Urdu and sounds almost like exactly one domain word
   (same sound key, or one sound away) is replaced by it.

Everyday words (common_words.txt, and every word used in the intent examples) are never changed,
so 'کم' does not become 'کام' and a correct sentence passes through untouched.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .normalize import edit_distance, normalize, sound_key

HERE = Path(__file__).resolve().parent


@dataclass
class Correction:
    original: str
    corrected: str
    reason: str


@dataclass
class Corrected:
    text: str
    corrections: list[Correction] = field(default_factory=list)


@dataclass(frozen=True)
class Lexicon:
    phrase_map: tuple[tuple[str, str], ...]   # (normalised mishearing, canonical), longest first
    domain: tuple[tuple[str, str], ...]       # (canonical single word, its sound key)
    domain_phrases: tuple[tuple[str, str], ...]  # (canonical multi-word term, sound key)
    protected: frozenset[str]


@lru_cache(maxsize=1)
def lexicon() -> Lexicon:
    alikes = json.loads((HERE / "sound_alikes.json").read_text(encoding="utf-8"))["words"]
    intents = json.loads((HERE / "intents.json").read_text(encoding="utf-8"))["intents"]
    phrase_map: dict[str, str] = {}
    canon: set[str] = set()
    for word, variants in alikes.items():
        canon.add(normalize(word))
        for v in variants:
            phrase_map[normalize(v)] = normalize(word)
    targets = {normalize(w) for w in alikes}   # words the fuzzy step may correct TO
    for spec in intents.values():
        canon.update(normalize(k) for k in spec["keywords"])
        targets.update(normalize(k) for k, weight in spec["keywords"].items() if weight >= 2)
    protected = set()
    for line in (HERE / "common_words.txt").read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("#"):
            protected.update(normalize(line).split())
    for spec in intents.values():
        for ex in spec["examples"]:
            protected.update(normalize(ex).split())
    protected.update(w for c in canon for w in c.split())
    # only meaningful content words are correction targets, never weak hints like 'کیسے'
    singles = tuple((c, sound_key(c)) for c in sorted(targets) if " " not in c and len(c) >= 3)
    multis = tuple((c, sound_key(c)) for c in sorted(targets) if " " in c)
    ordered = tuple(sorted(phrase_map.items(), key=lambda kv: -len(kv[0])))
    return Lexicon(ordered, singles, multis, frozenset(protected))


def _allowed_edits(key: str) -> int:
    """Short words must sound exactly like the target; longer ones may differ by one or two sounds."""
    return 0 if len(key) < 5 else 1 if len(key) < 8 else 2


def correct(text: str) -> Corrected:
    lex = lexicon()
    t = normalize(text)
    out: list[Correction] = []

    # 1. known mishearings (whole words / phrases only)
    for wrong, right in lex.phrase_map:
        if wrong == right:
            continue
        pattern = r"(?<!\S)" + re.escape(wrong) + r"(?!\S)"
        if re.search(pattern, t):
            t = re.sub(pattern, right, t)
            out.append(Correction(wrong, right, "sound-alike dictionary"))

    words = t.split()

    # 2. join two words that together sound like a domain word ('در خاست' -> 'درخواست')
    i, joined = 0, []
    while i < len(words):
        if i + 1 < len(words) and re.search(r"[؀-ۿ]", words[i] + words[i + 1]) \
                and not (words[i] in lex.protected and words[i + 1] in lex.protected
                         and words[i] + words[i + 1] not in lex.protected):  # Urdu script only
            key = sound_key(words[i] + words[i + 1])
            match = _best(key, lex.domain + lex.domain_phrases)
            if match and len(key) >= 4:
                joined.append(match)
                out.append(Correction(f"{words[i]} {words[i + 1]}", match, "joined split word"))
                i += 2
                continue
        joined.append(words[i])
        i += 1
    words = joined

    # 3. fuzzy by sound, for words that are not everyday Urdu
    fixed = []
    for w in words:
        if w in lex.protected or len(w) < 3 or not re.search(r"[؀-ۿ]", w):
            fixed.append(w)
            continue
        match = _best(sound_key(w), lex.domain)
        if match and match != w:
            out.append(Correction(w, match, "sounds like a domain word"))
            fixed.append(match)
        else:
            fixed.append(w)
    return Corrected(" ".join(fixed), out)


def _best(key: str, candidates) -> str | None:
    """The single candidate within the allowed sound distance, or None if none or several tie."""
    limit = _allowed_edits(key)
    scored = sorted((edit_distance(key, ck, limit), c) for c, ck in candidates if abs(len(ck) - len(key)) <= limit)
    if not scored or scored[0][0] > limit:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0] and scored[1][1] != scored[0][1]:
        return None  # two domain words equally close: do not guess
    return scored[0][1]
