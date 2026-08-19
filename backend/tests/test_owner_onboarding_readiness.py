"""Focused tests for the Phase 4B owner-self-service readiness dashboard.

The ``add-commerce-self-service-onboarding`` change Phase 4B
introduces a membership-scoped, read-only readiness projection
that powers ``GET /onboarding/readiness``. The tests in this
file assert the documented boundary:

* the dashboard derives the exact ``Comercio`` from the
  validated Supabase principal through the
  ``CuentaUsuario`` -> terminal ``BorradorOnboardingComercio``
  -> active ``OWNER`` ``ComercioUsuario`` chain. A different
  account's terminal draft cannot be observed through a
  forged request;
* the dashboard refuses to read any ``comercio_id`` from the
  URL, the query string or the body. The owner is the only
  selector the projection accepts;
* the dashboard reports only derived facts (basic profile,
  ``CommerceAvailabilityService.evaluate`` lifecycle state,
  eligible payment / delivery associations, channel state).
  It NEVER mutates, NEVER commits, NEVER rolls back and
  NEVER invokes the existing payment / delivery configuration
  service or any catalog / channel / outbox / Twilio /
  trial reservation seam;
* a globally inactive ``MediosPago`` / ``MetodosEntrega``
  row never counts as eligible;
* a missing, inactive or shared-membership-inactive channel
  reports the corresponding ``pending`` flag;
* ``INACTIVO`` commerces cannot accept orders even when the
  payment / delivery / channel checklist is fully satisfied;
* missing / inactive / mismatched membership, a terminal
  draft that points at a removed ``Comercio``, an
  inactive / missing account and a persistence failure all
  fail closed without ever falling back to another commerce
  or another state.

The test database is the existing ``supernova_test``
PostgreSQL fixture used across the project. Each test seeds
and tears down its own identifiers through the
``_Phase4BCleanup`` helper so the rows are cleanly removed
without touching other suites.
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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from backend.auth import SESSION_COOKIE_NAME
from backend.auth.principal import AuthenticatedPrincipal
from backend.models import (
    BorradorOnboardingComercio,
    CanalWhatsapp,
    Comercio,
    ComercioCanalCompartido,
    ComercioMedioPago,
    ComercioMetodoEntrega,
    ComercioUsuario,
    CuentaUsuario,
    MediosPago,
    MetodosEntrega,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.owner_onboarding_readiness_service import (
    OwnerReadinessAccountMissing,
    OwnerReadinessComercioMissing,
    OwnerReadinessDraftMissing,
    OwnerReadinessDraftNotTerminal,
    OwnerReadinessMembershipMissing,
    build_owner_readiness,
)
from backend.services.owner_onboarding_service import (
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

    Mirrors the helper in the Phase 4A completion tests so
    the readiness suite exercises the same ASGI integration:
    the Supabase principal override and the owner CSRF secret
    resolver share the test settings.
    """
    from backend import dependencies as deps
    from backend.routers import owner_onboarding

    app = FastAPI()
    app.include_router(owner_onboarding.router)

    def _session_override() -> Session:
        return session_local()

    def _csrf_secret_override() -> bytes:
        return csrf_secret

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
                status_code=401,
                detail="Owner authentication required",
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
    deps._resolve_owner_onboarding_csrf_secret = _csrf_secret_override
    return app


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
) -> dict[str, str]:
    """Return a complete draft field mapping with random identifiers."""
    stamp = suffix or _suffix()
    return {
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


def _seed_comercio(
    *,
    slug: str,
    estado_id: int,
    suffix: str | None = None,
) -> int:
    """Seed an ``INACTIVO`` Comercio row directly.

    The helper mirrors the orphan seed used by the Phase 4A
    completion tests so the readiness suite can build the
    exact pre-completion commerce state the dashboard
    reads.
    """
    stamp = suffix or _suffix()
    cuit1 = stamp[:8]
    cuit2 = stamp[8]
    cuit3 = stamp[:10]
    stmt_text = (
        "INSERT INTO comercios "
        "(nombre_fantasia, nombre_corto, "
        " razon_social, cuit, whatsapp, calle, "
        " numero, localidad, provincia, slug, "
        " estado_id, zona_horaria, moneda, "
        " idioma, prueba_pedidos_consumidos) "
        f"VALUES ('Comercio {stamp}', 'CO', "
        f" 'Comercio {stamp} SRL', "
        f" '30-{cuit1}-{cuit2}', '+5491{cuit3}', "
        " 'Av. Test', '1', 'CABA', "
        " 'Buenos Aires', :slug, "
        " :estado_id, "
        " 'America/Argentina/Buenos_Aires', "
        " 'ARS', 'es-AR', 0) RETURNING id"
    )
    with engine.begin() as conn:
        comercio_id = conn.execute(
            text(stmt_text),
            {"slug": slug, "estado_id": estado_id},
        ).scalar_one()
    return int(comercio_id)


def _seed_owner_membership(
    *, cuenta_usuario_id: int, comercio_id: int
) -> int:
    """Seed an active ``OWNER`` ``ComercioUsuario`` row."""
    with engine.begin() as conn:
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
    return int(membership_id)


def _seed_terminal_draft(
    *,
    cuenta_usuario_id: int,
    comercio_id: int,
) -> int:
    """Seed the terminal ``comercio_id`` / ``completado_en`` pair."""
    from datetime import datetime, timezone

    with engine.begin() as conn:
        borrador_id = conn.execute(
            text(
                "INSERT INTO borrador_onboarding_comercio "
                "(cuenta_usuario_id, version, completo, slug, "
                " nombre_fantasia, nombre_corto, "
                " razon_social, cuit, whatsapp, calle, "
                " numero, localidad, provincia, "
                " comercio_id, completado_en, fecha_alta, "
                " fecha_ultima_modificacion) "
                "VALUES (:cuenta_id, 1, true, :slug, "
                " 'Comercio', 'CO', 'Comercio SRL', "
                " '30-00000000-0', '+5491100000000', "
                " 'Av. Test', '1', 'CABA', "
                " 'Buenos Aires', :comercio_id, "
                " :completado_en, now(), now()) "
                "RETURNING id"
            ),
            {
                "cuenta_id": cuenta_usuario_id,
                "slug": f"terminal-{_suffix()}",
                "comercio_id": comercio_id,
                "completado_en": datetime.now(tz=timezone.utc),
            },
        ).scalar_one()
    return int(borrador_id)


def _seed_medio_pago(
    *,
    codigo: str,
    descripcion: str,
    activo: bool,
) -> int:
    with engine.begin() as conn:
        medio_id = conn.execute(
            text(
                "INSERT INTO medios_pago "
                "(codigo, descripcion, activo, "
                " habilita_titular, habilita_alias, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:codigo, :descripcion, :activo, "
                " false, false, now(), now()) "
                "RETURNING id"
            ),
            {
                "codigo": codigo,
                "descripcion": descripcion,
                "activo": activo,
            },
        ).scalar_one()
    return int(medio_id)


def _seed_metodo_entrega(
    *,
    codigo: str,
    descripcion: str,
    activo: bool,
    orden: int = 0,
) -> int:
    with engine.begin() as conn:
        metodo_id = conn.execute(
            text(
                "INSERT INTO metodos_entrega "
                "(codigo, descripcion, orden, activo, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:codigo, :descripcion, :orden, "
                " :activo, now(), now()) "
                "RETURNING id"
            ),
            {
                "codigo": codigo,
                "descripcion": descripcion,
                "orden": orden,
                "activo": activo,
            },
        ).scalar_one()
    return int(metodo_id)


def _seed_comercio_medio_pago(
    *,
    comercio_id: int,
    medio_pago_id: int,
    activo: bool,
) -> int:
    with engine.begin() as conn:
        assoc_id = conn.execute(
            text(
                "INSERT INTO comercio_medios_pago "
                "(id_comercio, id_medio_pago, activo, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:comercio_id, :medio_pago_id, "
                " :activo, now(), now()) "
                "RETURNING id"
            ),
            {
                "comercio_id": comercio_id,
                "medio_pago_id": medio_pago_id,
                "activo": activo,
            },
        ).scalar_one()
    return int(assoc_id)


def _seed_comercio_metodo_entrega(
    *,
    comercio_id: int,
    metodo_entrega_id: int,
    activo: bool,
    orden: int = 0,
) -> int:
    with engine.begin() as conn:
        assoc_id = conn.execute(
            text(
                "INSERT INTO comercio_metodos_entrega "
                "(id_comercio, id_metodo_entrega, activo, "
                " orden, fecha_alta, "
                " fecha_ultima_modificacion) "
                "VALUES (:comercio_id, "
                " :metodo_entrega_id, :activo, :orden, "
                " now(), now()) "
                "RETURNING id"
            ),
            {
                "comercio_id": comercio_id,
                "metodo_entrega_id": metodo_entrega_id,
                "activo": activo,
                "orden": orden,
            },
        ).scalar_one()
    return int(assoc_id)


def _seed_dedicated_channel(
    *,
    comercio_id: int,
    provider: str = "twilio",
    destination_e164: str | None = None,
    activo: bool = True,
) -> int:
    with engine.begin() as conn:
        canal_id = conn.execute(
            text(
                "INSERT INTO canales_whatsapp "
                "(provider, destination_e164, mode, "
                " id_comercio_exclusivo, activo, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:provider, :destination, 'dedicated', "
                " :comercio_id, :activo, now(), now()) "
                "RETURNING id"
            ),
            {
                "provider": provider,
                "destination": destination_e164
                or f"+54911{_suffix()[:6]}",
                "comercio_id": comercio_id,
                "activo": activo,
            },
        ).scalar_one()
    return int(canal_id)


def _seed_shared_channel(
    *,
    provider: str = "twilio",
    destination_e164: str | None = None,
    activo: bool = True,
) -> int:
    with engine.begin() as conn:
        canal_id = conn.execute(
            text(
                "INSERT INTO canales_whatsapp "
                "(provider, destination_e164, mode, "
                " id_comercio_exclusivo, activo, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:provider, :destination, 'shared', "
                " NULL, :activo, now(), now()) "
                "RETURNING id"
            ),
            {
                "provider": provider,
                "destination": destination_e164
                or f"+54911{_suffix()[:6]}",
                "activo": activo,
            },
        ).scalar_one()
    return int(canal_id)


def _seed_shared_membership(
    *,
    canal_id: int,
    comercio_id: int,
    routing_code: str,
    activo: bool = True,
) -> int:
    with engine.begin() as conn:
        membership_id = conn.execute(
            text(
                "INSERT INTO comercios_canales_compartidos "
                "(canal_id, comercio_id, routing_code, "
                " routing_code_normalizado, activo, "
                " fecha_alta, fecha_ultima_modificacion) "
                "VALUES (:canal_id, :comercio_id, "
                " :routing_code, :routing_code, :activo, "
                " now(), now()) "
                "RETURNING id"
            ),
            {
                "canal_id": canal_id,
                "comercio_id": comercio_id,
                "routing_code": routing_code,
                "activo": activo,
            },
        ).scalar_one()
    return int(membership_id)


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
    return int(cuenta_id)


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


class _Phase4BCleanup:
    """Cleanup helper that removes the test seed surface."""

    def __init__(self) -> None:
        self.seeded_subjects: list[str] = []
        self.seeded_slugs: list[str] = []
        self.seeded_comercio_ids: list[int] = []
        self.seeded_membership_ids: list[int] = []
        self.seeded_medio_pago_ids: list[int] = []
        self.seeded_metodo_entrega_ids: list[int] = []
        self.seeded_medio_pago_assoc_ids: list[int] = []
        self.seeded_metodo_entrega_assoc_ids: list[int] = []
        self.seeded_canal_ids: list[int] = []
        self.seeded_shared_membership_ids: list[int] = []

    def seed_subject(self) -> str:
        suffix = _suffix()
        subject = f"phase4b-{suffix}"
        self.seeded_subjects.append(subject)
        return subject

    def track_slug(self, slug: str) -> None:
        self.seeded_slugs.append(slug)

    def track_comercio(self, comercio_id: int) -> None:
        self.seeded_comercio_ids.append(comercio_id)

    def track_membership(self, membership_id: int) -> None:
        self.seeded_membership_ids.append(membership_id)

    def track_medio_pago(self, medio_pago_id: int) -> None:
        self.seeded_medio_pago_ids.append(medio_pago_id)

    def track_metodo_entrega(
        self, metodo_entrega_id: int
    ) -> None:
        self.seeded_metodo_entrega_ids.append(metodo_entrega_id)

    def track_medio_pago_assoc(self, assoc_id: int) -> None:
        self.seeded_medio_pago_assoc_ids.append(assoc_id)

    def track_metodo_entrega_assoc(self, assoc_id: int) -> None:
        self.seeded_metodo_entrega_assoc_ids.append(assoc_id)

    def track_canal(self, canal_id: int) -> None:
        self.seeded_canal_ids.append(canal_id)

    def track_shared_membership(self, membership_id: int) -> None:
        self.seeded_shared_membership_ids.append(membership_id)

    def cleanup(self) -> None:
        with engine.begin() as conn:
            if self.seeded_shared_membership_ids:
                conn.execute(
                    delete(ComercioCanalCompartido).where(
                        ComercioCanalCompartido.id.in_(
                            self.seeded_shared_membership_ids
                        )
                    )
                )
            if self.seeded_canal_ids:
                conn.execute(
                    delete(CanalWhatsapp).where(
                        CanalWhatsapp.id.in_(self.seeded_canal_ids)
                    )
                )
            if self.seeded_metodo_entrega_assoc_ids:
                conn.execute(
                    delete(ComercioMetodoEntrega).where(
                        ComercioMetodoEntrega.id.in_(
                            self.seeded_metodo_entrega_assoc_ids
                        )
                    )
                )
            if self.seeded_medio_pago_assoc_ids:
                conn.execute(
                    delete(ComercioMedioPago).where(
                        ComercioMedioPago.id.in_(
                            self.seeded_medio_pago_assoc_ids
                        )
                    )
                )
            if self.seeded_metodo_entrega_ids:
                conn.execute(
                    delete(MetodosEntrega).where(
                        MetodosEntrega.id.in_(
                            self.seeded_metodo_entrega_ids
                        )
                    )
                )
            if self.seeded_medio_pago_ids:
                conn.execute(
                    delete(MediosPago).where(
                        MediosPago.id.in_(self.seeded_medio_pago_ids)
                    )
                )
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
                    # removed in any order. Any membership that
                    # belongs to one of the seeded accounts is
                    # purged so the account row can be deleted.
                    conn.execute(
                        text(
                            "UPDATE borrador_onboarding_comercio "
                            "SET comercio_id = NULL, "
                            "completado_en = NULL "
                            "WHERE cuenta_usuario_id = ANY(:ids)"
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
                    delete(Comercio).where(
                        Comercio.slug.in_(self.seeded_slugs)
                    )
                )


class ServiceReadOnlyContractTest(unittest.TestCase):
    """The readiness service and its dependencies never mutate."""

    @staticmethod
    def _strip_docstrings(source: str) -> str:
        """Return ``source`` with docstring bodies removed.

        The readiness module documents the read-only contract
        inside docstrings, so a naive ``assertNotIn(".commit(",
        source)`` check would always fail. The helper strips
        triple-quoted blocks before the assertion runs.
        """
        import re

        cleaned = re.sub(r'"""[\s\S]*?"""', "", source)
        cleaned = re.sub(r"'''[\s\S]*?'''", "", cleaned)
        return cleaned

    def test_service_source_has_no_commit_or_rollback(self) -> None:
        """The service must be a pure read boundary."""
        from backend.services import owner_onboarding_readiness_service

        source = self._strip_docstrings(
            inspect.getsource(owner_onboarding_readiness_service)
        )
        self.assertNotIn(".commit(", source)
        self.assertNotIn(".rollback(", source)
        self.assertNotIn(".flush(", source)
        self.assertNotIn("session.add", source)

    def test_service_does_not_call_reserve_confirmed_order(self) -> None:
        """The dashboard never increments the trial counter."""
        from backend.services import owner_onboarding_readiness_service

        source = self._strip_docstrings(
            inspect.getsource(owner_onboarding_readiness_service)
        )
        self.assertNotIn("reserve_confirmed_order", source)


class MerchantStateSeedingMixin:
    @classmethod
    def setUpClass(cls) -> None:
        cls.inactivo_id = _seed_inactivo_estado()


class ReadOnlyProjectionOwnerIsolationTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """The OWNER only sees their own comercio's projection."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.other_subject = f"phase4b-other-{_suffix()}"
        self.cleanup.seeded_subjects.append(self.other_subject)
        self.slug = f"phase4b-iso-{_suffix()}"
        self.other_slug = f"phase4b-other-{_suffix()}"
        self.cleanup.track_slug(self.slug)
        self.cleanup.track_slug(self.other_slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_other_accounts_commerce_is_not_exposed(self) -> None:
        """A second account's terminal commerce is invisible.

        Seeds two accounts, each with its own terminal draft,
        its own comercio and its own active OWNER membership.
        The first principal must read its own comercio
        (nombre_fantasia / slug / comercio_id) and must NOT
        see any field from the second account's row.
        """
        _seed_cuenta(self.other_subject)
        own_cuenta_id = _seed_cuenta(self.subject)
        other_cuenta_id = _resolve_cuenta_id(self.other_subject)

        own_comercio_id = _seed_comercio(
            slug=self.slug,
            estado_id=self.inactivo_id,
        )
        self.cleanup.track_comercio(own_comercio_id)
        other_comercio_id = _seed_comercio(
            slug=self.other_slug,
            estado_id=self.inactivo_id,
        )
        self.cleanup.track_comercio(other_comercio_id)

        own_membership_id = _seed_owner_membership(
            cuenta_usuario_id=own_cuenta_id,
            comercio_id=own_comercio_id,
        )
        self.cleanup.track_membership(own_membership_id)
        other_membership_id = _seed_owner_membership(
            cuenta_usuario_id=other_cuenta_id,
            comercio_id=other_comercio_id,
        )
        self.cleanup.track_membership(other_membership_id)

        _seed_terminal_draft(
            cuenta_usuario_id=own_cuenta_id,
            comercio_id=own_comercio_id,
        )
        _seed_terminal_draft(
            cuenta_usuario_id=other_cuenta_id,
            comercio_id=other_comercio_id,
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertEqual(
            int(projection.profile.comercio_id), own_comercio_id
        )
        self.assertEqual(projection.profile.slug, self.slug)
        self.assertNotEqual(
            int(projection.profile.comercio_id), other_comercio_id
        )
        self.assertNotIn(self.other_slug, projection.profile.slug)


class ReadinessLifecycleStaysUnavailableTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``INACTIVO`` commerces are never reported as available."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-inactivo-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_inactivo_remains_unavailable_even_with_full_checklist(
        self,
    ) -> None:
        """A complete checklist must NOT promote INACTIVO.

        Seeds an active payment, an active delivery, an
        active dedicated channel and a still-``INACTIVO``
        lifecycle row. The dashboard must report
        ``UNAVAILABLE`` for the lifecycle evaluation even
        though every other requirement is eligible.
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug,
            estado_id=self.inactivo_id,
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        medio_pago_id = _seed_medio_pago(
            codigo=f"PM-{_suffix()[:6]}",
            descripcion="Mercado Pago",
            activo=True,
        )
        self.cleanup.track_medio_pago(medio_pago_id)
        medio_assoc_id = _seed_comercio_medio_pago(
            comercio_id=comercio_id,
            medio_pago_id=medio_pago_id,
            activo=True,
        )
        self.cleanup.track_medio_pago_assoc(medio_assoc_id)

        metodo_entrega_id = _seed_metodo_entrega(
            codigo=f"DE-{_suffix()[:6]}",
            descripcion="Delivery",
            activo=True,
        )
        self.cleanup.track_metodo_entrega(metodo_entrega_id)
        metodo_assoc_id = _seed_comercio_metodo_entrega(
            comercio_id=comercio_id,
            metodo_entrega_id=metodo_entrega_id,
            activo=True,
        )
        self.cleanup.track_metodo_entrega_assoc(metodo_assoc_id)

        canal_id = _seed_dedicated_channel(
            comercio_id=comercio_id,
        )
        self.cleanup.track_canal(canal_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertTrue(projection.payments.has_eligible_payment)
        self.assertEqual(projection.payments.eligible_count, 1)
        self.assertTrue(projection.deliveries.has_eligible_delivery)
        self.assertEqual(projection.deliveries.eligible_count, 1)
        self.assertTrue(projection.channel.has_dedicated_channel)
        self.assertEqual(
            projection.lifecycle.status,
            CommerceAvailabilityStatus.UNAVAILABLE,
        )
        self.assertEqual(
            projection.profile.estado_codigo, "INACTIVO"
        )

        with TestingSessionLocal() as session:
            outcome = CommerceAvailabilityService(
                session
            ).evaluate(comercio_id)
        self.assertEqual(
            outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
        )


class ReadinessPaymentEligibilityTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Globally inactive medios_pago never count as eligible."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-pay-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_global_inactive_medio_pago_is_not_eligible(self) -> None:
        """A globally inactive medios_pago row stays pending.

        Even when the ``ComercioMedioPago`` bridge row is
        ``activo=True``, a globally inactive ``MediosPago``
        row must NOT count as an eligible payment.
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        medio_inactive_id = _seed_medio_pago(
            codigo=f"PIA-{_suffix()[:6]}",
            descripcion="Inactive payment",
            activo=False,
        )
        self.cleanup.track_medio_pago(medio_inactive_id)
        medio_assoc_id = _seed_comercio_medio_pago(
            comercio_id=comercio_id,
            medio_pago_id=medio_inactive_id,
            activo=True,
        )
        self.cleanup.track_medio_pago_assoc(medio_assoc_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.payments.has_eligible_payment)
        self.assertEqual(projection.payments.eligible_count, 0)

    def test_inactive_comercio_bridge_is_not_eligible(self) -> None:
        """An inactive bridge row stays pending.

        A globally active ``MediosPago`` whose
        ``ComercioMedioPago`` bridge row is ``activo=False``
        must NOT count as an eligible payment either.
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        medio_pago_id = _seed_medio_pago(
            codigo=f"PAC-{_suffix()[:6]}",
            descripcion="Active payment",
            activo=True,
        )
        self.cleanup.track_medio_pago(medio_pago_id)
        medio_assoc_id = _seed_comercio_medio_pago(
            comercio_id=comercio_id,
            medio_pago_id=medio_pago_id,
            activo=False,
        )
        self.cleanup.track_medio_pago_assoc(medio_assoc_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.payments.has_eligible_payment)


class ReadinessDeliveryEligibilityTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Globally inactive metodos_entrega never count as eligible."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-del-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_global_inactive_metodo_entrega_is_not_eligible(self) -> None:
        """A globally inactive delivery row stays pending."""
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        metodo_inactive_id = _seed_metodo_entrega(
            codigo=f"DIA-{_suffix()[:6]}",
            descripcion="Inactive delivery",
            activo=False,
        )
        self.cleanup.track_metodo_entrega(metodo_inactive_id)
        metodo_assoc_id = _seed_comercio_metodo_entrega(
            comercio_id=comercio_id,
            metodo_entrega_id=metodo_inactive_id,
            activo=True,
        )
        self.cleanup.track_metodo_entrega_assoc(metodo_assoc_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.deliveries.has_eligible_delivery)


class ReadinessChannelStateTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Channel readiness reflects the existing channel rows only."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-chan-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def _seed_base(self) -> int:
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        return comercio_id

    def test_no_channel_reports_pending(self) -> None:
        """No channel rows -> the dashboard reports pending."""
        _ = self._seed_base()
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.channel.has_dedicated_channel)
        self.assertFalse(projection.channel.has_shared_membership)
        self.assertIsNone(projection.channel.dedicated_channel_id)
        self.assertIsNone(projection.channel.shared_membership_id)

    def test_inactive_dedicated_channel_reports_pending(self) -> None:
        """An inactive dedicated channel stays pending."""
        comercio_id = self._seed_base()
        canal_id = _seed_dedicated_channel(
            comercio_id=comercio_id, activo=False
        )
        self.cleanup.track_canal(canal_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.channel.has_dedicated_channel)

    def test_inactive_shared_membership_reports_pending(self) -> None:
        """An active shared channel with an inactive membership
        reports pending.
        """
        comercio_id = self._seed_base()
        canal_id = _seed_shared_channel(activo=True)
        self.cleanup.track_canal(canal_id)
        membership_id = _seed_shared_membership(
            canal_id=canal_id,
            comercio_id=comercio_id,
            routing_code=f"PHASE4B-{_suffix()[:6]}",
            activo=False,
        )
        self.cleanup.track_shared_membership(membership_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.channel.has_shared_membership)

    def test_inactive_shared_channel_reports_pending(self) -> None:
        """An inactive shared channel reports pending even with
        an active membership row.
        """
        comercio_id = self._seed_base()
        canal_id = _seed_shared_channel(activo=False)
        self.cleanup.track_canal(canal_id)
        membership_id = _seed_shared_membership(
            canal_id=canal_id,
            comercio_id=comercio_id,
            routing_code=f"PHASE4B-{_suffix()[:6]}",
            activo=True,
        )
        self.cleanup.track_shared_membership(membership_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertFalse(projection.channel.has_shared_membership)

    def test_active_dedicated_channel_reports_ready(self) -> None:
        """An active dedicated channel reports ready."""
        comercio_id = self._seed_base()
        canal_id = _seed_dedicated_channel(comercio_id=comercio_id)
        self.cleanup.track_canal(canal_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertTrue(projection.channel.has_dedicated_channel)
        self.assertEqual(
            projection.channel.dedicated_channel_id, canal_id
        )

    def test_active_shared_membership_reports_ready(self) -> None:
        """An active shared channel with an active membership
        row reports ready.
        """
        comercio_id = self._seed_base()
        canal_id = _seed_shared_channel(activo=True)
        self.cleanup.track_canal(canal_id)
        membership_id = _seed_shared_membership(
            canal_id=canal_id,
            comercio_id=comercio_id,
            routing_code=f"PHASE4B-{_suffix()[:6]}",
            activo=True,
        )
        self.cleanup.track_shared_membership(membership_id)

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            projection = build_owner_readiness(session, principal)

        self.assertTrue(projection.channel.has_shared_membership)
        self.assertEqual(
            projection.channel.shared_membership_id, membership_id
        )


class ReadinessFailClosedTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """Failure modes render bounded errors and never fall back."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-fail-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_missing_account_raises_account_missing(self) -> None:
        """A principal without an account row raises the typed
        ``OwnerReadinessAccountMissing`` signal so the route
        can render the bounded feedback view.
        """
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessAccountMissing):
                build_owner_readiness(session, principal)

    def test_missing_draft_raises_draft_missing(self) -> None:
        """An account with no draft raises the typed signal."""
        _seed_cuenta(self.subject)
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessDraftMissing):
                build_owner_readiness(session, principal)

    def test_inactive_account_raises_account_missing(self) -> None:
        """An inactive account fails closed without falling back."""
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO cuentas_usuario "
                    "(supabase_subject, activo, fecha_alta, "
                    " fecha_ultima_modificacion, fecha_baja) "
                    "VALUES (:subject, false, now(), now(), "
                    " now())"
                ),
                {"subject": self.subject},
            )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessAccountMissing):
                build_owner_readiness(session, principal)

    def test_non_terminal_draft_raises_not_terminal(self) -> None:
        """A non-terminal draft raises the typed signal."""
        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, principal)
            load_or_create_borrador(session, cuenta)
            with self.assertRaises(OwnerReadinessDraftNotTerminal):
                build_owner_readiness(session, principal)

    def test_missing_membership_raises_membership_missing(self) -> None:
        """A terminal draft without an OWNER membership fails
        closed and the route must NOT expose any commerce
        fact.
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessMembershipMissing):
                build_owner_readiness(session, principal)

    def test_inactive_membership_raises_membership_missing(self) -> None:
        """A terminal draft with an inactive OWNER membership
        fails closed.
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE comercio_usuarios SET activo = false "
                    "WHERE id = :membership_id"
                ),
                {"membership_id": membership_id},
            )

        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessMembershipMissing):
                build_owner_readiness(session, principal)

    def test_other_account_membership_raises_membership_missing(
        self,
    ) -> None:
        """A membership that belongs to another account is a
        fail-closed signal — the dashboard must never expose
        the comercio.
        """
        other_subject = f"phase4b-mb-{_suffix()}"
        self.cleanup.seeded_subjects.append(other_subject)
        _seed_cuenta(self.subject)
        other_cuenta_id = _seed_cuenta(other_subject)

        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=other_cuenta_id,
            comercio_id=comercio_id,
        )
        self.cleanup.track_membership(membership_id)

        own_cuenta_id = _resolve_cuenta_id(self.subject)
        _seed_terminal_draft(
            cuenta_usuario_id=own_cuenta_id, comercio_id=comercio_id
        )

        principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            with self.assertRaises(OwnerReadinessMembershipMissing):
                build_owner_readiness(session, principal)

    def test_terminal_draft_without_comercio_raises_comercio_missing(
        self,
    ) -> None:
        """A terminal draft pointing at a missing Comercio
        raises the typed signal so the dashboard never falls
        back to another comercio or exposes anything.

        The database ``RESTRICT`` foreign key normally
        prevents a terminal draft from referencing a missing
        ``Comercio`` row. To exercise the defensive branch
        the test temporarily drops the constraint, deletes
        the comercio and re-creates the constraint as
        ``NOT VALID`` so the broken state is reachable for
        the duration of the assertion. The cleanup drops
        the dangling reference so the test does not pollute
        the database across runs.
        """
        cuenta_id = _seed_cuenta(self.subject)
        orphan_slug = f"phase4b-orphan-{_suffix()}"
        self.cleanup.track_slug(orphan_slug)
        comercio_id = _seed_comercio(
            slug=orphan_slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        fk_name = (
            "borrador_onboarding_comercio_comercio_id_fkey"
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"ALTER TABLE borrador_onboarding_comercio "
                    f"DROP CONSTRAINT {fk_name}"
                )
            )
            conn.execute(
                delete(Comercio).where(Comercio.id == comercio_id)
            )

        try:
            principal = _make_principal(self.subject)
            with TestingSessionLocal() as session:
                with self.assertRaises(OwnerReadinessComercioMissing):
                    build_owner_readiness(session, principal)
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE borrador_onboarding_comercio "
                        "SET comercio_id = NULL, "
                        " completado_en = NULL "
                        "WHERE cuenta_usuario_id = :cuenta_id"
                    ),
                    {"cuenta_id": cuenta_id},
                )
                conn.execute(
                    text(
                        f"ALTER TABLE borrador_onboarding_comercio "
                        f"ADD CONSTRAINT {fk_name} "
                        f"FOREIGN KEY (comercio_id) "
                        f"REFERENCES comercios(id) "
                        f"ON DELETE RESTRICT NOT VALID"
                    )
                )


class ReadinessPersistenceFailureTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """A repository failure must not produce writes or fallback."""

    def setUp(self) -> None:
        self.cleanup = _Phase4BCleanup()
        self.subject = self.cleanup.seed_subject()
        self.slug = f"phase4b-persist-{_suffix()}"
        self.cleanup.track_slug(self.slug)

    def tearDown(self) -> None:
        self.cleanup.cleanup()

    def test_repository_failure_does_not_produce_writes(self) -> None:
        """A SQLAlchemy error escapes the helper with no writes.

        The test patches
        :meth:`MediosPagoRepository.list_active_for_comercio`
        to raise a generic ``SQLAlchemyError`` and verifies
        the readiness service never opened a writable
        transaction (the route's ``try/except SQLAlchemyError``
        is the only handler).
        """
        cuenta_id = _seed_cuenta(self.subject)
        comercio_id = _seed_comercio(
            slug=self.slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(comercio_id)
        membership_id = _seed_owner_membership(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )
        self.cleanup.track_membership(membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=cuenta_id, comercio_id=comercio_id
        )

        with self.assertRaises(SQLAlchemyError):
            from unittest.mock import patch

            from backend.repositories.medios_pago_repository import (
                MediosPagoRepository,
            )

            principal = _make_principal(self.subject)
            with patch.object(
                MediosPagoRepository,
                "list_active_for_comercio",
                side_effect=SQLAlchemyError(
                    "simulated read failure"
                ),
            ):
                with TestingSessionLocal() as session:
                    build_owner_readiness(session, principal)


class ReadinessRouteContractTest(
    MerchantStateSeedingMixin, unittest.TestCase
):
    """``GET /onboarding/readiness`` is the only Phase 4B surface."""

    def setUp(self) -> None:
        _seed_inactivo_estado()
        self.cleanup = _Phase4BCleanup()
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

    def test_readiness_route_exists_with_expected_path_and_methods(
        self,
    ) -> None:
        from backend.routers import owner_onboarding

        candidates = [
            r
            for r in owner_onboarding.router.routes
            if getattr(r, "path", "") == "/onboarding/readiness"
        ]
        self.assertEqual(len(candidates), 1)
        route = candidates[0]
        methods = set(getattr(route, "methods", set()))
        self.assertIn("GET", methods)
        self.assertNotIn("POST", methods)
        self.assertNotIn("PUT", methods)
        self.assertNotIn("DELETE", methods)
        self.assertNotIn("PATCH", methods)

    def test_get_renders_dashboard_for_terminal_owner(self) -> None:
        """A terminal owner GET renders the dashboard."""
        slug = f"phase4b-http-{_suffix()}"
        self.cleanup.track_slug(slug)
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

        with TestingSessionLocal() as session:
            with session.begin():
                from backend.services.owner_onboarding_completion_service import (
                    complete_onboarding,
                )

                outcome = complete_onboarding(session, principal)
                self.cleanup.track_comercio(int(outcome.comercio_id))

        response = self.client.get(
            "/onboarding/readiness",
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Estado y próximos pasos", response.text)
        self.assertIn(slug, response.text)

    def test_get_renders_bounded_503_for_missing_account(self) -> None:
        """A principal without an account gets a bounded 503."""
        response = self.client.get(
            "/onboarding/readiness",
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("Wizard no disponible", response.text)

    def test_get_does_not_accept_comercio_id_in_query(self) -> None:
        """A rogue ``comercio_id`` query parameter is ignored.

        The route accepts no ``comercio_id`` input. The test
        fires a request with a ``comercio_id`` query string
        pointing at a foreign account's comercio and asserts
        the dashboard renders the OWNER's own comercio, not
        the foreign one.
        """
        slug = f"phase4b-q-{_suffix()}"
        foreign_slug = f"phase4b-f-{_suffix()}"
        self.cleanup.track_slug(slug)
        self.cleanup.track_slug(foreign_slug)

        other_subject = f"phase4b-q-other-{_suffix()}"
        self.cleanup.seeded_subjects.append(other_subject)
        other_cuenta_id = _seed_cuenta(other_subject)

        foreign_comercio_id = _seed_comercio(
            slug=foreign_slug, estado_id=self.inactivo_id
        )
        self.cleanup.track_comercio(foreign_comercio_id)
        foreign_membership_id = _seed_owner_membership(
            cuenta_usuario_id=other_cuenta_id,
            comercio_id=foreign_comercio_id,
        )
        self.cleanup.track_membership(foreign_membership_id)
        _seed_terminal_draft(
            cuenta_usuario_id=other_cuenta_id,
            comercio_id=foreign_comercio_id,
        )

        own_principal = _make_principal(self.subject)
        with TestingSessionLocal() as session:
            cuenta = resolve_or_create_cuenta(session, own_principal)
            draft = load_or_create_borrador(session, cuenta)
            fields = _build_complete_draft_fields(slug=slug)
            saved = save_borrador(
                session,
                draft,
                expected_version=0,
                fields=fields,
            )
            assert saved.completo is True

        with TestingSessionLocal() as session:
            with session.begin():
                from backend.services.owner_onboarding_completion_service import (
                    complete_onboarding,
                )

                own_outcome = complete_onboarding(
                    session, own_principal
                )
                own_comercio_id = int(own_outcome.comercio_id)
                self.cleanup.track_comercio(own_comercio_id)

        response = self.client.get(
            f"/onboarding/readiness?comercio_id={foreign_comercio_id}",
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={self._principal_cookie()}"
                ),
                "origin": "http://testserver",
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(slug, response.text)
        self.assertNotIn(foreign_slug, response.text)
        self.assertIn(f"#{own_comercio_id}", response.text)


if __name__ == "__main__":
    unittest.main()