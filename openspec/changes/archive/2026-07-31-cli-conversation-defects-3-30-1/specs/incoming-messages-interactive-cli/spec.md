## ADDED Requirements

### Requirement: CLI bootstrap creates and associates a draft Pedido through the existing HTTP API

After `POST /sessions` returns a `201` with the new session id, the script SHALL issue `POST /pedidos` with body `{"id_session": <session_id>}` and SHALL store the returned `pedido_id` in memory. The script SHALL then issue `PUT /sessions/{session_id}/pedido` with body `{"id_pedido": <pedido_id>}` exactly once. The script SHALL NOT create the pedido through any other code path. The script SHALL NOT pass `id_pedido` to `POST /sessions`. The script SHALL NOT import `sqlalchemy`, `backend.repositories`, `backend.services`, `backend.models`, `backend.alembic`, `backend.dependencies`, `backend.intents`, `backend.llm`, `fastapi`, `uvicorn`, `requests`, `httpx`, `aiohttp`, or `websockets` to perform these calls.

#### Scenario: Successful bootstrap creates session and pedido

- **WHEN** the user enters a valid `comercio_id` and `cliente_id`, the API returns `201` from `POST /sessions`, `201` from `POST /pedidos`, and `200` from `PUT /sessions/{session_id}/pedido`
- **THEN** the script stores the returned `session_id` and `pedido_id` in memory, prints `<session {session_id}>` followed by `<pedido {pedido_id}>`, and enters the read-eval-print loop with the same session id and the pedido associated through the existing HTTP endpoints

#### Scenario: Pedido creation fails with 5xx

- **WHEN** `POST /pedidos` returns a non-2xx status after the session is created
- **THEN** the script closes the session it created via `POST /sessions/{session_id}/cerrar` exactly once, prints the API error detail, and exits non-zero

#### Scenario: Pedido association fails with 4xx

- **WHEN** `PUT /sessions/{session_id}/pedido` returns a non-2xx status after the pedido is created
- **THEN** the script closes the session it created via `POST /sessions/{session_id}/cerrar` exactly once, prints the API error detail, and exits non-zero

#### Scenario: Bootstrap issue order is session-first then pedido then association

- **WHEN** the script runs successfully against the API
- **THEN** the script issues `POST /sessions` exactly once, then `POST /pedidos` exactly once, then `PUT /sessions/{session_id}/pedido` exactly once, before any `POST /comercios/.../incoming-messages` call

### Requirement: CLI conversation exposes a working agregar_producto handler

The script SHALL make it possible for a real `agregar_producto` conversation against a seeded catalog to reach `executed` without manual intervention between the typed line and the resulting `PedidoProducto` row. The script SHALL NOT add a confirmation prompt, a `[y/N]` step, or any additional turn between the user's last refinement message and the executed outcome.

#### Scenario: CLI run ends on executed without an extra turn

- **WHEN** the user runs the CLI, types `quiero dos pizzas` against a five-pizza catalog, then types `la grande`, then types `Pizza de Muzzarella Grande`
- **THEN** the third response printed by the CLI carries `status == "executed"` and the API persists exactly one `PedidoProducto` row with `cantidad == 2` and the seeded `precio_unitario`

### Requirement: CLI cleanup closes only the session it created

The script SHALL continue to issue `POST /sessions/{session_id}/cerrar` exactly once on exit, where `session_id` is the id returned by the script's own `POST /sessions` call. The script SHALL NOT issue `POST /pedidos/{pedido_id}/...` or any pedido-mutation endpoint during cleanup. The pedido is closed transitively via the existing session cascade; the script SHALL NOT close the pedido explicitly.

#### Scenario: Exit cleanup still closes only the session

- **WHEN** the user types `exit` after a successful bootstrap
- **THEN** the script issues `POST /sessions/{session_id}/cerrar` exactly once and no other HTTP request, and exits with status `0`
