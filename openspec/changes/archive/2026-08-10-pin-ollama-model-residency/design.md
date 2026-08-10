# Design: reversible permanent model residency

The operation has two independent setting owners:

1. Railway receives `LLM_KEEP_ALIVE=-1`. QueryLlm already sends this setting in every `/api/generate` request, so it overrides the server default for Qwen.
2. Ubuntu systemd receives `OLLAMA_KEEP_ALIVE=-1` through a dedicated override. Embedding requests do not supply a keep-alive value, so the daemon setting governs `all-minilm`.

Safe sequence:

1. Capture current non-secret residency settings and verify no active test work.
2. Disable the provider worker and wait for the Railway deployment; receipts may queue but no inbound is claimed.
3. Add the systemd override, daemon-reload and restart Ollama; verify active listener and controlled readiness from Railway.
4. Set Railway `LLM_KEEP_ALIVE=-1` and re-enable the worker in one configuration deployment.
5. Let initial readiness warm both models; use `ollama ps` on Ubuntu to verify only Qwen and `all-minilm` are resident with non-expiring expiry.
6. Send one existing-safe test message; verify a single processed receipt and a single delivered outbound without manual CLIs.

If any step fails, keep the worker disabled while restoring the captured settings, restart Ollama, then re-enable/deploy the worker only after readiness passes.
