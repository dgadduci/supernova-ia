"""Selection service for the global communication flavor catalog.

The service is the single application boundary that mutates
``Comercio.flavor_comunicacion_id``. It enforces:

* the flavor must exist globally;
* the flavor must be active;
* only the targeted comercio is mutated;
* the caller-owned transaction is preserved: the repository uses
  ``flush()`` and never commits / rolls back.

It does not mutate ``descripcion`` or ``instruccion_llm`` because the
catalog is system-managed seed data and the OpenSpec contract forbids
commerce-provided flavor text.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import Comercio, FlavorComunicacion
from backend.repositories.comercio_repository import ComercioRepository
from backend.repositories.flavor_comunicacion_repository import (
    FlavorComunicacionRepository,
)
from backend.services.exceptions import (
    ComercioNotFound,
    FlavorComunicacionInactivo,
    FlavorComunicacionNotFound,
)


class ComunicacionFlavorService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._flavor_repo = FlavorComunicacionRepository(session)
        self._comercio_repo = ComercioRepository(session)

    def list_active_flavors(self) -> list[FlavorComunicacion]:
        return self._flavor_repo.list_active()

    def assign_to_comercio(
        self, comercio_id: int, flavor_id: int
    ) -> tuple[Comercio, FlavorComunicacion]:
        """Set ``comercio.flavor_comunicacion_id`` to ``flavor_id``.

        Raises:
            ComercioNotFound: if the comercio does not exist.
            FlavorComunicacionNotFound: if the flavor is unknown.
            FlavorComunicacionInactivo: if the flavor is inactive.

        The selection is rejected before any mutation so the caller
        can rely on a transactional all-or-nothing outcome.
        """
        comercio = self._comercio_repo.get_by_id(comercio_id)
        if comercio is None:
            raise ComercioNotFound(comercio_id)
        flavor = self._flavor_repo.get_by_id(flavor_id)
        if flavor is None:
            raise FlavorComunicacionNotFound(flavor_id)
        if not flavor.activo:
            raise FlavorComunicacionInactivo(flavor_id)
        if comercio.flavor_comunicacion_id == flavor.id:
            return comercio, flavor
        self._comercio_repo.set_flavor_comunicacion(comercio, flavor.id)
        self._session.flush()
        return comercio, flavor


__all__ = ["ComunicacionFlavorService"]
