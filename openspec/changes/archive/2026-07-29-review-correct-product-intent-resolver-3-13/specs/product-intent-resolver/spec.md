## MODIFIED Requirements

### Requirement: Exact product found
When the recognizer returns a single confident match, the resolver SHALL populate `resolved_data` with `producto_presentacion_id` and `cantidad` from that match, leave `candidate_ids` empty, and leave `unavailable_items` and `not_found_items` empty.

#### Scenario: Single confident match populates resolved_data
- **WHEN** the test calls `resolve_product_intent({"encontrados": [{"producto_presentacion_id": 42, "cantidad": 2}]})`
- **THEN** the result is `{"resolved_data": {"producto_presentacion_id": 42, "cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []}`
- **AND** the input does not need a legacy `id` field

### Requirement: Multiple possible candidates
When the recognizer returns one or more plausible matches and no confident match, the resolver SHALL collect every plausible match's `producto_presentacion_id` into `candidate_ids` in order, preserve the detected `cantidad` from the first plausible match into `resolved_data["cantidad"]` when present, and leave `resolved_data["producto_presentacion_id"]` empty.

#### Scenario: Multiple possible candidates populate candidate_ids
- **WHEN** the test calls `resolve_product_intent({"encontrados_posibles": [{"producto_presentacion_id": 10}, {"producto_presentacion_id": 11}, {"producto_presentacion_id": 12}]})`
- **THEN** `candidate_ids == [10, 11, 12]` in that order

#### Scenario: First candidate's cantidad is preserved
- **WHEN** the test calls `resolve_product_intent({"encontrados_posibles": [{"producto_presentacion_id": 10, "cantidad": 3}, {"producto_presentacion_id": 11}]})`
- **THEN** `resolved_data == {"cantidad": 3}` and `producto_presentacion_id` is NOT a key of `resolved_data`

### Requirement: Unavailable products
The resolver SHALL copy every `texto_origen` from `encontrados_no_disponibles` into `unavailable_items` in order. Other output keys are unchanged.

#### Scenario: Unavailable items are copied
- **WHEN** the test calls `resolve_product_intent({"encontrados_no_disponibles": [{"texto_origen": "out of stock item"}]})`
- **THEN** `unavailable_items == ["out of stock item"]`

#### Scenario: Multiple unavailable items preserve order
- **WHEN** the test calls `resolve_product_intent({"encontrados_no_disponibles": [{"texto_origen": "a"}, {"texto_origen": "b"}]})`
- **THEN** `unavailable_items == ["a", "b"]` in that order

### Requirement: Not-found products
The resolver SHALL copy every `texto_origen` from `no_encontrados` into `not_found_items` in order. Other output keys are unchanged.

#### Scenario: Not-found items are copied
- **WHEN** the test calls `resolve_product_intent({"no_encontrados": [{"texto_origen": "mystery item"}]})`
- **THEN** `not_found_items == ["mystery item"]`

#### Scenario: Multiple not-found items preserve order
- **WHEN** the test calls `resolve_product_intent({"no_encontrados": [{"texto_origen": "x"}, {"texto_origen": "y"}]})`
- **THEN** `not_found_items == ["x", "y"]` in that order

### Requirement: Confident match takes priority over candidates
When the recognizer returns both a confident match and one or more plausible candidates, the resolver SHALL populate `resolved_data` from the confident match using `producto_presentacion_id` and leave `candidate_ids` empty. The candidates are ignored in this case.

#### Scenario: Confident match suppresses candidates
- **WHEN** the test calls `resolve_product_intent({"encontrados": [{"producto_presentacion_id": 42, "cantidad": 2}], "encontrados_posibles": [{"producto_presentacion_id": 10}, {"producto_presentacion_id": 11}]})`
- **THEN** `resolved_data == {"producto_presentacion_id": 42, "cantidad": 2}` and `candidate_ids == []`

### Requirement: No additional implementation
The subphase SHALL NOT introduce an LLM call, an HTTP call, a DB write, persistence, an intent contract application, a handler invocation, an `IntentProcessor`, or any other intent resolver. The only changed runtime code is the existing resolver function; verification tests may be updated.

#### Scenario: Resolver scope remains limited
- **WHEN** the implementation is inspected
- **THEN** no recognizer fuzzy logic, persistence, handler, API, or dependency changes are introduced
