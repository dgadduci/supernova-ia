"""Public acquisition surface for the NovaOrders self-service trial.

This router is the only public, unauthenticated entry point added by
Phase 1 of the ``add-commerce-self-service-onboarding`` change. It
exposes two server-rendered Jinja pages:

* ``GET /`` (``GET /``) renders the public landing page. The handler
  renders a focused hero, three benefit cards, an honest
  "how the trial works" sequence, trust/privacy content and one
  primary ``Probá gratis`` call to action. It must not query the
  database, must not open a session and must not surface any
  administrative route.
* ``GET /comenzar`` renders the temporary "Próximamente" placeholder
  the landing CTA points to while passwordless identity and the
  commerce draft are still being prepared. The page is intentionally
  informational only: it shows the upcoming-trial message and a link
  back to the landing. It must not create or accept data.

Both handlers are pure rendering adapters: they never import a
domain service, never call ``get_session``, never mutate state, and
never log credentials. ``autoescape`` is enabled in the Jinja
environment so any user-supplied value (the URL placeholders) is
safely HTML-escaped before it lands in the rendered template.

The router adds no dependencies, runs no authentication check and
never raises on rate limiting: it is the smallest possible Phase-1
acquisition surface and intentionally leaves every other
administrative boundary untouched.
"""

from __future__ import annotations

from pathlib import Path as PathLib

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1] / "templates" / "public_onboarding"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

router = APIRouter(tags=["public-onboarding"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing(request: Request) -> HTMLResponse:
    """Render the public landing page for the self-service trial.

    The page introduces NovaOrders in Spanish, lists three benefits,
    explains how the trial works and links to the temporary
    ``/comenzar`` placeholder. The handler never opens a database
    session, never imports a domain service, never mutates state and
    never logs the credential.
    """
    return _templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "request": request,
            "comenzar_url": "/comenzar",
        },
        status_code=200,
    )


@router.get(
    "/comenzar", response_class=HTMLResponse, include_in_schema=False
)
def proximamente(request: Request) -> HTMLResponse:
    """Render the temporary "Próximamente" placeholder for the CTA target.

    The page does not create an account, does not persist any data and
    does not expose commerce, order or administrative information. It
    only confirms the trial request is being prepared and links back to
    the public landing. The handler never opens a database session,
    never imports a domain service and never mutates state.
    """
    return _templates.TemplateResponse(
        request=request,
        name="proximamente.html",
        context={"request": request},
        status_code=200,
    )


__all__ = ["router"]
