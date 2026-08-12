# Tasks

## 1. Specification and approval

- [x] 1.1 Inspeccionar en `origin/main` clasificación calibrada, modelo, Alembic head, dispatcher, cierre/observación, mapper, transacción y tests.
- [x] 1.2 Definir ownership, normalización, fallbacks, privacidad, migración, rollback, límites y validación focalizada.
- [x] 1.3 Obtener aprobación explícita antes de implementar.

## 2. Implementation (after approval)

- [x] 2.1 Agregar campo nullable y migración desde `b0c1d2e3f4a5`.
- [x] 2.2 Agregar handler sin ownership transaccional ni mutaciones ajenas.
- [x] 2.3 Agregar branches de dispatcher y mapper con respuesta privada.
- [x] 2.4 Agregar tests de persistencia, normalización, aislamiento, mapper y rollback.
- [x] 2.5 Revisar scope, migración, privacidad y contratos.

## 3. Validation and release

- [x] 3.1 Usuario ejecuta validaciones locales y entrega salida completa.
- [ ] 3.2 Tras autorización separada, deploy y verificación productiva E2E.
- [ ] 3.3 Obtener autorización separada antes de sync/archive.
