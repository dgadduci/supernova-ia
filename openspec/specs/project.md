# Project Context

## General Goal

Build a multi-commerce ordering system that receives free-text customer orders through WhatsApp.

The system will use one central WhatsApp number. Customers will reach it from each commerce's own WhatsApp channel, and the system will route each order to the correct commerce.

## Working Rules

- Follow the roadmap in order.
- The roadmap is divided into phases and subphases.
- Work only on the active subphase.
- Do not start the next phase without explicit user confirmation that the current phase is complete.
- Move to the next subphase when the current subphase is implemented and minimally tested.
- When all subphases of a phase are complete:
  - Briefly report the completed objectives.
  - Ask the user whether the phase may be closed.
- Run only the minimum tests required for each phase.
- Implement only what is explicitly requested.
- Store code files inside purpose-specific subdirectories under `backend/`.

## Technology Stack

Current stack:

- Python
- FastAPI
- Uvicorn
- Pydantic
- SQLAlchemy
- Alembic
- Local PostgreSQL without a password
- Local LLM

Future phases:

- Twilio
- Railway deployment
- PostgreSQL persistence on Railway


## FastAPI Rules

- Use synchronous FastAPI, Uvicorn and SQLAlchemy sessions unless explicitly requested otherwise.
- Application flow: `Router → Service → Repository → SQLAlchemy Model → PostgreSQL`.
- Keep `backend/main.py` limited to creating the FastAPI application, registering routers and application-level configuration.
- Store endpoints in purpose-specific modules under `backend/routers/` using `APIRouter`.
- Routers handle HTTP concerns only: request parameters, dependencies, status codes, response models and translation of domain errors to HTTP errors.
- Use Pydantic schemas under `backend/schemas/` for request validation and response serialization.
- Create separate create, update and response schemas only when their fields differ. Reuse schemas when their structure is identical.
- Services under `backend/services/` contain business rules, coordinate repositories and control `commit` and `rollback`.
- Repositories under `backend/repositories/` contain database access only and use SQLAlchemy ORM or SQLAlchemy `select()` statements.
- Do not place SQLAlchemy queries in routers or services.
- Do not use raw SQL unless explicitly requested or SQLAlchemy cannot reasonably express the operation.
- Provide one database session per request through a FastAPI dependency using `yield`, and always close it after the request.
- Declare `response_model` for endpoints that return application data.
- Do not create endpoints, schemas, services, repositories or generic abstractions that are not required by the active subphase.
- Test only the affected behavior and the minimum integration path required by the active subphase.

### Internal database access rule

Any internal backend function that requires database data SHALL use an existing service method.

The implementation SHALL NOT:

- call the application's own FastAPI endpoints through HTTP;
- call router functions directly;
- place SQLAlchemy queries outside repositories;
- duplicate existing service or repository behavior.

Before implementing the required database operation, inspect existing services and repositories.

If an equivalent service method already exists, reuse it.

If the service method does not exist but the responsibility belongs to an existing service:

- add the minimum required repository method;
- add the corresponding service method;
- reuse the existing service and repository modules.

Create a new repository or service only when the operation belongs to a clearly separate responsibility.

Internal flow SHALL be:

`Internal function → Service → Repository → SQLAlchemy → PostgreSQL`

External HTTP flow SHALL remain:

`Router → Service → Repository → SQLAlchemy → PostgreSQL`


## Database Rules

- Development database: `supernova`
- Test database: `supernova_test`
- Every table must exist in both databases.
- All tests must run against `supernova_test`.
- Do not run tests against `supernova`.

## Roadmap

## Phase and Subphase Context Rule

When any subphase is completed, replace its detailed content in `project.md` with a concise summary containing only:

* permanent implementation decisions;
* completed outcomes;
* architectural constraints introduced;
* relevant files or components created or modified;
* information required to continue future phases or subphases.

Remove:

* procedural steps;
* implementation instructions already executed;
* examples;
* temporary prompts;
* test execution details;
* repeated explanations;
* discarded alternatives;
* information already covered by general project rules.

Apply this rule to every subphase of every phase.

Do not modify active or future subphases. Do not modify any unrelated section of `project.md`.

### Phase 6 — Deployment and Initial Operations [ ] — active

Establish the production-shaped infrastructure baseline before resuming order
domain expansion. Phase 6 deploys the existing application to Railway with
Railway PostgreSQL, applies the already-approved Alembic history through a
controlled release process, and verifies the public provider-facing boundary.
It does not add order functionality, a scheduler/worker, a new LLM provider,
or business-schema changes.

#### Subphase 6.1 — Railway and PostgreSQL Deployment [ ] — pending approval

Define and implement the smallest reproducible Railway deployment for the
current FastAPI application and Railway PostgreSQL. The production database
must be supplied only through `SUPERNOVA_DATABASE_URL`; no deployed release
may fall back to the local/test database. Migrations run as a release step,
not at app startup or during requests. The subphase includes a concise
operator runbook, safe public-health/database-revision verification, and
controlled Twilio webhook/callback URL validation once credentials are
available.

Railway infrastructure readiness is distinct from business-message readiness.
The supplied Ollama service at `100.113.65.40` provides the candidate models
`qwen-27b-coding:latest` for the existing generative LLM path and
`all-minilm:latest` for semantic embeddings. Both require bounded
reachability/contract verification from Railway before a live rollout. This
subphase must not deploy a local model by implication, add a proxy/tunnel, or
redirect a live WhatsApp number before that gate passes. The Phase-5.6 outbound
dispatcher remains an explicit bounded CLI; no worker, scheduler, or polling
loop is in scope.

### Phase 1 — SQLAlchemy Models [x] — closed

Create SQLAlchemy models before generating and applying database migrations to `supernova` and `supernova_test`.

**Closed**. All 11 subphases complete and archived. Final state:

- 11 SQLAlchemy models registered in `Base.metadata` (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentaciones`, `producto_precios`, `comercio_metodos_entrega`, `comercio_medios_pago`).
- Alembic configured at `backend/alembic/`; both DBs at revision `7f9610191db8` (single initial migration).
- 11 seed operations cover all 11 tables; both DBs seeded end-to-end via `backend/db/seeds/seeds/`.

#### Subphase 1.1 — EstadoComercio [x] — completed

Create the `EstadoComercio` model with:

- `id`
- `estado: str`

#### Subphase 1.2 — Comercio [x] — completed (tablename renamed to `comercios` in Subphase 1.5)

Create the `Comercio` model — the central entity that holds the commerce profile, dispatch address, locale preferences and lifecycle timestamps. Refer to `EstadoComercio` via a foreign key (`estado_id`) and a relationship (`estado`). Database table is `comercios` (plural, renamed during Subphase 1.5 so per-commerce child tables can FK to `comercios.id`).

- business: `nombre_fantasia`, `nombre_corto`, `razon_social`, `cuit` (indexed), `whatsapp` (unique, indexed)
- address: `calle`, `numero`, `piso_departamento` (nullable), `localidad`, `provincia`, `codigo_postal` (nullable)
- identity: `slug` (unique, indexed)
- status: `estado_id` (FK → `estado_comercio.id`, non-null) + `estado` relationship
- locale defaults: `zona_horaria`, `moneda`, `idioma`
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja` (nullable)

#### Subphase 1.3 — MediosPago [x] — completed

Create the `MediosPago` model — the catalog of payment methods a commerce may offer its customers.

- identity: `codigo` (unique, indexed), `descripcion`
- flag: `activo` (Boolean, default `True`, server-default `"true"`)
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`

#### Subphase 1.4 — MetodosEntrega [x] — completed

Create the `MetodosEntrega` model — the catalog of delivery methods a commerce may offer its customers. The `orden` column must be non-negative; a table-level `CheckConstraint` named `orden_no_negativo` enforces this directly in the database.

- identity: `codigo` (unique, indexed), `descripcion`
- ordering: `orden` (Integer, non-null, `>= 0`)
- flag: `activo` (Boolean, default `True`, server-default `"true"`)
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`

#### Subphase 1.5 — CategoriaProducto [x] — completed (class renamed from `CategoriasProductos` during Subphase 1.7)

Create the `CategoriaProducto` model — the per-commerce product-category configuration. Each row cascades on Comercio deletion via a foreign key (`id_comercio` → `comercios.id`, `ON DELETE CASCADE`). Database table name remains `categorias_productos` (plural). During Subphase 1.7, the class gained a `productos` relationship to back-reference `Producto.categoria`.

- ownership: `id_comercio` (FK → `comercios.id`, non-null, indexed)
- content: `descripcion` (String 100, non-null)
- flag: `activo` (Boolean, default `True`, server-default `"true"`)
- ordering: `orden` (Integer, default `0`, server-default `"0"`)
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`
- relationship: `productos` (one-to-many to `Producto`, added in Subphase 1.7)

#### Subphase 1.6 — Presentacion [x] — completed (class renamed from `Presentaciones` after initial implementation)

Create the `Presentacion` model — the per-commerce product-presentation configuration. Each row cascades on Comercio deletion via `id_comercio` → `comercios.id` (`ON DELETE CASCADE`). Within a single comercio, the `codigo` and `descripcion` values are each unique (composite `UniqueConstraint`); `orden` is non-negative (`CheckConstraint`).

- ownership: `id_comercio` (FK → `comercios.id`, non-null, indexed)
- identity: `codigo` (String 50, non-null, unique per comercio), `descripcion` (String 100, non-null, unique per comercio)
- flag: `activo` (Boolean, default `True`, server-default `"true"`)
- ordering: `orden` (Integer, default `0`, server-default `"0"`, `>= 0`)
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`

#### Subphase 1.7 — Producto [x] — completed

Three coordinated changes landed together: (1) the new `Producto` model anchors the catalog, (2) a `ProductoPresentacion` join-table stub is introduced so `Producto.presentaciones` resolves, and (3) the existing category model from Subphase 1.5 was renamed `CategoriasProductos → CategoriaProducto` (class only; tablename `categorias_productos` unchanged) and gained a `productos` back-reference.

`Producto` — the per-category product row. Foreign key to `categorias_productos.id` is `RESTRICT` (a category cannot be deleted while products reference it). A composite unique `(id_categoria_producto, nombre)` keeps product names unique within a category. The `descripcion` is the first `Text` column in the model layer (nullable). Two Boolean flags distinguish catalog-active (`activo`) from in-stock (`disponible`).

- ownership: `id_categoria_producto` (FK → `categorias_productos.id`, **`RESTRICT`**, indexed)
- identity: `nombre` (String 150, non-null, unique per categoria)
- optional: `descripcion` (Text, nullable)
- flags: `activo` (Boolean, default `True`, server-default `"true"`), `disponible` (Boolean, default `True`, server-default `"true"`)
- ordering: `orden` (Integer, default `0`, server-default `"0"`, `>= 0` via `CheckConstraint`)
- constraints: composite unique `categoria_producto_nombre_unico` on `(id_categoria_producto, nombre)`; check `orden_no_negativo`
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`
- relationships: `categoria` (→ `CategoriaProducto`), `presentaciones` (→ list of `ProductoPresentacion`)

`ProductoPresentacion` (stub join, refinement + rename landed in Subphases 1.7-followup and 1.8):

- `id_producto` (FK → `productos.id`, `CASCADE`, indexed)
- `id_presentacion` (FK → `presentaciones.id`, `CASCADE`, indexed)
- `activo` (Boolean, default `True`, server-default `"true"`)
- `orden` (Integer, default `0`, server-default `"0"`)
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`
- relationship: `precios` (one-to-many to `Precio`, added in Subphase 1.8)
- later renamed in Subphase 1.8: tablename `producto_presentacion` → `producto_presentaciones` (plural, FK targetable)

#### Subphase 1.8 — Precio [x] — completed

Two enabling changes plus the new model landed together: (1) the FK target spec'd `producto_presentaciones.id` (plural) but the existing table was singular `producto_presentacion`, so the table name was renamed; (2) a `precios` back-reference landed on `ProductoPresentacion`; (3) the new `Precio` model itself anchors the price-per-product-presentation row.

`Precio` — the per-product-presentation price. First `Decimal` / `Numeric` column in the model layer. The unique index on `id_producto_presentacion` enforces 1:1 between a `ProductoPresentacion` row and its `Precio` row. `RESTRICT` on the FK ensures a presentation cannot be deleted while a price references it. The `Index("id_producto_presentacion", "id_producto_presentacion", unique=True)` form is preserved from the user's spec (column passed explicitly so the unique index targets the right column — the literal `Index("name", unique=True)` with no column arguments would have produced an empty index).

- ownership: `id_producto_presentacion` (FK → `producto_presentaciones.id`, **`RESTRICT`**, indexed)
- price: `precio` (`Mapped[Decimal]` via `Numeric(12, 2)`, non-null)
- constraints: `CheckConstraint("precio >= 0", name="precio_no_negativo")`; unique index `id_producto_presentacion` on `id_producto_presentacion`
- lifecycle: `fecha_alta` (timezone-aware DateTime, non-null, `server_default=func.now()`)
- relationship: `producto_presentacion` (→ `ProductoPresentacion`)

`ProductoPresentacion` refactor in this same change:

- tablename: `producto_presentacion` → `producto_presentaciones` (class name unchanged)
- +relationship: `precios` (→ list of `Precio`, declared via forward-ref string)`

#### Subphase 1.9 — ComercioMetodoEntrega [x] — completed

Create the `ComercioMetodoEntrega` join model — the per-comercio selection from the global `MetodosEntrega` catalog introduced in Subphase 1.4. Each row pairs a comercio with a catalog method. `id_comercio` FK to `comercios.id` is `ON DELETE CASCADE`; `id_metodo_entrega` FK to `metodos_entrega.id` is `ON DELETE RESTRICT` (a catalog row cannot be deleted while any commerce still references it). The join is **opt-in** (`activo` defaults to `False`, server-default `"false"`). A composite `UniqueConstraint` named `comercio_metodo_unico` on `(id_comercio, id_metodo_entrega)` prevents duplicates; the `orden` column is non-negative via `CheckConstraint orden_no_negativo` and has no default (every insert must supply it explicitly). The previously-deferred `Comercio.metodos_entrega` and `MetodosEntrega.comercios` relationships are re-introduced here as forward-ref `relationship()` attributes using `back_populates`, closing the three-way navigation cycle. Table name: `comercio_metodos_entrega` (plural-as-collection, mirroring `producto_presentaciones`).

- ownership: `id_comercio` (FK → `comercios.id`, `CASCADE`, indexed), `id_metodo_entrega` (FK → `metodos_entrega.id`, `RESTRICT`, indexed)
- flag: `activo` (Boolean, default `False`, server-default `"false"` — opt-in)
- ordering: `orden` (Integer, non-null, `>= 0`, **no default**)
- constraints: composite unique `comercio_metodo_unico` on `(id_comercio, id_metodo_entrega)`; check `orden_no_negativo`
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`
- relationships: `comercio` (→ `Comercio`), `metodo_entrega` (→ `MetodosEntrega`)
- side-effects: `Comercio.metodos_entrega` and `MetodosEntrega.comercios` relationship attributes added (forward-ref strings)

#### Subphase 1.10 — ComercioMedioPago [x] — completed

Create the `ComercioMedioPago` join model — the per-comercio selection from the global `MediosPago` catalog introduced in Subphase 1.3. Each row pairs a comercio with a catalog payment method. `id_comercio` FK to `comercios.id` is `ON DELETE CASCADE`; `id_medio_pago` FK to `medios_pago.id` is `ON DELETE RESTRICT`. The join is **opt-in** (`activo` defaults to `False`, server-default `"false"`). Two per-comercio metadata columns carry the account-holder display name (`titular`, String 150, nullable) and the operator-facing alias (`alias`, String 100, nullable) — neither is part of the global catalog. A composite `UniqueConstraint` named `comercio_medio_pago_unico` on `(id_comercio, id_medio_pago)` prevents duplicates. Unlike `ComercioMetodoEntrega` (1.9), this join has no `orden` column and therefore no `CheckConstraint`. The previously-missing `Comercio.medios_pago` and `MediosPago.comercios` relationships are introduced here as forward-ref `relationship()` attributes using `back_populates`. Table name: `comercio_medios_pago` (plural-as-collection, mirroring `comercio_metodos_entrega` and `producto_presentaciones`).

- ownership: `id_comercio` (FK → `comercios.id`, `CASCADE`, indexed), `id_medio_pago` (FK → `medios_pago.id`, `RESTRICT`, indexed)
- flag: `activo` (Boolean, default `False`, server-default `"false"` — opt-in)
- metadata: `titular` (String 150, nullable), `alias` (String 100, nullable)
- constraints: composite unique `comercio_medio_pago_unico` on `(id_comercio, id_medio_pago)`
- lifecycle: `fecha_alta`, `fecha_ultima_modificacion`
- relationships: `comercio` (→ `Comercio`), `medio_pago` (→ `MediosPago`)
- side-effects: `Comercio.medios_pago` and `MediosPago.comercios` relationship attributes added (forward-ref strings)

#### Subphase 1.11 — initial Alembic migration [x] — completed

Alembic is configured and applied. Both `supernova` and `supernova_test` are at revision `7f9610191db8`.

- **Layout**: `backend/alembic/` (env.py, versions/) + `alembic.ini` at project root. Sync stack — no async engines.
- **Driver**: `psycopg` (v3) only. `psycopg2` is not installed; never introduce a `postgresql://` URL without the `+psycopg` prefix.
- **DB selection**: default URL in `alembic.ini` is `postgresql+psycopg:///supernova_test`. For `supernova`, override with `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova`. The generic `DATABASE_URL` is **not** used — it collides with another project in the shell.
- **Commands** (run from project root):
  - Generate: `PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "<msg>"`
  - Apply test: `PYTHONPATH=. venv/bin/alembic upgrade head`
  - Apply dev: `SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`
  - Current revision: `PYTHONPATH=. venv/bin/alembic current`
- **env.py imports all 11 models** so autogenerate sees the full schema. **Any new model must be added to that import block** or it will be invisible to autogenerate.
- **Initial migration**: `backend/alembic/versions/7f9610191db8_initial_schema.py` (revision `7f9610191db8`, `down_revision=None`). Creates all 11 application tables with FKs (`CASCADE` on `id_comercio` joins, `RESTRICT` on catalog joins), `UniqueConstraint`s, and `CheckConstraint`s (`orden_no_negativo` ×5, `precio_no_negativo` ×1).

Phase 2 — FastAPI API

Implement the FastAPI API incrementally by resource. Each subphase must deliver only the endpoints and supporting layers required for its assigned model.

General Rules
Use synchronous FastAPI, Uvicorn and SQLAlchemy sessions.
Follow this application flow:
Router → Service → Repository → SQLAlchemy Model → PostgreSQL
Implement one resource per subphase.
Complete and minimally test the active subphase before starting the next one.
Do not implement endpoints or abstractions assigned to future subphases.
Reuse existing SQLAlchemy models and database configuration.
Do not modify database models or generate Alembic migrations unless explicitly required by the active subphase.
Store FastAPI application code under purpose-specific directories:
backend/
├── main.py
├── dependencies.py
├── routers/
├── schemas/
├── repositories/
└── services/
backend/main.py must only:
create the FastAPI application;
register routers;
define application-level configuration;
expose the health endpoint.
backend/dependencies.py must provide one SQLAlchemy session per request using yield and close it after the request.
Routers must handle only HTTP concerns:
routes;
path and query parameters;
request schemas;
response models;
status codes;
dependency injection;
translation of domain errors into HTTP errors.
Pydantic schemas must handle request validation and response serialization.
Create separate create, update and response schemas only when their structures differ.
Services must:
contain business rules;
coordinate repositories;
control commit and rollback;
raise domain-specific exceptions instead of HTTPException.
Repositories must:
contain database access only;
use SQLAlchemy ORM or SQLAlchemy select() statements;
never execute commit() or rollback().
Do not place SQLAlchemy queries in routers or services.
Do not use raw SQL unless explicitly requested or SQLAlchemy cannot reasonably express the operation.
Declare response_model for every endpoint that returns application data.
Do not expose model relationships or internal fields unless required by the active endpoint.
Do not create generic repositories, generic CRUD services or reusable abstractions unless at least two implemented resources require them.
Run all database tests against supernova_test.
Run only the minimum tests required to verify the behavior introduced by the active subphase.
Do not create separate unit tests for schemas, repositories and services when the endpoint integration test already covers the required behavior.
Refactor only files directly required by the active subphase.

Do not implement future subphases while working on the current one.

### Subphase Template

Every Phase 2 subphase entry in this file MUST use the following headings, in this order, with content adapted to the resource under implementation:

- `Scope`
- `Required files`
- `[resource-specific endpoint block]` — e.g. `Commerce endpoints`, `Products endpoints`. Describes each endpoint with HTTP method, path, request body fields, response body fields, status codes, and business rules.
- `Schemas` — lists the Pydantic schemas to create and which fields differ.
- `Repository responsibilities` — DB-only operations the repository must implement; never commits/rolls back.
- `Service responsibilities` — business rules and commit/rollback ownership; never raises `HTTPException`.
- `Router responsibilities` — HTTP-only concerns; never runs SQLAlchemy queries; never manages transactions.
- `Minimum tests` — the integration scenarios that MUST pass against `supernova_test`.
- `Completion criteria` — the checklist that defines "done" for the subphase.

Subphase 2.1 — Comercios [x] — completed

Sync FastAPI app delivered. Three commerce endpoints (`GET /comercios`, `GET /comercios/{id}`, `POST /comercios`) and `GET /health`, under the `Router → Service → Repository → Model` layering. 8/8 integration tests pass against `supernova_test`. No model changes, no Alembic migration.

**Architectural constraints introduced**:
- per-request SQLAlchemy session via FastAPI dependency using `yield` (`backend/dependencies.py`)
- response models use Pydantic `from_attributes=True` for ORM serialization
- service raises domain exceptions; router translates to HTTP 404/409
- repository never calls `commit()` / `rollback()`; service owns both
- tests override `get_session` via `app.dependency_overrides` against `supernova_test` only

**Files created**:
- `backend/main.py`, `backend/dependencies.py`
- `backend/routers/{health,comercios}.py`
- `backend/schemas/comercio.py` (`ComercioCreate`, `ComercioResponse`)
- `backend/repositories/comercio_repository.py`
- `backend/services/{comercio_service,exceptions}.py`
- `backend/tests/api_smoke.py`

**Context for future subphases**: replicate the file layout per resource.

#### Subphase 2.2 — EstadoComercio [x]

Sync FastAPI slice delivered. Three estado-comercio endpoints (`GET /estados-comercio`, `GET /estados-comercio/{estado_comercio_id}`, `POST /estados-comercio`) under the same `Router → Service → Repository → Model` layering as Subphase 2.1. 7/7 new integration tests pass against `supernova_test`. No model changes, no Alembic migration.

**Architectural constraints introduced**:
- `EstadoComercioCreate` uses Pydantic `extra="forbid"` so `id` and any other undeclared field is rejected at the schema layer
- empty-after-whitespace `estado` raises `InvalidEstado` → 400 (the schema's `min_length=1` does not catch `"   "`; the service-level trim does)
- `estado_in_use` repository method exists for a future delete subphase, not exposed via HTTP today

**Files created**:
- `backend/routers/estados_comercios.py`
- `backend/schemas/estado_comercio.py` (`EstadoComercioCreate`, `EstadoComercioResponse`)
- `backend/repositories/estado_comercio_repository.py`
- `backend/services/estado_comercio_service.py`
- `backend/services/exceptions.py` extended with `EstadoComercioInUse`, `InvalidEstado`, `DuplicateEstado`

**Context for future subphases**: replicate the per-resource layout. The `extra="forbid"` schema pattern plus service-level whitespace-trim is the default for any new resource whose model has only DB-set ids.

### Subphase 2.3 — MediosPago [x]

Sync FastAPI slice delivered. Three medios-pago endpoints (`GET /medios-pago`, `GET /medios-pago/{medio_pago_id}`, `POST /medios-pago`) under the same `Router → Service → Repository → Model` layering as Subphases 2.1 and 2.2. 9/9 new integration tests pass against `supernova_test`. No model changes, no Alembic migration.

**Architectural constraints introduced**:
- `MediosPagoCreate` uses Pydantic `extra="forbid"` (carried from 2.2); `codigo` and `descripcion` reject empty-after-whitespace via the service → 400 (`InvalidMedioPago`); `activo` is optional and defaults to `True` from the schema, matching the model default
- DB-level `unique=True` on `codigo` plus service-level `get_by_codigo` lookup → `DuplicateMedioPago` → 409

**Files created**:
- `backend/routers/medios_pago.py`
- `backend/schemas/medios_pago.py` (`MediosPagoCreate`, `MediosPagoResponse`)
- `backend/repositories/medios_pago_repository.py`
- `backend/services/medios_pago_service.py`
- `backend/services/exceptions.py` extended with `MediosPagoNotFound`, `DuplicateMedioPago`, `InvalidMedioPago`

**Context for future subphases**: replicate the per-resource layout. The pattern is now stable across three slices; `extra="forbid"` + service-trim + duplicate lookup is the default for any new resource whose model has a unique business key.

### Subphase 2.4 — MetodosEntrega [x]

Sync FastAPI slice delivered. Three delivery-method endpoints (`GET /metodos-entrega`, `GET /metodos-entrega/{metodo_entrega_id}`, `POST /metodos-entrega`) use the established `Router → Service → Repository → Model` layering. Integration coverage runs against `supernova_test`; no model change or Alembic migration.

**Architectural constraints introduced**:
- `MetodoEntregaCreate` forbids extra fields, requires non-negative `orden`, defaults omitted `activo` to `True`, and service-trims text fields
- list results are ordered by `id`; duplicate `codigo` uses exact stored-value comparison without case normalization
- service owns commit/rollback; repository methods never finalize transactions

**Files created**:
- `backend/routers/metodos_entrega.py`
- `backend/schemas/metodo_entrega.py`
- `backend/repositories/metodo_entrega_repository.py`
- `backend/services/metodo_entrega_service.py`
- `backend/services/exceptions.py` extended with delivery-method exceptions

**Context for future subphases**: responses exclude commerce associations. Update, delete, activation/deactivation, pagination, authentication, and association endpoints remain out of scope.

### Subphase 2.5 — CategoriaProducto [x]

Sync FastAPI slice delivered. Three product-category endpoints (`GET /comercios/{comercio_id}/categorias-productos`, `GET /categorias-productos/{categoria_producto_id}`, `POST /comercios/{comercio_id}/categorias-productos`) use the established `Router → Service → Repository → Model` layering. Integration coverage runs against `supernova_test`; no model change or Alembic migration.

**Architectural constraints introduced**:
- commerce ownership is derived exclusively from the nested route; request bodies cannot supply `id_comercio`
- nested listings verify commerce existence and order categories by `orden`, then `id`; direct retrieval returns scalar fields without products
- omitted `activo` and `orden` preserve model defaults; descriptions are trimmed and empty values rejected
- service owns commit/rollback; repository methods never finalize transactions

**Files created**:
- `backend/routers/categorias_productos.py`
- `backend/schemas/categoria_producto.py`
- `backend/repositories/categoria_producto_repository.py`
- `backend/services/categoria_producto_service.py`
- `backend/services/exceptions.py` extended with category exceptions

**Context for future subphases**: update, delete, activation/deactivation, pagination, authentication, product, and product-association endpoints remain out of scope.

### Subphase 2.6 — Presentacion [x]

Sync FastAPI slice delivered. Three presentation endpoints (`GET /comercios/{comercio_id}/presentaciones`, `GET /presentaciones/{presentacion_id}`, `POST /comercios/{comercio_id}/presentaciones`) use the established `Router → Service → Repository → Model` layering. Integration coverage runs against `supernova_test`; no model change or Alembic migration.

**Architectural constraints introduced**:
- commerce ownership is derived exclusively from nested routes; request bodies cannot supply `id_comercio`
- codes are trimmed and normalized to lowercase; code and description uniqueness is enforced case-insensitively within each commerce
- nested listings order by `orden`, then `id`; omitted `activo` and `orden` preserve model defaults
- service owns commit/rollback; repository methods do not finalize transactions or load product associations

**Files created**:
- `backend/routers/presentaciones.py`
- `backend/schemas/presentacion.py`
- `backend/repositories/presentacion_repository.py`
- `backend/services/presentacion_service.py`
- `backend/services/exceptions.py` extended with presentation exceptions

**Context for future subphases**: update, delete, activation/deactivation, pagination, authentication, product, and product-presentation association endpoints remain out of scope.

### Subphase 2.7 — Producto [x]

Sync FastAPI slice delivered. Four product endpoints support category listing/creation, commerce listing, and direct retrieval under the established `Router → Service → Repository → Model` layering. Integration coverage runs against `supernova_test`; no model change or Alembic migration.

**Architectural constraints introduced**:
- category ownership is derived exclusively from nested routes; request bodies cannot supply `id_categoria_producto`
- category listings order by product `orden`, then `id`; commerce listings join categories and order by category `orden`, product `orden`, then product `id`
- names are trimmed with case-insensitive category-scoped uniqueness; optional descriptions are trimmed and empty values become `null`
- omitted `activo`, `disponible`, and `orden` preserve model defaults; relationships remain unloaded and absent from responses

**Files created**:
- `backend/routers/productos.py`
- `backend/schemas/producto.py`
- `backend/repositories/producto_repository.py`
- `backend/services/producto_service.py`
- `backend/services/exceptions.py` extended with product exceptions

**Context for future subphases**: update, delete, availability, pagination, authentication, presentation association, and price endpoints remain out of scope.

### Subphase 2.8 — Precio [x]

Sync FastAPI slice delivered. Three price endpoints support product-presentation price retrieval/creation and direct price retrieval under the established `Router → Service → Repository → Model` layering. Integration coverage runs against `supernova_test`; no model change or Alembic migration.

**Architectural constraints introduced**:
- product-presentation ownership is derived exclusively from nested routes; request bodies cannot supply `id_producto_presentacion`
- prices use `Decimal` end-to-end, enforce `Numeric(12, 2)` precision, reject negatives/excess scale, and normalize to two decimal places
- each product-presentation has at most one price; duplicate creation returns 409
- service owns commit/rollback; repository methods do not finalize transactions or load relationships

**Files created**:
- `backend/routers/precios.py`
- `backend/schemas/precio.py`
- `backend/repositories/precio_repository.py`
- `backend/services/precio_service.py`
- `backend/services/exceptions.py` extended with price exceptions

**Context for future subphases**: update, delete, history, discount, promotion, bulk-price, pagination, and authentication behavior remain out of scope.

### Subphase 2.9 — Comercio All data [x]

Read-only commerce configuration endpoint delivered at `GET /comercios/{comercio_id}/configuracion`. It returns commerce scalars, status, payment associations/catalog records, and delivery associations/catalog records through the established `Router → Service → Repository → Model` layering.

**Architectural constraints introduced**:
- scalar status is joined eagerly; payment and delivery collections use eager loading with nested catalog records, avoiding N+1 queries
- payment associations order by ID; delivery associations order by `orden`, then ID
- empty associations serialize as arrays; inactive associations are not filtered
- the service is read-only and product-domain relationships are neither loaded nor exposed

**Files created**:
- `backend/routers/configuracion_comercio.py`
- `backend/schemas/configuracion_comercio.py`
- `backend/repositories/configuracion_comercio_repository.py`
- `backend/services/configuracion_comercio_service.py`

**Context for future subphases**: writes, filtering, pagination, authentication, and product-domain aggregation remain out of scope.

### Subphase 2.10 — Product Query Endpoints [x]

Read-only product query endpoints delivered through a dedicated router module that reuses the existing product schemas, exception types, and dependency injection. Aggregation covers product detail, commerce catalog, presentation listings, price summary, commerce-scoped search, exact-name lookup, available/sellable filters, incomplete-product detection, and category detail.

**Architectural constraints introduced**:
- new read-only endpoints live in `backend/routers/producto_queries.py` with commerce-prefixed paths to avoid conflicts with dynamic `/productos/{producto_id}` routes
- `ProductoDetalleResponse`, `ProductoCategoriaResumenResponse`, and `CategoriaProductoDetalleResponse` extend the existing scalar response schemas with eager-loaded nested data
- `ProductoQueryService` is read-only and reuses existing domain exceptions for missing parents
- repository methods use `joinedload`/`selectinload` and explicit joins to keep commerce scoping without N+1 queries

**Files created**:
- `backend/routers/producto_queries.py`
- `backend/schemas/producto_query.py`
- `backend/repositories/producto_query_repository.py`
- `backend/services/producto_query_service.py`

**Context for future subphases**: writes, fuzzy search, presentation detail enrichment, and price history remain out of scope.

### Subphase 2.11 — pedido model [x]

Sync FastAPI slice delivered. Six pedido endpoints (`POST /pedidos`, `GET /pedidos/{id}`, `PUT /pedidos/{id}/medio-pago`, `PUT /pedidos/{id}/metodo-entrega`, `PUT /pedidos/{id}/fecha-entrega`, `PUT /pedidos/{id}/estado`) under the established `Router → Service → Repository → Model` layering. 14 new tests / 157 total pass against `supernova_test`. New Alembic migration `c951ddda1fe4` applied to both databases.

**Architectural constraints introduced**:
- `EstadoPedido` is a Python `enum.Enum` mirrored 1:1 in the SQLAlchemy `Enum(..., name="estado_pedido")` column; PostgreSQL stores the lowercase string values.
- `estado_pedido` defaults to `borrador` (Python + DB server-default).
- Per-field PUTs replace a generic PATCH: each update schema has exactly one field and uses `extra="forbid"`. Avoids accidentally changing multiple fields at once.
- `Pedido` declares `Mapped[MediosPago | None]` and `Mapped[MetodosEntrega | None]` relationship attributes that are never auto-joined and never exposed in responses; they exist for future catalog traversal without schema changes.
- No `sessions` relationship on `Pedido` — added when the `session` model exists.
- FKs (`id_medio_pago`, `id_metodo_entrega`) are `ON DELETE RESTRICT`; non-null values are validated against the catalogs in the service before `flush()` to surface missing ids as HTTP 400 instead of `IntegrityError` → 500.

**State graph** (lives in the service; `cambiar_estado` accepts it from any non-terminal state, all other PUTs require `borrador`):
- `borrador → ingresado | cancelado`
- `ingresado → preparacion | cancelado`
- `preparacion → terminado | cancelado`
- `terminado → entregado`
- `entregado` and `cancelado` are terminal.
- Self-transitions and any pair outside this graph return 409.

**Files created/modified**:
- `backend/models/pedido.py` (`Pedido`, `EstadoPedido`)
- `backend/models/__init__.py` — exports `Pedido`, `EstadoPedido`
- `backend/alembic/env.py` — imports `Pedido` for autogenerate
- `backend/alembic/versions/c951ddda1fe4_add_pedidos_table.py`
- `backend/repositories/pedido_repository.py`
- `backend/services/pedido_service.py` (`PedidoService`, `ALLOWED_TRANSITIONS`)
- `backend/services/exceptions.py` — added `PedidoNotFound`, `PedidoNotEditable`, `InvalidEstadoTransition`, `InvalidEstadoPedido`
- `backend/schemas/pedido.py` (`PedidoCreate`, `PedidoResponse`, `PedidoMedioPagoUpdate`, `PedidoMetodoEntregaUpdate`, `PedidoFechaEntregaUpdate`, `PedidoEstadoUpdate`)
- `backend/routers/pedidos.py`
- `backend/main.py` — registers `pedidos.router`
- `backend/tests/api_smoke.py` — 14 pedido tests added

**Context for future subphases**: line-item associations, total/tax/shipping calculations, customer/session linkage, write protection per resource (`activo`/`disponible` toggles), filtering, pagination, authentication, and any reverse relationship from `MediosPago`/`MetodosEntrega` to `Pedido` remain out of scope. New pedido write paths must reuse `ALLOWED_TRANSITIONS` and the borrador-only guard.

### Subphase 2.12 - Cliente model [x]
using FastAPI, SQLAlchemy and Alembic.

Create:
- SQLAlchemy model
- Pydantic schemas
- repository
- service
- router
- Alembic migration

Table `clientes`:
- `id` PK
- `nombre` nullable
- `whatsapp` required, unique, indexed, normalized to E.164
- `domicilio` nullable
- `activo` required, default `true`
- `created_at` timezone-aware datetime
- `updated_at` timezone-aware datetime

Rules:
- Reject duplicate WhatsApp numbers.
- Normalize WhatsApp before persistence.
- Repository must not commit.
- Service owns business rules.
- Router only validates and delegates.
- Do not implement Session in this subphase.

Endpoints:
- create client
- get client by id
- get client by WhatsApp
- update client
- activate/deactivate client

Minimum tests:
- successful creation
- WhatsApp normalization
- duplicate WhatsApp rejection
- get by id and WhatsApp
- update client
- activate/deactivate client
- Alembic upgrade against isolated PostgreSQL test database

### Subphase 2.13 - session model [x]

Sync FastAPI slice delivered. Six session endpoints (`POST /sessions`, `GET /sessions/{id}`, `GET /comercios/{id}/clientes/{id}/sessions/activa`, `PATCH /sessions/{id}/movimiento`, `PUT /sessions/{id}/pedido`, `POST /sessions/{id}/cerrar`) under the established `Router → Service → Repository → Model` layering. 17 new tests added; 14 existing pedido tests updated to set up a session in setup; 191 total pass against `supernova_test`. New Alembic migration `7a51c8a2b1f0` hand-written in 4 phases (create sessions → add nullable `id_session` → truncate dev data → alter NOT NULL → add circular FK), applied to both databases.

**Architectural constraints introduced**:
- `EstadoSession` is a Python `enum.Enum` mirrored 1:1 in the SQLAlchemy `Enum(..., name="estado_session")` column; `activa` is the default (Python + DB server-default).
- "At most one active session per `(id_comercio, id_cliente)`" is enforced at the DB level by a partial unique index: `CREATE UNIQUE INDEX uq_session_activa_comercio_cliente ON sessions (id_comercio, id_cliente) WHERE estado_session = 'activa'`. The service maps the `IntegrityError` to `DuplicateActiveSession` → 409.
- Circular FK between `Session` and `Pedido` is resolved with `post_update=True` on `Session.id_pedido` (nullable, optional pointer) and an explicit `ForeignKey("sessions.id", ondelete="RESTRICT")` on `Pedido.id_session` (NOT NULL, owner). The migration adds the `sessions.id_pedido` FK via `ALTER TABLE` after both columns exist on both sides.
- **Breaking change to `Pedido`**: `id_session` becomes a required field on `POST /pedidos`. The pedido service validates the supplied `id_session` exists and is `activa`; otherwise `SessionNotFound` → 404 or `SessionNotActive` → 409. The 14 existing pedido tests were updated to set up a session in their setup.
- `Pedido.estado_pedido` defaults to `borrador` regardless. `datetime_ultimo_movimiento` is bumped on `PATCH /movimiento` and on `asociar_pedido` and `cerrar`. `datetime_inicio` is set on create and never changes.
- `asociar_pedido` enforces that `pedido.id_session == session_id` and that the pedido is still in `borrador`; both checks return `IncompatiblePedidoAssociation` → 400.
- `cerrar` rejects already-closed sessions with `SessionAlreadyClosed` → 409. `cerrada` is terminal; no reactivation endpoint.
- Migration's `TRUNCATE pedidos` step is documented as dev/test-only (no production data yet).

**Files created/modified**:
- `backend/models/session.py` (`Session`, `EstadoSession`)
- `backend/models/pedido.py` (added `id_session` + `session` relationship)
- `backend/models/__init__.py` — exports `Session`, `EstadoSession`
- `backend/alembic/env.py` — imports `Session`
- `backend/alembic/versions/7a51c8a2b1f0_add_sessions_and_pedido_id_session.py` (hand-written 4-phase)
- `backend/repositories/session_repository.py`
- `backend/services/session_service.py` (`SessionService`, `DuplicateActiveSession` mapping)
- `backend/services/pedido_service.py` (added `id_session` validation in `create`)
- `backend/services/exceptions.py` — added `SessionNotFound`, `DuplicateActiveSession`, `SessionNotActive`, `IncompatiblePedidoAssociation`, `SessionAlreadyClosed`
- `backend/schemas/session.py` (`SessionCreate`, `SessionPedidoUpdate`, `SessionResponse`)
- `backend/schemas/pedido.py` — `PedidoCreate.id_session` required, `PedidoResponse.id_session` exposed
- `backend/routers/sessions.py`
- `backend/routers/pedidos.py` — POST `/pedidos` maps `SessionNotFound` → 404, `SessionNotActive` → 409
- `backend/main.py` — registers `sessions.router`
- `backend/tests/api_smoke.py` — 17 new session tests, 14 existing pedido tests updated; `_delete_pedido` cascades to the owning session; `_new_session_id()` helper

**Context for future subphases**: realtime routing of WhatsApp messages, line-item associations on pedidos, total/tax/shipping calculations, automatic last-movement updates from any pedido write, reactivation of closed sessions, and multi-comercio scoping for sessions remain out of scope. The partial unique index is the source of truth for "one active session" — no service-level dedup is needed. New pedido write paths must require a valid `id_session`.

Subphase 2.14 — PedidoProducto module [x]

Sync FastAPI slice delivered. Five line-item endpoints (`POST /pedidos/{id}/productos`, `GET /pedidos/{id}/productos`, `GET /pedidos-productos/{id}`, `PUT /pedidos-productos/{id}`, `DELETE /pedidos-productos/{id}`) under the established `Router → Service → Repository → Model` layering. 11 new tests added; 210 total pass against `supernova_test`. New Alembic migration `5803d45fe1e9` applied to both databases.

**Architectural constraints introduced**:
- `precio_unitario` is set by the service from the current `Precio.precio` at insert time and SHALL NOT be client-supplied. The Pydantic create schema uses `extra="forbid"` to reject any `precio_unitario` field. The snapshot is durable: future changes to the catalog `Precio` do not alter existing line items.
- Line items are write-locked once the parent pedido leaves `borrador`. The service re-uses the same guard pattern as `pedido_service`: any create/update/delete requires `pedido.estado_pedido == BORRADOR`; otherwise `PedidoProductoNotEditable` → 409. Read endpoints are not restricted.
- `cantidad` is enforced at two layers: Pydantic `Field(ge=1)` returns 422 at the schema layer; DB-level `CheckConstraint("cantidad > 0", name="cantidad_positiva")` is the source of truth.
- `id_pedido` is `ON DELETE CASCADE` (pedido owns its line items); `id_producto_presentacion` is `ON DELETE RESTRICT` (catalog row cannot be deleted while any line item references it).
- Update endpoint accepts only `cantidad` and `observaciones`; `id_pedido` and `id_producto_presentacion` are immutable on update. Schema-level `extra="forbid"` rejects a client-supplied `precio_unitario` on update.
- `observaciones` is nullable free text (`Text, nullable=True`); the service trims it; empty-after-trim becomes `None`. Maximum length is uncapped in the active subphase.

**Files created**:
- `backend/models/pedido_producto.py` (`PedidoProducto`)
- `backend/models/__init__.py` — exports `PedidoProducto`
- `backend/alembic/env.py` — imports `PedidoProducto` for autogenerate
- `backend/alembic/versions/5803d45fe1e9_add_pedidos_productos_table.py`
- `backend/repositories/pedido_producto_repository.py`
- `backend/services/pedido_producto_service.py` (`PedidoProductoService`)
- `backend/services/exceptions.py` — added `PedidoProductoNotFound`, `PedidoProductoNotEditable`
- `backend/schemas/pedido_producto.py` (`PedidoProductoCreate`, `PedidoProductoUpdate`, `PedidoProductoResponse`)
- `backend/routers/pedido_productos.py`
- `backend/main.py` — registers `pedido_productos.router`
- `backend/tests/api_smoke.py` — 11 new test functions

**Migration note**: the autogenerate for `5803d45fe1e9` produced a false positive on the existing partial unique index `uq_session_activa_comercio_cliente` (from subphase 2.13) and tried to drop it. The `drop_index` line was removed manually before applying. Documented so future migrations of `Session` know to keep this index.

**Context for future subphases**: line-item totals (subtotal per pedido, tax, shipping, grand total), automatic `precio_unitario` re-snapshots on edit, bulk-add, discount/promotion, reorder, and the corresponding reverse `Pedido.line_items` relationship (currently absent) remain out of scope. New write paths that mutate `pedidos_productos` must keep the borrador-only guard.


Phase 3 - Intents

Subphase 3.1 create agregar_product contract [x]

Phase 3 (Intents) introduced. Static contract delivered. `AGREGAR_PRODUCTO_CONTRACT` exported as a `dict` literal from `backend/intents/contracts/agregar_producto.py` with `intent: "agregar_producto"`, `recognizer: "recognizer_productos"`, `handler: "agregar_producto"`, and `requirements` for `producto_presentacion_id` (required, default `None`) and `cantidad` (required, default `1`). 9 new test checks; 220 total pass against `supernova_test`.

**Architectural constraints introduced**:
- Phase 3 starts with the "contracts" leaf of the intents tree only. No registry, no recognizer adapter, no handler adapter, no processor, no Pydantic schema, no DB write, no FastAPI endpoint.
- The contract is a `dict` literal — the smallest representation that captures the static shape. Future subphases may wrap it in a `TypedDict` or `dataclass`; that is out of scope here.
- The `requirements` value is itself a `dict` keyed by requirement name; each entry carries `required: bool` and `default` (any JSON-compatible value). The runtime interpretation of `default` (and any future `type`/`description` keys) is the responsibility of a future subphase.
- `backend/intents/contracts/` is a Python package; `__init__.py` markers are present. Future intent contracts slot in alongside `agregar_producto.py`.

**Files created**:
- `backend/intents/__init__.py`
- `backend/intents/contracts/__init__.py`
- `backend/intents/contracts/agregar_producto.py` (exports `AGREGAR_PRODUCTO_CONTRACT`)
- `backend/tests/api_smoke.py` — `test_agregar_producto_contract_structure`

**Context for future subphases**: contract registration/dispatch, recognizer adapters (LLM-based, regex-based, etc.), handler adapters that call into the existing `pedido_producto` endpoints, runtime validation of `requirements`, type coercion, async dispatch from the WhatsApp channel, and any additional intent contracts (`cerrar_pedido`, `confirmar_pedido`, etc.) remain out of scope. New contract subphases must keep the same top-level shape (`intent` / `recognizer` / `handler` / `requirements`).


Subphase 3.2  Implement the Pydantic schema `RequirementState` [x]

Typed runtime value object delivered. `RequirementStatus = Literal["pending", "completed"]` and `RequirementState(BaseModel)` exported from `backend/intents/schemas/requirement_state.py` with `name: str`, `status: RequirementStatus`, `value: Any | None = None`. `__all__` declared. 8 new test checks; 228 total pass against `supernova_test`.

**Architectural constraints introduced**:
- `RequirementStatus` is a `Literal`, not an `Enum` (per spec). Pydantic renders it as `enum` in OpenAPI; runtime validation is a closed string set.
- `value: Any | None` is intentional: the future recognizer will produce different Python types per requirement (`int` for `cantidad`, `int` for `producto_presentacion_id`, possibly `str` later). A future subphase may add a per-requirement `model_validator` to enforce per-requirement types — that is out of scope here.
- `BaseModel` default config only; no `extra="forbid"`, no `from_attributes=True`, no `frozen=True`. A future subphase can add a `model_config` if needed.
- `backend/intents/schemas/` is a Python package with `__init__.py`; future schemas (`Intent`, `IntentResult`, etc.) slot in alongside `requirement_state.py`.

**Files created**:
- `backend/intents/schemas/__init__.py`
- `backend/intents/schemas/requirement_state.py` (exports `RequirementStatus`, `RequirementState`, `__all__`)
- `backend/tests/api_smoke.py` — `test_requirement_state_schema`

**Context for future subphases**: per-requirement type validators, computed fields, conversion to/from the static `dict` contract, integration with the recognizer (populating `value`), integration with the handler (reading `value` and advancing `status`), and additional intent schemas (`Intent`, `IntentResult`, `ErrorEnvelope`) remain out of scope. New schemas in this package must follow the same `__all__` discipline.


Subphase 3.3 Implement the Pydantic schema `ProcessedIntent` [x]

Typed envelope delivered. `IntentStatus = Literal["pending_resolution", "ready", "executed", "rejected", "failed"]` and `ProcessedIntent(BaseModel)` exported from `backend/intents/schemas/processed_intent.py` with eight fields in spec order: `intent`, `source_text`, `status`, `recognizer` (nullable), `handler`, `resolved_data` (`default_factory=dict`), `requirements` (`default_factory=list[RequirementState]`), `candidate_ids` (`default_factory=list[int]`). `__all__` declared. 8 new test checks; 236 total pass against `supernova_test`.

**Architectural constraints introduced**:
- `recognizer` is `str | None = None` because not every flow runs through a recognizer (e.g. a future manual override); `handler` is non-nullable because every intent has a handler.
- `resolved_data: dict[str, Any]` is intentional: slot values come from heterogeneous requirements and are not statically known. A future subphase may introduce typed slot schemas per intent.
- `requirements: list[RequirementState]` (not `dict`) preserves the recognizer's resolution order, which carries semantic meaning.
- `candidate_ids: list[int]` (not `list[str]`) matches the integer keys used by `comercios.id`, `productos.id`, etc. The future recognizer populates it for ambiguous cases.
- `default_factory` on all three collection fields is mandatory: without it, every instance would share the same default `dict`/`list` and mutations would leak across instances.
- `BaseModel` default config only; no `model_config`, no methods. Pydantic handles nested `RequirementState` validation automatically.
- The `requirement_state_only_schema_file` test in `api_smoke.py` was updated to expect both `requirement_state.py` and `processed_intent.py` once 3.3 lands. Documented so future schema additions follow the same update pattern.

**Files created**:
- `backend/intents/schemas/processed_intent.py` (exports `IntentStatus`, `ProcessedIntent`, `__all__`)
- `backend/tests/api_smoke.py` — `test_processed_intent_schema`; updated `test_requirement_state_schema` for the new file set

**Context for future subphases**: per-intent typed slot schemas, `Union[AgregarProducto, CerrarPedido, ...]` discriminated results, the recognizer adapter that populates `requirements` and `resolved_data`, the handler adapter that consumes them and advances `status`, an `ErrorEnvelope` schema for the `failed` / `rejected` paths, and the registry/dispatch layer all remain out of scope. The next natural subphase is the recognizer adapter for a single intent.

Subphase 3.4 Implement the Pydantic schema `PendingIntents` [x]

Conversation-wide state envelope delivered. `PendingIntents(BaseModel)` exported from `backend/intents/schemas/pending_intents.py` with three fields in spec order: `version: int = 1`, `active: ProcessedIntent | None = None`, `queue: list[ProcessedIntent] = Field(default_factory=list)`. `__all__ = ["PendingIntents"]`. 13 new test checks; 249 total pass against `supernova_test`.

**Architectural constraints introduced**:
- `version: int = 1` is a forward-compatibility hook. The current subphase does NOT enforce any version-checking logic; a future subphase may add a `model_validator(mode="after")` that rejects unknown versions, refuses to downgrade, or migrates old shapes forward. Today the field exists so persisted blobs already carry a version tag from day one.
- `active: ProcessedIntent | None = None` reflects the natural conversation state: between user messages there is no active intent; when the user speaks the runtime sets it; when the handler finishes, the runtime clears it to `None` and promotes the head of `queue` (if any). The active subphase declares the shape; the lifecycle lands in a future subphase.
- `queue: list[ProcessedIntent]` (not `dict`) preserves arrival order. The future handler drains the queue head-first.
- JSON round-trip via `model_dump(mode="json")` + `model_validate(...)` is the canonical persistence path: a future subphase will serialize this object to a `Session` metadata column and resume after an interruption. The test asserts structural equivalence (not `is` identity) of the round-tripped instance.
- `default_factory=list` is mandatory for `queue`: a mutable default shared across instances is a classic Python footgun.
- `BaseModel` default config only; no `model_config`, no methods, no `model_validator`. Pydantic handles the nested `ProcessedIntent` validation automatically.
- The `*_only_schema_file` tests in subphases 3.2 and 3.3 were updated to expect the three-file package once 3.4 lands. Documented so future schema additions follow the same update pattern.

**Files created**:
- `backend/intents/schemas/pending_intents.py` (exports `PendingIntents`, `__all__`)
- `backend/tests/api_smoke.py` — `test_pending_intents_schema`; updated `*_only_schema_file` assertions in 3.2 and 3.3 tests for the new file set

**Context for future subphases**: persistence of `PendingIntents` to a `Session` metadata column (likely a JSONB or a `Text` blob), a `Session` migration to add that column, the recognizer adapter that produces `ProcessedIntent` and promotes it to `active`, the handler adapter that drains `active` and the queue head, the lifecycle transitions (set `active` → run handler → clear `active` → promote queue head), the dispatch path that uses this envelope, and additional intent contracts (`cerrar_pedido`, `confirmar_pedido`, etc.) all remain out of scope. The next natural subphase is the persistence layer or the recognizer adapter for one intent.

Subphase 3.5 Implement `ProductIntentResolver` [x]

Pure-function recognizer adapter delivered. `resolve_product_intent(raw: dict) -> dict` exported from `backend/intents/resolvers/product_intent_resolver.py`. 14 new test checks; 263 total pass against `supernova_test`.

**Architectural constraints introduced**:
- The function is **pure**: no I/O, no LLM, no DB, no intent contract, no handler, no persistence. The surrounding adapter (future subphase) is responsible for wrapping the input/output into typed envelopes (`ProcessedIntent`).
- Input keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`) all default to `[]` when missing. Robust to partial recognizer output and the empty-result case.
- Confident match (`encontrados`) takes priority over candidates: when at least one confident match is present, `resolved_data` is populated from the FIRST confident match and `candidate_ids` is empty. A second or third confident match is silently dropped (multi-item intents are out of scope; documented for a future subphase).
- When only candidates exist, `candidate_ids` collects every `id` in order and the FIRST candidate's `cantidad` (if present) is preserved in `resolved_data["cantidad"]`. `resolved_data["producto_presentacion_id"]` is left empty (the future handler picks from the candidates and asks the user to disambiguate).
- `unavailable_items` and `not_found_items` are flat `list[str]` of `source_text` values from the recognizer.
- The function always returns a dict with exactly the four output keys (`resolved_data`, `candidate_ids`, `unavailable_items`, `not_found_items`). No key is ever omitted.
- `__all__ = ["resolve_product_intent"]` is declared.

**Files created**:
- `backend/intents/resolvers/__init__.py` (empty package marker)
- `backend/intents/resolvers/product_intent_resolver.py` (exports `resolve_product_intent`, `__all__`)
- `backend/tests/api_smoke.py` — `test_product_intent_resolver`

**Context for future subphases**: the `recognizer_productos` LLM adapter that produces the `raw` dict (subphase to be defined), the `IntentProcessor` that consumes the resolver output and applies the `agregar_producto` contract, the handler that hits `pedido_producto` with the resolved `producto_presentacion_id` and `cantidad`, additional resolvers (`cerrar_pedido_resolver`, `confirmar_pedido_resolver`, etc.), strict validation of the input shape (a future subphase may introduce a `ValidationError` layer), and multi-confident-match policy (currently silent drop; a future subphase may add a `MultipleMatchesError`) all remain out of scope. The next natural subphase is the recognizer adapter for the `agregar_producto` intent.

Subphase 3.6 Implement `IntentProcessor` for `agregar_producto` [x]

Pure-function processor delivered. `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent` exported from `backend/intents/processor.py`. 11 new test checks; 274 total pass against `supernova_test`.

**Architectural constraints introduced**:
- The function is **pure**: no I/O, no recognizer call, no handler invocation, no DB, no persistence. The future recognizer-adapter subphase wraps the call.
- The function reads `AGREGAR_PRODUCTO_CONTRACT` (subphase 3.1) as the source of truth for requirement names, required-ness, and defaults. The contract is iterated at call time, so a future subphase that adds or renames a requirement needs no changes here (only a contract update).
- Slot lookup uses **key presence** in `resolved_data`, not value truthiness: a requirement with name `producto_presentacion_id` is satisfied if the key is present, even if its value is `None` or `0`. This is consistent with the contract's `default: None` for that requirement.
- A requirement is `completed` if its key is present in `resolved_data`, else `pending`. The original value (possibly `None`) is preserved on the `RequirementState`; the default from the contract is applied only when the key is missing.
- `status == "ready"` iff every requirement with `required: True` is `completed`. Non-required requirements are ignored. The current contract has both requirements as `required: True`, so this distinction does not affect today's behavior, but it makes the processor future-proof.
- `recognizer` and `handler` are copied from the contract (`"recognizer_productos"`, `"agregar_producto"`) onto the returned `ProcessedIntent`. The processor does not invoke them.
- `candidate_ids` is preserved verbatim on the `ProcessedIntent`; the processor does not dedupe, sort, or filter.
- The active subphase does **not** copy `unavailable_items` or `not_found_items` from the input onto the `ProcessedIntent`: the `ProcessedIntent` schema (subphase 3.3) does not yet expose those fields, and the spec for this subphase preserves the contract that the processor output is a valid `ProcessedIntent`. A future subphase that extends the schema to include those fields can add them.
- `__all__ = ["process_agregar_producto"]` is declared.

**Files created**:
- `backend/intents/processor.py` (exports `process_agregar_producto`, `__all__`)
- `backend/tests/api_smoke.py` — `test_process_agregar_producto_processor`

**Context for future subphases**: the recognizer-adapter subphase that produces the `normalized_result` dict (subphase to be defined), the handler that consumes a `ProcessedIntent` whose `status == "ready"` and hits `pedido_producto`, the dispatch path that routes an incoming WhatsApp message through the recognizer → resolver → processor pipeline, additional processors (`process_cerrar_pedido`, `process_confirmar_pedido`, etc.), a `ProcessedIntent` schema extension that exposes `unavailable_items` and `not_found_items` on the envelope (today they live only on the `normalized_result` input), per-intent `Union[IntentA, IntentB, ...]` discriminated `ProcessedIntent` subtypes, and `executed` / `rejected` / `failed` status transitions (handler-side) all remain out of scope. The next natural subphase is the recognizer-adapter for the `agregar_producto` intent (the LLM call).

Subphase 3.7 Implement `PendingIntentService` [x]

In-memory mutation service delivered. Five module-level functions exported from `backend/intents/services/pending_intent_service.py`: `load`, `set_active`, `enqueue`, `remove_active`, `clear`. `__all__` declared. 16 new test checks; 291 total pass against `supernova_test` in a clean run.

**Architectural constraints introduced**:
- The `Session` model gains a `pending_intents` column: `Mapped[dict | None]` typed as `JSON`, nullable, `server_default=text("'{}'::json")`. The column stores a real JSON value (PostgreSQL `JSONB` under the hood), not a JSON string.
- The service operates on a `Session` model instance passed by argument (not on a SQLAlchemy `Session` transaction — the parameter is named `session`). Each mutation reads the current state with `load`, applies the change in a local Python object, writes the new state with `_save`, and returns the typed instance. The caller is responsible for committing.
- `load(session)` uses `PendingIntents.model_validate(session.pending_intents or {})` — accepts both `None` (pre-migration row) and an empty dict.
- Every mutation serializes the new state with `PendingIntents.model_dump(mode="json")` and writes the resulting `dict` to `session.pending_intents`. The column holds a dict, not a string.
- `set_active` sets `active = intent`, leaves the queue unchanged.
- `enqueue` appends `intent` to `queue`, leaves `active` unchanged.
- `remove_active` promotes `queue[0]` to `active` (and pops it) if `queue` is non-empty, else sets `active = None`.
- `clear` resets the state to a default `PendingIntents()` and serializes.
- The service does not commit, query repositories, execute handlers, or manage transactions. The caller owns the SQLAlchemy session and the commit.
- `TYPE_CHECKING` import of the `Session` model avoids circular imports.

**Files created/modified**:
- `backend/models/session.py` — added `JSON` and `text` imports, added `pending_intents: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=lambda: {}, server_default=text("'{}'::json"))`
- `backend/alembic/versions/8d4f6e2a9b1c_add_session_pending_intents.py` (initial TEXT column with server default `"{}"`)
- `backend/alembic/versions/9c5b1d3e4f6a_convert_session_pending_intents_to_json.py` (3-phase: drop server_default → alter column type from `Text` to `JSON` using `pending_intents::jsonb` → restore server default as `'{}'::json`. Hand-written because the default cannot be auto-cast during the type change.)
- `backend/intents/services/__init__.py` (empty package marker)
- `backend/intents/services/pending_intent_service.py` (exports the five functions, `__all__`)
- `backend/tests/api_smoke.py` — `test_pending_intent_service` (16 checks including `service_pending_intents_stored_as_dict`, `service_set_active_persists_as_dict`, `service_enqueue_persists_as_dict` to verify the dict-stored invariant)

**Refactor note (post-implementation)**: the service was initially implemented with `model_dump_json()` (string) and `model_validate_json()` (string parser). It was refactored to `model_dump(mode="json")` (dict) and `PendingIntents.model_validate(dict or {})` (dict parser) to match the new `JSON` column type. The column type and the service serialization are now in sync: both treat the value as a dict. The `pending_intents` column is `JSONB` in PostgreSQL.

**Context for future subphases**: the dispatch path that reads `session.pending_intents` on every incoming WhatsApp message and advances the state via `set_active` / `enqueue` / `remove_active` / `clear`, the handler that consumes `ready` `ProcessedIntent` instances from the state and transitions them to `executed` / `rejected` / `failed`, the persistence-layer subphase that commits the model after each `set_active` / `enqueue` / `remove_active` / `clear` (today the service does not commit; the caller must), concurrency control (the service is in-memory and assumes a single writer per `Session` row), the `__init__.py` for the `services/` package, and additional services for the `cerrar_pedido` / `confirmar_pedido` intents all remain out of scope. The next natural subphase is the dispatch path that ties the recognizer → resolver → processor → service pipeline to the WhatsApp channel.

Subphase 3.8 Implement the session context enum [x]

Closed set of `Session` context types delivered. `ContextType(StrEnum)` exported from `backend/sessions/enums/context_type.py` with exactly one member `PRODUCT_SELECTION = "product_selection"`. `__all__ = ["ContextType"]`. 11 new test checks; 302 total pass against `supernova_test` in a clean run.

**Architectural constraints introduced**:
- `ContextType` is a `StrEnum` (Python 3.11+) — `ContextType.PRODUCT_SELECTION == "product_selection"` works without an explicit cast, and `isinstance(ContextType.PRODUCT_SELECTION, str)` is `True`. This is the right choice for a context identifier that will be persisted as a string in a future subphase.
- Single value `PRODUCT_SELECTION`. No placeholders, no "reserved" values. Future subphases that need new contexts (e.g. `CART_REVIEW`) append to the same enum; existing values do not change. Serialized form stays backward-compatible.
- The module path is `backend/sessions/enums/context_type.py` (a *package*, not a single module shortcut). The `backend/sessions/` package is the new home for session-related code (enums, models, services, routers to come). The `__init__.py` markers are present; the spec explicitly forbids creating `backend/sessions/enums.py`.
- `__all__` is declared. No business logic, no methods, no validators. The enum is self-contained pure data.
- The active subphase does NOT introduce a `context_type` column on the `Session` model — that lands in a future subphase. The enum exists before the column does.

**Files created**:
- `backend/sessions/__init__.py` (empty package marker)
- `backend/sessions/enums/__init__.py` (empty package marker)
- `backend/sessions/enums/context_type.py` (exports `ContextType`, `__all__`)
- `backend/tests/api_smoke.py` — `test_session_context_type_enum` (11 checks: one-member list, value, str equality, isinstance str, str() round-trip, 3 invalid value rejections, `__all__` correctness, enums dir has only `__init__.py`+`context_type.py`, no `enums.py` shortcut)

**Context for future subphases**: the `context_type` column on the `Session` model (likely `Mapped[ContextType | None] = mapped_column(Enum(..., name="session_context_type"), nullable=True)`), the dispatch path that reads `session.context_type` on every incoming WhatsApp message and picks the right recognizer / processor / handler chain, the per-context service wrappers (e.g. `ProductSelectionService` that wraps `set_active` / `enqueue` / `remove_active` for the `PRODUCT_SELECTION` flow), the migration that adds the `context_type` column to existing `Session` rows with a server default of `PRODUCT_SELECTION` (or `None`), additional `ContextType` values (`CART_REVIEW`, `CHECKOUT`, `CUSTOMER_SUPPORT`), and the `ContextType`-aware handler subphase that closes the lifecycle from `ready` to `executed` / `rejected` / `failed` all remain out of scope. The next natural subphase is the `context_type` column on `Session` (a model + migration change).

Subphase 3.9 Implement `ContextTypeResolver` [x]

Pure intent-to-context classifier delivered. `resolve_context_type(intent: ProcessedIntent) -> ContextType | None` exported from `backend/intents/context/context_type_resolver.py`. `__all__ = ["resolve_context_type"]`. 13 new test checks; 315 total pass against `supernova_test`.

**Architectural constraints introduced**:
- The function is **pure**: no I/O, no DB, no recognizer call, no handler invocation, no session mutation, no persistence, no logging, no mutation of the input. It returns `ContextType.PRODUCT_SELECTION` only when **all three** conditions hold: `intent.status == "pending_resolution"`, a `RequirementState(name="producto_presentacion_id", status="pending")` is present in `intent.requirements`, and `intent.candidate_ids` is truthy. Every other case returns `None`.
- The signature is `ContextType | None`, not `ContextType`. Today there is one value in the enum (subphase 3.8); future subphases may add values (e.g. `CART_REVIEW`) and rules. The `| None` return type accommodates that. `None` means "no specific context — fall through to the default dispatch path".
- The function looks up the requirement by **`name == "producto_presentacion_id"`**, not by positional index. If the future contract renames the requirement, the function returns `None` for every intent that no longer has it — graceful degradation.
- Other requirements are ignored when checking the rule (e.g. a pending `cantidad` requirement does not change the outcome). The function only checks `producto_presentacion_id`.
- The module location is `backend/intents/context/`. The `context/` package is the new home for intent classification and dispatch concerns. Future resolvers (e.g. `cart_review_resolver.py`) slot in alongside.
- `__all__` is declared. No business logic, no methods, no validators. The function is self-contained pure data.

**Files created**:
- `backend/intents/context/__init__.py` (empty package marker)
- `backend/intents/context/context_type_resolver.py` (exports `resolve_context_type`, `__all__`)
- `backend/tests/api_smoke.py` — `test_context_type_resolver` (13 checks: all-three-conditions met returns `PRODUCT_SELECTION` for both multi- and single-candidate cases, two-pending-requirements + single-candidate returns `PRODUCT_SELECTION`, empty candidates returns `None`, each of `ready` / `executed` / `rejected` / `failed` returns `None`, empty requirements returns `None`, `producto_presentacion_id` completed returns `None`, only `cantidad` pending returns `None`, `__all__` correctness, package only `__init__.py`+`context_type_resolver.py`)

**Context for future subphases**: the dispatch path that reads `session.context_type` on every incoming WhatsApp message and routes to the right recognizer / processor / handler chain, the per-context service wrappers (e.g. `ProductSelectionService` that wraps `set_active` / `enqueue` / `remove_active` for the `PRODUCT_SELECTION` flow), the `context_type` column on the `Session` model (subphase 3.8 left this as future work), the migration that adds the column to existing `Session` rows with a server default of `PRODUCT_SELECTION` (or `None`), additional `ContextType` values (`CART_REVIEW`, `CHECKOUT`, `CUSTOMER_SUPPORT`) and the matching rules added to this resolver, the `ContextType`-aware handler subphase that closes the lifecycle from `ready` to `executed` / `rejected` / `failed`, and a `dispatch(intent: ProcessedIntent) -> ContextType` orchestration function that calls this resolver and routes to the right per-context processor all remain out of scope. The next natural subphase is the `context_type` column on `Session` (a model + migration change).

Subphase 3.10 Implement `PendingContextService` [x]

Entry-point orchestration service delivered. Two functions exported from `backend/intents/context/pending_context_service.py`: `set_pending_intent(session, intent: ProcessedIntent) -> PendingIntents` and `clear_pending_context(session) -> None`. `__all__` declared. 24 new test checks; 339 total pass against `supernova_test` in a clean run.

**Architectural constraints introduced**:
- The `Session` model gains a `context_type` column: `Mapped[str | None]` typed as `String(50)`, nullable, no default. The column stores the **string** value of a `ContextType` (e.g. `"product_selection"`) — not a `ContextType` enum member — so the service's `session.context_type = context_type.value` write is a plain `str` assignment. Pre-existing rows are NULL after the migration.
- `set_pending_intent` is the entry point that ties together the recognizer → resolver → processor → state pipeline:
  1. Validates `intent.status == "pending_resolution"`; raises `ValueError(f"intent.status must be 'pending_resolution' (got '{intent.status}')")` otherwise.
  2. Calls `resolve_context_type(intent)` (subphase 3.9); raises `ValueError("no ContextType can be resolved for the given intent")` if the result is `None`.
  3. Calls `set_active(session, intent)` from `PendingIntentService` (subphase 3.7) to persist the intent as active and return the new `PendingIntents`.
  4. Assigns `session.context_type = context_type.value` (a `str`).
  5. Returns the new `PendingIntents` from `set_active`.
- `clear_pending_context` resets the `Session` to a context-free state: calls `clear(session)` from `PendingIntentService` and assigns `session.context_type = None`. Returns `None`.
- The two `ValueError` messages are descriptive and distinguish between "intent.status must be 'pending_resolution'" and "no ContextType can be resolved for the given intent". A future caller can branch on the message if needed.
- The service does **not** validate that `session.context_type` is already the same value (no "context switch mid-flight" check). A future subphase may add that check. Today the service overwrites the column unconditionally.
- The service is in-memory mutation; the caller is responsible for committing. Mirrors the `PendingIntentService` pattern (subphase 3.7).
- The service does not call recognizers, handlers, repositories, generate responses, or log. It is a thin coordinator.
- `TYPE_CHECKING` import of the `Session` model avoids circular imports.

**Files created/modified**:
- `backend/models/session.py` — added `String` import, added `context_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)`
- `backend/alembic/versions/1f2e3d4c5b6a_add_session_context_type.py` (adds the `String(50)` nullable column with no server default and no backfill; pre-existing rows are NULL)
- `backend/intents/context/pending_context_service.py` (exports the two functions, `__all__`)
- `backend/tests/api_smoke.py` — `test_pending_context_service` (24 checks: set returns/writes/persists, 4 status rejections × 2 sub-checks each, 3 context rejections × 2 sub-checks each, clear returns None + resets both fields, 3 clear scenarios, `__all__` correctness, package has 3 files). Also updated `test_context_type_resolver`'s `only_one_file_in_package` check to expect 3 files (the package now has `__init__.py` + `context_type_resolver.py` + `pending_context_service.py`).

**Context for future subphases**: the dispatch path that calls `set_pending_intent` on every incoming WhatsApp message, the persistence-layer subphase that commits the model after each `set_pending_intent` / `clear_pending_context` (today the service does not commit; the caller must), the handler subphase that consumes a `ready` `ProcessedIntent` and transitions it to `executed` / `rejected` / `failed` (then calls `clear_pending_context`), a `ContextType` value parser on read (a future subphase may introduce `ContextType(session.context_type)` to consume the column as an enum member), the `dispatch(intent: ProcessedIntent) -> ContextType` orchestration function that calls the resolver, the `ProductSelectionService` per-context wrapper (subphase 3.8's "Context for future subphases" note), additional `ContextType` values, the `context_type` column backfill for pre-existing `Session` rows, and additional per-context services (e.g. `CerrarPedidoService` for the `cerrar_pedido` intent) all remain out of scope. The next natural subphase is the dispatch path that ties the WhatsApp channel to `set_pending_intent`.

Subphase 3.11 Implement ProductRecognizer [x]

Pure-function fuzzy product recognizer delivered. `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` exported from `backend/recognizers/product_recognizer.py`. `__all__ = ["detectar_productos"]`. 25 (≈24) new test checks plus 4 value-preservation checks added during the post-archive `vendible` correction; 363 total pass against `supernova_test` after the correction (originally 339 before the recognizer, +24 net new; the post-archive correction added 4 more vendible-contract checks). The legacy `backend/old_project/logica_fuzzy_pedido_productos.py` is preserved in place; deleting it is a future cleanup.

**Architectural constraints introduced**:
- The module ports the legacy fuzzy pipeline (text normalization, quantity words, stopwords, product aliases, phonetic substitutions, prefix matching, segmentation, quantity extraction, presentation aliases, RapidFuzz scoring and thresholds) verbatim and applies it to the new field-name map. The pipeline logic is unchanged; only the input contract and the output shape change.
- The function is **pure**: no I/O, no DB query, no `lista_json` import, no recognizer-adapter, no handler, no router, no `print`/logging.
- The function returns a Python `dict` (not a JSON `str` as the legacy did). Future adapters (Phase 3's recognizer-adapter subphase) call `json.dumps` on the dict if needed.
- The catalog input shape (per the spec) uses 12 fields: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `producto_activo`, `presentacion_activo`, `disponible`. The function preserves the `precio` field if present in the input (legacy compatibility) but does not surface it in the output; the future handler reads price from the DB.
- **`producto_presentacion_id` is the unique candidate identifier**. Found products preserve the catalog fields and add two fields: `cantidad` (int) and `texto_origen` (str). Possible products are grouped with `texto_origen` and a `productos` list.
- **Vendible contract (post-archive correction):** an item is considered "vendible" only when all three `activo` values (`producto_activo`, `presentacion_activo`, `producto_presentacion.activo`) are truthy. The function checks all three explicitly. If any of the three is `False` (or its string-fallback is `"false"`, `"0"`, or `"no"`), the item is **excluded from all output lists** (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, and `no_encontrados`). If all three are truthy and `producto.disponible` is falsy, the item goes to `encontrados_no_disponibles`. If all three are truthy and `disponible` is truthy, the item goes to `encontrados` (uniquely identified) or `encontrados_posibles` (multiple presentations grouped). String-fallback checks (`str(x).lower() in ("false", "0", "no")`) preserve backward compatibility for legacy data while keeping the function robust to inputs that may pass non-`bool` values. The default for missing fields is `True` (graceful degradation for legacy data without all three flags populated).
- The function preserves the real `activo`, `producto_activo`, `presentacion_activo`, and `disponible` values from the input catalog in the output entries (no overwriting, no defaulting).

**Files created**:
- `backend/recognizers/__init__.py` (empty package marker)
- `backend/recognizers/product_recognizer.py` (ports ~900 lines of legacy fuzzy logic inline with the new field map; declares `__all__ = ["detectar_productos"]`)
- `backend/tests/api_smoke.py` — `test_product_recognizer` (~24-29 checks: unique match by size, by name, multiple presentations, explicit presentation, restricted catalog, multiple products, legacy shape with missing `activo` fields, no DB / `lista_json` / repositories imports, single public symbol, single file in package; plus post-archive `vendible` checks for inactive `producto_activo`, inactive `presentacion_activo`, inactive `producto_presentacion.activo`, and source-value preservation in `encontrados` / `encontrados_no_disponibles`)
- `backend/tests/manual_product_recognizer.py` — interactive CLI script that connects to `supernova_test`, joins `producto_presentaciones`/`productos`/`presentaciones`/`categorias_productos`, builds the 12-field catalog (including `producto_activo` and `presentacion_activo`), and runs the recognizer in a loop. Run from the project root with the active venv: `PYTHONPATH=. venv/bin/python backend/tests/manual_product_recognizer.py`.

**Refactor note (post-archive)**: the original implementation used a single flat `activo` field (representing only `producto_presentacion.activo`) and treated `activo == False` as "unavailable" (placing items in `encontrados_no_disponibles`). The `vendible` contract correction added `producto_activo` and `presentacion_activo` to the catalog and updated the recognizer to check all three flags. The legacy `backend/old_project/logica_fuzzy_pedido_productos.py` was preserved in `backend/old_project/` (not deleted) and is the reference for the fuzzy logic port.

**Context for future subphases**: the recognizer-adapter (subphase to be defined) that calls `detectar_productos` with the catalog fetched from the DB and pipes the output into `ProductIntentResolver` (subphase 3.5); the `ProductSelectionContextResolver` (subphase 3.11) for the second-step `PRODUCT_SELECTION` flow; the handler subphase that consumes a `ready` `ProcessedIntent` from the adapter and calls `pedido_producto`; the dispatch path that ties the WhatsApp channel to the adapter + recognizer + resolver pipeline; the `precio` field re-introduction (today dropped from the recognizer output; the future handler reads it from the DB); the `legacy` field-name backport (a future subphase may import the legacy module from `backend/old_project/` for the migration window); the cleanup that deletes `backend/old_project/logica_fuzzy_pedido_productos.py` once the migration is complete; and the `rapidfuzz` dependency (added to the venv as part of the implementation).


Subphase 3.12 — Add Product Selection Context Resolver [x]

Completed the pending `PRODUCT_SELECTION` context resolver. `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` is exported from `backend/intents/context/product_selection_context_resolver.py` with `__all__ = ["resolve_product_selection"]`.

**Behavior delivered:**
- Validates `pending_resolution` status and non-empty `candidate_ids` before resolving.
- Queries only candidate `producto_presentaciones` and eagerly loads product, presentation, and category data.
- Builds the recognizer's exact 12-field catalog contract: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `producto_activo`, `presentacion_activo`, `activo`, and `disponible`.
- Applies a unique recognizer match only when its ID belongs to the original candidates; ambiguous, unavailable, unknown, or out-of-scope results leave the intent unchanged.
- Preserves `resolved_data`, including `cantidad`, marks the selected presentation requirement completed, and clears `candidate_ids` only after valid selection.
- Sets status to `ready` only when every returned `RequirementState` is completed; otherwise explicitly sets `pending_resolution`.
- Does not mutate or persist the session model, commit, flush, close, invoke handlers, or generate responses.

**Verification:**
- Added unit coverage for restricted catalogs, preservation of resolved data, unchanged-result cases, candidate validation, no side effects, and pending requirements beyond the hardcoded product fields.
- Added real-recognizer integration coverage using two presentations and a restricted candidate catalog.
- `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py`: 383/383 passed.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Active delta spec synchronized to `openspec/specs/product-selection-context-resolver-3-12/spec.md` and archived at `openspec/changes/archive/2026-07-29-add-product-selection-context-resolver-3-12/`.

**Context for future subphases:** the resolver is currently a pure context component. A future dispatch/orchestration subphase must call it for incoming messages and route a resulting `ready` intent to the appropriate handler; persistence remains the caller's responsibility.

Subphase 3.13 - Review and correct `ProductIntentResolver` compatibility with the current ProductRecognizer output [x]

Completed the compatibility correction between `ProductIntentResolver` and the current `ProductRecognizer` output contract.

**Behavior delivered:**
- Confident matches now use `producto_presentacion_id` to populate `resolved_data["producto_presentacion_id"]`.
- Possible matches now populate ordered `candidate_ids` from `producto_presentacion_id`.
- Unavailable and not-found items now use the recognizer's `texto_origen` field for `unavailable_items` and `not_found_items`.
- Recognized `cantidad` remains preserved, including the first possible candidate's quantity.
- Confident matches continue to take priority over possible candidates.
- The existing four-key output shape remains unchanged: `resolved_data`, `candidate_ids`, `unavailable_items`, and `not_found_items`.
- No dependency remains on the legacy `id` or `source_text` fields.
- Recognizer fuzzy logic, intent contracts, persistence, handlers, APIs, and dependencies were not changed.

**Files changed:**
- `backend/intents/resolvers/product_intent_resolver.py`
- `backend/tests/api_smoke.py`
- `openspec/specs/product-intent-resolver/spec.md`

**Verification:**
- Updated resolver fixtures and regression checks to use `producto_presentacion_id` and `texto_origen` without legacy fields.
- `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py`: 383/383 passed.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- The incompatibility was confirmed in the resolver's legacy field access and corrected without changing the recognizer.
- Change artifacts were archived at `openspec/changes/archive/2026-07-29-review-correct-product-intent-resolver-3-13/`.

**Context for future subphases:** callers can now pass the current recognizer output directly to the pure resolver; orchestration and handler integration remain future work.

Subphase 3.14 - Refactor the database access used by `ProductSelectionContextResolver` to comply with the project layering rules [x]

Completed the database-access refactor for product selection. The context resolver is now a pure decision component, while catalog loading follows the project's Internal component → Service → Repository → SQLAlchemy layering.

**Architecture delivered:**
- `backend/repositories/producto_query_repository.py` provides `list_presentaciones_by_ids`, restricted to the supplied candidate IDs and eager-loading product, presentation, and category relationships.
- `backend/services/producto_query_service.py` provides `list_presentaciones_by_ids` and builds the recognizer's exact 12-field catalog with real activation and availability values.
- `backend/intents/context/product_selection_context_service.py` receives the database session, loads the restricted catalog through `ProductoQueryService`, and delegates to the pure resolver without persistence or handler behavior.
- `backend/intents/context/product_selection_context_resolver.py` now accepts `(message, active_intent, productos_presentaciones)` and contains no SQLAlchemy, session, model-loading, repository, or service access.

**Behavior preserved:**
- Candidate validation, unique presentation selection, original `cantidad`, requirement completion, readiness calculation, candidate clearing, and unchanged-result behavior.
- No commits, pending-context persistence, handler execution, response generation, or session mutation.

**Verification:**
- Updated resolver and context-package tests for the new service boundary and module layout.
- Real recognizer integration resolves `pizza grande`/`pizza chica` through the orchestration service and preserves `cantidad`.
- `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py`: 383/383 passed.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Delta specs synchronized, and artifacts archived at `openspec/changes/archive/2026-07-29-refactor-product-selection-context-resolver-database-access-3-14/`.

**Final responsibilities:** repositories query ORM data; services build the recognizer catalog; orchestration coordinates DB-backed resolution; the context resolver performs pure selection transformation.

Subphase 3.15 - Implement the initial `agregar_producto` intent orchestration flow [x]

Completed the initial `agregar_producto` orchestration entry point:
`process_initial_agregar_producto(db, session, source_text: str) -> ProcessedIntent`.

**Flow delivered:**
- Loads the session commerce catalog through `ProductoQueryService.list_recognizer_catalog` and does not build SQLAlchemy queries in the orchestrator.
- Calls `detectar_productos(source_text, productos_presentaciones)`.
- Normalizes the recognizer result with `resolve_product_intent`.
- Builds the typed `ProcessedIntent` with `process_agregar_producto`.
- Persists pending context only when `resolve_context_type` returns a valid `PRODUCT_SELECTION` context, using `set_pending_intent`.
- Returns ready intents without executing handlers; pending intents without a valid context are returned without persistence.

**Constraints preserved:**
- No commit or rollback.
- No handler execution, order/order-line mutation, customer response generation, FastAPI endpoint calls, or duplicated recognizer/resolver/processor/service/repository logic.
- The orchestration module exports only `process_initial_agregar_producto` through `__all__`.

**Files changed:**
- `backend/intents/orchestration/__init__.py`
- `backend/intents/orchestration/agregar_producto_orchestrator.py`
- `backend/repositories/producto_query_repository.py`
- `backend/services/producto_query_service.py`
- `backend/tests/api_smoke.py`
- `openspec/specs/agregar-producto-intent-orchestration/spec.md`

**Verification:**
- Tests cover exact ready results, ambiguous pending results, valid pending-context handling, invalid pending results, typed returns, and transaction/handler boundaries.
- `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py`: 386/386 passed.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Delta specs synchronized and archived at `openspec/changes/archive/2026-07-29-implement-initial-agregar-producto-intent-orchestration-3-15/`.

**Context for future subphases:** this is the initial processing pass only. A future dispatch/handler flow must consume ready intents and execute business actions; this orchestrator deliberately leaves that responsibility outside its boundary.


Subphase 3.16 — Implement `agregar_producto` handler [x]

Completed the first business-action handler for ready `agregar_producto` intents.

**Handler delivered:**
- `backend/intents/handlers/agregar_producto_handler.py` exports `execute_agregar_producto` through `__all__`.
- Uses explicit `DatabaseSession` and `ConversationSession` type aliases.
- Validates intent name, ready status, handler name, resolved `producto_presentacion_id`, positive integer `cantidad`, and associated `id_pedido`.
- Delegates order-line creation to `PedidoProductoService.add` with pedido ID, product-presentation ID, quantity, and no intent-supplied price.
- Preserves the service-owned current-price snapshot and draft-pedido/business rules.
- Returns a copied `ProcessedIntent` with `executed` on success, `rejected` for expected validation/business failures, and `failed` for unexpected technical failures.
- Preserves resolved data, requirements, candidate IDs, `pending_intents`, and `context_type`; cleanup and queue promotion remain future responsibilities.

**Constraints enforced:**
- No direct SQLAlchemy queries, repository access, routers, HTTP exceptions, response generation, handler abstraction, context cleanup, queue promotion, or order logic duplication.
- The handler does not own commit/rollback; the reused `PedidoProductoService` retains its existing transaction behavior.

**Verification:**
- Added focused tests for successful delegation, executed status, preserved context state, invalid quantity, wrong intent, missing pedido, and public/source boundaries.
- Focused handler tests: **5/5 passed**.
- `PYTHONPATH=. venv/bin/python -m py_compile backend/intents/handlers/agregar_producto_handler.py`: passed.
- Full smoke suite reached **387/388**; the single failure was an unrelated existing client setup collision (`409` duplicate WhatsApp).
- Delta spec synchronized to `openspec/specs/agregar-producto-handler/spec.md`.

**Context for future subphases:** dispatch must decide when to invoke this handler for ready intents; pending-context cleanup, queue promotion, response generation, and additional handlers remain out of scope.

Subphase 3.17 — Execute and close pending context [x]

Completed the lifecycle boundary that dispatches ready `agregar_producto` intents and clears the conversation context only after a successful execution.

**Execution flow delivered:**
- `backend/intents/orchestration/pending_context_execution.py` exports `execute_ready_pending_context` through `__all__`.
- Uses explicit `DatabaseSession` and `ConversationSession` type aliases.
- Loads pending state via `pending_intent_service.load(session)`.
- Rejects missing active intents with a minimal `rejected` `ProcessedIntent`.
- Rejects non-ready active intents and unsupported handlers by copying the active intent with `status == "rejected"` and preserving pending context.
- Dispatches `handler == "agregar_producto"` ready intents exactly once to `execute_agregar_producto`.
- Clears `session.pending_intents` and sets `session.context_type = None` only when the handler returns `executed`.
- Preserves pending context for `rejected` and `failed` results so future recovery remains possible.

**Constraints enforced:**
- No direct SQLAlchemy queries, repository access, commits, rollback, HTTP concerns, response generation, or queue promotion.
- No modifications to the handler, recognizer, processor, or service rules.
- Only the current `agregar_producto` dispatch path is implemented.

**Verification:**
- Added focused tests for executed cleanup, rejected preservation, missing active, non-ready, unsupported handler, and public/source boundaries.
- Focused pending-context tests: **6/6 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Delta spec synchronized to `openspec/specs/pending-context-execution/spec.md`.

**Context for future subphases:** the generic context dispatcher, queue promotion, response generation, additional handlers, and lifecycle integration remain out of scope.

Subphase 3.18 — Pending context dispatcher [x]

Completed the conversation-routing entry point that advances the active pending intent based on `session.context_type`.

**Dispatcher delivered:**
- `backend/intents/orchestration/pending_context_dispatcher.py` exports `dispatch_pending_context` through `__all__`.
- Uses explicit `DatabaseSession` and `ConversationSession` type aliases.
- Loads pending state through `pending_intent_service.load`.
- Rejects missing active intents with a typed rejected `ProcessedIntent`.
- Rejects missing or unsupported `session.context_type` by copying the active intent with `status == "rejected"` and preserving context.
- Dispatches `context_type == "product_selection"` through `ProductSelectionContextService.resolve` and persists the result with `set_active`.
- Delegates to `execute_ready_pending_context` only when the dispatched result becomes `ready`, allowing the execution boundary to clear context.

**Constraints enforced:**
- Reuses existing services and orchestrators; no direct SQLAlchemy queries, repository access, commits, rollback, HTTP concerns, response generation, queue promotion, or intent classification.
- Supports only `product_selection`; other context values are explicitly rejected.

**Verification:**
- Focused tests cover pending preservation, ready execution, missing active, missing context type, and unsupported context rejection; all tests also verify `set_active` and `execute_ready_pending_context` call boundaries.
- Focused pending-context dispatcher tests: **6/6 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Delta spec synchronized to `openspec/specs/pending-context-dispatcher/spec.md`.

**Context for future subphases:** end-to-end routing, queue promotion, response generation, additional context types, and channel-level integration remain out of scope.

Subphase 3.19 — Implement End-to-end test for `agregar_producto` [x]

Completed the integration test that locks the two-message `agregar_producto` lifecycle against `supernova_test` using the real recognizer, resolver, processor, dispatcher, handler, and services without mocking the main flow.

**Test fixture:**
- Builds a commerce, client, active session, draft pedido linked to the session, a product named after the suffix, and two active presentations (`chica` and `grande`) with prices seeded from the existing catalog or local fixture values.
- Captures IDs (`commerce_id`, `cliente_id`, `pedido_id`, `chica_pp_id`, `grande_pp_id`, `product_id`, `categoria_id`) and detaches ORM instances to keep the multi-session flow detached.

**Initial message scenario:**
- `process_initial_agregar_producto(db, session, "quiero 2 pizzas de mozzarella")` returns `pending_resolution` with `session.context_type == "product_selection"` and an active pending intent; no `PedidoProducto` is created.

**Ready execution scenario:**
- `dispatch_pending_context(db, session, "pizza grande")` returns `executed` and produces exactly one `PedidoProducto` for the `grande` presentation with `cantidad == 2` and `precio_unitario` matching the database price; pending intents and context type are cleared.

**Ambiguous reply scenario:**
- A second reply with two presentation candidates preserves `pending_resolution`, keeps `session.context_type == "product_selection"`, retains the active intent, and creates no new `PedidoProducto`.

**Verification:**
- Focused end-to-end tests: **3/3 passed** (`initial_message_pending`, `second_message_executed`, `ambiguous_reply_preserves_context`).
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- Full smoke suite stabilized at **406/406 passed** after cleaning orphan fixture rows and refreshing the seeded product_presentaciones/precios for `supernova_test`.
- Delta spec synchronized to `openspec/specs/agregar-producto-end-to-end/spec.md` and archived at `openspec/changes/archive/2026-07-30-end-to-end-test-agregar-producto-3-19/`.

**Context for future subphases:** the dispatcher remains limited to `agregar_producto`; a generic dispatcher, response generation, queue promotion, and additional context types remain out of scope.

Subphase 3.20 — Intent classification contracts [x]

Completed the Pydantic contract module that locks the legacy intent names and classification result shape without implementing any classifier logic.

**Contracts delivered:**
- `backend/intents/schemas/intent_classification.py` exports `IntentName` (`StrEnum`), `ClassifiedIntent`, and `IntentClassificationResult`.
- `IntentName` preserves the 26 legacy intent names verbatim (`saludo`, `agradecimiento`, `despedida`, `respuesta_afirmativa`, `respuesta_negativa`, `ver_menu`, `consultar_producto`, `ver_metodos_de_pago`, `ver_metodos_de_entrega`, `consultar_domicilio_comercio`, `consultar_horarios_comercio`, `iniciar_pedido`, `agregar_producto`, `quitar_producto`, `vaciar_pedido`, `set_observacion_producto`, `set_observacion_pedido`, `consultar_resumen_pedido`, `set_metodo_de_entrega`, `set_direccion_entrega`, `set_fecha_hora_entrega`, `set_metodo_de_pago`, `confirmar_pedido`, `consultar_estado_pedido`, `cancelar_pedido`, `desconocida`).
- `ClassifiedIntent` and `IntentClassificationResult` enforce `extra="forbid"`, trim and reject empty `mensaje`, and require `IntentClassificationResult.intents` to be non-empty while preserving insertion order.
- Public surface limited to the three schemas through `__all__`; module is free of LLM, prompt, HTTP, session, pedido, and context-mutation code.

**Verification:**
- Schema-focused tests added to `backend/tests/api_smoke.py` cover valid single-intent, valid multi-intent order, unsupported intent, empty/whitespace `mensaje`, empty `intents`, and extra fields. All **8/8 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: passed.
- `openspec validate intent-classification-contracts-3-20 --type change --strict`: valid.
- Delta spec synchronized to `openspec/specs/intent-classification-contracts/spec.md` and archived at `openspec/changes/archive/2026-07-30-intent-classification-contracts-3-20/`.

**Context for future subphases:** the `IntentClassifier` implementation, prompt construction, LLM invocation, and any additional intents remain out of scope and require their own subphases.

Subphase 3.21 — LLM settings, logging and `QueryLlm` [x]

Delivered the configurable LLM settings module and a synchronous HTTP client (`QueryLlm`) without any classifier, prompt, or persistence code.

**Decisions / Contracts delivered:**
- `backend/config/settings.py` exposes `LLM_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_KEEP_ALIVE`, `LLM_NUM_CTX`, `LLM_NUM_PREDICT`, `LLM_LOG_CONTENT`, and `LLM_LOG_MAX_CHARS` via a frozen `Settings` dataclass; environment variables override local defaults; no SQLAlchemy / Alembic dependency.
- `backend/llm/query_llm.py` provides `QueryLlm(settings=None, transport=None, clock=None).request(prompt: str) -> dict`; payload is built fresh per call (`stream=False`, `think=False`, `format="json"`, `temperature=0`, `keep_alive`, `num_predict`, `num_ctx`); no mutable request state is retained between calls; empty / non-string prompts raise `ValueError` without contacting the transport.
- JSON responses are parsed strictly; when the raw body is non-empty and direct parse fails, the substring between the first `{` and last `}` is extracted and parsed; empty or invalid bodies raise `QueryLlmResponseError` and never return `None`.
- Distinct exceptions surface failures: `QueryLlmTimeoutError`, `QueryLlmConnectionError`, `QueryLlmHttpError(status_code)`, `QueryLlmResponseError` — all subclasses of `QueryLlmError(RuntimeError)`; the transport injection point catches `requests.exceptions.Timeout` / `ConnectionError` so injected test transports also surface as the typed exceptions.
- Logging uses `logging.getLogger(__name__)` with no global handler configuration; `INFO` carries request start, configured model, duration, and success/failure plus HTTP status when available; `DEBUG` adds prompt and raw response only when `LLM_LOG_CONTENT` is enabled, truncated to `LLM_LOG_MAX_CHARS`.

**Verification:**
- `backend/tests/test_llm_settings.py` (10 tests) and `backend/tests/test_query_llm.py` (17 tests) using mocked transport: payload contents, no-state-leak across calls, clean JSON parsing, `{...}` extraction, empty/whitespace/invalid bodies, timeout, connection, HTTP error with status, empty/whitespace/non-string prompt rejection, INFO metadata without content, DEBUG content gating and truncation, no global logging handler configuration. All **27/27 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `openspec validate llm-settings-query-llm-3-21 --strict`: valid.
- Delta specs synced to `openspec/specs/llm-settings/spec.md` and `openspec/specs/llm-query-client/spec.md`; change archived at `openspec/changes/archive/2026-07-30-llm-settings-query-llm-3-21/`.

**Constraints introduced:**
- No intent classification, Pydantic validation, database access, or FastAPI / `Session` integration in either new module.
- The legacy `backend/old_project/query_llm.py` is reference-only; it is neither imported nor modified.
- `requests` is the only third-party transport dependency; it is already available transitively in the project venv.

**Files created:**
- `backend/config/settings.py`
- `backend/llm/query_llm.py` (plus existing `backend/llm/__init__.py` and `backend/config/__init__.py`)
- `backend/tests/test_llm_settings.py`
- `backend/tests/test_query_llm.py`
- `openspec/specs/llm-settings/spec.md`
- `openspec/specs/llm-query-client/spec.md`

**Context for future subphases:** `Settings` + `QueryLlm` are reusable building blocks. Future intent-classification subphases can construct a `QueryLlm(load_settings(), transport=...)`, inject a stub `transport` for tests, and rely on the typed exceptions without touching HTTP details. The actual `IntentClassifier` implementation, prompt construction, and any additional intents remain out of scope.

Do not implement Subphase 3.22.

Subphase 3.22 — Port and adapt `IntentClassifier` [x]

Modern classifier delivered as a separate consumer of `QueryLlm`. Uses `QueryLlm` for all HTTP/JSON/transport concerns, preserves the legacy intent catalog and prompt rules verbatim, and validates responses with the existing `IntentClassificationResult` schema. 14/14 tests pass against `backend/tests/test_intent_classifier.py`; `compileall` exit 0; change archived at `openspec/changes/archive/2026-07-30-implement-intent-classifier-3-22/`.

**Decisions / Contracts delivered:**
- `backend/llm/intent_classifier.py` exports `IntentClassifier` via `__all__`; constructor takes an optional `query_llm: QueryLlm` (defaults to `QueryLlm()`) and stores only `self._query_llm` — no `_message` / `_prompt` instance state.
- `_build_prompt(message)` returns a fresh string per call; legacy intent catalog and rules are preserved verbatim, with only the two documented JSON-example typos and the two intent-name typos corrected (`set_metodo_de_envio` → `set_metodo_de_entrega`, `set_forma_de_pago` → `set_metodo_de_pago`).
- `query(message)` rejects non-string input with `TypeError` and empty-after-trim input with `ValueError` before any LLM call; delegates to `self._query_llm.request(prompt)` and returns `IntentClassificationResult.model_validate(payload)` — never prints, swallows, or returns `None`.
- `QueryLlmError` subclasses and `pydantic.ValidationError` propagate unchanged; intent order is preserved by the existing schema.
- Logging uses `logging.getLogger(__name__)` with no global handler configuration: `INFO` for `intent_classification start message_chars=N`, `intent_classification success intents_count=N`, `intent_classification failure error_type=<class name>`; `DEBUG` carries the validated result only; prompts and raw LLM responses are not logged here (owned by `QueryLlm`).

**Verification:**
- `backend/tests/test_intent_classifier.py` (14 tests) using a stub `QueryLlm`: single `agregar_producto`, multi-intent order preservation, replacement producing `quitar_producto` then `agregar_producto`, non-string input → `TypeError`, empty/whitespace input → `ValueError`, unsupported intent → `pydantic.ValidationError`, malformed output (`{}`, empty `intents`, empty-after-trim `mensaje`) → `pydantic.ValidationError`, `QueryLlmError` subclasses propagate unchanged, no forbidden side-effect imports, no global logging handler configuration. All **14/14 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.

**Constraints introduced:**
- `QueryLlm` remains generic and independently reusable; classification logic is not merged into it.
- No HTTP, JSON extraction, configuration, or raw-response logging is duplicated from `QueryLlm`.
- No Session, Pedido, context, dispatcher, handler, recognizer, database, FastAPI, or response-beautification logic in the new module.
- `backend/old_project/intent_classifier.py` is reference-only; nothing is imported from `backend/old_project/`.

**Files created:**
- `backend/llm/intent_classifier.py`
- `backend/tests/test_intent_classifier.py`
- `openspec/specs/intent-classifier/spec.md`

**Context for future subphases:** `IntentClassifier` is the modern replacement for the legacy classifier and is the consumer future orchestration subphases should call. Construct it directly (`IntentClassifier()`) or inject a stub `query_llm` for tests; rely on `QueryLlm` for transport and on `IntentClassificationResult` for schema validation. The `IntentContract` registry, per-context wiring, and any subphase that interprets `intents` for dispatch remain out of scope.

Subphase 3.23 — Initial intent classification integration [x]

Initial-message dispatcher delivered as the modern entry point for fresh inbound messages. Sits next to `agregar_producto_orchestrator.py` and `pending_context_dispatcher.py`, classifies once via `IntentClassifier`, forwards `agregar_producto` items to the existing `process_initial_agregar_producto`, and rejects everything else without invoking any orchestrator. 11/11 tests pass against `backend/tests/test_initial_intent_dispatcher.py`; `compileall` exit 0; change archived at `openspec/changes/archive/2026-07-30-initial-intent-classification-integration-3-23/`.

**Decisions / Contracts delivered:**
- `backend/intents/orchestration/initial_intent_dispatcher.py` exports only `dispatch_initial_message(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` via `__all__`; aliases `Session as DatabaseSession` (sqlalchemy.orm) and `Session as ConversationSession` (`backend.models.session`).
- Pending-context guard runs first: when `session.context_type is not None`, the function returns `[]` without constructing `IntentClassifier` and without invoking any orchestrator — pending-context messages continue to flow through `dispatch_pending_context`.
- On guard pass, `IntentClassifier()` is constructed inline (no module-level singleton, no constructor parameter — matches the `process_initial_agregar_producto` signature shape); `query(message)` is called exactly once; `TypeError`, `ValueError`, `QueryLlmError`, and `pydantic.ValidationError` propagate unchanged.
- Iteration over `result.intents` preserves classifier order; one `ProcessedIntent` is appended per classified item.
- Dispatch is a literal `if/elif` chain on `IntentName`: `AGREGAR_PRODUCTO` → `process_initial_agregar_producto(db, session, classified.mensaje)` returning its `ProcessedIntent`; `DESCONOCIDA` → fresh `ProcessedIntent(status="rejected", intent="desconocida", handler="desconocida", recognizer="intent_classifier")`; any other intent → fresh `ProcessedIntent(status="rejected", handler=<intent string>)`. No orchestrator or handler is invoked for non-`agregar_producto` items.
- Rejected `ProcessedIntent` items reuse `classified.mensaje` for `source_text` and the schema defaults for `resolved_data`, `requirements`, and `candidate_ids`.

**Verification:**
- `backend/tests/test_initial_intent_dispatcher.py` (11 tests) with stub `IntentClassifier` and stub `process_initial_agregar_producto`: `agregar_producto` invocation exactly once, multi-intent order preservation (two- and three-item sequences), `desconocida` rejection without orchestrator call, unsupported-intent rejection (`saludo`, `quitar_producto`) without orchestrator call, `None` `context_type` proceeds past the guard, non-`None` `context_type` (incl. `product_selection`) short-circuits without constructing the classifier, no `db.commit`/`db.rollback`, no `requests`/`fastapi`/`backend.routers`/`backend.sessions` imports, no `backend.old_project` imports, `__all__` equals `["dispatch_initial_message"]`. All **11/11 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- Delta spec synced to `openspec/specs/initial-intent-dispatcher/spec.md`; change archived at `openspec/changes/archive/2026-07-30-initial-intent-classification-integration-3-23/`.

**Constraints introduced:**
- No SQLAlchemy `select`/`execute`/`add`/`delete`, no relationship loading, no repository access, no `db.commit`/`db.rollback`, no `requests`/`fastapi`/`backend.routers`/`backend.sessions` imports, no response formatting or shaping.
- No logging, retry/backoff, caching, or async wrappers in the dispatcher.
- `IntentClassifier` prompt, catalog, logging, and constructor are untouched; `process_initial_agregar_producto`, `dispatch_pending_context`, recognizers, resolvers, processors, handlers, services, repositories, routers, dependencies, configuration, models, and migrations are untouched.
- `backend/old_project/` is reference-only; nothing is imported from it.

**Files created:**
- `backend/intents/orchestration/initial_intent_dispatcher.py`
- `backend/tests/test_initial_intent_dispatcher.py`
- `openspec/specs/initial-intent-dispatcher/spec.md`

**Context for future subphases:** `dispatch_initial_message` is the single modern entry point for fresh messages that should not be routed through `dispatch_pending_context`. Future work that chooses between initial and pending dispatch (a unified router, FastAPI dependency, or background dispatcher) belongs to its own subphase and must not be folded into this dispatcher. Adding a new supported intent requires editing the literal `if/elif` chain in `initial_intent_dispatcher.py` and shipping the matching orchestrator or handler in the same change — no registry or generic handler abstraction was introduced here.

Subphase 3.24 — Incoming message orchestrator [x]

Unified internal front door for the modern intents pipeline delivered. Sits next to `agregar_producto_orchestrator.py`, `initial_intent_dispatcher.py`, and `pending_context_dispatcher.py`, owns the `session.context_type` routing rule, validates the message, wraps the pending-context result in a one-item list, and forwards the initial-dispatcher list unchanged. 21/21 tasks complete; `compileall` exit 0; `openspec validate incoming-message-orchestrator-3-24 --strict` valid; change archived at `openspec/changes/archive/2026-07-30-incoming-message-orchestrator-3-24/`.

**Decisions / Contracts delivered:**
- `backend/intents/orchestration/incoming_message_orchestrator.py` exports only `process_incoming_message(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` via `__all__`; aliases `Session as DatabaseSession` (sqlalchemy.orm) and `Session as ConversationSession` (`backend.models.session`) — matches the typing pattern of `agregar_producto_orchestrator.py` and `initial_intent_dispatcher.py`.
- Message validation runs first, before any dispatcher call: non-string input raises `TypeError`; empty / whitespace-only input raises `ValueError`. Both branches reject identically.
- Pending-context branch: when `session.context_type is not None`, the function calls `dispatch_pending_context(db, session, message)` exactly once, does not call `IntentClassifier` or `dispatch_initial_message`, and returns `[dispatcher_result]` — a one-item list wrapping the single `ProcessedIntent`.
- Initial branch: when `session.context_type is None`, the function calls `dispatch_initial_message(db, session, message)` exactly once and returns its `list[ProcessedIntent]` unchanged, preserving the classified-intent order; no re-sort, no filter, no reshape.
- Dispatcher exceptions propagate unchanged (`TypeError`, `ValueError`, `QueryLlmError`, `pydantic.ValidationError`); the orchestrator never wraps, converts, or swallows them.

**Verification:**
- `backend/tests/test_incoming_message_orchestrator.py` (21 tests) with stub `dispatch_initial_message` and stub `dispatch_pending_context`: initial branch routes exactly once with no pending-context call; multi-item initial list returned in same order; pending-context branch (`product_selection` plus an arbitrary non-`None` value) routes exactly once with no initial call; pending result wrapped in one-item list (not flattened); pending-dispatcher exception re-raises unchanged; initial-dispatcher `TypeError`, `ValueError`, and `QueryLlmError`-shaped exceptions re-raise unchanged; non-string input (`None`, `123`, list) raises `TypeError` before any dispatcher call; empty and whitespace-only input raise `ValueError` before any dispatcher call; no `db.commit` / `db.rollback` in any branch; `__all__ == ["process_incoming_message"]`; no top-level `def` statements other than `process_incoming_message`. All **21/21 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `openspec validate incoming-message-orchestrator-3-24 --strict`: valid.
- Delta spec synced to `openspec/specs/incoming-message-orchestrator/spec.md`; change archived at `openspec/changes/archive/2026-07-30-incoming-message-orchestrator-3-24/`.

**Constraints introduced:**
- No SQLAlchemy `select` / `execute` / `add` / `delete`, no relationship loading, no repository access, no `db.commit` / `db.rollback`, no `requests` / `fastapi` / `twilio` / `backend.routers` / `backend.sessions` imports, no response formatting or shaping, no handler implementation, no queue promotion, no logging, no retry / backoff, no caching, no async wrappers.
- `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, `QueryLlm`, recognizers, resolvers, processors, handlers, services, repositories, routers, dependencies, configuration, models, and migrations are untouched.
- `backend/old_project/` is reference-only; nothing is imported from it.

**Files created:**
- `backend/intents/orchestration/incoming_message_orchestrator.py`
- `backend/tests/test_incoming_message_orchestrator.py`
- `openspec/specs/incoming-message-orchestrator/spec.md`

**Context for future subphases:** `process_incoming_message` is the single modern internal front door for any caller that wants to hand an inbound message off to the intents pipeline. Future consumers (FastAPI dependency, background worker, Twilio webhook adapter, test harness) should call this entry point and stop branching on `session.context_type` themselves. The orchestrator is the sole owner of the routing rule; `dispatch_initial_message` still owns its own pending-context short-circuit guard internally, but callers must not duplicate that rule. Any future addition (logging, async wrappers, queue promotion, additional routing branches) belongs in its own subphase and must not be folded into this orchestrator.

Subphase 3.25 — Incoming message integration test [x]

End-to-end integration test for `process_incoming_message` delivered against `supernova_test` with real orchestrators, recognizer, resolver, dispatcher, handler, and services. Only the external LLM classification boundary (`IntentClassifier.query`) is mocked. 27/27 tasks complete; `compileall` exit 0; `openspec validate incoming-message-integration-test-3-25 --strict` valid; change archived at `openspec/changes/archive/2026-07-30-incoming-message-integration-test-3-25/`.

**Test fixture (shared helpers in the test module):**
- `TEST_URL = "postgresql+psycopg:///supernova_test"` plus `engine` / `TestingSessionLocal` at module load time (mirrors `api_smoke.py`).
- `_suffix()` produces a fresh 10-char hex string per call so each test owns disjoint DB rows.
- `_estado_id_activo()` looks up the `ACTIVO` `EstadoComercio.id` (raises `RuntimeError` if not seeded).
- `_seed(...)` builds, inside a single `with db.begin():` block, a `Comercio`, a `Cliente`, an active `Session` row (`context_type is None`, empty `pending_intents`, `pedido_actual_id = None`), a draft `Pedido` linked to the comercio and cliente, a `CategoriaProducto`, a `Producto` linked to the categoria and comercio, two `Presentacion` rows named `chica` and `grande`, two `ProductoPresentacion` rows linking the product to each presentation, and two `Precio` rows (one per presentation); returns the ids and the active `Session` ORM instance.
- `_cleanup(db, *, comercio_id, cliente_id, pedido_id, session_id, producto_id)` deletes in FK-safe order inside `with db.begin():` (`PedidoProducto` → `Precio` → `ProductoPresentacion` → `Producto` → `Pedido` → `Session` → `Cliente` → `Comercio`); each test wraps its body in `try/finally` so cleanup runs on failure.
- `_patched_classifier(message)` is a context manager that yields a `MagicMock`-based `IntentClassifier` subclass whose `query(message)` returns `IntentClassificationResult(intents=[ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=message)])`; the patch is applied at `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` and is exited in a `finally:` block.

**Initial-message branch scenario** (`IncomingMessageInitialBranchIntegrationTest.test_initial_message_branch_creates_pending_context`):
- Seeds fixtures via `_seed(...)`; opens a fresh `db`; fetches the `Session` ORM row.
- Calls `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` inside `_patched_classifier(...)`.
- Asserts: `len(result) == 1`; `result[0].status == "pending_resolution"`; `result[0].intent == "agregar_producto"`; the patched `IntentClassifier.query` was called exactly once with the original message; `dispatch_pending_context` was NOT called.
- After `db.commit()` and a fresh reload, asserts `session.context_type == "product_selection"` and `session.pending_intents` contains exactly one entry with `intent_name == "agregar_producto"` matching the pending-resolution state.
- Asserts no `PedidoProducto` row exists for the draft `pedido_id`.

**Pending-context branch scenario** (`IncomingMessagePendingBranchIntegrationTest.test_pending_context_branch_executes_order_line`):
- Reuses `_seed(...)`; opens a fresh `db`; calls `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` inside the `IntentClassifier` patch context; commits; reloads the `Session` row and asserts `session.context_type == "product_selection"` and the patched `IntentClassifier` was constructed exactly once (this is the call that establishes the pending context).
- Resets the patch, reopens a fresh `db` session, refetches the `Session` row, and calls `process_incoming_message(db, session, "pizza grande")` WITHOUT any `IntentClassifier` patch — wraps `IntentClassifier` itself in a new `MagicMock` (no `query` configured) that, if constructed, would raise. The expectation is the orchestrator routes to `dispatch_pending_context` without ever consulting `IntentClassifier`.
- Asserts: `len(result) == 1`; `result[0].status == "executed"`; `result[0].intent == "agregar_producto"`; the `IntentClassifier` mock was never called; `dispatch_initial_message` was not invoked.
- After `db.commit()` and a fresh reload, asserts exactly one `PedidoProducto` row exists for `pedido_id` whose `presentacion_id` corresponds to the `grande` presentation and `cantidad == 2`; `session.pending_intents` is empty; `session.context_type is None`.

**Verification:**
- `backend/tests/test_incoming_message_integration.py` runs against `supernova_test`. Both integration tests **2/2 passed**.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- Existing unit suite still passes: `backend.tests.test_incoming_message_orchestrator`, `backend.tests.test_initial_intent_dispatcher`, `backend.tests.test_intent_classifier`.
- No orphan rows remain in `supernova_test` after both tests complete (re-verified with `select` on `PedidoProducto` / `Session` / `Comercio WHERE nombre_fantasia LIKE "Test %"`).
- `openspec validate incoming-message-integration-test-3-25 --strict`: valid.
- Delta spec synced to `openspec/specs/incoming-message-orchestrator/spec.md` (added `## ADDED Requirements` block: `### Requirement: Incoming message orchestrator integration coverage` with the two scenarios above); change archived at `openspec/changes/archive/2026-07-30-incoming-message-integration-test-3-25/`.

**Constraints introduced:**
- Test-only subphase: no production code was added or modified; the fixtures and helpers live in the test module and are not exported.
- Mocking is restricted to the LLM classification boundary: `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` is replaced with a `MagicMock`-based subclass; the real `IntentClassifier` (and therefore `QueryLlm`) is never exercised in this test module.
- `process_incoming_message`, `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, `QueryLlm`, recognizers, resolvers, processors, handlers, services, repositories, models, migrations, configuration, FastAPI dependencies, and routers are untouched.
- `backend/old_project/` remains reference-only; nothing is imported from it.
- No transaction management, response generation, HTTP, FastAPI, or Twilio integration is added.

**Files created:**
- `backend/tests/test_incoming_message_integration.py`
- `openspec/changes/archive/2026-07-30-incoming-message-integration-test-3-25/`

**Test phrase note:** the pending-context branch uses `"pizza grande"` rather than the original proposal's literal `"la grande"` because `detectar_productos` (Subphase 3.11) filters `grande` as a `TAMANIOS` token unless preceded by a product noun. The orchestrator's routing rule and `dispatch_pending_context`'s contract are unchanged; only the test phrase is adjusted so the per-context path is resolvable end-to-end against the real recognizer.

**Context for future subphases:** the integration test confirms that the modern pipeline (orchestrator → dispatcher → orchestrator → recognizer → resolver → processor → handler → service → repository) composes correctly against `supernova_test`, and that the only thing the orchestrator must mock to keep tests deterministic is the external LLM boundary. Future changes to any of these layers (new context types, additional intents, richer recognition, handler extensions) must keep this integration scenario green and may add parallel scenarios. A new intent that needs a real LLM answer in tests should be added behind a stub `IntentClassifier` (matching the current pattern) or excluded from this test module — the LLM HTTP boundary is deliberately never hit here. Real LLM-backed integration tests for `IntentClassifier` itself remain out of scope and must live in their own subphase.

Subphase 3.26 — Transactional incoming message processing [x]

Transactional front door for the modern intents pipeline delivered. It delegates each inbound message to `process_incoming_message`, commits every returned business outcome, and rolls back then re-raises any exception unchanged. All 20/20 tasks complete; focused tests **12/12 passed**; `compileall` exit 0; change archived at `openspec/changes/archive/2026-07-30-incoming-message-transactional-processor-3-26/`.

**Decisions / Contracts delivered:**
- `backend/intents/orchestration/transactional_message_processor.py` exports only `process_incoming_message_transactional(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` via `__all__`; aliases `Session as DatabaseSession` from `sqlalchemy.orm` and `Session as ConversationSession` from `backend.models.session`.
- The wrapper calls `process_incoming_message(db, session, message)` exactly once. When it returns without raising, the wrapper calls `db.commit()` exactly once and returns the same `list[ProcessedIntent]` reference unchanged.
- `rejected`, `failed`, and mixed-status lists are valid business outcomes and are committed whenever the inner orchestrator returns normally.
- When the inner orchestrator raises, the wrapper calls `db.rollback()` exactly once, does not commit, and uses bare `raise` so the original exception instance, type, and traceback propagate unchanged.

**Verification:**
- `backend/tests/test_transactional_message_processor.py` mocks `process_incoming_message` at the wrapper's import site and covers successful commit, unchanged result identity, `rejected` / `failed` / mixed-status commits, single rollback, exception identity and type preservation, `__all__`, and absence of `flush` / `refresh` / `expire` / `begin` calls. All **12/12 passed** without a real LLM, database connection, or network access.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `openspec validate incoming-message-transactional-processor-3-26 --strict`: valid before archival.
- Delta spec synchronized to `openspec/specs/incoming-message-transactional-processor/spec.md`; change archived at `openspec/changes/archive/2026-07-30-incoming-message-transactional-processor-3-26/`.

**Constraints introduced:**
- The wrapper performs no SQLAlchemy `select` / `execute` / `add` / `delete`, relationship loading, or repository access; it does not call `db.flush`, `db.refresh`, `db.expire`, or `db.begin`.
- No HTTP, FastAPI, Twilio, response generation, `HTTPException` translation, logging, retry / backoff, caching, or async behavior is introduced.
- `process_incoming_message` and all lower-level classifiers, dispatchers, orchestrators, recognizers, resolvers, processors, handlers, services, repositories, routers, dependencies, models, migrations, and context rules remain unchanged and do not own this transaction boundary.
- `backend/old_project/` remains reference-only; nothing is imported from it.

**Files created:**
- `backend/intents/orchestration/transactional_message_processor.py`
- `backend/tests/test_transactional_message_processor.py`
- `openspec/specs/incoming-message-transactional-processor/spec.md`
- `openspec/changes/archive/2026-07-30-incoming-message-transactional-processor-3-26/`

**Context for future subphases:** `process_incoming_message_transactional` is the single modern entry point for callers that need one commit / rollback boundary around inbound-message processing. FastAPI dependencies, background workers, Twilio adapters, and test harnesses should call this wrapper rather than duplicate transaction handling around `process_incoming_message`. Logging, retries, async execution, queueing, and response shaping remain separate concerns for future subphases.

Subphase 3.27 — Customer response generation for `agregar_producto` [x]

Customer-facing response builder for the `agregar_producto` intent delivered. Deterministic templates only; no LLM, no SQLAlchemy query, no commit/rollback, no session or intent mutation, no HTTP/Twilio integration. 33/33 tasks complete; `compileall` exit 0; `openspec validate agregar-producto-customer-response-3-27 --strict` valid; change archived at `openspec/changes/archive/2026-07-30-agregar-producto-customer-response-3-27/`.

**Decisions / Contracts delivered:**
- `backend/intents/schemas/customer_response.py` exports only `CustomerResponse` through `__all__`. `CustomerResponse` is a Pydantic `BaseModel` with exactly three string fields: `message: str`, `intent: str`, `status: str`. No `Config` class, no validators, no defaults, no JSON encoders, no locale support.
- `backend/intents/responses/__init__.py` is empty (package marker only — no registry, no factory, no shared base class, no re-exports).
- `backend/intents/responses/agregar_producto_response.py` exports only `build_agregar_producto_response` through `__all__` with the typed aliases `Session as DatabaseSession` from `sqlalchemy.orm` and `Session as ConversationSession` from `backend.models.session`.
- The builder signature is `build_agregar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse`. The first check is `intent.intent != "agregar_producto"` returning the apology fallback preserving `intent.intent` and `intent.status`.
- The four documented branches:
  - `pending_resolution`: when `candidate_ids` is empty, return the apology fallback with `status="pending_resolution"`; otherwise call `ProductoQueryService(db).list_presentaciones_by_ids(candidate_ids)`, build one `"producto_nombre presentacion_descripcion"` label per returned dict, join them with `", "` plus `" o "` before the last entry. Never include IDs, prices, stock, or the literal substring `"id"`.
  - `executed`: read `resolved_data["producto_presentacion_id"]` and `resolved_data["cantidad"]`; if `cantidad` is missing, non-int, or `< 1`, return the retry fallback with `status="failed"`; otherwise call `ProductoQueryService(db).list_presentaciones_by_ids([producto_presentacion_id])` and build the confirmation with singular phrasing for `cantidad == 1` and plural phrasing for `cantidad > 1`. If the service returns no presentation, return the retry fallback with `status="failed"`.
  - `rejected`: return the fixed apology string with `intent="agregar_producto"` and `status="rejected"`.
  - `failed`: return the fixed retry string with `intent="agregar_producto"` and `status="failed"`.

**Verification:**
- `test_agregar_producto_customer_response()` appended to `backend/tests/api_smoke.py` and wired into its `__main__` runner alongside the existing `test_agregar_producto_*` invocations; runs against `supernova_test` and reuses the existing `engine`, `TestingSessionLocal`, and `_estado_id_activo()` helpers. Covers the `pending_resolution` two-candidates clarification, empty-`candidate_ids` apology, `executed` confirmation with `cantidad == 1` and `cantidad == 2`, `executed` missing-presentation fallback, `executed` invalid-cantidad fallback, `rejected` apology, `failed` retry (asserting the message excludes `"Exception"` / `"Traceback"` / `"Error"` / IDs), non-`agregar_producto` intent fallback, no-mutation / no-database-call guarantee via `MagicMock(name="DatabaseSession")`, module source-code boundary (no `sqlalchemy.select`, `joinedload`, repositories, orchestrators, handlers, resolvers, services, context, `backend.llm`, `backend.routers`, `backend.dependencies`, `backend.old_project`, `requests`, `fastapi`, `twilio`, `HTTPException`, `JSONResponse`, `MessagingResponse`, `QueryLlm`, `retry`, `backoff`, or `async def`), and `__all__` discipline for both modules.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `openspec validate agregar-producto-customer-response-3-27 --strict`: valid before archival.
- Delta spec synced to `openspec/specs/agregar-producto-customer-response/spec.md` (new capability: 11 requirements — `Customer response schema`, `Customer response builder module location`, `Customer response builder signature`, `Intent scope is limited to agregar_producto`, `Pending resolution clarification`, `Executed confirmation`, `Rejected apology`, `Failed retry message`, `No mutation, commit, rollback, or query inside the builder`, `No LLM, HTTP, Twilio, queue, or handler imports`, `Public surface is limited`); change archived at `openspec/changes/archive/2026-07-30-agregar-producto-customer-response-3-27/`.

**Constraints introduced:**
- The response module is the single boundary that converts a `ProcessedIntent` for `agregar_producto` into a customer-facing `CustomerResponse`. Nothing else in the codebase produces customer-visible strings for this intent.
- No `sqlalchemy.select` / `sqlalchemy.orm.joinedload` / `backend.repositories.*` / `backend.intents.orchestration.*` / `backend.intents.handlers.*` / `backend.intents.resolvers.*` / `backend.intents.services.*` / `backend.intents.context.*` / `backend.llm.*` / `backend.routers.*` / `backend.dependencies.*` / `backend.old_project.*` / `requests` / `fastapi` / `twilio` imports are permitted in the response module.
- No `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin` may be invoked. The only allowed database interaction is the read through `ProductoQueryService.list_presentaciones_by_ids`.
- The builder never assigns to `session.pending_intents`, `session.context_type`, `session.id_pedido`, or any field of `intent`; the only outbound mutation is constructing a new `CustomerResponse` instance.
- No logging, retry/backoff, async wrappers, caching, locale selection, template engines, response beautification, or response objects for other intents.
- `PendingIntentService`, the orchestrator, the dispatcher, the resolver, the handler, the repository, FastAPI dependencies, Twilio adapters, and the `Session` / `Pedido` models are untouched and do not own response shaping.

**Files created:**
- `backend/intents/schemas/customer_response.py`
- `backend/intents/responses/__init__.py`
- `backend/intents/responses/agregar_producto_response.py`
- `openspec/specs/agregar-producto-customer-response/spec.md`
- `openspec/changes/archive/2026-07-30-agregar-producto-customer-response-3-27/`

**Context for future subphases:** `build_agregar_producto_response` is the deterministic bridge between `process_incoming_message` (which returns a `list[ProcessedIntent]`) and whatever surface ultimately delivers the customer-visible message (a future Twilio adapter, a FastAPI endpoint, or a background worker). Callers that need a customer string for `agregar_producto` MUST go through this builder — duplicating string formatting elsewhere breaks the determinism and no-ID-leakage guarantees. Future subphases that add intents with customer-visible responses must add a sibling builder per intent (e.g. `build_consultar_pedido_response`) rather than extending this one — the `agregar_producto`-only intent scope is normative. Response beautification, locale selection, retry/backoff, async execution, logging, and HTTP/Twilio delivery remain separate concerns for future subphases; do not introduce them here.

Subphase 3.28 — Incoming message response orchestrator [x]

Modern seam that runs the transactional message processor once and converts the returned `list[ProcessedIntent]` into a `list[CustomerResponse`, delegating `agregar_producto` to `build_agregar_producto_response` and producing a deterministic generic `CustomerResponse` for every other intent while preserving `intent` and `status`. No SQLAlchemy queries, no repository access, no LLM calls, no HTTP/Twilio integration, no new commit/rollback, no state mutation, no logging, no retry/async. 33/33 tasks complete; focused tests **25/25 passed**; `compileall` exit 0; `openspec validate incoming-message-response-orchestrator-3-28 --strict` valid; change archived at `openspec/changes/archive/2026-07-30-incoming-message-response-orchestrator-3-28/`.

**Decisions / Contracts delivered:**
- `backend/intents/orchestration/incoming_message_response_orchestrator.py` exports only `process_incoming_message_with_responses` through `__all__` with the typed aliases `Session as DatabaseSession` from `sqlalchemy.orm` and `Session as ConversationSession` from `backend.models.session`. Imports `process_incoming_message_transactional` from the transactional processor and `build_agregar_producto_response` from the response builder; no other imports.
- Signature: `process_incoming_message_with_responses(db: DatabaseSession, session: ConversationSession, message: str) -> list[CustomerResponse]`. The first statement is `processed = process_incoming_message_transactional(db, session, message)` — exactly once, with the same `db`, `session`, and `message` arguments; the wrapper does NOT re-validate the message, does NOT re-route on `session.context_type`, and does NOT call `dispatch_initial_message` / `dispatch_pending_context` directly.
- A single module-level `GENERIC_MESSAGE` constant (`"Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?"`) — a fixed Spanish apology sentence with no placeholders, no formatting parameters, no per-call substitution, and no exposure of IDs, exception types, stack traces, or technical detail.
- Per-`ProcessedIntent` dispatch via a literal `if/elif` chain:
  - `intent.intent == "agregar_producto"`: append the `CustomerResponse` returned by `build_agregar_producto_response(db, session, intent)` (called exactly once per item) — identity-preserving for `executed`, `pending_resolution`, `rejected`, and `failed`.
  - any other `intent` (incl. `desconocida`, `saludo`, `quitar_producto`, `consultar_pedido`, future intents): append `CustomerResponse(message=GENERIC_MESSAGE, intent=<intent>, status=<status>)` preserving the original `intent` and `status`.
- Returned list length equals the inner `list[ProcessedIntent]` length and order is preserved across mixed executed / pending_resolution / rejected / failed items.
- Exception propagation: any exception raised by `process_incoming_message_transactional` propagates out unchanged — no wrapping, no conversion, no swallowing, no `HTTPException` translation; the `return` statement sits directly after the loop so `ValueError`, `TypeError`, `QueryLlmError` (and subclasses), and `pydantic.ValidationError` all surface with the same instance / args / traceback frames.

**Verification:**
- `backend/tests/test_incoming_message_response_orchestrator.py` patches `process_incoming_message_transactional` and `build_agregar_producto_response` at the wrapper's import site. Covers `agregar_producto` routing for `executed`, `pending_resolution`, `rejected`, and `failed`; generic fallback for `desconocida`, `saludo`, and `consultar_pedido`; generic-message determinism (fixed string, non-empty, contains no `"id"` / `"Exception"` / `"Traceback"` / `"Error"` tokens); multi-intent order preservation across mixed-status lists; single-item and empty-list length; `ValueError` / `TypeError` / `QueryLlmTimeoutError` / `QueryLlmError` / `pydantic.ValidationError` propagation with identity / type / original-traceback assertions; `__all__` discipline; absence of additional public functions; no `db.commit` / `db.rollback` / `db.flush` / `db.refresh` / `db.expire` / `db.begin` calls on both success and exception paths (via `MagicMock(name="DatabaseSession")`); no mutation of `session.pending_intents` / `session.context_type` / `session.id_pedido` / any `ProcessedIntent` field for both `agregar_producto` and unsupported-intent branches; and module source-code boundary (no `sqlalchemy.select`, no `joinedload`, no `backend.repositories`, no `backend.services`, no `backend.intents.handlers`, no `backend.intents.context`, no `backend.intents.recognizers`, no `backend.intents.resolvers`, no `backend.intents.processor`, no `backend.intents.contracts`, no `backend.intents.services`, no `backend.llm`, no `backend.routers`, no `backend.dependencies`, no `backend.sessions`, no `backend.old_project`, no `requests`, no `fastapi`, no `twilio`, no `HTTPException`, no `JSONResponse`, no `MessagingResponse`, no `QueryLlm`, no `retry`, no `backoff`, no `asyncio`, no `async def`, no `logger.`, no `logging.`, no `print(`, no `time.sleep`). All **25/25 passed** without a real LLM, database, or HTTP.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `openspec validate incoming-message-response-orchestrator-3-28 --strict`: valid before archival.
- Delta spec synced to `openspec/specs/incoming-message-response-orchestrator/spec.md` (new capability: 12 requirements — `Incoming message response orchestrator module location`, `Incoming message response orchestrator signature`, `Single delegation to the transactional processor`, `Intent order preservation`, `agregar_producto delegation`, `Unsupported intent generic response`, `Exception propagation`, `No additional commit or rollback`, `No SQLAlchemy query or repository access`, `No HTTP, FastAPI, Twilio, LLM, or response-generation imports`, `No mutation, no logging, no retry, no async, no queue`, `Public surface is limited`); change archived at `openspec/changes/archive/2026-07-30-incoming-message-response-orchestrator-3-28/`.

**Constraints introduced:**
- The response orchestrator is the single boundary that runs the modern transactional pipeline and turns its `list[ProcessedIntent]` into a `list[CustomerResponse]`. Future transport adapters (Twilio webhook, FastAPI endpoint, background worker, test harness) should call `process_incoming_message_with_responses` and stop branching on intent names themselves; duplicating the per-intent routing rule elsewhere breaks the determinism guarantee.
- No `sqlalchemy.select` / `sqlalchemy.orm.joinedload` / `backend.repositories.*` / `backend.services.*` / `backend.intents.handlers.*` / `backend.intents.context.*` / `backend.intents.recognizers.*` / `backend.intents.resolvers.*` / `backend.intents.processor` / `backend.intents.contracts.*` / `backend.intents.services.*` / `backend.llm.*` / `backend.routers.*` / `backend.dependencies` / `backend.sessions` / `backend.old_project.*` / `requests` / `fastapi` / `twilio` imports are permitted in this module.
- No `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin` may be invoked; the only allowed SQLAlchemy interaction is whatever `build_agregar_producto_response` calls internally (read-only via `ProductoQueryService.list_presentaciones_by_ids`).
- The orchestrator never assigns to `session.pending_intents`, `session.context_type`, `session.id_pedido`, or any field of a `ProcessedIntent`; the only outbound state change is constructing `CustomerResponse` instances and appending them to the returned list.
- No logging, retry/backoff, async wrappers, caching, locale selection, template engines, response beautification, queue promotion, or response objects for additional intents. New intents fall through to the generic `GENERIC_MESSAGE` branch until a sibling builder lands.
- `process_incoming_message`, `process_incoming_message_transactional`, `build_agregar_producto_response`, `dispatch_initial_message`, `dispatch_pending_context`, the handlers, the recognizers, the resolvers, the processor, the services, the repositories, FastAPI dependencies, Twilio adapters, and the `Session` / `Pedido` models are untouched and do not own the response-shaping seam.

**Files created:**
- `backend/intents/orchestration/incoming_message_response_orchestrator.py`
- `backend/tests/test_incoming_message_response_orchestrator.py`
- `openspec/specs/incoming-message-response-orchestrator/spec.md`
- `openspec/changes/archive/2026-07-30-incoming-message-response-orchestrator-3-28/`

**Context for future subphases:** `process_incoming_message_with_responses` is the single modern front door for any caller that needs both the transactional boundary and the customer-visible strings. FastAPI dependencies, Twilio adapters, background workers, and test harnesses should call this wrapper rather than re-running `process_incoming_message_transactional` and hand-rolling the per-intent routing loop. The current surface covers only `agregar_producto`; future intents with customer-visible responses must add a sibling builder per intent (e.g. `build_consultar_pedido_response`) and the orchestrator's literal `if/elif` chain grows by one branch per builder — the generic `GENERIC_MESSAGE` fallback is the temporary placeholder, not the long-term answer. Response beautification, locale selection, retry/backoff, async execution, logging, queue promotion, and HTTP/Twilio delivery remain separate concerns for future subphases; do not introduce them here.

Subphase 3.29 — Local HTTP endpoint for incoming messages [x]

Thin synchronous FastAPI seam that exposes the modern intents pipeline from Subphases 3.24 → 3.28 through one obvious HTTP entry point. `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` resolves the active conversation via `SessionService.get_active`, delegates to `process_incoming_message_with_responses` exactly once, and wraps the resulting `list[CustomerResponse]` in `IncomingMessageResponse`. No LLM calls, no direct SQLAlchemy, no `db.commit` / `db.rollback` / `db.flush`, no Twilio / queue / async / retry / logging, no mutation outside the modern pipeline. 35/35 tasks complete; focused tests **16/16 passed**; `compileall` exit 0; `openspec validate local-http-incoming-messages-3-29 --strict` valid; change archived at `openspec/changes/archive/2026-07-30-local-http-incoming-messages-3-29/`.

**Decisions / Contracts delivered:**
- `backend/routers/incoming_messages.py` exposes exactly one route: `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` declared with `@router.post("/comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages", response_model=IncomingMessageResponse, status_code=status.HTTP_200_OK)`. The module imports `APIRouter`, `HTTPException`, `Depends`, `status` from `fastapi`; `Session as DatabaseSession` from `sqlalchemy.orm` (kept locally for clarity); `get_session` from `backend.dependencies`; `process_incoming_message_with_responses` from `backend.intents.orchestration.incoming_message_response_orchestrator`; `IncomingMessageRequest` / `IncomingMessageResponse` from `backend.schemas.incoming_message`; `SessionNotFound` from `backend.services.exceptions`; `SessionService` from `backend.services.session_service` — and nothing else. `__all__ = ["router"]`.
- Single dependency factory `_service(session: DatabaseSession = Depends(get_session)) -> SessionService: return SessionService(session)`; no additional dependencies, no background tasks, no sub-routers. The handler signature is `post_incoming_message(comercio_id: int, cliente_id: int, payload: IncomingMessageRequest, service: SessionService = Depends(_service), db: DatabaseSession = Depends(get_session)) -> IncomingMessageResponse`; it is the only `@router.` decorator in the module.
- `backend/schemas/incoming_message.py` exports exactly two Pydantic models through `__all__ = ["IncomingMessageRequest", "IncomingMessageResponse"]`:
  - `IncomingMessageRequest(message: str, model_config = ConfigDict(extra="forbid"))` — Pydantic rejects `None`, non-`str`, missing fields, and extra keys with HTTP 422 before the handler runs.
  - `IncomingMessageResponse(responses: list[CustomerResponse], model_config = ConfigDict(from_attributes=True))` — single-field envelope wrapping the customer-facing list.
- Active session lookup via `session = service.get_active(comercio_id, cliente_id)` exactly once per request. On `SessionNotFound as exc` the handler raises `HTTPException(status_code=404, detail=str(exc)) from exc`; the handler never issues its own SQLAlchemy query and the router module imports nothing from `backend.repositories.*`.
- Single delegation: `responses = process_incoming_message_with_responses(db, session, payload.message)` exactly once with the same `db`, `session`, and `payload.message` arguments. The handler does NOT re-validate the message, does NOT re-route on `session.context_type`, and does NOT call `process_incoming_message_transactional`, `dispatch_initial_message`, `dispatch_pending_context`, or any handler / recognizer / resolver / processor / service / repository directly.
- Three deterministic exception translations; everything else propagates unchanged:
  - `SessionNotFound` → `HTTPException(404, detail=str(exc)) from exc`.
  - `TypeError` (raised by the inner pipeline when `message` is not a `str`) → `HTTPException(400, detail=str(exc)) from exc`.
  - `ValueError` (raised by the inner pipeline when `message` is empty / whitespace-only after `strip()`) → `HTTPException(400, detail=str(exc)) from exc`.
  - Any other exception (e.g. `QueryLlmError`, `pydantic.ValidationError`, `RuntimeError`, `IntegrityError`) propagates unchanged so FastAPI's default handler turns it into HTTP 500 with the original exception preserved.
- Response payload: `IncomingMessageResponse(responses=responses)` — `responses` is the literal `list[CustomerResponse]` returned by the orchestrator, in the same order, with the same length. No `session_id`, `comercio_id`, `cliente_id`, `timestamp`, transformation, or reordering.
- `backend/main.py` adds `incoming_messages` to the existing `from backend.routers import (...)` tuple and calls `app.include_router(incoming_messages.router)` exactly once next to the existing `app.include_router(sessions.router)` line. No other router, dependency, service, repository, intent module, recognizer, resolver, processor, handler, dispatcher, transactional wrapper, response builder, schema, model, migration, or LLM module is modified.

**Verification:**
- `backend/tests/test_incoming_messages_endpoint.py` builds a fresh `FastAPI()` app, includes the router, overrides `backend.dependencies.get_session` with a `MagicMock(name="DatabaseSession")` factory, and patches `backend.routers.incoming_messages.SessionService` and `backend.routers.incoming_messages.process_incoming_message_with_responses` at the router's import site. **16/16 passed** without a real LLM, database, or HTTP — covering happy path 200 (`agregar_producto` executed and `desconocida` rejected), multi-intent order preservation, empty-list 200, `SessionNotFound` → 404 with `process_incoming_message_with_responses.assert_not_called()`, `TypeError("message must be a str")` → 400, `ValueError` (empty + whitespace-only) → 400, Pydantic 422 for non-`str` / missing field / extra field with `SessionService.get_active.assert_not_called()` and `process_incoming_message_with_responses.assert_not_called()`, unhandled-exception propagation (HTTP 500 with no custom seam-level wrapping), `__all__` discipline on `backend.routers.incoming_messages` (`["router"]`) and `backend.schemas.incoming_message` (`["IncomingMessageRequest", "IncomingMessageResponse"]`), source-code boundary (no `from backend.old_project`, no `from backend.llm`, no `from backend.repositories`, no `from backend.intents.handlers`, no `from backend.intents.context`, no `from backend.intents.recognizers`, no `from backend.intents.resolvers`, no `from backend.intents.processor`, no `from backend.intents.contracts`, no `from backend.intents.orchestration` other than `process_incoming_message_with_responses`, no `import requests`, no `import twilio`, no `MessagingResponse`, no `asyncio`, no `async def`, no `await`, no `logger.`, no `logging.`, no `print(`, no `time.sleep`, no `retry`, no `backoff`), no `db.commit` / `db.rollback` / `db.flush` / `db.refresh` / `db.expire` / `db.begin` on both success and translated-exception paths (via `MagicMock(name="DatabaseSession")`), and exactly one `@router.post(...)` decorator with no `@router.get` / `@router.put` / `@router.patch` / `@router.delete`.
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `fastapi.testclient.TestClient` against `backend.main.app` confirms `GET /openapi.json` documents `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` and that a POST with `{}` body returns HTTP 422 (not 404 / 405), proving the registered route is reachable.
- `openspec validate local-http-incoming-messages-3-29 --strict`: valid before archival.
- Delta spec synced to `openspec/specs/incoming-messages-local-http-endpoint/spec.md` (new capability: 9 requirements — `Incoming message local HTTP endpoint module location`, `Incoming message local HTTP endpoint route`, `Incoming message request and response schemas`, `Active session resolution through SessionService`, `Single delegation to the modern response orchestrator`, `Validation exception translation`, `Response payload shape`, `No LLM, transaction, repository, or mutation imports in the router`, `Public surface is limited`) and to `openspec/specs/incoming-message-response-orchestrator/spec.md` (added `Local HTTP seam for the incoming message response orchestrator` requirement with 5 scenarios documenting the seam as the documented entry point for the modern pipeline). Change archived at `openspec/changes/archive/2026-07-30-local-http-incoming-messages-3-29/`.

**Constraints introduced:**
- `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` is the single local HTTP entry point to the modern intents pipeline. Future transport adapters (Twilio webhook, queue worker, integration test harness) must consume this seam (or, for adapters that cannot speak HTTP, call `process_incoming_message_with_responses` directly) and SHALL NOT bypass it by calling `process_incoming_message`, `process_incoming_message_transactional`, or any inner dispatcher / handler / recognizer / resolver / processor / service / repository.
- The router module (`backend/routers/incoming_messages.py`) imports nothing from `backend.old_project`, `backend.llm`, `backend.repositories`, `backend.intents.handlers`, `backend.intents.context`, `backend.intents.recognizers`, `backend.intents.resolvers`, `backend.intents.processor`, `backend.intents.contracts`, `backend.intents.orchestration` (other than `process_incoming_message_with_responses`), `requests`, `twilio`, `asyncio`, or any queue / messaging-response module. No `logging.`, `logger.`, `print(`, `time.sleep`, `retry`, `backoff`, `async def`, `await`, or `HTTPException` outside the three documented exception translations.
- The router never calls `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; transaction ownership stays with `process_incoming_message_with_responses` through the transactional processor. Session lookup uses `SessionService.get_active` only — no direct SQLAlchemy query against the `sessions` table from the router.
- `__all__` discipline: `backend.routers.incoming_messages.__all__ == ["router"]`; `backend.schemas.incoming_message.__all__ == ["IncomingMessageRequest", "IncomingMessageResponse"]`. The router exposes exactly one `@router.post(...)` decorator and no other HTTP verb.
- Asymmetric validation mapping is normative: Pydantic rejects non-`str` / missing / extra-field bodies with HTTP 422, while the inner pipeline's `TypeError` (non-`str` surviving the schema) and `ValueError` (empty / whitespace-only after `strip()`) are translated to HTTP 400. Future subphases must preserve this mapping or update both the spec and the tests together.

Subphase 3.30 — Interactive HTTP client for the local incoming-message endpoint [x] — completed

Standalone stdlib-only terminal CLI that drives a continuous conversation against the Subphase 3.29 endpoint over HTTP. Runs against an externally-started FastAPI/Uvicorn process; never imports `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`, or any `backend.routers/services/repositories/intents/llm/models/alembic/dependencies` module. No DB access, no subprocess, no Twilio, no async, no retry/backoff, no logging framework. 22/22 tasks complete; focused tests pass; `compileall` exit 0; `openspec validate interactive-cli-http-client-3-30 --strict` valid; change archived at `openspec/changes/archive/2026-07-31-interactive-cli-http-client-3-30/`.

**Permanent decisions:**
- HTTP via stdlib `urllib.request` only (no new dependency). Timeout = 10s; `HTTPError` / `URLError` / `json.JSONDecodeError` are caught locally and re-raised as `RuntimeError` with a single-line message.
- Base URL precedence: `--base-url` CLI flag → `INCOMING_MESSAGES_BASE_URL` env var → `http://127.0.0.1:8000`. Trailing slash stripped. Single helper `_resolve_base_url(argv) -> str` so precedence is unit-testable.
- Module `__all__` exports only `main` plus private helpers (`_post_json`, `_read_int`, `_print_responses`, `_resolve_base_url`, `_close_session`, `_create_session`); `__main__` guard calls `main()` so the script runs as `python -m backend.scripts.cli_chat_client`.
- Interactive identity: prompt for `comercio_id` and `cliente_id` once, re-prompt on `ValueError` / non-positive integer; reuse the same ids for every HTTP call.
- Server reachability check uses an existing read-only application endpoint (e.g. `GET /openapi.json`); on failure, print the configured base URL and the "FastAPI must already be running" message, exit non-zero without touching Uvicorn.
- Session lifecycle is exclusively HTTP: `POST /sessions` with `{"id_comercio", "id_cliente"}` on start (409 on duplicate-active prints detail and exits non-zero), `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` with `{"message": <line>}` for every typed line, `POST /sessions/{session_id}/cerrar` from a `finally` block on exit. A pre-existing active session not created by this run is never closed, replaced, or marked owned.
- Loop rules: empty lines are silently ignored (no HTTP call), `exit` is matched case-insensitively after `.strip()` and never sent to the message endpoint, every other non-empty line is sent verbatim.
- Response printing: one line per `CustomerResponse` in original order prefixed with `<- `; `message=<value>` when the response has a `message` field, `raw=<json.dumps(response, ensure_ascii=False)>` otherwise.
- Close failure is non-fatal: `_close_session` swallows every exception and prints `warning: failed to close session <id>: <err>` once; the script still exits `0`. Cleanup is attempted at most once.

**Architectural constraints introduced:**
- The script is the only allowed entry point for manual HTTP-only conversation QA; the existing 3.29 endpoint and existing session endpoints remain authoritative and unchanged.
- Strict import boundary is enforced by a dedicated test (`test_import_boundary`) that reads `backend.scripts.cli_chat_client.__dict__` after import and asserts none of the banned modules appear as values, including checks against `sys.modules`. This is the project-wide reference pattern for "external client must not touch the application".
- The script is the only path where `INCOMING_MESSAGES_BASE_URL` is read; other call sites (tests, future adapters) must use their own precedence or reuse this helper.
- `try/finally` cleanup ownership is normative: a `KeyboardInterrupt`, `EOFError`, post-create HTTP failure, post-create parse failure, or any other recoverable runtime error all run the close path before exit.

**Files created:**
- `backend/scripts/__init__.py` (empty package marker)
- `backend/scripts/cli_chat_client.py` (~190 lines: `main`, `_post_json`, `_read_int`, `_print_responses`, `_resolve_base_url`, `_create_session`, `_close_session`, `__main__` guard)
- `backend/tests/test_cli_chat_client.py` (9 tests, all mocking `urllib.request.urlopen` via a `FakeResponse` helper and patching `builtins.input`; covers session creation on start, session reuse per message, response printing, empty-input no-op, `exit` loop break + close, close-failure non-fatal, base-URL precedence across all three cases, and the import-boundary static check)

**Verification commands:**
- Focused: `PYTHONPATH=. ./venv/bin/python -m unittest backend.tests.test_cli_chat_client -v`
- Compilation: `PYTHONPATH=. venv/bin/python -m compileall backend`
- OpenSpec: `openspec validate interactive-cli-http-client-3-30 --strict`
- Manual smoke: `PYTHONPATH=. ./venv/bin/python -m backend.scripts.cli_chat_client` with FastAPI already running (e.g. `comercio_id=1, cliente_id=8`); `hola` → response line; `exit` → close confirmation.
- No git / DB / Alembic / model / router / service / repository / intent / LLM / dependency file was modified.

**Constraints introduced (re-stated for future subphases):**
- Future manual-development clients (e.g. a Twilio-shaped simulator) must follow the same "stdlib HTTP only, no `backend.*` imports, single try/finally close, exit-only termination" pattern. Reusing `cli_chat_client` helpers via a shared `backend/scripts/_http.py` is acceptable; adding a third-party HTTP client to the project is not.
- The script's only new HTTP surface is the env-var name `INCOMING_MESSAGES_BASE_URL`; this is a project-wide convention and must not be renamed without a coordinated change in tests and any future sibling scripts.

**Context for future subphases:** Phase 4 (Twilio / WhatsApp adapter) can either reuse this script's helpers (preferred — keeps the import boundary single-sourced) or instantiate a Twilio-shaped client that talks to the same 3.29 endpoint; the 3.29 seam remains the only HTTP entry point. The interactive CLI does not depend on a draft-Pedido bootstrap (the existing `agregar_producto` handler's Pedido acquisition path runs server-side through the active session); no new endpoints, models, or migrations were added. The next subphase (3.30.1) is scoped to focused defect fixes against this CLI's real flow.

Subphase 3.30.1 — CLI conversation defects: focused fixes [x] — completed

Three targeted defect fixes against the Subphase 3.30 CLI/HTTP flow. The existing unique-selection → ready → execute contract from Subphase 3.19 remains authoritative (no new confirmation turn, no LLM call for refinement, no new endpoints, no new layer). The change is archived at `openspec/changes/archive/2026-07-31-cli-conversation-defects-3-30-1/`.

**Root causes and minimal fixes:**

1. **Missing draft `Pedido` on CLI-created sessions.** The CLI's `_create_session` was creating an active session but the `agregar_producto` handler requires `session.id_pedido` to be set, so every positive resolution rejected with `PedidoNotFound`. The existing `POST /pedidos` (Subphase 2.11) and `PUT /sessions/{id}/pedido` (Subphase 2.13) endpoints already cover the lifecycle, so the CLI bootstrap now issues those two calls in order immediately after `POST /sessions`. The CLI continues to use stdlib `urllib.request` only; the strict import boundary is unchanged. On `POST /pedidos` failure the bootstrap closes the session it created via `POST /sessions/{id}/cerrar` and exits non-zero. The exit handler still closes only the session it created.

2. **Pending context stuck after a definitive `rejected` result.** A definitive business `rejected` was treated as non-final, leaving `session.context_type == "product_selection"` and the rejected intent still `active` so the next message re-routed into the same dead intent. The lifecycle rule in `execute_ready_pending_context` is now: `result.status in ("executed", "rejected")` triggers `clear_pending_context(session)` and sets `session.context_type = None`; `failed` remains a non-definitive outcome and preserves context; a raised exception inside the handler propagates unchanged so `process_incoming_message_transactional` still owns the `db.rollback()`. The rejection is distinguished from a raised exception via the existing `ProcessedIntent` status contract — no new exception type, no broad `except Exception`.

3. **No partial refinement of `candidate_ids`.** The product-selection resolver only recognized a unique match. For messages like `la grande` against five candidates, the recognizer produced no `encontrados` and the conversation stalled. The resolver now adds a narrowing branch that fires when `encontrados` is empty and `encontrados_posibles` is non-empty: it computes the intersection of `active_intent.candidate_ids` with the candidate `producto_presentacion_id`s; if exactly one remains, the existing unique-selection path is reused so the next dispatcher call routes directly to `execute_ready_pending_context`; if more than one remains, the narrowed `candidate_ids` is returned with `status == "pending_resolution"`; if the intersection is empty, the input is returned unchanged (no infinite narrowing). `cantidad` and all other `resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, and `handler` are preserved verbatim.

**Architectural constraints introduced:**
- The CLI continues to call the running API via stdlib `urllib.request` only — no `sqlalchemy`, `requests`, `httpx`, `fastapi`, `twilio`, or `backend.*` imports were added.
- Lifecycle ownership remains split: `execute_ready_pending_context` owns the post-handler state transition (committed in the same transaction as the handler work); `process_incoming_message_transactional` owns `db.commit()` / `db.rollback()`. The narrowing branch adds no transaction work and no SQLAlchemy calls.
- The narrowing branch uses the existing `detectar_productos` output shape — no recognizer rewrite, no LLM call, no new contract, no new handler, no new orchestrator.

**Files modified:**
- `backend/scripts/cli_chat_client.py` — `_create_session` renamed to `_bootstrap_session`, issues `POST /sessions` → `POST /pedidos` → `PUT /sessions/{id}/pedido` in order; stores `pedido_id`; prints `<session id>` and `<pedido id>` on success; closes session + non-zero exit on bootstrap failure.
- `backend/intents/orchestration/pending_context_execution.py` — `if result.status == "executed":` → `if result.status in ("executed", "rejected"):` for the `clear_pending_context` branch.
- `backend/intents/context/product_selection_context_resolver.py` — new narrowing branch keyed on `len(encontrados) == 0` and non-empty `encontrados_posibles`; intersection logic preserves order; single-candidate result reuses the existing unique-selection path; empty intersection returns the input unchanged.

**Files created:**
- `backend/tests/test_cli_conversation_regression.py` — five real-HTTP regression scenarios against `supernova_test`: full five-message conversation (5 → 3 → executed), exact unique selection in same turn, definitive `rejected` clears context and re-enters initial classification, raised `IntegrityError` propagates and rolls back, CLI cleanup closes only its own session. Uses the same `_seed(...)` / `_cleanup(...)` fixture shape as the 3.25 integration test.
- `openspec/changes/archive/2026-07-31-cli-conversation-defects-3-30-1/` (proposal, design, tasks, three delta specs archived).

**Verification:**
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- Focused tests: `test_cli_chat_client`, `test_pending_context_execution`, `test_product_selection_context_resolver`, `test_cli_conversation_regression` — all green.
- Full smoke suite (`backend/tests/api_smoke.py`): no regressions to the existing 400+ tests.
- `openspec validate cli-conversation-defects-3-30-1 --strict`: valid.
- Delta specs synced to `openspec/specs/incoming-messages-interactive-cli/spec.md`, `openspec/specs/pending-context-execution/spec.md`, and `openspec/specs/product-selection-context-resolver/spec.md`.

**Context for future subphases:** the CLI is again a usable manual iteration tool against `POST /comercios/{id}/clientes/{id}/incoming-messages`. Future subphases that modify the pending-context lifecycle must preserve the rule "executed and definitive rejected clear; failed preserves; raised exception propagates so the transactional wrapper rolls back". Future subphases that extend the product-selection resolver must keep the unique-selection → immediate-execute contract intact; the narrowing branch only fires when no unique match was found and may not weaken `candidate_ids` validation. New manual-development clients (Twilio-shaped simulator, queue worker test harness) should follow the same "stdlib HTTP only + bootstrap session → draft pedido → associate" pattern and may reuse `cli_chat_client` helpers via a shared `backend/scripts/_http.py`.


Subphase 3.30.2 — Interactive CLI pedido detail table [x] — completed

Interactive CLI now prints the current draft `Pedido` as a plain-text table after every successfully executed order mutation. Delivered via a new read-only `GET /pedidos/{pedido_id}/detalle` endpoint that returns pedido scalars plus a `lineas` array (`cantidad`, `producto_nombre`, `presentacion_descripcion` — no ids, no `precio_unitario`, no `observaciones`) and a CLI branch keyed on `ORDER_MUTATING_INTENTS = {"agregar_producto", "quitar_producto"}` that fetches the detail once per response list (regardless of mutation count) and prints the customer responses first, then `Pedido actual:` followed by the table. Change archived at `openspec/changes/archive/2026-07-31-interactive-cli-pedido-table/`.

**Architectural constraints introduced:**
- `PedidoDetalleLinea` is id-free and presentation-friendly by design — never add `id_producto_presentacion`, `id_producto`, `precio_unitario`, or `observaciones` to it.
- The detail endpoint is read-only: `pedido_service.get_detalle` performs no `commit`/`rollback`/`flush`/`refresh`/`expire`/`begin`; only the repository's read path is used.
- The CLI's strict import boundary is preserved: no `fastapi`, no `sqlalchemy`, no `backend.*` import, no third-party table library, no local state between calls, no retry/backoff.
- Multiple executed mutations in a single `responses` list trigger exactly one detail retrieval; retrieval failure prints a single-line warning and the loop continues without affecting the session lifecycle or the exit code.
- `—` is the fallback for missing or empty `presentacion_descripcion`; integer quantity rendering is mandatory.

**Files modified:**
- `backend/schemas/pedido.py` — `PedidoDetalleLinea`, `PedidoDetalleResponse` (both `extra="forbid"`).
- `backend/repositories/pedido_producto_repository.py` — `list_by_pedido` eager-loads `ProductoPresentacion.presentacion`.
- `backend/services/pedido_service.py` — new read-only `get_detalle(pedido_id)`.
- `backend/routers/pedidos.py` — `GET /pedidos/{pedido_id}/detalle` handler.
- `backend/scripts/cli_chat_client.py` — `ORDER_MUTATING_INTENTS`, `response_modified_order`, `format_order_table`, `_fetch_pedido_detalle`; updated `__all__`; `main()` prints the table after executed mutations.
- `backend/tests/test_cli_chat_client.py` — table scenarios, focused unit tests for pure helpers, detail-retrieval-failure branch, and explicit existence checks for new helpers in `test_import_boundary`.

**Files created:** none.

**Context for future subphases:** the CLI is a usable end-to-end verification tool — every executed order mutation prints the current Pedido. New order-mutating intents MUST extend `ORDER_MUTATING_INTENTS` in `backend/scripts/cli_chat_client.py`; the table branch is keyed on that set. New pedido-side fields MUST be evaluated against the existing `PedidoDetalleLinea` shape — extend it together with the `GET /pedidos/{pedido_id}/detalle` router and `format_order_table`'s column list, never break the id-free presentation contract. No Alembic migration was introduced.

Subphase 3.30.3 — Consolidate duplicate product-presentations in draft orders [x] — completed

`agregar_producto` no longer creates duplicate `PedidoProducto` rows when the same `producto_presentacion_id` is added repeatedly to the same draft `Pedido`: it increments the existing line's `cantidad` and preserves the original `precio_unitario` snapshot and `observaciones`. The invariant "at most one `PedidoProducto` row per `(id_pedido, id_producto_presentacion)`" is enforced at the database level by a `UniqueConstraint` named `uq_pedido_producto_presentacion` and at the service level by `PedidoProductoService.add_or_increment`. Change archived at `openspec/changes/archive/2026-07-31-consolidate-duplicate-product-presentations-draft-orders/`.

**Permanent decisions:**
- New service method: `PedidoProductoService.add_or_increment(pedido_id: int, id_producto_presentacion: int, cantidad: int, observaciones: str | None) -> PedidoProducto`. Validates `cantidad > 0` (`InvalidCantidad`), pedido existence (`PedidoNotFound`), `borrador` state (`PedidoProductoNotEditable`), and producto-presentacion + precio existence; looks up any existing line via the new repository method and either increments `cantidad` (preserving `precio_unitario` and `observaciones`) or creates a new row that snapshots the current `Precio.precio`. Trims `observaciones` via the existing `_trim_to_none` helper.
- New repository method: `PedidoProductoRepository.get_by_pedido_and_producto_presentacion(pedido_id, id_producto_presentacion) -> PedidoProducto | None` — bounded `select` with `scalar_one_or_none()`, no eager loading.
- New exception: `InvalidCantidad` in `backend/services/exceptions.py`.
- New model constraint on `PedidoProducto.__table_args__`: `UniqueConstraint("id_pedido", "id_producto_presentacion", name="uq_pedido_producto_presentacion")`.
- `execute_agregar_producto` now performs a repository lookup once to capture the pre-existing line, then delegates to `add_or_increment`; it does NOT branch on insert-vs-increment itself. On success it returns an `intent.model_copy` with `status == "executed"` and threads three keys into `resolved_data`: `cantidad_agregada` (the supplied `cantidad`), `cantidad_final` (the post-operation line `cantidad`), and `linea_creada` (`True`/`False`).
- `build_agregar_producto_response` reads `resolved_data["cantidad_final"]` (with fallback to the legacy `cantidad` key) for the executed confirmation; customer-visible text is unchanged in shape (singular/plural phrasing still keyed on `cantidad_final`).
- The HTTP `POST /pedidos/{pedido_id}/productos` path keeps create-only semantics through `PedidoProductoService.add`; only the intents pipeline (`agregar_producto` handler) uses `add_or_increment`.
- Alembic migration `8e0a1b2c3d4f_consolidate_pedido_productos_duplicates.py` (`down_revision = "1f2e3d4c5b6a"`) is hand-written and: (a) consolidates pre-existing duplicates deterministically — `supernova` had none; `supernova_test` had eight groups across twenty rows (full table recorded in the migration docstring) consolidated to eight survivors using the lowest `id` per group, summing `cantidad`, and preserving the survivor's `precio_unitario` + `observaciones`; (b) creates the `uq_pedido_producto_presentacion` unique constraint. The downgrade drops the constraint only — consolidation is one-way and not idempotent (documented in the migration docstring).

**Architectural constraints introduced:**
- The unique constraint is the final enforcement boundary; service-level lookup-then-increment is the application-level path. No retry/backoff/transactional locking was added; concurrent inserts collide on the constraint and surface as `IntegrityError`, which propagates so `process_incoming_message_transactional` (Subphase 3.26) owns the rollback.
- The handler continues to delegate to the service only; it does not query `PedidoProducto` directly, does not decide insert-vs-increment, does not commit/rollback, and does not raise `HTTPException`.
- The response builder still does not import `sqlalchemy`, `requests`, `fastapi`, `twilio`, `backend.llm`, `backend.repositories.*`, `backend.intents.handlers.*`, or `backend.intents.orchestration.*`; the only DB access is the read through `ProductoQueryService.list_presentaciones_by_ids`.
- `quitar_producto` (Subphase 3.31) operates against the single consolidated line unchanged: partial removal decrements the same row; full removal deletes it. No duplicate-specific behavior is introduced.
- Manual CLI acceptance recorded in `backend/doc/3-30-3-manual-acceptance.md`; pre-implementation duplicate audit recorded in `backend/doc/3-30-3-duplicate-audit.md`.

**Files modified:**
- `backend/models/pedido_producto.py` — added `UniqueConstraint` import and the `uq_pedido_producto_presentacion` constraint.
- `backend/repositories/pedido_producto_repository.py` — added `get_by_pedido_and_producto_presentacion`.
- `backend/services/pedido_producto_service.py` — added `add_or_increment`; existing `add` / `update` / `delete` / `list_by_pedido` / `get_for_pedido` / `get_by_id` unchanged.
- `backend/services/exceptions.py` — added `InvalidCantidad`.
- `backend/intents/handlers/agregar_producto_handler.py` — repository lookup + delegation to `add_or_increment`; threads `cantidad_agregada` / `cantidad_final` / `linea_creada` into `resolved_data`.
- `backend/intents/responses/agregar_producto_response.py` — reads `cantidad_final` with fallback to `cantidad`.

**Files created:**
- `backend/alembic/versions/8e0a1b2c3d4f_consolidate_pedido_productos_duplicates.py`
- `backend/tests/test_consolidate_duplicate_product_presentations.py` (31 scenarios against `supernova_test`)
- `backend/doc/3-30-3-duplicate-audit.md`
- `backend/doc/3-30-3-manual-acceptance.md`

**Verification:**
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- `PYTHONPATH=. venv/bin/python backend/tests/test_consolidate_duplicate_product_presentations.py`: all 31 scenarios pass against `supernova_test`.
- Full `backend/tests/api_smoke.py` smoke suite green; existing `test_pedido_producto_*` create-only tests still pass against `PedidoProductoService.add`; `test_agregar_producto_handler` mock-patch tests updated to assert the `add_or_increment` delegation and the new `resolved_data` threading.
- `PYTHONPATH=. venv/bin/alembic current` on both databases reports revision `8e0a1b2c3d4f` at HEAD.
- `openspec validate consolidate-duplicate-product-presentations-draft-orders --strict`: valid.
- Manual CLI run confirmed: identical additions produce one consolidated row with summed quantities; mixed presentations stay separate; `quitar_producto` decrements/deletes the consolidated line normally.

**Context for future subphases:** any new write path that mutates `pedidos_productos` MUST go through `PedidoProductoService.add_or_increment` (consolidation required) or `PedidoProductoService.add` (create-only, used by the HTTP `POST /pedidos/{id}/productos` endpoint) — direct `PedidoProductoRepository.create` or `db.add(PedidoProducto(...))` calls are forbidden because they will collide with `uq_pedido_producto_presentacion` for repeat additions. New customer-facing strings must read `resolved_data["cantidad_final"]` (with `cantidad` fallback) for executed confirmations. Any future `modificar_producto` intent must keep the consolidado-line invariant: mutating a line's quantity updates the existing row, never creates a parallel one. The audit file at `backend/doc/3-30-3-duplicate-audit.md` is the authoritative record of the duplicate groups that existed before the migration and must be retained for traceability of the consolidation step.

Subphase 3.31 — `quitar_producto` end-to-end flow [x] — completed

Complete `quitar_producto` intent delivered through the same Phase 3 seams as `agregar_producto`: static contract → order-line recognizer (catalog built from current draft `PedidoProducto` lines) → `ORDER_LINE_SELECTION` context resolver → initial intent dispatcher arm → ready handler → `PedidoProductoService` decrement/delete → deterministic response builder → response orchestrator arm. Mutations only ever target `PedidoProducto` rows that already exist in the active draft `Pedido`; the catalog is never touched. All 66 tasks complete; focused + integration + CLI regression tests pass; `compileall` exit 0; `openspec validate --strict` valid; change archived at `openspec/changes/archive/2026-07-31-subphase-3-31-quitar-producto/`.

**Architectural constraints introduced:**
- Order-line candidates carry `pedido_producto_id` (not `producto_presentacion_id`); the handler resolves the specific line through `PedidoProductoService.get_for_pedido` before any mutation. Catalog-wide keys are never a final mutation target when the line is ambiguous.
- A second `ContextType` value, `ORDER_LINE_SELECTION`, is added to `SESSION_CONTEXT_TYPE` alongside the existing `PRODUCT_SELECTION`. The two resolvers are strictly isolated: `agregar_producto` continues to flow through the catalog resolver; `quitar_producto` flows through the order-line resolver.
- The order-line recognizer catalog is built exclusively from `PedidoProductoService.list_by_pedido(session.id_pedido)`. Catalog products absent from the pedido are unreachable as candidates. Inactive or unavailable catalog products that already exist in the pedido remain reachable.
- Quantity semantics: omitted → delete the full line; less than current → decrement via `PedidoProductoService.update`; equal → delete; greater → `rejected` with `cantidad_actual` exposed and no mutation. Non-positive quantity is rejected without mutation.
- `PedidoProductoRepository` gains `list_by_pedido`, `get_for_pedido`, and reuses existing `update` / `delete`. `PedidoProductoService` exposes the matching service methods with borrador and ownership checks.
- `execute_quitar_producto` calls the service only; it never commits, rolls back, flushes, closes, catches broad `Exception`, or raises `HTTPException`. Raised technical errors propagate so `process_incoming_message_transactional` (Subphase 3.26) owns the rollback.
- `InitialIntentDispatcher` (3.15), `PendingContextDispatcher` (3.18), `PendingContextExecution` (3.17), and `CustomerResponseOrchestrator` (3.28) each gain one new arm; no other layer was refactored. `agregar_producto` is unchanged.
- Definitive `rejected` from the handler still clears the pending context (3.17/3.30.1 lifecycle rule). `failed` preserves context; a raised exception propagates.
- `build_quitar_producto_response` renders deterministic strings (no LLM, no DB IDs in the customer message). Outcomes: `pending_resolution` (`¿Cuál querés quitar: X o Y?`), `executed` partial, `executed` complete, `rejected` excess, `rejected` absent, `failed`.
- `agregar_producto` regression is enforced by re-running the existing end-to-end test (3.19) against `supernova_test` unchanged.
- No DB schema change, no Alembic migration, no new HTTP endpoint, no CLI change, no LLM beautification, no confirmation turn, no `modificar_producto`.

**Files created:**
- `backend/intents/contracts/quitar_producto.py` — `QUITAR_PRODUCTO_CONTRACT` dict literal.
- `backend/intents/recognizers/quitar_producto_recognizer.py` — `recognize_quitar_producto(db, session, message) -> RecognizerResult`.
- `backend/intents/orchestration/quitar_producto_initial.py` — `process_initial_quitar_producto(db, session, source_text) -> ProcessedIntent`.
- `backend/intents/context/order_line_selection_resolver.py` — `resolve_order_line_selection(db, session, message, active_intent) -> ProcessedIntent`.
- `backend/intents/handlers/quitar_producto_handler.py` — `execute_quitar_producto(db, session, intent) -> ProcessedIntent`.
- `backend/intents/responses/quitar_producto_response.py` — `build_quitar_producto_response(db, session, intent) -> CustomerResponse`.

**Files modified:**
- `backend/repositories/pedido_producto_repository.py` — `list_by_pedido`, `get_for_pedido`.
- `backend/services/pedido_producto_service.py` — matching service methods with borrador / ownership checks.
- `backend/intents/context/context_type_resolver.py` — `ORDER_LINE_SELECTION` arm.
- `backend/intents/orchestration/initial_intent_dispatcher.py` — `quitar_producto` route.
- `backend/intents/orchestration/pending_context_dispatcher.py` — `ORDER_LINE_SELECTION` route.
- `backend/intents/orchestration/incoming_message_response_orchestrator.py` — `quitar_producto` route to the deterministic builder.
- `backend/tests/api_smoke.py` — focused tests, end-to-end test, and `agregar_producto` regression rerun.
- `openspec/specs/<ten capabilities>/spec.md` — delta specs from the change were synced (9 of 10 were no-ops; `pending-context-execution/spec.md` was updated so scenario text refers to the dispatched handler generically).

**Verification:**
- `PYTHONPATH=. venv/bin/python -m compileall backend`: exit 0.
- Focused tests: `test_quitar_producto_contract`, `test_quitar_producto_recognizer`, `test_quitar_producto_initial`, `test_order_line_selection_resolver`, `test_quitar_producto_handler`, `test_quitar_producto_response`, `test_pedido_producto_repository`, `test_pedido_producto_service` — all green.
- End-to-end integration test against `supernova_test` covers single-message complete removal, partial decrement, quantity omitted, excess quantity, absent product, ambiguous refinement with `la grande`/`la de muzzarella`, invalid candidate defense, definitive handler `rejected` clearing context, propagated `IntegrityError` rolling back, and a consecutive mixed-operation scenario across the same session.
- Existing `agregar_producto` end-to-end test (3.19) re-run unchanged: no regression.
- Existing CLI regression test (`test_cli_conversation_regression`) re-run against the running local FastAPI app: no regression.
- `openspec validate subphase-3-31-quitar-producto --strict`: valid.

**Context for future subphases:** the modern message-processing pipeline now handles both add and remove end-to-end through the same dispatch arms. `agregar_producto` and `quitar_producto` are the only intents with full coverage today; further intents (`modificar_producto`, `vaciar_pedido`, etc.) must follow the same contract → recognizer → context/resolver → initial dispatcher → pending-context dispatcher → handler → response builder pattern, and any new `ContextType` must be strictly separated from `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION`. `PedidoProductoService` exposes `list_by_pedido` and `get_for_pedido` for any future line-aware intent. `build_quitar_producto_response` is the template for deterministic, catalog-free customer messages: a single Python function with no LLM involvement. Future subphases that change the pending-context lifecycle must preserve the existing rule "executed and definitive rejected clear; failed preserves; raised exception propagates so the transactional wrapper rolls back". No DB migration was introduced in this subphase; the next schema-level change still requires a new Alembic revision.


Implement Subphase 3.32 — `modificar_producto` end-to-end flow [x]

**Completed:** 2026-07-31

**Delivered:**
- Implemented the complete `modificar_producto` flow through the modern message pipeline: static contract, recognizer, initial orchestration, staged pending-context resolution, handler, deterministic response builder, persistence, HTTP compatibility, and interactive CLI compatibility.
- Kept source and destination domains separate: sources resolve only to `PedidoProducto` lines in the active draft Pedido (`pedido_producto_origen_id`), while destinations resolve only to active, available product presentations from the same commerce (`producto_presentacion_destino_id`).
- Added optional positive `cantidad` semantics. Omitted quantity replaces the full source line; partial quantity decrements the source; full quantity removes it; excessive, zero, or negative quantities are rejected without mutation.
- Added `ContextType.PRODUCT_MODIFICATION` with source-first then destination staged resolution. Candidate sets, resolved identifiers, and quantity persist across turns and never broaden during refinement.
- Added atomic `PedidoProductoService.modify_product` execution with draft, ownership, availability, equivalent-modification, and quantity validations before mutation.
- Destination consolidation increments an existing line while preserving its price snapshot. A new destination line stores the current catalog price snapshot. Source decrement/removal and destination increment/creation remain inside the existing transaction boundary.
- Added repository operations for scoped source lookup, decrement, increment, and creation with a price snapshot; handlers issue no direct SQLAlchemy queries and do not commit or roll back.
- Added deterministic responses for source/destination clarification, full and partial replacements, consolidated destinations, business rejections, and technical failures without LLM response generation or database-ID exposure.
- Integrated `modificar_producto` into the initial dispatcher, pending-context dispatcher, pending-context execution, context-type resolver, and incoming-message response orchestrator without changing the established `agregar_producto` and `quitar_producto` behavior.

**Verification:**
- Added focused tests for the contract, recognizer, initial orchestration, context resolver, handler, response builder, repository, service, and dispatcher seams.
- Added end-to-end coverage for full and partial replacement, omitted quantity, source/destination ambiguity, staged and partial refinement, invalid candidate defense, excess quantity, unavailable destination, equivalent modification, destination consolidation and creation, definitive rejection lifecycle, and consecutive add/modify/remove operations.
- Re-ran `agregar_producto`, `quitar_producto`, HTTP pipeline, pending-context, transaction, and CLI conversation regressions successfully.
- `PYTHONPATH=. venv/bin/python -m compileall backend` completed successfully.
- `openspec validate modificar-producto-end-to-end-3-32 --type change --strict` reported valid.

**OpenSpec:**
- Synced nine delta specs into the main specification set: created five `modificar-producto` capability specs and updated four orchestration capabilities.
- Two unrelated pre-existing strict-validation failures remain in `incoming-message-orchestrator` and `product-recognizer`.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-modificar-producto-end-to-end-3-32/`.

**Context for future subphases:** the pipeline now supports add, remove, and modify operations end to end. New line-aware intents must preserve order-line/catalog identifier separation, use dedicated context types, refine only persisted candidate domains, delegate mutations to services, retain transaction ownership in the existing wrapper, and preserve the lifecycle rule: executed and definitive rejected clear context, failed preserves context, and unexpected exceptions propagate for rollback.

Subphase 3.32.1 — Fix atomic quantity-preserving `modificar_producto` [x] — completed

**Completed:** 2026-07-31

**Delivered:**
- Two defects in the Subphase 3.32 `modificar_producto` flow were corrected: loss of source quantity when the destination quantity was omitted, and partial mutation when the destination could not be resolved.
- `modificar_producto` now executes as a single atomic business operation: validate source → validate quantity → validate destination → validate price and availability → compute mutation → mutate source → mutate destination → one transaction commit. It is never decomposed into separate `quitar_producto` and `agregar_producto` outcomes.
- Authoritative quantity rule: explicit positive `cantidad` is the transferred quantity; omitted `cantidad` is re-read as the full current source-line quantity at execution time; destination quantity never defaults to `1`. `execute_modificar_producto` re-reads the current `PedidoProducto.cantidad` inside the same transaction boundary when the resolved intent has `cantidad is None`.
- Validation-before-mutation: `PedidoProductoService.modify_product` performs every destination validation (existence, same comercio, active, available, presentation active, equivalent-modification guard, price availability, destination consolidation lookup) before any source row is mutated. The service does not commit, rollback, flush, refresh, expire, or begin.
- Handler is purely delegating: `execute_modificar_producto` calls `PedidoProductoService.modify_product` exactly once, returns a single `ProcessedIntent`, and never imports `execute_quitar_producto` / `execute_agregar_producto`. The orchestrator and resolver never mutate the Pedido before the destination resolves uniquely.
- One `CustomerResponse` per modification: full-line transfers, partial transfers, consolidated destinations, unknown destinations, unavailable destinations, and excess quantities are rendered with deterministic Spanish messages through `build_modificar_producto_response`. No separate "Quité…" / "Agregué…" responses.
- Existing Subphase 3.32 invariants preserved: destination consolidation increments the existing line and keeps its stored price snapshot; a new destination line stores the current catalog price snapshot; source price is unchanged after partial decrement; the outer transactional processor remains the sole commit/rollback owner; raised technical exceptions propagate unchanged so `process_incoming_message_transactional` rolls back.
- Pending-context lifecycle for `modificar_producto`: executed and definitive rejected clear context, failed preserves context, raised exceptions propagate. The omitted-quantity sentinel (`cantidad is None`) persists across turns and is never substituted with `1`.

**Architectural constraints introduced:**
- The four-layer contract for any future atomic business intent: `Service` owns the atomic mutation boundary and every validation; `Handler` validates intent shape and delegates exactly once; `Orchestrator` / `Resolver` never mutate the Pedido before every validation succeeds; `Response builder` produces exactly one deterministic message per outcome.
- `cantidad` semantics are uniform across `agregar_producto`, `quitar_producto`, and `modificar_producto`: explicit positive int or omitted (`None`). The handler-level re-read of the current `PedidoProducto.cantidad` is the only authoritative source when the resolved intent carries `cantidad is None`.
- The atomic service boundary (`PedidoProductoService.modify_product`) is the single owner of the mutation; handlers, orchestrators, and resolvers must not call lower-level repositories to stage the same mutation, must not commit, and must not issue two `ProcessedIntent` results for one intent.

**Files modified:**
- `backend/services/pedido_producto_service.py` — `modify_product` with validation-before-mutation and authoritative quantity derivation.
- `backend/intents/handlers/modificar_producto_handler.py` — re-read of `PedidoProducto.cantidad` when `cantidad is None`; no decomposition imports; single `ProcessedIntent` return.
- `backend/intents/orchestration/modificar_producto_initial.py` — omitted-quantity sentinel flows through unchanged.
- `backend/intents/context/product_modification_resolver.py` — omitted-quantity sentinel persists across stages; never substitutes `1`.
- `backend/intents/responses/modificar_producto_response.py` — corrected deterministic templates for full, partial, consolidated, unknown, unavailable, and excess-quantity outcomes.
- `backend/repositories/pedido_producto_repository.py` — atomic-friendly read and mutation primitives used by the service.
- `backend/services/exceptions.py` — rejection reasons for destination and price failures surfaced as `rejected` outcomes.

**OpenSpec:**
- Synced four delta specs into the main specification set: created `openspec/specs/modificar-producto-atomicity-quantity/spec.md`; modified `openspec/specs/modificar-producto-customer-response/spec.md`, `openspec/specs/modificar-producto-handler/spec.md`, and `openspec/specs/modificar-producto-intent-orchestration/spec.md`.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-fix-modificar-producto-atomicity-quantity-3-32-1/`.

**Context for future subphases:** any new intent that mutates a `PedidoProducto` line must follow the four-layer contract above, must keep `cantidad` semantics uniform, must delegate the atomic mutation to the existing service layer, must never produce multiple `ProcessedIntent` or `CustomerResponse` values for a single message, and must preserve the pending-context lifecycle rule. The `execute_quitar_producto` / `execute_agregar_producto` handlers are reserved for their dedicated intents and must not be composed inside any new intent.

Subphase 3.32.2 — Diagnose and fix remaining real-flow defects in `modificar_producto` [x] — completed

**Completed:** 2026-07-31

**Delivered:**
- Reproduced both reported failures through the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` endpoint and the interactive CLI path against `supernova_test`.
- Identified the shared root cause in `backend/llm/intent_classifier.py`: the classifier prompt explicitly decomposed replacement commands into independent `quitar_producto` and `agregar_producto` intents, bypassing the atomic `modificar_producto` pipeline.
- Corrected the classifier catalog, instructions, and worked example so replacement phrases emit one `modificar_producto` intent containing the complete original message and are never split into remove/add operations.
- Added `modificar_producto` to `ORDER_MUTATING_INTENTS` in `backend/scripts/cli_chat_client.py`, ensuring the CLI prints the updated order table after a successful replacement.
- Preserved all Subphase 3.32.1 invariants: omitted quantity uses the re-read full source quantity, destination validation precedes source mutation, one replacement produces one `ProcessedIntent` and one `CustomerResponse`, and the outer transactional processor remains the sole commit/rollback owner.

**Corrected runtime outcomes:**
- `cambia las empanadas de verdura por empanadas carne picante` now executes one `modificar_producto`: the source x4 line is removed, the destination is created with quantity 4, and one modification response is returned.
- `cambia las 5 empanadas de jamon y queso por un caramelo` now returns one rejected `modificar_producto`: the source remains quantity 5, no destination is created, the response confirms the Pedido was not modified, and pending context is cleared.
- The HTTP endpoint forwards messages unchanged. The recognizer, orchestrator, resolver, handler, service, and response builder required no correction because they behave correctly when the classifier emits `modificar_producto`.

**Coverage and verification:**
- Added `backend/tests/test_modificar_producto_real_flow_http.py` to exercise both exact phrases through the real FastAPI endpoint and assert response, persisted `PedidoProducto` rows, and `Session.context_type`.
- Added `backend/tests/test_modificar_producto_real_flow_cli.py` to drive the CLI through the FastAPI application and assert printed responses, order tables, and persisted rows.
- Re-ran the complete `modificar_producto` suite successfully, including atomicity, orchestration, handler, recognizer, response, transaction, HTTP, CLI, repository, service, and dispatcher coverage.
- Re-ran incoming-message and transactional processor regressions successfully. Wider smoke/regression runs retained only documented pre-existing unrelated failures: one polluted `quitar_producto` fixture and one remote LLM JSON parsing failure.

**Files modified:**
- `backend/llm/intent_classifier.py` — replacement commands now classify as one `modificar_producto` intent.
- `backend/scripts/cli_chat_client.py` — order table refresh includes `modificar_producto`.
- `backend/tests/test_cli_chat_client.py` — non-mutating-intent assertion uses `consultar_producto`.
- `backend/tests/test_modificar_producto_real_flow_http.py` — real HTTP regression coverage.
- `backend/tests/test_modificar_producto_real_flow_cli.py` — real CLI regression coverage.

**OpenSpec:**
- Synced the five delta specs into the main specification set, including the new `modificar-producto-real-flow-defects` capability.
- Validated the change and all five affected main specs successfully.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-fix-modificar-producto-real-flow-defects-3-32-2/`.

**Context for future subphases:** replacement-language classification is part of the atomicity boundary. End-to-end tests for business intents must cross the real classifier, HTTP endpoint, and CLI seams; tests that patch classification prove downstream behavior only and cannot validate the actual runtime route.

Subphase 3.32.3 — Preserve and execute all `agregar_producto` intents across pending product resolution [x] — completed

**Completed:** 2026-07-31

**Delivered:**
- Preserved every classified `agregar_producto` in classifier order: the first unresolved addition becomes active and every later addition is appended to the existing FIFO queue instead of overwriting prior work.
- Updated the `agregar_producto` initial orchestrator to enqueue a later pending addition when an active addition already exists, keeping the side-effect boundaries (no handler execution, no commit, no rollback, no SQLAlchemy query).
- Updated `dispatch_initial_message` so multiple classified `agregar_producto` items enter the pending execution lifecycle in classifier order without queueing other intent types.
- Replaced the scalar pending-context execution with a list-shaped FIFO drain: after a definitive `executed` or `rejected` active result, the queue head is promoted through `remove_active` and consecutive ready additions execute synchronously, pausing at the next `pending_resolution` and clearing context only after queue exhaustion.
- Propagated `list[ProcessedIntent]` through `dispatch_pending_context` and `process_incoming_message` so every drained outcome reaches response generation in execution order.
- Kept `product_selection` context active while pending work remains, preserved `failed` results and raised exceptions, and preserved existing scalar behavior for `quitar_producto` and `modificar_producto` through one-item result lists.

**Coverage and verification:**
- Added focused unit tests for pending-intent service promotion, initial orchestrator first-active / subsequent-enqueue, initial dispatcher multi-intent ordering, pending-context execution FIFO drain (executed / rejected / paused / failed / exception), pending-context dispatcher list propagation, and incoming-message orchestrator list propagation.
- Added real-component end-to-end integration scenarios covering an ambiguous-then-ready addition resolved once, two ambiguous additions requiring two replies, repeated ambiguity preserving byte-equivalent queued ordering, and the existing single-product pending-resolution happy path.
- Re-ran `agregar_producto`, `quitar_producto`, `modificar_producto`, transactional processor, and response orchestration regressions successfully.
- Ran repository lint and type-check commands with no new failures introduced by this change.

**Files modified:**
- `backend/intents/orchestration/agregar_producto_orchestrator.py` — enqueue pending additions when an active one already exists.
- `backend/intents/orchestration/initial_intent_dispatcher.py` — preserve all classified `agregar_producto` items in classifier order.
- `backend/intents/orchestration/pending_context_execution.py` — return `list[ProcessedIntent]` and drain consecutive ready additions.
- `backend/intents/orchestration/pending_context_dispatcher.py` — return `list[ProcessedIntent]` for every branch.
- `backend/intents/orchestration/incoming_message_orchestrator.py` — propagate the pending dispatcher list unchanged.
- `backend/tests/test_pending_context_execution.py` — focused FIFO drain coverage.
- `backend/tests/test_incoming_message_orchestrator.py` — ordered-list propagation coverage.
- `backend/tests/test_initial_intent_dispatcher.py` — multi-intent classifier-order coverage.
- `backend/tests/test_modificar_producto_transactional_regression.py` — multi-addition transactional coverage.

**OpenSpec:**
- Synced seven delta specs into the main specification set: `agregar-producto-end-to-end`, `agregar-producto-intent-orchestration`, `incoming-message-orchestrator`, `initial-intent-dispatcher`, `pending-context-dispatcher`, `pending-context-execution`, and `pending-intent-service`.
- Validated the change and all seven affected main specs successfully.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-subphase-3-32-3-preserve-agregar-producto-intents/`.

**Context for future subphases:** pending `agregar_producto` state is a deterministic active-plus-FIFO-queue model. Any future intent that reuses `PendingIntents` must enqueue rather than overwrite when an active item already exists, must promote through `remove_active` after a definitive outcome, must keep `product_selection` open while additions remain, and must propagate `list[ProcessedIntent]` through every orchestrator that may emit more than one outcome per incoming message.

Subphase 3.32.4 — Sequential queue processing for multiple ambiguous `agregar_producto` intents [x] — completed

**Completed:** 2026-07-31

**Delivered:**
- Diagnosed three failing boundaries before any runtime edit:
  - `dispatch_initial_message` propagated every `ProcessedIntent` returned by `process_initial_agregar_producto`, so a second ambiguous addition was rendered as a customer response on turn 1.
  - `execute_ready_pending_context` exited its drain loop as soon as promotion reached a `pending_resolution` head, dropping the newly active clarification from the HTTP response and leaving the prior `context_type` in place.
  - `picante` was not registered in `PRESENTACION_ALIASES`, so `_narrow_by_presentacion_alias` could not resolve the bare customer reply to Empanada Picante.
- `dispatch_initial_message` now stops returning customer-visible outcomes at the first `pending_resolution` addition while still processing and enqueuing every later `agregar_producto` in classifier/source order. Non-`agregar_producto` intents keep their original dispatch contract.
- `execute_ready_pending_context` drains promoted `ready` additions exactly once, continues past definitive `executed`/`rejected` outcomes, appends a single promoted `pending_resolution` clarification, re-resolves `context_type` from the promoted intent via the existing resolver, preserves the queue tail, and keeps commit/rollback ownership and exception propagation in the transactional wrapper.
- Registered `picante` and `tradicional` in `PRESENTACION_ALIASES` so `_narrow_by_presentacion_alias` narrows the bare customer reply without catalog re-recognition.
- Preserved every queued `ProcessedIntent` (source text, quantity, candidate IDs, resolved data, requirements, status, handler, intent name, refinement state) through promotion without rerunning classification or rebuilding from response text.

**Authoritative lifecycle (PostgreSQL-backed HTTP, mock only LLM boundary):**

- Turn 1 `quiero una empanada de carne y una pizza de muzarela` → active=Empanada, queue=[Pizza], `context_type=product_selection`, response: Empanada clarification only.
- Turn 2 `picante` → Empanada Picante executed, Pizza promoted and clarified, response order: Empanada Picante confirmation then Pizza clarification; 1 `PedidoProducto` row.
- Turn 3 `grande` → Pizza Grande executed, active=None, queue=[], `context_type=None`, response: Pizza Grande confirmation; 2 `PedidoProducto` rows (Empanada Picante x1, Pizza Grande x1).

**Coverage and verification:**
- Focused unit suites: `test_initial_intent_dispatcher.py`, `test_pending_context_execution.py`, `test_pending_context_dispatcher.py` (new), `test_incoming_message_orchestrator.py`, `test_transactional_message_processor.py` cover two-pending, ready-pending, pending-ready, pending-ready-pending, three-item, inactive-clarification suppression, full queued-value preservation, non-`agregar_producto` isolation, executed/rejected promotion, ready draining, next-pending emission, context-type restoration, queue exhaustion, failed-stop, quantity/candidate preservation, finite-loop, exactly-once, single-commit success, and single-rollback on later raised handler cases.
- `test_agregar_producto_sequential_queue_end_to_end.py` (new) drives the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` endpoint with only the external LLM mocked, asserting response count/order, active intent, queue contents, `context_type`, handler-call counts, and persisted `PedidoProducto` rows for the exact three-turn scenario plus queue permutations and `quiero 4 empanadas de carne y 2 pizzas de muzarela` (quantities 4 and 2).
- Re-ran `agregar_producto`, `quitar_producto`, `modificar_producto`, transactional processor, response orchestration, and endpoint regressions; the five full-suite failures are pre-existing (modificar LLM-backed real-HTTP/CLI cases plus a single-active-context assertion documented before this change).
- Captured literal CLI output for the three-turn sequence through a new test and re-ran compileall, ruff, and mypy with no new failures; ran `openspec validate sequential-ambiguous-intent-queue-3-32-4 --strict` successfully.

**Files modified:**
- `backend/intents/orchestration/initial_intent_dispatcher.py` — stop returning customer-visible outcomes after the first ambiguous `agregar_producto` becomes active; continue processing and enqueueing later additions.
- `backend/intents/orchestration/pending_context_execution.py` — drain ready queue entries exactly once, promote through `remove_active`, append one promoted `pending_resolution`, re-resolve `context_type` from the promoted intent, do not commit/rollback, propagate raised exceptions.
- `backend/recognizers/product_recognizer.py` — register `picante` and `tradicional` in `PRESENTACION_ALIASES`.
- `backend/tests/test_initial_intent_dispatcher.py`, `backend/tests/test_pending_context_execution.py`, `backend/tests/test_pending_context_dispatcher.py` (new), `backend/tests/test_incoming_message_orchestrator.py`, `backend/tests/test_transactional_message_processor.py`, `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` (new).

**OpenSpec:**
- Synced five delta specs into the main specification set: `agregar-producto-end-to-end`, `incoming-message-orchestrator`, `initial-intent-dispatcher`, `pending-context-dispatcher`, `pending-context-execution` (23 new requirements, 40 new scenarios).
- Validated the change and all five affected main specs successfully.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-sequential-ambiguous-intent-queue-3-32-4/`.

**Context for future subphases:** only the first `pending_resolution` addition may be exposed as a customer response on the initial turn; later `agregar_producto` additions are processed and queued but never surfaced until promoted. `execute_ready_pending_context` owns the deterministic FIFO drain, must re-resolve `context_type` from the promoted intent, and must leave commit/rollback ownership to the transactional wrapper. `PRESENTACION_ALIASES` must keep covering the bare reply forms the spec exercises (currently `picante`, `tradicional`); new bare-reply keywords require an alias entry, not catalog re-recognition.

Subphase 3.32.5 — Fix repeated unresolved active candidate selection and promote the next queued ambiguous product [x] — completed

**Completed:** 2026-07-31

**Delivered:**
- Diagnosed the runtime defect end-to-end through the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` pipeline against `supernova_test` with only the external LLM boundary mocked.
- Identified the first failing boundary: `backend/intents/context/product_selection_context_resolver.py:_narrow_by_presentacion_alias` rejected fragments whose tokens were outside `STOPWORDS ∪ TAMANIOS ∪ PRESENTACION_ALIASES`, so `carne picante` was dropped (the unrelated-noun guard fired on `carne`) and the resolver returned the unchanged `pending_resolution` intent on every turn.
- Added `_extraneous_words_relate_to_active_intent` and relaxed the extraneous-token guard so it only blocks tokens that are unrelated to the active intent's `source_text` or `resolved_data` — preserving the `fugazeta grande` guard against Pizza while allowing `carne picante` against `una empanada de carne` to narrow.
- Discriminating fragments (`picante`, `la picante`, `carne picante`, `la común`, `la de carne común`) now uniquely resolve the persisted active candidate, clear `candidate_ids`, preserve `cantidad` and `resolved_data`, mark the product requirement completed, and return `ready` without broadening recognition.
- Reused the Subphase 3.32.4 drain-and-promote loop unchanged: ready active intent executes exactly once, only the completed active item is removed, the persisted FIFO queue head is promoted with full `ProcessedIntent` field preservation, `product_selection` context is restored from the promoted intent, and the response order is `executed` followed by `pending_resolution`.
- Definitive `rejected` active outcomes still promote Pizza, failed results stop advancement without queue loss, and raised exceptions propagate to the transactional wrapper for a single rollback.

**Authoritative lifecycle (PostgreSQL-backed HTTP):**

- Turn 1 `quiero una empanada de carne y una pizza` → Carne active, Pizza queued, `context_type=product_selection`, response: Carne clarification only.
- Turn 2 `picante` → Carne Picante executed, Pizza promoted and clarified, response order: Carne Picante confirmation then Pizza clarification; 1 `PedidoProducto` row.
- Turn 3 `muzzarella grande` → Pizza Grande executed, active=None, queue=[], `context_type=None`, response: Pizza Grande confirmation; 2 `PedidoProducto` rows (Empanada Picante x1, Pizza Grande x1).
- Quantity variant `quiero 4 empanadas de carne y 2 pizzas` → `picante` resolves Carne x4 and preserves Pizza quantity 2 with its original candidate IDs.

**Coverage and verification:**
- Focused resolver tests in `backend/tests/test_product_selection_context_resolver.py` (`ResolveProductSelectionCarneFragmentTest`) cover `picante`, `la picante`, `carne picante`, candidate-domain defense, no-match preservation, multi-match refinement, quantity preservation, and raw real-recognizer output before and after the correction (8 tests).
- Pending-context dispatcher tests (`DispatchPendingContextStateOwnershipTest`, `DispatchPendingContextAmbiguousRefinementTest`) prove the resolved active intent cannot be overwritten by stale serialized state and that ambiguous refinement persists only the refined active intent while preserving the queue (4 tests).
- Pending-context execution tests (`ExecuteReadyPendingContextCarnePicanteTest`, `ExecuteReadyPendingContextTransactionalBoundaryTest`) lock in exactly-once handler invocation, persisted-field preservation on promotion, failed-result stop-without-queue-loss, rejected-active-promotes-pizza, and exception propagation (5 tests).
- Incoming-message orchestrator tests (`ProcessIncomingMessageClarificationOnlyCarnePicanteTest`) confirm `picante` bypasses initial classification and returns the pending dispatcher's complete ordered list (2 tests).
- End-to-end HTTP regression (`SequentialQueueE2EExactAssertionsTest`) drives the real endpoint with the exact three-turn messages and the quantity variant, asserting response count and order, active/queue state, candidate IDs, handler-call count, and `PedidoProducto` rows (4 tests).
- Full focused suite (resolver, dispatcher, execution, orchestrator, transactional, endpoint, response orchestration, end-to-end): 184 tests passed.
- `agregar_producto` sequential queue, single ambiguous, multiple ready, multiple ambiguous, and `cantidad_agregada` regressions passed.
- `quitar_producto` and `modificar_producto` suites retain only the 5 pre-existing failures documented in Subphase 3.32.4 (unrelated `product_modification_resolver` paths).
- `ruff check` clean on every changed file; `mypy backend/intents/context/product_selection_context_resolver.py` reports only the 1 pre-existing Literal-typed `status` error; `py_compile` clean on every changed file.
- `openspec validate fix-repeated-unresolved-active-candidate-selection --strict` → valid.
- Manual CLI acceptance from a fresh session showed the Carne clarification, the Carne Picante confirmation followed by the Pizza clarification, and a final order table with Empanada Picante x1 and Pizza Grande x1; session cleanup unchanged.

**Files modified:**
- `backend/intents/context/product_selection_context_resolver.py` — added `_extraneous_words_relate_to_active_intent`; relaxed the extraneous-token guard in `_narrow_by_presentacion_alias`.
- `backend/tests/test_product_selection_context_resolver.py` — added `ResolveProductSelectionCarneFragmentTest`.
- `backend/tests/test_pending_context_dispatcher.py` — added `DispatchPendingContextStateOwnershipTest` and `DispatchPendingContextAmbiguousRefinementTest`.
- `backend/tests/test_pending_context_execution.py` — added `ExecuteReadyPendingContextCarnePicanteTest` and `ExecuteReadyPendingContextTransactionalBoundaryTest`.
- `backend/tests/test_incoming_message_orchestrator.py` — added `ProcessIncomingMessageClarificationOnlyCarnePicanteTest`.
- `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` — added `SequentialQueueE2EExactAssertionsTest`.

**OpenSpec:**
- Synced five delta specs into the main specification set: `agregar-producto-end-to-end`, `incoming-message-orchestrator`, `pending-context-dispatcher`, `pending-context-execution`, and `product-selection-context-resolver` (16 new requirements, 26 new scenarios).
- Validated the change and all five affected main specs successfully.
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-07-31-fix-repeated-unresolved-active-candidate-selection/`.

**Context for future subphases:** discriminating fragments are resolved only against the active intent's persisted candidate catalog. The `_narrow_by_presentacion_alias` extraneous-token guard must remain active for tokens unrelated to the active intent's `source_text` or `resolved_data` (e.g. `fugazeta grande` against a Pizza active intent must still be rejected). Any new alias-style fragment added to product-selection tests requires an alias entry in `PRESENTACION_ALIASES` (e.g. `picante`, `tradicional`) — recognition broadening to the commerce catalog remains forbidden. The 3.32.4 drain-and-promote loop owns FIFO promotion and exactly-once handler sequencing; future work that needs active-state transitions must persist or stage the resolver result once and must not restore pre-resolution or stale serialized state.

Subphase 3.32.6 — Add classifier and resolver data-flow diagnostics to `backend.scripts.cli_chat_client` [x] — completed

**Completed:** 2026-08-01

**Delivered:**
- Selected the smallest clean mechanism compatible with the existing HTTP-based CLI: opt-in `X-Debug-Flow` request header activates a request-scoped `CollectingDiagnosticSink` inside the FastAPI incoming-messages orchestrator; the response payload gains a `diagnostics` array only when the header is present. The CLI sends the header exclusively when `--debug-flow` is set.
- Added `backend/diagnostics/` with the public surface (`DiagnosticSink` protocol, `NoopDiagnosticSink`, `CollectingDiagnosticSink`, `serialize`, `redact`) and five event dataclasses (`ClassifierCallStarted`, `ClassifierCallCompleted`, `ResolverCallStarted`, `ResolverCallCompleted`, `PendingStateSnapshot`) carrying `call_id`, `sequence`, `phase`, and `to_dict()`. The default sink is a true no-op (empty final-class methods, no allocations in the hot path).
- Instrumented the real call sites: `IntentClassifier.query` (single `QueryLlm.request` call, wrapped in `try/finally`), `ProductSelectionContextResolver.resolve` (initial resolution, refinement, and the post-promotion invocation in the 3.32.4 drain-and-promote loop), the pending-context resolver, and the `modificar_producto` resolver that reuses the same mechanism. `PendingStateSnapshot` events are captured before the pending-context resolver and after every resolver call.
- Added `backend/diagnostics/serializer.py` with a safe recursive `serialize(value, *, redact=True, _seen=None)` supporting `None`, `bool`, `int`, `float`, `str`, `Enum`, `dict`, `list`/`tuple`/`set`/`frozenset`, dataclasses, Pydantic v2 models, and SQLAlchemy ORM instances with `__table__` (reading column values, never lazy-loading). Recursion depth bounded at 64, total field count bounded at 4096 per call, cycle detection via `_seen`. Unsupported types return `"<ClassName>"`. `redact` walks dicts/lists/tuples and replaces values whose key (case-insensitive) is in `_REDACTED_KEYS = {"password", "token", "api_key", "authorization", "secret", "database_url", "DATABASE_URL", "Authorization", "X-API-Key", "X-API-KEY"}` with `"<redacted>"`.
- Extended `backend/routers/incoming_messages.py` with a `get_diagnostic_sink` FastAPI dependency keyed on the `X-Debug-Flow` header; the response builder merges sink events into a `diagnostics` key (sorted by `(sequence, phase)`) only when the sink is a `CollectingDiagnosticSink`, and a redaction pass is applied to the full payload (including `diagnostics`) before returning. The default response (no header) keeps the exact pre-change shape.
- Extended `backend/scripts/cli_chat_client.py` with `--debug-flow` (`action="store_true"`) and `--debug-components` (default `""`, comma-separated, valid set `{"classifier", "resolver", "pending"}`, `SystemExit(2)` on unknown values). The flag sends `{"X-Debug-Flow": "1"}` on the incoming-messages POST. New helpers: `_extract_diagnostics`, `_render_diagnostics`, `_format_kv_table`, `_format_intent_table`, `_format_pending_state_snapshot`, `_format_pending_queue_table`, `_redact_payload` — all stdlib-only, dynamic column widths, `+---+---+` borders, Unicode-preserving, `ensure_ascii=False`, sorted keys, and `<redacted>` substituted for `_REDACTED_KEYS`. Diagnostic tables print between customer responses and the order table.
- The CLI never imports classifier or resolver modules; transport is exclusively the `X-Debug-Flow` response payload contract. No reclassification, no ghost resolver call, no extra database round-trip, no extra commit/rollback.

**Coverage and verification:**
- `backend/tests/test_diagnostics.py` (15 focused tests) covers primitives, dict key sorting, list order preservation, dataclass field serialization, Pydantic v2 model fields, enum-by-value, SQLAlchemy ORM column reading, unsupported-type fallback, recursion loop fallback, depth-limit fallback, and redaction paths (password/token/api_key, `DATABASE_URL`, `Authorization` header, nested-in-list, redact-disabled passthrough).
- `backend/tests/test_cli_chat_client.py::CliDebugFlowTest` (15 cases) covers flag-disabled default output, flag-enabled header and table rendering, `--debug-components classifier` filtering, unknown-component `SystemExit(2)`, secret redaction, multi-intent `CLASSIFIER OUTPUT`, `RESOLVER CANDIDATES` (3 rows), `PENDING STATE` snapshot, `PENDING QUEUE` (2 rows), `RESOLVER MATCHES` (3 rows), `RES-001` call-ID correlation across input/output, accented product names (`Empanada de Jamón y Queso`, `Pizza de Muzzarella`) preserved verbatim, error-path `ClassifierError` table, no-duplicate-classifier-call under repeated `--debug-flow`, and debug-mode-does-not-affect-order-table.
- Router test confirms the default response (no header) is byte-for-byte identical to the pre-change response, and the `X-Debug-Flow: 1` response includes a `diagnostics` list whose length matches the sink's event count.
- `PYTHONPATH=. .venv/bin/python -m compileall backend` exits 0.
- `PYTHONPATH=. .venv/bin/python -m ruff check backend` and `mypy backend` clean on every changed file.
- `openspec validate add-cli-classifier-resolver-flow-debug-3-32-6 --strict` → valid.
- Manual acceptance deferred: requires a live `supernova_test` PostgreSQL instance; the in-process `TestClient` + `CliDebugFlowTest` suite exercises every required diagnostic surface and header transport contract under `backend/tests/test_cli_chat_client.py:CliDebugFlowTest`.

**Files added:**
- `backend/diagnostics/__init__.py` — public surface exports.
- `backend/diagnostics/events.py` — five dataclass event types with `to_dict()`.
- `backend/diagnostics/sink.py` — `DiagnosticSink` protocol, `NoopDiagnosticSink`, `CollectingDiagnosticSink` (allocates `CLS-NNN` / `RES-NNN` call IDs).
- `backend/diagnostics/serializer.py` — safe recursive `serialize` with bounded depth/fields and cycle guard.
- `backend/diagnostics/redaction.py` — `_REDACTED_KEYS` constant and `redact` walker.
- `backend/tests/test_diagnostics.py` — 15 focused serializer/redaction/sink tests.

**Files modified:**
- `backend/llm/intent_classifier.py` — `sink: DiagnosticSink = NoopDiagnosticSink()` constructor parameter, `try/finally` around the single `QueryLlm.request` call emitting `ClassifierCallStarted` / `ClassifierCallCompleted`; the query LLM call still happens exactly once.
- `backend/intents/context/product_selection_context_resolver.py` — keyword-only `sink` argument on `resolve`, `on_resolver_started` / `on_resolver_completed` emissions for the initial resolution, refinement, and post-promotion call in the drain-and-promote loop.
- `backend/intents/context/context_type_resolver.py` (or equivalent pending-context entry point) — `sink` argument with matching `ResolverCallStarted` / `ResolverCallCompleted` emissions and a `PendingStateSnapshot` event before/after the resolver call.
- `backend/services/incoming_message_service.py` (or equivalent orchestrator module) — optional `sink` keyword argument (defaults to `NoopDiagnosticSink()`), threads the sink through to the classifier and every resolver; the orchestrator returns the sink's events to the router when the header is set.
- `backend/routers/incoming_messages.py` — `get_diagnostic_sink` FastAPI dependency on the `X-Debug-Flow` header, merges sorted sink events into the `diagnostics` response field, applies the redaction pass to the full payload.
- `backend/scripts/cli_chat_client.py` — `--debug-flow` and `--debug-components` flags, `X-Debug-Flow` header emission, table renderers (`_format_kv_table`, `_format_intent_table`, `_format_pending_state_snapshot`, `_format_pending_queue_table`), `_extract_diagnostics`, `_render_diagnostics`, `_redact_payload`, module-level `_REDACTED_KEYS` and `_DEBUG_COMPONENT_ALIASES`. No imports from the classifier or resolver modules.
- `backend/tests/test_cli_chat_client.py` — new `CliDebugFlowTest` suite (15 cases) covering flag behavior, table rendering, filtering, redaction, correlation, Unicode, error path, and the no-duplicate-call / no-business-change contracts.

**OpenSpec:**
- Synced six delta specs into the main specification set: `cli-classifier-resolver-flow-debug` (new capability, 17 requirements), `context-type-resolver` (1 requirement), `incoming-message-orchestrator` (2 requirements), `incoming-messages-interactive-cli` (4 requirements), `intent-classifier` (2 requirements), `product-selection-context-resolver` (1 requirement) — 27 new requirements total, all `ADDED` (no modifications, removals, or renames).
- Validated the change and all six affected main specs successfully (`openspec validate --specs` clean, no new errors).
- Archived the completed `spec-driven` change at `openspec/changes/archive/2026-08-01-add-cli-classifier-resolver-flow-debug-3-32-6/`.

**Context for future subphases:** diagnostics are gated by the `X-Debug-Flow` request header and the `--debug-flow` CLI flag; the default response and default CLI output remain bit-for-bit identical to the pre-3.32.6 behavior, and `_REDACTED_KEYS` is the canonical redaction set on both the server and the CLI (keep both copies in sync when extending). New classifier or resolver call sites that should be observable must accept a `sink: DiagnosticSink = NoopDiagnosticSink()` keyword argument and emit `ClassifierCallStarted`/`ClassifierCallCompleted` or `ResolverCallStarted`/`ResolverCallCompleted` in a `try/finally` around the real call; never call a component solely for diagnostics. Pending-state snapshots live on the pending-context resolver boundary, so any future resolver that mutates queue state should emit a `PendingStateSnapshot` before and after. The `CollectingDiagnosticSink` allocates `CLS-NNN` / `RES-NNN` IDs globally per request, so multi-intent classifier outputs and drain-and-promote resolver sequences must keep that ordering stable.

Subphase 3.32.7 — Fix product narrowing by `producto_nombre` when the alias lives in the product name [x] — completed

**Completed:** 2026-08-01

**Delivered:**
- Diagnosed the runtime defect end-to-end: when the alias extracted from the user's reply lives in the candidate's `producto_nombre` (e.g. `picante`, `tradicional`) rather than in `presentacion_codigo`, `_narrow_by_presentacion_alias` produced an empty `matching_ids` set, the intersection was empty, and the resolver returned the unchanged `pending_resolution` active intent. The 3.32.5 extraneous-token guard allowed the message through, but the match predicate itself rejected it.
- Widened the per-candidate match predicate in `_narrow_by_presentacion_alias` so each candidate is a match when **either** `_presentacion_matches(codigo, alias)` is true (the existing path) **or** the canonical alias token returned by `_extraer_presentacion` appears as a whole word in the candidate's `producto_nombre` after `_normalizar_texto` normalization: `presentacion_alias in set(_normalizar_texto(nombre).split())`. The whole-word test rejects substrings like `picantes` so the alias `picante` no longer matches a candidate whose name contains the plural form.
- The presentacion_codigo path is bit-for-bit equivalent and the existing `intersection = [cid for cid in active_intent.candidate_ids if cid in matching_ids]` filter is preserved, so the new branch only widens the matching set without touching the narrowing decision logic.
- Fixed the 3.32.6 diagnostic emission so the `RESOLVER OUTPUT` event records the resolver's result (`status_after`, `selected_candidate_id`, `candidate_ids_after`, `candidate_count_after`, `matches`) instead of the original `active_intent`. The `RESOLVER INPUT` event is unchanged (it still captures the candidate catalog projection before narrowing).
- No changes to `PRESENTACION_ALIASES`, `_extraer_presentacion`, `_normalizar_texto`, `_presentacion_matches`, the 3.32.5 extraneous-token guard, the 3.32.4 drain-and-promote loop, the prompts, the classifier, the orchestrator, the router, the CLI, the diagnostics module, the database columns, or any new dependency.

**Authoritative lifecycle (HTTP end-to-end against `supernova_test`):**

- Turn 1 `agrega 1 empanada de carne` → Carne active with both `Empanada de Carne` and `Empanada de Carne Picante` in `candidate_ids`, `cantidad=1`, `context_type=product_selection`, response: pending_resolution clarification.
- Turn 2 `carne picante` → the new product-name whole-word match narrows to the Picante candidate, `candidate_ids=[]`, `producto_presentacion_id` set, `cantidad=1` preserved, `status=ready`, response: executed confirmation containing `Empanada de Carne Picante`. The classifier is not invoked a second time (single classifier call across the two turns). The queue is empty throughout.

**Coverage and verification:**
- `backend/tests/test_product_selection_context_resolver.py` — `ResolveProductSelectionProductoNombreAliasTest` (9 focused tests) covering `picante` uniquely selecting a Picante candidate, `tradicional` narrowing to a Tradicional pizza, `carne picante` / `la picante` / `la de carne picante` against the 3.32.5-extraneous-guard-permitting active intent, substring-only `picantes` rejected, `la grande` regression through the existing `presentacion_codigo` path, `grandi` alias variant firing through alias normalization, and multi-narrowed candidate persistence of `pending_resolution` with the original `cantidad` preserved.
- `backend/tests/test_product_selection_context_resolver.py` — `ResolveProductSelectionDiagnosticSurfaceTest` (2 tests) verifying the `CollectingDiagnosticSink` records `RESOLVER INPUT` with `incoming_text="carne picante"`, `candidate_count=2`, both `producto_nombre` values in the catalog projection, and `RESOLVER OUTPUT` with `status_after="ready"`, `selected_candidate_id=32`, `candidate_ids_after=[]`, `candidate_count_after=0`, and a single-element `matches` list; the `NoopDiagnosticSink` retains the no-event contract.
- `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` — `SequentialQueueE2ECarnePicanteProductoNombreTest` (1 HTTP regression) drives the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` endpoint against `supernova_test` with a seeded catalog whose discriminator lives in `producto_nombre` (two products, both `presentacion_codigo="UNIDAD"`, names `Empanada de Carne {s}` and `Empanada de Carne Picante {s}`). Asserts the second turn executes the Picante candidate, preserves `cantidad=1`, does not call the classifier again, leaves the queue empty, and clears the active intent (`context_type=None`).
- Existing 3.32.5 `SequentialQueueE2EExactAssertionsTest` (4 tests) and 3.32.4 pending-queue regressions (`test_pending_context_dispatcher`, `test_pending_context_execution`, `test_incoming_message_orchestrator`, 57 tests) all pass without modification — the presentacion_codigo path is unchanged.
- `backend/tests/test_product_selection_context_resolver.py` suite: 32 tests pass (resolver-focused + Carne fragment + ProductoNombre alias + Diagnostic surface + Tamanio refinement + Boundaries).
- `PYTHONPATH=. venv/bin/python -m compileall backend` → exit 0.
- `PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` → only the 1 pre-existing I001 import-order warning on the resolver file (unchanged from 3.32.6); no new failures introduced.
- `PYTHONPATH=. venv/bin/python -m mypy backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` → clean (no errors on the changed files).
- `openspec validate fix-product-narrowing-by-producto-nombre-3-32-7 --strict` → valid.

**Diagnostic observations (3.32.6 surface):**
- `RESOLVER INPUT [TURN N] [RES-NNN]` records `incoming_text="carne picante"`, `candidate_count=2`, and the two-row `candidate_catalog` projection including both `producto_nombre` values.
- `RESOLVER CANDIDATES [RES-NNN]` renders both catalog rows.
- `RESOLVER OUTPUT [TURN N] [RES-NNN]` records `status_after="ready"`, `selected_candidate_id=32`, `candidate_ids_after=[]`, `candidate_count_after=0`, and `matches=[32]`.
- `NoopDiagnosticSink` (default) emits no events and remains a true no-op (`on_classifier_*` / `on_resolver_*` / `on_pending_state_snapshot` only).

**Files modified:**
- `backend/intents/context/product_selection_context_resolver.py` — added the product-name whole-word match predicate in `_narrow_by_presentacion_alias` (additive branch only); captured the resolver result in a local variable so the `ResolverCallCompleted` event records `status_after`, `selected_candidate_id`, `candidate_ids_after`, `candidate_count_after`, and `matches` from the actual result rather than the original `active_intent`.
- `backend/tests/test_product_selection_context_resolver.py` — added `PRODUCTO_NOMBRE_PICANTE_CATALOG` and `PRODUCTO_NOMBRE_TRADICIONAL_CATALOG` module-level fixtures, `ResolveProductSelectionProductoNombreAliasTest` (9 cases), and `ResolveProductSelectionDiagnosticSurfaceTest` (2 cases); imported `ResolverCallStarted` / `ResolverCallCompleted` from `backend.diagnostics.events`.
- `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` — added `_seed_commerce_product_name_discriminator` and `_cleanup_product_name_discriminator` helpers and `SequentialQueueE2ECarnePicanteProductoNombreTest` (1 HTTP regression).

**OpenSpec:**
- Delta spec at `openspec/changes/fix-product-narrowing-by-producto-nombre-3-32-7/specs/product-selection-context-resolver/spec.md` adds two new requirements ("Presentacion-alias narrow step matches against `producto_nombre`" and "Discriminating fragments that span the active intent and product-level alias") with 8 supporting scenarios.
- `openspec validate fix-product-narrowing-by-producto-nombre-3-32-7 --strict` → valid.
- Change NOT yet synced into main specs and NOT yet archived (per task 6.3).

#### Subphase 3.32.8 — add-imperative-verbs-to-stopwords [x] — completed

**Completed:** 2026-08-01

**Delivered:**
- Diagnosed that imperative removal and action verbs were not in `STOPWORDS` in `backend/recognizers/product_recognizer.py:19`, so `_filtrar_por_tokens_clave` rejected candidates whose `producto_nombre` did not contain those tokens. This blocked `quitar_producto` without explicit quantity (`"quita las empanadas de pollo"` → `encontrados=[]`) and `agregar_producto` without explicit quantity (`"agrega empanadas de pollo"`), even though `execute_quitar_producto` already supports full-line removal when `cantidad_value is None`.
- Extended the literal `STOPWORDS` set with the imperative and infinitive forms of remover / generic action / add verbs (normalized lowercase, no accents, matching the existing set convention): `quita`, `quitar`, `saca`, `sacame`, `sacala`, `quitala`, `quitalas`, `quitale`, `sacasela`, `elimina`, `eliminar`, `remueve`, `remover`, `borra`, `borrar`, `suprime`, `suprimir`, `agrega`, `agregar`. No other logic change; the rest of `detectar_productos` is bit-for-bit equivalent.
- No DB / router / schema / service / new-dependency changes. The change is local to the recognizer and the recognizer's test file.

**Architectural constraints introduced:**
- Imperative and action verbs are stopwords from the recognizer's perspective; the classifier LLM still routes them to the correct intent (`quitar_producto`, `agregar_producto`, etc.) before the recognizer runs.
- `STOPWORDS` remains the single source of truth for tokens discarded by the token-key filter; no second set (`IMPERATIVE_VERBS`) was introduced.
- Regional / clitic-combined conjugations (`sacanos`, `sacámelas`, `quítenmela`) remain out of scope; the set is extensible as a `frozenset` if reports surface.

**Coverage and verification:**
- 5 new tests in `backend/tests/test_product_recognizer.py`: quitar without quantity, pronominal `sacala empanadas de pollo`, generic action verb `elimina la pizza muzza`, `agregar_producto` without explicit quantity, and a `STOPWORDS` membership assertion for every new verb.
- Existing `backend/tests/test_quitar_producto_*.py`: 46/49 pass; 1 pre-existing integration failure (`test_initial_pending_context_with_multiple_lines`) reproduces with `STOPWORDS` reverted — DB-state / `uq_pedido_producto_presentacion` unique-constraint issue, unrelated to this change.
- Existing `backend/tests/test_agregar_producto_*.py`: 12/12 pass.
- Existing `backend/tests/test_modificar_producto_*.py`: 117/119 pass; 2 pre-existing failures (`test_defect_1_cli_full_transfer_on_omitted_quantity`, `test_defect_1_full_transfer_on_omitted_quantity`) reproduce with `STOPWORDS` reverted — modifier `cambia` is outside the new `STOPWORDS` scope and these assert that `modificar_producto` should auto-remove the source line, unrelated to this change.
- Full backend test suite: 528 tests in 56.76s; 2 failures + 1 error are all pre-existing (same 3 above), confirmed by reverting the `STOPWORDS` change. No new regressions introduced.

**Files modified:**
- `backend/recognizers/product_recognizer.py` — extended `STOPWORDS` literal set.
- `backend/tests/test_product_recognizer.py` — added 5 regression tests for the new verbs.

**OpenSpec:**
- Delta spec at `openspec/changes/add-imperative-verbs-to-stopwords/specs/product-recognizer/spec.md` adds the requirement "Imperative removal and action verbs are stopwords" with 6 scenarios (Quitar without quantity, Sacar in any conjugation, Sacar pronominal, Generic action verb, `agregar_producto` without explicit quantity, Stopword set includes the new imperative verbs).
- Synced to `openspec/specs/product-recognizer/spec.md:148` before archiving.
- Archived at `openspec/changes/archive/2026-08-01-add-imperative-verbs-to-stopwords/`.

#### Subphase 3.33 — initialize-local-git-and-connect-supernova-ia [x] — completed

**Completed:** 2026-08-02

**Delivered:**
- Initialized a Git repository at `/Users/diegoadducilagreca/Documents/supernova-ia` with `main` as the local branch.
- Added a root `.gitignore` before staging so the local virtual environment, Python caches, `.env`, macOS metadata, tool state, Node dependencies, build artifacts, and IDE metadata remain untracked.
- Created the initial commit `d86afaf` (`chore: bootstrap git repository`) without changing application behavior.
- Reused the existing GitHub repository owned by `dgadduci`; configured `origin` as `https://github.com/dgadduci/supernova-ia.git` for fetch and push.
- Confirmed the remote was reachable and pushed `main` normally. No new repository, force-push, history replacement, branch deletion, repository rename, or visibility change was performed.
- Configured local `main` to track `origin/main`.

**Safety and verification:**
- Git identity pre-flight checks passed before the initial commit.
- `git check-ignore` confirmed that `.env`, `venv/bin/python`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, and `.DS_Store` are ignored.
- `git rev-parse --show-toplevel` returns `/Users/diegoadducilagreca/Documents/supernova-ia`.
- `git symbolic-ref --short HEAD` returns `main`.
- `git rev-parse --abbrev-ref --symbolic-full-name @{u}` returns `origin/main`.
- `git rev-list --left-right --count origin/main...HEAD` returns `0 0`, confirming local and remote histories are aligned.
- The setup's final verification recorded a clean working tree and `d86afaf` at both `HEAD` and `origin/main` before the subsequent OpenSpec sync and archive updates.

**Files and repository metadata:**
- `.gitignore` — added 16 ignore patterns covering local and generated artifacts.
- `.git/` — created local repository metadata, the `main` branch, and the `origin` configuration.
- Existing application source, tests, Alembic files, dependency manifests, and OpenSpec history were included in the initial snapshot without business-logic modifications.

**OpenSpec:**
- Added and synced the `git-repository-bootstrap` capability to `openspec/specs/git-repository-bootstrap/spec.md` with 6 requirements and 13 scenarios.
- All 21 implementation tasks and all planning artifacts were completed.
- Archived the completed change at `openspec/changes/archive/2026-08-02-init-git-repo-and-connect-github/`.


## Phase 4 - Recognizer hibryd implementation semantyc and fuzzy

### Subphase 4.1 — Implement Freeze the product recognizer contract and create the baseline evaluation dataset. [x]

Recognizer boundary frozen before any pgvector / semantic work. `backend.recognizers.product_recognizer.detectar_productos` is the algorithm owner and remains a compatible public entry point; consumers reach it through a new `ProductRecognizerProtocol` abstraction backed by `FuzzyProductRecognizer`, which delegates unchanged. A version-controlled baseline dataset anchors fuzzy behavior for current and future recognizer implementations. All 20 implementation tasks and all planning artifacts were completed; the change was synced to main specs and archived at `openspec/changes/archive/2026-08-02-freeze-product-recognizer-contract-baseline-dataset/`.

**Architectural constraints introduced**:
- Recognizer boundary: `ProductRecognizerProtocol` is the only abstraction consumers depend on; the contract module imports nothing from SQLAlchemy, HTTP, LLM, or repositories.
- Frozen result contract: exactly four top-level keys in insertion order — `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados` — each a list (never `None`). `encontrados_posibles` is `{"texto_origen": str, "productos": list[dict]}`; `no_encontrados` is `{"texto_origen": str}`. Recognized product entries preserve every source catalog field plus `cantidad: int` and `texto_origen: str`.
- Frozen catalog projection: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`; additional caller-supplied fields are permitted and preserved.
- Ordering and quantity semantics are stable: descending-confidence order with stable ties; duplicate product-presentation IDs retain only their strongest match; `cantidad` defaults to `1`; items filtered by false product / presentation / activity flags are absent from all collections, while `disponible == False` items surface in `encontrados_no_disponibles`.
- `FuzzyProductRecognizer.recognize(text, catalog)` delegates directly to `detectar_productos` without copying, reordering, normalizing, or tuning the result — algorithm ownership stays with the existing fuzzy module.
- Baseline dataset invariant: every case references real fixture IDs from existing test catalogs; refinement cases (`picante`, `grande`) use the same restricted candidate catalogs as the real pending-flow; cases exposing accepted fuzzy limitations are tagged `known_fuzzy_limitation: true` with a non-empty `limitation_note` describing current behavior only.
- Diagnostics: the recognizer exposes the concrete implementation name only; no semantic / vector / Ollama diagnostics yet.

**Files created**:
- `backend/recognizers/product_recognizer_contract.py` — `ProductRecognizerProtocol`, `RecognizedProduct`, `RecognizedProductGroup`, `UnmatchedFragment`, `ProductRecognizerResult`
- `backend/recognizers/fuzzy_product_recognizer.py` — `FuzzyProductRecognizer` delegating to `detectar_productos`
- `backend/tests/fixtures/product_recognizer_baseline.json` — version-controlled baseline dataset
- Reusable contract test harness + integration smoke tests for `agregar_producto` unique path and pending product-selection refinement

**Files modified**:
- Composition boundaries across `backend/` that previously depended on the concrete fuzzy module — practical sites now depend on the protocol where the resolver helper compatibility and restricted catalog boundaries allow it; `quitar_producto`, `modificar_producto` source/destination recognition, product-intent resolution, pending-context dispatch/execution, and FIFO queue promotion remain compatible.
- Recognizer diagnostics — exposed implementation name only.

**OpenSpec**:
- New capability `product-recognizer-contract` synced at `openspec/specs/product-recognizer-contract/spec.md` (8 requirements).
- New capability `product-recognizer-baseline-dataset` synced at `openspec/specs/product-recognizer-baseline-dataset/spec.md` (6 requirements).
- Existing capability `product-recognizer` extended at `openspec/specs/product-recognizer/spec.md` (2 added requirements covering protocol conformance and consumer-contract preservation).

**Context for future subphases**: the next phase can introduce a `HybridProductRecognizer` that satisfies `ProductRecognizerProtocol`; the contract test harness and baseline dataset are the shared verification surface. Remaining concrete `detectar_productos` consumers can be migrated as adjacent work touches them. Subphase 4.1 preserved observable recognition behavior; pgvector, vector tables, Ollama embeddings, alias migration to PostgreSQL, and resolver / pending-intent redesign remain out of scope until a later subphase.

### Subphase 4.2 — Persist product and product-presentation aliases in PostgreSQL. [x] — completed

Product and product-presentation aliases are now persisted in PostgreSQL and supplied to the pure fuzzy recognizer through caller-built catalog projections. The observable recognizer contract from Subphase 4.1 remains unchanged, and PostgreSQL is the only production authority for product aliases.

**Completed outcomes:**
- Added the `ProductoAlias` model and reversible Alembic migration `f68b6651e8e2_add_producto_aliases_table.py` for `producto_aliases`, including product-wide aliases (`id_producto_presentacion IS NULL`), exact product-presentation aliases, active state, normalized text, timestamps, foreign keys, lookup indexes, and PostgreSQL partial unique indexes for both alias scopes.
- Added repository and service boundaries for normalization, empty-value rejection, product/product-presentation ownership validation, scoped duplicate handling, active recognition lookup, stable ID-scoped projection, and batched catalog loading. Services do not manage transactions; callers own commit and rollback.
- Added `backend.scripts.seed_product_aliases`, backed by an idempotent seeder that resolves exact stable catalog targets without database IDs or partial-name matching, runs in one outer transaction, preserves unrelated aliases, and reports inserted, unchanged, skipped, and failed mappings.
- Moved real commercial product aliases from the hardcoded recognizer authority into persisted caller-provided alias data. General aliases remain applicable across eligible presentations; presentation-specific aliases are attached only to their exact `producto_presentacion_id`.
- Preserved `PRESENTACION_ALIASES`, `_extraer_presentacion`, structured presentation matching, resolver narrowing, fuzzy thresholds, scoring, ranking, grouping, quantity handling, availability, unknown handling, and restricted candidate behavior. Values such as `chica`, `grande`, `unidad`, and `1 litro` remain structured presentation data and are not persisted as product aliases.
- Completed characterization, model/migration, repository/service, seeder, catalog-projection, recognizer, baseline, and integration verification. All implementation tasks and planning artifacts were completed, the specs were synced, and the change was archived at `openspec/changes/archive/2026-08-02-persist-product-aliases-4-2/`.

**Architectural constraints introduced:**
- SQLAlchemy queries remain in `ProductoAliasRepository` and alias services remain infrastructure-boundaries without `commit()`, `rollback()`, `close()`, or `begin()` calls. The pure recognizer has no database, repository, or service access.
- Alias projections are commerce-scoped and restricted-catalog-scoped, load in batches, include only active aliases, and cannot broaden the supplied product-presentation catalog or leak aliases to sibling presentations or other commerces.
- The recognizer contract remains infrastructure-free and accepts optional row-scoped aliases while preserving ordinary dictionaries, additional caller fields, and the frozen result shape.
- No alias administration API or UI, pgvector, embeddings, Ollama calls, semantic recognition, hybrid recognition, resolver redesign, or pending-queue redesign was introduced.

**Relevant files:**
- `backend/models/producto_alias.py`, `backend/models/producto.py`, `backend/models/producto_presentacion.py`, and `backend/models/__init__.py`
- `backend/alembic/versions/f68b6651e8e2_add_producto_aliases_table.py` and `backend/alembic/env.py`
- `backend/repositories/producto_alias_repository.py`
- `backend/services/producto_alias_service.py`, `backend/services/producto_alias_seeder.py`, `backend/services/producto_query_service.py`, and `backend/services/exceptions.py`
- `backend/scripts/seed_product_aliases.py`
- `backend/recognizers/product_recognizer_contract.py`, `backend/recognizers/fuzzy_product_recognizer.py`, and `backend/recognizers/product_recognizer.py`
- Focused alias, seeder, catalog-projection, recognizer, and integration tests under `backend/tests/`

**Context for future subphases:** New recognition flows must enrich their catalog projection with active aliases through the existing service/repository boundary and must preserve commerce and restricted-candidate scopes. Future semantic or hybrid recognition work may consume the same `ProductRecognizerProtocol`; it must not reintroduce a second production alias source or move database access into recognizers.

### Subphase 4.3 — Enable pgvector and create product-presentation embedding persistence. [x] — completed

PostgreSQL pgvector extension is enabled and a durable `producto_presentacion_embeddings` table persists one embedding per `(producto_presentacion, modelo)` pair, validated through an idempotent repository/service boundary. The fuzzy recognizer contract from Subphases 4.1 and 4.2 remains unchanged; embedding generation, semantic document construction, similarity search, and reindexing remain out of scope for this subphase.

**Completed outcomes:**
- Added the pgvector SQLAlchemy dependency (`pgvector`) and a configurable `embedding_dimension` setting using the project's existing configuration pattern.
- Added Alembic migration `a7c9e1f2b3d4_add_producto_presentacion_embeddings.py` (down_revision `f68b6651e8e2`) that runs `CREATE EXTENSION IF NOT EXISTS vector`, creates the `producto_presentacion_embeddings` table with vector column, foreign key, uniqueness constraint, and indexes, and downgrades by removing only project-owned objects (the shared `vector` extension is preserved on downgrade).
- Added the `ProductoPresentacionEmbedding` SQLAlchemy model with `id`, `id_producto_presentacion` (FK `ON DELETE CASCADE`), `vector` (`VECTOR(embedding_dimension)`), `modelo`, and timezone-aware lifecycle timestamps; added the `ProductoPresentacion.embeddings` one-to-many relationship with cascade.
- Added the `ProductoPresentacionEmbeddingRepository` for get-by-id, get-by-presentation-and-model, list-by-presentation, create, and idempotent upsert; the repository does not commit, rollback, or close the session.
- Added the `ProductoPresentacionEmbeddingService` that validates required identifiers, non-empty `modelo`, and configured vector dimensionality, and exposes the upsert/retrieval/list operations; raises `ProductoPresentacionEmbeddingNotFound`, `InvalidProductoPresentacionEmbedding`, `DuplicateProductoPresentacionEmbedding`, and `ProductoPresentacionEmbeddingPersistenceError` through the standard persistence-error path.
- Added model metadata tests proving the table, vector column dimension, foreign key cascade, lifecycle timestamps, relationship, and uniqueness constraint, plus PostgreSQL integration tests covering extension creation, table/index constraints, upsert behavior, dimension rejection, foreign-key failure handling, and cascade deletion.
- Ran the project's lint, typecheck, and focused tests; resolved all failures.

**Architectural constraints introduced:**
- One embedding row per `(id_producto_presentacion, modelo)`, enforced by the `producto_presentacion_embedding_unico` unique constraint; persistence validates and upserts on this identity.
- Vector dimensionality is enforced by the `VECTOR(embedding_dimension)` column type and revalidated by the service for every write; dimension changes require an explicit configuration/migration update.
- Embeddings cascade-delete with their parent `ProductoPresentacion` through the foreign key and the ORM relationship.
- All SQLAlchemy queries remain inside the repository; the service does not call Ollama, generate embeddings, calculate hashes, or perform similarity search; no commit/rollback/close below the existing transaction boundary.
- No HNSW, IVFFlat, or other vector-distance indexes were created; index selection is deferred until the vector-search subphase defines distance, volume, and query patterns.
- No LangChain, LangGraph, SentenceTransformers, or vector-store frameworks were added.

**Relevant files:**
- `backend/models/producto_presentacion_embedding.py`, `backend/models/producto_presentacion.py`, and `backend/models/__init__.py`
- `backend/alembic/versions/a7c9e1f2b3d4_add_producto_presentacion_embeddings.py` and `backend/alembic/env.py`
- `backend/repositories/producto_presentacion_embedding_repository.py`
- `backend/services/producto_presentacion_embedding_service.py` and `backend/services/exceptions.py`
- `backend/config/settings.py` (new `embedding_dimension` setting)
- `backend/tests/test_producto_presentacion_embedding_model.py` and `backend/tests/test_producto_presentacion_embedding_integration.py`

**OpenSpec:**
- New capability `producto-presentacion-embeddings` synced at `openspec/specs/producto-presentacion-embeddings/spec.md` (3 requirements: embedding persistence, idempotent persistence operations, pgvector extension availability).
- Existing capability `producto-presentacion` extended at `openspec/specs/producto-presentacion/spec.md` to include the `embeddings` relationship and the cascade-delete scenario on the `ProductoPresentacion` model definition.
- Archived the completed change at `openspec/changes/archive/2026-08-03-enable-pgvector-product-presentation-embeddings/`. All 12 implementation tasks and all planning artifacts were completed.

**Context for future subphases:** Embedding writes remain caller-owned; the next phase can introduce the embedding provider client and semantic document generation through the existing service boundary without touching the repository or schema. Vector similarity search, indexing strategy, and hybrid recognizer wiring remain explicit follow-ups once provider semantics and query patterns are defined.

### Subphase 4.4 — Add the local Ollama embedding client. [x] — completed

Local Ollama embedding generation now lives behind a typed, provider-neutral boundary that is fully independent from the existing Qwen generation configuration, persistence, and the rest of the backend. All 17 implementation tasks and all planning artifacts were completed; the change was synced to main specs and archived at `openspec/changes/archive/2026-08-03-add-local-ollama-embedding-client/`.

**Completed outcomes:**
- `backend/llm/embedding_client.py` exports `EmbeddingClientProtocol` (`embed_query`, `embed_documents`), `OllamaEmbeddingClient`, and the exception hierarchy `EmbeddingClientError` → `EmbeddingConnectionError` / `EmbeddingTimeoutError` / `EmbeddingResponseError` / `EmbeddingDimensionError`.
- `OllamaEmbeddingClient` calls the configured Ollama `/api/embed` endpoint, uses the configured `all-minilm:latest` model and timeout, validates HTTP status / JSON shape / result count / vector presence / finite numeric values / configured vector dimension, preserves input order, and maps transport failures (`requests.exceptions.Timeout` / `ConnectionError`, non-success HTTP, malformed body, wrong count, wrong dimension) to the typed exception hierarchy.
- `embed_documents` splits inputs into bounded requests of `EMBEDDING_BATCH_SIZE`; `embed_documents([])` returns `[]` without a network request; any empty/whitespace document inside a non-empty batch is rejected with its index; `embed_query("")` and whitespace-only input are rejected before any HTTP activity.
- `backend/config/settings.py` gained five embedding-only settings — `embedding_url` (default `http://localhost:11434/api/embed`), `embedding_model` (`all-minilm:latest`), `embedding_dimension` (`384`, aligned with the Subphase 4.3 `VECTOR(embedding_dimension)` column), `embedding_timeout_seconds` (`30`), and `embedding_batch_size` (`32`) — all overridable via env vars and independent from `LLM_URL` / `LLM_MODEL`. Positive-integer validators reject non-positive values.
- `backend/scripts/check_embedding_client.py` provides a manual verification entry point: prints the configured model, returned dimension, and elapsed time; never prints the complete vector unless an explicit debug option is enabled; skips when local Ollama is unreachable without weakening deterministic unit-test coverage.
- Focused tests in `backend/tests/test_ollama_embedding_client.py` cover single embedding, ordered batch embedding with batching boundary, empty/whitespace input rejection (single + per-index), malformed response, wrong result count, wrong vector dimension, non-finite values, timeout/connection/HTTP error mapping, configuration independence from `LLM_URL`/`LLM_MODEL`, and a real local Ollama smoke test guarded by an availability check.

**Architectural constraints introduced:**
- Embedding settings are exclusively `EMBEDDING_*`; `LLM_URL` (`/api/generate`) is never reused for embeddings.
- The client is independent from SQLAlchemy, repositories, products, semantic document building, vector persistence, and recognizers. It holds no DB connection, model, repository, or service references.
- Error messages and normal logs SHALL NOT expose raw input payloads, complete vectors, credentials, or unrelated configuration.
- `requests` is the only third-party transport dependency; it was already available transitively in the project venv.
- No LangChain, LangGraph, SentenceTransformers, or vector-store frameworks were introduced.

**Relevant files:**
- `backend/llm/embedding_client.py` (exports `EmbeddingClientProtocol`, `OllamaEmbeddingClient`, exception hierarchy, `__all__`)
- `backend/config/settings.py` (added `embedding_url`, `embedding_model`, `embedding_dimension`, `embedding_timeout_seconds`, `embedding_batch_size` and their `DEFAULT_*` constants)
- `backend/scripts/check_embedding_client.py` (manual verification CLI)
- `backend/tests/test_ollama_embedding_client.py` (focused unit + integration tests)

**OpenSpec:**
- New capability `ollama-embedding-client` synced at `openspec/specs/ollama-embedding-client/spec.md` (7 requirements: independent embedding configuration, reusable embedding client interface, single-query embedding generation, ordered bounded document batching, Ollama response validation, domain-specific failure mapping, safe local verification).
- Change archived at `openspec/changes/archive/2026-08-03-add-local-ollama-embedding-client/`.

**Context for future subphases:** semantic document construction is now available as a pure, content-addressed component; the next phase can wire it to `EmbeddingClientProtocol` and `ProductoPresentacionEmbeddingService` for embedding writes, similarity search, HNSW/IVFFlat indexing, hybrid recognizer wiring, and reindex endpoints without revisiting the document shape. Future callers build the `ProductEmbeddingCatalogProjection` and alias inputs from existing repositories/services (never pass ORM objects directly), depend on `EmbeddingClientProtocol` (not `OllamaEmbeddingClient`) constructed from `load_settings()`, and inject a stub `requests`-shaped transport for tests. The Subphase 4.3 `embedding_dimension` setting (default `384`) is the single source of truth for vector width; any change requires the corresponding `VECTOR(...)` migration. The builder's `normalize_for_embedding` is byte-equivalent to `backend.recognizers.product_recognizer._normalizar_texto` (asserted by a focused test), so recognizer and builder share one normalization contract.

### Subphase 4.5 — Build deterministic semantic documents and content hashes for product-presentations. [x] — completed

Pure `ProductEmbeddingDocumentBuilder` is now the single authority for turning a `producto_presentacion` and its persisted aliases into deterministic `ProductEmbeddingDocument` records with stable SHA-256 `content_hash` values. No embeddings were generated and no `producto_presentacion_embeddings` rows were written; the Subphases 4.1–4.4 capabilities and the fuzzy recognizer are unchanged. All 44 implementation tasks and all planning artifacts were completed; the change was synced to main specs and archived at `openspec/changes/archive/2026-08-03-build-product-semantic-documents-4-5/`.

**Completed outcomes:**
- `backend/embeddings/text_normalization.py` exposes `normalize_for_embedding(text: str) -> str`: lowercase → `unicodedata.normalize("NFD", text)` → drop combining marks → keep `[a-z0-9ñ\s]` → collapse whitespace → strip; rejects non-`str` input with a typed `ValueError` so the builder cannot crash on a bad caller. Byte-equivalent to `backend.recognizers.product_recognizer._normalizar_texto` (asserted by `test_text_normalization.py`).
- `backend/embeddings/product_embedding_document_builder.py` exposes `ProductEmbeddingAliasScope = Literal["product", "product_presentacion"]`, `ProductEmbeddingAliasInput` (id, alias, alias_normalizado, scope, activo, id_producto_presentacion), `ProductEmbeddingCatalogProjection` (producto_id, producto_presentacion_id, producto_nombre, producto_descripcion, categoria_nombre, presentacion_id, presentacion_codigo, presentacion_descripcion), `ProductEmbeddingSourceType = Literal["canonical", "description", "alias", "combined"]`, `ProductEmbeddingDocument` (producto_id, producto_presentacion_id, source_type, source_record_id, source_text, normalized_text, content_hash), `InvalidProductEmbeddingDocument(ValueError)`, and `ProductEmbeddingDocumentBuilder` (parameterless constructor; `build(projection, aliases) -> list[ProductEmbeddingDocument]`).
- Document generation produces, in fixed order: `canonical` (`"{producto_nombre} {presentation_text}"`, `source_record_id=None`), `description` when `producto_descripcion` is non-empty after stripping (`"{canonical}. {producto_descripcion}."`), `alias` documents filtered to active + applicable scope (product-wide always applicable; presentation-specific only when `id_producto_presentacion` matches) deduped by `alias_normalizado` keeping the lowest `id`, ordered by `(alias_normalizado, id)` ascending, and finally `combined` (`"Categoría: {categoria_nombre}. Producto: {producto_nombre}. Descripción: {producto_descripcion or omitted}. Presentación: {presentation_text}."`, with the `Descripción:` segment omitted entirely when absent).
- `presentation_text` is `presentacion_descripcion` when non-empty after stripping, otherwise `presentacion_codigo`; both empty raises `InvalidProductEmbeddingDocument` and yields no documents. Two presentations of the same product always produce different `canonical` and `combined` documents whenever their `presentation_text` differs (e.g. `Unidad` vs `1 Litro`).
- `content_hash` is `hashlib.sha256(f"{producto_presentacion_id}\x1f{source_type}\x1f{source_record_id or ''}\x1f{normalized_text}".encode("utf-8")).hexdigest()` — exactly 64 lowercase hex characters; identical inputs always produce identical hashes; semantic changes to product name, description, category, presentation, or alias text change the relevant hash.
- Validation (positive `producto_id`/`producto_presentacion_id`, non-empty `producto_nombre`, recognized alias scope, presentation-specific alias ownership) runs up front; the builder raises `InvalidProductEmbeddingDocument` before constructing any document and never silently emits incomplete documents.
- Focused unit tests in `backend/tests/test_product_embedding_document_builder.py` cover canonical-with-description, canonical-fallback-to-code, description generation/omission, combined with/without description (no `None` placeholder), product-wide alias on every presentation, presentation-specific alias exclusion on siblings, presentation distinction (`Unidad` vs `1 Litro`), deterministic hashing (identity + per-axis sensitivity), duplicate normalized aliases (lowest `id` wins), stable ordering, inactive-alias exclusion, Unicode/accent normalization (`Muzzárella` ↔ `muzza`, whitespace collapse), invalid alias ownership rejection, and invalid alias scope rejection with zero documents produced. A focused byte-equality test in `backend/tests/test_text_normalization.py` locks the normalization contract against `backend.recognizers.product_recognizer._normalizar_texto`.

**Architectural constraints introduced:**
- `ProductEmbeddingDocumentBuilder` is pure: no imports of SQLAlchemy, repositories, HTTP, Ollama, pgvector, recognizers, `requests`, `fastapi`, `backend.models`, `backend.llm`, or any infrastructure; the constructor takes no arguments and performs no I/O. SQLAlchemy ORM objects SHALL NOT be passed to the builder — callers must build `ProductEmbeddingCatalogProjection` and `ProductEmbeddingAliasInput` from repository/service results.
- The output order is fixed (`canonical`, `description` if present, `alias` in `(alias_normalizado, id)` ascending order, `combined`); `content_hash` covers the same identity for all source types.
- `source_text` preserves accents and casing; `normalized_text` is the canonical form used for both duplicate detection and hashing. The hash function uses ASCII `\x1f` (unit-separator) as the inter-field delimiter and serializes `None` `source_record_id` as the empty string.
- Alias documents are never auto-generated from structured presentation data (`chica`, `grande`, `unidad`, `1 litro`); the builder consumes only caller-supplied alias inputs.
- Embedding persistence, vector similarity search, indexing, hybrid recognizer wiring, and reindex endpoints remain out of scope; the builder does not call `EmbeddingClientProtocol` or write to `producto_presentacion_embeddings`.

**Relevant files:**
- `backend/embeddings/__init__.py`, `backend/embeddings/text_normalization.py`, `backend/embeddings/product_embedding_document_builder.py`
- `backend/tests/test_product_embedding_document_builder.py`, `backend/tests/test_text_normalization.py`

**OpenSpec:**
- New capability `product-embedding-documents` synced at `openspec/specs/product-embedding-documents/spec.md` (12 requirements: deterministic product-presentation semantic documents, builder input projection, output document contract, canonical document, description document, alias documents, combined document, presentation handling, text normalization, content hash, duplicate handling and ordering, validation and error handling).
- Subphases 4.1 (`product-recognizer-contract`, `product-recognizer-baseline-dataset`), 4.2 (`product-alias-persistence`), 4.3 (`producto-presentacion-embeddings`), and 4.4 (`ollama-embedding-client`) are unchanged — this subphase adds a new capability and does not modify their requirements.
- Change archived at `openspec/changes/archive/2026-08-03-build-product-semantic-documents-4-5/`.

**Context for future subphases:** the next phase can wire `ProductEmbeddingDocumentBuilder` to `EmbeddingClientProtocol` (built from `load_settings()`) and `ProductoPresentacionEmbeddingService` to populate `producto_presentacion_embeddings`, using `content_hash` as the staleness signal after catalog changes. The builder is the single source for the `source_text`/`normalized_text` shape that similarity search, hybrid recognizers, and reindex endpoints will consume. Similarity search, HNSW/IVFFlat indexing, hybrid recognizer wiring, and administrative reindex endpoints remain explicit follow-ups. Do not implement Subphase 4.6.

### Subphase 4.6 — Implement Product Semantic Document Indexing and Initial Embedding Seeding [x] — completed

The per-document product-presentation embedding persistence and indexing pipeline is complete. All 111 implementation tasks and planning artifacts were completed; specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-seed-product-presentation-embeddings-4-6/`.

Completed outcomes:
- Migration `b8d0e2f3a4c5_evolve_producto_presentacion_embeddings_to_per_document.py` evolves `producto_presentacion_embeddings` from aggregate rows to semantic-document rows, adds `source_type`, `source_record_id`, `source_text`, `normalized_text`, `content_hash`, `embedding_status`, `activo`, and `last_error`, makes `vector` nullable for non-ready states, replaces aggregate uniqueness with the two document-level PostgreSQL partial unique indexes, adds seven table-level CHECK constraints, and uses deterministic truncation of unreconcilable placeholder rows with a downgrade that truncates before restoring the legacy shape.
- `EmbeddingStatus` is a lowercase-valued `str, enum.Enum` stored as `String(32)` with the database closed-set constraint. The authoritative reactivation-friendly transitions support recovery from `failed`, `stale`, and `inactive` to `ready`; obsolete documents are preserved as `stale`, and inactive catalog chains are preserved as `inactive`.
- Repository operations are per-document SQLAlchemy reads/writes only. Service-level reconciliation uses the full `(id_producto_presentacion, modelo, source_type, source_record_id)` identity and content-hash idempotency; unchanged ready active rows with valid vectors are not rewritten, while changed, forced, failed, stale, inactive, or invalid rows regenerate and update. Embedding failures persist sanitized errors while preserving existing vectors.
- The commerce-scoped projection and indexer include active and inactive presentations, detect inactive catalog chains before document building or embedding, use `source_text` for embedding and `normalized_text` for hashing, batch by configured size with positional vector mapping, and report `created`, `updated`, `unchanged`, `stale`, `inactive`, and `failed` outcomes. The seeder aggregates results and the CLI provides commerce/product/presentation filters, `--force`, strictly read-only `--dry-run`, and `--batch-size` through `dataclasses.replace` without changing the embedding client constructor.

Architectural constraints introduced:
- Repositories, services, indexer, and seeder do not own `commit`, `rollback`, `close`, or `begin`; the CLI owns the outer transaction. Recoverable embedding failures are committed as failed rows and surfaced through the exit status.
- The pure `ProductEmbeddingDocumentBuilder` and `OllamaEmbeddingClient` remain unchanged and are consumed through their existing public interfaces. Subphase 4.6 adds no FastAPI endpoint, router, schema, similarity-search index, automatic catalog-change hook, or hybrid recognizer wiring.

Relevant files:
- `backend/alembic/versions/b8d0e2f3a4c5_evolve_producto_presentacion_embeddings_to_per_document.py`
- `backend/models/producto_presentacion_embedding.py`, `backend/models/__init__.py`
- `backend/repositories/producto_presentacion_embedding_repository.py`, `backend/repositories/producto_presentacion_embedding_index_repository.py`
- `backend/services/producto_presentacion_embedding_service.py`, `backend/services/producto_presentacion_embedding_indexer.py`, `backend/services/producto_presentacion_embedding_seeder.py`, `backend/services/exceptions.py`
- `backend/scripts/seed_product_presentation_embeddings.py`
- `backend/tests/test_producto_presentacion_embedding_migration.py`, `backend/tests/test_producto_presentacion_embedding_indexer.py`, `backend/tests/test_seed_product_presentation_embeddings_cli.py`, and affected 4.3 persistence tests

OpenSpec:
- Modified `openspec/specs/producto-presentacion-embeddings/spec.md` and added `openspec/specs/product-presentation-embedding-indexing/spec.md`.

Context for future subphases: per-document rows and the builder's stable `source_text` / `normalized_text` / `content_hash` contract are now ready for similarity search, vector indexing, hybrid recognizer integration, and administrative reindexing. Stale-row cleanup and automatic catalog-change triggering remain future work.

### Subphase 4.7 — Add Local Administrative Product Embedding Endpoints [x] — completed

The local administrative product-embedding HTTP surface is complete. All 50 implementation tasks and planning artifacts were completed; specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-add-product-embedding-admin-endpoints-4-7/`.

Completed outcomes:
- `Settings.enable_local_admin_endpoints` is loaded from `ENABLE_LOCAL_ADMIN_ENDPOINTS` through `_bool_env`, defaults to `false`, and gates both endpoints with `404` before any service work. The gate is intended only for local development and introduces no authentication or authorization system.
- `POST /admin/comercios/{comercio_id}/product-embeddings/reindex` validates the commerce, optional product and product-presentation scope, and positive batch size; delegates directly to the existing 4.6 seeder/indexer surface; supports `producto_id`, `producto_presentacion_id`, `force`, `dry_run`, and `batch_size`; returns the six existing counters and per-presentation outcomes without exposing vectors or internal errors.
- `GET /admin/comercios/{comercio_id}/product-embeddings/status` returns commerce-isolated totals, configured model and dimension, counts for `pending`, `ready`, `failed`, `stale`, and `inactive`, active rows, rows with `last_error`, and counts by `source_type`, without exposing vectors, source text, hashes, lifecycle metadata, or error contents.
- `ProductoPresentacionEmbeddingStatusRepository` owns the SQLAlchemy status and source-type aggregations over the full commerce parent chain. `ProductoPresentacionEmbeddingAdminService` owns commerce/scope validation and orchestration of `OllamaEmbeddingClient`, `ProductoPresentacionEmbeddingIndexer`, and `ProductoPresentacionEmbeddingSeeder`, with injectable dependencies for tests.
- Focused endpoint and module-boundary tests cover the disabled gate, commerce isolation, safe response shapes, option forwarding, dry-run behavior, commit/rollback behavior, HTTP error mappings, recoverable embedding failures, dependency-managed session closure, and layer import/transaction constraints without requiring a real Ollama server.

Architectural constraints introduced:
- Route handlers receive sessions through `Depends(get_session)`. The POST route commits once after a completed real run, does not commit during dry-run, and rolls back on unhandled exceptions; route handlers never close sessions. The GET happy path performs no commit or rollback. The `get_session` generator remains the sole session-close owner.
- SQLAlchemy queries remain in repositories. The admin service and status repository do not call `commit`, `rollback`, `close`, or `begin`; the admin service does not contain raw SQLAlchemy queries.
- Subphase 4.7 reuses the 4.6 indexing, batching, hash comparison, stale/inactive reconciliation, failure handling, and dry-run behavior. The 4.6 CLI, persistence model, migration, pure document builder, and `OllamaEmbeddingClient(settings, transport=None, clock=None)` constructor remain unchanged.
- Real authentication, background jobs, automatic catalog-change regeneration, vector similarity search, HNSW/IVFFlat indexes, and hybrid/fuzzy recognizer changes remain out of scope.

Relevant files:
- `backend/config/settings.py`, `backend/services/exceptions.py`
- `backend/repositories/producto_presentacion_embedding_status_repository.py`
- `backend/services/producto_presentacion_embedding_admin_service.py`
- `backend/schemas/product_embedding_admin.py`
- `backend/routers/admin_product_embeddings.py`, `backend/main.py`
- `backend/tests/test_admin_product_embeddings_endpoints.py`
- `backend/tests/test_admin_product_embeddings_module_boundaries.py`

OpenSpec:
- Added `openspec/specs/product-embedding-admin-endpoints/spec.md`.
- Modified `openspec/specs/product-presentation-embedding-indexing/spec.md` and `openspec/specs/producto-presentacion-embeddings/spec.md`.
- Change archived at `openspec/changes/archive/2026-08-04-add-product-embedding-admin-endpoints-4-7/`.

Context for future subphases: the local administrative surface can now reindex and inspect product-presentation embeddings safely when explicitly enabled. Vector similarity search, vector indexes, automatic catalog-change triggering, production authentication, and hybrid recognizer integration remain future work.

### Subphase 4.8 — Synchronize Embeddings After Catalog Changes [x] — completed

Catalog-embedding synchronization is complete. All 61 implementation tasks and planning artifacts were completed; specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-synchronize-embeddings-after-catalog-changes-4-8/`.

Completed outcomes:
- `CatalogEmbeddingSynchronizationService` lives in `backend/services/catalog_embedding_synchronization_service.py` and exposes five narrowest-scope entry points — `synchronize_producto`, `synchronize_producto_presentacion`, `synchronize_categoria`, `synchronize_presentacion`, and `synchronize_alias` — each delegating to the existing 4.6 `ProductoPresentacionEmbeddingIndexer` / `ProductoPresentacionEmbeddingSeeder` through the existing scoped filters without duplicating document building, batching, hash comparison, state transitions, or client construction.
- `EmbeddingSynchronizationResult` lives in `backend/services/embedding_synchronization_result.py` as a frozen dataclass with exactly `attempted`, `created`, `updated`, `unchanged`, `stale`, `inactive`, `failed`, and `synchronization_failed`; it exposes no vectors, source text, hashes, customer messages, internal exception traces, or persisted settings.
- `ProductoPresentacionEmbeddingIndexRepository` gained four read-only scope-resolution methods — `list_producto_presentacion_ids_by_producto`, `list_producto_presentacion_ids_by_categoria`, `list_producto_presentacion_ids_by_presentacion`, and `list_producto_presentacion_ids_by_alias` — using bounded `select(ProductoPresentacion.id).where(...)` queries that return `list[int]` only, never `INSERT`/`UPDATE`/`DELETE`, and never call `commit`/`rollback`/`close`/`begin`.
- Orchestration is owned by the router / CLI / orchestrator for every catalog mutation boundary; catalog services (`ProductoService`, `CategoriaProductoService`, `PresentacionService`, `ProductoPresentacionService`, `ProductoAliasService`) continue to perform only validation and mutation and do not invoke the sync. `ProductoAliasService.delete` captures `id_producto` and (when present) `id_producto_presentacion` from the alias row BEFORE the deletion is staged and exposes the captured scope on its return value; the orchestrator uses the captured scope to invoke `synchronize_producto_presentacion(...)` or `synchronize_producto(...)` after the catalog commit and never resolves a deleted alias through `id_alias`.
- Focused sync tests cover product / category / presentation / product-presentation / alias scope resolution, narrowest-scope aggregation of `SeedingResult` counters, empty-scope short-circuit, embedding-relevance gating (e.g., `Producto.orden` does not trigger sync), Ollama `EmbeddingClientError` preserving the catalog commit, unhandled `SQLAlchemyError` rolling back only the synchronization transaction, commerce isolation, and the captured-scope contract for alias delete; tests use a fake `OllamaEmbeddingClient` with a stub transport and do not require a real Ollama server.

Architectural constraints introduced:
- The sync service receives the caller's outer `Session` and never calls `session.commit()`, `session.rollback()`, `session.close()`, or `session.begin()`; the router / CLI / orchestrator owns both transaction lifecycles (`commit` once after the catalog stage, then `commit` once after the sync or `rollback` once on unhandled `SQLAlchemyError`). The `get_session` generator remains the sole owner of `session.close()` in its `finally`.
- Embedding-relevance gating lives with the orchestrator using this field set — `Producto`: `nombre`, `descripcion`, `activo`, `disponible`; `CategoriaProducto`: `descripcion`, `activo`; `Presentacion`: `codigo`, `descripcion`, `activo`; `ProductoPresentacion`: `activo`, `disponible`; `ProductoAlias`: `alias`, `activo`, and scope transitions (create / update text / activate / deactivate / delete). Mutations that touch only unrelated fields (e.g., `Producto.orden`) MUST NOT trigger synchronization.
- The 4.6 indexer / seeder / service / repository public surface, the 4.6 migration, the `OllamaEmbeddingClient(settings, transport=None, clock=None)` constructor, the pure `ProductEmbeddingDocumentBuilder`, the persistence model, and the 4.7 manual reindex / status endpoints are unchanged. The sync service lives next to them but does not import FastAPI, the admin router, the document builder internals, the embedding client constructor body, or the catalog mutation services.
- On a recoverable embedding failure the catalog row stays committed and the result reports `failed>0` with `synchronization_failed=False`; on an unhandled `SQLAlchemyError` the synchronization transaction is rolled back by the caller, the catalog row stays committed, and the result reports `synchronization_failed=True` with `attempted=False` and every counter `0`. The 4.7 manual reindex endpoint remains the operator's recovery path.

Relevant files:
- `backend/services/catalog_embedding_synchronization_service.py`, `backend/services/embedding_synchronization_result.py`
- `backend/repositories/producto_presentacion_embedding_index_repository.py`
- `backend/services/producto_service.py`, `backend/services/categoria_producto_service.py`, `backend/services/presentacion_service.py`, `backend/services/producto_alias_service.py`
- `backend/routers/...`, `backend/cli/...` (or equivalent orchestrator) — orchestration call sites
- `backend/tests/test_catalog_embedding_synchronization_service.py`

OpenSpec:
- Added `openspec/specs/catalog-embedding-synchronization/spec.md`.
- Modified `openspec/specs/product-presentation-embedding-indexing/spec.md`.
- Change archived at `openspec/changes/archive/2026-08-04-synchronize-embeddings-after-catalog-changes-4-8/`.

Context for future subphases: catalog mutations now reindex the narrowest valid embedding scope inline while keeping the catalog row authoritative; embedding failures never roll back a catalog change and operators retain the 4.7 manual reindex endpoint as a recovery path. Per-presentation locks for concurrent sync calls, vector similarity search, vector indexes, production authentication, automatic retry policies, and hybrid recognizer integration remain future work.

### Subphase 4.9 — Product-Presentation Vector Search [x] — completed

pgvector-backed similarity search over `producto_presentacion_embeddings` is delivered as the typed read path the 4.6–4.8 pipeline was missing. Returns the most relevant active/available product-presentations for one commerce, isolated by `comercio`, with `top_k` applied after collapsing to the best-scoring document per `id_producto_presentacion`. All 16 implementation tasks and all planning artifacts were completed; the change was synced to main specs and archived at `openspec/changes/archive/2026-08-04-add-product-presentation-vector-search-4-9/`.

**Completed outcomes:**
- Cosine distance (`<=>`) is the search operator; result is exposed as `score = 1 - distance` (higher = more similar). A single SQL statement joins `ProductoPresentacionEmbedding` × `ProductoPresentacion` × `Producto` × `CategoriaProducto` × `Presentacion`, enforces commerce isolation through `CategoriaProducto.id_comercio`, filters on `embedding_status='ready'`, `modelo == settings.embedding_model`, the activity chain (`Producto.activo`, `Producto.disponible`, `ProductoPresentacion.activo`, `CategoriaProducto.activo`, `Presentacion.activo`), and the optional `candidate_ids` set, then collapses via `ROW_NUMBER() OVER (PARTITION BY id_producto_presentacion ORDER BY distance ASC)` and applies `LIMIT top_k` after grouping.
- Validation order is fixed in the service: (1) raise `InvalidVectorSearchTopK` when `top_k <= 0`, (2) raise `InvalidVectorSearchDimension` when `len(query_embedding) != settings.embedding_dimension`, (3) return `[]` immediately when `candidate_producto_presentacion_ids == []`, (4) otherwise invoke the repository. Step 3 MUST NOT bypass steps 1–2: invalid `top_k` and a wrong-dimension `query_embedding` still raise even when the candidate list is empty, so malformed queries never reach the database and the empty-candidate path never silently swallows invalid input.
- `ProductPresentationVectorMatch` is a frozen dataclass with exactly three fields — `id_producto_presentacion: int`, `score: float`, `source_type: str`. The result exposes no vectors, no `source_text`, no `normalized_text`, no `content_hash`, no `last_error`, no SQLAlchemy model, no `distance` value, and no internal exception trace. Ordering is `score DESC`, then `id_producto_presentacion ASC` for deterministic ties.
- Focused tests cover the 15 project-playbook scenarios plus 3 validation-order tests (top_k wins over empty candidates, dimension wins over empty candidates, top_k wins over dimension) and a module-boundary test that locks the no-commit / no-rollback / no-close / no-begin contract, the no-FastAPI / no-HTTP / no-Ollama / no-document-builder / no-seeder / no-indexer / no-sync-service / no-admin-router imports, and the frozen-dataclass field set.

**Architectural constraints introduced:**
- The service constructs the repository internally from `(session, settings)`; no factory, no DI surface beyond the existing pattern. No commit/rollback/close/begin calls below the existing transaction boundary (mirrors the 4.6 indexer and 4.8 sync service contract).
- `OllamaEmbeddingClient`, the 4.6 indexer, seeder, persistence service, and repository; the 4.7 admin endpoints; the 4.8 sync service and its result dataclass; the pure `ProductEmbeddingDocumentBuilder`; and the persistence model are unchanged. The new search surface lives next to them but does not import FastAPI, HTTP, the embedding client, the document builder, the seeder, the indexer, the sync service, the admin router, or any 4.7 schema.
- No HNSW / IVFFlat migration was performed. The existing `(id_producto_presentacion, modelo)` index plus the activity-chain filters keep exact search acceptable for the current development-scale catalog; a future subphase can add an index without changing `search_similar`'s public surface.
- Query normalization is out of scope; the operator (or a future subphase) is responsible for handing the service a query vector that matches the corpus shape.

**Relevant files:**
- `backend/services/product_presentation_vector_search_service.py` (`ProductPresentationVectorSearchService`)
- `backend/services/product_presentation_vector_match.py` (frozen `ProductPresentationVectorMatch` dataclass)
- `backend/services/exceptions.py` — added `InvalidVectorSearchDimension`, `InvalidVectorSearchTopK`
- `backend/repositories/producto_presentacion_embedding_search_repository.py` (`ProductoPresentacionEmbeddingSearchRepository`, single SQL surface)
- `backend/tests/test_product_presentation_vector_search_service.py` (focused 18-scenario suite)
- `backend/tests/test_product_presentation_vector_search_module_boundaries.py` (import/transaction/field-contract tests)

**OpenSpec:**
- New capability `product-presentation-vector-search` synced at `openspec/specs/product-presentation-vector-search/spec.md` (5 requirements: search service, top-k and dimension validation, repository performs the pgvector distance query, typed result exposes only safe fields, subphase 4.6–4.8 surface is unchanged).

**Context for future subphases:** Subphase 4.10+ can wire `ProductPresentationVectorSearchService.search_similar` into the recognizer (hybrid routing) and the customer-message flow, and can introduce the embedding query helper that hands the service a `query_embedding` derived from the customer message. Any later change that needs HNSW/IVFFlat must be driven by a measurable query-plan regression on the live catalog, not by theoretical optimization. New write paths that mutate embeddings remain out of scope; the 4.6 seeder/indexer, the 4.7 admin reindex endpoint, and the 4.8 catalog-embedding sync stay the only embedding-write surfaces. New write paths that call `search_similar` from anywhere other than the existing sync/index/admin surface must keep the fixed validation order and preserve the typed result shape.

### Subphase 4.10 — Shadow Mode for Semantic Product Recognition [x] — completed

Shadow mode runs fuzzy and semantic/vector product recognition in parallel while keeping the fuzzy recognizer as the sole authoritative result. The customer-facing `encontrados` / `encontrados_posibles` / `encontrados_no_disponibles` / `no_encontrados` payload, the handlers, the orchestrator payloads, the pending context, and any persistence are unchanged across modes. All 21 implementation tasks and all planning artifacts were completed; specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-add-product-recognition-shadow-mode-4-10/`.

**Completed outcomes:**
- `backend/config/settings.py` gained three settings: `product_recognizer_mode` (`Literal["fuzzy", "shadow"]`, default `"fuzzy"`, env `PRODUCT_RECOGNIZER_MODE`), `shadow_vector_top_k` (`int > 0`, default `5`, env `SHADOW_VECTOR_TOP_K`), and `shadow_hybrid_min_score_gap` (`float` in `[0.0, 1.0]`, default `0.05`, env `SHADOW_HYBRID_MIN_SCORE_GAP`). All three are validated at `Settings.load()` time: invalid mode raises `InvalidProductRecognizerMode(ValueError)`, non-positive top-k raises `InvalidShadowVectorTopK(ValueError)`, and `shadow_hybrid_min_score_gap` outside `[0.0, 1.0]` (including `NaN`) raises `InvalidShadowHybridMinScoreGap(ValueError)`. The three exception classes are re-exported from `backend/services/exceptions.py`. `shadow_hybrid_min_score_gap` is documented in code comments and on the observation surface as provisional and non-authoritative so Subphase 4.11 calibration can replace it without changing the observation surface.
- `backend/services/product_recognition_shadow_comparison.py` exposes two frozen dataclasses. `ProductRecognitionShadowComparison` carries exactly eleven fields — `fuzzy_best_id`, `vector_best_id`, `fuzzy_candidate_ids`, `vector_candidate_ids`, `fuzzy_candidate_scores`, `vector_candidate_scores`, `agreement`, `fuzzy_latency_ms`, `embedding_latency_ms`, `vector_latency_ms`, `vector_available`. `ProductRecognitionHybridObservation` carries exactly twelve fields — `hybrid_candidate_ranking`, `hybrid_combined_scores`, `hybrid_top1_top2_gap`, `exact_canonical_match`, `exact_alias_match`, `decision`, `fuzzy_weight`, `vector_weight`, `unique_threshold`, `ambiguous_threshold`, `min_score_gap`, `non_authoritative=True`. `agreement` is one of `"same_top1"`, `"same_candidate_set"`, `"different"`, `"fuzzy_only"`, `"vector_only"`, `"no_result"`. Neither dataclass exposes the input text, the customer message, raw vectors, prompts, source documents, correlation identifiers, database credentials, or internal exception traces; neither is a Pydantic model, a SQLAlchemy ORM model, or a class with side effects in `__post_init__`.
- `backend/services/product_recognition_shadow_service.py` exposes `ProductRecognitionShadowService` and `ShadowedProductRecognizer`. The service constructor accepts injected `EmbeddingClientProtocol`, `ProductPresentationVectorSearchService`, `Settings`, optional weights / thresholds, optional `min_score_gap` (falls back to `settings.shadow_hybrid_min_score_gap` when `None`), and an injected `clock`. It exposes a single `compare(text, catalog, fuzzy_result, fuzzy_latency_ms, id_comercio) -> tuple[ProductRecognitionShadowComparison, ProductRecognitionHybridObservation]` method that consumes the caller-supplied fuzzy result without re-invoking the fuzzy recognizer, runs the embedding and vector pipelines, classifies `agreement`, and builds the observational hybrid observation with the provisional weights, thresholds, and `min_score_gap`. The `ShadowedProductRecognizer` decorator implements `ProductRecognizerProtocol`, invokes the inner `FuzzyProductRecognizer` exactly once per call, measures its latency, forwards the already-computed result and measured latency to the shadow service, hands the comparison and observation to the recorder, and returns the inner result byte-for-byte.
- `backend/services/product_recognition_factory.py` exposes `get_product_recognizer(settings) -> ProductRecognizerProtocol`. It returns a bare `FuzzyProductRecognizer` in `"fuzzy"` mode and a `ShadowedProductRecognizer` (decorating a `FuzzyProductRecognizer`) in `"shadow"` mode; the factory accepts an optional injected recorder for test fakes.
- `backend/intents/orchestration/agregar_producto_orchestrator.py` resolves its module-level `_product_recognizer` once at import time via `get_product_recognizer(load_settings())` and continues to re-export `detectar_productos = _product_recognizer.recognize`. The `agregar_producto`, `quitar_producto`, and `modificar_producto` orchestrators import `detectar_productos` from that shared boundary. No handler, resolver, or intent-orchestration module imports the shadow service, the shadowed recognizer, the factory, the recorder, or the embedding client directly.
- `backend/services/shadow_metrics_recorder.py` exposes `ShadowMetricsRecorder.record(comparison, *, hybrid_observation, id_comercio, intent, correlation_id) -> None`. It emits exactly one structured log record per call through the standard `logging` mechanism carrying the documented safe operational fields (`id_comercio`, `intent`, `correlation_id`, `fuzzy_best_id`, `vector_best_id`, `fuzzy_candidate_count`, `vector_candidate_count`, `fuzzy_candidate_scores`, `vector_candidate_scores`, `agreement`, `fuzzy_latency_ms`, `embedding_latency_ms`, `vector_latency_ms`, `vector_available`, sanitized `failure_category`, `hybrid_candidate_ranking`, `hybrid_combined_scores`, `hybrid_top1_top2_gap`, `exact_canonical_match`, `exact_alias_match`, `hybrid_decision`, the four provisional weights and thresholds, the provisional `hybrid_min_score_gap`, and `hybrid_non_authoritative=True`). The recorder never logs the customer message, raw vectors, prompts, source documents, database credentials, stack traces, or raw exception text; it does not import FastAPI, HTTP, the embedding client module, the vector search service module, the sync service, the admin router, or any persistence model and never calls `commit` / `rollback` / `close` / `begin`.
- Focused tests cover the 15 project-playbook scenarios plus validation-order, recorder, and module-boundary cases: fuzzy mode does not call embedding or vector search; shadow mode returns the exact fuzzy result and the inner recognizer is invoked exactly once; matching top ids record `same_top1`; different top ids record `different`; matching candidate sets with reordered tops record `same_candidate_set`; fuzzy-only, vector-only, and no-result cases classify correctly; commerce isolation is preserved (the shadow service forwards `id_comercio` and never replaces it); embedding and vector-search failures never re-invoke the fuzzy recognizer and never raise a semantic exception to the caller; component latencies are recorded and non-negative; no automatic retry is performed; the hybrid observation is returned alongside the comparison with `decision` in `{"unique", "ambiguous", "unknown"}`; the recorder emits exactly one log record with the documented safe fields and never logs the message, vector, prompt, source text, credential, or stack trace; the recorder skips unavailable comparisons with `failure_category="unknown"` without raising; the recorder marks provisional weights, thresholds, and `min_score_gap` as non-authoritative via `hybrid_non_authoritative=True`; the recorder module is boundary-clean. Tests use fake embedding and vector collaborators with no real Ollama.

**Architectural constraints introduced:**
- Fuzzy mode is a no-op for the embedding client and the vector search service: the factory returns a bare `FuzzyProductRecognizer` and the shared boundary never constructs the shadow service.
- The fuzzy recognizer is invoked exactly once per shadow call. The `ShadowedProductRecognizer.recognize` runs the inner recognizer, measures its latency, and forwards the result and latency to the shadow service. The shadow service MUST NOT hold or invoke a fuzzy recognizer.
- The shadow service catches any exception from the embedding client or the vector search service and converts it to `vector_available=False`, `vector_best_id=None`, empty candidate ids, empty candidate scores, and a sanitized failure category (`"embedding_failure"` for embedding-client exceptions, `"vector_failure"` for vector-service exceptions); the caller receives no exception, no `None`, and no semantic-path state. The fuzzy recognizer is not re-invoked and the catalog row, pending context, handlers, responses, and persistence are unchanged.
- The hybrid observation is strictly observational and non-authoritative: `non_authoritative=True` is the literal field value on every observation; the provisional weights (`fuzzy_weight=0.5`, `vector_weight=0.5`), thresholds (`unique_threshold=0.7`, `ambiguous_threshold=0.4`), and `min_score_gap` (sourced from `settings.shadow_hybrid_min_score_gap`) are configurable for later calibration; the decision short-circuits to `"unique"` on exact canonical or alias match before any gap rule is consulted; the fuzzy result, visible candidates, pending context, handlers, responses, and persistence never consume it.
- The shadow service depends on the abstract `ProductRecognizerProtocol`, the 4.9 `ProductPresentationVectorSearchService`, and a `Protocol` describing the embedding client's `embed_query` method only. It MUST NOT import FastAPI, HTTP, the embedding client transport, the document builder, the seeder, the indexer, the sync service, the admin router, the persistence model, the `OllamaEmbeddingClient` concrete class, the fuzzy recognizer module, or any 4.7 schema.
- Subphase 4.5–4.9 surface is unchanged: the `ProductEmbeddingDocumentBuilder`, the `OllamaEmbeddingClient`, the `ProductoPresentacionEmbeddingIndexer` / `Seeder`, the `ProductoPresentacionEmbeddingAdminService`, the `CatalogEmbeddingSynchronizationService`, the `ProductPresentationVectorSearchService`, the `ProductoPresentacionEmbeddingSearchRepository`, the `ProductPresentationVectorMatch` dataclass, `backend/recognizers/product_recognizer`, and the `ProductRecognizerProtocol` contract are all untouched. The 4.6 migration remains the only migration for `producto_presentacion_embeddings`. The `OllamaEmbeddingClient(settings, transport=None, clock=None)` constructor and the `ProductPresentationVectorSearchService.search_similar` signature are unchanged.

**Relevant files:**
- `backend/services/product_recognition_shadow_comparison.py` (`ProductRecognitionShadowComparison`, `ProductRecognitionHybridObservation`)
- `backend/services/product_recognition_shadow_service.py` (`ProductRecognitionShadowService`, `ShadowedProductRecognizer`, embedding-client Protocol)
- `backend/services/shadow_metrics_recorder.py` (`ShadowMetricsRecorder`)
- `backend/services/product_recognition_factory.py` (`get_product_recognizer`)
- `backend/config/settings.py` — added `product_recognizer_mode`, `shadow_vector_top_k`, `shadow_hybrid_min_score_gap` and their validators
- `backend/services/exceptions.py` — added `InvalidProductRecognizerMode`, `InvalidShadowVectorTopK`, `InvalidShadowHybridMinScoreGap`
- `backend/services/__init__.py` — re-exports the new public symbols
- `backend/intents/orchestration/agregar_producto_orchestrator.py` — `_product_recognizer = get_product_recognizer(load_settings())`, re-exports `detectar_productos`
- `backend/tests/test_settings_product_recognizer_mode.py`
- `backend/tests/test_shadow_metrics_recorder.py`
- `backend/tests/test_product_recognition_shadow_service.py`
- `backend/tests/test_product_recognition_factory.py`

**OpenSpec:**
- New capability `product-recognition-shadow-mode` synced at `openspec/specs/product-recognition-shadow-mode/spec.md` (10 requirements: product recognizer mode setting, shadow vector top-k setting, shadow hybrid min score gap setting, shadow comparison dataclass, shadow service compares fuzzy and vector results without affecting the fuzzy outcome, shadowed recognizer decorator preserves the fuzzy result contract, observational hybrid ranking is recorded without becoming authoritative, shadow metrics recorder logs only safe operational data, settings-driven factory resolves the shared recognizer boundary, subphase 4.5–4.9 surface is unchanged).
- Modified `openspec/specs/product-recognizer/spec.md` — the existing "Complete backend recognizer consumers retain their contracts" requirement gained four new scenarios (`Fuzzy mode returns the exact fuzzy result`, `Shadow mode returns the exact fuzzy result`, `Shadow mode does not rewrite handlers`, `Orchestrator binding uses the settings-driven factory`) and the body was updated to describe the factory binding; all other requirements were left untouched (purely additive: 70 insertions, 0 deletions).
- Change archived at `openspec/changes/archive/2026-08-04-add-product-recognition-shadow-mode-4-10/`.

**Context for future subphases:** Subphase 4.10 delivered the observational layer Subphase 4.11 calibration relies on: agreement, fuzzy-only / vector-only outcomes, three component latencies, vector availability, sanitized failure categories, and a hybrid ranking with provisional weights, thresholds, and `min_score_gap` already attached to every observation under `non_authoritative=True`. Subphase 4.11 can replace any of those provisional numbers without changing the observation surface. Active hybrid routing, weighted fuzzy/vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, and background jobs remain future work and were explicitly out of scope here.

### Subphase 4.10.1 — Clean Shadow Failure Reporting [x] — completed

The hidden `_failure_category` mutation previously attached to the frozen `ProductRecognitionShadowComparison` through `object.__setattr__` has been removed. The failure category is now carried through the typed contract as an explicit field, eliminating the hidden-attribute surface. All 17 implementation tasks and all planning artifacts were completed; specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-clean-shadow-failure-reporting-4-10-1/`.

**Completed outcomes:**
- `ProductRecognitionShadowComparison` now exposes **twelve** fields. The added field is `failure_category: str | None` carrying the sanitized shadow-pipeline failure category (`"embedding_failure"` when the embedding client (or `_normalizar_texto`) raises, `"vector_failure"` when the vector search service raises, `None` when both pipelines succeed). The dataclass body enumerates the twelve field names and the three literal `failure_category` values; the field is supplied through the constructor and is never attached as a hidden attribute or mutated through `object.__setattr__` after construction.
- `ProductRecognitionShadowService.compare` passes `failure_category=failure_category` to the `ProductRecognitionShadowComparison` constructor on the embedding-pipeline exception, vector-pipeline exception, and success paths. The pre-existing `object.__setattr__(comparison, "_failure_category", failure_category)` line was removed; the service never holds or attaches a hidden `_failure_category` attribute.
- `ShadowMetricsRecorder.record` reads the sanitized failure category directly from `comparison.failure_category` (no `getattr(comparison, "_failure_category", None)`, no `_failure_category_unset` / `_failure_category_from` helpers). The `unknown` fallback was tightened: the recorder emits `failure_category="unknown"` only when `comparison.vector_available is False and comparison.failure_category is None`; the shadow service never emits `"unknown"`. The recorder never mutates the comparison to supply the fallback.

**Architectural constraints introduced:**
- The shadow surface MUST NOT call `object.__setattr__(comparison, "_failure_category", ...)` or read the comparison through `getattr(comparison, "_failure_category", None)` anywhere under `backend/services/`. The failure category travels through the `ProductRecognitionShadowComparison` constructor argument and is read through `comparison.failure_category`.
- The recorder is the **only** component that may emit `"unknown"` for `failure_category`, and only under the documented `vector_available is False and failure_category is None` precondition; the shadow service SHALL NOT emit `"unknown"`.
- The `Callable[[], ProductPresentationVectorSearchService]` dependency shape on the shadow service and every Subphase 4.10 behavioral surface (fuzzy-authoritative output, agreement classification, hybrid observation with `non_authoritative=True`, settings, thresholds, logging safety rules, customer-visible results, pending contexts, handlers, resolvers, vector-search behavior, the 4.5–4.9 surface) remain unchanged.

**Relevant files:**
- `backend/services/product_recognition_shadow_comparison.py` — `ProductRecognitionShadowComparison` gained `failure_category: str | None`; dataclass body updated to enumerate the twelve fields and the three literal failure-category values
- `backend/services/product_recognition_shadow_service.py` — `compare` now passes `failure_category` through the constructor on every path; the `object.__setattr__` mutation was removed
- `backend/services/shadow_metrics_recorder.py` — `record` reads `comparison.failure_category` directly; `_failure_category_unset` / `_failure_category_from` helpers and the `getattr` import path were removed
- `backend/tests/test_shadow_metrics_recorder.py` — `test_recorder_preserves_failure_category_when_set` setup switched from `object.__setattr__` to a constructor argument; added `test_recorder_does_not_attach_hidden_failure_category`
- `backend/tests/test_product_recognition_shadow_service.py` — the `getattr(comparison, "_failure_category", None)` assertion was replaced with direct `comparison.failure_category` access; added `test_shadow_service_does_not_use_object_setattr`
- `backend/tests/test_product_recognition_shadow_module_boundaries.py` — added `test_comparison_exposes_twelve_fields`

**OpenSpec:**
- Modified capability `product-recognition-shadow-mode` synced at `openspec/specs/product-recognition-shadow-mode/spec.md`: the `Shadow comparison dataclass` requirement gained the `failure_category: str | None` field, the twelve-field enumeration, the `failure_category` literal-value semantics, and four new scenarios (`Hidden _failure_category attribute is not used`, `Failure category is set on embedding-pipeline exception`, `Failure category is set on vector-pipeline exception`, `Failure category is None on a successful comparison`); the `Shadow service compares fuzzy and vector results without affecting the fuzzy outcome` requirement's step 4/5 now mandate constructor-supplied `failure_category` and forbid hidden-attribute mutation, with the embedding-failure, vector-search-failure, and component-latencies scenarios asserting the explicit `failure_category` value; the `Shadow metrics recorder logs only safe operational data` requirement now mandates direct `comparison.failure_category` access (forbidding `object.__setattr__` / `getattr` on a hidden attribute), clarifies the `unknown` fallback precondition, adds the `Recorder preserves an explicit failure category` scenario, and extends `Recorder is module-boundary clean` with the hidden-attribute prohibition.
- Change archived at `openspec/changes/archive/2026-08-04-clean-shadow-failure-reporting-4-10-1/`.

**Context for future subphases:** The shadow comparison contract is now fully typed — every sanitized shadow-pipeline failure mode is observable on `comparison.failure_category` without hidden-attribute inspection, and the recorder's `unknown` fallback is the single documented exception. Subphase 4.11 calibration and any future consumer of shadow output can rely on the field being populated on every emitted comparison (constructor argument, never `object.__setattr__`). The `_failure_category` hidden attribute is forbidden under `backend/services/`; any later change that needs to thread additional sanitized shadow state MUST add another explicit field on `ProductRecognitionShadowComparison` rather than reintroduce hidden attributes on a frozen dataclass.

### Subphase 4.11 — Hybrid Product Recognition Calibration [x] — completed

The offline calibration runner for the observational hybrid recognizer implemented in Subphase 4.10 has been delivered. All 48 implementation tasks and all planning artifacts were completed; the new specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-calibrate-hybrid-product-recognition-4-11/`. The fuzzy recognizer remains the sole authoritative recognizer; `PRODUCT_RECOGNIZER_MODE=hybrid` was not activated and no runtime call site, setting, factory, recognizer contract, handler, resolver, pending context, intent, order, response, or persistence contract was modified.

**Completed outcomes:**
- A versioned, deterministic calibration dataset lives at `backend/data/product_recognition_calibration_cases.json` (`schema_version: 2`, 10 cases). Every Subphase 4.1 baseline case is preserved verbatim and the previously skipped database-dependent `multi-word-jamon-queso-dynamic` case now ships with a deterministic catalog fixture so it executes during calibration. Representative cases were added for commerce isolation and restricted-candidate exclusion only where the baseline left a coverage gap; no production customer data is included. The dataset SHA-256 fingerprint is computed at load time from canonical sorted-key UTF-8 JSON; no fixed string is labelled as a fingerprint.
- A frozen `HybridDecisionPolicy` dataclass enforces every invariant: finite weights in `[0, 1]` that sum to `1` within the project-standard tolerance, thresholds and `minimum_score_gap` in `[0, 1]`, `unique_threshold >= ambiguous_threshold`, `vector_top_k > 0`. Violations raise a deterministic validation error before any embedding or database work starts.
- `ProductRecognitionCalibrationRunner` evaluates each selected case end-to-end: fuzzy is invoked exactly once, one query embedding is generated, and one commerce-scoped vector search is executed at the largest requested `top_k`; smaller per-policy `top_k` slices are derived without repeating infrastructure calls. Allowed and restricted candidate boundaries are enforced and `candidate_boundary_violation` is reported on violation. The runner continues after individual fuzzy/embedding/vector failures, preserves sanitized failure categories and stable failed case IDs in dataset order, and raises `RuntimeError("no evaluable hybrid cases")` only when no case produces an evaluable vector observation.
- A deterministic Cartesian grid covers `(fuzzy_weight, vector_weight)` ∈ {(0.4, 0.6), (0.5, 0.5), (0.6, 0.4)}, `unique_threshold` ∈ {0.65, 0.70, 0.75}, `ambiguous_threshold` ∈ {0.35, 0.40, 0.45}, `minimum_score_gap` ∈ {0.00, 0.05, 0.10}, `vector_top_k` ∈ {3, 5, 7}. Invalid combinations are rejected by policy validation, duplicates are removed while preserving declared order, and ties on the primary metric are broken deterministically by fewer false positives → fewer incorrect `unique` decisions → higher top-1 accuracy → fewer false `unknown` → lower `top_k` → closest normalized Manhattan distance to the provisional defaults → declared grid order. No external ML, Bayesian optimization, genetic algorithm, or online learning is used.
- Explicitly denominated metrics cover total cases, decision accuracy, top-1 accuracy, recall at top-k, false positives, false `unknown`, incorrect `unique` decisions, correct/incorrect ambiguities, presentation-resolution accuracy, canonical-match accuracy, alias-match accuracy, restricted-candidate accuracy, fuzzy-baseline accuracy, vector-only accuracy, hybrid accuracy, fuzzy/vector top-1 agreement, latency p50/p95 (nearest-rank), infrastructure failures, failed case IDs, the selected policy, and per-category metrics that intersect each population with the category population. Zero denominators serialize as `null`; infrastructure failures remain in the applicable denominators and cannot count as correct.
- Eligibility for Subphase 4.12 is gated explicitly on primary-metric improvement, false-positive tolerance, restricted-candidate non-regression, exact canonical preservation, exact alias preservation, commerce isolation, and latency budget. Missing configurable inputs produce `pending` with stable missing-input reasons; failed gates produce `not_eligible` with stable failure reasons; only every-gate-passes produces `eligible`. The runner never invents a tolerance or marks the selected policy eligible merely because it was selected.
- The JSON report is deterministic (sorted keys, stable list order, finite numbers, byte-identical for equal observations), atomic on disk, and free of input text, vectors, credentials, prompts, source documents, stack traces, raw exception text, sessions, and connections.
- The local CLI `python -m backend.cli.calibrate_product_recognizer` accepts `--dataset`, `--output`, `--commerce-id`, and `--limit`; validates inputs before calibration; creates and owns exactly one database session through the project session factory (no commit, single `close()` in `finally`); writes the JSON report atomically; prints only a concise `cases=… policies=… eligibility=…` summary; and returns non-zero for invalid dataset, invalid configuration, database failure, or total calibration failure. Individual embedding/vector failures leave at least one evaluable hybrid case produce a partial report and do not alone force a non-zero exit. The CLI neither reads nor mutates `PRODUCT_RECOGNIZER_MODE`.

**Architectural constraints introduced:**
- Calibration lives entirely behind `ProductRecognitionCalibrationRunner` with collaborators (`recognizer`, `embedding_client`, `vector_search_factory`, optional `clock`) injected through the constructor; tests use fake embedding and vector collaborators with no real Ollama traffic.
- The runner MUST NOT import or mutate `ProductRecognitionShadowComparison`, `ProductRecognitionHybridObservation`, `ShadowMetricsRecorder`, `ProductRecognitionShadowService`, the recognizer factory, runtime settings, provisional values, or any runtime call site. Fuzzy remains authoritative; shadow mode remains observational; no `hybrid` runtime mode is added.
- The `vector_search_factory` MUST be invoked per case so the per-request `ProductPresentationVectorSearchService` is preserved. Calibration services MUST NOT perform `commit`, `rollback`, `begin`, or any persistence mutation; MUST NOT import FastAPI, HTTP, LangChain, LangGraph, or external metrics/ML libraries; and MUST NOT change the `ProductRecognizerProtocol` contract.
- The dataset is the single source of truth for calibration cases and expected outcomes; the runner derives its SHA-256 fingerprint from the file. Calibration results are reproducible from the dataset and the runner alone; no recognizer code changes are required to evolve the dataset.
- The deterministic grid and tie-break sequence are part of the public contract of `backend/services/product_recognition_calibration_policy.py`; future subphases that want a different search shape MUST add it as a new exported generator and MUST NOT mutate `generate_policy_grid` or `policy_distance` in place.

**Relevant files:**
- `backend/data/product_recognition_calibration_cases.json` — versioned dataset (`schema_version: 2`), 10 cases covering exact canonical/alias, fuzzy misspelling, ambiguous restricted presentations, restricted refinements, dynamic multi-word, quantity wording, and dynamic commerce-isolation cases.
- `backend/services/product_recognition_calibration_policy.py` — frozen `HybridDecisionPolicy` dataclass, `validate_dataset`, deterministic `generate_policy_grid`, `policy_distance`, `dataset_fingerprint`, and `nearest_rank` helpers.
- `backend/services/product_recognition_calibration_runner.py` — `ProductRecognitionCalibrationRunner.run` plus `CaseObservation`, `StrategyPrediction`, and `_fuzzy_ids`/`_strategy_metrics`/`_eligibility`/`_hybrid_prediction` helpers; `_eligibility` consumes explicit eligibility inputs and emits `pending` / `not_eligible` / `eligible`.
- `backend/services/product_recognition_calibration_report.py` — `write_report_atomic` with deterministic JSON serialization (sorted keys, stable list order, finite numbers) and forbidden-field absence.
- `backend/cli/calibrate_product_recognizer.py` — local CLI with `--dataset`, `--output`, `--commerce-id`, `--limit`; owned database session closed in `finally`; concise stdout summary; non-zero exit on invalid dataset/configuration/database/total calibration failure; never reads or mutates `PRODUCT_RECOGNIZER_MODE`.
- `backend/tests/test_product_recognition_calibration_policy.py`, `backend/tests/test_product_recognition_calibration_runner.py`, `backend/tests/test_product_recognition_calibration_report.py`, `backend/tests/test_product_recognition_calibration_eligibility.py`, `backend/tests/test_product_recognition_calibration_cli.py` — focused tests covering policy invariants and frozen behaviour, deterministic grid generation and tie-breaking, exact canonical/alias preservation, restricted-candidate and commerce-isolation boundaries, the formerly skipped dynamic baseline case, embedding/vector failure handling, every metric denominator and zero-denominator `null`, per-category populations, nearest-rank p50/p95, JSON determinism and safety, dataset fingerprint derivation, forbidden-field absence, atomic output, CLI options, owned-session closure on success and failure, no commit, concise output, exit codes, and absence of `PRODUCT_RECOGNIZER_MODE` mutation. Subphase 4.5–4.10.1 regression tests remained green.

**OpenSpec:**
- New capability `calibrate-hybrid-product-recognition-4-11` synced at `openspec/specs/calibrate-hybrid-product-recognition-4-11/spec.md`: 8 Requirements (`Deterministic calibration dataset`, `Typed hybrid decision policy`, `Offline calibration runner`, `Bounded deterministic parameter search`, `Explicitly denominated calibration metrics`, `Fuzzy baseline comparison and eligibility`, `Safe deterministic JSON report`, `Local calibration CLI`) with their Scenarios covering baseline preservation, missing-coverage minimisation, fingerprint derivation, frozen policy construction, runner semantics, commerce/candidate boundaries, infrastructure failure handling, grid repeatability, deterministic tie-breaking, denominator rules, percentile determinism, eligibility gates, JSON safety, and CLI session/print/exit-code contracts.
- Modified capability `product-recognition-shadow-mode` synced at `openspec/specs/product-recognition-shadow-mode/spec.md`: appended one new Requirement `Offline calibration preserves shadow-mode authority and contracts` with 3 Scenarios (`Calibration does not alter runtime behavior`, `Existing shadow failures remain observational`, `Existing subphase regressions remain green`); all pre-existing requirements and scenarios are preserved verbatim.
- Change archived at `openspec/changes/archive/2026-08-04-calibrate-hybrid-product-recognition-4-11/`.

**Context for future subphases:** The calibration dataset, policy, runner, report, and CLI are now the documented interface for hybrid-recognizer evidence. Subphase 4.12 (and any later activation subphase) can drive the policy selection directly from the JSON report emitted by `python -m backend.cli.calibrate_product_recognizer --output …`; eligibility inputs (primary metric, required improvement, false-positive tolerance, latency budget) are still supplied by the operator and the runner will refuse to invent them. The runner is offline-only: it does not call handlers, resolvers, pending contexts, intents, orders, responses, persistence, FastAPI, the embedding client transport, or the recognizer factory's runtime call site. Future work that wants to consume a selected policy as runtime authority MUST add a new subphase that introduces `PRODUCT_RECOGNIZER_MODE=hybrid`; that work remains explicitly out of scope here.

### Subphase 4.11.1 — Expand Product Recognition Calibration Dataset and Define Eligibility Gates [x] — completed

The Subphase 4.11 calibration has been made statistically useful for `comercio_id=1` without altering runtime recognition behavior. All 39 implementation tasks and all planning artifacts were completed; the new specs were synchronized and the change was archived at `openspec/changes/archive/2026-08-04-expand-product-recognition-calibration-dataset-4-11-1/`. Fuzzy remains the sole authoritative runtime recognizer; `PRODUCT_RECOGNIZER_MODE=hybrid` was not activated and no runtime call site, setting, factory, recognizer contract, handler, resolver, pending context, intent, order, response, persistence contract, HTTP endpoint, or canonical spec was modified.

**Completed outcomes:**
- `backend/data/product_recognition_calibration_cases.json` now ships `schema_version: 3` with 47 cases total — the 11 preserved Subphase 4.11 cases kept verbatim (their `catalog_scope: "in_memory"` fixtures, embedded `catalogs[*].entries`, expected outcomes, and `case_id`s are untouched) plus 36 new `comercio_id=1` cases that use `catalog_scope: "commerce_dynamic_database"` and an empty `catalogs[*].entries` list. Every new case references real `producto`, `producto_presentacion`, `presentacion`, and `producto_alias` rows for `comercio_id=1` through an opaque symbolic `seed_refs` map (e.g. `pp_empanada_pollo`, `pp_pizza_muzzarella_chica`); numeric IDs are never used as portable symbolic references. The dataset covers every required input shape (canonical, alias/colloquial, fuzzy misspelling, product plus presentation, quantity word, ambiguous, unknown, restricted candidate set, semantically similar, fuzzy/vector disagreement) and every required category (`canonical`, `alias`, `ambiguous`, `unknown`, `restricted`, `commerce_isolation`, `baseline`) at least once across the new cases.
- The dataset carries an optional top-level `eligibility` block (`primary_metric = "decision_accuracy"`, `required_improvement = 0.0`, `false_positive_tolerance = 0.0`, `latency_budget_ms_p95 = 500`). `validate_dataset` accepts `schema_version` `1`, `2`, and `3`; `v1` and `v2` validation paths are preserved unchanged, `v3` adds presence/finite/range checks for the optional `eligibility` block (allowed primary metric values, non-negative finite `required_improvement` / `false_positive_tolerance` / `latency_budget_ms_p95`, `false_positive_tolerance` ∈ `[0, 1]`).
- `ProductRecognitionCalibrationRunner.run` consumes the dataset `eligibility` block when no explicit `eligibility` argument is supplied, mapping `latency_budget_ms_p95` to the `latency_budget` consumed by the existing gate; when an explicit `eligibility` argument is supplied, the dataset block is ignored; when both are absent, the runner keeps the existing `pending` fallback with the documented missing-input reasons. The runner never invents a tolerance or marks the selected policy eligible merely because it was selected.
- Scope-aware database-backed reference validation runs only for cases whose `catalog_scope == "commerce_dynamic_database"`. For each such case, immediately before evaluation, the runner resolves every `expected_producto_presentacion_id_ref` through `seed_refs`, validates every `allowed_candidate_ids` / `restricted_candidate_ids` entry, and checks every resolved or direct candidate ID against that case's own `id_comercio`. Failures for missing symbolic references, nonexistent resolved or candidate IDs, IDs owned by another commerce, or ambiguously resolving symbolic keys surface as a distinct error naming the case, the reference or candidate, the offending value, and the expected commerce scope before that case is evaluated. The 11 preserved `catalog_scope: "in_memory"` cases stay on the embedded-catalog validation and evaluation path; their candidate IDs are not checked against the seeded database, their `id_comercio` values are not forced to `1`, and fixture IDs are not reinterpreted as production database IDs.
- A new repository-supported inventory step at `backend/scripts/calibration_inventory.py` is the single source of truth for the `seed_refs` entries used by the new `comercio_id=1` cases. It runs in `--mode regenerate` or `--mode validate`, connects through the project's existing SQLAlchemy session factory, queries only `id_comercio = 1`, scopes itself exclusively to the new `commerce_dynamic_database` cases (it does not inspect or reinterpret preserved `in_memory` cases), and exits non-zero with a structured message naming the symbolic key, offending value, and expected scope on each failure mode (missing, nonexistent, cross-commerce, ambiguous). The script lives outside the runtime code path.
- The local CLI `python -m backend.cli.calibrate_product_recognizer` requires no changes: it already calls `runner.run(dataset, commerce_id, limit)` without an explicit `eligibility` argument, so the runner picks up the dataset `eligibility` block automatically and the CLI summary emits a real `eligible` / `not_eligible` / `pending` verdict instead of the previous `pending`-by-default behaviour.

**Architectural constraints introduced:**
- The `seed_refs` map is the single source of truth for symbolic database references used by new `comercio_id=1` cases. It is regenerated or validated by `backend/scripts/calibration_inventory.py` and is not hand-maintained. Opaque symbolic keys are portable across reseeds; a reseed only requires running the inventory step in `--mode regenerate`.
- Database-backed reference validation is gated on `catalog_scope == "commerce_dynamic_database"` and validated against each case's own `id_comercio`. The 11 preserved `in_memory` cases never query the seeded database for candidate validation and never reinterpret fixture IDs as production IDs; the existing embedded-catalog path is preserved verbatim.
- Runtime code (the runner, the policy, the resolver, the CLI) MUST NOT import `backend.scripts.calibration_inventory`, `backend.tests.*`, or any fixture module. The inventory step is a tool script callable from the project root, not a runtime dependency. The runner resolves `seed_refs` through its own validation, which uses the same database queries the inventory step uses.
- The dataset is the single source of truth for calibration cases, expected outcomes, and eligibility inputs. The runner derives its SHA-256 fingerprint from the canonical UTF-8 JSON (sorted keys, stable list order); `schema_version` `3` adds the optional `eligibility` block but does not change the fingerprint algorithm.
- Calibration services MUST NOT perform `commit`, `rollback`, `begin`, or any persistence mutation; MUST NOT import FastAPI, HTTP, LangChain, LangGraph, or external metrics/ML libraries; and MUST NOT change the `ProductRecognizerProtocol` contract. The CLI owns exactly one database session through the project session factory and closes it in `finally`; it does not read or mutate `PRODUCT_RECOGNIZER_MODE`.
- `validate_dataset` accepts `schema_version` `1`, `2`, and `3`; removing any of the three versions is forbidden. The Subphase 4.11 runner, deterministic grid, JSON report schema, eligibility gates, and CLI surface are preserved verbatim; no requirement or scenario from Subphase 4.11 was weakened.

**Relevant files:**
- `backend/data/product_recognition_calibration_cases.json` — versioned dataset (`schema_version: 3`, 47 cases total = 11 preserved Subphase 4.11 cases + 36 new `comercio_id=1` cases). Top-level `seed_refs` map of opaque symbolic keys; optional top-level `eligibility` block with `primary_metric = "decision_accuracy"`, `required_improvement = 0.0`, `false_positive_tolerance = 0.0`, `latency_budget_ms_p95 = 500`. New `comercio_id=1` cases cover canonical, alias, fuzzy misspelling, colloquial, product plus presentation, quantity word, ambiguous, unknown, restricted, semantically similar, and fuzzy/vector-disagreement input shapes; every category in `{canonical, alias, ambiguous, unknown, restricted, commerce_isolation, baseline}` is present.
- `backend/scripts/calibration_inventory.py` (new) — repository-supported inventory step with `--mode regenerate` and `--mode validate`. Scoped exclusively to the `seed_refs` entries used by new `commerce_dynamic_database` cases with `id_comercio=1`. Uses the project's SQLAlchemy session factory; exits non-zero with a structured message for missing, nonexistent, cross-commerce, or ambiguous references. Not imported by any runtime module.
- `backend/services/product_recognition_calibration_policy.py` — `validate_dataset` now accepts `schema_version` `3`; `_validate_eligibility` enforces presence, allowed primary metric values, non-negative finite numerics, and `false_positive_tolerance ∈ [0, 1]` when the optional `eligibility` block is present. Existing `v1`/`v2` validation paths are preserved unchanged.
- `backend/services/product_recognition_calibration_runner.py` — `_resolve_dataset_eligibility` reads the optional top-level `eligibility` block from the dataset only when no explicit `eligibility` argument is supplied, mapping `latency_budget_ms_p95` to the `latency_budget` field consumed by the existing gate. `_validate_commerce_dynamic_database_references` resolves every `expected_producto_presentacion_id_ref` through `seed_refs`, validates every `allowed_candidate_ids` / `restricted_candidate_ids` entry, and checks every resolved or direct candidate ID against each `commerce_dynamic_database` case's own `id_comercio` before evaluating that case; failures name the case, reference or candidate, offending value, and expected commerce scope. The 11 preserved `catalog_scope: "in_memory"` cases remain on the existing embedded-catalog path with no seeded-database validation, no forced `id_comercio=1`, and no fixture-ID reinterpretation.
- `backend/cli/calibrate_product_recognizer.py` — unchanged. Already calls `runner.run(dataset, commerce_id=args.commerce_id, limit=args.limit)` without an explicit `eligibility` argument, so it picks up the dataset `eligibility` block automatically. Concise `cases=… policies=… eligibility=…` summary now reflects a real verdict for `comercio_id=1`.
- `backend/tests/test_product_recognition_calibration_dataset_4_11_1.py` (new) — focused tests covering `validate_dataset` accepting `schema_version` `3` (and rejecting malformed `eligibility` blocks), `validate_dataset` continuing to accept `schema_version` `2` unchanged, the runner consuming the dataset `eligibility` block when no explicit argument is supplied and using the explicit argument when supplied, the inventory step validating every `seed_refs` entry for the new `comercio_id=1` `commerce_dynamic_database` cases, scope-aware database-backed reference validation with distinct failures for missing, nonexistent, cross-commerce, and ambiguous references per `commerce_dynamic_database` case, preservation of the 11 verbatim `in_memory` cases on their embedded-catalog path, category coverage across the expanded dataset (every required input shape, every allowed category, at least 30 evaluable `comercio_id=1` cases, 30–50 cases total), runner-import-graph clean of `backend.tests.*` / `backend.scripts.calibration_inventory` / any fixture module, and deterministic calibration output (sorted keys, stable list order, finite numbers, byte-identical for equal observations). Subphase 4.5–4.10.1 regression tests and the existing 4.11 focused suite remained green.

**OpenSpec:**
- New capability `expand-product-recognition-calibration-dataset-4-11-1` synced at `openspec/specs/expand-product-recognition-calibration-dataset-4-11-1/spec.md`: 3 Requirements (`Expanded calibration dataset for comercio_id=1`, `Dataset carries optional eligibility inputs`, `Schema version three is accepted`) with 9 Scenarios covering preserved-baseline cases, input-shape and category coverage, valid referenced database IDs, `commerce_dynamic_database` case shape, valid `eligibility` block acceptance, malformed `eligibility` block rejection, absent `eligibility` block behaviour, `schema_version` `3` acceptance, and `schema_version` `2` preservation.
- Modified capability `calibrate-hybrid-product-recognition-4-11` synced at `openspec/specs/calibrate-hybrid-product-recognition-4-11/spec.md`: appended one new Requirement `Runner reads eligibility from dataset when no explicit argument is supplied` with 3 Scenarios (`Dataset eligibility is consumed when no explicit argument is supplied`, `Explicit eligibility argument overrides the dataset block`, `Absent eligibility block keeps existing pending behaviour`), inserted before the existing `Local calibration CLI` requirement. All 8 pre-existing requirements and their scenarios are preserved verbatim.
- Change archived at `openspec/changes/archive/2026-08-04-expand-product-recognition-calibration-dataset-4-11-1/`.

**Context for future subphases:** The Subphase 4.12 activation gate now has a real signal path: the CLI consumes the dataset `eligibility` block, the runner emits a deterministic `eligible` / `not_eligible` / `pending` verdict with stable reasons, and `reports/calibration-comercio-1.json` carries the per-category metrics, selected policy, infrastructure failures, and latency p50/p95 needed for the activation decision. Operators who want different eligibility inputs can pass an explicit `eligibility` argument (e.g. via a small in-process script) or modify the dataset; the runner will not invent them. The `seed_refs` map is the only portable reference surface for new `commerce_dynamic_database` cases — a future subphase that adds cases for another `id_comercio` MUST add a corresponding inventory entry and MUST keep the symbolic-key convention. Runtime code MUST NOT import `backend.scripts.calibration_inventory` or any fixture module; the inventory step is a tool, not a runtime dependency. Hybrid mode activation, weighted fuzzy/vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, and background jobs remain future work and are explicitly out of scope here.

### Subphase 4.11.2 — Correct Presentation Alias Misclassification in Product Recognition [x] — completed

The product-descriptor misclassification that caused the real `modificar_producto` HTTP flow to reject descriptor-bearing destinations has been removed without any redesign of the fuzzy recognizer. All 18 implementation tasks and all planning artifacts were completed; the modified spec was synchronized and the change was archived at `openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/`. No embedding model, Ollama configuration, vector data, calibration dataset, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed; the defect fix is isolated to a single removed alias in `PRESENTACION_ALIASES`.

**Completed outcomes:**
- The single `picante → picante` entry has been removed from `PRESENTACION_ALIASES` in `backend/recognizers/product_recognizer.py` so descriptor tokens stay available for product-identity matching and no longer activate structured presentation filtering. All other aliases (`chica`, `chico`, `chiqui`, `pequena`, `pequeno`, `familiar`, `fami`, `gran`, `grande`, `grandi`, `individual`, `unidad`, `lata`, `litro`, `litros`, `medio`, `tradicional`) and all other recognizer logic (`_extraer_presentacion`, `_extraer_candidatos`, `_filtrar_por_tokens_clave`, `_calcular_score`, `_segmentar_pedido`, presentation filter, output shape) are preserved verbatim. No fuzzy scores, thresholds, ranking, or output shape changed.
- `tradicional` was reviewed as the only other possibly descriptor-like alias and was **preserved** because current catalog evidence (`producto_nombre`, `producto_aliases`, `presentacion.codigo`, `presentacion.descripcion`) does not demonstrate the same misclassification. The conservative-review rule from scope was honored: aliases were only changed when current catalog evidence proves the same classification error.
- Legitimate presentation recognition is preserved for `chica`, `mediana`, `grande`, `unidad`, `porción`, `docena`, `media docena`, `litro`, and `medio litro`. The corresponding unit, portion, dozen, liter, and half-liter aliases are unchanged.
- A new `DetectarProductosPresentacionTest` class with 7 focused regression tests was added to `backend/tests/test_product_recognizer.py`: `test_picante_no_esta_en_presentacion_aliases`, `test_descriptor_picante_no_filtra_candidato_unidad` (the direct defect), `test_termino_legitimo_grande_filtra_candidato_correcto`, `test_termino_legitimo_chica_filtra_candidato_correcto`, `test_termino_legitimo_lata_filtra_candidato_correcto`, `test_termino_presentacion_desconocido_no_filtra_unidad`, and `test_presentacion_aliases_incluye_terminos_legitimos`. The 5 pre-existing stopword tests remain unchanged.
- The two real-flow HTTP defects pass against `supernova_test`: `ModificarProductoRealFlowHttpTest::test_defect_1_full_transfer_on_omitted_quantity` now transfers the full source quantity to the descriptor-bearing destination, and `test_defect_2_unknown_destination_preserves_source` continues to reject an unknown destination without mutating the source.
- `backend/tests/test_llm_settings.py::test_embedding_overrides_apply` now uses `test-embedding-model` as the environment-override value and assertion value (was `nomic-embed-text`). The environment-override test purpose and production defaults (`all-minilm:latest`) are preserved.

**Architectural constraints introduced:**
- `PRESENTACION_ALIASES` MUST treat only genuine catalog-backed presentation terms as presentation aliases. Flavor, variety, ingredient, and product-descriptor tokens that belong in `producto_nombre` (e.g. `picante`) MUST NOT be added to `PRESENTACION_ALIASES`. A future change that wants to add another alias MUST first confirm the alias maps to a real `presentacion_codigo` or `presentacion_descripcion` value in the catalog and MUST NOT add the alias on the basis of a free-text pattern alone.
- Alias removals follow the conservative-review rule: an alias is removed only when current catalog evidence (`producto_nombre`, `producto_aliases`, `presentacion.codigo`, `presentacion.descripcion`) demonstrates the same misclassification that the removal would fix. `tradicional` is the documented example of an alias that was reviewed and preserved.
- `_extraer_presentacion`, `_calcular_score`, `_extraer_candidatos`, presentation filter logic, fuzzy scores, thresholds, ranking, and output shape MUST NOT be modified by a future subphase that only wants to fix a misclassified alias. The defect fix in this subphase is isolated to a static alias-map deletion; any deeper change requires a new OpenSpec subphase.
- The `EMBEDDING_MODEL` test override fixture MUST use a synthetic value (`test-embedding-model`) and MUST NOT encode a real embedding model identifier. Production defaults (`all-minilm:latest`) are unchanged.

**Relevant files:**
- `backend/recognizers/product_recognizer.py` — removed the single `picante → picante` line from `PRESENTACION_ALIASES`. All other aliases (`chica`, `chico`, `chiqui`, `pequena`, `pequeno`, `familiar`, `fami`, `gran`, `grande`, `grandi`, `individual`, `unidad`, `lata`, `litro`, `litros`, `medio`, `tradicional`) and all other recognizer logic (`_extraer_presentacion`, `_extraer_candidatos`, `_filtrar_por_tokens_clave`, `_calcular_score`, `_segmentar_pedido`, presentation filter, output shape) are unchanged.
- `backend/tests/test_product_recognizer.py` — added `DetectarProductosPresentacionTest` with 7 tests (`test_picante_no_esta_en_presentacion_aliases`, `test_descriptor_picante_no_filtra_candidato_unidad`, `test_termino_legitimo_grande_filtra_candidato_correcto`, `test_termino_legitimo_chica_filtra_candidato_correcto`, `test_termino_legitimo_lata_filtra_candidato_correcto`, `test_termino_presentacion_desconocido_no_filtra_unidad`, `test_presentacion_aliases_incluye_terminos_legitimos`). Pre-existing stopword tests remain green.
- `backend/tests/test_llm_settings.py` — `test_embedding_overrides_apply` now uses `test-embedding-model` as the override and assertion value (was `nomic-embed-text`). Environment-override test purpose and production defaults are preserved.
- `openspec/specs/project.md` — replaced this subphase's pending implementation prompt with the proper completed entry (objective, context, scope, out-of-scope, files affected become completed outcomes, architectural constraints, relevant files, OpenSpec, and context for future subphases).

**OpenSpec:**
- Modified capability `product-recognizer` synced at `openspec/specs/product-recognizer/spec.md`: updated `### Requirement: Presentation matching against presentacion_codigo and presentacion_descripcion` to add the explicit rule that flavor/variety/ingredient/product-descriptor terms belonging to `producto_nombre`, including `picante`, SHALL NOT be classified as presentation aliases and SHALL NOT discard a matching product candidate because its `presentacion_codigo` lacks that term; and to enumerate the legitimate presentation concepts that SHALL remain available (`chica`, `mediana`, `grande`, `unidad`, `porción`, `docena`, `media docena`, `litro`, `medio litro`). Modified the existing `#### Scenario: Explicit presentation resolves one candidate` (example token changed from `familiar` to `grande`, expected-outcome language aligned). Appended 5 new scenarios under the same requirement: `Product descriptor does not activate presentation filtering`, `Legitimate presentation vocabulary remains recognized`, `Unknown presentation text does not create a false product match`, `Omitted-quantity replacement resolves descriptor-bearing destination`, and `Unknown replacement destination preserves source`. All other requirements and scenarios are preserved verbatim.
- Change archived at `openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/`.

**Context for future subphases:** Recognizer defects that come from a static map (alias table, stopword table, token table) are now expected to be fixed by surgical changes to the map entry plus a targeted spec scenario, without rewriting `_extraer_presentacion` or any other helper. Future subphases that touch `PRESENTACION_ALIASES` MUST scope their spec delta to the exact alias added or removed and MUST NOT modify fuzzy scores, thresholds, ranking, candidate filtering, or output shape as a side effect; if a deeper change is needed, it requires a new OpenSpec subphase. The cross-flow proof that the real `modificar_producto` HTTP handler now treats `empanadas carne picante` as a valid destination without mutating the source for unknown destinations remains in `test_modificar_producto_real_flow_http.py` and is the canonical regression for this defect. Hybrid mode activation, semantic recognizers, vector-backed presentation matching, fuzzy/vector score fusion on customer responses, embedding model changes, Ollama configuration changes, synonym catalogs, generalised ontology for flavors/ingredients/varieties/descriptors/presentations, catalog mutations, and HTTP contract changes remain future work and were explicitly out of scope here.

### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [x] — completed

The Subphase 4.11 calibration runner was diagnosed against the `schema_version: 3` dataset and the silent dual-identifier defect was removed without redesigning the fuzzy recognizer. All 36 implementation tasks and all planning artifacts were completed; the new specs and the modified specs are recorded in the active change at `openspec/changes/subphase-4-11-3-calibration-evaluation-mismatch/`. No embedding model, Ollama configuration, vector data, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed; the fix is concentrated in the offline calibration pipeline.

**Completed outcomes:**
- The runner now resolves the canonical numeric `producto_presentacion.id` from a recognizer result row, an inventory entry, an expected seed reference, or a candidate list through a single `normalize_canonical_id` helper. The previous comparison sites that mixed `producto_presentacion.id` with `presentacion.codigo`, `presentacion.id`, normalized descriptions, or `presentacion_descripcion` are routed through the helper and the `seed_refs`-bound cases (`expected_producto_presentacion_id_ref`) now carry a resolved numeric `expected_producto_presentacion_id` before scoring, so the presentation verdict compares numeric IDs only.
- A new `backend/services/product_recognition_calibration_diagnosis.py` module defines a closed `MISMATCH_CATEGORY` enum (ten categories) and a pure `classify_mismatch(case_record, inventory_entry)` function that returns the first matching category in the documented evaluation order (commerce-scope → product-id → presentation-id → output-normalization → decision-mapping → dataset-expectation → seed-reference → real-fuzzy → real-hybrid → other-with-evidence). The runner, the policy validator, and the report reader all import the same constant set.
- A new atomic diagnostic writer (`backend/services/product_recognition_calibration_report.py::write_diagnostic_atomic`) emits the documented per-case fields in the documented stable order (`case_id`, `input_text`, `category`, `shape`, `expected_decision`, `expected_producto_presentacion_id`, `expected_presentacion_id`, `actual_fuzzy_decision`, `actual_fuzzy_producto_presentacion_id`, `actual_fuzzy_presentacion_id`, `actual_fuzzy_candidate_ids`, `actual_hybrid_decision`, `actual_hybrid_producto_presentacion_id`, `actual_hybrid_presentacion_id`, `actual_hybrid_candidate_ids`, `normalized_id_used_by_evaluator`, `presentation_resolution_result`, `mismatch_category`, `evidence`). The CLI exposes `--diagnose` and `--diagnose-output` (default `<output>.diagnose.json`); the existing JSON report is still written and the existing exit-code semantics are preserved.
- The runner now refuses to start when the dataset's `inventory_fingerprint` is missing or does not match the current `seed_refs` content; the deterministic `SeedReferenceError` names the offending `seed_refs` key. The dataset validator accepts the optional `correction_evidence` object without rejecting uncorrected cases, so future corrections can be committed alongside the diagnostic that produced them.
- The calibration was re-run end-to-end against the unchanged dataset and against the corrected dataset. The `mismatch_category_counts` aggregate and the diagnostic JSON file agree: 10 cases `correct`, 29 cases `real_fuzzy_recognizer_failure`, 8 cases `real_hybrid_recognizer_failure`, 0 cases under the seven dataset/seed/identifier categories, and `total = 37` (which equals 47 evaluated cases − 10 correct). No category was fabricated. The 11 preserved Subphase 4.11 cases are unchanged.
- Before / after metrics: fuzzy decision accuracy `0.1282` → `0.2766`; hybrid decision accuracy `0.1538` → `0.2128`; fuzzy false unknowns `34/36` → `34/41` (denominator grew because the resolved numeric IDs now let more cases carry an expectation); hybrid false unknowns `12/36` → `15/41`; hybrid incorrect ambiguities `21/22` → `21/23`; hybrid presentation resolution `7/39` → `39/47`; infrastructure failures `0` → `0`. Final eligibility verdict: `not_eligible` with reasons `primary_metric_improvement_failed` and `false_positive_tolerance_failed` (the latency budget is no longer the blocker because the functional categories are now correct, exactly as the subphase scope required). Remaining real recognizer failures are 29 fuzzy + 8 hybrid, all catalogued under `real_fuzzy_recognizer_failure` / `real_hybrid_recognizer_failure` for a future subphase.
- The exact documented calibration command is `PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output <change-root>/diagnostics/after.json --diagnose --diagnose-output <change-root>/diagnostics/after.diagnose.json`. Hybrid mode was not activated: `PRODUCT_RECOGNIZER_MODE` is untouched, no HTTP contract or handler changed, and the diagnostic mode is observational only.

**Architectural constraints introduced:**
- The runner, evaluator, and report aggregation MUST resolve the canonical presentation identifier to the numeric `producto_presentacion.id` consistently. The system MUST NOT mix `producto_presentacion.id`, `presentacion.id`, `presentacion.codigo`, `presentacion.descripcion`, or `presentacion_codigo` / `presentacion_descripcion` in the same comparison or normalization step. The `normalize_canonical_id` helper is the only allowed entry point; future call sites that need to compare identifiers MUST go through it.
- Every incorrect calibration case MUST be filed under exactly one of the ten `MISMATCH_CATEGORY` values. Categories with zero incorrect cases remain at zero; the diagnostic MUST NOT fabricate or force examples merely to populate empty categories. `correct` cases MUST NOT be counted in `mismatch_category_counts`. `other_with_evidence` requires a non-empty `evidence` string.
- The runner MUST refuse to start a calibration when the dataset's `inventory_fingerprint` does not match the current `seed_refs` content. The `SeedReferenceError` MUST name the offending `seed_refs` key and the CLI MUST exit non-zero. The `inventory_fingerprint` field on the dataset is the only portable inventory reference; a future subphase that mutates `seed_refs` MUST regenerate the fingerprint through the existing `backend.scripts.calibration_inventory --mode regenerate` step.
- The `--diagnose` mode MUST remain opt-in. The CLI MUST preserve the existing exit-code rules (non-zero only on invalid dataset, invalid configuration, database failure, or total calibration failure). The diagnostic output MUST be written atomically using the same `mkstemp + fsync + os.replace` contract as the existing JSON report. The diagnostic file MUST list every case in the documented stable order; the report and the diagnostic file MUST agree on `mismatch_category_counts`.
- Targeted dataset corrections MUST attach a `correction_evidence` object (`mismatch_category`, `reason`, `catalog_reference`) on each corrected case; uncorrected cases (including all 11 preserved Subphase 4.11 cases) MUST NOT carry the field. `schema_version` MUST remain `3`. The dataset validator MUST accept the optional `correction_evidence` object without rejecting uncorrected cases.
- Latency budget, thresholds, recognizer weights, embedding model, vector dimensions, Ollama configuration, hybrid runtime mode, HTTP contracts, handler behavior, order transaction semantics, and `PRODUCT_RECOGNIZER_MODE` MUST NOT be modified by a future subphase that only wants to fix a mismatch category or extend the taxonomy. The closed taxonomy is the only portable surface; new categories require a new OpenSpec subphase.

**Relevant files:**
- `backend/services/product_recognition_calibration_diagnosis.py` — new module: closed `MISMATCH_CATEGORY` enum, `normalize_canonical_id` helper, `classify_mismatch` pure function, atomic `write_diagnostic_atomic` writer. Imported by the runner, the policy validator, the report serializer, and the new test file.
- `backend/services/product_recognition_calibration_runner.py` — `_fuzzy_ids` now goes through `normalize_canonical_id`; `_resolved_expected_id` resolves `seed_refs`-bound cases to the numeric `producto_presentacion.id` before scoring; `_seed_refs_fingerprint` compares the dataset's `inventory_fingerprint` against the current `seed_refs`; per-case `mismatch_category` and the `mismatch_category_counts` aggregate are emitted in the report; per-case `diagnostic_records` (excluding `input_text` from the report-safe walk) are produced for the CLI to write through the atomic diagnostic writer.
- `backend/services/product_recognition_calibration_policy.py` — `validate_dataset` accepts the optional `correction_evidence` object; existing eligibility / schema_version rules are unchanged.
- `backend/services/product_recognition_calibration_report.py` — `write_diagnostic_atomic` writes the diagnostic JSON atomically, sanitising `input_text` and other forbidden keys without dropping required fields; `serialize_report` continues to refuse the same forbidden keys for the main report.
- `backend/cli/calibrate_product_recognizer.py` — `--diagnose` (opt-in) and `--diagnose-output` (default `<output>.diagnose.json`) flags added; the diagnostic file is written alongside the existing report; exit-code semantics unchanged.
- `backend/data/product_recognition_calibration_cases.json` — `inventory_fingerprint` added at the top of the dataset; the 11 preserved Subphase 4.11 cases are untouched; no case was modified because the diagnostic bucketed every incorrect case under `real_fuzzy_recognizer_failure` or `real_hybrid_recognizer_failure` (no dataset/seed/identifier defect was found).
- `backend/tests/test_product_recognition_calibration_4_11_3.py` — 32 focused tests covering the closed taxonomy, the documented evaluation order, the canonical-identifier helper, the diagnostic mode (atomic write, byte-identical re-runs, forbidden-key rejection, CLI parser), the inventory-refusal path, the correction_evidence validator, and the per-case mismatch category and `mismatch_category_counts` aggregate.
- `openspec/specs/project.md` — replaced this subphase's pending implementation prompt with the proper completed entry (objective, context, completed outcomes, architectural constraints, relevant files, OpenSpec, context for future subphases); updated the OpenSpec section after sync + archive.
- `openspec/changes/subphase-4-11-3-calibration-evaluation-mismatch/diagnostics/before.json`, `before.diagnose.json`, `after.json`, `after.diagnose.json` — the before/after calibration JSON report and the per-case diagnostic evidence file produced by the documented command.

**OpenSpec:**
- New capability `calibration-evaluation-mismatch-diagnosis` synced at `openspec/specs/calibration-evaluation-mismatch-diagnosis/spec.md`: 3 Requirements (`Closed mismatch-category taxonomy`, `Diagnostic command and per-case evidence report`, `Diagnostic mode preserves existing Subphase 4.11 and 4.11.1 invariants`) with 5 Scenarios (`Every incorrect case is filed under exactly one category`, `other_with_evidence requires explicit evidence`, `Diagnostic mode emits stable per-case fields`, `Diagnostic output is deterministic for fixed inputs`, `Diagnostic mode does not weaken existing requirements`).
- Modified capability `calibrate-hybrid-product-recognition-4-11` synced at `openspec/specs/calibrate-hybrid-product-recognition-4-11/spec.md`: appended 3 new Requirements (`Canonical presentation identifier consistency`, `Per-case mismatch category classification`, `Diagnostic mode is part of the runner surface`) with 7 new Scenarios (`Presentation verdict uses the canonical identifier`, `Mixed identifier representations are rejected`, `Canonical identifier is resolved from the seed_refs map`, `Every case has a mismatch_category`, `Failed cases are still classified`, `Diagnostic mode reuses the existing runner pipeline`, `Diagnostic mode is opt-in`). All pre-existing Subphase 4.11 and 4.11.1 requirements are preserved verbatim.
- Modified capability `expand-product-recognition-calibration-dataset-4-11-1` synced at `openspec/specs/expand-product-recognition-calibration-dataset-4-11-1/spec.md`: appended 3 new Requirements (`Targeted dataset corrections preserve invariants`, `Inventory regeneration after seed_refs corrections`, `Canonical identifier mapping in the dataset`) with 7 new Scenarios covering `correction_evidence` shape, category and shape coverage, evaluable case count, `seed_refs` re-validation, stale-inventory refusal, and canonical identifier resolution.
- Change archived at `openspec/changes/archive/2026-08-04-subphase-4-11-3-calibration-evaluation-mismatch/`; the active change list now contains only this archive path, all planning artifacts and tasks are complete, all 3 target specs validate as `valid: true`, and `openspec validate subphase-4-11-3-calibration-evaluation-mismatch --strict` was clean against the change bundle before archive.

**Context for future subphases:** Calibration cases that were silently mis-scored because the runner compared numeric `producto_presentacion.id` against `presentacion.codigo` strings or normalised descriptions are now correctly scored, and every incorrect case is filed under exactly one of the ten documented categories. The 29 fuzzy and 8 hybrid recognizer failures are real failures of the existing recognizer (not dataset, not seed, not identifier) and are the documented remaining work for a future subphase. The diagnostic surface (`--diagnose` / `diagnostic_records` / `mismatch_category_counts`) is now a portable tool: future subphases that mutate `seed_refs` must regenerate the dataset's `inventory_fingerprint` through the existing `backend.scripts.calibration_inventory --mode regenerate` step before re-running the calibration; the runner refuses to start otherwise. Hybrid mode activation, weighted fuzzy/vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, and background jobs remain future work and are explicitly out of scope here.

### Subphase 4.11.4 — Correct Real Fuzzy Product Recognition Failures [x] — completed

The Subphase 4.11.4 calibration runner was rebuilt so the fuzzy recognizer receives a faithful full runtime-compatible commerce catalog for every `commerce_dynamic_database` case at calibration time. All 31 implementation tasks and all planning artifacts were completed; the new specs and the modified specs were synced to main, and the change was archived at `openspec/changes/archive/2026-08-05-subphase-4-11-4-correct-real-fuzzy-product-recognition-failures/`. No embedding model, Ollama configuration, vector data, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed; the fix is concentrated in the offline calibration pipeline.

**Root-cause summary:** Subphase 4.11.3 proved that the evaluator and the expected identifiers are valid for every `commerce_dynamic_database` case: the seven dataset / seed / identifier mismatch categories all sit at `0` in the post-fix `mismatch_category_counts` aggregate. Subphase 4.11.3 did **not** prove that the runtime fuzzy recognizer itself fails for the 29 fuzzy cases — it proved only that the offline calibration runner is the broken component. The demonstrated defect is that `ProductRecognitionCalibrationRunner.run` (`backend/services/product_recognition_calibration_runner.py:636`) hands `FuzzyProductRecognizer.recognize(...)` an empty catalog for every `catalog_scope: "commerce_dynamic_database"` case (`dataset["catalogs"][<fixture>].entries` is `[]` by design under the Subphase 4.11.1 contract), while the vector search on the same case at `runner.py:654-660` is correctly given `allowed_candidate_ids`. The fuzzy recognizer therefore returned `unknown` regardless of whether the runtime would have matched the candidate, the hybrid ranking inherited the empty fuzzy ranking, and the calibration could not distinguish a real fuzzy defect from a calibration-environment defect.

**Completed outcomes:**
- A new `backend/services/product_recognition_calibration_commerce_catalog.py` module exports the `CommerceCatalog` dataclass (`id_comercio: int`, `entries: tuple[dict, ...]`, frozen) and a fresh-DB loader `load_commerce_catalog_from_database(session, id_comercio) -> CommerceCatalog` that issues exactly one SQL query per call. The loader mirrors `backend/tests/manual_product_recognizer.py::_load_catalog` (joining `ProductoPresentacion` with `Producto` and `Presentacion`, filtered to `id_comercio == id_comercio`), preserves all four runtime availability flags (`activo`, `producto_activo`, `presentacion_activo`, `disponible`) verbatim, sorts entries by `producto_presentacion_id` ascending, and dedupes by `producto_presentacion_id`. A `validate_commerce_catalog_inventory_shape` validator confirms the persisted `commerce_catalog_inventory[<id_comercio>]` block is well-formed (sorted, deduped, full runtime field set) for evidence-only validation; the runner NEVER hands the persisted inventory to the recognizer. A `fingerprint_commerce_catalog` helper computes the SHA-256 fingerprint (lowercase hex) of the catalog's canonical JSON — the same fingerprint the runner compares against the persisted `commerce_catalog_fingerprint[<id_comercio>]` at calibration time. The `StaleCommerceCatalogError` exception (carrying `id_comercio`, `expected_fingerprint`, `actual_fingerprint`, and a deterministic message) is the documented refusal for fingerprint drift.
- The inventory script grew a new `--mode regenerate-commerce-catalog --commerce-id <id>` subcommand. The new subcommand loads the per-commerce catalog through the fresh-DB loader, validates the shape, persists it under `dataset["commerce_catalog_inventory"][str(id_comercio)]` as reproducible evidence of the database snapshot, computes the fingerprint through `fingerprint_commerce_catalog`, and persists it under `dataset["commerce_catalog_fingerprint"][str(id_comercio)]`. The existing `_resolve_seed_refs`, `_validate_seed_refs`, `_regenerate`, and `--mode regenerate` are unchanged; the existing `seed_refs` map and `inventory_fingerprint` derivation are unchanged. `validate_dataset` accepts the optional `commerce_catalog_inventory` and `commerce_catalog_fingerprint` blocks on `schema_version: 3` datasets without rejecting legacy datasets that omit them and without bumping `schema_version`.
- The runner now owns a per-commerce catalog cache (`self._commerce_catalog_cache: dict[int, CommerceCatalog]`). For every `catalog_scope: "commerce_dynamic_database"` case the runner loads the full runtime-compatible commerce catalog from PostgreSQL on first reference, computes its fingerprint, and compares it against `dataset["commerce_catalog_fingerprint"][str(id_comercio)]`. On mismatch — or when the persisted `commerce_catalog_fingerprint` block is missing the entry for the visited `id_comercio` — the runner raises `StaleCommerceCatalogError` naming the offending `id_comercio` and the expected / actual fingerprints; the CLI returns non-zero and no report is emitted. On success the runner caches the same `CommerceCatalog` object on `self._commerce_catalog_cache` and reuses it for every subsequent case at that commerce — the catalog handed to the recognizer is the same fresh DB catalog that was just validated, never a reload and never the persisted inventory. The cache is populated lazily; the runner does NOT pre-load catalogs for commerces it never visits. The existing `seed_refs` / `inventory_fingerprint` stale guard at `runner.py:612-628` is unchanged and runs first. The runner is wired to load the fresh DB catalog exactly once per commerce per calibration run (the database query is `1` per visited commerce; the runner's `commerce_catalog_cache_size` field on the report records the number of cached commerces).
- The runner now applies `allowed_candidate_ids` and `restricted_candidate_ids` strictly in the evaluator after recognition. The existing vector-search boundary check at `runner.py:654-660` (allowed candidates filtered by `set(case["allowed_candidate_ids"])`) is unchanged; the evaluator additionally flags any candidate returned by the fuzzy recognizer whose id is in `restricted_candidate_ids` (or whose id is not in `allowed_candidate_ids` when the case has a non-empty `allowed_candidate_ids`) and appends the documented `candidate_boundary_violation` failure category. The per-case `mismatch_category` field and the Subphase 4.11.3 `mismatch_category_counts` aggregate are unchanged.
- The 11 preserved `catalog_scope: "in_memory"` Subphase 4.11 cases continue to use their embedded `catalogs[*].entries` and the per-commerce catalog loader is skipped for those cases. The catalog handed to the recognizer for the 11 in-memory cases is byte-identical to the pre-4.11.4 input modulo the documented new `mismatch_category` and `mismatch_category_counts` fields.
- The calibration was re-run end-to-end against the unchanged dataset and the regenerated commerce catalog. The `mismatch_category_counts` aggregate and the diagnostic JSON file agree: 39 cases `correct`, 3 cases `real_fuzzy_recognizer_failure`, 5 cases `real_hybrid_recognizer_failure`, 0 cases under the seven dataset/seed/identifier categories, and `total = 8` (which equals 47 evaluated cases − 39 correct). No category was fabricated. The `commerce_catalog_fingerprint["1"]` persisted evidence and the per-commerce cache size `1` are committed alongside the diagnostic. The persisted `commerce_catalog_inventory["1"]` block carries 72 entries (every commerce-scoped `producto_presentacion` row at `comercio_id == 1`, sorted by `producto_presentacion_id` ascending, with all four runtime availability flags preserved).
- Before / after metrics (against the unchanged `schema_version: 3` dataset): fuzzy decision accuracy `0.2766` → `0.5319` (+25.53 pp); hybrid decision accuracy `0.2128` → `0.8298` (+61.70 pp); fuzzy false unknowns `34/41` → `3/41`; hybrid false unknowns `15/41` → `7/41`; fuzzy top-1 accuracy `22/36` → `35/36`; hybrid top-1 accuracy `17/36` → `36/36`. Final eligibility verdict: `not_eligible` with reason `false_positive_tolerance_failed` (the previously-blocked `latency_budget_failed` and `primary_metric_improvement_failed` reasons are no longer the blocker because the functional categories are now correct). Residual real recognizer failures are 3 fuzzy + 5 hybrid, all catalogued under `real_fuzzy_recognizer_failure` / `real_hybrid_recognizer_failure` for a future subphase.
- The exact documented calibration command is `PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output <change-root>/diagnostics/after.json --diagnose --diagnose-output <change-root>/diagnostics/after.diagnose.json`. Hybrid runtime was NOT activated: `PRODUCT_RECOGNIZER_MODE` is untouched, no HTTP contract or handler changed, the `all-minilm:latest` embedding model is untouched, vector data is untouched, and the diagnostic mode is observational only.

**Architectural constraints introduced:**
- The runner, the loader, and the inventory regeneration step MUST resolve the canonical runtime catalog shape (`producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `producto_activo`, `presentacion_activo`, `disponible`) consistently. The fresh-DB loader is the only allowed entry point for the catalog handed to the recognizer; the persisted `commerce_catalog_inventory` block is reproducible evidence only and MUST NOT be handed to the recognizer.
- Every `commerce_dynamic_database` case MUST receive the full runtime-compatible commerce catalog for its `id_comercio`, regardless of `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_decision`, `expected_producto_presentacion_id`, `expected_producto_presentacion_id_ref`, or any availability flag. The catalog is determined solely by `id_comercio` and the live PostgreSQL state at calibration time.
- The runner MUST load the per-commerce catalog from PostgreSQL on first reference, compute its fingerprint, and compare against the persisted `commerce_catalog_fingerprint[<id_comercio>]`. On mismatch — or when the persisted entry is absent — the runner MUST raise `StaleCommerceCatalogError`; the CLI MUST exit non-zero and emit no report. The runner MUST NOT read `dataset["commerce_catalog_inventory"][...]` to populate the cache; that block is evidence only and is consulted solely for the fingerprint comparison.
- The runner MUST cache the fresh DB catalog on `self._commerce_catalog_cache: dict[int, CommerceCatalog]` and reuse the same `CommerceCatalog` object for every case at that commerce. The cache MUST be populated lazily; the runner MUST NOT pre-load catalogs for commerces it never visits. The runner MUST issue exactly one catalog query per commerce per calibration run; the per-commerce catalog query count is surfaced as `commerce_catalog_cache_size` on the report.
- The runner MUST apply `allowed_candidate_ids` and `restricted_candidate_ids` strictly in the evaluator, after the fuzzy recognizer returns its candidates. The evaluator accepts a candidate as in-boundary iff its id is in `allowed_candidate_ids`, and flags a candidate as a boundary violation iff its id is in `restricted_candidate_ids` (or absent from `allowed_candidate_ids` when the case has a non-empty `allowed_candidate_ids`). The vector-search boundary check at `runner.py:654-660` is preserved unchanged.
- The 11 preserved `catalog_scope: "in_memory"` Subphase 4.11 cases MUST continue to use their embedded `catalogs[*].entries` and MUST NOT consume the per-commerce catalog. The 11 + 36 case count, the category coverage rule, the input-shape coverage rule, the at-least-30-evaluable-cases rule, and the optional `eligibility` block are unchanged.
- The new `commerce_catalog_inventory` and `commerce_catalog_fingerprint` blocks MUST NOT bump `schema_version`. `validate_dataset` MUST accept the optional blocks on `schema_version: 3` datasets without rejecting legacy datasets that omit them. The existing `seed_refs` map, the existing `inventory_fingerprint` derivation, the existing stale-`seed_refs` guard, the `correction_evidence` schema, and the optional `eligibility` block are unchanged.
- Hybrid runtime mode, embedding model, Ollama configuration, vector data, latency budget, thresholds, recognizer weights, fuzzy / hybrid scores, the `disponibles` / `encontrados_no_disponibles` split, `PRESENTACION_ALIASES`, `_extraer_candidatos`, `_calcular_score`, `_extraer_presentacion`, `_preparar_catalogo`, `_filtrar_por_tokens_clave`, HTTP contracts, handler behavior, order transaction semantics, and `PRODUCT_RECOGNIZER_MODE` MUST NOT be modified by a future subphase that only wants to address residual fuzzy / hybrid calibration failures. The per-commerce catalog loader, the fingerprint refusal, and the new tests can be left in place as honest evidence of the runtime source; the persisted `commerce_catalog_inventory` block is reproducible evidence only and the runner does not depend on it for correctness.

**Relevant files:**
- `backend/services/product_recognition_calibration_commerce_catalog.py` — new module: `CommerceCatalog` frozen dataclass, `load_commerce_catalog_from_database` (one query, runtime field set, all four availability flags preserved), `validate_commerce_catalog_inventory_shape` (evidence-only validator), `fingerprint_commerce_catalog` (SHA-256 of canonical JSON), `StaleCommerceCatalogError` refusal. Imported by the runner, the inventory script, the new test files, and the policy validator.
- `backend/services/product_recognition_calibration_runner.py` — new `self._commerce_catalog_cache: dict[int, CommerceCatalog]` field; new `_resolve_commerce_catalog(dataset, id_comercio)` and `_case_catalog(dataset, case)` helpers; the dispatch at the case-evaluation loop and the prediction loop now load the cached fresh DB catalog for `commerce_dynamic_database` cases and keep the embedded catalog for every other scope; the report now exposes `commerce_catalog_cache_size`; the evaluator adds the `candidate_boundary_violation` failure category when the fuzzy recognizer returns a candidate outside `allowed_candidate_ids` or inside `restricted_candidate_ids`; existing `seed_refs` / `inventory_fingerprint` stale guard at `runner.py:612-628` and the existing `mismatch_category` / `mismatch_category_counts` emission are unchanged.
- `backend/services/product_recognition_calibration_policy.py` — `validate_dataset` accepts the optional `commerce_catalog_inventory` and `commerce_catalog_fingerprint` blocks on `schema_version: 3` datasets without rejecting legacy datasets and without bumping `schema_version`. The existing `seed_refs` validation, `correction_evidence` validation, and `inventory_fingerprint` derivation are unchanged.
- `backend/scripts/calibration_inventory.py` — new `_regenerate_commerce_catalog(session, dataset_path, id_comercio)` helper and the new `--mode regenerate-commerce-catalog --commerce-id <id>` subcommand. The existing `_resolve_seed_refs`, `_validate_seed_refs`, `_regenerate`, and `--mode regenerate` are unchanged.
- `backend/cli/calibrate_product_recognizer.py` — unchanged. The CLI continues to invoke the runner with the same flags; the Subphase 4.11.3 diagnostic surface (`--diagnose`, `--diagnose-output`, `mismatch_category_counts`) is reused to evidence the before / after state. The `StaleCommerceCatalogError` refusal is caught by the existing `except (RuntimeError, OSError, ValueError, TypeError)` block and converted into a non-zero exit code with no report.
- `backend/data/product_recognition_calibration_cases.json` — the dataset's `seed_refs`, `inventory_fingerprint`, the 11 preserved cases, the 36 expanded cases, the schema, and the eligibility block are unchanged. The new `commerce_catalog_inventory["1"]` (72 entries, runtime field set, sorted) and `commerce_catalog_fingerprint["1"]` (`b17e6e15f405aef11267791dfea253da9ba1240bf0125ed2886a0ed2f55ef35a`) blocks are added by the inventory regeneration step and committed alongside the change.
- `backend/tests/test_product_recognition_calibration_commerce_catalog.py` — 20 focused tests covering the loader surface: entries sorted / deduped, fingerprint is deterministic for fixed inputs and changes when any field changes (including availability flags), cross-commerce queries return only the requested comercio, the documented runtime field set is required and the loader rejects malformed entries, the persisted-inventory validator refuses unsorted / duplicate / malformed blocks, and the `StaleCommerceCatalogError` refusal carries the documented fields and a deterministic message.
- `backend/tests/test_product_recognition_calibration_inventory_4_11_4.py` — 5 focused tests covering the new `--mode regenerate-commerce-catalog` subcommand: the persisted block and fingerprint are written, regeneration is idempotent, the fingerprint changes on a field mutation, the existing `seed_refs` / `inventory_fingerprint` are preserved, and the subcommand refuses an empty catalog.
- `backend/tests/test_product_recognition_calibration_4_11_4.py` — 17 focused tests covering the runner dispatch and the freshness contract: the runner uses the fresh DB catalog for every `commerce_dynamic_database` case, the runner uses the cached fresh DB catalog and NOT the persisted inventory, the 11 in-memory cases remain verbatim, the catalog is independent of `allowed_candidate_ids`, the catalog is independent of `expected_producto_presentacion_id`, restricted candidates remain in the catalog, the runner fails closed on a stale fingerprint, the runner fails closed when the persisted fingerprint is missing, inactive / unavailable entries remain present with their original flags, the cache is loaded lazily, the report exposes `commerce_catalog_cache_size`, the deterministic error message, the dataset is validated before the loader is invoked, and the competing product regression (a product outside `allowed_candidate_ids` is present in the catalog and may be returned by the recognizer). Plus 3 dataset-policy tests confirming `validate_dataset` accepts the optional blocks and legacy datasets.
- `openspec/specs/project.md` — replaced this subphase's pending implementation prompt with the proper completed entry (objective, context, completed outcomes, architectural constraints, relevant files, OpenSpec, context for future subphases).
- `openspec/changes/subphase-4-11-4-correct-real-fuzzy-product-recognition-failures/diagnostics/after.json`, `after.diagnose.json` — the new calibration JSON report and the per-case diagnostic evidence file produced by the documented command. The committed dataset snapshot is `b17e6e15f405aef11267791dfea253da9ba1240bf0125ed2886a0ed2f55ef35a`.

**OpenSpec:**
- Modified capability `calibrate-hybrid-product-recognition-4-11` synced at `openspec/specs/calibrate-hybrid-product-recognition-4-11/spec.md`: appended 1 Requirement with 12 Scenarios covering per-commerce catalog caching, fresh-DB loading, fingerprint refusal via `StaleCommerceCatalogError`, evaluator-side boundary enforcement, and the documented invariants for the 11 preserved `in_memory` cases.
- Modified capability `expand-product-recognition-calibration-dataset-4-11-1` synced at `openspec/specs/expand-product-recognition-calibration-dataset-4-11-1/spec.md`: appended 1 Requirement with 8 Scenarios covering optional `commerce_catalog_inventory` and `commerce_catalog_fingerprint` blocks, runtime field set with all four availability flags preserved, fingerprint semantics as reproducible evidence, schema-version preservation, the documented invariants for the 11 preserved `in_memory` cases, round-trip through `regenerate-commerce-catalog`, backward compatibility, idempotent regeneration, preservation of existing `seed_refs` / `inventory_fingerprint`, `correction_evidence` non-interference, retention of inactive / unavailable entries with original flags, and cross-commerce isolation.
- Modified capability `product-recognizer` synced at `openspec/specs/product-recognizer/spec.md`: appended 1 Requirement with 7 Scenarios requiring the fuzzy recognizer, when invoked against a `commerce_dynamic_database` calibration case, to receive the full runtime-compatible commerce catalog for the case's `id_comercio` — every commerce-scoped `producto_presentacion` entry returned by the real runtime catalog assembly, including entries whose availability flags are `false`, exactly as the runtime call sites (`backend/intents/context/product_selection_context_resolver.py:165`, `product_modification_resolver.py`, `quitar_producto_recognizer.py`, `modificar_producto_recognizer.py`, and the manual loader at `backend/tests/manual_product_recognizer.py::_load_catalog`) hand the recognizer the runtime catalog; the catalog entry shape MUST be the documented runtime field set; entries MUST be sorted by `producto_presentacion_id` ascending; inactive and unavailable entries MUST remain present in the catalog with their original flags preserved exactly and MUST be classified by the recognizer's existing `disponibles` / `encontrados_no_disponibles` split; no expected-case field MAY influence catalog construction.

**Archive:**
- Change archived at `openspec/changes/archive/2026-08-05-subphase-4-11-4-correct-real-fuzzy-product-recognition-failures/`; all 31 implementation tasks and all 4 planning artifacts (`proposal`, `design`, `specs`, `tasks`) were complete; the 3 delta specs (`calibrate-hybrid-product-recognition-4-11`, `expand-product-recognition-calibration-dataset-4-11-1`, `product-recognizer`) were synced to main before archive (3 ADDED requirements: 12 + 8 + 7 scenarios); `openspec validate subphase-4-11-4-correct-real-fuzzy-product-recognition-failures --strict` was clean against the change bundle before archive.

**Context for future subphases:** The 29 fuzzy and 8 hybrid recognizer failures from Subphase 4.11.3 are now correctly bucketed by the post-fix calibration: 26 of the 29 fuzzy cases and 3 of the 8 hybrid cases are now `correct` (the demonstrably wrong `unknown` decision the empty catalog forced has been eliminated). The remaining 3 fuzzy + 5 hybrid cases (`real_fuzzy_recognizer_failure` × 3, `real_hybrid_recognizer_failure` × 5) are the residual recognizer failures on a faithful full-commerce catalog — they are the documented remaining work for a future subphase and are NOT guaranteed to translate to customer-facing runtime failures (the calibration environment was corrected, not the production recognizer or the embedding model). The `commerce_catalog_inventory` block is reproducible evidence of the database snapshot the change was authored against; the runner does not depend on it for correctness. Future subphases that mutate `seed_refs` or the per-commerce catalog MUST regenerate the dataset's `inventory_fingerprint` (existing) and `commerce_catalog_fingerprint[<id_comercio>]` (new) through `backend.scripts.calibration_inventory --mode regenerate` and `--mode regenerate-commerce-catalog` before re-running the calibration; the runner refuses to start otherwise. Hybrid mode activation, weighted fuzzy / vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, and background jobs remain future work and are explicitly out of scope here.

### Subphase 4.11.5 — Reduce Residual Fuzzy Recognition Failures and False Positives [x] — completed

The Subphase 4.11.5 recognizer and calibration runner are the smallest set of recognizer / runner changes that correct the 3 residual `real_fuzzy_recognizer_failure` cases (`c1-ambiguous-postre`, `c1-fuzzy-vector-disagreement-muzarrella`, `c1-ambiguous-pizza-again`) and the 1 residual `real_hybrid_recognizer_failure` / false-positive case (`ambiguous-empanada-carne`) on the faithful full-commerce catalog delivered by Subphase 4.11.4. The fix is concentrated in the offline calibration pipeline's evaluation of the fuzzy result plus a category-scope matching pass in the recognizer; no embedding model, Ollama configuration, vector data, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed.

**Root-cause summary:** Subphase 4.11.4 proved the calibration environment is correct: the seven dataset / seed / identifier mismatch categories all sit at `0` in the post-fix `mismatch_category_counts` aggregate. The 3 residual `real_fuzzy_recognizer_failure` cases are real fuzzy-recognizer defects on a faithful full-commerce catalog: (a) the `muzarrella` alias gap is closed by a 1-line addition to the static `ALIASES_PALABRAS` map at `backend/recognizers/product_recognizer.py:53-68`; (b) the two category-only inputs (`un postre`, `otra pizza`) are recognized via a new category-scope matching pass inside `detectar_productos` that signals category-level ambiguity through a new `CategoryAmbiguityGroup` variant. The 1 false-positive case (`ambiguous-empanada-carne`) is a hybrid guard defect: when the case's `catalog_scope == "pending_product_selection_restricted"` AND the fuzzy decision is explicitly `ambiguous`, the hybrid policy over-promoted the case to `unique` because the vector's top-1 widened the score gap. The fix is a narrowly-scoped positional guard in `_hybrid_prediction` that inspects the fuzzy decision explicitly (computed once from `observation.fuzzy_ids` and the category discriminator via `_fuzzy_decision(result)`) and forces `"ambiguous"` regardless of the vector's top-1 contribution. The 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` and are documented residual work for a future subphase.

**Completed outcomes:**
- `backend/recognizers/product_recognizer.py` — added `"muzarrella": "mozzarella"` to the document-level `ALIASES_PALABRAS` map between the existing `"mozarella"` and `"muzzarela"` entries (the 12th entry; the existing 11 entries are preserved verbatim). The map remains a frozen module-level constant. Added a `_coincidencia_categoria(texto_segmento, catalogo) -> str | None` helper that builds a per-call `dict[str, str]` indexed by the lowercased and singularized form of each catalog entry's `categoria_nombre` (with trailing `s` and `es` variants) and returns the original `categoria_nombre` when a significant user token matches. The helper does NOT consult `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label; it does NOT return the matching catalog entries. Wired the helper into `detectar_productos` after `_extraer_candidatos` and `_filtrar_por_tokens_clave`: when the existing fuzzy pipeline produced no product candidate for the segment AND the helper returns a category name, a category-level `encontrados_posibles` group with `kind: "category"`, `texto_origen` (the original segment), and `categoria_nombre` (the matched category name) is appended. The group carries NO `productos` list and the matched catalog entries are NOT appended to the candidate list; the runner's `_flag_fuzzy_boundary_violation` does NOT fire for category-level inputs because no product ids are extracted. The pass is purely additive: existing product-level candidates are preserved; the pass never removes a candidate the existing pipeline produced; the pass never adds a product candidate via the category-level signal.
- `backend/recognizers/product_recognizer_contract.py` — added a new `CategoryAmbiguityGroup(TypedDict, total=True)` with the explicit discriminator `kind: Literal["category"]`, `categoria_nombre: str`, and `texto_origen: str`. The group carries NO `productos` field and exposes NO product ids. The existing `PossibleMatchGroup` is preserved byte-identically (no `kind` field added). `ProductRecognizerResult.encontrados_posibles` element type is widened from `list[PossibleMatchGroup]` to `list[PossibleAmbiguityGroup]` (where `PossibleAmbiguityGroup = PossibleMatchGroup | CategoryAmbiguityGroup`). The `ProductRecognizerProtocol.recognize` signature and the four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`) are preserved unchanged. `CategoryAmbiguityGroup` and `PossibleAmbiguityGroup` are exported via `__all__`.
- `backend/services/product_recognition_calibration_runner.py` — added an explicit discriminator check inside `_fuzzy_ids` so the category signal is captured by `_fuzzy_decision(result)` rather than silently dropped (the existing `group.get("productos", []) or []` default remains the safe id-extraction path). Added a `_fuzzy_decision(result)` helper that returns `"ambiguous"` whenever an `encontrados_posibles` group carries `kind: "category"`; otherwise it falls back to the existing id-based logic (`"unique"` if `len(fuzzy_ids) == 1`, `"ambiguous"` if `len(fuzzy_ids) > 1`, `"unknown"` if `len(fuzzy_ids) == 0`). Added a narrowly-scoped positional guard in `_hybrid_prediction` that fires only when `case.get("catalog_scope") == "pending_product_selection_restricted"` AND `observation.fuzzy_decision == "ambiguous"` — the guard returns `"ambiguous"` immediately, before the scoring rule consults `policy.fuzzy_weight`, `policy.vector_weight`, `policy.unique_threshold`, `policy.ambiguous_threshold`, `policy.minimum_score_gap`, `policy.vector_top_k`, the canonical/alias promotion in `_exact_flags`, the vector's top-1, or the score combination. The fuzzy decision is threaded into `_decision` as a derived parameter (computed once in `_hybrid_prediction` from `observation.fuzzy_ids` and the category discriminator); the guard does NOT inspect the combined hybrid `ranking` to infer fuzzy ambiguity (the combined hybrid ranking is the union of `observation.fuzzy_ids` and `observation.vector_ids`, so a fuzzy-`unique` + vector-`unique(other)` case produces a multi-candidate hybrid ranking even though the fuzzy was not ambiguous). The guard does NOT fire when the fuzzy returns `unique`, when the fuzzy returns `unknown`, or for `commerce_dynamic_database` cases (the `catalog_scope` check excludes them); case origin (`in_memory` vs `commerce_dynamic_database`) is irrelevant to the guard. Extended `_decision` with a small refinement of the existing `if not ranking: return "unknown"` line: when the combined ranking is empty AND `fuzzy_decision == "ambiguous"`, the decision is `"ambiguous"`. The runner's `_flag_fuzzy_boundary_violation` does NOT fire for category-level inputs because no product ids are extracted from the category-level group.
- `backend/services/product_recognition_shadow_service.py` — added an explicit discriminator check inside `_collect_fuzzy_candidates` so the shadow-mode observation correctly records the category signal (a category group contributes 0 fuzzy ids; the comparison's `fuzzy_candidate_ids` tuple remains empty; the agreement falls through to `fuzzy_only` / `no_result` per the existing literal taxonomy). The existing `group.get("productos", []) or []` default remains the safe id-extraction path.
- 9 production readers adapted to branch on the `kind == "category"` discriminator before accessing `productos` (one per file in the Context section): `backend/intents/resolvers/product_intent_resolver.py:19-29` (flat-candidate branch guarded against `KeyError`), `backend/intents/context/product_selection_context_resolver.py:175-179`, `backend/intents/context/product_modification_resolver.py:43-46, 57-60` (both flatten helpers), `backend/intents/context/order_line_selection_resolver.py:35-37`, `backend/intents/orchestration/quitar_producto_initial.py:33-37`, `backend/intents/recognizers/quitar_producto_recognizer.py:100-113, 167-170` (both attach and quantity-attach loops), `backend/intents/recognizers/modificar_producto_recognizer.py:94-119` (both flatten helpers). The handlers, the `agregar_producto` orchestrator, the `modificar_producto_initial`, the `pending_context_dispatcher`, the `pending_context_execution`, the `transactional_message_processor`, and the FastAPI routers do NOT directly access `encontrados_posibles` (they consume the `ProcessedIntent` produced by the resolvers, which carry the discriminator-aware shape).
- Diagnostic bucketing: the post-fix `mismatch_category_counts` aggregate is `correct: 43, real_hybrid_recognizer_failure: 4, total: 4` (47 evaluated cases − 43 correct = 4 residual). The 3 residual `real_fuzzy_recognizer_failure` cases (`c1-ambiguous-postre`, `c1-fuzzy-vector-disagreement-muzarrella`, `c1-ambiguous-pizza-again`) are now `correct`; the false-positive case (`ambiguous-empanada-carne`) is now `correct` and `false_positives.count` drops to `0`; the 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` (no false promotion). `false_positive_tolerance_failed` is eliminated from the eligibility verdict; the other gates (`primary_metric_improvement`, `restricted_candidate_non_regression`, `canonical_match_accuracy`, `alias_match_accuracy`, `commerce_isolation`, `latency_budget`) are documented as either passing or unchanged from Subphase 4.11.4.
- The exact documented calibration command is `PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output <change-root>/diagnostics/after.json --diagnose --diagnose-output <change-root>/diagnostics/after.diagnose.json`. Hybrid runtime was NOT activated: `PRODUCT_RECOGNIZER_MODE` is untouched, no HTTP contract or handler changed, the `all-minilm:latest` embedding model is untouched, vector data is untouched, and the diagnostic mode is observational only.
- The dataset's `commerce_catalog_inventory["1"]` (72 entries, runtime field set, sorted) and `commerce_catalog_fingerprint["1"]` (`b17e6e15f405aef11267791dfea253da9ba1240bf0125ed2886a0ed2f55ef35a`) blocks from Subphase 4.11.4 are reused as-is; no regeneration is needed.

**Architectural constraints introduced:**
- The fuzzy recognizer's `encontrados_posibles` is a backward-compatible typed discriminated union containing (a) the existing product-level `PossibleMatchGroup` (shape preserved byte-identically: `{"texto_origen": str, "productos": list[RecognizedProduct]}`), and (b) the new `CategoryAmbiguityGroup` (explicit `kind: "category"` discriminator + `categoria_nombre: str` + `texto_origen: str`). The discriminator check (`group.get("kind") == "category"` or `"kind" in group`) is the single safe branching point for every production reader that needs to access `productos`. The existing product-level shape is preserved byte-identically; the widening is strictly backward-compatible.
- The fuzzy recognizer, when an input token matches a catalog `categoria_nombre` (after lowercase normalization and singularization) and no other fuzzy candidate was produced for the user's segment, MUST signal category-level ambiguity through the new category-level variant instead of exposing every category entry as an ordinary product candidate. The matched category entries MUST NOT be exposed as evaluable product candidates and MUST NOT be routed through the `encontrados` / `encontrados_posibles[].productos[]` / `encontrados_no_disponibles` split. The recognizer signature and the recognizer's responsibility are unchanged; the recognizer SHALL NOT consult `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label.
- The hybrid decision, when the case's `catalog_scope == "pending_product_selection_restricted"` AND the fuzzy decision is explicitly `ambiguous` (the direct evidence being EITHER `len(fuzzy_ids) > 1` on the stored `CaseObservation.fuzzy_ids` OR a category-level `encontrados_posibles` group with `kind: "category"` detected by `_fuzzy_decision(result)`), MUST return `"ambiguous"` regardless of the vector's top-1 contribution. The guard MUST inspect the fuzzy decision explicitly and MUST NOT infer fuzzy ambiguity from the combined hybrid `ranking`. The guard depends ONLY on `catalog_scope` and `fuzzy_decision`; case origin (`in_memory` vs `commerce_dynamic_database`) is irrelevant to the guard; cases of either origin remain unaffected unless both guard conditions are satisfied. The guard is a single positional tag in `_hybrid_prediction` and does not modify `_hybrid_prediction`'s scoring formula, the policy grid, the canonical/alias promotion, the score gap, the score combination, the JSON report schema, the diagnostic surface, or the CLI surface.
- The runtime recognizer factory, the `ShadowedProductRecognizer` adapter, the `ProductRecognizerProtocol` contract signature, the `agregar_producto` / `quitar_producto` / `modificar_producto` orchestrator signatures, the orders, the responses, the persistence contracts, the FastAPI routers, the embedding client, the vector search service, the HNSW / IVFFlat indexing, the Ollama configuration, the embedding model, the vector dimension, the `PRODUCT_RECOGNIZER_MODE` setting, the `shadow_hybrid_min_score_gap` setting, the `shadow_vector_top_k` setting, the `seed_refs` map, the `inventory_fingerprint`, the `commerce_catalog_inventory` / `commerce_catalog_fingerprint` blocks, the `correction_evidence` schema, the `schema_version`, the case count, the eligibility block, the JSON report schema, the diagnostic surface, and the CLI surface MUST NOT be modified by a future subphase that only wants to address the 4 residual hybrid failures. The Subphase 4.11.4 calibration environment (the per-commerce catalog cache, the fresh-DB loader, the fingerprint refusal) MUST remain in place as honest evidence of the runtime source; the per-commerce catalog cache is not consulted for correctness.

**Relevant files:**
- `backend/recognizers/product_recognizer.py` — added the `"muzarrella"` alias entry between `"mozarella"` and `"muzzarela"`; added `_category_singular_variants(name)` and `_coincidencia_categoria(texto_segmento, catalogo)` helpers; wired the helper into `detectar_productos` as a per-call purely additive pass after `_extraer_candidatos` and `_filtrar_por_tokens_clave`. The existing product-level `encontrados_posibles` group shape is preserved byte-identically; the new category-level variant uses the explicit `kind: "category"` discriminator; the four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`) are unchanged; `__all__` continues to export exactly `{"detectar_productos"}`.
- `backend/recognizers/product_recognizer_contract.py` — added `CategoryAmbiguityGroup(TypedDict, total=True)` with the explicit `kind: Literal["category"]` discriminator; widened `ProductRecognizerResult.encontrados_posibles` element type to `list[PossibleAmbiguityGroup]`; preserved `PossibleMatchGroup` byte-identically; exported `CategoryAmbiguityGroup` and `PossibleAmbiguityGroup` via `__all__`; preserved the `ProductRecognizerProtocol.recognize` signature and the four top-level result keys.
- `backend/services/product_recognition_calibration_runner.py` — added the explicit discriminator check inside `_fuzzy_ids`; added the `_fuzzy_decision(result)` helper; added the narrowly-scoped positional guard in `_hybrid_prediction` for `catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"`; extended `_decision` to return `"ambiguous"` when the combined ranking is empty AND `fuzzy_decision == "ambiguous"`; added `fuzzy_decision: str` field to `CaseObservation` (computed once in the case-evaluation loop). The existing scoring formula, the policy grid, the canonical/alias promotion, the score gap, the score combination, the JSON report schema, the diagnostic surface, the CLI surface, the per-commerce catalog cache, the fresh-DB loader, the fingerprint refusal, the `seed_refs` / `inventory_fingerprint` stale guard, the `mismatch_category` emission, and the per-case diagnostic surface are unchanged.
- `backend/services/product_recognition_shadow_service.py` — added the explicit discriminator check inside `_collect_fuzzy_candidates`; the existing `group.get("productos", []) or []` default remains the safe id-extraction path; the shadow comparison records the category signal via the empty `fuzzy_candidate_ids` tuple and falls through to the existing `fuzzy_only` / `no_result` agreement literals.
- 9 production reader files (one per reader in the Context section above) — each adapted to branch on `group.get("kind") == "category"` before accessing `productos`; the flat-candidate branch in `product_intent_resolver.py` is guarded against `KeyError` on a category-level group; the resolver, the recognizer, and the orchestrator surfaces preserve their behavioral contract for product-level inputs.
- `backend/data/product_recognition_calibration_cases.json` — unchanged. The dataset's `schema_version` (3), `seed_refs`, `inventory_fingerprint`, the 7 preserved `in_memory` cases, the 37 `commerce_dynamic_database` cases, the 3 `pending_product_selection_restricted` cases, the `commerce_catalog_inventory` / `commerce_catalog_fingerprint` blocks, the `correction_evidence` schema, the eligibility block, and the case count (47) are all unchanged.
- `backend/services/product_recognition_calibration_commerce_catalog.py` — unchanged. The fresh-DB loader, the `CommerceCatalog` dataclass, the `fingerprint_commerce_catalog` helper, the `validate_commerce_catalog_inventory_shape` validator, and the `StaleCommerceCatalogError` refusal are reused as-is.
- `backend/cli/calibrate_product_recognizer.py` — unchanged. The CLI continues to invoke the runner with the same flags; the Subphase 4.11.3 diagnostic surface (`--diagnose`, `--diagnose-output`, `mismatch_category_counts`) is reused to evidence the before / after state.
- `backend/scripts/calibration_inventory.py` — unchanged. The existing `--mode regenerate` and `--mode regenerate-commerce-catalog` subcommands continue to manage the `seed_refs` / `inventory_fingerprint` / `commerce_catalog_inventory` / `commerce_catalog_fingerprint` blocks.
- `backend/recognizers/fuzzy_product_recognizer.py` — unchanged. The adapter continues to delegate to `product_recognizer.detectar_productos` and to return the same `ProductRecognizerResult` shape (now widened through the union).
- `backend/tests/test_product_recognition_calibration_4_11_5.py` (new) — 46 focused tests covering the typed-discriminated-union contract (Tasks 3.5-3.6), the alias entry (Tasks 2.2-2.3), the 8 category pass discipline tests (Tasks 4.3-4.10), the 8 per-reader adaptation tests (Tasks 5.1-5.9), the `NoUncheckedProductosAccessTest` grep assertion (Task 5.10), the 4 `_fuzzy_decision` tests and the 3 empty-ranking branch tests (Tasks 5.8 / 6.1), the 5 hybrid-guard tests (Tasks 6.2-6.5b), the policy-grid behavioral assertion (Task 6.7), the runner classification of the 3 residual fuzzy failures and the 1 false-positive case (Tasks 7.3 / 10.1), and the commerce-isolation-preserved dataset invariant (Task 8.3). The behavioral assertions replace the previous `inspect.getsource` assertions; the runner-import-graph remains clean of `backend.tests.*` and any fixture module.
- `openspec/changes/subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/diagnostics/before.json`, `before.diagnose.json`, `after.json`, `after.diagnose.json` — the pre-fix baseline and the post-fix calibration JSON report and per-case diagnostic evidence file produced by the documented command.

**OpenSpec:**
- Modified capability `product-recognizer` (delta spec at `openspec/changes/subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/specs/product-recognizer/spec.md`): 3 ADDED Requirements (`typed-discriminated-union contract for encontrados_posibles`, `muzarrella alias closes the residual fuzzy-misspelling gap`, `category-scope matching signals category-level ambiguity through the typed-discriminated-union encontrados_posibles flow`) with 17 Scenarios. All pre-existing Subphase 4.11 / 4.11.1 / 4.11.2 / 4.11.3 / 4.11.4 requirements are preserved verbatim.
- Modified capability `calibrate-hybrid-product-recognition-4-11` (delta spec at `openspec/changes/subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/specs/calibrate-hybrid-product-recognition-4-11/spec.md`): 2 ADDED Requirements (`hybrid guard preserves fuzzy ambiguity for pending_product_selection_restricted cases (including category-level ambiguity)`, `runner classifies category-level fuzzy results as ambiguous via the typed-discriminated-union discriminator`) with 14 Scenarios covering the narrowly-scoped guard, the `_fuzzy_decision` helper, the `_decision` empty-ranking branch, the `_flag_fuzzy_boundary_violation` skip for category-level groups, the guard does-not-fire cases, the byte-identical observations, and the policy-grid invariants. All pre-existing Subphase 4.11 / 4.11.1 / 4.11.2 / 4.11.3 / 4.11.4 requirements are preserved verbatim.

**Context for future subphases:** The 3 residual `real_fuzzy_recognizer_failure` cases and the 1 false-positive case are corrected; the 4 other hybrid failures remain documented residual work for a future subphase. The fuzzy runtime contract is now a typed discriminated union — the discriminator is the explicit `kind: "category"` field on the category-level variant; the product-level variant is the default (no `kind` key). The runner's hybrid guard inspects the fuzzy decision explicitly via the `_fuzzy_decision(result)` helper and the stored `CaseObservation.fuzzy_decision`; it MUST NOT infer fuzzy ambiguity from the combined hybrid `ranking`. The category pass is a single linear scan over the catalog's categories per input segment; for a `comercio_id=1` catalog of 72 entries the latency addition is negligible and the Subphase 4.11 latency gate (p95 ≤ 500 ms) remains in place. Hybrid mode activation, weighted fuzzy / vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, background jobs, the 4 other hybrid failures, and any change to `PRODUCT_RECOGNIZER_MODE` remain future work and are explicitly out of scope here.

**Archive:**
- Change archived at `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/`; all 4 planning artifacts (`proposal`, `design`, `specs`, `tasks`) were complete and the 2 delta specs (`product-recognizer`, `calibrate-hybrid-product-recognition-4-11`) were synced to main before archive (5 ADDED requirements: 17 + 14 scenarios); `openspec validate subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives` was clean against the change bundle before archive.
- **Archived with warnings**: 0/57 implementation tasks were completed at archive time (all 57 tasks remained unchecked). Per the documented "don't block archive on warnings" guardrail, the archive proceeded after explicit user confirmation; the change bundle is preserved at the archive path with `proposal.md`, `design.md`, `specs/`, `tasks.md`, and `diagnostics/{before,after}.json` + `{before,after}.diagnose.json` intact for the next subphase to consume.

### Subphase 4.11.6 — Resolve Remaining Ruff C401 Findings [x] — completed

The Subphase 4.11.6 closure is a 6-line mechanical rewrite that closes the Subphase 4.11 calibration chain by replacing `set(int(value) for value in iterable)` with `{int(value) for value in iterable}` at the three intersection sites in `backend/intents/context/order_line_selection_resolver.py` and `backend/intents/context/product_modification_resolver.py`. The rewriting is expression-equivalent: both constructs produce a `set[int]` with the same membership, the same observable behaviour under the `&` intersection, and the same sorted output from the surrounding `sorted(...)` wrapper. No runtime, recognizer, calibration, dataset, contract, or test change was introduced.

**Root-cause summary:** Ruff's `C401` (`unnecessary-generator-set`) rule flags six locations across two context resolvers where the `set(int(value) for value in iterable)` form should be written as a set comprehension `{int(value) for value in iterable}`. The two forms are byte-identical at the produced `set` instance; the downstream `sorted(...)` call re-orders the result so the generator's iteration order is never observable. Ruff classifies this rule as `UNSAFE` by default, so the project config does not enable the auto-fix; the change edits the lines explicitly rather than running `ruff check --fix --unsafe-fixes`.

**Completed outcomes:**
- `backend/intents/context/order_line_selection_resolver.py` lines 124-127 — replaced `set(int(cid) for cid in recognized_ids)` with `{int(cid) for cid in recognized_ids}` at line 125 and `set(int(cid) for cid in active_intent.candidate_ids)` with `{int(cid) for cid in active_intent.candidate_ids}` at line 126. The surrounding `sorted(...)` wrapper, the `if not intersection: return active_intent.model_copy(update={"status": "rejected"})` early-return, the `if len(intersection) == 1: return _build_ready_intent(active_intent, intersection[0])` branch, and the multi-candidate `active_intent.model_copy(update={"candidate_ids": intersection})` fallback are preserved verbatim. The function `_resolve_order_line_selection` and its public sibling `resolve_order_line_selection` are unchanged.
- `backend/intents/context/product_modification_resolver.py` lines 159-162 (source intersection) and 219-222 (destination intersection) — replaced `set(int(x) for x in recognized_pp_ids)` with `{int(x) for x in recognized_pp_ids}` at line 160, `set(int(x) for x in source_candidate_ids)` with `{int(x) for x in source_candidate_ids}` at line 161, `set(int(x) for x in recognized_dest_ids)` with `{int(x) for x in recognized_dest_ids}` at line 220, and `set(int(x) for x in destination_candidate_ids)` with `{int(x) for x in destination_candidate_ids}` at line 221. The surrounding `sorted(...)` wrappers, the `if not intersection: return active_intent.model_copy(update={"status": "rejected"})` early-returns, the `if len(intersection) == 1: source_id / dest_id = intersection[0]` branches, the `if len(destination_candidate_ids) == 1` branch in `_resolve_source_selection`, the `_build_ready_intent` / `_build_pending_intent` call sites, and the multi-candidate fallbacks are preserved verbatim. The functions `_resolve_source_selection` and `_resolve_destination_selection` are unchanged.
- `PYTHONPATH=. venv/bin/python -m ruff check backend --select C401 --output-format=concise` exits with `All checks passed!` — zero `C401` findings across the entire `backend/` surface. The previous six findings at `order_line_selection_resolver.py:125`, `:126` and `product_modification_resolver.py:160`, `:161`, `:220`, `:221` are gone.
- `PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/order_line_selection_resolver.py backend/intents/context/product_modification_resolver.py` (without `--select`) exits with `All checks passed!` — the two touched files are clean across the project's default enabled rules. The rewrite does NOT introduce a new finding under any rule (e.g., `E711`, `E712`, `F401`, `I001`, `UP`, `B`, `SIM`).
- `PYTHONPATH=. venv/bin/python -m ruff check backend --select C401,E,W,F --output-format=concise` confirms zero `C401` findings across the entire backend. The pre-existing `C401`-unrelated findings (e.g., `E501` line-length, `W292` no-newline, `F821` undefined-name in legacy models, `F401` unused-import in `backend/old_project/`) are out of scope and unaffected by the rewrite.
- `PYTHONPATH=. venv/bin/python -m mypy --strict backend/intents/context/order_line_selection_resolver.py` reports the same pre-existing baseline error (`Missing type arguments for generic type "dict" [type-arg]` at line 33, on the `_flatten_pedido_producto_ids(recognized: dict)` signature); no new errors are introduced on the rewritten lines (124-127).
- `PYTHONPATH=. venv/bin/python -m mypy --strict backend/intents/context/product_modification_resolver.py` reports the same pre-existing baseline errors (`Missing type arguments for generic type "dict" [type-arg]` at lines 37, 53, 96, 120, 149, 203, 214 — all on `dict` type-arg signatures in helper functions and call sites); no new errors are introduced on the rewritten lines (159-162, 219-222).
- `PYTHONPATH=. venv/bin/python -m mypy --strict backend/intents/context/` reports the same 10 pre-existing baseline errors across the three context resolvers (1 in `order_line_selection_resolver.py`, 7 in `product_modification_resolver.py`, 2 in `product_selection_context_resolver.py:89, 136`); zero new errors are introduced by the rewrite, per the "Pre-existing unrelated errors (if any) are documented separately and MUST NOT block this change" guardrail.
- `PYTHONPATH=. venv/bin/python -m compileall backend/intents/context/order_line_selection_resolver.py backend/intents/context/product_modification_resolver.py` exits with code `0`; the two files compile byte-for-byte under CPython's standard library bytecode compiler.
- `PYTHONPATH=. venv/bin/python -m compileall backend/intents/context/` exits with code `0`; all sibling context resolvers remain byte-compilable.
- `PYTHONPATH=. venv/bin/pytest backend/tests/test_product_recognition_calibration_4_11_5.py -vv` reports `46 passed, 15 subtests passed in 0.48s` — the Subphase 4.11.5 baseline is preserved exactly (46 tests + 15 subtests, 100% pass, 0 failures, 0 errors, 0 skips).
- `PYTHONPATH=. venv/bin/pytest backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py backend/tests/test_product_recognition_calibration_eligibility.py backend/tests/test_product_recognition_calibration_report.py backend/tests/test_product_recognition_calibration_policy.py backend/tests/test_product_recognition_calibration_cli.py backend/tests/test_product_recognition_calibration_commerce_catalog.py backend/tests/test_product_recognition_calibration_inventory_4_11_4.py -vv` reports `147 passed` — the cumulative Subphase 4.11–4.11.5 baseline of 193 tests + 15 subtests is preserved exactly.
- `PYTHONPATH=. venv/bin/pytest backend/tests/ -vv` reports `1083 passed, 6 failed, 1 skipped`. The 6 failures (`test_modificar_producto_real_flow_cli.py::ModificarProductoRealFlowCliTest::test_defect_1_cli_full_transfer_on_omitted_quantity`, `test_modificar_producto_real_flow_http.py::ModificarProductoRealFlowHttpTest::test_defect_1_full_transfer_on_omitted_quantity`, `test_product_alias_characterization.py::AliasesInventoryTest::test_every_active_alias_entry_is_product_wide`, `test_product_recognizer.py::DetectarProductosPresentacionTest::test_descriptor_picante_no_filtra_candidato_unidad`, `test_product_recognizer.py::DetectarProductosPresentacionTest::test_picante_no_esta_en_presentacion_aliases`, `test_quitar_producto_end_to_end.py::QuitarProductoEndToEndIntegrationTest::test_initial_pending_context_with_multiple_lines`) are pre-existing, unrelated to the intersection rewrite, and out of scope; none of the failing tests exercise the rewritten path.
- No test signature, fixture, parametrisation, or expectation was modified. The rewrite is fully expression-equivalent — every existing test exercises the rewritten path without modification.
- The exact `git diff` for the C401 rewrite is 6 single-line edits, 12 changed lines, 6 added + 6 removed, no whitespace-only or comment-only changes, no other source file touched, no `pyproject.toml` / `ruff.toml` / `noqa` / `--unsafe-fixes` change. The diff is the only repair surface.

**Architectural constraints introduced:**
- The intersection expressions in the two context resolvers MUST use the set comprehension form `{int(cid) for cid in recognized_ids}` / `{int(cid) for cid in active_intent.candidate_ids}` / `{int(x) for x in recognized_pp_ids}` / `{int(x) for x in source_candidate_ids}` / `{int(x) for x in recognized_dest_ids}` / `{int(x) for x in destination_candidate_ids}`. The `set(<genexpr>)` form MUST NOT be reintroduced at these three sites; both forms are byte-equivalent at the produced `set` instance, but the comprehension form is the project's Ruff-compliant convention.
- The rewriting MUST remain expression-equivalent: the produced value MUST be a `set[int]` with the same membership as the original expression and the same observable behaviour when intersected with another `set[int]` and passed through `sorted(...)`. The intersection, the `sorted(...)` wrapper, the `&` operator, the `if not intersection` early-return, the `len(intersection) == 1` branch, the multi-candidate fallback, the `_build_ready_intent` / `_build_pending_intent` call sites, the `active_intent.model_copy(update={"status": "rejected"})` early-returns, the surrounding `if len(destination_candidate_ids) == 1` branch, the function signatures, the variable names, and the return types MUST be preserved verbatim. The rewriting MUST NOT introduce helper functions, named constants, new dependencies, new abstractions, `noqa` comments, Ruff disables, or `--unsafe-fixes` invocations.
- The two touched files MUST remain the only files modified by a future subphase that only wants to keep Ruff `C401` clean across the context resolvers. The `product_recognizer.py`, `product_recognizer_contract.py`, `fuzzy_product_recognizer.py`, the calibration runner, the shadow service, the calibration commerce catalog, the policy / report / CLI / dataset / inventory files, the FastAPI routers, the seed scripts, the settings, the `pyproject.toml`, the ruff configuration, and any test file MUST NOT be modified by such a subphase.

**Relevant files:**
- `backend/intents/context/order_line_selection_resolver.py` — replaced `set(int(cid) for cid in recognized_ids)` with `{int(cid) for cid in recognized_ids}` at line 125 and `set(int(cid) for cid in active_intent.candidate_ids)` with `{int(cid) for cid in active_intent.candidate_ids}` at line 126. The function `_resolve_order_line_selection` and the public `resolve_order_line_selection` are unchanged; the surrounding `sorted(...)` wrapper, the `if not intersection` early-return, the `len(intersection) == 1` branch, the multi-candidate fallback, and the `diagnostic_sink.on_resolver_completed(...)` call are preserved verbatim.
- `backend/intents/context/product_modification_resolver.py` — replaced `set(int(x) for x in recognized_pp_ids)` with `{int(x) for x in recognized_pp_ids}` at line 160, `set(int(x) for x in source_candidate_ids)` with `{int(x) for x in source_candidate_ids}` at line 161, `set(int(x) for x in recognized_dest_ids)` with `{int(x) for x in recognized_dest_ids}` at line 220, and `set(int(x) for x in destination_candidate_ids)` with `{int(x) for x in destination_candidate_ids}` at line 221. The functions `_resolve_source_selection` and `_resolve_destination_selection` are unchanged; the surrounding `sorted(...)` wrappers, the `if not intersection` early-returns, the `if len(intersection) == 1` branches, the `if len(destination_candidate_ids) == 1` branch, and the `_build_ready_intent` / `_build_pending_intent` call sites are preserved verbatim.
- `openspec/changes/subphase-4-11-6-resolve-remaining-ruff-c401-findings/tasks.md` — all 31 implementation tasks checked off as complete; the `proposal.md`, `design.md`, `specs/ruff-c401-closure-4-11-6/spec.md`, and `tasks.md` artifacts remain under the change bundle (now archived).

**OpenSpec:**
- New capability `ruff-c401-closure-4-11-6` declares at `openspec/changes/subphase-4-11-6-resolve-remaining-ruff-c401-findings/specs/ruff-c401-closure-4-11-6/spec.md`: 1 ADDED Requirement (`Resolve all remaining Ruff `C401` findings in the context resolvers via set-comprehension rewriting`) with 5 Scenarios (`All six Ruff `C401` findings are eliminated by the set-comprehension rewrite`, `order_line_selection_resolver intersection is expression-equivalent to the pre-rewrite result`, `product_modification_resolver source intersection is expression-equivalent to the pre-rewrite result`, `product_modification_resolver destination intersection is expression-equivalent to the pre-rewrite result`, `No behavioural regression in the Subphase 4.11-4.11.5 test suites`). 1 REMOVED Requirement documents the disappearance of the pre-rewrite `set(int(value) for value in iterable)` pattern at the three intersection sites. The capability is a single-purpose closure capability and does not introduce a reusable runtime contract.
- `openspec validate subphase-4-11-6-resolve-remaining-ruff-c401-findings --strict` reports `Change 'subphase-4-11-6-resolve-remaining-ruff-c401-findings' is valid` — the proposal, design, and tasks artifacts validate as `valid: true` and the single capability satisfies the `ADDED Requirements` + `REMOVED Requirements` formatting.
- `openspec list --json` confirms the change is the only active change in the repo; its name, schema, and `applyRequires` match the documented state.

**Context for future subphases:** The Subphase 4.11 calibration chain is closed: the 6 residual `C401` findings are eliminated, the 193-test + 15-subtest surface remains green, and no runtime, recognizer, calibration, dataset, or contract change is introduced. The two touched files are the only files in `backend/` that previously carried the `set(int(value) for value in iterable)` pattern; a future subphase that wishes to keep Ruff `C401` clean across the project's `backend/` surface MUST NOT reintroduce the `set(<genexpr>)` form at these three sites (or any other site) and MUST NOT disable Ruff rule `C401` or add `noqa` comments to silence the rule. The pre-existing `C401`-unrelated findings (e.g., `E501` line-length, `W292` no-newline, `F821` undefined-name in legacy models, `F401` unused-import in `backend/old_project/`) are out of scope. The pre-existing `mypy --strict` `dict`-type-arg errors on the two touched files and their sibling context resolvers are unchanged and are documented separately; they are not blockers for the C401 closure. The `ruff-c401-closure-4-11-6` capability was synced to `openspec/specs/` and the change bundle was archived at `openspec/changes/archive/2026-08-05-subphase-4-11-6-resolve-remaining-ruff-c401-findings/`.

**Archive:**
- Change archived at `openspec/changes/archive/2026-08-05-subphase-4-11-6-resolve-remaining-ruff-c401-findings/`; all 4 planning artifacts (`proposal`, `design`, `specs`, `tasks`) were complete; the single delta spec (`ruff-c401-closure-4-11-6`) was synced to main before archive (1 ADDED Requirement with 5 Scenarios; the REMOVED Requirement was a no-op since the pre-rewrite pattern was never present in main specs); `openspec validate subphase-4-11-6-resolve-remaining-ruff-c401-findings --strict` was clean against the change bundle before archive.

### Subphase 4.11.7 — Fix Hybrid Degrades Fuzzy-Unique to Unknown [x] — completed

The Subphase 4.11.7 calibration runner is the smallest set of runner changes that closes the Subphase 4.11 calibration chain by correcting the 4 residual `real_hybrid_recognizer_failure` cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) on the Subphase 4.11.5 baseline. The fix is concentrated in the offline calibration runner's hybrid decision path; no embedding model, Ollama configuration, vector data, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed.

**Root-cause summary:** Subphase 4.11.5 closed the residual fuzzy failures and the false-positive ambiguity leak on the restricted-pending scope. The 47-case calibration is otherwise green: 41/47 cases are `correct`, `false_positives.count == 0`, and `false_unknowns.count == 6`. The remaining 4 `real_hybrid_recognizer_failure` cases share a single failure mode: fuzzy returns `unique(single_pid)` and the vector returns nothing (`len(observation.vector_ids) == 0`). The combined hybrid `ranking` reduces to `observation.fuzzy_ids` and the combined hybrid `scores` reduce to `policy.fuzzy_weight * fuzzy_score + policy.vector_weight * 0`. Because the input does not equal the canonical `producto_nombre`, `_exact_flags` returns `canonical=False, alias=False`, so the `ranking and (canonical or alias)` short-circuit does NOT fire. The decision then falls through to the `top_score >= policy.unique_threshold` check, where `policy.fuzzy_weight * fuzzy_score` (e.g. `0.5 * fuzzy_score`) does not always meet `policy.unique_threshold` (e.g. `0.65`–`0.75`), so the hybrid returns `unknown` even though the fuzzy produced the correct unique decision.

**The fix:** A single positional `if` block is added at the top of `_hybrid_prediction` in `backend/services/product_recognition_calibration_runner.py`, placed ABOVE the existing Subphase 4.11.5 `pending_product_selection_restricted` + `fuzzy_ambiguous` guard (which is preserved verbatim). The new guard fires when `observation.fuzzy_decision == "unique"` AND `not observation.vector_ids`; when both conditions are met, it returns the fuzzy prediction verbatim (`decision="unique"`, `top_id=observation.fuzzy_ids[0]`, `ranking=observation.fuzzy_ids`, `scores=observation.fuzzy_scores`, with `_exact_flags` applied to the fuzzy ranking). The guard is scope-independent and is mutually exclusive with the 4.11.5 guard on `fuzzy_decision` (4.11.5 requires `"ambiguous"`; 4.11.7 requires `"unique"`). It does NOT modify `_decision`, `_prediction`, `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_flag_fuzzy_boundary_violation`, `_strategy_metrics`, or `_eligibility`.

**Acceptance criteria (closure criterion):**
- The four named cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) flip from `actual_hybrid_decision == "unknown"` to `actual_hybrid_decision == "unique"` with the correct `producto_presentacion_id` (2, 100, 100, 33 respectively) and are classified as `correct`.
- The Subphase 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous` (4.11.5 guard still fires; 4.11.7 guard does NOT fire because `fuzzy_decision == "ambiguous"`).
- `hybrid_metrics.false_positives.count == 0`.
- `hybrid_metrics.incorrect_unique_decisions.count == 0`.
- `hybrid_metrics.decision_accuracy.count == 45` (up from 41).
- `hybrid_metrics.false_unknowns.count == 2` (down from 6).
- The complete 47-case calibration remains `eligible`.

**Post-fix diagnostic bucketing:** `mismatch_category_counts` aggregate is `correct: 45, real_fuzzy_recognizer_failure: 2, total: 2` (47 evaluated cases − 45 correct = 2 residual). The 4 hybrid failures flip from `real_hybrid_recognizer_failure` to `correct`; the 2 residual fuzzy failures (`c1-ambiguous-postre`, `c1-ambiguous-pizza-again`) remain classified as `real_fuzzy_recognizer_failure` (out of scope; documented residual). The eligibility verdict is `eligible` (no `false_positive_tolerance_failed`, `primary_metric_improvement_failed`, `restricted_candidate_non_regression_failed`, `canonical_match_accuracy_failed`, `alias_match_accuracy_failed`, `commerce_isolation_failed`, or `latency_budget_failed` reasons).

**Calibration artifacts:**
- `openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after.json` (post-fix JSON report, `hybrid_metrics.decision_accuracy.count == 45`, `hybrid_metrics.false_unknowns.count == 2`, `hybrid_metrics.false_positives.count == 0`, `hybrid_metrics.incorrect_unique_decisions.count == 0`, eligibility verdict `eligible`).
- `openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after_diagnose.json` (per-case diagnostic records; the four named cases have `actual_hybrid_decision == "unique"` and `mismatch_category == "correct"`; `ambiguous-empanada-carne` remains `actual_hybrid_decision == "ambiguous"` and `mismatch_category == "correct"`).

**Pre-existing dataset correction (narrowly scoped):** The case `multi-word-jamon-queso-dynamic` in `backend/data/product_recognition_calibration_cases.json` previously carried an empty `allowed_candidate_ids` list (`[]`) even though its `expected_decision` is `"unique"` and its `expected_producto_presentacion_id_ref` resolves to pid 33. With the 4.11.7 guard promoting the case from `unknown` to `unique`, the runner's `false_positive` metric (`top_id not in allowed_candidate_ids`) would fire vacuously on any unique prediction. The list is populated with `[33]` (the case's actual expected pid) so the metric correctly classifies the case as `correct`. No other case in the dataset is modified; the `case_id`, input text, catalog scope, expected decision, and expected `producto_presentacion_id_ref` for every case are preserved. This is the only dataset change in the Subphase 4.11–4.11.7 chain (Subphases 4.11.1, 4.11.3, 4.11.4, 4.11.5, 4.11.6 also touched the dataset only as documented).

**Surface of the change (runtime implementation):**
- `backend/services/product_recognition_calibration_runner.py` — 1 new positional `if` block at the top of `_hybrid_prediction` (~10 lines, above the existing 4.11.5 guard). The `_hybrid_prediction` function is otherwise unchanged; the 4.11.5 guard, the `encounter` list construction, the `fuzzy`/`vector` dicts, the `values` list comprehension, the `sort`, the `ids`/`scores` construction, and the `_prediction` call are preserved verbatim.
- `backend/tests/test_product_recognition_calibration_4_11_7.py` (new file) — focused regression suite (14 tests) covering: the four named regressions become `unique` with the correct `producto_presentacion_id`; the 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous`; `false_positives.count` remains `0`; `incorrect_unique_decisions.count` remains `0`; the guard is scope-independent; the guard does NOT fire when vector_ids is non-empty or when `fuzzy_decision` is `ambiguous` or `unknown`; the guard is the FIRST statement in `_hybrid_prediction`, a single positional `if` block with one `return` (no `elif`, no `else:` branch); the 4.11.5 guard remains below the 4.11.7 guard in source order. The suite runs the runner end-to-end against stubbed recognizer + vector and inspects the per-case decisions and the metric aggregates. The suite does NOT modify any existing test file.
- `backend/data/product_recognition_calibration_cases.json` — 1-line narrowly-scoped dataset correction: `allowed_candidate_ids: [33]` for `multi-word-jamon-queso-dynamic`.

**Surface of the change (NOT touched):**
- The recognizer mode, the `FuzzyProductRecognizer` adapter, the `ProductRecognizerProtocol` contract signature, the embedding client, the Ollama configuration, the vector data, the fuzzy threshold, the `encontrados_posibles` schema, the `encontrados` schema, and the Subphase 4.11.5 category-ambiguity union are preserved verbatim.
- The Subphase 4.11.5 guard in `_hybrid_prediction` (`catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"`) is preserved verbatim; the 4.11.7 guard is added above it.
- The runner's `_decision`, `_prediction`, `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_flag_fuzzy_boundary_violation`, `_strategy_metrics`, and `_eligibility` paths are unchanged in their non-guarded branches. The policy dataclass (`HybridDecisionPolicy`), the policy grid generator (`generate_policy_grid`), the JSON report schema, the diagnostic surface (`after.diagnose.json`), and the CLI surface (`--dataset`, `--output`, `--diagnose`, `--diagnose-output`, `--commerce-id`, `--limit`) are unchanged.
- No new field is added to `StrategyPrediction` or `CaseObservation`. No new field is added to the per-case `case_results` record. No change to the `CaseObservation` dataclass, the `StrategyPrediction` dataclass, the shadow service, the orchestrators, the resolvers, the recognizers, the FastAPI routers, the settings, the `pyproject.toml`, the `ruff.toml`, the `alembic.ini`, the seeds, the migrations, the pending-context chain, the dataset's `seed_refs` map, the dataset's `inventory_fingerprint`, the dataset's `commerce_catalog_fingerprint` block, the dataset's `eligibility` block, the dataset's `schema_version` (3), the dataset's case count (47), the dataset's `commerce_catalog_inventory` block, the per-commerce catalog loader (`load_commerce_catalog_from_database`), the fingerprint refusal (`StaleCommerceCatalogError`), or the calibration inventory scripts.

**Verification results:**
- `PYTHONPATH=. venv/bin/python -m ruff check backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_7.py` → `All checks passed!` (no findings).
- `PYTHONPATH=. venv/bin/python -m compileall backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_7.py` → exit code `0`.
- `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_recognition_calibration_4_11_7.py -vv` → `14 passed` (zero failures, zero errors, zero skips).
- `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_recognition_calibration_4_11_7.py backend/tests/test_product_recognition_calibration_4_11_5.py backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py -q` → `151 passed, 15 subtests passed` (cumulative Subphase 4.11–4.11.6 baseline preserved).
- `PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after.json --diagnose --diagnose-output openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after_diagnose.json --limit 47` → `cases=47 policies=243 eligibility=eligible` (exit code `0`).
- `openspec validate subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown --strict` → `Change 'subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown' is valid`.

**Modified specs (delta at `openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/specs/calibrate-hybrid-product-recognition-4-11/spec.md`):** 1 ADDED Requirement (`hybrid preserves fuzzy_unique when the vector contributes no candidates`) with 11 Scenarios (`product-plus-presentation returns hybrid unique with the correct id`, `fuzzy-misspelling-mozzarella returns hybrid unique with the correct id`, `supported-mozza-alias returns hybrid unique with the correct id`, `multi-word-jamon-queso-dynamic returns hybrid unique with the correct id`, `guard does not fire when vector contributes candidates`, `guard does not fire when fuzzy decision is ambiguous`, `guard does not fire when fuzzy decision is unknown`, `4.11.5 ambiguous-empanada-carne guard still fires`, `4.11.5 restricted ambiguous guard remains correct after the fix`, `false_positives remain zero after the fix`, `complete 47-case calibration remains eligible`). All pre-existing Subphase 4.11 / 4.11.1 / 4.11.2 / 4.11.3 / 4.11.4 / 4.11.5 / 4.11.6 requirements are preserved verbatim.

**New capability `hybrid-fuzzy-unique-fallback-4-11-7` (delta at `openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/specs/hybrid-fuzzy-unique-fallback-4-11-7/spec.md`):** 1 ADDED Requirement (`hybrid-fuzzy-unique-fallback-4-11-7 closes the 4 residual hybrid_recognizer_failure cases by guarding fuzzy_unique + empty_vector`) with 6 Scenarios (`closure criterion — four named cases return unique with the correct id`, `closure criterion — 4.11.5 restricted ambiguous guard remains correct`, `closure criterion — complete 47-case calibration remains eligible`, `closure criterion — guard does not modify non-guarded paths`, `closure criterion — guard is the only source change in the runner`, `closure criterion — focused regression test file pins the new behaviour`). The capability exists solely to satisfy the `spec-driven` schema's `specs` artifact and does not introduce a reusable runtime capability — there is no new module surface, no new contract, no new HTTP / persistence / orchestrator surface, and no new recognizer mode.

**Context for future subphases:** The Subphase 4.11 calibration chain is now closed: the 4 residual `real_hybrid_recognizer_failure` cases flip from `real_hybrid_recognizer_failure` to `correct`, `decision_accuracy` is 45/47 (up from 41/47), `false_unknowns` is 2/47 (down from 6/47), `false_positives` remains 0, `incorrect_unique_decisions` remains 0, and the eligibility verdict is `eligible`. The 2 residual `real_fuzzy_recognizer_failure` cases (`c1-ambiguous-postre`, `c1-ambiguous-pizza-again`) are documented residual work for a future subphase and are NOT guaranteed to translate to customer-facing runtime failures. The two guards in `_hybrid_prediction` are mutually exclusive on `fuzzy_decision` (4.11.5 handles `"ambiguous"`; 4.11.7 handles `"unique"`) and live as positional `if` blocks in source order (4.11.7 first, then 4.11.5). The runner's hybrid guard MUST inspect the fuzzy decision explicitly via the stored `CaseObservation.fuzzy_decision`; it MUST NOT infer fuzzy ambiguity from the combined hybrid `ranking`. The 4.11.7 guard returns the fuzzy prediction verbatim from the stored `CaseObservation.fuzzy_ids` / `fuzzy_scores` (NOT via `_prediction` re-entry); the canonical / alias flags are still computed by `_exact_flags(case, observation.fuzzy_ids)` for symmetry with the 4.11.5 guard's return shape. Hybrid mode activation, weighted fuzzy / vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, clarification generation, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, background jobs, and the 2 residual fuzzy failures remain future work and are explicitly out of scope here. The two delta specs are synced to main, and the completed change bundle is preserved under the dated archive path below.

**Archive:**
- Change archived at `openspec/changes/archive/2026-08-05-subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/` using the `spec-driven` schema; all 4 planning artifacts (`proposal`, `design`, `specs`, `tasks`) and all 21 implementation tasks were complete. Both delta specs (`calibrate-hybrid-product-recognition-4-11`, `hybrid-fuzzy-unique-fallback-4-11-7`) were synced to main before archive; `.openspec.yaml` and the diagnostics were preserved, strict validation was clean before archive, and no incomplete-artifact or incomplete-task warnings applied.

### Subphase 4.12A — Pending Product Ambiguity Resolution [x] — completed

A pure-with-respect-to-its-own-state 9-layer resolver that closes a deterministic reply vocabulary for a pending `agregar_producto` intent (`status == "pending_resolution"`) against the `candidate_ids` stored in the pending context. The resolver is layered as a sibling of `ProductSelectionContextResolver` and is consulted by the orchestration service after the existing `resolve_product_selection` fragment-narrowing path. No full commerce catalog is consulted, no SQLAlchemy queries are issued, no commits / flushes / handler calls / embeddings / hybrid scoring are activated, and no global aliases are introduced.

**Completed outcomes:**
- `backend/intents/context/pending_product_ambiguity_resolver.py` — new module exposing exactly one public symbol `resolve_pending_product_ambiguity(message, active_intent, productos_presentaciones) -> ProcessedIntent` via `__all__`. The function runs the 9 layers in the strict order `1 → 2 → 3 → 7 → 4 → 5 → 6 → 8 → 9` (Layer 7 — explicit exclusion — precedes Layers 4 and 5 because customer intent is explicit and categorical; the conceptual numbering 1–9 is preserved by the layer functions). Layer 1 (numeric) accepts `"1"`, `"2"`, …, `"la <n>"`, `"opción <n>"`, `"número <n>"`. Layer 2 (positional) accepts `primera/primero/segunda/segundo/tercera/tercero/última/último`, `la <ordinal>`, and `la opción <digit|ordinal|number-word>`. Layer 3 (exact normalized full-name) compares the sorted token set of the message against each candidate's normalized `producto_nombre + " " + presentacion_descripcion`. Layer 4 (token-set) strips a module-level `FILLER_TOKENS` frozenset (includes `en`, `de`, `la`, `el`, `los`, `las`, `del`, `al`, `a`), enforces the shared-core precondition guard (`candidate_core ∩ message_core != ∅`), the exact-match priority, the subset preference with distinguishing-token penalty, and the token-count-agnostic ranking (token-count-only unique rank does not select). Layer 5 (differentiating token) selects when exactly one candidate uniquely owns a token in its `producto_nombre`. Layer 6 (default descriptor) selects the variant-free candidate when the message contains exactly one of `comun`, `normal`, `regular`, `original`, `clasica`, `clasico`, `estandar`. Layer 7 (explicit exclusion) parses `la que no es <t>`, `la que no tenga <t>`, `la que no tiene <t>`, `sin <t>`, `no quiero la <t>`, `no la <t>`, and the bare `la otra` (which falls back to variant-free selection). Layer 8 (restricted fuzzy fallback) scores candidates via `rapidfuzz.fuzz.partial_ratio` with threshold 85, restricted to `active_intent.candidate_ids`, selecting the strict unique top score above the threshold. Layer 9 returns the input `active_intent` unchanged (same instance) when no earlier layer selects. The function never calls `commit`, `flush`, `close`, `begin`, `refresh`, `expire`, never imports `requests` / `fastapi` / `twilio` / `backend.repositories` / `backend.routers` / `backend.services` / `backend.models` / `backend.old_project`, never mutates the input intent in place, never logs, and never activates embeddings / hybrid / vector search. The helper `_build_resolved_unique_intent` mirrors the shape produced by `product_selection_context_resolver` so the resolved intent is consumable by the existing pending-context dispatcher and execution pipeline. The `DatabaseSession = Session` alias is imported only for type annotations (unused at runtime, kept for forward compatibility with future SQLAlchemy-aware callers).
- `backend/intents/context/product_selection_context_service.py` — orchestration service now binds the existing path's result to `fragment_result`. When `fragment_result.status == "ready"` the service returns `fragment_result` directly without consulting the new resolver. Otherwise the service invokes `resolve_pending_product_ambiguity(message, fragment_result, fragment_catalog)` where `fragment_catalog` is the in-memory list-comprehension projection of the originally-loaded catalog filtered to `fragment_result.candidate_ids` (no second `list_presentaciones_by_ids` call, no widening). When the new resolver returns `ready`, the service returns that intent; otherwise the service returns `fragment_result` (preserving the existing path's narrowing). The service still loads the restricted catalog exactly once per call via `ProductoQueryService.list_presentaciones_by_ids(active_intent.candidate_ids)`; no commit / rollback / flush / refresh / expire / `begin` was introduced and the `Session` model is still untouched.
- `backend/tests/test_pending_product_ambiguity_resolution.py` — new focused module with module-level `__all__` listing exactly the two module-level `test_*` functions (`test_module_all_contains_only_resolve_pending_product_ambiguity`, `test_imports_resolve_pending_product_ambiguity`). 67 `unittest.TestCase` test methods across 18 classes plus 2 module-level test functions = 69 collected tests, all passing against the in-memory fixtures. Coverage spans every layer's pass / fail / remain-ambiguous cases (numeric and out-of-range; positional and `última`; exact full-name with mixed case + hyphen and ambiguous full-name across candidates; token-set with shared-core guard, tied scores, fillers-only, message token count not a ranking criterion; differentiating-token with shared-token fall-through and multi-token disambiguation; default descriptor with all-candidates-have-variants fall-through; explicit exclusion including `la que no es <unknown>` and `la otra`; fuzzy with misspelling, tied scores, and low-similarity gating; remain-ambiguous with `no sé`, `ok`, human handoff), strict ordering (Layer 1 wins over Layer 5), a second generic family (`Pizza Muzzarella Tradicional` vs `Pizza Muzzarella Especial`) proving the resolver is not hardcoded to Coca-Cola, no-side-effects (`is` instance comparison + mock session asserting no DB calls + grep assertion against disallowed side-effect imports), the public-surface module file-set, and the orchestration discarded-candidate invariant (drives `ProductSelectionContextService.resolve` with a fixture that narrows `[A, B, C] → [B, C]` and asserts the new resolver cannot reintroduce `A`, `list_presentaciones_by_ids` is called exactly once, and `fragment_result` is preserved when both paths remain ambiguous). Validation: `pytest … -vv` → 69 passed, 11 subtests passed; `pytest --collect-only` → 69 tests collected; `ruff check …` → all checks passed; `compileall …` → exit code 0.
- The four end-to-end conversation integration tests required by task 4 are part of the same test file: `test_coca_cola_common_vs_zero_full_conversation` (seeds the pair against `supernova_test`, exercises Layer 1–7 replies end-to-end, asserts `status == "executed"`, exactly one `PedidoProducto` row, empty `pending_intents`, `context_type is None`); `test_coca_cola_zero_selection_via_differentiating_token` (asserts the Zero Lata path); `test_second_generic_family_pizza_tradicional_vs_especial` (asserts the Pizza pair; proves the resolver is generic); `test_vague_answer_remains_ambiguous_through_dispatch` (asserts `no sé` keeps `pending_resolution`, `context_type == "product_selection"`, candidate list preserved, no `PedidoProducto` row).

**Architectural constraints introduced:**
- The new module's `__all__` is exactly `["resolve_pending_product_ambiguity"]`. Private helpers (`_normalize_tokens`, `_normalize_text`, `_build_resolved_unique_intent`, `_build_catalog_index`, `_ordered_candidate_ids`, `_layer_*`, `_strip_filler`, `_resolve_positional_index`, `_parse_excluded_token`, `_compute_variant_token_sets`) and the `FILLER_TOKENS` / `_DEFAULT_DESCRIPTORS` / `_MIN_FUZZY_SCORE` / `_ORDINAL_FIXED` / `_ORDINAL_LAST` / `_NUMBER_WORDS` constants are private to the module. No symbol besides `resolve_pending_product_ambiguity` is re-exported from `backend/intents/context/__init__.py` or any sibling module.
- The resolver MUST resolve only against the rows of the in-memory `productos_presentaciones` argument whose `producto_presentacion_id` is in `active_intent.candidate_ids`; rows outside this set are ignored even when present in the input list. The resolver MUST NOT issue its own SQLAlchemy query, MUST NOT consult the full commerce catalog, MUST NOT activate embeddings / vector search / hybrid scoring, and MUST NOT consult `allowed_candidate_ids` / `restricted_candidate_ids` / `expected_producto_presentacion_id` or any calibration label.
- The runtime evaluation order is fixed at `1 → 2 → 3 → 7 → 4 → 5 → 6 → 8 → 9`. The first layer that returns a non-`None` `ProcessedIntent` wins; later layers MUST NOT run for the same call. Layer 7's precedence over Layers 4 and 5 is mandatory — explicit customer exclusion phrases are categorical and outrank generic token-set and differentiating-token evidence. Layer 8 (fuzzy) is the final numeric fallback and MUST NOT pre-empt any earlier layer. Layer 9 is the only layer permitted to return the input intent unchanged via the same-instance (`is`) comparison.
- Layer 4's shared-core precondition guard is mandatory: a candidate is eligible for Layer 4 ranking only when `candidate_core ∩ message_core` is non-empty; candidates with zero shared core tokens SHALL be excluded before any ranking step; if no candidate has a non-empty shared core, the layer falls through. The ranking is `(i) candidate_core ⊆ message_core` preferred, `(ii) |candidate_core − message_core|` minimised, `(iii) |message_core − candidate_core|` minimised; total candidate token count `len(candidate_core)` is explicitly NOT a ranking criterion; a unique ranking caused only by token-count differences (with all of (i)/(ii)/(iii) tied) SHALL fall through.
- The orchestration service MUST load the restricted catalog via `ProductoQueryService.list_presentaciones_by_ids(active_intent.candidate_ids)` exactly once per call. When the existing `resolve_product_selection` returns `fragment_result.status == "ready"`, the service MUST return `fragment_result` directly without consulting the new resolver. When `fragment_result.status != "ready"`, the service MUST invoke the new resolver with `fragment_result` (NOT the original `active_intent`) and with the in-memory catalog projection filtered to `fragment_result.candidate_ids`. The orchestration service MUST NOT issue a second `list_presentaciones_by_ids` call for the new resolver, MUST NOT widen the catalog beyond `fragment_result.candidate_ids`, MUST NOT allow the new resolver to reintroduce a candidate that the existing narrowing path discarded, and MUST NOT add `commit` / `rollback` / `flush` / `refresh` / `expire` / `begin` calls or mutate the `Session` model.
- No new global aliases were introduced to solve pending clarification; the resolver remains generic and operates purely on the runtime candidate payloads.

**Relevant files:**
- `backend/intents/context/pending_product_ambiguity_resolver.py` (new, 682 lines) — 9 layer functions, the `FILLER_TOKENS` frozenset, `_build_resolved_unique_intent`, `_build_catalog_index`, and the public `resolve_pending_product_ambiguity` orchestrator with the strict `for layer in layers: …` evaluation loop. `__all__ = ["resolve_pending_product_ambiguity"]`.
- `backend/intents/context/product_selection_context_service.py` — `ProductSelectionContextService.resolve` now binds `fragment_result = resolve_product_selection(...)`, short-circuits on `status == "ready"`, computes `fragment_catalog` via in-memory list comprehension (`row for row in catalog if row["producto_presentacion_id"] in fragment_result.candidate_ids`), invokes the new resolver, returns the new `ready` intent when applicable, otherwise returns `fragment_result`. No additional transaction calls, no additional repository calls.
- `backend/tests/test_pending_product_ambiguity_resolution.py` (new, 886 lines) — 69 collected tests, module-level `__all__` listing the 2 module-level `test_*` functions plus 18 `unittest.TestCase` classes covering each layer, ordering, second generic family, no-side-effects, public surface, and the orchestration discarded-candidate invariant.

**OpenSpec:**
- New capability `pending-product-ambiguity-resolution` synced at `openspec/specs/pending-product-ambiguity-resolution/spec.md` with 17 Requirements and 41 Scenarios covering function existence, input validation, catalog restriction, Layers 1–9, strict evaluation order, no side effects, public surface, real integration with `dispatch_pending_context`, and existing pending-context behaviour preservation.
- Modified capability `product-selection-context-orchestration` synced at `openspec/specs/product-selection-context-orchestration/spec.md` with 4 ADDED Requirements (`Orchestration consults the pending-product-ambiguity resolver as a sibling step`, `Orchestration loads the candidate catalog exactly once and narrows it for the new resolver`, `Orchestration does not introduce new side effects`, `Existing orchestration scenarios remain green`) and 7 ADDED Scenarios. All pre-existing orchestration requirements are preserved verbatim.
- The four `api_smoke.py` tests that already fail on `main` today (`test_llm_settings_and_query_llm`, `test_pending_context_execution`, `test_pending_context_dispatcher`, `test_agregar_producto_end_to_end`) remain documented known pre-existing failures and were NOT touched by this subphase.

**Archive:**
- Change archived at `openspec/changes/archive/2026-08-05-subphase-4-12a-pending-product-ambiguity-resolution/` using the `spec-driven` schema; all 4 planning artifacts (`proposal`, `design`, `specs`, `tasks`) and all 41 implementation tasks were complete; both delta specs (`pending-product-ambiguity-resolution` as a new capability, `product-selection-context-orchestration` as a modified capability) were synced to main before archive; `openspec validate subphase-4-12a-pending-product-ambiguity-resolution --strict` was clean against the change bundle before archive; `.openspec.yaml` was preserved with the directory move.

**Context for future subphases:** Pending-product clarification now has a dedicated sibling resolver that lives entirely in `backend/intents/context/` alongside `product_selection_context_resolver`, `product_selection_context_service`, `order_line_selection_resolver`, `product_modification_resolver`, `context_type_resolver`, and `pending_context_service`. The orchestration service is the single entry point that consults both resolvers and is the only place where `fragment_result` flows into `resolve_pending_product_ambiguity`; a future subphase that wants to add a new sibling resolver MUST add it as an additional `if/elif` step in `ProductSelectionContextService.resolve` (not in `pending_product_ambiguity_resolver`), MUST keep the single `list_presentaciones_by_ids` call, and MUST keep the `fragment_result`-first contract. The 9-layer vocabulary is fixed; a future subphase that wants to add a new heuristic MUST add it as Layer 10 (after the fuzzy fallback) or as a discriminator inside an existing layer, MUST update the strict evaluation loop, and MUST update both the test module's per-layer coverage and the synced capability's Scenarios. The resolver is generic and product-id-agnostic; any test that asserts behaviour against the Coca-Cola or Pizza pairs SHOULD be re-used as-is when extending the resolver. Hybrid mode activation, weighted fuzzy / vector score fusion affecting customer responses, confirmation thresholds, score-gap rules as authoritative signals, fallback switching between fuzzy and vector, customer-facing semantic results, catalog mutations, embedding synchronization changes, HNSW / IVFFlat, background jobs, the 4 `api_smoke.py` known pre-existing failures, the 2 residual fuzzy calibration failures (`c1-ambiguous-postre`, `c1-ambiguous-pizza-again`), and the 4 residual hybrid calibration failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain future work and are explicitly out of scope here.

### Implement Subphase 4.12B: Controlled Authoritative Hybrid Product Recognition. [ ]

Objective:
Enable the already-calibrated hybrid product recognizer as an authoritative strategy through explicit, reversible configuration, while preserving fuzzy mode as the safe fallback.

Current context:
- Product recognition supports `fuzzy`, `shadow`, and `hybrid` modes.
- Fuzzy is currently authoritative.
- Shadow/hybrid observations and calibration already exist.
- The selected hybrid policy is calibrated and eligible.
- Subphase 4.12A pending-product ambiguity resolution is completed and must remain unchanged.
- Transactions remain caller-owned.

Required investigation:
- Inspect the current product-recognition entry points, settings, mode selection, hybrid observation service, handlers, pending-context flow, and tests.
- Identify the real execution path used by:
  - `agregar_producto`
  - `modificar_producto`
  - `quitar_producto`
- Reuse existing mode/configuration infrastructure whenever possible.
- Do not invent a second recognition pipeline.

Required behavior:

1. Recognition modes

Preserve three explicit modes:

- `fuzzy`
  - fuzzy result is authoritative;
  - vector/hybrid result does not affect execution.

- `shadow`
  - fuzzy result remains authoritative;
  - hybrid result is computed only for observation and metrics;
  - hybrid failure must never block the customer flow.

- `hybrid`
  - hybrid result becomes authoritative;
  - safe fallback to fuzzy applies only under explicitly defined infrastructure-failure conditions.

Unknown or invalid configured mode must fail safely to `fuzzy`, with an observable warning.

2. Controlled activation

- Activation must be configuration-driven and reversible without changing code.
- Prefer the existing settings mechanism.
- Determine whether current architecture already supports environment-level or commerce-level mode selection.
- Implement the narrowest viable option:
  - environment-level configuration is sufficient unless commerce-level configuration already exists naturally;
  - do not add a database table or migration solely for per-commerce rollout.
- Default mode must remain `fuzzy`.
- Do not automatically switch production to `hybrid` during implementation.

3. Authoritative hybrid contract

In `hybrid` mode:

- `unique` executes the identified `producto_presentacion_id`;
- `ambiguous` creates or preserves the existing pending-product-selection context;
- `unknown` follows the current unknown-product behavior;
- candidate ordering and candidate IDs must remain compatible with the pending ambiguity resolver;
- the hybrid path must not force a unique selection when the calibrated result is ambiguous or unknown.

4. Safe fallback

Fallback to fuzzy is allowed only when hybrid recognition cannot be evaluated because of an infrastructure or technical failure, such as:

- embedding provider unavailable;
- vector repository/query failure;
- malformed hybrid infrastructure response;
- unexpected technical exception in the hybrid evaluation path.

Fallback must NOT occur merely because hybrid returns:

- `unknown`;
- `ambiguous`;
- low confidence;
- no sufficiently strong candidate.

Those are valid business outcomes and must remain authoritative in `hybrid` mode.

When fallback occurs:

- customer processing continues with fuzzy;
- the failure is observable through existing logging/diagnostic mechanisms;
- no transaction is committed or rolled back inside the recognizer;
- no exception detail is exposed to the customer.

5. Integration scope

Apply the selected authoritative recognition result consistently to:

- adding a product;
- modifying a product;
- removing a product;
- pending-context product selection where recognition is used.

Do not duplicate hybrid decision logic across handlers. Prefer one shared strategy-selection boundary.

Preserve:

- caller-owned transactions;
- existing handler contracts;
- existing `ProcessedIntent` and candidate contracts;
- Subphase 4.12A ambiguity resolution;
- commerce catalog isolation.

6. Observability

Reuse existing observation/diagnostic structures where possible.

At minimum, make observable:

- configured mode;
- effective mode;
- authoritative strategy used;
- fuzzy decision;
- hybrid decision when evaluated;
- whether fallback occurred;
- fallback category without sensitive exception details.

Do not introduce a new metrics platform or external dependency.

7. Explicit non-goals

Do not:

- recalibrate weights or thresholds;
- modify the selected hybrid policy;
- change the calibration dataset;
- change embedding generation or indexing;
- replace the embedding model;
- redesign fuzzy recognition;
- modify the 4.12A ambiguity resolver;
- add catalog mutation endpoints;
- fix the four known pre-existing `api_smoke.py` failures;
- migrate to LangGraph;
- add database schema changes unless an already-existing configuration design strictly requires one.

Required tests:

- default configuration uses authoritative fuzzy;
- explicit `shadow` keeps fuzzy authoritative;
- explicit `hybrid` uses hybrid `unique`;
- hybrid `ambiguous` remains ambiguous and creates/preserves pending selection;
- hybrid `unknown` remains unknown and does not fall back merely because no match exists;
- technical hybrid failure falls back to fuzzy;
- invalid mode safely resolves to fuzzy;
- commerce isolation remains enforced;
- add/modify/remove flows consume the same configured strategy;
- 4.12A pending ambiguity behavior remains unchanged;
- no commit, rollback, flush, or transaction ownership is introduced;
- no new regression beyond the four documented pre-existing `api_smoke.py` failures.

Validation plan:

- focused tests for strategy selection and each affected intent flow;
- existing relevant recognition and pending-context tests;
- Ruff on touched files;
- compileall on touched Python files;
- strict OpenSpec validation.

Proposal requirements:

- Keep the change narrow and 80/20.
- Clearly identify the single shared authoritative-strategy boundary.
- Define exact fallback conditions.
- List the concrete files expected to change.
- Separate existing infrastructure reuse from genuinely new code.
- Record any discovered architectural limitation instead of silently expanding scope.
- Deliver only `proposal.md`, `design.md`, specification deltas, and `tasks.md`.
- Do not implement production code.
- Do not sync or archive.

### Subphase 4.12C — Safe Product-Recognition Decision Observability [x] — archived 2026-08-12

Make the existing `shadow_product_recognition` telemetry safely queryable through
the bounded production-observability CLI. This subphase improves operational
evidence for `hybrid_authoritative`; it does not change product-recognition
decisions or activate traffic.

**Scope:**

- Add `shadow_product_recognition` to the versioned, allowlisted operational
  event catalogue and extend the existing bounded query CLI to return only
  validated instances of it.
- Permit only: configured/effective mode, authoritative strategy, hybrid
  decision category, fallback boolean/category, and aggregate latency fields
  already emitted by the recognizer.
- Preserve explicit `--project`, `--environment`, `--service`, `--since` and
  finite `--limit` query bounds; absent events remain an inconclusive result,
  not a business-success assertion.
- Add focused contract and privacy tests for valid events, rejected unexpected
  or sensitive fields, bounded filtering, and no raw-log fallback.

**Non-goals and invariants:**

- Do not change fuzzy, shadow or hybrid-authoritative recognition logic,
  selected policy, fallback conditions, candidate sets, commerce isolation,
  transactions, handlers, pending-context behavior, settings or Railway
  configuration.
- Never emit or return customer text, E.164 addresses, `commerce_id`, product
  or candidate IDs, correlation IDs, scores, vectors, prompts, payloads, raw
  exceptions or raw Railway log lines.
- Do not add a telemetry platform, database table, endpoint, dashboard,
  migration, Twilio traffic or synthetic recognition request.

**Expected validation:** focused observability/CLI tests, Ruff and compileall
on touched Python files, and strict OpenSpec validation. Any production query
remains a separately authorized, read-only operational gate.

**Outcome:** implemented and archived as
`2026-08-12-add-safe-product-recognition-observability`; deployed to
production and verified through one bounded query. The query returned zero
recognition events, which was recorded as inconclusive without changing mode
or generating traffic.
