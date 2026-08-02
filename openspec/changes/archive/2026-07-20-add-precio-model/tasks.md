## 1. Prerequisite: refactor ProductoPresentacion

- [x] 1.1 In `backend/models/producto_presentacion.py`, change `__tablename__` from `"producto_presentacion"` to `"producto_presentaciones"`; add `precios: Mapped[list["Precio"]] = relationship(back_populates="producto_presentacion")`

## 2. New Precio model

- [x] 2.1 Create `backend/models/precio.py` containing the `Precio` class with `__tablename__ = "producto_precios"`, a `__table_args__` tuple declaring `CheckConstraint("precio >= 0", name="precio_no_negativo")` and `Index("id_producto_presentacion", "id_producto_presentacion", unique=True)` (column passed explicitly so the unique index has a target — cleanup of a spec literal that would otherwise produce an empty index), and the columns from the spec: `id` (PK autoincrement), `id_producto_presentacion` (Integer ForeignKey to `producto_presentaciones.id`, `ondelete="RESTRICT"`, non-null — column-level `index=True` intentionally omitted so it doesn't duplicate the unique index in `__table_args__`), `precio` (`Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)`), and `fecha_alta` (timezone-aware DateTime, non-null, `server_default=func.now()`); relationship `producto_presentacion: Mapped["ProductoPresentacion"] = relationship(back_populates="precios")`

## 3. Re-export

- [x] 3.1 Update `backend/models/__init__.py` to add `from backend.models.precio import Precio` and include `"Precio"` in `__all__`

## 4. Verification

- [x] 4.1 Activate the project-local `venv` and run `python -c "from backend.models import Precio, ProductoPresentacion; print(Precio.__name__, ProductoPresentacion.__name__)"` to confirm both imports load without error
- [x] 4.2 Inspect `Precio.__table__.columns` and confirm: `id` PK autoincrement; `id_producto_presentacion` Integer FK to `producto_presentaciones.id` non-null (column-level index is `None`/`False` — the index lives in `__table_args__`); `precio` `Numeric(12, 2)` non-null; `fecha_alta` tz-aware DateTime non-null with `server_default=func.now()`
- [x] 4.3 Confirm `Precio.id_producto_presentacion` ForeignKey targets `producto_presentaciones.id` (note the plural form, after the rename) and its `ondelete` is set to `RESTRICT`
- [x] 4.4 Inspect `Precio.__table__.constraints` and confirm: a `CheckConstraint` named `precio_no_negativo` with SQL expression `precio >= 0`
- [x] 4.5 Inspect `Precio.__table__.indexes` and confirm **exactly one** index exists: named `id_producto_presentacion`, `unique=True`, columns `["id_producto_presentacion"]` (cleanup applied — the original spec literal `Index("id_producto_presentacion", unique=True)` produced an empty index; the column is now passed explicitly and `index=True` is omitted from the column to avoid a duplicate non-unique auto-index)
- [x] 4.6 Confirm `Precio.producto_presentacion` relationship resolves to a `ProductoPresentacion` instance, and `ProductoPresentacion.precios` resolves to a list of `Precio` instances
- [x] 4.7 Confirm `Precio.__tablename__ == "producto_precios"`
- [x] 4.8 Confirm `ProductoPresentacion.__tablename__ == "producto_presentaciones"` (post-rename)
- [x] 4.9 Confirm `Base.metadata` registers all 9 expected tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentaciones`, `producto_precios`); explicit check that the singular `producto_presentacion` is **not** present as a leaked old tablename
