# Tasks

## 1. Specification and diagnosis

- [x] 1.1 Capture the controlled production evidence and verify the real
  deferred execution path.
- [x] 1.2 Define scope, transaction ownership, privacy boundary, fallback, and
  model-compatibility question.
- [x] 1.3 Obtain approval of this proposal before implementation.

## 2. Implementation (after approval)

- [x] 2.1 Add the versioned controlled intent corpus, including all registered
  intents and the payment/observation regressions.
- [x] 2.2 Add a read-only prompt/response audit runner that reports effective
  non-secret settings and exact fixture evidence.
- [x] 2.3 Add safe runtime classification correlation evidence without raw
  customer content or credentials.
- [x] 2.4 Adjust the prompt only if the controlled audit identifies a minimal,
  testable correction for Qwen 7B.
- [x] 2.5 Add focused regression, privacy, and no-double-classification tests.
- [x] 2.6 Review correction: move the static prompt template body (and its
  derived fingerprint) into `backend/diagnostics/prompt_template.py` so the
  runtime fingerprint is computed exclusively from the versioned static
  template and never from the rendered prompt; resolve the effective model
  for runtime events from the live `QueryLlm` settings (with an explicit
  `<unknown>` fallback for injected stubs); and stop attaching the parsed
  LLM response to the runtime `ClassifierCallCompleted` event so the
  echoed customer text cannot leak via the diagnostic boundary.

## 3. Validation and controlled production check

- [ ] 3.1 User runs focused pytest, Ruff, compileall, and strict OpenSpec
  validation locally and provides complete output.
- [ ] 3.2 Run the controlled Railway audit, record the effective model and
  corpus result, and verify no sensitive prompt content reaches runtime logs.
- [ ] 3.3 Repeat the WhatsApp guided-closure path: summary, payment, delivery,
  confirmation, and delivered outbound evidence.
- [ ] 3.4 Review scope, privacy, transaction ownership, and test evidence;
  sync/archive only with separate explicit authorization.
