## 1. Aprobación de diseño

- [x] 1.1 Aprobar el manifiesto lógico explícito como única traducción entre
  IDs históricos congelados y PKs del fixture Railway.
- [x] 1.2 Confirmar que el dataset fuente no se reescribe y que el manifiesto
  cubre todos los casos `commerce_dynamic_database`.
- [x] 1.3 Confirmar activación explícita de adaptación y rechazo de cualquier
  catálogo no identificado como fixture controlado.

## 2. Implementación

- [x] 2.1 Implementar el manifiesto y resolutor read-only sin control de
  transacciones.
- [x] 2.2 Materializar una copia en memoria preservando orden, límites y
  aislamiento; añadir fingerprint de ejecución separado.
- [x] 2.3 Integrar sólo por opción explícita del CLI, preservando el camino
  actual sin manifiesto.
- [x] 2.4 Declarar en el manifiesto todos los tokens dinámicos
  (`seed_refs`, `expected_producto_presentacion_id_ref`,
  `allowed_candidate_ids`, `restricted_candidate_ids`) con su identidad
  histórica exacta. Cada token declarado pero ausente del fixture
  controlado debe producir `MissingRuntimeIdentityError` antes de
  embedding, vector search o runner; los tokens del dataset ausentes
  del manifiesto deben producir `MissingManifestReferenceError`. No se
  permiten alias, aproximaciones, round-robin ni cruces de categoría.
- [x] 2.5 Añadir pruebas focalizadas que demuestren: cobertura completa
  del manifiesto, `MissingRuntimeIdentityError` cuando una identidad
  declarada no existe en el fixture, no instanciación de embedding
  client/vector factory/runner tras el error, ausencia de sustituciones
  semánticas, y CLI sin `--controlled-railway-manifest` conservando el
  flujo existente.

## 3. Validación y operación posterior

- [x] 3.1 El usuario ejecuta pytest focal, Ruff y compileall con `venv`, y
  aporta salida completa.
- [x] 3.2 Ejecutar validación OpenSpec estricta y `git diff --check`.
- [x] 3.3 Sólo con aprobación posterior: verify-only del fixture Railway y
  calibración read-only sin diagnóstico por caso.
- [ ] 3.4 No activar hybrid, no sembrar, deploy, sync, archive, commit ni push
  sin autoridad independiente.
