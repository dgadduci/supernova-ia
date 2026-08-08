## 1. Evidence and approval

- [x] 1.1 Record the sanitized baseline: passing generate, failing embed,
  zero-byte timeout, Ollama 200 access-log timing, direct external embed
  success, and direct-UDP `tailscale ping`.
- [x] 1.2 Run the bounded bidirectional diagnostic from the integrated Railway
  container and correlate it with a safe Ollama log observation.
- [x] 1.3 Inspect deployed Tailscale/Ollama versions, userspace daemon mode,
  loopback listener, and relevant user-owned host network/service settings.
- [x] 1.4 Identify the causal infrastructure mismatch and obtain explicit
  approval for one minimal correction. Do not apply a change while evidence is
  inconclusive.
- [x] 1.5 Run the approved reversible `tailscaled` version-alignment
  experiment, verify the deployed version, record its unchanged no-byte
  timeout, and roll it back. Do not repeat it as a proposed remedy.
- [x] 1.6 Inspect the Ollama host OS, active firewall mechanism, Tailscale
  interface MTU, and any existing MSS-clamping rule without changing network
  state. Select no adjustment until this evidence is reviewed.
- [x] 1.7 Propose one host-local, temporary MTU/MSS experiment with an exact
  rollback, then obtain approval before applying it.

## 2. Minimal infrastructure correction

- [x] 2.1 Implement only the approved Railway/Tailscale/Ollama infrastructure
  correction, preserving loopback-only SOCKS, tagged ephemeral identity,
  least-privilege access, and client-scoped proxy isolation.
- [x] 2.2 Update only the affected deployment runbook and focused safe
  diagnostic/startup checks. Do not modify application clients, settings,
  recognition, models, timeouts, Twilio, or product-domain code.

## 3. Verification and handoff

- [x] 3.1 Re-run the bounded proxy diagnostic and retain safe evidence of
  returned bytes and terminal HTTP outcome.
- [x] 3.2 Re-run the integrated Railway contract helper; require
  `generate=passed`, `embed=passed`, and dimension `384`.
- [ ] 3.3 The user runs focused validation for touched files, Ruff,
  `compileall`, strict OpenSpec validation, and `git diff --check` locally;
  provide complete output for review.
- [ ] 3.4 Review the evidence and implementation scope. Do not begin Twilio
  E2E, synchronize specs, archive, commit, or deploy without separate
  authorization.
