# -*- coding: utf-8 -*-
"""Step 12: document check for a CNIC photo (mock CNICs only).

What it does, honestly:
- OCR (Tesseract) -> text, average word confidence, CNIC number and name if it can find them
- Blur check (variance of the Laplacian) -> threshold `doc_blur_min`
- QR check (OpenCV) -> is there a QR, does the CNIC inside it agree with the printed CNIC and the account
- Edit checks: editing-software tag in EXIF + a simple error-level analysis (JPEG only)

None of this PROVES a document is real or fake. It raises flags; flags go to a human.
Thresholds `doc_blur_min` and `ocr_min_confidence` come from the active rule version.
"""
import io
import os
import re

import cv2
import numpy as np
import pytesseract
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs

if os.getenv("TESSERACT_CMD"):  # Windows: e.g. C:\Program Files\Tesseract-OCR\tesseract.exe
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
OCR_LANG = os.getenv("OCR_LANG", "eng")

NORMAL_SIDE = 1000  # blur and OCR are measured on this size so scores are comparable
EDIT_SOFTWARE = ("photoshop", "gimp", "canva", "picsart", "snapseed", "lightroom",
                 "paint.net", "pixlr", "facetune", "affinity")
# Error-level analysis tuning (not in the rule table on purpose; calibrate on your own samples).
ELA_QUALITY = 90
ELA_RATIO_FLAG = 4.0   # hottest 1% of blocks vs the median block
ELA_MIN_PEAK = 12.0    # ignore tiny absolute differences

_CNIC_RX = re.compile(r"(?<!\d)(\d{5})[-\s]?(\d{7})[-\s]?(\d)(?!\d)")


class BadImage(ValueError):
    pass


class OcrUnavailable(RuntimeError):
    pass


def _digits(cnic: str | None) -> str | None:
    d = re.sub(r"\D", "", cnic or "")
    return d if len(d) == 13 else None


def _find_cnic(text: str) -> str | None:
    m = _CNIC_RX.search(text or "")
    return "".join(m.groups()) if m else None


def _find_name(text: str) -> str | None:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        low = line.lower()
        if "name" in low and not any(w in low for w in ("father", "husband", "spouse")):
            after = re.sub(r"(?i)^.*?name\s*[:\-]?\s*", "", line).strip()
            cand = after if len(re.sub(r"[^A-Za-z]", "", after)) >= 3 else (lines[i + 1] if i + 1 < len(lines) else "")
            cand = re.sub(r"[^A-Za-z .'\-]", "", cand).strip()
            if len(cand) >= 3:
                return cand
    return None


def _normalised(img: Image.Image) -> Image.Image:
    w, h = img.size
    scale = NORMAL_SIDE / max(w, h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def _ocr(gray: np.ndarray) -> tuple[str, float]:
    try:
        data = pytesseract.image_to_data(gray, lang=OCR_LANG, config="--psm 6",
                                         output_type=pytesseract.Output.DICT)
        text = pytesseract.image_to_string(gray, lang=OCR_LANG, config="--psm 6")
    except pytesseract.TesseractNotFoundError as e:
        raise OcrUnavailable("Tesseract is not installed or TESSERACT_CMD is wrong.") from e
    confs = [float(c) for t, c in zip(data["text"], data["conf"]) if t.strip() and float(c) >= 0]
    return text, (round(sum(confs) / len(confs) / 100, 4) if confs else 0.0)


def _qr(img_rgb: Image.Image) -> str:
    det = cv2.QRCodeDetector()
    for side in (NORMAL_SIDE, 1600):
        w, h = img_rgb.size
        s = side / max(w, h)
        arr = cv2.cvtColor(np.asarray(img_rgb.resize((round(w * s), round(h * s)))), cv2.COLOR_RGB2BGR)
        text, _, _ = det.detectAndDecode(arr)
        if text:
            return text
    return ""


def _ela(img: Image.Image) -> dict | None:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    again = Image.open(buf).convert("RGB")
    diff = np.abs(np.asarray(img, dtype=np.int16) - np.asarray(again, dtype=np.int16)).max(axis=2).astype(np.float32)
    bs = 32
    h, w = (diff.shape[0] // bs) * bs, (diff.shape[1] // bs) * bs
    if h == 0 or w == 0:
        return None
    blocks = diff[:h, :w].reshape(h // bs, bs, w // bs, bs).mean(axis=(1, 3)).ravel()
    median, peak = float(np.median(blocks)), float(np.percentile(blocks, 99))
    return {"median": round(median, 2), "peak": round(peak, 2), "ratio": round(peak / (median + 1.0), 2)}


def _exif_software(img: Image.Image) -> str | None:
    try:
        exif = img.getexif()
    except Exception:
        return None
    tag = {v: k for k, v in ExifTags.TAGS.items()}.get("Software")
    val = exif.get(tag) if tag else None
    return str(val) if val else None


def check_document(data: bytes, rules: dict, rule_version: int | None = None,
                   claimed_cnic: str | None = None) -> dict:
    """action: auto | ask_more | human   (same words the name matcher uses)."""
    try:
        original = Image.open(io.BytesIO(data))
        original.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise BadImage("That file is not a readable image.") from e

    fmt = (original.format or "").upper()
    software = _exif_software(original)
    rgb = ImageOps.exif_transpose(original).convert("RGB")
    small = _normalised(rgb)
    gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)

    blur_min, ocr_min = rules["doc_blur_min"], rules["ocr_min_confidence"]
    flags: list[str] = []
    reasons: list[str] = []

    # --- blur
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blurry = blur_score < blur_min
    if blurry:
        flags.append("blurry")
    reasons.append(f"Sharpness score {blur_score:.0f} (needs at least {blur_min:.0f}).")

    # --- OCR
    text, ocr_conf = _ocr(gray)
    ocr_cnic, ocr_name = _find_cnic(text), _find_name(text)
    low_ocr = ocr_conf < ocr_min
    if low_ocr:
        flags.append("low_ocr_confidence")
    if not ocr_cnic:
        flags.append("no_cnic_found")
    reasons.append(f"Text reading confidence {ocr_conf:.2f} (needs at least {ocr_min:.2f}).")

    # --- QR
    payload = _qr(rgb)
    qr_cnic = _find_cnic(payload) if payload else None
    claimed = _digits(claimed_cnic)
    qr = {"found": bool(payload), "cnic_in_qr": bool(qr_cnic), "matches_printed_cnic": None, "matches_account_cnic": None}
    if not payload:
        flags.append("no_qr")
        reasons.append("No QR code could be read (older cards do not have one).")
    elif not qr_cnic:
        flags.append("qr_unreadable_payload")
        reasons.append("A QR code was found but it does not contain a CNIC number.")
    else:
        if ocr_cnic:
            qr["matches_printed_cnic"] = qr_cnic == ocr_cnic
            if not qr["matches_printed_cnic"]:
                flags.append("qr_cnic_mismatch")
                reasons.append("The CNIC in the QR code is different from the printed CNIC.")
        if claimed:
            qr["matches_account_cnic"] = qr_cnic == claimed
            if not qr["matches_account_cnic"]:
                flags.append("qr_account_mismatch")
                reasons.append("The CNIC in the QR code is different from the CNIC on the account.")

    printed_vs_account = None
    if ocr_cnic and claimed:
        printed_vs_account = ocr_cnic == claimed
        if not printed_vs_account:
            flags.append("printed_account_mismatch")
            reasons.append("The printed CNIC is different from the CNIC on the account.")

    # --- edit checks
    ela = None
    if software and any(s in software.lower() for s in EDIT_SOFTWARE):
        flags.append("edited_software")
        reasons.append(f"The file says it was saved by editing software ({software}).")
    if fmt in ("JPEG", "JPG"):
        ela = _ela(rgb)
        if ela and ela["ratio"] >= ELA_RATIO_FLAG and ela["peak"] >= ELA_MIN_PEAK:
            flags.append("ela_suspicious")
            reasons.append("Part of the image compresses differently from the rest (possible edit; weak signal).")
    else:
        reasons.append("Error-level edit check skipped: it only works on JPEG photos.")

    # --- action
    human_flags = {"qr_cnic_mismatch", "qr_account_mismatch", "edited_software", "ela_suspicious"}
    # A printed-CNIC mismatch is only trusted when the text was read well; otherwise it may just be an OCR slip.
    if "printed_account_mismatch" in flags and not low_ocr:
        human_flags.add("printed_account_mismatch")
    ask_flags = {"blurry", "low_ocr_confidence", "no_cnic_found", "qr_unreadable_payload", "printed_account_mismatch"}

    if human_flags & set(flags):
        action = "human"
        reasons.append("Something may be wrong with this document, so a human checks it.")
    elif ask_flags & set(flags):
        action = "ask_more"
        reasons.append("The photo is not good enough to read safely. Ask for a clearer photo.")
    else:
        action = "auto"
        reasons.append("Photo is clear and no edit signs were found.")

    # --- confidence (document quality, 0..1). Simple and explainable, not a trained model.
    conf = ocr_conf
    if blurry:
        conf *= 0.6
    if "ela_suspicious" in flags or "edited_software" in flags:
        conf *= 0.5
    if {"qr_cnic_mismatch", "qr_account_mismatch", "printed_account_mismatch"} & set(flags):
        conf *= 0.3
    if qr["matches_printed_cnic"] and qr["matches_account_cnic"] is not False:
        conf = min(1.0, conf + 0.1)
    if not ocr_cnic:
        conf *= 0.5

    return {
        "action": action, "confidence": round(conf, 4), "flags": flags,
        "ocr": {"confidence": ocr_conf, "text": text.strip()[:1500],
                "fields": {"cnic": ocr_cnic, "name": ocr_name}},
        "blur": {"score": round(blur_score, 1), "min_required": blur_min, "is_blurry": blurry},
        "qr": qr,
        "printed_cnic_matches_account": printed_vs_account,
        "edit_checks": {"file_format": fmt, "editing_software_tag": software, "ela": ela,
                        "ela_applicable": fmt in ("JPEG", "JPG")},
        "thresholds_used": {"doc_blur_min": blur_min, "ocr_min_confidence": ocr_min},
        "rule_version": rule_version, "reasons": reasons,
    }