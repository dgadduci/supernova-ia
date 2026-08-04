"""Service for the persisted product alias workflow.

The service is the only place that:

* normalizes raw alias text using the recognizer-compatible
  ``_normalizar_palabras_pedido`` contract;
* rejects empty normalized values;
* verifies a presentation-specific row's ``id_producto_presentacion``
  belongs to ``id_producto``;
* performs duplicate detection and ownership validation;
* translates IntegrityError into the project's typed exceptions;
* groups aliases for recognition-ready projection.

The service NEVER calls ``commit``, ``rollback``, ``close``, or ``begin``
on its session. Transaction ownership belongs to the caller.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import ProductoAlias, ProductoPresentacion
from backend.recognizers.product_recognizer import _normalizar_palabras_pedido
from backend.repositories.producto_alias_repository import (
    ProductoAliasRepository,
)
from backend.services.exceptions import (
    DuplicateProductoAlias,
    InvalidProductoAlias,
    ProductoAliasPresentationMismatch,
)


@dataclass(frozen=True)
class AliasProjection:
    """Recognition-ready alias data for one catalog row.

    General aliases (``id_producto_presentacion is None``) are returned for
    each row whose ``id_producto`` matches. Specific aliases are returned
    only for the exact ``id_producto_presentacion`` they belong to.
    """

    id_producto: int
    id_producto_presentacion: int | None
    general_aliases: tuple[str, ...]
    specific_aliases: tuple[str, ...]

    @property
    def all_aliases(self) -> tuple[str, ...]:
        return (*self.general_aliases, *self.specific_aliases)


class ProductoAliasService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ProductoAliasRepository(session)

    @staticmethod
    def normalize(alias: str) -> str:
        if alias is None:
            raise InvalidProductoAlias("alias must not be None")
        cleaned = alias.strip().lower()
        if not cleaned:
            raise InvalidProductoAlias("alias must not be empty")
        normalized = _normalizar_palabras_pedido(cleaned)
        if not normalized:
            raise InvalidProductoAlias(
                "alias must contain at least one recognizer-normalized token"
            )
        return normalized

    def _validate_presentation_ownership(
        self,
        id_producto: int,
        id_producto_presentacion: int | None,
    ) -> None:
        if id_producto_presentacion is None:
            return
        pp = self._session.get(ProductoPresentacion, id_producto_presentacion)
        if pp is None:
            raise InvalidProductoAlias(
                f"id_producto_presentacion {id_producto_presentacion} not found"
            )
        if pp.id_producto != id_producto:
            raise ProductoAliasPresentationMismatch(
                f"id_producto_presentacion {id_producto_presentacion} "
                f"belongs to producto {pp.id_producto}, not {id_producto}"
            )

    def create(
        self,
        id_producto: int,
        alias: str,
        id_producto_presentacion: int | None = None,
        activo: bool | None = True,
    ) -> ProductoAlias:
        normalized = self.normalize(alias)
        self._validate_presentation_ownership(
            id_producto, id_producto_presentacion
        )
        existing = self._repo.find_same_scope(
            id_producto,
            id_producto_presentacion,
            normalized,
            include_inactive=True,
        )
        if existing is not None:
            raise DuplicateProductoAlias(
                f"alias {normalized!r} already present for producto "
                f"{id_producto} presentation {id_producto_presentacion}"
            )
        try:
            return self._repo.create(
                id_producto,
                id_producto_presentacion,
                alias.strip(),
                normalized,
                activo,
            )
        except IntegrityError as exc:
            raise DuplicateProductoAlias(str(exc.orig)) from exc

    def ensure(
        self,
        id_producto: int,
        alias: str,
        id_producto_presentacion: int | None = None,
    ) -> ProductoAlias:
        """Idempotent create used by the seeder.

        Returns the existing row when one already exists in the same scope;
        otherwise creates and returns a new active row.
        """
        normalized = self.normalize(alias)
        self._validate_presentation_ownership(
            id_producto, id_producto_presentacion
        )
        existing = self._repo.find_same_scope(
            id_producto,
            id_producto_presentacion,
            normalized,
            include_inactive=True,
        )
        if existing is not None:
            return existing
        return self._repo.create(
            id_producto,
            id_producto_presentacion,
            alias.strip(),
            normalized,
            True,
        )

    def project_recognition_data(
        self,
        catalog_rows: Iterable[dict],
    ) -> dict[tuple[int, int | None], AliasProjection]:
        """Return recognition-ready alias data for each catalog row.

        Catalog rows must expose ``producto_presentacion_id`` and
        ``producto_id``. The result is keyed by
        ``(producto_id, producto_presentacion_id)`` so the caller can attach
        aliases to the exact rows it supplied.
        """
        rows = list(catalog_rows)
        if not rows:
            return {}
        id_producto_values = sorted({row["producto_id"] for row in rows})
        id_producto_presentacion_values = sorted(
            {row["producto_presentacion_id"] for row in rows}
        )
        aliases = self._repo.list_recognition_data(
            id_producto_values,
            id_producto_presentacion_values,
        )
        general_by_producto: dict[int, list[str]] = {pid: [] for pid in id_producto_values}
        specific_by_pp: dict[int, list[str]] = {
            ppid: [] for ppid in id_producto_presentacion_values
        }
        for alias in aliases:
            if alias.id_producto_presentacion is None:
                general_by_producto.setdefault(alias.id_producto, []).append(
                    alias.alias_normalizado
                )
            else:
                specific_by_pp.setdefault(alias.id_producto_presentacion, []).append(
                    alias.alias_normalizado
                )
        result: dict[tuple[int, int | None], AliasProjection] = {}
        for row in rows:
            pid = row["producto_id"]
            ppid = row["producto_presentacion_id"]
            result[(pid, ppid)] = AliasProjection(
                id_producto=pid,
                id_producto_presentacion=ppid,
                general_aliases=tuple(general_by_producto.get(pid, ())),
                specific_aliases=tuple(specific_by_pp.get(ppid, ())),
            )
        return result


__all__ = ["AliasProjection", "ProductoAliasService"]
