"""HTML pages. Small, no frameworks; they hold no data: the browser fetches it from the JSON API
with the logged-in user's token, and the API checks the role on every call."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
STATIC = Path(__file__).resolve().parents[1] / "static"


def _page(request: Request, name: str, title: str, **extra):
    return templates.TemplateResponse(request, name, {"title": title, "label": settings.prototype_label, **extra})


@router.get("/")
def home():
    return RedirectResponse("/login")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _page(request, "login.html", "Log in")


@router.get("/citizen", response_class=HTMLResponse)
def citizen_page(request: Request):
    return _page(request, "citizen.html", "My claim", body_class="citizen")


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request):
    return _page(request, "assistant.html", "Assistant", body_class="citizen")


@router.get("/officer", response_class=HTMLResponse)
def officer_page(request: Request):
    return _page(request, "officer.html", "Officer queue", body_class="wide")


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return _page(request, "admin.html", "Admin", body_class="wide")


@router.get("/auditor", response_class=HTMLResponse)
def auditor_page(request: Request):
    return _page(request, "auditor.html", "Auditor", body_class="wide")


@router.get("/sw.js")
def service_worker():
    """Served from the site root so the service worker controls the citizen page."""
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})
