# python tools/voice/stress_test.py : every test sentence corrupted the way speech recognition does (sound-alike
# letters, dropped ھ / ں, joined or split words), 4 times each; Roman Urdu sentences re-spelled the many ways
# people type them (paise / pesay, nahi / nahin, kya / kia). Counts right / unclear / WRONG.
"""Whisper-like corruption of every test sentence: swap sound-alike letters, drop ھ / ں, join or split words."""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from urdu_intent import detect_intent
SWAP = {"س": "ص", "ص": "س", "ث": "س", "ز": "ذ", "ذ": "ز", "ض": "ز", "ظ": "ز", "ت": "ط", "ط": "ت", "ہ": "ح", "ح": "ہ",
        "ک": "ق", "ق": "ک", "ا": "آ", "ے": "ی", "ی": "ے"}
def corrupt(t, rnd):
    w = t.split()
    if not w or any("a" <= c <= "z" for c in t.lower()): return None
    for _ in range(2):
        i = rnd.randrange(len(w)); op = rnd.random()
        if op < 0.5:
            cs = [k for k, c in enumerate(w[i]) if c in SWAP]
            if cs: k = rnd.choice(cs); w[i] = w[i][:k] + SWAP[w[i][k]] + w[i][k + 1:]
        elif op < 0.65: w[i] = w[i].replace("ھ", "").replace("ں", "")
        elif op < 0.85 and i + 1 < len(w) and len(w[i]) <= 4: w[i:i + 2] = [w[i] + w[i + 1]]
        elif len(w[i]) >= 6: k = len(w[i]) // 2; w[i:i + 1] = [w[i][:k], w[i][k:]]
    return " ".join(w)
ROMAN = [("aa", "a"), ("ee", "i"), ("oo", "u"), ("ai", "e"), ("ay", "e"), ("kh", "k"), ("w", "v"), ("q", "k"),
         ("z", "j"), ("ii", "i"), ("y ", "i ")]
def respell(t, rnd):
    """Roman Urdu typed another way: two spelling changes, or a doubled / dropped vowel."""
    if not any("a" <= c <= "z" for c in t.lower()) or any("\u0600" <= c <= "\u06ff" for c in t): return None
    v = t.lower() + " "
    for _ in range(2):
        a, b = rnd.choice(ROMAN)
        if rnd.random() < 0.5: a, b = b, a
        if a in v:
            k = rnd.choice([i for i in range(len(v)) if v.startswith(a, i)])
            v = v[:k] + b + v[k + len(a):]
    return v.strip()
rnd = random.Random(7); tot = right = unclear = wrong = 0
SETS = ("test_utterances.json", "test_heldout.json", "test_heldout2.json", "test_heldout3.json", "test_heldout4.json")
for f in SETS:
    for t in json.load(open(Path(__file__).resolve().parent / f, encoding="utf-8"))["tests"]:
        for _ in range(4):
            v = corrupt(t["text"], rnd) or respell(t["text"], rnd)
            if not v: continue
            g = detect_intent(v)["intent"]; tot += 1
            if g == t["intent"]: right += 1
            elif g == "unclear": unclear += 1
            else: wrong += 1; print("WRONG", t["intent"], "->", g, "|", v)
print(f"{tot} corrupted sentences: right {right} ({100*right/tot:.0f}%), unclear {unclear}, WRONG {wrong}")
