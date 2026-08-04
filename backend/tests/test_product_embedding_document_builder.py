"""Focused unit tests for ``ProductEmbeddingDocumentBuilder``.

These tests are pure: no database, no HTTP, no Ollama, no fixtures. They
cover the contract declared by Subphase 4.5 — the canonical, description,
alias, and combined documents; scope-aware alias inclusion; presentation
distinction; deterministic hashing; duplicate removal; stable ordering;
inactive-alias exclusion; Unicode normalization; and validation errors.
"""
from __future__ import annotations

import hashlib
import unittest
from typing import cast

from backend.embeddings.product_embedding_document_builder import (
    InvalidProductEmbeddingDocument,
    ProductEmbeddingAliasInput,
    ProductEmbeddingAliasScope,
    ProductEmbeddingCatalogProjection,
    ProductEmbeddingDocument,
    ProductEmbeddingDocumentBuilder,
)


def _projection(
    *,
    producto_id: int = 7,
    producto_presentacion_id: int = 31,
    producto_nombre: str = "Pizza de Muzzarella",
    producto_descripcion: str | None = "Pizza con salsa de tomate y queso mozzarella",
    categoria_nombre: str = "Pizzas",
    presentacion_id: int = 11,
    presentacion_codigo: str = "chica",
    presentacion_descripcion: str = "Chica",
) -> ProductEmbeddingCatalogProjection:
    return ProductEmbeddingCatalogProjection(
        producto_id=producto_id,
        producto_presentacion_id=producto_presentacion_id,
        producto_nombre=producto_nombre,
        producto_descripcion=producto_descripcion,
        categoria_nombre=categoria_nombre,
        presentacion_id=presentacion_id,
        presentacion_codigo=presentacion_codigo,
        presentacion_descripcion=presentacion_descripcion,
    )


def _alias(
    *,
    alias_id: int,
    alias: str = "Muzza",
    alias_normalizado: str = "muzza",
    scope: ProductEmbeddingAliasScope = "product",
    activo: bool = True,
    id_producto_presentacion: int | None = None,
) -> ProductEmbeddingAliasInput:
    return ProductEmbeddingAliasInput(
        id=alias_id,
        alias=alias,
        alias_normalizado=alias_normalizado,
        scope=scope,
        activo=activo,
        id_producto_presentacion=id_producto_presentacion,
    )


class HashShapeTest(unittest.TestCase):
    def test_hash_is_64_lowercase_hex(self):
        document = ProductEmbeddingDocument(
            producto_id=7,
            producto_presentacion_id=31,
            source_type="canonical",
            source_record_id=None,
            source_text="Pizza de Muzzarella Chica",
            normalized_text="pizza de muzzarella chica",
            content_hash=hashlib.sha256(b"spec").hexdigest(),
        )
        self.assertEqual(len(document.content_hash), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in document.content_hash))


class ProductEmbeddingDocumentBuilderCanonicalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_canonical_uses_presentacion_descripcion(self):
        projection = _projection(presentacion_codigo="chica", presentacion_descripcion="Chica")
        docs = self.builder.build(projection, ())
        canonical = _by_type(docs, "canonical")
        self.assertEqual(canonical.source_text, "Pizza de Muzzarella Chica")
        self.assertEqual(canonical.normalized_text, "pizza de muzzarella chica")
        self.assertIsNone(canonical.source_record_id)
        self.assertEqual(canonical.source_type, "canonical")

    def test_canonical_falls_back_to_presentacion_codigo(self):
        projection = _projection(
            producto_nombre="Coca",
            presentacion_codigo="1L",
            presentacion_descripcion="",
        )
        docs = self.builder.build(projection, ())
        canonical = _by_type(docs, "canonical")
        self.assertEqual(canonical.source_text, "Coca 1L")
        self.assertEqual(canonical.normalized_text, "coca 1l")

    def test_canonical_uses_unidad_vs_1_litro_distinction(self):
        unidad = _projection(
            producto_presentacion_id=11,
            presentacion_codigo="unidad",
            presentacion_descripcion="Unidad",
        )
        one_litro = _projection(
            producto_presentacion_id=12,
            presentacion_codigo="1L",
            presentacion_descripcion="1 Litro",
        )
        unidad_canonical = _by_type(self.builder.build(unidad, ()), "canonical")
        one_litro_canonical = _by_type(self.builder.build(one_litro, ()), "canonical")
        self.assertNotEqual(unidad_canonical.source_text, one_litro_canonical.source_text)
        self.assertNotEqual(unidad_canonical.content_hash, one_litro_canonical.content_hash)


class ProductEmbeddingDocumentBuilderDescriptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_description_document_included_when_set(self):
        projection = _projection()
        docs = self.builder.build(projection, ())
        description = _by_type(docs, "description")
        self.assertEqual(
            description.source_text,
            "Pizza de Muzzarella Chica. Pizza con salsa de tomate y queso mozzarella.",
        )
        self.assertIsNone(description.source_record_id)
        self.assertEqual(
            description.normalized_text,
            "pizza de muzzarella chica pizza con salsa de tomate y queso mozzarella",
        )

    def test_description_omitted_when_empty(self):
        projection = _projection(producto_descripcion="")
        docs = self.builder.build(projection, ())
        self.assertEqual(_types(docs), ["canonical", "combined"])

    def test_description_omitted_when_none(self):
        projection = _projection(producto_descripcion=None)
        docs = self.builder.build(projection, ())
        self.assertEqual(_types(docs), ["canonical", "combined"])

    def test_description_omitted_when_whitespace(self):
        projection = _projection(producto_descripcion="   \t  ")
        docs = self.builder.build(projection, ())
        self.assertEqual(_types(docs), ["canonical", "combined"])


class ProductEmbeddingDocumentBuilderCombinedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_combined_with_description(self):
        projection = _projection()
        docs = self.builder.build(projection, ())
        combined = _by_type(docs, "combined")
        self.assertEqual(
            combined.source_text,
            "Categoría: Pizzas. Producto: Pizza de Muzzarella. "
            "Descripción: Pizza con salsa de tomate y queso mozzarella. "
            "Presentación: Chica.",
        )

    def test_combined_without_description_omits_segment(self):
        projection = _projection(producto_descripcion="")
        docs = self.builder.build(projection, ())
        combined = _by_type(docs, "combined")
        self.assertIn("Categoría: Pizzas.", combined.source_text)
        self.assertIn("Producto: Pizza de Muzzarella.", combined.source_text)
        self.assertIn("Presentación: Chica.", combined.source_text)
        self.assertNotIn("Descripción:", combined.source_text)
        self.assertNotIn("None", combined.source_text)
        self.assertNotIn("  ", combined.source_text)

    def test_combined_without_description_uses_no_double_space(self):
        projection = _projection(producto_descripcion=None)
        docs = self.builder.build(projection, ())
        combined = _by_type(docs, "combined")
        self.assertNotIn("  ", combined.source_text)


class ProductEmbeddingDocumentBuilderAliasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_product_wide_alias_included_on_every_presentation(self):
        product_alias = _alias(alias_id=99, alias="Muzza", alias_normalizado="muzza")
        chica = _projection(producto_presentacion_id=11, presentacion_descripcion="Chica")
        grande = _projection(producto_presentacion_id=12, presentacion_descripcion="Grande")
        chica_docs = self.builder.build(chica, (product_alias,))
        grande_docs = self.builder.build(grande, (product_alias,))
        chica_alias = _by_type(chica_docs, "alias")
        grande_alias = _by_type(grande_docs, "alias")
        self.assertEqual(chica_alias.source_text, "Muzza Chica")
        self.assertEqual(grande_alias.source_text, "Muzza Grande")
        self.assertEqual(chica_alias.source_record_id, 99)
        self.assertEqual(grande_alias.source_record_id, 99)
        self.assertNotEqual(chica_alias.content_hash, grande_alias.content_hash)

    def test_product_wide_alias_does_not_require_presentation_match(self):
        product_alias = _alias(alias_id=99, alias="Muzza", alias_normalizado="muzza")
        for pp_id in (11, 12, 13, 99):
            docs = self.builder.build(
                _projection(producto_presentacion_id=pp_id), (product_alias,)
            )
            self.assertIn("alias", _types(docs))

    def test_presentation_specific_alias_raises_on_sibling(self):
        chica_specific = _alias(
            alias_id=77,
            alias="Coca de litro",
            alias_normalizado="coca de litro",
            scope="product_presentacion",
            id_producto_presentacion=42,
        )
        chica = _projection(producto_presentacion_id=42, presentacion_descripcion="Chica")
        grande = _projection(producto_presentacion_id=43, presentacion_descripcion="Grande")
        chica_docs = self.builder.build(chica, (chica_specific,))
        self.assertIn("alias", _types(chica_docs))
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(grande, (chica_specific,))

    def test_alias_documents_sorted_by_alias_normalizado_then_id(self):
        aliases = (
            _alias(alias_id=30, alias="Muzza", alias_normalizado="muzza"),
            _alias(alias_id=10, alias="Grande", alias_normalizado="grande"),
            _alias(alias_id=20, alias="Chica", alias_normalizado="chica"),
        )
        docs = self.builder.build(_projection(), aliases)
        alias_docs = [doc for doc in docs if doc.source_type == "alias"]
        self.assertEqual(
            [doc.source_record_id for doc in alias_docs],
            [20, 10, 30],
        )

    def test_duplicate_alias_normalizado_keeps_lowest_id(self):
        aliases = (
            _alias(alias_id=50, alias="Muzza", alias_normalizado="muzza"),
            _alias(alias_id=10, alias="Muzza", alias_normalizado="muzza"),
            _alias(alias_id=30, alias="Muzza", alias_normalizado="muzza"),
        )
        docs = self.builder.build(_projection(), aliases)
        alias_docs = [doc for doc in docs if doc.source_type == "alias"]
        self.assertEqual(len(alias_docs), 1)
        self.assertEqual(alias_docs[0].source_record_id, 10)

    def test_inactive_alias_excluded(self):
        aliases = (
            _alias(alias_id=99, alias="Muzza", activo=True),
            _alias(alias_id=100, alias="Mozza", alias_normalizado="mozza", activo=False),
        )
        docs = self.builder.build(_projection(), aliases)
        alias_docs = [doc for doc in docs if doc.source_type == "alias"]
        self.assertEqual(len(alias_docs), 1)
        self.assertEqual(alias_docs[0].source_record_id, 99)

    def test_presentation_code_not_emitted_as_alias(self):
        projection = _projection(presentacion_codigo="unidad", presentacion_descripcion="")
        docs = self.builder.build(projection, ())
        alias_docs = [doc for doc in docs if doc.source_type == "alias"]
        self.assertEqual(alias_docs, [])


class ProductEmbeddingDocumentBuilderPresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_different_presentations_of_same_product_differ(self):
        chica = _projection(
            producto_presentacion_id=11,
            presentacion_codigo="chica",
            presentacion_descripcion="Chica",
        )
        grande = _projection(
            producto_presentacion_id=12,
            presentacion_codigo="grande",
            presentacion_descripcion="Grande",
        )
        docs_chica = self.builder.build(chica, ())
        docs_grande = self.builder.build(grande, ())
        canonical_chica = _by_type(docs_chica, "canonical")
        canonical_grande = _by_type(docs_grande, "canonical")
        combined_chica = _by_type(docs_chica, "combined")
        combined_grande = _by_type(docs_grande, "combined")
        self.assertNotEqual(canonical_chica.source_text, canonical_grande.source_text)
        self.assertNotEqual(canonical_chica.content_hash, canonical_grande.content_hash)
        self.assertNotEqual(combined_chica.source_text, combined_grande.source_text)
        self.assertNotEqual(combined_chica.content_hash, combined_grande.content_hash)

    def test_missing_presentation_text_raises_with_no_documents(self):
        projection = _projection(presentacion_codigo="", presentacion_descripcion="")
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(projection, ())


class ProductEmbeddingDocumentBuilderHashTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_hash_is_deterministic(self):
        projection = _projection()
        first = self.builder.build(projection, ())
        second = self.builder.build(projection, ())
        self.assertEqual(
            [doc.content_hash for doc in first],
            [doc.content_hash for doc in second],
        )

    def test_hash_inputs_match_spec(self):
        projection = _projection(producto_presentacion_id=31)
        docs = self.builder.build(projection, ())
        canonical = _by_type(docs, "canonical")
        expected_raw = (
            "31\x1fcanonical\x1f\x1fpizza de muzzarella chica"
        )
        expected = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()
        self.assertEqual(canonical.content_hash, expected)

    def test_changing_product_name_changes_canonical_hash(self):
        a = self.builder.build(_projection(producto_nombre="Pizza de Muzzarella"), ())
        b = self.builder.build(_projection(producto_nombre="Pizza de Jamón y Queso"), ())
        self.assertNotEqual(
            _by_type(a, "canonical").content_hash,
            _by_type(b, "canonical").content_hash,
        )

    def test_changing_description_changes_description_hash_only(self):
        a = self.builder.build(
            _projection(producto_descripcion="Pizza con salsa de tomate y queso mozzarella"),
            (),
        )
        b = self.builder.build(
            _projection(producto_descripcion="Pizza con extra queso"),
            (),
        )
        self.assertNotEqual(
            _by_type(a, "description").content_hash,
            _by_type(b, "description").content_hash,
        )
        self.assertEqual(
            _by_type(a, "canonical").content_hash,
            _by_type(b, "canonical").content_hash,
        )

    def test_changing_alias_changes_only_alias_hash(self):
        aliases_a = (_alias(alias_id=99, alias="Muzza", alias_normalizado="muzza"),)
        aliases_b = (_alias(alias_id=99, alias="Mozza", alias_normalizado="mozza"),)
        a = self.builder.build(_projection(), aliases_a)
        b = self.builder.build(_projection(), aliases_b)
        self.assertNotEqual(
            _by_type(a, "alias").content_hash,
            _by_type(b, "alias").content_hash,
        )
        self.assertEqual(
            _by_type(a, "canonical").content_hash,
            _by_type(b, "canonical").content_hash,
        )
        self.assertEqual(
            _by_type(a, "combined").content_hash,
            _by_type(b, "combined").content_hash,
        )

    def test_changing_category_changes_combined_hash(self):
        a = self.builder.build(_projection(categoria_nombre="Pizzas"), ())
        b = self.builder.build(_projection(categoria_nombre="Empanadas"), ())
        self.assertNotEqual(
            _by_type(a, "combined").content_hash,
            _by_type(b, "combined").content_hash,
        )


class ProductEmbeddingDocumentBuilderOrderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_output_order_is_stable(self):
        aliases = (
            _alias(alias_id=99, alias="Muzza", alias_normalizado="muzza"),
            _alias(alias_id=10, alias="Grande", alias_normalizado="grande"),
        )
        first = self.builder.build(_projection(), aliases)
        second = self.builder.build(_projection(), aliases)
        self.assertEqual(_types(first), ["canonical", "description", "alias", "alias", "combined"])
        self.assertEqual(_types(second), _types(first))
        self.assertEqual(
            [doc.source_record_id for doc in first if doc.source_type == "alias"],
            [10, 99],
        )


class ProductEmbeddingDocumentBuilderUnicodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_accented_and_plain_inputs_normalize_to_same_canonical(self):
        a = _projection(producto_nombre="Muzzá")
        b = _projection(producto_nombre="muzza")
        docs_a = self.builder.build(a, ())
        docs_b = self.builder.build(b, ())
        canonical_a = _by_type(docs_a, "canonical")
        canonical_b = _by_type(docs_b, "canonical")
        self.assertEqual(canonical_a.normalized_text, canonical_b.normalized_text)
        self.assertEqual(canonical_a.normalized_text, "muzza chica")
        self.assertIn("Muzzá", canonical_a.source_text)
        self.assertNotIn("Muzzá", canonical_b.source_text)

    def test_muzzarella_preserves_consonant_cluster_under_accent_strip(self):
        a = _projection(producto_nombre="Muzzárella")
        b = _projection(producto_nombre="muzzarella")
        docs_a = self.builder.build(a, ())
        docs_b = self.builder.build(b, ())
        canonical_a = _by_type(docs_a, "canonical")
        canonical_b = _by_type(docs_b, "canonical")
        self.assertEqual(canonical_a.normalized_text, canonical_b.normalized_text)
        self.assertEqual(canonical_a.normalized_text, "muzzarella chica")
        self.assertIn("Muzzárella", canonical_a.source_text)

    def test_whitespace_variants_collapse_consistently(self):
        a = _projection(producto_nombre="Pizza  de   Muzzárella")
        b = _projection(producto_nombre="pizza de muzzarella")
        docs_a = self.builder.build(a, ())
        docs_b = self.builder.build(b, ())
        canonical_a = _by_type(docs_a, "canonical")
        canonical_b = _by_type(docs_b, "canonical")
        self.assertEqual(canonical_a.normalized_text, canonical_b.normalized_text)
        self.assertEqual(canonical_a.normalized_text, "pizza de muzzarella chica")


class ProductEmbeddingDocumentBuilderValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ProductEmbeddingDocumentBuilder()

    def test_invalid_product_id_raises_and_produces_no_documents(self):
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_id=0), ())
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_id=-1), ())

    def test_invalid_producto_presentacion_id_raises(self):
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_presentacion_id=0), ())

    def test_empty_producto_nombre_raises(self):
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_nombre=""), ())
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_nombre="   "), ())

    def test_cross_presentation_alias_raises(self):
        alien = _alias(
            alias_id=11,
            alias="Coca de litro",
            alias_normalizado="coca de litro",
            scope="product_presentacion",
            id_producto_presentacion=999,
        )
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(producto_presentacion_id=31), (alien,))

    def test_invalid_alias_scope_raises(self):
        bad = _alias(
            alias_id=11,
            alias="Muzza",
            alias_normalizado="muzza",
            scope=cast(ProductEmbeddingAliasScope, "invalid_scope"),
        )
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(_projection(), (bad,))

    def test_missing_presentation_text_raises(self):
        projection = _projection(presentacion_codigo="", presentacion_descripcion="")
        with self.assertRaises(InvalidProductEmbeddingDocument):
            self.builder.build(projection, ())


class ProductEmbeddingDocumentBuilderInfraImportTest(unittest.TestCase):
    def test_module_does_not_import_infrastructure(self):
        import backend.embeddings.product_embedding_document_builder as module

        source = module.__file__
        assert source is not None
        with open(source, "r", encoding="utf-8") as handle:
            content = handle.read()
        for forbidden in (
            "import sqlalchemy",
            "from sqlalchemy",
            "backend.repositories",
            "backend.recognizers",
            "backend.llm",
            "backend.models",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "import pgvector",
            "from pgvector",
        ):
            self.assertNotIn(forbidden, content)


def _types(documents: list[ProductEmbeddingDocument]) -> list[str]:
    return [doc.source_type for doc in documents]


def _by_type(
    documents: list[ProductEmbeddingDocument],
    source_type: str,
) -> ProductEmbeddingDocument:
    for doc in documents:
        if doc.source_type == source_type:
            return doc
    raise AssertionError(f"no document with source_type={source_type!r}")


if __name__ == "__main__":
    unittest.main()
