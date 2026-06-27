"""Engine + session factory.

One engine, created from ``DATABASE_URL`` with a sane pool, following the house
pattern. The local default matches the ``docker-compose.yml`` container (port 5433),
so the same code runs against local / test / production unchanged.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5433/spoor"

_engine: Optional[Engine] = None


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            database_url(),
            pool_pre_ping=True,                       # silently reconnect dropped connections
            echo=bool(os.getenv("DB_ECHO")),          # DB_ECHO=1 logs every SQL statement
        )
    return _engine


@contextmanager
def get_session() -> Iterator[Session]:
    """A session bound to the process engine. Caller commits."""
    with Session(get_engine()) as session:
        yield session
