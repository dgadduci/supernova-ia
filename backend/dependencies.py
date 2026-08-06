import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config.database_url import normalize_database_url

DEFAULT_URL = "postgresql+psycopg:///supernova_test"

_engine = create_engine(
    normalize_database_url(os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL))
)
_SessionLocal = sessionmaker(
    bind=_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
