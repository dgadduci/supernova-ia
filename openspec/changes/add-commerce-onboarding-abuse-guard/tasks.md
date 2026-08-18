# Tasks: add commerce onboarding abuse guard

## 0. Approval and boundary

- [ ] 0.1 Approve this change as a separate component from PR #101 and keep
  the existing NovaOrders Phase 2 adapter contract unchanged.
- [ ] 0.2 Choose Railway Redis versus an externally managed Redis provider and
  document backup, monitoring, recovery and environment separation.
- [ ] 0.3 Approve a staging-only deployment before any production service,
  domain, secret, DNS or Railway mutation.

## 1. Standalone guard service

- [x] 1.1 Add the independent abuse_guard/ service with its own FastAPI
  entrypoint, Dockerfile and minimal requirements; do not import NovaOrders.
- [x] 1.2 Add fail-closed configuration for Redis URL, Bearer token, hash
  secret, port and bounded email/IP/pair limits.
- [x] 1.3 Implement POST /check with exact request authentication, input
  normalization and bounded allowed/decision_id responses.
- [x] 1.4 Implement bounded GET /health and Redis-backed GET /ready responses.

## 2. Distributed limiter and privacy

- [x] 2.1 Implement keyed-hash Redis keys with finite TTLs for email, IP and
  email+IP windows.
- [x] 2.2 Make increment/limit/TTL evaluation atomic across replicas.
- [x] 2.3 Fail closed on every Redis/configuration/credential uncertainty and
  avoid raw identifier/secret logging.
- [x] 2.4 Emit bounded decision and failure events without high-cardinality
  personal-data labels.

## 3. Focused tests and documentation

- [x] 3.1 Add contract tests for allow, rate denial, invalid token, malformed
  input, unsupported action and bounded response bodies.
- [x] 3.2 Add Redis failure, TTL, key-hashing and concurrency-oriented tests
  with an injected fake/test transport; no real external calls.
- [x] 3.3 Add tests proving no imports or persistence path reaches NovaOrders.
- [x] 3.4 Document local execution, Railway second-service setup, private Redis
  variable references, token rotation and staging-only activation. Do not put
  real values in the repository.

## 4. Validation and handoff

- [x] 4.1 Run the exact pytest, Ruff, compileall, strict OpenSpec and diff
  checks from proposal.md, reporting complete output.
- [ ] 4.2 Codex reviews implementation, failure behavior, privacy, tests and
  scope; no production activation is implied by code completion.
- [ ] 4.3 Obtain separate approval before creating Railway/Redis services,
  domains, secrets, DNS, deploy, sync or archive.
