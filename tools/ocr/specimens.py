"""Render SPECIMEN test documents for fake people, plus 'phone photo' distortions.

These are simplified look-alikes of the two layouts the service reads (same labels, same
left/right structure), watermarked SPECIMEN and carrying no emblem or official branding. They exist
so the test suite and the Step 5 evaluation run on invented data and never on real people's papers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

GIVEN_M = ["Muhammad", "Ahmed", "Ali", "Usman", "Bilal", "Imran", "Tariq", "Zahid", "Khalid", "Rashid", "Asif"]
GIVEN_F = ["Ayesha", "Fatima", "Rukhsana", "Nasreen", "Shazia", "Saima", "Bushra", "Rubina", "Kausar", "Sadia"]
FAMILY = ["Khan", "Aslam", "Iqbal", "Hussain", "Butt", "Malik", "Qureshi", "Sheikh", "Akhtar", "Mahmood", "Baig"]
RELATIONS = ["Wife", "Son", "Daughter", "Brother", "Husband"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def fake_cnic(rng: random.Random, female: bool) -> str:
    last = rng.choice([0, 2, 4, 6, 8] if female else [1, 3, 5, 7, 9])
    return f"3{rng.randint(1000, 9999)}-{rng.randint(1000000, 9999999)}-{last}"


def dmy(d: date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


@dataclass
class FakeDeath:
    tracking_id: str
    deceased_name: str
    deceased_cnic: str
    deceased_female: bool
    dob: date
    death: date
    father: str
    mother: str
    spouse: str
    spouse_cnic: str
    applicant: str
    applicant_cnic: str
    relation: str
    entry: date

    def expected(self) -> dict:
        return {"certificate.tracking_id": self.tracking_id, "deceased.name": self.deceased_name,
                "deceased.cnic": self.deceased_cnic, "deceased.date_of_birth": self.dob.isoformat(),
                "deceased.date_of_death": self.death.isoformat(),
                "deceased.gender": "Female" if self.deceased_female else "Male",
                "father.name": self.father, "mother.name": self.mother, "spouse.name": self.spouse,
                "spouse.cnic": self.spouse_cnic, "applicant.name": self.applicant,
                "applicant.cnic": self.applicant_cnic, "applicant.relation": self.relation,
                "certificate.entry_date": self.entry.isoformat()}


def fake_death(seed: int, late: bool = False) -> FakeDeath:
    rng = random.Random(seed)
    female = rng.random() < 0.5
    fam = rng.choice(FAMILY)
    name = f"{rng.choice(GIVEN_F if female else GIVEN_M)} {fam}"
    spouse = f"{rng.choice(GIVEN_M if female else GIVEN_F)} {fam}"
    dob = date(rng.randint(1935, 1975), rng.randint(1, 12), rng.randint(1, 28))
    death = date(rng.randint(2018, 2026), rng.randint(1, 12), rng.randint(1, 28))
    if death > date(2026, 10, 1):
        death = date(2026, 9, rng.randint(1, 28))
    entry = death + timedelta(days=rng.randint(400, 3000) if late else rng.randint(2, 40))
    relation = rng.choice(RELATIONS[:4]) if female else rng.choice(["Wife", "Son", "Daughter", "Brother"])
    if female and relation == "Wife":
        relation = "Husband"
    applicant_cnic = fake_cnic(rng, relation in ("Wife", "Daughter"))
    applicant = spouse if relation in ("Wife", "Husband") else \
        f"{rng.choice(GIVEN_F if relation == 'Daughter' else GIVEN_M)} {fam}"
    if relation in ("Wife", "Husband"):
        spouse_cnic = applicant_cnic
    else:
        spouse_cnic = fake_cnic(rng, not female)
    return FakeDeath(
        tracking_id=str(rng.randint(10**13, 10**14 - 1)), deceased_name=name,
        deceased_cnic=fake_cnic(rng, female), deceased_female=female, dob=dob, death=death,
        father=f"{rng.choice(GIVEN_M)} {rng.choice(FAMILY)}", mother=f"{rng.choice(GIVEN_F)} Bibi",
        spouse=spouse, spouse_cnic=spouse_cnic, applicant=applicant, applicant_cnic=applicant_cnic,
        relation=relation, entry=entry)


def _watermark(img: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((img.width * 0.12, img.height * 0.42), "SPECIMEN", font=font(int(img.width * 0.16)), fill=(200, 60, 60, 40))
    layer = layer.rotate(30, center=(img.width / 2, img.height / 2))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def render_death_certificate(p: FakeDeath) -> np.ndarray:
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f, fb, small = font(24), font(30), font(20)
    d.text((W / 2, 50), "SPECIMEN - TEST DATA ONLY - NOT A REAL DOCUMENT", font=small, fill="black", anchor="mm")
    d.text((60, 110), f"Tracking Id: {p.tracking_id}", font=small, fill="black")
    d.text((60, 140), f"CRMS No: D{p.tracking_id[-9:]}", font=small, fill="black")
    d.text((W / 2, 130), "Death Registration Certificate", font=fb, fill="black", anchor="mm")
    y = [180]

    def header(text: str) -> None:
        y[0] += 20
        d.rectangle([40, y[0], W - 40, y[0] + 40], outline="black", width=2)
        d.text((W / 2, y[0] + 20), text, font=f, fill="black", anchor="mm")
        y[0] += 56

    def row(label: str, value: str, copy: bool = False) -> None:
        d.text((60, y[0]), label, font=f, fill="black")
        d.text((330, y[0]), value, font=f, fill="black")
        if copy and value:
            d.text((860, y[0]), value, font=f, fill="black")
        y[0] += 40

    header("Deceased Person's Details")
    row("Name :", p.deceased_name)
    row("Nationality :", "Pakistani")
    row("CNIC No :", p.deceased_cnic, True)
    row("Date of Birth :", dmy(p.dob), True)
    row("Gender :", "Female" if p.deceased_female else "Male")
    row("Date of Death :", dmy(p.death), True)
    row("Date of Burial/Last rite :", dmy(p.death), True)
    row("Place of Death :", "HOME")
    row("Reason of Death :", "Natural")
    header("Parental Information")
    row("Father's Name :", p.father)
    row("CNIC No :", "")
    row("Mother's Name :", p.mother)
    row("CNIC No :", "")
    header("Wife's Information" if not p.deceased_female else "Husband's Information")
    row("Name :", p.spouse)
    row("CNIC No :", p.spouse_cnic, True)
    header("Address")
    row("Address :", "House No. 12, Street 4, Model Town, City Lahore")
    row("Tehsil :", "Lahore City")
    row("District :", "Lahore")
    header("Applicant's Details")
    row("Name :", p.applicant)
    row("CNIC No :", p.applicant_cnic, True)
    d.text((60, y[0]), f"Relation with Deceased: {p.relation}", font=f, fill="black")
    y[0] += 40
    row("Entry Date :", dmy(p.entry), True)
    row("Issue Date :", dmy(p.entry), True)
    row("Entry Status :", "Normal")
    img = _watermark(img)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@dataclass
class FakeCard:
    name: str
    father: str
    female: bool
    cnic: str
    dob: date
    issue: date
    expiry: date

    def expected(self) -> dict:
        return {"cnic": self.cnic, "name": self.name, "father_or_husband_name": self.father,
                "gender": "Female" if self.female else "Male", "date_of_birth": self.dob.isoformat(),
                "date_of_issue": self.issue.isoformat(), "date_of_expiry": self.expiry.isoformat()}


def fake_card(seed: int) -> FakeCard:
    rng = random.Random(seed)
    female = rng.random() < 0.5
    fam = rng.choice(FAMILY)
    issue = date(rng.randint(2016, 2025), rng.randint(1, 12), rng.randint(1, 28))
    return FakeCard(name=f"{rng.choice(GIVEN_F if female else GIVEN_M)} {fam}",
                    father=f"{rng.choice(GIVEN_M)} {fam}", female=female, cnic=fake_cnic(rng, female),
                    dob=date(rng.randint(1950, 2004), rng.randint(1, 12), rng.randint(1, 28)), issue=issue,
                    expiry=issue.replace(year=issue.year + 10))


def render_smart_cnic(c: FakeCard) -> np.ndarray:
    """Card-shaped layout with labels above values, like the smart CNIC front."""
    W, H = 1012, 638
    img = Image.new("RGB", (W, H), (226, 240, 228))
    d = ImageDraw.Draw(img)
    lab, val, small = font(20), font(30), font(18)
    d.text((W / 2, 30), "SPECIMEN - TEST CARD - NOT VALID", font=small, fill=(40, 40, 40), anchor="mm")
    d.rectangle([700, 120, 960, 420], outline=(120, 120, 120), width=2)

    def field(x: int, y: int, label: str, value: str) -> None:
        d.text((x, y), label, font=lab, fill=(30, 90, 50))
        d.text((x, y + 28), value, font=val, fill=(10, 10, 10))

    field(40, 110, "Name", c.name)
    field(40, 190, "Father Name", c.father)
    field(40, 270, "Gender", "F" if c.female else "M")
    field(260, 270, "Country of Stay", "Pakistan")
    field(40, 350, "Identity Number", c.cnic)
    field(380, 350, "Date of Birth", f"{c.dob.day:02d}.{c.dob.month:02d}.{c.dob.year}")
    field(40, 430, "Date of Issue", f"{c.issue.day:02d}.{c.issue.month:02d}.{c.issue.year}")
    field(380, 430, "Date of Expiry", f"{c.expiry.day:02d}.{c.expiry.month:02d}.{c.expiry.year}")
    img = _watermark(img)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def render_cnic_back(c: FakeCard, qr: bool = True) -> np.ndarray:
    """A card back: address text, the number and (optionally) a QR code, but no photo, no labels
    and no date of birth."""
    W, H = 1012, 638
    img = Image.new("RGB", (W, H), (226, 240, 228))
    d = ImageDraw.Draw(img)
    f, small = font(26), font(18)
    d.text((W / 2, 30), "SPECIMEN - TEST CARD BACK - NOT VALID", font=small, fill=(40, 40, 40), anchor="mm")
    d.text((40, 120), "House No. 12, Street 4, Model Town, Lahore", font=f, fill=(10, 10, 10))
    d.text((40, 170), "Lahore, Punjab", font=f, fill=(10, 10, 10))
    d.text((40, 520), c.cnic, font=font(34), fill=(10, 10, 10))
    out = cv2.cvtColor(np.asarray(_watermark(img)), cv2.COLOR_RGB2BGR)
    if qr:
        code = cv2.QRCodeEncoder.create().encode("SPECIMEN-CARD-BACK")
        code = cv2.resize(code, (220, 220), interpolation=cv2.INTER_NEAREST)
        code = cv2.copyMakeBorder(code, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=255)
        out[300:300 + code.shape[0], 740:740 + code.shape[1]] = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
    return out


def as_phone_photo(img: np.ndarray, seed: int, strength: float = 1.0) -> np.ndarray:
    """Place the document on a table at a slight angle and perspective, with uneven light, mild
    blur and JPEG compression."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    pad = int(0.12 * max(h, w))
    table = np.full((h + 2 * pad, w + 2 * pad, 3), rng.integers(40, 110, 3), np.uint8)
    j = 0.04 * strength
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[pad + rng.uniform(-j, j) * w, pad + rng.uniform(-j, j) * h],
                      [pad + w + rng.uniform(-j, j) * w, pad + rng.uniform(-j, j) * h],
                      [pad + w + rng.uniform(-j, j) * w, pad + h + rng.uniform(-j, j) * h],
                      [pad + rng.uniform(-j, j) * w, pad + h + rng.uniform(-j, j) * h]])
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, m, (table.shape[1], table.shape[0]), dst=table, borderMode=cv2.BORDER_TRANSPARENT)
    yy, xx = np.mgrid[0:out.shape[0], 0:out.shape[1]]
    light = 1 - 0.18 * strength * (xx / out.shape[1]) * rng.uniform(0.5, 1)
    out = np.clip(out * light[..., None], 0, 255).astype(np.uint8)
    if strength > 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(85 - 15 * strength)])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def to_jpeg(img: np.ndarray, quality: int = 90) -> bytes:
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return enc.tobytes()
