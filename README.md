# spoor

A small CLI that invokes [Claude Code](https://docs.claude.com/en/docs/claude-code) skills to gather and process information about safari lodges.

> *spoor* (n.) — the track or trail of an animal. Here, the trail of facts left by a lodge across the web and its paperwork.

## How it works

`spoor` is a thin Python wrapper. Each subcommand builds a prompt and shells out to `claude -p` (Claude Code in headless mode). The actual work is done by **skills** in `.claude/skills/`, which Claude Code discovers automatically.

```
spoor collect "<group>"   →  claude -p "Use the collect skill ..."     →  data/raw/<lodge-slug>/<property-slug>.md
spoor evaluate "<group>"  →  claude -p "Use the evaluate skill ..."    →  data/evaluated/<lodge-slug>/<property-slug>.{py,json,md}
spoor categorise          →  claude -p "Use the categorise skill ..."  →  data/categorised/<category>.md
```

The project is a classic **Collect → Evaluate → Categorise** ETL (see `ADR.md`).
**Collect** gathers raw, faithful per-property dossiers. **Evaluate** turns each
dossier into a structured, reproducible assessment — without ever mutating the raw
data — doing the pricing maths deterministically so the numbers can be trusted and
reused. **Categorise** inverts the whole evaluated corpus into a per-traveller-archetype
view — one file per category listing the properties that genuinely suit it, with a
deterministically computed ADR range. It's the only cross-property step.

A safari lodge is usually a group that operates several **properties** (camps), each a
separately bookable product with its own value proposition and rate card. One `collect`
run discovers every property and writes one dossier per property.

## Requirements

- Python 3.9+
- The `claude` CLI on your PATH ([install Claude Code](https://docs.claude.com/en/docs/claude-code))
- [poppler](https://poppler.freedesktop.org/) for reading PDF rate cards (`brew install poppler` / `apt-get install poppler-utils`)
- For review collection:
  - **Booking.com** — [Playwright](https://playwright.dev/python/) + Chromium (JS-gated; see Install).
  - **TripAdvisor** — a [Firecrawl](https://firecrawl.dev) key in `FIRECRAWL_API_KEY` (TripAdvisor blocks headless browsers, so it's fetched via Firecrawl). Firecrawl is a paid service.

## Install

```bash
pip install -e ".[reviews]"      # include the headless-browser scraper for reviews
python3 -m playwright install chromium
export FIRECRAWL_API_KEY=...     # for TripAdvisor review collection (no Python dep)
```

Without reviews, plain `pip install -e .` works; pass `--no-reviews` to `collect`.

Or run without installing:

```bash
python -m spoor.cli collect "Londolozi" --website "https://www.londolozi.com"
```

## Usage

### `collect` — gather raw dossiers for a lodge group

Discovers every bookable property in a lodge group and writes one verbatim dossier
per property under `data/raw/<lodge-slug>/`.

```bash
spoor collect "Londolozi" \
  --website "https://www.londolozi.com" \
  --rate-card ./rates/londolozi-2026.pdf \
  --source "https://example.com/review" \
  --source ./notes/site-visit.md
```

- `name` (required unless `--names-file`) — the lodge group name; the slug is derived from it.
- `--names-file` — text file of lodge group names, one per line, to collect in a batch (see below).
- `--concurrency` — max agents to run at once in `--names-file` mode (default: `3`).
- `--website` — official site URL.
- `--rate-card` — path to a local PDF with pricing; repeat for several.
- `--source` — additional URL or local file; repeat for several.
- `--no-wetu` — skip the Wetu cross-reference (on by default).
- `--no-reviews` — skip TripAdvisor + Booking.com review collection (on by default).
- `--model` — model Claude Code runs with (default: `claude-sonnet-4-6`; override with `opus`, `haiku`, etc.).
- `-C, --dir` — project directory containing `.claude/` (default: current dir).

#### Batch mode — one agent per lodge

Pass a text file of names (one per line; blank lines and `#`-comments are ignored)
to fan out one `collect` agent per lodge group, running up to `--concurrency` at a
time:

```bash
cat config/lodges.txt
# Londolozi
# Tanda Tula
# Victoria Falls River Lodge

spoor collect --names-file config/lodges.txt --concurrency 3
```

`config/lodges.txt` is the working list of lodge groups for this project.

Each agent writes to its own `data/raw/<slug>/`, so they're fully independent. Because
several run at once, each agent's output is captured to `data/raw/<slug>/collect.log`
rather than streamed to the terminal; the terminal shows a one-line ✓/✗ per lodge as
each finishes, and the command exits non-zero if any agent failed. Batch mode collects
each group's website itself, so the per-lodge flags (`--website`, `--rate-card`,
`--source`) and a positional `name` can't be combined with `--names-file`; the shared
flags (`--no-wetu`, `--no-reviews`, `--model`) apply to every lodge.

### Why Sonnet 4.6 is the default model

`collect` defaults to **Claude Sonnet 4.6** because it's the cheapest model that does the
job reliably. Collection is an agentic, accuracy-sensitive task — faithful PDF rate
transcription, per-property attribution, provenance tracking, and dedup judgment — that
needs full tool use (WebFetch, Bash, PDF reading) but not frontier-level reasoning.
Sonnet 4.6 ($3/$15 per million input/output tokens) covers that capability at roughly
40% less than Opus 4.8 ($5/$25), with no meaningful loss in quality for this work. Opus
is overkill here; Haiku 4.5 ($1/$5) is cheaper still but riskier for exact rate
transcription, so it's an opt-in (`--model haiku`) for cost-sensitive runs you'll
spot-check rather than the default. Override anytime with `--model`.

**Sources collected per property:** the group website, **[Wetu Content Central](https://content.wetu.com/Africa)**
(a B2B supplier database — the skill finds each property's iBrochure and pulls Fast
Facts, room types, facilities, activities and more, **downloads Wetu's rate-card PDFs**
when no `--rate-card` is supplied, and **captures any live Wetu specials** — booking and
travel windows, descriptions, T&Cs), **guest reviews** from TripAdvisor (via a
Firecrawl-backed scraper) and Booking.com (via a headless-browser scraper), any PDF rate
cards, and any extra `--source`s. Each lands in its own section of the dossier so
provenance stays clear.

**Incremental & append-only:** re-running `collect` does **not** wipe prior output — it
updates each dossier in place. Sources refresh on their own cadence (website/Wetu ~30d,
rate cards ~14d, specials ~3d), while **guest reviews are immutable and append-only** —
they accumulate in `data/raw/<lodge-slug>/reviews/` and are never re-fetched or discarded.
Each dossier section carries a `<!-- collected: … -->` marker so the skill knows what's
still fresh. Downloaded source PDFs are retained under `data/raw/<lodge-slug>/_docs/` (their
Wetu links are short-lived, so the local copy is the durable record).

**Reviews** live alongside the dossiers:

```
data/raw/<lodge-slug>/reviews/
  <property-slug>-booking.jsonl       # append-only, deduped by content hash
  <property-slug>-tripadvisor.md      # append-only, deduped by content hash
```

Both scrapers are bundled with the skill and can also be run directly (from the project
root):

```bash
python3 .claude/skills/collect/scripts/booking_reviews.py \
  --url "https://www.booking.com/reviews/zw/hotel/victoria-falls-river-lodge.html" \
  --store "data/raw/victoria-falls-river-lodge/reviews/river-lodge-booking.jsonl"

FIRECRAWL_API_KEY=... python3 .claude/skills/collect/scripts/tripadvisor_reviews.py \
  --url "https://www.tripadvisor.com/Hotel_Review-g..-d..-Reviews-<slug>.html" \
  --store "data/raw/<lodge-slug>/reviews/<property-slug>-tripadvisor.md"
```

#### Review caveats

Two known limitations, flagged per-property in each dossier's *Collection notes*:

- **TripAdvisor exposes only its recent review subset, and has no stable per-review ID.**
  TripAdvisor blocks headless browsers, so it's fetched via Firecrawl and parsed
  deterministically into verbatim review text. The page surfaces only the most recent
  (mostly 5-bubble) reviews rather than the full history, so the quoted sample is partial
  and skewed toward the top — the stated overall/total are always captured, but the
  captured text is a recency-biased sample, not a representative average. Dedup is by
  content hash (reviewer + date + title + text), like Booking.com.
- **Booking.com only exposes a subset of reviews as text.** Its legacy reviews page
  serves extractable text for a fraction of the total verified count (e.g. ~15 of 31 for
  Victoria Falls River Lodge); the rest are score-only or non-English and can't be
  scraped. The aggregate score, subscores, and total count are always captured.

For `Londolozi` you'd get something like:

```
data/raw/londolozi/
  founders-camp.md
  varty-camp.md
  tree-camp.md
  granite-suites.md
  private-granite-suites.md
```

Each dossier is a faithful capture — exact rates, dates, and wording — with provenance
per section and an explicit notes section for any gaps. A later stage can refine it.

### `evaluate` — turn raw dossiers into a structured assessment

Reads `data/raw/<lodge>/` (read-only) and writes `data/evaluated/<lodge>/`, mirroring
the per-property layout. For each property it produces **three files**:

```
data/evaluated/<lodge>/
  <property>-pricing.py     # generated, self-contained pricing script (price(start,end,ages))
  <property>-adr.json       # the Benchmark Safari ADR table + reputation block — the reproducible source of truth
  <property>.md             # human evaluation: ADR table + grounded value/completeness/fit/reputation prose
```

```bash
spoor evaluate "Tanda Tula"                 # whole lodge
spoor build-pricing-script tanda-tula safari-camp   # one property's script only
spoor assess "Tanda Tula"                   # grounding-only QA over the evaluation prose
```

The phase is **two layers of determinism**:

1. **A numeric core.** Each property's rate card is turned (by an LLM, on Opus) into a
   self-contained, stdlib-only pricing script that brute-forces the cheapest valid room
   configuration for a party and stay — respecting capacities, age bands, single
   supplements, levies and objectively-qualifying specials, returning both RACK and STO
   figures. Tested Python (`spoor.benchmark`) then drives that script across a fixed
   **Benchmark Safari** (5 nights from the 15th of each month; Couple / Family / Group
   personas) to produce a reproducible 36-cell ADR table — *the LLM never assembles the
   table*. ADRs are native-currency canonical with a USD column from a pinned, dated FX
   rate (`config/fx.json`).
2. **Grounded prose.** The evaluation markdown's value / completeness / fit /
   self-competitiveness sections must cite the computed numbers or quote the raw dossier.

A **reputation layer** mirrors the same two-layer shape, additively (reviews never touch
pricing). Tested Python (`spoor.reputation`) parses a property's review files — declared
in a collect-authored `reviews:` manifest in the dossier front-matter — into a per-source
block folded into `adr.json`: TripAdvisor's *stated* overall, scale and total plus the
partial quoted-sample size, and Booking.com's computed average, score distribution and
date span. The two sources are kept **separate by scale** — never a blended composite. A
fifth `## Reputation` prose section then reports what the reviews say, proportionally,
with quantitative claims matching the block and thematic claims quoted verbatim with
attribution. A missing manifest makes evaluate warn and skip only that section.

**Reproducible by design.** A pricing script is regenerated only when it's missing or
the raw rate-card section changed (detected via a `# rate-card-sha256:` marker);
otherwise the existing, golden-tested script is reused and only the ADR is recomputed.
`--force-rebuild` overrides. **Model split:** `build-pricing-script` / `evaluate` run on
Opus (exacting codegen); `assess` runs on cheaper Sonnet (lighter QA).

```
spoor evaluate <lodge> [--force-rebuild] [--model opus]
spoor build-pricing-script <lodge> <property> [--force-rebuild]
spoor assess <lodge>
```

### `categorise` — invert the corpus into a per-traveller view

Reads `data/evaluated/` (read-only, across all lodges) and writes one markdown file per
category under `data/categorised/`. This is the **only cross-property step**: it answers
"which properties suit *this kind of traveller*?" rather than evaluating a single lodge.

```bash
spoor categorise                # all lodges already evaluated → data/categorised/<category>.md
```

There's a **fixed taxonomy of 14 traveller archetypes** (honeymoon couple, multi-gen
family, wildlife photographer, ultra-HNW collector, budget backpacker, …); run
`python -m spoor.categories --list` for the authoritative slug → label map. The phase
keeps the same determinism split as `evaluate`:

- **Numbers and the candidate list are deterministic.** `spoor.categories` prices each
  property's own generated `price()` script for the category's fixed party shape and
  emits the candidates plus a USD ADR range. The LLM **never** hand-computes an ADR.
- **Membership and prose are the model's.** It decides which candidates *genuinely* fit,
  grounded only in each property's evaluation, and writes one paragraph each — linking
  back to the source evaluation.

Runs on **Opus** (cross-property synthesis). `categorise` is the final
Collect → Evaluate → Categorise step.

### Tests

The deterministic core is covered by `pytest`. `pytest` isn't a runtime dependency,
so install it into a virtualenv via the `test` extra:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

(`.venv/` is gitignored.)

- **Golden price tests** (`tests/test_golden_*.py`) pin hand-verified prices for the two
  richest rate cards — **Makanyi** and **Tanda Tula Safari Camp** — covering single
  supplements, child bands, family-suite-vs-multiroom optimisation, levy itemisation, a
  stay-pay special, and infeasible/min-age cases. They run against the committed pricing
  scripts and are the acceptance gate for any regenerated script. Raw rate cards are
  frozen under `tests/golden/raw/`.
- **Benchmark tests** (`tests/test_benchmark.py`) check the ADR-table logic with a fake
  `price_fn` — personas × 12 months, ADR = total ÷ nights, native + USD columns, and
  Benchmark-N/A handling — independent of any real rate card.
- **Reputation tests** (`tests/test_reputation.py`, `tests/test_manifest.py`,
  `tests/test_report_reputation.py`, `tests/test_golden_reputation.py`) cover TripAdvisor /
  Booking.com parsing and aggregation, the manifest's missing-versus-empty distinction, the
  summary-table render, and a real-property block end-to-end (Tanda Tula — populated
  TripAdvisor + an empty Booking.com file).
- **Category tests** (`tests/test_categories.py`) cover the per-archetype candidate
  selection and deterministic ADR-range computation that back the `categorise` phase.

## Project layout

```
spoor/
├── .claude/skills/
│   ├── collect/SKILL.md                  # collect skill (+ scripts/booking_reviews.py, tripadvisor_reviews.py)
│   ├── build-pricing-script/SKILL.md     # generate one property's pricing script (Opus)
│   ├── evaluate/SKILL.md                 # evaluate a whole lodge (Opus)
│   ├── assess/SKILL.md                   # grounding-only QA (Sonnet)
│   └── categorise/SKILL.md               # invert the corpus into per-archetype files (Opus)
├── spoor/
│   ├── cli.py                            # the CLI wrapper (collect / evaluate / build / assess / categorise)
│   ├── benchmark.py                      # Benchmark Safari spec + compute_adr_table (tested)
│   ├── categories.py                     # 14-archetype taxonomy + deterministic candidates/ADR ranges (tested)
│   ├── pricing.py                        # loads a generated pricing script via importlib
│   ├── freshness.py                      # rebuild-or-reuse policy (rate-card hash)
│   ├── fx.py                             # pinned, dated native→USD conversion
│   ├── reputation.py                     # parse/aggregate reviews → reputation block (tested) + merge CLI
│   ├── manifest.py                       # read the dossier's reviews: front-matter (missing vs empty)
│   └── report.py                         # renders the ADR + reputation tables + completeness scaffold
├── config/
│   ├── fx.json                           # pinned, dated FX rates (USD per native unit)
│   └── lodges.txt                        # working list of lodge groups for batch collect
├── data/raw/                             # collected dossiers + reviews/ + _docs/
├── data/evaluated/                       # generated scripts + ADR JSON + evaluations
├── data/categorised/                     # per-traveller-archetype files (one per category)
├── tests/                                # pytest: golden price + benchmark + reputation + category tests
└── pyproject.toml
```

## Adding skills

Drop a new skill under `.claude/skills/<name>/SKILL.md`, then add a matching
subcommand in `spoor/cli.py` that builds the prompt and calls `_run_claude(...)`
with the tools that skill needs.
