# Design: confirmation-time order observation

## Decision

Remove product-line observations and replace them with a single bounded
confirmation context. The feature uses the existing `Pedido.observaciones`
field and existing incoming-message transaction owner; it does not introduce a
second message pipeline, an LLM mutation decision, a migration or a line-level
fallback.

```text
classified explicit confirmar_pedido
  -> validate existing closure prerequisites
  -> pending `order_confirmation_observation`
  -> fixed prompt

next inbound message (before classifier)
  -> exact normalized `no`: final revalidation -> confirm
  -> valid opaque text: normalize -> final revalidation -> set Pedido note -> confirm
  -> empty / >500: preserve pending -> retry prompt
```

The application cannot know when a customer has finished product selection.
Therefore it shall not proactively prompt after an add/remove/change turn;
only the explicit confirmation intent starts this flow.

## Pending contract

The pending `ProcessedIntent` remains `intent="confirmar_pedido"` and
`handler="confirmar_pedido"`, has no candidates and one pending
`observacion_pedido` requirement. `ContextType.ORDER_CONFIRMATION_OBSERVATION`
routs it to a new narrow resolver. The resolver consumes one reply without
calling initial classification:

- normalized exact `no` makes the requirement completed with no observation
  value;
- a valid 1–500 character normalized reply makes it completed without placing
  the raw text in diagnostics-oriented metadata; the finalizer receives it
  only through the in-memory pending intent contract;
- empty or over-limit text returns the same pending intent with a documented
  validation reason and no mutation.

No yes/no grammar beyond exact `no` is required. A customer who writes `sí`
will have `sí` saved as the requested free-text observation; the prompt tells
them to write the note directly. This avoids an unnecessary third turn and
keeps raw text treatment deterministic.

## Final mutation boundary

The initial confirmation turn validates prerequisites but does not mutate the
Pedido. The finalizer re-loads and revalidates the active session's own
Pedido, `borrador` state, non-empty lines, active payment and delivery before
staging changes. For `no` it stages only `estado_pedido=ingresado`; for text it
first stages the normalized `Pedido.observaciones` replacement and then the
same transition. No partial accepted observation may remain if final
confirmation is rejected or the outer transaction fails.

Neither the resolver nor finalizer calls transaction-control methods. The
existing outer inbound transaction owns the single commit/rollback.

## Removing old paths safely

The following runtime feature paths are removed: product-observation prompt
guidance/corpus examples, dispatcher import and branch, line recognizer,
orchestrator, handler, response builder, mapper branch, line selection context
special case, ready pending handler branch, service/repository write seam and
line-observation panel display. Any files that no longer have a caller are
deleted with their focused tests.

The `IntentName` values are retained temporarily to parse old classifier
payloads. The dispatcher returns a deterministic non-mutating guidance outcome
for either direct observation intent outside the confirmation context. It does
not call the legacy general-observation routine. A persisted active pending
intent whose handler is `set_observacion_producto` is invalid after deployment:
on its next message the pending dispatcher clears it and returns one rejected
guidance outcome, never invoking the old handler.

Existing `PedidoProducto.observaciones` rows remain unchanged and are not
rendered by the active pilot panel. This change makes no schema or data
mutation beyond normal confirmation-time `Pedido` writes.

## Responses, privacy and errors

The pending response is the fixed capture question. An invalid capture reply
returns a fixed retry prompt. Both `no` and valid text receive the existing
successful order-confirmation response; neither echoes the note. Direct
observation attempts receive a fixed instruction to confirm the order first.

Existing inbound message storage remains unchanged. New diagnostics use only
intent, status, context kind and candidate count; they add no raw observation
content, customer message, IDs or pending JSON. Technical exceptions propagate
to the current transaction owner; they are not converted into an executed
response.

## Tests

Focused tests must cover: initial valid-confirmation prompt; prerequisite
rejections without pending; `no` confirmation preserving prior note; free-text
capture replacing the order note and confirming; whitespace and 501-character
retry without mutation; final ownership/state/prerequisite revalidation;
transaction non-ownership and technical rollback; resolver bypass of
classifier/LLM/product/catalog/line access; direct observation intent
rejection; stale product-line pending safe clear; response privacy; mapper
routing; and panel removal of line observation display while keeping the
order-level note visible.
