# Tasks

## 1. Paired quantity recognition and pending preservation

- [x] 1.1 Extract source `cantidad` and optional `cantidad_destino` only when
  explicit positive quantities occur on both sides of `por`; preserve legacy
  one/zero-quantity behavior; surface an explicit-but-invalid destination
  quantity (zero, negative, or decimal — including ``1.5`` / ``1,5``) through
  a dedicated `cantidad_destino_invalid` signal so the legacy equal-quantity
  fallback can never collapse it into the absent case. Detection of decimal
  / non-integer tokens works on the raw destination text (before
  normalization strips ``.`` and ``,``) and is bounded by the raw ``por``
  boundary, which is semantically compatible with `_split_on_por()` —
  ``por`` is recognised as a standalone token bounded by start, end,
  whitespace, or punctuation (``:``, ``,``, ``.``, ``;``, ``!``, ``?``), and
  is never confused with substrings of longer words (``porcentaje``).
- [x] 1.2 Thread optional destination quantity through initial ready/pending
  intents and both resolver stages without candidate expansion or transaction
  control.

## 2. Atomic mutation and response

- [x] 2.1 Validate and delegate effective source/destination amounts through
  the existing caller-owned handler/service boundary; support legacy pending
  payloads lacking `cantidad_destino`.
- [x] 2.2 Atomically decrement/delete source by its amount and
  create/increment destination by its amount after all existing validations;
  preserve price and unique-line rules.
- [x] 2.3 Enrich the result and render deterministic distinct-quantity
  confirmations while preserving legacy equal-quantity responses; render a
  deterministic invalid-quantity rejection message when
  `cantidad_destino_invalid` is set.

## 3. Focused proof

- [x] 3.1 Cover paired digit/word extraction, compatibility, invalid amounts
  (zero, negative, decimal ``1.5`` / ``1,5``), ready/pending preservation and
  restricted candidates.
- [x] 3.2 Cover handler/service atomic `2 -> 1`, consolidation, ceiling,
  destination validation, no mutation on rejection and transaction ownership.
- [x] 3.3 Cover exact response text and real pending-destination clarification
  followed by `chica`, source -2 / destination +1 and cleanup.
- [x] 3.4 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 4. Pilot gate

- [x] 4.1 After approved deploy, in a clean local pilot draft execute
  `cambiar dos napolitanas grandes por una pizza de mozzarella`, select
  `chica` if prompted, and verify source -2 / destination +1, response,
  lines, and cleared context/pending.
- [x] 4.2 Re-run one explicit equal-quantity and one omitted-quantity
  modification regression; consider archive only after user approval.
