## Why

The fuzzy product recognizer currently classifies `picante` as a presentation alias even when it is part of a product's identity, causing valid candidates such as “Empanada de Carne Picante” to be discarded by presentation filtering. This breaks the real modificar-producto full-transfer flow and must be corrected without changing embeddings, calibration, or runtime mode selection.

## What Changes

- Remove product-descriptor terms that are not real catalog presentations from the recognizer's presentation aliases, beginning with `picante` and reviewing adjacent aliases only for the same clear classification error.
- Preserve recognition and candidate filtering for legitimate presentation terms, including sizes, units, portions, dozens, liters, and half-liters.
- Add focused recognizer and real-flow regressions for descriptor-bearing product identities, legitimate presentation filtering, unknown presentation text, omitted-quantity full transfer, and unknown-destination source preservation.
- Restore the LLM settings override test to use an unmistakably synthetic embedding model value while preserving its environment-override assertion.
- Record Subphase 4.11.2 in the project roadmap without changing embeddings, Ollama configuration, vector data, calibration datasets, recognizer mode selection, HTTP contracts, or order transaction semantics.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `product-recognizer`: Presentation filtering must only activate for legitimate presentation aliases; product descriptors such as `picante` remain available for product-identity matching and cannot discard the valid candidate.

## Impact

- Affects `backend/recognizers/product_recognizer.py`, focused product recognizer tests, `backend/tests/test_modificar_producto_real_flow_http.py`, `backend/tests/test_llm_settings.py`, and the Subphase 4 roadmap entry in `openspec/specs/project.md`.
- No API, persistence, dependency, embedding, Ollama, vector-search, calibration, mode-selection, handler, or transaction-contract changes are intended.
