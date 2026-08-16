# Tasks: experimental full LLM outbound response generation

## 1. Experimental Contract

- [x] 1.1 Replace wrapper-only prompt/output contract with a versioned,
  full-message batch contract in the existing styling boundary.
- [x] 1.2 Build and document the factual-preservation prompt hierarchy,
  including explicit menu-line preservation and flavor-subordinate rules.
- [x] 1.3 Retain strict structural JSON parsing, one-call batching, safe
  diagnostics, and deterministic technical fallback without semantic output
  validation or hardcoded flavor phrases.

## 2. Shared Integration

- [x] 2.1 Apply full generated text only to eligible `CustomerResponse`
  messages after deterministic mapping, preserving intent, status and order.
- [x] 2.2 Preserve `neutro`, unusable flavor, and ineligible outcomes as exact
  deterministic no-ops.
- [x] 2.3 Ensure the local channel and outbox reuse the same generated list
  without a second LLM call or transaction ownership.

## 3. Focused Tests and Validation

- [x] 3.1 Cover prompt inputs, batch structure, full-message application,
  technical/per-item fallback, privacy-safe diagnostics, and no transaction
  controls.
- [x] 3.2 Cover local/outbox equivalence, neutral behavior, and the full
  ineligible set.
- [x] 3.3 Run all focused validation commands in `proposal.md`.

## 4. Manual Pilot Calibration Gates (post-deploy only)

- [ ] 4.1 Under `joven`, test greeting, full/category menu, successful add,
  remove, modify, status, summary and confirmation; manually compare each
  generated message with the panel's deterministic order state.
- [ ] 4.2 Under `serio`, repeat representative add/menu/status/confirmation
  cases and confirm natural tone without factual drift.
- [ ] 4.3 Under `neutro`, confirm exact deterministic baseline and no style LLM
  invocation; confirm excluded error/ambiguity/free-text acknowledgement stays
  deterministic under a non-neutral flavor.
- [ ] 4.4 Record calibration defects and either approve promotion of this
  experimental branch or discard it in favor of the wrapper branch.
