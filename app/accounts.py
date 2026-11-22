"""Accounts for a live service.

Citizens (and the families a helper serves) sign up with their mobile number: name + CNIC + mobile, a 6-digit
code by SMS proves she holds the phone, then she chooses a 4-6 digit PIN. She logs in with mobile + PIN. A forgotten
PIN is reset the same way (code by SMS). There is no SMS gateway yet: with sms_mode=screen the code is shown on the
screen (and in the SMS inbox of the app) instead.

Staff (officer, auditor, helper, admin) are created by an admin with a temporary password that must be changed
at the first login. Admins can deactivate an account; changing a password logs out every other device.

Every account: 5 wrong attempts lock it for 15 minutes; every login, failure, lock and change is in the audit log.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import settings
from app.mock_services import api as mock
from app.models import OneTimeCode, SmsMessage, User
from app.security import hash_password, verify_password

STAFF_ROLES = ("officer", "auditor", "helper", "admin")
MIN_STAFF_PASSWORD = 10


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def mobile(raw: str | None) -> str | None:
    """Pakistani mobile -> 03XX-XXXXXXX; anything else -> None. Accepts +92 / 0092 / spaces / dashes."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("0092"):
        d = "0" + d[4:]
    elif d.startswith("92") and len(d) == 12:
        d = "0" + d[2:]
    if not re.fullmatch(r"03\d{9}", d):
        return None
    return f"{d[:4]}-{d[4:]}"


def check_pin(pin: str):
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        raise HTTPException(422, {"code": "bad_pin", "message_en": "The PIN must be 4 to 6 digits.",
                                  "message_ur": "پن 4 سے 6 ہندسوں کا ہونا چاہیے۔"})
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise HTTPException(422, {"code": "weak_pin", "message_en": "Choose a PIN that is not 1111 or 1234.",
                                  "message_ur": "ایسا پن چنیں جو 1111 یا 1234 جیسا نہ ہو۔"})


def check_staff_password(pw: str):
    if len(pw or "") < MIN_STAFF_PASSWORD or pw.isdigit() or pw.isalpha():
        raise HTTPException(422, f"The password needs at least {MIN_STAFF_PASSWORD} characters, with letters and numbers.")


# ------------------------------------------------------------------ login with lockout
def _locked(user: User) -> bool:
    return bool(user.locked_until and _aware(user.locked_until) > now())


def login(db: Session, user: User | None, secret: str, via: str, who: str) -> User:
    if user is not None and _locked(user):
        audit.record(db, "auth.login_locked", actor_role=audit.ACTOR_ANONYMOUS, details={"user_id": user.id, "via": via},
                     commit=True)
        mins = max(1, int((_aware(user.locked_until) - now()).total_seconds() // 60) + 1)
        raise HTTPException(429, {"code": "locked", "message_en": f"Too many wrong tries. Try again in {mins} minutes.",
                                  "message_ur": f"بہت زیادہ غلط کوششیں۔ {mins} منٹ بعد دوبارہ کوشش کریں۔"})
    if user is None or not user.is_active or not verify_password(secret, user.password_hash):
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until, user.failed_logins = now() + timedelta(minutes=settings.lockout_minutes), 0
                audit.record(db, "auth.locked", actor_role=audit.ACTOR_SYSTEM, details={"user_id": user.id})
        audit.record(db, "auth.login_failed", actor_role=audit.ACTOR_ANONYMOUS, details={"who": who, "via": via},
                     commit=True)
        raise HTTPException(401, {"code": "wrong", "message_en": "Wrong details. Check and try again.",
                                  "message_ur": "معلومات درست نہیں۔ دوبارہ دیکھ کر کوشش کریں۔"},
                            headers={"WWW-Authenticate": "Bearer"})
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now()
    audit.record(db, "auth.login", actor=user, details={"via": via}, commit=True)
    return user


# ------------------------------------------------------------------ one-time codes (SMS)
def send_code(db: Session, phone: str, purpose: str, payload: dict | None = None) -> dict:
    recent = db.scalar(select(func.count(OneTimeCode.id)).where(
        OneTimeCode.phone == phone, OneTimeCode.created_at > now() - timedelta(hours=1)))
    if recent >= 5:
        raise HTTPException(429, {"code": "too_many_codes", "message_en": "Too many codes for this number. Try again in an hour.",
                                  "message_ur": "اس نمبر پر بہت زیادہ کوڈ بھیجے گئے۔ ایک گھنٹے بعد کوشش کریں۔"})
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(OneTimeCode(phone=phone, purpose=purpose, code_hash=hash_password(code), payload=payload or {},
                       attempts=0, used=False, expires_at=now() + timedelta(minutes=settings.code_minutes)))
    text_ur = f"آسرا: آپ کا کوڈ {code} ہے۔ یہ کسی کو نہ بتائیں، ہم کبھی فون پر کوڈ نہیں مانگتے۔"
    text_en = f"Aasra: your code is {code}. Do not share it; we never ask for codes on the phone."
    owner = db.scalar(select(User).where(User.phone == phone))
    db.add(SmsMessage(user_id=owner.id if owner else None, phone=phone, kind=f"code_{purpose}", text_ur=text_ur,
                      text_en=text_en, status="sent_mock" if settings.sms_mode == "screen" else "queued"))
    audit.record(db, "auth.code_sent", actor_role=audit.ACTOR_SYSTEM, details={"purpose": purpose})  # never the code
    db.commit()
    out = {"sent": True, "minutes": settings.code_minutes}
    if settings.sms_mode == "screen":   # no SMS gateway yet: show it (a real gateway sends it instead)
        out["code_on_screen"] = code
    return out


def use_code(db: Session, phone: str, purpose: str, code: str) -> OneTimeCode:
    row = db.scalar(select(OneTimeCode).where(OneTimeCode.phone == phone, OneTimeCode.purpose == purpose,
                                              OneTimeCode.used.is_(False))
                    .order_by(OneTimeCode.id.desc()).limit(1))
    bad = {"code": "bad_code", "message_en": "The code is wrong or has expired. Ask for a new code.",
           "message_ur": "کوڈ غلط ہے یا اس کا وقت ختم ہو گیا۔ نیا کوڈ منگوائیں۔"}
    if row is None or _aware(row.expires_at) < now() or row.attempts >= 5:
        raise HTTPException(422, bad)
    if not verify_password(re.sub(r"\D", "", code or ""), row.code_hash):
        row.attempts += 1
        db.commit()
        raise HTTPException(422, bad)
    row.used = True
    return row


# ------------------------------------------------------------------ citizens
def signup_start(db: Session, full_name: str, cnic: str, phone_raw: str) -> dict:
    phone, cnic_n = mobile(phone_raw), mock.norm_cnic(cnic)
    if phone is None:
        raise HTTPException(422, {"code": "bad_phone", "message_en": "Enter a mobile number like 0300 1234567.",
                                  "message_ur": "موبائل نمبر اس طرح لکھیں: 0300 1234567"})
    if cnic_n is None:
        raise HTTPException(422, {"code": "bad_cnic", "message_en": "Enter the 13-digit CNIC number.",
                                  "message_ur": "13 ہندسوں کا شناختی کارڈ نمبر لکھیں۔"})
    name = " ".join((full_name or "").split())
    if len(name) < 3:
        raise HTTPException(422, {"code": "bad_name", "message_en": "Write the full name as on the CNIC.",
                                  "message_ur": "شناختی کارڈ والا پورا نام لکھیں۔"})
    if db.scalar(select(User.id).where((User.phone == phone) | (User.cnic == cnic_n))):
        raise HTTPException(409, {"code": "exists", "message_en": "An account with this mobile or CNIC already exists. Log in, or reset the PIN.",
                                  "message_ur": "اس موبائل یا شناختی کارڈ کا اکاؤنٹ پہلے سے ہے۔ لاگ اِن کریں یا پن دوبارہ بنائیں۔"})
    return send_code(db, phone, "signup", {"full_name": name, "cnic": cnic_n})


def signup_finish(db: Session, phone_raw: str, code: str, pin: str) -> User:
    phone = mobile(phone_raw)
    check_pin(pin)
    row = use_code(db, phone or "", "signup", code)
    p = row.payload
    if db.scalar(select(User.id).where((User.phone == phone) | (User.cnic == p["cnic"]))):
        raise HTTPException(409, "An account with this mobile or CNIC already exists.")
    user = User(email=None, full_name=p["full_name"], cnic=p["cnic"], phone=phone, role="citizen",
                password_hash=hash_password(pin), is_active=True, must_change_password=False, failed_logins=0,
                token_version=0, last_login_at=now())
    db.add(user)
    db.flush()
    audit.record(db, "auth.signup", actor=user, details={"via": "phone_code"})
    db.commit()
    return user


def pin_reset_start(db: Session, phone_raw: str) -> dict:
    phone = mobile(phone_raw)
    user = db.scalar(select(User).where(User.phone == phone, User.role == "citizen")) if phone else None
    if user is None:   # same answer either way: does not reveal who has an account
        return {"sent": True, "minutes": settings.code_minutes}
    return send_code(db, phone, "pin_reset")


def pin_reset_finish(db: Session, phone_raw: str, code: str, pin: str) -> User:
    phone = mobile(phone_raw)
    check_pin(pin)
    use_code(db, phone or "", "pin_reset", code)
    user = db.scalar(select(User).where(User.phone == phone, User.role == "citizen"))
    if user is None:
        raise HTTPException(422, "No account for this mobile")
    user.password_hash, user.token_version = hash_password(pin), (user.token_version or 0) + 1
    user.failed_logins, user.locked_until = 0, None
    audit.record(db, "auth.pin_reset", actor=user)
    db.commit()
    return user


# ------------------------------------------------------------------ staff (created by an admin)
def temporary_password() -> str:
    words = ("green", "river", "lamp", "cotton", "mango", "stone", "cloud", "wheat", "kite", "maple")
    return f"{secrets.choice(words)}-{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}"


def create_staff(db: Session, admin: User | None, full_name: str, email: str, role: str, phone: str | None = None) -> tuple[User, str]:
    if role not in STAFF_ROLES:
        raise HTTPException(422, f"Role must be one of {', '.join(STAFF_ROLES)}")
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Enter a valid email address")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "There is already an account with this email")
    temp = temporary_password()
    user = User(email=email, full_name=" ".join(full_name.split()), role=role, phone=mobile(phone) if phone else None,
                password_hash=hash_password(temp), is_active=True, must_change_password=True, failed_logins=0,
                token_version=0)
    db.add(user)
    db.flush()
    audit.record(db, "admin.user_created", actor=admin, actor_role=None if admin else audit.ACTOR_SYSTEM,
                 details={"user_id": user.id, "role": role})
    db.commit()
    return user, temp


def reset_staff_password(db: Session, admin: User, user: User) -> str:
    if user.role == "citizen":
        raise HTTPException(422, "Citizens reset their own PIN with a code sent to their mobile")
    temp = temporary_password()
    user.password_hash, user.must_change_password = hash_password(temp), True
    user.token_version, user.failed_logins, user.locked_until = (user.token_version or 0) + 1, 0, None
    audit.record(db, "admin.password_reset", actor=admin, details={"user_id": user.id})
    db.commit()
    return temp


def set_active(db: Session, admin: User, user: User, active: bool):
    if user.id == admin.id and not active:
        raise HTTPException(422, "You cannot deactivate your own account")
    if not active and user.role == "admin":
        others = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True), User.id != user.id))
        if not others:
            raise HTTPException(422, "Keep at least one active admin")
    user.is_active = active
    user.token_version = (user.token_version or 0) + (0 if active else 1)
    audit.record(db, "admin.user_activated" if active else "admin.user_deactivated", actor=admin, details={"user_id": user.id})
    db.commit()


def change_password(db: Session, user: User, current: str, new: str):
    if not verify_password(current, user.password_hash):
        audit.record(db, "auth.password_change_failed", actor=user, commit=True)
        raise HTTPException(401, "The current password is wrong")
    (check_pin if user.role == "citizen" else check_staff_password)(new)
    if verify_password(new, user.password_hash):
        raise HTTPException(422, "Choose a new password, not the same one")
    user.password_hash, user.must_change_password = hash_password(new), False
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, "auth.password_changed", actor=user)
    db.commit()
