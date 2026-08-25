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

### `llm_request_transport_phase` closed vocabulary

The `:class:`backend.llm.query_llm.QueryLlm`` boundary emits a closed,
privacy-safe sequence of `llm_request_transport_phase` events so the
operator can locate the last client-visible HTTP boundary the integrated
worker reached on every turn. The sequence uses Requests response
streaming only as an observation seam; the Ollama payload remains
`"stream": false` and the parsed business contract is unchanged.

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
