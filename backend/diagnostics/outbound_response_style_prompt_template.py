"""Versioned static prompt template for the experimental full-message
outbound styler.

This module hosts the static, versioned prompt contract used by the
experimental outbound styler. The styler makes at most one batched
LLM call per inbound turn for eligible ``CustomerResponse`` items and
replaces ONLY the customer-visible ``message`` of each eligible item
with the LLM-generated natural full message; intent, status and
response order are preserved untouched.

The prompt template is the single source of the factual-preservation
hierarchy and MUST repeat the immutable rules immediately before the
output schema AND immediately after the flavor directive so the
directive can never displace the authoritative facts supplied by the
deterministic backend.

The runtime prompt contains **only**:

* the selected flavor's bounded internal ``instruccion_llm`` text;
* the ordered eligible ``response_type`` token;
* the deterministic ``factual_message`` for that eligible item (this
  is the only authorized source of business facts).

It MUST NOT contain the inbound customer message, ineligible
response text, product IDs, presentation codes, customer/session/
pedido/comercio identifiers, or any other business identifier. The
fingerprint is therefore stable across comercios, customers and
ineligible inputs so runtime diagnostics that embed the fingerprint
leak no business information.

The runtime items block is rendered with ``json.dumps`` (UTF-8,
``ensure_ascii=False``) so the deterministic factual content is
transmitted with safe, unambiguous JSON delimiters (escaped quotes,
backslashes and line breaks). The block is NEVER built by raw string
interpolation; it is appended to the static body only as a serialized
JSON object literal.

The closed JSON envelope is:

* request: ``{"items": [{"index", "response_type",
  "factual_message"}, ...]}`` in the eligible-only batch order;
* response: ``{"items": [{"index", "message"}, ...]}`` with the
  same count, indices and ordering, no extra fields and a non-empty
  string ``message`` per item. The ``message`` may contain regular
  line breaks (``\\n``) so a menu can be rephrased on multiple lines;
  any other ASCII control character, ``\\r`` line endings, ``\\t`` or
  NUL bytes are rejected per item.

The parser is strictly structural: it validates the envelope shape,
exact item count, exact index order and that every ``message`` is a
non-empty string with no disallowed ASCII control characters. Line
breaks (``\\n``) are allowed and ``\\r\\n`` is normalized to ``\\n``
before the ``CustomerResponse`` is constructed. The parser
deliberately does NOT compare the LLM output with
``factual_message`` (no semantic validator, no protected-token
comparison). When the envelope is invalid the entire batch falls back
to the original deterministic messages; when only a single item is
invalid that item falls back to its factual message but the rest of
the batch is still applied.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION = "outbound-response-styler/v2.1.0"

_INTRO = (
    "\n"
    "Sos un asistente de presentación para un comercio. Recibís una "
    "lista ordenada de mensajes factuales ya redactados por el sistema "
    "y debés devolver una versión natural y breve de cada uno, en el "
    "mismo orden. Tu única salida es JSON válido: nada de Markdown, "
    "nada de explicaciones.\n"
)

_CONTEXT = """
Contexto:

* Recibís una instrucción interna de tono (la "directriz") que describe el estilo global seleccionado por el comercio. Esa directriz NO contiene pedidos, productos, clientes ni datos privados.
* Recibís, al final del prompt, un bloque JSON cerrado con la lista de mensajes factuales en el orden estricto en que deben renderizarse. Cada elemento lleva un `index` (entero), un `response_type` (categoría de mensaje) y un `factual_message` (el mensaje ya redactado por el sistema).
* NO tenés acceso al mensaje entrante del cliente, al pedido, al menú completo (más allá del `factual_message`), a la sesión, al comercio, a la dirección, a la observación, al medio de pago o entrega, a IDs ni a credenciales. NO los infieras ni los pidas.

"""

_RULES = """
Reglas inquebrantables:

1. La única fuente autorizada de hechos es el `factual_message` recibido. Todo hecho concreto presente en él debe aparecer en tu salida, sin agregar, omitir, sustituir, transformar ni reordenar hechos.

2. Hechos concretos que debés preservar cuando estén presentes en el `factual_message`:
   * productos y sus presentaciones;
   * cantidades;
   * precios;
   * fechas y horarios;
   * estados del pedido;
   * opciones, condiciones y elecciones;
   * cada línea de menú cuando el `factual_message` es un menú completo o por categoría.

3. NO inventes ni agregues: productos, promociones, descuentos, tiempos estimados, promesas, instrucciones, preguntas, comandos, datos de entrega, datos de pago ni información del comercio. NO hagas suposiciones sobre el cliente.

4. NO modifiques el contenido factual. Tu trabajo es reescribir el mismo mensaje en lenguaje natural y breve, respetando el orden y la cantidad de hechos.

5. Devolvé EXACTAMENTE el JSON indicado en la sección "Estructura de salida". No expliques nada. No uses Markdown. Cada ítem debe llevar únicamente `index` y `message`.

"""

_OUTPUT_STRUCT = """
Estructura de salida:

Devolvé únicamente JSON válido.
No expliques nada.
No uses Markdown.
El JSON debe respetar EXACTAMENTE esta forma (campos extra prohibidos):

{
  "items": [
    {
      "index": <entero>,
      "message": "<mensaje natural completo, breve, en español>"
    }
  ]
}

`items` debe tener EXACTAMENTE la misma cantidad de elementos, en el mismo orden y con los mismos `index` que la lista recibida. No omitas, no dupliques, no reordenes.

`message` debe ser una cadena no vacía en español, en una sola unidad de presentación al cliente (puede incluir saltos de línea si el `factual_message` los traía, como en un menú).

"""

_FLAVOR_PROMPT = (
    "\n"
    "Directriz interna de tono (NO contiene datos privados):\n"
    "\n"
    "{instruccion_llm}\n"
)

_FACTUAL_REAFFIRMATION = """
Reafirmación factual (prevalece sobre la directriz de tono):

A. La única fuente autorizada de hechos es el `factual_message` que aparece serializado en el bloque JSON inferior. Tu salida debe contener exactamente esos hechos y ningún otro.

B. Debés preservar, cuando estén presentes en el `factual_message`: productos y sus presentaciones, cantidades, precios, fechas, horarios, estados del pedido, opciones, condiciones y cada línea de menú cuando el `factual_message` sea un menú completo o por categoría.

C. NO agregues, omitas, sustituyas, transformes ni reordenes hechos. NO inventes descuentos, promesas, tiempos, instrucciones, preguntas, comandos, datos de pago o entrega ni información del comercio.

D. La directriz de tono ajusta exclusivamente vocabulario, calidez y registro. Si la directriz entra en conflicto con estas reglas, estas reglas prevalecen sin excepción.

E. Devolvé únicamente el JSON indicado, sin Markdown ni explicaciones adicionales. Cada ítem lleva sólo `index` y `message` (cadena no vacía que puede contener saltos de línea cuando el `factual_message` sea un menú).

"""

_RUNTIME_ITEMS_PROMPT = (
    "\n"
    "Bloque JSON cerrado con los mensajes factuales a reescribir "
    "(la única fuente autorizada de hechos):\n"
    "\n"
    "{items}\n"
)


def _render_runtime_items_json(items: list[dict[str, object]]) -> str:
    """Serialise the runtime items list as a pretty-printed JSON
    object with safe delimiters.

    The ``items`` list MUST already be projected to the documented
    ``{"index": <int>, "response_type": <token>,
    "factual_message": <str>}`` shape. The returned string is a
    valid JSON literal (``{"items": [...]}``) suitable for direct
    inclusion in the rendered prompt; runtime diagnostics MUST NOT
    persist or stream it. Serialisation uses ``ensure_ascii=False``
    so Unicode characters (accented Spanish letters, emojis, etc.)
    are preserved verbatim inside the prompt without leaking
    diagnostic signals via escape sequences.
    """
    payload: dict[str, list[dict[str, Any]]] = {"items": []}
    for item in items:
        payload["items"].append(
            {
                "index": item.get("index", ""),
                "response_type": item.get("response_type", ""),
                "factual_message": item.get("factual_message", ""),
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)


_PROMPT_TEMPLATE_BODY = (
    _INTRO
    + _CONTEXT
    + _RULES
    + _OUTPUT_STRUCT
    + _FLAVOR_PROMPT
    + _FACTUAL_REAFFIRMATION
    + _RUNTIME_ITEMS_PROMPT
)

_PROMPT_TEMPLATE_HASH = hashlib.sha256(_PROMPT_TEMPLATE_BODY.encode("utf-8")).hexdigest()


def outbound_style_template_fingerprint() -> str:
    """Return the static SHA-256 fingerprint of the active styler prompt.

    The fingerprint is derived only from the static template body
    (never from a rendered prompt, the selected flavor instruction or
    the runtime items JSON) and is therefore safe to expose in
    runtime diagnostics. Inputs that share the same template version
    produce the same fingerprint; changing the template body is
    detected by a different fingerprint even when
    ``OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION`` is left untouched.
    """
    return _PROMPT_TEMPLATE_HASH


def build_outbound_style_prompt(
    *,
    instruccion_llm: str,
    items: list[dict[str, object]],
) -> str:
    """Render the active styler prompt for the given flavor directive
    and ordered eligible items.

    The runtime items block is serialised as a closed JSON literal
    via :func:`_render_runtime_items_json`. The static body keeps
    the ``{instruccion_llm}`` placeholder for the bounded flavor
    directive. The returned string is what production would send to
    the upstream LLM; runtime diagnostics MUST NOT persist or stream
    it.
    """
    items_block = _render_runtime_items_json(items)
    rendered = _PROMPT_TEMPLATE_BODY.replace("{instruccion_llm}", instruccion_llm)
    return rendered.replace("{items}", items_block)


def outbound_style_template_identity() -> dict[str, str]:
    """Return non-secret identity metadata for the active styler prompt."""
    return {
        "outbound_style_prompt_template_version": OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        "outbound_style_prompt_template_hash": _PROMPT_TEMPLATE_HASH,
    }


__all__ = [
    "OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION",
    "build_outbound_style_prompt",
    "outbound_style_template_fingerprint",
    "outbound_style_template_identity",
]