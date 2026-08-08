## 1. Evidence and approval

- [ ] 1.1 Record the sanitized baseline: passing generate, failing embed,
  zero-byte timeout, Ollama 200 access-log timing, direct external embed
  success, and direct-UDP `tailscale ping`.
- [ ] 1.2 Run the bounded bidirectional diagnostic from the integrated Railway
  container and correlate it with a safe Ollama log observation.
- [ ] 1.3 Inspect deployed Tailscale/Ollama versions, userspace daemon mode,
  loopback listener, and relevant user-owned host network/service settings.
- [ ] 1.4 Identify the causal infrastructure mismatch and obtain explicit
  approval for one minimal correction. Do not apply a change while evidence is
  inconclusive.

## 2. Minimal infrastructure correction

- [ ] 2.1 Implement only the approved Railway/Tailscale/Ollama infrastructure
  correction, preserving loopback-only SOCKS, tagged ephemeral identity,
  least-privilege access, and client-scoped proxy isolation.
- [x] 2.2 Update only the affected deployment runbook and focused safe
  diagnostic/startup checks. Do not modify application clients, settings,
  recognition, models, timeouts, Twilio, or product-domain code.

## 3. Verification and handoff

- [ ] 3.1 Re-run the bounded proxy diagnostic and retain safe evidence of
  returned bytes and terminal HTTP outcome.
- [ ] 3.2 Re-run the integrated Railway contract helper; require
  `generate=passed`, `embed=passed`, and dimension `384`.
- [ ] 3.3 The user runs focused validation for touched files, Ruff,
  `compileall`, strict OpenSpec validation, and `git diff --check` locally;
  provide complete output for review.
- [ ] 3.4 Review the evidence and implementation scope. Do not begin Twilio
  E2E, synchronize specs, archive, commit, or deploy without separate
  authorization.
