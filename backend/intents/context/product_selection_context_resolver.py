from typing import Literal

from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer import (
    PRESENTACION_ALIASES,
    STOPWORDS,
    TAMANIOS,
    _extraer_presentacion,
    _normalizar_texto,
)
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    RecognizeContext,
)

_product_recognizer: ProductRecognizerProtocol = FuzzyProductRecognizer()


def detectar_productos(
    text: str,
    productos_presentaciones: list[dict],
    *,
    intent_metadata: RecognizeContext | None = None,
):
    return _product_recognizer.recognize(
        text,
        productos_presentaciones,
        intent_metadata=intent_metadata,
    )


def _build_resolved_unique_intent(
    active_intent: ProcessedIntent,
    selected_id: int,
) -> ProcessedIntent:
    new_requirements = []
    for req in active_intent.requirements:
        if req.name == "producto_presentacion_id":
            new_requirements.append(
                RequirementState(name=req.name, status="completed", value=selected_id)
            )
        else:
            new_requirements.append(req)

    all_requirements_completed = all(
        req.status == "completed" for req in new_requirements
    )
    new_status_value: Literal["ready", "pending_resolution"] = (
        "ready" if all_requirements_completed else "pending_resolution"
    )

    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status=new_status_value,
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        resolved_data={**active_intent.resolved_data, "producto_presentacion_id": selected_id},
        requirements=new_requirements,
        candidate_ids=[],
    )


def _presentacion_matches(presentacion_codigo: str, alias: str) -> bool:
    codigo_lower = presentacion_codigo.lower()
    alias_lower = alias.lower()
    if not codigo_lower or not alias_lower:
        return False
    if codigo_lower == alias_lower:
        return True
    if codigo_lower.startswith(alias_lower):
        return True
    return alias_lower in codigo_lower.split()


def _extraneous_words_relate_to_active_intent(
    extraneous: list[str], active_intent: ProcessedIntent,
) -> bool:
    """Return True when every extraneous token appears in the active
    intent's source_text or resolved_data, so it is safe to keep
    narrowing by presentacion alias."""
    if not extraneous:
        return False
    haystack_parts = [active_intent.source_text or ""]
    for value in (active_intent.resolved_data or {}).values():
        if isinstance(value, str):
            haystack_parts.append(value)
    haystack = _normalizar_texto(" ".join(haystack_parts))
    haystack_tokens = set(haystack.split())
    return all(token in haystack_tokens for token in extraneous)


def _descriptor_token(
    palabras: list[str],
    productos_presentaciones: list[dict],
    *,
    irrelevant: set[str],
) -> str | None:
    token_counts: dict[str, int] = {}
    for pp in productos_presentaciones:
        row_tokens: set[str] = set()
        for field in ("producto_nombre", "presentacion_codigo"):
            value = pp.get(field)
            if value:
                row_tokens.update(_normalizar_texto(str(value)).split())
        for token in row_tokens:
            token_counts[token] = token_counts.get(token, 0) + 1

    candidates: list[tuple[int, str]] = []
    for palabra in dict.fromkeys(palabras):
        if palabra in irrelevant:
            continue
        count = token_counts.get(palabra)
        if count is not None:
            candidates.append((count, palabra))
    if not candidates:
        return None
    candidates.sort()
    min_count = candidates[0][0]
    tied = [c for c in candidates if c[0] == min_count]
    if len(tied) > 1:
        return None
    return tied[0][1]


def _narrow_by_presentacion_alias(
    message: str,
    active_intent: ProcessedIntent,
    productos_presentaciones: list[dict],
) -> ProcessedIntent | None:
    """Narrow candidates by structured presentation or local descriptor.

    Structured presentation aliases come from ``_extraer_presentacion``.
    Descriptor tokens are matched exactly against normalized name and code
    words in the restricted catalog.
    """

    presentacion_alias = _extraer_presentacion(message)

    palabras = _normalizar_texto(message).split()
    irrelevant = STOPWORDS | TAMANIOS | set(PRESENTACION_ALIASES.keys())
    extraneous = [p for p in palabras if p not in irrelevant]

    descriptor_token: str | None = None
    if presentacion_alias is None:
        descriptor_token = _descriptor_token(
            palabras,
            productos_presentaciones,
            irrelevant=irrelevant,
        )
    if descriptor_token is not None:
        extraneous = [p for p in extraneous if p != descriptor_token]

    if presentacion_alias is None and descriptor_token is None:
        return None
    if extraneous and not _extraneous_words_relate_to_active_intent(
        extraneous, active_intent
    ):
        return None

    matching_ids: list[int] = []
    for pp in productos_presentaciones:
        codigo = str(pp.get("presentacion_codigo", ""))
        if presentacion_alias is not None and _presentacion_matches(
            codigo, presentacion_alias
        ):
            matching_ids.append(pp["producto_presentacion_id"])
            continue
        nombre = str(pp.get("producto_nombre", ""))
        nombre_tokens = set(_normalizar_texto(nombre).split())
        if presentacion_alias is not None and presentacion_alias in nombre_tokens:
            matching_ids.append(pp["producto_presentacion_id"])
            continue
        if descriptor_token is not None:
            codigo_tokens = set(_normalizar_texto(codigo).split())
            if descriptor_token in codigo_tokens or descriptor_token in nombre_tokens:
                matching_ids.append(pp["producto_presentacion_id"])

    intersection = [cid for cid in active_intent.candidate_ids if cid in matching_ids]
    if len(intersection) == 1:
        return _build_resolved_unique_intent(active_intent, intersection[0])
    if len(intersection) > 1:
        return active_intent.model_copy(update={"candidate_ids": intersection})
    return None


def resolve_product_selection(
    message: str,
    active_intent: ProcessedIntent,
    productos_presentaciones: list[dict],
    *,
    sink: DiagnosticSink | None = None,
    resolver_purpose: str = "product_selection_refinement",
) -> ProcessedIntent:
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    started = ResolverCallStarted(
        resolver_class=type(active_intent).__name__,
        resolver_method="resolve_product_selection",
        resolver_purpose=resolver_purpose,
        incoming_text=message,
        normalized_text=message,
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        quantity=(active_intent.resolved_data or {}).get("cantidad"),
        status_before=active_intent.status,
        requirements_before=list(active_intent.requirements),
        resolved_data_before=dict(active_intent.resolved_data or {}),
        candidate_ids_before=list(active_intent.candidate_ids),
        candidate_count=len(productos_presentaciones),
        candidate_catalog=list(productos_presentaciones),
    )
    diagnostic_sink.on_resolver_started(started)
    result: ProcessedIntent = active_intent
    matched_alias_ids: list[int] = []
    try:
        if active_intent.status != "pending_resolution" or not active_intent.candidate_ids:
            return result

        resultado = detectar_productos(
            message,
            productos_presentaciones,
            intent_metadata={"catalog_scope": "pending_product_selection_restricted"},
        )

        if len(resultado["encontrados"]) == 1:
            selected_id = resultado["encontrados"][0]["producto_presentacion_id"]
            if selected_id not in active_intent.candidate_ids:
                return result
            result = _build_resolved_unique_intent(active_intent, selected_id)
            matched_alias_ids = [selected_id]
            return result

        product_level_groups = [
            group
            for group in resultado["encontrados_posibles"]
            if group.get("kind") != "category"
        ]
        if len(resultado["encontrados"]) == 0 and product_level_groups:
            matched_ids: list[int] = []
            for group in product_level_groups:
                productos_raw = group.get("productos")
                productos = productos_raw if isinstance(productos_raw, list) else []
                for product in productos:
                    matched_ids.append(product["producto_presentacion_id"])
            intersection = [
                cid for cid in active_intent.candidate_ids if cid in matched_ids
            ]
            if not intersection:
                return result
            if len(intersection) == 1:
                result = _build_resolved_unique_intent(active_intent, intersection[0])
                matched_alias_ids = [intersection[0]]
                return result
            result = active_intent.model_copy(update={"candidate_ids": intersection})
            matched_alias_ids = list(intersection)
            return result

        if len(resultado["encontrados"]) == 0 and not product_level_groups:
            narrowed = _narrow_by_presentacion_alias(
                message, active_intent, productos_presentaciones
            )
            if narrowed is not None:
                result = narrowed
                if narrowed.status == "ready":
                    resolved_selected_id = (
                        narrowed.resolved_data.get("producto_presentacion_id")
                    )
                    if isinstance(resolved_selected_id, int):
                        matched_alias_ids = [resolved_selected_id]
                else:
                    matched_alias_ids = list(narrowed.candidate_ids)
                return result

        return result
    finally:
        output_selected_id: int | None = None
        status_after = result.status
        resolved_data_after = dict(result.resolved_data or {})
        candidate_ids_after = [int(cid) for cid in result.candidate_ids]
        if status_after == "ready":
            resolved_id = resolved_data_after.get("producto_presentacion_id")
            if isinstance(resolved_id, int):
                output_selected_id = resolved_id
        completed = ResolverCallCompleted(
            result_type=type(result).__name__,
            status_after=status_after,
            selected_candidate_id=output_selected_id,
            quantity_after=resolved_data_after.get("cantidad"),
            requirements_after=list(result.requirements),
            resolved_data_after=resolved_data_after,
            candidate_ids_after=list(candidate_ids_after),
            candidate_count_after=len(candidate_ids_after),
            matches=list(matched_alias_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_product_selection"]
