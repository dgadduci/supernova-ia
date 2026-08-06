## 1. Provider-edge contract

- [x] 1.1 Add the minimal Twilio SDK dependency and fail-closed ingress
  settings without exposing credentials.
- [x] 1.2 Add a small signature/form adapter with no SQLAlchemy or transaction
  control.

## 2. HTTP translation

- [x] 2.1 Add and register one synchronous Twilio inbound webhook route.
- [x] 2.2 Resolve existing active client and dedicated destination through
  existing boundaries, then delegate only the final command to Phase 5.4.
- [x] 2.3 Render the documented acknowledgement, duplicate and safe-control
  TwiML shapes without durable delivery/replay behavior.

## 3. Focused tests

- [x] 3.1 Cover valid signed dedicated processing and exact command mapping.
- [x] 3.2 Cover signature tampering/rejection with zero downstream calls.
- [x] 3.3 Cover pre-core routing/client outcomes, duplicates, invalid core
  context and propagated technical failures.
- [x] 3.4 Cover settings and static transaction/provider boundary rules.

## 4. Signature validation: full form and real query string

- [x] 4.1 Read the complete submitted form from `Request` in the webhook
  handler and pass it to the adapter/SDK validator instead of truncating to
  the four documented fields. Twilio signs every POST parameter; omitting
  extras made legitimate requests return 403.
- [x] 4.2 Pass the actual query string of the incoming request when
  constructing/validating the canonical signature URL.
- [x] 4.3 Continue to extract only `MessageSid`, `From`, `To`, `Body` from
  the validated form for the existing normalization/core flow.
- [x] 4.4 Preserve invariants: invalid signature still performs zero
  database/core calls; router never invokes `commit`/`rollback`/`flush`;
  core 5.4 remains the sole transaction owner; auth token, signature and
  raw body are not logged; no replay.
- [x] 4.5 Add focused tests proving (a) a valid signature is accepted when
  the POST contains one or more extra Twilio parameters, (b) modifying a
  signed extra parameter returns 403 with zero downstream calls, and (c)
  the request's actual query string is included in the canonical
  validation URL.

## 5. Sync handler + async form dependency

- [x] 5.1 Keep `post_twilio_whatsapp_inbound` as a synchronous `def`
  handler and isolate the async form read in a single
  `read_full_form` dependency that performs `await request.form()`
  and returns the complete `Mapping[str, str]` of string fields.
- [x] 5.2 The synchronous handler keeps validating the signature
  with the full POST form and the actual request query string,
  before any DB lookup, routing or core call; it still extracts
  only `MessageSid`, `From`, `To` and `Body` afterwards.
- [x] 5.3 Preserve every Phase-5.5 invariant: zero downstream calls
  on invalid signature, no router-level `commit`/`rollback`/`flush`,
  core 5.4 as the sole transaction owner, no token/signature/body
  logs, no response replay.
- [x] 5.4 Static/focused tests demonstrate the public endpoint is
  synchronous, the dependency is the only async seam, and the
  full-form + signed-query tests still pass through the
  dependency.

## 6. Validation

- [x] 6.1 Run focused pytest, Ruff and compileall on touched files.
- [x] 6.2 Run strict OpenSpec validation and `git diff --check`.
- [x] 6.3 Record exact outputs and any pre-existing blockers here.

### Recorded outputs

```
$ PYTHONPATH=. venv/bin/pytest -q backend/tests/test_twilio_inbound_adapter.py backend/tests/test_twilio_webhook.py backend/tests/test_llm_settings.py backend/tests/test_provider_message_receipt_core.py
99 passed, 1 warning, 135 subtests passed

$ PYTHONPATH=. venv/bin/python -m ruff check backend/config/settings.py backend/services/twilio_inbound_adapter.py backend/routers/twilio_webhook.py backend/main.py backend/tests/test_twilio_inbound_adapter.py backend/tests/test_twilio_webhook.py backend/tests/test_llm_settings.py
Found 3 errors (3 pre-existing B017 instances in backend/tests/test_llm_settings.py; the new Twilio frozen-field assertion uses dataclasses.FrozenInstanceError to avoid the warning, and the read_full_form dependency is wired without a stray noqa).

$ PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/services/twilio_inbound_adapter.py backend/routers/twilio_webhook.py backend/main.py backend/tests/test_twilio_inbound_adapter.py backend/tests/test_twilio_webhook.py backend/tests/test_llm_settings.py
(no output)

$ openspec validate add-twilio-inbound-webhook-5-5 --strict
Change 'add-twilio-inbound-webhook-5-5' is valid

$ git diff --check
(no output)
```
