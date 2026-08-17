from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.models import Comercio, EstadoComercio


class ComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Comercio]:
        stmt = (
            select(Comercio)
            .options(joinedload(Comercio.flavor_comunicacion))
            .order_by(Comercio.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, comercio_id: int) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.id == comercio_id)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_whatsapp(self, whatsapp: str) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.whatsapp == whatsapp)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_slug(self, slug: str) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.slug == slug)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, payload: dict) -> Comercio:
        comercio = Comercio(**payload)
        self._session.add(comercio)
        self._session.flush()
        return comercio

    def set_flavor_comunicacion(
        self, comercio: Comercio, flavor_id: int | None
    ) -> None:
        comercio.flavor_comunicacion_id = flavor_id
        self._session.flush()

    def update_profile(
        self,
        comercio: Comercio,
        *,
        nombre_fantasia: str,
        nombre_corto: str,
        razon_social: str,
        cuit: str,
        calle: str,
        numero: str,
        piso_departamento: str | None,
        localidad: str,
        provincia: str,
        codigo_postal: str | None,
        estado_id: int,
        zona_horaria: str,
        moneda: str,
        idioma: str,
    ) -> None:
        """Stage the documented permitted profile fields on ``comercio``.

        The repository intentionally mutates **only** the closed set
        of scalar fields documented by the OpenSpec change. Routing
        identifiers (``whatsapp``, ``slug``), association tables
        (channels, payments, deliveries, catalog), flavor assignment,
        lifecycle timestamps and any other ORM-managed attribute are
        not touched. The repository does not call ``commit`` /
        ``rollback``; the caller (the service) owns the transaction.
        """
        comercio.nombre_fantasia = nombre_fantasia
        comercio.nombre_corto = nombre_corto
        comercio.razon_social = razon_social
        comercio.cuit = cuit
        comercio.calle = calle
        comercio.numero = numero
        comercio.piso_departamento = piso_departamento
        comercio.localidad = localidad
        comercio.provincia = provincia
        comercio.codigo_postal = codigo_postal
        comercio.estado_id = estado_id
        comercio.zona_horaria = zona_horaria
        comercio.moneda = moneda
        comercio.idioma = idioma
        self._session.flush()

    def estado_exists(self, estado_id: int) -> bool:
        return self._session.get(EstadoComercio, estado_id) is not None
