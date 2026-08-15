# Design: product-line observation intent

## Decision

Implement one thin path parallel to `quitar_producto`, not a second product
pipeline:

```text
classifier intent only
  -> current-draft order-line recognizer
  -> unique: ready handler / multiple: existing order_line_selection
  -> service validates active session + own borrador + line membership
  -> caller-owned transaction commits
  -> deterministic response mapper
```

The existing fuzzy recognizer is only a candidate producer. It sees a catalog
built from `PedidoProductoService.list_by_pedido(session.id_pedido)` and emits
`PedidoProducto.id` candidates. It never reads the commerce catalog. A ready
handler validates the id again immediately before assignment, so neither a
classifier response nor stale candidate state can authorize a write.

## Classifier calibration amendment

The observed failure occurs before this path: the classifier selected
`agregar_producto` for `La pizza de mozzarella chica es sin aceitunas`, so the
order-line recognizer never ran. Amend only the existing static classifier
prompt and controlled corpus. They SHALL distinguish:

- a declarative product-specific instruction without an add verb → exactly one
  `set_observacion_producto`, preserving the literal message;
- an explicit request to add a product, even if it contains a condition → the
  existing `agregar_producto` path.

The classifier does not read current order lines. No post-classification
rewrite is allowed, so an existing line never turns an explicit add request
into an observation update. Prompt wording and corpus examples are LLM
guidance, not mutation authority; the existing own-draft recognizer and
handler remain the write boundary.

## Identity recovery amendment for declarative observations

The classifier amendment deliberately preserves the full literal message, and
that full text is also the observation value to store. It must not be split on
Spanish grammar: declarative forms are open-ended and future observation
phrasing cannot be captured by an allowlist of verbs or separators.

The existing order-line fuzzy recognizer remains the primary, bounded candidate
producer. Only if it produces zero candidates for an already-classified
`set_observacion_producto` turn, the observation recognizer may run a narrow
deterministic identity-evidence recovery against the *same active draft line
catalog*. It compares normalized full-token evidence from the raw message with
the candidate line's already-projected category, product, presentation and
existing aliases. It does not extract a substring, remove a condition, or
classify wording.

```text
"La pizza de mozzarella chica es sin aceitunas"
  -> classifier: set_observacion_producto, original message unchanged
  -> existing own-line fuzzy: zero candidates
  -> bounded identity evidence: Pizza + Mozzarella + Chica matches #82 only
  -> ready handler stores the full original message on #82
```

The identity-recovery result is fed into the existing unique/pending/rejected
path. One candidate may execute; more than one remains an
`order_line_selection` pending context; zero remains rejected. It cannot use a
commerce catalog, foreign order, recent line, LLM reference extraction, or
grammatical guess. This is a candidate-recovery refinement within the existing
recognizer path, not a parallel mutation pipeline.

## Intent data

The initial orchestrator creates a `ProcessedIntent` with
`intent=handler="set_observacion_producto"` and these fields:

- `resolved_data["observation_action"]`: `"set"` or `"clear"`, derived
  locally from the explicit grammar.
- `resolved_data["observation_text"]`: the trimmed original classified
  message only for `set`; absent for `clear`.
- `resolved_data["pedido_producto_id"]`: present only in `ready` state.
- `candidate_ids`: only unresolved `PedidoProducto.id` values in
  `pending_resolution` state.
- requirements: `pedido_producto_id` is completed only in ready state;
  `observacion` is completed for both locally determined actions.

The stored value is exactly `observation_text.strip()` for `set`; it is `NULL`
for `clear`. The implementation SHALL reject missing/empty text rather than
turning it into a clear. It SHALL not ask the LLM to extract a product name,
rewrite an observation, decide whether it means delete, or choose among lines.

## Ownership and transaction boundary

The handler rejects before calling the service unless the supplied conversation
session has a positive id, is `EstadoSession.ACTIVA`, and has `id_pedido`.
The new service method receives session id, pedido id, line id and nullable
observation. Before mutation it validates, in this order: Pedido exists;
`Pedido.id_session` equals the supplied session id; Pedido is `BORRADOR`; the
line exists and belongs to that Pedido. It returns a deterministic business
rejection/value for invalid ownership or state, and assigns only
`PedidoProducto.observaciones` for a valid row.

The repository performs the lookup/assignment only. Neither it nor the new
service calls `commit`, `rollback`, `flush`, `refresh`, `begin`, `close`, or
creates a transaction. This intentionally bypasses legacy `update`, which has
incompatible transaction ownership and no `NULL`-write semantics. The outer
transactional message processor remains the only commit/rollback owner.

## Ambiguity

For two or more initial candidates, reuse `ContextType.ORDER_LINE_SELECTION`.
The context resolver recognizes this intent as an order-line selection.
`resolve_order_line_selection` already intersects recognized reply ids with
the active `candidate_ids`; its ready construction preserves unrelated
`resolved_data`, so the action/text survive without reclassification. A reply
that does not match retains pending state; a reply outside the restricted set
is rejected. It must never rediscover candidates from the commerce catalog or
replace the original observation with the clarification text.

`execute_ready_pending_context` adds one handler branch. As for other
non-queued order-line actions, a definitive executed or rejected result clears
the active context; `failed` remains active and propagates to outer rollback.

## Responses and privacy

The mapper adds one explicit branch. The response builder reuses only order
line labels loaded from the active Pedido for a clarification. It emits fixed
Spanish messages in the following shape:

- pending: `¿Cuál querés modificar: <producto> (<presentación>) o ...?`
- executed set: `Actualicé la aclaración de <producto> (<presentación>).`
- executed clear: `Eliminé la aclaración de <producto> (<presentación>).`
- rejected: `Ese producto no está en tu pedido.`
- failed: existing generic retry wording.

Neither API/outbox response nor diagnostics repeats observation text, database
identifiers, candidate ids, session ids, raw prompt data, or LLM output.

## Tests

Focused tests prove: direct unique set; explicit clear to `NULL`; no draft,
inactive session, foreign Pedido/line and non-borrador rejections; exact raw
text preservation; ambiguous initial candidates; intersection-only refinement
with action/text preservation; foreign clarification rejection; no commerce
catalog access; service/handler transaction non-ownership; mapper routing and
no observation disclosure; full transactional rollback on a technical error.
Existing `quitar_producto`, `modificar_producto`, and `agregar_producto`
regressions remain the compatibility coverage; no migration test is needed.

The amendment adds focused static prompt/corpus tests and controlled classifier
payload tests for the declarative sentence, plus an existing-dispatcher routing
assertion. Those tests do not claim to prove live LLM behavior; the post-deploy
gate proves the actual classification and resulting line update. Tests also
pin that an explicit `quiero una ... sin aceitunas` request remains add,
without implementing combined add-with-observation.

The identity-recovery amendment adds focused tests with an active own-line
catalog containing Mozzarella Grande and Mozzarella Chica. A complete
declarative message with a condition must select only Chica and preserve its
full raw text; a second product/condition proves the behavior is not a
literal-pizza special case. Tests also prove that missing evidence remains
rejected and shared identity remains pending without candidate widening. No
test claims support for imperative `poné`/`agregale`/`sacale` phrasing; that is
separate product semantics work.
