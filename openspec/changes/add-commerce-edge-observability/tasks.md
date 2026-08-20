# Tasks: add commerce edge observability

## 0. Approval and discovery

- [x] 0.1 Obtain approval of this OpenSpec before implementation.
- [x] 0.2 Confirm the archived `add-commerce-isolated-twilio-edge` remains the
  only runtime source of the isolated edge, that no business behavior is
  included in this change, and that core pre-decision HTTP failures remain
  outside the core business-outcome event boundary.
- [x] 0.3 Confirm the existing core JSON event sink and adapter isolation
  boundary are the only observability surfaces used.

## 1. Core event contract

- [x] 1.1 Add `commerce_installation_inbound_outcome` to the existing core
  observability catalogue with closed outcomes, reasons, the two documented
  component values and validation.
- [x] 1.2 Emit one event from every validated isolated-ingress business branch
  without logging identifiers, body, credentials or exception text; preserve
  the existing non-200 pre-decision branches without inventing a core business
  outcome.
- [x] 1.3 Add focused core contract and route assertions, including the
  pre-decision boundary, both-component parser compatibility and
  emitter-failure preservation.

## 2. Adapter event contract

- [x] 2.1 Add the backend-independent bounded JSON-line emitter for the T-C
  adapter.
- [x] 2.2 Replace the adapter's isolated inbound outcome log calls with one
  event per existing local outcome branch, mapping core non-2xx responses to
  `unreachable/core_http_failure` and malformed core responses to
  `unreachable/core_invalid_response`, while preserving HTTP/TwiML behavior.
- [x] 2.3 Add adapter emitter and webhook-route tests for every branch and the
  no-secrets/no-PII invariant.

## 3. Validation and handoff

- [x] 3.1 Minimax 3 runs the exact focused pytest, Ruff, compileall and strict
  OpenSpec commands from `proposal.md` and reports complete output.
- [x] 3.2 Codex reviews the event catalogue, privacy boundary, route behavior,
  transaction ownership, tests and complete validation output.
- [ ] 3.3 Obtain separate authorization before deploying to Railway or
  changing any production/test configuration.
- [ ] 3.4 Sync and archive only after implementation review and validation
  pass with explicit user authorization.
