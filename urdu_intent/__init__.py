"""Urdu intent detection for the claims voice assistant. Pure Python, no extra packages.

    from urdu_intent import detect_intent
    r = detect_intent("میری درخاست کا کیا بنا")
    r["intent"]            -> "application_status"
    r["confidence"]        -> 0.8
    r["text_corrected"]    -> "میری درخواست کا کیا بنا"
    r["corrections"]       -> [{"original": "درخاست", "corrected": "درخواست", ...}]

How a sentence is scored, per intent:
* keywords: weighted words and phrases, matched by *sound* (so a one-letter mishearing still counts);
* similarity: character n-grams of the sentence vs. every example question of the intent;
* the two are combined; the best intent wins only if it is clearly ahead. Otherwise the answer is
  "unclear" with the candidates, and the app should ask again or hand over to a person.

The result only names what the person is asking. It never answers claim-specific questions:
`action` tells the main application what to do, after its own login, consent and audit checks.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .correct import correct, lexicon
from .normalize import edit_distance, normalize, sound_key

HERE = Path(__file__).resolve().parent
__version__ = "1.0.0"
__all__ = ["detect_intent", "MIN_SCORE", "MIN_MARGIN", "intents"]

# Decision thresholds (tuned on evaluate_intents.py; change there, re-run, then here)
MIN_SCORE = 0.40    # below this nothing matches well enough -> "unclear"
MIN_MARGIN = 0.08   # best must beat the runner-up by this much -> otherwise "unclear" (ambiguous)
W_KEYWORDS, W_SIMILARITY = 0.55, 0.45
# Second opinion by meaning (urdu_intent/meaning.py, only when its model files are present). It may only
# turn an "unclear" into an intent, never change a confident answer, and only to the keyword matcher's own
# first choice (two different methods agreeing). Tuned on evaluate_intents.py.
MEANING_MIN = 0.78      # its best intent must be at least this similar
MEANING_MARGIN = 0.06   # and this far ahead of the next intent
# ...and a weak keyword answer (score below VETO_BELOW) that the meaning model finds unrelated to the
# question (similarity below VETO_SIMILARITY) becomes "unclear": two methods strongly disagreeing = ask again.
VETO_BELOW = 0.60
VETO_SIMILARITY = 0.45


@lru_cache(maxsize=1)
def intents() -> dict:
    return json.loads((HERE / "intents.json").read_text(encoding="utf-8"))["intents"]


@lru_cache(maxsize=1)
def guards() -> dict:
    g = json.loads((HERE / "intents.json").read_text(encoding="utf-8")).get("guards", {})
    return {k: tuple(g.get(k, ())) for k in ("noise", "off_topic", "anchors", "exempt")}


def off_topic_reason(text: str, intent: str | None = None) -> str | None:
    """'noise': words Whisper invents from noise or silence ('subscribe', 'ناظرین'), whatever the intent.
    'off_topic': an everyday subject that is not the claim (a doctor's fee, a bus fare) and no claim word at
    all. None: fine. Safety and conversation intents (guards.exempt) are never blocked as off-topic."""
    g = guards()
    t = f" {normalize(text or '')} "

    sounds = {sound_key(w) for w in t.split() if not w.isascii()}

    def has(term: str) -> bool:
        n = normalize(term)
        return f" {n} " in t or (" " not in n and not n.isascii() and sound_key(n) in sounds)
    if any(has(w) for w in g["noise"]):
        return "noise"
    if intent in g["exempt"] or not any(has(w) for w in g["off_topic"]):
        return None
    keys = {sound_key(w) for w in t.split()}
    if any(has(a) or sound_key(a) in keys for a in g["anchors"]):
        return None
    return "off_topic"


def _ngrams(key: str) -> Counter:
    k = f"#{key}#"
    return Counter(k[i:i + n] for n in (2, 3, 4) for i in range(len(k) - n + 1))


@dataclass(frozen=True)
class _Model:
    idf: dict
    examples: dict          # intent -> list of (vector, norm)
    keywords: dict          # intent -> list of (keyword, sound keys of its words, weight, unused)


@lru_cache(maxsize=1)
def _model() -> _Model:
    specs = intents()
    docs = {name: [_ngrams(sound_key(correct(ex).text)) for ex in spec["examples"]] for name, spec in specs.items()}
    df = Counter()
    n_docs = 0
    for vecs in docs.values():
        for v in vecs:
            df.update(v.keys())
            n_docs += 1
    idf = {g: math.log((1 + n_docs) / (1 + c)) + 1 for g, c in df.items()}
    examples = {}
    for name, vecs in docs.items():
        weighted = []
        for v in vecs:
            w = {g: c * idf[g] for g, c in v.items()}
            weighted.append((w, math.sqrt(sum(x * x for x in w.values()))))
        examples[name] = weighted
    keywords = {}
    for name, spec in specs.items():
        kws = []
        for kw, weight in spec["keywords"].items():
            parts = tuple(sound_key(w) for w in normalize(correct(kw).text).split())
            kws.append((kw, parts, float(weight), 0))
        keywords[name] = kws
    return _Model(idf, examples, keywords)


def _similarity(model: _Model, key: str, intent: str) -> float:
    v = _ngrams(key)
    w = {g: c * model.idf.get(g, 1.0) for g, c in v.items()}
    norm = math.sqrt(sum(x * x for x in w.values())) or 1.0
    best = 0.0
    for ex, ex_norm in model.examples[intent]:
        dot = sum(val * ex.get(g, 0.0) for g, val in w.items())
        best = max(best, dot / (norm * ex_norm))
    return best


def _numbers(text: str) -> list[str]:
    """Digit sequences said aloud (an application number, a CNIC). CNICs are formatted 5-7-1."""
    found = []
    for m in re.findall(r"\d[\d\s-]{3,}\d", normalize(text)):
        d = re.sub(r"\D", "", m)
        found.append(f"{d[:5]}-{d[5:12]}-{d[12]}" if len(d) == 13 else d)
    return found


def detect_intent(text: str) -> dict:
    """Classify one transcribed sentence. Never raises on odd input; empty text -> 'unclear'."""
    fixed = correct(text or "")
    key = sound_key(fixed.text)
    base = {"text_raw": text, "text_corrected": fixed.text,
            "corrections": [c.__dict__ for c in fixed.corrections], "numbers": _numbers(fixed.text)}
    if len(key) < 2:
        return {**base, "intent": "unclear", "reason": "no_speech", "confidence": 0.0, "alternatives": [],
                "matched_keywords": []}

    model = _model()
    # Keywords are compared with whole words or runs of 2-4 words (so 'کیس' does not match inside
    # 'کیسا', and 'نئی درخواست' does not match across 'گئے درخواست'). Longer keywords may differ by
    # one sound. A keyword may also sit inside a single word ('اہل' in 'اہلیت', 'کیابنا').
    words = [sound_key(w) for w in fixed.text.split()]
    spans = {"".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, min(len(words), i + 4) + 1)}

    everyday = lexicon().protected_sounds

    def close(a: str, b: str) -> bool:
        if a != b and a in everyday:
            return False
        allowed = 0 if len(b) < (6 if b.isascii() else 5) else 1
        return a == b or (allowed > 0 and abs(len(a) - len(b)) <= allowed and edit_distance(a, b, allowed) <= allowed)

    def hit(parts: tuple, _unused: int) -> bool:
        joined = "".join(parts)
        if joined in spans:                                   # exact, also when written joined/split
            return True
        if len(parts) == 1 and len(joined) >= 4 and any(joined in w for w in words):
            return True                                       # inside one word: 'اہل' in 'اہلیت'
        n = len(parts)                                        # word by word, each may be one sound off
        return any(all(close(words[i + k], parts[k]) for k in range(n)) for i in range(len(words) - n + 1))

    scores, hits = {}, {}
    for name in intents():
        matched = [(kw, w) for kw, kkey, w, edits in model.keywords[name] if hit(kkey, edits)]
        kw_score = 1 - math.exp(-sum(w for _, w in matched) / 3)
        sim = _similarity(model, key, name)
        scores[name] = W_KEYWORDS * kw_score + W_SIMILARITY * sim
        hits[name] = [kw for kw, _ in matched]

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, top), (_, second) = ranked[0], ranked[1]
    alternatives = [{"intent": n, "score": round(s, 3)} for n, s in ranked[:3]]
    blocked = off_topic_reason(fixed.text, best)
    if blocked:
        return {**base, "intent": "unclear", "reason": blocked, "confidence": round(top, 3),
                "alternatives": alternatives, "matched_keywords": hits[best]}
    unsure = "no_good_match" if top < MIN_SCORE else "ambiguous" if top - second < MIN_MARGIN else None
    if unsure:
        rescued = _by_meaning(fixed.text, {ranked[0][0]})
        if rescued is None:
            return {**base, "intent": "unclear", "reason": unsure, "confidence": round(top, 3),
                    "alternatives": alternatives, "matched_keywords": hits[best]}
        name, sim, margin = rescued
        spec = intents()[name]
        return {**base, "intent": name, "confidence": round(min(0.9, sim), 3), "label_ur": spec["label_ur"],
                "label_en": spec["label_en"], "action": spec["action"], "needs_backend": spec["needs_backend"],
                "alternatives": alternatives, "matched_keywords": hits[name], "method": "meaning",
                "meaning": {"similarity": round(sim, 3), "margin": round(margin, 3)}}
    if top < VETO_BELOW and _meaning_disagrees(fixed.text, best):
        return {**base, "intent": "unclear", "reason": "methods_disagree", "confidence": round(top, 3),
                "alternatives": alternatives, "matched_keywords": hits[best]}
    spec = intents()[best]
    # confidence: how high the score is, discounted when the runner-up is close
    confidence = min(0.99, top * (0.6 + 0.4 * min(1.0, (top - second) / 0.3)) / 0.8)
    return {**base, "intent": best, "confidence": round(confidence, 3), "label_ur": spec["label_ur"],
            "label_en": spec["label_en"], "action": spec["action"], "needs_backend": spec["needs_backend"],
            "alternatives": alternatives, "matched_keywords": hits[best], "method": "keywords"}


def _meaning_disagrees(text: str, intent: str) -> bool:
    from . import meaning
    sims = meaning.scores(text)
    return bool(sims) and sims.get(intent, 0.0) < VETO_SIMILARITY


def _by_meaning(text: str, keyword_top: set):
    from . import meaning
    sims = meaning.scores(text)
    if not sims:
        return None
    ranked = sorted(sims.items(), key=lambda kv: -kv[1])
    (name, top), (_, second) = ranked[0], ranked[1]
    if name in keyword_top and top >= MEANING_MIN and top - second >= MEANING_MARGIN:
        return name, top, top - second
    return None
