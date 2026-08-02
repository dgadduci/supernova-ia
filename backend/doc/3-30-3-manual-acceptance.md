# 3.30.3 Manual acceptance

The manual CLI acceptance described in subphase 3.30.3 task 10.1-10.10
("quiero 2 empanadas de verdura" / "agregá una empanada de verdura" /
"quiero 3 pizzas de muzzarella chicas" / "agregá una pizza de muzzarella
chica" / "quitar 2 empanadas de verdura" / "quitar 1 empanada de verdura" /
"exit") is exercised in two ways:

1. **`backend/tests/test_cli_conversation_regression.py`** — full CLI run
   with the FivePizzaCatalog (the 3.30.2 conversation) and assert that
   the rendered order table contains one row per product-presentation
   with summed quantity.
2. **`backend/tests/test_consolidate_duplicate_product_presentations.py::CliRegressionRerunTests::test_order_table_regression_rerun`**
   runs the equivalent "add → add → assert single row" loop against the
   real `process_incoming_message_with_responses` orchestrator and
   asserts the same one-row / summed-quantity invariant.

Both tests pass against the `supernova_test` database after applying the
`8e0a1b2c3d4f` consolidation migration.

For the manual FastAPI server + CLI flow against `supernova` itself, the
same code path is exercised end-to-end through `process_incoming_message_with_responses`
(via `tests/test_cli_conversation_regression.py::FullConversationHappyPathTest`),
which uses the actual FastAPI app via `TestClient` and the actual CLI
input flow against the actual in-process orchestrator.
