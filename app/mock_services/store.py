import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"  # project root / data


def _load(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run:  python -m scripts.make_fake_people")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def identity_by_cnic() -> dict:
    return {p["cnic"]: p for p in _load("mock_identity.json")}


@lru_cache
def death_records() -> dict:
    return {r["deceased_cnic"]: r for r in _load("mock_records.json")}


@lru_cache
def programme_by_cnic() -> dict:
    return _load("mock_programme.json")


@lru_cache
def accounts_by_cnic() -> dict:
    return _load("mock_accounts.json")


@lru_cache
def telco_by_phone() -> dict:
    return _load("mock_telco.json")


def reload() -> None:
    for f in (identity_by_cnic, death_records, programme_by_cnic, accounts_by_cnic, telco_by_phone):
        f.cache_clear()


def public(record: dict | None) -> dict | None:
    """Hide internal fields (those starting with an underscore, e.g. the hidden truth)."""
    return None if record is None else {k: v for k, v in record.items() if not k.startswith("_")}
