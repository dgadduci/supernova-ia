# Tasks: add commerce isolated Twilio edge

## 0. Approval and discovery

- [x] 0.1 Inspect the central Twilio webhook, coordinator, dispatcher, outbox,
  channel resolver, commerce availability, the existing
  add-commerce-self-service-onboarding target architecture and the
  recipient-process layout.
- [x] 0.2 Confirm the existing central webhook, dispatcher and outbox remain
  the only Twilio surface until a separately approved migration change.
- [x] 0.3 Confirm the self-service onboarding track remains paused after
  Phase 4B and that no owner flow is modified by this change.

## 1. NovaOrders core installation registry

- [x] 1.1 Add `InstalacionTwilioComercio` SQLAlchemy model with opaque
  `instalacion_id`, `id_comercio` FK, `tc_service_url` (per-installation
  T-C service URL), `activo`, lifecycle timestamps and Fernet envelope
  columns. Register it in `backend/models/__init__.py` and
  `backend/alembic/env.py`.
- [x] 1.2 Add a hand-written Alembic migration that creates the
  `instalaciones_twilio_comercio` table, the unique index on
  `instalacion_id`, the FK to `comercios.id` (RESTRICT), the index on
  `id_comercio` AND the partial unique index
  `uq_instalacion_twilio_one_active_per_comercio` on
  `(id_comercio) WHERE activo = true`. The migration also creates the
  `instalaciones_twilio_comercio_idempotencia` table with the unique
  `(instalacion_id, idempotency_key)` constraint. Downgrade drops both
  tables.
- [x] 1.3 Add `InstalacionSecretEnvelope` service that loads
  `COMMERCE_INSTALLATION_MASTER_KEY` from env (Fernet URL-safe base64) and
  supports multi-key rotation. Add `InvalidInstallationMasterKey` and
  `InvalidInstallationSecretEnvelope` exceptions.
- [x] 1.4 Add `InstalacionTwilioComercioRepository` (DB-only) with
  `find_by_instalacion_id`, `find_active_by_instalacion_id`,
  `find_active_by_comercio_id`, and `add`/`mark_inactive` mutations.
- [x] 1.5 Add `InstalacionTwilioComercioService` (business rules) with
  `create_installation(comercio_id, tc_service_url)` returning the
  opaque id + plain secret exactly once. Service owns the envelope
  encryption, the secret generation and the per-installation
  `tc_service_url` validation (HTTPS public, plain HTTP only for
  `*.railway.internal`, no creds / query / fragment).
- [x] 1.6 Add the bounded `backend/cli/instalacion_twilio_provision.py`
  CLI that loads settings, calls the service, validates the URL and
  prints the opaque id plus the plain secret exactly once on stdout.
- [x] 1.7 Add the durable `InstalacionTwilioComercioIdempotenciaRepository`
  that owns the unique `INSERT` claim lifecycle for the bounded
  outbound helper.
- [x] 1.8 Add the startup fail-closed check in `backend/main.py` so a
  missing or invalid `COMMERCE_INSTALLATION_MASTER_KEY` with the
  isolated flag on refuses to start the NovaOrders process.

## 2. NovaOrders core internal ingress

- [x] 2.1 Add `commerce_installation_event` Pydantic schema with the
  canonical inbound contract fields (instalacion_id, comercio_id,
  proveedor, message_sid, from_e164, to_e164, cuerpo, profile_name_hash,
  num_media, optional metadata).
- [x] 2.2 Add `commerce_installation_outbound_command` Pydantic schema
  with the canonical outbound fields (instalacion_id, comercio_id,
  idempotency_key, destinatario_e164, cuerpo, optional
  status_callback_url, proveedor).
- [x] 2.3 Add `backend/routers/internal_commerce_installation.py` with:
  - `POST /internal/commerce-installation/{instalacion_id}/accept-event`
    authenticated by an `X-Installation-Signature` HMAC-SHA256 header.
  - The dependency decrypts the envelope, recomputes the HMAC over the
    raw bytes and rejects on mismatch, missing header, missing envelope
    or inactive row.
- [x] 2.4 Implement the handler:
  - resolves the active `CanalWhatsapp` for the comercio + destination;
  - resolves the active `Cliente` from `from_e164`;
  - delegates to `ProviderInboundMessageCoordinator.accept` with the
    exact command shape used by the central webhook;
  - maps `ACCEPTED` / `ALREADY_PROCESSED` / `INVALID_CONTEXT` to the
    documented JSON response;
  - never logs body, phone, token or signature.
- [x] 2.5 Register the router in `backend/main.py`. The router is mounted
  on the same FastAPI app; it does not require `X-Admin-Token` and does
  not require admin authentication.

## 3. NovaOrders core outbound command helper

- [x] 3.1 Add `OutboundCommandDispatcher` helper service that builds the
  canonical outbound command for a given outbox row + active
  installation, owns the durable
  `instalaciones_twilio_comercio_idempotencia` claim lifecycle, POSTs
  to the per-installation `tc_service_url` with the HMAC signature and
  translates the typed response back into the same outbox state machine
  vocabulary the central dispatcher uses. The helper raises
  `OutboundCommandSkipped` when the flag is off or no active
  installation exists so the central dispatcher falls back to the
  documented central Twilio path. The helper raises
  `OutboundCommandAmbiguous` when the network call returns no typed
  response and leaves the durable claim row `in_progress` for recovery.
- [x] 3.2 Add the `COMMERCE_ISOLATED_OUTBOUND_ENABLED` setting (default
  `False`). Rename `COMMERCE_ISOLATED_TC_BASE_URL` to
  `COMMERCE_ISOLATED_TC_BASE_URL_LEGACY` — the dispatcher never reads
  it; routing is exclusively driven by the per-installation
  `tc_service_url`.
- [x] 3.3 Wire the helper into `OutboundMessageDispatcher.dispatch()`
  so the central dispatcher delegates the network call to the helper
  when the flag is on and an active installation exists. The bounded
  CLI / central dispatcher remains the single owner of the outbox
  lease, finalize transaction and commit / rollback discipline.
- [x] 3.4 Implement the durable claim state machine through two short
  transactions: the claim transaction (INSERT or atomic
  `retryable -> in_progress` UPDATE) and the finalize transaction
  (typed outcome). The two transactions never carry the outbox row,
  never touch the central `MensajeProveedorSaliente` lease and never
  share state with the central dispatcher's caller-owned transaction.
  The bounded CLI keeps the same `idempotency_key` across the
  transition and never deletes the claim to retry.
- [x] 3.5 Implement the atomic `retryable -> in_progress` transition
  through a single `UPDATE` statement with a `WHERE estado =
  'retryable'` predicate. Two concurrent callers on the same
  `retryable` row serialise through the predicate: only one wins and
  runs the new send; the other returns the durable state without
  calling T-C. The database is the serialisation point; no
  process-local dictionary, no in-memory dedupe and no
  second-transaction lock is added.

## 4. T-C adapter skeleton (commerce_adapter/)

- [x] 4.1 Add `commerce_adapter/` package with `app/` and `tests/`
  subpackages, minimal `README.md`, minimal `requirements.txt`, empty
  `pyproject.toml`. The adapter must NOT import any NovaOrders backend
  module.
- [x] 4.2 Add `commerce_adapter/app/config.py` that loads the documented
  environment variables and raises on missing/invalid values at startup.
- [x] 4.3 Add `commerce_adapter/app/schemas.py` with Pydantic models for
  the canonical inbound event and the canonical outbound command
  (the latter with optional `status_callback_url`).
- [x] 4.4 Add `commerce_adapter/app/security.py` with:
  - HMAC-SHA256 sign/verify helpers over the exact byte payload;
  - Twilio signature URL builder using the configured base URL + actual
    query string.
- [x] 4.5 Add `commerce_adapter/app/twilio_client.py` exposing a
  `TwilioMessagesClient` Protocol and a `send` function that wraps
  `Client.messages.create` through the same typed result shape used by
  the central adapter; the seam omits `status_callback` when the
  command carries `None`.
- [x] 4.6 Add `commerce_adapter/app/novaorders_client.py` with an
  `httpx`-based client that POSTs the canonical event to NovaOrders and
  maps the response to a typed result.
- [x] 4.7 Add `commerce_adapter/app/canonical_event.py` with the four
  Twilio field normalization rules (the existing
  `normalize_destination`/`normalize_whatsapp` logic is mirrored for the
  adapter without backend coupling).
- [x] 4.8 Add `commerce_adapter/app/main.py` with the FastAPI
  application, routers, lifespan and bounded logging discipline.

## 5. T-C adapter routes

- [x] 5.1 Add `commerce_adapter/app/routes/health.py` with
  `GET /health` returning `{"status": "ok"}`.
- [x] 5.2 Add `commerce_adapter/app/routes/webhook.py` with the
  documented Twilio webhook behavior (signature → canonical event →
  NovaOrders forward → empty TwiML on accept/reject, 502 otherwise).
- [x] 5.3 Add `commerce_adapter/app/routes/outbound.py` with the
  documented outbound command behavior: validate `X-Installation-Id`
  exact match; validate HMAC signature; parse body; validate body
  `instalacion_id` / `comercio_id` match against the local
  configuration; perform exactly one `messages.create` through the
  typed seam.

## 6. T-C adapter tests

- [x] 6.1 Add `test_signature_validation.py` covering valid signature,
  missing signature, tampered body, tampered query string and missing
  configuration.
- [x] 6.2 Add `test_canonical_event.py` covering the four-field
  normalization and the canonical payload shape.
- [x] 6.3 Add `test_webhook_route.py` covering the full happy path,
  NovaOrders rejection, NovaOrders unreachability, duplicate
  `MessageSid`, isolation between two commerces, invalid installation
  and the no-secrets-in-logs invariant.
- [x] 6.4 Add `test_outbound_route.py` covering the full happy path,
  missing `X-Installation-Id`, mismatching `X-Installation-Id`,
  missing signature, signature for another installation, exactly one
  `messages.create` call, no body/phone/token/credentials in logs and
  the typed status mapping.
- [x] 6.5 Add `test_security_no_secrets.py` asserting that no log
  surface, exception traceback, or response body contains the
  installation secret, the Twilio auth token, the body, or the phone
  number.

## 7. NovaOrders core tests

- [x] 7.1 Add `test_instalacion_twilio_comercio_model.py` for the new
  model constraints (unique `instalacion_id`, FK, optional fields,
  partial unique index on `id_comercio WHERE activo = true`,
  idempotency table and unique constraint).
- [x] 7.2 Add `test_instalacion_secret_envelope.py` for the envelope
  service: round-trip, missing master key, invalid master key,
  rotation.
- [x] 7.3 Add `test_internal_commerce_installation_ingress.py` for the
  internal router: HMAC mismatch → 401, missing signature → 401,
  installation inactive → 401, unknown destination → 200 reject,
  unknown client → 200 reject, unavailable commerce → 200 reject,
  valid signature + valid authority → 200 accepted,
  `ALREADY_PROCESSED` → 200 duplicate.
- [x] 7.4 Add `test_outbound_message_dispatcher.py` covering the
  bounded helper: flag off preserves the central Twilio path; flag on
  with active installation routes through the helper; flag on without
  active installation falls back to the central path; the helper
  performs exactly one outbound HTTP call per row; per-installation
  `tc_service_url` is used (not a global URL); same idempotency key
  returns the durable result without a second network call; concurrent
  claim attempts serialise through the unique database index; an
  ambiguous network result raises `OutboundCommandAmbiguous` and the
  durable claim row stays `in_progress` for recovery.
- [x] 7.5 Add tests for the durable `retryable` state machine:
  - first attempt `429` then second attempt `sent` — exactly two
    real HTTP calls and the claim finalizes as `sent`;
  - first attempt `500` then second attempt `sent` — exactly two
    real HTTP calls and the claim finalizes as `sent`;
  - multiple `retryable` attempts before the final `sent` — every
    `retryable` claim drives a new HTTP call and the claim
    finalizes as `sent` only on the final attempt;
  - two concurrent callers on a `retryable` claim — the atomic
    `UPDATE ... WHERE estado = 'retryable'` predicate serialises
    them; only one runs the new HTTP call; the other returns the
    durable state without calling T-C; exactly one real HTTP call
    fires for the second attempt;
  - `sent` claim never fires a second call;
  - `terminal` claim never fires a second call;
  - `in_progress` claim (after a timeout) never fires a second call;
  - the retryable → sent retry sequence is driven through the real
    `OutboundMessageDispatcher` so the bounded CLI / outbox lease /
    finalize path is exercised end-to-end.

## 8. Validation

- [x] 8.1 Run
  `venv/bin/python -m pytest commerce_adapter/tests
  backend/tests/test_instalacion_twilio_comercio_model.py
  backend/tests/test_instalacion_secret_envelope.py
  backend/tests/test_internal_commerce_installation_ingress.py
  backend/tests/test_outbound_message_dispatcher.py
  backend/tests/test_run_outbound_dispatch_cli.py` and report the
  complete output.
- [x] 8.2 Run `venv/bin/ruff check commerce_adapter
  backend/services/outbound_command_dispatcher.py
  backend/services/instalacion_twilio_comercio_service.py
  backend/routers/internal_commerce_installation.py
  backend/cli/instalacion_twilio_provision.py
  backend/config/settings.py backend/main.py` and report the complete
  output.
- [x] 8.3 Run `venv/bin/python -m compileall -q commerce_adapter backend`
  and report the complete output.
- [x] 8.4 Run `venv/bin/openspec validate
  add-commerce-isolated-twilio-edge --strict` and report the complete
  output.
- [x] 8.5 Run `git diff --check` and report the complete output.
- [x] 8.6 If the local environment cannot run any of the above, report
  the exact error and do not claim the validation passed.