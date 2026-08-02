## Context

Subphase 3.24 shipped `process_incoming_message(db, session, message) -> list[ProcessedIntent]` as the modern internal front door for the intents pipeline, along with 21 focused unit tests in `backend/tests/test_incoming_message_orchestrator.py`. Those tests patch `dispatch_initial_message` and `dispatch_pending_context` with `MagicMock` returns and prove the routing rule, message validation, pending-result wrapping, classified-intent order preservation, exception propagation, and no-commit/rollback guarantee in isolation.

What the unit tests do not cover is the integration with the real components downstream of the orchestrator: `IntentClassifier.query`, `process_initial_agregar_producto`, the product recognizer, resolver, processor, the pending-context dispatcher and execution path, the handler that creates the `PedidoProducto`, and the services that read and write to `supernova_test`. A regression in any of those components (e.g., the orchestrator stops persisting `session.context_type`, the recognizer stops returning multiple `Producto` candidates, the resolver stops resolving quantities) would not be caught by the unit suite because both dispatchers are mocked.

Subphase 3.25 adds a single integration test module that exercises both routing branches of `process_incoming_message` against `supernova_test` with real orchestrators, recognizer, resolver, dispatcher, handler, and services, mocking only `IntentClassifier.query` (the external LLM classification boundary). The test suite intentionally avoids duplicating Subphase 3.19's `agregar-producto-end-to-end` coverage and intentionally avoids re-testing unsupported intents, invalid messages, or internal-unit behavior. If the integration test exposes a defect, the fix ships in a separate subphase; this change is test-only.

## Goals / Non-Goals

**Goals:**
- Add `backend/tests/test_incoming_message_integration.py` with exactly two tests — one per routing branch — that drive `process_incoming_message` end-to-end against `supernova_test`.
- Use real components throughout: `process_initial_agregar_producto`, `dispatch_pending_context`, recognizer, resolver, processor, `PedidoProducto`-creating handler, services, and the SQLAlchemy session.
- Mock only `IntentClassifier.query` (the external LLM classification boundary), at the `dispatch_initial_message` import site (`backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier`).
- Initial-branch test asserts: one returned `ProcessedIntent` with `status == "pending_resolution"`, `session.context_type == "product_selection"`, the active pending intent is persisted, no `PedidoProducto` row exists.
- Pending-branch test asserts: `IntentClassifier` is not constructed, one returned `ProcessedIntent` with `status == "executed"`, exactly one `PedidoProducto` with presentation `grande` and `cantidad == 2`, `session.pending_intents` is empty, `session.context_type is None`.
- Keep setup helpers minimal — one shared helper that seeds commerce, client, session, draft pedido, product with two active presentations and prices; both tests reuse it.
- Update `openspec/specs/incoming-message-orchestrator/spec.md` with two new integration scenarios documenting the new contract.

**Non-Goals:**
- Adding new production code, modules, services, or orchestrators.
- Modifying `process_incoming_message`, `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, `QueryLlm`, recognizers, resolvers, processors, handlers, services, repositories, models, migrations, configuration, FastAPI dependencies, or routers.
- Implementing transaction management, response generation, HTTP, FastAPI, or Twilio layers in the tests; commit/rollback remain the caller's responsibility.
- Re-testing unsupported intents (`desconocida`, `saludo`, `quitar_producto`), invalid messages (non-string, empty, whitespace-only), or internal-unit-level behavior already covered by `backend/tests/test_incoming_message_orchestrator.py` and `backend/tests/test_initial_intent_dispatcher.py`.
- Duplicating scenarios already covered by Subphase 3.19's `agregar-producto-end-to-end` suite.
- Implementing a FastAPI route, dependency, or background task that consumes `process_incoming_message`; the integration test drives the orchestrator directly.

## Decisions

- **File location: `backend/tests/test_incoming_message_integration.py`.** Sits next to `test_incoming_message_orchestrator.py` (unit) and `test_initial_intent_dispatcher.py` (unit) but is clearly labeled `_integration` to signal that it requires `supernova_test` and runs only in the integration phase. Mirrors the `api_smoke.py` / unit-test split already in the project.

- **Test framework: `unittest.TestCase`.** Matches the existing test style (`test_incoming_message_orchestrator.py`, `test_initial_intent_dispatcher.py`, `test_intent_classifier.py`).

- **Mock surface: only `IntentClassifier`, exactly one boundary.** Patch `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` with `unittest.mock.patch`. The patched constructor returns an object whose `query(message)` returns a pre-built `IntentClassificationResult` containing one `ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=<the original message>)`. The pending-context test asserts `IntentClassifier` is never called (no mock is constructed) — proven by patching the symbol with a `MagicMock` that records construction and asserting `IntentClassifier.assert_not_called()`.

- **Database connection: `supernova_test`.** Reuse the same `TEST_URL = "postgresql+psycopg:///supernova_test"` constant from `api_smoke.py`. Build an engine and `sessionmaker` at module load time exactly as `api_smoke.py` does; do not introduce a new conftest or shared fixture module.

- **Fixture strategy: one shared `_seed(...)` helper, no class-level setup.** The helper creates commerce, client, active session, draft pedido, product with two presentations (`chica`, `grande`), and prices inside a single `with TestingSessionLocal() as s, s.begin():` block so all writes commit atomically. It returns the IDs and objects the tests need (`session_id`, `pedido_id`, `producto_id`). Both tests call it; no fixture is shared between tests via class state, which keeps test isolation intact.

- **Cleanup: explicit `delete` after each test.** Each test calls a `_cleanup(db, comercio_id)` helper that deletes `PedidoProducto`, `Precio`, `ProductoPresentacion`, `Producto`, `Pedido`, `Session` (the conversation model), `Cliente`, and `Comercio` rows by their IDs in the correct FK order, inside `with TestingSessionLocal() as s, s.begin():`. The cleanup runs in `finally:` of each test so a failure does not leave orphan rows.

- **Pending-branch test reuses the post-initial-branch state.** Test 2 does not re-seed; it calls `_seed`, runs `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` to establish the pending context, then runs `process_incoming_message(db, session, "la grande")` and asserts the execution branch. Rationale: the contract under test is "pending-context dispatch works after the initial message created the pending context" — re-seeding would test a different invariant.

- **No transaction management inside the test.** The tests rely on the orchestrator's documented no-commit / no-rollback contract: each `process_incoming_message` call commits inside the caller-controlled `with TestingSessionLocal() as s, s.begin():` block, so `session.context_type`, the pending intent persistence, and the `PedidoProducto` insert all commit atomically with the test's transaction.

- **`IntentClassifier` mock yields the original message as `classified.mensaje`.** The pre-built `ClassifiedIntent` uses `mensaje="quiero 2 pizzas de mozzarella"` (the original inbound message). Rationale: this is what a real classifier would return, and it exercises the same path the production classifier exercises in `dispatch_initial_message`.

- **No logging, no async, no response shaping in the test.** Match the orchestrator's discipline: the test reads structured fields off the returned `ProcessedIntent` and queries the DB to verify side-effects; it does not capture logs or assert on user-facing replies.

- **Specs delta is a new ADDED Requirements block, not MODIFIED.** The new requirement documents the integration-test contract that now exists; the existing `incoming-message-orchestrator` requirements remain unchanged because the orchestrator's behavior is unchanged.

## Risks / Trade-offs

- [Risk] The integration test depends on `supernova_test` being seeded and reachable; if it is not, the test fails for environmental reasons rather than behavioral ones → Mitigation: the test reads the same seeded lookup rows (`EstadoComercio.ACTIVO`, presentations, prices) used by `api_smoke.py` and asserts on inserted-by-the-test rows only; it does not assert against fixture data shared with other suites.

- [Risk] Sharing the `_seed` helper between two tests creates coupling → Mitigation: the helper takes no implicit state, both tests call it with identical arguments, and cleanup runs in `finally:` per test; the helper itself is pure.

- [Risk] Mocking `IntentClassifier` at `initial_intent_dispatcher.IntentClassifier` could miss a future refactor that constructs it elsewhere → Mitigation: the pending-branch test asserts `IntentClassifier.assert_not_called()`, which catches accidental construction anywhere reachable through the import chain.

- [Risk] The pending-branch test reuses post-initial state, making it order-dependent within a single test run → Mitigation: both branches live in a single test method (`test_pending_branch_after_initial_branch`) so the order is enforced by the test, not by pytest collection.

- [Risk] Adding the new spec scenarios to `incoming-message-orchestrator` could be read as expanding the orchestrator's behavioral contract rather than documenting the new integration coverage → Mitigation: the new requirement explicitly states "the test exercises X" and references the test file path; the orchestrator's own behavior is not extended.

- [Risk] Cleanup may miss a new FK → Mitigation: cleanup uses explicit `delete(...).where(id == X)` per model and runs inside `with s.begin():` so a failure rolls back the entire cleanup, leaving the database in a deterministic pre-test state.

## Migration Plan

1. Add `backend/tests/test_incoming_message_integration.py` with two test methods and the shared `_seed` / `_cleanup` helpers; do not modify any production module.
2. Update `openspec/specs/incoming-message-orchestrator/spec.md` by appending one new requirement (`Incoming message orchestrator integration coverage`) with two scenarios (initial-branch and pending-branch).
3. Run only the new test module: `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_incoming_message_integration`.
4. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to catch syntax errors.
5. Roll back by deleting the new test file and reverting the spec delta; no other module imports them, so no ripple effects.

## Open Questions

None.