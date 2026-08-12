# Capability: draft-order-delivery-address

## ADDED Requirements

### Requirement: La dirección concreta se persiste sólo en el borrador activo

Cuando el clasificador existente devuelve `set_direccion_entrega`, el sistema SHALL normalizar y reemplazar `Pedido.direccion_entrega` únicamente en el pedido borrador correspondiente a la sesión activa. El campo SHALL ser texto nullable e independiente de `Pedido.observaciones` y `PedidoProducto.observaciones`. La entrada válida usa NFKC, trim y colapso de whitespace interno, con longitud de 1 a 500 code points.

#### Scenario: Dirección concreta reemplaza la dirección del borrador

- **WHEN** una sesión activa recibe `Me lo envías a Tilcara 2020` y posee un pedido borrador coincidente
- **THEN** guarda el texto normalizado en `direccion_entrega`
- **AND** no modifica productos, observaciones, pago, método, pendientes, confirmación ni cancelación

#### Scenario: Entrada inválida preserva la dirección anterior

- **WHEN** el texto queda vacío tras normalización o supera 500 code points
- **THEN** el intent es rechazado y conserva la dirección anterior
- **AND** no lo reinterpreta como observación ni otro intent

#### Scenario: Aislamiento sesión/comercio evita otro pedido

- **WHEN** la sesión está inactiva, no tiene pedido, el pedido falta, pertenece a otra sesión o no es borrador
- **THEN** rechaza sin mutar
- **AND** no busca, lee ni actualiza otro pedido

### Requirement: La ejecución tiene respuesta determinista y privada

El dispatcher inicial SHALL enviar `SET_DIRECCION_ENTREGA` al handler y el mapper SHALL renderizar respuesta fija en vez del fallback genérico. La respuesta y `resolved_data` de éxito SHALL NOT contener la dirección; sólo puede exponer `accepted_length`.

#### Scenario: Éxito no expone contenido de dirección

- **WHEN** la dirección se guarda correctamente
- **THEN** la respuesta confirma el guardado sin repetir dirección, ids ni detalle técnico

### Requirement: Se preservan transacciones y límites existentes

El handler SHALL NOT hacer commit, rollback, flush, refresh, begin ni close. Las excepciones técnicas SHALL llegar al dueño transaccional exterior. La capacidad SHALL NOT modificar calibración, reconocimiento, candidatos pendientes, método, pago, requisitos de confirmación o cancelación.

#### Scenario: Error posterior revierte el turno completo

- **WHEN** una parte posterior del mismo turno falla tras guardar la dirección
- **THEN** la transacción exterior revierte también la dirección
- **AND** el handler no confirma estado parcial
