## Objective

Make the already calibrated hybrid recognizer an opt-in authoritative strategy
behind the existing product-recognition factory, while keeping fuzzy the safe
default and without activating `hybrid` in production in this phase.

## Current execution path (verified)

`dispatch_initial_message` routes `agregar_producto` to
`process_initial_agregar_producto`, which loads the commerce catalog and uses
the factory-bound recognizer. It routes `quitar_producto` to
`process_initial_quitar_producto` -> `recognize_quitar_producto`, which builds
an order-line catalog; and `modificar_producto` to
`process_initial_modificar_producto` -> `recognize_modificar_producto`, which
recognizes the source against order lines and the destination against the
commerce catalog. Pending product selection and pending modification destination
selection repeat recognition against restricted catalogs.

The factory already selects `fuzzy`, `shadow`, or `hybrid_authoritative` from
`PRODUCT_RECOGNIZER_MODE`; invalid values safely resolve to fuzzy. However,
the quitar/modificar recognizers and both context resolvers currently construct
`FuzzyProductRecognizer` locally. Consequently, only agregar currently reaches
the configurable boundary. This change closes that routing gap; it does not
create another recognition pipeline.

## Scope

- Use the existing `get_product_recognizer(load_settings())` factory as the one
  shared strategy-selection boundary for all production recognition calls.
- Preserve `fuzzy` as authoritative in `fuzzy`; preserve fuzzy as authoritative
  and hybrid as best-effort observation in `shadow`.
- Treat existing `hybrid_authoritative` as the `hybrid` authoritative mode for
  this codebase; do not add a second mode literal or alter calibrated policy.
- In hybrid, translate `unique` to the chosen `producto_presentacion_id`,
  `ambiguous` to the existing pending candidate flow, and `unknown` to the
  existing unknown/rejected behavior for each caller.
- Preserve catalog scope, commerce isolation, `ProcessedIntent` contracts,
  candidate ordering, and 4.12A narrowing.

## Non-goals

No production activation, rollout table, per-commerce switch, calibration or
policy change, dataset/threshold/weight change, embedding/index/model change,
fuzzy redesign, 4.12A change, migration, catalog endpoint, LangGraph, or
`api_smoke.py` repair.

## Authoritative outcomes and fallback

Only a hybrid infrastructure failure may return the byte-for-byte fuzzy result:
embedding unavailable/failure, vector unavailable/query/repository failure,
malformed hybrid dependency response, or an unexpected technical exception.
`unknown`, `ambiguous`, low confidence, an empty/weak vector side, and absence
of a strong candidate are valid hybrid decisions and MUST NOT fall back.
An invalid mode resolves to fuzzy with a sanitized observation.

## Shared boundary and transactions

The factory is the sole shared boundary; callers pass their already scoped
catalog and optional `RecognizeContext`. No recognizer may reload or widen a
catalog. Recognizers, the factory, observations, and vector collaborators do
not commit, rollback, flush, or own caller transactions.

## Observability

Reuse `ShadowMetricsRecorder` and its existing comparison/observation payloads
to record configured mode, effective mode, authoritative strategy, fuzzy
decision, hybrid decision when evaluated, fallback boolean, and a sanitized
fallback category. Do not introduce an observability platform.

## Expected files

- `backend/intents/recognizers/quitar_producto_recognizer.py`
- `backend/intents/recognizers/modificar_producto_recognizer.py`
- `backend/intents/context/product_selection_context_resolver.py`
- `backend/intents/context/product_modification_resolver.py`
- `backend/services/product_recognition_factory.py` and existing hybrid/shadow
  observation collaborators only if required to complete the stated fields
- focused recognition, flow, factory, and observation tests

## Focused validation and reversibility

Run focused pytest for factory/controlled hybrid/shadow observations, agregar,
quitar, modificar, pending product selection, and pending modification; run
Ruff and `compileall` on touched Python files; then strict OpenSpec validation.
Per repository policy, the user must run the exact commands in the local
terminal and provide complete output. Reversibility is configuration-only:
leave production in `shadow`/`fuzzy`, or set `PRODUCT_RECOGNIZER_MODE=fuzzy`.
