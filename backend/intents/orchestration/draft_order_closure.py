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
- `pending_resolution` — for `confirmar_pedido` this is the bounded
  observation capture step after the final preconditions pass. The
  pending context never reaches the executor until the customer supplies
  either ``"no"`` or a valid 1..500 code-point observation. The
  orchestrator persists the pending context so the next inbound
  message is routed through the dedicated resolver.
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
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
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
    """Open the confirmation observation context for a complete borrador.

    ``confirmar_pedido`` is the single explicit confirmation intent and
    runs the documented active-session / own-draft / non-empty-lines /
    payment / delivery preconditions. When every precondition passes
    the orchestrator does NOT confirm the order yet: it returns a
    ``pending_resolution`` intent with a single pending
    ``observacion_pedido`` requirement so the next inbound message is
    routed through the dedicated order-confirmation observation
    resolver. The order confirmation is atomically staged by the
    same caller-owned transaction once the customer supplies either
    ``"no"`` or a valid 1..500 code-point observation. The
    finalizer is :func:`finalize_confirmar_pedido`.

    When a precondition fails the orchestrator returns the documented
    ``rejected`` outcome without mutating the pedido or the session;
    the rejection reason is the only data exposed to the response
    builder.
    """
    preconditions = _validate_confirmar_preconditions(
        db,
        session,
        source_text,
    )
    if preconditions.status != "ok":
        return preconditions.rejected
    pedido = preconditions.pedido
    assert pedido is not None

    pending = ProcessedIntent(
        intent="confirmar_pedido",
        source_text=source_text,
        status="pending_resolution",
        recognizer="draft_order_closure",
        handler="confirmar_pedido",
        resolved_data={},
        requirements=[
            RequirementState(
                name="observacion_pedido",
                status="pending",
                value=None,
            ),
        ],
        candidate_ids=[],
    )
    set_pending_intent(session, pending)
    return pending


def finalize_confirmar_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
    *,
    observation_text: str | None = None,
    skip_observation: bool = False,
) -> ProcessedIntent:
    """Atomically confirm the active draft pedido.

    The finalizer is the only authority allowed to flip
    ``pedido.estado_pedido`` from ``borrador`` to ``ingresado``. It
    re-runs the documented active-session / own-draft / non-empty-lines
    / payment / delivery preconditions immediately before staging any
    attribute write, so a stale pending context cleared by the
    transport never carries a partial confirmation forward. When the
    ``skip_observation`` flag is ``False`` and ``observation_text`` is
    not ``None``, the normalized text replaces
    ``pedido.observaciones`` in the same caller-owned transaction; any
    other combination preserves the prior ``pedido.observaciones``
    value. The function never invokes the LLM, the intent classifier,
    the product recognizer, the catalog, the order-line fuzzy
    recognizer or any session-control method
    (``commit`` / ``rollback`` / ``flush`` / ``refresh`` / ``begin`` /
    ``close``).
    """
    preconditions = _validate_confirmar_preconditions(
        db,
        session,
        source_text,
    )
    if preconditions.status != "ok":
        return preconditions.rejected

    pedido = preconditions.pedido
    assert pedido is not None
    if not skip_observation and observation_text is not None:
        pedido.observaciones = observation_text

    pedido.estado_pedido = EstadoPedido.INGRESADO
    resolved_data: dict[str, Any] = {"pedido_id": pedido.id}
    if not skip_observation and observation_text is not None:
        resolved_data["observation_accepted_length"] = len(
            pedido.observaciones or ""
        )
    return ProcessedIntent(
        intent="confirmar_pedido",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="confirmar_pedido",
        resolved_data=resolved_data,
    )


class _ConfirmarPreconditions:
    """Outcome of the documented confirmation preconditions.

    The local class is the channel through which
    :func:`process_initial_confirmar_pedido` and
    :func:`finalize_confirmar_pedido` share the precondition
    validation: ``status == "ok"`` carries the loaded pedido;
    otherwise ``rejected`` carries the deterministic rejection
    outcome. The class is only used inside this module so the
    ``__all__`` surface stays unchanged.
    """

    __slots__ = ("pedido", "rejected", "status")

    def __init__(
        self,
        *,
        status: str,
        pedido: Pedido | None,
        rejected: ProcessedIntent,
    ) -> None:
        self.status = status
        self.pedido = pedido
        self.rejected = rejected


def _validate_confirmar_preconditions(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> _ConfirmarPreconditions:
    """Validate the documented confirmation preconditions.

    The helper returns a ``_ConfirmarPreconditions`` with
    ``status == "ok"`` and the loaded ``pedido`` when every
    precondition passes and a ``rejected`` ProcessedIntent
    otherwise. The validation must be performed inside the
    caller's transaction so the live pedido state is observed
    without an independent read.
    """
    if session.estado_session != EstadoSession.ACTIVA:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=None,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "session_not_active",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=None,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "no_draft",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    if int(pedido.id_session) != int(session.id):
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "session_mismatch",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "pedido_not_borrador",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    comercio_id = session.id_comercio
    lines = PedidoProductoService(db).list_by_pedido(pedido.id)
    if not lines:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "empty_draft",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    if pedido.id_medio_pago is None or comercio_id is None:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "missing_payment",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    active_payments = {
        int(m.id)
        for m in MediosPagoRepository(db).list_active_for_comercio(int(comercio_id))
    }
    if int(pedido.id_medio_pago) not in active_payments:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "payment_not_active_for_comercio",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    if pedido.id_metodo_entrega is None:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "missing_delivery",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    active_deliveries = {
        int(m.id)
        for m in MetodoEntregaRepository(db).list_active_for_comercio(int(comercio_id))
    }
    if int(pedido.id_metodo_entrega) not in active_deliveries:
        return _ConfirmarPreconditions(
            status="rejected",
            pedido=pedido,
            rejected=_rejected(
                "confirmar_pedido",
                source_text,
                "delivery_not_active_for_comercio",
                "draft_order_closure",
                "confirmar_pedido",
            ),
        )
    return _ConfirmarPreconditions(
        status="ok",
        pedido=pedido,
        rejected=ProcessedIntent(
            intent="confirmar_pedido",
            source_text=source_text,
            status="rejected",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
        ),
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

_SPANISH_DAY_NAMES: dict[str, int] = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_SPANISH_FRAGMENT_RE = re.compile(
    r"(?P<date>"
    r"hoy"
    r"|ma[ñn]ana"
    r"|(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
    r")"
    r"\s+a\s+las\s+"
    r"(?P<hour>\d{1,2})"
    r"(?::(?P<minute>\d{1,2}))?"
    r"(?:\s+horas)?"
    r"(?:\s+de\s+la\s+(?P<qualifier>ma[ñn]ana|tarde|noche))?",
    flags=re.IGNORECASE | re.UNICODE,
)

_SPANISH_TIME_ONLY_RE = re.compile(
    r"\ba\s+las\s+"
    r"(?P<hour>\d{1,2})"
    r"(?::(?P<minute>\d{1,2}))?"
    r"(?:\s+horas)?"
    r"(?P<qualifier>\s+de\s+la\s+(?:ma[ñn]ana|tarde|noche))?",
    flags=re.IGNORECASE | re.UNICODE,
)


def _normalize_for_recognition(text: str) -> str:
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", stripped).strip()


def _qualifier_word(group_str: str | None) -> str | None:
    if not group_str:
        return None
    if "manana" in group_str:
        return "manana"
    if "tarde" in group_str:
        return "tarde"
    if "noche" in group_str:
        return "noche"
    return None


def _validate_time_only(
    match: re.Match[str],
) -> tuple[datetime | None, str]:
    """Validate a time-only Spanish fragment.

    Returns ``(None, "needs_date")`` when the hour is unambiguous and
    only a date is missing, and ``(None, "invalid_format")`` when the
    hour is ambiguous, out of range, or qualified by ``manana`` or
    ``noche`` at 12.
    """
    try:
        hour_int = int(match.group("hour"))
        minute_int = int(match.group("minute") or "0")
    except (TypeError, ValueError):
        return None, "invalid_format"

    if minute_int < 0 or minute_int > 59:
        return None, "invalid_format"

    qualifier = _qualifier_word(match.group("qualifier"))

    if qualifier is None:
        if 13 <= hour_int <= 23:
            return None, "needs_date"
        return None, "invalid_format"

    if hour_int < 1 or hour_int > 12:
        return None, "invalid_format"
    if qualifier in ("manana", "noche") and hour_int == 12:
        return None, "invalid_format"
    return None, "needs_date"


def _resolve_hour(hour_int: int, qualifier: str | None) -> int | None:
    if qualifier is None:
        if 0 <= hour_int <= 23:
            return hour_int
        return None
    if hour_int < 1 or hour_int > 12:
        return None
    if qualifier == "manana":
        if hour_int == 12:
            return None
        return hour_int
    if qualifier == "tarde":
        if hour_int == 12:
            return 12
        return hour_int + 12
    if qualifier == "noche":
        if hour_int == 12:
            return None
        return hour_int + 12
    return None


def _parse_spanish_expression(
    normalized: str,
    now_local: datetime,
) -> tuple[datetime | None, str]:
    """Parse a normalized Spanish temporal phrase.

    Returns ``(datetime, "spanish_relative")`` on success,
    ``(None, "needs_date")`` for time-only fragments,
    ``(None, "past_datetime")`` for resolved dates that are no longer
    future (with no rollover for ``hoy``), and
    ``(None, "invalid_format")`` for any other unrecognised,
    ambiguous, multi-fragment or off-contract input.
    """
    fragments = list(_SPANISH_FRAGMENT_RE.finditer(normalized))
    if not fragments:
        time_only = list(_SPANISH_TIME_ONLY_RE.finditer(normalized))
        if len(time_only) == 1:
            return _validate_time_only(time_only[0])
        return None, "invalid_format"
    if len(fragments) > 1:
        return None, "invalid_format"

    match = fragments[0]
    raw_date = match.group("date").strip()
    hour_str = match.group("hour")
    minute_str = match.group("minute") or "00"
    qualifier = match.group("qualifier")

    try:
        hour_int = int(hour_str)
        minute_int = int(minute_str)
    except ValueError:
        return None, "invalid_format"

    if minute_int < 0 or minute_int > 59:
        return None, "invalid_format"

    resolved_hour = _resolve_hour(hour_int, _qualifier_word(qualifier))
    if resolved_hour is None:
        return None, "invalid_format"

    date_token = raw_date.removeprefix("el ")

    if date_token == "hoy":
        target_date = now_local.date()
    elif date_token == "manana":
        target_date = now_local.date() + timedelta(days=1)
    else:
        target_weekday = _SPANISH_DAY_NAMES.get(date_token)
        if target_weekday is None:
            return None, "invalid_format"
        days_ahead = (target_weekday - now_local.weekday()) % 7
        target_date = now_local.date() + timedelta(days=days_ahead)

    candidate_dt = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        resolved_hour,
        minute_int,
        tzinfo=_DELIVERY_SCHEDULE_TIMEZONE,
    )

    if candidate_dt <= now_local:
        if date_token == "hoy":
            return None, "past_datetime"
        candidate_dt = candidate_dt + timedelta(days=7)
        if candidate_dt <= now_local:
            return None, "past_datetime"

    return candidate_dt, "spanish_relative"


def _parse_fecha_hora_entrega(
    source_text: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, str]:
    """Parse an absolute or Spanish-relative temporal expression.

    Returns ``(datetime, accepted_format)`` on success or
    ``(None, reason)`` on rejection. The reasons are
    ``"needs_date"``, ``"past_datetime"`` and ``"invalid_format"``.
    """
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

    if not stripped:
        return None, "invalid_format"

    reference = (
        now
        if now is not None
        else datetime.now(_DELIVERY_SCHEDULE_TIMEZONE)
    )
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=_DELIVERY_SCHEDULE_TIMEZONE)

    normalized = _normalize_for_recognition(stripped)
    if not normalized:
        return None, "invalid_format"

    return _parse_spanish_expression(normalized, reference)


def _is_future_fecha_hora_entrega(
    parsed_datetime: datetime,
    *,
    now: datetime | None = None,
) -> bool:
    if now is None:
        reference_datetime = datetime.now(_DELIVERY_SCHEDULE_TIMEZONE)
    elif now.tzinfo is None:
        reference_datetime = now.replace(tzinfo=_DELIVERY_SCHEDULE_TIMEZONE)
    else:
        reference_datetime = now
    return parsed_datetime > reference_datetime


def process_initial_set_fecha_hora_entrega(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
    *,
    now: datetime | None = None,
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

    if now is None:
        now = datetime.now(_DELIVERY_SCHEDULE_TIMEZONE)

    parsed_datetime, label = _parse_fecha_hora_entrega(source_text, now=now)
    if parsed_datetime is None:
        return _rejected(
            "set_fecha_hora_entrega",
            source_text,
            label,
            "draft_order_closure",
            "set_fecha_hora_entrega",
        )
    if not _is_future_fecha_hora_entrega(parsed_datetime, now=now):
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
        resolved_data={"accepted_format": label},
    )


__all__ = [
    "finalize_confirmar_pedido",
    "process_initial_confirmar_pedido",
    "process_initial_consultar_resumen_pedido",
    "process_initial_set_direccion_entrega",
    "process_initial_set_fecha_hora_entrega",
    "process_initial_set_metodo_de_entrega",
    "process_initial_set_metodo_de_pago",
    "process_initial_set_observacion_pedido",
]
