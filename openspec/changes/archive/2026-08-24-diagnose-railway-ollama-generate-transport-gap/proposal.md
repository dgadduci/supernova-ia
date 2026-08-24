# Diagnose intermittent Railway–Ollama generate transport failures

## Objective

Identify where an intermittent `QueryLlm` request is lost or stalled between
the Railway `supernova-ia` process and the local Ollama `/api/generate`
endpoint, without changing worker, classifier, timeout, retry, model, proxy,
or business behavior.

## Current execution path

`provider worker → coordinator → IntentClassifier → QueryLlm.request() →
requests.post → socks5h://127.0.0.1:1055 → userspace Tailscale →
100.113.65.40:11434/api/generate → local Ollama`.

The deployed transport-phase evidence distinguishes the boundary reached by
the client. In the latest three-call run, attempts 1 and 2 completed all
phases and returned HTTP 200; attempt 3 emitted only `request_started` and
timed out after 20 seconds. The supplied Ollama log contains the first two
requests but no third request. A prior run also showed the opposite symptom:
Ollama logged HTTP 200 while Railway timed out waiting for the response.

## Scope

- Add or extend one operator-run, sanitized diagnostic for the existing
  configured `/api/generate` route through the existing loopback SOCKS proxy.
- Measure connection result, HTTP status, elapsed time, and response-byte
  receipt without printing the controlled prompt or generated response.
- Preserve the existing `llm_request_transport_phase` evidence and provide a
  short runbook for correlating one attempt with Ollama's access log.
- Add focused tests for the diagnostic's success, timeout, connection-error,
  non-2xx, and empty-response classifications.

## Non-goals

- No changes to `QueryLlm`, `IntentClassifier`, coordinator, worker, outbox,
  Twilio, Ollama model/prompt, application timeout, retries, fallback, or
  proxy scope.
- No automatic retry, replay, timeout increase, direct/public Ollama route,
  alternate proxy, Tailscale ACL change, firewall change, or MSS/MTU change.
- No production behavior change and no business-message processing.

## Decision boundary

The diagnostic must distinguish:

| Evidence | Interpretation |
| --- | --- |
| Railway request never reaches Ollama | forward path, proxy, Tailscale, ACL, or endpoint reachability issue |
| Ollama records 200 but Railway receives zero bytes | response return path or SOCKS relay issue |
| Railway receives non-2xx | endpoint/service error; retain existing client behavior |
| Railway receives bytes and a complete valid response | transport succeeds for that attempt; continue correlating intermittent attempts |

No infrastructure correction is authorized by this diagnostic change. A
separate approved change is required after the evidence identifies a causal
configuration fault.

## Observability and privacy

Output may contain only target kind, connection/result category, HTTP status,
elapsed time, and received-byte count. It must not contain prompts, generated
text, URLs, proxy values, credentials, headers, customer/order data, raw
Tailscale status, or exception text/tracebacks.

## Expected files

- `backend/scripts/check_railway_ollama_contracts.py` or one narrowly scoped
  diagnostic module reused by that CLI.
- Focused diagnostic tests.
- `backend/development/railway.md` only for the operator command and safe
  correlation procedure.

## Rollback and deferred limitations

The change is reversible by removing the diagnostic-only code and documentation;
it does not alter deployment configuration or runtime business behavior. It
does not prove a root cause by itself and does not correct the Railway–Tailscale–
Ollama transport path.
