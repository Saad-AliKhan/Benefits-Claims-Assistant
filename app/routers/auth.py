"""Login (JWT). The browser posts email + password to /auth/login and keeps the token;
/docs uses /auth/token (the "Authorize" button)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import get_current_user
from app.models import Role, User
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Login and roles"])
HOME = {"citizen": "/assistant", "helper": "/citizen", "officer": "/officer", "admin": "/admin", "auditor": "/auditor"}


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


def _authenticate(db: Session, email: str, password: str, via: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        audit.record(db, "auth.login_failed", actor_role=audit.ACTOR_ANONYMOUS,
                     details={"email": email.lower().strip(), "via": via}, commit=True)
        raise HTTPException(401, "Wrong email or password", headers={"WWW-Authenticate": "Bearer"})
    audit.record(db, "auth.login", actor=user, details={"via": via}, commit=True)
    return user


def _me(user: User) -> dict:
    return {"id": user.id, "name": user.full_name, "email": user.email, "role": user.role,
            "cnic": user.cnic, "home": HOME[user.role]}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """Email + password -> a JWT and where this role's page is."""
    user = _authenticate(db, body.email, body.password, "web")
    return {"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": _me(user)}


@router.post("/token", include_in_schema=True)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """For /docs: put the email in 'username'."""
    user = _authenticate(db, form.username, form.password, "api")
    return {"access_token": create_access_token(user.id, user.role), "token_type": "bearer"}


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
