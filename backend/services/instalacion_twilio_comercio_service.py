"""Business rules for the commerce Twilio installation registry.

The service is the only place that knows how to:

* generate the opaque ``instalacion_id`` and the per-installation shared
  secret;
* encrypt the shared secret with the configured Fernet master key;
* persist the envelope on the installation row through the repository;
* reject duplicate active installations for the same ``comercio_id``;
* reject malformed per-installation T-C service URLs, comercio ids
  and identifiers.

The service never logs the plain shared secret. The bounded provisioning
CLI is the single caller; the bounded internal ingress dependency uses
only :func:`decrypt_installation_secret`, which decrypts on demand and
returns the plain value without logging.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.instalacion_twilio_comercio import (
    INSTALLACION_ID_PATTERN,
    InstalacionTwilioComercio,
)
from backend.repositories.instalacion_twilio_comercio_repository import (
    InstalacionTwilioComercioRepository,
)
from backend.services.exceptions import (
    DuplicateInstalacionTwilioComercio,
    InvalidInstallationIdentificador,
    InvalidInstallationSecretEnvelope,
    InvalidInstallationTcServiceUrl,
)
from backend.services.instalacion_secret_envelope import (
    MasterKeyBundle,
    decrypt_secret,
    encrypt_secret,
    generate_installation_secret,
)

_RAILWAY_INTERNAL_SUFFIX: str = ".railway.internal"


@dataclass(frozen=True)
class ProvisionedInstallation:
    """Typed outcome of :func:`InstalacionTwilioComercioService.create_installation`.

    ``plain_secret`` is returned exactly once and only from the
    provisioning seam. The bounded CLI prints it on stdout; the row
    never carries the plain value.
    """

    instalacion_id: str
    comercio_id: int
    plain_secret: str
    tc_service_url: str
    row: InstalacionTwilioComercio


@dataclass(frozen=True)
class DecryptedInstallationSecret:
    """Typed outcome of :func:`InstalacionTwilioComercioService.decrypt_installation_secret`.

    The plain secret is held only for the duration of the HMAC
    verification performed by the bounded ingress dependency. The
    dependency does not log it and does not return it to any caller.
    """

    instalacion_id: str
    comercio_id: int
    plain_secret: str


def _generate_instalacion_id() -> str:
    """Generate a 24-character lowercase alphanumeric identifier.

    The output matches ``INSTALLACION_ID_PATTERN`` so the bounded
    ingress path can safely embed the value in URLs and the bounded
    provisioning CLI can print it on stdout without escaping concerns.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(24))


def _validate_instalacion_id(instalacion_id: str) -> str:
    if (
        not isinstance(instalacion_id, str)
        or not INSTALLACION_ID_PATTERN.match(instalacion_id)
    ):
        raise InvalidInstallationIdentificador(
            "instalacion_id must be a 24-character lowercase alphanumeric string"
        )
    return instalacion_id


def validate_tc_service_url(value: Any) -> str:
    """Validate a per-installation T-C service URL.

    The validator is the single entry point used by the service, the
    CLI and any operator tooling. It enforces the documented
    contract:

    * the value must be a non-empty stripped string;
    * the scheme must be ``https`` for public URLs;
    * plain ``http`` is allowed only for hostnames that match the
      documented Railway private networking pattern
      (``*.railway.internal``);
    * the URL must not carry credentials, query string or fragment;
    * the URL must be absolute (``scheme://host[/path]``).

    The helper is exposed so the bounded provisioning CLI and the
    bounded internal ingress dependency can share the exact same
    validation.
    """
    if not isinstance(value, str):
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must be a string"
        )
    cleaned = value.strip()
    if not cleaned:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must be a non-empty stripped string"
        )
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"https", "http"}:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must use https (or http only for *.railway.internal)"
        )
    if not parsed.netloc:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must be an absolute URL"
        )
    hostname = (parsed.hostname or "").lower()
    if scheme == "http" and not (
        hostname == "railway.internal"
        or hostname.endswith(_RAILWAY_INTERNAL_SUFFIX)
    ):
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url with http is only allowed for "
            "*.railway.internal hostnames"
        )
    if parsed.username or parsed.password:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must not contain credentials"
        )
    if parsed.query:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must not contain a query string"
        )
    if parsed.fragment:
        raise InvalidInstallationTcServiceUrl(
            "tc_service_url must not contain a fragment"
        )
    return cleaned


def _validate_comercio_id(comercio_id: int) -> int:
    if (
        not isinstance(comercio_id, int)
        or isinstance(comercio_id, bool)
        or comercio_id <= 0
    ):
        raise InvalidInstallationIdentificador(
            "comercio_id must be a positive integer"
        )
    return int(comercio_id)


class InstalacionTwilioComercioService:
    """Business rules for the per-commerce installation registry.

    The service owns commit/rollback; the bounded provisioning CLI
    delegates the surrounding ``session.begin()`` to its caller.
    """

    def __init__(
        self,
        *,
        session: Session,
        master_keys: MasterKeyBundle,
        repo: InstalacionTwilioComercioRepository | None = None,
    ) -> None:
        self._session = session
        self._master_keys = master_keys
        self._repo = repo or InstalacionTwilioComercioRepository(session)

    def create_installation(
        self,
        *,
        comercio_id: int,
        tc_service_url: str,
    ) -> ProvisionedInstallation:
        """Provision a new installation and return the plain secret once.

        The function generates an opaque id, generates a 32-byte
        URL-safe secret, encrypts the secret with the current master
        key and stages the row through the repository. The plain
        secret is returned exactly once; the database row carries only
        the envelope and the key id.

        The "exactly one active installation per comercio" invariant
        is enforced by the database-level partial unique index
        ``uq_instalacion_twilio_one_active_per_comercio``: concurrent
        provisioners that try to insert a second active row for the
        same comercio receive an ``IntegrityError`` which the service
        translates to :class:`DuplicateInstalacionTwilioComercio`.

        The caller owns the surrounding transaction. ``commit`` is
        not performed here; the CLI performs the single commit /
        rollback after the service raises or returns.
        """
        validated_comercio_id = _validate_comercio_id(comercio_id)
        validated_tc_service_url = validate_tc_service_url(tc_service_url)

        instalacion_id = _generate_instalacion_id()
        plain_secret = generate_installation_secret()
        envelope, key_id = encrypt_secret(
            plain_secret=plain_secret, bundle=self._master_keys
        )

        try:
            row = self._repo.add(
                id_comercio=int(validated_comercio_id),
                tc_service_url=str(validated_tc_service_url),
                instalacion_id=str(instalacion_id),
                secreto_envelope=str(envelope),
                secreto_envelope_kid=str(key_id),
                activo=True,
            )
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateInstalacionTwilioComercio(
                "comercio already has an active installation; "
                "deactivate the previous one first"
            ) from exc

        return ProvisionedInstallation(
            instalacion_id=str(instalacion_id),
            comercio_id=int(validated_comercio_id),
            plain_secret=str(plain_secret),
            tc_service_url=str(validated_tc_service_url),
            row=row,
        )

    def decrypt_installation_secret(
        self, instalacion_id: str
    ) -> DecryptedInstallationSecret:
        """Decrypt the installation secret on demand for HMAC verification.

        The bounded ingress dependency holds the plain value only for
        the duration of the HMAC recomputation. The function does not
        log the plain value, does not return it in a response, and
        raises the typed ``InvalidInstallationSecretEnvelope`` on a
        missing or undecryptable envelope.
        """
        validated_id = _validate_instalacion_id(instalacion_id)
        row = self._repo.find_by_instalacion_id(validated_id)
        if row is None:
            raise InvalidInstallationSecretEnvelope(
                f"installation envelope row not found for id {validated_id}"
            )
        plain = decrypt_secret(
            envelope=str(row.secreto_envelope),
            key_id=str(row.secreto_envelope_kid),
            bundle=self._master_keys,
        )
        return DecryptedInstallationSecret(
            instalacion_id=str(row.instalacion_id),
            comercio_id=int(row.id_comercio),
            plain_secret=str(plain),
        )

    def deactivate_installation(self, instalacion_id: str) -> bool:
        """Mark an installation inactive.

        Returns ``True`` when the row existed and was active;
        ``False`` otherwise. The caller owns the surrounding
        transaction.
        """
        validated_id = _validate_instalacion_id(instalacion_id)
        return bool(
            self._repo.mark_inactive(instalacion_id=validated_id, fecha_baja=None)
        )


__all__ = [
    "DecryptedInstallationSecret",
    "InstalacionTwilioComercioService",
    "ProvisionedInstallation",
    "validate_tc_service_url",
]