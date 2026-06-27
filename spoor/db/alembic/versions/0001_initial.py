"""initial schema — properties, evaluations, categories, category_membership + view

Hand-authored (the schema is fixed by the PRD): the four tables along the join path
categories 1—N category_membership N—1 properties 1—1 evaluations, plus the readable
``category_listing`` view (Alembic autogenerate does not emit views).

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lodge_slug", sa.String(length=255), nullable=False),
        sa.Column("property_slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lodge_label", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("benchmark_year", sa.Integer(), nullable=True),
        sa.Column(
            "benchmark_applicable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("inclusion", sa.Text(), nullable=True),
        sa.Column("pricing_script_path", sa.Text(), nullable=True),
        sa.Column("dossier_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("lodge_slug", "property_slug", name="uq_property_identity"),
    )
    op.create_index("ix_properties_lodge_slug", "properties", ["lodge_slug"])
    op.create_index("ix_properties_property_slug", "properties", ["property_slug"])

    op.create_table(
        "evaluations",
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("adr_payload", postgresql.JSONB(), nullable=False),
        sa.Column("prose", postgresql.JSONB(), nullable=False),
        sa.Column("fx_date", sa.Date(), nullable=True),
        sa.Column(
            "evaluated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "categories",
        sa.Column("slug", sa.String(length=255), primary_key=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("ages", postgresql.ARRAY(sa.Integer()), nullable=False),
    )

    op.create_table(
        "category_membership",
        sa.Column(
            "category_slug",
            sa.String(length=255),
            sa.ForeignKey("categories.slug", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("adr_low_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("adr_high_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_membership_category", "category_membership", ["category_slug", "rank"]
    )
    op.create_index("idx_membership_property", "category_membership", ["property_id"])

    # Readable surface: "what is in this category and why", one query.
    op.execute(
        """
        CREATE VIEW category_listing AS
        SELECT
            c.label         AS category,
            cm.rank         AS rank,
            p.name          AS property,
            p.lodge_label   AS lodge,
            cm.adr_low_usd  AS adr_low_usd,
            cm.adr_high_usd AS adr_high_usd,
            cm.reasoning    AS reasoning,
            c.slug          AS category_slug,
            p.property_slug AS property_slug
        FROM category_membership cm
        JOIN categories c ON c.slug = cm.category_slug
        JOIN properties p ON p.id   = cm.property_id
        ORDER BY c.label, cm.rank, p.name
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS category_listing")
    op.drop_index("idx_membership_property", table_name="category_membership")
    op.drop_index("idx_membership_category", table_name="category_membership")
    op.drop_table("category_membership")
    op.drop_table("categories")
    op.drop_table("evaluations")
    op.drop_index("ix_properties_property_slug", table_name="properties")
    op.drop_index("ix_properties_lodge_slug", table_name="properties")
    op.drop_table("properties")
