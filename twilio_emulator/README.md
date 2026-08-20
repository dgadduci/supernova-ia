# twilio_emulator

Bounded test-only Twilio transport emulator. The package owns no
database, no worker and no NovaOrders business processing — it only
exposes two narrow surfaces:

- `POST /internal/emulator/inbound` — server-to-server authenticated
  control surface used by the admin/pilot panel to drive one synthetic
  inbound into the configured T-C webhook.
- `POST /2010-04-01/Accounts/{account_sid}/Messages.json` — Twilio-shaped
  outbound Messages API used by the existing T-C outbound route when
  the operator enables `TC_TWILIO_PROVIDER_MODE=emulator`.
- `GET /health` — bounded non-secret configuration projection.

## Standalone service contract

The package is intended to run as its own Railway service in `core/test`.
The reproducible definition is intentionally minimal:

| Surface        | Value                                                                                  |
| -------------- | -------------------------------------------------------------------------------------- |
| Start command  | `uvicorn twilio_emulator.app:create_app --factory --host 0.0.0.0 --port $PORT`         |
| Healthcheck    | `GET /health` returning `200` with a non-secret `emulator` projection                  |
| Builder image  | `python:3.13-slim` (matches the repository pinned runtime)                             |
| Build context  | Repository root (the image copies `requirements.txt` and `twilio_emulator/`)           |
| Process model   | Single Uvicorn worker; **no Alembic**, **no NovaOrders worker**, **no DB connection**   |

The start command uses the `--factory` flag so Uvicorn calls
`create_app()` to build a fresh `FastAPI` instance on each boot. The
service must bind Railway's `$PORT`; Railway injects the value at
runtime. The image `EXPOSE 8080` is documentation only — the bound
port is the value of `$PORT`.

The emulator does not require `SUPERNOVA_DATABASE_URL`, `TS_AUTHKEY`
or any of the core service variables. It does not start Tailscale,
does not run `python -m alembic upgrade head`, does not start the
provider worker and does not import `backend.*`.

## Dockerfile

The standalone image lives at `twilio_emulator/Dockerfile`. It installs
the pinned repository dependencies and starts Uvicorn with the factory
flag. The Railway service that consumes this image is configured
elsewhere (see "Railway configuration" below) and must set `$PORT` and
the `EMULATOR_*` variables.

## Healthcheck

The emulator exposes a non-secret health response at `GET /health`.
The response shape is:

```json
{
  "status": "ok",
  "emulator": {
    "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "public_base_url": "https://emulator.example.test",
    "http_port": 9090,
    "capture_retention": 32
  }
}
```

The response intentionally does not include the control token, the
auth token, the T-C webhook URL or any operator-supplied value. The
operator can hit `/health` to confirm the emulator is up without
leaking secrets.

## Required variables

The emulator reads its configuration from environment variables only.
It refuses to start (fail closed) when any required value is missing
or malformed. The operator pins each value externally; **no secret
value belongs in this repository, in this README, or in a log line**.

### Emulator service variables

| Variable                          | Contract                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------- |
| `EMULATOR_CONTROL_TOKEN`          | Opaque server-to-server control/capture token.                                    |
| `EMULATOR_TC_WEBHOOK_URL`         | Exact absolute `https` URL of the T-C inbound webhook.                            |
| `EMULATOR_TWILIO_ACCOUNT_SID`     | Synthetic `AC` + 32 hex characters; shared with T-C and the central dispatcher.    |
| `EMULATOR_TWILIO_AUTH_TOKEN`      | Opaque synthetic token; shared with T-C and the central dispatcher.               |
| `EMULATOR_PUBLIC_BASE_URL`        | Optional. Public `https` URL of this service. The emulator starts without it; when unset, the `/health` projection reports `public_base_url: null` and no other behavior changes. |

The emulator also recognises the same names with the `TWILIO_` prefix
(`TWILIO_EMULATOR_CONTROL_TOKEN`, `TWILIO_EMULATOR_TC_WEBHOOK_URL`,
`TWILIO_EMULATOR_ACCOUNT_SID`, `TWILIO_EMULATOR_AUTH_TOKEN`,
`TWILIO_EMULATOR_PUBLIC_BASE_URL`). The `EMULATOR_*` names take
precedence when both are set; the operator should pin the canonical
`EMULATOR_*` set on the emulator service itself.

### supernova-ia (core) variables

The core service must be configured to drive the emulator. The
operator pins these values on `supernova-ia` (test only):

| Variable                              | Contract                                                                |
| ------------------------------------- | ----------------------------------------------------------------------- |
| `TWILIO_PROVIDER_MODE`                | `emulator` to enable the emulator path; otherwise `real`.               |
| `COMMERCE_ISOLATED_OUTBOUND_ENABLED`  | `1` to opt into the canonical commerce-isolated outbound path.          |
| `TWILIO_EMULATOR_BASE_URL`            | Public `https` URL of the emulator service.                             |
| `TWILIO_EMULATOR_ACCOUNT_SID`         | Same synthetic SID used by the emulator and T-C.                        |
| `TWILIO_EMULATOR_AUTH_TOKEN`          | Same synthetic token used by the emulator and T-C.                      |
| `TWILIO_EMULATOR_CONTROL_TOKEN`       | Same control token used by the emulator to authenticate inbound calls.  |

### tc-comercio-1 (T-C) variables

The T-C service must be configured to accept the synthetic inbound
and to authenticate the outbound Messages API call:

| Variable                              | Contract                                                                |
| ------------------------------------- | ----------------------------------------------------------------------- |
| `TC_TWILIO_PROVIDER_MODE`             | `emulator` to enable the emulator path; otherwise `real`.               |
| `TC_TWILIO_EMULATOR_BASE_URL`         | Public `https` URL of the emulator service.                             |
| `TC_TWILIO_EMULATOR_ACCOUNT_SID`      | Same synthetic SID used by the emulator and the core dispatcher.        |
| `TC_TWILIO_EMULATOR_AUTH_TOKEN`       | Same synthetic token used by the emulator and the core dispatcher.      |

## Local execution

The emulator can be exercised locally without touching any Railway
service. The repository's existing focused tests cover the package
behaviour; the README deliberately does not document a local end-to-end
flow because the approved change scope only requires the reproducible
service definition.

```sh
PYTHONPATH=. \
EMULATOR_CONTROL_TOKEN=control-token \
EMULATOR_TC_WEBHOOK_URL=https://tc.example.test/webhook \
EMULATOR_TWILIO_ACCOUNT_SID=$(python -c 'import secrets; print("AC" + secrets.token_hex(16))') \
EMULATOR_TWILIO_AUTH_TOKEN=$(python -c 'import secrets; print(secrets.token_hex(32))') \
PORT=8080 \
uvicorn twilio_emulator.app:create_app --factory --host 0.0.0.0 --port "$PORT"
```

The command above is for local validation only. **Do not commit any
generated secret to the repository** and do not use the generated
values outside the local process.

## Focused tests

The package ships focused tests that cover the standalone contract
(`twilio_emulator/tests/test_standalone_contract.py`) in addition to
the existing unit tests. Run them locally through the repository's
focused validation command — see the project `AGENTS.md` for the
exact invocation. The standalone-contract tests verify, among other
things:

- `twilio_emulator.app:create_app` is importable and returns a
  `fastapi.FastAPI` instance.
- The factory does not transitively import `backend`, `alembic` or
  `sqlalchemy` (i.e. no NovaOrders database code is loaded).
- `GET /health` returns `200` and the projection does not contain the
  control token or the auth token.

## Railway configuration

This README documents the contract only. The actual Railway service,
variable values, healthcheck timeout and deployment hooks are owned
by the operator and configured through the Railway dashboard / API.
This repository does not include a `railway.toml` for the emulator and
does not bind `twilio-emulator` to the root `railway.toml`; each
service must keep its own deployment manifest.