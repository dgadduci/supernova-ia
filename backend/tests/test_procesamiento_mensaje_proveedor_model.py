"""Phase-7.4 ``ProcesamientoMensajeProveedor`` model tests.

The model is the durable deferred work item that records the
business processing of one provider-message receipt. These tests
cover the static model boundaries (table name, columns, unique
constraint, foreign keys, state machine values) and the Python-side
``__all__`` / import surface so future migrations cannot accidentally
rename the persistence boundary.

The tests use the live ``supernova_test`` PostgreSQL database for the
real-DDL checks so a future schema drift cannot break the receipt
uniqueness invariant.
"""
from __future__ import annotations

import ast
import importlib
import unittest
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    ContextoClienteCanalWhatsapp,
    EstadoComercio,
    RecepcionMensajeProveedor,
)
from backend.models.procesamiento_mensaje_proveedor import (
    ProcesamientoMensajeProveedor,
    ProcesamientoMensajeProveedorEstado,
    ProcesamientoMensajeProveedorFailureCategory,
)
from backend.repositories.procesamiento_mensaje_proveedor_repository import (
    ProcesamientoMensajeProveedorRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    REPO_ROOT
    / "backend"
    / "models"
    / "procesamiento_mensaje_proveedor.py"
)
REPOSITORY_PATH = (
    REPO_ROOT
    / "backend"
    / "repositories"
    / "procesamiento_mensaje_proveedor_repository.py"
)


TEST_URL = "postgresql+psycopg:///supernova_test"
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(
                EstadoComercio.codigo == "ACTIVO"
            )
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_comercio(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Proc {suffix}",
            nombre_corto=f"PR {suffix[:6]}",
            razon_social=f"Proc SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8].upper()}",
            whatsapp=f"+54931{suffix[:8]}",
            calle="Av. Proc",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"proc-{suffix.lower()}"[:150],
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)


def _seed_cliente(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54961{suffix[:8]}",
            nombre=f"Proc Cliente {suffix}",
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        return int(cliente.id)


def _seed_channel(
    suffix: str, comercio_id: int, destination: str
) -> int:
    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=destination,
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio_id,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_recepcion(
    suffix: str,
    canal_id: int,
    cliente_id: int,
    comercio_id: int,
) -> int:
    with TestingSessionLocal() as session, session.begin():
        recepcion = RecepcionMensajeProveedor(
            proveedor="twilio",
            identificador_recepcion=f"SM-{suffix}",
            canal_id=canal_id,
            cliente_id=cliente_id,
            comercio_id=comercio_id,
        )
        session.add(recepcion)
        session.flush()
        return int(recepcion.id)


def _delete_procesamientos_by_recepcion(recepcion_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
                == recepcion_id
            )
        )


def _delete_recepcion(recepcion_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.id == recepcion_id
            )
        )


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.comercio_id == comercio_id
            )
        )
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.comercio_id_seleccionado
                == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(
            delete(Comercio).where(Comercio.id == comercio_id)
        )


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.cliente_id == cliente_id
            )
        )
        session.execute(
            delete(Cliente).where(Cliente.id == cliente_id)
        )


class ModelSurfaceTest(unittest.TestCase):
    """The model exposes the documented state machine, failure
    category enum and module ``__all__`` boundary.
    """

    def test_module_all_lists_model_and_enums(self) -> None:
        importlib.import_module(
            "backend.models.procesamiento_mensaje_proveedor"
        )
        from backend.models import (
            procesamiento_mensaje_proveedor as mod,
        )

        self.assertEqual(
            set(mod.__all__),
            {
                "ProcesamientoMensajeProveedor",
                "ProcesamientoMensajeProveedorEstado",
                "ProcesamientoMensajeProveedorFailureCategory",
            },
        )

    def test_estado_enum_values_are_stable(self) -> None:
        self.assertEqual(
            {member.value for member in ProcesamientoMensajeProveedorEstado},
            {
                "pending",
                "leased",
                "retryable",
                "processed",
                "failed_terminal",
            },
        )

    def test_failure_category_enum_values_are_stable(self) -> None:
        self.assertEqual(
            {
                member.value
                for member in ProcesamientoMensajeProveedorFailureCategory
            },
            {
                "pipeline_error",
                "database_error",
                "budget_exhausted",
                "terminal_processor_error",
            },
        )


class ModelStaticBoundariesTest(unittest.TestCase):
    """AST-level checks: the persistence layer never imports HTTP,
    FastAPI, the Twilio SDK, TwiML, the coordinator or the callback
    service, and the repository never controls transactions.
    """

    def _parse(self, path: Path) -> ast.Module:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_model_does_not_import_http_or_twilio(self) -> None:
        tree = self._parse(MODEL_PATH)
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        forbidden = {
            "fastapi",
            "starlette",
            "twilio",
            "TwiML",
            "MessagingResponse",
            "RequestValidator",
        }
        leaked = forbidden & names
        self.assertEqual(
            leaked,
            set(),
            f"ProcesamientoMensajeProveedor must not import HTTP/Twilio "
            f"symbols: {leaked}",
        )

    def test_model_table_name_is_durable(self) -> None:
        source = MODEL_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '__tablename__ = "procesamientos_mensajes_proveedor"',
            source,
            "tablename must remain stable for the migration boundary",
        )

    def test_repository_does_not_control_transactions(self) -> None:
        tree = self._parse(REPOSITORY_PATH)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                continue
            self.assertNotIn(
                node.func.attr,
                {"commit", "rollback", "begin", "flush", "close"},
                "ProcesamientoMensajeProveedorRepository must not "
                "control transactions",
            )

    def test_repository_uses_conditional_updates(self) -> None:
        """The finalize mutations MUST condition on the lease token
        so a late result cannot overwrite a later attempt's state.
        """
        source = REPOSITORY_PATH.read_text(encoding="utf-8")
        for needle in (
            "finalize_processed",
            "finalize_retryable",
            "finalize_terminal",
        ):
            self.assertIn(needle, source)
        self.assertGreaterEqual(
            source.count("token_lease == lease_token"),
            3,
            "every finalize branch must condition on the lease token",
        )


class ModelStageIntegrationTest(unittest.TestCase):
    """Real PostgreSQL proof of the unique
    ``(recepcion_mensaje_proveedor_id)`` constraint that prevents
    duplicate deferred work items for a single receipt.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54972{suffix[:8]}"
        self.canal_id = _seed_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.recepcion_id = _seed_recepcion(
            suffix + "R", self.canal_id, self.cliente_id, self.comercio_id
        )
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_recepcion, self.recepcion_id)
        self.addCleanup(_delete_procesamientos_by_recepcion, self.recepcion_id)

    def test_stage_inserts_pending_row(self) -> None:
        with TestingSessionLocal() as session:
            repo = ProcesamientoMensajeProveedorRepository(session)
            row = repo.stage(
                recepcion_mensaje_proveedor_id=self.recepcion_id,
                mensaje="hola-mundo",
            )
            session.flush()
            inserted_id = int(row.id)
            session.commit()
        self.assertIsNotNone(inserted_id)
        with TestingSessionLocal() as session:
            loaded = session.get(
                ProcesamientoMensajeProveedor, inserted_id
            )
            assert loaded is not None
            self.assertEqual(
                int(loaded.recepcion_mensaje_proveedor_id),
                self.recepcion_id,
            )
            self.assertEqual(loaded.mensaje, "hola-mundo")
            self.assertEqual(
                loaded.estado,
                ProcesamientoMensajeProveedorEstado.PENDING.value,
            )
            self.assertEqual(int(loaded.intentos), 0)
            self.assertIsNone(loaded.token_lease)
            self.assertIsNone(loaded.lease_expira_en)
            self.assertIsNone(loaded.proximo_intento_en)
            self.assertIsNone(loaded.fecha_finalizacion)
            self.assertIsNotNone(loaded.fecha_creacion)

    def test_stage_does_not_flush_or_commit(self) -> None:
        class _FakeSession:
            def __init__(self) -> None:
                self.add_calls: list[Any] = []
                self.flushed = False
                self.committed = False
                self.rolled_back = False

            def add(self, row: Any) -> None:
                self.add_calls.append(row)

        session = _FakeSession()
        ProcesamientoMensajeProveedorRepository(
            session  # type: ignore[arg-type]
        ).stage(
            recepcion_mensaje_proveedor_id=self.recepcion_id,
            mensaje="hola",
        )
        self.assertEqual(len(session.add_calls), 1)
        self.assertFalse(session.flushed)
        self.assertFalse(session.committed)
        self.assertFalse(session.rolled_back)

    def test_duplicate_stage_violates_unique_constraint(self) -> None:
        """The unique ``(recepcion_mensaje_proveedor_id)`` index
        guarantees one work item per receipt at the database layer;
        a second ``INSERT`` for the same receipt must raise
        ``IntegrityError`` on commit.
        """
        from sqlalchemy.exc import IntegrityError

        with TestingSessionLocal() as session:
            repo = ProcesamientoMensajeProveedorRepository(session)
            repo.stage(
                recepcion_mensaje_proveedor_id=self.recepcion_id,
                mensaje="primero",
            )
            session.commit()

        with TestingSessionLocal() as session:
            repo = ProcesamientoMensajeProveedorRepository(session)
            repo.stage(
                recepcion_mensaje_proveedor_id=self.recepcion_id,
                mensaje="duplicado",
            )
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)