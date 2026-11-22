# -*- coding: utf-8 -*-
"""Creates ALL the fake data, from one place, so every part agrees:

    data/mock_identity.json   identity registry (mock NADRA): ~48 people, incl. tricky ones
    data/mock_records.json    death records (mock CRMS)
    data/mock_programme.json  programme list: income, dependants, already paid
    data/mock_accounts.json   bank accounts (mock)
    data/mock_telco.json      which CNIC each mobile number (SIM) is registered to (mock PTA / operators)
    data/scenarios.json       the claim scenarios: who claims for whom, and the HIDDEN truth
                              ("should this claim be paid?") used only by the evaluation

Everything is invented. Run from the project root:   python -m scripts.make_fake_people
The same data comes out on every run. Scenario S01 matches the OCR engine's mock answers
(data/ocr_fixtures/): Rukhsana Bibi claims after Muhammad Aslam.
"""
import json
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
TODAY = date(2026, 11, 22)

identity, records, programme, accounts, scenarios, telco = [], [], {}, {}, [], {}


def person(cnic, name, father_or_husband, dob, gender, city, marital="married", alive=True, died=None, truth=None,
           missing=()):
    rec = {"cnic": cnic, "full_name": name, "father_or_husband_name": father_or_husband, "dob": dob,
           "gender": gender, "marital_status": marital, "city": city, "phone": "0300-" + cnic[-9:-2],
           "life_status": "alive" if alive else "deceased", "date_of_death": died, "_truth_id": truth or cnic}
    for k in missing:  # tricky: fields missing from the registry
        rec[k] = None
    identity.append(rec)
    return rec


def death(deceased, applicant_cnic, applicant_name, relation, died, entry_days=9, tracking=None, district="Lahore"):
    d = date.fromisoformat(died)
    records.append({
        "tracking_id": tracking or ("8" + deceased["cnic"].replace("-", "")[:13]),
        "crms_no": "CRMS-" + deceased["cnic"][-9:-2],
        "deceased_cnic": deceased["cnic"], "deceased_name": deceased["full_name"], "deceased_dob": deceased["dob"],
        "date_of_death": died, "entry_date": (d + timedelta(days=entry_days)).isoformat(),
        "issue_date": (d + timedelta(days=entry_days + 2)).isoformat(), "entry_status": "Normal",
        "place_of_death": "Home", "district": district,
        "applicant_cnic": applicant_cnic, "applicant_name": applicant_name, "applicant_relation": relation,
    })


def scenario(sid, label, claimant, deceased_cnic, relation, should_pay, why, expected, email,
             income=18000, dependants=0, already_paid=False, account="active", message=None, phone=None,
             holder=None, **extra):
    programme[claimant["cnic"]] = {"programme": "Widow support (mock)", "monthly_income": income,
                                   "dependants": dependants, "already_paid": already_paid,
                                   "last_paid_on": "2026-03-01" if already_paid else None}
    if account:
        accounts[claimant["cnic"]] = {"account_id": "MOCKBANK-" + claimant["cnic"][-9:-2], "provider": "MockBank",
                                      "status": account, "holder_name": holder or claimant["full_name"]}
    scenarios.append({"id": sid, "label": label, "email": email,
                      "claimant": {"name": extra.pop("login_name", claimant["full_name"]), "cnic": claimant["cnic"],
                                   "phone": phone or claimant.get("phone") or "0301-0000000"},
                      "deceased_cnic": deceased_cnic, "relation": relation, "message": message,
                      "expected": expected, "truth": {"should_pay": should_pay, "why": why}, **extra})


# ---------------------------------------------------------------- the claims
# S01 clean (matches the OCR mock fixtures)
h = person("35202-1234567-1", "Muhammad Aslam", "Ghulam Rasool", "1958-03-02", "M", "Lahore", alive=False, died="2026-08-14")
w = person("35202-7654321-2", "Rukhsana Bibi", "Muhammad Aslam", "1962-05-20", "F", "Lahore", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-08-14")
scenario("S01", "clean claim", w, h["cnic"], "Wife", True, "genuine widow, all records agree", "green", "rukhsana@demo.pk")

clean = [("Nasreen Akhtar", "Tariq Mahmood", "Karachi"), ("Shazia Parveen", "Imran Ali", "Multan"),
         ("Bushra Iqbal", "Khalid Iqbal", "Faisalabad"), ("Sadia Hussain", "Zahid Hussain", "Peshawar")]
for i, (wn, hn, city) in enumerate(clean, start=2):
    h = person(f"3610{i}-4000{i:03d}-1", hn, "Abdul Hameed", f"196{i}-0{i}-1{i}", "M", city, alive=False, died=f"2026-0{i + 3}-0{i}")
    w = person(f"3610{i}-3000{i:03d}-2", wn, hn, f"197{i}-1{i % 3}-0{i}", "F", city, marital="widowed")
    death(h, w["cnic"], wn, "Wife", f"2026-0{i + 3}-0{i}", district=city)
    scenario(f"S0{i}", "clean claim", w, h["cnic"], "Wife", True, "genuine widow, all records agree", "green",
             f"{wn.split()[0].lower()}@demo.pk")

# S06 Muhammad / Mohammad: the registry spells the husband's name differently from the claim; still the same person
h = person("35201-4000060-3", "Mohammad Yousaf", "Mohd Siddique", "1955-01-09", "M", "Lahore", alive=False, died="2026-07-03")
w = person("35201-3000060-4", "Fatimah Bibi", "Muhammad Yousuf", "1960-02-11", "F", "Lahore", marital="widowed")
death(h, w["cnic"], "Fatima Bibi", "Wife", "2026-07-03")
scenario("S06", "Muhammad / Mohammad and Fatima / Fatimah spellings", w, h["cnic"], "Wife", True,
         "genuine; only the spelling differs", "green", "fatima@demo.pk", login_name="Fatima Bibi")

# S07 duplicate names: two different people called Ayesha Khan; the CNIC tells them apart
h = person("37405-4000070-5", "Asif Khan", "Gul Khan", "1961-04-04", "M", "Rawalpindi", alive=False, died="2026-06-20")
w = person("37405-3000070-6", "Ayesha Khan", "Asif Khan", "1966-06-06", "F", "Rawalpindi", marital="widowed")
person("37405-3000071-8", "Ayesha Khan", "Sher Khan", "1990-09-19", "F", "Rawalpindi", marital="married")
death(h, w["cnic"], w["full_name"], "Wife", "2026-06-20", district="Rawalpindi")
scenario("S07", "two people with the same name", w, h["cnic"], "Wife", True,
         "genuine; another Ayesha Khan exists", "green", "ayesha@demo.pk")

# S08 the husband claims (widower): spouses of either sex are eligible
h = person("35202-3000080-2", "Kausar Begum", "Sajjad Hussain", "1970-07-07", "F", "Lahore", alive=False, died="2026-05-15")
w = person("35202-4000080-1", "Sajjad Hussain", "Riaz Hussain", "1968-08-08", "M", "Lahore", marital="widowed")
death(h, w["cnic"], w["full_name"], "Husband", "2026-05-15")
scenario("S08", "widower claims", w, h["cnic"], "Husband", True, "genuine widower", "green", "sajjad@demo.pk")

# S09 registry record is missing fields -> ask for a CNIC photo
h = person("34101-4000090-7", "Rashid Mehmood", "Allah Ditta", "1957-05-05", "M", "Gujranwala", alive=False, died="2026-09-01")
w = person("34101-3000090-8", "Saima Rashid", "Rashid Mehmood", "1969-04-04", "F", "Gujranwala", marital="widowed",
           missing=("father_or_husband_name", "dob"))
death(h, w["cnic"], w["full_name"], "Wife", "2026-09-01", district="Gujranwala")
scenario("S09", "registry record missing fields", w, h["cnic"], "Wife", True,
         "genuine; the registry lacks her date of birth and husband's name", "yellow", "saima@demo.pk")

# S10 no death record yet -> ask for the death certificate
h = person("33100-4000100-9", "Abdul Ghafoor", "Noor Muhammad", "1950-10-10", "M", "Sargodha", alive=False, died="2026-10-12")
w = person("33100-3000100-0", "Zubaida Ghafoor", "Abdul Ghafoor", "1955-11-11", "F", "Sargodha", marital="widowed")
scenario("S10", "death not in the records yet", w, h["cnic"], "Wife", True,
         "genuine; the death was not yet entered in the records", "yellow", "zubaida@demo.pk",
         certificate={"tracking_id": "84100400010099", "entry_days": 6, "died": "2026-10-12"})

# S11 death registered three years late -> a person checks
h = person("38403-4000110-3", "Ghulam Abbas", "Fazal Din", "1949-12-12", "M", "Jhang", alive=False, died="2023-02-10")
w = person("38403-3000110-4", "Naseem Abbas", "Ghulam Abbas", "1953-01-21", "F", "Jhang", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2023-02-10", entry_days=1100, district="Jhang")
scenario("S11", "death registered 3 years late", w, h["cnic"], "Wife", True,
         "genuine; late registration needs a person to check", "red", "naseem@demo.pk")

# S12 large household -> amount above the automatic limit
h = person("35404-4000120-5", "Arshad Mahmood", "Nazir Ahmed", "1972-02-02", "M", "Okara", alive=False, died="2026-09-18")
w = person("35404-3000120-6", "Rubina Arshad", "Arshad Mahmood", "1978-03-03", "F", "Okara", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-09-18", district="Okara")
scenario("S12", "amount above the automatic limit", w, h["cnic"], "Wife", True,
         "genuine; 4 children make the amount large", "red", "rubina@demo.pk", dependants=4)

# S13 bank account blocked -> approved, but the payment fails -> a person sorts it out
h = person("35102-4000130-7", "Naveed Akram", "Akram Ali", "1969-06-16", "M", "Kasur", alive=False, died="2026-08-30")
w = person("35102-3000130-8", "Samina Naveed", "Naveed Akram", "1974-07-17", "F", "Kasur", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-08-30", district="Kasur")
scenario("S13", "bank account blocked", w, h["cnic"], "Wife", True,
         "genuine; payment fails, a person must fix the account", "green", "samina@demo.pk", account="blocked")

# S14 genuine widow who pastes a scam SMS she received -> a person checks, she is warned
h = person("35202-4000140-9", "Amjad Farooq", "Farooq Ahmed", "1963-09-09", "M", "Lahore", alive=False, died="2026-07-27")
w = person("35202-3000140-0", "Shabana Amjad", "Amjad Farooq", "1967-10-10", "F", "Lahore", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-07-27")
scenario("S14", "attaches a scam message she received", w, h["cnic"], "Wife", True,
         "genuine; the message is a scam aimed at her", "red", "shabana@demo.pk",
         message="آپ کی امدادی رقم روک دی گئی ہے۔ اسے جاری کرنے کے لیے فوراً اپنا شناختی کارڈ نمبر اور پن کوڈ اس نمبر پر بھیجیں 03001234567")

# S15 name typo between account and registry -> near match -> a person checks
h = person("36302-4000150-1", "Javed Iqbal", "Iqbal Hussain", "1960-01-15", "M", "Sahiwal", alive=False, died="2026-08-08")
w = person("36302-3000150-2", "Kausar Perveen", "Javed Iqbal", "1965-02-16", "F", "Sahiwal", marital="widowed")
death(h, w["cnic"], "Kausar Perveen", "Wife", "2026-08-08", district="Sahiwal")
scenario("S15", "name typed differently from the registry", w, h["cnic"], "Wife", True,
         "genuine; 'Kosar' vs 'Kausar'", "red", "kausar@demo.pk", login_name="Kosar Parveen")

# --- claims that should NOT be paid
# S16 applicant on the death record is the son, not the claimant
h = person("35301-4000160-3", "Mushtaq Ahmed", "Rehmat Ali", "1956-03-30", "M", "Bahawalpur", alive=False, died="2026-06-11")
w = person("35301-3000160-4", "Parveen Akhtar", "Mushtaq Ahmed", "1961-04-14", "F", "Bahawalpur", marital="widowed")
son = person("35301-4000161-5", "Bilal Mushtaq", "Mushtaq Ahmed", "1985-05-25", "M", "Bahawalpur")
death(h, son["cnic"], son["full_name"], "Son", "2026-06-11", district="Bahawalpur")
fake = person("35301-3000162-6", "Nargis Bibi", "Ali Raza", "1975-06-06", "F", "Bahawalpur", marital="married")
scenario("S16", "claims a death recorded for another family", fake, h["cnic"], "Wife", False,
         "she is not on the death record", "red", "nargis@demo.pk", phone=son["phone"])

# S17 the 'deceased' husband is alive in the registry
h = person("35202-4000170-7", "Waseem Akram", "Akram Khan", "1970-07-01", "M", "Lahore")
w = person("35202-3000170-8", "Tahira Waseem", "Waseem Akram", "1975-08-02", "F", "Lahore")
scenario("S17", "husband is alive in the registry", w, h["cnic"], "Wife", False,
         "the husband is alive", "red", "tahira@demo.pk")

# S18 already paid by the programme
h = person("34603-4000180-9", "Liaquat Ali", "Barkat Ali", "1959-09-19", "M", "Sialkot", alive=False, died="2025-12-02")
w = person("34603-3000180-0", "Razia Liaquat", "Liaquat Ali", "1964-10-20", "F", "Sialkot", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2025-12-02", district="Sialkot")
scenario("S18", "already paid this year", w, h["cnic"], "Wife", False,
         "the programme already paid her", "red", "razia@demo.pk", already_paid=True)

# S19 income above the programme limit
h = person("35202-4000190-1", "Faisal Qureshi", "Anwar Qureshi", "1966-11-11", "M", "Lahore", alive=False, died="2026-04-04")
w = person("35202-3000190-2", "Mehwish Faisal", "Faisal Qureshi", "1971-12-12", "F", "Lahore", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-04-04")
scenario("S19", "income above the limit", w, h["cnic"], "Wife", False,
         "household income PKR 120,000 a month", "red", "mehwish@demo.pk", income=120000)

# S20 the claimant's own CNIC belongs to someone who died (identity misuse)
h = person("35202-4000200-3", "Sarfraz Khan", "Habib Khan", "1958-02-28", "M", "Lahore", alive=False, died="2026-05-05")
w = person("35202-3000200-4", "Gulshan Sarfraz", "Sarfraz Khan", "1960-03-03", "F", "Lahore", alive=False, died="2026-06-01",
           marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-05-05")
scenario("S20", "claimant's CNIC belongs to a dead person", w, h["cnic"], "Wife", False,
         "the claimant herself is recorded as dead", "red", "gulshan@demo.pk")

# S21 brother of the deceased: not an eligible relation for a spouse benefit
h = person("35102-4000210-5", "Tanveer Ahmed", "Bashir Ahmed", "1975-05-15", "M", "Kasur", alive=False, died="2026-03-21",
           marital="single")
b = person("35102-4000211-7", "Nadeem Ahmed", "Bashir Ahmed", "1978-08-18", "M", "Kasur", marital="married")
death(h, b["cnic"], b["full_name"], "Brother", "2026-03-21", district="Kasur")
scenario("S21", "brother claims a spouse benefit", b, h["cnic"], "Brother", False,
         "brothers are not eligible for widow support", "red", "nadeem@demo.pk")

# S22 CNIC not in the registry at all (made-up number)
ghost = {"cnic": "35202-9999999-0", "full_name": "Sana Malik"}
h = person("35202-4000220-1", "Kamran Malik", "Saleem Malik", "1964-04-24", "M", "Lahore", alive=False, died="2026-08-01")
scenario("S22", "CNIC not in the registry", ghost, h["cnic"], "Wife", False,
         "the CNIC does not exist", "yellow", "sana@demo.pk", phone="0301-9999999")

# S23 second claim for a death that was already paid (S01's husband); seeded as a paid claim first
w2 = person("35202-3000230-6", "Kulsoom Aslam", "Muhammad Aslam", "1984-04-04", "F", "Lahore")
scenario("S23", "second claim for a death already paid", w2, "35202-1234567-1", "Wife", False,
         "Muhammad Aslam's widow was already paid (S01)", "red", "kulsoom@demo.pk", after="S01")

# S24 genuine widow, but the bank account is in her son's name -> payment held for a person
h = person("35202-4000240-5", "Riaz Ahmed", "Nazir Ahmed", "1962-02-12", "M", "Lahore", alive=False, died="2026-07-19")
w = person("35202-3000240-6", "Nusrat Parveen", "Riaz Ahmed", "1966-03-13", "F", "Lahore", marital="widowed")
death(h, w["cnic"], w["full_name"], "Wife", "2026-07-19")
scenario("S24", "bank account in her son's name", w, h["cnic"], "Wife", True,
         "genuine; the account must be in her own name", "green", "nusrat@demo.pk", holder="Ali Riaz")

# ---------------------------------------------------------------- other people in the registry (look-alikes)
person("35201-4000061-5", "Muhammad Yousuf", "Abdul Majeed", "1972-03-13", "M", "Lahore")      # not S06's husband
person("36103-3000031-4", "Shazia Perveen", "Arif Hussain", "1980-12-01", "F", "Multan")        # near S03's name
person("35202-3000011-0", "Rukhsana Bibi", "Ghulam Nabi", "1949-07-07", "F", "Lahore", marital="widowed")  # same name as S01
person("35202-4000012-1", "Mohammad Aslam", "Fazal Karim", "1977-01-17", "M", "Lahore")         # same name as S01's husband, alive
person("37405-4000072-9", "Muhammed Asif Khan", "Gul Khan", "1964-06-16", "M", "Rawalpindi")    # spelling look-alike

# every person's mobile number is registered to their own CNIC (as every Pakistani SIM is)
OPERATORS = {"0300": "Jazz (mock)", "0301": "Jazz (mock)"}
for p in identity:
    telco[p["phone"]] = {"cnic": p["cnic"], "name": p["full_name"], "operator": OPERATORS.get(p["phone"][:4], "mock")}

for f, obj in (("mock_telco.json", telco), ("mock_identity.json", identity), ("mock_records.json", records),
               ("mock_programme.json", programme), ("mock_accounts.json", accounts), ("scenarios.json", scenarios)):
    (DATA / f).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(identity)} people, {len(records)} death records, {len(scenarios)} claim scenarios -> {DATA}")
