## 1. Aprobación

- [x] 1.1 Confirmar destino Railway dedicado/vacío y marcador no secreto.
- [x] 1.2 Aprobar inventario exacto sin alias ni sustituciones.
- [x] 1.3 Aprobar verify-only, apply explícito, transacción única y no borrado.

## 2. Implementación

- [x] 2.1 Implementar datos estáticos y auditoría de cobertura del manifiesto.
- [x] 2.2 Implementar servicio/CLI con guard y transacción única.
- [x] 2.3 Implementar verify, idempotencia, conflicto, redacción y rollback.
- [x] 2.4 Añadir tests de contrato, aislamiento y adaptador.

## 3. Validación y operación posterior

- [ ] 3.1 Usuario ejecuta pytest focal, Ruff y compileall con `venv` y aporta salida.
- [ ] 3.2 Ejecutar OpenSpec estricto y `git diff --check`.
- [ ] 3.3 Tras aprobación/deploy: verify-only, apply, verify y resolución del manifiesto.
- [ ] 3.4 No calibrar, hybrid, Twilio, deploy, sync, archive, commit o push sin autorización.
