# Capability: railway-private-ollama-connectivity

## Purpose

Allow the existing Railway web process to reach the private Ollama node only
through a colocated, userspace Tailscale proxy, while preserving direct local
development behavior and all existing LLM/embedding client contracts.

## ADDED Requirements

### Requirement: colocated userspace Tailscale lifecycle

The Railway application container SHALL run Tailscale in userspace networking
mode in the same container/network namespace as Uvicorn. The proxy SHALL bind
only to loopback, SHALL receive no public Railway domain or exposed port, and
SHALL authenticate with a reusable, ephemeral auth key carrying
`tag:railway`. The application SHALL not start unless Tailscale has completed
bounded readiness successfully; if the Tailscale process terminates after
readiness, the application process SHALL terminate too.

#### Scenario: ready private-network startup

- **WHEN** required database/Tailscale settings are present and the tagged
  node authenticates before the configured deadline
- **THEN** Uvicorn starts with the existing Railway `$PORT` behavior
- **AND** the Tailscale proxy listens only on loopback
- **AND** no auth key, node key, or raw status is written to logs

#### Scenario: Tailscale readiness failure

- **WHEN** Tailscale cannot start, authenticate, or become ready before its
  bounded deadline
- **THEN** Uvicorn does not start
- **AND** the container exits non-zero
- **AND** it does not fall back to direct/public/localhost Ollama access

### Requirement: Ollama-only SOCKS5 proxy setting

The system SHALL expose optional `OLLAMA_PROXY_URL`. When unset, existing
LLM and embedding clients SHALL make their current direct calls. When set, it
MUST be an absolute `socks5://` or `socks5h://` URL and SHALL be passed only to the real HTTP
calls made by `QueryLlm` and `OllamaEmbeddingClient`. It SHALL NOT become a
process-wide proxy or affect Twilio, PostgreSQL, `/health`, migrations, or
other clients.

#### Scenario: Railway SOCKS5 proxy is used for both existing Ollama clients

- **WHEN** `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` is configured
- **AND** either existing client performs its real HTTP request
- **THEN** the request receives a proxy mapping for that loopback proxy
- **AND** its configured Ollama URL/model and existing timeout/error behavior
  are otherwise unchanged

#### Scenario: local development has no proxy

- **WHEN** `OLLAMA_PROXY_URL` is absent
- **THEN** no proxy mapping is supplied to either client
- **AND** the existing local defaults remain unchanged

#### Scenario: invalid proxy configuration fails safely

- **WHEN** `OLLAMA_PROXY_URL` is blank, relative, or has a non-SOCKS5 scheme
- **THEN** settings loading fails with a clear secret-free configuration error
- **AND** no HTTP request is attempted

### Requirement: deployed application-contract verification

The deployment procedure SHALL prove private reachability through the
integrated application container by exercising the configured existing
generate and embed clients. Verification output SHALL contain only safe
metadata: pass/fail, configured model, elapsed time, response status/category,
and embedding dimension. It SHALL NOT retain or log prompts, generated text,
vectors, credentials, or raw Tailscale status.

#### Scenario: generate and embed gates pass

- **WHEN** the integrated deployment can use its loopback proxy to contact
  `100.113.65.40:11434`
- **THEN** the generate client accepts the existing configured response
  contract for `qwen-27b-coding:latest`
- **AND** the embedding client accepts the existing response contract for
  `all-minilm:latest` with dimension `384`
- **AND** the business-readiness network gate is recorded as passed

#### Scenario: HTTP contract fails despite a connected node

- **WHEN** a Tailscale node is connected but either proxied Ollama request
  times out, is denied, or returns invalid data
- **THEN** the business-readiness network gate remains failed
- **AND** no model substitution, public exposure, or direct alternate route
  is introduced
