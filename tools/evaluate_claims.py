# -*- coding: utf-8 -*-
"""Step 5 evaluation: run EVERY fake claim scenario through the real claim flow and count what happened.

    python -m tools.evaluate_claims               typed details only (plain buttons, no photos)
    python -m tools.evaluate_claims --documents   + SPECIMEN photos read by the OCR engine (slower: ~5 s a photo)
    python -m tools.evaluate_claims --only S09,S10 [--out part.json]   just these (not saved; --merge joins parts)

Uses a throw-away database, so the app's data is not touched. Writes data/evaluation.json (shown on the
auditor page and in the public API) and prints a table.

Each scenario carries a hidden truth (should this claim be paid?). The numbers:
  auto-approved        the system acted alone and paid             (good if should_pay)
  asked for proof      yellow: the citizen was asked for a photo / document
  sent to a person     red, or a payment problem: an officer decides
  wrongly blocked      should be paid, but was NOT approved automatically (extra work / delay for a genuine claim)
  wrongly approved     should NOT be paid, but was paid automatically (the dangerous mistake)
"""
import json
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(documents: bool, only: set | None = None):
    tmp = tempfile.mkdtemp(prefix="lm-eval-")
    import os
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/eval.db"
    os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
    os.environ["OCR_MOCK"] = "false"
    from sqlalchemy.orm import sessionmaker
    from app import ai_engines, rules
    from app.db import Base, engine
    from app.mock_services import store
    from app.models import Role, RuleVersion
    from tools import claim_runner

    if documents:
        if not (ROOT / "data" / "specimens" / "S01_cnic.jpg").exists():
            from tools import specimen_documents
            specimen_documents.main()
        ai_engines._load_ocr()
        if ai_engines._state["ocr"] is None:
            raise SystemExit("OCR engine could not start: " + str(ai_engines._state["ocr_error"]))
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    for name in ("citizen", "helper", "officer", "admin", "auditor"):
        db.add(Role(name=name, label=name, description=name))
    active = RuleVersion(version=1, config=rules.DEFAULT_RULES, note="evaluation")
    db.add(active)
    db.commit()
    store.reload()

    rows, t0 = [], time.time()
    need = set(only or ())
    need |= {s["after"] for s in claim_runner.scenarios() if s["id"] in need and s.get("after")}
    for s in claim_runner.scenarios():
        if only and s["id"] not in need:
            continue
        case = claim_runner.run(db, s, documents=documents)
        zone = {"paid": "auto_approved", "approved": "auto_approved", "waiting_citizen": "asked_for_proof",
                "escalated": "sent_to_person", "payment_failed": "sent_to_person"}[case.status]
        if case.status == "payment_failed":
            zone = "sent_to_person"
        if only and s["id"] not in only:
            continue  # a prerequisite (e.g. S01 for S23): run, not counted
        rows.append({"id": s["id"], "label": s["label"], "should_pay": s["truth"]["should_pay"], "why": s["truth"]["why"],
                     "expected": s["expected"], "outcome": case.outcome, "status": case.status, "zone": zone,
                     "confidence": case.confidence, "amount": case.amount})
    if only:  # a partial run never replaces the saved numbers
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path(tmp) / "evaluation.json"
        out.write_text(json.dumps({"cases": rows, "with_documents": documents}, ensure_ascii=False), encoding="utf-8")
        print(f"partial run ({len(rows)} claims) -> {out}")
        return
    save(rows, documents, active.version, round(time.time() - t0, 1))


def save(rows: list[dict], documents: bool, rule_version: int, seconds: float):
    genuine = [r for r in rows if r["should_pay"]]
    bad = [r for r in rows if not r["should_pay"]]
    z = Counter(r["zone"] for r in rows)
    summary = {
        "claims": len(rows), "genuine": len(genuine), "should_not_pay": len(bad),
        "auto_approved": z["auto_approved"], "asked_for_proof": z["asked_for_proof"], "sent_to_person": z["sent_to_person"],
        "wrongly_blocked": sum(r["zone"] != "auto_approved" for r in genuine),
        "wrongly_blocked_ids": [r["id"] for r in genuine if r["zone"] != "auto_approved"],
        "wrongly_approved": sum(r["zone"] == "auto_approved" for r in bad),
        "wrongly_approved_ids": [r["id"] for r in bad if r["zone"] == "auto_approved"],
        "genuine_paid_automatically_pct": round(100 * sum(r["zone"] == "auto_approved" for r in genuine) / max(1, len(genuine))),
        "bad_stopped_pct": round(100 * sum(r["zone"] != "auto_approved" for r in bad) / max(1, len(bad))),
        "matches_expected": sum(r["outcome"] == r["expected"] for r in rows),
        "with_documents": documents, "rule_version": rule_version,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": seconds,
    }
    out = ROOT / "data" / "evaluation.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    runs = {**old.get("runs", {}), ("documents" if documents else "plain"): {"summary": summary, "cases": rows}}
    main_run = runs.get("plain") or runs[("documents" if documents else "plain")]
    out.write_text(json.dumps({"summary": main_run["summary"], "cases": main_run["cases"], "runs": runs}, indent=1,
                              ensure_ascii=False), encoding="utf-8")

    print(f"{'id':<4} {'should pay':<10} {'zone':<16} {'outcome':<7} {'conf':>5}  scenario")
    for r in rows:
        mark = "!" if (r["should_pay"]) != (r["zone"] == "auto_approved") else " "
        print(f"{r['id']:<4} {str(r['should_pay']):<10} {r['zone']:<16} {r['outcome']:<7} {r['confidence'] or 0:>5.2f} {mark} {r['label']}")
    print(f"\n{summary['claims']} claims ({'with' if documents else 'without'} photos): auto-approved {summary['auto_approved']}, "
          f"asked for proof {summary['asked_for_proof']}, sent to a person {summary['sent_to_person']}")
    print(f"wrongly blocked {summary['wrongly_blocked']} of {summary['genuine']} genuine {summary['wrongly_blocked_ids']}; "
          f"wrongly approved {summary['wrongly_approved']} of {summary['should_not_pay']} {summary['wrongly_approved_ids']}")
    print(f"-> {out}")


def merge(paths: list[str]):
    """Join partial runs (--only ... --out) into the saved numbers, e.g. when the photo run is split in parts."""
    parts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    rows = {r["id"]: r for part in parts for r in part["cases"]}
    order = [s["id"] for s in json.loads((ROOT / "data" / "scenarios.json").read_text(encoding="utf-8"))]
    save([rows[i] for i in order if i in rows], parts[0].get("with_documents", True), 1, 0.0)


if __name__ == "__main__":
    if "--merge" in sys.argv:
        merge(sys.argv[sys.argv.index("--merge") + 1:])
    else:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
        main("--documents" in sys.argv, only)
