# Calibrar la política de reconocimiento híbrido en Railway

## Objetivo

Ejecutar una calibración controlada, no destructiva y exclusivamente de
lectura desde Railway con el dataset congelado
`backend/data/product_recognition_calibration_cases.json`, usando el CLI
existente `backend.cli.calibrate_product_recognizer`. El resultado será un
reporte JSON revisable y, únicamente si su veredicto es elegible, una
propuesta verificable para conservarlo como artefacto de política persistente
que un futuro runtime de Railway pueda leer.

Este cambio no promueve `hybrid_authoritative`. La promoción requiere una
aprobación posterior e independiente.

## Ruta actual verificada

`PRODUCT_RECOGNIZER_MODE=shadow` conserva a `FuzzyProductRecognizer` como
única autoridad y observa embeddings/búsqueda vectorial. El CLI existente
valida el dataset, abre una sesión propia, ejecuta fuzzy, embedding y búsqueda
vectorial por caso, escribe atómicamente un reporte y cierra la sesión. El
loader de `hybrid_authoritative` ya falla cerrado: exige un archivo JSON
legible con `selected_policy` válido y `eligibility.status == "eligible"` en
`HYBRID_AUTHORITATIVE_POLICY_PATH`.

El despliegue actual no declara un volumen ni una ruta persistente de política.
Los reportes históricos en ubicaciones temporales no son un artefacto runtime
válido ni pueden reutilizarse como tal.

## Alcance

- Revisar y ejecutar una única calibración acotada contra Railway usando sólo
  el dataset versionado congelado y el CLI existente.
- Mantener `PRODUCT_RECOGNIZER_MODE=shadow` durante toda la calibración.
- Confirmar antes de ejecutar que las referencias/fingerprints del dataset
  corresponden al catálogo controlado disponible en el destino; ante ausencia
  o discrepancia, detenerse sin producir política.
- Evaluar la autoridad exclusiva de `report.eligibility.status` y registrar
  únicamente metadatos seguros del resultado.
- Definir y comprobar, sin asumir una ruta preexistente, un almacenamiento
  persistente montado en Railway para el reporte elegible. El operador deberá
  confirmar el mecanismo y la ruta real; la ruta se registrará sólo después de
  comprobar persistencia y legibilidad tras reinicio/redeploy.
- Definir los criterios de promoción y reversión para una fase posterior.

## No objetivos

- No cambiar reconocimiento, umbrales, dataset, modelos, embeddings, índice,
  timeouts, proxy, Tailscale, UFW, ACLs ni configuración de Ollama.
- No Twilio/WhatsApp E2E, tráfico real, datos de clientes, mensajes, pedidos,
  sesiones ni migraciones.
- No activar `hybrid_authoritative`, asignar `HYBRID_AUTHORITATIVE_POLICY_PATH`,
  desplegar, sincronizar, archivar, commitear ni modificar código o tests.
- No tratar `/tmp`, filesystem efímero de la imagen, ni un reporte archivado
  como almacenamiento persistente.

## Límite compartido, resultados y fallback

| Condición | Resultado autoritativo | Acción |
| --- | --- | --- |
| Dataset válido, catálogo controlado coincide y CLI termina | Se revisa el JSON emitido | Continuar sólo a evaluación de eligibility |
| `eligibility.status == "eligible"` | Candidato a artefacto, no activación | Verificar persistencia externa/montada y conservar copia segura |
| `eligibility.status != "eligible"` o falta | No hay política utilizable | Mantener `shadow`; no copiar a ruta runtime |
| Dataset/catálogo/fingerprint no coincide, o falla el CLI | Evidencia inválida/incompleta | Detenerse; no inventar una política |
| Artefacto no sobrevive o no es legible desde un montaje Railway verificado | Persistencia no resuelta | Mantener `shadow`; no fijar path ni promover |
| Cualquier fallo técnico de embedding/vector/DB | Fallo técnico, no resultado de negocio | Conservar sólo categoría segura y mantener fuzzy como autoridad |

Fuzzy es el fallback seguro y continúa como única autoridad. La sesión del
CLI es de sólo lectura: no se permite `commit`, `flush` mutante, `rollback`
operativo ni ninguna transacción de aplicación; el CLI no toma propiedad de
transacciones del runtime.

## Datos, observabilidad y seguridad

La única entrada de casos es el dataset congelado versionado. No se aceptan
logs, mensajes ni datos de clientes. El reporte de política puede conservar
campos que ya serializa de forma segura (versión/fingerprint del dataset,
conteos, política seleccionada, métricas agregadas, eligibility y razones),
pero no el archivo diagnóstico opcional si contiene evidencia por caso. Nunca
se registran `input_text`, vectores, prompts, URLs/credenciales, excepciones
crudas, datos de conexión ni textos de clientes.

La salida operativa permitida es: exit code, `cases`, `policies`,
`eligibility.status`, razones seguras, fingerprint/version del dataset,
métricas agregadas y prueba de existencia/lectura del artefacto persistente.

## Persistencia y reversibilidad

El diseño de persistencia queda deliberadamente condicionado: antes de escribir
un artefacto candidato, el operador identifica un almacenamiento persistente
de Railway montado para este servicio, su ruta real y sus permisos mínimos. Se
verifica que un archivo JSON de prueba sobreviva a la frontera acordada de
reinicio/redeploy y sea legible por el proceso runtime. Sólo entonces se podrá
copiar atómicamente el reporte elegible a esa ruta confirmada y conservar su
hash para revisión. No se usará una ruta propuesta como si ya existiera.

Una fase posterior podrá revertir una promoción dejando
`PRODUCT_RECOGNIZER_MODE=shadow` o `fuzzy` y retirando la referencia de
política; no deberá borrar el reporte de evidencia. La eliminación o sustitución
del artefacto persistente requiere aprobación explícita y un nuevo alcance.

## Criterios que bloquean promoción posterior

Todos deben cumplirse: reporte nuevo del dataset congelado con
`eligibility.status == "eligible"`; catálogo/fingerprints confirmados;
artefacto JSON íntegro y persistente accesible en Railway; configuración válida
probada en una verificación controlada; evidencia de fallback fuzzy ante fallo
técnico; y aprobación explícita. Cualquier ausencia, ineligibilidad, montaje
efímero, ruta no confirmada, error de carga o prueba no controlada bloquea la
promoción.

## Archivos esperados

- `openspec/changes/calibrate-railway-hybrid-recognition-policy/proposal.md`
- `openspec/changes/calibrate-railway-hybrid-recognition-policy/design.md`
- `openspec/changes/calibrate-railway-hybrid-recognition-policy/tasks.md`
- `openspec/changes/calibrate-railway-hybrid-recognition-policy/specs/railway-hybrid-recognition-calibration-policy/spec.md`

No se esperan archivos de aplicación, tests, configuración Railway ni cambios
en el OpenSpec activo de infraestructura.

## Validación propuesta

El usuario ejecutará localmente los comandos que requieran `venv` y aportará la
salida completa. La operación Railway sólo ocurrirá después de aprobar este
cambio. Los comandos previstos son:

```sh
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output "$CONFIRMED_PERSISTENT_POLICY_PATH"
openspec validate calibrate-railway-hybrid-recognition-policy --strict
git diff --check
```

El primer comando no se ejecutará hasta que `CONFIRMED_PERSISTENT_POLICY_PATH`
sea sustituido por la ruta Railway persistente ya verificada; no es una orden
ejecutable todavía. La revisión exige la salida completa y una inspección
segura del JSON para comprobar `eligibility.status`.

## Limitaciones diferidas

No se resuelve el aprovisionamiento de un volumen Railway, la activación del
modo autoritativo, el monitoreo prolongado de shadow ni la actualización del
dataset. Cada uno requiere un cambio y aprobación propios.
