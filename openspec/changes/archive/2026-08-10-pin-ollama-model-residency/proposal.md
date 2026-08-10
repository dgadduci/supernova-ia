# Pin NovaOrders Ollama model residency

## Why

NovaOrders routes both generation and embeddings to the same remote Ollama host. Qwen generation currently requests a two-hour residency and embeddings rely on the server default, producing avoidable model-load latency after idle periods. The validated host has no competing models and sufficient RAM/VRAM for Qwen 7B plus `all-minilm` to remain resident.

## What Changes

- Set Railway `LLM_KEEP_ALIVE=-1` so every application generation request pins Qwen for the server-process lifetime.
- Set the Ubuntu Ollama service environment `OLLAMA_KEEP_ALIVE=-1` so embedding requests, which do not carry a per-request keep-alive field, also keep `all-minilm` resident.
- Apply the settings through a bounded worker pause, Ollama restart, Railway redeploy, readiness warm-up, and read-only residency verification.

## Objective

Keep exactly the configured NovaOrders Qwen and embedding models resident between requests, avoiding idle reload latency while retaining a documented, reversible operational procedure.

## Current execution path

The application sends generation requests with `Settings.llm_keep_alive`; the current production value is `2h`. Embedding requests carry only model/input and therefore inherit the remote Ollama server's `OLLAMA_KEEP_ALIVE` policy. Both paths share one remote authority via the configured proxy.

## Scope and non-goals

In scope: two configuration values, controlled restarts, readiness warm-up and safe state verification.

Out of scope: code changes, API payload changes, model replacement, model downloads, GPU/RAM resizing, proxy changes, worker bounds, retry policy, migrations, prompts, queue semantics, or additional models.

## Shared boundary and transaction ownership

Railway owns application process lifecycle; Ubuntu systemd owns the Ollama daemon; the existing worker owns durable receipt processing. Operators do not run manual inbound/outbound CLIs or mutate database records. While the worker is paused, webhooks continue storing receipts durably.

## Authoritative outcomes and fallback

- Authoritative success: Railway reports `LLM_KEEP_ALIVE=-1`; Ubuntu has `OLLAMA_KEEP_ALIVE=-1`; controlled readiness passes; `ollama ps` lists the two configured models with non-expiring residency; worker resumes and one WhatsApp receipt reaches one processed inbound and one delivered outbound.
- Valid temporary state: the worker is disabled during the planned Ollama restart and receipts remain pending.
- Technical failure: Ollama does not restart, readiness fails after restore, either expected model is absent/non-resident, the worker cannot resume, or any terminal/duplicate processing occurs.
- Fallback: set Railway `LLM_KEEP_ALIVE` back to its captured value; remove or restore the captured Ubuntu `OLLAMA_KEEP_ALIVE` override; restart Ollama; redeploy/re-enable worker; verify readiness and pending work recovery.
- Must not trigger fallback: expected pending receipts during the worker pause, a normal warm-up load before residency is verified, or non-sensitive status output.

## Observability and privacy

Record only configuration value presence/value, service state, readiness categories/durations, model names, residency status, receipt/work/outbound IDs and states. Do not expose endpoint URLs, proxies, payloads, prompts, responses, vectors, credentials, environment dumps or customer message bodies.

## Expected files and validation

Only this OpenSpec change is added. The production configuration is user-operated and intentionally not committed.

```bash
openspec validate pin-ollama-model-residency --strict
```

## Rollback and deferred limitations

Rollback restores the captured settings and restarts the two services; no database repair or migration is required. This does not provide memory-pressure eviction, multi-model scheduling, alerting, or a per-embedding request keep-alive setting; those remain deferred.
