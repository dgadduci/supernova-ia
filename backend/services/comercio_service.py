from sqlalchemy.orm import Session

from backend.models import Comercio
from backend.repositories.comercio_repository import ComercioRepository
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicateSlug,
    DuplicateWhatsapp,
    EstadoComercioNotFound,
)


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


class ComercioService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ComercioRepository(session)

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

        try:
            comercio = self._repo.create(cleaned)
            self._session.flush()
            self._session.refresh(comercio, attribute_names=["flavor_comunicacion"])
            self._session.commit()
            return comercio
        except Exception:
            self._session.rollback()
            raise

    _EDIT_REQUIRED_FIELDS: tuple[str, ...] = (
        "nombre_fantasia",
        "nombre_corto",
        "razon_social",
        "cuit",
        "calle",
        "numero",
        "localidad",
        "provincia",
        "zona_horaria",
        "moneda",
        "idioma",
    )
    _EDIT_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
        {"whatsapp", "slug", "flavor_comunicacion_id", "id"}
    )

    def update(self, comercio_id: int, payload: dict) -> Comercio:
        """Update only the documented permitted basic fields of a Comercio.

        The method is the single authoritative update boundary for
        the ``Comercio`` row. It accepts a payload containing only the
        closed scalar fields documented by the OpenSpec change
        (``profile``, ``address``, ``estado_id``, ``zona_horaria``,
        ``moneda``, ``idioma``). Routing identifiers (``whatsapp`` /
        ``slug``) are not part of the signature and cannot be supplied
        through this path: any value submitted under those keys is
        rejected with :class:`ValueError` before the database is
        touched, so the stored routing identity is never mutable
        through this seam.

        The service owns the commit / rollback boundary. The
        repository never calls ``commit`` / ``rollback``; it only
        stages the permitted field set on the ORM row. On any
        exception during staging, the service rolls the whole
        transaction back so the prior ``Comercio`` row is unchanged
        and no related row is modified.

        The mutation is intentionally narrow: the ``Comercio`` row's
        ``whatsapp`` / ``slug`` / lifecycle timestamps, the
        ``flavor_comunicacion`` relation, every association table
        (``medios_pago``, ``metodos_entrega``, ``canal_whatsapp`` /
        ``canal_whatsapp_compartido``), and the rest of the catalog
        graph remain untouched.
        """
        forbidden = set(payload.keys()) & self._EDIT_IMMUTABLE_FIELDS
        if forbidden:
            raise ValueError(
                "Los identificadores de ruteo son inmutables: "
                + ", ".join(sorted(forbidden))
            )

        cleaned: dict = {
            k: (_strip(v) if isinstance(v, str) else v)
            for k, v in payload.items()
        }
        cleaned = {
            k: v
            for k, v in cleaned.items()
            if v != "" or k in {"piso_departamento", "codigo_postal"}
        }

        for required in self._EDIT_REQUIRED_FIELDS:
            if not cleaned.get(required):
                raise ValueError(f"{required} must not be empty")

        cleaned_piso = cleaned.get("piso_departamento") or None
        cleaned_cp = cleaned.get("codigo_postal") or None
        estado_id = cleaned.get("estado_id")
        if not isinstance(estado_id, int) or isinstance(estado_id, bool):
            # The panel adapter and the JSON-API schema both feed
            # ``estado_id`` through Pydantic so the only way to reach
            # this branch is a forged payload or a non-integer type.
            # The service keeps ``ValueError`` to preserve the
            # bounded panel feedback contract — a ``TypeError`` would
            # bypass the route's ``except ValueError`` re-render and
            # surface as an unhandled 500.
            raise ValueError("estado_id must be a positive integer")  # noqa: TRY004

        try:
            comercio = self._repo.get_by_id(comercio_id)
            if comercio is None:
                raise ComercioNotFound(comercio_id)
            if not self._repo.estado_exists(estado_id):
                raise EstadoComercioNotFound(estado_id)
            self._repo.update_profile(
                comercio,
                nombre_fantasia=cleaned["nombre_fantasia"],
                nombre_corto=cleaned["nombre_corto"],
                razon_social=cleaned["razon_social"],
                cuit=cleaned["cuit"],
                calle=cleaned["calle"],
                numero=cleaned["numero"],
                piso_departamento=cleaned_piso,
                localidad=cleaned["localidad"],
                provincia=cleaned["provincia"],
                codigo_postal=cleaned_cp,
                estado_id=estado_id,
                zona_horaria=cleaned["zona_horaria"],
                moneda=cleaned["moneda"],
                idioma=cleaned["idioma"],
            )
            self._session.flush()
            self._session.refresh(comercio, attribute_names=["flavor_comunicacion"])
            self._session.commit()
            return comercio
        except Exception:
            self._session.rollback()
            raise
