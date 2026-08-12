# Capability: draft-order-delivery-schedule

## ADDED Requirements

### Requirement: Programar sólo el borrador propio activo

Cuando el clasificador existente devuelve `set_fecha_hora_entrega` sin contexto pendiente, el sistema SHALL exigir sesión activa, cargar sólo `session.id_pedido`, verificar `Pedido.id_session == session.id` y `BORRADOR`, y reemplazar únicamente `Pedido.datetime_entrega_programada` dentro de la transacción exterior.

#### Scenario: Reemplazo exitoso

- **WHEN** la sesión activa tiene borrador propio y recibe `15/08/2026 19:30`
- **THEN** persiste el datetime timezone-aware en `America/Argentina/Buenos_Aires`
- **AND** no cambia productos, observaciones, dirección, pago, método, estado, sesión ni candidatos pendientes

#### Scenario: Pedido inválido no se modifica

- **WHEN** falta el pedido, pertenece a otra sesión o no está en `BORRADOR`
- **THEN** devuelve `rejected` con razón estable
- **AND** no busca ni modifica otro pedido

### Requirement: Exigir fecha y hora explícitas, no ambiguas y futuras

El sistema SHALL aceptar sólo `DD/MM/YYYY HH:MM` y `YYYY-MM-DD HH:MM`, interpretados en `America/Argentina/Buenos_Aires`. SHALL rechazar fecha sola, hora sola, texto relativo, offsets, texto adicional, formatos ambiguos o inválidos y valores pasados. El rechazo SHALL preservar el valor previo.

#### Scenario: Entrada incompleta no altera programación

- **WHEN** el cliente envía `mañana`, `15/08/2026` o `19:30`
- **THEN** devuelve `rejected` con `invalid_format`
- **AND** conserva el valor anterior

#### Scenario: Fecha pasada no altera programación

- **WHEN** una fecha con formato válido está en el pasado en la zona autoritativa
- **THEN** devuelve `rejected` con `past_datetime`
- **AND** conserva el valor anterior

### Requirement: Respuesta privada y transacción exterior

El dispatcher SHALL enviar el intent al handler y el mapper SHALL renderizar respuesta fija e igual en ruta local/outbox, sin fallback genérico. La respuesta SHALL NOT exponer fecha, texto, zona, ids ni detalle técnico. `resolved_data` SHALL contener sólo un indicador seguro del formato aceptado en éxito o una `reason` estable en rechazo; SHALL NOT contener el datetime completo. Las capas nuevas SHALL NOT llamar `commit`, `rollback`, `flush`, `refresh`, `begin` ni `close`; fallas técnicas SHALL propagarse al owner exterior.

#### Scenario: Falla posterior revierte el valor staged

- **WHEN** una operación posterior falla antes del commit exterior
- **THEN** el owner exterior revierte también la programación
- **AND** el handler no deja actualización parcial
