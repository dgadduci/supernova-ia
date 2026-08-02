[PASAR project.md]

perfecto. dame el spec que le deberia pasar a project.md de openspec para que comience con todo esto con el modelo CategoriaProducto. Recorda, test minimos indispensables y economia de tokens. Ya tengo instalados los servicios de fastapy, uvicorn, etc


EJEMPLO DE TU RESPUESTA:
### Phase 2 — FastAPI API

Implement the API incrementally using vertical slices. Do not create unused abstractions or endpoints.

#### Subphase 2.1 — FastAPI foundation and CategoriaProducto listing

Implement the minimum FastAPI infrastructure and a read-only endpoint for listing product categories belonging to a commerce.

##### Scope

* Create the FastAPI application in `backend/main.py`.
* Add a database-session dependency using the existing synchronous SQLAlchemy configuration.
* Create a health endpoint:

  * `GET /health`
  * Response: `{"status": "ok"}`
* Implement:

  * `GET /comercios/{comercio_id}/categorias-productos`
* Return only active categories belonging to the requested commerce.
* Order results by `orden`, then by `id`.
* Use the existing `CategoriaProducto` model without changing the database schema.

##### Required structure

Create only the files required by this subphase:

```text
backend/
├── main.py
├── dependencies.py
├── routers/
│   └── categorias_productos.py
├── schemas/
│   └── categoria_producto.py
├── repositories/
│   └── categoria_producto_repository.py
└── services/
    └── categoria_producto_service.py
```

Reuse existing database and model modules. Add `__init__.py` files only where required by the current package structure.

##### Responsibilities

* `main.py`: create the FastAPI application and register the router.
* `dependencies.py`: provide one SQLAlchemy session per request and close it using `yield`.
* Schema: serialize the category response.
* Repository: contain the SQLAlchemy query.
* Service: expose the listing operation without inventing additional business rules.
* Router: handle HTTP input, output and dependency injection only.

##### Response schema

Return:

* `id`
* `id_comercio`
* `descripcion`
* `activo`
* `orden`

Do not expose lifecycle fields unless required later.

##### Endpoint behavior

`GET /comercios/{comercio_id}/categorias-productos`

* `200`: return the active categories for the commerce.
* Return an empty list when the commerce has no active categories.
* Do not add commerce-existence validation in this subphase.
* Do not add pagination, authentication, create, update or delete endpoints.

##### Minimum tests

Run tests only against `supernova_test`.

Implement only:

1. Health endpoint returns `200` and `{"status": "ok"}`.
2. Category endpoint returns only active categories for the requested commerce and orders them by `orden`, then `id`.
3. Category endpoint does not return categories belonging to another commerce.

Do not create separate unit tests for schemas, repository and service unless required to diagnose a failure.

##### Completion criteria

* FastAPI starts locally through Uvicorn.
* `/docs` loads successfully.
* `/health` works.
* The category listing endpoint works against `supernova_test`.
* The minimum tests pass.
* No database migration is generated.
* No unrelated files are refactored.
