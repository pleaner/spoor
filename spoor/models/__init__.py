"""SQLModel table definitions for the database-backed evaluate + categorise stages.

This package is imported only when the optional ``db`` extra is installed; the
deterministic core (``spoor.benchmark``, ``spoor.categories``, the generated pricing
scripts) never imports it and stays stdlib-only.

The one rule that matters: **every model class must be imported here** so that
``SQLModel.metadata`` (and therefore Alembic autogenerate and ``create_all``) sees
the table. A model nobody imports is invisible to migrations.
"""

from __future__ import annotations

from spoor.models.category import Category, CategoryMembership
from spoor.models.evaluation import Evaluation
from spoor.models.property import Property

__all__ = ["Property", "Evaluation", "Category", "CategoryMembership"]
