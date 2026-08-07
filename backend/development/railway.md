# Railway deployment runbook

## Scope

The Railway web service runs FastAPI and a colocated, userspace Tailscale
daemon. Only the existing Ollama generate and embedding HTTP calls use the
loopback proxy. PostgreSQL migrations, Twilio, `/health`, and all other
outbound clients remain direct.

## Required Railway and Tailscale setup

1. Keep `SUPERNOVA_DATABASE_URL` as a Railway reference to PostgreSQL's
   `DATABASE_URL`; never copy its resolved value into the repository or logs.
2. Create a reusable, ephemeral Tailscale auth key tagged `tag:railway`.
   Tag ownership remains limited to a tailnet administrator. Store the key
   only as the Railway secret `TS_AUTHKEY`.
3. Add a least-privilege ACL grant equivalent to:

   ```jsonc
   {"src": ["tag:railway"], "dst": ["100.113.65.40"], "ip": ["tcp:11434"]}
   ```

4. Set `TS_HOSTNAME` to a stable operator-recognizable hostname, such as
   `novaorders-railway`. The ephemeral node's Tailscale IP is not stable.
5. Set `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` and retain the configured
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

`railway.toml` keeps Alembic as an independent pre-deploy command. `/health`
remains a liveness endpoint and does not call Ollama.

## Controlled verification

After deployment, verify these without printing credentials, prompts, outputs,
vectors, database URLs, or raw Tailscale status:

1. Railway logs contain `tailscale_ready proxy=enabled`; they must not contain
   auth keys, node keys, or raw status JSON.
2. The public `GET /health` returns `200` with `{"status":"ok"}`.
3. In a Railway shell for the integrated web service, run:

   ```sh
   PYTHONPATH=. python -m backend.scripts.check_railway_ollama_contracts
   ```

   It must report both `generate=passed` and `embed=passed`, with dimension
   `384`, while hiding the prompt, response, and vector.
4. Confirm the ephemeral `tag:railway` node is connected in Tailscale admin.
   A `tailscale ping` alone is diagnostic evidence, not the application gate.
5. Only after steps 1–4 pass, remove the standalone disposable `tailscale`
   Railway spike and revoke its temporary auth key.

## Rollback

Use Railway deployment rollback to return to the 6.1 release, then remove the
integrated ephemeral node and invalidate its auth key. Do not run an automatic
PostgreSQL downgrade. If integrated verification fails, retain the disposable
spike only as diagnostic infrastructure and keep real WhatsApp traffic off the
service.
