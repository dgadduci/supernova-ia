"""Browser-oriented administrative panel.

The package contains the panel-specific HTTP adapters, typed form /
view shapes, read projections and Jinja templates for the new
``/admin/catalog`` route family. It is intentionally NOT a parallel
application pipeline: every create or assignment it accepts flows
through the existing domain services and the shared
:class:`CatalogCreateService`, so the JSON API contract, the commit
/ rollback semantics and the post-create embedding synchronization
are preserved verbatim.

The package re-exports the panel authentication dependency from
:mod:`backend.dependencies` and the anti-CSRF helpers so the
templates and the routes share a single source of truth.
"""

from __future__ import annotations

from backend.dependencies import (
    PANEL_FORM_NONCE_FIELD,
    compute_panel_form_nonce,
    require_admin_browser_basic,
    require_same_origin_panel_form,
    resolve_panel_csrf_secret,
)

__all__ = [
    "PANEL_FORM_NONCE_FIELD",
    "compute_panel_form_nonce",
    "require_admin_browser_basic",
    "require_same_origin_panel_form",
    "resolve_panel_csrf_secret",
]