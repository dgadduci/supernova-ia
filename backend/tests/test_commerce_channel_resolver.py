"""Focused tests for the read-only ``CommerceChannelResolver``.

Covers the 5.1 resolver boundary: destination normalization, the
active dedicated success path, and every non-resolved outcome
(``invalid_destination``, ``unknown_channel``, ``inactive_channel``,
``unavailable_commerce``, ``requires_shared_routing``). Also asserts
that the resolver performs no transaction control and never invokes
the local incoming-message endpoint, classifier, recognizer, handler,
catalog or session-creation code.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Comercio,
    ComercioCanalCompartido,
    EstadoComercio,
)
from backend.services.canal_whatsapp_service import CanalWhatsappService
from backend.services.commerce_channel_resolver import (
    CommerceChannelResolver,
    ResolutionStatus,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(
                EstadoComercio.codigo == "ACTIVO"
            )
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _estado_id_inactivo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(
                EstadoComercio.codigo == "INACTIVO"
            )
        ).first()
        if row is None:
            raise RuntimeError("estado INACTIVO not seeded in supernova_test")
        return row[0]


def _seed_comercio(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Resolver Test {suffix}",
            nombre_corto=f"RT {suffix}",
            razon_social=f"Resolver Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54921{suffix[:8]}",
            calle="Av. Resolver",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"resolver-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_inactive_comercio(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Resolver Inactive {suffix}",
            nombre_corto=f"RI {suffix}",
            razon_social=f"Resolver Inactive SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54922{suffix[:8]}",
            calle="Av. Resolver",
            numero="200",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"resolver-inactive-{suffix}",
            estado_id=_estado_id_inactivo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _delete_canales_by_destination(destination: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.destination_e164 == destination
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.destination_e164 == destination
            )
        )


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.comercio_id == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class CommerceChannelResolverNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self._dest_counter = 0

    def _destination(self) -> str:
        self._dest_counter += 1
        suffix = self.fixtures["suffix"]
        digits = (int(suffix, 16) * 1000 + self._dest_counter) % 10_000_000
        return f"+54931{digits:07d}"

    def test_active_dedicated_channel_resolves(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", destination)
        self.assertTrue(outcome.is_resolved)
        self.assertEqual(outcome.status, ResolutionStatus.RESOLVED)
        self.assertEqual(outcome.routing_mode, CanalWhatsappMode.DEDICATED)
        self.assertEqual(outcome.comercio_id, self.fixtures["comercio_id"])
        self.assertIsNotNone(outcome.channel_id)
        self.assertEqual(outcome.resolution_source, "destination_number")

    def test_equivalent_destination_representations_resolve_same_channel(
        self,
    ):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            canonical = resolver.resolve_dedicated("twilio", destination)
            prefixed = resolver.resolve_dedicated(
                "twilio", f"whatsapp:{destination}"
            )
            spaced = resolver.resolve_dedicated(
                "twilio", f"  whatsapp:{destination}  "
            )
        self.assertEqual(canonical.channel_id, prefixed.channel_id)
        self.assertEqual(canonical.channel_id, spaced.channel_id)
        self.assertTrue(canonical.is_resolved)
        self.assertTrue(prefixed.is_resolved)
        self.assertTrue(spaced.is_resolved)

    def test_unknown_destination_returns_unknown_channel(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", destination)
        self.assertEqual(outcome.status, ResolutionStatus.UNKNOWN_CHANNEL)
        self.assertFalse(outcome.is_resolved)
        self.assertIsNone(outcome.comercio_id)
        self.assertIsNone(outcome.channel_id)
        self.assertEqual(outcome.resolution_source, "no_active_channel")

    def test_malformed_destination_returns_invalid_destination(self):
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", "not-a-number")
        self.assertEqual(
            outcome.status, ResolutionStatus.INVALID_DESTINATION
        )
        self.assertFalse(outcome.is_resolved)
        self.assertIsNone(outcome.comercio_id)
        self.assertIsNone(outcome.channel_id)
        self.assertEqual(
            outcome.resolution_source, "destination_normalization"
        )

    def test_whatsapp_prefix_only_after_strip_is_invalid(self):
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", "whatsapp:")
        self.assertEqual(
            outcome.status, ResolutionStatus.INVALID_DESTINATION
        )

    def test_empty_destination_returns_invalid_destination(self):
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", "")
        self.assertEqual(
            outcome.status, ResolutionStatus.INVALID_DESTINATION
        )

    def test_inactive_channel_returns_inactive_channel(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            session.flush()
            canal_id = int(canal.id)
            service.deactivate_channel(canal_id)
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", destination)
        self.assertEqual(
            outcome.status, ResolutionStatus.INACTIVE_CHANNEL
        )
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.channel_id, canal_id)
        self.assertEqual(outcome.routing_mode, CanalWhatsappMode.DEDICATED)
        self.assertIsNone(outcome.comercio_id)
        self.assertEqual(outcome.resolution_source, "inactive_channel")

    def test_active_dedicated_with_inactive_commerce_returns_unavailable(
        self,
    ):
        inactive = _seed_inactive_comercio()
        self.addCleanup(_delete_comercio, inactive["comercio_id"])
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            session.flush()
            canal_id = int(canal.id)
        with engine.begin() as conn:
            conn.execute(
                Comercio.__table__.update()
                .where(Comercio.id == self.fixtures["comercio_id"])
                .values(estado_id=_estado_id_inactivo())
            )
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", destination)
        self.assertEqual(
            outcome.status, ResolutionStatus.UNAVAILABLE_COMMERCE
        )
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.channel_id, canal_id)
        self.assertEqual(outcome.routing_mode, CanalWhatsappMode.DEDICATED)
        self.assertEqual(outcome.comercio_id, self.fixtures["comercio_id"])
        self.assertEqual(outcome.resolution_source, "inactive_commerce")

    def test_active_shared_channel_returns_requires_shared_routing(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            canal_id = int(canal.id)
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated("twilio", destination)
        self.assertEqual(
            outcome.status, ResolutionStatus.REQUIRES_SHARED_ROUTING
        )
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.channel_id, canal_id)
        self.assertEqual(outcome.routing_mode, CanalWhatsappMode.SHARED)
        self.assertIsNone(outcome.comercio_id)
        self.assertEqual(outcome.resolution_source, "shared_channel")

    def test_provider_identity_isolates_resolution(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            outcome = resolver.resolve_dedicated(
                "other-provider", destination
            )
        self.assertEqual(outcome.status, ResolutionStatus.UNKNOWN_CHANNEL)


class CommerceChannelResolverBoundaryTest(unittest.TestCase):
    """Prove the resolver performs no transaction control or
    business-pipeline call.

    The resolver's session MUST NOT receive ``commit``, ``rollback``,
    ``begin`` or ``flush``. The local endpoint, classifier,
    recognizer, handler, catalog and session-creation entry points
    MUST NOT be invoked.
    """

    def test_resolver_does_not_call_commit_or_rollback(self):
        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            with patch.object(session, "commit") as commit, patch.object(
                session, "rollback"
            ) as rollback, patch.object(session, "begin") as begin, patch.object(
                session, "flush"
            ) as flush:
                outcome = resolver.resolve_dedicated(
                    "twilio", "+5491199999999"
                )
        self.assertEqual(
            outcome.status, ResolutionStatus.UNKNOWN_CHANNEL
        )
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()

    def test_resolver_does_not_invoke_local_endpoint(self):
        from backend.routers import incoming_messages

        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            with patch.object(
                incoming_messages,
                "post_incoming_message",
            ) as endpoint, patch.object(
                incoming_messages,
                "process_incoming_message_with_responses",
            ) as responses:
                resolver.resolve_dedicated("twilio", "+5491199999999")
        endpoint.assert_not_called()
        responses.assert_not_called()

    def test_resolver_does_not_invoke_classifier_or_recognizer(self):
        from backend.intents.orchestration import (
            incoming_message_orchestrator,
        )
        from backend.recognizers import product_recognizer as recognizer_module

        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            with patch.object(
                incoming_message_orchestrator,
                "process_incoming_message",
            ) as orchestrator, patch.object(
                recognizer_module,
                "detectar_productos",
            ) as recognizer:
                resolver.resolve_dedicated("twilio", "+5491199999999")
        orchestrator.assert_not_called()
        recognizer.assert_not_called()

    def test_resolver_does_not_create_cliente_or_session(self):
        from backend.repositories import (
            cliente_repository,
            session_repository,
        )

        with TestingSessionLocal() as session:
            resolver = CommerceChannelResolver(session)
            with patch.object(
                cliente_repository,
                "ClienteRepository",
            ) as cliente_cls, patch.object(
                session_repository,
                "SessionRepository",
            ) as session_repo_cls:
                resolver.resolve_dedicated("twilio", "+5491199999999")
        cliente_cls.assert_not_called()
        session_repo_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()