"""The ``evaluations`` table — the middle-stage output, one row per property.

Carries both the numeric average-daily-rate payload (the full benchmark dict, incl. any
merged reputation) and the model-authored grounded prose, each as queryable ``JSONB``.
Persisting the evaluation is what lets categorise run independently off the database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evaluation(SQLModel, table=True):
    __tablename__ = "evaluations"

    property_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("properties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # The full benchmark dict — average-daily-rate payload + merged reputation.
    adr_payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    # Grounded prose keyed by section: value / completeness / fit /
    # self-competitiveness / reputation (reputation present only when reviews exist).
    prose: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    fx_date: Optional[date] = Field(default=None)
    evaluated_at: datetime = Field(default_factory=_utcnow)
