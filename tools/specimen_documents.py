# -*- coding: utf-8 -*-
"""Makes SPECIMEN photos for every claim scenario: the front of the claimant's CNIC and a death certificate,
rendered as slightly distorted phone photos (invented people, watermarked SPECIMEN, no official branding).

    python -m tools.specimen_documents            -> data/specimens/S01_cnic.jpg, S01_certificate.jpg, ...

Use them in the live demo (upload them in the claim) and in  python -m tools.evaluate_claims --documents.
A claim that should not be paid gets the certificate its claimant would show (e.g. one naming herself)."""
import json
from datetime import date
from pathlib import Path

from tools.ocr.specimens import (FakeCard, FakeDeath, as_phone_photo, render_death_certificate, render_smart_cnic,
                                 to_jpeg)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "specimens"


def _d(s, fallback):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback


def main():
    data = ROOT / "data"
    ident = {p["cnic"]: p for p in json.loads((data / "mock_identity.json").read_text(encoding="utf-8"))}
    recs = {r["deceased_cnic"]: r for r in json.loads((data / "mock_records.json").read_text(encoding="utf-8"))}
    OUT.mkdir(parents=True, exist_ok=True)
    for n, s in enumerate(json.loads((data / "scenarios.json").read_text(encoding="utf-8"))):
        me = ident.get(s["claimant"]["cnic"], {})
        female = s["claimant"]["cnic"][-1] in "02468"
        dob = _d(me.get("dob"), date(1969, 4, 4))
        issue = date(2021, 3, 1)
        card = FakeCard(name=me.get("full_name") or s["claimant"]["name"],
                        father=me.get("father_or_husband_name") or "Rashid Mehmood", female=female,
                        cnic=s["claimant"]["cnic"], dob=dob, issue=issue, expiry=issue.replace(year=2031))
        (OUT / f"{s['id']}_cnic.jpg").write_bytes(to_jpeg(as_phone_photo(render_smart_cnic(card), 100 + n, 0.5)))

        dec = ident.get(s["deceased_cnic"], {"full_name": "Unknown", "dob": None})
        rec = recs.get(s["deceased_cnic"])
        cert = s.get("certificate") or {}
        died = _d((rec or {}).get("date_of_death") or cert.get("died"), date(2026, 8, 1))
        entry = _d((rec or {}).get("entry_date"), None) or date.fromordinal(died.toordinal() + cert.get("entry_days", 7))
        applicant_cnic = (rec or {}).get("applicant_cnic") or s["claimant"]["cnic"]
        applicant = (rec or {}).get("applicant_name") or s["claimant"]["name"]
        relation = (rec or {}).get("applicant_relation") or s["relation"]
        spouse = applicant if relation in ("Wife", "Husband") else (me.get("full_name") or s["claimant"]["name"])
        fd = FakeDeath(tracking_id=(rec or {}).get("tracking_id") or cert.get("tracking_id") or "84100400099999",
                       deceased_name=dec["full_name"], deceased_cnic=s["deceased_cnic"],
                       deceased_female=s["deceased_cnic"][-1] in "02468", dob=_d(dec.get("dob"), date(1955, 5, 5)),
                       death=died, father=dec.get("father_or_husband_name") or "Abdul Hameed", mother="Zainab Bibi",
                       spouse=spouse, spouse_cnic=applicant_cnic if relation in ("Wife", "Husband") else s["claimant"]["cnic"],
                       applicant=applicant, applicant_cnic=applicant_cnic, relation=relation, entry=entry)
        (OUT / f"{s['id']}_certificate.jpg").write_bytes(
            to_jpeg(as_phone_photo(render_death_certificate(fd), 200 + n, 0.5)))
    print(f"SPECIMEN photos for every scenario -> {OUT}")


if __name__ == "__main__":
    main()
