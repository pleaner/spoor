# Prototype Report — Later Pipeline Stages on Postgres

A throwaway prototype to feel out whether the **evaluate → categorise** stages of `spoor`
can run against a database instead of the filesystem. Built on the `spike/postgres-db`
branch. Not the implementation we ship — a learning exercise.

## Table of Contents

- [Verdict](#verdict)
- [What was built](#what-was-built)
- [The data model](#the-data-model)
- [Results](#results)
- [How to inspect it](#how-to-inspect-it)
- [Decisions taken](#decisions-taken)
- [What a real build would add](#what-a-real-build-would-add)

## Verdict

It works. The existing file corpus imports cleanly into Postgres, and categorise runs
**entirely off the database** — reading its corpus from rows, not from a directory walk —
and produces the same category-to-property results, with capacity-based exclusions intact.
Nine unit tests pass against a live Postgres container. The shape is sound; nothing about
the pipeline resisted the move.

## What was built

Everything lives under `spike_db/`:

- **A persistent Postgres container** (`docker-compose.yml`) on port 5433 — deliberately
  separate from Magic Lake's, with a named volume that survives restarts. Tables are never
  dropped, so the data stays inspectable between runs.
- **The schema** (`schema.sql`) — four tables and one readable view.
- **A persistence layer** (`db.py`, `store.py`) — a thin psycopg2 wrapper; every write is an
  insert-or-update keyed on stable identity, so re-running is idempotent.
- **An importer** (`importer.py`) — loads the existing `data/evaluated/` tree into the
  database and seeds the fixed category taxonomy.
- **Categorise off the database** (`categorise_db.py`) — reads its corpus from rows,
  recomputes each property's average-daily-rate range for a category's party, and writes the
  category-to-property rows.
- **Unit tests** (`tests/test_spike.py`) — run against the live container.

## The data model

The same four ideas described in the design doc: `properties` (the anchor), `evaluations`
(the middle-stage payload, kept so categorise can rerun independently), `categories` (the
fourteen archetypes), and `category_membership` (the relationship that matters, with the
price range and feasibility that justify it). Pricing runs are deliberately not stored —
they are recomputed on demand.

![Entity-relationship diagram](artifacts/erd.png)

The authoritative definitions are in `schema.sql`; a dump of the live schema is in
`artifacts/ddl_live.sql`, and the editable diagram is `artifacts/erd.excalidraw`.

## Results

- **Imported** 7 properties and 14 categories from the existing files.
- **Categorise off the database** produced 93 included memberships across the 14 categories.
- The exclusions are real, not a pass-through: a six-person multi-generation family fits
  four of the seven properties and is correctly excluded from the three that cannot seat the
  party (zero feasible months).
- A single readable query (`SELECT * FROM category_listing`) answers "what is in this
  category, ranked by price, and why" — the readability the design called for.
- **9 / 9 unit tests pass**, covering idempotent import, the JSON payload round-trip, reading
  the corpus from the database, ranked membership, capacity exclusions, and idempotent reruns.

## How to inspect it

The container keeps its data. To look at what was written:

```bash
docker compose -f spike_db/docker-compose.yml up -d        # if not already running
psql postgresql://postgres:postgres@localhost:5433/spoor_spike -c 'SELECT * FROM category_listing;'
```

To rebuild from scratch:

```bash
.venv/bin/python -m spike_db.importer        # schema + categories + evaluations
.venv/bin/python -m spike_db.categorise_db   # categorise off the database
.venv/bin/python -m pytest spike_db/tests -v
```

## Decisions taken

- **Postgres, not SQLite.** It is the house database; the prototype uses the same image
  Magic Lake runs.
- **Keep the evaluation in the database, drop pricing runs.** Persisting evaluations is what
  lets categorise rerun on its own; pricing is cheap to recompute, so it is not stored.
- **Optimise the category-to-property relationship for reading.** A flat membership table
  plus a readable view, so the archetype listings are legible at a glance.

## What a real build would add

This prototype skips the parts a shipped version needs: schema migrations rather than a
single `schema.sql`, wiring the persistence layer into the actual skills (the prototype
imports finished files rather than having evaluate write rows as it runs), and an export
path that regenerates the human-readable files from the database. Those are scoped in the
design doc on the `teamwork` branch.
