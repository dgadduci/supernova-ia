"""Versioned metadata for the IntentClassifier prompt template.

The template body lives here (not in ``intent_classifier``) so the runtime
diagnostic fingerprint can be derived exclusively from the static template
contract. Runtime diagnostics never persist, emit, or correlate the rendered
prompt or the customer message; only the static template fingerprint is
exposed.

The fingerprint is a stable SHA-256 derived ONLY from the static template
body (never from a rendered prompt) and therefore changes whenever any
character of the static template body changes. This lets the audit detect
silent prompt drift between runs even when ``PROMPT_TEMPLATE_VERSION`` is left
untouched.

The :func:`prompt_fingerprint` helper remains for the controlled audit
runner, which already exposes the full rendered prompt in its report; it
MUST NOT be used from the runtime diagnostic path.
"""

from __future__ import annotations

import hashlib

PROMPT_TEMPLATE_VERSION = "intent-classifier/v1.1.0"

_INTENT_CATALOG = """
* Si el cliente saluda = `saludo`
* Si el cliente agradece = `agradecimiento`
* Si el cliente se despide o da por terminada la conversación = `despedida`
* Si responde afirmativamente a una pregunta previa = `respuesta_afirmativa`
* Si responde negativamente a una pregunta previa = `respuesta_negativa`
* Si quiere ver la carta o menú = `ver_menu`
* Si consulta por un producto, precio, tamaño, variante, ingredientes o disponibilidad = `consultar_producto`
* Si consulta por los medios de pago aceptados = `ver_metodos_de_pago`
* Si consulta por las formas de entrega disponibles = `ver_metodos_de_entrega`
* Si consulta el domicilio o ubicación del comercio = `consultar_domicilio_comercio`
* Si consulta los días u horarios de atención = `consultar_horarios_comercio`
* Si quiere comenzar un pedido pero todavía no indica productos = `iniciar_pedido`
* Si quiere agregar uno o más productos al pedido = `agregar_producto`
* Si quiere quitar uno o más productos del pedido = `quitar_producto`
* Si quiere sustituir o modificar un producto por otro producto distinto, se debe generar un único intent `modificar_producto` con el mensaje original completo del cliente. NO se debe descomponer en `quitar_producto` + `agregar_producto`; el orquestador `modificar_producto` se encarga de la sustitución atómica en una sola operación.
* Si quiere eliminar todos los productos del pedido actual = `vaciar_pedido`
* Si quiere agregar, modificar o eliminar una aclaración sobre un producto = `set_observacion_producto`
* Si quiere agregar, modificar o eliminar una aclaración general del pedido = `set_observacion_pedido`
* Si quiere consultar los productos cargados, cantidades, subtotal o resumen del pedido actual = `consultar_resumen_pedido`
* Si establece o cambia la forma de entrega, como delivery, retiro en local o consumo en salón = `set_metodo_de_entrega`
* Si establece o cambia el domicilio de entrega = `set_direccion_entrega`
* Si establece, cambia o elimina la fecha u hora programada del pedido = `set_fecha_hora_entrega`
* Si establece o cambia el medio de pago = `set_metodo_de_pago`
* Si quiere confirmar y enviar definitivamente el pedido = `confirmar_pedido`
* Si consulta el estado de un pedido ya confirmado = `consultar_estado_pedido`
* Si quiere cancelar un pedido ya confirmado = `cancelar_pedido`
* Si el mensaje no puede interpretarse con suficiente seguridad = `desconocida`

* Las intents deben conservar el orden en que deben ejecutarse.

Ejemplo:

Mensaje:

`Cambiame la pizza de mozzarella por una napolitana`

Salida:

```json
{
  "intents": [
    {
      "intent": "modificar_producto",
      "mensaje": "Cambiame la pizza de mozzarella por una napolitana"
    }
  ],
  "mensaje": "Cambiame la pizza de mozzarella por una napolitana"
}
```

"""

_OUTPUT_STRUCT = """
Devolvé únicamente JSON válido.
No expliques nada.
No uses Markdown.
ejemplo:
{
    "intents": [
        {
            "intent": "agregar_producto",
            "mensaje": "una empanada de carne"
        },
        {
            "intent": "agregar_producto",
            "mensaje": "dos pizzas de mozzarella"
        },
        {
            "intent": "set_metodo_de_entrega",
            "mensaje": "me la envies a tilcara 2020."
        },
        {
            "intent": "set_metodo_de_pago",
            "mensaje": "Pago en efectivo"
        }
    ],
    "mensaje": "quiero una empanada de carne y dos pizzas de mozzarella y que me la envies a tilcara 2020. Pago en efectivo"
}
"""

# Static template body with a placeholder for the customer message. The
# fingerprint is computed over this body so it is never influenced by
# customer text. ``{message}`` is replaced at render time via ``str.replace``
# (not ``str.format``) so the literal braces in the JSON example below do
# not need to be escaped.
_PROMPT_TEMPLATE_BODY = (
    "\n"
    "Catálogo de posibles intents:\n"
    f"{_INTENT_CATALOG}"
    "\n"
    "message\n"
    "{message}\n"
    "\n"
    "Instrucciones\n"
    "Debes devolver del Catalogo de intents, los intent que mejor se adapten al mensaje, siguiendo la estructura json que te envio de ejemplo\n"
    "Tambien debes devolver el message recibido\n"
    "Si el mensaje incluye varios intents, envialos como en el ejemplo del json\n"
    "Cuando detectes que se pide reemplazar un producto por otro, genera un único intent `modificar_producto` con el mensaje original completo. NO descomponas en `quitar_producto` + `agregar_producto`; el orquestador `modificar_producto` realiza la sustitución atómica en una sola operación.\n"
    "Cuando se trate de productos, separalos por producto y cantidad (si se especifica) en distintos intents\n"
    "\n"
    "Regla de no modificacion del mensaje\n"
    "El texto del mensaje recibido no debe ser alterado. Podes usar todo o partes, pero no modificarlo\n"
    "\n"
    "Regla de grounded intents\n"
    "Cada intent devuelto debe estar respaldado por texto del mensaje recibido. No inventes productos, direcciones, medios de pago ni métodos de entrega que el cliente no haya mencionado. Un mensaje que expresa una única acción (por ejemplo, \"Pago en Efectivo (prueba cierre)\") debe generar exactamente un intent correspondiente a esa acción y nada más; nunca lo descomponas en acciones no solicitadas.\n"
    f"{_OUTPUT_STRUCT}"
    "\n"
)

_PROMPT_TEMPLATE_HASH = hashlib.sha256(_PROMPT_TEMPLATE_BODY.encode("utf-8")).hexdigest()


def template_fingerprint() -> str:
    """Return the static SHA-256 fingerprint of the active prompt template.

    The fingerprint is derived only from the static template body (never from
    a rendered prompt) and is therefore safe to expose in runtime
    diagnostics. Inputs that share the same template version produce the
    same fingerprint; changing the template body (intentionally or
    otherwise) is detected by a different fingerprint even when
    ``PROMPT_TEMPLATE_VERSION`` is left untouched.
    """
    return _PROMPT_TEMPLATE_HASH


def prompt_fingerprint(rendered_prompt: str) -> str:
    """Hash an arbitrary rendered prompt string.

    This helper is reserved for the controlled audit runner, which already
    exposes the full rendered prompt in its report. Runtime diagnostics MUST
    use :func:`template_fingerprint` instead so that customer messages are
    never mixed into the persisted/streamed fingerprint.
    """
    return hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()


def build_intent_prompt(message: str) -> str:
    """Render the active prompt template for the given customer message.

    The returned string is the rendered prompt that production would send
    to the upstream LLM. Runtime diagnostics MUST NOT persist or stream it;
    only the static :func:`template_fingerprint` may be exposed.
    """
    return _PROMPT_TEMPLATE_BODY.replace("{message}", message)


def template_identity() -> dict[str, str]:
    """Return non-secret identity metadata for the active prompt template."""
    return {
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "prompt_template_hash": _PROMPT_TEMPLATE_HASH,
    }


__all__ = [
    "PROMPT_TEMPLATE_VERSION",
    "build_intent_prompt",
    "prompt_fingerprint",
    "template_fingerprint",
    "template_identity",
]
