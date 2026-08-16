"""Versioned static prompt template for the safe outbound response styler.

The styler is the bounded second LLM interpreter that adds a short
presentation wrapper (``prefix`` / ``suffix``) around the exact
deterministic customer response. The prompt template body lives in
this module so the runtime diagnostic fingerprint can be derived
exclusively from the static template contract. Runtime diagnostics
never persist, emit, log or correlate the rendered prompt, the
``FlavorComunicacion.instruccion_llm`` payload, the customer
message, the deterministic response text or the model output; only
the static template fingerprint is exposed.

The runtime prompt contains **only**:

* the selected flavor's bounded internal ``instruccion_llm`` text;
* the ordered, allowlisted ``response_type`` tokens for every
  eligible ``CustomerResponse`` in the current turn.

It MUST NOT contain the inbound customer message, the deterministic
customer response text, product names, prices, presentation codes,
quantities, addresses, observations, payment/delivery values, IDs,
session data, pedido data, comercio data or any other customer or
business identifier. The fingerprint is therefore stable across
comercios, customers and inputs, so a runtime diagnostic that
embeds the fingerprint leaks no business information.

The schema is closed: the model must return ``{"items": [...]}``
where each item carries exactly ``index``, ``prefix`` and
``suffix``; extra fields are rejected. ``prefix`` and ``suffix``
are bounded, single-line, factual-free presentation fragments;
digits, line breaks, question marks and disallowed control
characters are forbidden. Each fragment accepts at most 96
characters and the combined length of both fragments for the same
eligible item is bounded to 140 characters. The wrapper may
include flavor-appropriate emojis when the selected persisted
flavor instruction calls for them; the wrapper itself must remain
generic and factual-free because the model only receives the
opaque ``response_type`` token.

Empty wrappers are explicitly forbidden: every eligible item MUST
produce at least one non-empty wrapper field so the visible style
is preserved when the active flavor is non-neutral. The backend
treats an empty (``""`` / ``""``) wrapper for an eligible item as
invalid, keeps the original factual message unchanged and records
the bounded ``empty_wrapper`` diagnostic category.

Menu wrapper calibration
------------------------

The opaque ``menu_full`` response-type token identifies the
deterministically rendered full menu (categories, products,
presentations and prices). The styler never asks the LLM to
author a menu: it only asks for a bounded, generic, one-line
framing phrase around the already-rendered menu. The LLM receives
only the ``menu_full`` token and the selected persisted flavor
instruction; it never sees menu text, catalog data or order data.

The static template body MUST keep making that boundary explicit
and MUST NOT prescribe a particular phrase or emoji for any
flavor; tone and emoji choices stay governed by the selected
``instruccion_llm``. An invalid ``menu_full`` wrapper preserves
the exact deterministic menu through the existing
``wrapper_invalid`` fallback.
"""
from __future__ import annotations

import hashlib

OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION = "outbound-response-styler/v1.3.0"

_INTRO = (
    "\n"
    "Sos un asistente de presentación que añade un prefijo y/o un "
    "sufijo a una respuesta ya redactada por el sistema. "
    "La respuesta original se conserva tal cual: tu único trabajo es "
    "sugerir un envoltorio visual breve, cálido y expresivo, "
    "dentro de los límites definidos más abajo.\n"
    "Respetá estrictamente las reglas y el contrato definidos más abajo.\n"
)

_CONTEXT = """
Contexto limitado:

* Recibís una instrucción interna de tono (la "directriz") que describe el estilo global seleccionado por el comercio. Esa directriz NO contiene pedidos, productos, clientes ni datos privados.
* Recibís una lista acotada de tipos de respuesta, en el orden en que deben renderizarse. Cada tipo es un token opaco que identifica una categoría de mensaje (por ejemplo un saludo, un agregado exitoso, una confirmación de respuesta).
* No tenés acceso al mensaje del cliente, al texto de la respuesta original, al catálogo, al menú, al pedido, a la dirección, a la observación, al medio de pago o entrega, a IDs, a datos de sesión ni a credenciales. No los infieras ni los pidas.

"""

_RULES = """
Reglas del envoltorio:

1. Devolvé EXACTAMENTE un objeto JSON con la forma indicada en la sección "Estructura de salida". No expliques nada. No uses Markdown.

2. Para cada ítem de la lista, devolvé un objeto con tres campos: `index` (entero que coincide con el orden de la lista), `prefix` (cadena) y `suffix` (cadena). No agregues ningún otro campo.

3. `prefix` y `suffix` son fragmentos visuales. Deben ser cadenas de una sola línea, sin dígitos, sin saltos de línea, sin signos de pregunta (`?`), sin caracteres de control ni caracteres no imprimibles. Cada campo puede tener hasta 96 caracteres y la suma de las longitudes de `prefix + suffix` para el mismo ítem NO puede superar 140 caracteres. Podés proponer una frase breve, cálida y expresiva (no una sola palabra suelta) que se vista alrededor del mensaje original, e incluir uno o más emojis coherentes con la directriz de tono cuando la directriz los solicite. La frase debe ser genérica para el `response_type` recibido: no debe afirmar, inferir ni prometer hechos del cliente, comercio, pedido o sesión.

4. **Visibilidad obligatoria**: para cada ítem elegible, al menos uno de los campos `prefix` o `suffix` debe ser una cadena NO vacía. Una respuesta con `prefix` y `suffix` ambos vacíos NO es una salida válida para un ítem elegible: el sistema rechazará ese ítem y la respuesta original quedará sin estilo visible.

5. NO inventes hechos, productos, cantidades, precios, descuentos, promesas, fechas, horas, direcciones, observaciones, medios de pago ni métodos de entrega. NO hagas preguntas ni des instrucciones. NO pidas confirmación ni des comandos.

6. NO traduzcas, NO corrijas ni alteres el contenido del mensaje original. La respuesta original la conserva el sistema: tu `prefix` y `suffix` sólo la visten.

7. NO generes contenido que dependa de un cliente, comercio, pedido o turno específico. Tu sugerencia debe servir para cualquier instancia del mismo `response_type`.

8. Si la directriz de tono entra en conflicto con las reglas anteriores, las reglas anteriores prevalecen.

"""

_MENU_FULL_RULE = """
Regla específica para `menu_full`:

El token opaco `menu_full` representa un menú ya redactado por el sistema, que incluye categorías, productos, presentaciones y precios. Para ese ítem tu único trabajo es proponer un envoltorio visual de una sola línea que enmarque ese menú ya redactado. La regla es:

* Solo podés proponer una frase genérica de una sola línea que envuelva el menú ya redactado.
* NO podés reproducir, resumir, enumerar, listar, titular, formatear ni describir el menú ni sus categorías, productos, presentaciones, precios o cantidades.
* NO podés introducir productos, presentaciones, categorías, precios, cantidades, descuentos ni hechos del pedido o del cliente.
* NO podés usar Markdown, bullets, saltos de línea, preguntas ni instrucciones al cliente.
* La creatividad, el tono y los emojis siguen siendo gobernados exclusivamente por la directriz interna de tono: no hardcodees una frase ni un emoji específicos para `menu_full` ni para ningún flavor.

Un envoltorio para `menu_full` que reproduzca, resuma, enumere, liste, titule, formatee o describa cualquier contenido del menú será rechazado y la respuesta original quedará sin estilo (fallback `wrapper_invalid`).

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
      "prefix": "<cadena de hasta 96 caracteres, salvo que el suffix provea visibilidad>",
      "suffix": "<cadena de hasta 96 caracteres, salvo que el prefix provea visibilidad>"
    }
  ]
}

Recordá: cada campo `prefix` y `suffix` admite como máximo 96 caracteres, y la suma de sus longitudes para un mismo ítem NO puede superar 140 caracteres. Para cada ítem, al menos uno de `prefix` o `suffix` debe ser una cadena NO vacía. Una salida con ambos vacíos para un ítem elegible será rechazada y la respuesta original quedará sin estilo.

`items` debe tener EXACTAMENTE la misma cantidad de elementos, en el mismo orden y con los mismos `index` que la lista de tipos recibida. No omitas, no dupliques, no reordenes.

"""

_FLAVOR_PROMPT = (
    "\n"
    "Directriz interna de tono (NO contiene datos privados):\n"
    "\n"
    "{instruccion_llm}\n"
)

_ITEMS_PROMPT = (
    "\n"
    "Tipos de respuesta a vestir, en orden estricto:\n"
    "\n"
    "{items}\n"
)

_PROMPT_TEMPLATE_BODY = (
    _INTRO
    + _CONTEXT
    + _RULES
    + _MENU_FULL_RULE
    + _OUTPUT_STRUCT
    + _FLAVOR_PROMPT
    + _ITEMS_PROMPT
)

_PROMPT_TEMPLATE_HASH = hashlib.sha256(_PROMPT_TEMPLATE_BODY.encode("utf-8")).hexdigest()


def outbound_style_template_fingerprint() -> str:
    """Return the static SHA-256 fingerprint of the active styler prompt.

    The fingerprint is derived only from the static template body
    (never from a rendered prompt or the selected flavor instruction)
    and is therefore safe to expose in runtime diagnostics. Inputs
    that share the same template version produce the same fingerprint;
    changing the template body is detected by a different fingerprint
    even when ``OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION`` is left
    untouched.
    """
    return _PROMPT_TEMPLATE_HASH


def build_outbound_style_prompt(
    *,
    instruccion_llm: str,
    items: list[dict[str, object]],
) -> str:
    """Render the active styler prompt for the given flavor directive
    and bounded response-type list.

    The items list must already be projected to the documented
    ``{"index": <int>, "response_type": <token>}`` shape in the
    intended render order. The returned string is what production
    would send to the upstream LLM; runtime diagnostics MUST NOT
    persist or stream it.
    """
    item_lines: list[str] = []
    for item in items:
        index = item.get("index", "")
        response_type = item.get("response_type", "")
        item_lines.append(f"- index: {index} | response_type: {response_type}")
    items_block = "\n".join(item_lines) if item_lines else "(sin elementos)"
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
