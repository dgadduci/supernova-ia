# Capability: modificar-producto-real-flow-defects

## Purpose

Codify the diagnostic and real-flow regression contract for the two exact `modificar_producto` phrases that reproduce both real-flow defects even after Subphase 3.32.1 closed the orchestrator-level invariants. The capability requires the system to drive both phrases through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint and through the interactive CLI driver at `backend/scripts/cli_chat_client.py`, to identify which layer is responsible for each defect, to apply the minimum correction at that layer, and to add a regression matrix that crosses the seam between the orchestrator-level pipeline and the real HTTP/CLI entry points so the prior orchestrator-level coverage is no longer sufficient by itself.

## ADDED Requirements

### Requirement: Reproduction of defect 1 through the real pipeline

The system MUST drive the exact phrase `cambia las empanadas de verdura por empanadas carne picante` through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint and through the interactive CLI driver against a Pedido that contains exactly one `PedidoProducto` line for `Empanada de Verdura` with `cantidad == 4`. The reproduction MUST capture the raw HTTP request body, the raw HTTP response body, the CLI stdout, the resulting `PedidoProducto` rows, the `Session.context_type`, and the `ProcessedIntent.status`. The reproduction MUST be re-runnable against `supernova_test` and a temporary seeded commerce.

#### Scenario: HTTP reproduction captures the defect when present

- **WHEN** the real HTTP endpoint receives the exact phrase against the seeded Pedido
- **THEN** the captured per-layer trace records the recognizer `cantidad`, the orchestrator `resolved_data.cantidad`, the handler `cantidad` argument, the service `cantidad` argument, the `ModificationResult.cantidad_modificada`, and the final `CustomerResponse.message`; the trace is sufficient to identify whether the defect is in the recognizer, the orchestrator, the handler, the service, the response builder, or the HTTP endpoint

#### Scenario: CLI reproduction captures the defect when present

- **WHEN** the interactive CLI driver receives the exact phrase against the seeded Pedido
- **THEN** the captured CLI stdout records the printed customer response and the printed order table; the trace is sufficient to identify whether the defect is in the CLI driver or in the orchestrator-level pipeline

### Requirement: Reproduction of defect 2 through the real pipeline

The system MUST drive the exact phrase `cambia las 5 empanadas de jamon y queso por un caramelo` through the real HTTP endpoint and through the interactive CLI driver against a Pedido that contains exactly one `PedidoProducto` line for `Empanada de Jamón y Queso` with `cantidad == 5`, where `caramelo` is not in the comercio catalog. The reproduction MUST capture the same per-layer trace required for defect 1.

#### Scenario: HTTP reproduction of unknown destination captures the defect when present

- **WHEN** the real HTTP endpoint receives the exact phrase against the seeded Pedido and `caramelo` is absent from the catalog
- **THEN** the captured trace records the recognizer `destination_candidate_ids`, the orchestrator `status` and `reason`, the handler invocation, the service invocation, the `ModificationResult.status` and `reason`, and the final `CustomerResponse.message`; the trace is sufficient to identify whether the source mutation happened before destination validation

#### Scenario: CLI reproduction of unknown destination captures the defect when present

- **WHEN** the interactive CLI driver receives the exact phrase against the seeded Pedido and `caramelo` is absent from the catalog
- **THEN** the captured CLI stdout records the printed customer response and the printed order table; the trace is sufficient to identify whether the source line was removed before destination validation

### Requirement: Per-layer blame analysis

After the reproduction step, the system MUST record a per-layer blame analysis that identifies, for each defect, the specific layer (recognizer, initial orchestrator, pending-context resolver, handler, service, response builder, HTTP endpoint, or CLI driver) responsible for the runtime behavior, and the specific code line(s) at fault. The blame analysis MUST be written after the reproduction step, not before, and MUST cite the captured per-layer trace as evidence.

#### Scenario: Blame analysis cites the captured trace

- **WHEN** the blame analysis is finalized
- **THEN** every identified layer references the corresponding per-layer trace entry (recognizer output, orchestrator output, handler call, service call, response, HTTP endpoint, or CLI driver) that proves the layer is at fault

#### Scenario: Blame analysis explains why prior orchestrator-level tests passed

- **WHEN** the blame analysis is finalized
- **THEN** it explicitly explains why the existing 3.32.1 orchestrator-level tests (which patch the classifier and hand-craft `ProcessedIntent` payloads) pass while the real HTTP/CLI pipeline still reproduces the defect; typical reasons include a seam between the orchestrator-level pipeline and the real entry points, a transformation applied by the HTTP endpoint or the CLI driver, or a layer that is exercised by the real pipeline but not by the orchestrator fixtures

### Requirement: Minimum correction at the identified layer

The system MUST apply the smallest correction that fixes the defect at the layer the blame analysis identifies. The correction MUST NOT alter any of the 3.32.1 invariants: one `modificar_producto` operation per replacement command; one `ProcessedIntent`; one `CustomerResponse`; validate source, quantity, and destination before any mutation; one outer transaction owned by `process_incoming_message_transactional`; handler never decomposes into separate `quitar_producto`/`agregar_producto` calls; service never `commit`s, `rollback`s, `flush`es, `refresh`es, `expire`s, or `begin`s; recognizer never substitutes `1` for an omitted quantity; initial orchestrator never substitutes `1`; pending-context resolver never substitutes `1`; handler re-reads source quantity at execution time; service runs validations in strict pre-mutation order; price snapshot preserved for existing destination; current price read before source mutation; consolidation increments in place; equivalent modification rejected; foreign-comercio destination rejected; pending-context lifecycle preserved; deterministic response matrix preserved.

#### Scenario: Correction does not weaken any 3.32.1 invariant

- **WHEN** the correction is applied
- **THEN** every existing 3.32.1 unit and orchestrator-level test continues to pass without modification

#### Scenario: Correction is scoped to the identified layer

- **WHEN** the blame analysis identifies the recognizer as the layer at fault
- **THEN** the correction is applied in `backend/intents/recognizers/modificar_producto_recognizer.py` and no other layer is modified unless the per-layer trace proves that a second layer also contributes

### Requirement: Real-flow HTTP regression

The system MUST add `backend/tests/test_modificar_producto_real_flow_http.py`, which drives the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint with the exact two phrases and asserts: the rendered `CustomerResponse.message`; the `PedidoProducto` rows after the message; the `Session.context_type` after a definitive outcome; the destination `cantidad` equals the re-read source quantity when the quantity is omitted; the source `cantidad` is unchanged when the destination is rejected; the destination `cantidad` is never `1` when the quantity is omitted.

#### Scenario: HTTP regression for defect 1

- **WHEN** the real HTTP endpoint receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the rendered response message is `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.` (or its equivalent product-name substitution for the seeded catalog); the source `PedidoProducto` row is removed; a destination `PedidoProducto` row exists with `cantidad == 4`; `Session.context_type` is `None`

#### Scenario: HTTP regression for defect 2

- **WHEN** the real HTTP endpoint receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the rendered response message is `No encontré el producto de reemplazo. Tu pedido no fue modificado.`; the source `PedidoProducto` row remains with `cantidad == 5`; no destination `PedidoProducto` row exists; `Session.context_type` is `None`

### Requirement: Real-flow CLI regression

The system MUST add `backend/tests/test_modificar_producto_real_flow_cli.py`, which drives `backend/scripts/cli_chat_client.py` with the exact two phrases and asserts: the printed customer response message; the printed order table after each message; the destination row appears with `cantidad == 4` after defect 1; the source row is unchanged after defect 2.

#### Scenario: CLI regression for defect 1

- **WHEN** the interactive CLI driver receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the CLI prints the single modification message (`Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.` or equivalent), the printed order table shows the destination line with `cantidad == 4` and no source line, and the printed order table does not contain `Quité` or `Agregué` substrings

#### Scenario: CLI regression for defect 2

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the CLI prints the unknown-destination message (`No encontré el producto de reemplazo. Tu pedido no fue modificado.`), the printed order table shows the source line unchanged with `cantidad == 5`, and no destination line appears

### Requirement: Existing orchestrator-level tests remain green

Every existing 3.32 and 3.32.1 test file MUST remain green unchanged: the atomicity-focused suite, the end-to-end suite, the handler suite, the initial-orchestrator suite, the recognizer suite, the response suite, the transactional-regression suite, the response-orchestrator suite, the dispatcher-integration suite, the contract suite, the repository suite, the service suite, the CLI client suite, the CLI conversation regression suite, the HTTP endpoint suite, the incoming-message integration suite, the incoming-message orchestrator suite, the incoming-message response orchestrator suite, the transactional-message-processor suite, and the `agregar_producto` and `quitar_producto` regression suites.

#### Scenario: No existing test is weakened or deleted

- **WHEN** the correction is applied
- **THEN** no test file is removed, renamed, or weakened; the existing tests pass as-is

### Requirement: No DB schema change, no Alembic migration

The correction MUST NOT introduce any DB schema change or Alembic migration. The defect is in the seam between the orchestrator-level pipeline and the real HTTP/CLI entry points; it is not a data-model issue.

#### Scenario: No migration is added

- **WHEN** the correction is applied
- **THEN** no new file appears under `backend/alembic/versions/`; the existing Alembic revision is unchanged

### Requirement: No automatic sync, no automatic archive

The `/opsx:apply` command MUST stop after implementation, tests, task updates, and reporting. The command MUST NOT run `openspec sync` automatically. The command MUST NOT run `openspec archive` automatically. Both remain explicit user commands.

#### Scenario: Apply does not sync main specs

- **WHEN** `/opsx:apply` completes
- **THEN** the main `openspec/specs/` directory is unchanged; the delta specs under `openspec/changes/fix-modificar-producto-real-flow-defects-3-32-2/specs/` remain in the change directory

#### Scenario: Apply does not archive the change

- **WHEN** `/opsx:apply` completes
- **THEN** the change directory `openspec/changes/fix-modificar-producto-real-flow-defects-3-32-2/` remains on disk; no archive operation runs
