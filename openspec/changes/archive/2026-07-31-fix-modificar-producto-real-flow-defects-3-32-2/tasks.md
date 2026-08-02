## 1. Setup and baseline

- [x] 1.1 Confirm `supernova_test` is seeded and reachable via `postgresql+psycopg:///supernova_test`; run `PYTHONPATH=. venv/bin/alembic current` to verify the revision matches the latest migration.
- [x] 1.2 Run the existing 3.32.1 orchestrator-level suites to capture the green baseline: `backend/tests/test_modificar_producto_atomicity_focused.py`, `backend/tests/test_modificar_producto_end_to_end.py`, `backend/tests/test_modificar_producto_handler.py`, `backend/tests/test_modificar_producto_initial.py`, `backend/tests/test_modificar_producto_recognizer.py`, `backend/tests/test_modificar_producto_response.py`, `backend/tests/test_modificar_producto_transactional_regression.py`, `backend/tests/test_modificar_producto_response_orchestrator.py`, `backend/tests/test_modificar_producto_dispatcher_integration.py`. All 95 tests pass.
- [x] 1.3 Run the existing `agregar_producto` and `quitar_producto` regressions to capture the wider green baseline: `backend/tests/test_quitar_producto_*`, `backend/tests/test_cli_chat_client.py`, `backend/tests/test_cli_conversation_regression.py`, `backend/tests/test_incoming_messages_endpoint.py`, `backend/tests/test_incoming_message_integration.py`, `backend/tests/test_incoming_message_orchestrator.py`, `backend/tests/test_incoming_message_response_orchestrator.py`, `backend/tests/test_transactional_message_processor.py`. All tests pass except one pre-existing `UniqueViolation` failure in `test_quitar_producto_end_to_end.py::test_initial_pending_context_with_multiple_lines` (test data pollution, unrelated to this change).

## 2. Reproduction through the real HTTP endpoint

- [x] 2.1 Created `backend/tests/test_modificar_producto_real_flow_http.py` (serves as both reproduction and regression test). Seeds a `supernova_test` commerce with `Empanada de Verdura x4` and `Empanada de Jamón y Queso x5` source lines, uses `fastapi.testclient.TestClient(app=app, ...)` with `app.dependency_overrides` against `supernova_test`, posts `cambia las empanadas de verdura por empanadas carne picante` to `POST /comercios/{id}/clientes/{id}/incoming-messages`, captures the raw response, the resulting `PedidoProducto` rows, and the `Session.context_type`.
- [x] 2.2 Same test file covers the second phrase `cambia las 5 empanadas de jamon y queso por un caramelo` with the same per-layer evidence.
- [x] 2.3 Pre-correction per-layer trace recorded in `design.md`'s Diagnosis section.
- [x] 2.4 Both defects reproduced through the HTTP endpoint. Defect 1: two `CustomerResponse` entries (`quitar_producto` executed + `agregar_producto` executed), destination `cantidad == 1`. Defect 2: two `CustomerResponse` entries (`quitar_producto` executed + `agregar_producto` pending_resolution), source removed.

## 3. Reproduction through the real CLI driver

- [x] 3.1 Created `backend/tests/test_modificar_producto_real_flow_cli.py`. Imports `backend.scripts.cli_chat_client`, patches `urllib.request.urlopen` with a real adapter that forwards every HTTP call to the FastAPI `TestClient`, and patches `builtins.input` to feed the reproduction phrases. The initial Pedido lines are set up via `agregar_producto` messages through the CLI itself.
- [x] 3.2 Same test file covers both phrases. Captures the printed customer response, the printed order table, and the resulting `PedidoProducto` rows.
- [x] 3.3 Both defects reproduced through the CLI driver before the correction. Same per-layer trace as the HTTP endpoint (the CLI is a pure HTTP client; the trace is identical).

## 4. Diagnosis and per-layer blame analysis

- [x] 4.1 Appended the `## Diagnosis` section to `design.md` containing the per-layer trace for both phrases, the layer identified at fault (LLM-based intent classifier prompt in `backend/llm/intent_classifier.py`), the specific code lines at fault (`_INTENT_CATALOG` lines 30-32 and the worked example lines 48-70), and the explicit explanation of why the prior 3.32.1 orchestrator-level tests passed while the runtime failed (they patched the classifier with `_ModificarClassifier` and bypassed the LLM-based dispatcher seam).
- [x] 4.2 The diagnosis identifies the seam: the LLM classifier prompt instructed the LLM to decompose substitution requests into `quitar_producto` + `agregar_producto`, triggering a different code path than the hand-crafted `_ModificarClassifier` stubs.
- [x] 4.3 The diagnosis documents the coverage gap: the 3.32.1 orchestrator-level tests do not drive the real HTTP endpoint or the real CLI driver. The new real-flow regression tests (`backend/tests/test_modificar_producto_real_flow_http.py` and `backend/tests/test_modificar_producto_real_flow_cli.py`) close this gap.

## 5. Minimum correction at the identified layer

- [x] 5.1 Applied the smallest change that corrects the defect at the layer the diagnosis identifies (the LLM-based intent classifier prompt). Did not modify layers that were not at fault.
- [x] 5.2 Recognizer was NOT at fault; no changes made.
- [x] 5.3 Initial orchestrator was NOT at fault; no changes made.
- [x] 5.4 Handler was NOT at fault; no changes made.
- [x] 5.5 Service was NOT at fault; no changes made.
- [x] 5.6 Response builder was NOT at fault; no changes made.
- [x] 5.7 HTTP endpoint was NOT at fault; no changes made.
- [x] 5.8 CLI driver had a secondary defect: `ORDER_MUTATING_INTENTS` did not include `modificar_producto`, so the CLI would not print the order table after a successful modification. Added `"modificar_producto"` to the set. Updated the one CLI test (`test_response_modified_order_false_for_unknown_intent`) that asserted `modificar_producto` was not in the set to use a truly non-order-mutating intent (`consultar_producto`).
- [x] 5.9 Re-ran the reproduction tests after the correction. Both reproduction phrases now produce the documented outcomes end-to-end through the real HTTP endpoint and the real CLI driver.

## 6. Real-flow regression matrix

- [x] 6.1 Created `backend/tests/test_modificar_producto_real_flow_http.py`. Uses `fastapi.testclient.TestClient(app=app, ...)` with `app.dependency_overrides` against `supernova_test`. Seeds a fresh commerce with `Empanada de Verdura x4` and `Empanada de Jamón y Queso x5`. For each reproduction phrase, posts to `POST /comercios/{id}/clientes/{id}/incoming-messages` and asserts the rendered `CustomerResponse.message`, the resulting `PedidoProducto` rows, and the `Session.context_type`.
- [x] 6.2 Created `backend/tests/test_modificar_producto_real_flow_cli.py`. Imports the CLI module and drives it through the FastAPI `TestClient`. Captures stdout. Asserts the printed customer response message, the printed order table after each message, and the resulting `PedidoProducto` rows.
- [x] 6.3 HTTP regression test `test_defect_1_full_transfer_on_omitted_quantity` drives the omitted-quantity scenario through the real endpoint and asserts the destination `cantidad == 4`. The test does NOT patch the classifier; it drives the real pipeline end-to-end.
- [x] 6.4 HTTP regression test `test_defect_2_unknown_destination_preserves_source` drives the unknown-destination scenario through the real endpoint and asserts the source remains `cantidad == 5` and no destination row exists. The test does NOT patch the classifier.
- [x] 6.5 CLI regression test `test_defect_1_cli_full_transfer_on_omitted_quantity` drives the omitted-quantity scenario through the real CLI driver and asserts the printed order table shows the destination line with `cantidad == 4` and no source line.
- [x] 6.6 CLI regression test `test_defect_2_cli_unknown_destination_preserves_source` drives the unknown-destination scenario through the real CLI driver and asserts the source line unchanged with `cantidad == 5` and no destination line.
- [x] 6.7 Confirmed the new tests fail before the correction (pre-correction run: Defect 1 produced two responses with `cantidad == 1`; Defect 2 produced two responses with source removed) and pass after the correction. Documented in the diagnosis section.

## 7. Verification

- [x] 7.1 Re-ran the entire `backend/tests/test_modificar_producto_*` suite. All tests pass (atomicity-focused, end-to-end, handler, initial, recognizer, response, transactional-regression, response-orchestrator, dispatcher-integration, contract, repository, service, real-flow-http, real-flow-cli).
- [x] 7.2 Re-ran the `quitar_producto` and CLI conversation regression suites. All tests pass except one pre-existing `UniqueViolation` failure in `test_quitar_producto_end_to_end.py::test_initial_pending_context_with_multiple_lines` (test data pollution, unrelated to this change). The CLI chat client suite passes after the one test update in 5.8.
- [x] 7.3 Re-ran the `incoming_messages_endpoint`, `incoming_message_integration`, `incoming_message_orchestrator`, `incoming_message_response_orchestrator`, and `transactional_message_processor` suites. All tests pass.
- [x] 7.4 Ran the API smoke suite `backend/tests/api_smoke.py`. 106 tests pass; 1 pre-existing LLM endpoint failure (`test_llm_settings_and_query_llm`) unrelated to this change (LLM response JSON parsing error from the remote endpoint).

## 8. Reporting

- [x] 8.1 Appended the per-layer blame analysis and the before/after reproduction evidence to `design.md`'s diagnosis section. Cited the specific code lines at fault (`backend/llm/intent_classifier.py` `_INTENT_CATALOG` lines 30-32 and the worked example lines 48-70) and the specific tests that prove the correction holds (`backend/tests/test_modificar_producto_real_flow_http.py` and `backend/tests/test_modificar_producto_real_flow_cli.py`).
- [x] 8.2 Updated `tasks.md` to mark every task complete.
- [x] 8.3 Report to the user: which layer was at fault for each defect, why the prior orchestrator-level tests passed while runtime failed, the minimum correction applied, the new regression tests, and the green baseline re-run. Do NOT run `openspec sync` and do NOT run `openspec archive`. Both remain explicit user commands.
