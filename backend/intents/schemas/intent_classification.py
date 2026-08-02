from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntentName(StrEnum):
    SALUDO = "saludo"
    AGRADECIMIENTO = "agradecimiento"
    DESPEDIDA = "despedida"
    RESPUESTA_AFIRMATIVA = "respuesta_afirmativa"
    RESPUESTA_NEGATIVA = "respuesta_negativa"
    VER_MENU = "ver_menu"
    CONSULTAR_PRODUCTO = "consultar_producto"
    VER_METODOS_DE_PAGO = "ver_metodos_de_pago"
    VER_METODOS_DE_ENTREGA = "ver_metodos_de_entrega"
    CONSULTAR_DOMICILIO_COMERCIO = "consultar_domicilio_comercio"
    CONSULTAR_HORARIOS_COMERCIO = "consultar_horarios_comercio"
    INICIAR_PEDIDO = "iniciar_pedido"
    AGREGAR_PRODUCTO = "agregar_producto"
    QUITAR_PRODUCTO = "quitar_producto"
    MODIFICAR_PRODUCTO = "modificar_producto"
    VACIAR_PEDIDO = "vaciar_pedido"
    SET_OBSERVACION_PRODUCTO = "set_observacion_producto"
    SET_OBSERVACION_PEDIDO = "set_observacion_pedido"
    CONSULTAR_RESUMEN_PEDIDO = "consultar_resumen_pedido"
    SET_METODO_DE_ENTREGA = "set_metodo_de_entrega"
    SET_DIRECCION_ENTREGA = "set_direccion_entrega"
    SET_FECHA_HORA_ENTREGA = "set_fecha_hora_entrega"
    SET_METODO_DE_PAGO = "set_metodo_de_pago"
    CONFIRMAR_PEDIDO = "confirmar_pedido"
    CONSULTAR_ESTADO_PEDIDO = "consultar_estado_pedido"
    CANCELAR_PEDIDO = "cancelar_pedido"
    DESCONOCIDA = "desconocida"


class _TrimmedNonEmptyStr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mensaje: str = Field(min_length=1)

    @field_validator("mensaje")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("mensaje must not be empty after trimming")
        return cleaned


class ClassifiedIntent(_TrimmedNonEmptyStr):
    intent: IntentName


class IntentClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[ClassifiedIntent] = Field(min_length=1)
    mensaje: str = Field(min_length=1)

    @field_validator("mensaje")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("mensaje must not be empty after trimming")
        return cleaned


__all__ = ["IntentName", "ClassifiedIntent", "IntentClassificationResult"]
