# Plan: Consolidate the Database Work Under `docs/`

A plan to gather all the file→database material — the design, the throwaway
prototype, and its artifacts — into one place under `docs/`, so the repo root stays
clean and the whole body of work is discoverable together.

## Table of Contents

- [Goal](#goal)
- [Where things are now](#where-things-are-now)
- [Target layout](#target-layout)
- [Approach](#approach)
- [Steps](#steps)
- [Reference and path fixes](#reference-and-path-fixes)
- [What could break](#what-could-break)
- [Out of scope](#out-of-scope)

## Goal

Move the database-migration work — currently split between `docs/db-migration/` (the
design) and `spike_db/` at the repo root (the prototype) — into a single home under
`docs/`. The prototype is explicitly throwaway; its lasting value is as *reference*, so
it belongs with the documentation, not at the top level of the repo next to the product
package.

## Where things are now

Two locations, and they have **diverged** — resolve that first:

- `docs/db-migration/` — the design overview (`README.md`, `consolidation_plan.md`,
  `assets/`). Lives on `teamwork`.
- `spike_db/` (repo root) — the prototype: the Python modules, `schema.sql`,
  `docker-compose.yml`, `REPORT.md`, `tests/`, and `artifacts/` (entity-relationship
  diagram, live schema dump).
  - The **merged copy on `teamwork`** has the original single test file.
  - The **`spike/postgres-db` worktree** is ahead: a refactored test suite with a
    `conftest.py`, a `_corpus.py` helper, split test modules, and an isolated
    `spike_test` schema — all **uncommitted**.

So before moving anything, the prototype's latest state has to be settled on one branch.

## Target layout

Everything database-related under `docs/db-migration/`:

```
docs/db-migration/
├── README.md                 # design overview — the entry point (unchanged)
├── consolidation_plan.md     # this plan
├── assets/
│   ├── whiteboard.png
│   ├── db_migration.png
│   └── db_migration.html
└── prototype/                # the throwaway spike, self-contained reference
    ├── README.md             # was REPORT.md — how it went + how to run it
    ├── schema.sql
    ├── docker-compose.yml
    ├── db.py  store.py  importer.py  categorise_db.py  __init__.py
    ├── tests/                # conftest.py, _corpus.py, test_*.py
    └── artifacts/
        ├── erd.png  erd.excalidraw  gen_erd.py
        └── ddl_live.sql
```

## Approach

**Recommended — move the whole prototype, keep it runnable.** It is reference, but a
prototype whose tests still pass is far more convincing than one that has been pinned to
a wall. Moving the directory wholesale costs a small amount of path surgery (see
[Reference and path fixes](#reference-and-path-fixes)); that cost is worth paying once.

**Lighter alternative — move only the documentation and artifacts** (the report, the
diagram, the schema dump) into `docs/db-migration/prototype/`, and leave the runnable
code at `spike_db/` (or delete it now and let the real build start fresh). This is the
strictest reading of our own documentation rule — docs in `docs/`, code in the package —
and avoids touching any import paths. Choose this if we would rather not maintain
runnable throwaway code.

The rest of the plan assumes the recommended approach.

## Steps

1. **Settle the prototype on one branch.** Commit the `spike/postgres-db` worktree's test
   refactor, then bring it onto `teamwork` (the worktree is already based on it). After
   this, `teamwork` holds the authoritative prototype and the root `spike_db/` is the
   only copy to move.
2. **Move the directory:** `git mv spike_db docs/db-migration/prototype`.
3. **Rename the report:** `git mv docs/db-migration/prototype/REPORT.md
   docs/db-migration/prototype/README.md`, and add its table of contents per our doc
   standard.
4. **Fix the paths and imports** the move breaks (next section).
5. **Run the suite** from the new location to confirm it is still green against the
   container.
6. **Update the cross-references** in `CLAUDE.md` and `docs/db-migration/README.md` that
   point at `spike_db/`.
7. **Retire the standalone `spike/postgres-db` branch** once everything is on `teamwork`.

## Reference and path fixes

The move is mechanical but these spots must change together:

- **Repository-root depth.** `importer.py` and `categorise_db.py` compute the repo root
  as `Path(__file__).resolve().parents[1]`; from three levels deeper it becomes
  `parents[3]`. The tests' `parents[2]` becomes `parents[4]`. `conftest.py` / `_corpus.py`
  compute corpus paths the same way and need the same adjustment. (`db.py` resolves
  `schema.sql` relative to itself, so it is unaffected.)
- **The package name.** The tests import `from spike_db import …`. The folder is now
  `prototype`, so either rename the import to match or run the suite from inside
  `docs/db-migration/prototype/` with the package on the path. Pick one and apply it
  consistently.
- **The compose path in instructions.** Commands referencing
  `spike_db/docker-compose.yml` become `docs/db-migration/prototype/docker-compose.yml`.
  The compose file itself (named volume, port 5433) does not change.
- **Prose pointers.** `CLAUDE.md`'s roadmap line and `docs/db-migration/README.md` (the
  data-model and prototype sections) name `spike_db/` — repoint them at
  `docs/db-migration/prototype/`.

## What could break

- **Test discovery / imports** are the only real risk — the `parents[]` depths and the
  `spike_db` import name. Running the suite after the move (step 5) catches both.
- **The container is unaffected.** The named volume and port live in the compose file,
  which moves unchanged, so the persistent data survives.
- **The diverged copies** are the subtle trap: if the move happens before the worktree's
  newer tests are merged, the better suite is lost. Step 1 exists to prevent that.

## Out of scope

- The real migration itself (wiring `evaluate`/`categorise` to Postgres) — that is the
  design doc's rollout, not this reorganisation.
- Any change to the prototype's behaviour. This is a move, not a rewrite.
