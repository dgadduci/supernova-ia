"""Focused tests for the internal commerce-installation ingress router.

The tests cover the documented outcomes of the bounded internal
ingress endpoint:

* HMAC mismatch → ``401`` with no coordinator call;
* missing signature → ``401`` with no coordinator call;
* missing master key → ``503`` with no coordinator call;
* installation inactive → ``401`` with no coordinator call;
* unknown destination → ``200 {"status": "rejected", "reason":
  "unknown_destination"}``;
* unknown client → ``200 {"status": "rejected", "reason":
  "unknown_client"}``;
* unavailable commerce → ``200 {"status": "rejected", "reason":
  "unavailable_commerce"}``;
* valid signature + valid authority → ``200 {"status": "accepted"}``
  and exactly one coordinator call;
* duplicate message identifier → ``200 {"status": "duplicate"}`` and
  no second work item.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.routers.internal_commerce_installation as router_module
from backend.dependencies import get_session
from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Cliente,
    Comercio,
    EstadoComercio,
    InstalacionTwilioComercio,
)
from backend.services.instalacion_secret_envelope import (
    decrypt_secret,
    encrypt_secret,
    resolve_master_keys,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundAcceptanceOutcome,
    ProviderInboundMessageStatus,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


MASTER_KEY: str = Fernet.generate_key().decode("ascii")
MASTER_KEY_KID: str = "current"


ROUTE_TEMPLATE: str = "/internal/commerce-installation/{instalacion_id}/accept-event"


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id(nombre: str) -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == nombre)
        ).first()
        if row is None:
            raise RuntimeError(f"estado {nombre!r} not seeded")
        return int(row[0])


def _estado_id_activo() -> int:
    return _estado_id("ACTIVO")


def _seed_comercio(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Install Ingress {suffix}",
            nombre_corto=f"II {suffix}",
            razon_social=f"Install Ingress SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54914{suffix[:8]}",
            calle="Av. Ingress",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"install-ingress-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_canal(
    *,
    comercio_id: int,
    destination_e164: str,
    provider: str = "twilio",
) -> int:
    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider=provider,
            destination_e164=destination_e164,
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio_id,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_cliente(*, whatsapp: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=whatsapp,
            nombre="Test",
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        return int(cliente.id)


def _seed_instalacion(
    *,
    comercio_id: int,
    instalacion_id: str,
    plain_secret: str,
    activo: bool = True,
) -> None:
    bundle = resolve_master_keys(
        current_env=MASTER_KEY, previous_env=None
    )
    envelope, key_id = encrypt_secret(
        plain_secret=plain_secret, bundle=bundle
    )
    with TestingSessionLocal() as session, session.begin():
        row = InstalacionTwilioComercio(
            id_comercio=comercio_id,
            tc_service_url="https://tc.example.test",
            instalacion_id=instalacion_id,
            activo=activo,
            secreto_envelope=envelope,
            secreto_envelope_kid=key_id,
        )
        session.add(row)


def _delete_instalacion(instalacion_id: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.instalacion_id == instalacion_id
            )
        )


def _delete_canal(canal_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(CanalWhatsapp).where(CanalWhatsapp.id == canal_id)
        )


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Cliente).where(Cliente.id == cliente_id))


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _build_payload(
    *,
    instalacion_id: str,
    comercio_id: int,
    message_sid: str = "SM-ABC",
    from_e164: str | None = None,
    to_e164: str | None = None,
    cuerpo: str = "hola",
) -> bytes:
    if from_e164 is None:
        from_e164 = "+5491100000000"
    if to_e164 is None:
        to_e164 = "+5491100000000"
    payload = {
        "instalacion_id": instalacion_id,
        "comercio_id": comercio_id,
        "proveedor": "twilio",
        "message_sid": message_sid,
        "from_e164": from_e164,
        "to_e164": to_e164,
        "cuerpo": cuerpo,
        "num_media": 0,
    }
    return json.dumps(payload).encode("utf-8")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


class _StubCoordinator:
    def __init__(self, status: ProviderInboundMessageStatus) -> None:
        self._status = status
        self.accept_calls: list[Any] = []

    def accept(self, command: Any) -> ProviderInboundAcceptanceOutcome:
        self.accept_calls.append(command)
        return ProviderInboundAcceptanceOutcome(
            status=self._status,
            canal_id=int(command.canal_id),
            cliente_id=int(command.cliente_id),
            comercio_id=int(command.comercio_id),
            proveedor=str(getattr(command, "proveedor", "twilio")),
            identificador_recepcion=str(
                getattr(command, "identificador_recepcion", "SM-ABC")
            ),
            receipt_id=42,
            procesamiento_id=None,
            resolution_source="first_processing",
        )


class _IngressTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.suffix = _suffix()
        self.seeded = _seed_comercio(self.suffix)
        self.comercio_id = int(self.seeded["comercio_id"])
        # Unique-by-test instalacion_id so the unique constraint never
        # collides across tests in the shared supernova_test database.
        self.instalacion_id = (
            "i" + self.suffix + ("a" * (23 - len(self.suffix)))
        )[:24]
        self.plain_secret = "shared-secret-1234567890"
        self.destination = f"+54911{self.suffix[:8]}"
        self.client_phone = f"+54912{self.suffix[:8]}"
        self.canal_id = _seed_canal(
            comercio_id=self.comercio_id,
            destination_e164=self.destination,
        )
        self.cliente_id = _seed_cliente(
            whatsapp=self.client_phone,
        )
        _seed_instalacion(
            comercio_id=self.comercio_id,
            instalacion_id=self.instalacion_id,
            plain_secret=self.plain_secret,
        )
        self._saved_env = os.environ.copy()
        os.environ["COMMERCE_INSTALLATION_MASTER_KEY"] = MASTER_KEY

    def tearDown(self) -> None:
        if hasattr(self, "_coord_patcher"):
            self._stop_patches()
        _delete_instalacion(self.instalacion_id)
        _delete_canal(self.canal_id)
        _delete_cliente(self.cliente_id)
        _delete_comercio(self.comercio_id)
        os.environ.clear()
        os.environ.update(self._saved_env)

    def _build_app(
        self,
        *,
        coordinator_status: ProviderInboundMessageStatus = (
            ProviderInboundMessageStatus.ACCEPTED
        ),
        availability_status: Any = None,
    ) -> tuple[TestClient, _StubCoordinator]:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus,
        )

        if availability_status is None:
            availability_status = CommerceAvailabilityStatus.AVAILABLE

        coordinator = _StubCoordinator(status=coordinator_status)
        app = FastAPI()
        app.include_router(router_module.router)

        session = TestingSessionLocal()

        def _override_get_session() -> Any:
            return session

        app.dependency_overrides[get_session] = _override_get_session

        availability_instance = MagicMock()
        availability_value = MagicMock()
        availability_value.status = availability_status
        availability_instance.evaluate.return_value = availability_value

        self._coord_patcher = patch.object(
            router_module,
            "ProviderInboundMessageCoordinator",
            return_value=coordinator,
        )
        self._availability_patcher = patch.object(
            router_module,
            "CommerceAvailabilityService",
            return_value=availability_instance,
        )
        self._coord_patcher.start()
        self._availability_patcher.start()
        client = TestClient(app)
        return client, coordinator

    def _stop_patches(self) -> None:
        self._availability_patcher.stop()
        self._coord_patcher.stop()


class InternalIngressHappyPathTest(_IngressTestCase):
    def test_valid_signature_and_authority_returns_accepted(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164=self.client_phone,
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "accepted")
        self.assertEqual(data["receipt_id"], 42)
        self.assertEqual(len(coordinator.accept_calls), 1)


class InternalIngressSignatureFailureTest(_IngressTestCase):
    def test_missing_signature_returns_401(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(coordinator.accept_calls, [])

    def test_tampered_signature_returns_401(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, "wrong-secret"),
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressInactiveInstallationTest(_IngressTestCase):
    def test_inactive_installation_returns_401(self) -> None:
        _delete_instalacion(self.instalacion_id)
        _seed_instalacion(
            comercio_id=self.comercio_id,
            instalacion_id=self.instalacion_id,
            plain_secret=self.plain_secret,
            activo=False,
        )
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164=self.client_phone,
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressUnknownDestinationTest(_IngressTestCase):
    def test_unknown_destination_returns_rejected(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            to_e164="+18005551212",
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(response.json()["reason"], "unknown_destination")
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressUnknownClientTest(_IngressTestCase):
    def test_unknown_client_returns_rejected(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164="+18005550000",
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(response.json()["reason"], "unknown_client")
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressUnavailableCommerceTest(_IngressTestCase):
    def test_unavailable_commerce_returns_rejected(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus,
        )

        client, coordinator = self._build_app(
            availability_status=CommerceAvailabilityStatus.UNAVAILABLE,
        )
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164=self.client_phone,
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(response.json()["reason"], "unavailable_commerce")
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressDuplicateTest(_IngressTestCase):
    def test_duplicate_message_returns_duplicate(self) -> None:
        client, coordinator = self._build_app(
            coordinator_status=(
                ProviderInboundMessageStatus.ALREADY_PROCESSED
            ),
        )
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164=self.client_phone,
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "duplicate")
        self.assertEqual(len(coordinator.accept_calls), 1)


class InternalIngressMissingMasterKeyTest(_IngressTestCase):
    def test_missing_master_key_returns_503(self) -> None:
        os.environ.pop("COMMERCE_INSTALLATION_MASTER_KEY", None)
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id,
            from_e164=self.client_phone,
            to_e164=self.destination,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressUnknownInstallationTest(_IngressTestCase):
    def test_unknown_installation_returns_401(self) -> None:
        client, coordinator = self._build_app()
        unknown_id = "z" * 24
        body = _build_payload(
            instalacion_id=unknown_id,
            comercio_id=self.comercio_id,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=unknown_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(coordinator.accept_calls, [])


class InternalIngressPayloadMismatchTest(_IngressTestCase):
    def test_payload_comercio_mismatch_returns_400(self) -> None:
        client, coordinator = self._build_app()
        body = _build_payload(
            instalacion_id=self.instalacion_id,
            comercio_id=self.comercio_id + 1,
        )
        response = client.post(
            ROUTE_TEMPLATE.format(instalacion_id=self.instalacion_id),
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Installation-Signature": _sign(body, self.plain_secret),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(coordinator.accept_calls, [])


class DecryptEnvelopeRoundTripTest(unittest.TestCase):
    def test_decrypt_round_trip(self) -> None:
        bundle = resolve_master_keys(
            current_env=MASTER_KEY, previous_env=None
        )
        plain = "round-trip-secret"
        envelope, key_id = encrypt_secret(
            plain_secret=plain, bundle=bundle
        )
        decrypted = decrypt_secret(
            envelope=envelope, key_id=key_id, bundle=bundle
        )
        self.assertEqual(decrypted, plain)


if __name__ == "__main__":
    unittest.main(verbosity=2)
