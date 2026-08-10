# Design: deterministic social conversation responses

## Authoritative outcomes

| Classifier intent with no pending context | Processed status | Persisted effect | Customer response purpose |
| --- | --- | --- | --- |
| `saludo` | `executed` | None | Welcome and invite an order or question |
| `agradecimiento` | `executed` | None | Acknowledge and offer continued help |
| `despedida` | `executed` | None | Brief courteous closing |
| `respuesta_afirmativa` | `executed` | None | Explain that no active question needs confirmation; invite a concrete request |
| `respuesta_negativa` | `executed` | None | Acknowledge and invite a concrete request |
| `desconocida` | `executed` | None | Ask for a simple reformulation with order/menu examples |
| Any other unimplemented classifier intent | `rejected` | None | Existing `GENERIC_MESSAGE` fallback |
| Technical classifier/mapper/outbox failure | exception propagates | Outer transaction decides rollback | No social fallback response |

The wording is fixed Spanish text, intentionally brief, and must not claim a catalog item, payment/delivery option, order state, or completed action. It must not mention the raw classified source text.

## Execution design

1. `process_incoming_message` keeps its current pending-context priority unchanged. If `session.context_type` is non-null, only `dispatch_pending_context` handles the message.
2. With no pending context, `dispatch_initial_message` receives the classifier result and recognizes the six social names explicitly.
3. For each, it returns a `ProcessedIntent` with the classifier intent/source, `executed` status, `intent_classifier` recognizer, and a social-response handler marker. It does not call an order recognizer, handler, repository, or database method.
4. `build_customer_responses` dispatches those six intent names to one pure social-response builder. The builder selects from a fixed mapping and returns `CustomerResponse` preserving the processed intent/status.
5. The local response orchestration and provider coordinator continue to use the same mapper, so their visible response and staged outbox row remain identical and ordered.

## Preserved boundaries

The dispatcher continues to leave a non-null `context_type` untouched; a pending product selection, payment, delivery, or confirmation owns affirmative/negative wording. The mapper remains the sole rendering boundary for both local and provider traffic. The existing generic mapper fallback stays in place for every intent outside this narrowly approved set, preventing this change from silently introducing behavior for the later informational or mutation roadmap.

## Focused tests

Unit tests shall cover each social classifier intent: no business orchestrator/repository call, `executed` non-mutating processed result, preservation of classifier ordering when mixed with existing intents, and unchanged pending-context short circuit. Mapper tests shall cover the exact fixed response selected for each social intent, the retained generic fallback for an unimplemented intent, and response ordering. An existing local/provider-equivalent response orchestration test shall prove social output follows the common mapper/outbox boundary rather than a parallel reply path.
