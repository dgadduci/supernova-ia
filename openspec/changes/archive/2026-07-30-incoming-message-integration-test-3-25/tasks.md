## 1. Test Module Scaffold

- [x] 1.1 Create `backend/tests/test_incoming_message_integration.py` with module-level constants: `TEST_URL = "postgresql+psycopg:///supernova_test"`, `engine = create_engine(TEST_URL)`, and `TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)`.
- [x] 1.2 Add the documented imports: `unittest`, `unittest.mock.patch` and `MagicMock` from `unittest.mock`, `Decimal` from `decimal`, `uuid` (for unique suffixes), `select` / `delete` from `sqlalchemy`, `IntentClassificationResult` and `ClassifiedIntent` from `backend.intents.schemas.intent_classification`, `IntentName` from the same module, and `process_incoming_message` from `backend.intents.orchestration.incoming_message_orchestrator`.

## 2. Shared Fixtures and Helpers

- [x] 2.1 Implement a `_suffix()` helper that returns a fresh 10-character hex string per call (mirrors `api_smoke.py`).
- [x] 2.2 Implement a `_estado_id_activo()` helper that reads `EstadoComercio` where `estado == "ACTIVO"` and returns its id; raise `RuntimeError` if not seeded (mirrors `api_smoke.py`).
- [x] 2.3 Implement a `_seed(...)` helper that, inside `with TestingSessionLocal() as db, db.begin():`, inserts a `Comercio`, a `Cliente`, an active `Session` row (`context_type is None`, `pending_intents` empty, default `pedido_actual_id = None`), a draft `Pedido` linked to the comercio and cliente, a `CategoriaProducto`, a `Producto` linked to the categoria and comercio, two `Presentacion` rows named `chica` and `grande`, two `ProductoPresentacion` rows linking the product to each presentation, and two `Precio` rows (one per presentation). Return the ids and the active `Session` ORM instance.
- [x] 2.4 Implement a `_cleanup(db, *, comercio_id, cliente_id, pedido_id, session_id, producto_id)` helper that, inside `with db.begin():`, deletes in FK-safe order: `PedidoProducto` for `pedido_id`, `Precio` for `producto_id`, `ProductoPresentacion` for `producto_id`, `Producto` for `producto_id`, `Pedido` for `pedido_id`, `Session` for `session_id`, `Cliente` for `cliente_id`, `Comercio` for `comercio_id`. Wrap each test's body in `try/finally` so cleanup runs on failure.
- [x] 2.5 Implement a `_patched_classifier(message)` context-manager helper that yields a `MagicMock`-based `IntentClassifier` subclass whose `query(message)` returns `IntentClassificationResult(intents=[ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=message)])`. The patch MUST be applied at `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` and MUST be exited in a `finally:` block.

## 3. Initial-Message Branch Integration Test

- [x] 3.1 Add `class IncomingMessageInitialBranchIntegrationTest(unittest.TestCase)` with `test_initial_message_branch_creates_pending_context`. Use `_seed(...)` to create the fixtures; capture the returned ids.
- [x] 3.2 Open a fresh `db` session from `TestingSessionLocal()`, fetch the `Session` ORM row by id, and call `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` inside the `_patched_classifier(...)` context manager.
- [x] 3.3 Assert `len(result) == 1`; `result[0].status == "pending_resolution"`; `result[0].intent == "agregar_producto"`; the patched `IntentClassifier.query` was called exactly once with the original message; and `dispatch_pending_context` was NOT called (verify by asserting the real module import was used — i.e., the call routed through `dispatch_initial_message`).
- [x] 3.4 Commit the transaction (`db.commit()`), then in a fresh `db` session reload the `Session` ORM row and assert `session.context_type == "product_selection"` and the pending intent for `agregar_producto` is persisted (assert `session.pending_intents` contains exactly one entry with `intent_name == "agregar_producto"` and the persisted `state` matches the pending-resolution state).
- [x] 3.5 Assert no `PedidoProducto` row exists for the draft `pedido_id` (`select(PedidoProducto).where(PedidoProducto.pedido_id == pedido_id)` returns no rows).
- [x] 3.6 Run cleanup in `finally:`.

## 4. Pending-Context Branch Integration Test

- [x] 4.1 Add `class IncomingMessagePendingBranchIntegrationTest(unittest.TestCase)` with `test_pending_context_branch_executes_order_line`. Reuse `_seed(...)` to create the fixtures.
- [x] 4.2 Open a fresh `db` session and the active `Session` ORM row; patch `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` with a `MagicMock` whose constructor and `query` are both tracked.
- [x] 4.3 Call `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` inside the patch context; commit; reload the `Session` ORM row and assert `session.context_type == "product_selection"`. The patched `IntentClassifier` MUST have been constructed exactly once (this is the call that establishes the pending context).
- [x] 4.4 Reset the patch (exit the context manager), reopen a fresh `db` session, refetch the `Session` ORM row, and call `process_incoming_message(db, session, "pizza grande")` WITHOUT any `IntentClassifier` patch — wrap `IntentClassifier` itself in a new `MagicMock` (no `query` configured) that, if constructed, would raise. The expectation is the orchestrator routes to `dispatch_pending_context` without ever consulting `IntentClassifier`. (Note: uses "pizza grande" instead of "la grande" — the recognizer filters "grande" as a TAMANIOS token and only "pizza grande" matches the product, so the assertion `result[0].status == "executed"` can succeed.)
- [x] 4.5 Assert `len(result) == 1`; `result[0].status == "executed"`; `result[0].intent == "agregar_producto"`; the `IntentClassifier` mock was never called (assert `intent_classifier_mock.assert_not_called()`); and `dispatch_initial_message` was not invoked (assert `dispatch_initial_message` is the real module — the call routed through `dispatch_pending_context`).
- [x] 4.6 Commit; in a fresh `db` session assert exactly one `PedidoProducto` row exists for `pedido_id` whose `presentacion_id` corresponds to the `grande` presentation and whose `cantidad == 2`. Reload the `Session` ORM row and assert `session.pending_intents` is empty and `session.context_type is None`.
- [x] 4.7 Run cleanup in `finally:`.

## 5. Spec Sync

- [x] 5.1 Append the new `## ADDED Requirements` block (with `### Requirement: Incoming message orchestrator integration coverage` and its two scenarios) from `openspec/changes/incoming-message-integration-test-3-25/specs/incoming-message-orchestrator/spec.md` into the live `openspec/specs/incoming-message-orchestrator/spec.md`. Do not modify the existing requirements in the live spec.
- [x] 5.2 Confirm the live spec still validates by re-reading the two unchanged requirements (signature, validation, routing, wrapping, no-side-effects, no-HTTP, public-surface) and verifying their scenario blocks remain intact.

## 6. Verification

- [x] 6.1 Run `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_incoming_message_integration` and confirm both tests pass against `supernova_test`, without raising any unexpected exception.
- [x] 6.2 Run `PYTHONPATH=. venv/bin/python -m compileall backend` and confirm exit 0.
- [x] 6.3 Confirm no orphan rows remain in `supernova_test` after both tests complete (re-run `select(PedidoProducto).where(...)`, `select(Session).where(...)`, `select(Comercio).where(nombre_fantasia LIKE "Test %")` and verify zero rows for ids created by the tests).
- [x] 6.4 Confirm the existing unit suite still passes: `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_incoming_message_orchestrator backend.tests.test_initial_intent_dispatcher backend.tests.test_intent_classifier`.
- [x] 6.5 Run `openspec validate incoming-message-integration-test-3-25 --strict` and confirm valid.