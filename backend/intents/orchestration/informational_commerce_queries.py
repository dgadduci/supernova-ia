"""Read-only informational commerce queries orchestrators.

This module handles the six approved informational intents emitted by the
classifier when the session has no pending context:

* ``ver_menu`` — list the current commerce's active, available, sellable
  catalog in configured order.
* ``consultar_producto`` — detail one product (with its sellable
  presentation prices) when the classified source text contains
  exactly one sellable catalog product name/presentation; otherwise
  request clarification.
* ``ver_metodos_de_pago`` — list the current commerce's active payment
  options.
* ``ver_metodos_de_entrega`` — list the current commerce's active
  delivery options.
* ``consultar_domicilio_comercio`` — render the current commerce's
  address.
* ``consultar_horarios_comercio`` — fixed "not configured" reply, only
  when the supplied session's commerce actually exists in the catalog.

The orchestrators are read-only and deterministic. They never ``commit``,
``rollback``, ``flush``, ``refresh``, ``begin`` or ``close`` the database
session; they stage no attribute changes. ``session.id_comercio`` is
the sole authority for every lookup: no lookup accepts a commerce id
from the message and no lookup switches commerce. Missing commerce and
any technical failure (database error, repository exception, etc.)
propagate to the caller-owned transaction unchanged and never become an
empty business response.

The orchestrator depends only on services; it never imports a
repository directly. Each service is the sole owner of its
repository delegation, so the orchestrator can ask the service for
the commerce-scoped read it needs without breaking the service-layer
boundary.

The orchestrators never invoke the Fuzzy/Hybrid recognizers, never
widen or modify pending candidate sets and never log raw message text.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.intent_classification import ClassifiedIntent, IntentName
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.comercio_service import ComercioService
from backend.services.configuracion_comercio_service import ConfiguracionComercioService
from backend.services.medios_pago_service import MediosPagoService
from backend.services.metodo_entrega_service import MetodoEntregaService
from backend.services.producto_query_service import ProductoQueryService

INFORMATIONAL_COMMERCE_HANDLER = "informational_commerce_queries"

_INFORMATIONAL_INTENTS: frozenset[str] = frozenset({
    IntentName.VER_MENU.value,
    IntentName.CONSULTAR_PRODUCTO.value,
    IntentName.VER_METODOS_DE_PAGO.value,
    IntentName.VER_METODOS_DE_ENTREGA.value,
    IntentName.CONSULTAR_DOMICILIO_COMERCIO.value,
    IntentName.CONSULTAR_HORARIOS_COMERCIO.value,
})


def is_informational_commerce_intent(intent_name: str) -> bool:
    """Return ``True`` when ``intent_name`` is one of the approved
    informational intents handled by this module.
    """
    return intent_name in _INFORMATIONAL_INTENTS


def _normalize(text: str) -> str:
    """Lowercase, accent-strip, collapse whitespace. Mirrors the project's
    established normalization so user text and catalog ``codigo`` /
    ``descripcion`` values compare on the same canonical form.
    """
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9ñ\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def _require_comercio_id(session: ConversationSession) -> int:
    """Return ``session.id_comercio`` or raise ``ComercioNotFound`` so
    missing commerce surfaces as a technical failure that propagates
    to the caller-owned transaction.

    The session column itself is non-null, but defensive validation
    prevents tests/edges from silently producing empty business
    responses when the column is unset.
    """
    comercio_id = getattr(session, "id_comercio", None)
    if comercio_id is None:
        from backend.services.exceptions import ComercioNotFound
        raise ComercioNotFound(-1)
    return int(comercio_id)


def _executed(
    intent_name: str,
    source_text: str,
    *,
    resolved_data: dict[str, Any],
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent_name,
        source_text=source_text,
        status="executed",
        recognizer=INFORMATIONAL_COMMERCE_HANDLER,
        handler=INFORMATIONAL_COMMERCE_HANDLER,
        resolved_data=resolved_data,
    )


def _rejected(
    intent_name: str,
    source_text: str,
    *,
    reason: str,
    **extras: Any,
) -> ProcessedIntent:
    resolved_data: dict[str, Any] = {"reason": reason}
    resolved_data.update(extras)
    return ProcessedIntent(
        intent=intent_name,
        source_text=source_text,
        status="rejected",
        recognizer=INFORMATIONAL_COMMERCE_HANDLER,
        handler=INFORMATIONAL_COMMERCE_HANDLER,
        resolved_data=resolved_data,
    )


def _resolve_menu(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Return the executed menu listing or a rejected ``no_items`` outcome.

    The catalog is sourced through :class:`ProductoQueryService` so
    the active/available/sellable filter and configured ordering are
    owned by the existing service. The commerce comes exclusively from
    ``session.id_comercio``.
    """
    comercio_id = _require_comercio_id(session)
    products = ProductoQueryService(db).list_vendibles(comercio_id)

    items: list[dict[str, str]] = []
    for product in products:
        categoria_nombre = (
            product.categoria.descripcion if product.categoria else ""
        )
        for pp in product.presentaciones:
            items.append(
                {
                    "categoria_nombre": categoria_nombre,
                    "producto_nombre": product.nombre,
                    "presentacion_codigo": pp.presentacion.codigo,
                    "presentacion_descripcion": pp.presentacion.descripcion,
                }
            )

    if not items:
        return _rejected(
            IntentName.VER_MENU.value,
            source_text,
            reason="no_items",
        )
    return _executed(
        IntentName.VER_MENU.value,
        source_text,
        resolved_data={"items": items},
    )


def _match_products(
    source_text: str,
    products: list[Any],
) -> list[Any]:
    """Return the deterministic candidate product list.

    A product is a candidate iff it can be identified *completely*
    from the normalized classified source text. Identification is
    strict and total:

    * The product's normalized name tokens must ALL be present in
      the normalized source text (whitespace-separated, lowercased,
      accent-stripped, punctuation-collapsed).
    * OR at least one of its presentations identifies the product:
      every token of the normalized presentation code OR every
      token of the normalized presentation description is present
      in the normalized source text.

    No partial match, no token intersection, no fuzzy/hybrid
    recognizer, no edit-distance, no aliases and no synonyms are
    consulted. A single generic token (e.g. ``de``) or an isolated
    presentation token (e.g. ``grande`` from a multi-token
    description like ``Pizza Grande``) cannot select a product.

    The caller resolves the final outcome:

    * zero candidates → ``no_match`` with deterministic guidance;
    * exactly one candidate → unique product detail;
    * multiple candidates → ``ambiguous`` with deterministic guidance.
    """
    normalized_source = _normalize(source_text)
    if not normalized_source:
        return []
    source_tokens = set(normalized_source.split())

    candidates: list[Any] = []
    for product in products:
        normalized_product_name = _normalize(product.nombre)
        product_name_tokens = (
            set(normalized_product_name.split())
            if normalized_product_name
            else set()
        )
        if product_name_tokens and product_name_tokens.issubset(source_tokens):
            candidates.append(product)
            continue
        if _has_identifying_presentation(product, source_tokens):
            candidates.append(product)
    return candidates


def _has_identifying_presentation(product: Any, source_tokens: set[str]) -> bool:
    """Return ``True`` iff at least one of ``product``'s presentations
    is *fully* identified by ``source_tokens``.

    A presentation identifies the product only when **all** tokens of
    its normalized code **or** **all** tokens of its normalized
    description are contained in ``source_tokens``. Subset matching
    is exact and exhaustive; partial token intersection, prefix
    matching, fuzzy/Hybrid recognizers and synonym expansion are
    not used.
    """
    for pp in getattr(product, "presentaciones", []) or []:
        presentacion = getattr(pp, "presentacion", None)
        if presentacion is None:
            continue
        normalized_codigo = _normalize(presentacion.codigo)
        normalized_descripcion = _normalize(presentacion.descripcion)
        codigo_tokens = (
            set(normalized_codigo.split()) if normalized_codigo else set()
        )
        descripcion_tokens = (
            set(normalized_descripcion.split())
            if normalized_descripcion
            else set()
        )
        if codigo_tokens and codigo_tokens.issubset(source_tokens):
            return True
        if descripcion_tokens and descripcion_tokens.issubset(source_tokens):
            return True
    return False


def _resolve_product(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Return a unique product detail, or fixed ``no_match`` /
    ``ambiguous`` guidance.

    The deterministic match runs only against names/presentations
    fully contained in the classified source text; it never mutates
    the pending candidate set and never invokes the Fuzzy/Hybrid
    recognizer.
    """
    comercio_id = _require_comercio_id(session)
    products = ProductoQueryService(db).list_vendibles(comercio_id)
    candidates = _match_products(source_text, products)

    if not candidates:
        opciones = [
            {
                "producto_nombre": product.nombre,
                "presentacion_codigo": pp.presentacion.codigo,
            }
            for product in products
            for pp in product.presentaciones
        ]
        return _rejected(
            IntentName.CONSULTAR_PRODUCTO.value,
            source_text,
            reason="no_match",
            opciones=opciones,
        )
    if len(candidates) > 1:
        opciones = [
            {"producto_nombre": product.nombre} for product in candidates
        ]
        return _rejected(
            IntentName.CONSULTAR_PRODUCTO.value,
            source_text,
            reason="ambiguous",
            opciones=opciones,
        )

    matched_product = candidates[0]
    presentaciones: list[dict[str, object]] = []
    for pp in matched_product.presentaciones:
        precio = _first_valid_precio(pp)
        entry: dict[str, object] = {
            "producto_presentacion_id": pp.id,
            "producto_id": matched_product.id,
            "presentacion_id": pp.presentacion.id,
            "presentacion_codigo": pp.presentacion.codigo,
            "presentacion_descripcion": pp.presentacion.descripcion,
        }
        if precio is not None:
            entry["precio"] = precio
        presentaciones.append(entry)
    return _executed(
        IntentName.CONSULTAR_PRODUCTO.value,
        source_text,
        resolved_data={
            "producto_id": matched_product.id,
            "producto_nombre": matched_product.nombre,
            "categoria_nombre": matched_product.categoria.descripcion
            if matched_product.categoria
            else "",
            "presentaciones": presentaciones,
        },
    )


def _first_valid_precio(producto_presentacion: Any) -> str | None:
    """Return the first valid price string for a presentation.

    The orchestrator only knows that ``ProductoQueryService.list_vendibles``
    exposes ``precios`` on each returned ``ProductoPresentacion``. The
    repository already filters out presentations whose only price is
    negative; here we apply the same safety check defensively and
    return the price rendered as a stable two-decimal string. When the
    presentation has no valid price we return ``None`` so the caller
    can omit the field entirely instead of inventing one.
    """
    precios = getattr(producto_presentacion, "precios", None) or []
    for precio in precios:
        value = getattr(precio, "precio", None)
        if value is None:
            continue
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if decimal_value < 0:
            continue
        return f"{decimal_value.quantize(Decimal('0.01'))}"
    return None


def _resolve_metodos_de_pago(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    comercio_id = _require_comercio_id(session)
    medios = MediosPagoService(db).list_active_for_comercio(comercio_id)
    opciones = [
        {"codigo": medio.codigo, "descripcion": medio.descripcion}
        for medio in medios
    ]
    if not opciones:
        return _rejected(
            IntentName.VER_METODOS_DE_PAGO.value,
            source_text,
            reason="no_options",
        )
    return _executed(
        IntentName.VER_METODOS_DE_PAGO.value,
        source_text,
        resolved_data={"opciones": opciones},
    )


def _resolve_metodos_de_entrega(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    comercio_id = _require_comercio_id(session)
    metodos = MetodoEntregaService(db).list_active_for_comercio(comercio_id)
    opciones = [
        {"codigo": metodo.codigo, "descripcion": metodo.descripcion}
        for metodo in metodos
    ]
    if not opciones:
        return _rejected(
            IntentName.VER_METODOS_DE_ENTREGA.value,
            source_text,
            reason="no_options",
        )
    return _executed(
        IntentName.VER_METODOS_DE_ENTREGA.value,
        source_text,
        resolved_data={"opciones": opciones},
    )


def _resolve_domicilio(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    comercio_id = _require_comercio_id(session)
    comercio = ConfiguracionComercioService(db).get_by_id(comercio_id)
    return _executed(
        IntentName.CONSULTAR_DOMICILIO_COMERCIO.value,
        source_text,
        resolved_data={
            "calle": comercio.calle,
            "numero": comercio.numero,
            "piso_departamento": comercio.piso_departamento,
            "localidad": comercio.localidad,
            "provincia": comercio.provincia,
            "codigo_postal": comercio.codigo_postal,
        },
    )


def _resolve_horarios(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Return the fixed hours-not-configured outcome.

    No persisted source of operating hours exists in the catalog. We
    verify that ``session.id_comercio`` points to a real commerce via
    :class:`ComercioService` so a missing commerce propagates as a
    technical failure (``ComercioNotFound``) instead of producing an
    empty business response. Only an existing commerce can receive the
    fixed not-configured reply — we never invent a schedule.
    """
    comercio_id = _require_comercio_id(session)
    ComercioService(db).get_by_id(comercio_id)
    return _executed(
        IntentName.CONSULTAR_HORARIOS_COMERCIO.value,
        source_text,
        resolved_data={"reason": "not_configured"},
    )


_RESOLVERS = {
    IntentName.VER_MENU.value: _resolve_menu,
    IntentName.CONSULTAR_PRODUCTO.value: _resolve_product,
    IntentName.VER_METODOS_DE_PAGO.value: _resolve_metodos_de_pago,
    IntentName.VER_METODOS_DE_ENTREGA.value: _resolve_metodos_de_entrega,
    IntentName.CONSULTAR_DOMICILIO_COMERCIO.value: _resolve_domicilio,
    IntentName.CONSULTAR_HORARIOS_COMERCIO.value: _resolve_horarios,
}


def process_initial_informational_commerce_query(
    db: DatabaseSession,
    session: ConversationSession,
    classified: ClassifiedIntent,
) -> ProcessedIntent:
    """Dispatch a single informational classifier intent to its read-only
    resolver.

    The dispatcher is the single entry point invoked by
    :func:`backend.intents.orchestration.initial_intent_dispatcher.dispatch_initial_message`
    for each of the six approved informational intents. It must only be
    called when ``session.context_type is None`` (no pending context),
    because pending contexts retain absolute precedence.
    """
    intent_name = classified.intent.value
    resolver = _RESOLVERS.get(intent_name)
    if resolver is None:
        return _rejected(
            intent_name,
            classified.mensaje,
            reason="unsupported_intent",
        )
    return resolver(db, session, classified.mensaje)


__all__ = [
    "INFORMATIONAL_COMMERCE_HANDLER",
    "is_informational_commerce_intent",
    "process_initial_informational_commerce_query",
]
