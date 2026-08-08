## Why

After the supported-argument correction was deployed, one bounded production
dispatch pass reached Twilio and raised `TwilioRestException`. The adapter
only catches private test markers (`_TwilioTransportError` and
`_TwilioAPIError`), so the real SDK exception escapes through the dispatcher
and the CLI reports `dispatch_pass_failed`. The claimed row remains leased
until its existing expiry recovery path.

## Objective

Translate real Twilio REST API exceptions into the existing typed retryable or
terminal send results, using their HTTP status for retry policy, so one failed
provider request finalizes through the existing lease-conditional outbox path
instead of escaping as a technical dispatch failure.

## Current execution path

`backend.cli.run_outbound_dispatch` builds the real Twilio messages client.
`OutboundMessageDispatcher` commits one lease, calls
`twilio_outbound_adapter.send` outside any SQLAlchemy session, and expects a
typed result to conditionally finalize the row. The real client raises
`TwilioRestException` on a rejected REST request, but `send()` does not catch
that class. Its current `_TwilioAPIError.code` test marker conflates provider
error codes with HTTP statuses and is not a production SDK boundary.

## Scope

- Catch the pinned Twilio SDK's real `TwilioRestException` at the adapter
  boundary.
- Classify retryability from its HTTP `status`: `429` is retryable-429;
  `408`, `425`, and `5xx` are retryable-5xx; other known REST statuses are
  terminal.
- Preserve a sanitized numeric provider error code only when it exists, and
  never expose the exception message, URI, body, destination or credentials.
- Replace the private API-error test marker with SDK-realistic focused tests
  that prove retryable and terminal result/finalization behavior without a
  live request.

## Non-goals

- No retry policy, backoff, maximum-attempt, lease, state-machine, model,
  migration, CLI, callback, inbound, routing, Railway or settings change.
- No attempt to diagnose or modify the Twilio account/sender/template/
  recipient configuration that caused the provider rejection. That diagnosis
  uses sanitized Twilio Console evidence after this code safely records the
  typed terminal result.
- No broad catch-all that converts programming errors, configuration errors or
  unexpected SDK exceptions into provider outcomes.

## Shared boundary, outcomes and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| `TwilioRestException` with HTTP 429 | Existing `retryable` finalization, retryable-429 | later explicit bounded pass |
| `TwilioRestException` with HTTP 408, 425 or 5xx | Existing `retryable` finalization, retryable-5xx | later explicit bounded pass |
| `TwilioRestException` with any other HTTP 4xx | Existing `failed_terminal` finalization | no automatic resend |
| Transport marker already recognized by adapter | Existing retryable-timeout result | later explicit bounded pass |
| `TypeError` or an unexpected exception | Technical failure propagates unchanged | stop and diagnose in a separate approved change |

Provider error `code` is observability only; it MUST NOT be used as the HTTP
retry classifier. No outcome triggers TwiML, inbound replay, a rebuilt
response, another channel, direct Twilio calls or a new transaction.

## Transaction ownership and observability

No transaction ownership changes: the dispatcher keeps the committed claim,
network call with no session, and conditional finalize transaction. The
adapter remains database-free. Persist/log only the existing safe category and
numeric provider code; never persist or print exception text, API URI, request
or response data, E.164 values, message bodies, account SIDs or tokens.

## Expected files

- `backend/services/twilio_outbound_adapter.py`
- `backend/tests/test_twilio_outbound_dispatcher.py`
- This OpenSpec change: proposal, design, capability delta and tasks

Inspect first; adding a file or modifying a dispatcher/repository/CLI test
requires direct demonstrated need and separate approval.

## Focused tests and validation

The implementer shall run locally and report complete output:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_twilio_outbound_dispatcher.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_outbound_dispatcher_callback_integration.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/twilio_outbound_adapter.py backend/tests/test_twilio_outbound_dispatcher.py
openspec validate classify-real-twilio-rest-exceptions-5-6-2 --strict
git diff --check
```

Review complete output before any further production dispatch. Known
pre-existing integration-fixture failures must be identified with their exact
unchanged cause and cannot be counted as passing tests.

## Rollback and deferred limitations

Rollback is a source revert only; no database change is involved. The exact
Twilio Console rejection cause remains an operational follow-up after typed
classification is restored. Automatic dispatch and remote exactly-once
delivery remain deferred.
