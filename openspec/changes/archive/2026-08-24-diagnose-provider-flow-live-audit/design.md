# Design

## Polling boundary

Use the existing application settings/session factory and ORM models for:

- `RecepcionMensajeProveedor`;
- `ProcesamientoMensajeProveedor`;
- `MensajeProveedorSaliente`.

Join the processing row to its receipt and left-join outbound rows by the
receipt foreign key. The query must be bounded to rows created at or after the
auditor start boundary, with a small operator-configurable clock skew allowance
if the existing timestamp semantics require it. Do not query or hydrate
message body/destination columns.

## Safe snapshot

Each emitted snapshot may contain:

- numeric `recepcion_id`, `procesamiento_id` and `outbox_id`;
- an opaque short fingerprint derived locally from the provider/receipt key;
- receipt/processing/outbox states;
- attempt count and safe failure category/code;
- LLM outcome plus `llm_solicitado_en` and `llm_finalizado_en`;
- bounded outbound row count;
- an observation timestamp.

Do not print raw provider identifiers. Use a stable short hash so successive
polls can be grouped without exposing a SID or message content.

## Change detection

Keep an in-memory map keyed by the numeric receipt id. Emit the first snapshot
and only subsequent snapshots whose safe fields changed. A processed row with
zero outbound rows remains visible as a terminal diagnostic observation. Do not
infer a failure merely because a row is unchanged; report the last observation
and continue polling.

## CLI contract

Provide positive bounded `--interval-seconds` and `--duration-seconds`
arguments, with practical defaults, and allow Ctrl-C to exit zero after printing
a safe termination marker. Invalid arguments fail before opening a database
session. A database read error prints only a closed error category/class and
does not expose exception text or connection details.

The process is intended to run from the `supernova-ia` Railway shell before the
operator sends Twilio messages. It must not invoke `railway`, read service logs,
send HTTP provider requests, or process inbound work.

## Focused validation

Test the query projection with in-memory/fake sessions or existing test seams;
do not require a live database. Cover the no-row baseline, new receipt,
processing transition, LLM timing transition, outbound appearance, zero-row
processed terminal state, filtering, privacy and clean stop. Run focused
pytest, Ruff, compileall, strict OpenSpec validation and `git diff --check`.
