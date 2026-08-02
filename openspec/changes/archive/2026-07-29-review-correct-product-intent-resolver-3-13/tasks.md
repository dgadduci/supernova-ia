## 1. Resolver Contract Correction

- [x] 1.1 Update `backend/intents/resolvers/product_intent_resolver.py` to read `producto_presentacion_id` for confident and possible recognizer results while preserving the existing four-key output shape and pure behavior.
- [x] 1.2 Update unavailable and not-found extraction to read `texto_origen`, preserving item order and existing empty-input behavior.
- [x] 1.3 Confirm confident matches take priority over possible candidates and preserve the first match's `cantidad`.

## 2. Verification

- [x] 2.1 Update resolver fixtures in `backend/tests/api_smoke.py` to use the current ProductRecognizer output fields.
- [x] 2.2 Add a regression assertion that confident and possible results work without a legacy `id` field and that `candidate_ids` preserve recognizer order.
- [x] 2.3 Add or update unavailable and not-found tests to verify `texto_origen` is copied in order.
- [x] 2.4 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the resolver checks pass.
- [x] 2.5 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.
