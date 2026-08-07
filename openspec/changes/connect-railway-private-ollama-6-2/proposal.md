# Subphase 6.2: connect Railway to private Ollama through Tailscale

## Objective

Enable the existing Railway FastAPI service to call the user-owned Ollama
node at `100.113.65.40:11434` over the private Tailscale tailnet, for both
the existing generative and embedding clients, without exposing Ollama or
changing product-recognition, order, WhatsApp, or database behaviour.

## Verified starting point

- The Phase 6.1 Railway web service and PostgreSQL service are online; the
  public `/health` endpoint responds successfully.
- A disposable Railway service running `tailscale/tailscale:stable` joined
  the tailnet using the ephemeral `tag:railway` identity and can `tailscale
  ping` the Ollama node.
- Ollama is listening on `*:11434`, and a local `curl` to `/api/tags`
  returns JSON.
- The disposable service uses userspace networking. Its local SOCKS/HTTP
  proxy is private to that container, so a separate Railway web service
  cannot use it. The previous raw request therefore does not prove an Ollama
  HTTP response from the web-service process.

## Scope

- Replace the Railpack-only application image with the smallest explicit
  image/entrypoint capable of running Tailscale userspace networking and the
  existing FastAPI process in **the same Railway service/container**.
- Authenticate the container with a Railway-scoped, reusable, ephemeral
  Tailscale auth key and `tag:railway`; make the local proxy listen only on
  loopback.
- Add a dedicated, optional Ollama HTTP-proxy setting consumed only by the
  existing `QueryLlm` and `OllamaEmbeddingClient` HTTP calls. Do not apply a
  global proxy to Twilio, PostgreSQL, Railway health checks, or unrelated
  outbound traffic.
- Fail closed: if Tailscale cannot authenticate or reach its ready state, the
  web process does not start. Existing local development defaults remain
  direct/no-proxy.
- Prove, from the deployed web-service container, bounded safe calls through
  the existing generate and embed contracts; confirm the configured models
  and the 384-dimensional embedding result without retaining prompt, model
  output, or vectors.
- Replace/remove the disposable standalone `tailscale` Railway spike only
  after the integrated service passes verification, and revoke its temporary
  auth key when it is no longer needed.

## Non-goals

- No public Ollama endpoint, Funnel, Serve endpoint, reverse tunnel, subnet
  router, exit node, or inbound port for the Tailscale proxy.
- No new LLM provider, model change, vector re-indexing, recognition-policy
  change, order-domain change, migration, worker, scheduler, or CI/CD work.
- No automatic mutation of Tailscale ACLs from the application or Railway.
- No change to existing public HTTP routes other than the deployment process.

## Shared boundary and outcomes

| Condition | Outcome | Required fallback |
| --- | --- | --- |
| Tailscale authenticates and local proxy is ready | FastAPI starts; Ollama clients use the configured loopback proxy | none |
| Tailscale auth/proxy readiness fails | Release fails before application traffic | do not start FastAPI; do not use public/direct Ollama |
| Ollama generate/embed call succeeds through proxy | Business-readiness network gate passes for that contract | none |
| Ollama is unreachable, unauthorized, times out, or returns invalid contract data | Existing client reports its existing safe failure type | no model substitution, direct public URL, or localhost fallback in Railway |
| Proxy setting absent locally | Existing direct local Ollama behaviour is preserved | direct local path remains allowed only outside the Railway deployment contract |

## Transaction ownership and observability

This deployment subphase creates no request transaction owner and changes no
database transaction boundary. Logs may report sanitized lifecycle state
(`tailscale_started`, `tailscale_ready`, proxy enabled/disabled), configured
model names, elapsed time, HTTP status, and embedding dimension. They must
not include auth keys, node keys, proxy credentials, Ollama request text,
generated content, vectors, raw Tailscale status JSON, customer data, or
database URLs.

## Expected files

- `Dockerfile`, `.dockerignore`, and a minimal startup/entrypoint script
- `railway.toml` and `backend/development/railway.md`
- `backend/config/settings.py`, `backend/llm/query_llm.py`, and
  `backend/llm/embedding_client.py`
- focused unit tests and a bounded manual Railway verification helper only if
  one is needed to exercise the two existing contracts safely
- this OpenSpec change and its capability delta

## Validation and rollback

Validation requires focused settings/client tests, startup-script checks,
Ruff, `compileall`, strict OpenSpec validation, and `git diff --check` in the
user's local terminal. External verification requires Railway deployment
logs, `/health`, a Tailscale-admin view of the ephemeral tagged node, and
safe deployed generate/embed probes through the web-service process.

Rollback is Railway deployment rollback to the 6.1 release and removal of
the integrated node/auth key. It never includes an automatic database
downgrade. The standalone spike is removed only after the integrated route is
verified; otherwise it remains the disposable diagnostic environment.

## Deferred limitations

This subphase does not make LLM responses highly available, does not rotate
keys automatically, and does not add metrics beyond sanitized logs. It
establishes only the private reachability boundary required by the existing
clients.
