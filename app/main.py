"""Last Mile Claims: one web app (prototype; all data fake).

    pages      /login  /citizen  /officer  /admin  /auditor
    API        /auth  /claims  /consents  /helper  /officer  /admin  /audit  /ai  /voice  /mock  /api/v1
    docs       /docs (Swagger): "Authorize" with an email + password, or an API key for /api/v1
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import ai_engines, audit
from app.config import settings
from app.db import get_db
from app.routers import admin, agent as agent_routes, ai, audit as audit_routes, auth, claims, consents, mock, officer, pages, public_api, voice

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    ai_engines.start_loading()  # OCR + Whisper load in the background; pages work at once
    yield


app = FastAPI(
    title=f"{settings.app_name} (prototype)",
    version="1.0.0",
    description=(
        "AI-assisted benefits and claims. **Prototype: every person, document and payment is fake.**\n\n"
        "Log in: click **Authorize**, put an email in *username* and the password (demo accounts: see README). "
        "Public API (`/api/v1`): an admin creates a key on /admin; send it as `X-API-Key`.\n\n"
        "The AI supports people's decisions: OCR and voice are not proof of identity or of death, and a refusal "
        "is never automatic."
    ),
    lifespan=lifespan,
)

SKIP = ("/static/", "/docs", "/redoc", "/openapi.json", "/health", "/sw.js", "/favicon")


@app.middleware("http")
async def audit_every_action(request: Request, call_next):
    """Safety net for 'the audit log records every action': every request that changes something, and
    every refused request, gets an entry, even where a route forgot to write one."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(SKIP):
        return response
    changing = request.method not in ("GET", "HEAD", "OPTIONS")
    refused = response.status_code in (401, 403)
    if changing or refused:
        route = request.scope.get("route")
        user = getattr(request.state, "user", None)
        gen = request.app.dependency_overrides.get(get_db, get_db)()
        db = next(gen)
        try:
            audit.record(db, "http.refused" if refused else "http.request", actor=user,
                         actor_role=None if user else audit.ACTOR_ANONYMOUS,
                         details={"method": request.method, "path": getattr(route, "path", path),
                                  "status": response.status_code}, commit=True)
        finally:
            gen.close()
    return response


for r in (auth, pages, claims, agent_routes, consents, officer, admin, audit_routes, ai, voice, mock, public_api):
    app.include_router(r.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "prototype": True}


@app.get("/health/ai", tags=["Health"])
def health_ai():
    """Are the OCR and Whisper engines loaded? Until they are, the claim flow uses its fallbacks."""
    return ai_engines.status()
