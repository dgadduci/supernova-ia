# Tasks: safe outbound response styling

## 1. Shared Styling Contract

- [x] 1.1 Add a small outbound styling service that resolves only an active,
  non-neutral selected commerce flavor and identifies approved normal response
  types while excluding errors, rejections, ambiguities, and free-text input.
- [x] 1.2 Define a versioned static JSON prompt and strict wrapper parser;
  validate one ordered wrapper per eligible response and compose around the
  exact factual message only.
- [x] 1.3 Add bounded PII-safe diagnostics without logging prompt, customer
  text, flavor instruction, model output, or identifiers.

## 2. Shared Mapper Integration

- [x] 2.1 Invoke the styler once, after deterministic mapping/coalescing, in
  `build_customer_responses`; preserve original ordering, intent, and status.
- [x] 2.2 Ensure `stage_outbound_rows` consumes that shared result without a
  second style call or any new transaction ownership.
- [x] 2.3 Preserve exact factual fallback for neutral/absent/inactive flavor,
  ineligible output, and all styling failures.

## 3. Focused Coverage and Validation

- [x] 3.1 Test valid wrappers, one-call batching, no factual text in the
  prompt, exact factual containment, mixed eligible/ineligible ordering, and
  local/outbox equivalence.
- [x] 3.2 Test fail-closed behavior for neutral/absent/inactive flavor and
  malformed/schema/transport/unexpected failures, with no transaction control
  or PII leaks.
- [x] 3.3 Run the focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check` commands in `proposal.md`.

## 4. Pilot Gate (post-deploy only)

- [ ] 4.1 Select a non-neutral flavor for one pilot commerce and verify a
  greeting/menu plus a successful product mutation have a style wrapper while
  keeping the factual sentence (product and quantity) exact.
- [ ] 4.2 Select `neutro` and verify the same normal responses are exactly
  baseline deterministic text; verify an error or pending ambiguity remains
  unchanged under a non-neutral flavor.
