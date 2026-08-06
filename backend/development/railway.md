# Railway deployment runbook

## Scope

This runbook deploys the existing FastAPI service and its existing Alembic
history. It does not seed production data, create a worker, schedule outbound
delivery, create a Twilio number, or change application behavior.

## One-time Railway configuration

1. Create a Railway project and a PostgreSQL service.
2. Create one web service from this repository. Railway detects
   `railway.toml` at the repository root.
3. In the web-service variables, create `SUPERNOVA_DATABASE_URL` as a Railway
   reference to that PostgreSQL service's `DATABASE_URL` variable. Do not copy
   its resolved value into the repository, a shell history, or this document.
4. Set the web service's public domain. Its HTTPS origin, without a trailing
   webhook path, is the value for `TWILIO_WEBHOOK_BASE_URL`.
5. Add the required Twilio variables only when enabling the corresponding
   behavior:

   - inbound/callback validation: `TWILIO_AUTH_TOKEN`,
     `TWILIO_WEBHOOK_BASE_URL`;
   - explicit outbound dispatch: `TWILIO_ACCOUNT_SID`,
     `TWILIO_OUTBOUND_SENDER_E164`, `TWILIO_CALLBACK_STATUS_URL`, and the
     existing optional retry settings.

6. Configure the existing Ollama variables only after the Railway service can
   reach the supplied host through an approved secure network path:

   - `LLM_URL=http://100.113.65.40:11434/api/generate`
   - `LLM_MODEL=qwen-27b-coding:latest`
   - `EMBEDDING_URL=http://100.113.65.40:11434/api/embed`
   - `EMBEDDING_MODEL=all-minilm:latest`
   - `EMBEDDING_DIMENSION=384`

   Do not expose the Ollama host publicly, add a proxy/tunnel, or substitute a
   model as part of this subphase. The address and model names are deployment
   configuration, not values to log in application output.

## Deployment lifecycle

`railway.toml` uses Railpack and has these fixed lifecycle steps:

1. Before traffic: the pre-deploy command checks that
   `SUPERNOVA_DATABASE_URL` exists and runs `python -m alembic upgrade head`.
   A migration failure fails the deployment.
2. Start: the application again checks that the database variable exists, then
   starts `backend.main:app` with Uvicorn on Railway's injected `PORT`.
3. Activation: Railway calls `GET /health` and only activates the deployment
   after it returns `200` within 100 seconds.

The `/health` route is a liveness check. The successful release migration is
the database connectivity/schema gate; no request handler and no application
startup path runs migrations.

## Controlled verification

After the deployment is active, verify the following without printing
credentials, database URLs, message bodies, signatures, embeddings, or
generated text:

1. Railway build and pre-deploy logs show a successful release.
2. The public `GET /health` returns `200` with `{"status":"ok"}`.
3. Run `python -m alembic current` from a Railway shell or an approved
   one-off environment using the same referenced database configuration; it
   must report the repository head revision.
4. From the deployed service's approved network path, make bounded probes to
   the configured Ollama generate and embed endpoints. Verify only successful
   contract status and the 384 embedding dimension; do not retain prompt,
   response, or vector data in logs.
5. Only after steps 1–4 pass, configure Twilio inbound URL
   `/webhooks/twilio/whatsapp` and status-callback URL
   `/webhooks/twilio/whatsapp/status`, then perform a controlled signed test.

If an Ollama probe cannot reach the supplied host, the deployment is
infrastructure-ready but not approved for real business messages. Leave the
production WhatsApp number unpointed and record the gate; do not create a
fallback path.

## Outbound dispatch

Phase 5.6's outbox dispatcher remains manually invoked and bounded. Do not
configure it as a Railway cron job, web route, release command, or long-lived
worker. Run it only through the existing explicit CLI with its configured
per-pass limit after outbound Twilio settings are present.

## Rollback

Use Railway's deployment rollback or disable the web service to stop traffic.
Do not automatically downgrade PostgreSQL. Before any Alembic downgrade,
inspect whether production data exists and obtain explicit approval for a
specific rollback plan.
