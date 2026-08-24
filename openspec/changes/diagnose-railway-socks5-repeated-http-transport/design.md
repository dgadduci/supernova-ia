# Design: repeated HTTP transport diagnostic at the local SOCKS5 boundary

## Command

The diagnostic shall be runnable from the repository root inside the Railway
service with:

```text
PYTHONPATH=. python -m backend.scripts.probe_railway_socks5_repeated
```

Arguments:

- `--mode fresh|session`, default `fresh`.
- `--count`, positive integer, default `10`.
- `--connect-timeout-seconds`, positive finite number, default `5`.
- `--read-timeout-seconds`, positive finite number, default `20`.

The operator may run the command once in `fresh` mode and once in `session`
mode. The default `fresh` mode matches the current application shape. The
diagnostic must fail argument validation before creating a request or session.

## Request construction

Load the existing service settings once. Use the configured HTTP target and
configured SOCKS5 proxy as opaque values. Build one fixed, non-business JSON
payload sufficient for the configured HTTP contract, but never print it.

For `fresh`, invoke the top-level `requests.post` independently for each
attempt with the proxy mapping and timeout tuple
`(connect_timeout_seconds, read_timeout_seconds)`.

For `session`, create one `requests.Session` for the entire bounded run and
invoke its `post` method for each attempt with the same proxy mapping and
timeout tuple. Consume the response body before closing it. Do not add an
adapter retry policy or any application-level retry.

The diagnostic must not use `QueryLlm`, because the purpose is to observe the
HTTP call shape immediately below that boundary. It must not import worker,
coordinator, database, Twilio, Tailscale, or Ollama modules.

## Safe result model

Each attempt emits a bounded record with:

- `mode` and `attempt`;
- `inicio_utc`, `fin_utc`, and `duracion_ms`;
- `phase=returned` or `phase=exception`;
- HTTP status when a response exists;
- received-byte count when a response exists;
- a closed `outcome` token;
- a safe exception class/category when an exception occurs.

The suggested closed outcomes are `success`, `empty_response`,
`http_status`, `connect_timeout`, `read_timeout`, `proxy_error`,
`connection_error`, `request_error`, and `configuration_error`.

`success` requires a successful HTTP status and at least one received byte.
The output must not include the response content.

## Exit behavior

- Exit `0` only when all attempts are successful.
- Exit `1` when at least one attempt has a transport or HTTP failure.
- Exit `2` for invalid arguments before any request is made.
- Continue after individual attempt failures.
- Do not sleep, retry, replay, or fall back to a direct request unless the
  approved spec is later expanded.

## Interpretation boundary

The operator compares the two runs:

| Observation | Narrow interpretation |
| --- | --- |
| `fresh` fails and `session` succeeds | Repeated fresh connection setup is implicated; do not yet infer a specific infrastructure cause. |
| Both modes fail with connect/proxy categories | The failure occurs before a usable HTTP response at the local proxy boundary. |
| Both modes fail with read timeout | The request entered the HTTP call but no response completed within the read bound; the destination remains a black box. |
| Both modes succeed repeatedly | This isolated boundary is not reproducing the issue under that run. |

These outcomes are diagnostic evidence only. They must not trigger a runtime
fix automatically.
