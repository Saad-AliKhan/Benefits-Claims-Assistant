"""Versioned rules (the "config" for the decision zones). Rows are never edited: a change = a new version,
and every decision stores the version it used. The admin changes them on /admin."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, RuleVersion

# Version 1 is seeded by the migration using these values.
DEFAULT_RULES: dict[str, float | int] = {
    "auto_approve_min_confidence": 0.85,  # at or above -> green (act alone)
    "human_review_below_confidence": 0.60,  # below -> red (send to human)
    "max_auto_amount": 50000,  # PKR; above this a human must approve, whatever the confidence
    "name_match_auto_min": 0.92,  # name similarity: confident match
    "name_match_review_min": 0.75,  # name similarity: near match -> human
    "scam_block_min": 0.80,  # scam score at or above -> block / red
    "doc_blur_min": 100.0,  # Laplacian variance; below -> blurry photo
    "ocr_min_confidence": 0.70,  # OCR confidence below -> ask for a better photo
    "max_monthly_income": 50000,  # PKR; household income above this is not eligible (a person confirms)
    "late_registration_days": 365,  # death entered in the records this many days late -> a person checks
}

# key -> (min, max)
LIMITS: dict[str, tuple[float, float]] = {
    "auto_approve_min_confidence": (0.0, 1.0),
    "human_review_below_confidence": (0.0, 1.0),
    "max_auto_amount": (0, 10_000_000),
    "name_match_auto_min": (0.0, 1.0),
    "name_match_review_min": (0.0, 1.0),
    "scam_block_min": (0.0, 1.0),
    "doc_blur_min": (0.0, 5000.0),
    "ocr_min_confidence": (0.0, 1.0),
    "max_monthly_income": (0, 10_000_000),
    "late_registration_days": (1, 10_000),
}


class RuleError(ValueError):
    pass


def validate(config: dict) -> dict:
    """Returns a clean copy or raises RuleError with a readable message."""
    unknown = set(config) - set(DEFAULT_RULES)
    if unknown:
        raise RuleError(f"Unknown rule keys: {sorted(unknown)}")
    missing = set(DEFAULT_RULES) - set(config)
    if missing:
        raise RuleError(f"Missing rule keys: {sorted(missing)}")
    clean = {}
    for key, value in config.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuleError(f"{key} must be a number")
        lo, hi = LIMITS[key]
        if not lo <= value <= hi:
            raise RuleError(f"{key} must be between {lo} and {hi}")
        clean[key] = value
    if clean["human_review_below_confidence"] >= clean["auto_approve_min_confidence"]:
        raise RuleError("human_review_below_confidence must be lower than auto_approve_min_confidence")
    if clean["name_match_review_min"] >= clean["name_match_auto_min"]:
        raise RuleError("name_match_review_min must be lower than name_match_auto_min")
    return clean


def get_active(db: Session) -> RuleVersion:
    row = db.scalars(select(RuleVersion).order_by(RuleVersion.version.desc()).limit(1)).first()
    if row is None:  # migration seeds v1, so this only happens on a broken DB
        raise RuleError("No rule version found. Run: alembic upgrade head")
    return row


def get_version(db: Session, version: int) -> RuleVersion | None:
    return db.scalars(select(RuleVersion).where(RuleVersion.version == version)).first()


def list_versions(db: Session) -> list[RuleVersion]:
    return list(db.scalars(select(RuleVersion).order_by(RuleVersion.version.desc())))


def create_version(
    db: Session, changes: dict, actor_id: int | None, actor_role: str, note: str = ""
) -> RuleVersion:
    """Merge `changes` onto the active rules and store as a NEW version."""
    current = get_active(db)
    merged = validate({**current.config, **changes})
    new = RuleVersion(
        version=current.version + 1,
        config=merged,
        note=note,
        created_by_id=actor_id,
    )
    db.add(new)
    db.add(
        AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action="rules.new_version",
            details={
                "from_version": current.version,
                "to_version": new.version,
                "changed": {k: [current.config[k], merged[k]] for k in changes if current.config[k] != merged[k]},
                "note": note,
            },
        )
    )
    db.commit()
    db.refresh(new)
    return new