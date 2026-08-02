## ADDED Requirements

### Requirement: FastAPI application exposes a health endpoint
The system SHALL expose a `GET /health` endpoint that returns `200 OK` with body `{"status": "ok"}`, regardless of database state.

#### Scenario: Health endpoint is reachable
- **WHEN** a client sends `GET /health`
- **THEN** the server responds with status code `200` and JSON body `{"status": "ok"}`

### Requirement: FastAPI app entrypoint is minimal
The system SHALL provide a `backend/main.py` module that creates the FastAPI application, registers routers, defines application-level configuration, and exposes the `/health` endpoint. The module SHALL NOT contain business logic, database queries, or transaction management.

#### Scenario: App startup
- **WHEN** the application is launched via Uvicorn
- **THEN** the FastAPI instance is created, the `/health` router is registered, and the OpenAPI docs are available at `/docs`

### Requirement: SQLAlchemy session is provided per request via dependency
The system SHALL provide a single SQLAlchemy session per HTTP request through a FastAPI dependency that uses Python's `yield` syntax and closes the session after the request completes.

#### Scenario: Session lifecycle in a normal request
- **WHEN** an endpoint declares the session dependency
- **THEN** the dependency yields a session, the endpoint executes against it, and the session is closed when the request finishes (whether the endpoint succeeded or raised)

### Requirement: Health endpoint does not depend on the database
The system SHALL implement `/health` without opening a SQLAlchemy session or performing any database operation, so liveness probes are independent of database availability.

#### Scenario: Health endpoint returns ok even if the database is unreachable
- **WHEN** the database connection is not available
- **THEN** `GET /health` still returns `200 OK` with body `{"status": "ok"}`
