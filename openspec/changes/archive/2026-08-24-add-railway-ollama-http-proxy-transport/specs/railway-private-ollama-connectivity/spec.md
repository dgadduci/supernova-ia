# railway-private-ollama-connectivity Specification

## MODIFIED Requirements

### Requirement: Ollama-only SOCKS5 proxy setting

The system SHALL expose optional `OLLAMA_PROXY_URL`. When unset, existing LLM
and embedding clients SHALL make their current direct calls. When set, it MUST
be an absolute `socks5://`, `socks5h://`, or loopback `http://` URL and SHALL
be passed only to the real HTTP calls made by `QueryLlm` and
`OllamaEmbeddingClient`. It SHALL NOT become a process-wide proxy or affect
Twilio, PostgreSQL, `/health`, migrations, or other clients. The configured
URL is the sole transport selection; the system SHALL NOT fall back to another
proxy or to a direct route.

#### Scenario: Railway SOCKS5 proxy remains supported

- **WHEN** `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` is configured
- **AND** either existing client performs its real HTTP request
- **THEN** the request receives the existing SOCKS5 proxy mapping
- **AND** its configured Ollama URL/model and existing timeout/error behavior
  are otherwise unchanged

#### Scenario: Railway HTTP proxy is explicitly selected

- **WHEN** `OLLAMA_PROXY_URL=http://127.0.0.1:1056` is configured
- **AND** either existing client performs its real HTTP request
- **THEN** the request receives the HTTP proxy mapping
- **AND** no SOCKS5 or direct mapping is selected implicitly
- **AND** its configured Ollama URL/model and existing timeout/error behavior
  are otherwise unchanged

#### Scenario: local development has no proxy

- **WHEN** `OLLAMA_PROXY_URL` is absent
- **THEN** no proxy mapping is supplied to either client
- **AND** the existing local defaults remain unchanged

#### Scenario: invalid proxy configuration fails safely

- **WHEN** `OLLAMA_PROXY_URL` is blank, relative, credentialed, malformed, or
  has an unsupported scheme
- **THEN** settings loading fails with a clear secret-free configuration error
- **AND** no HTTP request is attempted

## ADDED Requirements

### Requirement: loopback HTTP userspace proxy listener

The Railway application container SHALL start a loopback-only Tailscale
userspace HTTP proxy listener at `127.0.0.1:1056` alongside the existing
loopback-only SOCKS5 listener at `127.0.0.1:1055`. Both listeners SHALL remain
private to the container and SHALL use the existing bounded Tailscale
readiness and supervision lifecycle.

#### Scenario: both explicit proxy options are available

- **WHEN** the container starts successfully in userspace networking mode
- **THEN** the SOCKS5 listener remains available at `127.0.0.1:1055`
- **AND** the HTTP listener is available at `127.0.0.1:1056`
- **AND** neither listener is exposed through a Railway public port

#### Scenario: Tailscale startup fails

- **WHEN** Tailscale cannot authenticate, become ready, or remain alive
- **THEN** the application does not start or is terminated by the existing
  supervision behavior
- **AND** it does not fall back to a direct or public Ollama route

### Requirement: explicit and reversible transport selection

The system SHALL treat `OLLAMA_PROXY_URL` as an explicit operator-selected
transport. It SHALL NOT automatically switch between HTTP, SOCKS5, or direct
access after a request or startup failure.

#### Scenario: operator rolls back to SOCKS5

- **WHEN** the operator restores `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055`
- **THEN** subsequent Ollama requests use the existing SOCKS5 path
- **AND** no code or database rollback is required

#### Scenario: selected HTTP proxy fails

- **WHEN** `OLLAMA_PROXY_URL=http://127.0.0.1:1056` is selected and the HTTP
  proxy cannot deliver a request
- **THEN** the existing client/worker error and retry semantics remain visible
- **AND** the system does not retry through SOCKS5 or direct access
