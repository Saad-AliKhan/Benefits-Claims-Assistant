"""Score the intent detector on tools/voice/test_utterances.json.

    python tools/voice/evaluate_intents.py            # summary
    python tools/voice/evaluate_intents.py --errors   # also list every mistake
    python tools/voice/evaluate_intents.py --file test_heldout.json   # a held-out set
    python tools/voice/evaluate_intents.py --file test_english2.json --english   # English mode (app.agent)

Three numbers matter:
  correct          picked the right intent (for 'unclear' tests: correctly refused to pick)
  wrong intent     picked a DIFFERENT intent: the costly mistake, should be ~0
  said unclear     refused to pick although an intent was meant: safe (the app asks again)
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Urdu in the Windows console
ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(ROOT))
from urdu_intent import detect_intent  # noqa: E402

if "--english" in sys.argv:
    from app.agent import english_intent as detect_intent  # noqa: E402,F811

name = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else "test_utterances.json"
tests = json.loads((Path(__file__).resolve().parent / name).read_text(encoding="utf-8"))["tests"]
show = "--errors" in sys.argv
groups = {"all": Counter(), "clean": Counter(), "asr": Counter(), "roman": Counter(), "out_of_scope": Counter()}
for t in tests:  # every other tag gets its own line too (helper, dialect, mixed, pair, hard_negative ...)
    if t.get("tag") and t["tag"] not in groups:
        groups[t["tag"]] = Counter()
for t in tests:
    r = detect_intent(t["text"])
    got, want = r["intent"], t["intent"]
    outcome = "correct" if got == want else ("said_unclear" if got == "unclear" else "wrong_intent")
    names = ["all", "out_of_scope" if want == "unclear" else ("asr" if t.get("asr") else
             "roman" if t.get("tag") == "roman" else "clean")]
    if t.get("tag") and t["tag"] != "roman":
        names.append(t["tag"])
    for g in names:
        groups[g][outcome] += 1
        groups[g]["n"] += 1
    if show and outcome != "correct":
        print(f"[{outcome}] want={want} got={got} conf={r.get('confidence')} | {t['text']} -> {r.get('text_corrected')} "
              f"| top={r.get('alternatives', [])[:2]}")
print(f"\n{'set':14} {'n':>4} {'correct':>8} {'wrong intent':>13} {'said unclear':>13}")
for g, c in groups.items():
    if c["n"]:
        print(f"{g:14} {c['n']:4} {c['correct'] / c['n']:8.0%} {c['wrong_intent']:13} {c['said_unclear']:13}")
