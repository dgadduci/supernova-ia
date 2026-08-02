import logging
from typing import Any, Protocol, cast

from backend.diagnostics import (
    ClassifierCallCompleted,
    ClassifierCallStarted,
    NoopDiagnosticSink,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.intent_classification import IntentClassificationResult
from backend.llm.query_llm import QueryLlm


class _QueryLlmLike(Protocol):
    def request(self, prompt: str) -> dict[str, Any]: ...


logger = logging.getLogger(__name__)


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


class IntentClassifier:
    def __init__(
        self,
        query_llm: _QueryLlmLike | None = None,
        *,
        sink: DiagnosticSink | None = None,
    ) -> None:
        self._query_llm: _QueryLlmLike = query_llm if query_llm is not None else QueryLlm()
        self._sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()

    def _build_prompt(self, message: str) -> str:
        return f"""
Catálogo de posibles intents:
{_INTENT_CATALOG}

message
{message}

Instrucciones
Debes devolver del Catalogo de intents, los intent que mejor se adapten al mensaje, siguiendo la estructura json que te envio de ejemplo
Tambien debes devolver el message recibido
Si el mensaje incluye varios intents, envialos como en el ejemplo del json
Cuando detectes que se pide reemplazar un producto por otro, genera un único intent `modificar_producto` con el mensaje original completo. NO descomponas en `quitar_producto` + `agregar_producto`; el orquestador `modificar_producto` realiza la sustitución atómica en una sola operación.
Cuando se trate de productos, separalos por producto y cantidad (si se especifica) en distintos intents

Regla de no modificacion del mensaje
El texto del mensaje recibido no debe ser alterado. Podes usar todo o partes, pero no modificarlo
{_OUTPUT_STRUCT}
"""

    def query(
        self,
        message: str,
        *,
        active_context_type: object | None = None,
        active_pending_intent: object | None = None,
        queued_intent_count: int = 0,
        prompt_name: object | None = None,
        model: object | None = None,
    ) -> IntentClassificationResult:
        if not isinstance(message, str):
            raise TypeError(
                f"El mensaje debe ser una cadena de texto, recibido: {type(message).__name__}"
            )

        cleaned = message.strip()
        if not cleaned:
            raise ValueError("El mensaje no puede estar vacío")

        logger.info("intent_classification start message_chars=%s", len(cleaned))
        start_event = ClassifierCallStarted(
            raw_message=message,
            normalized_message=cleaned,
            active_context_type=active_context_type,
            has_active_pending_intent=active_pending_intent is not None,
            active_pending_intent=active_pending_intent,
            queued_intent_count=queued_intent_count,
            classifier_class=type(self).__name__,
            classifier_method="query",
            prompt_name=prompt_name,
            model=model,
        )
        self._sink.on_classifier_started(start_event)
        parse_errors: list[object] = []
        fallback_state: object = None
        result_payload: object = None
        try:
            try:
                payload = self._query_llm.request(self._build_prompt(cleaned))
            except Exception as exc:
                parse_errors.append(type(exc).__name__)
                logger.info(
                    "intent_classification failure error_type=%s", type(exc).__name__
                )
                raise

            try:
                result = IntentClassificationResult.model_validate(payload)
            except Exception as exc:
                parse_errors.append(type(exc).__name__)
                logger.info(
                    "intent_classification failure error_type=%s", type(exc).__name__
                )
                raise

            result_payload = result
            logger.info(
                "intent_classification success intents_count=%s", len(result.intents)
            )
            logger.debug("intent_classification result: %s", result.model_dump())
            return result
        finally:
            completed_event = ClassifierCallCompleted(
                result=result_payload,
                intent_count=(
                    len(cast(Any, result_payload).intents)  # type: ignore[union-attr]
                    if result_payload is not None
                    else 0
                ),
                parse_errors=parse_errors,
                fallback_state=fallback_state,
            )
            self._sink.on_classifier_completed(completed_event)


__all__ = ["IntentClassifier"]