## Decisión

Separar identidad de evaluación de identidad física de base. Los números
actuales en `seed_refs` y listas de candidatos expresan el dataset histórico,
pero no son una autoridad portable para un fixture nuevo. El adaptador los
traduce mediante un manifiesto explícito de tokens lógicos; no infiere por
fuzzy, no busca por texto libre y no modifica el JSON fuente.

```text
dataset congelado + manifiesto lógico + catálogo fixture read-only
                         |
                         v
             dataset materializado en memoria (IDs runtime)
                         |
                         v
                 runner/CLI existentes -> reporte seguro
```

La cobertura insuficiente del fixture bloquea la materialización completa. Una
identidad histórica ausente debe producir un error tipado antes de consultar el
catálogo para resolverla y antes de embedding/vector/runner. Agregar esa
identidad al fixture requiere un cambio separado; este adaptador no puede
sustituir producto, categoría, presentación ni outcome para completar la
unicidad.


Cada token lógico declarará: fixture-commerce slug, category slug, product
slug/nombre canónico y presentation code. El manifiesto debe cubrir todos los
IDs usados por casos `commerce_dynamic_database`, incluyendo expected,
allowed, restricted y `seed_refs`. La relación es uno-a-uno.

La resolución hace una única consulta read-only por comercio fixture y forma
una tabla `token -> producto_presentacion.id`. Antes de materializar verifica:

1. el comercio fixture existe y está activo;
2. cada clave de negocio produce exactamente una asociación activa;
3. todo token requerido está cubierto y no hay alias silencioso;
4. cada candidato materializado pertenece al comercio del caso;
5. las listas resultantes conservan orden, unicidad, disjunción
   allowed/restricted y expectativas del dataset.

Sólo después reemplaza, en una copia profunda en memoria, IDs dinámicos y
`seed_refs` por sus PK runtime. El archivo fuente y su fingerprint fuente no
se escriben ni mutan. El dataset materializado obtiene un fingerprint de
ejecución separado, que se reporta junto con la versión/manifiesto para que no
se confunda con el dataset congelado.

## Selección explícita

La adaptación no se activa implícitamente por detectar Railway. El CLI deberá
recibir una selección explícita del manifiesto de fixture; sin ella conserva el
comportamiento actual. Esto evita que un catálogo de cliente o un entorno
desconocido sea reinterpretado como fixture controlado.

## Fallos

| Fallo | Comportamiento |
| --- | --- |
| Token no cubierto o clave sin fila | Error tipado antes de runner |
| Más de una fila para una clave | Error tipado antes de runner |
| PK materializada fuera del comercio | Error tipado antes de runner |
| Dataset fuente modificado | Error por fingerprint/versión esperada |
| Embedding/vector falla tras alineación | Semántica existente; fuzzy no pierde autoridad |

No se acepta como solución editar manualmente IDs, cambiar la secuencia de
PostgreSQL, insertar filas de relleno, usar datos de clientes, ni omitir casos.

## Tests y validación

Las pruebas deben cubrir mapeo completo, orden y límites preservados, comercio
cruzado, faltante, ambigüedad, inactividad, fuente inmutable, activación sólo
explícita, fallo antes de llamar embeddings y compatibilidad del CLI sin
manifiesto. Deben cubrir que ningún adaptador controla transacciones.

No se ejecuta Railway durante implementación. Después de aprobación y deploy,
la operación empieza con verify-only del fixture y una calibración controlada;
el reporte sigue siendo candidato hasta que `eligibility.status` sea elegible
y su artefacto persistente sea revisado.
