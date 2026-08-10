# Design: controlled readiness-false recovery exercise

1. Verify the production service is online, the provider worker is enabled, and no test receipt is already pending.
2. Run a safe topology check to identify whether Railway uses a loopback or remote path for generate and embedding, without revealing a URL.
3. User stops the actual configured Ollama dependency only after a fresh explicit authorization.
4. Run the controlled readiness probe from Railway. A safe generate failure establishes `ready=False` and skips embedding by contract; if generation passes, restore Ollama and stop the exercise.
5. Restart the Railway application so its newly started worker begins with `ollama_ready=False`.
6. Send one harmless WhatsApp message from the approved test client. During the unavailable window, inspect only receipt/work/outbox state. The receipt may be pending; inbound must not become terminal and must not produce a new outbound.
7. User restores Ollama. Wait for the worker's controlled generate and embedding readiness to pass.
8. Inspect the same receipt through `processed` and one `delivered` outbound. Confirm no duplicate work/outbox rows and bounded attempts.
9. If any invariant fails, restore Ollama, collect safe identifiers/state only, and stop for review. No manual CLI recovery or data edits occur.

The user owns stopping and starting Ollama. Codex provides read-only commands and evaluates evidence; the worker remains the sole owner of processing transactions and retry state.
