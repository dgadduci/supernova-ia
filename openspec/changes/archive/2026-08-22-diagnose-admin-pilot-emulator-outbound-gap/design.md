# Design: diagnose Admin/Pilot Emulator outbound gap

## Design decision

Instrument the existing provider coordinator at the point where the mapper
already returns staged outbound rows, then project that fact through the
existing exact-receipt Admin/Pilot status route. Add no new worker, queue,
dispatcher call, transaction or recovery path.

The key distinction is between a successful processing commit with zero
outbound rows and a transport/provider rejection. The first is a valid but
diagnostically incomplete pipeline result; the second is owned by the existing
outbound dispatcher and T-C boundaries. The panel must not conflate them.

## Processing event contract

Event name: `provider_inbound_processing_outcome`.

Component: `provider_worker`.

Closed outcomes:

| Outcome | Meaning |
| --- | --- |
| `processed_with_response` | Processing committed and at least one customer response/outbound row was staged. |
| `processed_without_response` | Processing committed and zero customer responses/outbound rows were staged. |
| `retry_scheduled` | Existing bounded retry finalization was committed. |
| `failed_terminal` | Existing terminal finalization was committed. |
| `lease_lost` | Existing conditional finalization lost the lease; no new business outcome is invented. |
| `unavailable` | Existing commerce-availability gate finalized the work as unavailable. |

Safe optional fields:

| Field | Contract |
| --- | --- |
| `response_count` | Non-negative bounded integer, required for processed outcomes. |
| `outbox_row_count` | Non-negative bounded integer, required for processed outcomes and never larger than the configured response bound. |
| `failure_category` | Existing closed processing failure category only when applicable. |
| `correlation_id` | Existing bounded opaque provider-path correlation only when already available; never a body, address, secret or arbitrary text. |

The event must be emitted only after the corresponding existing durable result
is known. Emission failure follows the current best-effort observability
contract and cannot alter processing.

## Coordinator instrumentation

`stage_outbound_rows` already returns one `StagedOutboundRow` per durable row.
Capture that returned list in `_process_locked` and use its length as the
authoritative staged count. Do not re-render responses, call the mapper twice,
query the dispatcher or infer a result from the LLM event.

The normal successful path is:

```text
process_incoming_message
  -> stage_outbound_rows -> staged_rows
  -> finalize_processed
  -> commit
  -> emit processed_with_response OR processed_without_response
```

The existing failure/lease paths retain their current finalization and
rollback. If the implementation needs to pass counts through a result object,
the added fields must be bounded and internal/read-only; they must not change
the public inbound HTTP contract.

No event is emitted before commit as if it were durable. If commit or
conditional finalization fails, use the existing failure path and emit only
the outcome that is actually finalized.

## Exact status projection

Add a closed `EmulatorDiagnostic` object to `EmulatorStatusResponse` while
leaving the existing `status`, `outbound_body`, `provider_message_sid` and
`timeline` fields intact.

The diagnostic should contain only bounded values such as:

- `processing_state`: `not_started`, `pending`, `leased`,
  `processed_with_response`, `processed_without_response`, `retryable`,
  `terminal` or `unknown`;
- `response_count`: nullable bounded integer;
- `outbox_row_count`: nullable bounded integer; and
- `failure_category`: nullable existing closed processing category.

The exact names may follow repository conventions, but the wire model must use
`extra='forbid'`, closed literals and bounded counts. A processing row in
`processed` state with zero exact-receipt outbox rows is the only condition that
may produce `processed_without_response`. A missing processing row is not
proof of that condition.

The query must retain the existing exact filters for synthetic inbound,
commerce, client/session and selected pedido. It must not return raw
`codigo_ultimo_fallo`, body, receipt identifier, provider SID or ORM data.

## Browser behavior

The browser keeps the current six-field server timing timeline and conversation
history. It validates the new diagnostic object before using it.

When the response is `status=processed` and diagnostic state is
`processed_without_response`:

1. render the bounded counts/state in the result area;
2. append a status row such as `Procesado sin respuesta outbound`;
3. stop polling and release the form; and
4. do not create an error row or use the emulator-rejected text.

When polling reaches an HTTP error, malformed response or the attempt limit,
the browser displays a neutral status-query error. When the server reports an
actual `retryable` or `terminal` outbound state, the existing bounded state
message remains available. No browser branch triggers a retry or resubmission.

## Boundaries preserved

- `ProviderInboundMessageCoordinator` remains the transaction owner.
- `stage_outbound_rows` remains the sole response-to-outbox mapper.
- The provider worker remains the only deferred processor.
- `OutboundMessageDispatcher` remains the only outbound transport owner.
- T-C and the standalone emulator remain unchanged.
- Existing `llm_request`, `provider_worker_liveness` and
  `outbound_attempt_outcome` events retain their current semantics.
- The new event explains the missing bridge; it does not replace existing
  worker or outbound evidence.

## Rejected alternatives

- Automatically sending the generic response when the mapper returns no rows
  was rejected because it would change business behavior and could hide the
  pipeline defect.
- Treating every `processed` state without a body as an emulator rejection was
  rejected because no outbound transport request may have occurred.
- Polling the T-C or emulator directly from the browser was rejected because
  it would bypass NovaOrders' exact receipt/outbox projection and broaden
  credentials/configuration exposure.
- Adding a migration or a second durable timeline table was rejected because
  the existing processing/outbox rows plus mapper result can represent the
  required investigation evidence.
- Adding a fixed worker timeout or automatic restart was rejected because the
  existing LLM/lease semantics do not establish a safe timeout boundary.
