# Design: Admin/Pilot Emulator timing observability

## Decision

Extend the existing Emulator status projection and volatile conversation
renderer. Do not add a second processing path or query Railway logs from the
application. The panel receives a bounded server timeline tied to the exact
synthetic inbound identifier and renders it alongside local observation
timestamps.

## Timing model

The timeline uses a closed set of nullable UTC ISO-8601 fields:

```text
inbound_received_at    receipt.fecha_recepcion
llm_requested_at       worker's call to the existing QueryLlm boundary
llm_finished_at        normal LLM response or caught timeout/error completion
llm_outcome            completed | timeout | error
processing_finished_at existing procesamiento fecha_finalizacion, when set
response_staged_at     existing outbound fecha_creacion, when an outbox row exists
```

`llm_requested_at` and `llm_finished_at` are the minimum new durable timing
metadata. They belong to the one-to-one provider processing work item and are
nullable so already existing rows and accepted-but-not-yet-processed rows
remain valid. A timeout has no LLM response body, but it still has a
`llm_finished_at` and `llm_outcome=timeout`.

The implementation SHALL use the existing model/repository transaction
ownership. If the normal business transaction rolls back after a technical
failure, the existing retry/terminal finalization path SHALL retain the
captured timing fields. It SHALL not add a side transaction solely for
observability.

## Correlation

The status route already receives `synthetic_inbound_id` and scopes its
receipt query by the selected commerce. The route SHALL use that same exact
receipt-to-processing relationship to construct the timeline. It SHALL NOT
search by message body, phone number, prompt text or a loosely matching
identifier.

The provider processing path SHALL pass the opaque synthetic inbound
identifier, or the existing equivalent safe correlation value, to the
`llm_request` event. Other QueryLlm callers remain compatible when no
correlation is available. The event contains timing/outcome metadata only.

## Status response contract

The existing response remains backward-compatible and gains one bounded
object:

```json
{
  "status": "pending",
  "outbound_body": null,
  "provider_message_sid": null,
  "timeline": {
    "inbound_received_at": "2026-08-21T18:45:20.570759+00:00",
    "llm_requested_at": null,
    "llm_finished_at": null,
    "llm_outcome": null,
    "processing_finished_at": null,
    "response_staged_at": null
  }
}
```

All timeline fields are nullable and the schema uses a closed set of keys.
The route SHALL preserve its existing fail-closed target, origin and
configuration checks. No timeline from another order, session, commerce or
synthetic inbound may be returned.

## Browser rendering

Each conversation kind stores an optional `observedAt` captured with the
browser clock when that row is first rendered or updated. The display helper
formats only valid bounded timestamps as `HH:MM:SS.mmm` in the browser's
local timezone. The timestamp is rendered through `textContent`/DOM APIs.

The existing per-kind rows remain independent:

```text
Enviado              [HH:MM:SS.mmm]
Estado: accepted     [HH:MM:SS.mmm]
LLM solicitada       [HH:MM:SS.mmm]  (server event, if available)
LLM finalizada       [HH:MM:SS.mmm]  (server event, if available)
Respuesta recibida  [HH:MM:SS.mmm]
Error                [HH:MM:SS.mmm]
```

The UI SHALL distinguish a local `observedAt` from a server timeline value
when both are shown. Missing server values render `—`; they do not become a
generic rejection. Repeated polling updates the existing kind row and its
displayed timestamp without creating duplicates. The existing bounded list,
safe text rendering and eviction rules remain unchanged.

## Failure and compatibility

The existing statuses and terminal set remain unchanged. A technical LLM
timeout remains a worker retry/terminal outcome according to the existing
configuration; this change only exposes its timing and safe outcome. If the
timeline is unavailable, malformed or omitted by an older deployment, the
panel retains its current status and generic fallback behavior while showing
available local observation times.

No provider payload, credential, signature, prompt, LLM response text or raw
exception message is returned by the status route or rendered in the panel.

## Testing strategy

Add focused unit/integration coverage for:

- timestamp capture/formatting and per-kind row updates in the existing panel
  JSDOM/contract tests;
- status projection timeline scoping, nullable milestones and closed schema;
- normal LLM completion and timeout timing persistence/correlation;
- retry/rollback behavior retaining safe timing metadata;
- absence of prompt/response/PII/secret fields in events and HTTP responses.

Do not add Railway, Twilio, Emulator or real-provider integration calls to the
test suite.
