"""Login (JWT). Staff: email + password (/auth/login). Citizens: mobile + PIN (/auth/login/phone), after signing up
with a code sent to the mobile (/auth/signup/...). /docs uses /auth/token (the "Authorize" button)."""
from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, audit
from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Role, User
from app.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Login and roles"])
HOME = {"citizen": "/assistant", "helper": "/citizen", "officer": "/officer", "admin": "/admin", "auditor": "/auditor"}


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class PhoneLoginIn(BaseModel):
    phone: str = Field(max_length=30)
    pin: str = Field(max_length=10)


class SignupStartIn(BaseModel):   # checked in accounts.signup_start, with messages in Urdu and English
    full_name: str = Field(max_length=200)
    cnic: str = Field(max_length=30)
    phone: str = Field(max_length=30)


class CodeIn(BaseModel):
    phone: str = Field(max_length=30)
    code: str = Field(max_length=10)
    pin: str = Field(max_length=10)


class PhoneIn(BaseModel):
    phone: str = Field(max_length=30)


class ChangeIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=4, max_length=200)


def _me(user: User) -> dict:
    return {"id": user.id, "name": user.full_name, "email": user.email, "phone": user.phone, "role": user.role,
            "cnic": user.cnic, "home": HOME[user.role], "must_change_password": bool(user.must_change_password)}


def _session(user: User) -> dict:
    return {"access_token": create_access_token(user.id, user.role, user.token_version or 0), "token_type": "bearer",
            "user": _me(user)}


@router.get("/options")
def options():
    """What the login page offers (no login needed): demo accounts in demo mode; codes on screen without SMS."""
    return {"demo_mode": settings.demo_mode, "codes_on_screen": settings.sms_mode == "screen",
            "app_name": settings.app_name}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """Staff (and demo accounts): email + password -> a JWT and where this role's page is."""
    email = body.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    return _session(accounts.login(db, user, body.password, "web", email))


@router.post("/login/phone")
def login_phone(body: PhoneLoginIn, db: Session = Depends(get_db)):
    """Citizens: mobile + PIN."""
    phone = accounts.mobile(body.phone)
    user = db.scalar(select(User).where(User.phone == phone, User.role == "citizen")) if phone else None
    return _session(accounts.login(db, user, body.pin, "phone", phone or "invalid"))


@router.post("/signup/start")
def signup_start(body: SignupStartIn, db: Session = Depends(get_db)):
    """Name + CNIC + mobile -> a 6-digit code to the mobile (on screen while there is no SMS gateway)."""
    return accounts.signup_start(db, body.full_name, body.cnic, body.phone)


@router.post("/signup/finish", status_code=201)
def signup_finish(body: CodeIn, db: Session = Depends(get_db)):
    """The code + a new 4-6 digit PIN -> the account, logged in."""
    return _session(accounts.signup_finish(db, body.phone, body.code, body.pin))


@router.post("/pin-reset/start")
def pin_reset_start(body: PhoneIn, db: Session = Depends(get_db)):
    """Forgot the PIN: a code to the mobile (the answer is the same whether or not the number has an account)."""
    return accounts.pin_reset_start(db, body.phone)


@router.post("/pin-reset/finish")
def pin_reset_finish(body: CodeIn, db: Session = Depends(get_db)):
    return _session(accounts.pin_reset_finish(db, body.phone, body.code, body.pin))


@router.post("/change-password")
def change_password(body: ChangeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Staff: new password (10+ characters, letters and numbers). Citizens: new PIN. Logs out other devices."""
    accounts.change_password(db, user, body.current, body.new)
    db.refresh(user)
    return _session(user)


@router.post("/token", include_in_schema=True)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """For /docs: put the email in 'username'."""
    email = form.username.lower().strip()
    user = accounts.login(db, db.scalar(select(User).where(User.email == email)), form.password, "api", email)
    return {"access_token": create_access_token(user.id, user.role, user.token_version or 0), "token_type": "bearer"}


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit.record(db, "auth.logout", actor=user, commit=True)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _me(user)


@router.get("/roles")
def roles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"name": r.name, "label": r.label, "description": r.description} for r in db.scalars(select(Role))]
