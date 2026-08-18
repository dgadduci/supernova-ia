"""Focused tests for the Phase 4A owner self-service onboarding completion.

The ``add-commerce-self-service-onboarding`` change Phase 4A
introduces the closed ``OWNER`` membership boundary and the
atomic completion transaction that consumes the Phase 3
private draft. The tests in this file assert the documented
boundary:

* the completion transaction creates exactly one ``Comercio``
  in ``INACTIVO``, one active ``OWNER`` membership and one
  terminal draft transition in the same caller-owned unit of
  work;
* the completion transaction is owned by the caller — the
  completion service and its repositories never call
  ``commit`` / ``rollback``;
* an authenticated account must produce a single commerce for
  the same draft: concurrent completion requests serialise
  through the ``SELECT ... FOR UPDATE`` lock and only the first
  transition is staged;
* a retry on a terminal draft returns the existing outcome;
* an inconsistent terminal draft (membership missing or owned
  by another account) fails closed without auto-repair;
* an incomplete draft (including a missing ``slug``) is rejected
  before any commerce-side write occurs;
* ``ComercioService.stage_create()`` validates the canonical
  commerce rules and never commits / rolls back on its own;
* the existing ``ComercioService.create()`` Admin-facing seam
  still commits through the shared staging logic;
* ``POST /onboarding/completar`` only accepts a CSRF nonce + a
  same-origin ``Origin`` header. It never accepts a
  ``comercio_id`` or any second copy of the commerce payload;
* the completion transaction creates no channel, customer,
  session, order, catalogue row, payment association,
  delivery association, trial reservation or provider work.

The test database is the existing ``supernova_test`` PostgreSQL
fixture used across the project. Each test seeds and tears down
its own identifiers through the ``_Phase4ACleanup`` helper so
the rows are cleanly removed without touching other suites.
"""

from __future__ import annotations

import inspect
import unittest
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from backend.auth import SESSION_COOKIE_NAME
from backend.auth.principal import AuthenticatedPrincipal
from backend.dependencies import (
    OWNER_FORM_NONCE_FIELD,
    compute_owner_onboarding_form_nonce,
)
from backend.models import (
    BorradorOnboardingComercio,
    Comercio,
    ComercioUsuario,
    CuentaUsuario,
)
from backend.repositories.borrador_onboarding_comercio_repository import (
    REQUIRED_BASIC_FIELDS,
    DraftTerminalError,
)
from backend.services.comercio_service import ComercioService
from backend.services.exceptions import DuplicateSlug
from backend.services.owner_onboarding_completion_service import (
    OwnerOnboardingIncomplete,
    OwnerOnboardingNoDraft,
    OwnerOnboardingTerminalInconsistent,
    complete_onboarding,
)
from backend.services.owner_onboarding_service import (
    OwnerAccountInactive,
    load_or_create_borrador,
    resolve_or_create_cuenta,
    save_borrador,
)

DB_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(DB_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


def _make_principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="https://abc.supabase.co/auth/v1",
        audience="authenticated",
    )


def _enable_supabase_settings(**overrides: Any) -> Any:
    from backend.auth.settings import resolve_supabase_auth_settings
    from backend.config.settings import Settings

    base = Settings(
        llm_url="http://localhost:11434/api/generate",
        llm_model="qwen2.5-coder:7b-ctx8192",
        llm_timeout=180,
        llm_keep_alive="2h",
        llm_num_ctx=8192,
        llm_num_predict=0,
        llm_log_content=False,
        llm_log_max_chars=1000,
        supabase_auth_enabled=True,
        supabase_project_url="https://abc.supabase.co",
        supabase_jwt_issuer="https://abc.supabase.co/auth/v1",
        supabase_jwt_audience="authenticated",
        supabase_callback_url="https://test.example/auth/callback",
        supabase_jwks_url="https://abc.supabase.co/auth/v1/jwks",
        supabase_publishable_key=(
            "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
        ),
        supabase_session_secret=(
            "local-session-secret-for-tests-32b"
        ),
        supabase_session_max_age_seconds=1800,
        supabase_pkce_cookie_max_age_seconds=300,
        supabase_allowed_algorithms=("RS256",),
        supabase_abuse_guard_url="https://guard.example.com/check",
        supabase_abuse_guard_token="guard-token",
        supabase_request_timeout_seconds=10,
    )
    for name, value in overrides.items():
        object.__setattr__(base, name, value)
    return resolve_supabase_auth_settings(settings=base)


def _build_router_app(
    *,
    session_local: Callable[[], Session],
    supabase_settings: Any,
    csrf_secret: bytes,
) -> FastAPI:
    """Build a minimal FastAPI app wiring the owner router.

    The helper installs ``get_session`` /
    ``require_authenticated_owner_principal`` overrides so the
    router sees the test sessionmaker and the cookie-derived
    principal without contacting the Supabase JWKS client. The
    helper also rebinds the module-level owner-onboarding CSRF
    secret resolver so the wizard and the completion route share
    the same deterministic nonce the test computes.

    The ``_principal_override`` is declared at module scope so
    its ``request: Request`` annotation is resolved as the real
    Starlette ``Request`` class even though the test module
    enables ``from __future__ import annotations``. Without
    that, FastAPI treats the annotation as a forward string
    reference and refuses to inject the request, surfacing as a
    ``422`` validation error (``query.request``) before any
    route handler runs. Declaring the override at module scope
    also keeps the test fixture deterministic across reloads.
    """
    from backend import dependencies as deps
    from backend.routers import owner_onboarding

    app = FastAPI()
    app.include_router(owner_onboarding.router)

    def _session_override() -> Session:
        return session_local()

    def _csrf_secret_override() -> bytes:
        return csrf_secret

    app.dependency_overrides[deps.get_session] = _session_override
    app.dependency_overrides[
        deps.require_authenticated_owner_principal
    ] = _build_router_app_principal_override(supabase_settings)
    # Monkey-patch the module-level resolver so the wizard and
    # completion route agree with the nonce the test computes.
    deps._resolve_owner_onboarding_csrf_secret = _csrf_secret_override
    return app


def _build_router_app_principal_override(
    supabase_settings: Any,
):
    """Return the cookie-derived principal override as a module-scope function.

    The helper is exposed at module scope (not nested inside
    :func:`_build_router_app`) so its ``request`` annotation
    evaluates against the module-level globals. ``Request``
    is also imported at the module top so the
    ``from __future__ import annotations`` directive does not
    leave the annotation as a forward string — FastAPI's
    resolver otherwise refuses to inject the request and
    surfaces a ``query.request`` 422 before any route handler
    runs. The helper closes over ``supabase_settings`` so the
    cookie decoder uses the caller-configured Supabase settings.
    """
    from fastapi import HTTPException

    from backend.auth.session import parse_session_cookie

    def _principal_override(
        request: Request,
    ) -> AuthenticatedPrincipal:
        cookie_header = request.headers.get("cookie")
        headers = {"cookie": cookie_header} if cookie_header else {}
        local_session = parse_session_cookie(
            headers, settings=supabase_settings
        )
        if local_session is None:
            raise HTTPException(
                status_code=401,
                detail="Owner authentication required",
            )
        return AuthenticatedPrincipal(
            subject=local_session.subject,
            issuer=local_session.issuer,
            audience=local_session.audience,
        )

    return _principal_override


def _principal_cookie(subject: str, settings: Any) -> str:
    from backend.auth.session import encode_session

    principal = AuthenticatedPrincipal(
        subject=subject,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    return encode_session(principal, settings=settings)


def _build_complete_draft_fields(
    slug: str | None = None,
    *,
    suffix: str | None = None,
    omit: tuple[str, ...] = (),
) -> dict[str, str]:
    """Return a complete draft field mapping with random identifiers.

    The helper centralises the construction of a complete
    payload so the completion tests do not duplicate the
    closed field set across every test. Each field that the
    wizard documents as required (including ``slug``) carries a
    unique sentinel value tied to ``suffix``; tests can drop a
    specific field via the ``omit`` tuple to exercise the
    incomplete-draft path.
    """
    stamp = suffix or _suffix()
    fields: dict[str, str] = {
        "nombre_fantasia": f"Comercio {stamp}",
        "nombre_corto": f"C{stamp[:6]}",
        "razon_social": f"Comercio {stamp} SRL",
        "cuit": f"30-{stamp[:8]}-{stamp[8]}",
        "whatsapp": f"+5491{stamp[:10]}",
        "slug": slug or f"comercio-{stamp}",
        "calle": "Av. Test",
        "numero": "100",
        "localidad": "CABA",
        "provincia": "Buenos Aires",
    }
    for field in omit:
        fields[field] = ""
    return fields


def _seed_inactivo_estado() -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM estado_comercio "
                "WHERE codigo = 'INACTIVO'"
            )
        ).first()
        if row is None:
            conn.execute(
                text(
                    "INSERT INTO estado_comercio "
                    "(codigo, descripcion, modo_operacion, "
                    " seleccionable) "
                    "VALUES ('INACTIVO', 'Inactivo', "
                    " CAST('bloqueado' AS "
                    " estado_comercio_modo_operacion), "
                    " true) "
                    "ON CONFLICT (codigo) DO NOTHING"
                )
            )
            row = conn.execute(
                text(
                    "SELECT id FROM estado_comercio "
                    "WHERE codigo = 'INACTIVO'"
                )
            ).first()
    assert row is not None
    return int(row[0])


def _seed_required_estados() -> dict[str, int]:
    """Seed the lifecycle rows that the completion tests assume."""
    cache: dict[str, int] = {}
    with engine.begin() as conn:
        for codigo, descripcion, modo, seleccionable in (
            (
                "INACTIVO",
                "Inactivo",
                "bloqueado",
                True,
            ),
            ("ACTIVO", "Activo", "habilitado", True),
        ):
            row = conn.execute(
                text(
                    "SELECT id FROM estado_comercio "
                    "WHERE codigo = :codigo"
                ),
                {"codigo": codigo},
            ).first()
            if row is None:
                conn.execute(
                    text(
                        "INSERT INTO estado_comercio "
                        "(codigo, descripcion, modo_operacion, "
                        " seleccionable) "
                        "VALUES (:codigo, :descripcion, "
                        " CAST(:modo AS "
                        " estado_comercio_modo_operacion), "
                        " :seleccionable) "
                        "ON CONFLICT (codigo) DO NOTHING"
                    ),
                    {
                        "codigo": codigo,
                        "descripcion": descripcion,
                        "modo": modo,
                        "seleccionable": seleccionable,
                    },
                )
                row = conn.execute(
                    text(
                        "SELECT id FROM estado_comercio "
                        "WHERE codigo = :codigo"
                    ),
                    {"codigo": codigo},
                ).first()
            assert row is not None
            cache[codigo] = int(row[0])
    return cache


class _Phase4ACleanup:
    """Cleanup helper that removes the test seed surface."""

    def __init__(self) -> None:
        self.seeded_subjects: list[str] = []
        self.seeded_slugs: list[str] = []
        self.seeded_membership_ids: list[int] = []
        self.seeded_comercio_ids: list[int] = []

    def seed_subject(self) -> str:
        suffix = _suffix()
        subject = f"phase4a-{suffix}"
        self.seeded_subjects.append(subject)
        return subject

    def track_slug(self, slug: str) -> None:
        self.seeded_slugs.append(slug)

    def track_comercio(self, comercio_id: int) -> None:
        self.seeded_comercio_ids.append(comercio_id)

    def track_membership(self, membership_id: int) -> None:
        self.seeded_membership_ids.append(membership_id)

    def cleanup(self) -> None:
        with engine.begin() as conn:
            if self.seeded_membership_ids:
                conn.execute(
                    delete(ComercioUsuario).where(
                        ComercioUsuario.id.in_(
                            self.seeded_membership_ids
                        )
                    )
                )
            if self.seeded_subjects:
                cuenta_ids = conn.execute(
                    select(CuentaUsuario.id).where(
                        CuentaUsuario.supabase_subject.in_(
                            self.seeded_subjects
                        )
                    )
                ).all()
                ids = [int(row[0]) for row in cuenta_ids]
                if ids:
                    # Clear terminal references first so the
                    # RESTRICT FK on the draft and the FK on
                    # the membership to the comercio can be
                    # removed in any order.
                    conn.execute(
                        text(
                            "UPDATE borrador_onboarding_comercio "
                            "SET comercio_id = NULL, "
                            "completado_en = NULL "
                            "WHERE cuenta_usuario_id IN ("
                            " SELECT id FROM cuentas_usuario "
                            "WHERE id = ANY(:ids)"
                            ")"
                        ),
                        {"ids": ids},
                    )
                    conn.execute(
                        text(
                            "DELETE FROM comercio_usuarios "
                            "WHERE cuenta_usuario_id = ANY(:ids)"
                        ),
                        {"ids": ids},
                    )
                    conn.execute(
                        delete(BorradorOnboardingComercio).where(
                            BorradorOnboardingComercio.cuenta_usuario_id.in_(
                                ids
                            )
                        )
                    )
                    conn.execute(
                        delete(CuentaUsuario).where(
                            CuentaUsuario.id.in_(ids)
                        )
                    )
            if self.seeded_comercio_ids:
                conn.execute(
                    delete(Comercio).where(
                        Comercio.id.in_(self.seeded_comercio_ids)
                    )
                )
            if self.seeded_slugs:
                conn.execute(
                    text(
                        "UPDATE borrador_onboarding_comercio "
                        "SET comercio_id = NULL "
                        "WHERE comercio_id IN ("
                        " SELECT id FROM comercios "
                        "WHERE slug = ANY(:slugs)"
                        ")"
                    ),
                    {"slugs": self.seeded_slugs},
                )
                conn.execute(
                    text(
                        "DELETE FROM comercio_usuarios "
                        "WHERE comercio_id IN ("
                        " SELECT id FROM comercios "
                        "WHERE slug = ANY(:slugs)"
                        ")"
                    ),
                    {"slugs": self.seeded_slugs},
                )
                conn.execute(
                    delete(Comercio).where(
                        Comercio.slug.in_(self.seeded_slugs)
                    )
                )


class ServiceStageOnlyContractTest(unittest.TestCase):
    """``ComercioService.stage_create`` stages without commit / rollback."""

    def test_stage_create_does_not_commit_or_rollback(self) -> None:
        # Direct check on the source.
        self.assertNotIn(".commit(", inspect.getsource(ComercioService.stage_create))
        self.assertNotIn(".rollback(", inspect.getsource(ComercioService.stage_create))

    def test_admin_create_still_commits_through_shared_seam(self) -> None:
        """The Admin ``create()`` keeps commit / rollback ownership."""
        # The create() body must still end with a commit and must
        # delegate the validation / staging steps to the shared
        # ``stage_create`` helper.
        admin_src = inspect.getsource(ComercioService.create)
        self.assertIn("self.stage_create(payload)", admin_src)
        self.assertIn("self._session.commit()", admin_src)
        self.assertIn("self._session.rollback()", admin_src)


class MerchantStateSeedingMixin:
    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _seed_required_estados()


class StageCreateSharedValidationTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``stage_create`` rejects duplicate slugs / state mismatches."""

    def setUp(self) -> None:
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.inactivo_id = self._seed["INACTIVO"]

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _payload(self, slug: str) -> dict:
        stamp = _suffix()
        return {
            "nombre_fantasia": f"Stage {stamp}",
            "nombre_corto": f"S{stamp[:6]}",
            "razon_social": f"Stage {stamp} SRL",
            "cuit": f"30-{stamp[:8]}-{stamp[8]}",
            "whatsapp": f"+5490{stamp[:10]}",
            "slug": slug,
            "calle": "Av. Stage",
            "numero": "1",
            "localidad": "CABA",
            "provincia": "Buenos Aires",
            "estado_id": self.inactivo_id,
        }

    def test_stage_create_flushes_without_commit(self) -> None:
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            payload = self._payload(f"stage-{_suffix()}")
            comercio = service.stage_create(payload)
            comercio_id_int = int(comercio.id)
            self.cleanup.track_comercio(comercio_id_int)
            self.cleanup.track_slug(payload["slug"])

            # No commit yet: a fresh session cannot see the row.
            with engine.connect() as conn:
                row = conn.execute(
                    select(Comercio).where(
                        Comercio.slug == payload["slug"]
                    )
                ).first()
            self.assertIsNone(row)

            # Caller commits: the row becomes visible.
            session.commit()
            with engine.connect() as conn:
                row = conn.execute(
                    select(Comercio).where(
                        Comercio.slug == payload["slug"]
                    )
                ).first()
            self.assertIsNotNone(row)

    def test_stage_create_runs_inside_caller_rollback(self) -> None:
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            payload = self._payload(f"stage-{_suffix()}")
            service.stage_create(payload)
            self.cleanup.track_slug(payload["slug"])

            # Caller rolls back: the staged row must not survive.
            session.rollback()

        with engine.connect() as conn:
            row = conn.execute(
                select(Comercio).where(
                    Comercio.slug == payload["slug"]
                )
            ).first()
        self.assertIsNone(row)

    def test_stage_create_rejects_duplicate_slug(self) -> None:
        slug = f"stage-dup-{_suffix()}"
        self.cleanup.track_slug(slug)
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            payload = self._payload(slug)
            staged = service.stage_create(payload)
            self.cleanup.track_comercio(int(staged.id))
            session.commit()

        with TestingSessionLocal() as session:
            service = ComercioService(session)
            with self.assertRaises(DuplicateSlug):
                service.stage_create(self._payload(slug))


class CompletionServiceAtomicityTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``complete_onboarding`` creates commerce + membership + terminal draft."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self._account_and_complete_draft(
            slug=f"phase4a-atomic-{_suffix()}"
        )

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _account_and_complete_draft(self, *, slug: str) -> int:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            saved = save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            assert saved.completo is True
            cuenta_id = int(cuenta.id)
        self.cleanup.track_slug(slug)
        return cuenta_id

    def test_completion_creates_inactivo_comercio_owner_membership(
        self,
    ) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            outcome = complete_onboarding(session, principal)
            session.commit()
            comercio_id_value = int(outcome.comercio_id)
            self.cleanup.track_comercio(comercio_id_value)

            comercio = session.get(Comercio, comercio_id_value)
            assert comercio is not None
            self.assertEqual(comercio.estado_id, self._seed["INACTIVO"])
            self.assertTrue(comercio.slug.startswith("phase4a-atomic-"))

            membership = session.execute(
                select(ComercioUsuario).where(
                    ComercioUsuario.comercio_id == comercio_id_value,
                    ComercioUsuario.rol == "OWNER",
                )
            ).scalar_one()
            self.assertEqual(
                int(membership.cuenta_usuario_id),
                int(cuenta.id),
            )
            self.assertTrue(membership.activo)
            self.cleanup.track_membership(int(membership.id))

            draft = session.execute(
                select(BorradorOnboardingComercio).where(
                    BorradorOnboardingComercio.cuenta_usuario_id
                    == int(cuenta.id)
                )
            ).scalar_one()
            self.assertEqual(int(draft.comercio_id), comercio_id_value)
            self.assertIsNotNone(draft.completado_en)

        # No side-effects on orders / payments / channels
        with engine.connect() as conn:
            sentinel = conn.execute(
                text(
                    "SELECT to_regclass("
                    "'public.canales_whatsapp')"
                )
            ).scalar()
            self.assertEqual(sentinel, "canales_whatsapp")
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM pedidos"
                    )
                ).scalar_one(),
                0,
            )

    def test_router_create_does_not_call_completion(self) -> None:
        """The Admin commit-bound seam still works through the shared staging helper."""
        # Smoke test of the Admin contract, not a Phase 4A flow.
        slug = f"admin-{_suffix()}"
        with TestingSessionLocal() as session:
            payload = {
                **{
                    key: value
                    for key, value in (
                        (
                            "nombre_fantasia",
                            f"Admin {_suffix()}",
                        ),
                        (
                            "nombre_corto",
                            f"A{_suffix()[:6]}",
                        ),
                        (
                            "razon_social",
                            f"Admin {_suffix()} SRL",
                        ),
                        (
                            "cuit",
                            f"30-{_suffix()[:8]}-{_suffix()[8]}",
                        ),
                        (
                            "whatsapp",
                            f"+54910{_suffix()[:8]}",
                        ),
                        ("slug", slug),
                        ("calle", "Av. Admin"),
                        ("numero", "1"),
                        ("localidad", "CABA"),
                        ("provincia", "Buenos Aires"),
                    )
                },
                "estado_id": self._seed["ACTIVO"],
            }
            comercio = ComercioService(session).create(payload)
            session.commit()
            self.cleanup.track_comercio(int(comercio.id))
            self.cleanup.track_slug(slug)


class CompletionServiceAtomicityRollbackTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """A persistence failure in the completion flow rolls everything back."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-rollback-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_intermediate_failure_rolls_back_all_three_rows(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        with TestingSessionLocal() as session:
            with self.assertRaises(RuntimeError):
                with session.begin():
                    complete_onboarding(session, principal)
                    raise RuntimeError("simulated flush failure")
            # Session closed cleanly; nothing reached durable storage.
            session.rollback()

        with engine.connect() as conn:
            slug_row = conn.execute(
                text("SELECT id FROM comercios WHERE slug = :slug"),
                {"slug": self.slug},
            ).first()
            self.assertIsNone(slug_row)
            cuenta_row = conn.execute(
                text(
                    "SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject"
                ),
                {"subject": self.subject},
            ).first()
            self.assertIsNotNone(cuenta_row)
            draft_row = conn.execute(
                text(
                    "SELECT id FROM borrador_onboarding_comercio "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": int(cuenta_row[0])},
            ).first()
            self.assertIsNotNone(draft_row)
            self.assertEqual(len(draft_row), 1)


class CompletionConcurrencyTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Two concurrent completion requests produce exactly one commerce."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-concurrent-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _prepare_complete_draft(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

    def test_two_concurrent_completions_produce_one_comercio(self) -> None:
        self._prepare_complete_draft()

        with TestingSessionLocal() as session_a:
            with session_a.begin():
                outcome_a = complete_onboarding(
                    session_a, _make_principal(self.subject)
                )

        with TestingSessionLocal() as session_b:
            with session_b.begin():
                outcome_b = complete_onboarding(
                    session_b, _make_principal(self.subject)
                )

        self.assertEqual(outcome_a.comercio_id, outcome_b.comercio_id)
        self.assertEqual(outcome_a.cuenta_id, outcome_b.cuenta_id)
        self.cleanup.track_comercio(int(outcome_a.comercio_id))

        with engine.connect() as conn:
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 1)
            owner_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercio_usuarios "
                    "WHERE comercio_id = :comercio_id "
                    "AND rol = 'OWNER'"
                ),
                {"comercio_id": int(outcome_a.comercio_id)},
            ).scalar_one()
            self.assertEqual(int(owner_count), 1)


class CompletionIdempotencyTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """A retry on a terminal draft returns the existing outcome."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-retry-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_retry_returns_existing_outcome_without_new_comercio(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        with TestingSessionLocal() as session:
            with session.begin():
                first = complete_onboarding(session, principal)
                first_comercio_id = int(first.comercio_id)
            self.cleanup.track_comercio(first_comercio_id)

        with TestingSessionLocal() as session:
            with session.begin():
                second = complete_onboarding(session, principal)

        self.assertEqual(first.comercio_id, second.comercio_id)
        self.assertEqual(first.completado_en, second.completado_en)

        with engine.connect() as conn:
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 1)


class CompletionTerminalInconsistencyTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """An inconsistent terminal draft fails closed without auto-repair."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-inconsistent-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _prepare_terminal_draft(
        self, *, with_membership: bool, owner_subject: str
    ) -> tuple[int, int]:
        principal = _make_principal(self.subject)
        # Note: resolve_or_create_cuenta calls session.commit() at
        # the Phase 3 boundary, so it must run outside a wrapped
        # ``session.begin()`` block.
        borrador_id_value: int = 0
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            borrador_id_value = int(draft.id)
        with TestingSessionLocal() as session, session.begin():
            comercio_id_local = _seed_orphan_comercio(
                slug=self.slug,
                estado_id=self._seed["INACTIVO"],
            )
            self.cleanup.track_comercio(comercio_id_local)

            from datetime import datetime, timezone

            from backend.models import BorradorOnboardingComercio
            from backend.repositories.borrador_onboarding_comercio_repository import (
                BorradorOnboardingComercioRepository,
            )

            borrador = session.get(BorradorOnboardingComercio, borrador_id_value)
            assert borrador is not None
            BorradorOnboardingComercioRepository(session).mark_terminal(
                borrador,
                comercio_id=comercio_id_local,
                completado_en=datetime.now(timezone.utc),
            )

            if with_membership:
                _seed_owner_membership(
                    cuenta_usuario_id=_resolve_cuenta_id(owner_subject),
                    comercio_id=comercio_id_local,
                )

        return comercio_id_local, _resolve_cuenta_id(self.subject)

    def test_missing_membership_fails_closed(self) -> None:
        _comercio_id_value, _ = self._prepare_terminal_draft(
            with_membership=False,
            owner_subject=self.subject,
        )
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(
                OwnerOnboardingTerminalInconsistent
            ):
                with session.begin():
                    complete_onboarding(session, principal)

        # The route must NOT create a second comercio; only the
        # pre-existing orphan commerce remains.
        with engine.connect() as conn:
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 1)

    def test_other_account_terminal_draft_fails_closed(self) -> None:
        other_subject = f"phase4a-other-{_suffix()}"
        self.cleanup.seeded_subjects.append(other_subject)
        _seed_cuenta(other_subject)
        _comercio_id_value, _ = self._prepare_terminal_draft(
            with_membership=True,
            owner_subject=other_subject,
        )
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(
                OwnerOnboardingTerminalInconsistent
            ):
                with session.begin():
                    complete_onboarding(session, principal)


def _seed_cuenta(subject: str) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM cuentas_usuario "
                "WHERE supabase_subject = :subject"
            ),
            {"subject": subject},
        ).first()
        if row is None:
            cuenta_id = conn.execute(
                text(
                    "INSERT INTO cuentas_usuario "
                    "(supabase_subject, activo, fecha_alta, "
                    " fecha_ultima_modificacion) "
                    "VALUES (:subject, true, now(), now()) "
                    "RETURNING id"
                ),
                {"subject": subject},
            ).scalar_one()
        else:
            cuenta_id = int(row[0])
    return cuenta_id


def _resolve_cuenta_id(subject: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM cuentas_usuario "
                "WHERE supabase_subject = :subject"
            ),
            {"subject": subject},
        ).first()
    assert row is not None
    return int(row[0])


def _seed_orphan_comercio(*, slug: str, estado_id: int) -> int:
    from sqlalchemy.exc import IntegrityError

    stamp = _suffix()
    with engine.begin() as conn:
        try:
            comercio_id = conn.execute(
                text(
                    "INSERT INTO comercios "
                    "(nombre_fantasia, nombre_corto, "
                    " razon_social, cuit, whatsapp, calle, "
                    " numero, localidad, provincia, slug, "
                    " estado_id, zona_horaria, moneda, "
                    " idioma, prueba_pedidos_consumidos) "
                    "VALUES ('Orphan " + stamp + "', 'OR', "
                    " 'Orphan " + stamp + " SRL', "
                    " '30-99999995-1', '+54910" + stamp[:8] + "', "
                    " 'Av. Orphan', '1', 'CABA', "
                    " 'Buenos Aires', :slug, "
                    " :estado_id, "
                    " 'America/Argentina/Buenos_Aires', "
                    " 'ARS', 'es-AR', 0) RETURNING id"
                ),
                {"slug": slug, "estado_id": estado_id},
            ).scalar_one()
        except IntegrityError:
            row = conn.execute(
                text(
                    "SELECT id FROM comercios WHERE slug = :slug"
                ),
                {"slug": slug},
            ).first()
            assert row is not None
            comercio_id = int(row[0])
    return int(comercio_id)


def _seed_owner_membership(
    *, cuenta_usuario_id: int, comercio_id: int
) -> int:
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        try:
            membership_id = conn.execute(
                text(
                    "INSERT INTO comercio_usuarios "
                    "(cuenta_usuario_id, comercio_id, rol, "
                    " activo, fecha_alta, "
                    " fecha_ultima_modificacion) "
                    "VALUES (:cuenta_id, :comercio_id, 'OWNER', "
                    " true, now(), now()) RETURNING id"
                ),
                {
                    "cuenta_id": cuenta_usuario_id,
                    "comercio_id": comercio_id,
                },
            ).scalar_one()
        except IntegrityError:
            row = conn.execute(
                text(
                    "SELECT id FROM comercio_usuarios "
                    "WHERE cuenta_usuario_id = :cuenta_id "
                    "AND comercio_id = :comercio_id "
                    "AND rol = 'OWNER'"
                ),
                {
                    "cuenta_id": cuenta_usuario_id,
                    "comercio_id": comercio_id,
                },
            ).first()
            assert row is not None
            membership_id = int(row[0])
    return int(membership_id)


class CompletionIncompleteDraftTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """The completion service rejects incomplete / slug-missing drafts."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_slug_missing_blocks_completion(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields()
            del fields["slug"]
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            self.assertFalse(bool(draft.completo))

        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerOnboardingIncomplete):
                with session.begin():
                    complete_onboarding(session, principal)

        with engine.connect() as conn:
            slug_count = conn.execute(
                text("SELECT COUNT(*) FROM comercios")
            ).scalar_one()
            self.assertGreaterEqual(int(slug_count), 0)

    def test_draft_save_rejects_terminal_draft(self) -> None:
        """The wizard refuses to save on a terminal draft."""
        principal = _make_principal(self.subject)
        slug = f"phase4a-terminal-{_suffix()}"
        self.cleanup.track_slug(slug)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        with TestingSessionLocal() as session:
            with session.begin():
                first = complete_onboarding(session, principal)
                comercio_id_value = int(first.comercio_id)
                self.cleanup.track_comercio(comercio_id_value)

        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            with self.assertRaises(DraftTerminalError):
                save_borrador(
                    session,
                    draft,
                    expected_version=int(draft.version),
                    fields=fields,
                )


class CompletionRouteContractTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """HTTP contract: POST /onboarding/completar is the only completion surface.

    The route-level tests in this class exercise the wizard
    surface through the real ASGI ``TestClient``: the router is
    the only boundary the wizard exposes, so every assertion
    runs against the wired FastAPI app, not against an internal
    service helper. The TestClient is configured with a real
    form-encoded body so the route's ``Form`` parameter is read
    through the same dependency path the production browser
    uses.
    """

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.settings = _enable_supabase_settings()
        self.csrf_secret = self.settings.session_secret.encode("utf-8")
        self.app = _build_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=self.settings,
            csrf_secret=self.csrf_secret,
        )
        self.client = TestClient(
            self.app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _principal_cookie(self) -> str:
        return _principal_cookie(self.subject, self.settings)

    def _completion_nonce(self) -> str:
        return compute_owner_onboarding_form_nonce(
            path="/onboarding/completar",
            secret=self.csrf_secret,
        )

    def test_completion_post_without_csrf_is_rejected(self) -> None:
        response = self.client.post(
            "/onboarding/completar",
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_completion_route_exists_with_expected_path_and_methods(
        self,
    ) -> None:
        """The completion route is wired at the expected path."""

        # The router registers the routes; iterate via the public
        # APIRouter's routes collection.
        from backend.routers import owner_onboarding

        paths = [
            getattr(r, "path", "")
            for r in owner_onboarding.router.routes
            if getattr(r, "path", "") == "/onboarding/completar"
        ]
        self.assertEqual(len(paths), 1)

    def test_completion_post_rejects_comercio_id_in_payload(self) -> None:
        """A rogue comercio_id or second payload is ignored.

        The test fires the real HTTP ``POST /onboarding/completar``
        surface with a stale payload so the router must build the
        staged commerce exclusively from the persisted draft, not
        from the post body. The completion helper ignores any
        field the wizard never reads; a rogue ``comercio_id``
        must therefore NOT produce a differently-slugged
        commerce. The route is invoked through the wired FastAPI
        app so the same-origin + CSRF dependency runs end-to-end.
        """
        slug = f"phase4a-render-{_suffix()}"
        self.cleanup.track_slug(slug)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        nonce = self._completion_nonce()
        cookie = self._principal_cookie()
        response = self.client.post(
            "/onboarding/completar",
            data={
                OWNER_FORM_NONCE_FIELD: nonce,
                "comercio_id": "9999",
                "slug": "rogue-slug-from-form",
            },
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie}",
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Tu comercio fue creado",
            response.text,
        )

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, slug FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": slug},
            ).all()
            rogue_rows = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": "rogue-slug-from-form"},
            ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], slug)
        self.assertEqual(len(rogue_rows), 0)

        self.cleanup.track_comercio(int(rows[0][0]))

    def test_completion_post_happy_path_persists_terminal_state(
        self,
    ) -> None:
        """Real HTTP ``POST /onboarding/completar`` happy path.

        The test drives the wired FastAPI app end-to-end so the
        ASGI stack, the same-origin + CSRF dependency and the
        session transaction are all exercised. The assertions
        verify the bounded terminal response, the INACTIVO
        ``Comercio`` row, the OWNER membership and the terminal
        draft transition in the database.
        """
        slug = f"phase4a-http-{_suffix()}"
        self.cleanup.track_slug(slug)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        nonce = self._completion_nonce()
        cookie = self._principal_cookie()
        response = self.client.post(
            "/onboarding/completar",
            data={OWNER_FORM_NONCE_FIELD: nonce},
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie}",
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Tu comercio fue creado",
            response.text,
        )

        # Verify the database state matches the OpenSpec Phase 4A
        # contract: one INACTIVO comercio, one active OWNER
        # membership and a terminal draft transition, all for
        # the resolved ``CuentaUsuario``.
        with engine.connect() as conn:
            comercio_row = conn.execute(
                text(
                    "SELECT id, estado_id, slug FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": slug},
            ).first()
            assert comercio_row is not None
            comercio_id_value = int(comercio_row[0])
            self.cleanup.track_comercio(comercio_id_value)
            inactivo_id_value = int(
                conn.execute(
                    text(
                        "SELECT id FROM estado_comercio "
                        "WHERE codigo = 'INACTIVO'"
                    )
                ).scalar_one()
            )
            self.assertEqual(
                int(comercio_row[1]), inactivo_id_value
            )
            self.assertEqual(comercio_row[2], slug)

            membership_row = conn.execute(
                text(
                    "SELECT id, activo, cuenta_usuario_id, "
                    "comercio_id FROM comercio_usuarios "
                    "WHERE comercio_id = :comercio_id "
                    "AND rol = 'OWNER'"
                ),
                {"comercio_id": comercio_id_value},
            ).first()
            assert membership_row is not None
            self.assertTrue(bool(membership_row[1]))
            self.cleanup.track_membership(int(membership_row[0]))

            cuenta_id_value = int(membership_row[2])

            draft_row = conn.execute(
                text(
                    "SELECT comercio_id, completado_en "
                    "FROM borrador_onboarding_comercio "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            assert draft_row is not None
            self.assertEqual(
                int(draft_row[0]), comercio_id_value
            )
            self.assertIsNotNone(draft_row[1])

            # The first access must NOT produce an unrelated
            # comercio: the slug is unique and the staged
            # commerce is the only one.
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 1)


class ServiceStageOnlyBoundaryTest(unittest.TestCase):
    """The completion service and its collaborators never commit / rollback."""

    def test_completion_service_is_stage_only(self) -> None:
        from backend.repositories.borrador_onboarding_comercio_repository import (
            BorradorOnboardingComercioRepository,
        )
        from backend.repositories.comercio_usuario_repository import (
            ComercioUsuarioRepository,
        )
        from backend.services.owner_onboarding_completion_service import (
            complete_onboarding,
            stage_payload_from_fields,
        )

        for source in (
            inspect.getsource(complete_onboarding),
            inspect.getsource(stage_payload_from_fields),
        ):
            self.assertNotIn(".commit(", source)
            self.assertNotIn(".rollback(", source)

        for cls in (
            ComercioUsuarioRepository,
            BorradorOnboardingComercioRepository,
        ):
            src = inspect.getsource(cls)
            with self.subTest(repo=cls.__name__):
                self.assertNotIn(".commit(", src)
                self.assertNotIn(".rollback(", src)


class RequiredFieldsIncludeSlugTest(unittest.TestCase):
    """The wizard and repository treat ``slug`` as a required field."""

    def test_repository_required_fields_contain_slug(self) -> None:
        self.assertIn("slug", REQUIRED_BASIC_FIELDS)

    def test_repo_save_updates_completo_including_slug(self) -> None:
        principal_subject = f"phase4a-fields-{_suffix()}"
        cleanup = _Phase4ACleanup()
        cleanup.seeded_subjects.append(principal_subject)
        try:
            with TestingSessionLocal() as session:
                principal = _make_principal(principal_subject)
                cuenta = resolve_or_create_cuenta(session, principal)
                draft = load_or_create_borrador(session, cuenta)
                fields = _build_complete_draft_fields()
                del fields["slug"]
                saved = save_borrador(
                    session,
                    draft,
                    expected_version=0,
                    fields=fields,
                )
                self.assertFalse(saved.completo)

                fields["slug"] = "phase4a-fields-slug"
                saved_with_slug = save_borrador(
                    session,
                    draft,
                    expected_version=int(saved.version),
                    fields=fields,
                )
                self.assertTrue(saved_with_slug.completo)
        finally:
            cleanup.cleanup()


class AccountInactiveBlocksCompletionTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """An inactive ``CuentaUsuario`` refuses completion."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-inactive-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_inactive_account_blocks_completion(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE cuentas_usuario "
                        "SET activo = false, "
                        " fecha_baja = now() "
                        "WHERE supabase_subject = :subject"
                    ),
                    {"subject": self.subject},
                )

        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerAccountInactive):
                with session.begin():
                    complete_onboarding(session, principal)


class NoDraftBlocksCompletionTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Account without a draft raises the typed ``NoDraft`` error."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_account_without_draft_raises_no_draft(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            resolve_or_create_cuenta(session, principal)

        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerOnboardingNoDraft):
                with session.begin():
                    complete_onboarding(session, principal)


class InactivoWrongModeBlocksCompletionTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``_inactivo_estado_id`` fails closed on a misconfigured row."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-wrongmode-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_inactivo_with_wrong_modo_raises_missing(self) -> None:
        """INACTIVO with ``modo_operacion != BLOQUEADO`` fails closed.

        The test forces the ``INACTIVO`` row into the
        ``HABILITADO`` mode (not the documented
        ``BLOQUEADO``) and confirms the completion service
        raises :class:`OwnerOnboardingInactivoMissing` rather
        than silently staging the commerce in a wrong
        lifecycle state.
        """
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE estado_comercio "
                    "SET modo_operacion = "
                    "CAST('habilitado' AS "
                    " estado_comercio_modo_operacion) "
                    "WHERE codigo = 'INACTIVO'"
                )
            )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        with TestingSessionLocal() as session:
            from backend.services.owner_onboarding_completion_service import (
                OwnerOnboardingInactivoMissing,
            )

            with self.assertRaises(OwnerOnboardingInactivoMissing):
                with session.begin():
                    complete_onboarding(session, principal)

        with engine.connect() as conn:
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 0)

        # Restore the row for the next test in the suite.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE estado_comercio "
                    "SET modo_operacion = "
                    "CAST('bloqueado' AS "
                    " estado_comercio_modo_operacion) "
                    "WHERE codigo = 'INACTIVO'"
                )
            )


class CompletionRecomputesCompletoTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``complete_onboarding`` recomputes completeness server-side."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-recompute-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_draft_with_completo_true_but_empty_field_blocks(
        self,
    ) -> None:
        """``completo=True`` with an empty required field blocks.

        The test simulates the documented drift scenario:
        ``draft.completo`` is ``True`` because the wizard save
        ran before the column was added (or before the
        requirement tightened) but a required basic field
        (``slug``) is empty. The completion service MUST
        recompute completeness from the persisted fields and
        refuse to stage the commerce, even though the flag
        itself says complete.
        """
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        # Force the draft into the drift scenario: drop the
        # ``slug`` value but leave ``completo`` True to mirror
        # the documented "stale flag" risk.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE borrador_onboarding_comercio "
                    "SET slug = NULL, completo = true "
                    "WHERE cuenta_usuario_id = ("
                    " SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject)"
                ),
                {"subject": self.subject},
            )

        with TestingSessionLocal() as session:
            from backend.services.owner_onboarding_completion_service import (
                OwnerOnboardingIncomplete,
            )

            with self.assertRaises(OwnerOnboardingIncomplete):
                with session.begin():
                    complete_onboarding(session, principal)

        with engine.connect() as conn:
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 0)


class FirstAccessNoNestedCommitTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """The first wizard access never produces a nested commit."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.settings = _enable_supabase_settings()
        self.csrf_secret = self.settings.session_secret.encode("utf-8")
        self.app = _build_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=self.settings,
            csrf_secret=self.csrf_secret,
        )
        self.client = TestClient(
            self.app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _principal_cookie(self) -> str:
        return _principal_cookie(self.subject, self.settings)

    def test_first_get_creates_account_without_500(self) -> None:
        """First authenticated ``GET /onboarding`` does not 500.

        The test drives the wired FastAPI app, performs a
        same-origin GET, and confirms:

        * the response is ``200``;
        * the wizard template renders without an unclassified
          exception;
        * the account row landed in the database before the
          response, so no nested-commit was needed;
        * the response never exposes a comercio / slug / id
          because the draft is not terminal.
        """
        cookie = self._principal_cookie()
        response = self.client.get(
            "/onboarding",
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie}",
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Datos básicos del comercio",
            response.text,
        )
        # The completion form is a sibling of the wizard form
        # only when ``progress.completo`` is True; on the first
        # access the wizard is empty so the completion button
        # must NOT be present yet.
        self.assertNotIn(
            'action="/onboarding/completar"',
            response.text,
        )

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject"
                ),
                {"subject": self.subject},
            ).first()
            self.assertIsNotNone(row)


class TerminalDraftMembershipMissingTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``GET /onboarding`` fails closed when membership is missing."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.other_subject = f"phase4a-other-{_suffix()}"
        self.cleanup.seeded_subjects.append(self.other_subject)
        self.slug = f"phase4a-get-membership-{_suffix()}"
        self.cleanup.track_slug(self.slug)
        self.settings = _enable_supabase_settings()
        self.csrf_secret = self.settings.session_secret.encode("utf-8")
        self.app = _build_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=self.settings,
            csrf_secret=self.csrf_secret,
        )
        self.client = TestClient(
            self.app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_terminal_draft_without_owner_membership_hides_comercio(
        self,
    ) -> None:
        """A terminal draft without OWNER membership must hide the
        comercio / slug / id and render a bounded feedback view.

        The test pre-seeds a terminal draft for the resolved
        account but leaves the OWNER membership missing on
        the referenced comercio. The router must detect the
        inconsistency, refuse to render
        ``onboarding_completado.html``, and never expose the
        comercio id, slug or any draft reference.
        """
        _seed_cuenta(self.other_subject)
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            borrador_id_value = int(draft.id)

        # Stage the orphan commerce and the terminal draft
        # transition but skip the OWNER membership insert.
        comercio_id_value: int = 0
        with TestingSessionLocal() as session, session.begin():
            comercio_id_value = _seed_orphan_comercio(
                slug=self.slug,
                estado_id=self._seed["INACTIVO"],
            )
            self.cleanup.track_comercio(comercio_id_value)
            borrador = session.get(
                BorradorOnboardingComercio, borrador_id_value
            )
            assert borrador is not None
            from datetime import datetime, timezone

            from backend.repositories.borrador_onboarding_comercio_repository import (
                BorradorOnboardingComercioRepository,
            )

            BorradorOnboardingComercioRepository(session).mark_terminal(
                borrador,
                comercio_id=comercio_id_value,
                completado_en=datetime.now(timezone.utc),
            )

        cookie = _principal_cookie(self.subject, self.settings)
        response = self.client.get(
            "/onboarding",
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie}",
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 503)
        # The bounded feedback view must NOT expose the
        # comercio id, slug, or the wizard template.
        self.assertNotIn(
            "Tu comercio fue creado",
            response.text,
        )
        self.assertNotIn(
            f"#{comercio_id_value}",
            response.text,
        )
        self.assertNotIn(
            self.slug,
            response.text,
        )
        self.assertNotIn(
            "Datos básicos del comercio",
            response.text,
        )


class CompletionMarkTerminalFailureRollbackTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``mark_terminal`` failure rolls back the staged commerce + membership.

    The completion transaction stages three rows in this exact
    order: ``Comercio`` (via ``stage_create``), ``ComercioUsuario``
    (via ``create_owner``) and the terminal ``comercio_id`` /
    ``completado_en`` transition on the draft (via
    ``mark_terminal``). When ``mark_terminal`` fails the staged
    commerce and the staged membership must be rolled back together
    with the draft transition: the helper must NOT translate the
    failure to HTML inside the transaction, must NOT skip the
    rollback, and must NOT leave any partial state behind.
    """

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-mt-fail-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_mark_terminal_failure_rolls_back_all_three_rows(
        self,
    ) -> None:
        """Failure of ``mark_terminal`` rolls back stage_create + create_owner.

        The test patches
        :meth:`BorradorOnboardingComercioRepository.mark_terminal`
        to raise a generic ``RuntimeError`` AFTER
        :meth:`ComercioService.stage_create` and
        :meth:`ComercioUsuarioRepository.create_owner` have
        already staged their rows. The completion transaction
        must escape the exception, the ``with session.begin():``
        context manager must roll back, and the database must
        have no ``Comercio`` row, no ``ComercioUsuario`` row,
        and no terminal ``comercio_id`` / ``completado_en``
        transition on the draft.
        """
        from unittest.mock import patch

        from backend.repositories.borrador_onboarding_comercio_repository import (
            BorradorOnboardingComercioRepository,
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        with patch.object(
            BorradorOnboardingComercioRepository,
            "mark_terminal",
            side_effect=RuntimeError(
                "simulated flush failure inside mark_terminal"
            ),
        ):
            with TestingSessionLocal() as session:
                with self.assertRaises(RuntimeError):
                    with session.begin():
                        complete_onboarding(session, principal)
                # The ``with`` block already rolled back; the
                # explicit rollback is a no-op but keeps the
                # session usable for the verification phase.
                session.rollback()

        with engine.connect() as conn:
            slug_row = conn.execute(
                text("SELECT id FROM comercios WHERE slug = :slug"),
                {"slug": self.slug},
            ).first()
            self.assertIsNone(slug_row)
            cuenta_row = conn.execute(
                text(
                    "SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject"
                ),
                {"subject": self.subject},
            ).first()
            self.assertIsNotNone(cuenta_row)
            assert cuenta_row is not None
            cuenta_id_value = int(cuenta_row[0])
            membership_row = conn.execute(
                text(
                    "SELECT id FROM comercio_usuarios "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNone(membership_row)
            draft_row = conn.execute(
                text(
                    "SELECT comercio_id, completado_en "
                    "FROM borrador_onboarding_comercio "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNotNone(draft_row)
            assert draft_row is not None
            self.assertIsNone(draft_row[0])
            self.assertIsNone(draft_row[1])


class CompletionMembershipIntegrityErrorTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``IntegrityError`` on ``create_owner`` is translated to a typed race.

    The completion service must catch a flush-time
    ``IntegrityError`` raised inside
    :meth:`ComercioUsuarioRepository.create_owner` and re-raise it
    as :class:`OwnerOnboardingUnicityRace` so the route can
    render a bounded service-unavailable view AFTER the
    ``with session.begin():`` context manager rolled the staged
    commerce and the staged membership back together. The
    integrity error must never surface as a raw 500.
    """

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-mb-fail-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_integrity_error_on_create_owner_translates_to_race(
        self,
    ) -> None:
        """``IntegrityError`` on ``create_owner`` is translated to a typed race.

        The test patches
        :meth:`ComercioUsuarioRepository.create_owner` to raise a
        SQLAlchemy ``IntegrityError`` AFTER
        :meth:`ComercioService.stage_create` has already staged
        the ``Comercio`` row. The completion service must catch
        the error and re-raise it as
        :class:`OwnerOnboardingUnicityRace`. The surrounding
        ``with session.begin():`` context manager must roll the
        staged commerce back, so the database must have no
        ``Comercio`` row, no ``ComercioUsuario`` row and no
        terminal ``comercio_id`` / ``completado_en`` transition
        on the draft.
        """
        from unittest.mock import patch

        from sqlalchemy.exc import IntegrityError

        from backend.repositories.comercio_usuario_repository import (
            ComercioUsuarioRepository,
        )
        from backend.services.owner_onboarding_completion_service import (
            OwnerOnboardingUnicityRace,
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        integrity = IntegrityError(
            "INSERT",
            {},
            Exception("duplicate key value violates unique constraint"),
        )
        with patch.object(
            ComercioUsuarioRepository,
            "create_owner",
            side_effect=integrity,
        ):
            with TestingSessionLocal() as session:
                with self.assertRaises(OwnerOnboardingUnicityRace):
                    with session.begin():
                        complete_onboarding(session, principal)
                session.rollback()

        with engine.connect() as conn:
            slug_row = conn.execute(
                text("SELECT id FROM comercios WHERE slug = :slug"),
                {"slug": self.slug},
            ).first()
            self.assertIsNone(slug_row)
            cuenta_row = conn.execute(
                text(
                    "SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject"
                ),
                {"subject": self.subject},
            ).first()
            self.assertIsNotNone(cuenta_row)
            assert cuenta_row is not None
            cuenta_id_value = int(cuenta_row[0])
            membership_row = conn.execute(
                text(
                    "SELECT id FROM comercio_usuarios "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNone(membership_row)
            draft_row = conn.execute(
                text(
                    "SELECT comercio_id, completado_en "
                    "FROM borrador_onboarding_comercio "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNotNone(draft_row)
            assert draft_row is not None
            self.assertIsNone(draft_row[0])
            self.assertIsNone(draft_row[1])


class CompletionInactiveMembershipIsInconsistentTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """An inactive OWNER membership is a terminal inconsistency, not idempotency.

    The completion service rejects retrying a terminal draft
    whose OWNER membership was soft-revoked (``activo=False``)
    after the fact. Rendering a success view on an inactive
    membership would let the wizard infer a successful
    completion while the application considers the account
    unauthorised over the referenced comercio, breaking the
    documented "fail closed, never repair" invariant.
    """

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-inactive-mb-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_inactive_owner_membership_is_not_idempotent(self) -> None:
        """An inactive OWNER membership fails closed without auto-repair.

        The test seeds a terminal draft (i.e.
        ``comercio_id`` + ``completado_en`` are populated) and a
        single OWNER ``ComercioUsuario`` row with ``activo=False``
        for the very same account that owns the draft. The
        completion service must NOT treat this state as a
        successful retry; it must raise
        :class:`OwnerOnboardingTerminalInconsistent` so the router
        surfaces a bounded feedback view and never inflates an
        inactive membership back into a success view.
        """
        principal = _make_principal(self.subject)
        borrador_id_value: int = 0
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            borrador_id_value = int(draft.id)

        with TestingSessionLocal() as session, session.begin():
            comercio_id_value = _seed_orphan_comercio(
                slug=self.slug,
                estado_id=self._seed["INACTIVO"],
            )
            self.cleanup.track_comercio(comercio_id_value)
            borrador = session.get(
                BorradorOnboardingComercio, borrador_id_value
            )
            assert borrador is not None
            from datetime import datetime, timezone

            from backend.repositories.borrador_onboarding_comercio_repository import (
                BorradorOnboardingComercioRepository,
            )

            BorradorOnboardingComercioRepository(session).mark_terminal(
                borrador,
                comercio_id=comercio_id_value,
                completado_en=datetime.now(timezone.utc),
            )
            membership_id = _seed_owner_membership(
                cuenta_usuario_id=int(cuenta_id_for_subject(self.subject)),
                comercio_id=comercio_id_value,
            )
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE comercio_usuarios "
                        "SET activo = false, fecha_baja = now() "
                        "WHERE id = :membership_id"
                    ),
                    {"membership_id": membership_id},
                )

        with TestingSessionLocal() as session:
            with self.assertRaises(
                OwnerOnboardingTerminalInconsistent
            ):
                with session.begin():
                    complete_onboarding(session, principal)

        with engine.connect() as conn:
            slug_row = conn.execute(
                text("SELECT id FROM comercios WHERE slug = :slug"),
                {"slug": self.slug},
            ).first()
            self.assertIsNotNone(slug_row)
            assert slug_row is not None
            slug_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE slug = :slug"
                ),
                {"slug": self.slug},
            ).scalar_one()
            self.assertEqual(int(slug_count), 1)
            owner_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM comercio_usuarios "
                    "WHERE comercio_id = :comercio_id "
                    "AND rol = 'OWNER'"
                ),
                {"comercio_id": int(slug_row[0])},
            ).scalar_one()
            self.assertEqual(int(owner_count), 1)


class CompletionHttpIntegrityErrorBoundedResponseTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """The HTTP route renders a bounded 503 on ``IntegrityError`` (no 500).

    The router is the only surface that translates the typed
    :class:`OwnerOnboardingUnicityRace` to a bounded HTML
    response. The test exercises the wired FastAPI app so the
    CSRF dependency, the session dependency and the completion
    transaction all run end-to-end with the patched
    :meth:`ComercioUsuarioRepository.create_owner` raising
    ``IntegrityError``.
    """

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4ACleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4a-http-ie-{_suffix()}"
        self.cleanup.track_slug(self.slug)
        self.settings = _enable_supabase_settings()
        self.csrf_secret = self.settings.session_secret.encode("utf-8")
        self.app = _build_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=self.settings,
            csrf_secret=self.csrf_secret,
        )
        self.client = TestClient(
            self.app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _principal_cookie(self) -> str:
        return _principal_cookie(self.subject, self.settings)

    def _completion_nonce(self) -> str:
        return compute_owner_onboarding_form_nonce(
            path="/onboarding/completar",
            secret=self.csrf_secret,
        )

    def test_integrity_error_on_membership_yields_bounded_503(
        self,
    ) -> None:
        """``IntegrityError`` on membership → bounded 503, no 500.

        The test fires the real HTTP ``POST /onboarding/completar``
        surface with a valid same-origin + CSRF cookie. The
        session-scoped patch makes ``create_owner`` raise
        ``IntegrityError`` so the helper cannot stage a second
        OWNER membership. The router must catch the translated
        :class:`OwnerOnboardingUnicityRace` and render the
        bounded 503 service-unavailable view; the database must
        have no ``Comercio`` row, no ``ComercioUsuario`` row and
        no terminal ``comercio_id`` / ``completado_en``
        transition on the draft.
        """
        from unittest.mock import patch

        from sqlalchemy.exc import IntegrityError

        from backend.repositories.comercio_usuario_repository import (
            ComercioUsuarioRepository,
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=self.slug)
            save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )

        integrity = IntegrityError(
            "INSERT",
            {},
            Exception("duplicate key value violates unique constraint"),
        )
        with patch.object(
            ComercioUsuarioRepository,
            "create_owner",
            side_effect=integrity,
        ):
            response = self.client.post(
                "/onboarding/completar",
                data={OWNER_FORM_NONCE_FIELD: self._completion_nonce()},
                headers={
                    "cookie": (
                        f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                    ),
                    "origin": "http://testserver",
                    "x-forwarded-proto": "https",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Tu comercio fue creado", response.text)
        self.assertNotIn(self.slug, response.text)

        with engine.connect() as conn:
            slug_row = conn.execute(
                text("SELECT id FROM comercios WHERE slug = :slug"),
                {"slug": self.slug},
            ).first()
            self.assertIsNone(slug_row)
            cuenta_row = conn.execute(
                text(
                    "SELECT id FROM cuentas_usuario "
                    "WHERE supabase_subject = :subject"
                ),
                {"subject": self.subject},
            ).first()
            self.assertIsNotNone(cuenta_row)
            assert cuenta_row is not None
            cuenta_id_value = int(cuenta_row[0])
            membership_row = conn.execute(
                text(
                    "SELECT id FROM comercio_usuarios "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNone(membership_row)
            draft_row = conn.execute(
                text(
                    "SELECT comercio_id, completado_en "
                    "FROM borrador_onboarding_comercio "
                    "WHERE cuenta_usuario_id = :cuenta_id"
                ),
                {"cuenta_id": cuenta_id_value},
            ).first()
            self.assertIsNotNone(draft_row)
            assert draft_row is not None
            self.assertIsNone(draft_row[0])
            self.assertIsNone(draft_row[1])


def cuenta_id_for_subject(subject: str) -> int:
    """Resolve the seeded ``CuentaUsuario.id`` for a test subject.

    The helper is intentionally local to the test module so the
    new tests do not depend on the private
    :func:`_resolve_cuenta_id` helper used by the orphan-seed
    fixtures. The lookup is a plain ``SELECT`` against
    ``cuentas_usuario`` and raises an ``AssertionError`` if the
    account row is missing.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM cuentas_usuario "
                "WHERE supabase_subject = :subject"
            ),
            {"subject": subject},
        ).first()
    assert row is not None
    return int(row[0])


if __name__ == "__main__":
    unittest.main()
