# railway-private-ollama-connectivity Specification

## Purpose
TBD - created by archiving change connect-railway-private-ollama-6-2. Update Purpose after archive.
## Requirements
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

The deployment procedure SHALL prove bidirectional private reachability from
the integrated Railway container through its loopback SOCKS proxy by
exercising the configured existing generate and embed clients. Verification
output SHALL contain only safe metadata: pass/fail, configured model, elapsed
time, response status/category, received-byte indication/count, and embedding
dimension. It SHALL NOT retain or log prompts, generated text, vectors,
credentials, endpoint secrets, or raw Tailscale status.

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

#### Scenario: generate and embed gates pass with returned response data

- **WHEN** the integrated deployment can use its loopback proxy to contact
  `100.113.65.40:11434`
- **AND** the proxied embedding request receives response bytes and a complete
  valid response
- **THEN** the generate client accepts its existing configured response
  contract
- **AND** the embedding client accepts the existing `all-minilm:latest`
  response contract with dimension `384`
- **AND** the business-readiness network gate is recorded as passed

#### Scenario: Ollama returns 200 but Railway receives no embedding response bytes

- **WHEN** the Ollama host records successful processing of a proxied
  `/api/embed` request
- **AND** the integrated Railway request times out or otherwise receives no
  response bytes through the loopback SOCKS proxy
- **THEN** the business-readiness network gate remains failed
- **AND** the incident SHALL be diagnosed and corrected only within the
  Railway–Tailscale–Ollama infrastructure boundary
- **AND** the system SHALL NOT change application timeouts, embedding payload
  or parsing, model selection, proxy scope, or use a direct/public fallback
