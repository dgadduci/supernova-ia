from sqlalchemy.orm import Session

from backend.models import Comercio
from backend.repositories.comercio_repository import ComercioRepository
from backend.repositories.flavor_comunicacion_repository import (
    FlavorComunicacionRepository,
)
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicateSlug,
    DuplicateWhatsapp,
    EstadoComercioNotFound,
    FlavorComunicacionNotFound,
)


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


class ComercioService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ComercioRepository(session)
        self._flavor_repo = FlavorComunicacionRepository(session)

    def list_all(self) -> list[Comercio]:
        return self._repo.list_all()

    def get_by_id(self, comercio_id: int) -> Comercio:
        comercio = self._repo.get_by_id(comercio_id)
        if comercio is None:
            raise ComercioNotFound(comercio_id)
        return comercio

    def create(self, payload: dict) -> Comercio:
        cleaned: dict = {
            k: (_strip(v) if isinstance(v, str) else v)
            for k, v in payload.items()
        }
        cleaned = {
            k: v for k, v in cleaned.items() if v != "" or k in {"piso_departamento", "codigo_postal"}
        }

        for required in (
            "nombre_fantasia", "nombre_corto", "razon_social", "cuit", "whatsapp",
            "calle", "numero", "localidad", "provincia", "slug",
        ):
            if not cleaned.get(required):
                raise ValueError(f"{required} must not be empty")

        if not self._repo.estado_exists(cleaned["estado_id"]):
            raise EstadoComercioNotFound(cleaned["estado_id"])
        if self._repo.get_by_whatsapp(cleaned["whatsapp"]) is not None:
            raise DuplicateWhatsapp(cleaned["whatsapp"])
        if self._repo.get_by_slug(cleaned["slug"]) is not None:
            raise DuplicateSlug(cleaned["slug"])

        cleaned.pop("flavor_comunicacion_id", None)
        neutro = self._flavor_repo.get_by_codigo("neutro")
        if neutro is None or not neutro.activo:
            raise FlavorComunicacionNotFound("neutro")
        cleaned["flavor_comunicacion_id"] = neutro.id

        try:
            comercio = self._repo.create(cleaned)
            self._session.flush()
            self._session.refresh(comercio, attribute_names=["flavor_comunicacion"])
            self._session.commit()
            return comercio
        except Exception:
            self._session.rollback()
            raise
