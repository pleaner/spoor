# spoor

A small CLI that invokes [Claude Code](https://docs.claude.com/en/docs/claude-code) skills to gather and process information about safari lodges.

> *spoor* (n.) — the track or trail of an animal. Here, the trail of facts left by a lodge across the web and its paperwork.

## How it works

`spoor` is a thin Python wrapper. Each subcommand builds a prompt and shells out to `claude -p` (Claude Code in headless mode). The actual work is done by **skills** in `.claude/skills/`, which Claude Code discovers automatically.

```
spoor collect "<group>"  →  claude -p "Use the collect skill ..."  →  data/raw/<lodge-slug>/<property-slug>.md
```

A safari lodge is usually a group that operates several **properties** (camps), each a
separately bookable product with its own value proposition and rate card. One `collect`
run discovers every property and writes one dossier per property.

## Requirements

- Python 3.9+
- The `claude` CLI on your PATH ([install Claude Code](https://docs.claude.com/en/docs/claude-code))
- [poppler](https://poppler.freedesktop.org/) for reading PDF rate cards (`brew install poppler` / `apt-get install poppler-utils`)
- For review collection: [Playwright](https://playwright.dev/python/) + Chromium (Booking.com is JS-gated; see Install)

## Install

```bash
pip install -e ".[reviews]"      # include the headless-browser scraper for reviews
python3 -m playwright install chromium
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
cat lodges.txt
# Londolozi
# Singita
# Sabi Sabi

spoor collect --names-file lodges.txt --concurrency 3
```

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
travel windows, descriptions, T&Cs), **guest reviews** from TripAdvisor (via fetch) and
Booking.com (via a headless-browser scraper), any PDF rate cards, and any extra
`--source`s. Each lands in its own section of the dossier so provenance stays clear.

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
  <property-slug>-tripadvisor.md      # append-only
```

The Booking.com scraper is bundled with the skill and can also be run directly
(from the project root):

```bash
python3 .claude/skills/collect/scripts/booking_reviews.py \
  --url "https://www.booking.com/reviews/zw/hotel/victoria-falls-river-lodge.html" \
  --store "data/raw/victoria-falls-river-lodge/reviews/river-lodge-booking.jsonl"
```

#### Review caveats

Two known limitations, flagged per-property in each dossier's *Collection notes*:

- **TripAdvisor text is condensed, and dedup is heuristic.** TripAdvisor is read via
  fetch (a headless browser is blocked there), which tends to *paraphrase* long review
  text rather than return it verbatim, and exposes no stable per-review IDs. So
  TripAdvisor append-dedup is best-effort — matched on reviewer + date + title — not the
  deterministic content-hash dedup used for Booking.com. Treat TripAdvisor review text
  as a faithful summary, not an exact quote.
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

## Project layout

```
spoor/
├── .claude/skills/collect/
│   ├── SKILL.md                         # the collect skill (instructions for Claude)
│   └── scripts/booking_reviews.py       # bundled headless-browser Booking.com scraper
├── spoor/cli.py                         # the CLI wrapper
├── data/raw/                            # collected dossiers + reviews/ + _docs/ land here
└── pyproject.toml
```

## Adding skills

Drop a new skill under `.claude/skills/<name>/SKILL.md`, then add a matching
subcommand in `spoor/cli.py` that builds the prompt and calls `_run_claude(...)`
with the tools that skill needs.
