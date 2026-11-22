# -*- coding: utf-8 -*-
"""Demo data: fake people, login accounts for every role, and (optionally) claims already in progress.

    python -m scripts.seed                 accounts only
    python -m scripts.seed --demo-claims   + runs most scenarios, so the officer queue and the auditor have data

Every demo account's password is  demo1234.  Staff: officer@demo.pk, officer2@demo.pk, admin@demo.pk,
auditor@demo.pk, helper@demo.pk. Citizens: one per scenario in data/scenarios.json (e.g. rukhsana@demo.pk).
Scenarios LEFT FOR THE LIVE DEMO (not run): see LIVE below.
"""
import sys

from app.consent import grant
from app.db import SessionLocal
from app.mock_services import store
from tools import claim_runner

STAFF = [("officer@demo.pk", "Officer Hina Qureshi", "officer"), ("officer2@demo.pk", "Officer Bilal Ahmed", "officer"),
         ("admin@demo.pk", "Admin Salman Naqvi", "admin"), ("auditor@demo.pk", "Auditor Maryam Rizvi", "auditor"),
         ("helper@demo.pk", "Helper Ayesha (community worker)", "helper")]
LIVE = ("S01", "S09", "S10", "S23")  # Rukhsana (green), Saima (asks for proof), Zubaida (no record), Kulsoom (after S01)


def main(demo_claims: bool):
    store.reload()
    db = SessionLocal()
    for email, name, role in STAFF:
        claim_runner.ensure_user(db, email, name, role)
    people = {s["id"]: claim_runner.claimant(db, s) for s in claim_runner.scenarios()}
    # Helper Mode: two families allow the community worker to help them
    helper = claim_runner.ensure_user(db, "helper@demo.pk", "", "helper")
    for sid in ("S01", "S10"):
        grant(db, people[sid], "helper_access", actor=people[sid], helper=helper)
    db.commit()
    print(f"accounts: {len(STAFF)} staff + {len(people)} citizens (password: {claim_runner.DEMO_PASSWORD})")
    if demo_claims:
        from app.models import Case
        if db.query(Case).count():
            print("claims already exist: skipped")
        else:
            for s in claim_runner.scenarios():
                if s["id"] in LIVE:
                    continue
                case = claim_runner.run(db, s)
                print(f"  {s['id']}  {case.status:<16} {s['label']}")
    db.close()


if __name__ == "__main__":
    main("--demo-claims" in sys.argv)
