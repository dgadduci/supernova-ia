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
