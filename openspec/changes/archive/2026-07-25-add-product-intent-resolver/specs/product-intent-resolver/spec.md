## ADDED Requirements

### Requirement: ProductIntentResolver function exists
The system SHALL export a single function `resolve_product_intent(raw: dict) -> dict` from `backend.intents.resolvers.product_intent_resolver`. The function SHALL be pure: no I/O, no LLM call, no DB write, no intent contract application, no handler execution, no persistence.

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.intents.resolvers.product_intent_resolver import resolve_product_intent`
- **THEN** the import completes without raising and the binding is a callable

### Requirement: Exact product found
When the recognizer returns a single confident match, the resolver SHALL populate `resolved_data` with `producto_presentacion_id` and `cantidad` from that match, leave `candidate_ids` empty, and leave `unavailable_items` and `not_found_items` empty.

#### Scenario: Single confident match populates resolved_data
- **WHEN** the test calls `resolve_product_intent({"encontrados": [{"id": 42, "cantidad": 2}]})`
- **THEN** the result is `{"resolved_data": {"producto_presentacion_id": 42, "cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []}`

### Requirement: Multiple possible candidates
When the recognizer returns one or more plausible matches and no confident match, the resolver SHALL collect every plausible match's `id` into `candidate_ids` in order, preserve the detected `cantidad` from the first plausible match into `resolved_data["cantidad"]` when present, and leave `resolved_data["producto_presentacion_id"]` empty (the future handler picks from the candidates).

#### Scenario: Multiple possible candidates populate candidate_ids
- **WHEN** the test calls `resolve_product_intent({"encontrados_posibles": [{"id": 10}, {"id": 11}, {"id": 12}]})`
- **THEN** `candidate_ids == [10, 11, 12]` in that order

#### Scenario: First candidate's cantidad is preserved
- **WHEN** the test calls `resolve_product_intent({"encontrados_posibles": [{"id": 10, "cantidad": 3}, {"id": 11}]})`
- **THEN** `resolved_data == {"cantidad": 3}` and `producto_presentacion_id` is NOT a key of `resolved_data`

#### Scenario: Candidate without cantidad leaves resolved_data empty
- **WHEN** the test calls `resolve_product_intent({"encontrados_posibles": [{"id": 10}]})`
- **THEN** `resolved_data == {}` and `candidate_ids == [10]`

### Requirement: Unavailable products
The resolver SHALL copy every `source_text` from `encontrados_no_disponibles` into `unavailable_items` in order. Other output keys are unchanged.

#### Scenario: Unavailable items are copied
- **WHEN** the test calls `resolve_product_intent({"encontrados_no_disponibles": [{"source_text": "out of stock item"}]})`
- **THEN** `unavailable_items == ["out of stock item"]`

#### Scenario: Multiple unavailable items preserve order
- **WHEN** the test calls `resolve_product_intent({"encontrados_no_disponibles": [{"source_text": "a"}, {"source_text": "b"}]})`
- **THEN** `unavailable_items == ["a", "b"]` in that order

### Requirement: Not-found products
The resolver SHALL copy every `source_text` from `no_encontrados` into `not_found_items` in order. Other output keys are unchanged.

#### Scenario: Not-found items are copied
- **WHEN** the test calls `resolve_product_intent({"no_encontrados": [{"source_text": "mystery item"}]})`
- **THEN** `not_found_items == ["mystery item"]`

#### Scenario: Multiple not-found items preserve order
- **WHEN** the test calls `resolve_product_intent({"no_encontrados": [{"source_text": "x"}, {"source_text": "y"}]})`
- **THEN** `not_found_items == ["x", "y"]` in that order

### Requirement: Empty recognizer result
The resolver SHALL return a fully-empty output dict when the input is empty (or has only empty arrays).

#### Scenario: Empty input produces empty output
- **WHEN** the test calls `resolve_product_intent({})`
- **THEN** the result is `{"resolved_data": {}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []}`

#### Scenario: All-empty arrays produce empty output
- **WHEN** the test calls `resolve_product_intent({"encontrados": [], "encontrados_posibles": [], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the result is `{"resolved_data": {}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []}`

#### Scenario: Missing keys default to empty
- **WHEN** the test calls `resolve_product_intent({"encontrados": [{"id": 1, "cantidad": 1}]})` (only one key supplied)
- **THEN** `candidate_ids == []`, `unavailable_items == []`, `not_found_items == []`, and `resolved_data == {"producto_presentacion_id": 1, "cantidad": 1}`

### Requirement: Confident match takes priority over candidates
When the recognizer returns both a confident match and one or more plausible candidates, the resolver SHALL populate `resolved_data` from the confident match and leave `candidate_ids` empty. The candidates are ignored in this case.

#### Scenario: Confident match suppresses candidates
- **WHEN** the test calls `resolve_product_intent({"encontrados": [{"id": 42, "cantidad": 2}], "encontrados_posibles": [{"id": 10}, {"id": 11}]})`
- **THEN** `resolved_data == {"producto_presentacion_id": 42, "cantidad": 2}` and `candidate_ids == []`

### Requirement: All four output keys are always present
The resolver SHALL always return a dict with exactly four keys: `resolved_data`, `candidate_ids`, `unavailable_items`, `not_found_items`. None of the keys are ever omitted, even when the corresponding input key was missing.

#### Scenario: All four keys present on every call
- **WHEN** the test inspects the keys of the result for any input
- **THEN** the key set is exactly `{"resolved_data", "candidate_ids", "unavailable_items", "not_found_items"}`

### Requirement: No additional implementation
The subphase SHALL NOT introduce an LLM call, an HTTP call, a DB write, persistence, an intent contract application, a handler invocation, an `IntentProcessor`, or any other intent resolver. The only new code is the resolver function, the empty `__init__.py`, and the verification test.

#### Scenario: Only the resolver module is added
- **WHEN** the test lists non-`__init__.py` files under `backend/intents/resolvers/`
- **THEN** the file set is exactly `{"product_intent_resolver.py"}`

#### Scenario: Module has no public symbols beyond the function
- **WHEN** the test introspects the module
- **THEN** the only public symbol defined is `resolve_product_intent`