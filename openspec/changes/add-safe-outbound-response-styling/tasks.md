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

## 5. Reactivate the safe wrapper contract

- [x] 5.1 Restore only the static template, styler, bounded style event
  contract and focused styler tests to the safe wrapper contract at `17d7566`;
  do not restore an old branch wholesale.
- [x] 5.2 Verify current mapper/local/outbox integration, one-call batching,
  exact factual containment, neutral/ineligible behavior, privacy and
  caller-owned transactions under the restored wrapper.
- [x] 5.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`.
- [ ] 5.4 After approved deploy, under `joven` verify greeting, full/category
  menu, add/remove/modify and status retain the exact factual message as an
  intact substring with a visible wrapper; under `neutro`, verify exact
  deterministic no-op. Record the experimental full-message pilot failure
  without archiving it as success.

## 6. Expressive wrapper calibration

- [x] 6.1 Expand wrapper validation and prompt wording to allow a short
  complete generic phrase (96 characters per field, 140 combined) while
  retaining one-line, non-numeric, question-free and factual-free constraints.
- [x] 6.2 Preserve the persisted flavor instruction as the sole source for
  tone and emoji choices; do not edit flavor rows, migrations, seeds or API
  configuration.
- [x] 6.3 Add focused boundary, emoji, exact-factual-substring, privacy,
  one-call and no-transaction tests; run focused validation.
- [ ] 6.4 After approved deploy, under `joven` verify longer expressive
  wrappers and contextually appropriate emojis around intact factual messages;
  under `neutro` verify exact deterministic no-op.

## 7. Local pilot styling diagnostics

- [x] 7.1 Add one typed, request-scoped styling diagnostic companion to the
  shared styling/mapper path without changing default response-list callers
  or invoking a second styling request.
- [x] 7.2 Expose only the closed PII-safe diagnostic through the authenticated
  local-test response and render its latest values in the existing pilot panel.
- [x] 7.3 Cover eligible menu/status attempts, bounded fallback/not-attempted
  outcomes, selected-flavor preservation, privacy/closed-schema boundaries,
  local/outbox compatibility and caller-owned transactions.
- [x] 7.4 Run this amendment's focused pytest, Ruff, compileall, strict
  OpenSpec validation and `git diff --check`.
- [ ] 7.5 After approved deploy under `joven`, send a full/category menu and
  status query through the local panel; verify the panel distinguishes
  `applied`, `fallback`, or `not_attempted` without displaying private data.

## 8. Menu wrapper calibration

- [x] 8.1 Revise and version the static prompt so `menu_full` means a generic
  one-line wrapper around an existing menu, never menu reproduction, Markdown
  or factual menu content.
- [x] 8.2 Preserve the selected flavor instruction as the sole source of tone
  and emoji choices; do not hardcode customer-facing menu phrases or change
  wrapper validation, mapper, business data, flavors or transactions.
- [x] 8.3 Add focused prompt-identity and `menu_full` wrapper tests; run this
  amendment's focused pytest, Ruff, compileall, strict validation and diff
  check.
- [x] 8.4 After approved deploy under `joven`, verify full and category menus
  produce `outbound_style.outcome=applied` with a visible valid wrapper, while
  their deterministic menu content remains complete and exact.

## 9. Factual-Claim Guard Amendment

- [x] 9.1 Revise only the static wrapper prompt/version and existing validator
  to reject bounded commerce/logistics claim terms; retain the generic,
  flavor-driven wrapper contract and all existing bounds.
- [x] 9.2 Add focused tests for an otherwise valid in-transit/order-state
  claim falling back as `wrapper_invalid`, generic-wrapper acceptance, exact
  deterministic preservation, diagnostics, one-call behavior, `neutro`, and
  no transaction control.
- [x] 9.3 Run the focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check` commands from `proposal.md`.
- [ ] 9.4 After approved deploy under `joven`, verify greeting, product add,
  and status have visible wrappers that add no unsupported commerce/logistics
  claims; verify a full/category menu remains complete and exact; and verify
  `neutro` remains byte-for-byte deterministic.

## 10. Bounded Invalid-Wrapper Diagnostic Amendment

- [x] 10.1 Preserve the existing one-call shared styler path while classifying
  invalid wrappers internally as claim-guard or shape-invalid, and project
  only the approved bounded aggregate token.
- [x] 10.2 Extend allowlisted event/local diagnostic tokens and add focused
  claim, shape, mixed-batch, empty-wrapper, privacy, one-call, `neutro`,
  local/provider, and no-transaction tests.
- [x] 10.3 Run focused pytest, impacted observability tests, Ruff, compileall,
  strict OpenSpec validation, and `git diff --check`.
- [x] 10.4 After approved deploy under `joven`, verify a fallback visibly
  distinguishes `wrapper_claim_guard` from `wrapper_shape_invalid` without
  exposing wrapper content or private data; then repeat the affected 9.4
  greeting/product-add checks.

## 11. Closed Eligibility Boundary for Order Facts

- [x] 11.1 Restrict the existing styler eligibility map to the closed
  presentation-safe response types: social conversation, menu, product
  information, payment/delivery-method information, commerce address, and
  commerce hours. Exclude all successful order mutations and order lifecycle
  facts from the style request.
- [x] 11.2 Preserve exact deterministic text, intent, status, ordering,
  one-call batching for any remaining eligible responses, privacy, shared
  local/provider behavior, and caller-owned transactions. A turn containing
  only excluded response types makes no style request and reports the existing
  `not_attempted` diagnostic.
- [x] 11.3 Add focused mapping/selection and integration tests for each of the
  eight excluded response types, mixed eligible/excluded batches, no-call
  excluded-only turns, and continued styling of the approved types; run the
  focused validation commands in `proposal.md`.
- [x] 11.4 After approved deploy under `joven`, verify a menu can still apply
  a wrapper, while add/remove/modify, status, summary, confirmation,
  start-order, and empty-order responses are exact deterministic output with
  no styling attempt for excluded-only turns.
