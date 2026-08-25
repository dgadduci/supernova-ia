# Proposal: reversible HTTPX QueryLlm transport experiment

## Objective

Determine whether HTTPX, using the same configured Ollama endpoint and SOCKS5
proxy, avoids the observed Requests stall before response headers. The existing
Requests transport remains the production default and the experiment is enabled
only by an explicit Test-environment setting.

## Current path and evidence

`QueryLlm.request()` emits `request_started`, then `_post()` uses
`requests.post(..., stream=True)` through the optional `OLLAMA_PROXY_URL`.
For the reproduced failure, Railway recorded `request_started` at
17:38:07 UTC followed by `QueryLlmTimeoutError` 180 seconds later, with no
`response_headers_received`. The matching Ollama journal contains no request
at that time. This locates the stall before the Ollama HTTP handler, but does
not establish whether Requests, the loopback SOCKS proxy, or the tunnel is the
root cause.

## Scope

- Add a closed `LLM_HTTP_CLIENT` setting with `requests` (default) and `httpx`.
- When explicitly set to `httpx`, issue the existing one `/api/generate`
  request using synchronous HTTPX, its streaming response API, the unchanged
  JSON payload, URL, SOCKS5/SOCKS5H proxy, and total timeout.
- Add the smallest SOCKS support dependency required by HTTPX (`socksio`).
- Preserve the existing transport-phase events, timing recorder, result shape,
  error boundary, privacy contract, transaction ownership, and single-request
  behavior.
- Test both selected transports with the same supported injected test seam.
- Operate only in Railway Test: deploy with default `requests`, set
  `LLM_HTTP_CLIENT=httpx` for the controlled experiment, correlate the same
  safe events, then unset the setting to revert without a code rollback.

## Non-goals

- No automatic fallback from HTTPX to Requests, retry, duplicate LLM request,
  timeout change, async client, pooling redesign, HTTP/2, proxy/Tailscale
  modification, Ollama change, worker/outbox/session/database/schema change,
  migration, endpoint, or production activation.
- No prompt/body/chunk/URL/proxy/header/credential/customer data or raw
  exception is logged.

## Authoritative outcomes

| Setting / result | Required behavior |
| --- | --- |
| unset or `requests` | Current Requests path is used unchanged. |
| `httpx` and complete response | Existing successful parse/result behavior. |
| `httpx` timeout / connection / HTTP / invalid response | Existing corresponding `QueryLlm*Error`; no fallback or second call. |
| other setting value | Settings loading fails safely before a request. |

## Rollback

The runtime rollback is removing `LLM_HTTP_CLIENT` (or setting it to
`requests`) and redeploying/restarting Test. Because `requests` is the
default, the committed code is inert until opted in. Reverting the experiment
commit also removes HTTPX selection and `socksio` if the experiment is
abandoned.

## Expected files

- `requirements.txt`
- `backend/config/settings.py`
- `backend/llm/query_llm.py`
- `backend/tests/test_llm_settings.py`
- `backend/tests/test_query_llm.py`
- `backend/development/railway.md`
- this OpenSpec delta

## Focused validation

- `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_llm_settings.py backend/tests/test_query_llm.py -q`
- `PYTHONPATH=. venv/bin/ruff check backend/config/settings.py backend/llm/query_llm.py backend/tests/test_llm_settings.py backend/tests/test_query_llm.py`
- `PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/llm/query_llm.py`
- `openspec validate experiment-httpx-query-llm-transport --strict`
- `git diff --check`

The user runs every `venv/bin/python` validation locally and provides the
complete output. No commit, sync, archive, deploy or configuration change is
authorized by this proposal.

## Deferred limits

This experiment compares clients; it does not prove or repair the underlying
network path. A successful Test run needs repeated controlled turns and the
same Railway/Ollama evidence before any durable transport decision.
