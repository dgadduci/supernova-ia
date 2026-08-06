"""Pending product ambiguity resolver.

Pure-with-respect-to-its-own-state resolver that closes a deterministic
9-layer reply vocabulary for a pending ``PROCESSEDIntent`` whose
``status == "pending_resolution"``. The resolver is layered as a sibling
of :mod:`backend.intents.context.product_selection_context_resolver` and
never queries the full commerce catalog.

The nine conceptual layers, numbered as in the design and the
capability spec, are:

1. numeric (``"1"``, ``"la 1"``, ``"opción 2"``, ``"número 1"``)
2. positional (Spanish ordinals + ``"la opción <n>"``, ``"la opción <word>"``)
3. exact normalized full-name match
4. exact token-set with filler-token stripping, shared-core precondition,
   subset preference, and distinguishing-token penalty
5. differentiating token
6. contextual default descriptors (``común``, ``normal``, ``regular``,
   ``original``, ``clásica``, ``clásico``, ``estándar``)
7. explicit exclusion (``"la que no es <token>"``, ``"sin <token>"``,
   ``"no quiero la <token>"``, ``"la otra"``, ...)
8. restricted fuzzy fallback over the persisted ``candidate_ids``
9. remain ambiguous — return the input intent unchanged

The runtime evaluation order is:

1 → 2 → 3 → 7 → 4 → 5 → 6 → 8 → 9

i.e. explicit customer exclusion phrases (Layer 7) take precedence over
generic token-set (Layer 4) and differentiating-token (Layer 5) matches
because the customer's intent is explicit and categorical. The other
layers keep the conceptual order: numeric and positional sweeps first
because they are the cheapest and least ambiguous, then exact-name,
then exclusion, then token-set, then differentiating, then default
descriptor, then fuzzy fallback, then remain ambiguous.

The resolver guarantees no commits, no flushes, no SQLAlchemy queries,
no handler invocations, no logging, no global alias mutation, no LLM
calls, and no embedding/hybrid activation.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from rapidfuzz import fuzz
from sqlalchemy.orm import Session as DatabaseSession  # noqa: F401

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState

__all__ = ["resolve_pending_product_ambiguity"]


_FILLER_TOKENS: frozenset[str] = frozenset(
    {
        "en",
        "de",
        "la",
        "el",
        "los",
        "las",
        "del",
        "al",
        "a",
    }
)
FILLER_TOKENS: frozenset[str] = _FILLER_TOKENS


_ORDINAL_FIXED: dict[str, int] = {
    "primera": 0,
    "primero": 0,
    "segunda": 1,
    "segundo": 1,
    "tercera": 2,
    "tercero": 2,
}


_ORDINAL_LAST: dict[str, None] = {
    "ultima": None,
    "ultimo": None,
}


_NUMBER_WORDS: dict[str, int] = {
    "uno": 0,
    "una": 0,
    "dos": 1,
    "tres": 2,
}


_DEFAULT_DESCRIPTORS: frozenset[str] = frozenset(
    {
        "comun",
        "normal",
        "regular",
        "original",
        "clasica",
        "clasico",
        "estandar",
    }
)


_MIN_FUZZY_SCORE: int = 85


def _normalize_tokens(text: str) -> list[str]:
    """Normalize a free-text message into tokens.

    The normalization follows the recognizer's ``_normalizar_texto``
    style: lowercase, NFD strip + ASCII encode (drops diacritics),
    replace non-alphanumeric (except ``ñ`` and whitespace) with space,
    collapse whitespace, split on whitespace.
    """
    if not text:
        return []
    normalized = text.lower()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("utf-8")
    normalized = re.sub(r"[^a-z0-9ñ\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return []
    return normalized.split()


def _normalize_text(text: str) -> str:
    """Normalize a free-text message into a whitespace-stripped string.

    Used for fuzzy matching. Returns an empty string when nothing
    remains after normalization.
    """
    if not text:
        return ""
    normalized = text.lower()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("utf-8")
    normalized = re.sub(r"[^a-z0-9ñ\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_resolved_unique_intent(
    active_intent: ProcessedIntent,
    candidate_id: int,
) -> ProcessedIntent:
    """Return a new ``ProcessedIntent`` with the given candidate selected.

    Mirrors the structure used by
    :mod:`backend.intents.context.product_selection_context_resolver`
    so the resolved intent is consumable by the existing pending-context
    dispatcher and execution pipeline.
    """
    new_requirements = [
        RequirementState(
            name=req.name,
            status="completed",
            value=candidate_id,
        )
        if req.name == "producto_presentacion_id"
        else req
        for req in active_intent.requirements
    ]
    all_completed = all(req.status == "completed" for req in new_requirements)
    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="ready" if all_completed else "pending_resolution",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        resolved_data={
            **active_intent.resolved_data,
            "producto_presentacion_id": candidate_id,
        },
        requirements=new_requirements,
        candidate_ids=[],
    )


def _build_catalog_index(
    productos_presentaciones: list[dict],
    allowed_ids: list[int],
) -> dict[int, dict]:
    """Index catalog rows restricted to ``allowed_ids``.

    Each indexed entry exposes ``producto_nombre``,
    ``presentacion_descripcion``, ``presentacion_codigo``, the joined
    normalized full-name token list, and the normalized
    ``producto_nombre`` token list. Rows whose ``producto_presentacion_id``
    is not in ``allowed_ids`` are ignored even when present in the input
    list.
    """
    allowed_set = {int(cid) for cid in allowed_ids}
    indexed: dict[int, dict] = {}
    for row in productos_presentaciones or []:
        pp_id = row.get("producto_presentacion_id")
        if pp_id is None or int(pp_id) not in allowed_set:
            continue
        nombre = str(row.get("producto_nombre") or "")
        presentacion = str(row.get("presentacion_descripcion") or "")
        joined = (nombre + " " + presentacion).strip()
        indexed[int(pp_id)] = {
            "id": int(pp_id),
            "producto_nombre": nombre,
            "presentacion_descripcion": presentacion,
            "presentacion_codigo": str(row.get("presentacion_codigo") or ""),
            "full_name_tokens": _normalize_tokens(joined),
            "nombre_tokens": _normalize_tokens(nombre),
        }
    return indexed


def _ordered_candidate_ids(active_intent: ProcessedIntent) -> list[int]:
    return [int(cid) for cid in active_intent.candidate_ids]


def _layer_numeric(
    message_tokens: list[str],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 1 — numeric selection.

    Accepted shapes (after normalization + token splitting):

    - ``["1"]``, ``["2"]``, ... — pure digit
    - ``["la", "1"]`` — ``la <digit>``
    - ``["opcion", "1"]`` — ``opción <digit>``
    - ``["numero", "1"]`` — ``número <digit>``

    Out-of-range digits fall through.
    """
    if len(message_tokens) not in (1, 2):
        return None
    digit_str: str
    if len(message_tokens) == 1:
        digit_str = message_tokens[0]
    else:
        prefix, digit_str = message_tokens
        if prefix not in {"la", "opcion", "numero"}:
            return None
        if not digit_str.isdigit():
            return None
    if not digit_str.isdigit():
        return None
    digit = int(digit_str)
    if digit < 1 or digit > len(ordered_ids):
        return None
    return _build_resolved_unique_intent(active_intent, ordered_ids[digit - 1])


def _resolve_positional_index(token: str, length: int) -> int | None:
    if token in _ORDINAL_FIXED:
        idx = _ORDINAL_FIXED[token]
        return idx if 0 <= idx < length else None
    if token in _ORDINAL_LAST:
        last = length - 1
        return last if last >= 0 else None
    if token in _NUMBER_WORDS:
        idx = _NUMBER_WORDS[token]
        return idx if 0 <= idx < length else None
    if token.isdigit():
        idx = int(token) - 1
        return idx if 0 <= idx < length else None
    return None


def _layer_positional(
    message_tokens: list[str],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 2 — positional selection.

    Accepted shapes (after normalization + token splitting):

    - pure ordinal word (``primera``, ``primero``, ``segunda``,
      ``segundo``, ``tercera``, ``tercero``, ``ultima``, ``ultimo``)
    - ``"la"`` + ordinal word
    - ``"la opción <digit|ordinal|number-word>"`` (three tokens)
    """
    if not message_tokens:
        return None

    if len(message_tokens) == 1:
        idx = _resolve_positional_index(message_tokens[0], len(ordered_ids))
        if idx is not None:
            return _build_resolved_unique_intent(active_intent, ordered_ids[idx])
        return None

    if len(message_tokens) == 2 and message_tokens[0] == "la":
        idx = _resolve_positional_index(message_tokens[1], len(ordered_ids))
        if idx is not None:
            return _build_resolved_unique_intent(active_intent, ordered_ids[idx])
        return None

    if (
        len(message_tokens) == 3
        and message_tokens[0] == "la"
        and message_tokens[1] == "opcion"
    ):
        idx = _resolve_positional_index(message_tokens[2], len(ordered_ids))
        if idx is not None:
            return _build_resolved_unique_intent(active_intent, ordered_ids[idx])
        return None

    return None


def _layer_exact_name(
    message_tokens: list[str],
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 3 — exact normalized full-name match.

    The message token set must equal the candidate's normalized full
    name token set. Compared as multisets (sorted equality) to permit
    minor reordering. Exactly one candidate must match.
    """
    if not message_tokens:
        return None
    message_signature = sorted(message_tokens)
    matched: list[int] = []
    for cid in ordered_ids:
        entry = catalog_index.get(cid)
        if entry is None:
            continue
        if sorted(entry["full_name_tokens"]) == message_signature:
            matched.append(cid)
    if len(matched) == 1:
        return _build_resolved_unique_intent(active_intent, matched[0])
    return None


def _strip_filler(tokens: list[str]) -> set[str]:
    return {t for t in tokens if t not in _FILLER_TOKENS}


def _layer_token_set(
    message_tokens: list[str],
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 4 — exact token-set with filler stripping.

    Implements the strict shared-core precondition, exact-match
    priority, subset preference, distinguishing-token penalty, and
    token-count-agnostic ranking from the spec.
    """
    message_core = _strip_filler(message_tokens)
    if not message_core:
        return None

    eligible: list[tuple[int, set[str]]] = []
    for cid in ordered_ids:
        entry = catalog_index.get(cid)
        if entry is None:
            continue
        candidate_core = _strip_filler(entry["full_name_tokens"])
        if candidate_core & message_core:
            eligible.append((cid, candidate_core))

    if not eligible:
        return None

    if len(eligible) == 1:
        cid, _ = eligible[0]
        return _build_resolved_unique_intent(active_intent, cid)

    exact_matches = [cid for cid, core in eligible if core == message_core]
    if len(exact_matches) == 1:
        return _build_resolved_unique_intent(active_intent, exact_matches[0])
    if len(exact_matches) > 1:
        return None

    def _rank_key(core: set[str]) -> tuple:
        is_subset = core <= message_core
        return (
            not is_subset,
            len(core - message_core),
            len(message_core - core),
        )

    ranked = sorted(
        eligible,
        key=lambda row: _rank_key(row[1]),
    )

    top_cid, top_core = ranked[0]
    if len(ranked) == 1:
        return _build_resolved_unique_intent(active_intent, top_cid)

    _, second_core = ranked[1]
    if _rank_key(top_core) != _rank_key(second_core):
        return _build_resolved_unique_intent(active_intent, top_cid)

    return None


def _layer_differentiating_token(
    message_tokens: list[str],
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 5 — differentiating token.

    Find tokens from the message that are present in exactly one
    candidate's normalized ``producto_nombre``. When such tokens exist
    and they all uniquely identify the same candidate, select it.
    """
    if not message_tokens:
        return None

    unique_owners: list[int] = []
    for token in set(message_tokens):
        owners = [
            cid
            for cid in ordered_ids
            if cid in catalog_index and token in catalog_index[cid]["nombre_tokens"]
        ]
        if len(owners) == 1:
            unique_owners.append(owners[0])

    if not unique_owners:
        return None

    owners_set = set(unique_owners)
    if len(owners_set) == 1:
        return _build_resolved_unique_intent(active_intent, owners_set.pop())
    return None


def _compute_variant_token_sets(
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
) -> dict[int, set[str]]:
    """Per-candidate set of tokens that distinguish one candidate.

    For each candidate, return the tokens present in its normalized
    full-name set that are absent from every other candidate's
    normalized full-name set.
    """
    cores: dict[int, set[str]] = {}
    for cid in ordered_ids:
        entry = catalog_index.get(cid)
        if entry is None:
            continue
        cores[cid] = _strip_filler(entry["full_name_tokens"])

    variants: dict[int, set[str]] = {}
    for cid, core in cores.items():
        other_union: set[str] = set()
        for other_cid, other_core in cores.items():
            if other_cid == cid:
                continue
            other_union |= other_core
        variants[cid] = core - other_union
    return variants


def _layer_default_descriptor(
    message_tokens: list[str],
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 6 — contextual default descriptor.

    Recognise ``comun``, ``normal``, ``regular``, ``original``,
    ``clasica``, ``clasico``, ``estandar`` (with diacritic-stripped
    variants). Select the variant-free candidate when exactly one
    candidate has no distinguishing variant tokens.
    """
    descriptors_present = [t for t in message_tokens if t in _DEFAULT_DESCRIPTORS]
    if len(descriptors_present) != 1:
        return None

    variants = _compute_variant_token_sets(catalog_index, ordered_ids)
    variant_free: list[int] = []
    for cid in ordered_ids:
        if cid not in catalog_index:
            continue
        if not variants.get(cid):
            variant_free.append(cid)
    if len(variant_free) == 1:
        return _build_resolved_unique_intent(active_intent, variant_free[0])
    return None


def _parse_excluded_token(
    raw_message: str,
    message_tokens: list[str],
) -> str | None:
    """Parse an excluded token from a Layer 7 phrase.

    Returns the normalized token to exclude, or ``None`` when the message
    is the bare ``"la otra"`` phrase (no excluded token). For ``la otra``
    the layer falls back to a variant-free selection.
    """
    if not message_tokens:
        return None
    normalized_raw = _normalize_text(raw_message or "")
    if not normalized_raw:
        return None

    if normalized_raw == "la otra":
        return "_LA_OTRA_"

    patterns_with_token = [
        "la que no es ",
        "la que no tenga ",
        "la que no tiene ",
        "sin ",
        "no quiero la ",
        "no la ",
    ]
    for prefix in patterns_with_token:
        if normalized_raw.startswith(prefix):
            remainder = normalized_raw[len(prefix):].strip()
            if not remainder:
                return None
            head = remainder.split()[0]
            return head if head else None
    return None


def _layer_explicit_exclusion(
    raw_message: str,
    message_tokens: list[str],
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 7 — explicit exclusion.

    Recognise ``la que no es <token>``, ``la que no tenga <token>``,
    ``la que no tiene <token>``, ``sin <token>``, ``no quiero la
    <token>``, ``no la <token>``, ``la otra``. Select the candidate
    whose normalized ``producto_nombre`` does NOT contain the excluded
    token. ``la otra`` falls back to selecting the variant-free
    candidate (Layer 6 logic without a descriptor).
    """
    excluded = _parse_excluded_token(raw_message, message_tokens)
    if excluded is None:
        return None

    if excluded == "_LA_OTRA_":
        variants = _compute_variant_token_sets(catalog_index, ordered_ids)
        variant_free: list[int] = []
        for cid in ordered_ids:
            if cid not in catalog_index:
                continue
            if not variants.get(cid):
                variant_free.append(cid)
        if len(variant_free) == 1:
            return _build_resolved_unique_intent(active_intent, variant_free[0])
        return None

    candidates: list[int] = []
    for cid in ordered_ids:
        entry = catalog_index.get(cid)
        if entry is None:
            continue
        if excluded not in entry["nombre_tokens"]:
            candidates.append(cid)
    if len(candidates) == 1:
        return _build_resolved_unique_intent(active_intent, candidates[0])
    return None


def _layer_fuzzy_fallback(
    raw_message: str,
    catalog_index: dict[int, dict],
    ordered_ids: list[int],
    active_intent: ProcessedIntent,
) -> ProcessedIntent | None:
    """Layer 8 — restricted fuzzy fallback.

    Compute :func:`rapidfuzz.fuzz.partial_ratio` between the normalized
    message and each candidate's normalized full name. Select the
    unique highest score above :data:`_MIN_FUZZY_SCORE`.
    """
    query = _normalize_text(raw_message or "")
    if not query:
        return None
    scores: list[tuple[int, int]] = []
    for cid in ordered_ids:
        entry = catalog_index.get(cid)
        if entry is None:
            continue
        candidate_str = " ".join(entry["full_name_tokens"])
        if not candidate_str:
            continue
        score = int(fuzz.partial_ratio(query, candidate_str))
        scores.append((cid, score))

    if not scores:
        return None

    top_score = max(score for _, score in scores)
    if top_score < _MIN_FUZZY_SCORE:
        return None

    top_candidates = [cid for cid, score in scores if score == top_score]
    if len(top_candidates) != 1:
        return None

    return _build_resolved_unique_intent(active_intent, top_candidates[0])


def resolve_pending_product_ambiguity(
    message: str,
    active_intent: ProcessedIntent,
    productos_presentaciones: list[dict],
) -> ProcessedIntent:
    """Resolve a pending ``agregar_producto`` intent against the active
    ``candidate_ids`` using the 9-layer reply vocabulary.

    The function is pure with respect to its own state: it never imports
    ``session`` (``db``), never issues SQLAlchemy queries, never commits,
    never flushes, never logs, never calls handlers, never mutates the
    input intent, never consults the full commerce catalog, and never
    activates embeddings or hybrid scoring.
    """
    if active_intent.status != "pending_resolution":
        return active_intent
    if not active_intent.candidate_ids:
        return active_intent

    allowed_ids = _ordered_candidate_ids(active_intent)
    if not allowed_ids:
        return active_intent

    catalog_index = _build_catalog_index(
        productos_presentaciones, allowed_ids
    )
    if not catalog_index:
        return active_intent

    message_tokens = _normalize_tokens(message or "")

    layers: list[Callable[[], ProcessedIntent | None]] = [
        lambda: _layer_numeric(message_tokens, allowed_ids, active_intent),
        lambda: _layer_positional(message_tokens, allowed_ids, active_intent),
        lambda: _layer_exact_name(
            message_tokens, catalog_index, allowed_ids, active_intent
        ),
        lambda: _layer_explicit_exclusion(
            message or "",
            message_tokens,
            catalog_index,
            allowed_ids,
            active_intent,
        ),
        lambda: _layer_token_set(
            message_tokens, catalog_index, allowed_ids, active_intent
        ),
        lambda: _layer_differentiating_token(
            message_tokens, catalog_index, allowed_ids, active_intent
        ),
        lambda: _layer_default_descriptor(
            message_tokens, catalog_index, allowed_ids, active_intent
        ),
        lambda: _layer_fuzzy_fallback(
            message or "", catalog_index, allowed_ids, active_intent
        ),
    ]

    for layer in layers:
        result = layer()
        if result is not None:
            return result

    return active_intent
