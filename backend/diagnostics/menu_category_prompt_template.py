"""Versioned static prompt template for the dedicated menu category resolver.

The resolver is the bounded second LLM interpreter that decides which
single category, if any, a customer menu browse request refers to. The
prompt template body lives in this module so the runtime diagnostic
fingerprint can be derived exclusively from the static template
contract. Runtime diagnostics never persist, emit or correlate the
rendered prompt, the customer message or the candidate token/name
pairs; only the static template fingerprint is exposed.

The runtime prompt contains **only**:

* the classified ``ver_menu`` source text; and
* a bounded list of opaque ``(token, nombre)`` category candidate
  pairs from the current commerce.

It MUST NOT contain database IDs, product names, prices, presentation
codes, customer data, pedido data, aliases, settings, credentials or
provider data. The fingerprint is therefore stable across commerces,
customer messages and candidate lists, so a runtime diagnostic that
embeds the fingerprint leaks no business information.

The schema is closed: a selection requires both ``token`` and
``nombre``; a no-selection requires both to be ``null``. Extra fields
are forbidden. The prompt instructs the model to return ``null``
selection whenever it is uncertain or when more than one category is
justified.
"""
from __future__ import annotations

import hashlib

MENU_CATEGORY_PROMPT_TEMPLATE_VERSION = "menu-category-resolver/v1.1.0"

_INTRO = (
    "\n"
    "Sos un intérprete de lenguaje que decide a qué categoría de menú "
    "se refiere el mensaje del cliente que aparece al final de este "
    "prompt.\n"
    "Respetá estrictamente las reglas y el contrato definidos más abajo.\n"
)

_CONTEXT = """
Contexto limitado:

* Recibís el mensaje literal del cliente clasificado como `ver_menu`.
* Recibís una lista acotada de categorías disponibles en el comercio actual, identificadas únicamente por un token opaco (que no es un identificador real) y por su nombre exacto visible para el cliente.

No tenés acceso a identificadores de base, nombres de productos, precios, presentaciones, medios de pago, métodos de entrega, direcciones, datos del cliente, datos del pedido, configuración del comercio ni credenciales. No los infieras ni los pidas.
"""

_RULES = """
Reglas de decisión:

1. Devolvé EXACTAMENTE un objeto JSON con la forma indicada en la sección "Estructura de salida". No expliques nada. No uses Markdown.

2. Si el mensaje del cliente nombra o describe de forma inequívoca UNA sola categoría presente en la lista, devolvé esa categoría usando el mismo `token` y el mismo `nombre` exacto que aparecen en la lista. No inventes tokens ni transformes los nombres.

3. Si el mensaje nombra DOS o MÁS categorías distintas presentes en la lista (por ejemplo "qué pizzas y empanadas hay" o "qué pizzas, empanadas y bebidas tenés"), devolvé ambos campos en `null`. La presencia de más de una categoría visible nunca debe reducirse a una sola.

4. Si el mensaje nombra ninguna categoría de la lista, o la coincidencia es ambigua, devolvé ambos campos en `null`. La incertidumbre también es `null`.

5. No inventes categorías, productos ni subcategorías que no estén en la lista.

6. Considerá variaciones naturales de lenguaje, singular/plural y diferencias menores de ortografía o acentuación, pero solo dentro de los nombres efectivamente listados.

7. No devuelvas nunca un token sin su nombre ni un nombre sin su token. Deben corresponder siempre al mismo candidato de la lista.

"""

_CANDIDATE_BLOCK = """
Lista de categorías disponibles (cada una con su token opaco y su nombre exacto):

{candidates}

"""

_OUTPUT_STRUCT = """
Estructura de salida:

Devolvé únicamente JSON válido.
No expliques nada.
No uses Markdown.
El JSON debe respetar EXACTAMENTE esta forma (campos extra prohibidos):

{
  "token": "<token de la categoría elegida, o null>",
  "nombre": "<nombre exacto de la categoría elegida, o null>"
}

`token` y `nombre` deben coincidir con la misma entrada de la lista, o ambos deben ser `null`.

"""

_MESSAGE_PROMPT = (
    "\n"
    "Mensaje del cliente (interpreta únicamente este mensaje):\n"
    "\n"
    "{message}\n"
)

_PROMPT_TEMPLATE_BODY = (
    _INTRO
    + _CONTEXT
    + _RULES
    + _CANDIDATE_BLOCK
    + _OUTPUT_STRUCT
    + _MESSAGE_PROMPT
)

_PROMPT_TEMPLATE_HASH = hashlib.sha256(_PROMPT_TEMPLATE_BODY.encode("utf-8")).hexdigest()


def menu_category_template_fingerprint() -> str:
    """Return the static SHA-256 fingerprint of the active resolver prompt.

    The fingerprint is derived only from the static template body
    (never from a rendered prompt or a candidate list) and is
    therefore safe to expose in runtime diagnostics. Inputs that share
    the same template version produce the same fingerprint; changing
    the template body is detected by a different fingerprint even when
    ``MENU_CATEGORY_PROMPT_TEMPLATE_VERSION`` is left untouched.
    """
    return _PROMPT_TEMPLATE_HASH


def build_menu_category_prompt(
    message: str,
    candidates: list[dict[str, str]],
) -> str:
    """Render the active resolver prompt for the given classified menu
    query and bounded candidate list.

    The candidate list must already be projected to opaque
    ``{"token": ..., "nombre": ...}`` pairs in the configured order.
    The returned string is what production would send to the upstream
    LLM; runtime diagnostics MUST NOT persist or stream it.
    """
    candidate_lines: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        token = candidate.get("token", "")
        nombre = candidate.get("nombre", "")
        candidate_lines.append(f"- token: {token} | nombre: {nombre}")
    candidates_block = "\n".join(candidate_lines) if candidate_lines else "(sin categorías)"
    rendered = _PROMPT_TEMPLATE_BODY.replace("{candidates}", candidates_block)
    return rendered.replace("{message}", message)


def menu_category_template_identity() -> dict[str, str]:
    """Return non-secret identity metadata for the active resolver prompt."""
    return {
        "menu_category_prompt_template_version": MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
        "menu_category_prompt_template_hash": _PROMPT_TEMPLATE_HASH,
    }


__all__ = [
    "MENU_CATEGORY_PROMPT_TEMPLATE_VERSION",
    "build_menu_category_prompt",
    "menu_category_template_fingerprint",
    "menu_category_template_identity",
]