"""Bounded outbound response styler.

The styler is an optional, presentation-only post-processor applied
to the deterministic ``CustomerResponse`` list produced by
:mod:`backend.services.outbound_response_mapper`. It NEVER decides
business behaviour, intent, status, ordering or quantity: every
factual element of the response is rendered first by the existing
deterministic builders and the styler merely prepends or appends a
short bounded wrapper to the exact original ``message`` for
eligible normal responses.

Eligibility is derived from the ``(intent, status)`` pair of each
response, never from the rendered text. Errors, rejections,
pending / ambiguous selections, generic recovery messages
(``desconocida``) and responses associated with customer free-text
input (observations, address, payment/delivery method, date/time)
are NEVER eligible and NEVER sent to the LLM.

The styler resolves the commerce flavor via the existing
``Comercio.flavor_comunicacion`` relation. The neutral ``neutro``
flavor, an absent flavor, an inactive flavor, a flavor whose
internal ``instruccion_llm`` is empty and any turn with zero
eligible responses make the styler a strict no-op: the original
factual responses are returned byte-for-byte and no ``QueryLlm``
call is performed.

For an active non-neutral flavor with at least one eligible
response, the styler issues exactly one batched ``QueryLlm``
request for the turn and parses the wrapper-only JSON contract:

* Input contract (request):
  ``{"items": [{"index": <int>, "response_type": <token>}, ...]}``
  in the eligible-input order.

* Output contract (response):
  ``{"items": [{"index": <int>, "prefix": <str>, "suffix": <str>}, ...]}``
  with the same count, indices and ordering, and no extra fields.

The styler composes the final message as
``prefix + original_factual_message + suffix`` so the original
deterministic message remains one intact contiguous substring in
the rendered output. A wrapper that fails validation for a single
item falls back to the original message for that item; a malformed
batch structure falls back to the original message for every
item.

The styler NEVER owns database transaction control. It never calls
``commit``, ``rollback``, ``flush``, ``refresh``, ``begin``,
``begin_nested`` or ``close``. Existing callers retain their
transaction ownership and the mapper signature is preserved so
``stage_outbound_rows`` consumes the already-styled list.

Observability is bounded: the styler emits one structured event
per attempt via :func:`backend.observability.emit_event`. The
event payload only contains the flavor code, eligible count,
applied count, fallback category, elapsed milliseconds and the
static prompt-template fingerprint. The payload never contains
the rendered prompt, the ``instruccion_llm`` text, customer text,
factual response text, model output or any business identifier.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics.outbound_response_style_prompt_template import (
    OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
    build_outbound_style_prompt,
    outbound_style_template_identity,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.llm.query_llm import (
    QueryLlm,
    QueryLlmConnectionError,
    QueryLlmError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)
from backend.models.comercio import Comercio
from backend.models.flavor_comunicacion import FlavorComunicacion
from backend.observability import (
    COMPONENT_OUTBOUND_STYLE,
    EVENT_OUTBOUND_STYLE,
    emit_event,
)

logger = logging.getLogger(__name__)


NEUTRO_FLAVOR_CODE = "neutro"


OUTCOME_NOT_ATTEMPTED = "not_attempted"
OUTCOME_ATTEMPTED = "attempted"
OUTCOME_APPLIED = "applied"

FALLBACK_NONE = "none"
FALLBACK_TIMEOUT = "timeout"
FALLBACK_CONNECTION = "connection"
FALLBACK_HTTP = "http_error"
FALLBACK_RESPONSE = "response_error"
FALLBACK_MALFORMED_BATCH = "malformed_batch"
FALLBACK_WRAPPER_INVALID = "wrapper_invalid"
FALLBACK_UNEXPECTED = "unexpected"


RESPONSE_TYPE_SOCIAL_GREETING = "social_greeting"
RESPONSE_TYPE_SOCIAL_THANKS = "social_thanks"
RESPONSE_TYPE_SOCIAL_GOODBYE = "social_goodbye"
RESPONSE_TYPE_SOCIAL_YES = "social_yes"
RESPONSE_TYPE_SOCIAL_NO = "social_no"
RESPONSE_TYPE_MENU_FULL = "menu_full"
RESPONSE_TYPE_MENU_CATEGORY = "menu_category"
RESPONSE_TYPE_PRODUCT_INFO = "product_info"
RESPONSE_TYPE_INFO_PAYMENT_METHODS = "info_payment_methods"
RESPONSE_TYPE_INFO_DELIVERY_METHODS = "info_delivery_methods"
RESPONSE_TYPE_INFO_ADDRESS = "info_address"
RESPONSE_TYPE_INFO_HOURS = "info_hours"
RESPONSE_TYPE_PRODUCT_ADD_SUCCESS = "product_add_success"
RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS = "product_remove_success"
RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS = "product_modify_success"
RESPONSE_TYPE_ORDER_STATUS = "order_status"
RESPONSE_TYPE_ORDER_SUMMARY = "order_summary"
RESPONSE_TYPE_ORDER_CONFIRMED = "order_confirmed"
RESPONSE_TYPE_ORDER_STARTED = "order_started"
RESPONSE_TYPE_ORDER_EMPTIED = "order_emptied"


EXECUTED_STATUS = "executed"
_VER_MENU_INTENT = "ver_menu"


@dataclass(frozen=True)
class EligibleResponse:
    """Internal view of an eligible response kept by the styler.

    ``index`` is the position in the rendered
    ``CustomerResponse`` list (preserved through the styler so
    the caller can map wrappers back to their original positions).
    ``batch_position`` is the zero-based sequential position in
    the eligible-only batch sent to the LLM (always ``0, 1, 2,
    ..., N-1`` and used as the wire-level ``index`` token in the
    prompt and in the parsed response).
    """

    index: int
    response_type: str
    response: CustomerResponse
    batch_position: int = 0


_ELIGIBLE_INTENT_STATUS_MAP: dict[tuple[str, str], str] = {
    ("saludo", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_GREETING,
    ("agradecimiento", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_THANKS,
    ("despedida", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_GOODBYE,
    ("respuesta_afirmativa", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_YES,
    ("respuesta_negativa", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_NO,
    (_VER_MENU_INTENT, EXECUTED_STATUS): RESPONSE_TYPE_MENU_FULL,
    ("consultar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_INFO,
    (
        "ver_metodos_de_pago",
        EXECUTED_STATUS,
    ): RESPONSE_TYPE_INFO_PAYMENT_METHODS,
    (
        "ver_metodos_de_entrega",
        EXECUTED_STATUS,
    ): RESPONSE_TYPE_INFO_DELIVERY_METHODS,
    ("consultar_domicilio_comercio", EXECUTED_STATUS): RESPONSE_TYPE_INFO_ADDRESS,
    ("consultar_horarios_comercio", EXECUTED_STATUS): RESPONSE_TYPE_INFO_HOURS,
    ("agregar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_ADD_SUCCESS,
    ("quitar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS,
    ("modificar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS,
    ("consultar_estado_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_STATUS,
    ("consultar_resumen_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_SUMMARY,
    ("confirmar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_CONFIRMED,
    ("iniciar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_STARTED,
    ("vaciar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_EMPTIED,
}


def response_type_for(intent: str, status: str) -> str | None:
    """Return the bounded ``response_type`` for an eligible pair.

    Returns ``None`` for ineligible pairs (errors, rejections,
    pending / ambiguous selections, customer free-text responses
    or any unrecognised intent / status combination).
    """
    if not isinstance(intent, str) or not isinstance(status, str):
        return None
    return _ELIGIBLE_INTENT_STATUS_MAP.get((intent, status))


def is_eligible_response(response: CustomerResponse) -> bool:
    """Return ``True`` when the response maps to a bounded styler token."""
    return response_type_for(response.intent, response.status) is not None


def select_eligible(
    responses: Sequence[CustomerResponse],
) -> list[EligibleResponse]:
    """Project ``responses`` to the eligible subset, preserving order.

    Each projected entry carries both the original position in
    ``responses`` (``index``) and the wire-level position in the
    eligible-only batch (``batch_position``, ``0..N-1``).
    """
    eligible: list[EligibleResponse] = []
    for index, response in enumerate(responses):
        if not isinstance(response, CustomerResponse):
            continue
        response_type = response_type_for(response.intent, response.status)
        if response_type is None:
            continue
        eligible.append(
            EligibleResponse(
                index=index,
                response_type=response_type,
                response=response,
                batch_position=len(eligible),
            )
        )
    return eligible


def _resolve_flavor(
    db: DatabaseSession, comercio_id: int | None
) -> FlavorComunicacion | None:
    """Resolve the selected flavor for ``comercio_id`` without
    mutating the supplied session.
    """
    if db is None:
        return None
    if not isinstance(comercio_id, int) or isinstance(comercio_id, bool):
        return None
    if comercio_id <= 0:
        return None
    comercio = db.get(Comercio, comercio_id)
    if comercio is None:
        return None
    flavor_id = getattr(comercio, "flavor_comunicacion_id", None)
    if not isinstance(flavor_id, int):
        return None
    return db.get(FlavorComunicacion, flavor_id)


def _is_flavor_usable(flavor: FlavorComunicacion | None) -> bool:
    if flavor is None:
        return False
    if not bool(getattr(flavor, "activo", False)):
        return False
    code = getattr(flavor, "codigo", None)
    if not isinstance(code, str):
        return False
    if code.strip() == "" or code.strip() == NEUTRO_FLAVOR_CODE:
        return False
    instruction = getattr(flavor, "instruccion_llm", None)
    return isinstance(instruction, str) and instruction.strip() != ""


_DIGIT_PATTERN = re.compile(r"\d")
_DISALLOWED_TEXT_CHARS = frozenset({"\n", "\r", "\t", "?"})
_WRAPPER_MAX_LENGTH = 24


def _safe_short_wrapper(value: Any) -> str | None:
    """Return ``value`` when it is a safe wrapper fragment, else ``None``.

    A safe wrapper fragment is a single-line printable string of at
    most :data:`_WRAPPER_MAX_LENGTH` characters that contains no
    digits, line breaks, question marks or ASCII control characters.
    An empty string is also safe (the caller composes nothing).
    """
    if not isinstance(value, str):
        return None
    if len(value) > _WRAPPER_MAX_LENGTH:
        return None
    if value == "":
        return value
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    if any(char in _DISALLOWED_TEXT_CHARS for char in value):
        return None
    if _DIGIT_PATTERN.search(value):
        return None
    return value


def _parse_wrappers(
    payload: Any,
    *,
    eligible_count: int,
) -> tuple[dict[int, tuple[Any, Any]] | None, str]:
    """Parse the LLM response into a batch-position keyed wrapper
    mapping.

    Returns ``(None, fallback_category)`` when the batch structure
    is invalid (the caller must fall back for the entire batch);
    returns ``(parsed_mapping, FALLBACK_NONE)`` when the batch is
    structurally valid. The mapping is keyed by the wire-level
    ``index`` token (``0..N-1``) of each eligible item, NOT by
    the original position in the rendered ``CustomerResponse``
    list. The caller maps back to the original positions using
    the eligible items it built.

    The parser is strict about structure: ``items`` must be a list
    of exactly ``eligible_count`` objects, each carrying only
    ``index``, ``prefix`` and ``suffix``. Indices must match the
    eligible-only batch exactly once and in order
    (``0, 1, ..., N-1``).

    Per-item wrapper content (digits, line breaks, question marks,
    control characters, excessive length) is NOT enforced here: a
    malformed wrapper is treated as an invalid individual item,
    not as a malformed batch. The caller falls back per-item and
    emits ``FALLBACK_WRAPPER_INVALID`` so the remaining items can
    still be styled.
    """
    if not isinstance(payload, dict):
        return None, FALLBACK_MALFORMED_BATCH
    if set(payload.keys()) != {"items"}:
        return None, FALLBACK_MALFORMED_BATCH
    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        return None, FALLBACK_MALFORMED_BATCH
    if len(raw_items) != eligible_count:
        return None, FALLBACK_MALFORMED_BATCH
    parsed: dict[int, tuple[Any, Any]] = {}
    for position, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            return None, FALLBACK_MALFORMED_BATCH
        if set(raw_item.keys()) != {"index", "prefix", "suffix"}:
            return None, FALLBACK_MALFORMED_BATCH
        raw_index = raw_item["index"]
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            return None, FALLBACK_MALFORMED_BATCH
        if raw_index != position:
            return None, FALLBACK_MALFORMED_BATCH
        parsed[raw_index] = (raw_item["prefix"], raw_item["suffix"])
    return parsed, FALLBACK_NONE


def _composed_message(
    response: CustomerResponse,
    *,
    prefix: str,
    suffix: str,
) -> str:
    return f"{prefix}{response.message}{suffix}"


def _wrapper_preserves_factual(
    original: CustomerResponse,
    *,
    prefix: str,
    suffix: str,
) -> bool:
    """Return ``True`` when the composed wrapper keeps the original
    factual message intact as a contiguous substring.
    """
    if not isinstance(prefix, str) or not isinstance(suffix, str):
        return False
    composed = _composed_message(original, prefix=prefix, suffix=suffix)
    if not composed.startswith(prefix):
        return False
    if not composed.endswith(suffix):
        return False
    return original.message in composed


def _emit_diagnostic(
    *,
    outcome: str | None,
    flavor_code: str | None,
    eligible_count: int,
    applied_count: int,
    elapsed_ms: int,
    failure_category: str | None,
    exception_type: str | None,
    stream: Any = None,
) -> None:
    """Emit one bounded observability event for a styler attempt.

    The event payload intentionally excludes the prompt, the
    ``instruccion_llm`` text, customer text, factual response
    text, model output and any business identifier. The static
    prompt-template identity is derived exclusively from the
    static template body and is therefore safe to embed.

    Every event carries the bounded template-identity fields
    ``outbound_style_prompt_template_version`` and
    ``outbound_style_prompt_template_hash`` so operators can
    correlate styler attempts with prompt drift without ever
    persisting or streaming the rendered prompt.

    The contract mirrors the existing LLM-request event family:
    success-style outcomes (``attempted``, ``not_attempted``,
    ``applied``) declare exactly ``outcome``; failure-style
    outcomes declare exactly ``failure_category``. The two are
    mutually exclusive.
    """
    identity = outbound_style_template_identity()
    payload_kwargs: dict[str, Any] = {
        "event": EVENT_OUTBOUND_STYLE,
        "component": COMPONENT_OUTBOUND_STYLE,
        "eligible_count": int(eligible_count),
        "applied_count": int(applied_count),
        "elapsed_ms": int(elapsed_ms),
        "outbound_style_prompt_template_version": str(
            identity["outbound_style_prompt_template_version"]
        ),
        "outbound_style_prompt_template_hash": str(
            identity["outbound_style_prompt_template_hash"]
        ),
    }
    if outcome is not None:
        payload_kwargs["outcome"] = outcome
    if failure_category is not None:
        payload_kwargs["failure_category"] = failure_category
    if flavor_code is not None:
        payload_kwargs["flavor_code"] = flavor_code
    if exception_type is not None:
        payload_kwargs["exception_type"] = exception_type
    if stream is not None:
        payload_kwargs["stream"] = stream
    emit_event(**payload_kwargs)


def _now(clock: Callable[[], float] | None) -> float:
    if clock is None:
        import time as _time

        return _time.monotonic()
    return clock()


def style_responses(
    db: DatabaseSession,
    comercio_id: int | None,
    responses: Sequence[CustomerResponse],
    *,
    query_llm: QueryLlm | None = None,
    clock: Callable[[], float] | None = None,
    stream: Any = None,
) -> list[CustomerResponse]:
    """Apply the optional bounded styler to ``responses``.

    Returns a new list that preserves the order, ``intent`` and
    ``status`` of every input response. Eligible items carry a
    wrapped ``message``; ineligible items and any eligible item
    that fails wrapper validation keep the original ``message``
    byte-for-byte.

    The function never raises: every internal exception becomes a
    bounded fallback outcome. The function never calls any
    database transaction-control method on ``db``.
    """
    materialised: list[CustomerResponse] = list(responses) if responses else []
    eligible = select_eligible(materialised)

    if not eligible:
        _emit_diagnostic(
            outcome=OUTCOME_NOT_ATTEMPTED,
            flavor_code=None,
            eligible_count=0,
            applied_count=0,
            elapsed_ms=0,
            failure_category=None,
            exception_type=None,
            stream=stream,
        )
        return materialised

    flavor = _resolve_flavor(db, comercio_id)
    if not _is_flavor_usable(flavor):
        _emit_diagnostic(
            outcome=OUTCOME_NOT_ATTEMPTED,
            flavor_code=None,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=0,
            failure_category=None,
            exception_type=None,
            stream=stream,
        )
        return materialised

    flavor_code = str(getattr(flavor, "codigo", "") or "")
    instruction = str(getattr(flavor, "instruccion_llm", "") or "")

    prompt_items: list[dict[str, object]] = [
        {"index": item.batch_position, "response_type": item.response_type}
        for item in eligible
    ]
    rendered_prompt = build_outbound_style_prompt(
        instruccion_llm=instruction,
        items=prompt_items,
    )

    client = query_llm if query_llm is not None else QueryLlm()
    started = _now(clock)

    try:
        payload = client.request(rendered_prompt)
    except QueryLlmTimeoutError:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_TIMEOUT,
            exception_type="QueryLlmTimeoutError",
            stream=stream,
        )
        return materialised
    except QueryLlmConnectionError:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_CONNECTION,
            exception_type="QueryLlmConnectionError",
            stream=stream,
        )
        return materialised
    except QueryLlmHttpError:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_HTTP,
            exception_type="QueryLlmHttpError",
            stream=stream,
        )
        return materialised
    except QueryLlmResponseError:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_RESPONSE,
            exception_type="QueryLlmResponseError",
            stream=stream,
        )
        return materialised
    except QueryLlmError:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_UNEXPECTED,
            exception_type="QueryLlmError",
            stream=stream,
        )
        return materialised
    except Exception as exc:  # noqa: BLE001 - styler is the last-resort guard
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_UNEXPECTED,
            exception_type=type(exc).__name__,
            stream=stream,
        )
        return materialised

    parsed, batch_category = _parse_wrappers(
        payload, eligible_count=len(eligible)
    )
    if parsed is None:
        elapsed_ms = int((_now(clock) - started) * 1000)
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=batch_category,
            exception_type=None,
            stream=stream,
        )
        return materialised

    applied_count = 0
    styled: list[CustomerResponse] = list(materialised)
    for eligible_item in eligible:
        wrapper = parsed.get(eligible_item.batch_position)
        if wrapper is None:
            continue
        raw_prefix, raw_suffix = wrapper
        prefix = _safe_short_wrapper(raw_prefix)
        suffix = _safe_short_wrapper(raw_suffix)
        if prefix is None or suffix is None:
            continue
        original = styled[eligible_item.index]
        if not _wrapper_preserves_factual(
            original, prefix=prefix, suffix=suffix
        ):
            continue
        styled[eligible_item.index] = CustomerResponse(
            message=_composed_message(original, prefix=prefix, suffix=suffix),
            intent=original.intent,
            status=original.status,
        )
        applied_count += 1

    elapsed_ms = int((_now(clock) - started) * 1000)
    if applied_count == 0:
        _emit_diagnostic(
            outcome=None,
            flavor_code=flavor_code,
            eligible_count=len(eligible),
            applied_count=0,
            elapsed_ms=elapsed_ms,
            failure_category=FALLBACK_WRAPPER_INVALID,
            exception_type=None,
            stream=stream,
        )
        return materialised

    _emit_diagnostic(
        outcome=OUTCOME_APPLIED,
        flavor_code=flavor_code,
        eligible_count=len(eligible),
        applied_count=applied_count,
        elapsed_ms=elapsed_ms,
        failure_category=None,
        exception_type=None,
        stream=stream,
    )
    return styled


def styler_version() -> str:
    """Return the static prompt template version embedded in the styler."""
    return OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION


def styler_fingerprint() -> str:
    """Return the static prompt template fingerprint embedded in the styler."""
    identity = outbound_style_template_identity()
    return str(identity["outbound_style_prompt_template_hash"])


__all__ = [
    "COMPONENT_OUTBOUND_STYLE",
    "EVENT_OUTBOUND_STYLE",
    "EXECUTED_STATUS",
    "FALLBACK_CONNECTION",
    "FALLBACK_HTTP",
    "FALLBACK_MALFORMED_BATCH",
    "FALLBACK_NONE",
    "FALLBACK_RESPONSE",
    "FALLBACK_TIMEOUT",
    "FALLBACK_UNEXPECTED",
    "FALLBACK_WRAPPER_INVALID",
    "NEUTRO_FLAVOR_CODE",
    "OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION",
    "OUTCOME_APPLIED",
    "OUTCOME_ATTEMPTED",
    "OUTCOME_NOT_ATTEMPTED",
    "RESPONSE_TYPE_INFO_ADDRESS",
    "RESPONSE_TYPE_INFO_DELIVERY_METHODS",
    "RESPONSE_TYPE_INFO_HOURS",
    "RESPONSE_TYPE_INFO_PAYMENT_METHODS",
    "RESPONSE_TYPE_MENU_CATEGORY",
    "RESPONSE_TYPE_MENU_FULL",
    "RESPONSE_TYPE_ORDER_CONFIRMED",
    "RESPONSE_TYPE_ORDER_EMPTIED",
    "RESPONSE_TYPE_ORDER_STARTED",
    "RESPONSE_TYPE_ORDER_STATUS",
    "RESPONSE_TYPE_ORDER_SUMMARY",
    "RESPONSE_TYPE_PRODUCT_ADD_SUCCESS",
    "RESPONSE_TYPE_PRODUCT_INFO",
    "RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS",
    "RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS",
    "RESPONSE_TYPE_SOCIAL_GOODBYE",
    "RESPONSE_TYPE_SOCIAL_GREETING",
    "RESPONSE_TYPE_SOCIAL_NO",
    "RESPONSE_TYPE_SOCIAL_THANKS",
    "RESPONSE_TYPE_SOCIAL_YES",
    "EligibleResponse",
    "is_eligible_response",
    "response_type_for",
    "select_eligible",
    "style_responses",
    "styler_fingerprint",
    "styler_version",
]