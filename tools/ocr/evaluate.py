"""Accuracy report on invented SPECIMEN documents (Step 5 evaluation numbers for the OCR part).

    python tools/ocr/evaluate.py --n 10                 # 10 fake people per document type
    python tools/ocr/evaluate.py --n 10 --out eval.json

For each fake person it renders the document, then three versions: a clean scan, a mild phone photo
and a harder phone photo. Each is read by the real pipeline and compared field by field.

Reported per document type and version:
  field_accuracy   share of checked fields whose value is exactly right
  silent_errors    wrong values NOT marked needs_review (the number that matters most: should be 0)
  auto_ok          documents whose key fields are all confident and that carry no warning/critical flag
                   (what the backend could accept without a person, if its rules agree)
  retake           photos refused with 'please retake'
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(ROOT))

from ocr_core import BadImage, load_engine, read_document  # noqa: E402
from tools.ocr.specimens import (as_phone_photo, fake_card, fake_death, render_death_certificate,  # noqa: E402
                             render_smart_cnic, to_jpeg)

VERSIONS = {"scan": None, "photo_mild": 0.6, "photo_hard": 1.2}


def run(n: int) -> dict:
    engine = load_engine()
    stats: dict = defaultdict(lambda: {"docs": 0, "fields": 0, "correct": 0, "silent_errors": 0, "flagged_errors": 0,
                                       "auto_ok": 0, "retake": 0, "seconds": 0.0, "errors": []})
    for i in range(n):
        people = [("death_certificate", fake_death(1000 + i, late=(i % 4 == 3)), render_death_certificate),
                  ("cnic", fake_card(2000 + i), render_smart_cnic)]
        for doc, person, render in people:
            page = render(person)
            for version, strength in VERSIONS.items():
                img = page if strength is None else as_phone_photo(page, seed=i, strength=strength)
                s = stats[f"{doc}/{version}"]
                s["docs"] += 1
                t0 = time.perf_counter()
                try:
                    result = read_document(engine, doc, to_jpeg(img))
                except BadImage as e:
                    s["retake"] += 1
                    s["errors"].append(f"#{i} retake: {e.reason}")
                    continue
                finally:
                    s["seconds"] += time.perf_counter() - t0
                fields = result["fields"]
                for key, want in person.expected().items():
                    got = fields[key]
                    s["fields"] += 1
                    if got["value"] == want:
                        s["correct"] += 1
                    elif got["needs_review"]:
                        s["flagged_errors"] += 1
                    else:
                        s["silent_errors"] += 1
                        s["errors"].append(f"#{i} {key}: got {got['value']!r}, want {want!r}")
                serious = [f for f in result["flags"] if f["severity"] in ("warning", "critical")]
                if result["overall_confidence"] >= result["review_threshold"] and not serious:
                    s["auto_ok"] += 1
    report = {}
    for key, s in sorted(stats.items()):
        report[key] = {
            "documents": s["docs"],
            "field_accuracy": round(s["correct"] / s["fields"], 4) if s["fields"] else None,
            "silent_errors": s["silent_errors"],
            "wrong_but_flagged_for_review": s["flagged_errors"],
            "auto_ok": s["auto_ok"],
            "retake": s["retake"],
            "avg_seconds": round(s["seconds"] / max(1, s["docs"]), 2),
            "examples": s["errors"][:10],
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="fake people per document type")
    ap.add_argument("--out", type=Path, help="write the report as JSON")
    args = ap.parse_args()
    report = run(args.n)
    print(f"{'set':32} {'docs':>4} {'field_acc':>9} {'silent':>6} {'flagged':>7} {'auto_ok':>7} {'retake':>6} {'sec':>5}")
    for key, r in report.items():
        print(f"{key:32} {r['documents']:4} {r['field_accuracy'] or 0:9.3f} {r['silent_errors']:6} "
              f"{r['wrong_but_flagged_for_review']:7} {r['auto_ok']:7} {r['retake']:6} {r['avg_seconds']:5}")
        for ex in r["examples"]:
            print("    ", ex)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
