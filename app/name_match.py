"""Step 10: name matching that tolerates spelling variants but never guesses.

Rules of thumb used here:
- Muhammad / Mohammad / Muhammed (etc.) are the SAME token after normalising.
- Word order does not matter ("Ali Muhammad" == "Muhammad Ali").
- CNIC is a stronger signal than a name, but a CNIC that disagrees with the name goes to a human.
- Anything that is not a clear single match goes to a human (or asks for more info).

Pure functions: no database access. Thresholds come from the active rule version
(`name_match_auto_min`, `name_match_review_min`), so the admin can change them live.
"""
import re
import unicodedata

from rapidfuzz import fuzz

# canonical spelling -> spellings seen in real documents
_VARIANTS = {
    "muhammad": ["mohammad", "muhammed", "mohammed", "muhamad", "mohamad", "mohamed", "muhammd",
                 "mohd", "muhd", "md", "m"],
    "ahmad": ["ahmed", "ahmid"],
    "hussain": ["hussein", "husain", "hosain", "hossain", "husein"],
    "hasan": ["hassan", "hasan"],
    "fatima": ["fatimah", "fatema", "fatma"],
    "ayesha": ["aisha", "aysha", "ayisha", "aishah"],
    "khadija": ["khadeeja", "khadijah", "khadiza", "khadeja"],
    "zainab": ["zaynab", "zeinab", "zaineb"],
    "abdul": ["abdur", "abdel", "abd", "abdu"],
    "rehman": ["rahman", "rahmaan", "reham", "rahmaan"],
    "usman": ["osman", "uthman", "othman"],
    "yousuf": ["yusuf", "yousaf", "yousef", "yusuff", "yousuph"],
    "ibrahim": ["ebrahim", "ibraheem", "ebraheem"],
    "ismail": ["ismael", "esmail", "ismaeel", "ismaiel"],
    "shaikh": ["sheikh", "shaikh", "shaykh", "shaik"],
    "nasreen": ["nasrin", "nasreen", "nazreen"],
    "parveen": ["parvin", "perveen", "pervin"],
    "bibi": ["bibee", "bebe"],
    "begum": ["begam", "bagum"],
    "iqbal": ["eqbal", "ikbal"],
    "sultana": ["sultanah"],
    "akhtar": ["akhter", "akhtr"],
    "naeem": ["nayem", "naim", "nayeem"],
}
CANON = {v: c for c, vs in _VARIANTS.items() for v in vs}
for c in _VARIANTS:
    CANON[c] = c

HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "late", "mst", "musammat", "sh"}
# Very common tokens: they must not make two different people look alike.
COMMON = {"muhammad", "bibi", "begum"}


def tokens(name: str) -> list[str]:
    """'Mohammad  ALI Khan' -> ['muhammad', 'ali', 'khan']"""
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    parts = re.sub(r"[^a-z]+", " ", folded.lower()).split()
    return [CANON.get(p, p) for p in parts if p not in HONORIFICS]


def normalize_cnic(cnic: str | None) -> str | None:
    digits = re.sub(r"\D", "", cnic or "")
    return digits if len(digits) == 13 else None


def name_score(a: str, b: str) -> float:
    """0..1. Takes the stricter of 'whole name' and 'distinctive words only'. When either name is written in
    Urdu, the English one is converted into Urdu and the two are compared there (app/urdu_names.py)."""
    from app.urdu_names import has_urdu, same_name_score
    if has_urdu(a) or has_urdu(b):
        return same_name_score(a, b)
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    full = fuzz.token_sort_ratio(" ".join(ta), " ".join(tb)) / 100
    da = [t for t in ta if t not in COMMON]
    db = [t for t in tb if t not in COMMON]
    if da and db:
        distinct = fuzz.token_sort_ratio(" ".join(da), " ".join(db)) / 100
        return round(min(full, distinct), 4)
    return round(full, 4)


def match_name(name: str, cnic: str | None, candidates: list[dict], rules: dict, rule_version: int | None = None) -> dict:
    """candidates: [{"name": "...", "cnic": "..."(optional), ...any other fields}]
    Returns status: match | near_match | ambiguous | cnic_conflict | cnic_match_name_mismatch | no_match
    and action: auto | human | ask_more."""
    auto_min = rules["name_match_auto_min"]
    review_min = rules["name_match_review_min"]
    reasons: list[str] = []
    q_cnic = normalize_cnic(cnic)

    result = {
        "query_name": name, "status": "no_match", "action": "ask_more", "confidence": 0.0,
        "best": None, "alternatives": [], "duplicates_collapsed": 0, "reasons": reasons,
        "thresholds_used": {"name_match_auto_min": auto_min, "name_match_review_min": review_min},
        "rule_version": rule_version,
    }
    from app.urdu_names import has_urdu
    if not tokens(name) and not has_urdu(name):
        reasons.append("The name is empty or has no readable letters.")
        return result

    # 1) collapse exact duplicates (same CNIC listed twice)
    seen, unique = set(), []
    for c in candidates:
        key = normalize_cnic(c.get("cnic")) or f"name:{' '.join(tokens(c.get('name', ''))) or c.get('name', '')}"
        if key in seen:
            result["duplicates_collapsed"] += 1
            continue
        seen.add(key)
        unique.append(c)
    if result["duplicates_collapsed"]:
        reasons.append(f"{result['duplicates_collapsed']} duplicate record(s) with the same identity were merged.")

    # 2) score and classify each candidate
    scored = []
    for c in unique:
        s = name_score(name, c.get("name", ""))
        c_cnic = normalize_cnic(c.get("cnic"))
        if q_cnic and c_cnic:
            if q_cnic == c_cnic:
                if s >= auto_min:
                    status, conf = "match", round((s + 1) / 2, 4)
                elif s >= review_min:
                    status, conf = "near_match", s
                else:
                    status, conf = "cnic_match_name_mismatch", s
            elif s >= review_min:
                status, conf = "cnic_conflict", s
            else:
                continue
        elif s >= auto_min:
            status, conf = "match", s
        elif s >= review_min:
            status, conf = "near_match", s
        else:
            continue
        scored.append({"candidate": c, "name_score": s, "status": status, "confidence": conf,
                       "cnic_equal": bool(q_cnic and c_cnic and q_cnic == c_cnic)})

    if not scored:
        reasons.append("No record is similar enough to this name. Ask for the CNIC or a clearer name.")
        return result

    scored.sort(key=lambda x: (x["cnic_equal"], x["confidence"]), reverse=True)
    best, rest = scored[0], scored[1:]
    status, confidence = best["status"], best["confidence"]
    reasons.append(f"Best record scored {best['name_score']:.2f} on the name.")

    # 3) never pick between two plausible people
    if not best["cnic_equal"]:
        close = [r for r in rest
                 if r["status"] in ("match", "near_match") and best["confidence"] - r["confidence"] < 0.05]
        if close:
            status = "ambiguous"
            reasons.append(f"{len(close)} other person(s) match almost equally well, so the system will not choose.")

    if status == "match":
        action = "auto"
        reasons.append("Name matches at or above the automatic threshold.")
    elif status == "near_match":
        action = "human"
        reasons.append("Name is similar but below the automatic threshold, so a human checks it.")
    elif status == "cnic_conflict":
        action = "human"
        reasons.append("The name is similar but the CNIC numbers differ.")
    elif status == "cnic_match_name_mismatch":
        action = "human"
        reasons.append("The CNIC matches but the name is quite different.")
    else:
        action = "human"

    result.update(status=status, action=action, confidence=round(confidence, 4),
                  best=best["candidate"], alternatives=[r["candidate"] for r in rest[:3]])
    return result