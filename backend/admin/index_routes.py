"""Browser-oriented administrative panel navigation index.

The router exposes a single ``GET /admin`` landing page that acts as
the stable, server-rendered entry point for every administrative
panel family (``/admin/catalog`` and ``/admin/pilot/orders``). The
route is intentionally a pure rendering adapter: it does not open a
database session, never imports a domain service, never mutates
state and never logs the credential.

The landing page is just a navigation hub — it never lists, drafts,
creates or hides domain rows, and it never becomes a new source of
data. The authentication boundary is the shared browser-only HTTP
Basic dependency already used by the catalog and pilot panels, so
the same configured ``order_management_admin_token`` protects every
section of the administrative surface uniformly.
"""

from __future__ import annotations

from pathlib import Path as PathLib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.dependencies import require_admin_browser_basic

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1] / "templates" / "admin"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True


router = APIRouter(
    prefix="/admin",
    tags=["admin-index"],
    dependencies=[Depends(require_admin_browser_basic)],
)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def admin_index(request: Request) -> HTMLResponse:
    """Render the global administrative panel landing page.

    The page is a navigation hub that lists the three documented
    entry points:

    * ``/admin/catalog/comercios`` — Comercios
    * ``/admin/catalog/medios-pago`` — Medios de pago
    * ``/admin/pilot/orders`` — Operación (panel piloto)

    The handler never opens a database session, never imports a
    domain service and never mutates state. The response is a
    server-rendered HTML page so the operator can land on
    ``/admin`` from a direct URL, a bookmark or a typed address —
    it does not depend on JavaScript to navigate.
    """
    return _templates.TemplateResponse(
        request=request,
        name="admin_index.html",
        context={
            "request": request,
            "comercios_url": "/admin/catalog/comercios",
            "medios_pago_url": "/admin/catalog/medios-pago",
            "operacion_url": "/admin/pilot/orders",
        },
        status_code=200,
    )


__all__ = ["router"]