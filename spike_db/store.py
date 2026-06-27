"""Persistence layer for the spike — UPSERTs in, queries out.

This is the seam the deterministic core would call instead of writing files. Every
write is an UPSERT keyed on stable identity, so re-running is idempotent (the file
pipeline can't do this — it overwrites sibling files and hopes the slug matched).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from psycopg2.extras import Json, RealDictCursor


# ── writes ───────────────────────────────────────────────────────────────────

def upsert_property(conn, *, lodge_slug: str, property_slug: str, name: str,
                    currency: Optional[str], benchmark_year: Optional[int],
                    benchmark_applicable: bool, inclusion: Optional[str],
                    pricing_script_path: Optional[str],
                    dossier_path: Optional[str]) -> int:
    """Insert or update a property; return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO properties
                (lodge_slug, property_slug, name, currency, benchmark_year,
                 benchmark_applicable, inclusion, pricing_script_path, dossier_path)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (lodge_slug, property_slug) DO UPDATE SET
                name = EXCLUDED.name,
                currency = EXCLUDED.currency,
                benchmark_year = EXCLUDED.benchmark_year,
                benchmark_applicable = EXCLUDED.benchmark_applicable,
                inclusion = EXCLUDED.inclusion,
                pricing_script_path = EXCLUDED.pricing_script_path,
                dossier_path = EXCLUDED.dossier_path
            RETURNING id
            """,
            (lodge_slug, property_slug, name, currency, benchmark_year,
             benchmark_applicable, inclusion, pricing_script_path, dossier_path),
        )
        return cur.fetchone()[0]


def put_evaluation(conn, *, property_id: int, adr_json: dict,
                   fx_date: Optional[str]) -> None:
    """Persist the middle-ETL evaluation blob (UPSERT on property_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluations (property_id, adr_json, fx_date)
            VALUES (%s, %s, %s)
            ON CONFLICT (property_id) DO UPDATE SET
                adr_json = EXCLUDED.adr_json,
                fx_date = EXCLUDED.fx_date,
                evaluated_at = now()
            """,
            (property_id, Json(adr_json), fx_date),
        )


def upsert_category(conn, *, slug: str, label: str, ages: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO categories (slug, label, ages)
            VALUES (%s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, ages = EXCLUDED.ages
            """,
            (slug, label, list(ages)),
        )


def replace_category_membership(conn, *, category_slug: str, rows: list[dict]) -> None:
    """Atomically rewrite a category's membership (delete then bulk insert).

    `rows` items: {property_id, rank, low_usd, high_usd, feasible_months, included}.
    Wrapped so a rerun of one category is all-or-nothing.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM category_membership WHERE category_slug = %s",
                    (category_slug,))
        for r in rows:
            cur.execute(
                """
                INSERT INTO category_membership
                    (category_slug, property_id, rank, low_usd, high_usd,
                     feasible_months, included)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (category_slug, r["property_id"], r["rank"], r["low_usd"],
                 r["high_usd"], r["feasible_months"], r["included"]),
            )


# ── reads ────────────────────────────────────────────────────────────────────

def iter_evaluated_properties(conn) -> list[dict]:
    """The DB-backed replacement for categories.discover_properties().

    categorise reads its corpus from HERE instead of globbing data/evaluated — this
    is what lets it rerun independently off the database.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.id AS property_id, p.lodge_slug, p.property_slug, p.name,
                   p.benchmark_year, p.pricing_script_path
            FROM properties p
            JOIN evaluations e ON e.property_id = p.id
            ORDER BY p.lodge_slug, p.property_slug
            """
        )
        return [dict(r) for r in cur.fetchall()]


def category_listing(conn, category_slug: Optional[str] = None) -> list[dict]:
    """The human-readable category→property surface (the `category_listing` view)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if category_slug:
            cur.execute(
                "SELECT * FROM category_listing WHERE category_slug = %s", (category_slug,))
        else:
            cur.execute("SELECT * FROM category_listing")
        return [dict(r) for r in cur.fetchall()]


def counts(conn) -> dict[str, int]:
    """Quick row counts for the report."""
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for t in ("properties", "evaluations", "categories", "category_membership"):
            cur.execute(f"SELECT count(*) FROM {t}")
            out[t] = cur.fetchone()[0]
    return out
