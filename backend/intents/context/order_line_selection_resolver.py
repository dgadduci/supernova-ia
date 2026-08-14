"""Order-line selection resolver.

Refines an active order-line ``pending_resolution`` intent when the
customer replies with a more specific order-line identifier (size,
product name, etc.). Today this is used by both ``quitar_producto``
and ``set_observacion_producto`` pending intents; the resolver is
generic over the intent name and only the deterministic
``pedido_producto_id`` narrowing.

The resolver restricts the refinement strictly to the current
``candidate_ids`` (no broadening back to the commerce catalog) and
never mutates ``session``, the pedido, or any persisted state. The
resolver preserves each pending intent's existing ``resolved_data``
(``observation_action``, ``observation_text``, ``cantidad``, etc.) so a
follow-up clarification does not reclassify or rewrite the original
intent.

When the refinement narrows to exactly one candidate, populates
``resolved_data["pedido_producto_id"]``, sets ``status="ready"``, and
lets the existing ready-execution path dispatch the handler. When the
refinement yields several candidates, sets ``status="pending_resolution"``
with the reduced ``candidate_ids``. When the message resolves to a
``pedido_producto_id`` not in the current candidate set, returns
``rejected`` without mutating the pedido.

For a pending ``quitar_producto`` clarification between candidate
presentations (e.g. ``Mozzarella Grande`` vs ``Mozzarella Chica``) the
resolver applies a narrow deterministic pre-check: a bare normalized
presentation code (``chica``, ``grande``) or the same code with a
single leading Spanish article (``la``, ``el``, ``una``, ``un``,
``las``, ``los``) selects the unique matching candidate, restricted
to the persisted ``candidate_ids`` of ``session.id_pedido``. Any
other input — including phrases containing a different product, no
match, duplicate code or unsupported intent — falls through to the
existing restricted recognizer/intersection path with no candidate
widening and no new rejection.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession
from backend.recognizers.product_recognizer import _normalizar_texto
from backend.services.pedido_producto_service import PedidoProductoService

_BARE_PRESENTATION_ARTICLES: frozenset[str] = frozenset(
    {"la", "el", "una", "un", "las", "los"},
)


def _flatten_pedido_producto_ids(recognized: dict) -> list[int]:
    ids: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pp_id = entry.get("pedido_producto_id")
        if pp_id is not None:
            ids.append(int(pp_id))
    for group in recognized.get("encontrados_posibles") or []:
        if group.get("kind") == "category":
            continue
        for product in group.get("productos") or []:
            pp_id = product.get("pedido_producto_id")
            if pp_id is not None:
                ids.append(int(pp_id))
    return ids


def _build_ready_intent(
    active_intent: ProcessedIntent,
    pedido_producto_id: int,
) -> ProcessedIntent:
    new_requirements: list[RequirementState] = [
        RequirementState(
            name="pedido_producto_id",
            status="completed",
            value=pedido_producto_id,
        ),
    ]
    req_cant = next(
        (r for r in active_intent.requirements if r.name == "cantidad"),
        RequirementState(name="cantidad", status="pending", value=None),
    )
    new_requirements.append(req_cant)

    for req in active_intent.requirements:
        if req.name in ("pedido_producto_id", "cantidad"):
            continue
        new_requirements.append(req)

    resolved_data = {
        **active_intent.resolved_data,
        "pedido_producto_id": pedido_producto_id,
    }
    if req_cant.value is not None and "cantidad" not in active_intent.resolved_data:
        resolved_data["cantidad"] = req_cant.value

    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="ready",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        resolved_data=resolved_data,
        requirements=new_requirements,
        candidate_ids=[],
    )


def _strip_leading_bare_article(normalized: str) -> str:
    """Return ``normalized`` with at most one leading article removed.

    Accepts the Spanish articles ``la``, ``el``, ``una``, ``un``,
    ``las`` and ``los`` in their already-normalized lowercase form.
    Any other first token is preserved; multi-token phrases with no
    article prefix are returned unchanged so ``Napolitana chica`` is
    not collapsed to ``chica`` and continues through the existing
    restricted recognizer path.
    """
    parts = normalized.split(" ", 1)
    if len(parts) == 2 and parts[0] in _BARE_PRESENTATION_ARTICLES:
        return parts[1]
    return normalized


def _match_bare_presentation(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
) -> int | None:
    """Return the unique active ``pedido_producto_id`` whose
    ``presentacion.codigo`` equals a normalized bare code.

    The helper is only invoked for a pending ``quitar_producto``
    ``order_line_selection``: it reads ``PedidoProducto`` rows for
    ``session.id_pedido``, filters strictly to the persisted
    ``active_intent.candidate_ids`` and compares the candidate
    presentation codes against the normalized reply (the bare code
    alone or the bare code with one leading Spanish article). It
    returns the matching id only when exactly one active candidate
    matches; zero or multiple matches, missing pedido, missing
    association or malformed relations return ``None`` so the caller
    can fall through to the existing recognizer/intersection path.

    Technical read failures from ``PedidoProductoService.list_by_pedido``
    (``PedidoNotFound``, ``SQLAlchemyError`` and its subclasses) are
    intentionally **not** swallowed: they propagate so the calling
    transactional processor can roll back and surface a
    ``failed`` outcome instead of silently retrying through
    ``recognize_quitar_producto`` (which performs a second read and
    could end in a selection or mutation on a transient error).

    The helper never calls ``recognize_quitar_producto``,
    hybrid/LLM recognition, fuzzy matching, transaction control
    (commit/rollback/flush/refresh/begin/close) or any catalog
    lookup beyond ``PedidoProductoService.list_by_pedido``.
    """
    pedido_id = getattr(session, "id_pedido", None)
    if pedido_id is None:
        return None

    try:
        candidate_set = {int(cid) for cid in active_intent.candidate_ids}
    except (TypeError, ValueError):
        return None
    if not candidate_set:
        return None

    if not isinstance(message, str):
        return None

    normalized_message = _normalizar_texto(message)
    if not normalized_message:
        return None

    tokens = normalized_message.split()
    if len(tokens) > 2:
        return None
    if len(tokens) == 2 and tokens[0] not in _BARE_PRESENTATION_ARTICLES:
        return None

    bare_target = _strip_leading_bare_article(normalized_message)
    if not bare_target:
        return None

    pedido_productos = PedidoProductoService(db).list_by_pedido(pedido_id)

    matched: list[int] = []
    seen: set[int] = set()
    for pp in pedido_productos:
        try:
            pp_id = int(pp.id)
        except (TypeError, ValueError, AttributeError):
            continue
        if pp_id not in candidate_set:
            continue
        presentacion = getattr(
            getattr(pp, "producto_presentacion", None),
            "presentacion",
            None,
        )
        codigo = getattr(presentacion, "codigo", None)
        if not isinstance(codigo, str):
            continue
        if _normalizar_texto(codigo) != bare_target:
            continue
        if pp_id in seen:
            continue
        seen.add(pp_id)
        matched.append(pp_id)

    if len(matched) == 1:
        return matched[0]
    return None


def resolve_order_line_selection(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
) -> ProcessedIntent:
    """Refine an active order-line ``pending_resolution`` intent.

    Both ``quitar_producto`` and ``set_observacion_producto`` share this
    seam: the resolver narrows by ``pedido_producto_id`` against the
    active ``candidate_ids`` and forwards the original
    ``resolved_data`` (``observation_action`` /
    ``observation_text`` / ``cantidad``) unchanged so the ready intent
    preserves the original action and value.
    """
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    started = ResolverCallStarted(
        resolver_class=type(active_intent).__name__,
        resolver_method="resolve_order_line_selection",
        resolver_purpose="order_line_refinement",
        session_id=getattr(session, "id", None),
        incoming_text=message,
        normalized_text=message,
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        quantity=(active_intent.resolved_data or {}).get("cantidad"),
        status_before=active_intent.status,
        requirements_before=list(active_intent.requirements),
        resolved_data_before=dict(active_intent.resolved_data or {}),
        candidate_ids_before=list(active_intent.candidate_ids),
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        if (
            active_intent.status != "pending_resolution"
            or not active_intent.candidate_ids
        ):
            return active_intent

        if (
            active_intent.intent == "quitar_producto"
            and getattr(session, "id_pedido", None) is not None
        ):
            matched_pedido_producto_id = _match_bare_presentation(
                db, session, message, active_intent,
            )
            if matched_pedido_producto_id is not None:
                return _build_ready_intent(
                    active_intent, matched_pedido_producto_id,
                )

        recognized = recognize_quitar_producto(db, session, message)
        recognized_ids = _flatten_pedido_producto_ids(recognized)

        if not recognized_ids:
            return active_intent

        intersection = sorted(
            {int(cid) for cid in recognized_ids}
            & {int(cid) for cid in active_intent.candidate_ids}
        )

        if not intersection:
            return active_intent.model_copy(update={"status": "rejected"})

        if len(intersection) == 1:
            return _build_ready_intent(active_intent, intersection[0])

        return active_intent.model_copy(update={"candidate_ids": intersection})
    finally:
        completed = ResolverCallCompleted(
            result_type=type(active_intent).__name__,
            status_after=active_intent.status,
            quantity_after=(active_intent.resolved_data or {}).get("cantidad"),
            requirements_after=list(active_intent.requirements),
            resolved_data_after=dict(active_intent.resolved_data or {}),
            candidate_ids_after=list(active_intent.candidate_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_order_line_selection"]