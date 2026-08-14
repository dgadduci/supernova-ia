# Proposal: fix plural presentation product recognition

## Why

In the deployed local pilot, `quiero una napolitana grande` creates one line,
but `quiero dos napolitanas grandes` returns the generic add-product
rejection and leaves the line unchanged. The order remains a valid active
draft and its pending state is empty, so this is not a session, price,
transaction, or pending-context failure.

The product normalizer singularizes generic words before product-token
filtering. `napolitanas` becomes `napolitana`, but `grandes` becomes `grand`.
`grand` is neither a recognized presentation size nor a product token, so it
is treated as a required unmatched token and discards the correct Napolitana
candidate. The quantity `dos` is already normalized to `2`; the missing
presentation plural normalization is the narrow defect.

## What Changes

- Normalize only the observed Spanish plural presentation forms `grandes` to
  `grande` and `chicas` to `chica`, before generic singularization in the
  existing product-text normalization path.
- Prove `quiero dos napolitanas grandes` reaches the existing exact
  Napolitana Grande add path with quantity `2`, and an equivalent `chicas`
  case selects only its exact presentation when available.
- Preserve existing product segmentation, quantity parsing, catalog bounds,
  fuzzy/hybrid authority, handler, caller-owned transaction, response and
  pending behavior.

## Current execution path

```text
incoming add message
  -> initial classifier: agregar_producto
  -> shared product recognizer normalization
  -> grandes becomes grand through generic -es stripping
  -> key-token filter requires grand in product name
  -> no candidate -> rejected agregar_producto response
```

## Scope and non-goals

Scope is limited to the shared product normalizer and its focused product/add
tests. This is not a general Spanish morphology feature.

Non-goals: no new aliases, catalog data, prompt, classifier, LLM/hybrid
policy, fuzzy threshold, embedding, candidate fallback, handler, service,
transaction, response text, pending resolver, panel, provider, Twilio,
observability, schema or migration change. Do not normalize other plural words
speculatively; `grandes` and `chicas` are the only approved forms.

## Authoritative outcomes and fallback

| Condition | Outcome |
| --- | --- |
| Exact product plus `grandes`/`chicas` matches one presentation | Existing recognition returns only that presentation and preserves parsed quantity. |
| Product remains ambiguous after normalized presentation | Existing pending-resolution behavior and restricted candidates remain. |
| Product is absent, unavailable, or another token remains unmatched | Existing rejected/unavailable behavior remains. |
| Hybrid authoritative decision is `unknown`, `ambiguous`, or `unique` | Existing configured hybrid policy remains authoritative; no fuzzy fallback is introduced. |
| Technical failure | Existing failure propagation and caller transaction semantics remain. |

## Transaction ownership, privacy and observability

Normalization is pure and performs no I/O. No recognizer, orchestrator,
handler or service receives transaction-control authority. No new trace or
data field is emitted; existing privacy boundaries remain unchanged.

## Expected files

- `backend/recognizers/product_recognizer.py`
- `backend/tests/test_product_recognizer.py`
- the smallest existing focused add-product integration test needed to prove
  quantity `2` reaches the normal execution seam
- `openspec/changes/fix-plural-presentation-product-recognition/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_recognizer.py backend/tests/test_agregar_producto_processor.py backend/tests/test_agregar_producto_handler.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/tests/test_product_recognizer.py backend/tests/test_agregar_producto_processor.py backend/tests/test_agregar_producto_handler.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/recognizers/product_recognizer.py
openspec validate fix-plural-presentation-product-recognition --strict
git diff --check
```

## Rollback and production gate

This source-only normalization is reversible by removing the two explicit
mappings. After approval, implementation, review and deploy, repeat the exact
message `quiero dos napolitanas grandes` in the active pilot draft and verify
the existing Napolitana Grande line increments from 1 to 3 with a success
response and empty pending/context. Resume the product-flow TODO only after
that check. Do not archive any active change without explicit approval.
