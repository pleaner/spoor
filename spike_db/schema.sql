-- spoor file→DB spike — schema for the LATER ETL stages (evaluate + categorise).
--
-- Design decisions (from the design narration, 2026-06-27):
--   * categories + the category↔property relationship are the PAYLOAD — modelled
--     for easy reading at a later stage (see the readable view at the bottom).
--   * evaluations IS persisted (the middle ETL step: raw → evaluation) — not for
--     its own sake, but because it lets categorise rerun INDEPENDENTLY off the DB.
--   * pricing runs are NOT persisted — they're cheap to recompute, so there is
--     deliberately no pricing_runs table. categorise recomputes price() on the fly
--     from the (file-resident) generated pricing script.
--
-- This is a throwaway prototype. Tables are created IF NOT EXISTS and never dropped
-- by the tooling, so the data survives across runs for inspection.

-- ─────────────────────────────────────────────────────────────────────────────
-- properties — the anchor entity. Identity = (lodge_slug, property_slug), which is
-- exactly what the file-path convention encodes today.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS properties (
    id                   SERIAL PRIMARY KEY,
    lodge_slug           TEXT    NOT NULL,
    property_slug        TEXT    NOT NULL,
    name                 TEXT    NOT NULL,
    currency             TEXT,                         -- "ZAR" | "BWP" | ...
    benchmark_year       INTEGER,
    benchmark_applicable BOOLEAN NOT NULL DEFAULT TRUE,
    inclusion            TEXT,
    pricing_script_path  TEXT,                         -- file stays canonical; recomputed, not persisted
    dossier_path         TEXT,                         -- data/raw/<lodge>/<property>.md
    UNIQUE (lodge_slug, property_slug)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- evaluations — the middle ETL step output (raw → evaluation), one row per property.
-- The full adr.json blob is kept as JSONB (reproducible source of truth, queryable).
-- Persisting this is what makes categorise independently rerunnable off the DB.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evaluations (
    property_id   INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    adr_json      JSONB   NOT NULL,                    -- the whole benchmark dict
    fx_date       DATE,                                -- pulled out of the blob for filtering
    evaluated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- categories — the fixed traveller taxonomy. The archetypes that come out the
-- other side; this is what the consumer cares about most.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    slug   TEXT PRIMARY KEY,                           -- e.g. 'honeymoon-couple'
    label  TEXT    NOT NULL,                           -- e.g. 'Honeymoon couple'
    ages   INTEGER[] NOT NULL                          -- the party handed to price()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- category_membership — THE relationship. Which properties belong to which
-- category, and the numbers that justify it. Kept deliberately flat + readable.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_membership (
    category_slug    TEXT    NOT NULL REFERENCES categories(slug)  ON DELETE CASCADE,
    property_id      INTEGER NOT NULL REFERENCES properties(id)    ON DELETE CASCADE,
    rank             INTEGER,                           -- ascending-ADR order within the category
    low_usd          NUMERIC(12,2),                     -- RACK ADR low  (NULL = party never fits)
    high_usd         NUMERIC(12,2),                     -- RACK ADR high
    feasible_months  INTEGER NOT NULL DEFAULT 0,        -- 0 = excluded on capacity grounds
    included         BOOLEAN NOT NULL DEFAULT FALSE,    -- feasible_months > 0
    PRIMARY KEY (category_slug, property_id)
);

CREATE INDEX IF NOT EXISTS idx_membership_category ON category_membership(category_slug, rank);
CREATE INDEX IF NOT EXISTS idx_membership_property ON category_membership(property_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- The "easy to read at a later stage" surface: a flat, human-scannable join of
-- category → property with the justifying numbers. `SELECT * FROM category_listing`.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW category_listing AS
SELECT
    c.label            AS category,
    cm.rank            AS rank,
    p.name             AS property,
    p.lodge_slug       AS lodge,
    cm.low_usd         AS adr_low_usd,
    cm.high_usd        AS adr_high_usd,
    cm.feasible_months AS feasible_months,
    cm.included        AS included,
    c.slug             AS category_slug,
    p.property_slug    AS property_slug
FROM category_membership cm
JOIN categories c ON c.slug = cm.category_slug
JOIN properties p ON p.id   = cm.property_id
ORDER BY c.label, cm.included DESC, cm.rank NULLS LAST, p.name;
