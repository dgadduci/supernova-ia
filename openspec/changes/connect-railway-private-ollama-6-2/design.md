## Decision

Railway cannot provide the container privileges needed for a kernel TUN
interface. The production web service will therefore run `tailscaled` in
userspace-networking mode in the same container as Uvicorn. Tailscale will
bind its HTTP/SOCKS proxy to `127.0.0.1:1055`; it receives no Railway public
domain and no exposed port.

The image will be built from the existing Python runtime dependency set and
will copy the Tailscale binaries from the official pinned Tailscale image.
An entrypoint, rather than application import/startup code, owns the
Tailscale process lifecycle:

1. require `SUPERNOVA_DATABASE_URL`, `TS_AUTHKEY`, and a non-empty
   `TS_HOSTNAME` before doing any work;
2. launch `tailscaled --tun=userspace-networking` with both local proxy
   protocols on `127.0.0.1:1055` and ephemeral in-memory state;
3. execute `tailscale up` using the Railway secret auth key and hostname;
4. wait for a bounded ready state and for the loopback proxy to accept local
   connections; do not print credentials or full status output;
5. start the current Uvicorn command and forward termination signals to both
   managed processes; if Tailscale exits before/while the application is
   running, terminate the application so Railway restarts or fails the
   service rather than serving without the private network boundary.

The existing Railway pre-deploy Alembic command remains outside this
entrypoint: it requires only the database and must not need Tailscale. The
application's public health endpoint remains a liveness check and must not
call Ollama.

## Dedicated Ollama proxy contract

Add `OLLAMA_HTTP_PROXY` to `Settings`, defaulting to `None`. It is an absolute
`http://` URL when configured; invalid or blank configured values fail
settings load with a clear, secret-free configuration error. In Railway it is
set to `http://127.0.0.1:1055`.

`QueryLlm` and `OllamaEmbeddingClient` build a per-request requests proxy
mapping only when this setting is present, for their `http` and `https`
traffic. The mapping is passed directly to their existing `requests.post`
call. Injected transports keep their existing signatures and test behaviour;
the proxy mapping is supplied only on real transport calls or through a
backward-compatible optional transport keyword where tests explicitly inspect
it. No process-wide `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, or `NO_PROXY`
variables are set by the entrypoint.

This containment ensures the Twilio client and all other network clients keep
their existing direct behavior. `LLM_URL` and `EMBEDDING_URL` retain their
existing values (`http://100.113.65.40:11434/api/generate` and
`http://100.113.65.40:11434/api/embed`) and models retain their existing
names. Tailscale's HTTP proxy routes only those client requests to the private
tailnet destination.

## Tailnet boundary

The user, not the repository, owns the policy and secret setup. The required
auth key is reusable (to survive Railway redeployments), ephemeral (to remove
stale nodes), and applies `tag:railway`. The minimum retained grant is:

```jsonc
{"src": ["tag:railway"], "dst": ["100.113.65.40"], "ip": ["tcp:11434"]}
```

`tag:railway` ownership remains limited to an administrator. The app never
receives Tailscale admin/API tokens and never edits ACLs. An ephemeral node
may get a changing 100.x address; the deployment relies on its stable hostname
for operator identification, not on a fixed source address.

## Failure behavior

| Failure | Behaviour |
| --- | --- |
| Missing Tailscale variable / invalid proxy setting | fail before Uvicorn starts |
| `tailscaled` cannot start, authenticate, or become ready by deadline | exit non-zero; Railway does not activate deployment |
| Tailscale process dies after readiness | stop Uvicorn; Railway recovery policy handles restart |
| Ollama network timeout/connection/HTTP/response failure | preserve existing domain-specific LLM/embedding errors; no fallback |
| `/health` request | unchanged; no Tailscale or Ollama dependency |

## Safe deployed proof

The deployed application container must run a bounded verification that uses
the configured `QueryLlm` and `OllamaEmbeddingClient`, not a raw network
probe. The generate request uses a non-sensitive minimal fixed prompt and
checks only that the existing JSON contract is accepted. The embed request
uses non-sensitive fixed text and checks only success and dimension `384`.
The helper reports pass/fail, model, safe status/category, elapsed time, and
dimension; it must not print the prompt, response, or vector.

This is the completion gate for 6.2. A successful `tailscale ping` is useful
diagnostic evidence but is insufficient on its own because it does not prove
the HTTP proxy path or the Ollama application contract.
