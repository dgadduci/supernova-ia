import time
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.dependencies import get_session
from backend.main import app
from backend.models import (
    CategoriaProducto,
    Cliente,
    Comercio,
    EstadoComercio,
    MediosPago,
    MetodosEntrega,
    Pedido,
    PedidoProducto,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.services.categoria_producto_service import CategoriaProductoService
from backend.services.metodo_entrega_service import MetodoEntregaService
from backend.services.precio_service import PrecioService
from backend.services.presentacion_service import PresentacionService
from backend.services.producto_service import ProductoService

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_session() -> Session:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_session] = _override_session

client = TestClient(app)


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(text("SELECT id FROM estado_comercio WHERE estado = 'ACTIVO'")).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _payload(**overrides) -> dict:
    s = _suffix()
    base = {
        "nombre_fantasia": f"Test Comercio {s}",
        "nombre_corto": f"TC {s}",
        "razon_social": f"Test Comercio SRL {s}",
        "cuit": f"30-{s[:8]}-{s[8]}",
        "whatsapp": f"+54911{s[:8]}",
        "calle": "Av. Test",
        "numero": "1234",
        "piso_departamento": None,
        "localidad": "CABA",
        "provincia": "Buenos Aires",
        "codigo_postal": "C1000",
        "slug": f"test-comercio-{s}",
        "estado_id": _estado_id_activo(),
    }
    base.update(overrides)
    return base


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _existing_comercio_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM comercios ORDER BY id"))]


results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}".rstrip())


def test_health() -> None:
    r = client.get("/health")
    ok = r.status_code == 200 and r.json() == {"status": "ok"}
    record("health", ok, f"{r.status_code} {r.text[:80]}")


def test_create_and_get() -> None:
    payload = _payload()
    r = client.post("/comercios", json=payload)
    if r.status_code != 201:
        record("create_comercio", False, f"{r.status_code} {r.text}")
        return
    created = r.json()
    new_id = created["id"]
    try:
        record("create_comercio", True, f"id={new_id}")

        r2 = client.get(f"/comercios/{new_id}")
        ok = r2.status_code == 200 and r2.json()["id"] == new_id
        record("get_comercio", ok, f"{r2.status_code} id={new_id}")

        r3 = client.get("/comercios")
        if r3.status_code != 200:
            record("list_comercios", False, f"{r3.status_code}")
        else:
            data = r3.json()
            ids = [c["id"] for c in data]
            ordered = ids == sorted(ids)
            contains = new_id in ids
            record("list_comercios", ordered and contains, f"len={len(ids)} ordered={ordered} contains_new={contains}")
    finally:
        _delete_comercio(new_id)


def test_get_missing_404() -> None:
    max_id = max(_existing_comercio_ids() or [0])
    r = client.get(f"/comercios/{max_id + 99999}")
    record("get_missing_404", r.status_code == 404, f"{r.status_code}")


def test_create_missing_estado_404() -> None:
    max_id = max(_existing_comercio_ids() or [0])
    payload = _payload(estado_id=max_id + 99999)
    r = client.post("/comercios", json=payload)
    record("create_missing_estado_404", r.status_code == 404, f"{r.status_code}")


def test_create_duplicate_whatsapp_409() -> None:
    payload = _payload()
    r1 = client.post("/comercios", json=payload)
    if r1.status_code != 201:
        record("create_duplicate_whatsapp_409", False, f"setup failed: {r1.status_code} {r1.text}")
        return
    new_id = r1.json()["id"]
    try:
        payload2 = _payload(slug=f"another-slug-{_suffix()}", cuit=f"30-{_suffix()[:8]}-{_suffix()[8]}")
        payload2["whatsapp"] = payload["whatsapp"]
        r2 = client.post("/comercios", json=payload2)
        record("create_duplicate_whatsapp_409", r2.status_code == 409, f"{r2.status_code}")
    finally:
        _delete_comercio(new_id)


def test_create_duplicate_slug_409() -> None:
    payload = _payload()
    r1 = client.post("/comercios", json=payload)
    if r1.status_code != 201:
        record("create_duplicate_slug_409", False, f"setup failed: {r1.status_code} {r1.text}")
        return
    new_id = r1.json()["id"]
    try:
        payload2 = _payload(
            slug=payload["slug"],
            cuit=f"30-{_suffix()[:8]}-{_suffix()[8]}",
            whatsapp=f"+54911{_suffix()[:8]}",
        )
        r2 = client.post("/comercios", json=payload2)
        record("create_duplicate_slug_409", r2.status_code == 409, f"{r2.status_code}")
    finally:
        _delete_comercio(new_id)


def _estado_payload(estado: str | None = None) -> dict:
    return {"estado": estado if estado is not None else f"TEST_{_suffix()}"}


def _existing_estado_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM estado_comercio ORDER BY id"))]


def _delete_estado(estado_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(EstadoComercio).where(EstadoComercio.id == estado_id))


def test_list_estados_comercio() -> None:
    r = client.get("/estados-comercio")
    if r.status_code != 200:
        record("list_estados_comercio", False, f"{r.status_code}")
        return
    data = r.json()
    ids = [e["id"] for e in data]
    record("list_estados_comercio", ids == sorted(ids), f"len={len(ids)} ordered={ids == sorted(ids)}")


def test_get_estado_comercio_missing_404() -> None:
    max_id = max(_existing_estado_ids() or [0])
    r = client.get(f"/estados-comercio/{max_id + 99999}")
    record("get_estado_comercio_missing_404", r.status_code == 404, f"{r.status_code}")


def test_create_estado_comercio_201() -> None:
    payload = _estado_payload()
    r = client.post("/estados-comercio", json=payload)
    if r.status_code != 201:
        record("create_estado_comercio_201", False, f"{r.status_code} {r.text}")
        return
    new_id = r.json()["id"]
    try:
        body = r.json()
        ok = body["estado"] == payload["estado"] and body["id"] == new_id
        record("create_estado_comercio_201", ok, f"id={new_id} estado={body['estado']!r}")
    finally:
        _delete_estado(new_id)


def test_create_estado_comercio_duplicate_409() -> None:
    payload = _estado_payload()
    r1 = client.post("/estados-comercio", json=payload)
    if r1.status_code != 201:
        record("create_estado_comercio_duplicate_409", False, f"setup failed: {r1.status_code} {r1.text}")
        return
    new_id = r1.json()["id"]
    try:
        r2 = client.post("/estados-comercio", json=payload)
        record("create_estado_comercio_duplicate_409", r2.status_code == 409, f"{r2.status_code}")
    finally:
        _delete_estado(new_id)


def test_create_estado_comercio_trims_whitespace() -> None:
    suffix = _suffix()
    payload = {"estado": f"  TEST_{suffix}  "}
    r = client.post("/estados-comercio", json=payload)
    if r.status_code != 201:
        record("create_estado_comercio_trims_whitespace", False, f"{r.status_code} {r.text}")
        return
    new_id = r.json()["id"]
    try:
        persisted = r.json()["estado"]
        record(
            "create_estado_comercio_trims_whitespace",
            persisted == f"TEST_{suffix}",
            f"persisted={persisted!r}",
        )
    finally:
        _delete_estado(new_id)


def test_create_estado_comercio_empty_400() -> None:
    payload = {"estado": "   "}
    r = client.post("/estados-comercio", json=payload)
    record("create_estado_comercio_empty_400", r.status_code == 400, f"{r.status_code}")


def test_create_estado_comercio_rejects_id_422() -> None:
    payload = {"id": 999999, "estado": f"TEST_{_suffix()}"}
    r = client.post("/estados-comercio", json=payload)
    record("create_estado_comercio_rejects_id_422", r.status_code == 422, f"{r.status_code}")


def _existing_medio_pago_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM medios_pago ORDER BY id"))]


def _delete_medio_pago(medio_pago_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(MediosPago).where(MediosPago.id == medio_pago_id))


def _medio_pago_payload(codigo: str | None = None, descripcion: str | None = None) -> dict:
    suffix = _suffix()
    return {
        "codigo": codigo if codigo is not None else f"TEST_{suffix}",
        "descripcion": descripcion if descripcion is not None else f"Test medio {suffix}",
    }


def test_list_medios_pago() -> None:
    r = client.get("/medios-pago")
    if r.status_code != 200:
        record("list_medios_pago", False, f"{r.status_code}")
        return
    data = r.json()
    ids = [m["id"] for m in data]
    record("list_medios_pago", ids == sorted(ids), f"len={len(ids)} ordered={ids == sorted(ids)}")


def test_get_medio_pago_missing_404() -> None:
    max_id = max(_existing_medio_pago_ids() or [0])
    r = client.get(f"/medios-pago/{max_id + 99999}")
    record("get_medio_pago_missing_404", r.status_code == 404, f"{r.status_code}")


def test_create_medio_pago_201() -> None:
    payload = _medio_pago_payload()
    r = client.post("/medios-pago", json=payload)
    if r.status_code != 201:
        record("create_medio_pago_201", False, f"{r.status_code} {r.text}")
        return
    new_id = r.json()["id"]
    try:
        body = r.json()
        ok = body["codigo"] == payload["codigo"] and body["activo"] is True and body["id"] == new_id
        record("create_medio_pago_201", ok, f"id={new_id} activo={body['activo']}")
    finally:
        _delete_medio_pago(new_id)


def test_create_medio_pago_duplicate_409() -> None:
    payload = _medio_pago_payload()
    r1 = client.post("/medios-pago", json=payload)
    if r1.status_code != 201:
        record("create_medio_pago_duplicate_409", False, f"setup failed: {r1.status_code} {r1.text}")
        return
    new_id = r1.json()["id"]
    try:
        r2 = client.post("/medios-pago", json=payload)
        record("create_medio_pago_duplicate_409", r2.status_code == 409, f"{r2.status_code}")
    finally:
        _delete_medio_pago(new_id)


def test_create_medio_pago_trims_whitespace() -> None:
    suffix = _suffix()
    payload = {
        "codigo": f"  TEST_{suffix}  ",
        "descripcion": f"  Test medio {suffix}  ",
    }
    r = client.post("/medios-pago", json=payload)
    if r.status_code != 201:
        record("create_medio_pago_trims_whitespace", False, f"{r.status_code} {r.text}")
        return
    new_id = r.json()["id"]
    try:
        body = r.json()
        ok = body["codigo"] == f"TEST_{suffix}" and body["descripcion"] == f"Test medio {suffix}"
        record("create_medio_pago_trims_whitespace", ok, f"codigo={body['codigo']!r} descripcion={body['descripcion']!r}")
    finally:
        _delete_medio_pago(new_id)


def test_create_medio_pago_empty_codigo_400() -> None:
    payload = {"codigo": "   ", "descripcion": "x"}
    r = client.post("/medios-pago", json=payload)
    record("create_medio_pago_empty_codigo_400", r.status_code == 400, f"{r.status_code}")


def test_create_medio_pago_empty_descripcion_400() -> None:
    payload = {"codigo": "X", "descripcion": "   "}
    r = client.post("/medios-pago", json=payload)
    record("create_medio_pago_empty_descripcion_400", r.status_code == 400, f"{r.status_code}")


def test_create_medio_pago_rejects_id_422() -> None:
    payload = {"id": 999999, **_medio_pago_payload()}
    r = client.post("/medios-pago", json=payload)
    record("create_medio_pago_rejects_id_422", r.status_code == 422, f"{r.status_code}")


def test_create_medio_pago_activo_defaults_true() -> None:
    payload = _medio_pago_payload()
    assert "activo" not in payload, "test setup: payload must omit activo"
    r = client.post("/medios-pago", json=payload)
    if r.status_code != 201:
        record("create_medio_pago_activo_defaults_true", False, f"{r.status_code} {r.text}")
        return
    new_id = r.json()["id"]
    try:
        body = r.json()
        record("create_medio_pago_activo_defaults_true", body["activo"] is True, f"activo={body['activo']}")
    finally:
        _delete_medio_pago(new_id)


def _existing_metodo_entrega_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM metodos_entrega ORDER BY id"))]


def _delete_metodo_entrega(metodo_entrega_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(MetodosEntrega).where(MetodosEntrega.id == metodo_entrega_id))


def _metodo_entrega_payload(**overrides) -> dict:
    suffix = _suffix()
    payload = {
        "codigo": f"TEST_{suffix}",
        "descripcion": f"Test metodo {suffix}",
        "orden": 10,
    }
    payload.update(overrides)
    return payload


def test_list_and_get_metodos_entrega() -> None:
    r = client.get("/metodos-entrega")
    if r.status_code != 200:
        record("list_metodos_entrega", False, f"{r.status_code}")
        return
    ids = [m["id"] for m in r.json()]
    record("list_metodos_entrega", ids == sorted(ids), f"len={len(ids)} ordered={ids == sorted(ids)}")
    if ids:
        r2 = client.get(f"/metodos-entrega/{ids[0]}")
        record("get_metodo_entrega", r2.status_code == 200 and r2.json()["id"] == ids[0], f"{r2.status_code}")


def test_get_metodo_entrega_missing_404() -> None:
    max_id = max(_existing_metodo_entrega_ids() or [0])
    r = client.get(f"/metodos-entrega/{max_id + 99999}")
    record("get_metodo_entrega_missing_404", r.status_code == 404, f"{r.status_code}")


def test_create_metodo_entrega_201_and_activo() -> None:
    for activo in (None, False):
        payload = _metodo_entrega_payload()
        if activo is not None:
            payload["activo"] = activo
        r = client.post("/metodos-entrega", json=payload)
        if r.status_code != 201:
            record("create_metodo_entrega_201_and_activo", False, f"{r.status_code} {r.text}")
            return
        new_id = r.json()["id"]
        try:
            expected_activo = True if activo is None else activo
            body = r.json()
            ok = body["activo"] is expected_activo and body["orden"] == payload["orden"]
            record(f"create_metodo_entrega_activo_{expected_activo}", ok, f"id={new_id}")
        finally:
            _delete_metodo_entrega(new_id)


def test_create_metodo_entrega_trims_and_rejects_duplicate() -> None:
    suffix = _suffix()
    payload = _metodo_entrega_payload(
        codigo=f"  TEST_{suffix}  ",
        descripcion=f"  Test metodo {suffix}  ",
    )
    r1 = client.post("/metodos-entrega", json=payload)
    if r1.status_code != 201:
        record("create_metodo_entrega_trims", False, f"{r1.status_code} {r1.text}")
        return
    new_id = r1.json()["id"]
    try:
        body = r1.json()
        trimmed = body["codigo"] == f"TEST_{suffix}" and body["descripcion"] == f"Test metodo {suffix}"
        record("create_metodo_entrega_trims", trimmed, f"codigo={body['codigo']!r}")
        duplicate_payload = _metodo_entrega_payload(codigo=f"TEST_{suffix}")
        r2 = client.post("/metodos-entrega", json=duplicate_payload)
        record("create_metodo_entrega_duplicate_409", r2.status_code == 409, f"{r2.status_code}")
    finally:
        _delete_metodo_entrega(new_id)


def test_create_metodo_entrega_validation() -> None:
    cases = [
        ("empty_codigo_400", _metodo_entrega_payload(codigo="   "), 400),
        ("empty_descripcion_400", _metodo_entrega_payload(descripcion="   "), 400),
        ("negative_orden_422", _metodo_entrega_payload(orden=-1), 422),
        ("rejects_id_422", {"id": 999999, **_metodo_entrega_payload()}, 422),
        ("rejects_fecha_alta_422", {"fecha_alta": "2026-01-01T00:00:00Z", **_metodo_entrega_payload()}, 422),
        ("rejects_extra_422", {"extra": True, **_metodo_entrega_payload()}, 422),
    ]
    for name, payload, expected in cases:
        r = client.post("/metodos-entrega", json=payload)
        record(f"create_metodo_entrega_{name}", r.status_code == expected, f"{r.status_code}")


def test_metodo_entrega_service_rolls_back_on_create_failure() -> None:
    session = TestingSessionLocal()
    service = MetodoEntregaService(session)

    def fail_create(*args, **kwargs):
        raise RuntimeError("forced create failure")

    try:
        with patch.object(service._repo, "create", side_effect=fail_create):
            try:
                service.create(f"TEST_{_suffix()}", "Test rollback", 1, True)
            except RuntimeError:
                record("metodo_entrega_create_failure_rolls_back", not session.in_transaction())
            else:
                record("metodo_entrega_create_failure_rolls_back", False, "failure was not raised")
    finally:
        session.close()


def _delete_categoria_producto(categoria_producto_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(CategoriaProducto).where(CategoriaProducto.id == categoria_producto_id))


def _categoria_producto_payload(**overrides) -> dict:
    payload = {"descripcion": f"Test categoria {_suffix()}"}
    payload.update(overrides)
    return payload


def test_categoria_producto_create_get_and_list() -> None:
    comercio_ids = _existing_comercio_ids()
    if len(comercio_ids) < 2:
        record("categoria_producto_setup", False, "requires two seeded comercios")
        return
    comercio_id, other_comercio_id = comercio_ids[:2]
    created_ids: list[int] = []
    try:
        first = client.post(
            f"/comercios/{comercio_id}/categorias-productos",
            json=_categoria_producto_payload(),
        )
        second = client.post(
            f"/comercios/{comercio_id}/categorias-productos",
            json=_categoria_producto_payload(orden=10, activo=False),
        )
        other = client.post(
            f"/comercios/{other_comercio_id}/categorias-productos",
            json=_categoria_producto_payload(orden=0),
        )
        responses = [first, second, other]
        if not all(response.status_code == 201 for response in responses):
            record("create_categoria_producto", False, str([r.status_code for r in responses]))
            return
        created_ids = [response.json()["id"] for response in responses]
        first_body = first.json()
        defaults_ok = first_body["activo"] is True and first_body["orden"] == 0
        record("create_categoria_producto", first_body["id_comercio"] == comercio_id, f"id={created_ids[0]}")
        record("categoria_producto_explicit_values", second.json()["activo"] is False, "activo=false")
        get_response = client.get(f"/categorias-productos/{created_ids[0]}")
        record("get_categoria_producto", get_response.status_code == 200, f"{get_response.status_code}")
        listed = client.get(f"/comercios/{comercio_id}/categorias-productos")
        listed_ids = [category["id"] for category in listed.json()]
        listed_categories = listed.json()
        ordered = [(c["orden"], c["id"]) for c in listed_categories] == sorted(
            (c["orden"], c["id"]) for c in listed_categories
        )
        isolated = all(category["id_comercio"] == comercio_id for category in listed_categories)
        record("list_categorias_productos", listed.status_code == 200 and ordered and isolated, f"{listed.status_code}")
        record("categoria_producto_defaults", defaults_ok, f"activo={first_body['activo']} orden={first_body['orden']}")
        record("categoria_producto_list_contains_created", created_ids[0] in listed_ids and created_ids[1] in listed_ids, f"ids={listed_ids}")
    finally:
        for category_id in created_ids:
            _delete_categoria_producto(category_id)


def test_categoria_producto_missing_and_validation() -> None:
    comercio_id = max(_existing_comercio_ids() or [0])
    missing_comercio = client.get(f"/comercios/{comercio_id + 99999}/categorias-productos")
    record("list_categoria_producto_missing_comercio_404", missing_comercio.status_code == 404, f"{missing_comercio.status_code}")
    missing_category = client.get("/categorias-productos/999999")
    record("get_categoria_producto_missing_404", missing_category.status_code == 404, f"{missing_category.status_code}")
    cases = [
        ("empty_description_400", _categoria_producto_payload(descripcion="   "), 400),
        ("negative_orden_422", _categoria_producto_payload(orden=-1), 422),
        ("rejects_id_comercio_422", {"id_comercio": comercio_id, **_categoria_producto_payload()}, 422),
        ("rejects_id_422", {"id": 999999, **_categoria_producto_payload()}, 422),
    ]
    for name, payload, expected in cases:
        response = client.post(f"/comercios/{comercio_id}/categorias-productos", json=payload)
        record(f"categoria_producto_{name}", response.status_code == expected, f"{response.status_code}")


def test_categoria_producto_service_rolls_back_on_create_failure() -> None:
    session = TestingSessionLocal()
    service = CategoriaProductoService(session)

    def fail_create(*args, **kwargs):
        raise RuntimeError("forced create failure")

    comercio_id = max(_existing_comercio_ids() or [0])
    try:
        with patch.object(service._repo, "create", side_effect=fail_create):
            try:
                service.create(comercio_id, "Test rollback", None, None)
            except RuntimeError:
                # Subphase 4.8: catalog services MUST NOT call
                # session.rollback / session.commit / session.close /
                # session.begin. The router owns the transaction
                # boundary. The session therefore remains in its
                # original transaction state.
                record(
                    "categoria_producto_create_failure_rolls_back",
                    session.in_transaction(),
                )
            else:
                record("categoria_producto_create_failure_rolls_back", False, "failure was not raised")
    finally:
        session.close()


def test_presentacion_service_rolls_back_on_create_failure() -> None:
    session = TestingSessionLocal()
    service = PresentacionService(session)

    def fail_create(*args, **kwargs):
        raise RuntimeError("forced create failure")

    comercio_id = max(_existing_comercio_ids() or [0])
    try:
        with patch.object(service._repo, "create", side_effect=fail_create):
            try:
                service.create(comercio_id, "rollback", "Rollback", None, None)
            except RuntimeError:
                # Subphase 4.8: catalog services MUST NOT call
                # session.rollback / session.commit / session.close /
                # session.begin. The router owns the transaction
                # boundary. The session therefore remains in its
                # original transaction state.
                record(
                    "presentacion_create_failure_rolls_back",
                    session.in_transaction(),
                )
            else:
                record("presentacion_create_failure_rolls_back", False, "failure was not raised")
    finally:
        session.close()


def _delete_presentacion(presentacion_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(Presentacion).where(Presentacion.id == presentacion_id))


def _presentacion_payload(**overrides) -> dict:
    suffix = _suffix()
    payload = {"codigo": f"TEST_{suffix}", "descripcion": f"Test presentacion {suffix}"}
    payload.update(overrides)
    return payload


def test_presentacion_create_get_list_and_scoped_duplicates() -> None:
    comercio_ids = _existing_comercio_ids()
    if len(comercio_ids) < 2:
        record("presentacion_setup", False, "requires two seeded comercios")
        return
    comercio_id, other_comercio_id = comercio_ids[:2]
    suffix = _suffix()
    payload = {"codigo": f"  TEST_{suffix}  ", "descripcion": f"  Test presentacion {suffix}  "}
    created_ids: list[int] = []
    try:
        first = client.post(f"/comercios/{comercio_id}/presentaciones", json=payload)
        other = client.post(
            f"/comercios/{other_comercio_id}/presentaciones",
            json={"codigo": f"TEST_{suffix}", "descripcion": f"Test presentacion {suffix}"},
        )
        if first.status_code != 201 or other.status_code != 201:
            record("create_presentacion", False, f"{first.status_code}/{other.status_code}")
            return
        created_ids = [first.json()["id"], other.json()["id"]]
        body = first.json()
        record("create_presentacion", body["codigo"] == f"test_{suffix}" and body["descripcion"] == f"Test presentacion {suffix}", f"id={created_ids[0]}")
        record("presentacion_defaults", body["activo"] is True and body["orden"] == 0, "defaults")
        get_response = client.get(f"/presentaciones/{created_ids[0]}")
        record("get_presentacion", get_response.status_code == 200, f"{get_response.status_code}")
        listed = client.get(f"/comercios/{comercio_id}/presentaciones")
        categories = listed.json()
        ordered = [(p["orden"], p["id"]) for p in categories] == sorted((p["orden"], p["id"]) for p in categories)
        isolated = all(p["id_comercio"] == comercio_id for p in categories)
        record("list_presentaciones", listed.status_code == 200 and ordered and isolated, f"{listed.status_code}")
        duplicate_code = client.post(f"/comercios/{comercio_id}/presentaciones", json=_presentacion_payload(codigo=f"TEST_{suffix}"))
        duplicate_description = client.post(f"/comercios/{comercio_id}/presentaciones", json=_presentacion_payload(descripcion=f"TEST PRESENTACION {suffix}"))
        record("presentacion_duplicate_code_409", duplicate_code.status_code == 409, f"{duplicate_code.status_code}")
        record("presentacion_duplicate_description_409", duplicate_description.status_code == 409, f"{duplicate_description.status_code}")
    finally:
        for presentacion_id in created_ids:
            _delete_presentacion(presentacion_id)


def test_presentacion_missing_and_validation() -> None:
    comercio_id = max(_existing_comercio_ids() or [0])
    missing_comercio = client.get(f"/comercios/{comercio_id + 99999}/presentaciones")
    missing_presentation = client.get("/presentaciones/999999")
    record("list_presentacion_missing_comercio_404", missing_comercio.status_code == 404, f"{missing_comercio.status_code}")
    record("get_presentacion_missing_404", missing_presentation.status_code == 404, f"{missing_presentation.status_code}")
    cases = [
        ("empty_codigo_400", _presentacion_payload(codigo="   "), 400),
        ("empty_descripcion_400", _presentacion_payload(descripcion="   "), 400),
        ("negative_orden_422", _presentacion_payload(orden=-1), 422),
        ("rejects_id_comercio_422", {"id_comercio": comercio_id, **_presentacion_payload()}, 422),
        ("rejects_id_422", {"id": 999999, **_presentacion_payload()}, 422),
    ]
    for name, payload, expected in cases:
        response = client.post(f"/comercios/{comercio_id}/presentaciones", json=payload)
        record(f"presentacion_{name}", response.status_code == expected, f"{response.status_code}")


def _category_ids_by_comercio(comercio_id: int) -> list[int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id FROM categorias_productos WHERE id_comercio = :id ORDER BY orden, id"),
            {"id": comercio_id},
        )
        return [row[0] for row in rows]


def _delete_producto(producto_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Producto).where(Producto.id == producto_id))


def _producto_payload(**overrides) -> dict:
    payload = {"nombre": f"Test producto {_suffix()}"}
    payload.update(overrides)
    return payload


def test_producto_create_get_category_and_commerce_lists() -> None:
    comercio_ids = _existing_comercio_ids()
    if not comercio_ids:
        record("producto_setup", False, "requires seeded comercio")
        return
    comercio_id = comercio_ids[0]
    category_ids = _category_ids_by_comercio(comercio_id)
    if len(category_ids) < 2:
        record("producto_setup", False, "requires two categories in one comercio")
        return
    first_category, second_category = category_ids[:2]
    shared_name = f"Shared producto {_suffix()}"
    created_ids: list[int] = []
    try:
        first = client.post(
            f"/categorias-productos/{first_category}/productos",
            json={"nombre": f"  {shared_name}  ", "descripcion": "  Detailed product  "},
        )
        second = client.post(
            f"/categorias-productos/{second_category}/productos",
            json={"nombre": shared_name, "descripcion": "   ", "orden": 7, "activo": False, "disponible": False},
        )
        if first.status_code != 201 or second.status_code != 201:
            record("create_producto", False, f"{first.status_code}/{second.status_code}")
            return
        created_ids = [first.json()["id"], second.json()["id"]]
        first_body = first.json()
        second_body = second.json()
        record("create_producto", first_body["nombre"] == shared_name and first_body["descripcion"] == "Detailed product", f"id={created_ids[0]}")
        record("producto_defaults", first_body["activo"] is True and first_body["disponible"] is True and first_body["orden"] == 0, "defaults")
        record("producto_empty_description_null", second_body["descripcion"] is None, "description=null")
        get_response = client.get(f"/productos/{created_ids[0]}")
        record("get_producto", get_response.status_code == 200, f"{get_response.status_code}")
        category_response = client.get(f"/categorias-productos/{first_category}/productos")
        category_products = category_response.json()
        category_ordered = [(p["orden"], p["id"]) for p in category_products] == sorted((p["orden"], p["id"]) for p in category_products)
        category_scoped = all(p["id_categoria_producto"] == first_category for p in category_products)
        record("list_productos_by_categoria", category_response.status_code == 200 and category_ordered and category_scoped, f"{category_response.status_code}")
        commerce_response = client.get(f"/comercios/{comercio_id}/productos")
        commerce_products = commerce_response.json()
        category_order = {category_id: position for position, category_id in enumerate(category_ids)}
        commerce_keys = [(category_order[p["id_categoria_producto"]], p["orden"], p["id"]) for p in commerce_products]
        commerce_scoped = all(p["id_categoria_producto"] in category_order for p in commerce_products)
        record("list_productos_by_comercio", commerce_response.status_code == 200 and commerce_scoped and commerce_keys == sorted(commerce_keys), f"{commerce_response.status_code}")
        duplicate = client.post(
            f"/categorias-productos/{first_category}/productos",
            json=_producto_payload(nombre=shared_name.upper()),
        )
        record("producto_duplicate_name_409", duplicate.status_code == 409, f"{duplicate.status_code}")
    finally:
        for producto_id in created_ids:
            _delete_producto(producto_id)


def test_producto_missing_validation_and_empty_commerce() -> None:
    comercio_ids = _existing_comercio_ids()
    comercio_id = max(comercio_ids or [0])
    category_ids = _category_ids_by_comercio(comercio_ids[0]) if comercio_ids else []
    category_id = category_ids[0] if category_ids else 0
    missing_category_id = 999999
    checks = [
        ("missing_category_list_404", client.get(f"/categorias-productos/{missing_category_id}/productos"), 404),
        ("missing_product_404", client.get("/productos/999999"), 404),
        ("missing_commerce_404", client.get(f"/comercios/{comercio_id + 99999}/productos"), 404),
        ("empty_name_400", client.post(f"/categorias-productos/{category_id}/productos", json=_producto_payload(nombre="   ")), 400),
        ("negative_order_422", client.post(f"/categorias-productos/{category_id}/productos", json=_producto_payload(orden=-1)), 422),
        ("rejects_category_body_422", client.post(f"/categorias-productos/{category_id}/productos", json={"id_categoria_producto": category_id, **_producto_payload()}), 422),
    ]
    for name, response, expected in checks:
        record(f"producto_{name}", response.status_code == expected, f"{response.status_code}")
    payload = _payload()
    created_commerce = client.post("/comercios", json=payload)
    if created_commerce.status_code != 201:
        record("producto_empty_commerce_list", False, f"setup={created_commerce.status_code}")
        return
    new_commerce_id = created_commerce.json()["id"]
    try:
        response = client.get(f"/comercios/{new_commerce_id}/productos")
        record("producto_empty_commerce_list", response.status_code == 200 and response.json() == [], f"{response.status_code}")
    finally:
        _delete_comercio(new_commerce_id)


def test_producto_service_rolls_back_on_create_failure() -> None:
    session = TestingSessionLocal()
    service = ProductoService(session)
    comercio_ids = _existing_comercio_ids()
    category_ids = _category_ids_by_comercio(comercio_ids[0]) if comercio_ids else []
    category_id = category_ids[0] if category_ids else 0

    def fail_create(*args, **kwargs):
        raise RuntimeError("forced create failure")

    try:
        with patch.object(service._repo, "create", side_effect=fail_create):
            try:
                service.create(category_id, f"Rollback {_suffix()}", None, None, None, None)
            except RuntimeError:
                # Subphase 4.8: catalog services MUST NOT call
                # session.rollback / session.commit / session.close /
                # session.begin. The router owns the transaction
                # boundary. The session therefore remains in its
                # original transaction state.
                record(
                    "producto_create_failure_rolls_back",
                    session.in_transaction(),
                )
            else:
                record("producto_create_failure_rolls_back", False, "failure was not raised")
    finally:
        session.close()


def _unpriced_producto_presentacion_id() -> tuple[int, bool]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pp.id FROM producto_presentaciones pp "
                "LEFT JOIN producto_precios p ON p.id_producto_presentacion = pp.id "
                "WHERE p.id IS NULL ORDER BY pp.id LIMIT 1"
            )
        ).first()
        if row is not None:
            return row[0], False
        candidate = connection.execute(
            text(
                "SELECT p.id, pr.id FROM productos p "
                "JOIN categorias_productos c ON c.id = p.id_categoria_producto "
                "JOIN presentaciones pr ON pr.id_comercio = c.id_comercio "
                "LEFT JOIN producto_presentaciones pp "
                "ON pp.id_producto = p.id AND pp.id_presentacion = pr.id "
                "WHERE pp.id IS NULL ORDER BY p.id, pr.id LIMIT 1"
            )
        ).first()
    if candidate is None:
        raise RuntimeError("no available producto-presentacion fixture")
    with TestingSessionLocal() as session, session.begin():
        association = ProductoPresentacion(
            id_producto=candidate[0],
            id_presentacion=candidate[1],
            activo=True,
            orden=0,
        )
        session.add(association)
        session.flush()
        association_id = association.id
    return association_id, True


def _delete_producto_presentacion(producto_presentacion_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id == producto_presentacion_id
            )
        )


def _delete_precio(precio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Precio).where(Precio.id == precio_id))


def test_precio_create_and_retrieve_exact_decimal() -> None:
    producto_presentacion_id, created_association = _unpriced_producto_presentacion_id()
    before_count = None
    with engine.connect() as connection:
        before_count = connection.execute(text("SELECT count(*) FROM producto_presentaciones")).scalar()
    response = client.post(
        f"/producto-presentaciones/{producto_presentacion_id}/precio",
        json={"precio": "12345678.90"},
    )
    if response.status_code != 201:
        record("create_precio", False, f"{response.status_code} {response.text}")
        if created_association:
            _delete_producto_presentacion(producto_presentacion_id)
        return
    precio_id = response.json()["id"]
    try:
        body = response.json()
        exact = Decimal(str(body["precio"])) == Decimal("12345678.90")
        record("create_precio", exact and body["id_producto_presentacion"] == producto_presentacion_id, f"id={precio_id} precio={body['precio']}")
        direct = client.get(f"/precios/{precio_id}")
        nested = client.get(f"/producto-presentaciones/{producto_presentacion_id}/precio")
        record("get_precio", direct.status_code == 200 and Decimal(str(direct.json()["precio"])) == Decimal("12345678.90"), f"{direct.status_code}")
        record("get_precio_by_producto_presentacion", nested.status_code == 200 and nested.json()["id"] == precio_id, f"{nested.status_code}")
        duplicate = client.post(
            f"/producto-presentaciones/{producto_presentacion_id}/precio",
            json={"precio": "1.00"},
        )
        record("duplicate_precio_409", duplicate.status_code == 409, f"{duplicate.status_code}")
        with engine.connect() as connection:
            after_count = connection.execute(text("SELECT count(*) FROM producto_presentaciones")).scalar()
        record("precio_does_not_modify_producto_presentacion", before_count == after_count)
    finally:
        _delete_precio(precio_id)
        if created_association:
            _delete_producto_presentacion(producto_presentacion_id)


def test_precio_missing_and_validation() -> None:
    producto_presentacion_id, created_association = _unpriced_producto_presentacion_id()
    missing_id = 999999
    checks = [
        ("missing_association_get_404", client.get(f"/producto-presentaciones/{missing_id}/precio"), 404),
        ("missing_association_post_404", client.post(f"/producto-presentaciones/{missing_id}/precio", json={"precio": "1.00"}), 404),
        ("existing_without_price_404", client.get(f"/producto-presentaciones/{producto_presentacion_id}/precio"), 404),
        ("missing_price_404", client.get("/precios/999999"), 404),
        ("rejects_association_body_422", client.post(f"/producto-presentaciones/{producto_presentacion_id}/precio", json={"id_producto_presentacion": producto_presentacion_id, "precio": "1.00"}), 422),
        ("negative_422", client.post(f"/producto-presentaciones/{producto_presentacion_id}/precio", json={"precio": "-0.01"}), 422),
        ("excess_scale_422", client.post(f"/producto-presentaciones/{producto_presentacion_id}/precio", json={"precio": "1.001"}), 422),
        ("excess_precision_422", client.post(f"/producto-presentaciones/{producto_presentacion_id}/precio", json={"precio": "10000000000.00"}), 422),
    ]
    for name, response, expected in checks:
        record(f"precio_{name}", response.status_code == expected, f"{response.status_code}")
    if created_association:
        _delete_producto_presentacion(producto_presentacion_id)


def test_precio_service_rolls_back_on_create_failure() -> None:
    session = TestingSessionLocal()
    service = PrecioService(session)
    producto_presentacion_id, created_association = _unpriced_producto_presentacion_id()

    def fail_create(*args, **kwargs):
        raise RuntimeError("forced create failure")

    try:
        with patch.object(service._repo, "create", side_effect=fail_create):
            try:
                service.create(producto_presentacion_id, Decimal("10.00"))
            except RuntimeError:
                record("precio_create_failure_rolls_back", not session.in_transaction())
            else:
                record("precio_create_failure_rolls_back", False, "failure was not raised")
    finally:
        session.close()
        if created_association:
            _delete_producto_presentacion(producto_presentacion_id)


def test_configuracion_comercio_complete_and_eager() -> None:
    comercio_ids = _existing_comercio_ids()
    if not comercio_ids:
        record("configuracion_comercio_setup", False, "requires seeded comercio")
        return
    comercio_id = comercio_ids[0]
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get(f"/comercios/{comercio_id}/configuracion")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
    if response.status_code != 200:
        record("configuracion_comercio_complete", False, f"{response.status_code} {response.text}")
        return
    body = response.json()
    scalar_fields = {
        "id", "nombre_fantasia", "nombre_corto", "razon_social", "cuit",
        "whatsapp", "calle", "numero", "piso_departamento", "localidad",
        "provincia", "codigo_postal", "slug", "estado_id", "zona_horaria",
        "moneda", "idioma", "fecha_alta", "fecha_ultima_modificacion", "fecha_baja",
    }
    record("configuracion_comercio_complete", scalar_fields.issubset(body), f"id={body['id']}")
    record("configuracion_comercio_estado", body["estado"]["id"] == body["estado_id"], body["estado"]["estado"])
    payments = body["medios_pago"]
    deliveries = body["metodos_entrega"]
    payment_ok = all(item["id_comercio"] == comercio_id and "medio_pago" in item for item in payments)
    delivery_ok = all(item["id_comercio"] == comercio_id and "metodo_entrega" in item for item in deliveries)
    record("configuracion_comercio_medios_pago", payment_ok and [item["id"] for item in payments] == sorted(item["id"] for item in payments), f"count={len(payments)}")
    delivery_keys = [(item["orden"], item["id"]) for item in deliveries]
    record("configuracion_comercio_metodos_entrega", delivery_ok and delivery_keys == sorted(delivery_keys), f"count={len(deliveries)}")
    forbidden = {"categorias_productos", "productos", "presentaciones", "precios", "producto_presentaciones"}
    record("configuracion_comercio_excludes_products", forbidden.isdisjoint(body))
    selects = [statement for statement in statements if statement.startswith("SELECT")]
    writes = [statement for statement in statements if statement.startswith(("INSERT", "UPDATE", "DELETE"))]
    record("configuracion_comercio_eager_queries", len(selects) <= 3 and not writes, f"selects={len(selects)} writes={len(writes)}")


def test_configuracion_comercio_empty_and_missing() -> None:
    missing = client.get("/comercios/999999/configuracion")
    record("configuracion_comercio_missing_404", missing.status_code == 404, f"{missing.status_code}")
    created = client.post("/comercios", json=_payload())
    if created.status_code != 201:
        record("configuracion_comercio_empty_arrays", False, f"setup={created.status_code}")
        return
    comercio_id = created.json()["id"]
    try:
        response = client.get(f"/comercios/{comercio_id}/configuracion")
        body = response.json()
        ok = response.status_code == 200 and body["medios_pago"] == [] and body["metodos_entrega"] == []
        record("configuracion_comercio_empty_arrays", ok, f"{response.status_code}")
    finally:
        _delete_comercio(comercio_id)


def _first_priced_producto_presentacion() -> int | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pp.id_producto, pp.id_presentacion, pp.id "
                "FROM producto_presentaciones pp "
                "JOIN producto_precios p ON p.id_producto_presentacion = pp.id "
                "ORDER BY pp.id LIMIT 1"
            )
        ).first()
    return row[0] if row is not None else None


def _first_priced_association() -> tuple[int, int, int] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pp.id, pp.id_producto, pp.id_presentacion "
                "FROM producto_presentaciones pp "
                "JOIN producto_precios p ON p.id_producto_presentacion = pp.id "
                "ORDER BY pp.id LIMIT 1"
            )
        ).first()
    if row is None:
        return None
    return row[0], row[1], row[2]


def test_producto_queries_detail_association_price() -> None:
    producto_id = _first_priced_producto_presentacion()
    if producto_id is None:
        record("producto_detalle_setup", False, "requires priced producto")
        return
    detail = client.get(f"/productos/{producto_id}/detalle")
    if detail.status_code != 200:
        record("producto_detalle", False, f"{detail.status_code} {detail.text}")
        return
    body = detail.json()
    record("producto_detalle", body["id"] == producto_id and body["id_comercio"] > 0, f"id={body['id']}")
    presentations = body["presentaciones"]
    if not presentations:
        record("producto_presentaciones", False, "no presentations in detail")
        return
    association = presentations[0]
    listed = client.get(f"/productos/{producto_id}/presentaciones")
    listed_body = listed.json()
    ordered = [(item["orden"], item["id"]) for item in listed_body] == sorted(
        (item["orden"], item["id"]) for item in listed_body
    )
    record("producto_presentaciones_list", listed.status_code == 200 and ordered, f"{listed.status_code}")
    specific = client.get(
        f"/productos/{producto_id}/presentaciones/{association['id_presentacion']}"
    )
    record(
        "producto_presentacion_specific",
        specific.status_code == 200 and specific.json()["id_producto"] == producto_id,
        f"{specific.status_code}",
    )
    foreign = client.get(f"/productos/{producto_id}/presentaciones/{association['id_presentacion'] + 9999}")
    record("producto_presentacion_404", foreign.status_code == 404, f"{foreign.status_code}")
    price = client.get(
        f"/productos/{producto_id}/presentaciones/{association['id_presentacion']}/precio"
    )
    price_body = price.json()
    record(
        "producto_presentacion_precio",
        price.status_code == 200 and Decimal(str(price_body["precio"])) == Decimal(str(association["precios"][0]["precio"])),
        f"{price.status_code}",
    )
    summary = client.get(f"/productos/{producto_id}/precios")
    summary_body = summary.json()
    summary_ok = (
        summary.status_code == 200
        and len(summary_body) == len(presentations)
        and all(Decimal(str(item["precio"])) > 0 for item in summary_body)
    )
    record("producto_precios_summary", summary_ok, f"count={len(summary_body)}")
    missing = client.get("/productos/999999/detalle")
    record("producto_detalle_missing_404", missing.status_code == 404, f"{missing.status_code}")


def test_producto_queries_search_name_availability() -> None:
    comercio_id = _existing_comercio_ids()[0]
    empty = client.get(f"/comercios/{comercio_id}/productos/buscar?q=")
    record("producto_buscar_empty_400", empty.status_code == 400, f"{empty.status_code}")
    foreign = client.get(f"/comercios/{999999 + comercio_id}/productos/buscar?q=zzz")
    record("producto_buscar_missing_comercio_404", foreign.status_code == 404, f"{foreign.status_code}")
    association = _first_priced_association()
    if association is None:
        record("producto_buscar_setup", False, "requires priced producto")
        return
    _, producto_id, _ = association
    with engine.connect() as connection:
        nombre = connection.execute(
            text("SELECT nombre FROM productos WHERE id = :id"), {"id": producto_id}
        ).scalar()
    if not nombre:
        record("producto_buscar_setup", False, "missing product name")
        return
    search = client.get(
        f"/comercios/{comercio_id}/productos/buscar", params={"q": (nombre or "").split()[0]}
    )
    ids = [item["id"] for item in search.json()] if search.status_code == 200 else []
    record("producto_buscar_comercio_scope", search.status_code == 200 and producto_id in ids, f"count={len(ids)}")
    exact = client.get(
        f"/comercios/{comercio_id}/productos/por-nombre", params={"nombre": nombre}
    )
    record(
        "producto_por_nombre_match",
        exact.status_code == 200 and exact.json()[0]["id"] == producto_id,
        f"{exact.status_code}",
    )
    missing_name = client.get(
        f"/comercios/{comercio_id}/productos/por-nombre", params={"nombre": "ZZZ-UNKNOWN-NAME"}
    )
    record("producto_por_nombre_missing_404", missing_name.status_code == 404, f"{missing_name.status_code}")
    disponibles = client.get(f"/comercios/{comercio_id}/productos/disponibles")
    vendibles = client.get(f"/comercios/{comercio_id}/productos/vendibles")
    incompletos = client.get(f"/comercios/{comercio_id}/productos/incompletos")
    record(
        "producto_disponibles",
        disponibles.status_code == 200,
        f"{disponibles.status_code}",
    )
    record(
        "producto_vendibles",
        vendibles.status_code == 200,
        f"{vendibles.status_code}",
    )
    record(
        "producto_incompletos",
        incompletos.status_code == 200,
        f"{incompletos.status_code}",
    )


def test_producto_queries_catalogo_and_category() -> None:
    comercio_id = _existing_comercio_ids()[0]
    catalogo = client.get(
        f"/comercios/{comercio_id}/catalogo", params={"solo_activos": "true", "solo_disponibles": "true"}
    )
    if catalogo.status_code != 200:
        record("producto_catalogo_filters", False, f"{catalogo.status_code}")
    else:
        categories = catalogo.json()["categorias"]
        ordered = [
            (cat["orden"], cat["id"]) for cat in categories
        ] == sorted((cat["orden"], cat["id"]) for cat in categories)
        all_have_products = all(cat["productos"] for cat in categories) and all(
            cat["productos"] and cat["productos"][0]["disponible"] for cat in categories
        )
        record(
            "producto_catalogo_filters",
            ordered and all_have_products,
            f"categories={len(categories)}",
        )
    category = _category_ids_by_comercio(comercio_id)[0]
    detail = client.get(f"/categorias-productos/{category}/productos-detalle")
    if detail.status_code != 200:
        record("producto_categoria_detalle", False, f"{detail.status_code} {detail.text}")
    else:
        body = detail.json()
        products = body["productos"]
        only_current = all(prod["id_categoria_producto"] == category for prod in products)
        record(
            "producto_categoria_detalle",
            only_current and products,
            f"count={len(products)}",
        )
    missing = client.get(f"/categorias-productos/999999/productos-detalle")
    record("producto_categoria_detalle_missing_404", missing.status_code == 404, f"{missing.status_code}")


def test_llm_settings_and_query_llm() -> None:
    import logging as _logging
    import os

    from backend.config.settings import load_settings
    from backend.llm.query_llm import (
        QueryLlm,
        QueryLlmConnectionError,
        QueryLlmHttpError,
        QueryLlmResponseError,
        QueryLlmTimeoutError,
    )

    defaults = load_settings()
    record(
        "llm_settings_defaults",
        defaults.llm_url == "http://localhost:11434/api/generate"
        and defaults.llm_model == "qwen2.5-coder:7b-ctx8192"
        and defaults.llm_timeout == 180
        and defaults.llm_keep_alive == "2h"
        and defaults.llm_num_ctx == 8192
        and defaults.llm_num_predict == 1500
        and defaults.llm_log_content is False
        and defaults.llm_log_max_chars == 1000,
        defaults.llm_url,
    )

    os.environ["LLM_MODEL"] = "custom"
    os.environ["LLM_URL"] = "http://example/api"
    os.environ["LLM_NUM_PREDICT"] = "500"
    overridden = load_settings()
    record(
        "llm_settings_env_overrides",
        overridden.llm_model == "custom"
        and overridden.llm_url == "http://example/api"
        and overridden.llm_num_predict == 500,
        f"{overridden.llm_model}/{overridden.llm_num_predict}",
    )
    del os.environ["LLM_MODEL"]
    del os.environ["LLM_URL"]
    del os.environ["LLM_NUM_PREDICT"]

    class _StubResponse:
        def __init__(self, body: str, status_code: int = 200, text: str = "") -> None:
            self._body = body
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                import requests as _req
                raise _req.exceptions.HTTPError(response=self)

        def json(self) -> dict:
            return {"response": self._body}

    def _client(body: str, json: dict, timeout: int) -> _StubResponse:
        _client.captured = {"json": json, "timeout": timeout, "url": defaults.llm_url}
        return _StubResponse(body)

    try:
        os.environ["LLM_URL"] = ""
    except Exception:
        pass

    defaults_for_query = load_settings()
    settings = load_settings()
    client = QueryLlm(settings=settings, transport=_client)
    result = client.request("hola")
    record(
        "llm_query_payload_and_response",
        result == {"ok": True}
        and _client.captured["json"]["prompt"] == "hola"
        and _client.captured["json"]["stream"] is False
        and _client.captured["json"]["think"] is False
        and _client.captured["json"]["format"] == "json"
        and _client.captured["json"]["options"]["temperature"] == 0
        and _client.captured["json"]["options"]["num_predict"] == 1500
        and _client.captured["json"]["options"]["num_ctx"] == 8192
        and _client.captured["timeout"] == 180,
        str(result),
    )

    def _extract_client(body: str) -> _StubResponse:
        return _StubResponse(body)
    client_extract = QueryLlm(settings=load_settings(), transport=_extract_client)
    record(
        "llm_query_json_extraction",
        client_extract.request("hola") == {"intents": []},
        "extracted",
    )

    def _empty_client(url: str, json: dict, timeout: int) -> _StubResponse:
        return _StubResponse("")
    client_empty = QueryLlm(settings=load_settings(), transport=_empty_client)
    try:
        client_empty.request("hola")
        accepted = True
    except QueryLlmResponseError:
        accepted = False
    record("llm_query_empty_rejected", not accepted, "empty body")

    def _bad_client(url: str, json: dict, timeout: int) -> _StubResponse:
        return _StubResponse("not-json")
    client_bad = QueryLlm(settings=load_settings(), transport=_bad_client)
    try:
        client_bad.request("hola")
        accepted = True
    except QueryLlmResponseError:
        accepted = False
    record("llm_query_invalid_json_rejected", not accepted, "not-json")

    def _timeout_client(url: str, json: dict, timeout: int):
        import requests as _req
        raise _req.exceptions.Timeout("simulated")
    client_timeout = QueryLlm(settings=load_settings(), transport=_timeout_client)
    try:
        client_timeout.request("hola")
        accepted = True
    except QueryLlmTimeoutError:
        accepted = False
    record("llm_query_timeout_exception", not accepted, "timeout")

    def _conn_client(url: str, json: dict, timeout: int):
        import requests as _req
        raise _req.exceptions.ConnectionError("simulated")
    client_conn = QueryLlm(settings=load_settings(), transport=_conn_client)
    try:
        client_conn.request("hola")
        accepted = True
    except QueryLlmConnectionError:
        accepted = False
    record("llm_query_connection_exception", not accepted, "connection")

    def _http_client(url: str, json: dict, timeout: int) -> _StubResponse:
        return _StubResponse("boom", status_code=500, text="boom")
    client_http = QueryLlm(settings=load_settings(), transport=_http_client)
    try:
        client_http.request("hola")
        accepted = True
    except QueryLlmHttpError as exc:
        accepted = False
    record("llm_query_http_exception", not accepted, "http")

    try:
        QueryLlm(settings=load_settings(), transport=_client).request("   ")
        accepted = True
    except ValueError:
        accepted = False
    record("llm_query_empty_prompt_rejected", not accepted, "blank prompt")

    log_records: list[_logging.LogRecord] = []

    class _ListHandler(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            log_records.append(record)

    capture_handler = _ListHandler(level=_logging.DEBUG)
    capture_logger = _logging.getLogger("backend.llm.query_llm")
    capture_logger.setLevel(_logging.DEBUG)
    capture_logger.addHandler(capture_handler)
    previous_content = load_settings().llm_log_content

    import os as _os

    _os.environ["LLM_LOG_CONTENT"] = "1"
    os.environ["LLM_LOG_MAX_CHARS"] = "4"
    info_settings = load_settings()
    info_client = QueryLlm(settings=info_settings, transport=_client)
    info_client.request("hola mundo")
    capture_logger.setLevel(_logging.INFO)
    _os.environ["LLM_LOG_CONTENT"] = previous_content and "1" or "0"
    _os.environ["LLM_LOG_MAX_CHARS"] = "1000"
    log_records.clear()
    capture_logger.setLevel(_logging.DEBUG)
    info_settings = load_settings()
    info_client = QueryLlm(settings=info_settings, transport=_client)
    info_client.request("hola mundo")
    info_records = [r for r in log_records if r.levelno == _logging.INFO]
    debug_records = [r for r in log_records if r.levelno == _logging.DEBUG]
    record(
        "llm_query_info_logs_metadata",
        any("model=" in r.getMessage() for r in info_records)
        and any("duration=" in r.getMessage() for r in info_records)
        and not any("prompt=" in r.getMessage() or "response=" in r.getMessage() for r in info_records),
        str(len(info_records)),
    )
    capture_logger.setLevel(_logging.INFO)
    capture_logger.removeHandler(capture_handler)


def test_intent_classification_contracts() -> None:
    from pydantic import ValidationError

    from backend.intents.schemas.intent_classification import (
        ClassifiedIntent,
        IntentClassificationResult,
        IntentName,
    )

    record(
        "intent_classification_legacy_names",
        len(IntentName) == 26
        and IntentName.AGREGAR_PRODUCTO.value == "agregar_producto"
        and IntentName.DESCONOCIDA.value == "desconocida",
        str(len(IntentName)),
    )

    single = ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje="hola")
    record(
        "intent_classification_single_valid",
        single.intent is IntentName.AGREGAR_PRODUCTO and single.mensaje == "hola",
        single.mensaje,
    )

    try:
        ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje="   ")
        accepted = True
    except ValidationError:
        accepted = False
    record("intent_classification_empty_message_rejected", not accepted, "whitespace")

    try:
        ClassifiedIntent.model_validate({"intent": "novalido", "mensaje": "x"})
        unsupported = True
    except ValidationError:
        unsupported = False
    record("intent_classification_unsupported_intent_rejected", not unsupported, "novalido")

    try:
        ClassifiedIntent.model_validate({"intent": "agregar_producto", "mensaje": "x", "extra": True})
        extra = True
    except ValidationError:
        extra = False
    record("intent_classification_extra_fields_rejected", not extra, "extra")

    result = IntentClassificationResult.model_validate(
        {
            "intents": [
                {"intent": "agregar_producto", "mensaje": "Quiero 2 pizzas"},
                {"intent": "set_direccion_entrega", "mensaje": "Av. Siempre Viva 742"},
            ],
            "mensaje": "Mensaje original",
        }
    )
    record(
        "intent_classification_order_preserved",
        [i.intent for i in result.intents] == [
            IntentName.AGREGAR_PRODUCTO,
            IntentName.SET_DIRECCION_ENTREGA,
        ],
        "order",
    )

    try:
        IntentClassificationResult.model_validate({"intents": [], "mensaje": "x"})
        empty_list = True
    except ValidationError:
        empty_list = False
    record("intent_classification_empty_intents_rejected", not empty_list, "empty list")

    try:
        IntentClassificationResult.model_validate(
            {"intents": [{"intent": "agregar_producto", "mensaje": "ok"}], "mensaje": "   "}
        )
        empty_message = True
    except ValidationError:
        empty_message = False
    record("intent_classification_empty_message_rejected", not empty_message, "whitespace")


def test_product_recognizer() -> None:
    import pathlib

    from backend.recognizers.product_recognizer import detectar_productos

    cat_mozzarella = [
        {
            "producto_presentacion_id": 1,
            "producto_id": 1,
            "presentacion_id": 1,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "chica",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
        {
            "producto_presentacion_id": 2,
            "producto_id": 1,
            "presentacion_id": 2,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "grande",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
        {
            "producto_presentacion_id": 21,
            "producto_id": 1,
            "presentacion_id": 21,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "familiar",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
    ]
    cat_with_unavailable = cat_mozzarella + [
        {
            "producto_presentacion_id": 50,
            "producto_id": 5,
            "presentacion_id": 50,
            "categoria_id": 301,
            "producto_nombre": "Coca Cola",
            "categoria_nombre": "Bebidas",
            "presentacion_codigo": "lata",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": False,
        },
        {
            "producto_presentacion_id": 51,
            "producto_id": 5,
            "presentacion_id": 51,
            "categoria_id": 301,
            "producto_nombre": "Coca Cola",
            "categoria_nombre": "Bebidas",
            "presentacion_codigo": "1 litro",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
    ]
    cat_with_inactive_pp = [
        {
            "producto_presentacion_id": 1,
            "producto_id": 1,
            "presentacion_id": 1,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "chica",
            "presentacion_descripcion": "",
            "activo": False,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
    ]
    cat_with_inactive_producto = [
        {
            "producto_presentacion_id": 2,
            "producto_id": 1,
            "presentacion_id": 2,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "grande",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": False,
            "presentacion_activo": True,
            "disponible": True,
        },
    ]
    cat_with_inactive_presentacion = [
        {
            "producto_presentacion_id": 3,
            "producto_id": 1,
            "presentacion_id": 3,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "mediana",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": False,
            "disponible": True,
        },
    ]
    cat_full_active = [
        {
            "producto_presentacion_id": 100,
            "producto_id": 1,
            "presentacion_id": 1,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "chica",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": True,
        },
    ]
    cat_legacy_shape = [
        {
            "producto_presentacion_id": 22,
            "producto_id": 1,
            "presentacion_id": 1,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "chica",
            "presentacion_descripcion": "",
            "activo": True,
            "disponible": True,
        },
        {
            "producto_presentacion_id": 37,
            "producto_id": 2,
            "presentacion_id": 2,
            "categoria_id": 201,
            "producto_nombre": "Empanada de Carne",
            "categoria_nombre": "Empanadas",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "",
            "activo": True,
            "disponible": True,
        },
    ]
    cat_legacy_short = [
        {
            "producto_presentacion_id": 100,
            "producto_id": 1,
            "presentacion_id": 1,
            "categoria_id": 101,
            "producto_nombre": "Pizza Mozzarella",
            "categoria_nombre": "Pizzas",
            "presentacion_codigo": "chica",
            "presentacion_descripcion": "",
            "disponible": True,
        }
    ]

    r1 = detectar_productos("una pizza muzza grande", cat_mozzarella)
    unique_id = r1["encontrados"][0]["producto_presentacion_id"] if r1["encontrados"] else None
    record(
        "product_recognizer_unique_match",
        len(r1["encontrados"]) == 1 and unique_id == 2,
        f"encontrados={[(p['producto_nombre'], p['presentacion_codigo']) for p in r1['encontrados']]}",
    )
    record(
        "product_recognizer_preserves_catalog_fields",
        all(
            k in r1["encontrados"][0]
            for k in (
                "producto_presentacion_id",
                "producto_id",
                "presentacion_id",
                "categoria_id",
                "producto_nombre",
                "categoria_nombre",
                "presentacion_codigo",
                "presentacion_descripcion",
                "activo",
                "producto_activo",
                "presentacion_activo",
                "disponible",
            )
        )
        if r1["encontrados"]
        else False,
        "all catalog fields preserved",
    )
    record(
        "product_recognizer_adds_cantidad",
        r1["encontrados"][0].get("cantidad") == 1 if r1["encontrados"] else False,
        f"cantidad={r1['encontrados'][0].get('cantidad') if r1['encontrados'] else None}",
    )
    record(
        "product_recognizer_adds_texto_origen",
        r1["encontrados"][0].get("texto_origen") == "una pizza muzza grande"
        if r1["encontrados"]
        else False,
        f"texto_origen={r1['encontrados'][0].get('texto_origen') if r1['encontrados'] else None}",
    )

    r2 = detectar_productos("quiero una pizza", cat_mozzarella)
    record(
        "product_recognizer_multiple_presentations_posibles",
        len(r2["encontrados"]) == 0
        and len(r2["encontrados_posibles"]) == 1
        and len(r2["encontrados_posibles"][0]["productos"]) == 3,
        f"posibles_len={len(r2['encontrados_posibles'][0]['productos']) if r2['encontrados_posibles'] else 0}",
    )
    record(
        "product_recognizer_posibles_grouping",
        r2["encontrados_posibles"][0]["texto_origen"] == "quiero una pizza"
        if r2["encontrados_posibles"]
        else False,
        f"texto_origen={r2['encontrados_posibles'][0]['texto_origen'] if r2['encontrados_posibles'] else None}",
    )

    r3 = detectar_productos("una pizza familiar", cat_mozzarella)
    familiar_id = (
        r3["encontrados"][0]["producto_presentacion_id"] if r3["encontrados"] else None
    )
    record(
        "product_recognizer_explicit_presentation",
        len(r3["encontrados"]) == 1 and familiar_id == 21,
        f"familiar_id={familiar_id}",
    )

    r_inactive_pp = detectar_productos("una pizza", cat_with_inactive_pp)
    record(
        "product_recognizer_inactive_product_presentation_excluded",
        len(r_inactive_pp["encontrados"]) == 0
        and len(r_inactive_pp["encontrados_posibles"]) == 0
        and len(r_inactive_pp["encontrados_no_disponibles"]) == 0,
        f"encontrados={len(r_inactive_pp['encontrados'])} posibles={len(r_inactive_pp['encontrados_posibles'])} no_disponibles={len(r_inactive_pp['encontrados_no_disponibles'])}",
    )

    r_inactive_producto = detectar_productos("una pizza", cat_with_inactive_producto)
    record(
        "product_recognizer_inactive_producto_excluded",
        len(r_inactive_producto["encontrados"]) == 0
        and len(r_inactive_producto["encontrados_posibles"]) == 0
        and len(r_inactive_producto["encontrados_no_disponibles"]) == 0,
        f"encontrados={len(r_inactive_producto['encontrados'])} posibles={len(r_inactive_producto['encontrados_posibles'])} no_disponibles={len(r_inactive_producto['encontrados_no_disponibles'])}",
    )

    r_inactive_presentacion = detectar_productos("una pizza", cat_with_inactive_presentacion)
    record(
        "product_recognizer_inactive_presentacion_excluded",
        len(r_inactive_presentacion["encontrados"]) == 0
        and len(r_inactive_presentacion["encontrados_posibles"]) == 0
        and len(r_inactive_presentacion["encontrados_no_disponibles"]) == 0,
        f"encontrados={len(r_inactive_presentacion['encontrados'])} posibles={len(r_inactive_presentacion['encontrados_posibles'])} no_disponibles={len(r_inactive_presentacion['encontrados_no_disponibles'])}",
    )

    cat_with_unavailable_one = [
        {
            "producto_presentacion_id": 50,
            "producto_id": 5,
            "presentacion_id": 50,
            "categoria_id": 301,
            "producto_nombre": "Coca Cola",
            "categoria_nombre": "Bebidas",
            "presentacion_codigo": "lata",
            "presentacion_descripcion": "",
            "activo": True,
            "producto_activo": True,
            "presentacion_activo": True,
            "disponible": False,
        },
    ]
    r_unavailable = detectar_productos("quiero una coca", cat_with_unavailable_one)
    record(
        "product_recognizer_active_but_unavailable_in_no_disponibles",
        len(r_unavailable["encontrados"]) == 0
        and len(r_unavailable["encontrados_no_disponibles"]) == 1
        and r_unavailable["encontrados_no_disponibles"][0]["producto_presentacion_id"] == 50,
        f"no_disp_ids={[p['producto_presentacion_id'] for p in r_unavailable['encontrados_no_disponibles']]}",
    )
    item_no_disp = r_unavailable["encontrados_no_disponibles"][0]
    record(
        "product_recognizer_active_but_unavailable_preserves_source_values",
        item_no_disp["producto_activo"] is True
        and item_no_disp["presentacion_activo"] is True
        and item_no_disp["disponible"] is False
        and item_no_disp["activo"] is True,
        f"producto_activo={item_no_disp['producto_activo']!r} presentacion_activo={item_no_disp['presentacion_activo']!r} disponible={item_no_disp['disponible']!r} activo={item_no_disp['activo']!r}",
    )

    r_full = detectar_productos("una pizza muzza", cat_full_active)
    record(
        "product_recognizer_full_active_available_in_encontrados",
        len(r_full["encontrados"]) == 1
        and r_full["encontrados"][0]["producto_presentacion_id"] == 100,
        f"encontrados={[(p['producto_nombre'], p['presentacion_codigo']) for p in r_full['encontrados']]}",
    )
    item_full = r_full["encontrados"][0]
    record(
        "product_recognizer_full_active_preserves_source_values",
        item_full["producto_activo"] is True
        and item_full["presentacion_activo"] is True
        and item_full["disponible"] is True
        and item_full["activo"] is True,
        f"producto_activo={item_full['producto_activo']!r} presentacion_activo={item_full['presentacion_activo']!r} disponible={item_full['disponible']!r} activo={item_full['activo']!r}",
    )

    r5 = detectar_productos("quiero algo raro", cat_mozzarella)
    record(
        "product_recognizer_unknown_in_no_encontrados",
        len(r5["encontrados"]) == 0
        and len(r5["encontrados_no_disponibles"]) == 0
        and len(r5["no_encontrados"]) == 1,
        f"no_encontrados_len={len(r5['no_encontrados'])}",
    )

    r6 = detectar_productos(
        "una pizza muzza y una empanada de carne", cat_legacy_shape
    )
    found_ids = sorted(p["producto_presentacion_id"] for p in r6["encontrados"])
    record(
        "product_recognizer_multiple_products",
        found_ids == [22, 37]
        and r6["encontrados"][0].get("cantidad") == 1
        and r6["encontrados"][1].get("cantidad") == 1,
        f"found_ids={found_ids}",
    )

    restricted = cat_mozzarella[:1]
    r7 = detectar_productos("una pizza familiar", restricted)
    record(
        "product_recognizer_restricted_catalog",
        len(r7["encontrados"]) == 0 and len(r7["no_encontrados"]) >= 1,
        f"encontrados_len={len(r7['encontrados'])} no_encontrados_len={len(r7['no_encontrados'])}",
    )

    r8 = detectar_productos("quiero algo", [])
    record(
        "product_recognizer_empty_catalog",
        len(r8["encontrados"]) == 0
        and len(r8["encontrados_posibles"]) == 0
        and len(r8["encontrados_no_disponibles"]) == 0
        and len(r8["no_encontrados"]) == 1,
        f"all empty={all(len(r8[k]) == 0 for k in ['encontrados', 'encontrados_posibles', 'encontrados_no_disponibles'])}",
    )

    r10 = detectar_productos("una pizza chica", cat_legacy_short)
    record(
        "product_recognizer_legacy_missing_activos_treated_as_true",
        len(r10["encontrados"]) == 1
        and r10["encontrados"][0]["presentacion_codigo"] == "chica",
        f"presentacion_codigo={r10['encontrados'][0]['presentacion_codigo'] if r10['encontrados'] else None}",
    )

    import backend.recognizers.product_recognizer as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "product_recognizer_only_one_public_symbol",
        public_symbols == {"detectar_productos"},
        str(sorted(public_symbols)),
    )

    recognizers_dir = pathlib.Path(module.__file__).parent
    recognizer_files = {
        p.name for p in recognizers_dir.iterdir() if p.is_file()
    }
    record(
        "product_recognizer_only_one_file_in_package",
        recognizer_files == {"__init__.py", "product_recognizer.py"},
        str(sorted(recognizer_files)),
    )

    source = module.__file__
    with open(source) as f:
        text = f.read()
    record(
        "product_recognizer_does_not_import_lista_json",
        "lista_json" not in text,
        "lista_json not in source",
    )
    record(
        "product_recognizer_does_not_import_sqlalchemy",
        "sqlalchemy" not in text and "from backend.db" not in text,
        "no sqlalchemy import",
    )
    record(
        "product_recognizer_does_not_import_repositories",
        "from backend.repositories" not in text,
        "no repositories import",
    )


def test_product_selection_context_resolver() -> None:
    import unittest.mock as mock

    from backend.intents.context.product_selection_context_resolver import (
        resolve_product_selection as _resolve,
    )
    def resolve_product_selection(db, message, intent):
        rows = db.scalars.return_value.all.return_value
        catalog = [
            {
                "producto_presentacion_id": pp.id,
                "producto_id": pp.id_producto,
                "presentacion_id": pp.id_presentacion,
                "categoria_id": pp.producto.id_categoria_producto,
                "producto_nombre": pp.producto.nombre,
                "categoria_nombre": pp.producto.categoria.descripcion,
                "presentacion_codigo": pp.presentacion.codigo,
                "presentacion_descripcion": pp.presentacion.descripcion,
                "producto_activo": bool(pp.producto.activo),
                "presentacion_activo": bool(pp.presentacion.activo),
                "activo": bool(pp.activo),
                "disponible": bool(pp.producto.disponible),
            }
            for pp in rows
        ]
        return _resolve(message, intent, catalog)

    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState

    def make_intent(
        status="pending_resolution",
        candidate_ids=None,
        resolved_data=None,
    ):
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza grande",
            status=status,
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data=resolved_data
            if resolved_data is not None
            else {"cantidad": 2},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id", status="pending", value=None
                ),
                RequirementState(name="cantidad", status="completed", value=2),
            ],
            candidate_ids=candidate_ids
            if candidate_ids is not None
            else [1, 2],
        )

    # returns unchanged when status is not pending_resolution
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos"
    ) as m:
        intent = make_intent(status="ready")
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "msg", intent)
        record(
            "pscr_returns_unchanged_when_status_ready",
            result is intent,
            "input returned unchanged",
        )
        m.assert_not_called()
        mock_db.scalars.assert_not_called()

    # returns unchanged when candidate_ids is empty
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos"
    ) as m:
        intent = make_intent(candidate_ids=[])
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "msg", intent)
        record(
            "pscr_returns_unchanged_when_candidates_empty",
            result is intent,
            "input returned unchanged",
        )
        m.assert_not_called()
        mock_db.scalars.assert_not_called()

    # unique selection by presentation
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 2,
                    "producto_id": 1,
                    "presentacion_id": 2,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "grande",
                    "presentacion_descripcion": "Grande",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 2,
                    "texto_origen": "una pizza grande",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        intent = make_intent()
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "la grande", intent)
        pp_req = next(
            r for r in result.requirements
            if r.name == "producto_presentacion_id"
        )
        record(
            "pscr_unique_selection",
            result.resolved_data["producto_presentacion_id"] == 2
            and result.candidate_ids == []
            and result.status == "ready"
            and pp_req.status == "completed"
            and pp_req.value == 2,
            f"pp_id={result.resolved_data.get('producto_presentacion_id')} status={result.status} pp_req.status={pp_req.status}",
        )

    # original quantity preserved
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 2,
                    "producto_id": 1,
                    "presentacion_id": 2,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "grande",
                    "presentacion_descripcion": "Grande",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 2,
                    "texto_origen": "la grande",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        intent = make_intent(resolved_data={"cantidad": 3, "note": "keep me"})
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "la grande", intent)
        record(
            "pscr_original_cantidad_preserved",
            result.resolved_data.get("cantidad") == 3
            and result.resolved_data.get("note") == "keep me",
            f"resolved_data={result.resolved_data}",
        )

    # query restricted to candidate_ids - verify the catalog contains the expected IDs and fields
    captured_catalog = []
    captured_intent_metadata = []
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        side_effect=lambda message, catalog, *, intent_metadata=None: (
            captured_catalog.extend(catalog)
            or captured_intent_metadata.append(intent_metadata)
            or {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }
        ),
    ):
        from backend.intents.context.product_selection_context_resolver import (
            resolve_product_selection as _r,
        )
        from unittest.mock import MagicMock

        class FakePP:
            def __init__(self, pp_id):
                self.id = pp_id
                self.id_producto = 1
                self.id_presentacion = 1
                self.activo = True
                self.producto = type("P", (), {
                    "id_categoria_producto": 1,
                    "nombre": "Pizza",
                    "activo": True,
                    "disponible": True,
                })()
                self.producto.categoria = type("C", (), {"descripcion": "Pizzas"})()
                self.presentacion = type("Pr", (), {
                    "codigo": "chica",
                    "descripcion": "Chica",
                    "activo": True,
                })()

        fake_db = MagicMock()
        fake_db.scalars.return_value.all.return_value = [FakePP(1), FakePP(2)]
        intent = make_intent(candidate_ids=[1, 2, 5])
        resolve_product_selection(fake_db, "x", intent)
    record(
        "pscr_query_restricted",
        {item["producto_presentacion_id"] for item in captured_catalog} == {1, 2},
        f"sent_ids={ {item['producto_presentacion_id'] for item in captured_catalog} }",
    )
    record(
        "pscr_catalog_has_12_fields",
        all(
            set(item.keys()) == {
                "producto_presentacion_id",
                "producto_id",
                "presentacion_id",
                "categoria_id",
                "producto_nombre",
                "categoria_nombre",
                "presentacion_codigo",
                "presentacion_descripcion",
                "producto_activo",
                "presentacion_activo",
                "activo",
                "disponible",
            }
            for item in captured_catalog
        ),
        f"keys={set(captured_catalog[0].keys()) if captured_catalog else set()}",
    )
    record(
        "pscr_intent_metadata_is_pending_product_selection_restricted",
        captured_intent_metadata == [{"catalog_scope": "pending_product_selection_restricted"}],
        f"intent_metadata={captured_intent_metadata}",
    )

    # ambiguous result returns unchanged
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 1,
                    "producto_id": 1,
                    "presentacion_id": 1,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "chica",
                    "presentacion_descripcion": "Chica",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 1,
                    "texto_origen": "x",
                },
                {
                    "producto_presentacion_id": 2,
                    "producto_id": 1,
                    "presentacion_id": 2,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "grande",
                    "presentacion_descripcion": "Grande",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 1,
                    "texto_origen": "x",
                },
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        intent = make_intent()
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_ambiguous_returns_unchanged",
            result is intent,
            "input returned unchanged",
        )

    # unavailable returns unchanged
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [
                {
                    "producto_presentacion_id": 1,
                    "producto_id": 1,
                    "presentacion_id": 1,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "chica",
                    "presentacion_descripcion": "Chica",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": False,
                    "cantidad": 1,
                    "texto_origen": "x",
                }
            ],
            "no_encontrados": [],
        },
    ):
        intent = make_intent()
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_unavailable_returns_unchanged",
            result is intent,
            "input returned unchanged",
        )

    # unknown returns unchanged
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "x"}],
        },
    ):
        intent = make_intent()
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_unknown_returns_unchanged",
            result is intent,
            "input returned unchanged",
        )

    # selected id outside original candidates returns unchanged
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 99,
                    "producto_id": 1,
                    "presentacion_id": 1,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "chica",
                    "presentacion_descripcion": "Chica",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 1,
                    "texto_origen": "x",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        intent = make_intent(candidate_ids=[1, 2])
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_selected_outside_candidates_rejected",
            result is intent,
            "input returned unchanged",
        )

    # status stays input when another required pending
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 2,
                    "producto_id": 1,
                    "presentacion_id": 2,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "grande",
                    "presentacion_descripcion": "Grande",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 1,
                    "texto_origen": "x",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 1},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id", status="pending", value=None
                ),
                RequirementState(name="other_requirement", status="pending", value=None),
            ],
            candidate_ids=[1, 2],
        )
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "la grande", intent)
        record(
            "pscr_status_keeps_input_when_other_pending",
            result.status == "pending_resolution",
            f"status={result.status}",
        )

    # function does not commit
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [
                {
                    "producto_presentacion_id": 1,
                    "producto_id": 1,
                    "presentacion_id": 1,
                    "categoria_id": 1,
                    "producto_nombre": "Pizza Mozzarella",
                    "categoria_nombre": "Pizzas",
                    "presentacion_codigo": "chica",
                    "presentacion_descripcion": "Chica",
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "activo": True,
                    "disponible": True,
                    "cantidad": 1,
                    "texto_origen": "x",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        },
    ):
        mock_db = mock.MagicMock()
        intent = make_intent()
        resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_does_not_commit",
            not mock_db.commit.called,
            f"commit called={mock_db.commit.called}",
        )

    # does not modify active_intent on no-resolution
    with mock.patch(
        "backend.intents.context.product_selection_context_resolver.detectar_productos",
        return_value={
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "x"}],
        },
    ):
        intent = make_intent()
        before = intent
        mock_db = mock.MagicMock()
        result = resolve_product_selection(mock_db, "x", intent)
        record(
            "pscr_does_not_modify_active_intent_on_no_resolution",
            result is before,
            "input returned unchanged",
        )

    # module __all__
    import backend.intents.context.product_selection_context_resolver as m
    record(
        "pscr_module_all",
        set(getattr(m, "__all__", ())) == {"resolve_product_selection"},
        f"__all__={getattr(m, '__all__', ())}",
    )

    # only one file in package
    import pathlib

    p = pathlib.Path(m.__file__).parent
    files = {x.name for x in p.iterdir() if x.is_file()}
    record(
        "pscr_only_one_file",
        "product_selection_context_resolver.py" in files
        and "context_type_resolver.py" in files
        and "pending_context_service.py" in files,
        f"files={sorted(files)}",
    )


def test_pscr_real_integration() -> None:
    """Real-integration test: calls the actual detectar_productos with no mock."""
    import datetime as _dt
    import unittest.mock as _mock

    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    from backend.intents.context.product_selection_context_service import (
        ProductSelectionContextService,
    )
    from backend.services.producto_query_service import ProductoQueryService
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState
    from backend.models.categorias_productos import CategoriaProducto
    from backend.models.presentaciones import Presentacion
    from backend.models.producto import Producto
    from backend.models.producto_alias import ProductoAlias
    from backend.models.producto_presentacion import ProductoPresentacion

    _engine = _create_engine("sqlite:///:memory:")
    _Session = _sessionmaker(bind=_engine)
    # Create only the four tables the resolver needs; do NOT use
    # Base.metadata.create_all because the Session model has a postgres-only
    # server_default with `::json` cast that SQLite can't parse.
    CategoriaProducto.__table__.create(_engine)
    Presentacion.__table__.create(_engine)
    Producto.__table__.create(_engine)
    ProductoPresentacion.__table__.create(_engine)
    ProductoAlias.__table__.create(_engine)

    with _Session() as s:
        s.add(CategoriaProducto(id_comercio=1, descripcion="Pizzas", activo=True, orden=0,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.add(Presentacion(id_comercio=1, codigo="chica", descripcion="Chica", activo=True, orden=0,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.add(Presentacion(id_comercio=1, codigo="grande", descripcion="Grande", activo=True, orden=1,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.add(Producto(id_categoria_producto=1, nombre="Pizza Mozzarella", descripcion=None,
            activo=True, disponible=True, orden=0,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.flush()
        s.add(ProductoPresentacion(id_producto=1, id_presentacion=1, activo=True, orden=0,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.add(ProductoPresentacion(id_producto=1, id_presentacion=2, activo=True, orden=1,
            fecha_alta=_dt.datetime.now(), fecha_ultima_modificacion=_dt.datetime.now()))
        s.commit()
        s.close()

    def _make_intent_pp(candidate_ids, cantidad=2, source_text="la grande"):
        return ProcessedIntent(
            intent="agregar_producto",
            source_text=source_text,
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": cantidad},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id", status="pending", value=None
                ),
                RequirementState(name="cantidad", status="completed", value=cantidad),
            ],
            candidate_ids=candidate_ids,
        )

    # Real end-to-end test: "pizza grande" should pick the "grande" presentation
    with _Session() as session:
        intent = _make_intent_pp(candidate_ids=[1, 2])
        result = ProductSelectionContextService(session).resolve("pizza grande", intent)
        record(
            "pscr_integration_pizza_grande_picks_grande",
            result.resolved_data["producto_presentacion_id"] == 2
            and result.status == "ready",
            f"pp_id={result.resolved_data.get('producto_presentacion_id')} status={result.status}",
        )
        record(
            "pscr_integration_pizza_grande_clears_candidates",
            result.candidate_ids == [],
            f"candidate_ids={result.candidate_ids}",
        )
        record(
            "pscr_integration_pizza_grande_preserves_cantidad",
            result.resolved_data.get("cantidad") == 2,
            f"cantidad={result.resolved_data.get('cantidad')}",
        )
        pp_req = next(
            r for r in result.requirements
            if r.name == "producto_presentacion_id"
        )
        record(
            "pscr_integration_pizza_grande_marks_pp_completed",
            pp_req.status == "completed",
            f"status={pp_req.status}",
        )

    # Real end-to-end test: "pizza chica" should pick the "chica" presentation
    with _Session() as session:
        intent = _make_intent_pp(candidate_ids=[1, 2], source_text="pizza chica")
        result = ProductSelectionContextService(session).resolve("pizza chica", intent)
        record(
            "pscr_integration_pizza_chica_picks_chica",
            result.resolved_data["producto_presentacion_id"] == 1
            and result.status == "ready",
            f"pp_id={result.resolved_data.get('producto_presentacion_id')} status={result.status}",
        )


def test_pending_context_service() -> None:
    from backend.intents.context.pending_context_service import (
        clear_pending_context,
        set_pending_intent,
    )
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState
    from backend.intents.services.pending_intent_service import load as load_state
    from backend.models.session import Session as SessionModel

    valid = ProcessedIntent(
        intent="agregar_producto",
        source_text="x",
        status="pending_resolution",
        handler="agregar_producto",
        resolved_data={},
        requirements=[RequirementState(name="producto_presentacion_id", status="pending", value=None)],
        candidate_ids=[10, 11],
    )

    sa = SessionModel()
    sa.pending_intents = {}
    sa.context_type = None
    new_state = set_pending_intent(sa, valid)
    record(
        "pending_context_set_pending_intent_returns_state",
        new_state.active is valid,
        f"active.intent={new_state.active.intent if new_state.active else None}",
    )
    record(
        "pending_context_set_pending_intent_writes_context_type",
        sa.context_type == "product_selection",
        f"context_type={sa.context_type}",
    )
    persisted = load_state(sa)
    record(
        "pending_context_set_pending_intent_persists_in_state",
        persisted.active is not None
        and persisted.active.intent == valid.intent
        and persisted.active.source_text == valid.source_text,
        f"active.intent={persisted.active.intent if persisted.active is not None else None}",
    )

    for bad_status in ("ready", "executed", "rejected", "failed"):
        bm = SessionModel()
        bm.pending_intents = {}
        bm.context_type = None
        try:
            set_pending_intent(
                bm,
                ProcessedIntent(
                    intent="x",
                    source_text="x",
                    status=bad_status,
                    handler="x",
                    resolved_data={},
                    requirements=[],
                    candidate_ids=[],
                ),
            )
            rejected = False
        except ValueError:
            rejected = True
        not_mutated = bm.context_type is None
        record(
            f"pending_context_rejects_status_{bad_status}_raises",
            rejected,
            "ValueError raised" if rejected else "FAIL",
        )
        record(
            f"pending_context_rejects_status_{bad_status}_no_mutation",
            not_mutated,
            f"context_type={bm.context_type}",
        )

    for case_name, requirements, candidate_ids in (
        (
            "pp_completed",
            [RequirementState(name="producto_presentacion_id", status="completed", value=42)],
            [1],
        ),
        (
            "missing_pp",
            [RequirementState(name="cantidad", status="pending", value=1)],
            [1],
        ),
        (
            "empty_candidates",
            [RequirementState(name="producto_presentacion_id", status="pending", value=None)],
            [],
        ),
    ):
        bm = SessionModel()
        bm.pending_intents = {}
        bm.context_type = None
        try:
            set_pending_intent(
                bm,
                ProcessedIntent(
                    intent="x",
                    source_text="x",
                    status="pending_resolution",
                    handler="x",
                    resolved_data={},
                    requirements=requirements,
                    candidate_ids=candidate_ids,
                ),
            )
            rejected = False
        except ValueError:
            rejected = True
        not_mutated = bm.context_type is None
        record(
            f"pending_context_rejects_{case_name}_raises",
            rejected,
            "ValueError raised" if rejected else "FAIL",
        )
        record(
            f"pending_context_rejects_{case_name}_no_mutation",
            not_mutated,
            f"context_type={bm.context_type}",
        )

    cl = SessionModel()
    cl.pending_intents = {}
    cl.context_type = None
    set_pending_intent(cl, valid)
    result = clear_pending_context(cl)
    record(
        "pending_context_clear_returns_none",
        result is None,
        f"returned={result!r}",
    )
    record(
        "pending_context_clear_resets_context_type",
        cl.context_type is None,
        f"context_type={cl.context_type}",
    )
    after_clear = load_state(cl)
    record(
        "pending_context_clear_resets_pending_intents",
        after_clear.active is None and after_clear.queue == [],
        f"active={after_clear.active} queue_len={len(after_clear.queue)}",
    )

    cl2 = SessionModel()
    cl2.pending_intents = {}
    cl2.context_type = "product_selection"
    clear_pending_context(cl2)
    record(
        "pending_context_clear_resets_only_context_type",
        cl2.context_type is None and load_state(cl2).active is None,
        f"context_type={cl2.context_type}",
    )

    cl3 = SessionModel()
    cl3.pending_intents = {}
    cl3.context_type = None
    clear_pending_context(cl3)
    record(
        "pending_context_clear_on_fresh_session",
        cl3.context_type is None,
        f"context_type={cl3.context_type}",
    )

    import backend.intents.context.pending_context_service as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "pending_context_only_two_public_symbols",
        public_symbols == {"set_pending_intent", "clear_pending_context"},
        str(sorted(public_symbols)),
    )

    import pathlib

    context_dir = pathlib.Path(module.__file__).parent
    context_files = {
        p.name for p in context_dir.iterdir() if p.is_file()
    }
    record(
        "pending_context_two_files_in_package",
        context_files == {
            "__init__.py",
            "context_type_resolver.py",
            "pending_context_service.py",
            "product_selection_context_resolver.py",
            "product_selection_context_service.py",
        },
        str(sorted(context_files)),
    )


def test_context_type_resolver() -> None:
    from backend.intents.context.context_type_resolver import resolve_context_type
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState
    from backend.sessions.enums.context_type import ContextType

    def make_intent(status, pp_status=None, qty_status=None, candidates=None):
        requirements = []
        if pp_status is not None:
            requirements.append(
                RequirementState(name="producto_presentacion_id", status=pp_status, value=None)
            )
        if qty_status is not None:
            requirements.append(
                RequirementState(name="cantidad", status=qty_status, value=1)
            )
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status=status,
            handler="agregar_producto",
            resolved_data={},
            requirements=requirements,
            candidate_ids=candidates or [],
        )

    record(
        "context_type_resolver_all_three_returns_product_selection",
        resolve_context_type(make_intent("pending_resolution", "pending", "pending", [10, 11]))
        == ContextType.PRODUCT_SELECTION,
        "all three conditions met",
    )
    record(
        "context_type_resolver_single_candidate_returns_product_selection",
        resolve_context_type(make_intent("pending_resolution", "pending", "pending", [42]))
        == ContextType.PRODUCT_SELECTION,
        "single candidate",
    )
    record(
        "context_type_resolver_two_pending_requirements_returns_product_selection",
        resolve_context_type(
            make_intent("pending_resolution", "pending", "pending", [1])
        )
        == ContextType.PRODUCT_SELECTION,
        "two pending requirements, single candidate",
    )
    record(
        "context_type_resolver_empty_candidates_returns_none",
        resolve_context_type(make_intent("pending_resolution", "pending", "pending", []))
        is None,
        "empty candidate_ids",
    )
    for s in ("ready", "executed", "rejected", "failed"):
        record(
            f"context_type_resolver_{s}_returns_none",
            resolve_context_type(make_intent(s, "completed", "completed", [1])) is None,
            f"status={s}",
        )
    record(
        "context_type_resolver_empty_requirements_returns_none",
        resolve_context_type(make_intent("pending_resolution", None, None, [1])) is None,
        "empty requirements list",
    )
    record(
        "context_type_resolver_pp_completed_returns_none",
        resolve_context_type(make_intent("pending_resolution", "completed", "pending", [1]))
        is None,
        "pp completed",
    )
    record(
        "context_type_resolver_only_cantidad_pending_returns_none",
        resolve_context_type(make_intent("pending_resolution", None, "pending", [1]))
        is None,
        "only cantidad pending",
    )

    import backend.intents.context.context_type_resolver as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "context_type_resolver_only_one_public_symbol",
        public_symbols == {"resolve_context_type"},
        str(sorted(public_symbols)),
    )

    import pathlib

    context_dir = pathlib.Path(module.__file__).parent
    context_files = {
        p.name for p in context_dir.iterdir() if p.is_file()
    }
    record(
        "context_type_resolver_only_two_files_in_package",
        context_files
        == {
            "__init__.py",
            "context_type_resolver.py",
            "pending_context_service.py",
            "product_selection_context_resolver.py",
            "product_selection_context_service.py",
        },
        str(sorted(context_files)),
    )


def test_session_context_type_enum() -> None:
    from backend.sessions.enums.context_type import ContextType

    record(
        "context_type_has_only_one_member",
        list(ContextType) == [ContextType.PRODUCT_SELECTION],
        str(list(ContextType)),
    )
    record(
        "context_type_product_selection_value",
        ContextType.PRODUCT_SELECTION.value == "product_selection",
        f"value={ContextType.PRODUCT_SELECTION.value}",
    )
    record(
        "context_type_str_equality",
        ContextType.PRODUCT_SELECTION == "product_selection",
        str(ContextType.PRODUCT_SELECTION == "product_selection"),
    )
    record(
        "context_type_isinstance_str",
        isinstance(ContextType.PRODUCT_SELECTION, str),
        str(isinstance(ContextType.PRODUCT_SELECTION, str)),
    )
    record(
        "context_type_str_call",
        str(ContextType.PRODUCT_SELECTION) == "product_selection",
        str(str(ContextType.PRODUCT_SELECTION)),
    )

    for bad in ("unknown", "Product_Selection", ""):
        try:
            ContextType(bad)
            rejected = False
        except ValueError:
            rejected = True
        record(
            f"context_type_rejects_{bad or 'empty'}_value",
            rejected,
            "ValueError raised" if rejected else "FAIL: not rejected",
        )

    import backend.sessions.enums.context_type as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "context_type_only_one_public_symbol",
        public_symbols == {"ContextType"},
        str(sorted(public_symbols)),
    )

    import os
    import pathlib

    enums_path = pathlib.Path(module.__file__).parent
    enums_files = {p.name for p in enums_path.iterdir() if p.is_file()}
    record(
        "context_type_enums_dir_only_two_files",
        enums_files == {"__init__.py", "context_type.py"},
        str(sorted(enums_files)),
    )

    sessions_path = pathlib.Path(module.__file__).parent.parent
    shortcuts = sessions_path / "enums.py"
    record(
        "context_type_no_enums_py_shortcut",
        not shortcuts.exists(),
        f"exists={shortcuts.exists()}",
    )


def test_pending_intent_service() -> None:
    from backend.intents.services.pending_intent_service import (
        clear,
        enqueue,
        load,
        remove_active,
        set_active,
    )
    from backend.intents.schemas.pending_intents import PendingIntents
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.models.session import Session as SessionModel

    empty = SessionModel()
    empty.pending_intents = {}
    record(
        "service_load_empty",
        load(empty).model_dump() == {"version": 1, "active": None, "queue": []},
        str(load(empty).model_dump()),
    )

    none_pi = SessionModel()
    none_pi.pending_intents = None
    record(
        "service_load_none_treated_as_empty",
        load(none_pi).model_dump() == {"version": 1, "active": None, "queue": []},
        str(load(none_pi).model_dump()),
    )

    persisted = SessionModel()
    intent_a = ProcessedIntent(
        intent="agregar_producto",
        source_text="add 2 pizzas",
        status="ready",
        handler="agregar_producto",
    )
    intent_b = ProcessedIntent(
        intent="agregar_producto",
        source_text="add 3 pizzas",
        status="pending_resolution",
        handler="agregar_producto",
    )

    persisted.pending_intents = PendingIntents(active=intent_a, queue=[intent_b]).model_dump(mode="json")
    record(
        "service_pending_intents_stored_as_dict",
        isinstance(persisted.pending_intents, dict),
        f"type={type(persisted.pending_intents).__name__}",
    )
    loaded = load(persisted)
    record(
        "service_load_persisted_state",
        loaded.active is not None
        and loaded.active.intent == "agregar_producto"
        and loaded.active.source_text == "add 2 pizzas"
        and len(loaded.queue) == 1
        and loaded.queue[0].source_text == "add 3 pizzas",
        f"active={loaded.active.intent if loaded.active else None} queue_len={len(loaded.queue)}",
    )

    sa = SessionModel()
    sa.pending_intents = {}
    new_state = set_active(sa, intent_a)
    record(
        "service_set_active_returns_new_state",
        new_state.active is intent_a,
        f"active={new_state.active.intent if new_state.active else None}",
    )
    record(
        "service_set_active_persists_as_dict",
        isinstance(sa.pending_intents, dict)
        and sa.pending_intents == PendingIntents(active=intent_a).model_dump(mode="json"),
        f"type={type(sa.pending_intents).__name__}",
    )
    reloaded = load(sa)
    record(
        "service_set_active_round_trip",
        reloaded.active is not None and reloaded.active.intent == "agregar_producto",
        f"reloaded.active={reloaded.active.intent if reloaded.active else None}",
    )

    en = SessionModel()
    en.pending_intents = {}
    after_enqueue_a = enqueue(en, intent_a)
    after_enqueue_b = enqueue(en, intent_b)
    record(
        "service_enqueue_appends",
        len(after_enqueue_b.queue) == 2
        and after_enqueue_b.queue[0].source_text == "add 2 pizzas"
        and after_enqueue_b.queue[1].source_text == "add 3 pizzas",
        f"queue_len={len(after_enqueue_b.queue)}",
    )
    record(
        "service_enqueue_returns_new_state",
        len(after_enqueue_a.queue) == 1 and after_enqueue_a.queue[0] is intent_a,
        f"queue_len={len(after_enqueue_a.queue)}",
    )
    record(
        "service_enqueue_persists_as_dict",
        isinstance(en.pending_intents, dict),
        f"type={type(en.pending_intents).__name__}",
    )

    ra = SessionModel()
    ra.pending_intents = {}
    set_active(ra, intent_a)
    enqueue(ra, intent_b)
    promoted = remove_active(ra)
    record(
        "service_remove_active_promotes_queue_head",
        promoted.active is not None
        and promoted.active.source_text == "add 3 pizzas"
        and len(promoted.queue) == 0,
        f"active={promoted.active.source_text if promoted.active else None} queue_len={len(promoted.queue)}",
    )
    final = remove_active(ra)
    record(
        "service_remove_active_with_empty_queue_sets_none",
        final.active is None and len(final.queue) == 0,
        f"active={final.active} queue_len={len(final.queue)}",
    )

    cl = SessionModel()
    cl.pending_intents = {}
    set_active(cl, intent_a)
    enqueue(cl, intent_b)
    result = clear(cl)
    record("service_clear_returns_none", result is None, f"returned={result!r}")
    record(
        "service_clear_persists_empty_state",
        load(cl).model_dump() == {"version": 1, "active": None, "queue": []},
        str(load(cl).model_dump()),
    )

    rt = SessionModel()
    rt.pending_intents = {}
    set_active(rt, intent_a)
    enqueue(rt, intent_b)

    parsed = PendingIntents.model_validate(rt.pending_intents or {})
    record(
        "service_mutations_round_trip",
        parsed.active is not None
        and parsed.active.intent == "agregar_producto"
        and len(parsed.queue) == 1,
        f"active={parsed.active.intent if parsed.active else None} queue_len={len(parsed.queue)}",
    )

    import backend.intents.services.pending_intent_service as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "service_only_five_public_symbols",
        public_symbols == {"load", "set_active", "enqueue", "remove_active", "clear"},
        str(sorted(public_symbols)),
    )

    import pathlib

    services_dir = pathlib.Path(module.__file__).parent
    service_files = {
        p.name for p in services_dir.iterdir() if p.is_file()
    }
    record(
        "service_only_service_file_in_package",
        service_files == {"__init__.py", "pending_intent_service.py"},
        str(sorted(service_files)),
    )


def test_process_agregar_producto_processor() -> None:
    from backend.intents.processor import process_agregar_producto
    from backend.intents.schemas.processed_intent import ProcessedIntent

    full = process_agregar_producto(
        "add 2 pizzas",
        {
            "resolved_data": {"producto_presentacion_id": 42, "cantidad": 2},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    record(
        "processor_returns_processed_intent_full",
        isinstance(full, ProcessedIntent)
        and full.intent == "agregar_producto"
        and full.source_text == "add 2 pizzas"
        and full.recognizer == "recognizer_productos"
        and full.handler == "agregar_producto"
        and full.status == "ready"
        and full.resolved_data == {"producto_presentacion_id": 42, "cantidad": 2}
        and full.candidate_ids == [],
        f"status={full.status}",
    )

    all_completed = process_agregar_producto(
        "add 2 pizzas",
        {
            "resolved_data": {"producto_presentacion_id": 42, "cantidad": 2},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    all_completed_ok = (
        all_completed.status == "ready"
        and all(req.status == "completed" for req in all_completed.requirements)
    )
    record(
        "processor_all_required_completed_ready",
        all_completed_ok,
        f"status={all_completed.status}",
    )

    missing_pp = process_agregar_producto(
        "add 2 pizzas",
        {
            "resolved_data": {"cantidad": 2},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    pp_state = next(r for r in missing_pp.requirements if r.name == "producto_presentacion_id")
    record(
        "processor_missing_producto_presentacion_id_pending_resolution",
        missing_pp.status == "pending_resolution" and pp_state.status == "pending" and pp_state.value is None,
        f"status={missing_pp.status} pp_state.status={pp_state.status} pp_state.value={pp_state.value}",
    )

    missing_qty = process_agregar_producto(
        "add a pizza",
        {
            "resolved_data": {"producto_presentacion_id": 42},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    qty_state = next(r for r in missing_qty.requirements if r.name == "cantidad")
    record(
        "processor_missing_cantidad_default_one",
        missing_qty.status == "pending_resolution" and qty_state.status == "pending" and qty_state.value == 1,
        f"qty_state.value={qty_state.value}",
    )

    candidates = process_agregar_producto(
        "add pizza",
        {
            "resolved_data": {"producto_presentacion_id": 1, "cantidad": 1},
            "candidate_ids": [10, 11, 12],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    record(
        "processor_candidate_ids_preserved",
        candidates.candidate_ids == [10, 11, 12],
        f"candidate_ids={candidates.candidate_ids}",
    )

    empty_candidates = process_agregar_producto(
        "x",
        {
            "resolved_data": {"producto_presentacion_id": 1, "cantidad": 1},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    record(
        "processor_empty_candidate_ids",
        empty_candidates.candidate_ids == [],
        f"candidate_ids={empty_candidates.candidate_ids}",
    )

    source_text = process_agregar_producto(
        "add 2 pizzas",
        {
            "resolved_data": {"producto_presentacion_id": 1, "cantidad": 1},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    record(
        "processor_source_text_preserved",
        source_text.source_text == "add 2 pizzas",
        f"source_text={source_text.source_text}",
    )

    rh = process_agregar_producto(
        "x",
        {
            "resolved_data": {"producto_presentacion_id": 1, "cantidad": 1},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    record(
        "processor_recognizer_and_handler_from_contract",
        rh.recognizer == "recognizer_productos" and rh.handler == "agregar_producto",
        f"recognizer={rh.recognizer} handler={rh.handler}",
    )

    rt = process_agregar_producto(
        "add 2 pizzas",
        {
            "resolved_data": {"producto_presentacion_id": 42, "cantidad": 2},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
    )
    round_tripped = ProcessedIntent.model_validate(rt.model_dump())
    rt_ok = (
        round_tripped.status == rt.status
        and round_tripped.intent == rt.intent
        and round_tripped.handler == rt.handler
        and round_tripped.resolved_data == rt.resolved_data
        and round_tripped.candidate_ids == rt.candidate_ids
    )
    record("processor_pydantic_round_trip", rt_ok, f"status={round_tripped.status}")

    import backend.intents.processor as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "processor_only_one_public_symbol",
        public_symbols == {"process_agregar_producto"},
        str(sorted(public_symbols)),
    )

    import pathlib

    intents_dir = pathlib.Path(module.__file__).parent
    processor_file = intents_dir / "processor.py"
    record(
        "processor_only_new_file_in_intents",
        processor_file.exists() and processor_file.is_file(),
        str(processor_file.name),
    )


def test_product_intent_resolver() -> None:
    from backend.intents.resolvers.product_intent_resolver import resolve_product_intent

    single = resolve_product_intent({"encontrados": [{"producto_presentacion_id": 42, "cantidad": 2}]})
    record(
        "resolver_single_confident_match",
        single == {
            "resolved_data": {"producto_presentacion_id": 42, "cantidad": 2},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
        str(single),
    )

    multi = resolve_product_intent(
        {"encontrados_posibles": [{"producto_presentacion_id": 10, "cantidad": 3}, {"producto_presentacion_id": 11}, {"producto_presentacion_id": 12}]}
    )
    record(
        "resolver_multiple_candidates_candidate_ids_in_order",
        multi["candidate_ids"] == [10, 11, 12],
        f"candidate_ids={multi['candidate_ids']}",
    )
    record(
        "resolver_multiple_candidates_first_cantidad_preserved",
        multi["resolved_data"] == {"cantidad": 3},
        f"resolved_data={multi['resolved_data']}",
    )
    record(
        "resolver_multiple_candidates_no_producto_id",
        "producto_presentacion_id" not in multi["resolved_data"],
        f"resolved_data={multi['resolved_data']}",
    )

    no_cantidad = resolve_product_intent({"encontrados_posibles": [{"producto_presentacion_id": 10}]})
    record(
        "resolver_candidate_without_cantidad_empty_resolved_data",
        no_cantidad["resolved_data"] == {} and no_cantidad["candidate_ids"] == [10],
        f"resolved_data={no_cantidad['resolved_data']}",
    )

    unavailable = resolve_product_intent(
        {"encontrados_no_disponibles": [{"texto_origen": "a"}, {"texto_origen": "b"}]}
    )
    record(
        "resolver_unavailable_items_in_order",
        unavailable["unavailable_items"] == ["a", "b"],
        f"unavailable_items={unavailable['unavailable_items']}",
    )

    not_found = resolve_product_intent(
        {"no_encontrados": [{"texto_origen": "x"}, {"texto_origen": "y"}]}
    )
    record(
        "resolver_not_found_items_in_order",
        not_found["not_found_items"] == ["x", "y"],
        f"not_found_items={not_found['not_found_items']}",
    )

    empty = resolve_product_intent({})
    record(
        "resolver_empty_input",
        empty == {
            "resolved_data": {},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
        str(empty),
    )

    all_empty = resolve_product_intent(
        {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
    )
    record(
        "resolver_all_empty_arrays",
        all_empty == {
            "resolved_data": {},
            "candidate_ids": [],
            "unavailable_items": [],
            "not_found_items": [],
        },
        str(all_empty),
    )

    partial = resolve_product_intent({"encontrados": [{"producto_presentacion_id": 1, "cantidad": 1}]})
    record(
        "resolver_missing_keys_default_empty",
        partial["candidate_ids"] == []
        and partial["unavailable_items"] == []
        and partial["not_found_items"] == []
        and partial["resolved_data"] == {"producto_presentacion_id": 1, "cantidad": 1},
        str(partial),
    )

    confident_with_candidates = resolve_product_intent(
        {
            "encontrados": [{"producto_presentacion_id": 42, "cantidad": 2}],
            "encontrados_posibles": [{"producto_presentacion_id": 10}, {"producto_presentacion_id": 11}],
        }
    )
    record(
        "resolver_confident_match_suppresses_candidates",
        confident_with_candidates["resolved_data"] == {"producto_presentacion_id": 42, "cantidad": 2}
        and confident_with_candidates["candidate_ids"] == [],
        f"resolved_data={confident_with_candidates['resolved_data']} candidate_ids={confident_with_candidates['candidate_ids']}",
    )

    keys_present = set(resolve_product_intent({}).keys())
    record(
        "resolver_all_four_output_keys_present",
        keys_present == {"resolved_data", "candidate_ids", "unavailable_items", "not_found_items"},
        str(sorted(keys_present)),
    )

    import backend.intents.resolvers.product_intent_resolver as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "resolver_only_one_public_symbol",
        public_symbols == {"resolve_product_intent"},
        str(sorted(public_symbols)),
    )

    import pathlib

    resolvers_dir = pathlib.Path(module.__file__).parent
    resolver_files = {
        p.name for p in resolvers_dir.iterdir() if p.is_file() and p.name != "__init__.py"
    }
    record(
        "resolver_only_one_file_in_package",
        resolver_files == {"product_intent_resolver.py"},
        str(sorted(resolver_files)),
    )


def test_pending_intents_schema() -> None:
    from typing import Any, cast

    from pydantic import ValidationError

    from backend.intents.schemas.pending_intents import PendingIntents
    from backend.intents.schemas.processed_intent import ProcessedIntent

    default = PendingIntents()
    default_ok = default.version == 1 and default.active is None and default.queue == []
    record("pending_intents_default_creation", default_ok, f"version={default.version}")

    a = PendingIntents()
    b = PendingIntents()
    a.queue.append(ProcessedIntent(intent="x", source_text="x", status="pending_resolution", handler="x"))
    isolated = b.queue == []
    record("pending_intents_default_queue_isolated", isolated, f"a.queue={len(a.queue)} b.queue={len(b.queue)}")

    active_pi = ProcessedIntent(
        intent="agregar_producto",
        source_text="add 2",
        status="ready",
        handler="agregar_producto",
    )
    with_active = PendingIntents(active=active_pi)
    record(
        "pending_intents_creation_with_active",
        with_active.active is not None
        and with_active.active.intent == "agregar_producto"
        and with_active.queue == [],
        f"active={with_active.active.intent if with_active.active else None}",
    )

    queued = PendingIntents(
        queue=[
            ProcessedIntent(intent="first", source_text="x", status="ready", handler="h"),
            ProcessedIntent(intent="second", source_text="x", status="pending_resolution", handler="h"),
        ]
    )
    queue_ok = (
        len(queued.queue) == 2
        and queued.queue[0].intent == "first"
        and queued.queue[1].intent == "second"
        and queued.active is None
    )
    record("pending_intents_creation_with_queue", queue_ok, f"queue={[p.intent for p in queued.queue]}")

    both = PendingIntents(
        active=active_pi,
        queue=[ProcessedIntent(intent="next", source_text="x", status="pending_resolution", handler="h")],
    )
    both_ok = (
        both.active is not None
        and both.active.intent == "agregar_producto"
        and len(both.queue) == 1
        and both.queue[0].intent == "next"
        and both.version == 1
    )
    record("pending_intents_creation_with_active_and_queue", both_ok, f"active+queue")

    try:
        PendingIntents(
            active=ProcessedIntent(
                intent="x", source_text="x", status=cast(Any, "bad"), handler="x"
            )
        )
        active_rejected = False
    except ValidationError:
        active_rejected = True
    record("pending_intents_invalid_active_status_rejected", active_rejected, "ValidationError raised")

    try:
        PendingIntents(
            queue=[
                ProcessedIntent(
                    intent="x", source_text="x", status=cast(Any, "bad"), handler="x"
                )
            ]
        )
        queue_rejected = False
    except ValidationError:
        queue_rejected = True
    record("pending_intents_invalid_queue_status_rejected", queue_rejected, "ValidationError raised")

    try:
        PendingIntents(active=cast(Any, {"source_text": "x", "status": "pending_resolution", "handler": "x"}))
        missing_intent_rejected = False
    except ValidationError:
        missing_intent_rejected = True
    record("pending_intents_missing_active_intent_rejected", missing_intent_rejected, "ValidationError raised")

    full = PendingIntents(
        active=ProcessedIntent(
            intent="agregar_producto",
            source_text="add 2",
            status="ready",
            handler="agregar_producto",
        ),
        queue=[
            ProcessedIntent(
                intent="agregar_producto",
                source_text="add 3",
                status="pending_resolution",
                handler="agregar_producto",
            ),
            ProcessedIntent(
                intent="confirmar_pedido",
                source_text="confirm",
                status="pending_resolution",
                handler="confirmar_pedido",
            ),
        ],
    )
    dumped = full.model_dump(mode="json")
    restored = PendingIntents.model_validate(dumped)
    round_trip_ok = (
        restored.version == full.version
        and full.active is not None
        and restored.active is not None
        and restored.active.intent == full.active.intent
        and restored.active.status == full.active.status
        and len(restored.queue) == len(full.queue)
        and [p.intent for p in restored.queue] == [p.intent for p in full.queue]
    )
    record("pending_intents_json_round_trip", round_trip_ok, f"restored.queue={[p.intent for p in restored.queue]}")

    default_dumped = default.model_dump(mode="json")
    default_restored = PendingIntents.model_validate(default_dumped)
    default_round_trip = (
        default_restored.version == 1
        and default_restored.active is None
        and default_restored.queue == []
    )
    record("pending_intents_default_round_trip", default_round_trip, f"version={default_restored.version}")

    import json

    serializes_clean = True
    try:
        json.dumps(dumped)
    except (TypeError, ValueError):
        serializes_clean = False
    record("pending_intents_dump_is_json_serializable", serializes_clean, "json.dumps succeeded")

    import backend.intents.schemas.pending_intents as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "pending_intents_only_one_public_symbol",
        public_symbols == {"PendingIntents"},
        str(sorted(public_symbols)),
    )

    import pathlib

    schemas_dir = pathlib.Path(module.__file__).parent
    schema_files = {
        p.name for p in schemas_dir.iterdir() if p.is_file() and p.name != "__init__.py"
    }
    record(
        "pending_intents_schemas_package_files",
        schema_files
        == {
            "customer_response.py",
            "intent_classification.py",
            "pending_intents.py",
            "processed_intent.py",
            "requirement_state.py",
        },
        str(sorted(schema_files)),
    )


def test_processed_intent_schema() -> None:
    from typing import Any, cast

    from pydantic import ValidationError

    from backend.intents.schemas.processed_intent import IntentStatus, ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState

    state = RequirementState(name="cantidad", status="completed", value=3)
    full = ProcessedIntent(
        intent="agregar_producto",
        source_text="add 2 pizzas",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"cantidad": 2},
        requirements=[state],
        candidate_ids=[10, 11],
    )
    ok_full = (
        full.intent == "agregar_producto"
        and full.source_text == "add 2 pizzas"
        and full.status == "ready"
        and full.recognizer == "recognizer_productos"
        and full.handler == "agregar_producto"
        and full.resolved_data == {"cantidad": 2}
        and len(full.requirements) == 1
        and full.requirements[0].value == 3
        and full.candidate_ids == [10, 11]
    )
    record("processed_intent_valid_creation", ok_full, f"intent={full.intent} status={full.status}")

    minimal = ProcessedIntent(
        intent="agregar_producto",
        source_text="add",
        status="pending_resolution",
        handler="agregar_producto",
    )
    defaults_ok = (
        minimal.recognizer is None
        and minimal.resolved_data == {}
        and minimal.requirements == []
        and minimal.candidate_ids == []
    )
    record("processed_intent_default_empty_collections", defaults_ok, f"resolved_data={minimal.resolved_data}")

    a = ProcessedIntent(intent="x", source_text="x", status="pending_resolution", handler="x")
    b = ProcessedIntent(intent="x", source_text="x", status="pending_resolution", handler="x")
    a.resolved_data["k"] = "v"
    isolated = b.resolved_data == {}
    record("processed_intent_default_factory_isolation", isolated, f"a={a.resolved_data} b={b.resolved_data}")

    try:
        ProcessedIntent(
            intent="x",
            source_text="x",
            status="pending_resolution",
            handler="x",
            requirements=[RequirementState(name="x", status=cast(Any, "bad"))],
        )
        nested_rejected = False
    except ValidationError:
        nested_rejected = True
    record("processed_intent_nested_invalid_rejected", nested_rejected, "ValidationError raised")

    try:
        ProcessedIntent(
            intent="x",
            source_text="x",
            status=cast(Any, "unknown"),
            handler="x",
        )
        status_rejected = False
    except ValidationError:
        status_rejected = True
    record("processed_intent_invalid_status_rejected", status_rejected, "ValidationError raised")

    try:
        ProcessedIntent(
            **cast(Any, {"source_text": "x", "status": "pending_resolution", "handler": "x"}),
        )
        missing_intent = False
    except ValidationError:
        missing_intent = True
    record("processed_intent_missing_intent_rejected", missing_intent, "ValidationError raised")

    import backend.intents.schemas.processed_intent as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "processed_intent_only_two_public_symbols",
        public_symbols == {"IntentStatus", "ProcessedIntent"},
        str(sorted(public_symbols)),
    )

    import pathlib

    schemas_dir = pathlib.Path(module.__file__).parent
    schema_files = {
        p.name for p in schemas_dir.iterdir() if p.is_file() and p.name != "__init__.py"
    }
    record(
        "processed_intent_only_schema_file",
        schema_files
        == {
            "customer_response.py",
            "intent_classification.py",
            "pending_intents.py",
            "processed_intent.py",
            "requirement_state.py",
        },
        str(sorted(schema_files)),
    )


def test_requirement_state_schema() -> None:
    from typing import Any, cast

    from pydantic import ValidationError

    from backend.intents.schemas.requirement_state import RequirementState

    state = RequirementState(name="cantidad", status="pending", value=2)
    ok_valid = (
        state.name == "cantidad"
        and state.status == "pending"
        and state.value == 2
    )
    record("requirement_state_valid_creation", ok_valid, f"name={state.name} status={state.status} value={state.value}")

    for status in ("pending", "completed"):
        default_state = RequirementState(name="x", status=status)
        record(
            f"requirement_state_default_value_none_{status}",
            default_state.value is None,
            f"value={default_state.value}",
        )

    try:
        RequirementState(name="x", status=cast(Any, "unknown"))
        invalid_rejected = False
    except ValidationError:
        invalid_rejected = True
    record("requirement_state_rejects_invalid_status", invalid_rejected, "ValidationError raised")

    try:
        RequirementState(**cast(Any, {"status": "pending"}))
        missing_name_rejected = False
    except ValidationError:
        missing_name_rejected = True
    record("requirement_state_rejects_missing_name", missing_name_rejected, "ValidationError raised")

    try:
        RequirementState(name=cast(Any, 123), status="pending")
        wrong_type_rejected = False
    except ValidationError:
        wrong_type_rejected = True
    record("requirement_state_rejects_non_string_name", wrong_type_rejected, "ValidationError raised")

    import backend.intents.schemas.requirement_state as module

    public_symbols = set(getattr(module, "__all__", ()))
    record(
        "requirement_state_only_two_public_symbols",
        public_symbols == {"RequirementState", "RequirementStatus"},
        str(sorted(public_symbols)),
    )

    import pathlib

    schemas_dir = pathlib.Path(module.__file__).parent
    schema_files = {
        p.name for p in schemas_dir.iterdir() if p.is_file() and p.name != "__init__.py"
    }
    record(
        "requirement_state_only_schema_file",
        schema_files
        == {
            "customer_response.py",
            "intent_classification.py",
            "pending_intents.py",
            "processed_intent.py",
            "requirement_state.py",
        },
        str(sorted(schema_files)),
    )


def test_agregar_producto_contract_structure() -> None:
    from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT

    record(
        "agregar_producto_contract_is_dict",
        isinstance(AGREGAR_PRODUCTO_CONTRACT, dict),
        type(AGREGAR_PRODUCTO_CONTRACT).__name__,
    )
    record(
        "agregar_producto_contract_top_level_keys",
        set(AGREGAR_PRODUCTO_CONTRACT.keys())
        == {"intent", "recognizer", "handler", "requirements"},
        str(sorted(AGREGAR_PRODUCTO_CONTRACT.keys())),
    )
    record(
        "agregar_producto_contract_intent",
        AGREGAR_PRODUCTO_CONTRACT["intent"] == "agregar_producto",
        AGREGAR_PRODUCTO_CONTRACT["intent"],
    )
    record(
        "agregar_producto_contract_recognizer",
        AGREGAR_PRODUCTO_CONTRACT["recognizer"] == "recognizer_productos",
        AGREGAR_PRODUCTO_CONTRACT["recognizer"],
    )
    record(
        "agregar_producto_contract_handler",
        AGREGAR_PRODUCTO_CONTRACT["handler"] == "agregar_producto",
        AGREGAR_PRODUCTO_CONTRACT["handler"],
    )
    requirements = AGREGAR_PRODUCTO_CONTRACT["requirements"]
    record(
        "agregar_producto_contract_requirements_keys",
        set(requirements.keys()) == {"producto_presentacion_id", "cantidad"},
        str(sorted(requirements.keys())),
    )
    pp = requirements["producto_presentacion_id"]
    record(
        "agregar_producto_contract_pp_required",
        pp["required"] is True and pp["default"] is None,
        f"required={pp['required']} default={pp['default']}",
    )
    qty = requirements["cantidad"]
    record(
        "agregar_producto_contract_cantidad_required",
        qty["required"] is True and qty["default"] == 1,
        f"required={qty['required']} default={qty['default']}",
    )
    import backend.intents.contracts.agregar_producto as contract_module

    public_symbols = {n for n in dir(contract_module) if not n.startswith("_")}
    record(
        "agregar_producto_contract_only_public_symbol",
        public_symbols == {"AGREGAR_PRODUCTO_CONTRACT"},
        str(sorted(public_symbols)),
    )
    import pathlib

    contracts_dir = pathlib.Path(contract_module.__file__).parent
    contract_files = {
        p.name for p in contracts_dir.iterdir() if p.is_file() and p.name != "__init__.py"
    }
    record(
        "agregar_producto_contract_only_contract_file",
        contract_files == {"agregar_producto.py"},
        str(sorted(contract_files)),
    )


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(Cliente).where(Cliente.id == cliente_id))


def _existing_cliente_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM clientes ORDER BY id"))]


def _cliente_whatsapp_digits(suffix: str) -> str:
    return f"+54911{int(suffix, 16) % 100_000_000:08d}"


def _new_cliente_payload(**overrides) -> dict:
    suffix = _suffix()
    payload = {
        "whatsapp": f"+54911{suffix[:8]}",
        "nombre": f"Cliente {suffix}",
        "domicilio": f"Calle {suffix} 123",
    }
    payload.update(overrides)
    return payload


def test_cliente_create_normalizes_whatsapp() -> None:
    payload = _new_cliente_payload(whatsapp="+54 9 11 5555-1234")
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_create_normalizes", False, f"{response.status_code} {response.text}")
        return
    cliente_id = response.json()["id"]
    try:
        body = response.json()
        ok = (
            body["whatsapp"] == "+5491155551234"
            and body["nombre"] == payload["nombre"]
            and body["activo"] is True
            and body["created_at"]
            and body["updated_at"]
        )
        record("cliente_create_normalizes", ok, f"id={cliente_id} whatsapp={body['whatsapp']}")
    finally:
        _delete_cliente(cliente_id)


def test_cliente_create_duplicate_whatsapp_409() -> None:
    payload = _new_cliente_payload()
    r1 = client.post("/clientes", json=payload)
    if r1.status_code != 201:
        record("cliente_create_duplicate_409", False, f"setup: {r1.status_code} {r1.text}")
        return
    cliente_id = r1.json()["id"]
    try:
        duplicate = _new_cliente_payload(whatsapp=payload["whatsapp"], nombre="Otro")
        r2 = client.post("/clientes", json=duplicate)
        record(
            "cliente_create_duplicate_409",
            r2.status_code == 409,
            f"{r2.status_code}",
        )
        formatted = _new_cliente_payload(whatsapp="  +549 1155551234  ", nombre="Otro2")
        formatted["whatsapp"] = payload["whatsapp"].replace("+", "+ ")
        r3 = client.post("/clientes", json=formatted)
        record(
            "cliente_create_duplicate_normalized_409",
            r3.status_code == 409,
            f"{r3.status_code}",
        )
    finally:
        _delete_cliente(cliente_id)


def test_cliente_create_invalid_whatsapp_400() -> None:
    payload = _new_cliente_payload(whatsapp="not-a-phone")
    response = client.post("/clientes", json=payload)
    record(
        "cliente_create_empty_digits_400",
        response.status_code == 400,
        f"{response.status_code}",
    )


def test_cliente_get_by_id_and_whatsapp_roundtrip() -> None:
    payload = _new_cliente_payload()
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_get_by_id", False, f"setup: {response.status_code}")
        return
    cliente_id = response.json()["id"]
    canonical = response.json()["whatsapp"]
    try:
        r1 = client.get(f"/clientes/{cliente_id}")
        record(
            "cliente_get_by_id",
            r1.status_code == 200 and r1.json()["id"] == cliente_id,
            f"{r1.status_code}",
        )
        r2 = client.get(f"/clientes/whatsapp/{canonical}")
        record(
            "cliente_get_by_whatsapp",
            r2.status_code == 200 and r2.json()["id"] == cliente_id,
            f"{r2.status_code}",
        )
        r3 = client.get(f"/clientes/whatsapp/{'+54911000000' + _suffix()[:1]}")
        record("cliente_get_by_whatsapp_missing_404", r3.status_code == 404, f"{r3.status_code}")
        max_id = max(_existing_cliente_ids() or [0])
        r4 = client.get(f"/clientes/{max_id + 99999}")
        record("cliente_get_by_id_missing_404", r4.status_code == 404, f"{r4.status_code}")
    finally:
        _delete_cliente(cliente_id)


def test_cliente_update_mutates_subset_and_rejects_whatsapp() -> None:
    payload = _new_cliente_payload()
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_update", False, f"setup: {response.status_code}")
        return
    cliente_id = response.json()["id"]
    try:
        r1 = client.put(
            f"/clientes/{cliente_id}",
            json={"nombre": "Nuevo nombre", "domicilio": "Nueva dir 999"},
        )
        body = r1.json()
        record(
            "cliente_update_persists",
            r1.status_code == 200 and body["nombre"] == "Nuevo nombre" and body["domicilio"] == "Nueva dir 999",
            f"{r1.status_code}",
        )
        r2 = client.put(
            f"/clientes/{cliente_id}",
            json={"whatsapp": "+541111111111"},
        )
        record(
            "cliente_update_rejects_whatsapp_422",
            r2.status_code == 422,
            f"{r2.status_code}",
        )
        max_id = max(_existing_cliente_ids() or [0])
        r3 = client.put(f"/clientes/{max_id + 99999}", json={"nombre": "x"})
        record("cliente_update_missing_404", r3.status_code == 404, f"{r3.status_code}")
    finally:
        _delete_cliente(cliente_id)


def test_cliente_activate_deactivate() -> None:
    payload = _new_cliente_payload()
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_activate_deactivate", False, f"setup: {response.status_code}")
        return
    cliente_id = response.json()["id"]
    try:
        r1 = client.patch(f"/clientes/{cliente_id}/activo", json={"activo": False})
        record(
            "cliente_deactivate",
            r1.status_code == 200 and r1.json()["activo"] is False,
            f"{r1.status_code}",
        )
        r2 = client.patch(f"/clientes/{cliente_id}/activo", json={"activo": True})
        record(
            "cliente_activate",
            r2.status_code == 200 and r2.json()["activo"] is True,
            f"{r2.status_code}",
        )
        max_id = max(_existing_cliente_ids() or [0])
        r3 = client.patch(f"/clientes/{max_id + 99999}/activo", json={"activo": True})
        record("cliente_activo_missing_404", r3.status_code == 404, f"{r3.status_code}")
    finally:
        _delete_cliente(cliente_id)


def test_cliente_update_trims_strings_to_none() -> None:
    payload = _new_cliente_payload(nombre="   ", domicilio="   ")
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_trim_whitespace", False, f"setup: {response.status_code}")
        return
    cliente_id = response.json()["id"]
    try:
        body = response.json()
        record(
            "cliente_create_trims_whitespace",
            body["nombre"] is None and body["domicilio"] is None,
            f"nombre={body['nombre']} domicilio={body['domicilio']}",
        )
    finally:
        _delete_cliente(cliente_id)


def test_cliente_create_rejects_id_422() -> None:
    payload = {"id": 999999, **_new_cliente_payload()}
    response = client.post("/clientes", json=payload)
    record("cliente_create_rejects_id_422", response.status_code == 422, f"{response.status_code}")


def test_cliente_no_session_field() -> None:
    payload = _new_cliente_payload()
    response = client.post("/clientes", json=payload)
    if response.status_code != 201:
        record("cliente_no_session_field", False, f"setup: {response.status_code}")
        return
    cliente_id = response.json()["id"]
    try:
        body = response.json()
        record(
            "cliente_create_no_session_field",
            "session" not in body and "id_session" not in body,
            "no session keys",
        )
    finally:
        _delete_cliente(cliente_id)


def _delete_pedido(pedido_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        session_id = s.execute(
            text("SELECT id_session FROM pedidos WHERE id = :id"), {"id": pedido_id}
        ).scalar()
        if session_id is not None:
            s.execute(
                text("UPDATE sessions SET id_pedido = NULL WHERE id = :id"),
                {"id": session_id},
            )
        s.execute(delete(Pedido).where(Pedido.id == pedido_id))
        if session_id is not None:
            s.execute(delete(SessionModel).where(SessionModel.id == session_id))


def _existing_pedido_ids() -> list[int]:
    with engine.connect() as c:
        return [row[0] for row in c.execute(text("SELECT id FROM pedidos ORDER BY id"))]


def _new_session_id() -> int:
    """Create a fresh Cliente + Session and return the new session id."""
    comercio_id = _existing_comercio_ids()[0]
    cliente_response = client.post(
        "/clientes", json={"whatsapp": _cliente_whatsapp_digits(_suffix())}
    )
    if cliente_response.status_code != 201:
        raise RuntimeError(f"cliente setup failed: {cliente_response.status_code} {cliente_response.text}")
    cliente_id = cliente_response.json()["id"]
    session_response = client.post(
        "/sessions", json={"id_comercio": comercio_id, "id_cliente": cliente_id}
    )
    if session_response.status_code != 201:
        raise RuntimeError(f"session setup failed: {session_response.status_code} {session_response.text}")
    return session_response.json()["id"]


def _new_pedido() -> int:
    session_id = _new_session_id()
    response = client.post("/pedidos", json={"id_session": session_id})
    if response.status_code != 201:
        raise RuntimeError(f"setup failed: {response.status_code} {response.text}")
    return response.json()["id"]


def _pedido_estado(pedido_id: int) -> str | None:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT estado_pedido FROM pedidos WHERE id = :id"), {"id": pedido_id}
        ).first()
    return row[0] if row is not None else None


def _force_pedido_estado(pedido_id: int, estado: str) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(
            text("UPDATE pedidos SET estado_pedido = :estado WHERE id = :id"),
            {"estado": estado, "id": pedido_id},
        )


def test_pedido_create_defaults_to_borrador() -> None:
    session_id = _new_session_id()
    response = client.post("/pedidos", json={"id_session": session_id})
    if response.status_code != 201:
        record("pedido_create_defaults_borrador", False, f"{response.status_code} {response.text}")
        return
    pedido_id = response.json()["id"]
    try:
        body = response.json()
        ok = (
            body["estado_pedido"] == "borrador"
            and body["id_session"] == session_id
            and body["id_medio_pago"] is None
            and body["id_metodo_entrega"] is None
            and body["datetime_entrega_programada"] is None
        )
        record("pedido_create_defaults_borrador", ok, f"id={pedido_id} estado={body['estado_pedido']}")
        get_response = client.get(f"/pedidos/{pedido_id}")
        record(
            "pedido_get_after_create",
            get_response.status_code == 200 and get_response.json()["estado_pedido"] == "borrador",
            f"{get_response.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_create_with_known_fks() -> None:
    medio_pago_id = _existing_medio_pago_ids()[0] if _existing_medio_pago_ids() else None
    metodo_entrega_id = _existing_metodo_entrega_ids()[0] if _existing_metodo_entrega_ids() else None
    if medio_pago_id is None or metodo_entrega_id is None:
        record("pedido_create_with_known_fks", False, "requires seeded catalogs")
        return
    session_id = _new_session_id()
    payload = {
        "id_session": session_id,
        "id_medio_pago": medio_pago_id,
        "id_metodo_entrega": metodo_entrega_id,
        "datetime_entrega_programada": "2026-08-01T10:00:00+00:00",
    }
    response = client.post("/pedidos", json=payload)
    if response.status_code != 201:
        record("pedido_create_with_known_fks", False, f"{response.status_code} {response.text}")
        return
    pedido_id = response.json()["id"]
    try:
        body = response.json()
        ok = (
            body["id_medio_pago"] == medio_pago_id
            and body["id_metodo_entrega"] == metodo_entrega_id
            and body["datetime_entrega_programada"].startswith("2026-08-01")
            and body["estado_pedido"] == "borrador"
            and body["id_session"] == session_id
        )
        record("pedido_create_with_known_fks", ok, f"id={pedido_id}")
    finally:
        _delete_pedido(pedido_id)


def test_pedido_create_missing_id_session_422() -> None:
    response = client.post("/pedidos", json={})
    record("pedido_create_missing_id_session_422", response.status_code == 422, f"{response.status_code}")


def test_pedido_create_non_existent_id_session_404() -> None:
    missing_session = 999999
    response = client.post("/pedidos", json={"id_session": missing_session})
    record("pedido_create_non_existent_session_404", response.status_code == 404, f"{response.status_code}")


def test_pedido_create_closed_id_session_409() -> None:
    session_id = _new_session_id()
    close = client.post(f"/sessions/{session_id}/cerrar")
    if close.status_code != 200:
        record("pedido_create_closed_session_409", False, f"setup: {close.status_code}")
        return
    response = client.post("/pedidos", json={"id_session": session_id})
    record("pedido_create_closed_session_409", response.status_code == 409, f"{response.status_code}")


def test_pedido_create_unknown_fk_returns_400_no_row() -> None:
    missing_fk = 999999
    session_id = _new_session_id()
    before = max(_existing_pedido_ids() or [0])
    cases = [
        ("unknown_medio_pago", {"id_session": session_id, "id_medio_pago": missing_fk}),
        ("unknown_metodo_entrega", {"id_session": session_id, "id_metodo_entrega": missing_fk}),
    ]
    for name, body in cases:
        response = client.post("/pedidos", json=body)
        after = max(_existing_pedido_ids() or [0])
        record(
            f"pedido_create_{name}_400",
            response.status_code == 400 and after == before,
            f"{response.status_code} count_delta={after - before}",
        )


def test_pedido_get_missing_404() -> None:
    max_id = max(_existing_pedido_ids() or [0])
    response = client.get(f"/pedidos/{max_id + 99999}")
    record("pedido_get_missing_404", response.status_code == 404, f"{response.status_code}")


def test_pedido_updates_in_borrador_succeed() -> None:
    pedido_id = _new_pedido()
    medio_pago_id = _existing_medio_pago_ids()[0]
    metodo_entrega_id = _existing_metodo_entrega_ids()[0]
    try:
        r1 = client.put(
            f"/pedidos/{pedido_id}/medio-pago", json={"id_medio_pago": medio_pago_id}
        )
        record(
            "pedido_set_medio_pago_in_borrador",
            r1.status_code == 200 and r1.json()["id_medio_pago"] == medio_pago_id,
            f"{r1.status_code}",
        )
        r2 = client.put(
            f"/pedidos/{pedido_id}/metodo-entrega",
            json={"id_metodo_entrega": metodo_entrega_id},
        )
        record(
            "pedido_set_metodo_entrega_in_borrador",
            r2.status_code == 200 and r2.json()["id_metodo_entrega"] == metodo_entrega_id,
            f"{r2.status_code}",
        )
        r3 = client.put(
            f"/pedidos/{pedido_id}/fecha-entrega",
            json={"datetime_entrega_programada": "2026-09-01T15:30:00+00:00"},
        )
        record(
            "pedido_set_fecha_entrega_in_borrador",
            r3.status_code == 200 and r3.json()["datetime_entrega_programada"].startswith("2026-09-01"),
            f"{r3.status_code}",
        )
        r4 = client.put(
            f"/pedidos/{pedido_id}/fecha-entrega", json={"datetime_entrega_programada": None}
        )
        record(
            "pedido_set_fecha_entrega_clears",
            r4.status_code == 200 and r4.json()["datetime_entrega_programada"] is None,
            f"{r4.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_update_unknown_fk_returns_400() -> None:
    pedido_id = _new_pedido()
    try:
        r1 = client.put(
            f"/pedidos/{pedido_id}/medio-pago", json={"id_medio_pago": 999999}
        )
        record("pedido_set_medio_pago_unknown_400", r1.status_code == 400, f"{r1.status_code}")
        r2 = client.put(
            f"/pedidos/{pedido_id}/metodo-entrega", json={"id_metodo_entrega": 999999}
        )
        record(
            "pedido_set_metodo_entrega_unknown_400", r2.status_code == 400, f"{r2.status_code}"
        )
        after = _pedido_estado(pedido_id)
        record("pedido_update_unknown_fk_unchanged", after == "borrador", f"estado={after}")
    finally:
        _delete_pedido(pedido_id)


def test_pedido_updates_outside_borrador_409() -> None:
    pedido_id = _new_pedido()
    _force_pedido_estado(pedido_id, "ingresado")
    medio_pago_id = _existing_medio_pago_ids()[0]
    try:
        r1 = client.put(
            f"/pedidos/{pedido_id}/medio-pago", json={"id_medio_pago": medio_pago_id}
        )
        record(
            "pedido_set_medio_pago_outside_borrador_409",
            r1.status_code == 409,
            f"{r1.status_code}",
        )
        r2 = client.put(
            f"/pedidos/{pedido_id}/metodo-entrega", json={"id_metodo_entrega": _existing_metodo_entrega_ids()[0]}
        )
        record(
            "pedido_set_metodo_entrega_outside_borrador_409",
            r2.status_code == 409,
            f"{r2.status_code}",
        )
        r3 = client.put(
            f"/pedidos/{pedido_id}/fecha-entrega",
            json={"datetime_entrega_programada": "2026-10-01T00:00:00+00:00"},
        )
        record(
            "pedido_set_fecha_entrega_outside_borrador_409",
            r3.status_code == 409,
            f"{r3.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_state_transitions() -> None:
    pedido_id = _new_pedido()
    try:
        r1 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "ingresado"})
        record(
            "pedido_transition_borrador_ingresado",
            r1.status_code == 200 and r1.json()["estado_pedido"] == "ingresado",
            f"{r1.status_code}",
        )
        r2 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "preparacion"})
        record(
            "pedido_transition_ingresado_preparacion",
            r2.status_code == 200 and r2.json()["estado_pedido"] == "preparacion",
            f"{r2.status_code}",
        )
        r3 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "terminado"})
        record(
            "pedido_transition_preparacion_terminado",
            r3.status_code == 200 and r3.json()["estado_pedido"] == "terminado",
            f"{r3.status_code}",
        )
        r4 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "entregado"})
        record(
            "pedido_transition_terminado_entregado",
            r4.status_code == 200 and r4.json()["estado_pedido"] == "entregado",
            f"{r4.status_code}",
        )
        r5 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "cancelado"})
        record(
            "pedido_transition_entregado_cancelado_409",
            r5.status_code == 409,
            f"{r5.status_code}",
        )
        after = _pedido_estado(pedido_id)
        record(
            "pedido_transition_entregado_unchanged", after == "entregado", f"estado={after}"
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_forbidden_transition_409() -> None:
    pedido_id = _new_pedido()
    try:
        r1 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "terminado"})
        record("pedido_forbidden_borrador_terminado_409", r1.status_code == 409, f"{r1.status_code}")
        r2 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "entregado"})
        record("pedido_forbidden_borrador_entregado_409", r2.status_code == 409, f"{r2.status_code}")
        r3 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "borrador"})
        record("pedido_self_transition_409", r3.status_code == 409, f"{r3.status_code}")
        r4 = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "no_existe"})
        record("pedido_invalid_estado_400", r4.status_code == 400, f"{r4.status_code}")
    finally:
        _delete_pedido(pedido_id)


def test_pedido_cancel_from_working_states() -> None:
    for source_state in ("borrador", "ingresado", "preparacion"):
        pedido_id = _new_pedido()
        if source_state != "borrador":
            _force_pedido_estado(pedido_id, source_state)
        try:
            r = client.put(f"/pedidos/{pedido_id}/estado", json={"estado_pedido": "cancelado"})
            record(
                f"pedido_cancel_from_{source_state}",
                r.status_code == 200 and r.json()["estado_pedido"] == "cancelado",
                f"{r.status_code}",
            )
        finally:
            _delete_pedido(pedido_id)


def test_pedido_update_missing_404() -> None:
    max_id = max(_existing_pedido_ids() or [0])
    missing = max_id + 99999
    cases = [
        ("medio_pago", client.put(f"/pedidos/{missing}/medio-pago", json={"id_medio_pago": None})),
        ("metodo_entrega", client.put(f"/pedidos/{missing}/metodo-entrega", json={"id_metodo_entrega": None})),
        ("fecha_entrega", client.put(f"/pedidos/{missing}/fecha-entrega", json={"datetime_entrega_programada": None})),
        ("estado", client.put(f"/pedidos/{missing}/estado", json={"estado_pedido": "ingresado"})),
    ]
    for name, response in cases:
        record(f"pedido_update_{name}_404", response.status_code == 404, f"{response.status_code}")


def test_pedido_relationship_attributes_exist() -> None:
    with TestingSessionLocal() as session:
        pedido = session.get(Pedido, _new_pedido())
        try:
            assert pedido is not None
            record(
                "pedido_has_medio_pago_relationship",
                hasattr(pedido, "medio_pago"),
                "attribute present",
            )
            record(
                "pedido_has_metodo_entrega_relationship",
                hasattr(pedido, "metodo_entrega"),
                "attribute present",
            )
            body = client.get(f"/pedidos/{pedido.id}").json()
            record(
                "pedido_response_excludes_catalog_objects",
                "medio_pago" not in body or not isinstance(body.get("medio_pago"), dict),
                "scalar response",
            )
        finally:
            session.delete(pedido)
            session.commit()


def _delete_session(session_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(SessionModel).where(SessionModel.id == session_id))


def _delete_cliente_force(cliente_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(Cliente).where(Cliente.id == cliente_id))


def _new_session_via_api(comercio_id: int, cliente_id: int) -> int:
    response = client.post(
        "/sessions", json={"id_comercio": comercio_id, "id_cliente": cliente_id}
    )
    if response.status_code != 201:
        raise RuntimeError(f"session setup failed: {response.status_code} {response.text}")
    return response.json()["id"]


def _new_cliente_via_api() -> int:
    suffix = _suffix()
    whatsapp = f"+54911{int(suffix, 16) % 100_000_000:08d}"
    response = client.post("/clientes", json={"whatsapp": whatsapp})
    if response.status_code != 201:
        raise RuntimeError(f"cliente setup failed: {response.status_code} {response.text}")
    return response.json()["id"]


def test_session_create_defaults_to_activa() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        response = client.post(
            "/sessions", json={"id_comercio": comercio_id, "id_cliente": cliente_id}
        )
        if response.status_code != 201:
            record("session_create_defaults_activa", False, f"{response.status_code} {response.text}")
            return
        session_id = response.json()["id"]
        try:
            body = response.json()
            ok = (
                body["estado_session"] == "activa"
                and body["id_pedido"] is None
                and body["id_comercio"] == comercio_id
                and body["id_cliente"] == cliente_id
                and body["datetime_inicio"]
                and body["datetime_ultimo_movimiento"]
            )
            record("session_create_defaults_activa", ok, f"id={session_id} estado={body['estado_session']}")
        finally:
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_create_without_pedido() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        response = client.post(
            "/sessions", json={"id_comercio": comercio_id, "id_cliente": cliente_id}
        )
        if response.status_code != 201:
            record("session_create_without_pedido", False, f"setup: {response.status_code}")
            return
        session_id = response.json()["id"]
        try:
            record(
                "session_create_without_pedido",
                response.json()["id_pedido"] is None,
                f"id_pedido={response.json()['id_pedido']}",
            )
        finally:
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_duplicate_active_409() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        first = _new_session_via_api(comercio_id, cliente_id)
        try:
            second = client.post(
                "/sessions", json={"id_comercio": comercio_id, "id_cliente": cliente_id}
            )
            record(
                "session_duplicate_active_409",
                second.status_code == 409,
                f"{second.status_code}",
            )
        finally:
            _delete_session(first)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_get_by_id_and_active() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        session_id = _new_session_via_api(comercio_id, cliente_id)
        try:
            r1 = client.get(f"/sessions/{session_id}")
            record(
                "session_get_by_id",
                r1.status_code == 200 and r1.json()["id"] == session_id,
                f"{r1.status_code}",
            )
            r2 = client.get(
                f"/sessions/comercios/{comercio_id}/clientes/{cliente_id}/activa"
            )
            record(
                "session_get_active",
                r2.status_code == 200 and r2.json()["id"] == session_id,
                f"{r2.status_code}",
            )
            r3 = client.get(f"/sessions/{session_id + 99999}")
            record("session_get_by_id_missing_404", r3.status_code == 404, f"{r3.status_code}")
        finally:
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_update_movimiento_bumps_timestamp() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        session_id = _new_session_via_api(comercio_id, cliente_id)
        try:
            r1 = client.patch(f"/sessions/{session_id}/movimiento")
            ok = r1.status_code == 200 and r1.json()["datetime_ultimo_movimiento"] is not None
            record("session_update_movimiento_activa", ok, f"{r1.status_code}")
            close = client.post(f"/sessions/{session_id}/cerrar")
            if close.status_code != 200:
                record("session_update_movimiento_cerrada_409", False, f"setup: {close.status_code}")
                return
            r2 = client.patch(f"/sessions/{session_id}/movimiento")
            record("session_update_movimiento_cerrada_409", r2.status_code == 409, f"{r2.status_code}")
            r3 = client.patch(f"/sessions/{session_id + 99999}/movimiento")
            record("session_update_movimiento_missing_404", r3.status_code == 404, f"{r3.status_code}")
        finally:
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_close_active_and_rejects_already_closed() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        session_id = _new_session_via_api(comercio_id, cliente_id)
        try:
            r1 = client.post(f"/sessions/{session_id}/cerrar")
            record(
                "session_close_active",
                r1.status_code == 200 and r1.json()["estado_session"] == "cerrada",
                f"{r1.status_code}",
            )
            r2 = client.post(f"/sessions/{session_id}/cerrar")
            record("session_close_already_closed_409", r2.status_code == 409, f"{r2.status_code}")
            r3 = client.post(f"/sessions/{session_id + 99999}/cerrar")
            record("session_close_missing_404", r3.status_code == 404, f"{r3.status_code}")
        finally:
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def test_session_asociar_pedido_succeeds_and_validates() -> None:
    comercio_id = _existing_comercio_ids()[0]
    cliente_id = _new_cliente_via_api()
    try:
        session_id = _new_session_via_api(comercio_id, cliente_id)
        pedido_response = client.post("/pedidos", json={"id_session": session_id})
        if pedido_response.status_code != 201:
            record("session_asociar_pedido_succeeds", False, f"pedido setup: {pedido_response.status_code}")
            return
        pedido_id = pedido_response.json()["id"]
        try:
            r1 = client.put(
                f"/sessions/{session_id}/pedido", json={"id_pedido": pedido_id}
            )
            ok = r1.status_code == 200 and r1.json()["id_pedido"] == pedido_id
            record("session_asociar_pedido_succeeds", ok, f"{r1.status_code}")
            r2 = client.put(
                f"/sessions/{session_id}/pedido", json={"id_pedido": 999999}
            )
            record("session_asociar_pedido_missing_404", r2.status_code == 404, f"{r2.status_code}")
            close = client.post(f"/sessions/{session_id}/cerrar")
            if close.status_code != 200:
                return
            r3 = client.put(
                f"/sessions/{session_id}/pedido", json={"id_pedido": pedido_id}
            )
            record("session_asociar_pedido_cerrada_409", r3.status_code == 409, f"{r3.status_code}")
        finally:
            _delete_pedido(pedido_id)
            _delete_session(session_id)
    finally:
        _delete_cliente_force(cliente_id)


def _delete_pedido_producto(item_id: int) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(delete(PedidoProducto).where(PedidoProducto.id == item_id))


def _force_pedido_estado_orm(pedido_id: int, estado: str) -> None:
    with TestingSessionLocal() as s, s.begin():
        s.execute(
            text("UPDATE pedidos SET estado_pedido = :estado WHERE id = :id"),
            {"estado": estado, "id": pedido_id},
        )


def test_pedido_producto_create_snapshots_price_and_quantity_validated() -> None:
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_create_snapshots", False, "requires priced producto")
        return
    pp_id, _, _ = association
    pedido_id = _new_pedido()
    try:
        with engine.connect() as connection:
            current_precio = connection.execute(
                text("SELECT precio FROM producto_precios WHERE id_producto_presentacion = :id"),
                {"id": pp_id},
            ).scalar()
        response = client.post(
            f"/pedidos/{pedido_id}/productos",
            json={"id_producto_presentacion": pp_id, "cantidad": 2, "observaciones": "extra queso"},
        )
        if response.status_code != 201:
            record("pedido_producto_create_snapshots", False, f"{response.status_code} {response.text}")
            return
        item_id = response.json()["id"]
        try:
            body = response.json()
            ok = (
                body["id_pedido"] == pedido_id
                and body["id_producto_presentacion"] == pp_id
                and body["cantidad"] == 2
                and Decimal(str(body["precio_unitario"])) == Decimal(str(current_precio))
                and body["observaciones"] == "extra queso"
            )
            record("pedido_producto_create_snapshots", ok, f"id={item_id} precio={body['precio_unitario']}")
        finally:
            _delete_pedido_producto(item_id)
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_rejects_precio_unitario_in_body() -> None:
    pedido_id = _new_pedido()
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_rejects_precio_unitario", False, "requires priced producto")
        return
    pp_id, _, _ = association
    try:
        response = client.post(
            f"/pedidos/{pedido_id}/productos",
            json={
                "id_producto_presentacion": pp_id,
                "cantidad": 1,
                "precio_unitario": "999.99",
            },
        )
        record(
            "pedido_producto_rejects_precio_unitario",
            response.status_code == 422,
            f"{response.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_rejects_nonexistent_pedido() -> None:
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_rejects_missing_pedido_404", False, "requires priced producto")
        return
    pp_id, _, _ = association
    max_id = max(_existing_pedido_ids() or [0])
    response = client.post(
        f"/pedidos/{max_id + 99999}/productos",
        json={"id_producto_presentacion": pp_id, "cantidad": 1},
    )
    record(
        "pedido_producto_rejects_missing_pedido_404",
        response.status_code == 404,
        f"{response.status_code}",
    )


def test_pedido_producto_rejects_nonexistent_producto_presentacion() -> None:
    pedido_id = _new_pedido()
    try:
        response = client.post(
            f"/pedidos/{pedido_id}/productos",
            json={"id_producto_presentacion": 999999, "cantidad": 1},
        )
        record(
            "pedido_producto_rejects_missing_pp_404",
            response.status_code == 404,
            f"{response.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_rejects_zero_quantity() -> None:
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_rejects_zero_qty_422", False, "requires priced producto")
        return
    pp_id, _, _ = association
    pedido_id = _new_pedido()
    try:
        for qty in (0, -1):
            response = client.post(
                f"/pedidos/{pedido_id}/productos",
                json={"id_producto_presentacion": pp_id, "cantidad": qty},
            )
            record(
                f"pedido_producto_rejects_qty_{qty}_422",
                response.status_code == 422,
                f"{response.status_code}",
            )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_rejects_add_when_pedido_not_borrador() -> None:
    pedido_id = _new_pedido()
    _force_pedido_estado_orm(pedido_id, "ingresado")
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_rejects_add_not_borrador_409", False, "requires priced producto")
        return
    pp_id, _, _ = association
    try:
        response = client.post(
            f"/pedidos/{pedido_id}/productos",
            json={"id_producto_presentacion": pp_id, "cantidad": 1},
        )
        record(
            "pedido_producto_rejects_add_not_borrador_409",
            response.status_code == 409,
            f"{response.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_list_get_update_delete_in_borrador() -> None:
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_lifecycle", False, "requires priced producto")
        return
    pp_id, _, _ = association
    pedido_id = _new_pedido()
    try:
        r1 = client.post(
            f"/pedidos/{pedido_id}/productos",
            json={"id_producto_presentacion": pp_id, "cantidad": 1},
        )
        if r1.status_code != 201:
            record("pedido_producto_lifecycle", False, f"setup: {r1.status_code} {r1.text}")
            return
        item_id = r1.json()["id"]
        r2 = client.get(f"/pedidos/{pedido_id}/productos")
        record(
            "pedido_producto_list_by_pedido",
            r2.status_code == 200 and any(i["id"] == item_id for i in r2.json()),
            f"{r2.status_code}",
        )
        r3 = client.get(f"/pedidos-productos/{item_id}")
        record(
            "pedido_producto_get_by_id",
            r3.status_code == 200 and r3.json()["id"] == item_id,
            f"{r3.status_code}",
        )
        r4 = client.put(
            f"/pedidos-productos/{item_id}",
            json={"cantidad": 3, "observaciones": "sin sal"},
        )
        record(
            "pedido_producto_update",
            r4.status_code == 200
            and r4.json()["cantidad"] == 3
            and r4.json()["observaciones"] == "sin sal",
            f"{r4.status_code}",
        )
        r5 = client.put(
            f"/pedidos-productos/{item_id}", json={"precio_unitario": "1.00"}
        )
        record(
            "pedido_producto_update_rejects_precio_422",
            r5.status_code == 422,
            f"{r5.status_code}",
        )
        r6 = client.delete(f"/pedidos-productos/{item_id}")
        record("pedido_producto_delete", r6.status_code == 204, f"{r6.status_code}")
        r7 = client.get(f"/pedidos-productos/{item_id}")
        record(
            "pedido_producto_get_after_delete_404",
            r7.status_code == 404,
            f"{r7.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_rejects_update_when_pedido_not_borrador() -> None:
    association = _first_priced_association()
    if association is None:
        record("pedido_producto_update_not_borrador_409", False, "requires priced producto")
        return
    pp_id, _, _ = association
    pedido_id = _new_pedido()
    r1 = client.post(
        f"/pedidos/{pedido_id}/productos",
        json={"id_producto_presentacion": pp_id, "cantidad": 1},
    )
    if r1.status_code != 201:
        record("pedido_producto_update_not_borrador_409", False, f"setup: {r1.status_code}")
        return
    item_id = r1.json()["id"]
    _force_pedido_estado_orm(pedido_id, "preparacion")
    try:
        r2 = client.put(
            f"/pedidos-productos/{item_id}", json={"cantidad": 5}
        )
        record(
            "pedido_producto_update_not_borrador_409",
            r2.status_code == 409,
            f"{r2.status_code}",
        )
        r3 = client.delete(f"/pedidos-productos/{item_id}")
        record(
            "pedido_producto_delete_not_borrador_409",
            r3.status_code == 409,
            f"{r3.status_code}",
        )
    finally:
        _force_pedido_estado_orm(pedido_id, "borrador")
        _delete_pedido(pedido_id)


def test_pedido_producto_list_empty() -> None:
    pedido_id = _new_pedido()
    try:
        r1 = client.get(f"/pedidos/{pedido_id}/productos")
        record(
            "pedido_producto_list_empty",
            r1.status_code == 200 and r1.json() == [],
            f"{r1.status_code}",
        )
    finally:
        _delete_pedido(pedido_id)


def test_pedido_producto_missing_404() -> None:
    r1 = client.get("/pedidos-productos/999999")
    r2 = client.put("/pedidos-productos/999999", json={"cantidad": 1})
    r3 = client.delete("/pedidos-productos/999999")
    for name, response in (("get_404", r1), ("update_404", r2), ("delete_404", r3)):
        record(
            f"pedido_producto_{name}",
            response.status_code == 404,
            f"{response.status_code}",
        )


def test_agregar_producto_orchestrator() -> None:
    from unittest.mock import MagicMock, patch

    from backend.intents.orchestration.agregar_producto_orchestrator import (
        process_initial_agregar_producto,
    )
    from backend.intents.schemas.processed_intent import ProcessedIntent

    session = MagicMock(id_comercio=1, pending_intents={}, context_type=None)
    db = MagicMock()
    catalog = [{"producto_presentacion_id": 42}]
    found = {
        "encontrados": [{"producto_presentacion_id": 42, "cantidad": 2}],
        "encontrados_posibles": [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [],
    }
    with patch(
        "backend.services.producto_query_service.ProductoQueryService.list_recognizer_catalog",
        return_value=catalog,
    ), patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.detectar_productos",
        return_value=found,
    ) as recognizer, patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.set_pending_intent"
    ) as set_pending, patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.execute_agregar_producto"
    ) as execute_handler:
        executed = execute_handler.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 42, "cantidad": 2},
        )
        ready = process_initial_agregar_producto(db, session, "pizza")
    record(
        "agregar_producto_orchestrator_exact_ready",
        isinstance(ready, ProcessedIntent)
        and ready.status == "executed"
        and ready.resolved_data == {"producto_presentacion_id": 42, "cantidad": 2}
        and recognizer.called
        and execute_handler.called
        and not set_pending.called
        and not db.commit.called
        and not db.rollback.called,
        f"status={ready.status} resolved_data={ready.resolved_data}",
    )

    ambiguous = {
        "encontrados": [],
        "encontrados_posibles": [
            {"producto_presentacion_id": 42, "cantidad": 2},
            {"producto_presentacion_id": 43},
        ],
        "encontrados_no_disponibles": [],
        "no_encontrados": [],
    }
    with patch(
        "backend.services.producto_query_service.ProductoQueryService.list_recognizer_catalog",
        return_value=catalog,
    ), patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.detectar_productos",
        return_value=ambiguous,
    ), patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.set_pending_intent"
    ) as set_pending:
        pending = process_initial_agregar_producto(db, session, "pizza")
    record(
        "agregar_producto_orchestrator_pending_context",
        pending.status == "pending_resolution"
        and pending.candidate_ids == [42, 43]
        and set_pending.called
        and pending is set_pending.call_args.args[1]
        and session.context_type is None,
        f"status={pending.status} candidates={pending.candidate_ids}",
    )

    empty = {
        "encontrados": [],
        "encontrados_posibles": [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [{"texto_origen": "misteriosa"}],
    }
    session.pending_intents = {}
    with patch(
        "backend.services.producto_query_service.ProductoQueryService.list_recognizer_catalog",
        return_value=catalog,
    ), patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.detectar_productos",
        return_value=empty,
    ), patch(
        "backend.intents.orchestration.agregar_producto_orchestrator.set_pending_intent"
    ) as set_pending:
        unknown = process_initial_agregar_producto(db, session, "misteriosa")
    record(
        "agregar_producto_orchestrator_invalid_pending_not_stored",
        unknown.status == "pending_resolution"
        and not set_pending.called
        and session.pending_intents == {},
        f"status={unknown.status} pending={session.pending_intents}",
    )


def test_agregar_producto_handler() -> None:
    from unittest.mock import MagicMock, patch

    from backend.intents.handlers.agregar_producto_handler import execute_agregar_producto
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState

    intent = ProcessedIntent(
        intent="agregar_producto",
        source_text="pizza grande",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"producto_presentacion_id": 42, "cantidad": 2},
        requirements=[
            RequirementState(name="producto_presentacion_id", status="completed", value=42),
            RequirementState(name="cantidad", status="completed", value=2),
        ],
        candidate_ids=[],
    )
    conversation_session = MagicMock(id_pedido=7, pending_intents={"active": "keep"}, context_type="product_selection")
    db = MagicMock()
    fake_row = MagicMock(id=99, cantidad=2)
    with patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
    ) as mock_repo_cls, patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
    ) as mock_service_cls:
        mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
        mock_service_cls.return_value.add_or_increment.return_value = fake_row
        executed = execute_agregar_producto(db, conversation_session, intent)
    record(
        "agregar_producto_handler_executes_ready_intent",
        executed.status == "executed"
        and executed.resolved_data.get("producto_presentacion_id") == 42
        and executed.resolved_data.get("cantidad") == 2
        and executed.resolved_data.get("cantidad_agregada") == 2
        and executed.resolved_data.get("cantidad_final") == 2
        and executed.resolved_data.get("linea_creada") is True
        and conversation_session.pending_intents == {"active": "keep"}
        and conversation_session.context_type == "product_selection"
        and mock_service_cls.return_value.add_or_increment.call_args.args == (7, 42, 2, None)
        and not db.commit.called
        and not db.rollback.called,
        f"status={executed.status} args={mock_service_cls.return_value.add_or_increment.call_args.args}",
    )

    invalid = intent.model_copy(update={"resolved_data": {"cantidad": 0}})
    with patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
    ) as mock_repo_cls, patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
    ) as mock_service_cls:
        mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
        rejected = execute_agregar_producto(db, conversation_session, invalid)
    record(
        "agregar_producto_handler_rejects_invalid_quantity",
        rejected.status == "rejected" and not mock_service_cls.called,
        f"status={rejected.status}",
    )

    wrong_intent = intent.model_copy(update={"intent": "otro_intent"})
    with patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
    ) as mock_repo_cls, patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
    ) as mock_service_cls:
        mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
        rejected_wrong = execute_agregar_producto(db, conversation_session, wrong_intent)
    record(
        "agregar_producto_handler_rejects_wrong_intent",
        rejected_wrong.status == "rejected" and not mock_service_cls.called,
        f"status={rejected_wrong.status}",
    )

    no_pedido = MagicMock(id_pedido=None, pending_intents={}, context_type=None)
    with patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
    ) as mock_repo_cls, patch(
        "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
    ) as mock_service_cls:
        mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
        rejected_no_pedido = execute_agregar_producto(db, no_pedido, intent)
    record(
        "agregar_producto_handler_rejects_missing_pedido",
        rejected_no_pedido.status == "rejected" and not mock_service_cls.called,
        f"status={rejected_no_pedido.status}",
    )

    import pathlib
    import backend.intents.handlers.agregar_producto_handler as module

    source = pathlib.Path(module.__file__).read_text()
    record(
        "agregar_producto_handler_public_surface_and_no_sql",
        set(module.__all__) == {"execute_agregar_producto"}
        and "from sqlalchemy import" not in source
        and "HTTPException" not in source,
        str(module.__all__),
    )


def test_pending_context_execution() -> None:
    from unittest.mock import MagicMock, patch

    from backend.intents.orchestration.pending_context_execution import (
        execute_ready_pending_context,
    )
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState

    base_requirements = [
        RequirementState(name="producto_presentacion_id", status="completed", value=42),
        RequirementState(name="cantidad", status="completed", value=2),
    ]
    active_ready = ProcessedIntent(
        intent="agregar_producto",
        source_text="pizza grande",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"producto_presentacion_id": 42, "cantidad": 2},
        requirements=base_requirements,
        candidate_ids=[],
    )

    class FakeState:
        def __init__(self, active=None, queue=None):
            self.active = active
            self.queue = queue or []

    session = MagicMock(pending_intents={}, context_type="product_selection")

    with patch(
        "backend.intents.orchestration.pending_context_execution.load_pending_state",
        return_value=FakeState(active=active_ready),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.execute_agregar_producto",
        return_value=active_ready.model_copy(update={"status": "executed"}),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.clear_pending_context"
    ) as clear:
        executed = execute_ready_pending_context(MagicMock(), session)
    record(
        "pending_context_execution_executes_and_clears",
        executed.status == "executed"
        and clear.called
        and session.pending_intents == {}
        and session.context_type is None,
        f"status={executed.status} pending={session.pending_intents} ctx={session.context_type}",
    )

    rejected = active_ready.model_copy(update={"status": "rejected"})
    with patch(
        "backend.intents.orchestration.pending_context_execution.load_pending_state",
        return_value=FakeState(active=active_ready),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.execute_agregar_producto",
        return_value=rejected,
    ), patch(
        "backend.intents.orchestration.pending_context_execution.clear_pending_context"
    ) as clear:
        rejected_result = execute_ready_pending_context(MagicMock(), session)
    record(
        "pending_context_execution_clears_context_on_rejected",
        rejected_result.status == "rejected"
        and clear.called
        and session.pending_intents == {}
        and session.context_type is None,
        f"status={rejected_result.status} cleared={clear.called} ctx={session.context_type}",
    )

    pending_active = active_ready.model_copy(update={"status": "pending_resolution"})
    with patch(
        "backend.intents.orchestration.pending_context_execution.load_pending_state",
        return_value=FakeState(active=pending_active),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.execute_agregar_producto"
    ) as handler, patch(
        "backend.intents.orchestration.pending_context_execution.clear_pending_context"
    ) as clear:
        non_ready = execute_ready_pending_context(MagicMock(), session)
    record(
        "pending_context_execution_rejects_non_ready",
        non_ready.status == "rejected"
        and not handler.called
        and not clear.called,
        f"status={non_ready.status}",
    )

    with patch(
        "backend.intents.orchestration.pending_context_execution.load_pending_state",
        return_value=FakeState(active=None),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.execute_agregar_producto"
    ) as handler, patch(
        "backend.intents.orchestration.pending_context_execution.clear_pending_context"
    ) as clear:
        missing = execute_ready_pending_context(MagicMock(), session)
    record(
        "pending_context_execution_rejects_missing_active",
        missing.status == "rejected"
        and not handler.called
        and not clear.called,
        f"status={missing.status}",
    )

    unsupported = active_ready.model_copy(update={"handler": "cerrar_pedido"})
    with patch(
        "backend.intents.orchestration.pending_context_execution.load_pending_state",
        return_value=FakeState(active=unsupported),
    ), patch(
        "backend.intents.orchestration.pending_context_execution.execute_agregar_producto"
    ) as handler, patch(
        "backend.intents.orchestration.pending_context_execution.clear_pending_context"
    ) as clear:
        bad_handler = execute_ready_pending_context(MagicMock(), session)
    record(
        "pending_context_execution_rejects_unsupported_handler",
        bad_handler.status == "rejected"
        and not handler.called
        and not clear.called,
        f"status={bad_handler.status}",
    )

    import pathlib
    import backend.intents.orchestration.pending_context_execution as module

    source = pathlib.Path(module.__file__).read_text()
    record(
        "pending_context_execution_public_surface_and_no_sql",
        set(module.__all__) == {"execute_ready_pending_context"}
        and "from sqlalchemy import" not in source
        and "HTTPException" not in source,
        str(module.__all__),
    )


def test_pending_context_dispatcher() -> None:
    from unittest.mock import MagicMock, patch

    from backend.intents.orchestration.pending_context_dispatcher import (
        dispatch_pending_context,
    )
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.intents.schemas.requirement_state import RequirementState
    from backend.intents.services import pending_intent_service
    from backend.intents.services.pending_intent_service import PendingIntents as _RealPendingIntents

    requirements = [
        RequirementState(name="producto_presentacion_id", status="pending", value=None),
        RequirementState(name="cantidad", status="pending", value=1),
    ]
    active_pending = ProcessedIntent(
        intent="agregar_producto",
        source_text="la grande",
        status="pending_resolution",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"cantidad": 2},
        requirements=requirements,
        candidate_ids=[10, 11],
    )

    def _state_with(active=None):
        return pending_intent_service.PendingIntents(active=active)

    class _FakePendingIntents:
        def __init__(self, active=None):
            self.active = active

    pending_intent_service.PendingIntents = _RealPendingIntents

    session = MagicMock(pending_intents={"active": "x"}, context_type="product_selection")

    def restore():
        from backend.intents.services.pending_intent_service import PendingIntents as _RestorePending
        pending_intent_service.PendingIntents = _RestorePending
    restore()

    with patch(
        "backend.intents.orchestration.pending_context_dispatcher.load_pending_state",
        return_value=_FakePendingIntents(active_pending),
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.set_active"
    ) as set_active, patch(
        "backend.intents.orchestration.pending_context_dispatcher.ProductSelectionContextService.resolve",
        return_value=active_pending,
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.execute_ready_pending_context"
    ) as execute:
        pending_result = dispatch_pending_context(MagicMock(), session, "la grande")
    record(
        "pending_context_dispatcher_pending_preserves_context",
        pending_result.status == "pending_resolution"
        and set_active.called
        and not execute.called,
        f"status={pending_result.status} set_active={set_active.called}",
    )

    from backend.intents.services.pending_intent_service import PendingIntents as _RestorePending
    pending_intent_service.PendingIntents = _RestorePending

    ready_intent = active_pending.model_copy(
        update={"status": "ready", "resolved_data": {"producto_presentacion_id": 42, "cantidad": 2}}
    )
    executed_intent = ready_intent.model_copy(update={"status": "executed"})
    session.pending_intents = {"active": "keep"}
    session.context_type = "product_selection"
    pending_intent_service.PendingIntents = _RealPendingIntents
    with patch(
        "backend.intents.orchestration.pending_context_dispatcher.load_pending_state",
        return_value=_FakePendingIntents(ready_intent),
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.set_active"
    ) as set_active, patch(
        "backend.intents.orchestration.pending_context_dispatcher.ProductSelectionContextService.resolve",
        return_value=ready_intent,
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.execute_ready_pending_context",
        return_value=executed_intent,
    ) as execute:
        executed = dispatch_pending_context(MagicMock(), session, "la grande")
    record(
        "pending_context_dispatcher_ready_triggers_execution",
        executed.status == "executed"
        and set_active.called
        and execute.called,
        f"status={executed.status} executed={execute.called}",
    )

    session.pending_intents = {}
    session.context_type = "product_selection"
    with patch(
        "backend.intents.orchestration.pending_context_dispatcher.load_pending_state",
        return_value=_FakePendingIntents(None),
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.set_active"
    ) as set_active, patch(
        "backend.intents.orchestration.pending_context_dispatcher.execute_ready_pending_context"
    ) as execute:
        missing = dispatch_pending_context(MagicMock(), session, "msg")
    record(
        "pending_context_dispatcher_rejects_missing_active",
        missing.status == "rejected"
        and not set_active.called
        and not execute.called,
        f"status={missing.status}",
    )

    session.pending_intents = {"active": "keep"}
    session.context_type = None
    with patch(
        "backend.intents.orchestration.pending_context_dispatcher.load_pending_state",
        return_value=_FakePendingIntents(active_pending),
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.set_active"
    ) as set_active, patch(
        "backend.intents.orchestration.pending_context_dispatcher.execute_ready_pending_context"
    ) as execute:
        no_ctx = dispatch_pending_context(MagicMock(), session, "msg")
    record(
        "pending_context_dispatcher_rejects_missing_context_type",
        no_ctx.status == "rejected"
        and not set_active.called
        and not execute.called,
        f"status={no_ctx.status}",
    )

    session.pending_intents = {"active": "keep"}
    session.context_type = "unknown"
    with patch(
        "backend.intents.orchestration.pending_context_dispatcher.load_pending_state",
        return_value=_FakePendingIntents(active_pending),
    ), patch(
        "backend.intents.orchestration.pending_context_dispatcher.set_active"
    ) as set_active, patch(
        "backend.intents.orchestration.pending_context_dispatcher.execute_ready_pending_context"
    ) as execute:
        unknown_ctx = dispatch_pending_context(MagicMock(), session, "msg")
    record(
        "pending_context_dispatcher_rejects_unsupported_context",
        unknown_ctx.status == "rejected"
        and not set_active.called
        and not execute.called,
        f"status={unknown_ctx.status}",
    )

    import pathlib
    import backend.intents.orchestration.pending_context_dispatcher as module
    from backend.intents.services.pending_intent_service import PendingIntents as _RestorePending
    pending_intent_service.PendingIntents = _RestorePending

    source = pathlib.Path(module.__file__).read_text()
    record(
        "pending_context_dispatcher_public_surface_and_no_sql",
        set(module.__all__) == {"dispatch_pending_context"}
        and "from sqlalchemy import" not in source
        and "HTTPException" not in source,
        str(module.__all__),
    )


def test_agregar_producto_end_to_end() -> None:
    import datetime as _dt
    import uuid

    from backend.intents.orchestration.agregar_producto_orchestrator import (
        process_initial_agregar_producto,
    )
    from backend.intents.orchestration.pending_context_dispatcher import (
        dispatch_pending_context,
    )
    from backend.intents.services.pending_intent_service import PendingIntents as _RealPendingIntents
    from backend.intents.services.pending_intent_service import load as load_pending_state
    from backend.models import (
        CategoriaProducto,
        Cliente,
        Comercio,
        EstadoComercio,
        EstadoPedido,
        Pedido,
        PedidoProducto,
        Presentacion,
        Precio,
        Producto,
        ProductoPresentacion,
        Session as SessionModel,
    )
    from backend.services.categoria_producto_service import CategoriaProductoService
    from backend.services.cliente_service import ClienteService
    from backend.services.comercio_service import ComercioService
    from backend.services.pedido_service import PedidoService
    from backend.services.presentacion_service import PresentacionService
    from backend.services.precio_service import PrecioService
    from backend.services.producto_service import ProductoService
    from backend.services.session_service import SessionService
    from decimal import Decimal

    suffix = uuid.uuid4().hex[:10]
    comercio_payload = {
        "nombre_fantasia": f"Test Comercio E2E {suffix}",
        "nombre_corto": f"TCE {suffix}",
        "razon_social": f"Test Comercio E2E SRL {suffix}",
        "cuit": f"30-{suffix[:8]}-{suffix[8]}",
        "whatsapp": f"+54911888{suffix[:4]}",
        "calle": "Av. E2E",
        "numero": "1000",
        "piso_departamento": None,
        "localidad": "CABA",
        "provincia": "Buenos Aires",
        "codigo_postal": "C1000",
        "slug": f"test-comercio-e2e-{suffix}",
        "estado_id": _estado_id_activo(),
    }

    with TestingSessionLocal() as setup:
        comercio = ComercioService(setup).create(comercio_payload)
        categoria = CategoriaProductoService(setup).create(
            comercio.id, f"E2E {suffix}", True, 0
        )
        presentaciones = {
            codigo: PresentacionService(setup).create(
                comercio.id, codigo, f"Presentacion {codigo} {suffix}", True, orden
            )
            for codigo, orden in (("chica", 0), ("grande", 1))
        }
        categoria_id = categoria.id
        del categoria
        producto = ProductoService(setup).create(
            categoria_id, f"Pizza Mozzarella {suffix}", None, True, True, 0
        )
        product_id = producto.id
        asociaciones = {}
        for codigo, presentacion in presentaciones.items():
            assoc = ProductoPresentacion(
                id_producto=product_id,
                id_presentacion=presentacion.id,
                activo=True,
                orden=presentacion.orden,
            )
            setup.add(assoc)
            setup.flush()
            asociaciones[codigo] = assoc
        precios = {}
        for codigo, assoc in asociaciones.items():
            precio = PrecioService(setup).create(assoc.id, Decimal("12345.67"))
            precios[codigo] = precio
        cliente = ClienteService(setup).create(f"+5491{int(suffix, 16) % 100000000:08d}", None, None, True)
        cliente_id = cliente.id
        del cliente
        session_row = SessionService(setup).create(comercio.id, cliente_id, None)
        pedido = PedidoService(setup).create(session_row.id, None, None, None)
        SessionService(setup).asociar_pedido(session_row.id, pedido.id)
        session_id = session_row.id
        comercio_id = comercio.id
        pedido_id = pedido.id
        chica_pp_id = asociaciones["chica"].id
        grande_pp_id = asociaciones["grande"].id
        chica_precio = precios["chica"].precio
        grande_precio = precios["grande"].precio
        session_ctx_id = session_row.id

    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_ctx_id)
        assert session_row is not None
        pending = process_initial_agregar_producto(db, session_row, "quiero 2 pizzas de mozzarella")
        db.commit()
        db.refresh(session_row)
        loaded = load_pending_state(session_row)
        record(
            "agregar_producto_e2e_initial_message_pending",
            pending.status == "pending_resolution"
            and session_row.context_type == "product_selection"
            and loaded.active is not None
            and loaded.active.status == "pending_resolution"
            and len(db.query(PedidoProducto).filter_by(id_pedido=pedido_id).all()) == 0,
            f"status={pending.status} ctx={session_row.context_type} pedido_lines=0",
        )

    with TestingSessionLocal() as db:
        db.expire_all()
        session_row = db.get(SessionModel, session_ctx_id)
        assert session_row is not None
        executed = dispatch_pending_context(db, session_row, "pizza grande")
        db.commit()
        db.expire_all()
        session_row = db.get(SessionModel, session_ctx_id)
        assert session_row is not None
        lines = db.query(PedidoProducto).filter_by(id_pedido=pedido_id).all()
        active = load_pending_state(session_row).active
        record(
            "agregar_producto_e2e_second_message_executed",
            executed.status == "executed"
            and len(lines) == 1
            and lines[0].id_producto_presentacion == grande_pp_id
            and lines[0].cantidad == 2
            and lines[0].precio_unitario == grande_precio
            and session_row.context_type is None
            and active is None,
            f"status={executed.status} lines={len(lines)} pp={getattr(lines[0], 'id_producto_presentacion', None)} qty={getattr(lines[0], 'cantidad', None)} ctx={session_row.context_type} active={active}",
        )

    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_ctx_id)
        assert session_row is not None
        db.commit()
        active = PresentacionService(db).create(comercio_id, "mediana", f"Presentacion mediana {suffix}", True, 2)
        db.add(
            ProductoPresentacion(
                id_producto=product_id,
                id_presentacion=active.id,
                activo=True,
                orden=2,
            )
        )
        db.commit()
        session_row.context_type = "product_selection"
        session_row.pending_intents = {
            "active": {
                "intent": "agregar_producto",
                "source_text": "pizza mediana",
                "status": "pending_resolution",
                "recognizer": "recognizer_productos",
                "handler": "agregar_producto",
                "resolved_data": {"cantidad": 2},
                "requirements": [],
                "candidate_ids": [chica_pp_id, active.id],
            }
        }
        db.commit()
        db.expire_all()
        session_row = db.get(SessionModel, session_ctx_id)
        active_session = db.get(SessionModel, session_ctx_id)
        assert active_session is not None
        ambiguous = dispatch_pending_context(db, active_session, "pizza grande y mediana")
        db.commit()
        db.expire_all()
        session_row = db.get(SessionModel, session_ctx_id)
        ambiguous_lines = db.query(PedidoProducto).filter_by(id_pedido=pedido_id).all()
        record(
            "agregar_producto_e2e_ambiguous_reply_preserves_context",
            ambiguous.status == "pending_resolution"
            and session_row.context_type == "product_selection"
            and load_pending_state(session_row).active is not None,
            f"status={ambiguous.status} ctx={session_row.context_type} active={load_pending_state(session_row).active}",
        )

    with TestingSessionLocal() as db:
        comercio = db.get(Comercio, comercio_id)
        pedidos = db.query(Pedido).filter_by(id_session=session_ctx_id).all()
        for p in pedidos:
            for line in db.query(PedidoProducto).filter_by(id_pedido=p.id).all():
                db.delete(line)
            db.delete(p)
        db.query(PedidoProducto).filter(
            PedidoProducto.id_producto_presentacion.in_([chica_pp_id, grande_pp_id])
        ).delete(synchronize_session=False)
        db.query(Precio).filter(Precio.id_producto_presentacion.in_([chica_pp_id, grande_pp_id])).delete(synchronize_session=False)
        db.query(ProductoPresentacion).filter_by(id_producto=product_id).delete(synchronize_session=False)
        db.query(Producto).filter_by(id=product_id).delete()
        db.query(Presentacion).filter_by(id_comercio=comercio_id).delete(synchronize_session=False)
        db.query(CategoriaProducto).filter_by(id=categoria_id).delete(synchronize_session=False)
        sess_row = db.get(SessionModel, session_ctx_id)
        if sess_row is not None:
            db.delete(sess_row)
        db.flush()
        cliente_row = db.get(Cliente, cliente_id)
        if cliente_row is not None:
            db.delete(cliente_row)
        db.query(Comercio).filter_by(id=comercio_id).delete(synchronize_session=False)
        db.commit()


def test_agregar_producto_customer_response() -> None:
    import uuid
    from decimal import Decimal
    from unittest.mock import MagicMock, patch

    import backend.intents.responses.agregar_producto_response as response_module
    import backend.intents.schemas.customer_response as schema_module
    from backend.intents.responses.agregar_producto_response import (
        build_agregar_producto_response,
    )
    from backend.intents.schemas.processed_intent import ProcessedIntent
    from backend.models import (
        CategoriaProducto,
        Cliente,
        Comercio,
        Pedido,
        PedidoProducto,
        Presentacion,
        Precio,
        Producto,
        ProductoPresentacion,
        Session as SessionModel,
    )
    from backend.services.categoria_producto_service import CategoriaProductoService
    from backend.services.cliente_service import ClienteService
    from backend.services.comercio_service import ComercioService
    from backend.services.pedido_service import PedidoService
    from backend.services.precio_service import PrecioService
    from backend.services.presentacion_service import PresentacionService
    from backend.services.producto_service import ProductoService
    from backend.services.session_service import SessionService

    apology_message = "No pude procesar tu pedido, ¿podrías reformularlo?"
    retry_message = "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
    suffix = uuid.uuid4().hex[:10]
    comercio_payload = {
        "nombre_fantasia": f"Test Comercio Response {suffix}",
        "nombre_corto": f"TCR {suffix}",
        "razon_social": f"Test Comercio Response SRL {suffix}",
        "cuit": f"30-{suffix[:8]}-{suffix[8]}",
        "whatsapp": f"+54911777{suffix[:4]}",
        "calle": "Av. Response",
        "numero": "1000",
        "piso_departamento": None,
        "localidad": "CABA",
        "provincia": "Buenos Aires",
        "codigo_postal": "C1000",
        "slug": f"test-comercio-response-{suffix}",
        "estado_id": _estado_id_activo(),
    }

    with TestingSessionLocal() as setup:
        comercio = ComercioService(setup).create(comercio_payload)
        categoria = CategoriaProductoService(setup).create(
            comercio.id, f"Response {suffix}", True, 0
        )
        chica = PresentacionService(setup).create(
            comercio.id, f"chica-{suffix}", "chica", True, 0
        )
        grande = PresentacionService(setup).create(
            comercio.id, f"grande-{suffix}", "grande", True, 1
        )
        producto = ProductoService(setup).create(
            categoria.id, f"Pizza Mozzarella {suffix}", None, True, True, 0
        )
        chica_pp = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=chica.id,
            activo=True,
            orden=0,
        )
        grande_pp = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=grande.id,
            activo=True,
            orden=1,
        )
        setup.add_all([chica_pp, grande_pp])
        setup.flush()
        chica_price = PrecioService(setup).create(chica_pp.id, Decimal("12345.67"))
        grande_price = PrecioService(setup).create(grande_pp.id, Decimal("23456.78"))
        cliente = ClienteService(setup).create(
            f"+54912{int(suffix, 16) % 100000000:08d}", None, None, True
        )
        session_row = SessionService(setup).create(comercio.id, cliente.id, None)
        pedido = PedidoService(setup).create(session_row.id, None, None, None)
        SessionService(setup).asociar_pedido(session_row.id, pedido.id)
        setup.commit()
        comercio_id = comercio.id
        categoria_id = categoria.id
        producto_id = producto.id
        cliente_id = cliente.id
        session_id = session_row.id
        pedido_id = pedido.id
        chica_pp_id = chica_pp.id
        grande_pp_id = grande_pp.id
        price_strings = (str(chica_price.precio), str(grande_price.precio))

    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_id)
        assert session_row is not None
        pending_intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[chica_pp_id, grande_pp_id],
        )
        pending_response = build_agregar_producto_response(db, session_row, pending_intent)
        record(
            "agregar_producto_customer_response_pending_resolution",
            "Pizza Mozzarella" in pending_response.message
            and "chica" in pending_response.message
            and "grande" in pending_response.message
            and "o " in pending_response.message
            and str(chica_pp_id) not in pending_response.message
            and str(grande_pp_id) not in pending_response.message
            and "id" not in pending_response.message.lower()
            and all(price not in pending_response.message for price in price_strings)
            and "stock" not in pending_response.message.lower()
            and pending_response.intent == "agregar_producto"
            and pending_response.status == "pending_resolution",
            pending_response.message,
        )

        empty_response = build_agregar_producto_response(
            db,
            session_row,
            pending_intent.model_copy(update={"candidate_ids": []}),
        )
        record(
            "agregar_producto_customer_response_empty_candidates",
            empty_response.message == apology_message
            and empty_response.status == "pending_resolution",
            empty_response.message,
        )

        executed_intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza grande",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={
                "producto_presentacion_id": grande_pp_id,
                "cantidad": 1,
            },
            requirements=[],
            candidate_ids=[],
        )
        singular_response = build_agregar_producto_response(
            db, session_row, executed_intent
        )
        record(
            "agregar_producto_customer_response_executed_singular",
            "Pizza Mozzarella" in singular_response.message
            and "grande" in singular_response.message
            and "1" in singular_response.message
            and "agregué" in singular_response.message
            and str(grande_pp_id) not in singular_response.message
            and all(price not in singular_response.message for price in price_strings),
            singular_response.message,
        )

        plural_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(
                update={
                    "resolved_data": {
                        "producto_presentacion_id": grande_pp_id,
                        "cantidad": 2,
                    }
                }
            ),
        )
        record(
            "agregar_producto_customer_response_executed_plural",
            "Pizza Mozzarella" in plural_response.message
            and "grande" in plural_response.message
            and "2" in plural_response.message
            and "agregué" not in plural_response.message
            and str(grande_pp_id) not in plural_response.message
            and all(price not in plural_response.message for price in price_strings),
            plural_response.message,
        )

        missing_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(
                update={
                    "resolved_data": {
                        "producto_presentacion_id": 999999,
                        "cantidad": 1,
                    }
                }
            ),
        )
        record(
            "agregar_producto_customer_response_missing_presentation",
            missing_response.message == retry_message
            and missing_response.intent == "agregar_producto"
            and missing_response.status == "failed",
            missing_response.message,
        )

        invalid_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(
                update={
                    "resolved_data": {
                        "producto_presentacion_id": grande_pp_id,
                        "cantidad": 0,
                    }
                }
            ),
        )
        record(
            "agregar_producto_customer_response_invalid_quantity",
            invalid_response.message == retry_message
            and invalid_response.status == "failed",
            invalid_response.message,
        )

        rejected_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(update={"status": "rejected"}),
        )
        record(
            "agregar_producto_customer_response_rejected",
            rejected_response.message == apology_message
            and rejected_response.intent == "agregar_producto"
            and rejected_response.status == "rejected",
            rejected_response.message,
        )

        failed_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(update={"status": "failed"}),
        )
        record(
            "agregar_producto_customer_response_failed",
            failed_response.message == retry_message
            and failed_response.intent == "agregar_producto"
            and failed_response.status == "failed"
            and all(
                value not in failed_response.message
                for value in ("Exception", "Traceback", "Error", str(grande_pp_id))
            ),
            failed_response.message,
        )

        other_response = build_agregar_producto_response(
            db,
            session_row,
            executed_intent.model_copy(update={"intent": "consultar_pedido"}),
        )
        record(
            "agregar_producto_customer_response_other_intent",
            other_response.message == apology_message
            and other_response.intent == "consultar_pedido"
            and other_response.status == "executed",
            other_response.message,
        )

        session_snapshot = (
            session_row.pending_intents,
            session_row.context_type,
            session_row.id_pedido,
        )
        intent_snapshot = pending_intent.model_dump()
        mock_db = MagicMock(name="DatabaseSession")
        mock_presentation = {
            "producto_nombre": "Pizza Mozzarella",
            "presentacion_descripcion": "grande",
        }
        with patch.object(
            response_module.ProductoQueryService,
            "list_presentaciones_by_ids",
            return_value=[mock_presentation],
        ):
            build_agregar_producto_response(mock_db, session_row, pending_intent)
            build_agregar_producto_response(mock_db, session_row, executed_intent)
        no_database_mutation = True
        for method_name in ("commit", "rollback", "flush", "refresh", "expire", "begin"):
            try:
                getattr(mock_db, method_name).assert_not_called()
            except AssertionError:
                no_database_mutation = False
        record(
            "agregar_producto_customer_response_no_mutation",
            no_database_mutation
            and session_snapshot
            == (
                session_row.pending_intents,
                session_row.context_type,
                session_row.id_pedido,
            )
            and intent_snapshot == pending_intent.model_dump(),
        )

    response_source = Path(response_module.__file__).read_text()
    schema_source = Path(schema_module.__file__).read_text()
    forbidden_response_source = (
        "from sqlalchemy import select",
        "joinedload",
        "from backend.repositories",
        "from backend.intents.orchestration",
        "from backend.intents.handlers",
        "from backend.intents.resolvers",
        "from backend.intents.services",
        "from backend.intents.context",
        "from backend.llm",
        "from backend.routers",
        "from backend.dependencies",
        "from backend.old_project",
        "import requests",
        "import fastapi",
        "import twilio",
        "HTTPException",
        "JSONResponse",
        "MessagingResponse",
        "QueryLlm",
        "retry",
        "backoff",
        "async def",
    )
    record(
        "agregar_producto_customer_response_module_boundaries",
        all(value not in response_source for value in forbidden_response_source)
        and set(schema_module.CustomerResponse.model_fields)
        == {"message", "intent", "status"}
        and "Config" not in schema_source
        and "validator" not in schema_source,
    )
    record(
        "agregar_producto_customer_response_public_surface",
        response_module.__all__ == ["build_agregar_producto_response"]
        and schema_module.__all__ == ["CustomerResponse"],
    )

    with TestingSessionLocal() as db:
        for line in db.query(PedidoProducto).filter_by(id_pedido=pedido_id).all():
            db.delete(line)
        session_row = db.get(SessionModel, session_id)
        if session_row is not None:
            session_row.id_pedido = None
        db.flush()
        pedido = db.get(Pedido, pedido_id)
        if pedido is not None:
            db.delete(pedido)
        db.flush()
        db.query(Precio).filter(
            Precio.id_producto_presentacion.in_([chica_pp_id, grande_pp_id])
        ).delete(synchronize_session=False)
        db.query(ProductoPresentacion).filter_by(id_producto=producto_id).delete(
            synchronize_session=False
        )
        db.query(Producto).filter_by(id=producto_id).delete()
        db.query(Presentacion).filter_by(id_comercio=comercio_id).delete(
            synchronize_session=False
        )
        db.query(CategoriaProducto).filter_by(id=categoria_id).delete(
            synchronize_session=False
        )
        session_row = db.get(SessionModel, session_id)
        if session_row is not None:
            db.delete(session_row)
        db.flush()
        cliente = db.get(Cliente, cliente_id)
        if cliente is not None:
            db.delete(cliente)
        db.query(Comercio).filter_by(id=comercio_id).delete(
            synchronize_session=False
        )
        db.commit()


if __name__ == "__main__":
    test_health()
    test_get_missing_404()
    test_create_missing_estado_404()
    test_create_and_get()
    test_create_duplicate_whatsapp_409()
    test_create_duplicate_slug_409()
    test_list_estados_comercio()
    test_get_estado_comercio_missing_404()
    test_create_estado_comercio_201()
    test_create_estado_comercio_duplicate_409()
    test_create_estado_comercio_trims_whitespace()
    test_create_estado_comercio_empty_400()
    test_create_estado_comercio_rejects_id_422()
    test_list_medios_pago()
    test_get_medio_pago_missing_404()
    test_create_medio_pago_201()
    test_create_medio_pago_duplicate_409()
    test_create_medio_pago_trims_whitespace()
    test_create_medio_pago_empty_codigo_400()
    test_create_medio_pago_empty_descripcion_400()
    test_create_medio_pago_rejects_id_422()
    test_create_medio_pago_activo_defaults_true()
    test_list_and_get_metodos_entrega()
    test_get_metodo_entrega_missing_404()
    test_create_metodo_entrega_201_and_activo()
    test_create_metodo_entrega_trims_and_rejects_duplicate()
    test_create_metodo_entrega_validation()
    test_metodo_entrega_service_rolls_back_on_create_failure()
    test_categoria_producto_create_get_and_list()
    test_categoria_producto_missing_and_validation()
    test_categoria_producto_service_rolls_back_on_create_failure()
    test_presentacion_create_get_list_and_scoped_duplicates()
    test_presentacion_missing_and_validation()
    test_presentacion_service_rolls_back_on_create_failure()
    test_producto_create_get_category_and_commerce_lists()
    test_producto_missing_validation_and_empty_commerce()
    test_producto_service_rolls_back_on_create_failure()
    test_precio_create_and_retrieve_exact_decimal()
    test_precio_missing_and_validation()
    test_precio_service_rolls_back_on_create_failure()
    test_configuracion_comercio_complete_and_eager()
    test_configuracion_comercio_empty_and_missing()
    test_producto_queries_detail_association_price()
    test_producto_queries_search_name_availability()
    test_producto_queries_catalogo_and_category()
    test_product_recognizer()
    test_product_selection_context_resolver()
    test_pscr_real_integration()
    test_pending_context_service()
    test_context_type_resolver()
    test_session_context_type_enum()
    test_pending_intent_service()
    test_process_agregar_producto_processor()
    test_agregar_producto_orchestrator()
    test_agregar_producto_handler()
    test_pending_context_execution()
    test_pending_context_dispatcher()
    test_agregar_producto_end_to_end()
    test_agregar_producto_customer_response()
    test_product_intent_resolver()
    test_pending_intents_schema()
    test_processed_intent_schema()
    test_requirement_state_schema()
    test_agregar_producto_contract_structure()
    test_pedido_create_defaults_to_borrador()
    test_pedido_create_with_known_fks()
    test_pedido_create_missing_id_session_422()
    test_pedido_create_non_existent_id_session_404()
    test_pedido_create_closed_id_session_409()
    test_pedido_create_unknown_fk_returns_400_no_row()
    test_pedido_get_missing_404()
    test_pedido_updates_in_borrador_succeed()
    test_pedido_update_unknown_fk_returns_400()
    test_pedido_updates_outside_borrador_409()
    test_pedido_state_transitions()
    test_pedido_forbidden_transition_409()
    test_pedido_cancel_from_working_states()
    test_pedido_update_missing_404()
    test_pedido_relationship_attributes_exist()
    test_cliente_create_normalizes_whatsapp()
    test_cliente_create_duplicate_whatsapp_409()
    test_cliente_create_invalid_whatsapp_400()
    test_cliente_get_by_id_and_whatsapp_roundtrip()
    test_cliente_update_mutates_subset_and_rejects_whatsapp()
    test_cliente_activate_deactivate()
    test_cliente_update_trims_strings_to_none()
    test_cliente_create_rejects_id_422()
    test_cliente_no_session_field()
    test_session_create_defaults_to_activa()
    test_session_create_without_pedido()
    test_session_duplicate_active_409()
    test_session_get_by_id_and_active()
    test_session_update_movimiento_bumps_timestamp()
    test_session_close_active_and_rejects_already_closed()
    test_session_asociar_pedido_succeeds_and_validates()
    test_pedido_producto_create_snapshots_price_and_quantity_validated()
    test_pedido_producto_rejects_precio_unitario_in_body()
    test_pedido_producto_rejects_nonexistent_pedido()
    test_pedido_producto_rejects_nonexistent_producto_presentacion()
    test_pedido_producto_rejects_zero_quantity()
    test_pedido_producto_rejects_add_when_pedido_not_borrador()
    test_pedido_producto_list_get_update_delete_in_borrador()
    test_pedido_producto_rejects_update_when_pedido_not_borrador()
    test_pedido_producto_list_empty()
    test_pedido_producto_missing_404()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"== {passed}/{total} passed ==")
    if passed != total:
        raise SystemExit(1)
