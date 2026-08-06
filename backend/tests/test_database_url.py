import unittest

from backend.config.database_url import normalize_database_url


class NormalizeDatabaseUrlTest(unittest.TestCase):
    def test_bare_postgresql_url_uses_psycopg_v3(self) -> None:
        self.assertEqual(
            normalize_database_url("postgresql://user:password@host:5432/database"),
            "postgresql+psycopg://user:password@host:5432/database",
        )

    def test_legacy_postgres_url_uses_psycopg_v3(self) -> None:
        self.assertEqual(
            normalize_database_url("postgres://user:password@host/database"),
            "postgresql+psycopg://user:password@host/database",
        )

    def test_explicit_dialect_is_preserved(self) -> None:
        url = "postgresql+psycopg://user:password@host/database"

        self.assertEqual(normalize_database_url(url), url)
