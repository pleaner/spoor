"""The ``properties`` table — the anchor entity.

One row per bookable camp, identified by ``(lodge_slug, property_slug)`` (exactly what
the file-path convention encoded). Carries the lodge-group display label sourced from
the raw dossier's ``**Lodge group:**`` line — a provenance the file-era ``adr.json``
never recorded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Property(SQLModel, table=True):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("lodge_slug", "property_slug", name="uq_property_identity"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    lodge_slug: str = Field(index=True, max_length=255)
    property_slug: str = Field(index=True, max_length=255)
    name: str = Field(max_length=255)
    # Lodge-group display label, e.g. "Londolozi" / "Tanda Tula".
    lodge_label: Optional[str] = Field(default=None, max_length=255)
    currency: Optional[str] = Field(default=None, max_length=10)
    benchmark_year: Optional[int] = Field(default=None)
    benchmark_applicable: bool = Field(default=True)
    inclusion: Optional[str] = Field(default=None)
    # The generated pricing script stays a real file; categorise loads it by path.
    pricing_script_path: Optional[str] = Field(default=None)
    dossier_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
