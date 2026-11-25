# -*- coding: utf-8 -*-
"""PaddleOCR-VL-1.6 as a SECOND READER for CNICs and death certificates.

PaddleOCR-VL-1.6 (Baidu PaddlePaddle, Apache-2.0) is a 0.9B vision-language model for reading documents in 109
languages, Urdu included. It reads a whole image as text, but it gives no confidence per value and it is slow on
a laptop CPU, so it does not replace the main reader (RapidOCR + the field detector + the label rules, tuned and
fast). It is asked only when it can add something:

  * the Urdu (Nastaliq) name on the card, which the main reader cannot read at all. On an old green card the
    names are printed only in Urdu, so until now they came only from the identity record;
  * a key value the main reader is unsure of (needs_review): if the second reader independently reads the same
    CNIC number / date, confidence goes up; if it reads a different one, the value is marked disputed and goes to
    a person. It never silently changes a value.

Switch (environment variable OCR_VL):
    off          never used
    when_unsure  (default) only for green cards and for documents with a key field to check
    always       every document (slower; for measuring it: tools/ocr/evaluate_vl.py)
It is used only when its model folder exists (python tools/ocr/fetch_vl.py) and torch + transformers are
installed (requirements-vl.txt). Anything going wrong inside it is logged and ignored: the main reading stands.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

import numpy as np

from .config import SETTINGS
from .datatypes import Extraction, Field, Flag
from .normalize import cnic_digits, parse_date

log = logging.getLogger("lastmile.ocr.vl")
ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path(os.environ.get("OCR_VL_PATH") or ROOT / "models" / "paddleocr-vl-1.6")
HF_REPO = "PaddlePaddle/PaddleOCR-VL-1.6"
MODES = ("off", "when_unsure", "always")
PROMPT = "OCR:"
# The model's image budget is a pixel count (its card: 1280 * 28 * 28). Cards are small anyway; a certificate page
# is shrunk to this, which keeps the time down on a CPU.
MAX_PIXELS = int(os.environ.get("OCR_VL_MAX_PIXELS", 1280 * 28 * 28))
MAX_TOKENS = {"cnic": 256, "death_certificate": 1024}
AGREE_WEIGHT = 0.8      # how much an independent agreeing reading counts (no per-value confidence from the model)


def mode() -> str:
    m = (os.environ.get("OCR_VL") or "when_unsure").strip().lower()
    return m if m in MODES else "when_unsure"


# --------------------------------------------------------------------------- the model
class VLReader:
    """PaddleOCR-VL-1.6 through Hugging Face transformers (element-level OCR, no layout model needed)."""

    def __init__(self, folder: Path = FOLDER):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        threads = int(os.environ.get("OCR_VL_THREADS", "0"))
        if threads:
            torch.set_num_threads(threads)
        # bfloat16 halves the memory (~2 GB instead of ~4 GB); OCR_VL_DTYPE=float32 can be faster on older CPUs
        dtype = getattr(torch, os.environ.get("OCR_VL_DTYPE", "bfloat16"))
        try:
            self.model = AutoModelForImageTextToText.from_pretrained(str(folder), torch_dtype=dtype)
            self.processor = AutoProcessor.from_pretrained(str(folder))
        except (ValueError, KeyError, OSError):   # transformers too old for the built-in class: the model's own code
            self.model = AutoModelForImageTextToText.from_pretrained(str(folder), torch_dtype=dtype,
                                                                     trust_remote_code=True)
            self.processor = AutoProcessor.from_pretrained(str(folder), trust_remote_code=True)
        self.model = self.model.to("cpu").eval()
        self._torch = torch
        self._lock = threading.Lock()
        self.name = "PaddleOCR-VL-1.6"

    def read(self, image_bgr: np.ndarray, max_new_tokens: int = 256) -> str:
        from PIL import Image

        rgb = Image.fromarray(np.ascontiguousarray(image_bgr[:, :, ::-1]))
        messages = [{"role": "user", "content": [{"type": "image", "image": rgb}, {"type": "text", "text": PROMPT}]}]
        p = self.processor
        inputs = p.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt",
            images_kwargs={"size": {"shortest_edge": p.image_processor.min_pixels, "longest_edge": MAX_PIXELS}})
        with self._lock, self._torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return p.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()


_reader: VLReader | None = None
_error: str | None = None
_load_lock = threading.Lock()


def installed() -> bool:
    """The model folder is there (cheap check, nothing is loaded)."""
    return (FOLDER / "config.json").is_file()


def get() -> VLReader | None:
    """The reader, loaded once (about 10-30 s); None when it is off, not downloaded or failed to load."""
    global _reader, _error
    if mode() == "off" or not installed():
        return None
    if _reader is None and _error is None:
        with _load_lock:
            if _reader is None and _error is None:
                try:
                    t0 = time.time()
                    _reader = VLReader()
                    log.info("PaddleOCR-VL ready in %.0f s", time.time() - t0)
                except Exception as e:  # torch / transformers missing, broken files, not enough memory
                    _error = f"{type(e).__name__}: {e}"
                    log.error("PaddleOCR-VL could not start: %s", _error)
    return _reader


def status() -> dict:
    return {"mode": mode(), "downloaded": installed(), "ready": _reader is not None, "error": _error,
            "model": HF_REPO}


# --------------------------------------------------------------------------- reading its text
_ARABIC = re.compile(r"[؀-ۿ]")
_LABEL_NAME = re.compile(r"^\s*نام\s*[:：\-]?\s*(.*)$")
_LABEL_RELATIVE = [  # (pattern, relation)
    (re.compile(r"^\s*(?:والد\s*/\s*شوہر|والد\s*یا\s*شوہر)\s*کا\s*نام\s*[:：\-]?\s*(.*)$"), None),
    (re.compile(r"^\s*(?:والد\s*کا\s*نام|ولدیت|ولد)\s*[:：\-]?\s*(.*)$"), "Father"),
    (re.compile(r"^\s*(?:شوہر\s*کا\s*نام|زوجہ|زوجیت)\s*[:：\-]?\s*(.*)$"), "Husband"),
]
_NOT_A_NAME = ("پاکستان", "شناختی", "کارڈ", "جمہوریہ", "اسلامی", "تاریخ", "پیدائش", "نشان", "دستخط", "جنس", "ملک",
               "رہائش", "پتہ", "حکومت", "قومی", "نادرا", "منسوخ", "اجرا")


def _clean_name(s: str) -> str | None:
    s = re.sub(r"[0-9۰-۹:：\-–_|/\\.,،؛;()\[\]{}\"'*#]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    letters = len(_ARABIC.findall(s))
    if letters < 2 or len(s.split()) > 5 or any(w in s for w in _NOT_A_NAME) or re.search(r"[A-Za-z]", s):
        return None
    return s


def _lines(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", "\n", text or "")       # the model may wrap blocks in tags
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def urdu_names(text: str) -> dict:
    """The Urdu name and father's / husband's name from the card's text, when their labels are found.
    -> {'name': str|None, 'relative': str|None, 'relation': 'Father'|'Husband'|None}"""
    lines = _lines(text)
    out = {"name": None, "relative": None, "relation": None}

    def value(i: int, rest: str) -> str | None:
        if rest and _clean_name(rest):
            return _clean_name(rest)
        for nxt in lines[i + 1:i + 3]:                # the value printed on the next line (old green card)
            if _ARABIC.search(nxt) and not _LABEL_NAME.match(nxt) and not any(p.match(nxt) for p, _ in _LABEL_RELATIVE):
                return _clean_name(nxt)
        return None

    for i, ln in enumerate(lines):
        for pat, relation in _LABEL_RELATIVE:
            m = pat.match(ln)
            if m and out["relative"] is None:
                out["relative"], out["relation"] = value(i, m.group(1)), relation
                break
        else:
            m = _LABEL_NAME.match(ln)
            if m and out["name"] is None:
                out["name"] = value(i, m.group(1))
    return out


def cnic_numbers(text: str) -> list[str]:
    """Every CNIC number in the text, as 'XXXXX-XXXXXXX-X', in reading order, without repeats."""
    found = []
    for m in re.finditer(r"[0-9۰-۹OoIlSB]{5}\s*[-–]?\s*[0-9۰-۹OoIlSB]{7}\s*[-–]?\s*[0-9۰-۹OoIlSB]", text or ""):
        d = cnic_digits(m.group(0).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        if len(d) == 13:
            v = f"{d[:5]}-{d[5:12]}-{d[12]}"
            if v not in found:
                found.append(v)
    return found


def dates(text: str) -> list[str]:
    """Every full date in the text (ISO), in reading order."""
    out = []
    for m in re.finditer(r"\d{1,2}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*\d{4}|\d{4}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*\d{1,2}|"
                         r"\d{1,2}\s*[ -]?[A-Za-z]{3,9}\s*[ ,-]?\s*\d{4}", text or ""):
        d = parse_date(m.group(0))
        if d and d.isoformat() not in out:
            out.append(d.isoformat())
    return out


# --------------------------------------------------------------------------- using it on a reading
def should_run(ex: Extraction) -> bool:
    m = mode()
    if m == "off":
        return False
    if m == "always":
        return True
    if ex.doc_type == "cnic" and (ex.fields.get("card.type") and ex.fields["card.type"].value == "old_green"):
        return True
    return any(ex.fields.get(k) is None or ex.fields[k].value is None or ex.fields[k].needs_review
               for k in ex.key_fields)


def _agree(f: Field, what: str) -> None:
    joint = min(0.97, 1 - (1 - f.confidence) * (1 - AGREE_WEIGHT))
    f.confidence = max(f.confidence, joint)
    f.method += "+vl_agree"
    f.needs_review = f.confidence < SETTINGS.REVIEW_BELOW or (bool(f.note) and "differ" in (f.note or ""))
    f.note = f.note or f"the second reader (PaddleOCR-VL) also read this {what}"


def _dispute(f: Field, other: str) -> None:
    f.confidence = min(f.confidence, 0.7)
    f.needs_review = True
    f.method += "+vl_disputed"
    f.note = f"the second reader (PaddleOCR-VL) read {other}: a person should check"


def apply_cnic(ex: Extraction, text: str) -> dict:
    f, report = ex.fields, {}
    # 1) CNIC number: the front of a card carries exactly one
    nums = cnic_numbers(text)
    num = f.get("cnic")
    if num is not None and num.value and nums:
        if num.value in nums:
            if num.needs_review or num.confidence < 0.97:
                _agree(num, "CNIC number")
            report["cnic"] = "agree"
        elif len(nums) == 1:
            _dispute(num, nums[0])
            report["cnic"] = "differ"
    # 2) date of birth: the earliest full date on the card (issue and expiry come later)
    ds = sorted(dates(text))
    dob = f.get("date_of_birth")
    if ds and dob is not None:
        if dob.value and dob.value in ds:
            if dob.needs_review:
                _agree(dob, "date of birth")
            report["date_of_birth"] = "agree"
        elif dob.value and len(dob.value) == 10 and ds[0] != dob.value and dob.needs_review:
            _dispute(dob, ds[0])
            report["date_of_birth"] = "differ"
        elif not dob.value:
            f["date_of_birth"] = Field(ds[0], 0.6, True, ds[0], "paddleocr_vl",
                                       "read only by the second reader: check it against the card")
            ex.flags[:] = [fl for fl in ex.flags if not (fl.code == "MISSING_KEY_FIELD" and "date_of_birth" in fl.detail)]
            report["date_of_birth"] = "filled"
    # 3) the Urdu names, which the main reader cannot read
    ur = urdu_names(text)
    if ur["name"]:
        f["name_ur"] = Field(ur["name"], 0.75, True, ur["name"], "paddleocr_vl",
                             "the name printed in Urdu, read by the second reader")
        if f.get("name") is None or f["name"].value is None:     # old green card: Urdu is all there is
            f["name"] = Field(ur["name"], 0.75, True, ur["name"], "paddleocr_vl(urdu)",
                              "printed only in Urdu; read by the second reader, check it with the identity record")
        report["name_ur"] = "read"
    if ur["relative"]:
        f["father_or_husband_name_ur"] = Field(ur["relative"], 0.75, True, ur["relative"], "paddleocr_vl")
        if f.get("father_or_husband_name") is None or f["father_or_husband_name"].value is None:
            f["father_or_husband_name"] = Field(ur["relative"], 0.75, True, ur["relative"], "paddleocr_vl(urdu)",
                                                "printed only in Urdu; read by the second reader")
        rel = f.get("father_or_husband.relation")
        if ur["relation"] and (rel is None or rel.value is None):
            # the Urdu label says which ('والد کا نام' / 'شوہر کا نام'), where the English one often does not
            f["father_or_husband.relation"] = Field(ur["relation"], 0.8, True, None, "paddleocr_vl(urdu_label)")
        report["father_or_husband_name_ur"] = "read"
    if f.get("name_ur") and any(fl.code == "URDU_ONLY_FIELDS" for fl in ex.flags):
        ex.flags.append(Flag("URDU_NAMES_READ", "info",
                             "the Urdu names were read by the second reader; confirm them against the identity record"))
    return report


def apply_certificate(ex: Extraction, text: str) -> dict:
    """A certificate has many CNIC numbers (deceased, parents, spouse, applicant), so a number is only confirmed
    when the second reader found it somewhere on the page; one it did not find is left as it is."""
    f, report = ex.fields, {}
    nums, ds = cnic_numbers(text), dates(text)
    digits_text = re.sub(r"\D", "", (text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    for key in ("deceased.cnic", "applicant.cnic"):
        fld = f.get(key)
        if fld is not None and fld.value and fld.value in nums:
            if fld.needs_review:
                _agree(fld, "CNIC number")
            report[key] = "agree"
    fld = f.get("deceased.date_of_death")
    if fld is not None and fld.value and fld.value in ds:
        if fld.needs_review:
            _agree(fld, "date")
        report["deceased.date_of_death"] = "agree"
    fld = f.get("certificate.tracking_id")
    tid = re.sub(r"\D", "", str(fld.value or "")) if fld is not None else ""
    if len(tid) >= 6 and tid in digits_text:
        if fld.needs_review:
            _agree(fld, "tracking number")
        report["certificate.tracking_id"] = "agree"
    return report


def second_opinion(ex: Extraction, image: np.ndarray) -> None:
    """Ask the second reader when it can help, and fold its reading into `ex` (in place). Never raises."""
    try:
        if not should_run(ex):
            return
        reader = get()
        if reader is None:
            return
        t0 = time.perf_counter()
        text = reader.read(image, MAX_TOKENS.get(ex.doc_type, 512))
        report = apply_cnic(ex, text) if ex.doc_type == "cnic" else apply_certificate(ex, text)
        ex.quality["second_reader"] = {"model": reader.name, "ms": int((time.perf_counter() - t0) * 1000),
                                       "results": report}
        log.info("vl doc=%s ms=%d results=%s", ex.doc_type, ex.quality["second_reader"]["ms"],
                 ",".join(f"{k}:{v}" for k, v in report.items()) or "-")   # no values: personal data
    except Exception:  # noqa: BLE001 - the main reading stands
        log.exception("PaddleOCR-VL second reading failed")
        ex.quality["second_reader"] = {"model": "PaddleOCR-VL-1.6", "error": True}
