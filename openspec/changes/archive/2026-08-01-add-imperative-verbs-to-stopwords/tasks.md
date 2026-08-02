## 1. Extend STOPWORDS in product_recognizer

- [x] 1.1 Edit `backend/recognizers/product_recognizer.py` to add the imperative removal and action verbs to the `STOPWORDS` set: `quita`, `quitar`, `saca`, `sacame`, `sacala`, `quitala`, `quitalas`, `quitale`, `sacasela`, `elimina`, `eliminar`, `remueve`, `remover`, `borra`, `borrar`, `suprime`, `suprimir`, `agrega`, `agregar`.

## 2. Add regression tests

- [x] 2.1 Add a unit test (in `backend/tests/test_product_recognizer.py` if it exists, otherwise in `test_quitar_producto_recognizer.py`) that calls `detectar_productos("quita las empanadas de pollo", [...catalog with "Empanada de Pollo"...])` and asserts the product is in `encontrados` and the fragment is not in `no_encontrados`.
- [x] 2.2 Add a unit test for the pronominal conjugation `"sacala empanadas de pollo"` against the same empanada catalog.
- [x] 2.3 Add a unit test for a generic action verb `"elimina la pizza muzza"` against a pizza catalog.
- [x] 2.4 Add a unit test for `agregar_producto` without explicit quantity: `detectar_productos("agrega empanadas de pollo", [...catalog with "Empanada de Pollo"...])`.
- [x] 2.5 Add a unit test that asserts every verb listed in `["quita", "quitar", "saca", "sacame", "sacala", "quitala", "quitalas", "quitale", "sacasela", "elimina", "eliminar", "remueve", "remover", "borra", "borrar", "suprime", "suprimir", "agrega", "agregar"]` is a member of `STOPWORDS`.

## 3. Verify the end-to-end quitar_producto flow

- [x] 3.1 Run the existing `backend/tests/test_quitar_producto_*.py` suite to confirm no regressions. (46/49 unit tests pass; 1 pre-existing integration test failure in `test_quitar_producto_end_to_end.py::test_initial_pending_context_with_multiple_lines` reproduces with STOPWORDS reverted — DB-state / `uq_pedido_producto_presentacion` unique-constraint issue, unrelated to this change.)
- [x] 3.2 Run `backend/tests/test_agregar_producto_*.py` and `backend/tests/test_modificar_producto_*.py` to confirm no regressions. (`test_agregar_producto_*.py`: 12/12 pass. `test_modificar_producto_*.py`: 117/119 pass; 2 pre-existing failures in `test_modificar_producto_real_flow_cli.py::test_defect_1_cli_full_transfer_on_omitted_quantity` and `test_modificar_producto_real_flow_http.py::test_defect_1_full_transfer_on_omitted_quantity` reproduce with STOPWORDS reverted — modifier `cambia` is outside the new STOPWORDS scope and this asserts that `modificar_producto` should auto-remove the source line, which is unrelated to this change.)
- [x] 3.3 Run the full backend test suite and confirm no regressions. (528 tests in 56.76s; 2 failures + 1 error are all pre-existing (the same 3 from 3.1 + 3.2), confirmed by reverting the STOPWORDS change. No new regressions introduced by this change; the 5 new tests in `test_product_recognizer.py` all pass.)