"""Does the second reader (PaddleOCR-VL-1.6) help, and what does it cost? Run on the laptop after fetch_vl.py.

    python tools/ocr/evaluate_vl.py --n 5                    # SPECIMEN documents: main reader alone vs. with VL
    python tools/ocr/evaluate_vl.py --photos tests/local_samples/cnic   # real card photos: what VL reads in Urdu

1) Specimens (tools/ocr/evaluate.py, OCR_VL=off and then OCR_VL=always): field accuracy, SILENT errors (wrong and not
   marked for review: must stay 0), documents a person must check, seconds per document.
2) --photos DIR: every image in DIR is read with OCR_VL=always and the Urdu names, the second reader's verdicts and
   its time are printed, so you can check them against the cards by eye. Nothing is saved (personal data).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def specimens(n: int):
    from tools.ocr.evaluate import run
    rows = {}
    for m in ("off", "always"):
        os.environ["OCR_VL"] = m
        t0 = time.time()
        rows[m] = run(n)
        print(f"OCR_VL={m}: {time.time() - t0:.0f} s")
    print(f"\n{'set':28} {'':>3} {'field_acc':>9} {'silent':>6} {'flagged':>7} {'auto_ok':>7} {'sec':>6}")
    for key in rows["off"]:
        for m in ("off", "always"):
            r = rows[m][key]
            print(f"{key if m == 'off' else '':28} {'VL' if m == 'always' else '-':>3} {r['field_accuracy'] or 0:9.3f} "
                  f"{r['silent_errors']:6} {r['wrong_but_flagged_for_review']:7} {r['auto_ok']:7} {r['avg_seconds']:6}")
    worse = [k for k in rows["off"] if rows["always"][k]["silent_errors"] > rows["off"][k]["silent_errors"]]
    print("\nSILENT errors went UP on: " + ", ".join(worse) if worse else "\nNo more silent errors with VL.")


def photos(folder: Path):
    from ocr_core import BadImage, load_engine, read_document
    from ocr_core import vl
    os.environ["OCR_VL"] = "always"
    if vl.get() is None:
        sys.exit(f"PaddleOCR-VL is not available: {vl.status()}")
    engine = load_engine()
    for p in sorted(x for x in folder.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")):
        try:
            r = read_document(engine, "cnic", p.read_bytes())
        except BadImage as e:
            print(f"{p.name}: retake ({e.reason})")
            continue
        f, sr = r["fields"], r["quality"].get("second_reader", {})
        v = lambda k: (f.get(k) or {}).get("value")
        print(f"{p.name}: card={v('card.type')} name={v('name')!r} name_ur={v('name_ur')!r} "
              f"relative_ur={v('father_or_husband_name_ur')!r} relation={v('father_or_husband.relation')} "
              f"vl={sr.get('results')} {sr.get('ms', '?')} ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--photos", type=Path)
    a = ap.parse_args()
    if a.photos:
        photos(a.photos)
    else:
        specimens(a.n)


if __name__ == "__main__":
    main()
