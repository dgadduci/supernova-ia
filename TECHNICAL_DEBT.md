# Technical debt register

## Cross-service production observability

**Status:** Addressed by archived OpenSpec
`2026-08-11-add-production-observability-cli`.

NovaOrders now emits privacy-safe, versioned operational events to stdout for
the provider worker, outbound/callback Twilio flow, LLM/Ollama and database
technical boundaries. The Railway-backed query CLI provides bounded terminal
access, and the provider-message inventory provides safe read-only retention
evidence.

Centralized alerting, dashboards and a third-party telemetry platform remain
out of scope until they are an operational need. All current observability
surfaces continue to forbid message bodies, E.164 values, credentials, tokens,
signed URLs, provider payloads and raw exception messages.

This work followed `harden-provider-outbound-delivery`, which preserved the
durable outbox and introduced its initial safe outbound diagnostics.

## Durable provider-message retention and safe purge

**Status:** Deferred — not an immediate product need; separate OpenSpec
required before implementation.

The read-only provider-message retention inventory can report safe counts by
age and state, but NovaOrders deliberately has no automatic deletion or purge
of durable provider-message records. Retaining data indefinitely is not the
default policy, but no retention period has been selected yet.

A future, explicitly approved OpenSpec must choose the retention window and
legal/support requirements; define eligible terminal states; preserve active
leases, pending/retry work and required idempotency evidence; and provide a
recoverable `--dry-run` / explicit apply process with rollback and backup
considerations. It must never expose message bodies, E.164 addresses,
provider SIDs, credentials or payloads in inventory or purge output.
