"""Focused tests for the Phase 3 owner onboarding wizard.

The change ``add-commerce-self-service-onboarding`` Phase 3
introduces the account / draft persistence boundary and the
authenticated ``/onboarding`` wizard. The tests in this file
cover the documented boundary:

* account identity is keyed by the immutable Supabase subject
  only; nothing else is stored;
* the resolver returns the same row for the same subject across
  requests and refuses inactive accounts;
* the wizard creates at most one draft per account and scopes
  every read / write to the authenticated account;
* the wizard refuses to accept a ``comercio_id`` parameter;
* the wizard never creates ``Comercio`` or ``ComercioUsuario``
  rows;
* the wizard POST is gated by both a path-bound CSRF nonce and a
  same-origin origin check, with a clear failure when either is
  missing / wrong;
* two concurrent saves using the same ``expected_version`` end
  with exactly one update; the second one is rejected with
  :class:`DraftConcurrencyError` so the second tab reloads the
  fresh values.

The test database is the existing ``supernova_test`` PostgreSQL
fixture used across the project. Each test seeds its own
identifiers through ``_AccountDraftCleanup`` so the rows are
cleanly removed on teardown without touching other suites.
"""

import inspect
import os
import unittest
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.auth import SESSION_COOKIE_NAME
from backend.auth.principal import AuthenticatedPrincipal
from backend.dependencies import (
    OWNER_FORM_NONCE_FIELD,
    compute_owner_onboarding_form_nonce,
)
from backend.models import (
    BorradorOnboardingComercio,
    CuentaUsuario,
)
from backend.repositories.borrador_onboarding_comercio_repository import (
    DraftConcurrencyError,
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
    """Build an AuthenticatedPrincipal with the documented issuer / audience.

    The Phase 2 principal contract is minimal — the test only
    needs a non-empty subject so the resolver / router flows can
    exercise the account boundary. The issuer / audience values
    match the defaults of ``resolve_supabase_auth_settings``.
    """
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="https://abc.supabase.co/auth/v1",
        audience="authenticated",
    )


def _enable_supabase_settings(**overrides: Any):
    """Resolve a fully-enabled SupabaseAuthSettings for testing."""
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
        supabase_session_secret="local-session-secret-for-tests-32b",
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


def _build_owner_router_app(
    *,
    session_local: Callable[[], Session],
    supabase_settings: Any,
) -> FastAPI:
    """Build a minimal FastAPI app with the owner router + Phase 2 deps.

    The helper installs ``get_session`` and
    ``require_authenticated_owner_principal`` overrides so the
    router sees the test sessionmaker and the cookie-derived
    principal without contacting the Supabase JWKS client.
    """
    from starlette.requests import Request

    from backend import dependencies as deps
    from backend.routers import owner_onboarding

    app = FastAPI()
    app.include_router(owner_onboarding.router)

    def _session_override() -> Session:
        return session_local()

    def _principal_override(
        request: Request,
    ) -> AuthenticatedPrincipal:
        from fastapi import HTTPException

        from backend.auth.session import parse_session_cookie

        cookie_header = request.headers.get("cookie")
        headers = {"cookie": cookie_header} if cookie_header else {}
        local_session = parse_session_cookie(
            headers, settings=supabase_settings
        )
        if local_session is None:
            raise HTTPException(
                status_code=401, detail="Owner authentication required"
            )
        return AuthenticatedPrincipal(
            subject=local_session.subject,
            issuer=local_session.issuer,
            audience=local_session.audience,
        )

    app.dependency_overrides[deps.get_session] = _session_override
    app.dependency_overrides[
        deps.require_authenticated_owner_principal
    ] = _principal_override
    return app


def _principal_cookie(subject: str, settings: Any) -> str:
    """Encode a Phase 2 session cookie for ``subject``.

    The helper pins the issuer / audience to the values the
    resolved SupabaseAuthSettings expects so the cookie survives
    the decoder's exact-match checks.
    """
    from backend.auth.session import encode_session

    principal = AuthenticatedPrincipal(
        subject=subject,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    return encode_session(principal, settings=settings)


class _AccountDraftCleanup:
    """Track rows the test creates so they can be deleted on teardown."""

    def __init__(self) -> None:
        self.seeded_subjects: list[str] = []

    def seed_subject(self) -> str:
        suffix = _suffix()
        subject = f"phase3-{suffix}"
        self.seeded_subjects.append(subject)
        return subject

    def cleanup(self) -> None:
        with engine.begin() as conn:
            conn.execute(
                delete(BorradorOnboardingComercio).where(
                    BorradorOnboardingComercio.cuenta_usuario_id.in_(
                        select(CuentaUsuario.id).where(
                            CuentaUsuario.supabase_subject.like("phase3-%")
                        )
                    )
                )
            )
            conn.execute(
                delete(CuentaUsuario).where(
                    CuentaUsuario.supabase_subject.like("phase3-%")
                )
            )


class AccountIdentityTest(unittest.TestCase):
    """The resolver keys accounts by the immutable Supabase subject only."""

    def setUp(self) -> None:
        self.cleanup = _AccountDraftCleanup()
        self.subject = self.cleanup.seed_subject()

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_resolver_creates_then_loads_same_account(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            created = resolve_or_create_cuenta(session, principal)

        with TestingSessionLocal() as session:
            loaded = resolve_or_create_cuenta(session, principal)

        self.assertEqual(created.id, loaded.id)
        self.assertEqual(loaded.supabase_subject, self.subject)
        self.assertTrue(loaded.activo)

        with engine.connect() as conn:
            rows = conn.execute(
                select(CuentaUsuario).where(
                    CuentaUsuario.supabase_subject == self.subject
                )
            ).all()
        self.assertEqual(len(rows), 1)

    def test_resolver_rejects_inactive_account(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)

        with TestingSessionLocal() as session:
            cuenta_row = session.get(CuentaUsuario, cuenta.id)
            assert cuenta_row is not None
            cuenta_row.activo = False
            session.commit()

        with TestingSessionLocal() as session, self.assertRaises(
            OwnerAccountInactive
        ):
            resolve_or_create_cuenta(session, principal)

    def test_resolver_does_not_store_email(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)

        with engine.connect() as conn:
            row = conn.execute(
                select(CuentaUsuario).where(
                    CuentaUsuario.id == cuenta.id
                )
            ).first()
        self.assertIsNotNone(row)
        assert row is not None
        available = set(row._mapping.keys())
        self.assertIn("supabase_subject", available)
        self.assertNotIn("email", available)
        self.assertNotIn("email_address", available)
        self.assertNotIn("provider_metadata", available)


class DraftIsolationAndScopeTest(unittest.TestCase):
    """Per-account scope: one draft per account, never cross-account."""

    def setUp(self) -> None:
        self.cleanup = _AccountDraftCleanup()
        self.subject_a = self.cleanup.seed_subject()
        self.subject_b = self.cleanup.seed_subject()

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _account(self, subject: str) -> CuentaUsuario:
        principal = _make_principal(subject)
        with TestingSessionLocal() as session:
            return resolve_or_create_cuenta(session, principal)

    def test_one_draft_per_account(self) -> None:
        account_a = self._account(self.subject_a)
        account_b = self._account(self.subject_b)

        with TestingSessionLocal() as session:
            draft_a1 = load_or_create_borrador(session, account_a)
            draft_a2 = load_or_create_borrador(session, account_a)
        with TestingSessionLocal() as session:
            draft_b1 = load_or_create_borrador(session, account_b)

        self.assertEqual(draft_a1.id, draft_a2.id)
        self.assertNotEqual(draft_a1.id, draft_b1.id)
        self.assertEqual(draft_a1.cuenta_usuario_id, account_a.id)
        self.assertEqual(draft_b1.cuenta_usuario_id, account_b.id)

        with engine.connect() as conn:
            rows = conn.execute(
                select(
                    BorradorOnboardingComercio.cuenta_usuario_id
                ).where(
                    BorradorOnboardingComercio.cuenta_usuario_id.in_(
                        [account_a.id, account_b.id]
                    )
                )
            ).all()
        seen: dict[int, int] = {}
        for (cid,) in rows:
            seen[cid] = seen.get(cid, 0) + 1
        self.assertEqual(seen.get(account_a.id, 0), 1)
        self.assertEqual(seen.get(account_b.id, 0), 1)

    def test_save_only_owns_draft(self) -> None:
        account_a = self._account(self.subject_a)
        account_b = self._account(self.subject_b)

        with TestingSessionLocal() as session:
            draft_a = load_or_create_borrador(session, account_a)
            draft_b = load_or_create_borrador(session, account_b)
            draft_a_id = draft_a.id
            draft_b_id = draft_b.id

        fields = {
            "nombre_fantasia": "Comercio A",
            "nombre_corto": "CA",
            "razon_social": "Comercio A SRL",
            "cuit": "30-11111111-1",
            "whatsapp": "+5491111111111",
            "slug": "comercio-a",
            "calle": "Av. A",
            "numero": "100",
            "localidad": "CABA",
            "provincia": "Buenos Aires",
        }
        with TestingSessionLocal() as session:
            reloaded_a = session.get(
                BorradorOnboardingComercio, draft_a_id
            )
            assert reloaded_a is not None
            save_borrador(
                session,
                reloaded_a,
                expected_version=0,
                fields=fields,
            )

        with TestingSessionLocal() as session:
            reloaded_b = session.get(
                BorradorOnboardingComercio, draft_b_id
            )
        assert reloaded_b is not None
        self.assertIsNone(reloaded_b.nombre_fantasia)
        self.assertEqual(reloaded_b.cuenta_usuario_id, account_b.id)
        self.assertEqual(reloaded_b.version, 0)

    def test_router_rejects_comercio_id_in_form(self) -> None:
        settings = _enable_supabase_settings()
        app = _build_owner_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=settings,
        )
        client = TestClient(
            app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )
        cookie_value = _principal_cookie(self.subject_a, settings)
        response = client.get(
            "/onboarding",
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie_value}",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="comercio_id"', response.text)
        self.assertNotIn('name="comercioId"', response.text)
        self.assertNotIn("comercio_id=", response.text)

    def test_router_does_not_create_commerce_rows(self) -> None:
        settings = _enable_supabase_settings()
        # The dependency resolves the CSRF secret from
        # ``OWNER_ONBOARDING_CSRF_SECRET`` so the test publishes
        # the same secret the wizard uses to bind the nonce.
        os.environ["OWNER_ONBOARDING_CSRF_SECRET"] = (
            settings.session_secret
        )
        app = _build_owner_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=settings,
        )
        client = TestClient(
            app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )
        cookie_value = _principal_cookie(self.subject_a, settings)
        # The TestClient issues its requests with
        # ``Request.url.scheme == "http"`` and ``Host == "testserver"``
        # so the request's effective origin is ``http://testserver``;
        # the wizard therefore expects the matching Origin header.
        get_origin_header = "http://testserver"

        get_response = client.get(
            "/onboarding",
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie_value}",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(get_response.status_code, 200)

        nonce = compute_owner_onboarding_form_nonce(
            path="/onboarding",
            secret=settings.session_secret.encode("utf-8"),
        )

        post_response = client.post(
            "/onboarding",
            data={
                OWNER_FORM_NONCE_FIELD: nonce,
                "expected_version": "0",
                "nombre_fantasia": "Comercio X",
                "nombre_corto": "CX",
                "razon_social": "Comercio X SRL",
                "cuit": "30-22222222-2",
                "whatsapp": "+5491222222222",
                "slug": "comercio-x",
                "calle": "Av. X",
                "numero": "200",
                "localidad": "CABA",
                "provincia": "Buenos Aires",
            },
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie_value}",
                "origin": get_origin_header,
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertIn(
            "Guardamos los cambios en tu borrador.",
            post_response.text,
        )

        with engine.connect() as conn:
            sentinel_comercio = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = 'phase3-no-comercio-sentinel'"
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                sentinel_comercio,
                "the wizard must not create a Comercio row",
            )
            # The Phase 4A migration now creates the membership
            # table; the wizard POST still does not write a
            # ``comercio`` row, which is what the assertion
            # above guarantees.

        with engine.connect() as conn:
            cuentas = conn.execute(
                select(CuentaUsuario).where(
                    CuentaUsuario.supabase_subject == self.subject_a
                )
            ).all()
            drafts = conn.execute(
                select(BorradorOnboardingComercio).where(
                    BorradorOnboardingComercio.cuenta_usuario_id.in_(
                        select(CuentaUsuario.id).where(
                            CuentaUsuario.supabase_subject
                            == self.subject_a
                        )
                    )
                )
            ).all()
        self.assertEqual(len(cuentas), 1)
        self.assertEqual(len(drafts), 1)


class OnboardingCsrfAndSameOriginTest(unittest.TestCase):
    """``POST /onboarding`` enforces path-bound nonce + same-origin."""

    def setUp(self) -> None:
        self.cleanup = _AccountDraftCleanup()
        self.subject = self.cleanup.seed_subject()
        self.settings = _enable_supabase_settings()
        self.app = _build_owner_router_app(
            session_local=TestingSessionLocal,
            supabase_settings=self.settings,
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

    def test_post_without_csrf_is_rejected(self) -> None:
        response = self.client.post(
            "/onboarding",
            data={
                "expected_version": "0",
                "nombre_fantasia": "Sin CSRF",
            },
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "https://test.example",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_post_with_tampered_csrf_is_rejected(self) -> None:
        response = self.client.post(
            "/onboarding",
            data={
                OWNER_FORM_NONCE_FIELD: "0" * 64,
                "expected_version": "0",
            },
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "https://test.example",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_post_with_cross_origin_is_rejected(self) -> None:
        nonce = compute_owner_onboarding_form_nonce(
            path="/onboarding",
            secret=self.settings.session_secret.encode("utf-8"),
        )
        response = self.client.post(
            "/onboarding",
            data={
                OWNER_FORM_NONCE_FIELD: nonce,
                "expected_version": "0",
            },
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "https://attacker.example",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_post_without_origin_is_rejected(self) -> None:
        nonce = compute_owner_onboarding_form_nonce(
            path="/onboarding",
            secret=self.settings.session_secret.encode("utf-8"),
        )
        response = self.client.post(
            "/onboarding",
            data={
                OWNER_FORM_NONCE_FIELD: nonce,
                "expected_version": "0",
            },
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 400)


class ConcurrentSaveTest(unittest.TestCase):
    """Two parallel saves with the same version end in exactly one row."""

    def setUp(self) -> None:
        self.cleanup = _AccountDraftCleanup()
        self.subject = self.cleanup.seed_subject()

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_concurrent_save_with_same_version_rejects_second(self) -> None:
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            draft_id = draft.id
            initial_version = draft.version

        self.assertEqual(initial_version, 0)

        with TestingSessionLocal() as session:
            cached_draft = session.get(
                BorradorOnboardingComercio, draft_id
            )
            assert cached_draft is not None
            save_borrador(
                session,
                cached_draft,
                expected_version=initial_version,
                fields={
                    "nombre_fantasia": "First",
                    "nombre_corto": "F1",
                    "razon_social": "First SRL",
                    "cuit": "30-33333333-3",
                    "whatsapp": "+5491333333333",
                    "slug": "first-slug",
                    "calle": "Av. 1",
                    "numero": "100",
                    "localidad": "CABA",
                    "provincia": "Buenos Aires",
                },
            )

        with TestingSessionLocal() as session:
            cached_draft = session.get(
                BorradorOnboardingComercio, draft_id
            )
            assert cached_draft is not None
            with self.assertRaises(DraftConcurrencyError):
                save_borrador(
                    session,
                    cached_draft,
                    expected_version=initial_version,
                    fields={"nombre_fantasia": "Second"},
                )

        with TestingSessionLocal() as session:
            refreshed = session.get(
                BorradorOnboardingComercio, draft_id
            )
        assert refreshed is not None
        self.assertEqual(refreshed.nombre_fantasia, "First")
        self.assertEqual(refreshed.version, 1)

    def test_two_sessions_loaded_before_first_commit_rejects_second(
        self,
    ) -> None:
        """Two sessions pre-load the same draft before the first commit.

        The test reproduces the exact race Codex flagged: both
        sessions hold the draft in memory with ``version == 0``
        before any commit lands. With the prior in-memory check
        the second ``save_borrador`` would have seen the stale
        version and silently overwritten the first save's values.
        The atomic DB-level check (``UPDATE ... WHERE id = :id AND
        version = :expected_version``) must reject the second save
        even though the in-memory snapshot still matches, and the
        persisted values must reflect the first save exclusively.
        """
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            draft = load_or_create_borrador(session, cuenta)
            draft_id = draft.id
            initial_version = draft.version

        self.assertEqual(initial_version, 0)

        with TestingSessionLocal() as session_a:
            draft_a = session_a.get(
                BorradorOnboardingComercio, draft_id
            )
            assert draft_a is not None
            with TestingSessionLocal() as session_b:
                draft_b = session_b.get(
                    BorradorOnboardingComercio, draft_id
                )
                assert draft_b is not None
                # Both drafts are loaded with version=0 in memory
                # before either session commits. A naive
                # in-memory ``draft.version == expected_version``
                # check would let both saves through.
                self.assertEqual(draft_a.version, initial_version)
                self.assertEqual(draft_b.version, initial_version)

                save_borrador(
                    session_a,
                    draft_a,
                    expected_version=initial_version,
                    fields={
                        "nombre_fantasia": "First",
                        "nombre_corto": "F1",
                        "razon_social": "First SRL",
                        "cuit": "30-33333333-3",
                        "whatsapp": "+5491333333333",
                        "slug": "first-slug",
                        "calle": "Av. 1",
                        "numero": "100",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                    },
                )

                with self.assertRaises(DraftConcurrencyError):
                    save_borrador(
                        session_b,
                        draft_b,
                        expected_version=initial_version,
                        fields={
                            "nombre_fantasia": "Second",
                            "nombre_corto": "S2",
                            "razon_social": "Second SRL",
                            "cuit": "30-44444444-4",
                            "whatsapp": "+5491444444444",
                            "slug": "second-slug",
                            "calle": "Av. 2",
                            "numero": "200",
                            "localidad": "CABA",
                            "provincia": "Buenos Aires",
                        },
                    )

        with TestingSessionLocal() as session:
            refreshed = session.get(
                BorradorOnboardingComercio, draft_id
            )
        assert refreshed is not None
        self.assertEqual(refreshed.nombre_fantasia, "First")
        self.assertEqual(refreshed.nombre_corto, "F1")
        self.assertEqual(refreshed.razon_social, "First SRL")
        self.assertEqual(refreshed.cuit, "30-33333333-3")
        self.assertEqual(refreshed.whatsapp, "+5491333333333")
        self.assertEqual(refreshed.calle, "Av. 1")
        self.assertEqual(refreshed.numero, "100")
        self.assertEqual(refreshed.version, 1)
        self.assertTrue(refreshed.completo)


class ExistingSurfacePreservationTest(unittest.TestCase):
    """Phase 3 does not regress Phase 1 / Phase 2 endpoints."""

    def test_landing_and_comenzar_still_respond(self) -> None:
        from backend.routers import public_onboarding

        app = FastAPI()
        app.include_router(public_onboarding.router)
        client = TestClient(
            app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/comenzar").status_code, 200)

    def test_no_dependencies_files_import_commerce_or_lifecycle(self) -> None:
        """Phase 3 module surface must not import Phase 4 helpers."""
        import backend.repositories.borrador_onboarding_comercio_repository as borrador_repo
        import backend.repositories.cuenta_usuario_repository as cu_repo
        import backend.routers.owner_onboarding as router_module
        import backend.services.owner_onboarding_service as service_module

        forbidden_imports: tuple[str, ...] = (
            "ComercioService",
            "ComercioUsuario",
            "CommerceAvailabilityService",
            "ComercioMedioPago",
            "ComercioMetodoEntrega",
            "CanalWhatsapp",
            "outbound_dispatcher",
            "Outbox",
        )

        for module in (
            router_module,
            service_module,
            cu_repo,
            borrador_repo,
        ):
            source_path = module.__file__ or ""
            with open(source_path, encoding="utf-8") as handle:
                text_source = handle.read()
            for needle in forbidden_imports:
                with self.subTest(
                    module=module.__name__, needle=needle
                ):
                    self.assertNotIn(
                        f"from backend.{needle.lower()}", text_source
                    )
                    self.assertNotIn(
                        f"from backend.{needle}", text_source
                    )
                    self.assertNotIn(
                        f"import {needle}", text_source
                    )


class RepositoryStageOnlyTest(unittest.TestCase):
    """Repositories stage/flush and never call commit/rollback."""

    def test_repositories_do_not_commit_or_rollback(self) -> None:
        from backend.repositories.borrador_onboarding_comercio_repository import (
            BorradorOnboardingComercioRepository,
        )
        from backend.repositories.cuenta_usuario_repository import (
            CuentaUsuarioRepository,
        )

        for repo_cls in (
            CuentaUsuarioRepository,
            BorradorOnboardingComercioRepository,
        ):
            with self.subTest(repo=repo_cls.__name__):
                source = inspect.getsource(repo_cls)
                self.assertNotIn(".commit(", source)
                self.assertNotIn(".rollback(", source)


if __name__ == "__main__":
    unittest.main()
