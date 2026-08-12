"""Guided draft-order closure orchestrators.

The `consultar_resumen_pedido`, `set_metodo_de_entrega`,
`set_metodo_de_pago`, `set_observacion_pedido`,
`set_direccion_entrega`, and `confirmar_pedido` intents all operate
exclusively against the conversation session's associated `borrador`
pedido. Each orchestrator returns a typed `ProcessedIntent` whose
`status` is one of:

- `executed` — a permitted mutation succeeded (or, for summary, a complete
  read was produced). For `confirmar_pedido` this is the single
  `borrador → ingresado` transition. For `set_observacion_pedido` this is
  the single replacement of `pedidos.observaciones` with the normalized
  in-range text. For `set_direccion_entrega` this is the single
  replacement of `pedidos.direccion_entrega` with the normalized
  in-range text.
- `rejected` — a valid business outcome that mutates nothing: missing or
  non-borrador pedido, empty pedido, missing required choice, ambiguous,
  inactive, or commerce-foreign choice, already-confirmed pedido,
  out-of-range observation text, out-of-range address text, etc.
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
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import EstadoPedido, MediosPago, MetodosEntrega, Pedido
from backend.models.session import EstadoSession
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
    `descripcion` of each candidate. Exact normalized code/description
    equality is authoritative. When no exact match exists, falls back to
    description-token containment: a candidate description qualifies only
    when every whitespace-delimited token of its normalized description
    appears as a whole token in the normalized customer text. Candidate
    `codigo` tokens, substrings, edit distance, synonyms, LLM, and any
    candidate outside the repository-supplied set are never considered.

    Returns `(None, "missing")` when no choice was supplied,
    `(None, "ambiguous")` when more than one candidate qualifies at any
    stage, `(None, "not_active")` when none qualifies, or
    `(candidate, "unique")` when exactly one candidate qualifies.
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

    input_tokens = set(normalized.split())
    fallback_matches: list[Any] = []
    for candidate in candidates:
        descripcion = getattr(candidate, "descripcion", None)
        if not isinstance(descripcion, str):
            continue
        normalized_desc = _normalize_choice(descripcion)
        if not normalized_desc:
            continue
        desc_tokens = set(normalized_desc.split())
        if not desc_tokens or not desc_tokens.issubset(input_tokens):
            continue
        fallback_matches.append(candidate)
    if len(fallback_matches) == 1:
        return fallback_matches[0], "unique"
    if len(fallback_matches) > 1:
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


_OBSERVATION_MIN_LENGTH = 1
_OBSERVATION_MAX_LENGTH = 500


def _normalize_observacion(text: str) -> str:
    """Normalize a free-text observation for `set_observacion_pedido`.

    The function applies Unicode NFKC normalization to fold compatibility
    forms (full-width spaces, ligatures, etc.), then strips leading and
    trailing whitespace (Python's built-in ``str.strip()`` removes every
    code point classified as whitespace by ``unicodedata.category``),
    then collapses any internal run of whitespace into a single ASCII
    space using a Unicode-aware regex.

    The function never truncates, never strips courtesies, never
    lowercases, never reclassifies, and never alters the codepoints of
    non-whitespace characters. The returned string's length is measured
    in code points.
    """
    normalized = unicodedata.normalize("NFKC", text)
    stripped = normalized.strip()
    return re.sub(r"\s+", " ", stripped, flags=re.UNICODE)


def process_initial_set_observacion_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Replace the borrador pedido's general observation with the normalized text.

    The orchestrator uses exclusively `session.id_pedido` as the target
    authority. It validates `Pedido.id_session == session.id` and
    `pedido.estado_pedido == BORRADOR` before staging any write. The
    text is normalized (NFKC + strip + Unicode whitespace collapse) and
    accepted only when its length is in the closed interval
    `[1, 500]` code points. A valid value replaces the prior
    `pedidos.observaciones` value (which may be `NULL` or a previous
    accepted text). An empty, whitespace-only, or too-long value is a
    non-mutating rejection that preserves the prior value.

    The orchestrator never reclassifies, never invokes the LLM, never
    consults the product recognizer, never reads or writes
    `PedidoProducto.observaciones`, never widens or modifies any
    pending candidate set, and never takes transaction ownership. The
    `CustomerResponse` text never carries the raw or normalized
    observation text; the `resolved_data` carries only a stable reason
    code on rejection and a non-revealing `accepted_length` on success.
    """
    if session.estado_session != EstadoSession.ACTIVA:
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "session_not_active",
            "draft_order_closure",
            "set_observacion_pedido",
        )
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "no_draft",
            "draft_order_closure",
            "set_observacion_pedido",
        )
    if int(pedido.id_session) != int(session.id):
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "session_mismatch",
            "draft_order_closure",
            "set_observacion_pedido",
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            "set_observacion_pedido",
        )

    normalized = _normalize_observacion(source_text)
    length = len(normalized)
    if length < _OBSERVATION_MIN_LENGTH:
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "text_empty",
            "draft_order_closure",
            "set_observacion_pedido",
        )
    if length > _OBSERVATION_MAX_LENGTH:
        return _rejected(
            "set_observacion_pedido",
            source_text,
            "text_too_long",
            "draft_order_closure",
            "set_observacion_pedido",
        )

    pedido.observaciones = normalized
    return ProcessedIntent(
        intent="set_observacion_pedido",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="set_observacion_pedido",
        resolved_data={"accepted_length": length},
    )


_DIRECCION_ENTREGA_MIN_LENGTH = 1
_DIRECCION_ENTREGA_MAX_LENGTH = 500


def _normalize_direccion_entrega(text: str) -> str:
    """Normalize a concrete delivery address for `set_direccion_entrega`.

    Applies Unicode NFKC normalization to fold compatibility forms
    (full-width spaces, ligatures, etc.), then strips leading and
    trailing whitespace (Python's built-in ``str.strip()`` removes every
    code point classified as whitespace by ``unicodedata.category``),
    then collapses any internal run of whitespace into a single ASCII
    space using a Unicode-aware regex.

    The function never truncates, never extracts components, never
    lowercases, never infers delivery method, never geocodes, never
    reclassifies, and never alters the codepoints of non-whitespace
    characters. The returned string's length is measured in code
    points.
    """
    normalized = unicodedata.normalize("NFKC", text)
    stripped = normalized.strip()
    return re.sub(r"\s+", " ", stripped, flags=re.UNICODE)


def process_initial_set_direccion_entrega(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Replace the borrador pedido's concrete delivery address with the normalized text.

    The orchestrator uses exclusively ``session.id_pedido`` as the target
    authority. It validates that the session is active, that
    ``Pedido.id_session == session.id``, and that
    ``pedido.estado_pedido == BORRADOR`` before staging any write. The
    text is normalized (NFKC + strip + Unicode whitespace collapse) and
    accepted only when its length is in the closed interval
    ``[1, 500]`` code points. A valid value replaces the prior
    ``pedidos.direccion_entrega`` value (which may be ``NULL`` or a
    previous accepted text). An empty, whitespace-only, or too-long
    value is a non-mutating rejection that preserves the prior value.

    The orchestrator never reclassifies, never invokes the LLM, never
    consults the product recognizer, never reads or writes
    ``Pedido.observaciones`` or ``PedidoProducto.observaciones``, never
    infers or assigns a delivery method, never widens or modifies any
    pending candidate set, never consults payment or scheduling state,
    and never takes transaction ownership. The ``CustomerResponse`` text
    never carries the raw or normalized address; ``resolved_data``
    carries only a stable reason code on rejection and a non-revealing
    ``accepted_length`` on success.
    """
    if session.estado_session != EstadoSession.ACTIVA:
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "session_not_active",
            "draft_order_closure",
            "set_direccion_entrega",
        )
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "no_draft",
            "draft_order_closure",
            "set_direccion_entrega",
        )
    if int(pedido.id_session) != int(session.id):
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "session_mismatch",
            "draft_order_closure",
            "set_direccion_entrega",
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            "set_direccion_entrega",
        )

    normalized = _normalize_direccion_entrega(source_text)
    length = len(normalized)
    if length < _DIRECCION_ENTREGA_MIN_LENGTH:
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "text_empty",
            "draft_order_closure",
            "set_direccion_entrega",
        )
    if length > _DIRECCION_ENTREGA_MAX_LENGTH:
        return _rejected(
            "set_direccion_entrega",
            source_text,
            "text_too_long",
            "draft_order_closure",
            "set_direccion_entrega",
        )

    pedido.direccion_entrega = normalized
    return ProcessedIntent(
        intent="set_direccion_entrega",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="set_direccion_entrega",
        resolved_data={"accepted_length": length},
    )


_DELIVERY_SCHEDULE_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")
_DELIVERY_SCHEDULE_FORMATS = (
    (
        r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}",
        "%d/%m/%Y %H:%M",
        "dd/mm/yyyy_hh:mm",
    ),
    (
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}",
        "%Y-%m-%d %H:%M",
        "yyyy-mm-dd_hh:mm",
    ),
)


def _parse_fecha_hora_entrega(source_text: str) -> tuple[datetime, str] | None:
    stripped = source_text.strip()
    for pattern, format_value, accepted_format in _DELIVERY_SCHEDULE_FORMATS:
        if re.fullmatch(pattern, stripped) is None:
            continue
        try:
            parsed_datetime = datetime.strptime(
                f"{stripped}+0000",
                f"{format_value}%z",
            ).replace(tzinfo=_DELIVERY_SCHEDULE_TIMEZONE)
        except ValueError:
            continue
        return parsed_datetime, accepted_format
    return None


def _is_future_fecha_hora_entrega(
    parsed_datetime: datetime,
    *,
    now: datetime | None = None,
) -> bool:
    reference_datetime = (
        now if now is not None else datetime.now(_DELIVERY_SCHEDULE_TIMEZONE)
    )
    return parsed_datetime > reference_datetime


def process_initial_set_fecha_hora_entrega(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    if session.estado_session != EstadoSession.ACTIVA:
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "session_not_active",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "no_draft",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )
    if int(pedido.id_session) != int(session.id):
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "session_mismatch",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "pedido_not_borrador",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )

    parsed = _parse_fecha_hora_entrega(source_text)
    if parsed is None:
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "invalid_format",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )
    parsed_datetime, accepted_format = parsed
    if not _is_future_fecha_hora_entrega(parsed_datetime):
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            "past_datetime",
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )

    pedido.datetime_entrega_programada = parsed_datetime
    return ProcessedIntent(
        intent="set_fecha_hora_entrega",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="set_fecha_hora_entrega",
        resolved_data={"accepted_format": accepted_format},
    )


__all__ = [
    "process_initial_confirmar_pedido",
    "process_initial_consultar_resumen_pedido",
    "process_initial_set_direccion_entrega",
    "process_initial_set_fecha_hora_entrega",
    "process_initial_set_metodo_de_entrega",
    "process_initial_set_metodo_de_pago",
    "process_initial_set_observacion_pedido",
]
