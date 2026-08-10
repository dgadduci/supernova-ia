# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect current generation and embedding keep-alive boundaries.
- [x] 1.2 Define bounded pause, startup, warm-up, evidence and rollback rules.
- [x] 1.3 Obtain approval for this configuration-only change.

## 2. Controlled production configuration

- [x] 2.1 Capture current non-secret values, model residency and no-active-work baseline.
- [ ] 2.2 Disable worker and verify receipts remain durable while inbound is paused.
- [x] 2.3 Apply reversible Ubuntu `OLLAMA_KEEP_ALIVE=-1`, restart Ollama and verify readiness.
- [x] 2.4 Set Railway `LLM_KEEP_ALIVE=-1m`, re-enable/redeploy worker and verify warm-up residency.
- [x] 2.5 Send one safe WhatsApp receipt and verify one processed inbound plus one delivered outbound.
- [x] 2.6 Review safe evidence and rollback readiness.

## 3. Closure

- [x] 3.1 Run strict OpenSpec validation locally and review evidence.
- [x] 3.2 Obtain separate authorization before archive.
