from __future__ import annotations

import math
from collections.abc import Iterable
from numbers import Real
from typing import Never, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.models import ProductoPresentacionEmbedding
from backend.repositories.producto_presentacion_embedding_repository import (
    ProductoPresentacionEmbeddingRepository,
)
from backend.services.exceptions import (
    DuplicateProductoPresentacionEmbedding,
    InvalidProductoPresentacionEmbedding,
    ProductoPresentacionEmbeddingNotFound,
    ProductoPresentacionEmbeddingPersistenceError,
    ProductoPresentacionNotFound,
)


class ProductoPresentacionEmbeddingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ProductoPresentacionEmbeddingRepository(session)

    def create_or_update(
        self,
        id_producto_presentacion: int,
        vector: Iterable[float] | str | None = None,
        modelo: str | Iterable[float] | None = None,
        *,
        embedding: Iterable[float] | None = None,
        model: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        vector, modelo = self._resolve_values(vector, modelo, embedding, model)
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(modelo)
        valid_vector = self._validate_vector(vector)
        self._require_producto_presentacion(valid_id)
        try:
            return self._repo.create_or_update(
                valid_id,
                valid_vector,
                valid_model,
            )
        except IntegrityError as exc:
            return self._translate_integrity_error(valid_id, exc)

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
        vector, modelo = self._resolve_values(vector, modelo, embedding, model)
        valid_id = self._validate_producto_presentacion_id(id_producto_presentacion)
        valid_model = self._validate_model(modelo)
        valid_vector = self._validate_vector(vector)
        self._require_producto_presentacion(valid_id)
        if self._repo.get_by_identity(valid_id, valid_model) is not None:
            raise DuplicateProductoPresentacionEmbedding(
                f"embedding already exists for presentation {valid_id} and model {valid_model!r}"
            )
        try:
            return self._repo.create(valid_id, valid_vector, valid_model)
        except IntegrityError as exc:
            return self._translate_integrity_error(valid_id, exc)

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
                f"embedding not found for presentation {valid_id} and model {valid_model!r}"
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
    def _validate_vector(vector: Iterable[float] | None) -> list[float]:
        if vector is None or isinstance(vector, (str, bytes)):
            raise InvalidProductoPresentacionEmbedding("vector is required")
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
    ) -> Never:
        if not self._repo.producto_presentacion_exists(id_producto_presentacion):
            raise ProductoPresentacionNotFound(id_producto_presentacion) from exc
        raise ProductoPresentacionEmbeddingPersistenceError(str(exc.orig)) from exc


__all__ = ["ProductoPresentacionEmbeddingService"]
