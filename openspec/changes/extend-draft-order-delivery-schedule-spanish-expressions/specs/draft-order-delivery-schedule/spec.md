# Capability: draft-order-delivery-schedule

## MODIFIED Requirements

### Requirement: Exigir fecha y hora explícitas, no ambiguas y futuras

El sistema SHALL conservar la aceptación de `DD/MM/YYYY HH:MM` y `YYYY-MM-DD HH:MM` exactos. Además SHALL aceptar, dentro de un único fragmento temporal determinista, `hoy`, `mañana` o `el` opcional seguido de un día de semana, y luego `a las` con una hora concreta `H` o `H:MM`, con `horas` opcional y los calificadores `de la mañana`, `de la tarde` o `de la noche` cuando desambigüen una hora 1–12. Todo SHALL interpretarse en `America/Argentina/Buenos_Aires` contra un reloj testeable/injectable y deberá ser estrictamente futuro.

El sistema SHALL rechazar hora sin fecha con `needs_date`; SHALL rechazar un resultado pasado con `past_datetime` y SHALL NOT moverlo automáticamente al día siguiente. SHALL rechazar con `invalid_format` rangos, ventanas, recurrencias, duración relativa, expresiones vagas, AM/PM ambiguo, múltiples fragmentos temporales, offsets, zonas del mensaje y toda expresión no definida por este requisito. El rechazo SHALL preservar el valor previo.

#### Scenario: Hoy con hora concreta se persiste

- **WHEN** el cliente envía `Quiero que me lo envíes hoy a las 22 horas` y las 22:00 aún son futuras en Buenos Aires
- **THEN** persiste sólo el datetime timezone-aware de hoy a las 22:00
- **AND** `resolved_data` no contiene el datetime ni el texto de entrada

#### Scenario: Hora sin fecha pide aclaración

- **WHEN** el cliente envía `Quiero que me lo mandes a las 11 de la noche`
- **THEN** devuelve `rejected` con razón `needs_date` y una respuesta fija que pide fecha
- **AND** no asume hoy ni mañana, no crea contexto pendiente y no modifica el valor previo

#### Scenario: Hoy pasado no salta a mañana

- **WHEN** el cliente envía `hoy a las 22` después de las 22:00 en Buenos Aires
- **THEN** devuelve `rejected` con razón `past_datetime`
- **AND** conserva el valor anterior y pide un horario futuro sin convertirlo a mañana

#### Scenario: Expresión no contratada no altera programación

- **WHEN** el cliente envía `En dos horas`, `Entre 19 y 20`, `Tipo 8` o `Mañana temprano`
- **THEN** devuelve `rejected` con razón `invalid_format`
- **AND** no modifica el valor anterior ni reinterpreta el mensaje en otro handler

### Requirement: Respuesta privada y transacción exterior

El dispatcher y mapper existentes SHALL seguir usando el handler y builder del intent sin fallback genérico. Las respuestas de `needs_date`, `past_datetime` e `invalid_format` SHALL ser fijas y SHALL NOT exponer fecha/hora resuelta, texto, zona, ids o detalles técnicos. `resolved_data` SHALL contener sólo una razón estable en rechazo o una etiqueta segura de forma en éxito; SHALL NOT contener datetime completo. El handler SHALL NOT llamar `commit`, `rollback`, `flush`, `refresh`, `begin` ni `close`; las fallas técnicas SHALL propagarse al owner transaccional exterior.

#### Scenario: Ruta local y outbox conservan privacidad

- **WHEN** cualquiera de los outcomes temporales se renderiza localmente o para el outbox
- **THEN** ambas rutas generan el mismo mensaje fijo del builder
- **AND** ninguna incluye el texto recibido ni el datetime completo
