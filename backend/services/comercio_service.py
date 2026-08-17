from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import Comercio
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.repositories.comercio_repository import ComercioRepository
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicateSlug,
    DuplicateWhatsapp,
    EstadoComercioNotFound,
    EstadoComercioNotSelectable,
    InvalidTrialConfiguration,
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

    def _normalise_lifecycle_payload(
        self,
        payload: dict,
        *,
        require_routing_identifiers: bool = True,
    ) -> tuple[dict, datetime | None, int | None]:
        cleaned: dict = {
            k: (_strip(v) if isinstance(v, str) else v)
            for k, v in payload.items()
        }
        cleaned = {
            k: v
            for k, v in cleaned.items()
            if v != "" or k in {"piso_departamento", "codigo_postal"}
        }
        if "prueba_pedidos_consumidos_reset" in cleaned:
            raise ValueError(
                "prueba_pedidos_consumidos_reset no es controlable desde el payload; "
                "lo decide la transición de modo dentro del servicio."
            )
        required = [
            "nombre_fantasia",
            "nombre_corto",
            "razon_social",
            "cuit",
        ]
        if require_routing_identifiers:
            required += [
                "whatsapp",
                "calle",
                "numero",
                "localidad",
                "provincia",
                "slug",
            ]
        else:
            required += [
                "calle",
                "numero",
                "localidad",
                "provincia",
            ]
        for key in required:
            if not cleaned.get(key):
                raise ValueError(f"{key} must not be empty")

        prueba_hasta = cleaned.pop("prueba_hasta", None)
        prueba_max_pedidos = cleaned.pop("prueba_max_pedidos", None)
        return cleaned, prueba_hasta, prueba_max_pedidos

    def _validate_trial_for_estado(
        self,
        *,
        estado_id: int,
        prueba_hasta: datetime | None,
        prueba_max_pedidos: int | None,
    ) -> EstadoComercioModoOperacion:
        modo = self._repo.estado_modo(estado_id)
        if modo is None:
            raise EstadoComercioNotFound(estado_id)
        if modo is not EstadoComercioModoOperacion.PRUEBA:
            if prueba_hasta is not None or prueba_max_pedidos is not None:
                raise InvalidTrialConfiguration(
                    "Los comercios no en PRUEBA no admiten fecha ni cupo de prueba."
                )
            return modo
        if prueba_hasta is None:
            raise InvalidTrialConfiguration(
                "El estado PRUEBA exige una fecha de fin de prueba."
            )
        if prueba_max_pedidos is None:
            raise InvalidTrialConfiguration(
                "El estado PRUEBA exige un máximo de pedidos confirmados."
            )
        if not isinstance(prueba_max_pedidos, int) or isinstance(
            prueba_max_pedidos, bool
        ) or prueba_max_pedidos <= 0:
            raise InvalidTrialConfiguration(
                "El máximo de pedidos debe ser un entero positivo."
            )
        if not isinstance(prueba_hasta, datetime):
            raise InvalidTrialConfiguration(
                "La fecha de fin de prueba debe ser un datetime con zona horaria."
            )
        if prueba_hasta.tzinfo is None or prueba_hasta.utcoffset() is None:
            raise InvalidTrialConfiguration(
                "La fecha de fin de prueba debe incluir zona horaria."
            )
        if prueba_hasta <= datetime.now(tz=prueba_hasta.tzinfo):
            raise InvalidTrialConfiguration(
                "La fecha de fin de prueba debe ser futura."
            )
        return modo

    def _assert_estado_seleccionable(self, estado_id: int) -> None:
        if not self._repo.estado_seleccionable(estado_id):
            raise EstadoComercioNotSelectable(
                "El estado seleccionado no admite asignación desde la "
                "administración; conserve la referencia histórica o use "
                "un estado seleccionable."
            )

    def create(self, payload: dict) -> Comercio:
        cleaned, prueba_hasta, prueba_max_pedidos = (
            self._normalise_lifecycle_payload(
                payload, require_routing_identifiers=True
            )
        )

        estado_id = cleaned.get("estado_id")
        if not isinstance(estado_id, int) or isinstance(estado_id, bool):
            raise ValueError("estado_id must be a positive integer")  # noqa: TRY004

        self._assert_estado_seleccionable(estado_id)

        self._validate_trial_for_estado(
            estado_id=estado_id,
            prueba_hasta=prueba_hasta,
            prueba_max_pedidos=prueba_max_pedidos,
        )

        if not self._repo.estado_exists(estado_id):
            raise EstadoComercioNotFound(estado_id)
        if self._repo.get_by_whatsapp(cleaned["whatsapp"]) is not None:
            raise DuplicateWhatsapp(cleaned["whatsapp"])
        if self._repo.get_by_slug(cleaned["slug"]) is not None:
            raise DuplicateSlug(cleaned["slug"])

        cleaned["prueba_hasta"] = prueba_hasta
        cleaned["prueba_max_pedidos"] = prueba_max_pedidos
        cleaned["prueba_pedidos_consumidos"] = 0

        try:
            comercio = self._repo.create(cleaned)
            self._session.flush()
            self._session.refresh(comercio, attribute_names=["flavor_comunicacion"])
            self._session.commit()
            return comercio
        except Exception:
            self._session.rollback()
            raise

    _EDIT_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
        {"whatsapp", "slug", "flavor_comunicacion_id", "id"}
    )

    def update(self, comercio_id: int, payload: dict) -> Comercio:
        """Update only the documented permitted basic fields of a Comercio.

        The method is the single authoritative update boundary for
        the ``Comercio`` row. It accepts a payload containing only the
        closed scalar fields documented by the OpenSpec change
        (``profile``, ``address``, ``estado_id``, ``zona_horaria``,
        ``moneda``, ``idioma``, ``prueba_hasta``,
        ``prueba_max_pedidos``). Routing identifiers (``whatsapp`` /
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

        The service rejects every ``estado_id`` that is not marked
        ``seleccionable`` so a forged or stale submission cannot
        move a commerce into SUSPENDIDO, BAJA, or any other historical
        blocked configuration.

        Trial transitions are validated against the configured
        operating mode. Entering PRUEBA from a non-trial mode
        requires a future deadline and a positive quota and
        atomically resets ``prueba_pedidos_consumidos`` to zero;
        editing an already-PRUEBA commerce updates the limits but
        preserves the prior counter; leaving PRUEBA preserves the
        last deadline, quota and counter as read-only historical
        configuration that the availability policy simply ignores
        outside PRUEBA. The reset decision is derived exclusively
        from the previous / new mode transition inside the service;
        ``prueba_pedidos_consumidos_reset`` cannot be supplied by the
        caller.
        """
        forbidden = set(payload.keys()) & self._EDIT_IMMUTABLE_FIELDS
        if forbidden:
            raise ValueError(
                "Los identificadores de ruteo son inmutables: "
                + ", ".join(sorted(forbidden))
            )

        cleaned, prueba_hasta, prueba_max_pedidos = (
            self._normalise_lifecycle_payload(
                payload, require_routing_identifiers=False
            )
        )

        cleaned_piso = cleaned.get("piso_departamento") or None
        cleaned_cp = cleaned.get("codigo_postal") or None
        estado_id = cleaned.get("estado_id")
        if not isinstance(estado_id, int) or isinstance(estado_id, bool):
            raise ValueError("estado_id must be a positive integer")  # noqa: TRY004  # noqa: TRY004

        try:
            comercio = self._repo.get_by_id(comercio_id)
            if comercio is None:
                raise ComercioNotFound(comercio_id)
            self._assert_estado_seleccionable(estado_id)
            if not self._repo.estado_exists(estado_id):
                raise EstadoComercioNotFound(estado_id)
            previous_modo = self._repo.estado_modo(comercio.estado_id)
            new_modo = self._validate_trial_for_estado(
                estado_id=estado_id,
                prueba_hasta=prueba_hasta,
                prueba_max_pedidos=prueba_max_pedidos,
            )
            entering_trial = (
                previous_modo is not EstadoComercioModoOperacion.PRUEBA
                and new_modo is EstadoComercioModoOperacion.PRUEBA
            )
            preserve_trial_config = (
                previous_modo is EstadoComercioModoOperacion.PRUEBA
                and new_modo is not EstadoComercioModoOperacion.PRUEBA
            )
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
                prueba_hasta=prueba_hasta,
                prueba_max_pedidos=prueba_max_pedidos,
                reset_counter_on_entry=entering_trial,
                preserve_trial_config=preserve_trial_config,
            )
            self._session.flush()
            self._session.refresh(comercio, attribute_names=["flavor_comunicacion"])
            self._session.commit()
            return comercio
        except Exception:
            self._session.rollback()
            raise