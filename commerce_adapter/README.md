"""Commerce Twilio (T-C) adapter.

This package contains a small, isolated FastAPI service that wraps one
merchant's Twilio account. NovaOrders never receives the merchant's
Twilio webhook directly; the adapter validates the signature,
normalizes the form, signs a canonical event with HMAC and POSTs it
to NovaOrders. NovaOrders replies with ``accepted`` / ``duplicate`` /
``rejected``; the adapter returns the empty TwiML only on the first
two outcomes.

Outbound commands are sent the other way: NovaOrders POSTs a canonical
command to the adapter, the adapter authenticates the request with the
shared installation secret, performs exactly one
``Client.messages.create`` and returns the SID + status.

The adapter is intentionally minimal:

* No NovaOrders backend import.
* No SQLAlchemy.
* No state beyond the configuration loaded at startup.
* No logging of body, phone, token, signature, profile name or
  credential.
* No retries of ``messages.create``; the bounded NovaOrders outbox is
  the single driver of retry/state.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| ``TC_TWILIO_AUTH_TOKEN`` | yes | Merchant Twilio auth token |
| ``TC_TWILIO_ACCOUNT_SID`` | yes | Merchant Twilio account SID |
| ``TC_TWILIO_WEBHOOK_BASE_URL`` | yes | Exact public URL Twilio is configured to POST to |
| ``TC_NOVAORDERS_INGRESS_URL`` | yes | Internal ingress URL of NovaOrders |
| ``TC_INSTALLATION_ID`` | yes | Opaque installation id issued by the NovaOrders provisioning CLI |
| ``TC_INSTALLATION_SECRET`` | yes | Shared secret issued by the NovaOrders provisioning CLI |
| ``TC_COMERCIO_ID`` | yes | Internal comercio PK for this installation |
| ``TC_TWILIO_SENDER_E164`` | yes | Canonical merchant sender E.164 used in ``messages.create`` |
| ``TC_HTTP_TIMEOUT_SECONDS`` | no | NovaOrders HTTP timeout (default 5) |

## Endpoints

* ``GET /health`` — public health probe.
* ``POST /webhooks/twilio/whatsapp/inbound`` — merchant Twilio webhook
  (Twilio's ``application/x-www-form-urlencoded``).
* ``POST /internal/commands/send-message`` — authenticated outbound
  command from NovaOrders.

## Local run

```bash
PYTHONPATH=commerce_adapter \
TC_TWILIO_AUTH_TOKEN=*** \
TC_TWILIO_ACCOUNT_SID=*** \
TC_TWILIO_WEBHOOK_BASE_URL=https://example.test \
TC_NOVAORDERS_INGRESS_URL=https://example.test \
TC_INSTALLATION_ID=$(printf 'a%.0s' {1..24}) \
TC_INSTALLATION_SECRET=*** \
TC_COMERCIO_ID=7 \
TC_TWILIO_SENDER_E164=+15555555555 \
venv/bin/uvicorn commerce_adapter.app.main:app --host 0.0.0.0 --port 8000
```
"""
__all__: list[str] = []