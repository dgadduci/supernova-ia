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
7. Set `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` and retain the configured
   private Ollama URLs/models:

   - `LLM_URL=http://100.113.65.40:11434/api/generate`
   - `LLM_MODEL=qwen-27b-coding:latest`
   - `EMBEDDING_URL=http://100.113.65.40:11434/api/embed`
   - `EMBEDDING_MODEL=all-minilm:latest`
   - `EMBEDDING_DIMENSION=384`

Remove the previous `OLLAMA_HTTP_PROXY` variable. Do not assign a public domain
or exposed port to the Tailscale proxy. Do not set `HTTP_PROXY`, `HTTPS_PROXY`,
`ALL_PROXY`, or `NO_PROXY` for this service.

## Deployment lifecycle

The Docker image starts `tailscaled` in userspace mode and binds its SOCKS5
proxy to `127.0.0.1:1055`. It fails before Uvicorn starts unless the
database, auth key, hostname, and Railway port are present and Tailscale is
ready within 30 seconds (override only with positive `TS_READY_TIMEOUT_SECONDS`).
If Tailscale exits after readiness, the entrypoint stops Uvicorn so Railway can
restart or fail the deployment.

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
