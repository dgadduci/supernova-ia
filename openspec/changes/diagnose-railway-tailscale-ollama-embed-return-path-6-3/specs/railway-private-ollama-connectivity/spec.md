# Capability: railway-private-ollama-connectivity

## MODIFIED Requirements

### Requirement: deployed application-contract verification

The deployment procedure SHALL prove bidirectional private reachability from
the integrated Railway container through its loopback SOCKS proxy by
exercising the configured existing generate and embed clients. Verification
output SHALL contain only safe metadata: pass/fail, configured model, elapsed
time, response status/category, received-byte indication/count, and embedding
dimension. It SHALL NOT retain or log prompts, generated text, vectors,
credentials, endpoint secrets, or raw Tailscale status.

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
