"""Focused tests for the public acquisition landing surface.

The change ``add-commerce-self-service-onboarding`` introduces two
public, server-rendered pages for Phase 1:

* ``GET /`` — the Spanish landing page with hero, benefits, planned
  process, isolation/config-per-commerce copy and a transparent
  ``Próximamente`` call to action.
* ``GET /comenzar`` — the temporary ``El registro aún no está abierto``
  placeholder the landing CTA points to while passwordless identity
  remains out of scope. The placeholder only renders the
  not-enabled message and a ``Volver al inicio`` link.

These tests cover the minimal contracts required by the change:

* Public availability — neither endpoint requires authentication,
  neither opens a database session and neither mutates state.
* Content — the landing renders the documented hero, three benefit
  cards, the four-step planned flow, the isolation/config-per-commerce
  block, the final ``Próximamente`` CTA and the ``/comenzar`` link.
  The ``/comenzar`` placeholder renders the documented
  not-enabled message and a single back link.
* Isolation — the landing and the placeholder never link to
  administrative (``/admin``), operational (``/health``), webhook
  (``/webhooks/...``) or internal API (``/api/...``) routes, and the
  existing ``/admin`` boundary still requires browser Basic
  credentials.
* Transparency — the landing and placeholder CTAs use the
  ``Próximamente`` label and never suggest the registration is open;
  the placeholder explicitly states the access request is not enabled
  and that no email is captured; no unapproved third-party-sharing or
  email-delivery claims appear anywhere.
* Accessibility — Spanish ``lang`` attribute, a working skip-link,
  focus-visible styling, semantic landmarks (``<header role="banner">``,
  ``<main>`` with a heading, ``<footer role="contentinfo">``), labels
  for links, ``aria-labelledby`` on each section, no remote assets,
  no embedded scripts, no autoplay media and at least one touch
  target large enough for narrow-viewport interaction.
* Existing surface preservation — ``/health`` keeps returning the
  same payload (even if no longer linked from the public surface),
  Twilio webhook URLs are still routed through the same router, and
  ``/admin`` keeps requiring credentials.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routers.public_onboarding as public_onboarding_module
from backend.dependencies import get_session


def _build_public_onboarding_app() -> FastAPI:
    """Build a FastAPI app with only the public onboarding surface.

    The minimal app keeps the boundary test isolated from unrelated
    routers (twilio, admin, commerce) so the assertions verify the
    contract of the public onboarding router itself. The isolation
    tests use the full production app to confirm the broader wiring.
    """
    app = FastAPI()
    app.include_router(public_onboarding_module.router)
    return app


class _SessionOverride:
    """Test double that records how many times the session was requested."""

    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
        return self._return_value

    def assert_not_called(self) -> None:
        if self.call_count != 0:
            raise AssertionError(
                f"session override was called {self.call_count} time(s)"
            )


def _install_session_override(
    test: unittest.TestCase, app: FastAPI, session: object
) -> _SessionOverride:
    override = _SessionOverride(session)

    def _dependency() -> object:
        return override()

    app.dependency_overrides[get_session] = _dependency
    test.addCleanup(lambda: app.dependency_overrides.pop(get_session, None))
    return override


def _new_session_double() -> MagicMock:
    """Return a MagicMock double for the database session dependency.

    The landing is a pure rendering adapter so the test only uses the
    mock to assert it is never opened. ``MagicMock`` is sufficient.
    """
    return MagicMock(name="DatabaseSession")


# Substrings that must NEVER appear on the public surfaces. The list
# is intentionally explicit: any accidental reintroduction must be
# caught by a focused regression. Phase 1 forbids references to
# third-party data sharing, email-magic-link delivery promises,
# current-behavior readiness gates and phone-number scraping because
# those claims are not yet approved.
_FORBIDDEN_COPY: tuple[str, ...] = (
    "No comercializamos",
    "comercializamos información",
    "te avisaremos",
    "te contactamos",
    "enlace seguro enviado a tu",
    "enlace a tu email",
    "enlace a tu casilla",
    "Probá NovaOrders gratis",
    "Probá gratis",
    # Pre-operate configuration is a planned future flow, NOT a
    # current readiness gate. The old copy turned it into a current
    # technical claim about how the system already behaves.
    "Configuración explícita antes de operar",
    "El sistema exige medios de pago",
    "exige medios de pago",
    "antes de pasar a aceptar pedidos reales",
)

# Subpath prefixes the public surface must NEVER link to. The list
# covers administrative, operational, webhook and internal API
# surfaces so a future template edit cannot leak them.
_FORBIDDEN_LINK_PREFIXES: tuple[str, ...] = (
    "/admin",
    "/health",
    "/webhooks/",
    "/api/",
    "/internal/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/sessions",
    "/pedidos",
    "/comercios",
    "/clientes",
    "/productos",
    "/medios-pago",
    "/metodos-entrega",
    "/admin_pilot_orders",
)


def _extract_anchor_hrefs(
    html_text: str,
) -> list[tuple[str, str, dict[str, str]]]:
    """Return a flat list of ``(href, label, attrs)`` for every ``<a>``.

    The helper is intentionally tolerant: it accepts attributes in any
    order, ignores whitespace, and lower-cases attribute names so it
    stays stable across cosmetic template edits. The label is the
    trimmed text content between the opening and closing tag with
    nested HTML stripped.
    """
    anchors: list[tuple[str, str, dict[str, str]]] = []
    pattern = re.compile(r"<a\b([^>]*?)>(.*?)</a>", re.DOTALL)
    for match in pattern.finditer(html_text):
        raw_attrs = match.group(1)
        body = match.group(2)
        attrs: dict[str, str] = {}
        for part in raw_attrs.split():
            key, sep, value = part.partition("=")
            if not sep:
                continue
            attrs[key.strip().lower()] = value.strip().strip('"').strip("'")
        href = attrs.get("href", "")
        label = re.sub(r"<[^>]+>", " ", body)
        label = re.sub(r"\s+", " ", label).strip()
        anchors.append((href, label, attrs))
    return anchors


class PublicLandingRouteTest(unittest.TestCase):
    """``GET /`` exposes the documented Spanish landing surface."""

    def setUp(self) -> None:
        self.session = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_landing_returns_200_without_authentication(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.override.assert_not_called()

    def test_landing_root_and_slash_are_equivalent(self) -> None:
        """``/`` must render the landing page so the visitor can reach
        it from the documented root URL or from a bookmark."""
        for path in ("/", "/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("NovaOrders", response.text)

    def test_landing_uses_spanish_language_attribute(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # The lang attribute drives screen-reader pronunciation and
        # the operating-system spell-check heuristics, so the public
        # Spanish landing must declare it.
        self.assertRegex(response.text, r'<html\s+lang="es-AR"')

    def test_landing_renders_hero_with_value_proposition(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # The hero carries the documented value proposition and the
        # transparent call to action. Copy assertions are stable: the
        # design tokens and Spanish copy belong to Phase 0/1
        # decisions and the landing must not regress them.
        self.assertIn(
            "Recibí y administrá los pedidos de tu local por WhatsApp",
            response.text,
        )
        self.assertIn(
            "El registro público de nuevos comercios aún no está abierto",
            response.text,
        )
        self.assertIn('id="hero-title"', response.text)
        # The honest CTA label — the landing must NOT invite the
        # visitor to start a trial that is not yet open.
        self.assertIn("Próximamente", response.text)
        self.assertNotIn("Probá gratis", response.text)
        self.assertNotIn("Probá NovaOrders", response.text)

    def test_landing_renders_three_documented_benefits(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for benefit_heading in (
            "Pedidos claros y consistentes",
            "Configuración a tu medida",
            "Revisión operativa antes de activar",
        ):
            with self.subTest(benefit=benefit_heading):
                self.assertIn(benefit_heading, response.text)

    def test_landing_renders_planned_process_steps(self) -> None:
        """The process section describes the *planned* flow; the
        headings use the documented future-tense phrasing so the
        visitor never reads the steps as already-available actions."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for step_heading in (
            "Apertura del registro",
            "Configuración del comercio",
            "Validación en modo PRUEBA",
            "Salida en vivo con acompañamiento",
        ):
            with self.subTest(step=step_heading):
                self.assertIn(step_heading, response.text)
        # The process list is the structured ``<ol>``; using a
        # bullet list would lose the ordinal semantics screen
        # readers rely on.
        self.assertIn('<ol class="process-list">', response.text)
        # The intro paragraph frames the section as a *plan*, not
        # an active flow the visitor can trigger today.
        self.assertIn(
            "La apertura del registro público se habilitará próximamente",
            response.text,
        )
        # The legacy imperative headings must NOT reappear: the
        # landing must never invite the visitor to take an action
        # that is not yet wired (no magic link, no email capture,
        # no wizard).
        for legacy_step in (
            "Solicitá tu prueba",
            "Configurá tu comercio",
            "Probá en modo PRUEBA",
            "Salí en vivo cuando estés listo",
        ):
            with self.subTest(legacy_step=legacy_step):
                self.assertNotIn(legacy_step, response.text)

    def test_landing_renders_isolation_and_config_block(self) -> None:
        """The trust section must remain grounded in OpenSpec-backed
        facts only. Magic-link delivery promises and unapproved
        third-party-sharing claims must be gone. The pre-operate
        configuration item is rendered as a planned future flow —
        never as a gate the system currently enforces on incoming
        orders."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="privacidad"', response.text)
        # What stays: the OpenSpec-backed isolation/config block.
        self.assertIn("Datos aislados por comercio", response.text)
        # The ``Configuración previa a la salida en vivo`` heading is
        # the documented replacement for the old "explícita" heading.
        self.assertIn(
            "Configuración previa a la salida en vivo", response.text
        )
        # The body must express the configuration requirement as a
        # future flow only — never as a current technical gate.
        self.assertIn(
            "el flujo previsto contemplará configurar medios de pago",
            response.text,
        )
        self.assertIn(
            "Disponibilidad controlada por el sistema", response.text
        )
        # The previously-approved claim of the system *enforcing* the
        # configuration must be gone: it described behavior that is
        # not yet a real readiness gate for accepting real orders.
        self.assertNotIn("Configuración explícita antes de operar", response.text)
        self.assertNotIn(
            "El sistema exige medios de pago", response.text
        )
        self.assertNotIn("exige medios de pago", response.text)
        self.assertNotIn(
            "antes de pasar a aceptar pedidos reales", response.text
        )
        # What must be gone: magic-link / third-party sharing claims.
        self.assertNotIn("Acceso seguro por enlace a tu email", response.text)
        self.assertNotIn(
            "Vas a entrar con un enlace seguro enviado a tu casilla",
            response.text,
        )
        self.assertNotIn("Sin compartir datos con terceros", response.text)
        self.assertNotIn(
            "No comercializamos información de comercios", response.text
        )

    def test_landing_renders_transparent_final_call_to_action(self) -> None:
        """The closing block must make the access-not-open state
        explicit and never tell the visitor that access is being
        coordinated for them via notifications."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Cuándo se abre el registro", response.text)
        self.assertIn(
            "La solicitud de acceso para nuevos comercios aún no está habilitada",
            response.text,
        )
        # At least two visible ``Próximamente`` CTAs (header + final).
        self.assertGreaterEqual(
            response.text.count("Próximamente"),
            2,
            "expected at least two visible 'Próximamente' CTAs",
        )

    def test_landing_links_point_to_temporary_comenzar_route(self) -> None:
        """Every visible ``Próximamente`` button must point to the
        documented ``/comenzar`` placeholder — never to an
        administrative, operational, webhook or internal-API
        surface and never to a non-existent page."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        hrefs = _extract_anchor_hrefs(response.text)
        cta_hrefs = [
            href
            for href, label, _attrs in hrefs
            if label.strip() == "Próximamente"
        ]
        self.assertGreater(len(cta_hrefs), 0)
        for href in cta_hrefs:
            with self.subTest(href=href):
                self.assertEqual(href, "/comenzar")
        # The placeholder route must resolve to a 200 page.
        placeholder = self.client.get("/comenzar")
        self.assertEqual(placeholder.status_code, 200)

    def test_landing_has_no_data_capture_markers(self) -> None:
        """The landing must not contain any element capable of
        capturing user data — no forms, no inputs, no email/phone
        fields, no fetch/submit handlers."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for forbidden in (
            "<form",
            "<input",
            "<textarea",
            "<select",
            "<button",
            'method="post"',
            'method="POST"',
            'enctype="multipart/form-data"',
            'action="/',
            'name="email"',
            'name="phone"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)


class PublicLandingAccessibilityTest(unittest.TestCase):
    """The landing satisfies the documented accessibility contracts."""

    def setUp(self) -> None:
        self.session = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_landing_has_skip_link_and_main_landmark(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("skip-link", response.text)
        self.assertIn("Saltar al contenido", response.text)
        self.assertIn('id="main-content"', response.text)
        self.assertIn("<main", response.text)
        self.assertIn('role="banner"', response.text)
        self.assertIn('role="contentinfo"', response.text)

    def test_landing_sections_use_aria_labelledby(self) -> None:
        """Every section must announce its purpose to assistive tech
        through an ``aria-labelledby`` link to its heading."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for section_id in (
            "hero-title",
            "beneficios-title",
            "proceso-title",
            "privacidad-title",
            "cta-final-title",
        ):
            with self.subTest(section=section_id):
                self.assertIn(f'id="{section_id}"', response.text)
                self.assertIn(f'aria-labelledby="{section_id}"', response.text)

    def test_landing_declares_focus_ring_token(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # The CSS must declare both the focus-ring color and a rule
        # for ``:focus-visible`` so keyboard navigation is reachable.
        self.assertIn("--focus-ring", response.text)
        self.assertIn(":focus-visible", response.text)
        # The interactive navigation links must meet the documented
        # 44px touch target minimum; this keeps the small-viewport
        # CTA reachable with a thumb.
        self.assertIn("min-height: 44px", response.text)

    def test_landing_has_no_remote_assets_or_inline_javascript(self) -> None:
        """The landing must remain readable and accessible without
        any third-party CSS, JavaScript or autoplaying media. External
        assets break restricted networks and inline scripts violate
        the Phase 0/1 contracts."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        forbidden_substrings = [
            "https://fonts.googleapis",
            "https://cdn.jsdelivr",
            "https://unpkg.com",
            '<link rel="stylesheet"',
            "<script",
            "javascript:",
            "history.back",
            "location.replace",
        ]
        for needle in forbidden_substrings:
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, response.text)
        # The page must not reference any media file that could be
        # auto-played by the browser.
        for media_tag in ("<video", "<audio", "<iframe"):
            with self.subTest(media=media_tag):
                self.assertNotIn(media_tag, response.text)

    def test_landing_cta_has_descriptive_label_and_target(self) -> None:
        """The primary CTA must be a real ``<a>`` element with a
        ``href`` so it is reachable through the tab key. A button
        without a destination, or a click handler that depends on
        JavaScript, would defeat keyboard navigation."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'class="cta" href="/comenzar" data-cta="hero-primary"',
            response.text,
        )
        self.assertIn(
            'class="cta" href="/comenzar" data-cta="final"', response.text
        )


class PublicLandingIsolationTest(unittest.TestCase):
    """The public surface must not link to operational surfaces."""

    def setUp(self) -> None:
        from backend.main import app as production_app

        self.session = _new_session_double()
        self.app = production_app
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def _assert_no_forbidden_anchor(self, response_text: str) -> None:
        """Walk every rendered anchor and fail on any forbidden prefix.

        The helper centralises the isolation contract so each public
        route enforces the same rule.
        """
        hrefs = _extract_anchor_hrefs(response_text)
        for href, _label, _attrs in hrefs:
            for prefix in _FORBIDDEN_LINK_PREFIXES:
                with self.subTest(href=href, prefix=prefix):
                    if prefix.endswith("/"):
                        self.assertFalse(
                            href.startswith(prefix),
                            f"public surface must not link to {prefix}... "
                            f"(found {href})",
                        )
                    else:
                        self.assertFalse(
                            href == prefix or href.startswith(prefix + "/"),
                            f"public surface must not link to {prefix} "
                            f"(found {href})",
                        )

    def test_landing_does_not_link_to_admin_or_health(self) -> None:
        """The public landing must never link to ``/admin``,
        ``/health``, ``/webhooks/...`` or any other operational or
        internal API route. Exposing those routes from the landing
        would make administrative and operational enumeration trivial.
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self._assert_no_forbidden_anchor(response.text)
        # A full-text double-check keeps the test resilient to
        # non-anchor attributes (e.g. ``action``, ``data-*``).
        for prefix in _FORBIDDEN_LINK_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertNotIn(prefix, response.text)
        # The landing must NOT carry an absolute ``http://`` or
        # ``https://`` URL pointing anywhere outside the local
        # surface either.
        self.assertNotIn("https://", response.text)
        self.assertNotIn("http://", response.text)
        # The session is the only signal the landing opened state.
        self.override.assert_not_called()

    def test_comenzar_does_not_link_to_admin_or_health(self) -> None:
        """The ``/comenzar`` placeholder must only offer the back
        link to the landing. Operational, administrative, webhook or
        internal API routes must never appear on the placeholder."""
        response = self.client.get("/comenzar")
        self.assertEqual(response.status_code, 200)
        self._assert_no_forbidden_anchor(response.text)
        for prefix in _FORBIDDEN_LINK_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertNotIn(prefix, response.text)
        self.assertNotIn("https://", response.text)
        self.assertNotIn("http://", response.text)
        # No submission surface — no form, no input, no mailto, no
        # explicitly-named email/phone input that could capture data.
        for forbidden in (
            "<form",
            "<input",
            "<textarea",
            "<select",
            "<button",
            'name="email"',
            'name="phone"',
            'type="email"',
            'type="tel"',
            "mailto:",
            'method="post"',
            'method="POST"',
            "javascript:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        self.override.assert_not_called()

    def test_admin_route_still_requires_browser_basic_credentials(self) -> None:
        """The Phase 1 change must never widen the existing
        administrative boundary. An unauthenticated ``/admin`` must
        still keep the documented credential-gate response. When the
        administrative token is configured the boundary returns
        ``401``; when no token is configured the existing behaviour
        returns ``503``. The landing must never accidentally make
        the admin route publicly accessible — any ``2xx`` or ``3xx``
        would be a regression."""
        response = self.client.get("/admin")
        self.assertIn(
            response.status_code,
            (401, 503),
            "admin route must keep its credential gate (401/503)",
        )
        self.assertNotIn(response.status_code, range(200, 400))

    def test_health_endpoint_is_unchanged(self) -> None:
        """The ``/health`` surface is part of the public monitoring
        contract and must keep returning the same payload even if it
        is no longer linked from the public onboarding pages."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_twilio_webhook_surface_is_unchanged(self) -> None:
        """The Twilio webhook routers stay mounted at the same paths
        and still reject unsigned POSTs with the documented failure
        code. This guards against accidental route reordering while
        wiring the new public router."""
        # An unsigned POST to the inbound webhook must keep failing.
        # The documented Twilio signature boundary is preserved.
        response_post = self.client.post(
            "/webhooks/twilio/whatsapp/inbound", data={}
        )
        self.assertEqual(response_post.status_code, 403)


class PublicOnboardingTemplatesStaticTest(unittest.TestCase):
    """Static checks on the new Jinja templates."""

    @staticmethod
    def _templates_dir() -> Path:
        return (
            Path(public_onboarding_module.__file__).resolve().parent.parent
            / "templates"
            / "public_onboarding"
        )

    def test_landing_template_uses_documented_sections(self) -> None:
        contents = (self._templates_dir() / "landing.html").read_text(
            encoding="utf-8"
        )
        # The Jinja placeholders are the documented contract: the
        # handler passes ``comenzar_url`` and the brand link points
        # at the documented root.
        self.assertIn('href="/"', contents)
        # The hero, benefits, process, trust and final CTA blocks
        # must each carry the documented marker so layout decisions
        # stay readable.
        for marker in (
            "section.hero",
            "section.benefits",
            "section.process",
            "section.trust",
            "section.cta-final",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, contents)
        for placeholder in ("{{ comenzar_url }}",):
            with self.subTest(placeholder=placeholder):
                self.assertIn(placeholder, contents)
        # The transparent CTA label must be present; the legacy
        # ``Probá gratis`` label must never leak back in.
        self.assertIn("Próximamente", contents)
        self.assertNotIn("Probá gratis", contents)
        self.assertNotIn("Probá NovaOrders", contents)
        # No remote assets, no JavaScript navigation.
        for needle in (
            "https://fonts.googleapis",
            "https://cdn.jsdelivr",
            "https://unpkg.com",
            '<link rel="stylesheet"',
            "<script",
            "history.back",
            "history.pushState",
        ):
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, contents)
        # The focus ring token makes the visual link to the rest of
        # the admin design system explicit even when the public
        # landing has its own palette.
        self.assertIn("--focus-ring", contents)
        # The pre-operate configuration item must appear as a
        # planned future flow rather than as a current technical
        # gate. The new heading carries the future-flow framing
        # and the body is phrased with ``el flujo previsto``.
        self.assertIn(
            "Configuración previa a la salida en vivo", contents
        )
        self.assertIn(
            "el flujo previsto contemplará configurar medios de pago",
            contents,
        )
        self.assertIn("métodos de entrega y un canal verificado", contents)
        # The block-list of forbidden copy must not appear anywhere
        # in the source so a future copy edit cannot reintroduce a
        # claim that has not been approved.
        for forbidden in _FORBIDDEN_COPY:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, contents)

    def test_proximamente_template_links_back_to_landing(self) -> None:
        contents = (self._templates_dir() / "proximamente.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('href="/"', contents)
        # The transparent placeholder copy must state that the
        # access request is not enabled.
        self.assertIn("El registro aún no está abierto", contents)
        self.assertIn(
            "La solicitud de acceso para nuevos comercios todavía no está habilitada",
            contents,
        )
        # The placeholder must never expose a form, a remote asset
        # or a script — it is the temporary stand-in for the
        # ``/comenzar`` target.
        for needle in (
            "<form",
            "<input",
            "<textarea",
            "<select",
            "<button",
            "<script",
            "https://",
            "http://",
            "mailto:",
            "/health",
            "/admin",
            "/webhooks",
            "/api/",
            'name="email"',
            'type="email"',
            'method="post"',
            'method="POST"',
        ):
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, contents)
        # No promise of notification by email or future magic link.
        for needle in (
            "te avisaremos",
            "te contactamos",
            "enlace seguro",
        ):
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, contents)


if __name__ == "__main__":
    unittest.main()
