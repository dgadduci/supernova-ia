# Capability: commerce-isolated-twilio-edge

## Purpose

Run the first commerce-owned Twilio (T-C) adapter in parallel with the
existing central Twilio webhook and dispatcher so a commerce can route
its own merchant Twilio account through NovaOrders without NovaOrders
holding merchant Twilio credentials. The T-C adapter is a per-commerce
FastAPI service that validates the inbound Twilio webhook, forwards a
canonical event to NovaOrders over an authenticated internal ingress,
and exposes one authenticated outbound command endpoint that performs
exactly one ``messages.create`` per call. NovaOrders owns the durable
receipt, the existing outbox and a per-installation idempotency claim
that prevents a second ``messages.create`` even under ambiguous
network results. The central Twilio webhook and dispatcher remain
operational and unchanged; the new path is opt-in through
``COMMERCE_ISOLATED_OUTBOUND_ENABLED`` and an active installation row.

## Requirements

### Requirement: Commerce installations are a separately administered technical registry

NovaOrders SHALL store one technical installation row per commerce that
uses the T-C adapter. The row SHALL include the commerce foreign key,
the per-installation T-C service URL (``tc_service_url`` — same adapter
code, one Railway service per commerce), an opaque unique installation
id, the lifecycle state, the encryption envelope of the shared secret
and the key identifier used for the envelope. The plain shared secret
SHALL NOT persist in the database, SHALL NOT appear in any log, SHALL
NOT be returnable from any HTTP response and SHALL NOT be settable from
a browser. A missing or invalid ``COMMERCE_INSTALLATION_MASTER_KEY``
SHALL cause the NovaOrders process to fail closed at startup whenever
``COMMERCE_ISOLATED_OUTBOUND_ENABLED`` is on or the internal ingress is
mounted.

#### Scenario: Installation provisioning produces the plain secret exactly once

- **WHEN** an operator runs the bounded provisioning CLI for a given
  comercio
- **THEN** the service generates an opaque installation id, generates a
  32-byte URL-safe random shared secret, encrypts the secret with the
  configured Fernet master key, persists the envelope and prints the
  opaque id and the plain secret exactly once on stdout
- **AND** the database row contains only the envelope and the key id
- **AND** the per-installation ``tc_service_url`` is validated against
  the documented HTTPS / Railway-private-network contract before the
  row is committed

#### Scenario: Master key missing fails closed at startup

- **WHEN** ``COMMERCE_INSTALLATION_MASTER_KEY`` is unset or not a valid
  Fernet URL-safe base64 key and ``COMMERCE_ISOLATED_OUTBOUND_ENABLED``
  is on
- **THEN** the NovaOrders process refuses to start at import time
- **AND** the operator receives the typed ``InvalidInstallationMasterKey``
  error before ``uvicorn`` accepts any traffic

#### Scenario: Concurrent provisioners cannot create two active installations

- **WHEN** two provisioners race to insert two active installation rows
  for the same ``comercio_id``
- **THEN** exactly one row is committed and the second provisioner
  receives the typed ``DuplicateInstalacionTwilioComercio`` error
- **AND** the database-level partial unique index
  ``uq_instalacion_twilio_one_active_per_comercio`` enforces the
  invariant
- **AND** a new installation can be created after the previous one is
  marked inactive

### Requirement: Per-installation T-C service URL is the routing authority

NovaOrders SHALL use the per-installation ``tc_service_url`` stored on
each ``InstalacionTwilioComercio`` row as the only routing authority
for outbound commands. The legacy ``COMMERCE_ISOLATED_TC_BASE_URL``
environment variable SHALL NOT drive routing — it is preserved only
for backward compatibility. The dispatcher SHALL validate the URL with
HTTPS-only public URLs, plain HTTP only for ``*.railway.internal``
hostnames, no credentials, no query string and no fragment.

#### Scenario: Per-installation URL is used by the dispatcher

- **WHEN** two installations with two different ``tc_service_url``
  values are active for two different comercios
- **THEN** the dispatcher routes each outbox row to its own URL and
  never to a global base URL

#### Scenario: Invalid URL is rejected at provisioning time

- **WHEN** an operator runs the bounded provisioning CLI with a
  ``--tc-service-url`` that uses plain HTTP on a non-Railway hostname,
  carries credentials, carries a query string, carries a fragment or is
  otherwise malformed
- **THEN** the CLI exits non-zero with the typed
  ``InvalidInstallationTcServiceUrl`` error and no row is committed

### Requirement: Ambiguous helper results finalize the central outbox as retryable

The central ``OutboundMessageDispatcher.dispatch()`` flow SHALL
catch :class:`OutboundCommandAmbiguous` raised by the bounded
``OutboundCommandDispatcher`` helper. The dispatcher SHALL
synthesize a typed ``OutboundCommandResult`` whose ``status`` is
``"in_progress"`` and SHALL finalize the central
``MensajeProveedorSaliente`` outbox row as ``retryable`` through
its existing caller-owned finalize transaction. The dispatcher
SHALL NOT fall back to the documented central Twilio path for an
ambiguous result. The durable
``instalaciones_twilio_comercio_idempotencia`` claim row SHALL
remain in ``in_progress`` state so a subsequent retry with the
same ``(instalacion_id, idempotency_key)`` short-circuits to the
durable state without firing a second ``messages.create``. The
duplicate-send protection is preserved across the ambiguous
result.

#### Scenario: T-C timeout finalizes the outbox as retryable and preserves the claim

- **WHEN** the bounded helper performs the network call to the T-C
  adapter and the call raises a timeout / connection drop / malformed
  body
- **THEN** the helper raises :class:`OutboundCommandAmbiguous`
- **AND** the central dispatcher finalizes the central outbox row as
  ``retryable`` through its existing caller-owned finalize
  transaction
- **AND** the durable ``instalaciones_twilio_comercio_idempotencia``
  claim row stays in ``in_progress`` state
- **AND** the central dispatcher does NOT invoke the documented
  central Twilio ``messages.create`` fallback on this row
- **AND** the central dispatcher returns ``RETRY_SCHEDULED`` so the
  bounded CLI drives the documented bounded retry path

#### Scenario: Subsequent retry short-circuits the durable claim

- **WHEN** the central dispatcher finalized the central outbox row as
  ``retryable`` after an ambiguous helper result and the bounded CLI
  drives the next dispatch on the same row
- **THEN** the bounded helper reads the existing ``in_progress`` claim
  and returns the durable ``in_progress`` state
- **AND** the bounded helper performs zero new HTTP calls to the T-C
  adapter
- **AND** the central dispatcher does NOT invoke the documented
  central Twilio ``messages.create`` fallback on this row

### Requirement: HTTP classification is closed and explicit

The bounded ``OutboundCommandDispatcher`` helper SHALL classify
non-200 HTTP responses per the closed policy below. Unknown ``4xx``
codes SHALL NOT default to ``retryable``; they SHALL be treated as
ambiguous results.

| Status | Outcome |
| --- | --- |
| ``429`` | ``retryable`` with ``code="http_429_rate_limited"`` |
| ``500``-``599`` | ``retryable`` with ``code="http_<status>_provider"`` |
| ``400`` | ``terminal`` with ``code="http_400_contract"`` |
| ``401`` | ``terminal`` with ``code="http_401"`` |
| ``403`` | ``terminal`` with ``code="http_403"`` |
| ``404`` | ``terminal`` with ``code="http_404"`` |
| ``409`` | ``terminal`` with ``code="http_409"`` |
| ``422`` | ``terminal`` with ``code="http_422"`` |
| any other ``4xx`` | ambiguous — claim stays ``in_progress`` and the helper raises :class:`OutboundCommandAmbiguous` |

The list of terminal ``4xx`` codes is closed and explicitly
documented. Adding a new code requires updating the proposal,
the design and the spec so the contract stays closed.

#### Scenario: 404 finalizes the claim as terminal

- **WHEN** the bounded helper performs the network call and the T-C
  adapter returns HTTP ``404``
- **THEN** the helper finalizes the durable claim as ``terminal``
  with ``code="http_404"``
- **AND** the helper returns the typed ``terminal`` outcome so the
  bounded CLI finalizes the central outbox row as ``failed_terminal``

#### Scenario: 409 finalizes the claim as terminal

- **WHEN** the bounded helper performs the network call and the T-C
  adapter returns HTTP ``409``
- **THEN** the helper finalizes the durable claim as ``terminal``
  with ``code="http_409"``

#### Scenario: 422 finalizes the claim as terminal

- **WHEN** the bounded helper performs the network call and the T-C
  adapter returns HTTP ``422``
- **THEN** the helper finalizes the durable claim as ``terminal``
  with ``code="http_422"``

#### Scenario: Unknown 4xx leaves the claim in_progress

- **WHEN** the bounded helper performs the network call and the T-C
  adapter returns an HTTP status code in the ``4xx`` range that is
  not in the documented terminal set
- **THEN** the helper raises :class:`OutboundCommandAmbiguous`
- **AND** the durable ``instalaciones_twilio_comercio_idempotencia``
  claim row stays in ``in_progress`` state
- **AND** the central dispatcher finalizes the central outbox row as
  ``retryable`` through its existing caller-owned finalize
  transaction

### Requirement: CanonicalOutboundResponse is a closed contract

``CanonicalOutboundResponse`` is the canonical typed response sent
back by the T-C adapter. The contract SHALL be closed:

- ``status`` SHALL be restricted to the documented set
  ``{"sent", "retryable", "terminal"}``;
- ``message_sid`` SHALL be a non-empty string whenever
  ``status == "sent"`` and SHALL be ``None`` otherwise;
- any extra field SHALL be rejected by the ``extra="forbid"`` policy;
- any invalid response — unknown ``status``, missing ``message_sid``
  on ``"sent"``, extra fields, malformed body — SHALL be treated as
  an ambiguous result. The bounded helper SHALL raise
  :class:`OutboundCommandAmbiguous` so the bounded CLI finalizes
  the central outbox row as ``retryable`` while the durable claim
  row stays ``in_progress`` for recovery. The helper SHALL NOT
  finalize the durable claim with an invalid state and SHALL NOT
  fire a second ``messages.create`` call after an invalid response.

#### Scenario: Unknown status is ambiguous

- **WHEN** the bounded helper receives a ``200`` response whose body
  carries a ``status`` value outside the documented set
- **THEN** the helper raises :class:`OutboundCommandAmbiguous`
- **AND** the durable ``instalaciones_twilio_comercio_idempotencia``
  claim row stays in ``in_progress`` state
- **AND** the central dispatcher finalizes the central outbox row as
  ``retryable`` through its existing caller-owned finalize
  transaction

#### Scenario: sent without message_sid is ambiguous

- **WHEN** the bounded helper receives a ``200`` response whose body
  carries ``status="sent"`` but no non-empty ``message_sid``
- **THEN** the helper raises :class:`OutboundCommandAmbiguous`
- **AND** the durable claim row stays in ``in_progress`` state
- **AND** the bounded helper performs zero new HTTP calls on a
  subsequent retry for the same ``(instalacion_id,
  idempotency_key)``

#### Scenario: valid sent finalizes the claim as sent

- **WHEN** the bounded helper receives a ``200`` response whose body
  carries ``status="sent"`` and a non-empty ``message_sid``
- **THEN** the helper finalizes the durable claim as ``sent``
- **AND** the helper returns the typed ``sent`` outcome so the
  bounded CLI finalizes the central outbox row as ``accepted``

#### Scenario: valid retryable finalizes the claim as retryable

- **WHEN** the bounded helper receives a ``200`` response whose body
  carries ``status="retryable"``
- **THEN** the helper finalizes the durable claim as ``retryable``
- **AND** the helper returns the typed ``retryable`` outcome so the
  bounded CLI finalizes the central outbox row as ``retryable``

#### Scenario: valid terminal finalizes the claim as terminal

- **WHEN** the bounded helper receives a ``200`` response whose body
  carries ``status="terminal"``
- **THEN** the helper finalizes the durable claim as ``terminal``
- **AND** the helper returns the typed ``terminal`` outcome so the
  bounded CLI finalizes the central outbox row as ``failed_terminal``

### Requirement: Outbound commands are effectively idempotent through a durable claim

NovaOrders SHALL prevent a second ``messages.create`` call for the same
``(instalacion_id, idempotency_key)`` pair through a durable
``instalaciones_twilio_comercio_idempotencia`` claim row whose unique
``(instalacion_id, idempotency_key)`` index is the serialisation point
for the ``INSERT`` race. The dispatcher SHALL NOT rely on a
process-local dictionary or on the central outbox row as the only
guarantee.

The durable state machine for the claim row SHALL be:

* ``sent`` — the T-C adapter returned a SID. The claim is permanent in
  this phase; a second caller returns the durable SID without firing
  a second ``messages.create``. The bounded CLI never deletes ``sent``
  claims in this phase;
* ``terminal`` — the T-C adapter returned a status code in the
  closed terminal ``4xx`` set (``400`` / ``401`` / ``403`` / ``404``
  / ``409`` / ``422``). The claim is permanent in this phase; a
  second caller returns the durable state without firing a second
  ``messages.create``. Any other ``4xx`` status code is NOT
  ``terminal`` — it is treated as an ambiguous result so the helper
  raises :class:`OutboundCommandAmbiguous` and the durable claim
  stays ``in_progress``. The bounded CLI never deletes ``terminal``
  claims in this phase;
* ``in_progress`` — the bounded dispatch has staged the claim and has
  not yet seen a typed response. The state is also the durable marker
  for an ambiguous network result (timeout, connection drop, malformed
  body). A subsequent dispatch short-circuits to the durable state
  without firing a second ``messages.create``. The duplicate-send
  protection is preserved after an ambiguous timeout because the row
  stays in ``in_progress`` and the next dispatch short-circuits to
  the durable state instead of firing a new ``messages.create``;
* ``retryable`` — the T-C adapter or the bounded CLI drove a bounded
  retryable failure. The next dispatch atomically transitions the row
  back to ``in_progress`` through a single
  ``UPDATE ... WHERE estado = 'retryable'`` statement and performs a
  new HTTP call. Two concurrent callers on the same ``retryable`` row
  serialise through the predicate: only one wins and runs the new
  send; the other returns the durable state without calling T-C. The
  bounded CLI keeps the same ``idempotency_key`` and never deletes
  the row.

The claim and the finalize SHALL use two short transactions that are
deliberately separate from the central dispatcher's caller-owned outbox
transaction. The claim transaction commits and closes before the
network call so the claim is durable across a process restart and the
database never holds a transaction across the network round-trip. The
finalize transaction commits and closes after the HTTP call returns so
a concurrent retry running on a different process sees the durable
outcome.

An ambiguous result after ``messages.create`` (timeout, malformed
body) SHALL raise :class:`OutboundCommandAmbiguous` so the bounded CLI
finalizes the outbox row as ``retryable`` while the durable claim row
remains ``in_progress`` for recovery; a subsequent retry with the same
key SHALL short-circuit to the durable state without firing a second
``messages.create``.

The atomic transition ``retryable -> in_progress`` SHALL be performed
through a single ``UPDATE`` statement with a ``WHERE estado =
'retryable'`` predicate. The database is the serialisation point: two
concurrent attempts on the same ``retryable`` row SHALL affect only
one row total, the loser's update affects zero rows, and only one
caller SHALL perform the new HTTP call. The bounded CLI SHALL keep the
same ``idempotency_key`` across the transition and SHALL NOT delete the
row to retry.

#### Scenario: Same idempotency key returns the durable result without a second call

- **WHEN** the bounded helper claims the slot, the T-C adapter returns a
  typed response and a second caller submits the same key
- **THEN** the second caller receives the durable result
  (``sent`` / ``retryable`` / ``terminal``) without performing a second
  ``messages.create`` call

#### Scenario: First attempt 429 then second attempt sent

- **WHEN** the bounded helper attempts the network call and the T-C
  adapter returns a ``429`` response so the durable claim finalizes as
  ``retryable``
- **AND** the bounded CLI drives the next dispatch on the same
  ``(instalacion_id, idempotency_key)`` pair
- **THEN** the bounded helper atomically transitions the durable claim
  from ``retryable`` to ``in_progress``
- **AND** the bounded helper performs a new HTTP call to the T-C
  adapter
- **AND** the durable claim finalizes as ``sent`` when the T-C
  adapter returns a typed ``sent`` response
- **AND** exactly two real HTTP calls fired for the two attempts

#### Scenario: First attempt 500 then second attempt sent

- **WHEN** the bounded helper attempts the network call and the T-C
  adapter returns a ``500`` response so the durable claim finalizes as
  ``retryable``
- **AND** the bounded CLI drives the next dispatch on the same
  ``(instalacion_id, idempotency_key)`` pair
- **THEN** the bounded helper atomically transitions the durable claim
  from ``retryable`` to ``in_progress``
- **AND** the bounded helper performs a new HTTP call to the T-C
  adapter
- **AND** the durable claim finalizes as ``sent`` when the T-C
  adapter returns a typed ``sent`` response
- **AND** exactly two real HTTP calls fired for the two attempts

#### Scenario: Multiple retryable attempts before the final sent

- **WHEN** the bounded helper attempts the network call and the T-C
  adapter returns a sequence of ``429`` / ``5xx`` responses so the
  durable claim remains ``retryable`` between attempts
- **AND** the bounded CLI drives the next dispatch on each subsequent
  retry
- **THEN** every ``retryable`` claim drives a new HTTP call through the
  atomic ``retryable -> in_progress`` transition
- **AND** the durable claim finalizes as ``sent`` only on the final
  successful attempt

#### Scenario: ``sent`` claim never fires a second call

- **WHEN** the bounded helper claims the slot and the T-C adapter
  returns a typed ``sent`` response so the durable claim finalizes as
  ``sent``
- **AND** a subsequent dispatch submits the same key
- **THEN** the bounded helper returns the durable ``sent`` state
- **AND** the bounded helper performs zero new HTTP calls to the T-C
  adapter

#### Scenario: ``terminal`` claim never fires a second call

- **WHEN** the bounded helper claims the slot and the T-C adapter
  returns a typed ``terminal`` response so the durable claim
  finalizes as ``terminal``
- **AND** a subsequent dispatch submits the same key
- **THEN** the bounded helper returns the durable ``terminal`` state
- **AND** the bounded helper performs zero new HTTP calls to the T-C
  adapter

#### Scenario: ``in_progress`` claim never fires a second call

- **WHEN** the bounded helper claims the slot and the T-C adapter
  returns no typed response (timeout, malformed body) so the durable
  claim remains ``in_progress``
- **AND** a subsequent dispatch submits the same key
- **THEN** the bounded helper returns the durable ``in_progress``
  state
- **AND** the bounded helper performs zero new HTTP calls to the T-C
  adapter
- **AND** the duplicate-send protection is preserved after the
  ambiguous timeout

#### Scenario: Concurrent dispatchers serialise through the unique index

- **WHEN** two dispatchers race to claim the same
  ``(instalacion_id, idempotency_key)``
- **THEN** the database-level unique constraint ensures exactly one
  ``INSERT`` succeeds; the other caller short-circuits to the durable
  state without performing a second ``messages.create`` call

#### Scenario: Two concurrent callers on a retryable claim

- **WHEN** the durable claim is in ``retryable`` state and two
  dispatchers submit the same ``(instalacion_id, idempotency_key)``
  pair concurrently
- **THEN** the atomic ``UPDATE ... WHERE estado = 'retryable'``
  predicate serialises them: exactly one row is updated to
  ``in_progress``; the loser's update affects zero rows
- **AND** only the winning caller performs a new HTTP call to the T-C
  adapter
- **AND** the losing caller returns the durable state without calling
  T-C
- **AND** exactly one real HTTP call fires for the second attempt
- **AND** the bounded CLI keeps the same ``idempotency_key`` across
  the transition

#### Scenario: Ambiguous result after the network call

- **WHEN** the T-C adapter returns no typed response (timeout,
  malformed body) after the bounded helper performed the network call
- **THEN** the helper raises :class:`OutboundCommandAmbiguous`
- **AND** the durable claim row remains ``in_progress`` so a retry
  returns the durable state rather than firing a second send

#### Scenario: No in-memory dedupe is the only guarantee

- **WHEN** the bounded helper is restarted between two calls with the
  same key
- **THEN** the durable database row is the single source of truth that
  serialises the calls — the second call returns the durable result
  without firing a second ``messages.create``

### Requirement: Central dispatcher delegates to the bounded helper when the flag is on

The existing central ``OutboundMessageDispatcher.dispatch()`` SHALL
delegate the network call to the bounded
``OutboundCommandDispatcher`` helper when
``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` AND an active installation
exists for the row's ``comercio_id``. The dispatcher SHALL fall back to
the documented central Twilio path on the same row when the flag is
off OR no active installation exists. The bounded CLI / central
dispatcher SHALL remain the single owner of the outbox lease, finalize
transaction and commit / rollback discipline.

#### Scenario: Flag off preserves the central Twilio behaviour

- **WHEN** ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=false``
- **THEN** ``OutboundMessageDispatcher.dispatch()`` invokes the central
  Twilio ``messages.create`` call exactly like today and never invokes
  the bounded helper

#### Scenario: Flag on with active installation routes through the helper

- **WHEN** ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` and an active
  installation exists for the row's ``comercio_id``
- **THEN** ``OutboundMessageDispatcher.dispatch()`` invokes the bounded
  helper, which POSTs the canonical command to the per-installation
  ``tc_service_url``
- **AND** the bounded helper returns the typed result so the central
  dispatcher can finalize the outbox row in its caller-owned narrow
  transaction

#### Scenario: Flag on with no active installation falls back to central

- **WHEN** ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=true`` but no active
  installation exists for the row's ``comercio_id``
- **THEN** the bounded helper raises ``OutboundCommandSkipped`` and the
  central dispatcher falls back to the documented central Twilio path
  on the same row

### Requirement: ``status_callback_url`` is optional and never a placeholder

NovaOrders SHALL NOT pass any placeholder ``status_callback_url`` value
to ``messages.create``. ``TWILIO_CALLBACK_STATUS_URL`` SHALL be
optional — when missing or blank, NovaOrders SHALL omit the kwarg from
``messages.create``. The canonical outbound command contract SHALL
allow ``status_callback_url`` to be ``None``.

#### Scenario: No callback URL is configured

- **WHEN** ``TWILIO_CALLBACK_STATUS_URL`` is unset or blank
- **THEN** the central dispatcher and the bounded T-C helper omit the
  ``status_callback`` kwarg from ``messages.create`` and no placeholder
  URL is persisted

#### Scenario: Valid callback URL is forwarded

- **WHEN** ``TWILIO_CALLBACK_STATUS_URL`` is configured to a validated
  absolute ``https://`` URL
- **THEN** the dispatcher forwards it on ``messages.create`` exactly
  once

### Requirement: Inbound Twilio webhooks are validated before any downstream work

The T-C adapter SHALL accept a Twilio form POST only after validating
``X-Twilio-Signature`` against the exact public URL of the configured
merchant base URL plus the request path and actual query string, and
against the complete submitted form. A missing configuration, missing
signature, or invalid signature SHALL return a non-success HTTP status
without TwiML and SHALL NOT trigger any NovaOrders call.

#### Scenario: Valid signature reaches NovaOrders

- **WHEN** a valid signed Twilio form is received by the adapter
- **THEN** the adapter normalizes the four documented fields into the
  canonical event
- **AND** the adapter signs the canonical JSON body with
  HMAC-SHA256(installation secret, body)
- **AND** the adapter POSTs the body and the signature to NovaOrders
- **AND** the adapter does not call the classifier, recognizer, handler,
  response mapper or outbox

#### Scenario: Tampered signature fails closed

- **WHEN** the signature is missing, malformed, or fails SDK validation
- **THEN** the adapter returns ``403`` with an empty body
- **AND** the adapter does not POST to NovaOrders

### Requirement: Empty TwiML is returned only after NovaOrders confirms acceptance

The T-C adapter SHALL return the empty TwiML ``<Response></Response>``
only when NovaOrders reports ``accepted`` or ``duplicate``. The empty
TwiML SHALL NOT contain ``<Message>``. Any other outcome SHALL return a
non-success HTTP status so Twilio retries.

#### Scenario: NovaOrders accepts the event

- **WHEN** NovaOrders returns ``{"status": "accepted", ...}`` or
  ``{"status": "duplicate", ...}``
- **THEN** the adapter returns ``200 application/xml`` with body
  ``<Response></Response>``
- **AND** the adapter does not send any other TwiML or HTTP body for
  the same request

#### Scenario: NovaOrders rejects the event

- **WHEN** NovaOrders returns ``{"status": "rejected", "reason": ...}``
- **THEN** the adapter returns ``200 application/xml`` with body
  ``<Response></Response>`` because the event was durably classified
  as a no-op for that commerce
- **AND** the adapter does not call Twilio for that event

#### Scenario: NovaOrders unreachable

- **WHEN** NovaOrders is unreachable or returns a non-success status
- **THEN** the adapter returns ``502`` with an empty body
- **AND** Twilio retries

### Requirement: NovaOrders ingress accepts only the documented canonical event

NovaOrders SHALL accept a canonical event from a T-C adapter only when
the installation is active, the HMAC signature over the raw request
bytes is valid for that installation's envelope, and the destination
and the sender both resolve to the documented authorities for the
installation's commerce. A request whose commerce fails any of those
checks SHALL NOT be processed.

#### Scenario: Valid signature and authority

- **WHEN** a request is signed for an active installation and the
  destination resolves to the active ``CanalWhatsapp`` of that
  installation's commerce and the sender resolves to an active
  ``Cliente``
- **THEN** NovaOrders delegates to the existing
  ``ProviderInboundMessageCoordinator.accept`` exactly as the central
  Twilio webhook does
- **AND** the coordinator is the sole transaction owner for the
  receipt and the deferred work item

#### Scenario: Signature mismatch fails closed

- **WHEN** the HMAC signature is missing or fails verification
- **THEN** NovaOrders returns ``401`` without invoking the coordinator
- **AND** the adapter returns ``502`` and Twilio retries

#### Scenario: Destination does not belong to the commerce

- **WHEN** the destination is not the active ``CanalWhatsapp`` for the
  installation's commerce
- **THEN** NovaOrders returns ``200 {"status": "rejected", "reason":
  "unknown_destination"}``
- **AND** NovaOrders does not invoke the coordinator
- **AND** the adapter returns the empty TwiML

#### Scenario: Sender does not resolve to an active client

- **WHEN** the sender is not an active ``Cliente``
- **THEN** NovaOrders returns ``200 {"status": "rejected", "reason":
  "unknown_client"}``
- **AND** NovaOrders does not invoke the coordinator
- **AND** the adapter returns the empty TwiML

### Requirement: Inbound idempotency follows the existing coordinator

NovaOrders SHALL treat the inbound event as idempotent by the unique
pair ``(proveedor, identificador_recepcion)``. The existing
``ProviderInboundMessageCoordinator`` is the sole owner of the
receipt + work-item transaction; the ingress dependency SHALL NOT
open, commit, rollback or flush any SQLAlchemy transaction.

#### Scenario: Duplicate message identifier

- **WHEN** a request with the same ``proveedor`` and ``MessageSid`` is
  received after a prior accepted delivery
- **THEN** NovaOrders returns ``200 {"status": "duplicate"}``
- **AND** the existing coordinator returns ``ALREADY_PROCESSED``
- **AND** no second work item is created

### Requirement: Outbound commands perform exactly one merchant Twilio send

The T-C adapter SHALL accept a canonical outbound command only when
the request is signed for the local installation and the
``instalacion_id``/``comercio_id`` pair matches the local installation.
The adapter SHALL call exactly one ``Client.messages.create`` through
the configured merchant Twilio account, SHALL return the SID and a
typed status, and SHALL NOT log body, phone, token or credential.

The T-C adapter SHALL validate the outbound command envelope in this
exact order: ``X-Installation-Id`` header presence and exact match
against the local installation; HMAC signature over the raw body
bytes; JSON body parsing; ``instalacion_id`` body match against the
local configuration; ``comercio_id`` body match against the local
configuration. Any failure SHALL return a typed ``401`` or ``403``
without firing ``messages.create``.

#### Scenario: Valid command sends exactly one message

- **WHEN** a properly signed command with matching ``instalacion_id`` /
  ``comercio_id`` and matching ``X-Installation-Id`` is received
- **THEN** the adapter calls ``messages.create`` exactly once
- **AND** the response includes the SID and ``{"status": "sent"}`` on
  success

#### Scenario: Missing ``X-Installation-Id`` header fails closed

- **WHEN** the request omits the ``X-Installation-Id`` header
- **THEN** the adapter returns ``401`` and never calls
  ``messages.create``

#### Scenario: Mismatching ``X-Installation-Id`` fails closed

- **WHEN** the request carries a ``X-Installation-Id`` header that
  differs from the local ``TC_INSTALLATION_ID``
- **THEN** the adapter returns ``401`` and never calls
  ``messages.create``

#### Scenario: Command for another installation is rejected

- **WHEN** a command is signed for a different installation or for a
  non-matching ``instalacion_id``/``comercio_id`` pair
- **THEN** the adapter returns ``403`` and never calls
  ``messages.create``

#### Scenario: Missing signature fails closed

- **WHEN** the request omits the HMAC signature header
- **THEN** the adapter returns ``401`` and never calls
  ``messages.create``

### Requirement: No provider payload, secret or token is logged

The T-C adapter and the NovaOrders ingress SHALL NOT log message
bodies, customer phone numbers, the merchant Twilio auth token, the
shared installation secret, raw Twilio payloads, or Twilio signature
values. The bounded log records SHALL only contain bounded event
names, status categories, and bounded surrogate identifiers.

#### Scenario: Empty TwiML body never leaks the inbound body

- **WHEN** the adapter returns the empty TwiML after NovaOrders accepts
  or rejects the event
- **THEN** the response body contains exactly ``<Response></Response>``
- **AND** the response never contains the inbound body or the sender
  number

#### Scenario: Outbound logs do not contain the body or phone

- **WHEN** the adapter processes an outbound command
- **THEN** the recorded log fields are limited to the installation id
  tail, the comercio id, the outbox id, the idempotency key tail and
  the typed status
- **AND** the body and destination phone are absent from every log
  record
