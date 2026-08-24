# Tasks: diagnose the QueryLlm response transport gap

## 1. Contract

- [x] 1.1 Inspect the existing `llm_request` event contract and choose whether
  the closed phases fit it or require one narrowly scoped companion event.
- [x] 1.2 Add closed phase and bounded metadata validation without accepting
  prompts, responses, URLs, proxy values, secrets or arbitrary text.

## 2. QueryLlm instrumentation

- [x] 2.1 Emit the request-start phase immediately before the existing `_post`.
- [x] 2.2 Emit the response-received phase only after `_post` returns.
- [x] 2.3 Emit the JSON-extracted phase after existing response extraction.
- [x] 2.4 Emit the result-parsed phase after existing `_parse` succeeds.
- [x] 2.5 Preserve all current timeout, connection, HTTP, parsing and fallback
  behavior.

## 3. Focused tests

- [x] 3.1 Test successful phase ordering and bounded metadata.
- [x] 3.2 Test timeout before response receipt and absence of false phases.
- [x] 3.3 Test HTTP, malformed-response and empty-response behavior remains
  unchanged.
- [x] 3.4 Test correlation and privacy validation.
- [x] 3.5 Test observability emission failure does not affect QueryLlm.

## 4. Validation and handoff

- [x] 4.1 Run focused pytest. *(311 passed, 0 failed in 1.31s)*
- [x] 4.2 Run Ruff on touched files. *(1 pre-existing C408 in test_query_llm.py:26; 0 new findings)*
- [x] 4.3 Run compileall on touched files. *(no output — success)*
- [x] 4.4 Run strict OpenSpec validation and `git diff --check`. *(both passed)*
- [x] 4.5 Report exact phase interpretation and unresolved proxy limitations.
- [x] 4.6 Do not run sync, archive, commit, push, PR or deploy.
