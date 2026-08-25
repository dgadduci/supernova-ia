# Capability: query-llm-response-transport-diagnostics

## ADDED Requirements

### Requirement: Incremental non-streaming response evidence

The QueryLlm HTTP boundary SHALL request an HTTP streaming response while
preserving the Ollama payload's `stream: false` value. It SHALL emit bounded,
privacy-safe evidence after headers return, after the first body chunk returns,
and after the whole body is consumed, before existing JSON/result evidence.

The diagnostic SHALL preserve request count, timeout, proxy selection, result
parsing, transaction ownership and business fallback behaviour. It SHALL close
the response on all paths and SHALL NOT expose header values or body content.

#### Scenario: Header-only partial trace is honest

- **WHEN** headers return but body iteration later blocks or times out
- **THEN** the trace contains `response_headers_received` and no fabricated
  `body_completed`
- **AND THEN** the existing timeout behaviour remains authoritative

#### Scenario: Complete body retains existing parsing

- **WHEN** headers and all chunks are received
- **THEN** the trace contains first-chunk and body-completed evidence before
  the current JSON/result phases
- **AND THEN** the parsed result is equivalent to the prior non-streaming path

