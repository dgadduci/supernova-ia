## Why

The durable outbox safely separated customer/order processing from Twilio
delivery, but outbound failures are not yet consistently diagnosable from the
automatic worker. The terminal/retry state persists a safe category and code,
and the manual CLI prints per-attempt results, yet the worker only reports exit
codes and bounds. Technical failures carry only an exception class. There is no
single Twilio delivery event contract across adapter, dispatcher and worker.

The observed Twilio 63038 was an account-trial daily cap that has since been
removed operationally. It is evidence that failure evidence needs to be
observable, not a reason to make one provider code the policy centre.

## Objective

Make every outbound Twilio attempt and durable terminal/retry outcome safely
observable and operationally diagnosable, while preserving the durable outbox,
existing bounded retry classification, and strict isolation from customer
intent and order mutation.

## Current execution path

`ProviderInboundMessageCoordinator` owns receipt, session/order pipeline and
outbox staging in the caller-owned transaction. `OutboundMessageDispatcher`
claims one due row in a committed lease transaction, invokes the Twilio SDK
outside any session, then conditionally finalizes it as `accepted`,
`retryable`, or `failed_terminal`. The adapter maps known REST/transport
results to safe category/code values. The worker runs bounded inbound then
outbound CLI passes; callbacks advance accepted rows monotonically.

The dispatcher currently emits only a late-acceptance log. Generic technical
failure reaches the CLI/worker with a type-only record. The configured
`outbound_bound=16` is a sequential pass budget, not a concurrency/rate
control and not a diagnosis of any provider rejection.

## Scope

- Define a single safe outbound-attempt event/record shape containing outcome,
  stable outbox id, attempt count, durable state, failure category, provider
  HTTP status when known, provider error code when known, and exception class
  only for technical failure.
- Emit it at the dispatcher/CLI/worker boundary for accepted, retry scheduled,
  terminal provider failure, no-due work, and technical dispatch failure.
- Preserve HTTP-status-based retry policy: typed transport failures, 408, 425,
  429 and 5xx retain existing bounded retry behavior; other classified REST
  rejections remain terminal. Provider code enriches observability and MUST NOT
  silently become a new retry policy without separately approved evidence.
- Ensure automatic-worker cycle logs include aggregated safe outcome/category
  counts so terminal Twilio failures are not reduced to an exit code.
- Add focused safe-observability and no-regression tests.

## Non-goals

- No migration, outbox redesign, new message pipeline, new queue, direct
  provider retry loop, global rate/concurrency limiter, webhook rewrite, LLM,
  LangGraph, order work, alternate channel or provider-account change.
- No centralized observability platform, Sentry integration, metrics backend,
  alerts, trace correlation or Railway-console configuration; those are a
  separate cross-cutting phase.
- No raw outbound/inbound bodies, E.164 addresses, callback signatures, URLs,
  credentials, account identifiers, provider payloads or exception messages in
  application logs.

## Authoritative outcomes and fallback

| Condition | Durable outcome | Required observation / must not happen |
| --- | --- | --- |
| First valid inbound processing | `pending` outbox row in the coordinator transaction | receipt/sequence prevents response rebuilding or duplicate staging |
| Twilio returns a SID | `accepted` | safe accepted event; missing callback must not resend |
| Typed transport, 408, 425, 429 or 5xx | `retryable` with existing backoff | safe retry event including category/code/status when known; no inline retry |
| Other classified REST rejection or exhausted retries | `failed_terminal` | safe terminal event and worker aggregate; no silent resend |
| Unknown SDK/programming/configuration error | technical failure; lease recovery stays authoritative | safe technical event with class only; no provider misclassification |
| Signed callback | existing monotonic delivered/terminal transition | existing callback observability remains authoritative |

No delivery result may rerun customer intent, restage a response, mutate an
order, or cause a fallback through TwiML/SMS/another channel.

## Transaction ownership and observability

The coordinator preserves caller-owned transaction ownership. The dispatcher
retains the committed claim and conditional-finalization transactions; the
network call remains outside any database session. The adapter and worker own
no business transaction. Existing durable safe category/code columns suffice,
so no migration is expected.

The application log is the delivery diagnostic surface in this phase. Events
use a fixed name and a documented allowlist of safe fields; raw exception text
and customer/provider content are forbidden. Operators use the outbox id plus
safe category/code/status to reconcile with Twilio Console and Railway logs.

## Expected files and validation

Expected implementation surface:

- `backend/services/twilio_outbound_adapter.py`
- `backend/services/outbound_message_dispatcher.py` and dispatch types
- `backend/cli/run_outbound_dispatch.py`
- `backend/cli/run_provider_processing_worker.py`
- focused outbound adapter/dispatcher, CLI and worker tests
- this OpenSpec change and provider-outbound capability delta

The implementer must run locally and provide complete output:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_twilio_outbound_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_provider_processing_worker.py backend/tests/test_outbound_dispatcher_callback_integration.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/twilio_outbound_adapter.py backend/services/outbound_message_dispatcher.py backend/services/outbound_dispatch_types.py backend/cli/run_outbound_dispatch.py backend/cli/run_provider_processing_worker.py backend/tests/test_twilio_outbound_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/twilio_outbound_adapter.py backend/services/outbound_message_dispatcher.py backend/services/outbound_dispatch_types.py backend/cli/run_outbound_dispatch.py backend/cli/run_provider_processing_worker.py
openspec validate harden-provider-outbound-delivery --strict
git diff --check
```

## Rollback and deferred limitations

This is source-only reversible and leaves durable rows valid. Deferred:
centralized cross-service observability, alerts/metrics, safe operator recovery
of terminal rows, provider-specific retry-after support, and any throughput or
concurrency controls justified by future measured evidence.
