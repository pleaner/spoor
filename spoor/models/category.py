"""The ``categories`` and ``category_membership`` tables.

``categories`` mirrors the fixed fourteen-archetype taxonomy from
``spoor.categories.CATEGORIES`` (one authoritative source). ``category_membership`` is
the relationship that matters most, and it is **positives-only**: a row exists for a
property only when the model judges it genuinely suits the category. It carries the
deterministic numbers (``rank`` + USD average-daily-rate range) and the one grounded
``reasoning`` paragraph that justifies the fit (``NOT NULL``). There is deliberately no
``suitable`` flag, no ``included`` column, and no stored feasibility count — an excluded
property simply leaves no row.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class Category(SQLModel, table=True):
    __tablename__ = "categories"

    slug: str = Field(primary_key=True, max_length=255)
    label: str = Field(max_length=255)
    # The party (ages) handed to each property's price() for this archetype.
    ages: List[int] = Field(sa_column=Column(ARRAY(Integer), nullable=False))


class CategoryMembership(SQLModel, table=True):
    __tablename__ = "category_membership"
    __table_args__ = (
        Index("idx_membership_category", "category_slug", "rank"),
        Index("idx_membership_property", "property_id"),
    )

    category_slug: str = Field(
        sa_column=Column(
            String(255),
            ForeignKey("categories.slug", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    property_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("properties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # Ascending-average-daily-rate order within the category.
    rank: int = Field(nullable=False)
    adr_low_usd: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(12, 2)))
    adr_high_usd: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(12, 2)))
    # The model's grounded one-paragraph justification — required.
    reasoning: str = Field(sa_column=Column(Text, nullable=False))
