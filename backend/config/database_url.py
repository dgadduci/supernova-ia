"""Database URL normalization shared by application and Alembic startup."""


def normalize_database_url(url: str) -> str:
    """Select the installed psycopg v3 dialect for bare PostgreSQL URLs."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url
