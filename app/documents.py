"""Uploaded document photos: read them (app/document_reader.py), keep the photo and the result
(documents table), write the audit entry. Field values never go into the audit log."""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_engines, audit, document_reader
from app.config import settings
from app.models import Case, Document, User

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
READERS = {"cnic": document_reader.read_cnic, "death_certificate": document_reader.read_death_certificate}


def read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is too large (max 8 MB)")
    if not data:
        raise HTTPException(422, "The file is empty.")
    return data


def read(doc_type: str, data: bytes, upload: UploadFile, cfg: dict, version: int, cnic: str | None, rid: str) -> dict:
    try:
        return READERS[doc_type](data, cfg, version, cnic, filename=upload.filename or f"{doc_type}.jpg",
                                 content_type=upload.content_type, request_id=rid)
    except document_reader.BadImage as e:
        raise HTTPException(422, str(e))


def outcome(res: dict) -> str:
    return "retake" if res.get("retake") else ("unavailable" if res.get("source") == "none" else "ok")


def audit_ocr(db: Session, user: User, doc_type: str, res: dict, rid: str, version: int,
              case_id: int | None = None, document_id: int | None = None):
    svc = res.get("service") or {}
    audit.record(db, "ai.ocr_run", actor=user, case_id=case_id,
                 details={"doc_type": doc_type, "document_id": document_id, "request_id": rid,
                          "source": res.get("source"), "outcome": outcome(res), "action": res["action"],
                          "overall_confidence": svc.get("overall_confidence"), "flags": res["flags"],
                          "rule_version": version})


def _store_photo(case_id: int, data: bytes, filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    rel = Path(f"case_{case_id}") / f"{uuid.uuid4().hex}{ext}"
    full = Path(settings.upload_dir) / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return rel.as_posix()


def read_and_store(db: Session, case: Case, user: User, doc_type: str, upload: UploadFile,
                   cfg: dict, version: int, claimant_cnic: str | None) -> tuple[dict, Document]:
    data = read_upload(upload)
    rid = ai_engines.new_request_id(f"case{case.id}-{doc_type}")
    res = read(doc_type, data, upload, cfg, version, claimant_cnic, rid)
    stored = dict(res)
    if isinstance(stored.get("ocr"), dict):
        stored["ocr"] = {**stored["ocr"], "text": ""}  # the fallback reader's raw text is not kept
    svc = res.get("service") or {}
    row = Document(case_id=case.id, doc_type=doc_type, file_ref=_store_photo(case.id, data, upload.filename),
                   source=res.get("source", "none"), outcome=outcome(res), action=res["action"], ocr_json=stored,
                   ocr_version=svc.get("ocr_version"), overall_confidence=svc.get("overall_confidence"),
                   status="retake" if res.get("retake") else "pending", request_id=rid, uploaded_by=user.id)
    db.add(row)
    db.flush()
    audit_ocr(db, user, doc_type, res, rid, version, case.id, row.id)
    return res, row


def latest(db: Session, case_id: int, doc_type: str) -> dict | None:
    """The most recent reading of this kind of document for the case."""
    row = db.scalars(select(Document).where(Document.case_id == case_id, Document.doc_type == doc_type)
                     .order_by(Document.id.desc()).limit(1)).first()
    return row.ocr_json if row else None


def photo_path(doc: Document) -> Path | None:
    p = Path(settings.upload_dir) / doc.file_ref if doc.file_ref else None
    return p if p and p.is_file() else None
