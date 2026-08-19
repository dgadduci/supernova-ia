"""Bounded helper that posts canonical outbound commands to a T-C adapter.

The helper is the small, opt-in seam that lets the central outbound
dispatcher route an outbox row through a commerce-owned T-C adapter
when the documented feature flag is on **and** an active
``InstalacionTwilioComercio`` exists for the row's ``comercio_id``.

The helper is read-only w.r.t. NovaOrders state for the actual
``messages.create`` call: it stages no new outbox rows, opens no
SQLAlchemy session for the network call and commits no transaction on
the central dispatcher's outbox. The bounded CLI / central dispatcher
remains the single owner of the outbox lease, the durable row state and
the ``commit`` / ``rollback`` discipline. The helper's only persistent
effect is the durable ``instalaciones_twilio_comercio_idempotencia``
claim row.

Durable state machine
---------------------

The helper owns the claim lifecycle of the
``instalaciones_twilio_comercio_idempotencia`` row. The four
documented states map to the following contract:

* ``in_progress`` — the helper has staged the claim and has not yet
  seen a typed response from the T-C adapter. A subsequent dispatch
  short-circuits to the durable state without firing a second
  ``messages.create``. The state is also the durable marker for an
  ambiguous network result (timeout, connection drop, malformed body);
  the helper raises :class:`OutboundCommandAmbiguous` so the bounded
  CLI can finalize the outbox row as ``retryable`` while the
  durable claim remains ``in_progress`` for recovery. Concurrent
  claims on the same key serialise through the unique index and the
  atomic transition below; the loser returns the durable state
  without calling T-C.
* ``sent`` — the T-C adapter returned a SID. The claim is permanent
  in this phase; a second caller returns the durable SID without
  firing a second ``messages.create``. The claim is never deleted
  in this phase.
* ``retryable`` — the T-C adapter or the bounded CLI drove a
  bounded retryable failure. The claim is the explicit marker for
  "the next dispatch must perform a new HTTP call". The next
  dispatch atomically transitions the row to ``in_progress``
  through an ``UPDATE`` with a ``WHERE estado = 'retryable'``
  predicate, then performs the new HTTP call. Two concurrent
  callers on the same ``retryable`` row serialise through the
  predicate: only one wins and runs the new send; the other
  returns the durable state without calling T-C. The
  ``idempotency_key`` is preserved across the transition; the
  claim is never deleted; no in-memory dictionary is used.
* ``terminal`` — the T-C adapter returned a 4xx-class terminal
  failure. The claim is permanent; a second caller returns the
  durable state without firing a second ``messages.create``. The
  claim is never deleted in this phase.

Claim lifecycle (the durable part):

* the helper **first** tries to ``INSERT`` a fresh
  ``(instalacion_id, idempotency_key)`` claim row in ``in_progress``
  state through the unique database constraint — concurrent callers
  either win the insert and run the network call or lose the insert
  and fall through to the next phase;
* when the ``INSERT`` loses the race the helper **then** reads the
  existing row. If the row is in ``retryable`` the helper performs
  the atomic transition ``retryable -> in_progress`` through the
  repository; the row stays in ``in_progress`` for the new HTTP
  call. If the row is in any other state the helper returns the
  durable state without calling T-C;
* the helper **then** calls the T-C adapter with the same
  ``idempotency_key``;
* the helper **then** translates the typed T-C outcome into the
  same durable claim row (``sent`` / ``retryable`` / ``terminal``)
  and returns the typed result so the bounded CLI can finalize the
  existing outbox row in its own caller-owned transaction.

The helper uses two short transactions per HTTP call:

1. **Claim transaction** — opened on the supplied ``session_factory``,
   flushed, committed and closed. The claim is durable before the
   network call so a process restart cannot lose the ``INSERT``;
2. **HTTP call** — performed with no SQLAlchemy session open so the
   database never holds a transaction across the network round-trip;
3. **Finalize transaction** — opened on the same ``session_factory``
   after the HTTP call returns, committed and closed. The finalize is
   durable before the helper returns so a concurrent retry sees the
   typed outcome.

The two transactions never carry the outbox row, never touch the
central ``MensajeProveedorSaliente`` lease, and never share state
with the central dispatcher's caller-owned transaction. The bounded
CLI / central dispatcher stays the single owner of the outbox lease,
the finalize transaction and the commit / rollback discipline.

Failure / fallback contract:

* when the helper is disabled (``COMMERCE_ISOLATED_OUTBOUND_ENABLED``
  is ``False``) the helper raises :class:`OutboundCommandSkipped`
  and the central dispatcher falls back to the documented central
  Twilio path;
* when the helper is enabled but no active installation exists for
  the row's ``comercio_id`` the helper raises
  :class:`OutboundCommandSkipped` so the central dispatcher falls
  back to the documented central Twilio path;
* when the helper is enabled, the active installation exists and
  the helper successfully claims the idempotency slot the helper
  performs the HTTP call to the per-installation T-C URL — never
  to a global base URL — and never logs body, phone, token,
  signature or credential.

HTTP classification contract:

* ``200`` with a typed response — finalize the claim with the
  reported state (``sent`` / ``retryable`` / ``terminal``);
* ``400`` / ``401`` / ``403`` / ``404`` / ``409`` / ``422`` —
  finalize the claim as ``terminal`` with the documented safe
  code so the claim is never left ``in_progress`` because of a
  configuration drift. The list is closed;
* ``429`` and ``5xx`` — finalize the claim as ``retryable`` with the
  documented safe code so the bounded CLI drives the documented
  bounded retry path without firing a second ``messages.create``;
* the next dispatch on the same ``retryable`` row atomically
  transitions the row back to ``in_progress`` before performing a
  new HTTP call;
* any network failure (timeout, connection drop) — leave the claim
  ``in_progress`` and raise :class:`OutboundCommandAmbiguous`;
* an unparsable body on ``200`` — leave the claim ``in_progress``
  and raise :class:`OutboundCommandAmbiguous`;
* any unknown ``4xx`` status code — leave the claim ``in_progress``
  and raise :class:`OutboundCommandAmbiguous`. Unknown ``4xx``
  codes are never defaulted to ``retryable``: a silent
  misconfiguration cannot pollute the durable claim state.

The helper is the single owner of the
``instalaciones_twilio_comercio_idempotencia`` claim lifecycle.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import sessionmaker

from backend.config.settings import Settings
from backend.models.instalacion_twilio_comercio import InstalacionTwilioComercio
from backend.models.instalacion_twilio_comercio_idempotencia import (
    InstalacionTwilioComercioIdempotencia,
)
from backend.models.mensaje_proveedor_saliente import MensajeProveedorSaliente
from backend.models.recepcion_mensaje_proveedor import RecepcionMensajeProveedor
from backend.repositories.instalacion_twilio_comercio_idempotencia_repository import (
    InstalacionTwilioComercioIdempotenciaRepository,
)
from backend.repositories.instalacion_twilio_comercio_repository import (
    InstalacionTwilioComercioRepository,
)
from backend.schemas.commerce_installation_outbound_command import (
    CanonicalOutboundCommand,
    CanonicalOutboundResponse,
)
from backend.services.exceptions import (
    InvalidInstallationComandoSalida,
    InvalidInstallationTcServiceUrl,
)
from backend.services.instalacion_secret_envelope import (
    MasterKeyBundle,
    resolve_master_keys_from_env,
)
from backend.services.instalacion_twilio_comercio_service import (
    InstalacionTwilioComercioService,
)

logger = logging.getLogger(__name__)


SessionFactory = Callable[[], SqlSession]


class OutboundCommandSkipped(Exception):
    """Raised when the helper cannot route the row through the T-C.

    The bounded CLI / central dispatcher translates this exception
    into the existing dispatcher behaviour: the row stays in its
    current state and the central dispatcher falls back to the
    existing central Twilio send on the next pass.
    """


class OutboundCommandAmbiguous(Exception):
    """Raised when the helper cannot guarantee the durable outcome.

    The exception is the single boundary for the ambiguous-result
    contract described in the spec: the helper claimed the
    idempotency slot, performed the network call to the T-C
    adapter, and never received a typed response (timeout,
    connection drop, malformed body). The claim row is left in
    ``in_progress`` state so a retry with the same key either
    short-circuits to the existing durable state once the T-C
    adapter eventually answers, or keeps the durable
    ``in_progress`` marker so no second ``messages.create`` ever
    fires.
    """


@dataclass(frozen=True)
class ClaimDecision:
    """Outcome of the durable claim lifecycle.

    ``row`` is the durable
    :class:`InstalacionTwilioComercioIdempotencia` row.

    ``will_perform_http`` is ``True`` only when the helper owns the
    ``in_progress`` state and must perform a new HTTP call. The
    flag is ``False`` when the helper must return the durable state
    without calling T-C: a ``sent`` / ``terminal`` /
    ``in_progress`` row is permanent for this phase, and a concurrent
    transition on a ``retryable`` row returns ``False`` for the
    losing caller.
    """

    row: InstalacionTwilioComercioIdempotencia
    will_perform_http: bool


@dataclass(frozen=True)
class OutboundCommandResult:
    """Typed outcome of a single T-C adapter call."""

    status: str
    message_sid: str | None
    code: str | None
    http_status: int
    instalacion_id: str
    comercio_id: int


def _instalacion_marker(instalacion_id: str) -> str:
    if not isinstance(instalacion_id, str) or len(instalacion_id) < 6:
        return "short"
    return f"tail-{instalacion_id[-6:]}"


def _idempotency_marker(value: str) -> str:
    if not isinstance(value, str) or len(value) < 6:
        return "short"
    return f"tail-{value[-6:]}"


def _hmac_sign(payload: bytes, secret: str) -> str:
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    return hmac.new(
        secret.encode("utf-8"),
        bytes(payload),
        hashlib.sha256,
    ).hexdigest()


def _resolve_callback_url(settings: Settings) -> str | None:
    """Return the optional, validated ``status_callback_url``.

    The helper never invents a placeholder URL. When the operator
    does not configure ``TWILIO_CALLBACK_STATUS_URL`` the helper
    forwards ``None`` so the T-C adapter omits ``status_callback``
    from ``messages.create``.
    """
    raw = settings.twilio_callback_status_url
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    return cleaned


def _validate_inbound_target_url(value: str) -> str:
    """Validate the per-installation T-C service URL on the outbound path.

    The validator reuses the documented contract: HTTPS for public
    URLs, plain HTTP only for ``*.railway.internal`` hostnames, no
    credentials, no query string, no fragment.
    """
    parsed = urlparse(str(value))
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
        or hostname.endswith(".railway.internal")
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
    return str(value).rstrip("/")


def _build_canonical_command(
    *,
    outbox_row: MensajeProveedorSaliente,
    installation: InstalacionTwilioComercio,
    idempotency_key: str,
    status_callback_url: str | None,
) -> CanonicalOutboundCommand:
    mensaje = str(getattr(outbox_row, "cuerpo", "") or "")
    if not mensaje:
        raise InvalidInstallationComandoSalida(
            "outbox row has no body to send"
        )
    destinatario = str(getattr(outbox_row, "destinatario_e164", "") or "")
    if not destinatario:
        raise InvalidInstallationComandoSalida(
            "outbox row has no destination phone"
        )
    return CanonicalOutboundCommand(
        instalacion_id=str(installation.instalacion_id),
        comercio_id=int(installation.id_comercio),
        idempotency_key=str(idempotency_key),
        destinatario_e164=destinatario,
        cuerpo=mensaje,
        status_callback_url=status_callback_url,
        proveedor=str(getattr(outbox_row, "proveedor", "twilio")),
    )


def _resolve_comercio_id(
    *,
    session: SqlSession,
    outbox_row: MensajeProveedorSaliente,
) -> RecepcionMensajeProveedor | None:
    """Resolve the related receipt for the row.

    The ``MensajeProveedorSaliente`` row carries the
    ``recepcion_mensaje_proveedor_id`` foreign key; the related
    ``RecepcionMensajeProveedor`` carries the durable ``comercio_id``.
    A missing or unrelated receipt is treated as a no-op so the
    bounded CLI falls back to the central dispatcher.
    """
    recepcion_id = int(getattr(outbox_row, "recepcion_mensaje_proveedor_id", 0) or 0)
    if recepcion_id <= 0:
        return None
    return session.get(RecepcionMensajeProveedor, recepcion_id)


def _classify_non_success(status_code: int) -> tuple[str, str]:
    """Map a non-200 HTTP status to ``(estado, code)``.

    The mapping is the single boundary for the bounded CLI retry
    semantics described in the spec and is closed:

    * ``429`` — the provider or the gateway asked for a bounded
      retry; finalize the claim as ``retryable`` so the bounded
      CLI drives the documented bounded retry path without firing
      a second ``messages.create``;
    * ``5xx`` — same as ``429``: finalize as ``retryable``;
    * ``400`` / ``401`` / ``403`` / ``404`` / ``409`` / ``422`` —
      the request itself is rejected; finalize the claim as
      ``terminal`` so the bounded CLI does not block on a permanent
      misconfiguration. The list is closed and explicitly documented;
    * any other ``4xx`` — the helper raises
      :class:`OutboundCommandAmbiguous` so the bounded CLI
      finalizes the central outbox row as ``retryable`` while the
      durable claim row stays ``in_progress`` for recovery. The
      function never defaults an unknown ``4xx`` code to
      ``retryable``: a silent misconfiguration cannot pollute the
      durable claim state.
    """
    if status_code == 429:
        return "retryable", "http_429_rate_limited"
    if 500 <= status_code < 600:
        return "retryable", f"http_{status_code}_provider"
    if status_code in {400, 401, 403, 404, 409, 422}:
        if status_code == 400:
            return "terminal", "http_400_contract"
        return "terminal", f"http_{status_code}"
    if 400 <= status_code < 500:
        raise OutboundCommandAmbiguous(
            f"unknown 4xx status code from T-C adapter: "
            f"{status_code}"
        )
    raise OutboundCommandAmbiguous(
        f"unhandled status code from T-C adapter: {status_code}"
    )


class OutboundCommandDispatcher:
    """Bounded helper that posts canonical outbound commands to the T-C.

    The helper is intentionally narrow: it owns the HTTP call to the
    T-C adapter and the durable ``(instalacion_id, idempotency_key)``
    claim lifecycle only. The outbox row is read-only; the bounded
    CLI / central dispatcher owns the finalize transaction.

    The helper opens short-lived SQLAlchemy sessions on the supplied
    ``session_factory`` for the claim and the finalize so the network
    round-trip happens outside any database transaction and so the
    claim survives a process restart between the two transactions.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: Settings,
        master_keys: MasterKeyBundle | None = None,
        http_post: Any | None = None,
    ) -> None:
        if session_factory is None:
            raise ValueError(
                "OutboundCommandDispatcher requires a session_factory"
            )
        self._session_factory = session_factory
        self._settings = settings
        self._master_keys = master_keys
        self._http_post = http_post

    @classmethod
    def from_session(
        cls,
        *,
        session: SqlSession,
        settings: Settings,
        master_keys: MasterKeyBundle | None = None,
        http_post: Any | None = None,
    ) -> OutboundCommandDispatcher:
        """Build a helper from a single ``Session`` (legacy seam).

        The helper still opens fresh sessions for the claim and the
        finalize so the network round-trip happens outside any
        transaction. The supplied ``Session`` is only consulted for
        the installation lookup; the caller may keep it open for the
        duration of the helper call without leaking the outbox
        transaction into the claim or the finalize.
        """
        if session is None:
            raise ValueError(
                "OutboundCommandDispatcher.from_session requires a session"
            )
        engine = session.get_bind()
        factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        return cls(
            session_factory=factory,
            settings=settings,
            master_keys=master_keys,
            http_post=http_post,
        )

    def is_enabled(self) -> bool:
        """Return ``True`` when the helper is configured to dispatch.

        The helper is enabled when the feature flag is set. The
        installation lookup is per-row and is performed inside
        :meth:`dispatch`.
        """
        return bool(self._settings.commerce_isolated_outbound_enabled)

    def _open_read_session(self) -> SqlSession:
        return self._session_factory()

    def _open_claim_session(self) -> SqlSession:
        return self._session_factory()

    def _open_finalize_session(self) -> SqlSession:
        return self._session_factory()

    def _resolve_installation(
        self,
        *,
        comercio_id: int,
    ) -> InstalacionTwilioComercio | None:
        session = self._open_read_session()
        try:
            repo = InstalacionTwilioComercioRepository(session)
            return repo.find_active_by_comercio_id(int(comercio_id))
        finally:
            session.close()

    def _decrypt_secret(
        self,
        *,
        session: SqlSession,
        instalacion_id: str,
        bundle: MasterKeyBundle,
    ) -> str:
        decrypted = InstalacionTwilioComercioService(
            session=session, master_keys=bundle
        ).decrypt_installation_secret(str(instalacion_id))
        return str(decrypted.plain_secret)

    def _claim_slot(
        self,
        *,
        instalacion_id: str,
        idempotency_key: str,
    ) -> ClaimDecision:
        """Claim the slot through the durable state machine.

        The claim lifecycle is the single source of truth that
        prevents a second ``messages.create`` call:

        1. **Phase 1 (fresh claim)** — try to ``INSERT`` a fresh
           ``in_progress`` row through the unique database
           constraint. The winning caller transitions to phase 2
           with ``will_perform_http=True``;
        2. **Phase 2 (retryable transition)** — when the ``INSERT``
           loses the race and the existing row is in ``retryable``
           state, atomically transition the row to ``in_progress``
           through a single ``UPDATE ... WHERE estado = 'retryable'``
           statement. The winning caller transitions to phase 2
           with ``will_perform_http=True``; the loser's update
           affects zero rows and falls through to phase 3;
        3. **Phase 3 (durable state)** — read the existing row and
           return the durable state with ``will_perform_http=False``.
           ``sent`` / ``terminal`` / ``in_progress`` are permanent
           for this phase; no second ``messages.create`` call fires.

        Each phase opens its own short-lived SQLAlchemy session and
        commits before returning. The helper never carries a
        transaction across the network call and never relies on a
        process-local dictionary for the duplicate-send guarantee.
        The database is the serialisation point.
        """
        claim_session = self._open_claim_session()
        existing_row: InstalacionTwilioComercioIdempotencia | None = None
        already_claimed = False
        insert_worked = False
        try:
            repo = InstalacionTwilioComercioIdempotenciaRepository(claim_session)
            try:
                existing_row, already_claimed = repo.claim_in_progress(
                    instalacion_id=str(instalacion_id),
                    idempotency_key=str(idempotency_key),
                )
                claim_session.commit()
                insert_worked = not already_claimed
            except IntegrityError:
                claim_session.rollback()
                existing_row, already_claimed = repo.claim_in_progress(
                    instalacion_id=str(instalacion_id),
                    idempotency_key=str(idempotency_key),
                )
                claim_session.commit()
                insert_worked = not already_claimed
        finally:
            claim_session.close()

        if insert_worked:
            assert existing_row is not None
            return ClaimDecision(row=existing_row, will_perform_http=True)

        if already_claimed:
            assert existing_row is not None
            if str(existing_row.estado) == "retryable":
                transition_session = self._open_claim_session()
                try:
                    transition_repo = (
                        InstalacionTwilioComercioIdempotenciaRepository(
                            transition_session
                        )
                    )
                    won = transition_repo.transition_retryable_to_in_progress(
                        instalacion_id=str(instalacion_id),
                        idempotency_key=str(idempotency_key),
                    )
                    transition_session.commit()
                    if won:
                        refreshed = transition_repo.find(
                            instalacion_id=str(instalacion_id),
                            idempotency_key=str(idempotency_key),
                        )
                        if refreshed is not None:
                            return ClaimDecision(
                                row=refreshed, will_perform_http=True
                            )
                        existing_row = refreshed
                finally:
                    transition_session.close()

        durable_session = self._open_claim_session()
        try:
            durable_repo = InstalacionTwilioComercioIdempotenciaRepository(
                durable_session
            )
            durable_row = durable_repo.find(
                instalacion_id=str(instalacion_id),
                idempotency_key=str(idempotency_key),
            )
            if durable_row is None:
                raise OutboundCommandAmbiguous(
                    "durable idempotency claim row vanished "
                    "during claim lifecycle"
                )
            return ClaimDecision(row=durable_row, will_perform_http=False)
        finally:
            durable_session.close()

    def _finalize_slot(
        self,
        *,
        instalacion_id: str,
        idempotency_key: str,
        estado: str,
        message_sid: str | None,
        codigo: str | None,
        http_status: int | None,
    ) -> None:
        """Finalize the claim in its own short transaction.

        The transaction is committed before this function returns so
        the typed outcome is durable for any concurrent retry that
        runs on a different process.
        """
        session = self._open_finalize_session()
        try:
            repo = InstalacionTwilioComercioIdempotenciaRepository(session)
            repo.finalize(
                instalacion_id=str(instalacion_id),
                idempotency_key=str(idempotency_key),
                estado=str(estado),
                message_sid=message_sid,
                codigo=codigo,
                http_status=http_status,
            )
            session.commit()
        finally:
            session.close()

    def dispatch(
        self,
        *,
        outbox_row: MensajeProveedorSaliente,
    ) -> OutboundCommandResult:
        """POST the canonical command for ``outbox_row`` to the T-C.

        The function raises :class:`OutboundCommandSkipped` when the
        helper is disabled, no active installation exists for the
        row's ``comercio_id`` or the row carries no related
        receipt. It raises :class:`OutboundCommandAmbiguous` when
        the network call did not return a typed response so the
        bounded CLI can finalize the outbox row as ``retryable``
        while the durable claim remains ``in_progress``.

        On a successful typed outcome the helper finalizes the
        durable claim row in its own short transaction and returns
        the typed :class:`OutboundCommandResult`. The outbox row is
        never touched by the helper; the central dispatcher stays
        the single owner of the outbox lease, the finalize
        transaction and the commit / rollback discipline.
        """
        if not self.is_enabled():
            raise OutboundCommandSkipped("outbound command helper is disabled")

        outbox_id = int(outbox_row.id)
        idempotency_key = f"outbox-{outbox_id}"

        read_session = self._open_read_session()
        try:
            recepcion = _resolve_comercio_id(
                session=read_session, outbox_row=outbox_row
            )
            if recepcion is None:
                raise OutboundCommandSkipped(
                    "outbox row has no related receipt"
                )
            comercio_id = int(recepcion.comercio_id)
            bundle = self._master_keys or resolve_master_keys_from_env()
        finally:
            read_session.close()

        installation = self._resolve_installation(comercio_id=comercio_id)
        if installation is None:
            raise OutboundCommandSkipped(
                f"no active installation for comercio_id={comercio_id}"
            )

        base_url = _validate_inbound_target_url(
            str(getattr(installation, "tc_service_url", "") or "")
        )

        secret_session = self._open_read_session()
        try:
            bundle = self._master_keys or resolve_master_keys_from_env()
            plain_secret = self._decrypt_secret(
                session=secret_session,
                instalacion_id=str(installation.instalacion_id),
                bundle=bundle,
            )
        finally:
            secret_session.close()

        decision = self._claim_slot(
            instalacion_id=str(installation.instalacion_id),
            idempotency_key=idempotency_key,
        )
        if not decision.will_perform_http:
            logger.info(
                "core_outbound_command_attempt",
                extra={
                    "instalacion_id": _instalacion_marker(
                        str(installation.instalacion_id)
                    ),
                    "comercio_id": int(installation.id_comercio),
                    "outbox_id": outbox_id,
                    "idempotency_key": _idempotency_marker(idempotency_key),
                    "status": "durable_state",
                    "durable_state": str(decision.row.estado),
                },
            )
            return OutboundCommandResult(
                status=str(decision.row.estado),
                message_sid=decision.row.message_sid,
                code=decision.row.codigo,
                http_status=int(decision.row.http_status or 0),
                instalacion_id=str(installation.instalacion_id),
                comercio_id=int(installation.id_comercio),
            )

        command = _build_canonical_command(
            outbox_row=outbox_row,
            installation=installation,
            idempotency_key=idempotency_key,
            status_callback_url=_resolve_callback_url(self._settings),
        )

        payload = command.model_dump_json().encode("utf-8")
        signature = _hmac_sign(payload, plain_secret)
        url = base_url.rstrip("/") + "/internal/commands/send-message"
        headers = {
            "Content-Type": "application/json",
            "X-Installation-Signature": signature,
            "X-Installation-Id": str(installation.instalacion_id),
        }

        try:
            if self._http_post is None:
                import httpx

                with httpx.Client(
                    timeout=float(
                        self._settings.commerce_isolated_http_timeout_seconds
                    )
                ) as client:
                    response = self._do_post(client, url, payload, headers)
            else:
                response = self._http_post(
                    url=url, payload=payload, headers=headers
                )
        except Exception as exc:
            logger.info(
                "core_outbound_command_attempt",
                extra={
                    "instalacion_id": _instalacion_marker(
                        str(installation.instalacion_id)
                    ),
                    "comercio_id": int(installation.id_comercio),
                    "outbox_id": outbox_id,
                    "idempotency_key": _idempotency_marker(idempotency_key),
                    "status": "ambiguous",
                    "error": type(exc).__name__,
                },
            )
            raise OutboundCommandAmbiguous(
                "T-C adapter network call failed before a typed "
                "response arrived; the durable claim remains in "
                "in_progress"
            ) from exc

        status_code = int(getattr(response, "status_code", 0) or 0)
        body_text = getattr(response, "text", "") or ""
        body_json: dict[str, Any] = {}
        if body_text:
            try:
                raw_body = json.loads(str(body_text))
            except ValueError:
                raw_body = None
            if isinstance(raw_body, dict):
                body_json = raw_body

        if status_code == 200:
            try:
                parsed = CanonicalOutboundResponse.model_validate(body_json)
            except Exception as exc:
                logger.info(
                    "core_outbound_command_attempt",
                    extra={
                        "instalacion_id": _instalacion_marker(
                            str(installation.instalacion_id)
                        ),
                        "comercio_id": int(installation.id_comercio),
                        "outbox_id": outbox_id,
                        "idempotency_key": _idempotency_marker(
                            idempotency_key
                        ),
                        "status": "ambiguous",
                        "error": type(exc).__name__,
                    },
                )
                raise OutboundCommandAmbiguous(
                    "T-C adapter returned an unparsable response"
                ) from exc
            self._finalize_slot(
                instalacion_id=str(installation.instalacion_id),
                idempotency_key=idempotency_key,
                estado=str(parsed.status),
                message_sid=parsed.message_sid,
                codigo=parsed.code,
                http_status=status_code,
            )
            logger.info(
                "core_outbound_command_attempt",
                extra={
                    "instalacion_id": _instalacion_marker(
                        str(installation.instalacion_id)
                    ),
                    "comercio_id": int(installation.id_comercio),
                    "outbox_id": outbox_id,
                    "idempotency_key": _idempotency_marker(idempotency_key),
                    "status": str(parsed.status),
                    "provider_code": parsed.code,
                    "http_status": status_code,
                },
            )
            return OutboundCommandResult(
                status=str(parsed.status),
                message_sid=parsed.message_sid,
                code=parsed.code,
                http_status=status_code,
                instalacion_id=str(installation.instalacion_id),
                comercio_id=int(installation.id_comercio),
            )

        try:
            estado, code = _classify_non_success(status_code)
        except OutboundCommandAmbiguous as exc:
            logger.info(
                "core_outbound_command_attempt",
                extra={
                    "instalacion_id": _instalacion_marker(
                        str(installation.instalacion_id)
                    ),
                    "comercio_id": int(installation.id_comercio),
                    "outbox_id": outbox_id,
                    "idempotency_key": _idempotency_marker(
                        idempotency_key
                    ),
                    "status": "ambiguous",
                    "http_status": status_code,
                    "error": type(exc).__name__,
                },
            )
            raise
        self._finalize_slot(
            instalacion_id=str(installation.instalacion_id),
            idempotency_key=idempotency_key,
            estado=estado,
            message_sid=None,
            codigo=code,
            http_status=status_code,
        )
        logger.info(
            "core_outbound_command_attempt",
            extra={
                "instalacion_id": _instalacion_marker(
                    str(installation.instalacion_id)
                ),
                "comercio_id": int(installation.id_comercio),
                "outbox_id": outbox_id,
                "idempotency_key": _idempotency_marker(idempotency_key),
                "status": estado,
                "provider_code": code,
                "http_status": status_code,
            },
        )
        return OutboundCommandResult(
            status=estado,
            message_sid=None,
            code=code,
            http_status=status_code,
            instalacion_id=str(installation.instalacion_id),
            comercio_id=int(installation.id_comercio),
        )

    def _do_post(
        self,
        client: Any,
        url: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> Any:
        return client.post(url, content=payload, headers=headers)


__all__ = [
    "ClaimDecision",
    "OutboundCommandAmbiguous",
    "OutboundCommandDispatcher",
    "OutboundCommandResult",
    "OutboundCommandSkipped",
    "SessionFactory",
]