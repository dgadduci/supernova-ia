from sqlalchemy.orm import Session

from backend.models import Comercio
from backend.repositories.configuracion_comercio_repository import (
    ConfiguracionComercioRepository,
)
from backend.services.exceptions import ComercioNotFound


class ConfiguracionComercioService:
    def __init__(self, session: Session) -> None:
        self._repo = ConfiguracionComercioRepository(session)

    def get_by_id(self, comercio_id: int) -> Comercio:
        comercio = self._repo.get_by_id(comercio_id)
        if comercio is None:
            raise ComercioNotFound(comercio_id)
        return comercio
