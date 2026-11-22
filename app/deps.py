"""Who is calling, and may they? Every API route depends on one of these.

Login gives a JWT (POST /auth/login or /auth/token). The browser sends it as
`Authorization: Bearer <token>`; /docs does the same after "Authorize".
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models import User
from app.security import decode_access_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
ROLES = ("citizen", "helper", "officer", "admin", "auditor")


def get_optional_user(token: str | None = Depends(oauth2), db: Session = Depends(get_db)) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active or int(payload.get("ver", 0)) != (user.token_version or 0):
        return None
    return user


def get_current_user(request: Request, user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Please log in", headers={"WWW-Authenticate": "Bearer"})
    request.state.user = user  # lets the audit middleware name the actor
    return user


def require_role(*roles: str):
    """Server-side role check: the wrong role gets 403, and the attempt is written to the audit log."""
    def checker(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.role not in roles:
            audit.record(db, "access.denied", actor=user,
                         details={"path": request.url.path, "method": request.method, "needs": list(roles)},
                         commit=True)
            raise HTTPException(403, "You do not have permission for this")
        return user

    return checker
