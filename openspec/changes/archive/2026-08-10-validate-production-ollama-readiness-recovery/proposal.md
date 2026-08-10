# Validate production Ollama-readiness recovery

## Why

The worker readiness gate is deployed and has processed real WhatsApp traffic, but its critical startup boundary has not been demonstrated in production: the worker must start while the controlled readiness probe is not ready, defer a receipt durably, and process it once readiness recovers without terminal exhaustion or duplicate outbound delivery. The probe short-circuits embedding after a generate failure. The gate caches its first success for the worker-process lifetime; stopping Ollama after that success is not a valid readiness-false exercise.

## What Changes

- Add a runbook-only OpenSpec change for one controlled production exercise.
- Record the expected database and delivery evidence for the readiness-false and recovery windows.
- Do not change application code, settings, schema, retry policy, worker bounds, traffic routing, or prompts.

## Objective

Prove the deployed worker's inbound gate defers work safely while Ollama is unavailable and resumes exactly once after readiness succeeds.

## Current execution path

`webhook -> recepcion -> work item -> freshly started provider worker -> readiness probes -> inbound processing -> outbox -> outbound dispatch -> delivered`.

Outbound dispatch continues its bounded pass while readiness is false. Only inbound claiming is gated.

## Scope and non-goals

In scope: one known test client and commerce, one controlled inbound message, safe Railway/Ollama coordination, and read-only evidence collection.

Out of scope: code changes, deployments, database mutation other than normal live-message processing, retry-policy changes, replaying failed-terminal work, production data cleanup, load testing, or any new monitoring feature.

## Shared boundary and transactions

The application and worker retain ownership of all transactions. The exercise does not execute manual inbound/outbound CLIs, insert receipts, modify sessions/orders, or alter queues. Ollama availability is the only temporarily changed dependency state, controlled by the user.

## Authoritative outcomes and fallback

- Valid business outcome: while readiness is false, the test receipt remains pending/claimable and creates no outbound response.
- Authoritative recovery: after controlled generate and embedding probes both succeed, exactly one inbound processing reaches `processed` and exactly one outbound reaches `delivered`.
- Technical failure: terminal failure, a terminal retry count increase caused by the readiness window, duplicate processing/outbound, or readiness false while inbound work is claimed.
- Fallback: restore Ollama availability immediately; the worker must resume normal readiness checks. If evidence is adverse, stop the exercise and do not retry manually until reviewed.
- Must not trigger fallback: an empty worker cycle, outbound processing of pre-existing due rows, or a pending test receipt during the intentionally unavailable window.

## Observability and privacy

Collect IDs, states, attempt counts, safe readiness categories/timestamps, and provider SID only. Before the exercise, verify through a safe control probe that readiness is false: a generate failure is sufficient and reports embedding as skipped by contract; otherwise both probes may be observed. Do not capture customer message bodies, rendered prompts, LLM responses, URLs, credentials, tokens, or environment dumps.

## Expected files

Only this OpenSpec change: `proposal.md`, `design.md`, `tasks.md`, and the worker-readiness delta. No runtime file is expected to change unless a separate remediation proposal is approved.

## Validation and reversibility

The controlled test is reversible by restarting Ollama; no migration, config write, or code rollback is involved. The user must explicitly authorize the temporary Ollama stop immediately before it occurs.

Deferred limitations: this validates one recovery window, not continuous availability, load, alerting, or automatic remediation beyond the deployed gate.
