# Design: repeated QueryLlm diagnostic probe

## Command shape

The script shall be runnable as a module from the repository root:

```text
python -m backend.scripts.probe_query_llm_repeated
```

Arguments:

- `--count`: positive integer, default `10`.
- `--delay-seconds`: non-negative finite number, default `0`.
- `--prompt`: non-empty string, with a deterministic safe diagnostic default.

The script loads settings once, creates one `QueryLlm(settings=settings)` and
calls `request(prompt, correlation_id=...)` sequentially. The delay occurs
only between attempts, never before the first request and never after the
last request.

## Terminal output

For every attempt, print:

- attempt number and UTC start/end timestamps;
- `Mensaje enviado` with the exact prompt;
- `Respuesta recibida` with the parsed dictionary returned by `QueryLlm`;
- elapsed milliseconds and `outcome=success`.

For an error, print the message, `outcome=error` and the safe exception class
name, without exception text or traceback. The output is intentionally visible
to the operator and is not sent to application logs by the script.

## Error and exit semantics

Catch the existing `QueryLlmError` family and unexpected `Exception` per
attempt so one failure does not hide subsequent observations. Do not catch
`BaseException`. Return exit code `1` when at least one attempt failed; return
`0` only when all attempts succeeded. Invalid CLI arguments must fail before
the first request with the standard argument-parser error.

## Isolation rules

The script may import only the existing settings and `QueryLlm` boundary plus
standard-library CLI/time/output helpers. It must not import FastAPI, database
models, repositories, worker modules, T-C adapters or Twilio clients.

The script must not write files, modify environment variables, mutate
business state or alter global timeout/proxy configuration.
