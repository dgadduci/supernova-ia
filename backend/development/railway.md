# Railway deployment runbook

## Scope

The Railway web service runs FastAPI and a colocated, userspace Tailscale
daemon. Only the existing Ollama generate and embedding HTTP calls use the
loopback proxy. PostgreSQL migrations, Twilio, `/health`, and all other
outbound clients remain direct.

## Required Railway and Tailscale setup

1. Keep `SUPERNOVA_DATABASE_URL` as a Railway reference to PostgreSQL's
   `DATABASE_URL`; never copy its resolved value into the repository or logs.
2. Configure Twilio only with Railway variables and public HTTPS URLs:

   - `TWILIO_AUTH_TOKEN` and `TWILIO_WEBHOOK_BASE_URL` are required before
     enabling inbound webhook validation.
   - `TWILIO_WEBHOOK_BASE_URL` identifies the public HTTPS base used to build
     the inbound webhook URL.
   - `TWILIO_ACCOUNT_SID`, `TWILIO_OUTBOUND_SENDER_E164`,
     `TWILIO_CALLBACK_STATUS_URL`, and the existing retry settings are needed
     only before an explicit outbound-dispatch pass.
   - Configure Twilio's inbound URL and status-callback URL to the matching
     existing public routes; never place credentials, signatures, or signed
     payloads in this runbook, Railway logs, or repository files.
3. The outbound dispatcher remains the existing bounded manual CLI. Do not add
   a Railway cron, worker, scheduler, polling loop, or automatic replay path.
   Invoke it only as an explicit operator action after the required Twilio
   configuration is in place.
4. Create a reusable, ephemeral Tailscale auth key tagged `tag:railway`.
   Tag ownership remains limited to a tailnet administrator. Store the key
   only as the Railway secret `TS_AUTHKEY`.
5. Add a least-privilege ACL grant equivalent to:

   ```jsonc
   {"src": ["tag:railway"], "dst": ["100.113.65.40"], "ip": ["tcp:11434"]}
   ```

6. Set `TS_HOSTNAME` to a stable operator-recognizable hostname, such as
   `novaorders-railway`. The ephemeral node's Tailscale IP is not stable.
7. Set `OLLAMA_PROXY_URL` to exactly one of the supported transport
   values and retain the configured private Ollama URLs/models:

   - `LLM_URL=http://100.113.65.40:11434/api/generate`
   - `LLM_MODEL=qwen-27b-coding:latest`
   - `EMBEDDING_URL=http://100.113.65.40:11434/api/embed`
   - `EMBEDDING_MODEL=all-minilm:latest`
   - `EMBEDDING_DIMENSION=384`

   Supported `OLLAMA_PROXY_URL` selections (loopback-only, both
   listeners are started by the same userspace `tailscaled` process):

   - SOCKS5 (default, current path): `socks5h://127.0.0.1:1055`
   - HTTP (A/B alternative): `http://127.0.0.1:1056`

   The single configured value is the authoritative transport
   selection. The application MUST NOT fall back automatically to
   the other listener, to a public route, or to direct Ollama
   access on a transport failure; a misconfigured or unreachable
   proxy remains a configuration/transport error visible to the
   existing client/worker error and retry semantics.

   The HTTP listener is intended only for a controlled operator-run
   A/B test of the intermittent `requests.post` boundary failure.
   Roll back to the existing SOCKS5 selection by restoring
   `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` and redeploying the
   same implementation; no code or database rollback is required.

Remove the previous `OLLAMA_HTTP_PROXY` variable. Do not assign a public domain
or exposed port to either Tailscale proxy listener. Do not set `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, or `NO_PROXY` for this service. The proxy is
scoped only to the existing Ollama generate and embedding clients.

## Deployment lifecycle

The Docker image starts `tailscaled` in userspace mode and binds its SOCKS5
proxy to `127.0.0.1:1055` and its outbound HTTP proxy to `127.0.0.1:1056`.
Both listeners are loopback-only and run on the same `tailscaled` process;
neither is exposed through a Railway public port. The application uses
exactly the transport selected by `OLLAMA_PROXY_URL` and MUST NOT fall back
between listeners, to a public route, or to direct Ollama access. The
entrypoint fails before Uvicorn starts unless the database, auth key,
hostname, and Railway port are present and Tailscale is ready within
30 seconds (override only with positive `TS_READY_TIMEOUT_SECONDS`).
If Tailscale exits after readiness, the entrypoint stops Uvicorn so Railway
can restart or fail the deployment.

`railway.toml` no longer declares an independent pre-deploy command. The
Docker entrypoint is the single repository-managed migration authority:
after the required-variable checks and before any Tailscale or Uvicorn
process starts, it runs `python -m alembic upgrade head`. The gate fails
closed: a missing URL or a non-zero Alembic exit aborts the entrypoint
before any child process is launched. `/health` remains a liveness endpoint
and does not call Ollama.

Authoritative post-deploy migration verification:

1. Confirm the deploy succeeded and the entrypoint log contains
   `migration=completed` (or, on failure, only `startup_error
   migration_failed` plus the non-zero exit; no traffic was served).
2. From a Railway shell for the integrated web service, run:

   ```sh
   python -m alembic current
   ```

   and record only the resulting revision; never print the database URL.
3. Confirm the public `GET /health` returns `200` with `{"status":"ok"}`
   only after both of the above.

Do not treat a successful build, config parsing, or `/health` response as
proof that the release migration reached the expected revision.

## Readiness boundary

Infrastructure readiness requires a successful build/release, the verified
Alembic revision on Railway PostgreSQL, and public `GET /health` returning
`200` with `{"status":"ok"}`. `/health` is intentionally only a liveness
check; it does not establish database, Twilio, or business-message readiness.

Business-message readiness additionally requires the passed integrated
generate/embed probes, configured Twilio inbound and status-callback URLs, and
a controlled non-destructive signed webhook verification. Keep the production
WhatsApp number disabled until every applicable business gate has evidence.

## Controlled verification

After deployment, verify these without printing credentials, prompts, outputs,
vectors, database URLs, or raw Tailscale status:

1. Railway logs contain `tailscale_ready proxy=enabled`; they must not contain
   auth keys, node keys, or raw status JSON.
2. In a Railway shell for the integrated web service, run:

   ```sh
   python -m alembic current
   ```

   Record only the resulting revision; do not print the database URL.
3. The public `GET /health` returns `200` with `{"status":"ok"}`.
4. In a Railway shell for the integrated web service, run the bounded response-byte diagnostic before the contract helper:

   ```sh
   PYTHONPATH=. python -m backend.scripts.check_railway_ollama_contracts --transport-diagnostic
   ```

   It must report the connection result, HTTP status, elapsed time, received-byte count, and an error category only. A `200` with zero bytes remains a failed diagnostic; do not treat `tailscale ping` or the Ollama access log alone as proof of returned HTTP bytes.

   For intermittent `QueryLlm` losses against the `/api/generate` route, run the same diagnostic against the generate target without changing settings, timeout, proxy, model, or worker behavior:

   ```sh
   PYTHONPATH=. python -m backend.scripts.check_railway_ollama_contracts \
     --transport-diagnostic --target generate
   ```

   It reuses `Settings.llm_url`, `Settings.llm_model`, `Settings.ollama_proxy_url`, and `Settings.llm_timeout`. The probe uses a fixed controlled prompt that is never printed or returned. The result reports only `target`, `connection`, `category`, `http_status`, `elapsed_seconds`, and `received_bytes`, and exits `0` only when HTTP succeeds with received bytes. Exit code `1` with `category=response_bytes_received` is impossible; a `200` with zero bytes remains `category=empty_response`.

   After each attempt, record the UTC timestamp and the safe result, then correlate manually with the Ollama access log for a matching `/api/generate` request. Repeat the command manually to reproduce intermittent failures. A single isolated result is not a root cause: correlate the four-way boundary (request reached Ollama, Ollama response observed, bytes received, byte count bounded) before drawing any conclusion. Do not infer a cause from `tailscale ping`, a single Ollama log line, or one diagnostic run alone.
5. In a Railway shell for the integrated web service, run:

   ```sh
   PYTHONPATH=. python -m backend.scripts.check_railway_ollama_contracts
   ```

   It must report both `generate=passed` and `embed=passed`, with dimension
   `384`, while hiding the prompt, response, and vector.
6. Confirm the ephemeral `tag:railway` node is connected in Tailscale admin.
   A `tailscale ping` alone is diagnostic evidence, not the application gate.
7. Configure Twilio's public inbound and status-callback URLs, then perform a
   non-destructive signed webhook verification. Retain only safe success/fail
   evidence and never log the signature, credentials, or form body.
8. Only after steps 1–7 pass, remove the standalone disposable `tailscale`
   Railway spike and revoke its temporary auth key.

## Rollback

Use Railway deployment rollback to return to the 6.1 release, then remove the
integrated ephemeral node and invalidate its auth key. Do not run an automatic
PostgreSQL downgrade. If integrated verification fails, retain the disposable
spike only as diagnostic infrastructure and keep real WhatsApp traffic off the
service.

## Provider-flow live audit

The integrated `supernova-ia` Railway service runs the closed provider
pipeline (`recepciones_mensajes_proveedor` → `procesamientos_mensajes_proveedor`
→ `mensajes_proveedor_salientes`). When a Twilio test message goes through
the integrated service and the operator must locate the last persisted
boundary without changing business state, run the read-only audit CLI
**before** the test message is sent.

### Pre-flight

1. Open the Railway shell for the integrated web service.
2. Verify `SUPERNOVA_DATABASE_URL` is configured (the CLI does not print it
   and reads it from the environment, matching every other Railway-driven
   client).
3. Decide on a duration. The default is `--duration-seconds=600` (10 min).
   Pick a window long enough to cover the slowest expected round trip plus
   the operator's manual steps. The CLI terminates cleanly with exit code
   `0` once the duration elapses.

### Command

```sh
PYTHONPATH=. python -m backend.scripts.audit_provider_flow_live \
  --duration-seconds 600 \
  --interval-seconds 1
```

* `--interval-seconds` controls the polling cadence. Must be positive.
  The default is `1`. Tighter intervals (e.g. `0.5`) are fine for short
  audits; longer intervals reduce database pressure but may miss fast
  transitions.
* `--duration-seconds` is the bounded audit lifetime. Must be positive.
  Defaults to `600` so the CLI never lingers indefinitely.
* `--database-url` is optional. When omitted, the CLI uses
  `SUPERNOVA_DATABASE_URL` from the Railway environment and falls back to
  the local `postgresql+psycopg:///supernova_test` URL only for tests.

The CLI never writes, never commits, never flushes, never updates, never
deletes, never claims a work item, never retries, never replays, never
sends an HTTP request and never reads message bodies. It only opens a
short-lived read-only session per poll, runs bounded `SELECT`s, closes
the session and discards intermediate state.

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Clean termination: duration elapsed or `Ctrl-C`. |
| `1`  | A polling read failed. Only the closed `module.Class` label is printed. |
| `2`  | Argument validation failed (negative or zero `--interval-seconds` / `--duration-seconds`). No database session was opened. |

### Reading the timeline

Each emitted snapshot is bound to one receipt and is keyed by its numeric
`recepcion_id`. The opaque `fingerprint` is a short SHA-256 of the provider
receipt key — it never reveals the underlying provider identifier, but it
is stable per receipt so the operator can correlate observations across
successive polls.

The safe fields the CLI prints:

* `recepcion_id`, `procesamiento_id`, `outbox_first_id`, `outbox_row_count`.
* `fingerprint`, `fecha_recepcion`, `observado_en`.
* `procesamiento_estado`, `intentos`, `categoria_ultimo_fallo`,
  `codigo_ultimo_fallo`.
* `llm_resultado`, `llm_solicitado_en`, `llm_finalizado_en`.
* `outbox_estados`.

The CLI never prints `cuerpo`, `destinatario_e164`,
`identificador_proveedor`, the Twilio Account SID, the auth token, the
webhook signature, the inbound message text, the LLM prompt, the LLM
response, exception tracebacks, the database URL or any other secret.

The emitted `observation: procesado + outbox_row_count=0` line is an
**observable terminal condition** — the worker has committed its terminal
state for that turn but the outbox staging did not produce a durable
outbound row. The auditor labels it as an observation and does **not**
infer a root cause; correlate it manually with the Railway log timeline
and with the Twilio message status before drawing any conclusion.

### Worker progress liveness read-only query

The provider worker emits the closed `provider_worker_liveness` event
at every cycle and phase boundary. The vocabulary is bounded to
`cycle_started`, `phase_started`, `phase_completed`, `phase_failed`
and `cycle_completed`; the closed phase allowlist is `readiness`,
`inbound`, `inbound_runner`, `outbound`, `cycle_summary` and `sleep`.
The event payload carries only `cycle_index` (a process-local counter),
bounded `elapsed_ms`, and on failure the safe `worker_exception`
category and the bounded `exception_type` class name. The event never
includes message bodies, phone numbers, provider SIDs, prompts, model
responses, URLs, proxies, credentials, exception messages or
tracebacks.

Use the bounded Railway log filter below to locate the last worker
boundary reached inside one process. The query is read-only, never
mutates Railway state, and only filters the structured `provider_worker_liveness`
event emitted by the worker. Do not pipe the output to a different
service and do not write the result back into the Railway project.

```sh
railway logs --service supernova-ia --since 30m | \
  grep '"event":"provider_worker_liveness"' | \
  python -c "
import json, sys
last = {}
for line in sys.stdin:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get('event') != 'provider_worker_liveness':
        continue
    cycle_index = event.get('cycle_index')
    if cycle_index is None:
        continue
    entry = last.setdefault(cycle_index, [])
    entry.append((event.get('phase'), event.get('outcome')))
for cycle_index in sorted(last):
    print(f'cycle_index={cycle_index} ' + ' '.join(
        f'{phase or \"-\"}:{outcome}'
        for phase, outcome in last[cycle_index]
    ))
"
```

The script only filters the structured liveness event line and prints
the per-cycle phase ordering. It never prints a raw Railway line, a
sensitive value, a payload, an exception message or a traceback. The
`provider_worker_liveness` event is the only event this script reads;
the read-only ``audit_provider_flow_live`` CLI above remains the
authoritative source for per-receipt diagnostics and the closed
`llm_request_transport_phase` event remains the authoritative source
for HTTP transport boundaries.

#### Interpreting an incomplete trace

Correlate only the bounded `cycle_index` within one process lifetime
and the timestamp ordering. Do not infer a cause or a recovery action
from a missing event; the diagnostic is observational only and does
not trigger any automatic restart, lease release or replay.

| Last evidence observed | Safe narrow conclusion | Not supported |
|---|---|---|
| `inbound` `phase_started` | the bounded pass began | that a row was claimed or the LLM was reached |
| `inbound_runner` `phase_started` | the runner invocation began after SIGALRM was armed | that the core coordinator or the LLM was reached |
| `inbound_runner` `phase_completed` | the whole inbound CLI pass returned | that a particular item succeeded |
| `inbound_runner` `phase_failed` | the runner raised; the safe class name and elapsed time are recorded | that the failure is recoverable, retryable or terminal |
| `outbound` `phase_completed` and `cycle_summary` `phase_started` | the outbound pass and the safe cycle-summary construction returned | that the summary line was written |
| `cycle_summary` `phase_completed` | the cycle summary writer returned | why a later cycle is absent |
| `cycle_summary` `phase_failed` | the writer raised; the safe class name is recorded | that the failure is recoverable, retryable or terminal |
| `cycle_completed` followed by `sleep` `phase_started` with no completion | the existing sleeper seam did not return | a recovery action |
| completed `sleep` with no next `cycle_started` | the outer-loop gap is the last reached boundary | a root cause or automatic remediation |

The diagnostic MUST NOT be the basis for an automatic restart, lease
release, retry, replay, watchdog action or any other recovery. Pair
the trace with the existing durable audit, the separate
`diagnose-core-inbound-pre-llm-stall` core checkpoint change, the
`llm_request_transport_phase` HTTP transport events, the bounded
`audit_provider_flow_live` CLI and the Twilio message status before
drawing any conclusion.

### `llm_request_transport_phase` closed vocabulary

The `:class:`backend.llm.query_llm.QueryLlm`` boundary emits a closed,
privacy-safe sequence of `llm_request_transport_phase` events so the
operator can locate the last client-visible HTTP boundary the integrated
worker reached on every turn. The sequence uses Requests response
streaming only as an observation seam; the Ollama payload remains
`"stream": false` and the parsed business contract is unchanged.

#### SOCKS-boundary closed phases

When `OLLAMA_PROXY_URL` selects the SOCKS scheme and the QueryLlm
default Requests transport is active, the boundary emits four
additional closed phases around the existing Requests / urllib3 /
PySocks seams so the operator can locate whether the request stalled
before the SOCKS connect, during the connect, inside the HTTP writer
or after the bytes were handed to the socket layer. The four
boundary tokens are emitted only by the QueryLlm-scoped Requests
observer; they never appear when the proxy is unset, when an
injected test transport is used, or when the reversible HTTPX
experiment is enabled:

1. `socks_connect_started` — the scoped SOCKS / urllib3 connect
   seam was entered. `elapsed_ms=0`. No `http_status`,
   `response_bytes` or `chunk_count` is attached.
2. `socks_connect_completed` — the SOCKS / urllib3 connect seam
   returned a usable target socket. Bounded non-negative
   `elapsed_ms`. A blocked or failed seam never fabricates this
   event.
3. `request_write_started` — the inherited HTTP writer was entered.
   `elapsed_ms=0`. No `http_status`, `response_bytes` or
   `chunk_count` is attached.
4. `request_write_completed` — the inherited HTTP writer returned
   after handing request bytes to the socket layer. Bounded
   non-negative `elapsed_ms`. A blocked or failed writer never
   fabricates this event.

The full strict-order contract on a successful turn is:

```text
request_started
request_write_started
socks_connect_started
socks_connect_completed
request_write_completed
response_headers_received
first_body_chunk
body_completed
response_received
json_extracted
result_parsed
```

The order is the real order of the Requests / urllib3 / PySocks
stack: `HTTPConnection.request` enters the inherited writer seam
first, then the lazy `send` path triggers `connect()` which routes
through `SOCKSConnection._new_conn`, and only when that seam
returns does the writer resume and complete. The observer does not
force `connect()` ahead of the writer and does not pre-allocate a
socket the writer is perfectly capable of opening lazily.

The QueryLlm SOCKS branch constructs a fresh
`_SocksPhaseObserverSession` per call so two consecutive SOCKS
requests never share a session, an adapter, a proxy manager, a
connection pool or a socket. A connection that already has a cached
socket skips the lazy `connect()` step, so the SOCKS pair is
omitted (and never fabricated) and only the writer pair fires.
The per-call session is closed exactly once by a private
`_SocksResponseSessionCloser` wrapper that the surrounding
`QueryLlm.request` `finally` block closes together with the
response; a second `close` on the response is idempotent and does
not re-close the session. All four new phases share the existing
opaque synthetic inbound correlation value (`correlation_id`) and
never carry URL, host, IP, port, proxy, credential, SOCKS
handshake byte, header, prompt, message text, response text,
exception text or traceback.

#### Narrow interpretation rules

The SOCKS-boundary tokens narrow what the trace establishes; they
never claim physical delivery to Ollama. The safe conclusions are:

| Last phase reached | Establishes | Does not establish |
|---|---|---|
| `request_started` only | QueryLlm entered the request boundary | that any socket activity happened |
| `request_write_started` only | the inherited HTTP writer was entered | that the lazy `connect()` step ran or that any SOCKS seam fired |
| `socks_connect_started` only | the scoped SOCKS / urllib3 seam was entered | that proxy TCP, SOCKS negotiation or proxy-to-target connection succeeded |
| `socks_connect_completed` | the scoped seam returned a target socket | that HTTP bytes reached Ollama |
| `request_write_completed` | the inherited writer returned after handing bytes to the socket layer | that the proxy forwarded the bytes or that Ollama received them |
| `response_headers_received` | the existing body / parser diagnostics remain authoritative | complete body or parsed result |

### Reversible HTTPX QueryLlm transport experiment (Test only)

The opt-in, reversible HTTPX experiment gates a synchronous HTTPX
streaming path behind `LLM_HTTP_CLIENT=httpx`. The closed vocabulary is
exactly `requests` (default) and `httpx`; any other value fails settings
loading with a secret-free configuration error before any HTTP request
is attempted. Requests remains the production default and the committed
code is inert until the variable is set.

Activation (Test only):

1. Set `LLM_HTTP_CLIENT=httpx` in Railway Test for the integrated web
   service and redeploy/restart.
2. Run controlled turns and correlate the seven closed
   `llm_request_transport_phase` events with the Ollama journal.
3. Do not enable the setting in production during this experiment.

Operational rollback (Test):

1. Remove `LLM_HTTP_CLIENT` (or set it to `LLM_HTTP_CLIENT=requests`) in
   Railway Test and redeploy/restart. The next process start selects
   Requests by default without any code, schema, migration, timeout,
   proxy, Tailscale, Twilio or worker change.

The HTTPX branch is intentionally minimal: one synchronous
`httpx.Client` driving `build_request(...)` + `send(..., stream=True)`, the same `OLLAMA_PROXY_URL` scope
(`socks5://` or `socks5h://`), the same total `LLM_TIMEOUT`, the same
seven-phase event order, the same closed error categories
(`QueryLlmTimeoutError`, `QueryLlmConnectionError`,
`QueryLlmHttpError`, `QueryLlmResponseError`) and no Requests fallback.
A failed HTTPX attempt never invokes Requests and never issues a second
LLM request.

The closed vocabulary has seven tokens; six of them are observed
during a successful turn and `response_received` is both observed on
success and retained as the historical compatibility token the
diagnostic emits after `body_completed` to preserve the previous
non-streaming `response_received` semantics:

1. `request_started` — `requests.post` was issued (no body bytes yet).
2. `response_headers_received` — the response status line and headers
   reached the client. Carries `http_status` (and only `http_status`
   besides `elapsed_ms` and `correlation_id`).
3. `first_body_chunk` — the first non-empty body chunk returned by
   `iter_content`. Carries `chunk_count=1`. Emitted at most once.
4. `body_completed` — the body iterator finished normally (no read
   timeout, no chunked-encoding error). Carries the final bounded
   `chunk_count` and `response_bytes`.
5. `response_received` — historical compatibility token. In the
   streaming path it now signals that the full HTTP response was
   received (i.e. emitted only after `body_completed`, before
   `json_extracted`). The parser continues to accept historical
   `response_received` lines from the previous non-streaming
   release.
6. `json_extracted` — the Ollama JSON envelope was decoded into the
   inner `response` field.
7. `result_parsed` — `_parse` returned a dict (the worker is the only
   caller that reads the result).

`response_headers_received` reports headers available; `response_received`
reports body fully received. The two are deliberately distinct so
operators can correlate a partial body trace with the previous
release's `response_received` semantics.

Any other phase token is rejected by `build_event`. If `iter_content`
raises before the iterator finishes, the trace stops at the last
reached phase and never fabricates `body_completed`, `response_received`,
`json_extracted` or `result_parsed`. If `requests.post` raises before
headers arrive, the trace stops at `request_started`.

Allowed optional fields are limited to `elapsed_ms`, `http_status`,
`response_bytes`, `chunk_count` and the existing opaque correlation
identifier. The emission path is fail-soft: a misconfigured emitter
cannot break the surrounding business flow.

The streaming `iter_content` reader classifies `requests.exceptions`
in the same way the initial `requests.post` call does: `Timeout`
becomes `QueryLlmTimeoutError`, `ConnectionError` (including
`ChunkedEncodingError` and other subclasses Requests uses for a
read-timeout during streaming) becomes `QueryLlmConnectionError`. The
classification is centralised so the historical contract remains
identical on every code path; no retry or second request is added.

### Correlating Railway SOCKS-boundary evidence with proxy / host captures

`request_write_completed` confirms the client handed the request
bytes to its local socket layer; it does **not** prove the proxy
forwarded the bytes or that Ollama received them. Locating a stall
in the proxy-to-Ollama / Tailscale leg requires a separate read-only
capture on the operator-controlled host where the proxy or Ollama
runs. The capture must remain time-bounded, observability-only and
free of secrets in this runbook.

#### Closed preflight

1. Confirm the SOCKS proxy / Ollama host capture is run on the
   machine where the proxy (`OLLAMA_PROXY_URL`) or the Ollama
   service is actually running. The Railway web service container
   does **not** host the proxy or Ollama and is not the right
   host. Capture on the wrong host yields no useful correlation.
2. Verify the operator has approved read-only access to the target
   host (admin / sudo) and a recorded time window long enough to
   cover the slowest expected round trip plus manual steps. Stop
   the capture the moment the diagnostic window elapses.
3. Decide the bounded UTC start timestamp and capture duration
   before issuing the command; the capture must NOT run unattended
   and MUST NOT write to the Railway project or to any database.
4. Identify the bounded client evidence already collected: the
   `correlation_id` (the existing opaque synthetic inbound
   identifier) and the UTC timestamp of the
   `llm_request_transport_phase` lines printed in Railway logs.
   The capture is only meaningful when its UTC window brackets
   those timestamps.

#### Read-only capture recipes (illustrative shapes only)

The exact command depends on the host's available tooling; the
recipes below are illustrative and must be adapted by an operator
with read-only access. They MUST NOT include hosts, URLs, IPs,
credentials, ports, interface names, or any other identifier from
this runbook. Substitute the operator-approved target at run time.

* On the host running the SOCKS proxy or Ollama, run the equivalent
  of `journalctl` or the platform's journal reader scoped to the
  proxy / Ollama service unit, restricted to a bounded UTC window
  bracketing the `correlation_id` recorded by the Railway log line.
  Stop the read the moment the diagnostic window elapses. Do not
  redirect the journal output to a persistent file or to the
  Railway project.
* On the same host, run the equivalent of `tcpdump` (or the
  platform's packet capture tool) on the operator-approved
  interface, restricted to the closed port pair (proxy listen port
  and Ollama listen port) and to a bounded UTC window. Apply the
  standard `tcpdump` `-W` / `-G` ring-buffer arguments so the
  capture self-stops at the configured boundary. Run as a user
  that does NOT have permission to write persistent state; the
  capture MUST terminate at the ring-buffer boundary and MUST NOT
  be replayed or archived by the Railway service.

#### Correlation rules

1. Map the `correlation_id` from the Railway
   `llm_request` / `llm_request_transport_phase` line to the
   proxy / Ollama access log entry inside the same bounded UTC
   window. A matching ingress at the proxy proves the bytes
   reached the proxy; a matching entry at Ollama proves the bytes
   reached Ollama.
2. The four SOCKS-boundary phases narrow the last client-side
   observation:

   * `request_started` without `request_write_started` — the
     client never reached the inherited writer seam; the local
     failure happened before any socket activity.
   * `request_write_started` without `socks_connect_started` —
     the inherited writer was entered but the lazy SOCKS connect
     never ran (e.g. the writer raised before the first
     `send`); the writer seam is the last reached boundary.
   * `socks_connect_started` without `socks_connect_completed` —
     the local-to-proxy TCP, the SOCKS negotiation, or the
     proxy-to-target connection stalled; the four application
     telemetry phases cannot split those three operations.
   * `socks_connect_completed` without `request_write_completed`
     — the client established the proxy session but the writer
     did not return; the stall is in the local writer seam.
   * `request_write_completed` without
     `response_headers_received` — the client handed bytes to
     the socket layer; only the proxy / Ollama host capture can
     establish whether the bytes reached Ollama. The absence of a
     matching ingress at the proxy or at Ollama inside the same
     bounded UTC window narrows the issue to that network leg.
   * `response_headers_received` — the existing body / parser
     diagnostics remain authoritative.

3. Do not infer a root cause or trigger any restart, lease release,
   retry, replay or automatic remediation from a single bounded
   correlation. Pair the trace with the existing durable audit,
   the separate `diagnose-core-inbound-pre-llm-stall` core
   checkpoint change, the bounded `audit_provider_flow_live`
   CLI, the Twilio message status and the proxy / Ollama host
   capture before drawing any conclusion. A single isolated
   observation is not a root cause.
4. The capture is purely diagnostic; it MUST NOT modify Railway
   variables, `OLLAMA_PROXY_URL`, `OLLAMA_HTTP_PROXY`,
   `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, the
   Tailscale ACL, the proxy configuration or any other
   operational state.

### What the CLI does not do

* It does not read stdout from `supernova-ia`. Correlate the printed
  timeline with the Railway log panel for the same web service from a
  separate terminal or browser tab.
* It does not invoke `railway`, does not connect to Twilio, does not
  call any provider HTTP endpoint, and does not process the inbound
  message itself.
* It does not commit, flush, update, delete, claim, lease, retry or
  replay.

### Stopping the audit

* `Ctrl-C` (SIGINT): the CLI sets an internal flag at the next poll
  iteration, prints `audit: terminated observado_en=...` and exits `0`
  after releasing the read-only session.
* Letting the duration expire: identical outcome with the wall-clock
  boundary as the trigger.

If a single isolated observation is reported, do **not** treat it as a
root cause. Correlate the four-way boundary (Twilio inbound timestamp,
CLI snapshot, Railway log line, Twilio status callback) before drawing
any conclusion.

## Repeated HTTP transport diagnostic at the local SOCKS5 boundary

When intermittent `QueryLlm` request loss cannot be narrowed by the
single-shot `--transport-diagnostic --target generate` probe, run the
bounded repeated-transport diagnostic below to compare the
production-shaped `requests.post` call shape against a diagnostic-only
reused `requests.Session`. The probe sits below the production
`QueryLlm` boundary so it can observe the exact `requests` →
`socks5h://127.0.0.1:1055` call shape without depending on the worker,
the coordinator, the database, Twilio, Tailscale or Ollama.

### Pre-flight

1. Open the Railway shell for the integrated web service in the `core`
   project, `test` environment, `supernova-ia` service.
2. Confirm `LLM_URL`, `OLLAMA_PROXY_URL` and the SOCKS5 daemon are still
   configured exactly as the deployment runbook prescribes. The probe
   reads them through `Settings` and never prints them.
3. Pick a bounded attempt count. The default is `10` so each run stays
   under a minute; raise it only when you need to reproduce a known
   intermittent failure pattern.

### Command — fresh mode (matches the current application shape)

```sh
PYTHONPATH=. python -m backend.scripts.probe_railway_socks5_repeated \
  --mode fresh \
  --count 10 \
  --connect-timeout-seconds 5 \
  --read-timeout-seconds 20
```

`fresh` invokes the top-level `requests.post` once per attempt, exactly
the same call shape `QueryLlm._post` uses today. It does not own a
session, so every attempt opens a fresh proxy-side connection.

### Command — session mode (diagnostic-only comparison)

```sh
PYTHONPATH=. python -m backend.scripts.probe_railway_socks5_repeated \
  --mode session \
  --count 10 \
  --connect-timeout-seconds 5 \
  --read-timeout-seconds 20
```

`session` creates one `requests.Session` for the bounded run and reuses
it across the loop. The session is **diagnostic-only**; it is not used
by `QueryLlm`, the worker or the coordinator.

### Arguments

* `--mode` — `fresh` (default) or `session`. Anything else exits `2`
  without issuing any request.
* `--count` — positive integer (default `10`). Must be a positive
  integer; zero or negative values exit `2`.
* `--connect-timeout-seconds` — positive finite number (default `5`).
* `--read-timeout-seconds` — positive finite number (default `20`).

The probe forwards the timeouts as the tuple
`(connect_timeout_seconds, read_timeout_seconds)` so the connect phase
and the response-read phase are bounded independently.

### Safe output

Each attempt prints a single bounded line containing only:

* `mode` (`fresh` or `session`).
* `attempt` (1-based index).
* `inicio_utc`, `fin_utc` (ISO-8601 UTC with `Z` suffix).
* `duracion_ms` (elapsed milliseconds for the attempt).
* `phase` (`returned` or `exception`).
* `http_status` (when a response was returned).
* `received_bytes` (when a response was returned).
* `outcome` (closed token — `success`, `empty_response`, `http_status`,
  `connect_timeout`, `read_timeout`, `proxy_error`, `connection_error`,
  `request_error`, `configuration_error`).
* `exception_class` (closed Requests class label when an exception is
  classified).

The probe NEVER prints the target URL, proxy URL, request body, response
body, headers, credentials, customer/order data, exception text or
tracebacks. Each attempt is independent: a failed attempt is recorded
and the next bounded attempt still runs.

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | All requested attempts returned a successful HTTP response with at least one byte. |
| `1`  | At least one attempt reported a non-`success` outcome (timeout, HTTP failure, empty response, transport error). |
| `2`  | Invalid arguments (`--count`, `--mode`, timeouts). No request or `requests.Session` was created. |

### Reading the two runs

Compare the bounded output from a `fresh` run against a `session` run
executed back-to-back under the same Railway conditions:

| Observation | Narrow interpretation |
| --- | --- |
| `fresh` fails and `session` succeeds | Repeated fresh connection setup is implicated. Do not yet infer a specific infrastructure cause. |
| Both modes fail with `connect_timeout`, `proxy_error` or `connection_error` | The failure occurs before a usable HTTP response at the local proxy boundary. |
| Both modes fail with `read_timeout` | The HTTP call was established but no response completed within the read bound; the destination remains a black box. |
| Both modes succeed repeatedly | This isolated boundary is not reproducing the issue under that run; revisit the worker, the lease/finalize transaction, the observability seam or the destination service. |

These outcomes are diagnostic evidence only. They must not trigger a
runtime fix automatically. Do not correlate against `tailscale ping`,
Ollama access logs or a single attempt in isolation.

### Stopping the probe

The probe terminates cleanly when the bounded attempt count finishes.
`Ctrl-C` (SIGINT) aborts the in-flight attempt and exits non-zero with
no further output.
