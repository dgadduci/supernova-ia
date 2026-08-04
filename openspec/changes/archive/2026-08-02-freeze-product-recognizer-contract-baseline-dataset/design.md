## Context

The current fuzzy recognizer is `backend.recognizers.product_recognizer.detectar_productos(texto, productos_presentaciones)`. It is a pure function over a caller-provided catalog. The current production call inventory across `backend/` is:

- `backend/intents/orchestration/agregar_producto_orchestrator.py`: initial `agregar_producto` recognition against the commerce-scoped catalog.
- `backend/intents/context/product_selection_context_resolver.py`, reached through `ProductSelectionContextService` and `pending_context_dispatcher.py`: pending product-selection refinement against the active intent’s restricted candidate catalog.
- `backend/intents/recognizers/quitar_producto_recognizer.py`: order-line recognition against only the active draft pedido’s `PedidoProducto`-derived catalog, followed by `pedido_producto_id` attachment and quantity extraction.
- `backend/intents/recognizers/modificar_producto_recognizer.py`: initial modification source recognition against the draft order-line catalog and destination recognition against the active commerce catalog.
- `backend/intents/context/product_modification_resolver.py`: pending modification source refinement through `recognize_quitar_producto`, and destination refinement against the active candidate-ID catalog.
- `backend/intents/orchestration/pending_context_dispatcher.py`: dispatches pending product selection, order-line selection, and product-modification flows to the resolver paths that consume recognizer results.
- `backend/intents/orchestration/pending_context_execution.py`: executes definitive results, removes the active queued intent, promotes the next queued intent, and returns the promoted pending result; it does not call the recognizer directly but is part of the recognizer-result lifecycle.
- `backend/intents/resolvers/product_intent_resolver.py`: consumes the recognizer’s four collections to derive selected IDs, candidate IDs, quantities, unavailable items, and unknown fragments.
- `backend/intents/orchestration/incoming_message_orchestrator.py` and the initial/pending dispatchers: route messages into the recognition and refinement paths and therefore remain integration boundaries even without a direct fuzzy import.

`backend/old_project/logica_fuzzy_pedido_productos.py` contains the legacy JSON-string recognizer and is not the current implementation targeted by this change. `backend/tests/`, including `api_smoke.py` and the manual CLI, contains verification or tooling call sites rather than production call sites; both categories will be explicitly classified during inventory so they are not mistaken for runtime consumers.

Before defining the protocol, the observable current contract is frozen as follows:

- Input is `texto: str` plus `productos_presentaciones: list[dict]`. Each catalog entry must provide `producto_presentacion_id: int` and `producto_nombre: str`; the recognized catalog projection provides `producto_id: int`, `presentacion_id: int`, `categoria_id: int`, `categoria_nombre: str`, `presentacion_codigo: str`, `presentacion_descripcion: str`, `activo: bool`, and `disponible: bool`. Additional catalog fields supplied by callers are accepted by the runtime function and preserved in matched output entries.
- The return value is a plain Python `dict`, not a JSON string, with exactly these top-level keys in this insertion order: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, and `no_encontrados`.
- `encontrados` is a `list[dict]`. Each entry copies every field from its source catalog entry and adds `cantidad: int` and `texto_origen: str`. `cantidad` is always positive and defaults to `1` when no explicit number or quantity word is present.
- `encontrados_posibles` is a `list[dict]` of groups shaped exactly as `{"texto_origen": str, "productos": list[dict]}`. Each nested product has the same copied catalog fields plus `cantidad` and `texto_origen`.
- `encontrados_no_disponibles` is a `list[dict]` of matched product entries with the same copied-field and added-field shape. The current implementation places entries with `disponible` false here; entries filtered by any false product, presentation, or product-presentation active flag are omitted from all output collections. Missing activity and availability flags default to active/available according to the current implementation.
- `no_encontrados` is a `list[dict]` of `{"texto_origen": str}` unmatched segments in segmentation order.
- Empty values are lists, never `None`. An empty catalog yields empty `encontrados`, `encontrados_posibles`, and `encontrados_no_disponibles`, with unmatched input segments in `no_encontrados`. Empty text follows the current segmentation fallback and yields `no_encontrados == [{"texto_origen": ""}]`.
- Recognition processes message segments in segmentation order. Within found and unavailable collections, entries are ordered by descending confidence, with stable ordering for ties. Possible groups are emitted in the first-seen order of their source segments, and products inside each group retain the confidence ordering. Unknown fragments retain segment order. Duplicate product-presentation IDs are collapsed to the strongest match.

Subphase 4.1 establishes these facts as compatibility tests before semantic or vector recognition is added. The fuzzy algorithm, aliases, normalization, thresholds, ranking, output ordering, resolver behavior, pending-context behavior, customer responses, and HTTP contracts are fixed constraints.

## Goals / Non-Goals

**Goals:**

- Produce a complete `backend/` call-site and result-lifecycle inventory.
- Define exact static types for the current catalog projection and nested result dictionaries without converting runtime results to models.
- Keep the protocol separate from the fuzzy implementation where practical.
- Provide a fuzzy implementation that satisfies the protocol while preserving `detectar_productos` compatibility.
- Create reusable contract tests for current observable behavior.
- Add a baseline dataset covering unique, ambiguous, restricted-catalog refinement, unknown, quantity, presentation, alias, misspelling, and multi-word cases.
- Mark accepted fuzzy limitations explicitly and validate every case against the real fuzzy implementation.

**Non-Goals:**

- Rewriting or tuning the fuzzy algorithm.
- Adding pgvector, vector tables, embeddings, Ollama calls, semantic scoring, or `HybridProductRecognizer`.
- Moving aliases or catalog data into PostgreSQL.
- Redesigning resolvers, pending-intent queues, customer responses, or HTTP APIs.
- Changing database models, repositories, production catalog data, or observable recognition behavior.
- Implementing Subphase 4.2.

## Decisions

1. **Freeze the dictionary contract before introducing the protocol.** Define `TypedDict` or explicit aliases for the required catalog entry, recognized product entry, possible-match group, unmatched fragment, and four-key result. The aliases describe the existing dictionaries only; the runtime function continues returning ordinary dictionaries. A new Pydantic result model was rejected because it would change runtime behavior and downstream assumptions.

2. **Keep protocol and fuzzy implementation separate.** Put `ProductRecognizerProtocol` and the static contract types in `backend/recognizers/product_recognizer_contract.py`. Put `FuzzyProductRecognizer` in `backend/recognizers/fuzzy_product_recognizer.py` as a thin delegate to the existing `backend.recognizers.product_recognizer.detectar_productos`. Leave the existing fuzzy algorithm and legacy function in place. Keeping the wrapper in the existing module remains an acceptable fallback only if import-cycle or public-surface constraints make the separate module impractical.

3. **Preserve the legacy function as the compatibility seam.** Existing direct imports remain valid while practical composition boundaries can receive the protocol-compatible implementation. No resolver or pending queue is rewritten solely to eliminate a direct function import; all such paths are covered by contract and integration tests.

4. **Inventory lifecycle consumers, not only direct imports.** The inventory records the catalog and result transformation at each direct call, then follows the result through `product_intent_resolver`, pending-context services and dispatch, handlers, execution, and FIFO promotion. This prevents queue behavior from being treated as a recognizer concern while still proving that the frozen result shape survives every handoff.

5. **Use restricted pending-flow catalogs for refinement cases.** Dataset entries for `picante`, `grande`, and equivalent refinements must use the exact candidate catalogs and candidate IDs used by the real pending product-selection or modification flow. They must not use the full commerce catalog or a newly invented synthetic candidate set.

6. **Store the baseline as a version-controlled fixture.** Use `backend/tests/fixtures/product_recognizer_baseline.json` unless an existing test-data convention is found. Each case contains case metadata, a real fixture/catalog reference or exact catalog context, expected current result, and optional `known_fuzzy_limitation: true` with a `limitation_note`. A limitation annotation describes accepted current fuzzy behavior; it is not a desired semantic outcome and must not be interpreted as a future-quality target.

7. **Run every baseline case through real fuzzy recognition.** Dataset validation loads the actual catalog context and calls `FuzzyProductRecognizer` without mocking recognition. It validates current result type, IDs, quantities, and restricted-catalog behavior. Future semantic implementations may use the same cases, but limitation annotations distinguish compatibility baselines from desired future improvements.

8. **Keep diagnostics observational.** Update the existing diagnostic payload only if needed to identify the concrete implementation name. No semantic/vector/Ollama diagnostic fields or new logging paths are introduced.

## Risks / Trade-offs

- **[Risk] Existing direct imports and helper imports make a complete protocol migration invasive.** → Keep the legacy function, separate only the protocol and thin adapter, migrate practical composition seams, and cover every remaining direct path in the inventory.
- **[Risk] The current dictionary contract is broader than the required catalog projection.** → Type the required projection explicitly, allow additional preserved fields in the runtime-facing alias, and assert preservation rather than stripping unknown fields.
- **[Risk] Baseline IDs may drift when test fixtures change.** → Validate every expected ID against its resolved fixture and fail with the case ID and missing reference.
- **[Risk] Refinement cases could accidentally test an unrestricted catalog.** → Store and validate the exact restricted candidate IDs/catalogs used by pending-context tests.
- **[Risk] Known fuzzy limitations could be mistaken for semantic requirements.** → Require explicit limitation metadata and assert only the current fuzzy expectation; do not include a desired future result field in the compatibility dataset.
- **[Risk] A wrapper could alter ordering or mutable output behavior.** → Delegate directly, compare legacy and protocol results, and avoid copying or normalizing the returned dictionary.

## Migration Plan

1. Record the complete call-site and output-contract inventory.
2. Add static aliases and the protocol module, then add the thin fuzzy adapter while retaining the existing function.
3. Migrate only practical composition seams and run contract tests.
4. Create the baseline fixture from existing test catalogs, including restricted pending-flow catalogs and limitation annotations.
5. Run dataset validation and focused integration regressions for initial recognition, pending refinement, removal, modification, execution, and queue promotion.
6. If compatibility fails, roll back the composition-boundary changes and adapter while leaving the existing fuzzy module and behavior unchanged. Do not sync or archive automatically.

## Open Questions

- Which existing test catalog helper should be the canonical fixture source for each baseline case when multiple tests contain equivalent real IDs?
- Does the existing diagnostic sink already expose an implementation-name field, or is a minimal additive field required?
