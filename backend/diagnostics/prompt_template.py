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

PROMPT_TEMPLATE_VERSION = "intent-classifier/v1.2.0"

_INTRO = (
    "\n"
    "Sos un clasificador de intents para un sistema de pedidos por WhatsApp.\n"
    "Tu única tarea es clasificar el mensaje del cliente que aparece al final de este prompt.\n"
    "Respetá estrictamente las reglas y el catálogo definidos más abajo.\n"
)

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

"""

_RULES = """
Reglas de clasificación:

1. Cada intent devuelto debe estar respaldado por texto del mensaje actual del cliente. No inventes productos, direcciones, medios de pago ni métodos de entrega que el cliente no haya mencionado.

2. No reutilices ni copies contenido del catálogo, de las reglas, de los ejemplos ni de ninguna otra sección de este prompt. Cada campo `mensaje` que devuelvas debe ser un substring literal del mensaje actual.

3. Un mensaje que expresa una única acción inequívoca debe generar exactamente un intent correspondiente a esa acción y nada más. Nunca lo descompones en acciones no solicitadas.

4. Solo devolvés múltiples intents cuando el mensaje actual exprese varias acciones distintas y ordenadas.

5. El texto del mensaje recibido no debe ser alterado. Podés usar todo o partes, pero no modificarlo.

6. Cuando detectes que se pide reemplazar un producto por otro, generá un único intent `modificar_producto` con el mensaje original completo. NO descomponas en `quitar_producto` + `agregar_producto`; el orquestador `modificar_producto` realiza la sustitución atómica en una sola operación.

7. Cuando se trate de productos, separalos por producto y cantidad (si se especifica) en distintos intents.

"""

_EXAMPLES = """
Ejemplos de referencia (NO los uses como contenido para clasificar el mensaje actual; solo ilustran el contrato de salida para cada caso):

Mensaje:
`Cómo puedo recibir el pedido?`

Salida:
```json
{
  "intents": [
    {
      "intent": "ver_metodos_de_entrega",
      "mensaje": "Cómo puedo recibir el pedido?"
    }
  ],
  "mensaje": "Cómo puedo recibir el pedido?"
}
```

Mensaje:
`La pizza es sin aceitunas`

Salida:
```json
{
  "intents": [
    {
      "intent": "set_observacion_producto",
      "mensaje": "La pizza es sin aceitunas"
    }
  ],
  "mensaje": "La pizza es sin aceitunas"
}
```

Mensaje:
`Por favor que la entrega sea sin demorarse mucho`

Salida:
```json
{
  "intents": [
    {
      "intent": "set_observacion_pedido",
      "mensaje": "Por favor que la entrega sea sin demorarse mucho"
    }
  ],
  "mensaje": "Por favor que la entrega sea sin demorarse mucho"
}
```

Mensaje:
`Me lo envias a Tilcara 2020`

Salida:
```json
{
  "intents": [
    {
      "intent": "set_direccion_entrega",
      "mensaje": "Me lo envias a Tilcara 2020"
    }
  ],
  "mensaje": "Me lo envias a Tilcara 2020"
}
```

Mensaje:
`Pago en Efectivo (prueba cierre)`

Salida:
```json
{
  "intents": [
    {
      "intent": "set_metodo_de_pago",
      "mensaje": "Pago en Efectivo (prueba cierre)"
    }
  ],
  "mensaje": "Pago en Efectivo (prueba cierre)"
}
```

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
Estructura de salida:

Devolvé únicamente JSON válido.
No expliques nada.
No uses Markdown.
El JSON debe respetar esta forma:

{
    "intents": [
        {
            "intent": "<nombre del intent del catálogo>",
            "mensaje": "<substring literal del mensaje actual>"
        }
    ],
    "mensaje": "<mensaje actual>"
}

"""

_MESSAGE_PROMPT = (
    "\n"
    "Mensaje actual del cliente (clasificá únicamente este mensaje):\n"
    "\n"
    "{message}\n"
)

# Static template body. ``{message}`` is replaced at render time via
# ``str.replace`` (not ``str.format``) so the literal braces in the JSON
# examples and structure above do not need to be escaped. The current
# customer message is the LAST section of the template; everything above
# (catalog, rules, examples, output structure) is fixed contract text.
_PROMPT_TEMPLATE_BODY = (
    _INTRO
    + "Catálogo de posibles intents:\n"
    + _INTENT_CATALOG
    + _RULES
    + _EXAMPLES
    + _OUTPUT_STRUCT
    + _MESSAGE_PROMPT
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
