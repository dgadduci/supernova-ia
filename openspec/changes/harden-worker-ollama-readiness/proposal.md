# Gate automatic inbound processing on Ollama readiness

## Objective

Prevent the automatic provider-processing worker from consuming customer inbound work immediately after a Railway restart while the private Ollama generate/embed path is not ready.

## Evidence and current path

After worker enablement, receipt 33 was claimed and exhausted three LLM failures around five seconds, reaching `failed_terminal` with no outbox row. `LLM_TIMEOUT` was verified as 180 seconds, so this was transient post-redeploy connectivity/readiness rather than the application timeout. Soon afterwards, the existing safe generate/embed diagnostic passed and receipt 34 completed automatically: receipt -> processed -> one outbound -> delivered.

Today the entrypoint waits for Tailscale's local backend state, then starts the worker. The worker immediately runs inbound then outbound. That Tailscale condition does not prove the configured Ollama generate and embedding endpoints are usable. `backend.scripts.check_railway_ollama_contracts` already probes both safely, but only as an operator CLI.

## Scope and non-goals

- Extract/reuse a side-effect-free controlled generate+embedding readiness seam.
- Until that seam passes, skip only the inbound pass, keep work durable and run the existing bounded outbound pass.
- Retry readiness at the configured worker interval; after first success, resume existing inbound-then-outbound cycles without probing every message.
- Add focused recovery, no-claim, outbound-continuity and privacy tests.

No migration, requeue of receipt 33, retry/backoff/category change, webhook change, new queue/service/scheduler, direct provider send, timeout change, or recognition-policy change.

## Boundaries, fallback, observability

The probe opens no DB session, sends no provider message and mutates no state. The worker remains only an orchestrator: existing coordinator/dispatcher own transactions, leases and retries. While not ready, the fallback is skip inbound, run outbound, safely record not-ready, sleep. It must not claim inbound rows, fabricate retries, process inline or terminate web traffic. Later per-message failures keep their existing policy.

Output may include only ready/not-ready, safe class/category, duration, bounds and cycle index. It must not include probe text, prompts, responses/vectors, URL/proxy, customer/provider content, credentials, signatures, account IDs or environment dumps.

## Validation and rollback

Expected surface: existing diagnostic probe module, worker CLI, focused tests and this change. `docker-entrypoint.sh`, DB, webhook and manual CLIs remain unchanged.

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_processing_worker.py backend/tests/test_railway_tailscale_entrypoint.py backend/tests/test_query_llm.py backend/tests/test_ollama_embedding_client.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/cli/run_provider_processing_worker.py backend/scripts/check_railway_ollama_contracts.py backend/tests/test_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/cli/run_provider_processing_worker.py backend/scripts/check_railway_ollama_contracts.py
openspec validate harden-worker-ollama-readiness --strict
```

Disable the worker flag for manual rollback. Code rollback needs no schema/work-row mutation. Terminal-work replay and readiness checks after initial success are deferred.
