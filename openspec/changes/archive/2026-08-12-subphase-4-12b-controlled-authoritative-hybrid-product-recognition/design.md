## Design

### Single recognition boundary

`backend.services.product_recognition_factory.get_product_recognizer` remains
the only selector. Every real production wrapper (`agregar`, `quitar`,
`modificar`, pending product selection, and pending modification destination)
binds its recognizer through that factory rather than constructing
`FuzzyProductRecognizer` itself. The wrapper continues to supply the catalog
it already owns; there is no central catalog query and no second pipeline.

The factory uses the environment-level setting already present. It therefore
already supports rollout by environment. No natural per-commerce configuration
exists in this path, so this phase MUST NOT introduce one.

### Call flows

| Flow | Existing scoped catalog | Hybrid result handling |
| --- | --- | --- |
| agregar initial | `ProductoQueryService.list_recognizer_catalog(session.id_comercio)` | `unique` reaches current ready handler; `ambiguous` produces current pending product selection; `unknown` retains current unknown path. |
| quitar initial/refinement | active `PedidoProducto` rows only | Existing order-line candidate conversion decides ready/pending/rejected; hybrid never queries the commerce catalog. |
| modificar source | active `PedidoProducto` rows only | Existing source candidate and pending behavior is preserved. |
| modificar destination/refinement | commerce catalog or persisted destination IDs only | Existing destination ready/pending/rejected behavior is preserved; restricted destination candidates cannot be widened. |
| pending product selection | persisted active candidate catalog | Pass `catalog_scope=pending_product_selection_restricted`; preserve the 4.12A candidate order and in-memory narrowing. |

### Mode contract

- `fuzzy`: fuzzy result is authoritative; no hybrid work.
- `shadow`: fuzzy result is authoritative. Hybrid observation is best effort and
  all technical failures are swallowed after recording safely.
- `hybrid_authoritative`: hybrid decision is authoritative. `unique` is
  translated using only the passed catalog; `ambiguous` is represented in the
  existing possible-candidate shape so current pending-context logic owns it;
  `unknown` uses the existing `no_encontrados`/caller rejection behavior.
- An unknown mode is effective `fuzzy`; structured observation records the
  configured and effective modes with `invalid_mode`.

### Fallback semantics

Hybrid returns fuzzy unchanged only for: embedding failure/unavailable,
vector search or repository/query failure/unavailable, malformed dependency
output, or unexpected technical exception. These map to safe, non-sensitive
categories (for example `embedding_failure`, `vector_failure`,
`malformed_response`, `unexpected_technical_failure`).

Hybrid decisions of unknown or ambiguous, low confidence, a low score gap, no
candidate above threshold, or a valid empty filtered vector result are semantic
outcomes: translate and return them, never fallback.

### Scope, ordering, and ownership

The passed catalog is authoritative. The hybrid recognizer filters vector
matches to its `producto_presentacion_id`s before guards, scoring, ranking, or
translation; it cannot reload a full catalog or introduce another commerce's
candidate. Existing candidate ordering remains intact when generating possible
groups and 4.12A remains the authority for pending candidate narrowing.

The factory, recognizers, shadow service, observation recorder, and vector
lookup neither commit, rollback, flush, begin, nor close caller-owned
transactions. Handlers remain the execution/mutation boundary.

### Observability

Reuse `ProductRecognitionShadowComparison`,
`ProductRecognitionHybridObservation`, and `ShadowMetricsRecorder`. Each
evaluation records configured/effective mode, authoritative strategy, fuzzy
decision, hybrid decision when evaluated, fallback flag, and safe fallback
category. In fuzzy mode hybrid fields may be absent; in shadow failures cannot
affect returned fuzzy output.
