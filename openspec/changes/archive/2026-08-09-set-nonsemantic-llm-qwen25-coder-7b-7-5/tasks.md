## 1. Design completion and approval

- [x] 1.1 Confirm that the change is limited to the existing non-semantic
  `QueryLlm` path and that semantic recognition/embeddings remain untouched.
- [x] 1.2 Confirm the exact model identifier `qwen2.5-coder:7b-ctx8192` and
  context default `8192`.

## 2. Source and contract

- [x] 2.1 Change the `LLM_MODEL` local default in `backend/config/settings.py`
  without weakening environment-override precedence.
- [x] 2.2 Preserve the `LLM_NUM_CTX=8192` default and existing QueryLlm payload
  contract.
- [x] 2.3 Update only the relevant LLM settings/query-client OpenSpec deltas.

## 3. Verification

- [x] 3.1 Add focused mocked tests for the exact default model/context and
  override precedence; do not call Ollama.
- [x] 3.2 Run each exact validation command from `proposal.md` locally and
  report its complete output.

## 4. Operational boundary

- [x] 4.1 Do not pull a model, alter Railway environment variables, deploy,
  send Twilio messages, sync or archive as part of this change.
