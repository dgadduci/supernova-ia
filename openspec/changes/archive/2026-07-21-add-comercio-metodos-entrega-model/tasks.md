## 1. Model implementation

- [x] 1.1 Create `backend/models/comercio_metodos_entrega.py` containing the `ComercioMetodoEntrega` class with `__tablename__ = "comercio_metodos_entrega"`, a `__table_args__` tuple declaring `UniqueConstraint("id_comercio", "id_metodo_entrega", name="comercio_metodo_unico")` and `CheckConstraint("orden >= 0", name="orden_no_negativo")`, and the columns from the user's body: `id` (PK autoincrement); `id_comercio` (`ForeignKey("comercios.id", ondelete="CASCADE")`, non-null, indexed); `id_metodo_entrega` (`ForeignKey("metodos_entrega.id", ondelete="RESTRICT")`, non-null, indexed); `activo` (Boolean, non-null, `default=False`, `server_default="false"`); `orden` (Integer, non-null, no default); and lifecycle timestamps `fecha_alta` (timezone-aware DateTime, non-null, `server_default=func.now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, `server_default=func.now()`, `onupdate=func.now()`)

- [x] 1.2 In the same file, declare the two bidirectional relationships as forward-ref strings: `comercio: Mapped["Comercio"] = relationship(back_populates="metodos_entrega")` and `metodo_entrega: Mapped["MetodosEntrega"] = relationship(back_populates="comercios")`

## 2. Wire Comercio back-reference

- [x] 2.1 In `backend/models/comercio.py`, add `metodos_entrega: Mapped[list["ComercioMetodoEntrega"]] = relationship(back_populates="comercio")` (forward-ref string for the partner class)

## 3. Wire MetodosEntrega back-reference

- [x] 3.1 In `backend/models/metodos_entrega.py`, add `comercios: Mapped[list["ComercioMetodoEntrega"]] = relationship(back_populates="metodo_entrega")` (forward-ref string for the partner class)

## 4. Re-export

- [x] 4.1 Re-export `ComercioMetodoEntrega` from `backend/models/__init__.py` so consumers can `from backend.models import ComercioMetodoEntrega`

## 5. Verification

- [x] 5.1 Activate the project-local `venv` and run `python -c "from backend.models import Comercio, ComercioMetodoEntrega, MetodosEntrega"` (and from a fresh interpreter, also import `Producto` to confirm the existing cycle still resolves) to confirm all three modules load without cycle issues

- [x] 5.2 Inspect `ComercioMetodoEntrega.__table__.columns` and confirm: `id` is an integer autoincrement primary key; `id_comercio` is a non-null integer FK to `comercios.id` with `ondelete="CASCADE"` and `index=True`; `id_metodo_entrega` is a non-null integer FK to `metodos_entrega.id` with `ondelete="RESTRICT"` and `index=True`; `activo` is a non-null Boolean with `default=False` and `server_default="false"`; `orden` is a non-null Integer (no default); `fecha_alta` and `fecha_ultima_modificacion` are timezone-aware DateTime columns with the supplied server defaults (`fecha_ultima_modificacion` additionally `onupdate=func.now()`)

- [x] 5.3 Inspect the table-level constraints on `ComercioMetodoEntrega.__table__` and confirm: a `UniqueConstraint` named `comercio_metodo_unico` over `(id_comercio, id_metodo_entrega)`; a `CheckConstraint` named `orden_no_negativo` with SQL expression `orden >= 0`

- [x] 5.4 Confirm `ComercioMetodoEntrega.__tablename__ == "comercio_metodos_entrega"` and the table is registered in `Base.metadata`

- [x] 5.5 Confirm `ComercioMetodoEntrega.comercio` and `.metodo_entrega` are `relationship()`s; `Comercio.metodos_entrega` is a relationship whose partner is a list of `ComercioMetodoEntrega`; `MetodosEntrega.comercios` is a relationship whose partner is a list of `ComercioMetodoEntrega`

- [x] 5.6 Confirm `Base.metadata` registers all 10 expected tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentaciones`, `producto_precios`, `comercio_metodos_entrega`)
