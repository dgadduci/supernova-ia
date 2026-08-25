# Tasks: incremental QueryLlm body receipt diagnosis

## 1. Closed observation contract

- [x] 1.1 Add bounded header, first-chunk and completed-body phase validation.
- [x] 1.2 Keep all existing transport phase contracts valid and private.
- [x] 1.3 Reintroduce the historical `response_received` token as a
  closed vocabulary entry, emitted after `body_completed` in the
  successful streaming flow to preserve the previous non-streaming
  semantics while the parser continues to accept historical
  `response_received` lines.

## 2. Existing client seam

- [x] 2.1 Request HTTP streaming while retaining Ollama `stream: false`.
- [x] 2.2 Consume/close one response and preserve current parsing/errors.
- [x] 2.3 Emit only reached phases; no recovery or second request.
- [x] 2.4 Centralize the Requests exception classification the initial
  `requests.post` and the streaming `iter_content` reading use so a
  `Timeout` keeps `QueryLlmTimeoutError` and a `ConnectionError`
  (including the `ChunkedEncodingError` shape Requests uses for a
  read-timeout during streaming) keeps `QueryLlmConnectionError`.
- [x] 2.5 Preserve the previous `response.json()` envelope semantics:
  JSON-dict envelope → extract `response`; valid JSON non-dict
  envelope (`[]`, `null`, number, string) → empty body that
  `_parse` rejects with `QueryLlmResponseError`; non-JSON envelope →
  fall back to the raw envelope text and the previous `_parse`
  recovery.

## 3. Tests and operation

- [x] 3.1 Cover headers, partial body, complete body, close semantics and
  privacy.
- [x] 3.2 Run the focused local checks from `proposal.md` and report
  complete output.
- [ ] 3.3 Deploy only to test, correlate one controlled failure, then
  decide the separate root-cause fix.
- [x] 3.4 Do not commit, sync, archive, push or alter production.