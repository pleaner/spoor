"""Programmatic Alembic — drives ``alembic upgrade head`` in-process.

``spoor db migrate`` calls :func:`upgrade_to_head`. The Alembic config is built from
paths relative to this package so it works regardless of the caller's cwd.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from spoor.db.connection import database_url

_HERE = Path(__file__).resolve().parent
ALEMBIC_INI = _HERE / "alembic.ini"
ALEMBIC_DIR = _HERE / "alembic"


def alembic_config(url: Optional[str] = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url or database_url())
    return cfg


def upgrade_to_head(url: Optional[str] = None) -> None:
    """Apply all pending migrations. Safe to run repeatedly (idempotent)."""
    command.upgrade(alembic_config(url), "head")


def current_revision(url: Optional[str] = None) -> None:
    command.current(alembic_config(url))
