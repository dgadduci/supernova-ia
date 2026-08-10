"""Guided draft-order closure orchestrators.

The four `consultar_resumen_pedido`, `set_metodo_de_entrega`,
`set_metodo_de_pago`, and `confirmar_pedido` intents all operate exclusively
against the conversation session's associated `borrador` pedido. Each
orchestrator returns a typed `ProcessedIntent` whose `status` is one of:

- `executed` — a permitted mutation succeeded (or, for summary, a complete
  read was produced). For `confirmar_pedido` this is the single
  `borrador → ingresado` transition.
- `rejected` — a valid business outcome that mutates nothing: missing or
  non-borrador pedido, empty pedido, missing required choice, ambiguous,
  inactive, or commerce-foreign choice, already-confirmed pedido, etc.
- `failed` — reserved for technical exceptions. These propagate to the
  existing transactional owner (`process_incoming_message_transactional`
  or `ProviderInboundMessageCoordinator.process_lease`), which performs
  the full-turn rollback. They never become customer-success responses.

The orchestrators never `commit`, `rollback`, `flush`, `refresh`, `begin`,
or `close` the SQLAlchemy session; they only stage attribute changes that
the outer transaction owns.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import EstadoPedido, MediosPago, MetodosEntrega, Pedido
from backend.models.session import Session as ConversationSession
from backend.repositories.medios_pago_repository import MediosPagoRepository
from backend.repositories.metodo_entrega_repository import MetodoEntregaRepository
from backend.services.pedido_producto_service import PedidoProductoService


def _normalize_choice(text: str) -> str:
    """Lowercase, accent-strip, collapse whitespace. Mirrors the project's
    established normalization so that user text and catalog `codigo`/
    `descripcion` values compare on the same canonical form.
    """
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9ñ\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def _load_session_pedido(
    db: DatabaseSession,
    session: ConversationSession,
) -> Pedido | None:
    pedido_id = session.id_pedido
    if pedido_id is None:
        return None
    return db.get(Pedido, int(pedido_id))


def _rejected(
    intent_name: str,
    source_text: str,
    reason: str,
    recognizer: str,
    handler: str,
    **extras: Any,
) -> ProcessedIntent:
    resolved_data: dict[str, Any] = {"reason": reason}
    resolved_data.update(extras)
    return ProcessedIntent(
        intent=intent_name,
        source_text=source_text,
        status="rejected",
        recognizer=recognizer,
        handler=handler,
        resolved_data=resolved_data,
    )


def process_initial_consultar_resumen_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Describe the persisted borrador's lines and selected choices.

    The orchestrator never mutates the pedido, its lines, the session, or
    any pending context.
    """
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            "consultar_resumen_pedido",
            source_text,
            "no_draft",
            "draft_order_closure",
            "consultar_resumen_pedido",
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            "consultar_resumen_pedido",
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            "consultar_resumen_pedido",
        )

    lines_summary: list[dict[str, Any]] = []
    for line in PedidoProductoService(db).list_by_pedido(pedido.id):
        presentacion = line.producto_presentacion.presentacion
        producto = line.producto_presentacion.producto
        lines_summary.append(
            {
                "pedido_producto_id": line.id,
                "producto_nombre": producto.nombre,
                "presentacion_codigo": presentacion.codigo,
                "cantidad": line.cantidad,
            }
        )

    medio_pago_label: str | None = None
    if pedido.id_medio_pago is not None:
        medio_pago = db.get(MediosPago, int(pedido.id_medio_pago))
        if medio_pago is not None:
            medio_pago_label = f"{medio_pago.codigo} ({medio_pago.descripcion})"

    metodo_entrega_label: str | None = None
    if pedido.id_metodo_entrega is not None:
        metodo_entrega = db.get(MetodosEntrega, int(pedido.id_metodo_entrega))
        if metodo_entrega is not None:
            metodo_entrega_label = f"{metodo_entrega.codigo} ({metodo_entrega.descripcion})"

    resolved_data: dict[str, Any] = {
        "pedido_id": pedido.id,
        "estado_pedido": pedido.estado_pedido.value,
        "lineas": lines_summary,
        "tiene_lineas": bool(lines_summary),
        "medio_pago": medio_pago_label,
        "metodo_entrega": metodo_entrega_label,
    }
    return ProcessedIntent(
        intent="consultar_resumen_pedido",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="consultar_resumen_pedido",
        resolved_data=resolved_data,
    )


def _match_choice(
    *,
    candidates: list[Any],
    raw_text: str,
) -> tuple[Any | None, str]:
    """Return `(match, reason)` for a single normalized user choice.

    Compares the normalized user text against the normalized `codigo` and
    `descripcion` of each candidate. Returns `(None, "missing")` when no
    choice was supplied, `(None, "ambiguous")` when more than one candidate
    matches, `(None, "not_active")` when no candidate matches, or
    `(candidate, "unique")` when exactly one candidate matches.
    """
    normalized = _normalize_choice(raw_text)
    if not normalized:
        return None, "missing"

    matches: list[Any] = []
    for candidate in candidates:
        codigo = getattr(candidate, "codigo", None)
        descripcion = getattr(candidate, "descripcion", None)
        if isinstance(codigo, str) and _normalize_choice(codigo) == normalized:
            matches.append(candidate)
            continue
        if isinstance(descripcion, str) and _normalize_choice(descripcion) == normalized:
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0], "unique"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "not_active"


def _set_commerce_scoped_choice(
    *,
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
    intent_name: str,
    field: str,
    repo: Any,
) -> ProcessedIntent:
    """Common flow for `set_metodo_de_pago` and `set_metodo_de_entrega`.

    Validates the session-borrador precondition, finds a unique active
    commerce-scoped match, and stages the attribute update on the
    `Pedido`. Never commits, rolls back, or flushes.
    """
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            intent_name,
            source_text,
            "no_draft",
            "draft_order_closure",
            intent_name,
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            intent_name,
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            intent_name,
        )
    comercio_id = session.id_comercio
    if comercio_id is None:
        return _rejected(
            intent_name,
            source_text,
            "no_comercio",
            "draft_order_closure",
            intent_name,
        )

    candidates = repo(db).list_active_for_comercio(int(comercio_id))
    match, reason = _match_choice(candidates=candidates, raw_text=source_text)
    if match is None:
        extras: dict[str, Any] = {"opciones": [
            {"codigo": c.codigo, "descripcion": c.descripcion} for c in candidates
        ]}
        return _rejected(
            intent_name,
            source_text,
            reason,
            "draft_order_closure",
            intent_name,
            **extras,
        )

    if field == "id_medio_pago":
        pedido.id_medio_pago = int(match.id)
        label_codigo = match.codigo
        label_descripcion = match.descripcion
    else:
        pedido.id_metodo_entrega = int(match.id)
        label_codigo = match.codigo
        label_descripcion = match.descripcion

    return ProcessedIntent(
        intent=intent_name,
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler=intent_name,
        resolved_data={
            f"{field}": int(match.id),
            "codigo": label_codigo,
            "descripcion": label_descripcion,
        },
    )


def process_initial_set_metodo_de_pago(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Set the pedido's payment method from a single normalized choice.

    Mutates only when the user supplies exactly one normalized codigo or
    descripcion that matches an active medios_pago enabled for the
    session's commerce.
    """
    return _set_commerce_scoped_choice(
        db=db,
        session=session,
        source_text=source_text,
        intent_name="set_metodo_de_pago",
        field="id_medio_pago",
        repo=MediosPagoRepository,
    )


def process_initial_set_metodo_de_entrega(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Set the pedido's delivery method from a single normalized choice.

    Mutates only when the user supplies exactly one normalized codigo or
    descripcion that matches an active metodos_entrega enabled for the
    session's commerce.
    """
    return _set_commerce_scoped_choice(
        db=db,
        session=session,
        source_text=source_text,
        intent_name="set_metodo_de_entrega",
        field="id_metodo_entrega",
        repo=MetodoEntregaRepository,
    )


def process_initial_confirmar_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Transition a complete borrador to `ingresado` exactly once.

    "Complete" means at least one persisted line, an active medios_pago
    selection enabled for the session's commerce, and an active
    metodos_entrega selection enabled for the session's commerce.
    Address, scheduled time, and payment authorization are intentionally
    not completion requirements.
    """
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "no_draft",
            "draft_order_closure",
            "confirmar_pedido",
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            "confirmar_pedido",
        )
    comercio_id = session.id_comercio

    lines = PedidoProductoService(db).list_by_pedido(pedido.id)
    if not lines:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "empty_draft",
            "draft_order_closure",
            "confirmar_pedido",
        )
    if pedido.id_medio_pago is None or comercio_id is None:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "missing_payment",
            "draft_order_closure",
            "confirmar_pedido",
        )
    active_payments = {
        int(m.id)
        for m in MediosPagoRepository(db).list_active_for_comercio(int(comercio_id))
    }
    if int(pedido.id_medio_pago) not in active_payments:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "payment_not_active_for_comercio",
            "draft_order_closure",
            "confirmar_pedido",
        )
    if pedido.id_metodo_entrega is None:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "missing_delivery",
            "draft_order_closure",
            "confirmar_pedido",
        )
    active_deliveries = {
        int(m.id)
        for m in MetodoEntregaRepository(db).list_active_for_comercio(int(comercio_id))
    }
    if int(pedido.id_metodo_entrega) not in active_deliveries:
        return _rejected(
            "confirmar_pedido",
            source_text,
            "delivery_not_active_for_comercio",
            "draft_order_closure",
            "confirmar_pedido",
        )

    pedido.estado_pedido = EstadoPedido.INGRESADO
    return ProcessedIntent(
        intent="confirmar_pedido",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="confirmar_pedido",
        resolved_data={"pedido_id": pedido.id},
    )


__all__ = [
    "process_initial_consultar_resumen_pedido",
    "process_initial_set_metodo_de_pago",
    "process_initial_set_metodo_de_entrega",
    "process_initial_confirmar_pedido",
]
