"""Per-document service for ``producto_presentacion_embeddings``.

Subphase 4.6 evolves the persistence boundary from one aggregate row
per ``(id_producto_presentacion, modelo)`` to one row per semantic
document. The service is the only place that:

- performs the hash-based idempotency comparison for
  ``create_or_update_document(...)`` and decides between the
  ``created`` / ``updated`` / ``unchanged`` outcomes;
- records embedding failures through ``record_failed_document(...)``;
- validates the embedding status state machine through
  ``mark_status(...)`` and the thin wrappers ``mark_stale(...)`` and
  ``mark_inactive(...)``;
- validates input vectors and the ``id_producto_presentacion`` FK
  before delegating to the repository.

The service NEVER calls ``commit``, ``rollback``, ``close``, or
``begin`` on its session. SQLAlchemy ``flush()`` is permitted (no
commit). Repository writes do their own ``flush()`` per call.

The legacy aggregate methods (``create_or_update``, ``upsert``,
``get_by_identity``, ``get_by_producto_presentacion_and_model``,
``get_by_producto_presentacion``, ``find_by_producto_presentacion_and_model``,
``list_by_producto_presentacion``, ``create``, ``save``,
``retrieve``) are kept as deprecated wrappers that route to the
per-document surface with ``source_type='canonical'`` and
``source_record_id=None``. The wrappers preserve the existing public
surface for callers that have not migrated.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from numbers import Real
from typing import Literal, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.embeddings import ProductEmbeddingDocument
from backend.models import (
    EmbeddingStatus,
    ProductoPresentacionEmbedding,
)
from backend.repositories.producto_presentacion_embedding_repository import (
    ProductoPresentacionEmbeddingRepository,
)
from backend.services.exceptions import (
    DuplicateEmbeddingDocument,
    DuplicateProductoPresentacionEmbedding,
    InvalidEmbeddingStatusTransition,
    InvalidProductoPresentacionEmbedding,
    ProductoPresentacionEmbeddingNotFound,
    ProductoPresentacionEmbeddingPersistenceError,
    ProductoPresentacionNotFound,
)

DocumentReconciliationOutcome = Literal["created", "updated", "unchanged"]


_ALLOWED_STATUS_TRANSITIONS: dict[EmbeddingStatus, frozenset[EmbeddingStatus]] = {
    EmbeddingStatus.PENDING: frozenset(
        {EmbeddingStatus.READY, EmbeddingStatus.FAILED, EmbeddingStatus.INACTIVE}
    ),
    EmbeddingStatus.READY: frozenset(
        {
            EmbeddingStatus.FAILED,
            EmbeddingStatus.STALE,
            EmbeddingStatus.INACTIVE,
            EmbeddingStatus.READY,
        }
    ),
    EmbeddingStatus.FAILED: frozenset(
        {
            EmbeddingStatus.READY,
            EmbeddingStatus.FAILED,
            EmbeddingStatus.STALE,
            EmbeddingStatus.INACTIVE,
        }
    ),
    EmbeddingStatus.STALE: frozenset(
        {
            EmbeddingStatus.READY,
            EmbeddingStatus.FAILED,
            EmbeddingStatus.INACTIVE,
        }
    ),
    EmbeddingStatus.INACTIVE: frozenset(
        {
            EmbeddingStatus.READY,
            EmbeddingStatus.FAILED,
            EmbeddingStatus.STALE,
        }
    ),
}


class ProductoPresentacionEmbeddingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ProductoPresentacionEmbeddingRepository(session)

    # -- Per-document surface ------------------------------------------------

    def find_by_document(
        self,
        id_producto_presentacion: int,
        modelo: str,
        source_type: str,
        source_record_id: int | None,
    ) -> ProductoPresentacionEmbedding | None:
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(modelo)
        return self._repo.find_by_document(
            valid_id, valid_model, source_type, source_record_id
        )

    def list_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(modelo)
        return self._repo.list_by_producto_presentacion_and_model(
            valid_id, valid_model
        )

    def list_by_comercio(
        self,
        id_comercio: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        valid_model = self._validate_model(modelo)
        return self._repo.list_by_comercio(id_comercio, valid_model)

    def list_by_producto(
        self,
        id_producto: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        valid_model = self._validate_model(modelo)
        return self._repo.list_by_producto(id_producto, valid_model)

    def list_by_producto_presentacion(
        self,
        id_producto_presentacion: int,
    ) -> list[ProductoPresentacionEmbedding]:
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        self._require_producto_presentacion(valid_id)
        rows = self._repo.list_by_producto_presentacion(valid_id)
        for row in rows:
            self._validate_vector(row.vector)
        return rows

    def create_or_update_document(
        self,
        document: ProductEmbeddingDocument,
        vector: Sequence[float] | None,
        *,
        modelo: str,
        force: bool = False,
    ) -> DocumentReconciliationOutcome:
        """Reconcile one document against the persisted row.

        Returns ``"created"`` when no row exists, ``"unchanged"`` only
        when ALL of the unchanged conditions hold
        (matching ``content_hash``, ``embedding_status == 'ready'``,
        ``activo == True``, present dimension-valid ``vector``, and
        ``force == False``), and ``"updated"`` otherwise.
        """
        valid_id = self._validate_producto_presentacion_id(
            document.producto_presentacion_id
        )
        valid_model = self._validate_model(modelo)
        valid_vector = self._validate_vector(vector)
        self._require_producto_presentacion(valid_id)
        existing = self._repo.find_by_document(
            valid_id,
            valid_model,
            document.source_type,
            document.source_record_id,
        )
        if existing is None:
            try:
                self._repo.insert_document(
                    id_producto_presentacion=valid_id,
                    modelo=valid_model,
                    source_type=document.source_type,
                    source_record_id=document.source_record_id,
                    source_text=document.source_text,
                    normalized_text=document.normalized_text,
                    content_hash=document.content_hash,
                    vector=valid_vector,
                    embedding_status=EmbeddingStatus.READY.value,
                    activo=True,
                    last_error=None,
                )
            except IntegrityError as exc:
                raise DuplicateEmbeddingDocument(
                    f"duplicate document for presentation {valid_id} "
                    f"model {valid_model!r} source {document.source_type!r}"
                ) from exc
            return "created"
        if (
            not force
            and existing.content_hash == document.content_hash
            and existing.embedding_status == EmbeddingStatus.READY.value
            and existing.activo is True
            and existing.vector is not None
            and len(existing.vector) == load_settings().embedding_dimension
        ):
            return "unchanged"
        self._repo.update_document(
            existing,
            source_text=document.source_text,
            normalized_text=document.normalized_text,
            content_hash=document.content_hash,
            vector=valid_vector,
            embedding_status=EmbeddingStatus.READY.value,
            activo=True,
            last_error=None,
        )
        return "updated"

    def record_failed_document(
        self,
        document: ProductEmbeddingDocument,
        error_message: str,
        *,
        modelo: str,
    ) -> None:
        """Record a failed embedding for the document tuple.

        When no row exists, insert one with ``vector=NULL``,
        ``embedding_status='failed'``, ``activo=True``, and the
        sanitized ``last_error``. When a row exists, update it with
        the supplied metadata, ``embedding_status='failed'``,
        ``activo=True``, sanitized ``last_error``, while preserving the
        previous ``vector`` and ``fecha_alta``.
        """
        valid_id = self._validate_producto_presentacion_id(
            document.producto_presentacion_id
        )
        valid_model = self._validate_model(modelo)
        self._require_producto_presentacion(valid_id)
        sanitized_error = _sanitize_error_message(error_message)
        existing = self._repo.find_by_document(
            valid_id,
            valid_model,
            document.source_type,
            document.source_record_id,
        )
        if existing is None:
            try:
                self._repo.insert_document(
                    id_producto_presentacion=valid_id,
                    modelo=valid_model,
                    source_type=document.source_type,
                    source_record_id=document.source_record_id,
                    source_text=document.source_text,
                    normalized_text=document.normalized_text,
                    content_hash=document.content_hash,
                    vector=None,
                    embedding_status=EmbeddingStatus.FAILED.value,
                    activo=True,
                    last_error=sanitized_error,
                )
            except IntegrityError as exc:
                raise DuplicateEmbeddingDocument(
                    f"duplicate document for presentation {valid_id} "
                    f"model {valid_model!r} source {document.source_type!r}"
                ) from exc
            return
        self._repo.update_document(
            existing,
            source_text=document.source_text,
            normalized_text=document.normalized_text,
            content_hash=document.content_hash,
            vector=existing.vector,
            embedding_status=EmbeddingStatus.FAILED.value,
            activo=True,
            last_error=sanitized_error,
        )

    def mark_status(
        self,
        row: ProductoPresentacionEmbedding,
        new_status: EmbeddingStatus | str,
    ) -> ProductoPresentacionEmbedding:
        if isinstance(new_status, str) and not isinstance(new_status, EmbeddingStatus):
            try:
                target = EmbeddingStatus(new_status)
            except ValueError as exc:
                raise InvalidEmbeddingStatusTransition(
                    f"unknown embedding status {new_status!r}"
                ) from exc
        elif isinstance(new_status, EmbeddingStatus):
            target = new_status
        else:
            target = new_status
        current = self._coerce_status(row.embedding_status)
        if current == target:
            return row
        allowed = _ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise InvalidEmbeddingStatusTransition(
                f"forbidden transition {current.value} -> {target.value}"
            )
        return self._repo.mark_status(row, target.value)

    def mark_stale(
        self, row: ProductoPresentacionEmbedding
    ) -> ProductoPresentacionEmbedding:
        return self.mark_status(row, EmbeddingStatus.STALE)

    def mark_inactive(
        self, row: ProductoPresentacionEmbedding
    ) -> ProductoPresentacionEmbedding:
        return self.mark_status(row, EmbeddingStatus.INACTIVE)

    @staticmethod
    def _coerce_status(value: str | EmbeddingStatus) -> EmbeddingStatus:
        if isinstance(value, EmbeddingStatus):
            return value
        try:
            return EmbeddingStatus(value)
        except ValueError as exc:
            raise InvalidEmbeddingStatusTransition(
                f"unknown embedding status {value!r}"
            ) from exc

    # -- Legacy aggregate wrappers (deprecated) ------------------------------

    def create_or_update(
        self,
        id_producto_presentacion: int,
        vector: Iterable[float] | str | None = None,
        modelo: str | Iterable[float] | None = None,
        *,
        embedding: Iterable[float] | None = None,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        resolved_vector, resolved_model = self._resolve_values(
            vector, modelo, embedding, model
        )
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(resolved_model)
        valid_vector = self._validate_legacy_vector(resolved_vector)
        self._require_producto_presentacion(valid_id)
        try:
            return self._repo.create_or_update(
                valid_id, valid_vector, valid_model
            )
        except IntegrityError as exc:
            self._translate_integrity_error(valid_id, exc)
            raise AssertionError("unreachable")

    def upsert(
        self,
        id_producto_presentacion: int,
        vector: Iterable[float] | str | None = None,
        modelo: str | Iterable[float] | None = None,
        *,
        embedding: Iterable[float] | None = None,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        return self.create_or_update(
            id_producto_presentacion,
            vector,
            modelo,
            embedding=embedding,
            model=model,
        )

    def save(
        self,
        id_producto_presentacion: int,
        vector: Iterable[float] | str | None = None,
        modelo: str | Iterable[float] | None = None,
        *,
        embedding: Iterable[float] | None = None,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        return self.create_or_update(
            id_producto_presentacion,
            vector,
            modelo,
            embedding=embedding,
            model=model,
        )

    def create(
        self,
        id_producto_presentacion: int,
        vector: Iterable[float] | str | None = None,
        modelo: str | Iterable[float] | None = None,
        *,
        embedding: Iterable[float] | None = None,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        resolved_vector, resolved_model = self._resolve_values(
            vector, modelo, embedding, model
        )
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(resolved_model)
        valid_vector = self._validate_legacy_vector(resolved_vector)
        self._require_producto_presentacion(valid_id)
        if self._repo.get_by_identity(valid_id, valid_model) is not None:
            raise DuplicateProductoPresentacionEmbedding(
                f"embedding already exists for presentation {valid_id} "
                f"and model {valid_model!r}"
            )
        try:
            return self._repo.create(valid_id, valid_vector, valid_model)
        except IntegrityError as exc:
            self._translate_integrity_error(valid_id, exc)
            raise AssertionError("unreachable")

    def get_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str | None = None,
        *,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(model if model is not None else modelo)
        self._require_producto_presentacion(valid_id)
        row = self._repo.get_by_identity(valid_id, valid_model)
        if row is None:
            raise ProductoPresentacionEmbeddingNotFound(
                f"embedding not found for presentation {valid_id} "
                f"and model {valid_model!r}"
            )
        self._validate_vector(row.vector)
        return row

    def get_by_identity(
        self,
        id_producto_presentacion: int,
        modelo: str | None = None,
        *,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        return self.get_by_producto_presentacion_and_model(
            id_producto_presentacion,
            modelo,
            model=model,
        )

    def retrieve(
        self,
        id_producto_presentacion: int,
        modelo: str | None = None,
        *,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        return self.get_by_producto_presentacion_and_model(
            id_producto_presentacion,
            modelo,
            model=model,
        )

    def find_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str | None = None,
        *,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding | None:
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(model if model is not None else modelo)
        self._require_producto_presentacion(valid_id)
        row = self._repo.get_by_identity(valid_id, valid_model)
        if row is not None:
            self._validate_vector(row.vector)
        return row

    # -- Validation helpers --------------------------------------------------

    @staticmethod
    def _resolve_values(
        vector: Iterable[float] | str | None,
        modelo: str | Iterable[float] | None,
        embedding: Iterable[float] | None,
        model: str | None,
    ) -> tuple[Iterable[float] | None, str | None]:
        if embedding is not None:
            if vector is not None:
                raise InvalidProductoPresentacionEmbedding(
                    "vector and embedding cannot both be supplied"
                )
            vector = embedding
        if model is not None:
            if modelo is not None:
                raise InvalidProductoPresentacionEmbedding(
                    "modelo and model cannot both be supplied"
                )
            modelo = model
        if isinstance(vector, str):
            if modelo is None or isinstance(modelo, str):
                raise InvalidProductoPresentacionEmbedding(
                    "vector must be an iterable of numeric values"
                )
            vector, modelo = modelo, vector
        if isinstance(modelo, str) or modelo is None:
            return cast(Iterable[float] | None, vector), modelo
        raise InvalidProductoPresentacionEmbedding(
            "model identifier must be a string"
        )

    @staticmethod
    def _validate_legacy_vector(
        vector: Iterable[float] | None,
    ) -> list[float]:
        validated = ProductoPresentacionEmbeddingService._validate_vector(vector)
        if validated is None:
            raise InvalidProductoPresentacionEmbedding("vector is required")
        return validated

    @staticmethod
    def _validate_producto_presentacion_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidProductoPresentacionEmbedding(
                "id_producto_presentacion must be a positive integer"
            )
        return value

    @staticmethod
    def _validate_model(value: str | None) -> str:
        if not isinstance(value, str):
            raise InvalidProductoPresentacionEmbedding("modelo is required")
        cleaned = value.strip()
        if not cleaned:
            raise InvalidProductoPresentacionEmbedding("modelo must not be empty")
        return cleaned

    @staticmethod
    def _validate_vector(vector: Iterable[float] | None) -> list[float] | None:
        if vector is None:
            return None
        if isinstance(vector, (str, bytes)):
            raise InvalidProductoPresentacionEmbedding("vector must be iterable")
        try:
            values = list(vector)
        except TypeError as exc:
            raise InvalidProductoPresentacionEmbedding(
                "vector must be iterable"
            ) from exc
        expected_dimension = load_settings().embedding_dimension
        if len(values) != expected_dimension:
            raise InvalidProductoPresentacionEmbedding(
                f"vector must contain {expected_dimension} values"
            )
        normalized: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise InvalidProductoPresentacionEmbedding(
                    "vector values must be numeric"
                )
            number = float(value)
            if not math.isfinite(number):
                raise InvalidProductoPresentacionEmbedding(
                    "vector values must be finite"
                )
            normalized.append(number)
        return normalized

    def _require_producto_presentacion(self, id_producto_presentacion: int) -> None:
        if not self._repo.producto_presentacion_exists(id_producto_presentacion):
            raise ProductoPresentacionNotFound(id_producto_presentacion)

    def _translate_integrity_error(
        self,
        id_producto_presentacion: int,
        exc: IntegrityError,
    ) -> None:
        if not self._repo.producto_presentacion_exists(id_producto_presentacion):
            raise ProductoPresentacionNotFound(id_producto_presentacion) from exc
        raise ProductoPresentacionEmbeddingPersistenceError(str(exc.orig)) from exc


def _sanitize_error_message(message: str) -> str:
    """Return a safe, short error message for ``last_error``.

    The persisted message MUST NOT echo source text, vectors, or other
    caller-supplied payloads. Only the exception type and the safe
    metadata fields are retained.
    """
    if not message:
        return "embedding failure"
    first_line = message.splitlines()[0].strip()
    if len(first_line) > 500:
        first_line = first_line[:500]
    return first_line


__all__ = [
    "DocumentReconciliationOutcome",
    "ProductoPresentacionEmbeddingService",
]
