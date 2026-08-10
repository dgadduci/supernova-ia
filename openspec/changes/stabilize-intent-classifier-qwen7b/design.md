# Design: stabilize intent classification for Qwen 7B

## Authoritative outcomes

| Situation | Required outcome | Must not happen |
| --- | --- | --- |
| Curated audit fixture | exactly the approved intent sequence and preserved source fragment | unrelated product, address, payment, or delivery intents |
| Runtime classified turn | one validated result plus safe diagnostic correlation evidence | raw prompt/message or credentials in logs/durable state |
| LLM transport/parse failure | existing typed technical failure and transaction rollback/retry behavior | generic business success or partial mutation |
| Ambiguous business message | existing valid dispatcher behavior | new heuristic that changes pending candidates or transaction ownership |

## Diagnostic design

1. Define a versioned, curated intent corpus. Each case specifies its input,
   expected ordered intents, and expected source fragments. It includes all
   existing intent names and the production failures for payment and
   observations.
2. Provide an explicitly invoked diagnostic runner that calls the same
   `IntentClassifier`/`QueryLlm` path as production. Because fixture inputs are
   controlled, its report may include the exact rendered prompt and parsed LLM
   response; it never reads a database, sends a provider message, or changes
   application state.
3. The runner reports effective non-secret settings: model identifier, context
   length, output limit, temperature, keep-alive, prompt-template version, and
   a prompt fingerprint. It must not print endpoint credentials, proxy values,
   account IDs, tokens, or environment dumps.
4. Runtime diagnostics record only the prompt-template version/fingerprint,
   effective model, response validation category, classified intent names and
   count, and a correlation identifier. They must not persist or log the raw
   message, full prompt, or raw LLM response.
5. Use the audit evidence to compare the current Qwen 7B behavior against the
   prompt's assumptions. If a prompt change is needed, make it minimal and
   encode the approved output contract: preserve the message text, emit only
   intents grounded in that message, and avoid decomposing a single-intent
   payment/observation message into unrelated actions.

## Prompt compatibility criteria

The proposal does not assume that Qwen 7B behaves identically to Qwen 27B.
Before changing instructions, the diagnostic report must establish the actual
prompt sent, current effective model, and output for each corpus case. The
implementation may simplify wording, strengthen output constraints, or add
targeted few-shot examples only where the audit demonstrates value. It must not
add a second classifier or a parallel recognition pipeline.

## Failure and transaction design

Prompt rendering and diagnostic capture are pure relative to business state.
`QueryLlm` remains the sole transport owner; `IntentClassifier` validates the
single response once. Diagnostic failures must not cause a second LLM request
or mask the original exception. The existing outer local/deferred transaction
owns every rollback and commit.

## Focused tests

- Prompt template/version and request payload are deterministic for each
  fixture under a stub transport.
- The audit runner emits exact fixture prompts/responses only for its controlled
  corpus and never initializes database or provider clients.
- Runtime diagnostic records are redacted and contain no raw message/prompt,
  response body, URL, proxy, token, or account identifier.
- Payment and observation regression cases assert exactly one intended intent.
- Existing malformed-response, timeout, validation, order-preservation, and
  no-double-classification contracts remain unchanged.
