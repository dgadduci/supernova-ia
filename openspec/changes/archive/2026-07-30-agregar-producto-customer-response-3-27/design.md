## Context

The modern `agregar_producto` pipeline has stabilized across Subphases 3.24 → 3.26:

- `process_incoming_message(db, session, message)` (3.24) validates the message and routes to `dispatch_pending_context` or `dispatch_initial_message`, returning a `list[ProcessedIntent]` with statuses `pending_resolution`, `ready`, `executed`, `rejected`, or `failed`.
- `process_initial_agregar_producto` produces a `pending_resolution` `ProcessedIntent` carrying `candidate_ids` (product-presentation IDs) when multiple presentations match the customer's message, and `resolved_data` (`producto_presentacion_id`, `cantidad`) when one is unambiguous.
- `dispatch_pending_context` (3.18) consumes the customer's reply; if the reply resolves to exactly one presentation, it returns `executed`; otherwise it leaves `pending_resolution` and `session.context_type` set.
- `execute_agregar_producto` (3.16) produces `executed`, `rejected`, or `failed` after invoking `PedidoProductoService.add`.
- `process_incoming_message_transactional` (3.26) owns the `db.commit()` / `db.rollback()` boundary around the orchestrator.

Until now the pipeline had no seam that converts a `ProcessedIntent` into a customer-facing string. Subphase 3.27 introduces that seam for `agregar_producto` only:

- A small `CustomerResponse` Pydantic model captures the message plus the two pieces of metadata a future transport adapter will need (`intent`, `status`) without baking Twilio / FastAPI concerns into the intent layer.
- A single builder function `build_agregar_producto_response(db, session, intent)` returns a `CustomerResponse` for any of the four runtime outcomes (`pending_resolution`, `executed`, `rejected`, `failed`), reusing `ProductoQueryService.list_presentaciones_by_ids` so the builder stays free of SQLAlchemy and repository imports.

The builder is the narrowest deterministic shaper that still gives the customer enough information to continue the conversation (clarification when ambiguous, confirmation when added, apology when rejected, retry when failed). Transport, message templating engines, locale, and beautification are explicitly future concerns.

## Goals / Non-Goals

**Goals:**

- Expose `build_agregar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse` from `backend/intents/responses/agregar_producto_response.py` as the single deterministic builder for `agregar_producto` customer replies.
- Expose `CustomerResponse(message: str, intent: str, status: str)` from `backend/intents/schemas/customer_response.py`.
- For `status == "pending_resolution"` with non-empty `candidate_ids`: load candidates through `ProductoQueryService.list_presentaciones_by_ids(intent.candidate_ids)`; build a clarification listing only product + presentation names; do not expose IDs, prices, or stock.
- For `status == "executed"`: load the resolved presentation through `ProductoQueryService.list_presentaciones_by_ids([resolved_data["producto_presentacion_id"]])`, validate `resolved_data["cantidad"]` is a positive integer, and confirm the product, presentation, and quantity in a single deterministic sentence.
- For `status == "rejected"`: return a concise apology without naming internal reasons or IDs.
- For `status == "failed"`: return a generic retry prompt without exception types, IDs, or technical detail.
- For any non-`agregar_producto` intent or any unrecognized status: return a generic apology response that still records the original `intent.intent` and `intent.status`.
- Stay free of LLM calls, SQLAlchemy queries, repository imports, `db.commit` / `db.rollback`, mutation of `session`, `pedido`, or `intent`, HTTP / Twilio integration, response beautification, response objects for other intents, retry/backoff, async wrappers, and logging.
- Add focused tests in `backend/tests/api_smoke.py` that exercise each status branch against the existing `supernova_test` database and assert no state mutation, no `db.commit`, no `db.rollback`, and no SQLAlchemy queries in the builder.

**Non-Goals:**

- Implementing response objects for any other intent (`consultar_pedido`, `confirmar_pedido`, etc.).
- Generating responses via LLM, templates, locale, or message-formatting libraries.
- Sending replies over Twilio, WhatsApp, FastAPI, HTTP, or any transport layer.
- Composing `PedidoProducto` summaries, price totals, or running order lines; the confirmation only states the product, presentation, and quantity that was added.
- Mutating `Session` (`pending_intents`, `context_type`), `Pedido`, `PedidoProducto`, or `intent`.
- Refreshing, expiring, flushing, committing, or rolling back the SQLAlchemy session.
- Introducing a registry, a factory, or a multi-intent dispatcher for responses.
- Modifying `backend/intents/handlers/agregar_producto_handler.py`, `backend/intents/orchestration/*`, `backend/services/pedido_producto_service.py`, `backend/services/producto_query_service.py`, `backend/repositories/producto_query_repository.py`, `backend/models/*`, `backend/llm/*`, `backend/routers/*`, or `backend/dependencies/*`.

## Decisions

- **Module location: `backend/intents/responses/agregar_producto_response.py`.** A new `responses/` package sits next to `handlers/`, `orchestration/`, `resolvers/`, `schemas/`, `services/`, and `context/` inside the intents package. The response shaper is the customer-facing mirror of the existing handler / orchestrator pair, so it earns its own sibling directory rather than living inside `handlers/` (which would conflate business execution with reply shaping) or `orchestration/` (which would mix transport-free coordination with message authoring).

- **Schema location: `backend/intents/schemas/customer_response.py`.** `CustomerResponse` belongs with the other Pydantic intent schemas (`processed_intent.py`, `requirement_state.py`, `pending_intents.py`, `intent_classification.py`). Rationale: the existing `intents/schemas/` package is the project's single home for typed contracts; adding a sibling Pydantic model there keeps the contract surface discoverable and avoids a parallel "responses" schema package.

- **Single `CustomerResponse` model with three string fields.** `message: str`, `intent: str`, `status: str`. Rationale: the future Twilio / FastAPI adapter needs only the textual reply and the routing metadata (`intent`, `status`) it already consumes elsewhere in the pipeline; richer fields (template id, locale, channel metadata) belong with the transport adapter, not the intent layer. Strings over enums: `status` mirrors the `IntentStatus` literal set but is passed through verbatim so the response schema does not have to import the intent status enum or stay coupled to its evolution.

- **Single public function: `build_agregar_producto_response`.** `__all__ = ["build_agregar_producto_response"]` keeps the surface narrow and mirrors the discipline of `execute_agregar_producto`, `process_incoming_message`, `dispatch_pending_context`, and `process_initial_agregar_producto`. Rationale: the future transport adapter needs exactly one deterministic shaper per intent; exposing helpers now would force future changes to deprecate them.

- **Typing aliases for the two `Session` meanings.** Use `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model — the same aliases already used in `agregar_producto_orchestrator.py`, `incoming_message_orchestrator.py`, `pending_context_dispatcher.py`, `execute_agregar_producto`, and `process_incoming_message_transactional`. Rationale: keeps the call site readable and avoids shadowing the most-imported symbol in the module.

- **Reuse `ProductoQueryService.list_presentaciones_by_ids` for both `pending_resolution` and `executed`.** The function already returns a list of dicts containing `producto_nombre`, `presentacion_descripcion`, `presentacion_codigo`, and the IDs we never expose. Rationale: the builder should not import the repository directly, should not duplicate the joinedload that warms the `producto` and `presentacion` relationships, and should not bypass the existing business-rule checks the service already enforces for input validation. Wrapping the call inside the builder costs nothing extra.

- **Deterministic templates only — no LLM, no template engine.** Four pure-string format calls; no `jinja2`, no `string.Template`, no formatting library beyond f-strings. Rationale: the future beautification subphase will own templates; this subphase is the contract test surface for the shaper's four deterministic branches.

- **Clarification message lists at most one name per product + presentation pair, in the order returned by the service.** Use a single sentence that joins each pair with a comma and an "o" before the last entry; do not include quantities in the clarification (the customer already knows what they ordered). Rationale: the customer only needs to see the human-readable alternatives to choose from; IDs, prices, and stock are internal concerns.

- **Confirmation message includes product, presentation, and quantity.** For `executed` status with `cantidad == 1`, the message uses the singular ("agregué 1 Pizza Mozzarella grande"). For `cantidad > 1`, the message uses the plural ("agregué 2 Pizza Mozzarella grande"). Rationale: the customer benefits from a direct confirmation that names the product, the chosen presentation, and the quantity added — exactly the three pieces of data the handler snapshot was created from.

- **Rejected message is a fixed apology sentence, no technical reasons.** "No pude procesar tu pedido, ¿podrías reformularlo?" (Spanish, deterministic, no exception messages, no status codes). Rationale: rejected is a business outcome already shaped by `execute_agregar_producto` (handler-level rejections, missing pedido, invalid resolved data); the response shaper must not duplicate the handler's reasons and must not leak the original `reason` strings into the customer channel.

- **Failed message is a generic retry prompt with zero technical detail.** "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?" (Spanish, deterministic, no exception types, no stack trace, no IDs). Rationale: failed is the unexpected-exception path; the response shaper must not surface internal debugging context.

- **Generic fallback for non-`agregar_producto` intents or unrecognized statuses.** Return `CustomerResponse(message=APOLOGY_MESSAGE, intent=intent.intent, status=intent.status)`. Rationale: the shaper is intentionally `agregar_producto`-only but must not crash on other intents that might reach it before a future multi-intent dispatcher exists; the fallback preserves the original `intent` and `status` so a future caller can still log the routing decision.

- **No mutation, no commit, no rollback, no flush, no refresh, no expire.** The builder only reads through `ProductoQueryService.list_presentaciones_by_ids`. It never assigns to `session.pending_intents`, `session.context_type`, `session.id_pedido`, `pedido.*`, or `intent.*`. Rationale: the project rule "no Session/Pedido/intent mutation outside the orchestrator/handler" is binding; the response shaper is downstream of all persistence and must remain a pure read.

- **Tests follow `api_smoke.py` style and reuse the existing `supernova_test` engine.** Add one new function `test_agregar_producto_customer_response` that creates a commerce + categoria + presentacion + producto + asociacion + precio, exercises each of the four branches via `build_agregar_producto_response`, asserts the message contents (substrings for product/presentation/quantity, absence of IDs for the clarification branch, fixed apology for rejected, fixed retry for failed), and asserts no `db.commit` / `db.rollback` / state mutation was triggered. Rationale: matches the established project discipline of accumulating `record(...)` checks in `api_smoke.py` instead of creating a new test file.

## Risks / Trade-offs

- [Risk] A future transport adapter may want richer metadata (channel, locale, template id, message id) on `CustomerResponse` → Mitigation: keep `CustomerResponse` to three string fields and let the transport adapter wrap it with its own envelope. The shaper's discipline of staying schema-minimal is the same discipline applied by `ProcessedIntent` in Subphase 3.3.

- [Risk] Templates may need to vary by locale (es-AR vs pt-BR) → Mitigation: this subphase ships a single Spanish template per branch; a future "response beautification" subphase can introduce locale-aware templating without changing `CustomerResponse`. The current deterministic templates are intentionally minimal so the future locale work does not have to revert any customer-visible wording.

- [Risk] The clarification message accidentally exposes a database ID if a future field is added to `list_presentaciones_by_ids` → Mitigation: the builder constructs each presentation label from `producto_nombre` and `presentacion_descripcion` only, both of which are already-defined business strings; the minimum tests assert the literal substring "id" never appears in the clarification message and assert a known numeric ID is absent.

- [Risk] The shaper silently swallows a `ProductoPresentacionNotFound` for the `executed` branch when the snapshot price was deleted between handler execution and response generation → Mitigation: the builder catches `ProductoPresentacionNotFound` and returns the generic `failed` reply for that single outcome; this preserves the contract that the shaper never raises and never exposes the technical reason. The minimum tests cover both the success path (matching ID) and the missing-ID path.

- [Risk] The `pending_resolution` branch is invoked with empty `candidate_ids` → Mitigation: the builder returns the apology fallback when `candidate_ids` is empty (the customer would otherwise see a malformed "tienes que elegir entre:" prompt with no options). The minimum tests assert the empty-candidates case.

- [Risk] Adding a fourth module to the intents package increases import surface → Mitigation: `__all__` discipline keeps the public surface to a single function; the test suite asserts `__all__ == ["build_agregar_producto_response"]` so future drift is caught immediately.

- [Risk] Future subphases may want to add logging, retries, or async wrappers here, blurring the pure-shaper contract → Mitigation: the non-goals section is explicit; the minimum tests assert the module does not import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.llm`, `backend.old_project`, or any handler / queue / dispatcher module.

## Migration Plan

1. Create `backend/intents/schemas/customer_response.py` exposing `CustomerResponse(message: str, intent: str, status: str)` with `__all__ = ["CustomerResponse"]`; do not touch any other schema.
2. Create `backend/intents/responses/__init__.py` (empty package marker).
3. Create `backend/intents/responses/agregar_producto_response.py` with `__all__ = ["build_agregar_producto_response"]` and the typed-alias imports; implement `build_agregar_producto_response` per the four-branch decision tree using `ProductoQueryService(db).list_presentaciones_by_ids`.
4. Append `test_agregar_producto_customer_response()` to `backend/tests/api_smoke.py` covering: `pending_resolution` clarification with two candidates (asserts presentation names present, IDs absent), `executed` confirmation with `cantidad == 1` and `cantidad == 2` (asserts product/presentation/quantity in message, no IDs), `rejected` apology (asserts the fixed apology string), `failed` retry (asserts the fixed retry string and no technical detail), non-`agregar_producto` intent fallback, empty `candidate_ids` fallback, missing `producto_presentacion_id` in the executed branch (`failed` fallback), `__all__` discipline, no `db.commit` / `db.rollback` / `HTTPException` / `requests` / `fastapi` / `twilio` / `backend.llm` / `backend.routers` / `backend.old_project` imports, no mutation of `session`/`intent`.
5. Wire the new test into the `__main__` runner of `api_smoke.py` so it runs as part of the standard smoke suite.
6. Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` (or `python -m unittest` against the new symbols) and confirm all new `record(...)` entries pass.
7. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to catch syntax errors.
8. Run `openspec validate agregar-producto-customer-response-3-27 --strict` and confirm valid.
9. Roll back by deleting the new files; no other module imports them, so no ripple effects.

## Open Questions

None.