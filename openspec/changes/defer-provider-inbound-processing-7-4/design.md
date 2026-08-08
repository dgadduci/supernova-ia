## Decision

Use a durable two-step, manually driven inbound boundary. The webhook becomes
an acceptance transaction only; an explicit CLI processes durable work later.
This is the smallest reliable response to Twilio's 15-second deadline that
does not introduce a worker, scheduler or ephemeral in-process background task.

```mermaid
flowchart LR
  T["Twilio signed webhook"] --> A["Validate route + claim receipt + stage inbound work"]
  A --> R["Return empty TwiML within provider deadline"]
  R --> Q["Durable pending inbound work"]
  Q --> C["Explicit bounded inbound CLI"]
  C --> P["Existing session/pedido + intent pipeline"]
  P --> O["Existing durable outbound outbox"]
  O --> D["Existing explicit outbound dispatcher"]
```

## Durable work record

The new table is receipt-owned and has a unique foreign key to
`recepciones_mensajes_proveedor`. It contains:

- receipt relation, state, attempt count, due timestamp, lease token/expiry,
  safe failure category/code, creation/finalization timestamps;
- nullable transient `mensaje` body, populated only while the work is pending,
  leased or retryable; and
- no address copy. The deferred processor derives the response destination from
  the still-authoritative client relation on the receipt.

The state model mirrors the minimal proven outbound semantics:
`pending`, `leased`, `retryable`, `processed`, `failed_terminal`. A work item
is claimed with a lease in a short transaction; an expired lease becomes due
again. A bounded attempt budget and fixed/documented backoff prevent loops.

## Acceptance

After existing Twilio signature, client and channel routing checks, acceptance
validates the same active client/channel/commerce authority as the current
coordinator. For a first valid `(provider, receipt identifier)` it inserts the
receipt and one pending work item containing the message body in one
transaction, then commits and returns empty TwiML. A duplicate returns empty
TwiML without a new work item. Invalid context preserves existing generic
control TwiML and no persistence.

The acceptance path MUST NOT import or call the classifier, recognizer,
session/pedido staging, message pipeline, response mapper or outbound mapper.
That keeps it bounded by validation and one short database transaction.

## Processing

`backend.cli.run_inbound_processing` claims at most
`--max-items-per-pass N` due work rows, defaulting to one. For each leased row,
it runs the existing provider business path using the already-committed receipt:

1. acquire/stage the active session;
2. create/associate a draft pedido if the session lacks one;
3. run the existing incoming-message pipeline on the stored body;
4. map and stage outbound rows referencing the existing receipt; and
5. mark the work `processed`, clear the transient body, and commit once.

Technical exceptions roll back the item turn's business effects, then
finalize/schedule the work using a safe failure category without raw exception
text. Terminal exhaustion clears the body. A duplicate receipt never invokes
this path twice.

The processor operates in receipt creation order for due rows. It must not
process a later work item for the same client/channel while an earlier work item
is in any non-terminal state (`pending`, `leased` or `retryable`); this
preserves conversational order in the manual pilot. The conversational block
is enforced inside the single `claim_due` query as a correlated `NOT EXISTS`
subquery that joins the candidate's own receipt row, the receipt row of the
candidate blocker, and the candidate blocker's work row. The exclusion
predicate is:

* a blocker receipt created strictly earlier for the same `(canal_id,
  cliente_id)` pair — "earlier" means
  `(fecha_recepcion, recepciones_mensajes_proveedor.id) < (candidate_fecha,
  candidate_id)`;
* AND the blocker work is `pending`, `leased`, or `retryable`. The
  conversational block is unconditional based on state and is INDEPENDENT
  of `lease_expira_en` and `proximo_intento_en`: a `retryable` blocker with
  a future `proximo_intento_en` and a `leased` blocker with an expired lease
  both remain blockers for a later candidate;
* AND the blocker work is NOT a `processed` or `failed_terminal` row, which
  never block a later item in the same conversation.

The candidate's own eligibility remains time-bounded so the bounded retry
budget is preserved: `_claim_eligible_predicate` still requires a
`retryable` candidate to have a due (or unset) `proximo_intento_en` and a
`leased` candidate to have an expired `lease_expira_en` (lease-recovery
path). The conversational block targets STRICTLY later rows, so a candidate
that is its own earliest unresolved row remains eligible: an earlier
`leased` row whose lease has expired is still eligible for its own claim
through the lease-recovery path while continuing to block every later
candidate in the same conversation.

The eligible subquery still uses `FOR UPDATE SKIP LOCKED`, still returns at
most one id, and the surrounding `UPDATE` still pins the lease token and
increments the attempt counter as before. Items from conversations that do not
share the `(canal_id, cliente_id)` pair remain fully independent.

## Rejected alternatives

- **Continue synchronous webhook processing:** disproven by Railway's 14,977 ms
  request and Twilio timeout.
- **FastAPI background task:** response may succeed, but process restart loses
  the work; it is not durable or idempotent.
- **Return success and drop the body:** loses a customer message.
- **Automatic worker/scheduler:** useful later, but explicitly outside this
  controlled pilot; the bounded CLI provides a reversible operational seam.

## Validation commands

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py backend/tests/test_run_outbound_dispatch_cli.py
PYTHONPATH=. venv/bin/python -m ruff check backend/models/procesamiento_mensaje_proveedor.py backend/repositories/procesamiento_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/routers/twilio_webhook.py backend/cli/run_inbound_processing.py backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/procesamiento_mensaje_proveedor.py backend/repositories/procesamiento_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/routers/twilio_webhook.py backend/cli/run_inbound_processing.py backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py
PYTHONPATH=. venv/bin/python -m alembic upgrade head
openspec validate defer-provider-inbound-processing-7-4 --strict
git diff --check
```
