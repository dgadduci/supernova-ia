## ADDED Requirements

### Requirement: Resolver narrows candidate_ids on partial recognition

When `detectar_productos` returns zero items in `encontrados` AND at least one group in `encontrados_posibles` AND every `producto_presentacion_id` referenced by those groups is already in `active_intent.candidate_ids`, the function SHALL return a new `ProcessedIntent` whose `candidate_ids` is the intersection of the original `candidate_ids` and the set of `producto_presentacion_id`s from the recognizer output, preserving the original order. The narrowed intent SHALL keep `status == "pending_resolution"` when the intersection has more than one element. The narrowed intent SHALL preserve `resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, and `handler` verbatim from the input.

#### Scenario: Partial narrowing leaves multiple candidates

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaChica, PizzaMuzzarellaGrande, PizzaNapolitanaChica, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `la grande` and the recognizer returns three `producto_presentacion_id`s in `encontrados_posibles` (`PizzaMuzzarellaGrande`, `PizzaNapolitanaGrande`, `PizzaMargheritaGrande`)
- **THEN** the returned intent has `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` (in that order), `status == "pending_resolution"`, and the original `resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, and `handler` preserved

#### Scenario: Partial narrowing leaves one candidate and resolves to ready

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns exactly one `producto_presentacion_id` (`PizzaMuzzarellaGrande`) in `encontrados`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved in `resolved_data`

#### Scenario: Empty intersection returns the input unchanged

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaChica, PizzaNapolitanaChica]` and the message is `la grande` and the recognizer returns three `producto_presentacion_id`s in `encontrados_posibles` that are NOT in `active_intent.candidate_ids`
- **THEN** the function returns `active_intent` unchanged (same instance) — the narrowing does not collapse the candidate set to empty

### Requirement: Unique selection is reused when refinement leaves exactly one candidate

When the recognizer returns exactly one item in `encontrados` AND that item's `producto_presentacion_id` is in the original `active_intent.candidate_ids`, the function SHALL follow the existing unique-selection path: build a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the selected id, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: Exact unique match resolves to ready without an extra confirmation

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns exactly one `producto_presentacion_id` in `encontrados`
- **THEN** the returned intent has `status == "ready"`, `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, `candidate_ids == []`, and the original `cantidad` preserved — the dispatcher then routes the intent to `execute_ready_pending_context` in the SAME turn

### Requirement: Confident match takes priority over candidates

When the recognizer returns exactly one item in `encontrados` AND at least one group in `encontrados_posibles`, the function SHALL ignore the candidate groups and apply the unique-selection path against the single `encontrados` item. The candidate-narrowing branch SHALL NOT fire when a confident match is present.

#### Scenario: Confident match wins over candidates

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns one `producto_presentacion_id` in `encontrados` (the muzzarella grande) AND groups in `encontrados_posibles`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, `status == "ready"`, `candidate_ids == []`, and the candidate groups are ignored

### Requirement: No new side effects from the narrowing branch

The narrowing branch SHALL NOT call `commit`, `flush`, `refresh`, `expire`, or `begin` on the database, SHALL NOT modify the `Session` model, SHALL NOT mutate `active_intent` in place, SHALL NOT log anything, and SHALL NOT call handlers. The narrowing branch SHALL only return a new `ProcessedIntent` instance (or the input unchanged when the narrowing is not applicable).

#### Scenario: Narrowing does not commit

- **WHEN** the narrowing branch fires
- **THEN** the `db.commit` is not called (verified by a mock) and the input `active_intent` instance is not mutated (`is` comparison preserved when the function returns the input unchanged)

#### Scenario: Narrowing does not load the catalog

- **WHEN** the function builds the candidate-ids intersection
- **THEN** the function uses the recognizer's `encontrados_posibles` output and `active_intent.candidate_ids` directly — no additional SQLAlchemy query is issued from the resolver
