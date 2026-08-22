# Tasks: diagnose Admin/Pilot Emulator outbound gap

## 0. Approval and discovery

- [x] 0.1 Obtain approval of this OpenSpec before implementation.
- [x] 0.2 Confirm the current provider coordinator, mapper, exact status
  projection and browser polling path before editing.
- [x] 0.3 Confirm that the implementation does not require Railway,
  environment-variable, secret, migration or T-C/emulator changes.

## 1. Structured processing evidence

- [x] 1.1 Add `provider_inbound_processing_outcome` to the existing safe event
  catalogue with closed outcomes, bounded counts and privacy validation.
- [x] 1.2 Capture the existing `stage_outbound_rows` result count exactly once
  in the coordinator without changing mapper, transaction, lease or retry
  ownership.
- [x] 1.3 Emit the authoritative processed-with-response or
  processed-without-response outcome after the existing durable result, plus
  bounded evidence for existing retry/terminal/unavailable/lease-loss paths.
- [x] 1.4 Add focused event and coordinator tests proving zero-response does
  not create a fallback row, replay the inbound or invoke outbound transport.

## 2. Exact Admin/Pilot diagnostic projection

- [x] 2.1 Add a closed diagnostic response model with bounded state/counts and
  no raw identifiers, body, provider payload or exception detail.
- [x] 2.2 Derive the diagnostic only from the exact selected
  pedido/session/comercio, receipt, processing row and receipt-linked outbox
  rows.
- [x] 2.3 Add status-route tests for pending, processed-with-response,
  processed-without-response, retryable, terminal and mismatched-target cases.

## 3. Browser terminal behavior

- [x] 3.1 Validate the diagnostic object in the existing browser polling code.
- [x] 3.2 Stop polling and show a neutral processed-without-response message
  when the server provides definitive evidence.
- [x] 3.3 Replace polling/transport timeout wording that falsely claims an
  emulator rejection; preserve bounded messages for actual outbound states.
- [x] 3.4 Add focused JSDOM/template tests for terminal handling, no false
  rejection, preserved timing timeline and conversation history.

## 4. Validation and handoff

- [x] 4.1 Run the exact focused pytest, Ruff, compileall, strict OpenSpec and
  `git diff --check` commands from `proposal.md` and report complete output.
- [x] 4.2 Report changed files, evidence semantics, deferred limitations and
  confirm that no Railway/configuration/secret/deployment action occurred.
- [x] 4.3 Do not run OpenSpec sync/archive, commit, push, PR or deployment.

## Explicitly out of scope

- [x] 5.1 Do not change the LLM, prompt, recognizer, response mapper business
  decisions, fallback behavior, worker cadence, leases, retries or outbox
  delivery.
- [x] 5.2 Do not add migrations, dashboards, alerts, watchdogs, new queues,
  alternate providers or parallel processing paths.
