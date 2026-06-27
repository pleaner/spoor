# Moving the Later Pipeline Stages from Files to a Database

A design overview for taking the **evaluate** and **categorise** stages of `spoor`
off the filesystem and into a database.

> **Status:** the design is agreed and the build is the subject of
> [issues/db-migration-prd.md](../../issues/db-migration-prd.md). A throwaway
> prototype (`spike_db/`, see [Prototype](#prototype)) proved the shape end-to-end; it
> is being promoted into the `spoor` package and then removed. This doc describes the
> intended production shape.

## Table of Contents

- [Origin](#origin)
- [The idea](#the-idea)
- [Architecture at a glance](#architecture-at-a-glance)
- [What moves, what stays](#what-moves-what-stays)
- [Why a database](#why-a-database)
- [Database choice: Postgres](#database-choice-postgres)
- [The data model](#the-data-model)
- [How the stages change](#how-the-stages-change)
- [Getting the existing data in](#getting-the-existing-data-in)
- [Rollout](#rollout)
- [Settled questions](#settled-questions)
- [Open questions](#open-questions)
- [Prototype](#prototype)
- [Related: Firecrawl review scraper](#related-firecrawl-review-scraper)

## Origin

This started at a whiteboard. Three items: **File → DB**, **Firecrawl?**, and a
**CLAUDE.md** for the repo. This doc covers the first.

![Whiteboard — File → DB, Firecrawl?, CLAUDE.md](assets/whiteboard.png)

## The idea

`spoor` runs a three-stage pipeline — **Collect → Evaluate → Categorise** — and today
every stage persists to the filesystem under `data/`. That is fine for *producing* one
property at a time, but wrong for *asking questions across* properties, which is what
the later stages increasingly need to do.

The plan: move the **later stages** — evaluate and categorise, and the data they
persist — into a database. **Collect is untouched**; its raw dossiers, review files,
and source PDFs stay on disk and remain the source of truth.

A few terms used throughout:

- **Average daily rate** — the per-night room rate (rate + mandatory per-person levies,
  divided by nights). The pipeline computes it per property and per traveller archetype.
- **Evaluation** — the middle stage's output for one property: a structured, reproducible
  assessment plus the numbers behind it.
- **Category** — one of the fourteen fixed traveller archetypes (honeymoon couple,
  multi-generation family, and so on) that the corpus is inverted into.

## Architecture at a glance

![spoor file → database architecture](assets/db_migration.png)

Collect keeps writing files. Evaluate and categorise stop treating the filesystem as the
database: they write rows. The questions that are awkward today — "every property under a
given price for a couple", "which archetype does this property belong to", "is this
evaluation stale" — become ordinary queries rather than directory walks.

## What moves, what stays

The boundary is deliberate. The migration stops at the *input edge* of evaluate, so
collect can keep evolving independently.

- **Becomes rows:** the per-property evaluation — both its numbers (the average-daily-rate
  payload) and its grounded prose — and the category-to-property relationships that
  categorise produces. The database is the source of truth for these; the markdown files
  evaluate and categorise used to write are no longer produced.
- **Stays a file:** the raw dossiers and review files (collect's output); the original
  rate-card PDFs; and the generated `*-pricing.py` script for each property. The pricing
  script stays a file because it is a real, runnable, golden-tested artifact — the tests
  load it and assert exact prices, and that gate must not move.
- **Not persisted at all:** pricing runs. Driving a pricing script across the benchmark is
  cheap, so categorise recomputes it on demand rather than storing it. The
  average-daily-rate *ranges* a category's party yields are stored (they justify
  membership); the act of running the script is not cached.

## Why a database

The file model is fine for writing one property; it fights you when you read across them.

- **Cross-property questions mean re-parsing the whole corpus.** Categorise re-reads every
  evaluation and re-runs every pricing script on each run. "Show me everything under a
  price for a couple" is a script, not a query.
- **There is no clean way to update in place.** A property's identity is encoded in a file
  path, so re-running overwrites sibling files and hopes the name matched. A row can be
  updated atomically, keyed on stable identity.
- **Provenance is scattered.** When something was evaluated, against which rate-card
  version, by which model — that lives across file headers and embedded fields, if at all.
  Columns make it first-class.
- **Categorise cannot rerun on its own.** It depends on the evaluate output existing as
  files. Persisting evaluations means categorise can run independently off the database —
  the main reason the evaluation stage is kept in the model at all.

## Database choice: Postgres

**Postgres.** It is the house database — Magic Lake already runs it (see that repo's
`deploy/docker/` and `docs/infrastructure/database.md`), so the tooling, the local
container pattern, and the team's familiarity all carry straight over. It handles the
JSON payloads (the evaluation blob), the relational joins (category-to-property), and any
future concurrency without a second thought. We run it locally in a container.

## The data model

Four ideas, kept small and readable:

- **properties** — the anchor. One row per bookable camp, identified by its lodge and
  property slugs, and carrying the lodge-group display label (sourced from the raw
  dossier's `Lodge group` line, which `adr.json` never recorded).
- **evaluations** — the middle-stage output, one row per property, carrying both the
  numeric payload (the average-daily-rate blob, as queryable JSON) and the grounded prose
  (the model-authored sections — value, completeness, fit, self-competitiveness, and
  reputation when reviews exist — kept as JSON keyed by section). This is what lets
  categorise run off the database.
- **categories** — the fourteen fixed archetypes (the taxonomy lives in
  `spoor/categories.py` and is mirrored into the table).
- **category_membership** — the relationship that matters most: one row for each property
  that genuinely *suits* a category, carrying the deterministic numbers (average-daily-rate
  range, rank) and the one grounded paragraph that justifies the fit. The two halves have
  distinct owners — see [How the stages change](#how-the-stages-change). Membership is
  positives-only: a row exists only when the property both fits the party and the evaluation
  supports the archetype; an excluded property leaves no row (its exclusion is derivable as
  any evaluated property absent from the category). Modelled to be read directly: a single
  listing answers "what is in this category and why".

The authoritative schema lives with the code, as versioned migrations under
`spoor/db/migrations/`. Pricing *runs* are deliberately absent — recomputed, not stored.

## How the stages change

The principle the project rests on does not move: **the skill does the thinking, the
tested core does the maths.** Only the final step of each deterministic stage changes from
"write a file" to "write a row".

- **Evaluate** computes the same numbers it does today and persists them as the evaluation
  row instead of the `adr.json` file; it also writes its grounded prose straight into that
  row as structured sections, rather than as a `<property>.md` file. The generated
  `*-pricing.py` script is still written to disk.
- **Categorise** reads its corpus from the database instead of walking `data/evaluated/`,
  recomputes each property's average-daily-rate range for a category's party, and writes
  the category-to-property rows.
- **The two owners of a membership row stay separate, as they were across two files
  before.** The tested core computes the numbers; the model decides suitability and writes
  the paragraph. They are joined at write time: the skill hands its per-property judgement
  to a single command that recomputes the numbers and writes the whole category in one
  atomic replace — so a rerun cannot leave numbers and judgement out of step, and the model
  still never authors a number.
- The deterministic modules (`spoor/benchmark.py`, `spoor/categories.py`, and friends) keep
  their logic; they gain a persistence layer (`spoor/db/`) to call instead of writing files.

## Getting the existing data in

A one-time import walks the current `data/evaluated/` tree and loads each property and its
evaluation into the database; the category relationships are produced by running categorise
against that imported corpus. The order matters: import while the files are still present,
verify the row counts, and only then delete them. The generated `*-pricing.py` scripts and
the raw tree stay; the evaluation markdown, the `adr.json` files, and the categorised
markdown are removed once their content lives in the database.

## Rollout

Staged so the test suite stays green throughout. Surface area, not time:

1. **Persistence layer + schema.** Promote `spike_db/` into `spoor/db/`: connection, the
   versioned migrations, and the store. Add the `db migrate` and `db import` commands.
   Nothing in the pipeline reads the database yet; the deterministic-core tests stay
   green and database-free.
2. **One-time import.** Backfill the database from the present `data/evaluated/` tree and
   verify the row counts against the files.
3. **Cut the stages over.** Evaluate writes the evaluation row (numbers + prose) and stops
   writing its markdown and `adr.json`; categorise sources its corpus from the database and
   writes membership rows instead of markdown. The price goldens still load the committed
   pricing scripts by path.
4. **Remove the superseded files.** Delete the evaluation markdown, the `adr.json` files,
   and the categorised markdown. The `*-pricing.py` scripts and the raw tree stay real files
   permanently.

## Settled questions

- **Do the evaluation and categorised markdown files stay as a regenerated export?** No.
  Once the database is canonical they are deleted, not exported. The `*-pricing.py` scripts
  and the raw tree remain the only files the later stages depend on.

## Open questions

- **How far up does the database go?** This design stops at the evaluate input edge.
  Pulling collect (dossiers, reviews) in later is a larger change and is deferred.

## Prototype

A throwaway prototype validated this end-to-end: a persistent Postgres container, an early
version of the schema, the existing file corpus imported, and categorise run entirely off
the database with unit tests passing. Its write-up, schema, and entity-relationship diagram
live under `spike_db/`. The prototype is for learning whether the shape works — not the
implementation we ship; in particular it priced membership on capacity alone and never
stored the model's suitability judgement or its grounded paragraph, which the production
schema adds.

## Related: Firecrawl review scraper

The whiteboard's second item asked whether the Firecrawl-based TripAdvisor review scraper
actually works. It does: a live fetch returned a full page of correctly-parsed reviews and
the unit tests pass. A handful of robustness issues are worth hardening before relying on
it heavily — an unstable de-duplication key and no partial save if a page fetch fails
mid-run among them. The scraper lives in `.claude/skills/collect/scripts/`.
