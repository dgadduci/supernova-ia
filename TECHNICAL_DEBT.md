# Technical debt register

## Cross-service production observability

**Status:** Pending — separate OpenSpec required.

The application has module-level Python logs and Railway captures process
stdout/stderr, but it has no configured centralized/structured observability
solution. Twilio delivery evidence is partial; LLM and embedding calls record
basic lifecycle metadata; Railway platform/deploy events remain separate.

A future, explicitly approved change should define a privacy-safe common event
schema, structured output/retention, service failure and latency visibility
(Twilio, LLM/Ollama, database and Railway runtime), correlation identifiers,
and alerting/operational ownership. It must establish redaction rules before
exporting events and must not log message bodies, E.164 values, credentials,
tokens, signed URLs, provider payloads or raw exception messages.

This debt is intentionally outside
`harden-provider-outbound-delivery`, which only improves safe outbound Twilio
diagnostics through the existing durable outbox path.
