# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Table of Contents

- [Read These First](#read-these-first)
- [Rules](#rules)
- [Project Overview](#project-overview)
  - [Key directories](#key-directories)
- [Quick Start](#quick-start)
- [The Pipeline](#the-pipeline)
- [Testing](#testing)
- [Skills](#skills)
- [Key Conventions](#key-conventions)
- [Roadmap](#roadmap)

## Read These First

Before coding, read:
- [README.md](README.md) — canonical description: the Collect → Evaluate → Categorise pipeline, every command-line flag, the data layout, and the determinism model.
- [architecture_decisions.md](architecture_decisions.md) — the architecture decisions and the reasons behind them: why we drive Claude Code skills instead of writing against a code library, why each property gets its own pricing *script*, and the split between tested numbers and model-written prose that the whole project rests on.
- [docs/how_we_doc.md](docs/how_we_doc.md) — how we write documentation. Overview docs state intent and point into the code; they do not reproduce it.

## Rules

- Never commit code without an instruction from the user to do so.
- **Plain words, not acronyms.** Early docs leaned on acronyms and it hurt readability — spell things out. Write "average daily rate", "architecture decisions", "product requirements document" in full; if a short form earns its keep, introduce it in parentheses once, then stay consistent. (Universally standard ones — US dollar / USD, PDF, JSON, URL — are fine.)
- Documentation includes a table of contents at the top and follows [docs/how_we_doc.md](docs/how_we_doc.md). Update the contents whenever the structure changes.
- **Never mutate `data/raw/`.** It is the read-only source of truth. `evaluate` writes only `data/evaluated/`; `categorise` writes only `data/categorised/`. Each stage reads upstream read-only and writes its own stage directory.
- **The model never hand-computes a number.** Average-daily-rate tables, pricing, and candidate lists come from tested Python (`spoor.benchmark`, `spoor.categories`) driving generated pricing scripts. The model writes prose grounded in those numbers — it does not assemble the table.
- Effort estimates never reference time. Estimate surface area instead — skills touched, files affected, stages involved.
- The deterministic core (`spoor/` modules + generated pricing scripts) is **stdlib-only**. Keep it that way; `playwright` and `pytest` are optional extras, not runtime dependencies.
- When adding a skill, also add a matching subcommand in `spoor/cli.py` and a row in the [Skills](#skills) table below.

## Project Overview

`spoor` is a thin Python command-line tool that invokes Claude Code **skills** to gather and process information about safari lodges. Each subcommand builds a prompt and shells out to `claude -p` (Claude Code headless); the real work lives in `.claude/skills/`, which Claude Code discovers automatically.

It is a classic three-stage data pipeline — **Collect → Evaluate → Categorise** (gather, transform, invert):
- **Collect** — gather raw, faithful per-property dossiers (website, Wetu, rate-card PDFs, TripAdvisor + Booking.com reviews). Append-only; never editorialises.
- **Evaluate** — turn each dossier into a structured, reproducible assessment: a generated, stdlib-only pricing script + a deterministic Benchmark Safari average-daily-rate table + grounded prose. Reads raw read-only.
- **Categorise** — invert the whole evaluated corpus into a per-traveller-archetype view (14 fixed archetypes). The only cross-property step.

A lodge (e.g. "Londolozi") is a **group** that operates several bookable **properties** (camps), each with its own value proposition and rate card. One `collect` run discovers every property and writes one dossier per property.

> **Average daily rate** is the single most-used term here: the per-night room rate, computed as (rate + mandatory per-person-per-night levies) ÷ nights, on a published-rack basis. The pipeline reports it per property and per traveller archetype.

### Key directories

- `spoor/` — the Python package: `cli.py` (the wrapper), plus the deterministic core (`benchmark.py`, `categories.py`, `pricing.py`, `freshness.py`, `fx.py`, `reputation.py`, `manifest.py`, `report.py`).
- `.claude/skills/<name>/SKILL.md` — the skills that do the actual work (see [Skills](#skills)).
- `config/` — `fx.json` (pinned, dated native→US-dollar rates; no live foreign-exchange lookups) and `lodges.txt` (working batch list of lodge groups).
- `data/raw/` — collected dossiers + `reviews/` + `_docs/`. Source of truth; never mutated by later stages.
- `data/evaluated/` — generated pricing scripts (`<property>-pricing.py`), average-daily-rate data (`<property>-adr.json`), and evaluation markdown (`<property>.md`).
- `data/categorised/` — one markdown file per traveller archetype.
- `tests/` — stdlib-only pytest suite (golden price, benchmark, reputation, category). Frozen golden rate cards under `tests/golden/`.

## Quick Start

Install (including the headless-browser review scraper):

```bash
pip install -e ".[reviews]"          # adds playwright for the Booking.com scraper
python3 -m playwright install chromium
export FIRECRAWL_API_KEY=...          # for TripAdvisor review collection (no Python dependency)
```

Requirements: Python 3.9+, the `claude` command on PATH, and `poppler` for PDF rate cards (`brew install poppler`). Plain `pip install -e .` works if you pass `--no-reviews` to `collect`.

Run without installing:

```bash
python -m spoor.cli collect "Londolozi" --website "https://www.londolozi.com"
```

## The Pipeline

```bash
spoor collect "Londolozi" --website "https://www.londolozi.com" --rate-card ./rates/londolozi-2026.pdf
spoor collect --names-file config/lodges.txt --concurrency 3   # batch: one agent per lodge

spoor evaluate "Tanda Tula"                              # whole lodge → 3 files per property
spoor build-pricing-script tanda-tula safari-camp        # one property's pricing script only
spoor assess "Tanda Tula"                                # grounding-only check over the prose

spoor categorise                                         # all evaluated lodges → data/categorised/<category>.md
```

- `collect` defaults to **Claude Sonnet 4.6** (cheapest model that does the accuracy-sensitive collection reliably); override with `--model`.
- `build-pricing-script` / `evaluate` run on **Opus** (exacting code generation); `assess` runs on **Sonnet** (lighter checking); `categorise` runs on **Opus** (cross-property synthesis).
- A pricing script is regenerated only when missing or the raw rate-card section changed (detected via a `# rate-card-sha256:` marker); otherwise the golden-tested script is reused and only the average daily rate recomputed. `--force-rebuild` overrides.
- `python -m spoor.categories --list` prints the authoritative slug → label map for the 14 archetypes.

## Testing

`pytest` is **not** a runtime dependency — install it explicitly via the `test` extra:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

The suite is stdlib-only and currently **73 tests pass**. Coverage:
- **Golden price tests** (`tests/test_golden_*.py`) — hand-verified prices for the two richest rate cards (**Makanyi**, **Tanda Tula Safari Camp**): single supplements, child bands, family-suite-vs-multiroom optimisation, levy itemisation, stay-pay specials, infeasible/min-age cases. They run against the committed pricing scripts and are the **acceptance gate** for any regenerated script.
- **Benchmark tests** (`tests/test_benchmark.py`) — average-daily-rate-table logic against a fake `price_fn`, independent of any real rate card.
- **Reputation tests** (`test_reputation.py`, `test_manifest.py`, `test_report_reputation.py`, `test_golden_reputation.py`) — TripAdvisor / Booking.com parsing + aggregation, manifest missing-vs-empty, table render, real-property block.
- **Category tests** (`tests/test_categories.py`) — per-archetype candidate selection + deterministic average-daily-rate-range computation.

## Skills

Skills live in `.claude/skills/<name>/SKILL.md` and are discovered by Claude Code automatically. Most map 1:1 to a `spoor` subcommand; the last two are standalone development workflows.

> **The pipeline skills (`collect`, `evaluate`, `assess`, `categorise`, `build-pricing-script`) are part of the evolving product solution — they will change as the design develops.** Treat them as live solution code, not stable infrastructure. Don't load them into context or assume their current shape on every request; open a skill's `SKILL.md` only when a task actually touches that stage.

| Skill | Model | What it does |
| --- | --- | --- |
| `collect` | Sonnet 4.6 | Discover every bookable property in a lodge group and write one verbatim, append-only dossier per property (website, Wetu, rate-card PDFs, TripAdvisor + Booking.com reviews). Bundles `scripts/booking_reviews.py` + `scripts/tripadvisor_reviews.py`. |
| `build-pricing-script` | Opus | Turn one property's raw rate card into a self-contained, stdlib-only pricing script exposing `price(start, end, ages=[...])`; stamps the rate-card hash and self-tests. The single highest-leverage, most error-sensitive step. |
| `evaluate` | Opus | Evaluate every property in a lodge: ensure a current pricing script, compute the Benchmark Safari average-daily-rate table deterministically, and write grounded value/completeness/fit/reputation prose. Three files per property. |
| `assess` | Sonnet | Grounding-only checking: confirm that every claim in `<property>.md` traces to the raw dossier or the computed average-daily-rate data; flag the unsupported. Never edits the evaluation. |
| `categorise` | Opus | Invert the evaluated corpus into 14 per-archetype files, each with a deterministic US-dollar average-daily-rate range and one grounded paragraph per genuinely-fitting property. The only cross-property step. |
| `to-prd` | — | Turn the current conversation into a product requirements document and publish it to the issue tracker (no interview). Development workflow, not part of the pipeline. |
| `grill-me` | — | Interview the user relentlessly to stress-test a plan or design before building, one question at a time. Development workflow. |

## Key Conventions

- **Two layers of determinism** (the core idea): a tested numeric core that the model may never bypass, with grounded prose on top. Reputation mirrors the same shape additively — reviews never touch pricing, and TripAdvisor / Booking.com are kept separate by scale (never a blended composite).
- **Native currency is canonical**, the US-dollar figure is a derived column from the pinned `config/fx.json` (no live foreign-exchange lookups).
- **Append-only collection.** Re-running `collect` updates dossiers in place and accumulates reviews; it never wipes prior output. Sources carry `<!-- collected: … -->` freshness markers.
- **A pricing script per property**, not one parametric pricer — rate cards vary too wildly for a config schema, and generating explicit code surfaces completeness gaps (see architecture_decisions.md).

## Roadmap

A file→database migration of the later pipeline stages (`evaluate` / `categorise` outputs) is planned on the `teamwork` branch — see [docs/db-migration/README.md](docs/db-migration/README.md). Still in design; the current source of truth remains the `data/` tree.
