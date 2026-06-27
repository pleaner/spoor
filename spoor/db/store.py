"""The store — upserts in, queries out.

A thin service module over the SQLModel models (the guide's rule: keep query/write
helpers here, not on the models). Every write is an upsert keyed on stable identity, so
re-running a stage is idempotent. Callers pass a ``Session`` and own the transaction
(commit/rollback), which is what lets the per-category write be atomic and the tests
roll back cleanly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, text
from sqlmodel import Session, select

from spoor.models import Category, CategoryMembership, Evaluation, Property


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_date(value: "str | date | None") -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


# ── writes ───────────────────────────────────────────────────────────────────

def upsert_property(
    session: Session,
    *,
    lodge_slug: str,
    property_slug: str,
    name: str,
    lodge_label: Optional[str] = None,
    currency: Optional[str] = None,
    benchmark_year: Optional[int] = None,
    benchmark_applicable: bool = True,
    inclusion: Optional[str] = None,
    pricing_script_path: Optional[str] = None,
    dossier_path: Optional[str] = None,
) -> int:
    """Insert or update a property on its ``(lodge_slug, property_slug)`` identity; return id."""
    obj = session.exec(
        select(Property).where(
            Property.lodge_slug == lodge_slug,
            Property.property_slug == property_slug,
        )
    ).first()
    if obj is None:
        obj = Property(lodge_slug=lodge_slug, property_slug=property_slug, name=name)
    obj.name = name
    obj.lodge_label = lodge_label
    obj.currency = currency
    obj.benchmark_year = benchmark_year
    obj.benchmark_applicable = benchmark_applicable
    obj.inclusion = inclusion
    obj.pricing_script_path = pricing_script_path
    obj.dossier_path = dossier_path
    obj.updated_at = _utcnow()
    session.add(obj)
    session.flush()
    return obj.id


def put_evaluation(
    session: Session,
    *,
    property_id: int,
    adr_payload: dict,
    prose: dict,
    fx_date: "str | date | None" = None,
) -> None:
    """Persist (upsert) the evaluation row for a property."""
    obj = session.get(Evaluation, property_id)
    if obj is None:
        obj = Evaluation(property_id=property_id, adr_payload=adr_payload, prose=prose)
    obj.adr_payload = adr_payload
    obj.prose = prose
    obj.fx_date = _as_date(fx_date)
    obj.evaluated_at = _utcnow()
    session.add(obj)
    session.flush()


def upsert_category(session: Session, *, slug: str, label: str, ages: list[int]) -> None:
    obj = session.get(Category, slug)
    if obj is None:
        obj = Category(slug=slug, label=label, ages=list(ages))
    obj.label = label
    obj.ages = list(ages)
    session.add(obj)
    session.flush()


def seed_categories(session: Session) -> int:
    """Mirror the fixed taxonomy from ``spoor.categories.CATEGORIES`` (idempotent)."""
    from spoor.categories import CATEGORIES

    for slug, spec in CATEGORIES.items():
        upsert_category(session, slug=slug, label=spec["label"], ages=spec["ages"])
    return len(CATEGORIES)


def replace_category_membership(
    session: Session, *, category_slug: str, rows: list[dict]
) -> None:
    """Atomically rewrite a category's membership (delete then insert).

    ``rows`` items: ``{property_id, rank, adr_low_usd, adr_high_usd, reasoning}``.
    Positives-only — only rows for genuinely-suitable properties are passed in. The
    caller's transaction makes a per-category rerun all-or-nothing.
    """
    session.execute(
        delete(CategoryMembership).where(CategoryMembership.category_slug == category_slug)
    )
    for r in rows:
        session.add(
            CategoryMembership(
                category_slug=category_slug,
                property_id=r["property_id"],
                rank=r["rank"],
                adr_low_usd=r["adr_low_usd"],
                adr_high_usd=r["adr_high_usd"],
                reasoning=r["reasoning"],
            )
        )
    session.flush()


# ── reads ────────────────────────────────────────────────────────────────────

def read_corpus(session: Session) -> list[dict]:
    """The DB-backed corpus categorise runs against (replaces globbing data/evaluated).

    Returns one dict per fully-evaluated property, carrying its identity, the locating
    fields the pricing loop needs (``benchmark_year``, ``pricing_script_path``), and the
    stored ``adr_payload`` / ``prose`` so the skill can ground suitability off the DB.
    """
    stmt = (
        select(Property, Evaluation)
        .join(Evaluation, Evaluation.property_id == Property.id)
        .order_by(Property.lodge_slug, Property.property_slug)
    )
    out: list[dict] = []
    for prop, ev in session.exec(stmt):
        out.append(
            {
                "property_id": prop.id,
                "lodge_slug": prop.lodge_slug,
                "property_slug": prop.property_slug,
                "name": prop.name,
                "lodge_label": prop.lodge_label,
                "benchmark_year": prop.benchmark_year,
                "pricing_script_path": prop.pricing_script_path,
                "adr_payload": ev.adr_payload,
                "prose": ev.prose,
            }
        )
    return out


def category_listing(session: Session, category_slug: Optional[str] = None) -> list[dict]:
    """The human-readable category→property surface (the ``category_listing`` view)."""
    sql = "SELECT * FROM category_listing"
    params: dict[str, Any] = {}
    if category_slug:
        sql += " WHERE category_slug = :slug"
        params["slug"] = category_slug
    rows = session.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def counts(session: Session) -> dict[str, int]:
    """Row counts for the import-verification report."""
    out: dict[str, int] = {}
    for t in ("properties", "evaluations", "categories", "category_membership"):
        out[t] = session.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
    return out
