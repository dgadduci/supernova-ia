## 1. Model implementation

- [x] 1.1 Create `backend/models/comercio_medios_pago.py` containing the `ComercioMedioPago` class with `__tablename__ = "comercio_medios_pago"`, a `__table_args__` tuple declaring `UniqueConstraint("id_comercio", "id_medio_pago", name="comercio_medio_pago_unico")`, and the columns from the user's body: `id` (PK autoincrement); `id_comercio` (`ForeignKey("comercios.id", ondelete="CASCADE")`, non-null, indexed); `id_medio_pago` (`ForeignKey("medios_pago.id", ondelete="RESTRICT")`, non-null, indexed); `activo` (Boolean, non-null, `default=False`, `server_default="false"`); `titular` (String ≤ 150, nullable); `alias` (String ≤ 100, nullable); and lifecycle timestamps `fecha_alta` (timezone-aware DateTime, non-null, `server_default=func.now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, `server_default=func.now()`, `onupdate=func.now()`)

- [x] 1.2 In the same file, declare the two bidirectional relationships as forward-ref strings: `comercio: Mapped["Comercio"] = relationship(back_populates="medios_pago")` and `medio_pago: Mapped["MediosPago"] = relationship(back_populates="comercios")`

## 2. Wire Comercio back-reference

- [x] 2.1 In `backend/models/comercio.py`, add `medios_pago: Mapped[list["ComercioMedioPago"]] = relationship(back_populates="comercio")` (forward-ref string for the partner class); preserve the existing `metodos_entrega` attribute from Subphase 1.9

## 3. Wire MediosPago back-reference

- [x] 3.1 In `backend/models/medios_pago.py`, add the `relationship` import alongside `mapped_column`; add `comercios: Mapped[list["ComercioMedioPago"]] = relationship(back_populates="medio_pago")` (forward-ref string for the partner class)

## 4. Re-export

- [x] 4.1 Re-export `ComercioMedioPago` from `backend/models/__init__.py` so consumers can `from backend.models import ComercioMedioPago`

## 5. Verification

- [x] 5.1 Activate the project-local `venv` and run `python -c "from backend.models import Comercio, ComercioMedioPago, MediosPago"` (and from a fresh interpreter, also import `ComercioMetodoEntrega` to confirm both cycles still resolve) to confirm all three modules load without cycle issues

- [x] 5.2 Inspect `ComercioMedioPago.__table__.columns` and confirm: `id` is an integer autoincrement primary key; `id_comercio` is a non-null integer FK to `comercios.id` with `ondelete="CASCADE"` and `index=True`; `id_medio_pago` is a non-null integer FK to `medios_pago.id` with `ondelete="RESTRICT"` and `index=True`; `activo` is a non-null Boolean with `default=False` and `server_default="false"`; `titular` is a nullable String ≤ 150 (no default); `alias` is a nullable String ≤ 100 (no default); `fecha_alta` and `fecha_ultima_modificacion` are timezone-aware DateTime columns with the supplied server defaults (`fecha_ultima_modificacion` additionally `onupdate=func.now()`)

- [x] 5.3 Inspect the table-level constraints on `ComercioMedioPago.__table__` and confirm: a `UniqueConstraint` named `comercio_medio_pago_unico` over `(id_comercio, id_medio_pago)`; **no** `CheckConstraint` (no `orden` column to constrain)

- [x] 5.4 Confirm `ComercioMedioPago.__tablename__ == "comercio_medios_pago"` and the table is registered in `Base.metadata`

- [x] 5.5 Confirm `ComercioMedioPago.comercio` and `.medio_pago` are `relationship()`s; `Comercio.medios_pago` is a relationship whose partner is a list of `ComercioMedioPago`; `MediosPago.comercios` is a relationship whose partner is a list of `ComercioMedioPago`; `Comercio.metodos_entrega` (from 1.9) is still intact

- [x] 5.6 Confirm `Base.metadata` registers all 11 expected tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentaciones`, `producto_precios`, `comercio_metodos_entrega`, `comercio_medios_pago`)
