# Design: Railway test provisioning for the Twilio Emulator

## Topology

```text
Admin/pilot browser
        |
        v
supernova-ia (test, emulator mode)
        |
        | authenticated control request
        v
twilio-emulator (test-only Railway service)
        |
        | signed Twilio-shaped webhook
        v
tc-comercio-1 (test, emulator mode)
        |
        v
NovaOrders ingress -> worker -> outbox -> T-C outbound
        |
        | Twilio-shaped Messages API over HTTPS
        v
twilio-emulator -> synthetic MessageSid
```

The emulator is a separate service because the core process is already
responsible for NovaOrders HTTP traffic and the provider worker. Running the
emulator inside the core process would create a second public application
surface and make service health/rollback ambiguous.

## Standalone process

Use the existing `twilio_emulator.app:create_app` factory with Uvicorn. The
service must bind Railway's `$PORT`, expose `GET /health`, and load only the
explicit `EMULATOR_*` variables. It must not run Alembic, import NovaOrders
database code or start a worker.

The service definition must preserve the repository's pinned Python/runtime
dependencies and must not make the root core `railway.toml` select a second
process. Railway service-level configuration should identify the emulator
start command and health path explicitly.

## Variable contract

| Service | Variable | Contract |
| --- | --- | --- |
| `twilio-emulator` | `EMULATOR_CONTROL_TOKEN` | opaque server-to-server control/capture token |
| `twilio-emulator` | `EMULATOR_TC_WEBHOOK_URL` | exact HTTPS T-C inbound webhook |
| `twilio-emulator` | `EMULATOR_TWILIO_ACCOUNT_SID` | synthetic `AC` plus 32 hex characters |
| `twilio-emulator` | `EMULATOR_TWILIO_AUTH_TOKEN` | opaque synthetic token |
| `twilio-emulator` | `EMULATOR_PUBLIC_BASE_URL` | its public HTTPS URL, if used by the service projection |
| `supernova-ia` | `TWILIO_PROVIDER_MODE` | `emulator` only in `test` |
| `supernova-ia` | `COMMERCE_ISOLATED_OUTBOUND_ENABLED` | `1` in `test` for the canonical path |
| `supernova-ia` | `TWILIO_EMULATOR_BASE_URL` | emulator public HTTPS URL |
| `supernova-ia` | `TWILIO_EMULATOR_ACCOUNT_SID` | exact same synthetic SID |
| `supernova-ia` | `TWILIO_EMULATOR_AUTH_TOKEN` | exact same synthetic token |
| `supernova-ia` | `TWILIO_EMULATOR_CONTROL_TOKEN` | exact same control token used by the emulator |
| `tc-comercio-1` | `TC_TWILIO_PROVIDER_MODE` | `emulator` only in `test` |
| `tc-comercio-1` | `TC_TWILIO_EMULATOR_BASE_URL` | emulator public HTTPS URL |
| `tc-comercio-1` | `TC_TWILIO_EMULATOR_ACCOUNT_SID` | exact same synthetic SID |
| `tc-comercio-1` | `TC_TWILIO_EMULATOR_AUTH_TOKEN` | exact same synthetic token |

The existing real `TWILIO_*` / `TC_TWILIO_*` values remain stored and are not
used while emulator mode is active. No secret value belongs in Git, an
OpenSpec file, a health response or a browser request.

## Activation order

1. Build and deploy the standalone emulator with emulator mode still disabled
   in core/T-C.
2. Verify its health response and configuration projection contain no secret
   values.
3. Configure the emulator's exact T-C webhook URL and shared synthetic
   credentials.
4. Configure T-C emulator mode and verify its health/startup.
5. Configure core emulator mode and the control token.
6. Verify the admin detail page shows the emulator action.
7. Run one controlled active-order E2E test and inspect bounded statuses/events.

If any step fails, stop activation and keep the previous real-mode behavior.

## Failure matrix

| Failure | Expected behavior |
| --- | --- |
| Missing emulator variable | Emulator/T-C/core fail closed at their existing configuration boundary |
| Invalid synthetic SID or mismatched pair | Startup/configuration rejection; no real Twilio fallback |
| Emulator health unavailable | Do not enable core/T-C emulator mode; panel remains hidden |
| Emulator cannot reach T-C webhook | Bounded technical failure; no second pipeline |
| Worker/outbox delay | Admin status remains accepted/pending until the existing worker completes |
| Railway deployment failure | Previous healthy emulator release remains active or service stays disabled; no core/T-C activation |

## Transaction and data boundaries

The emulator retains only its existing bounded in-memory capture. Durable
provider receipt, processing and outbound state remains in NovaOrders. No
migration, fixture mutation or direct database repair is part of provisioning.

## Rollback

The operator can disable emulator mode on core and T-C independently, remove
the test-only emulator variables, and then remove or stop the emulator service.
The rollback must be tested by confirming that the panel hides the emulator
action and that real-mode configuration remains intact without making a real
provider call.
