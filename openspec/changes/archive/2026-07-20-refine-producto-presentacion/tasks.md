## 1. Refine ProductoPresentacion constraints

- [x] 1.1 In `backend/models/producto_presentacion.py`, add imports for `CheckConstraint` and `UniqueConstraint` from sqlalchemy; add a `__table_args__` tuple declaring `UniqueConstraint("id_producto", "id_presentacion", name="producto_presentacion_unico")` and `CheckConstraint("orden >= 0", name="orden_no_negativo")`

## 2. Wire Presentacion back-reference

- [x] 2.1 In `backend/models/presentaciones.py`, add `productos_presentacion: Mapped[list["ProductoPresentacion"]] = relationship(back_populates="presentacion")` (forward-ref string for the partner class)

## 3. Verification

- [x] 3.1 Activate the project-local `venv` and run `python -c "from backend.models import ProductoPresentacion, Presentacion"` (and from a fresh interpreter, also import `Producto`) to confirm both modules load without cycle issues
- [x] 3.2 Inspect `ProductoPresentacion.__table__.constraints` and confirm: a `UniqueConstraint` named `producto_presentacion_unico` over `(id_producto, id_presentacion)`; a `CheckConstraint` named `orden_no_negativo` with SQL expression `orden >= 0`
- [x] 3.3 Confirm the existing `ProductoPresentacion` columns, FKs (`id_producto` → `productos.id` and `id_presentacion` → `presentaciones.id`, both `ondelete="CASCADE"`), defaults (`activo` `True`/`"true"`, `orden` `0`/`"0"`), and lifecycle timestamps are still correct (the change is additive, not destructive)
- [x] 3.4 Confirm `Presentacion.productos_presentacion` is a `relationship` whose partner is a list of `ProductoPresentacion` instances; `ProductoPresentacion.presentacion` partner resolves to a `Presentacion` instance
- [x] 3.5 Confirm `Base.metadata` still registers all 8 expected tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentacion`)
