"""Accuracy on your own labelled photos (real documents stay on your machine).

    python tools/ocr/evaluate_labelled.py --doc cnic --images path\\to\\photos --truth truth.json

truth.json maps each photo's file name to the values it should produce, e.g.
    {"card1.jpg": {"cnic": "16201-3205786-1", "name": "Wajid Ali", "date_of_expiry": "lifetime"}}
Fields left out of an entry are not scored. Values are compared ignoring case, spaces and dashes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(ROOT))

from ocr_core import BadImage, load_engine, read_document  # noqa: E402


def same(a, b) -> bool:
    if a is None or b is None:
        return a == b
    # case, spaces and dashes do not count ('91-100076542318' == '91100076542318')
    return re.sub(r"[^0-9a-z]", "", str(a).lower()) == re.sub(r"[^0-9a-z]", "", str(b).lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", choices=["cnic", "death_certificate"], required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    truth = json.loads(a.truth.read_text(encoding="utf-8"))
    engine = load_engine()
    per_field: dict[str, Counter] = {}
    docs = Counter()
    t0 = time.perf_counter()
    for name, want in truth.items():
        docs["documents"] += 1
        try:
            r = read_document(engine, a.doc, (a.images / name).read_bytes())
        except BadImage as e:
            docs["retake"] += 1
            print(f"{name[:24]:24} RETAKE {e.reason}")
            continue
        serious = [f for f in r["flags"] if f["severity"] in ("warning", "critical")]
        if r["overall_confidence"] >= r["review_threshold"] and not serious:
            docs["auto_ok"] += 1
        for key, value in want.items():
            got = r["fields"].get(key, {})
            c = per_field.setdefault(key, Counter())
            c["n"] += 1
            if same(got.get("value"), value):
                c["right"] += 1
            elif got.get("needs_review"):
                c["wrong_flagged"] += 1
            else:
                c["wrong_silent"] += 1
                if a.verbose:
                    print(f"{name[:24]:24} {key}: got {got.get('value')!r} want {value!r}")
    print(f"\n{'field':26} {'n':>3} {'right':>6} {'wrong, flagged':>15} {'wrong, silent':>14}")
    tot = Counter()
    for key, c in per_field.items():
        tot.update(c)
        print(f"{key:26} {c['n']:3} {c['right'] / c['n']:6.0%} {c['wrong_flagged']:15} {c['wrong_silent']:14}")
    if tot["n"]:
        print(f"{'ALL FIELDS':26} {tot['n']:3} {tot['right'] / tot['n']:6.0%} {tot['wrong_flagged']:15} "
              f"{tot['wrong_silent']:14}")
    print(f"\ndocuments {docs['documents']}, retake {docs['retake']}, could auto-accept {docs['auto_ok']}, "
          f"avg {(time.perf_counter() - t0) / max(1, docs['documents']):.1f} s")


if __name__ == "__main__":
    main()
