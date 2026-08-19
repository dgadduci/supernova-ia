# Proposal: add commerce isolated Twilio edge

## Objective

Connect NovaOrders to its first commerce-owned Twilio (T-C) adapter so the
existing central Twilio webhook and dispatcher can run in parallel with a
real, isolated, commerce-provisioned T-C adapter. The change keeps the
current central Twilio surface untouched, preserves every existing commerce
flow, and adds the minimum technical registry, signed webhook bridge,
canonical event contract, internal NovaOrders ingress endpoint, and
authenticated outbound command path required to operate one T-C adapter per
commerce.

The T-C adapter is an isolated FastAPI service that wraps the merchant's
Twilio account. NovaOrders never receives the merchant webhook directly and
never holds merchant Twilio credentials. The first version does not migrate
or delete the central Twilio webhook and dispatcher; that is a separately
approved, later stage.

## Current execution path

Today NovaOrders owns the only Twilio surface in the repository:

- `backend/routers/twilio_webhook.py` exposes the public webhook and
  delegates to the central provider inbound coordinator.
- `backend/services/provider_inbound_message_coordinator.py` claims the
  receipt, stages deferred work and routes through the central pipeline.
- `backend/services/outbound_message_dispatcher.py` is the central Twilio
  outbox driver.
- The dispatcher is wired to `backend/services/twilio_outbound_adapter.py`,
  which is the only component that knows how to call
  ``twilio.rest.Client.messages.create``.
- `CanalWhatsapp`, ``RecepcionesMensajeProveedor`` and
  ``MensajesProveedorSaliente`` are the durable records produced by this
  flow.

There is no installation concept for a per-commerce T-C adapter. There is
no canonical inbound contract decoupled from Twilio field names. There is
no internal, installation-authenticated endpoint that accepts events from
an external adapter, and the central dispatcher uses NovaOrders-owned
Twilio credentials.

The current webhook and dispatcher remain operational throughout this
change so the existing pilot and any production traffic continue to flow.
The new bridge only operates for commerces that already have a
``CanalWhatsapp`` row registered for their merchant sender and for which an
installation has been provisioned in NovaOrders.

## Target provider boundary

```text
Customer WhatsApp
      │
      ▼
Merchant Meta/WABA/Twilio sender
      │ signed form webhook
      ▼
Commerce Railway service: T-C adapter
      │ signed canonical event
      ▼
NovaOrders core (authenticated internal ingress)
      │ reuse existing coordinator/outbox
      │ one idempotent outbound command
      ▼
Commerce Railway service: T-C adapter ── one Twilio API send ──► merchant Twilio account
      │
      └── empty <Response></Response> acknowledgement to inbound webhook
```

The T-C adapter is **one Railway service per installation** (the same
adapter code deployed once per commerce). The service may live in the
main Railway ``core`` project (using Railway private networking to reach
NovaOrders) or in any other Railway project (using HTTPS authenticated by
the per-installation shared secret). The URL of every T-C service is
stored on its ``InstalacionTwilioComercio`` row under
``tc_service_url`` so the dispatcher always uses the exact per-commerce
URL — there is no global ``tc_project_url`` / ``tc_service_url`` /
``COMMERCE_ISOLATED_TC_BASE_URL`` value that drives routing.

The T-C adapter is the only component that holds the merchant Twilio
credentials and is the only component that signs its webhook. NovaOrders is
the only component that owns the durable receipt and the existing outbox.
The adapter never reaches into NovaOrders business state directly and
NovaOrders never accepts a raw Twilio field set on the inbound path.

## Scope

- Add one durable technical installation row per commerce in NovaOrders
  that stores: ``comercio_id``, ``tc_service_url`` (per-installation T-C
  service URL — same adapter code, different Railway services), an opaque
  fixed-length ``instalacion_id``, ``activo``, ``fecha_alta``,
  ``fecha_ultima_modificacion``, ``fecha_baja`` plus the encryption
  envelope of a per-installation shared secret used to authenticate the
  adapter. A database-level partial unique index on
  ``(id_comercio) WHERE activo = true`` enforces "exactly one active
  installation per comercio" — concurrent provisioners cannot insert two
  active rows.
- Add a small, operational idempotency registry
  (``instalaciones_twilio_comercio_idempotencia``) keyed on
  ``(instalacion_id, idempotency_key)`` so the T-C adapter performs
  exactly one ``messages.create`` per outbound command even under
  concurrent dispatchers and even when a retry follows a network timeout.
  The table carries no pedido, no cliente, no canal, no catalog state.
- Add one Fernet-based envelope service (``encryption-at-rest``) that uses
  a server-side master key loaded from ``COMMERCE_INSTALLATION_MASTER_KEY``.
  The plain secret never persists and never appears in logs or in the
  owner panel.
- Add one internal, installation-authenticated ingress endpoint
  (``POST /internal/commerce-installation/{instalacion_id}/accept-event``)
  that validates the inbound event, resolves the destination against the
  existing ``CanalWhatsapp`` and ``Cliente`` authority for that
  installation's commerce, and delegates to the existing
  ``ProviderInboundMessageCoordinator``. The endpoint is idempotent by
  ``(proveedor, identificador_recepcion)`` exactly like the central webhook.
- Wire the new ``OutboundCommandDispatcher`` helper into the existing
  ``OutboundMessageDispatcher.dispatch()`` flow so the central dispatcher
  delegates one row's network call to the helper when
  ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` and an active installation
  exists for the row's ``comercio_id``. When the flag is off or no active
  installation exists the dispatcher falls back to the documented central
  Twilio path on the same row.
- Add one commerce-owned T-C adapter service under ``commerce_adapter/``:
  - configuration via environment variables only — the adapter fails
    closed at startup when any required value is missing or malformed;
  - ``GET /health`` health endpoint;
  - ``POST /webhooks/twilio/whatsapp/inbound`` Twilio webhook that validates
    ``X-Twilio-Signature`` against the exact public URL configured for
    that merchant, normalizes the form into the canonical event contract,
    forwards the event to NovaOrders with an HMAC signature derived from
    the installation secret, and returns an empty TwiML
    (``<Response></Response>``) only after NovaOrders confirms acceptance.
    If NovaOrders is unreachable, the endpoint returns a non-success
    status so Twilio retries.
  - ``POST /internal/commands/send-message`` authenticated command endpoint
    that validates ``X-Installation-Id`` against the local installation,
    ``X-Installation-Signature`` against the body, the ``instalacion_id``
    and ``comercio_id`` body fields against the local configuration, then
    performs exactly one ``Client.messages.create`` through the merchant
    Twilio account. The ``status_callback_url`` field is optional and
    omitted from ``messages.create`` when ``TWILIO_CALLBACK_STATUS_URL``
    is not configured — no placeholder URL is ever persisted.
  - ``scripts/twilio_messages_client.py`` Twilio client seam used by both
    routes; tests inject a fake ``TwilioMessagesClient`` and never perform
    a network call.
  - focused tests for the contract surface.
- Fail closed at NovaOrders process startup: a missing or invalid
  ``COMMERCE_INSTALLATION_MASTER_KEY`` when
  ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` (or when the internal ingress
  is enabled) prevents ``uvicorn`` from accepting traffic instead of
  returning a 503 on the first request.

## Non-goals

- No deletion of ``backend/routers/twilio_webhook.py`` or the central
  dispatcher.
- No migration or cutover of an existing pilot to the T-C adapter.
- No modification of the self-service onboarding flow or any of its
  artifacts.
- No Twilio credentials stored in NovaOrders, in the owner panel or in any
  log.
- No change to fuzzy, hybrid or product recognition, pending candidate
  behavior, fuzzy fallback policy, lifecycle/trial policy, catalogue
  flows, payment or delivery configuration, or owner wizard.
- No new ``CanalWhatsapp``/``MensajeProveedorSaliente`` shape: the existing
  tables and outbox are reused unchanged.
- No sandbox-vs-production branching in the contract shape. The same
  canonical adapter contract and the same canonical event shape serve both
  sandbox and production; only provider configuration, capabilities and
  sender numbers differ.

## Shared boundary, outcomes, and fallback

### Authoritative outcomes

The bridge has three authoritative outcomes:

1. **Inbound accepted.** The T-C adapter forwards the canonical event to
   NovaOrders, NovaOrders accepts it through the existing coordinator
   (``ProviderInboundMessageStatus.ACCEPTED`` or
   ``ALREADY_PROCESSED``), and the adapter returns the empty TwiML.
2. **Inbound rejection.** NovaOrders reports
   ``ProviderInboundMessageStatus.INVALID_CONTEXT`` or an analogous
   documented rejection, or the central channel authority reports
   ``unknown_channel`` / ``inactive_channel``. The adapter returns the
   empty TwiML because the event was durably classified as a no-op for
   this commerce; it does not invent a provider success.
3. **Outbound delivered.** NovaOrders stages an outbound command, the
   adapter validates the installation + signature + idempotency, performs
   exactly one ``messages.create``, and returns the SID + status. The
   existing outbox row is the single durable proof.

### Technical failures

The following are technical failures and never a documented business
outcome:

- Twilio signature missing/malformed/invalid → adapter returns a
  non-success HTTP status without TwiML. The Twilio webhook will retry.
- T-C missing/invalid configuration → the adapter fails closed (HTTP 5xx)
  for every request. No Twilio acknowledgement is returned.
- NovaOrders unreachable or returns 5xx → the adapter returns a
  non-success HTTP status so Twilio retries.
- ``messages.create`` returning 5xx / 429 → the adapter reports the
  failure to NovaOrders; the outbox row stays in its current
  ``retryable`` state until the bounded CLI re-tries.
- Missing/invalid HMAC signature on the NovaOrders ingress → HTTP 401 and
  no coordinator call.
- ``COMMERCE_INSTALLATION_MASTER_KEY`` missing or invalid → startup fails
  closed. No installation can be created and no event can be accepted.
- ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` and the bounded outbound
  helper cannot claim the per-installation idempotency slot due to a
  concurrent caller → the second caller returns ``already_claimed`` and
  zero ``messages.create`` calls fire.

### Conditions that must NOT trigger fallback

- The adapter must NOT fall back to NovaOrders central credentials when its
  own credentials are missing.
- The adapter must NOT retry the Twilio API in the webhook path; that is
  the bounded CLI's job.
- NovaOrders must NOT accept an inbound event whose
  ``instalacion_id``/``comercio_id`` pair fails the installation lookup.
- NovaOrders must NOT pick a different commerce if the destination does
  not resolve for the supplied installation.
- NovaOrders must NOT replay a previous TwiML acknowledgement or send a
  second ``messages.create`` for the same idempotency key.

## Transaction ownership

- The T-C adapter never opens a SQLAlchemy session.
- The T-C adapter never commits, rolls back or mutates NovaOrders state.
- The NovaOrders internal ingress endpoint uses the existing
  ``ProviderInboundMessageCoordinator`` as the sole transaction owner for
  inbound acceptance.
- The NovaOrders outbound command path uses the existing
  ``MensajeProveedorSalienteRepository`` to stage the outbox row in the
  same caller-owned transaction. The bounded ``OutboundCommandDispatcher``
  helper owns the per-installation idempotency claim
  (``instalaciones_twilio_comercio_idempotencia``) in two short
  transactions that are deliberately separate from the central
  dispatcher's caller-owned outbox transaction:
  - **Claim transaction** — a short-lived ``INSERT`` of a fresh
    ``in_progress`` claim (or an atomic ``UPDATE ... WHERE estado =
    'retryable'`` transition on an existing claim) opened on the
    helper's ``session_factory``. The transaction is committed and
    closed before the network call so the claim is durable across a
    process restart and the database never holds a transaction across
    the network round-trip;
  - **Finalize transaction** — a short-lived write of the typed
    outcome (``sent`` / ``retryable`` / ``terminal``) or a leave-alone
    for the ambiguous path, opened on the same ``session_factory``
    after the HTTP call returns. The transaction is committed and
    closed before the helper returns so a concurrent retry running on
    a different process sees the durable outcome.
  The two transactions never carry the outbox row, never touch the
  central ``MensajeProveedorSaliente`` lease and never share state
  with the central dispatcher's caller-owned transaction. The bounded
  CLI / central dispatcher stays the single owner of the outbox
  lease, the finalize transaction and the commit / rollback
  discipline.
- The T-C outbound command endpoint never mutates NovaOrders state; it
  returns the SID + status and lets the bounded CLI reconcile the row.

## Ambiguous-result handling (central dispatcher / helper seam)

The helper raises :class:`OutboundCommandAmbiguous` when the network
call to the T-C adapter returns no typed response (timeout, connection
drop, malformed body, invalid ``CanonicalOutboundResponse`` or
unknown 4xx status code). The central
``OutboundMessageDispatcher.dispatch()`` flow catches the exception,
translates it to a typed ``OutboundCommandResult`` whose ``status`` is
``"in_progress"`` and finalizes the central
``MensajeProveedorSaliente`` outbox row as ``retryable`` through its
existing caller-owned finalize transaction. The central dispatcher
never falls back to the documented central Twilio path for an
ambiguous result: the bounded CLI / outbox lease stays the single
owner of the row and the next dispatch drives the documented bounded
retry path on the same row. The helper leaves the durable
``instalaciones_twilio_comercio_idempotencia`` claim row in
``in_progress`` state so a retry on the same key short-circuits to
the durable state without firing a second ``messages.create`` — the
duplicate-send protection is preserved across the ambiguous result.

## Closed HTTP classification

The helper classifies non-200 HTTP responses per a closed policy:

- ``429`` — ``retryable`` with ``code="http_429_rate_limited"``;
- ``5xx`` — ``retryable`` with ``code="http_<status>_provider"``;
- ``400`` / ``401`` / ``403`` / ``404`` / ``409`` / ``422`` —
  ``terminal`` with ``code="http_<status>"``;
- any other ``4xx`` — treated as an ambiguous result. The helper
  raises :class:`OutboundCommandAmbiguous` so the bounded CLI
  finalizes the central outbox row as ``retryable`` while the
  durable claim row stays ``in_progress`` for recovery. No second
  ``messages.create`` call fires.

The mapping is the single boundary for the bounded CLI retry
semantics. Unknown ``4xx`` codes are never defaulted to
``retryable``: an undocumented ``4xx`` is treated as ambiguous so a
silent misconfiguration cannot pollute the durable claim state.

## Closed ``CanonicalOutboundResponse`` contract

``CanonicalOutboundResponse`` is the canonical typed response sent
back by the T-C adapter. The contract is closed:

- ``status`` is restricted to the documented set
  ``{"sent", "retryable", "terminal"}``;
- ``message_sid`` MUST be a non-empty string whenever
  ``status == "sent"`` and MUST be ``None`` otherwise;
- ``code`` is optional and limited to documented safe codes;
- any extra field is rejected by the ``extra="forbid"`` policy.

An invalid response — unknown ``status``, missing
``message_sid`` on ``"sent"``, extra fields, malformed body —
is treated as an ambiguous result. The helper raises
:class:`OutboundCommandAmbiguous` so the bounded CLI finalizes the
central outbox row as ``retryable`` while the durable claim row
stays ``in_progress`` for recovery. The helper NEVER finalizes the
durable claim with an invalid state and NEVER fires a second
``messages.create`` call after an invalid response.

## Security, isolation and fallback

- Each commerce owns exactly one active installation at a time. A second
  active installation for the same comercio is refused by the
  database-level partial unique index
  ``uq_instalacion_twilio_one_active_per_comercio`` — concurrent
  provisioners cannot insert two active rows. A previously deactivated
  installation does not block a new one.
- The plain installation secret is never stored. NovaOrders stores only
  the Fernet envelope produced by
  ``COMMERCE_INSTALLATION_MASTER_KEY`` and decrypts on demand only inside
  the bounded ingress dependency. The plain value is never logged, never
  returned in a response, and never accepted from a browser or any
  external request.
- The ``instalacion_id`` is opaque, fixed-length and is the single
  selector for the ingress path; ``comercio_id`` in the body is treated
  as untrusted hint and re-resolved against the installation row.
- Per-installation T-C service URLs are validated by the bounded
  provisioning CLI: HTTPS only for public URLs, plain HTTP only for
  Railway private networking (``*.railway.internal``), credentials /
  query string / fragment are always rejected.
- The T-C adapter only logs event names, status categories, and bounded
  identifiers. Body, phone, token, signature, and raw Twilio payloads are
  never logged in either service.
- A missing or invalid installation fails closed for that commerce. The
  adapter never falls back to a different installation.

## Observability

- T-C adapter emits one ``commerce_adapter_inbound_outcome`` event per
  inbound request carrying only: ``instalacion_id`` tail,
  ``comercio_id``, ``message_sid_tail``, ``status``,
  ``resolution_source``.
- T-C adapter emits one ``commerce_adapter_outbound_attempt`` event per
  outbound command carrying only: ``instalacion_id`` tail, ``comercio_id``,
  ``idempotency_key_tail``, ``status`` and (when known) the safe provider
  code and HTTP status.
- NovaOrders ingress emits one ``core_inbound_acceptance`` event
  carrying only the existing safe coordinator payload plus the
  installation tail.
- NovaOrders outbound helper emits one ``core_outbound_command_attempt``
  event per attempt carrying only: ``instalacion_id`` tail, ``comercio_id``,
  ``outbox_id``, ``idempotency_key_tail``, ``status``,
  ``durable_state`` and (when known) the safe provider code and HTTP
  status.
- No raw message bodies, phones, signatures or credentials appear in any
  log.

## Expected files

### New files in NovaOrders core

- ``backend/models/instalacion_twilio_comercio.py`` (model)
- ``backend/models/instalacion_twilio_comercio_idempotencia.py`` (model)
- ``backend/repositories/instalacion_twilio_comercio_repository.py``
- ``backend/repositories/instalacion_twilio_comercio_idempotencia_repository.py``
- ``backend/services/instalacion_twilio_comercio_service.py``
- ``backend/services/instalacion_secret_envelope.py`` (Fernet envelope)
- ``backend/services/outbound_command_dispatcher.py`` (per-installation
  T-C helper wired into the central dispatcher)
- ``backend/services/exceptions.py`` extended with
  ``InvalidInstallationSecretEnvelope``,
  ``InvalidInstallationMasterKey``,
  ``InvalidInstallationTcServiceUrl`` and
  ``InvalidInstallationComandoSalida``
- ``backend/routers/internal_commerce_installation.py`` (private ingress)
- ``backend/schemas/commerce_installation_event.py`` (canonical inbound
  contract)
- ``backend/schemas/commerce_installation_outbound_command.py`` (canonical
  outbound command contract)
- ``backend/alembic/versions/<new>_add_instalaciones_twilio_comercio.py``
- ``backend/tests/test_instalacion_twilio_comercio_model.py``
- ``backend/tests/test_instalacion_secret_envelope.py``
- ``backend/tests/test_internal_commerce_installation_ingress.py``
- ``backend/tests/test_outbound_message_dispatcher.py``

### New files in the T-C adapter

- ``commerce_adapter/__init__.py``
- ``commerce_adapter/pyproject.toml`` (minimal, optional)
- ``commerce_adapter/requirements.txt`` (minimal, optional)
- ``commerce_adapter/README.md`` (operator/setup notes)
- ``commerce_adapter/app/__init__.py``
- ``commerce_adapter/app/config.py``
- ``commerce_adapter/app/main.py``
- ``commerce_adapter/app/schemas.py``
- ``commerce_adapter/app/security.py`` (HMAC + Twilio signature helpers)
- ``commerce_adapter/app/canonical_event.py`` (provider-to-canonical
  mapping)
- ``commerce_adapter/app/novaorders_client.py``
- ``commerce_adapter/app/twilio_client.py``
- ``commerce_adapter/app/routes/health.py``
- ``commerce_adapter/app/routes/webhook.py``
- ``commerce_adapter/app/routes/outbound.py``
- ``commerce_adapter/tests/__init__.py``
- ``commerce_adapter/tests/test_signature_validation.py``
- ``commerce_adapter/tests/test_canonical_event.py``
- ``commerce_adapter/tests/test_webhook_route.py``
- ``commerce_adapter/tests/test_outbound_route.py``
- ``commerce_adapter/tests/test_security_no_secrets.py``

### Modified files in NovaOrders core

- ``backend/models/__init__.py`` (export the new models)
- ``backend/alembic/env.py`` (import the new models for autogenerate)
- ``backend/services/exceptions.py`` (add the new exception types)
- ``backend/services/outbound_message_dispatcher.py`` (delegate to the
  bounded helper when the flag is on)
- ``backend/services/twilio_outbound_adapter.py`` (make
  ``status_callback_url`` optional)
- ``backend/cli/run_outbound_dispatch.py`` (no longer require callback
  URL)
- ``backend/main.py`` (startup fail-closed when the master key is
  missing or invalid)
- ``backend/config/settings.py`` (rename ``commerce_isolated_tc_base_url``
  to ``commerce_isolated_tc_base_url_legacy`` for backward
  compatibility; the dispatcher never uses it)

## Out of scope

The following remain explicitly out of scope and are not introduced by this
change:

- Owner self-service setup of the installation. The owner panel does not
  expose or manage the installation.
- Operator CLI for installation lifecycle. The current changeset exposes
  only the bounded test/CLI seam; an operator surface is a later change.
- Project provisioning, secret delivery, rotation or deprovisioning.
- Removal of the central Twilio webhook and dispatcher.
- A native NovaOrders chat channel.
- Multiple ``CanalWhatsapp`` rows for the same commerce sender, shared
  WhatsApp channels, or shared selector logic.

## Validation

The implementer must run locally and report complete output for the
focused command set:

```text
PYTHONPATH=. venv/bin/python -m pytest commerce_adapter/tests backend/tests/test_instalacion_twilio_comercio_model.py backend/tests/test_instalacion_secret_envelope.py backend/tests/test_internal_commerce_installation_ingress.py backend/tests/test_outbound_message_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py -q
PYTHONPATH=. venv/bin/python -m compileall -q commerce_adapter backend
PYTHONPATH=. venv/bin/ruff check commerce_adapter backend/services/outbound_command_dispatcher.py backend/services/instalacion_twilio_comercio_service.py backend/routers/internal_commerce_installation.py backend/cli/instalacion_twilio_provision.py backend/config/settings.py backend/main.py
PYTHONPATH=. venv/bin/openspec validate add-commerce-isolated-twilio-edge --strict
git diff --check
```

If the local environment cannot load the project virtual environment the
implementer must report the exact error and must not claim the validation
passed. The Codex sandbox falls into this case; the user runs the
commands locally and forwards the output.

## Rollback and reversibility

- Removing the new installation rows is safe; they have no FK that
  protects historic data because nothing in NovaOrders references them
  yet. The new migration's ``downgrade()`` drops both tables and all
  rows together.
- Disabling an installation only flips ``activo`` to ``False``; the row
  and its secret envelope remain so a future re-enable does not require
  re-provisioning the merchant.
- The T-C adapter is an isolated Railway service; rolling it back is the
  Railway service deletion plus unregistering the merchant webhook URL
  with Twilio. NovaOrders does not need to deploy anything.
- No production data is migrated, no central webhook is disabled and no
  pilot is touched. A release can be reverted by disabling the affected
  installation rows.
- ``sent`` claims are never deleted in this phase. The bounded CLI does
  not own an operator surface that can drop a claim; the documented
  duplicate-send guarantee depends on the durable row surviving every
  short transaction. Dropping a ``sent`` claim would let the bounded
  CLI re-issue a ``messages.create`` for a previously-sent key, which
  would break the documented contract. Operators who need to drop
  historical rows belong to a future operator-only change that is
  explicitly out of scope.