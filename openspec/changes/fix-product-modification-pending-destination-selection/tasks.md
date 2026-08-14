# Tasks

## 1. Restricted destination refinement

- [x] 1.1 Add exact bare-presentation matching only to modification
  `destination_selection`, using only the existing restricted destination
  catalog and one optional leading article.
- [x] 1.2 Route one match through the existing ready path without generic
  recognition or transaction control; retain current fallback on zero/multiple
  matches and preserve source/quantity exactly.

## 2. Faithful pending panel projection

- [x] 2.1 Admit `modificar_producto` to the existing closed active-intent
  projection and derive only the stage-relevant candidate count.
- [x] 2.2 Preserve no-PII behavior, other intent projections and no-session-
  mutation behavior.

## 3. Focused proof

- [x] 3.1 Cover `chica`, case/article variants, zero/multiple/multi-token
  fallback, source/quantity preservation, candidate bounds and no recognizer
  call on deterministic success.
- [x] 3.2 Add the smallest pending destination-selection execution proof for
  an exact two-unit modification and cleared context.
- [x] 3.3 Cover panel active intent, stage-relevant count, consistency,
  no-PII and unchanged invalid-state behavior.
- [x] 3.4 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 4. Pilot gate

- [ ] 4.1 After approved deploy, create a modification destination ambiguity
  in the local pilot channel and reply `chica`; verify the exact transfer,
  response, context cleanup and faithful panel state before/after resolution.
- [ ] 4.2 Resume the product-flow TODO and consider archive only after 4.1
  succeeds and explicit user approval is given.
