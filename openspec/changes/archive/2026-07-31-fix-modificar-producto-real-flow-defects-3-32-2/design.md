## Context

Subphase 3.32 (`modificar-producto-end-to-end-3-32`) wired `modificar_producto` through the full modern message-processing pipeline. Subphase 3.32.1 (`fix-modificar-producto-atomicity-quantity-3-32-1`) declared two real-flow defects corrected:

- **Defect 1 — Source quantity is lost when destination quantity is omitted.** Sending `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4` produces a destination `cantidad == 1` instead of `4`.
- **Defect 2 — Source is mutated before destination validation.** Sending `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` (and `caramelo` not in the catalog) leaves the Pedido with the source line removed and no destination.

Subphase 3.32.1 corrected both defects at the orchestrator/handler/service level. The 3.32.1 atomicity-focused suite, the end-to-end matrix, and the existing handler, recognizer, initial-orchestrator, response, transactional, response-orchestrator, and dispatcher-integration suites pass against `supernova_test` and `pytest` reports every test green.

Real CLI testing against the running local FastAPI app still reproduces both defects. The 3.32.1 unit and orchestrator-level tests exercise the corrected code by calling `execute_modificar_producto` and `PedidoProductoService.modify_product` directly with hand-crafted `ProcessedIntent` payloads and a `_ModificarClassifier` patched into `initial_intent_dispatcher.IntentClassifier`. They never drive the real HTTP endpoint `POST /comercios/{id}/clientes/{id}/incoming-messages` nor the interactive CLI driver at `backend/scripts/cli_chat_client.py`. The defects live in the seam between the orchestrator-level correction and the real HTTP/CLI pipeline, and the 3.32.1 test matrix never crossed that seam.

This change follows a diagnose-then-fix workflow: first reproduce the exact two phrases through the real HTTP endpoint and the interactive CLI driver, identify which layer is at fault (recognizer, initial orchestrator, pending-context resolver, handler, service, response, HTTP endpoint, or CLI), apply the minimum correction to that layer, and add a regression matrix that drives the real HTTP/CLI pipeline end-to-end so the prior orchestrator-level coverage is no longer sufficient by itself. The change MUST NOT auto-sync and MUST NOT auto-archive; both remain explicit user commands.

## Goals / Non-Goals

**Goals:**

- Drive the two exact phrases through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint and through `backend/scripts/cli_chat_client.py`; capture the actual `CustomerResponse.message`, the actual `PedidoProducto` rows, the actual `Session.context_type`, and the actual `ProcessedIntent.status` for each phrase.
- Identify, with evidence, which layer is responsible for each defect when driven by the real pipeline. Document the diagnosis in this design after the reproduction step, not before.
- Apply the minimum correction in the layer the reproduction reveals. Keep every 3.32.1 invariant intact: one `modificar_producto` operation, one `ProcessedIntent`, one `CustomerResponse`, validation-before-mutation, one outer transaction, no separate `quitar_producto`/`agregar_producto` execution, no `commit`/`rollback`/`flush`/`refresh`/`expire`/`begin` in the service, no LLM in the response builder, no DB ID exposure, no extra confirmation turn, no new intent.
- Preserve the authoritative quantity rule (omitted quantity = re-read source quantity, never `1`) at every layer the real pipeline crosses.
- Preserve the validation-before-mutation rule at every layer the real pipeline crosses.
- Preserve the price-snapshot and consolidation rules at every layer the real pipeline crosses.
- Preserve the corrected pending-context lifecycle (`executed` clears, definitive `rejected` clears, `failed` preserves, raised exceptions propagate for rollback).
- Preserve the deterministic response matrix (`Cambié N ... por N ...`, `Solo tenés N ... para cambiar. Tu pedido no fue modificado.`, `No encontré el producto de reemplazo. Tu pedido no fue modificado.`, `El producto no está disponible. Tu pedido no fue modificado.`).
- Add real-flow regression tests that drive the real HTTP endpoint and the interactive CLI driver with the exact two phrases. The new tests MUST coexist with the existing orchestrator-level tests; the existing tests MUST remain green.
- Keep the change inside the seams established by 3.32 and 3.32.1: no DB schema change, no Alembic migration, no new HTTP endpoint, no CLI redesign, no LLM beautification, no new intent, no broad transaction changes, no lower-level commits, and no second `CustomerResponse` per modification.
- Do NOT sync main specs automatically. Do NOT archive the change automatically. Both remain explicit user commands.

**Non-Goals:**

- Do not redesign `modificar_producto`. Do not redesign the dispatcher or the transactional processor. Do not redesign the response builder. Do not redesign the CLI driver.
- Do not introduce a new HTTP endpoint. Do not introduce a new intent. Do not introduce an LLM call in the response builder.
- Do not introduce a DB schema change or Alembic migration.
- Do not introduce optimistic locking, retry logic, SAVEPOINTs, or any change to the outer transaction boundary.
- Do not introduce a new public repository method or a new public service method unless reproduction proves it is strictly required.
- Do not auto-sync main specs. Do not auto-archive the change.

## Decisions

### 1. Reproduce before fixing

The first task of this change is to drive the two exact phrases through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint and through `backend/scripts/cli_chat_client.py` against a seeded `supernova_test` commerce. Capture: the raw HTTP response body, the CLI stdout/stderr, the resulting `PedidoProducto` rows, the `Session.context_type`, and the `ProcessedIntent.status`. The reproduction MUST be reproducible by any contributor with a checkout, `supernova_test` seeded, and `uvicorn backend.main:app` running locally.

**Rationale:** The defects pass every orchestrator-level test but still reproduce in real CLI testing. The reproduction step is the only way to identify which layer is at fault (recognizer, initial orchestrator, pending-context resolver, handler, service, response, HTTP endpoint, or CLI) before applying a fix. Fixing without reproducing risks re-introducing the 3.32.1 anti-pattern of "tests pass but runtime fails."

**Alternatives considered:**

- *Fix forward without reproduction.* Rejected: this is exactly what 3.32.1 did. Without a reproduction step, the fix layer is a guess, and the test matrix can pass while runtime still fails.
- *Skip the CLI driver and only reproduce through HTTP.* Rejected: the CLI driver is one of the two real entry points the user is using. The CLI may carry its own defect (e.g., it parses the response differently, or it submits a different message body, or it injects an extra confirmation turn). Both entry points must be exercised.

### 2. Capture evidence per layer

For each phrase, capture the per-layer trace: the classifier output, the recognizer output (`source_candidate_ids`, `destination_candidate_ids`, `cantidad`), the orchestrator output (`status`, `stage`, `resolved_data`), the handler call signature (`source_id`, `dest_id`, `cantidad`), the service call signature (`pedido_id`, `pedido_producto_origen_id`, `producto_presentacion_destino_id`, `cantidad`), the `ModificationResult.status` and `reason`, and the final `CustomerResponse.message`. The trace is recorded in a Markdown table inside `design.md`'s diagnosis section.

**Rationale:** Per-layer evidence is the only way to prove which layer misbehaves. If the recognizer emits the wrong `source_candidate_ids`, that is a recognizer defect. If the recognizer is correct but the orchestrator substitutes `1` for `None`, that is an orchestrator defect. If the orchestrator is correct but the handler re-reads `source.cantidad` and the handler sees `cantidad == 4`, the defect is elsewhere (e.g., the HTTP endpoint deserializes `cantidad` as `1`, or the CLI driver swallows a word and submits a different message). The per-layer table is the diagnosis.

**Alternatives considered:**

- *Black-box reproduction only (response message and DB state).* Rejected: insufficient to identify which layer is at fault when the defect spans multiple layers. The 3.32.1 unit tests already prove the orchestrator-level layers are individually correct in isolation; the question is which layer breaks the chain when driven by the real pipeline.
- *Reproduce through the orchestrator-level test entry points.* Rejected: that is what 3.32.1 already does. The whole point of 3.32.2 is to drive the real pipeline, not the orchestrator fixtures.

### 3. Apply the minimum correction in the layer the reproduction reveals

Once the per-layer trace identifies the layer, apply the smallest change that corrects the defect at that layer. The minimum-correction rule prevents over-engineering and keeps every 3.32.1 invariant intact. If the defect is in the recognizer, the fix is in the recognizer. If the defect is in the CLI driver, the fix is in the CLI driver. The change does not preemptively correct layers that already behave correctly in isolation.

**Rationale:** The defect is layer-local. The 3.32.1 unit tests prove the orchestrator-level layers are individually correct; the issue is in the seam between the orchestrator-level pipeline and the real HTTP/CLI entry points. Applying a global correction would re-introduce the "tests pass but runtime fails" anti-pattern.

**Alternatives considered:**

- *Apply a global correction across every layer.* Rejected: violates the minimum-correction rule and risks regressing the 3.32.1 invariants.
- *Apply the correction in the handler and let the recognizer/CLI be.* Rejected: the diagnosis may show the defect is upstream of the handler (e.g., the CLI driver parses the message and submits `cantidad == 1` instead of omitting it). The fix must be at the layer the reproduction reveals.

### 4. Real-flow regression matrix

Add two new test files:

- `backend/tests/test_modificar_producto_real_flow_http.py` — uses `httpx.AsyncClient` (or the existing test client pattern) to drive the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint with the exact two phrases. The test seeds a fresh commerce against `supernova_test`, drives the phrase, and asserts the response message, the `PedidoProducto` rows, and the `Session.context_type`.
- `backend/tests/test_modificar_producto_real_flow_cli.py` — drives `backend/scripts/cli_chat_client.py` as a subprocess (or via in-process invocation if the existing CLI test pattern allows) with the exact two phrases, captures the printed customer response and the printed order table, and asserts the same invariants.

The matrix also covers the full atomic-quantity regression suite already in `test_modificar_producto_end_to_end.py` and `test_modificar_producto_atomicity_focused.py`. The change MUST NOT weaken or delete the existing suites.

**Rationale:** The orchestrator-level tests pass while runtime fails because they never cross the seam between the orchestrator and the real HTTP/CLI entry points. Driving the real entry points in the test matrix closes that gap and makes future regressions visible.

**Alternatives considered:**

- *Drive only the HTTP endpoint, not the CLI driver.* Rejected: the CLI driver is one of the two real entry points and may carry its own defect. The full reproduction requires both.
- *Add the HTTP regression but reuse the existing `test_modificar_producto_end_to_end.py` file.* Rejected: the existing file patches the classifier and bypasses the real HTTP endpoint. Adding a separate file makes the seam visible and prevents accidental coupling.

### 5. Diagnosis captured in `design.md` after reproduction

The diagnosis section of this design (written after the reproduction step, not before) MUST identify, per defect, the layer at fault and the evidence (per-layer trace, raw HTTP response, CLI stdout, DB state). If the defect is in the recognizer, the recognizer code is cited; if it is in the CLI driver, the CLI driver code is cited. The diagnosis MUST also explain why the prior 3.32.1 orchestrator-level tests passed: typically, because they patched the classifier, hand-crafted the `ProcessedIntent`, and bypassed the real HTTP/CLI entry points.

**Rationale:** The diagnosis is the value of this change. Without it, future contributors will repeat the same anti-pattern. The diagnosis is written after the reproduction so it reflects actual evidence, not a priori reasoning.

**Alternatives considered:**

- *Write the diagnosis before reproduction.* Rejected: this is what 3.32.1 did, and it produced an incomplete diagnosis. The diagnosis must follow the evidence.
- *Skip the diagnosis and only fix the defect.* Rejected: the diagnosis is what makes this change a learning artifact rather than a one-off patch.

### 6. Preserve every 3.32.1 invariant

The correction MUST NOT alter any of the 3.32.1 invariants: one `modificar_producto` operation per replacement command; one `ProcessedIntent`; one `CustomerResponse`; validate source, quantity, and destination before any mutation; one outer transaction owned by `process_incoming_message_transactional`; handler never decomposes into separate `quitar_producto`/`agregar_producto` calls; service never `commit`s, `rollback`s, `flush`es, `refresh`es, `expire`s, or `begin`s; recognizer never substitutes `1` for an omitted quantity; initial orchestrator never substitutes `1`; pending-context resolver never substitutes `1`; handler re-reads source quantity at execution time; service runs validations in strict pre-mutation order; price snapshot preserved for existing destination; current price read before source mutation; consolidation increments in place; equivalent modification rejected; foreign-comercio destination rejected; pending-context lifecycle preserved; deterministic response matrix preserved.

**Rationale:** These invariants are the 3.32.1 contract. Breaking any of them re-introduces the defects 3.32.1 was designed to correct.

**Alternatives considered:**

- *Loosen an invariant to make the fix simpler.* Rejected: every invariant is load-bearing. Loosening any one of them re-opens a defect.

### 7. CLI order-table regression for both phrases

Add a CLI regression test that drives the exact two phrases through `backend/scripts/cli_chat_client.py` and asserts the printed order table: after Defect 1, the table shows the destination line with `cantidad == 4` and no source line; after Defect 2, the table shows the source line unchanged.

**Rationale:** The CLI prints the order table after each customer response. The table is the customer's view of the Pedido state. If the table is wrong, the customer-facing UX is broken even if the API response is correct.

**Alternatives considered:**

- *Skip the CLI table regression.* Rejected: the table is part of the real CLI driver and is one of the two real entry points the user uses.

### 8. Existing tests remain green

Every existing 3.32 and 3.32.1 test file MUST remain green unchanged:

- `backend/tests/test_modificar_producto_atomicity_focused.py`
- `backend/tests/test_modificar_producto_end_to_end.py`
- `backend/tests/test_modificar_producto_handler.py`
- `backend/tests/test_modificar_producto_initial.py`
- `backend/tests/test_modificar_producto_recognizer.py`
- `backend/tests/test_modificar_producto_response.py`
- `backend/tests/test_modificar_producto_transactional_regression.py`
- `backend/tests/test_modificar_producto_response_orchestrator.py`
- `backend/tests/test_modificar_producto_dispatcher_integration.py`
- `backend/tests/test_modificar_producto_contract.py`
- `backend/tests/test_modificar_producto_repository.py`
- `backend/tests/test_modificar_producto_service.py`
- `backend/tests/test_cli_chat_client.py`
- `backend/tests/test_cli_conversation_regression.py`
- `backend/tests/test_incoming_messages_endpoint.py`
- `backend/tests/test_incoming_message_integration.py`
- `backend/tests/test_incoming_message_orchestrator.py`
- `backend/tests/test_incoming_message_response_orchestrator.py`
- `backend/tests/test_transactional_message_processor.py`
- The `agregar_producto` and `quitar_producto` regressions.

**Rationale:** These tests are the lower-level safety net. Weakening them to make the fix pass re-introduces the 3.32.1 anti-pattern.

**Alternatives considered:**

- *Refactor existing tests to make the fix easier.* Rejected: out of scope; refactoring risks regression.

### 9. No DB schema change, no Alembic migration

The correction MUST NOT introduce any DB schema change or Alembic migration. The defect is in the seam between the orchestrator-level pipeline and the real HTTP/CLI entry points; it is not a data-model issue.

**Rationale:** Mirrors the 3.32.1 rule. A schema change is a sledgehammer; the defect is a scalpel problem.

**Alternatives considered:**

- *Add a column to `pedidos_productos` to store the omitted-quantity sentinel.* Rejected: the service already reads the source quantity at execution time. The schema is sufficient; the seam is the issue.

### 10. No automatic sync, no automatic archive

The change MUST NOT run `openspec sync` automatically. The change MUST NOT run `openspec archive` automatically. Both remain explicit user commands. The `/opsx:apply` command must stop after implementation, tests, task updates, and reporting.

**Rationale:** Mirrors the 3.32.1 rule and the user's explicit instruction. Auto-sync and auto-archive risk racing the user's review.

**Alternatives considered:**

- *Auto-sync and auto-archive on apply.* Rejected: explicitly forbidden.

## Risks / Trade-offs

- **Layer misidentified by reproduction** → Capture per-layer trace for both phrases; cite the specific code line(s) at fault in the diagnosis; require the trace to show the defect at the identified layer before the fix lands. If the fix does not correct the runtime behavior, the diagnosis is wrong and the trace is re-run.
- **CLI driver has its own defect independent of the recognizer/handler** → Reproduction MUST drive the CLI driver as a subprocess, not just the HTTP endpoint. The CLI stdout and order table are part of the captured evidence.
- **Real HTTP endpoint deserializes `cantidad` as `1` or strips a word from the message** → Reproduction MUST capture the raw HTTP request body sent by the CLI driver (or the test client) and the raw response body. The trace MUST include the message string that arrives at the orchestrator.
- **Existing 3.32.1 tests weakened by the fix** → The fix MUST be applied in the layer the reproduction reveals. Existing tests are not touched; new real-flow tests are added alongside.
- **Diagnosis is written after the reproduction, but the design is written before** → The diagnosis section of `design.md` is left as a placeholder until reproduction completes. The proposal and tasks reference the diagnosis step explicitly. The diagnosis is updated in-place after the reproduction, before the fix lands.
- **Defect spans multiple layers** → The per-layer trace identifies every layer that contributes to the defect. The fix addresses every contributing layer. The trace table makes the contribution visible.
- **Reproduce step requires a running local FastAPI app** → The new HTTP regression test uses `httpx.AsyncClient` with `app.dependency_overrides` (mirroring the pattern in `backend/tests/api_smoke.py`); it does not require a separate `uvicorn` process. The CLI regression test uses `subprocess.run` against the CLI driver script with a temporary `supernova_test`-seeded commerce.
- **Defect not reproducible against `supernova_test` but reproducible against `supernova`** → Both databases MUST be exercised in the reproduction step if the user reports the defect on `supernova`. The default reproduction is against `supernova_test`.
- **Atomic-quantity invariants drift between the orchestrator-level pipeline and the real pipeline** → The new real-flow tests assert the same invariants as the 3.32.1 unit tests (one `ProcessedIntent`, one `CustomerResponse`, destination quantity equals re-read source quantity, source unchanged on rejected). Drift is caught by the new tests.

## Migration Plan

No DB migration is required. The change is source-only: new test files, possibly a minimal correction in the layer the reproduction reveals, and the diagnosis section appended to `design.md`. The change is rolled out by deploying the corrected layer and the new regression tests. After rollout, the real CLI driver and the real HTTP endpoint produce the documented outcomes for both exact phrases.

Rollback is achieved by reverting the corrected layer and removing the new regression tests. After rollback, `modificar_producto` reverts to the current defective runtime behavior (the orchestrator-level tests still pass; the real CLI still reproduces both defects). No data needs to be migrated or backfilled.

The change remains active under `openspec/changes/fix-modificar-producto-real-flow-defects-3-32-2/` after `/opsx:apply` completes. `/opsx:sync` is manual; `/opsx:archive` is manual; the agent MUST NOT run either automatically.

## Open Questions

- Which layer is at fault for each defect? This question MUST be answered by the reproduction step, not assumed. The diagnosis is recorded in this design after reproduction.
- Does the CLI driver parse the message differently from the HTTP endpoint (e.g., strip a word, normalize case, default a missing field)? The reproduction step MUST drive both entry points and capture the message string that arrives at the orchestrator in each case.
- Does the HTTP endpoint accept the message verbatim, or does it lowercase, trim, or otherwise transform it before dispatch? The reproduction step MUST capture the raw HTTP request body.
- Is the recognizer's `_extract_quantity` correctly returning `None` for the exact Defect 1 phrase? The per-layer trace MUST include the recognizer's `cantidad` value.
- Is the handler's `_reread_source_cantidad` correctly invoked when the resolved `ProcessedIntent` arrives through the real pipeline (not through a hand-crafted fixture)? The per-layer trace MUST include the `cantidad` argument passed to `PedidoProductoService.modify_product`.
- Is the CLI driver re-printing the order table after each customer response, and does the table match the DB state? The CLI regression test asserts both.

These open questions are the questions the reproduction step MUST answer. The diagnosis is the answer.

## Diagnosis

This diagnosis was written after the reproduction step (Phase 2 / Phase 3 of
the task plan) and before the minimum correction (Phase 5).

### Layer identified at fault: LLM-based intent classifier prompt

The defect for both phrases lives in the LLM-based intent classifier prompt
in `backend/llm/intent_classifier.py`. The `_INTENT_CATALOG` constant
explicitly instructed the LLM to decompose any product-substitution request
into two separate intents (`quitar_producto` followed by `agregar_producto`)
instead of emitting a single `modificar_producto` intent. The prompt also
contained a worked example that reinforced this decomposition:

```python
* Si quiere sustituir o modifiar un producto por otro producto distinto,
  se deben generar dos intents, en este orden:
  1. `quitar_producto`, con el producto que desea retirar.
  2. `agregar_producto`, con el nuevo producto que desea incorporar.

Ejemplo:
Mensaje: `Cambiame la pizza de mozzarella por una napolitana`
Salida:
{
  "intents": [
    {"intent": "quitar_producto", "mensaje": "pizza de mozzarella"},
    {"intent": "agregar_producto", "mensaje": "pizza napolitana"}
  ],
  ...
}
```

### Why the prior 3.32.1 orchestrator-level tests passed

Every 3.32.1 unit and orchestrator-level test (atomicity-focused, end-to-end,
handler, initial-orchestrator, recognizer, response, transactional-regression,
response-orchestrator, dispatcher-integration) bypasses the LLM classifier
by patching `backend.intents.orchestration.initial_intent_dispatcher.
IntentClassifier` with a hand-crafted `_ModificarClassifier` that always
returns `IntentName.MODIFICAR_PRODUCTO`. The patched classifier feeds a
pre-built `ProcessedIntent` directly into `process_initial_modificar_producto`
and `execute_modificar_producto`, never exercising the seam between the
LLM-based dispatcher and the real entry points.

The recognizer, initial orchestrator, pending-context resolver, handler,
service, and response builder are all individually correct in isolation
when given a properly classified `modificar_producto` intent — that is what
the 3.32.1 tests prove. The defect is in the seam between the LLM-based
classifier and the rest of the pipeline: the LLM was instructed to decompose
substitution requests into separate quitar/agregar operations, which the
downstream pipeline correctly handled as two independent operations.

### Per-layer trace (pre-correction)

**Defect 1**: `cambia las empanadas de verdura por empanadas carne picante`
against a Pedido with `Empanada de Verdura x4`.

| Layer | Pre-correction evidence |
| --- | --- |
| Classifier (LLM) | Returned `[IntentName.QUITAR_PRODUCTO, IntentName.AGREGAR_PRODUCTO]` with `mensaje` split as `"empanadas de verdura"` and `"empanadas carne picante"`. |
| HTTP endpoint | Forwarded the raw message verbatim to the dispatcher. No transformation. |
| Initial dispatcher | Iterated over the two classified intents and produced two `ProcessedIntent` entries: `quitar_producto` (executed) and `agregar_producto` (executed). |
| Recognizer (quitar) | Found the source `Empanada de Verdura x4` line and called `PedidoProductoService.remove_product` with `cantidad == 4` (full source removal). |
| Service (quitar) | Removed the source line. |
| Recognizer (agregar) | Found the `Empanada de Carne Picante` product and called `PedidoProductoService.add_product` with `cantidad == 1` (the default single-unit quantity from the agregar recognizer, not the transferred source quantity). |
| Service (agregar) | Created the destination line with `cantidad == 1`. |
| Handler | Never invoked — the pipeline decomposed the modification into two independent intents before the `modificar_producto` handler could run. |
| Response builder | Built two separate `CustomerResponse` entries: `"Quité Empanada de Verdura ..."` and `"Listo, agregué 1 Empanada de Carne Picante ..."`. |

**Defect 2**: `cambia las 5 empanadas de jamon y queso por un caramelo`
against a Pedido with `Empanada de Jamón y Queso x5`, where `caramelo` is
absent from the catalog.

| Layer | Pre-correction evidence |
| --- | --- |
| Classifier (LLM) | Returned `[IntentName.QUITAR_PRODUCTO, IntentName.AGREGAR_PRODUCTO]` with `mensaje` split as `"5 empanadas de jamon y queso"` and `"un caramelo"`. |
| HTTP endpoint | Forwarded the raw message verbatim. |
| Initial dispatcher | Produced two `ProcessedIntent` entries. |
| Recognizer (quitar) | Found `Empanada de Jamón y Queso x5` and called `remove_product` with `cantidad == 5`. |
| Service (quitar) | Removed the source line (committed in the outer transaction). |
| Recognizer (agregar) | Could not match `caramelo` against the comercio catalog; produced a `pending_resolution` `ProcessedIntent`. |
| Handler | Never invoked. |
| Response builder | Built `"Quité Empanada de Jamón y Queso ..."` (executed) and `"No pude procesar tu pedido, ¿podrías reformularlo?"` (pending_resolution). |

The root cause for both defects is the same: the LLM classifier decomposed
the substitution request into two independent operations before the
`modificar_producto` pipeline could handle it atomically. The orchestrator-
level layers are not at fault; they are simply bypassed by the decomposed
intents.

### Minimum correction applied

**Layer corrected**: `backend/llm/intent_classifier.py` — the
`_INTENT_CATALOG` constant and the `_build_prompt` instructions.

**Change**: The catalog now lists `modificar_producto` as the intent for
product-substitution requests and explicitly instructs the LLM NOT to
decompose the request into `quitar_producto` + `agregar_producto`. The
worked example was updated to emit a single `modificar_producto` intent
with the full original message. The `_build_prompt` method was updated to
match.

**Before**:
```
* Si quiere sustituir o modifiar un producto por otro producto distinto,
  se deben generar dos intents, en este orden:
  1. `quitar_producto`, con el producto que desea retirar.
  2. `agregar_producto`, con el nuevo producto que desea incorporar.
```

**After**:
```
* Si quiere sustituir o modificar un producto por otro producto distinto,
  se debe generar un único intent `modificar_producto` con el mensaje
  original completo del cliente. NO se debe descomponer en
  `quitar_producto` + `agregar_producto`; el orquestador `modificar_producto`
  se encarga de la sustitución atómica en una sola operación.
```

**Secondary correction**: `backend/scripts/cli_chat_client.py` — the
`ORDER_MUTATING_INTENTS` set. The CLI driver only printed the order table
after `agregar_producto` or `quitar_producto` intents; `modificar_producto`
was missing from the set. With the corrected classifier now emitting a
single `modificar_producto` intent for substitution requests, the CLI
would never print the order table after a successful modification. The
set was extended to include `modificar_producto` so the CLI prints the
order table after every order-mutating intent, including the new
modification intent. The one CLI test that asserted `modificar_producto`
was not in `ORDER_MUTATING_INTENTS` was updated to use a truly
non-order-mutating intent (`consultar_producto`).

### Why no other layers were corrected

- **Recognizer** (`backend/intents/recognizers/modificar_producto_recognizer.py`):
  Returns `cantidad is None` for the omitted-quantity phrase and resolves
  source/destination candidates correctly when fed a proper
  `modificar_producto` intent. Verified by the 3.32.1 recognizer suite.
- **Initial orchestrator** (`backend/intents/orchestration/modificar_producto_initial.py`):
  Preserves the `cantidad is None` sentinel, emits `ready` only when both
  domains resolve uniquely, and rejects when either domain has zero
  candidates. Verified by the 3.32.1 initial-orchestrator suite.
- **Handler** (`backend/intents/handlers/modificar_producto_handler.py`):
  Re-reads the source quantity when `cantidad is None`, passes the re-read
  value to `PedidoProductoService.modify_product`, and never substitutes
  `1`. Verified by the 3.32.1 handler suite.
- **Service** (`backend/services/pedido_producto_service.py`): Runs all
  destination validations before any source mutation, reads `current_precio`
  before the source mutation, preserves the destination price snapshot,
  and consolidates in place. Verified by the 3.32.1 atomicity-focused suite.
- **Response builder** (`backend/intents/responses/modificar_producto_response.py`):
  Renders the deterministic message matrix for every rejection reason.
  Verified by the 3.32.1 response suite.
- **HTTP endpoint** (`backend/routers/incoming_messages.py`): Forwards the
  message verbatim to `process_incoming_message_with_responses`. No
  transformation.
- **Pending-context resolver** (`backend/intents/context/product_modification_resolver.py`):
  Preserves the omitted-quantity sentinel across turns and clears the
  pending context on `executed` / `rejected`. Verified by the 3.32.1
  end-to-end and pending-context suites.

### Coverage gap in the 3.32.1 orchestrator-level tests

The 3.32.1 orchestrator-level tests have a single coverage gap: they do
not drive the real `POST /comercios/{id}/clientes/{id}/incoming-messages`
endpoint or the interactive CLI driver. They patch the LLM-based
classifier with hand-crafted stubs that always return
`IntentName.MODIFICAR_PRODUCTO`, so the classifier seam is never
exercised. The new real-flow regression tests
(`backend/tests/test_modificar_producto_real_flow_http.py` and
`backend/tests/test_modificar_producto_real_flow_cli.py`) close this gap
by driving the exact two reproduction phrases through the real HTTP
endpoint and the interactive CLI driver against `supernova_test`.

### Before/after evidence

**Before the correction** (driving the exact phrases through the real HTTP
endpoint against `supernova_test`):

- Defect 1: response contained two `CustomerResponse` entries
  (`quitar_producto` executed + `agregar_producto` executed); source line
  removed; destination line created with `cantidad == 1` (not `4`).
- Defect 2: response contained two `CustomerResponse` entries
  (`quitar_producto` executed + `agregar_producto` pending_resolution);
  source line removed; no destination line; message
  `"No pude procesar tu pedido, ¿podrías reformularlo?"`.

**After the correction** (same endpoint, same seed data):

- Defect 1: response contained exactly one `CustomerResponse` with
  `intent == "modificar_producto"`, `status == "executed"`, and message
  `"Cambié 4 Empanada de Verdura ... por 4 Empanada de Carne Picante ..."`;
  source line removed; destination line created with `cantidad == 4`.
- Defect 2: response contained exactly one `CustomerResponse` with
  `intent == "modificar_producto"`, `status == "rejected"`, and message
  `"No encontré el producto de reemplazo. Tu pedido no fue modificado."`;
  source line preserved with `cantidad == 5`; no destination line;
  `Session.context_type` cleared to `None`.

The CLI driver (after the secondary correction to `ORDER_MUTATING_INTENTS`)
prints the order table after the successful modification, confirming the
destination line with `cantidad == 4` and no source line.

