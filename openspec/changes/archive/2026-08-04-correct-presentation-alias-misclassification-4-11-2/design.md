## Context

`detectar_productos` first builds fuzzy product candidates, then `_extraer_presentacion` scans every normalized input token through the hardcoded `PRESENTACION_ALIASES` map. If any mapped token is found, the recognizer discards every candidate whose `presentacion_codigo` does not match that mapped value. Because `picante` is a product flavor/variant in the current catalog rather than a structured presentation, `empanadas carne picante` finds the destination by name and then incorrectly removes it during presentation filtering. The resulting unknown destination prevents the real modificar-producto flow from completing.

The fix must preserve the recognizer's pure dictionary contract, existing legitimate presentation handling, omitted-quantity semantics in the modificar-producto pipeline, and the fuzzy recognizer's runtime authority. It must not touch embeddings, Ollama, vector data, calibration, HTTP contracts, or transaction behavior.

## Goals / Non-Goals

**Goals:**

- Stop `picante` from activating structured presentation filtering when it is part of product identity.
- Keep legitimate presentation aliases and their current candidate-filtering behavior intact.
- Prove the correction at both the pure recognizer boundary and the real modificar-producto HTTP flow.
- Preserve the unknown-destination safety path and restore the synthetic LLM settings override fixture.

**Non-Goals:**

- Redesigning candidate scoring, token extraction, alias persistence, or presentation modeling.
- Building a generalized ontology for flavors, ingredients, varieties, descriptors, and presentations.
- Changing embeddings, Ollama settings, vector search, calibration data, hybrid/fuzzy selection, handlers, HTTP payloads, or order transaction semantics.
- Synchronizing or archiving the change during implementation.

## Decisions

1. **Correct the classification at the static presentation-alias source.** Remove `picante` from `PRESENTACION_ALIASES` because the current catalog models it in product identity, not `presentacion_codigo`. This is preferred over special-casing `_extraer_presentacion` or bypassing filtering later because the defect is incorrect source data, and correcting that data preserves the established pipeline.

2. **Review adjacent aliases conservatively.** Inspect nearby aliases such as `tradicional` against current catalog presentation values, but change them only when the same product-descriptor misclassification is clearly demonstrated. This avoids broad semantic changes and keeps the patch minimal.

3. **Preserve legitimate presentation behavior rather than refactor it.** Existing aliases and size/unit handling for `chica`, `mediana`, `grande`, `unidad`, `porción`, `docena`, `media docena`, `litro`, and `medio litro` remain intact. Focused tests will ensure genuine presentation text continues to narrow candidates and unknown text does not create a match.

4. **Test both the causal boundary and the reported failure.** Add pure recognizer regressions for descriptor identity, valid presentation filtering, and unknown input, then retain or strengthen the real HTTP regressions for omitted-quantity transfer and unknown-destination source preservation. This distinguishes the root cause from downstream transaction guarantees.

5. **Keep the settings test semantically meaningful.** Replace the override fixture value with `test-embedding-model`, distinct from the production default, so the test continues proving environment override plumbing without implying an embedding-model change.

## Risks / Trade-offs

- [A removed alias was used as a presentation in stale data] → Verify current catalog presentation codes/descriptions and focused recognition fixtures before changing any alias beyond `picante`.
- [Legitimate presentation filtering regresses] → Add explicit regression coverage for real presentation terms and run the focused recognizer suite.
- [The HTTP defect has another contributing layer] → Run the two exact real-flow tests; modify downstream code only if the trace proves a separate blocking defect.
- [Broad test churn obscures the small fix] → Keep production changes confined to the alias classification unless evidence requires otherwise, and do not weaken existing tests.
