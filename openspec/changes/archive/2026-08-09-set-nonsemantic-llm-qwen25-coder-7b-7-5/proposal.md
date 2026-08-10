## Why

The inbound Twilio pilot will exercise the existing intent-classification path.
The configured non-semantic LLM default is currently `qwen-27b-coding:latest`,
which consumes more hardware than the controlled pilot needs.  The approved
operational choice is Ollama model `qwen2.5-coder:7b-ctx8192`, with an 8,192
token context, for every current non-semantic LLM request.

Changing the model after the Twilio end-to-end run would mix model behaviour
with webhook, queue and outbound behaviour.  This change establishes the
model boundary first, without changing semantic product recognition.

## Objective

Make `qwen2.5-coder:7b-ctx8192` and `LLM_NUM_CTX=8192` the documented local
defaults for the synchronous non-semantic `QueryLlm` path used by
`IntentClassifier`, while preserving explicit environment overrides and all
semantic-recognition/embedding configuration.

## Current execution path

`incoming message -> InitialIntentDispatcher -> IntentClassifier -> QueryLlm
-> Ollama /api/generate`.

`QueryLlm` reads `Settings.llm_model` and `Settings.llm_num_ctx` and sends
them in its request payload.  The current source defaults are
`qwen-27b-coding:latest` and `8192`.  Product semantic recognition uses its
own fuzzy/hybrid/vector settings and the separate embedding client; it does
not consume `QueryLlm` settings.

## Scope

- Change the documented/default `LLM_MODEL` value to
  `qwen2.5-coder:7b-ctx8192`.
- Retain and explicitly test the `8192` default for `LLM_NUM_CTX`.
- Prove `QueryLlm` emits that default model and context in its mocked Ollama
  payload, and that explicit `LLM_MODEL` / `LLM_NUM_CTX` overrides still win.
- Add OpenSpec deltas for the LLM settings/query-client contract.

## Non-goals

- No product recognizer, embedding model, embedding endpoint, fuzzy/hybrid
  policy, candidate selection or semantic-recognition change.
- No prompt, intent schema, temperature, output format, timeout, retry,
  `LLM_NUM_PREDICT`, pipeline, webhook, queue, outbox or Twilio change.
- No live Ollama request, model pull, Railway configuration/deployment, or
  end-to-end Twilio execution.
- No new model-routing abstraction: `QueryLlm` is the sole current
  non-semantic LLM client and retains its existing settings contract.

## Shared boundary, fallback and observability

`Settings` remains authoritative.  If `LLM_MODEL` or `LLM_NUM_CTX` is set in
the environment, that explicit value wins; otherwise the new defaults apply.
There is no automatic model fallback or silent switch.  Existing `QueryLlm`
INFO logging continues to expose only the configured model and request timing,
never prompts, bodies or credentials.

An existing deployment-level `LLM_MODEL` override will continue to take
precedence over this source default.  Updating such an override is an
explicit, separately authorized deployment action after code review and local
validation.

## Transaction ownership and reversibility

This change is configuration-only and owns no database transaction.  It adds
no migration or durable state.  Rollback is restoring the prior source default
or explicitly setting `LLM_MODEL` to the previous model; semantic-recognition
settings remain untouched.

## Expected files

- `backend/config/settings.py`
- `backend/tests/test_llm_settings.py`
- `backend/tests/test_query_llm.py`
- `backend/tests/api_smoke.py` only if its settings-default assertions require
  adjustment
- this OpenSpec change and deltas for `llm-settings` and `llm-query-client`

## Focused tests and validation

The implementer shall prove, without a live LLM request, that defaults yield
the exact model `qwen2.5-coder:7b-ctx8192` and `num_ctx=8192`, explicit
environment overrides remain authoritative, and the payload preserves the
existing JSON/temperature contract.

The user runs locally:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_llm_settings.py backend/tests/test_query_llm.py backend/tests/test_intent_classifier.py
PYTHONPATH=. venv/bin/python -m ruff check backend/config/settings.py backend/llm/query_llm.py backend/tests/test_llm_settings.py backend/tests/test_query_llm.py backend/tests/test_intent_classifier.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/llm/query_llm.py backend/tests/test_llm_settings.py backend/tests/test_query_llm.py backend/tests/test_intent_classifier.py
openspec validate set-nonsemantic-llm-qwen25-coder-7b-7-5 --strict
git diff --check
```

## Deferred limitations

The controlled semantic-recognition rollout retains its existing independent
configuration.  Live accuracy/latency evaluation of the 7B model, any Railway
environment update, and Twilio end-to-end testing occur only after this change
is implemented, reviewed and explicitly deployed.
