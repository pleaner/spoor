# PRD — Collect phase

> Note on terms: this document spells terms out in full. Wetu Content Central is named in
> full on first use, then "Wetu". On-disk filenames (`adr.json`, `_docs/`, `.jsonl`) are
> kept verbatim because they are literal paths.

## Problem Statement

To assess a safari lodge I first need faithful source material about it, and that material
is scattered across incompatible places: the operator's marketing website, the Wetu Content
Central B2B supplier database, PDF rate cards (often emailed or buried in Wetu document
links), and guest reviews on TripAdvisor and Booking.com. None of these is structured the
same way, several are behind bot protection or expiring links, and a single "lodge" is
usually not one product but a **group of separately bookable camps**, each with its own
positioning, rooms, rates, and reputation.

Gathering this by hand is slow, inconsistent, and lossy — exact figures get rounded, date
ranges get dropped, reviews get summarised away. The downstream **evaluate** and
**categorise** phases can only be as good as the raw material they read, and they require
that material to be **faithful** (exact numbers, exact wording) and **traceable** (every
fact attributable to a named source). The pricing maths in evaluate is deterministic, so a
rate transcribed approximately produces a confidently wrong answer.

There is also a cost problem: re-gathering everything from the web on every run is slow and
wasteful, and re-fetching guest reviews risks losing or rewording an immutable record.

I need a **collect** phase that discovers every bookable property in a named lodge group and
captures one raw, verbatim dossier per property — incrementally, append-only for reviews,
and never editorialised. This is the **C** in the project's Collect → Evaluate →
Categorise ETL (see `ADR.md`).

## Solution

Collect is implemented as a **Claude Code skill** (`.claude/skills/collect/SKILL.md`) driven
by a thin **CLI** (`spoor collect`). The split mirrors the rest of the pipeline: the CLI is
deterministic orchestration (argument validation, prompt construction, headless invocation,
batching), and the skill is the model-driven judgement (discovery, source capture, faithful
transcription).

1. **CLI (`spoor collect`)** builds a headless prompt from the user's inputs and shells out
   to `claude -p` with a tightly scoped tool allow-list. It supports a single named lodge
   (with optional `--website`, repeatable `--rate-card`, repeatable `--source`) or a
   `--names-file` batch that runs one independent agent per lodge concurrently.

2. **Skill** does the work per lodge: compute the lodge slug, **discover** every distinct
   bookable property from the website, **cross-reference Wetu** for structured per-property
   content and rate-card PDFs, **read every rate card** and transcribe pricing exactly,
   **collect reviews** from TripAdvisor (via WebFetch) and Booking.com (via a bundled
   headless-browser scraper), and **write one dossier per property** under
   `data/raw/<lodge-slug>/<property-slug>.md`.

3. **Incremental, append-first** collection: each dossier section carries a `collected:`
   marker and a cadence. Re-runs keep still-fresh sections verbatim, refresh stale ones, and
   **never re-fetch reviews** — reviews are immutable and append-only, stored in per-source
   stores under `data/raw/<lodge-slug>/reviews/`.

From the user's perspective: `spoor collect "Londolozi"` produces a faithful, source-traced
dossier per camp that the evaluate phase can read directly, and re-running it later refreshes
what has gone stale and adds new reviews without discarding anything.

## User Stories

1. As an analyst, I want to name a lodge group and get one dossier per bookable camp, so that
   each separately bookable product is assessed on its own terms.
2. As an analyst, I want room types within a single camp **not** treated as separate
   properties, so that the property list reflects what is actually bookable.
3. As an analyst, I want pricing transcribed exactly — per-person-per-night rates, currency,
   season date ranges, single supplements, child policies, minimum-stay rules, levies — so
   that the deterministic pricing in evaluate is built on trustworthy numbers.
4. As an analyst, I want every fact attributable to a named source (website sub-page URL,
   Wetu iBrochure ID, source PDF), so that the dossier is auditable.
5. As an analyst, I want Wetu used as a structured second source per property, so that
   gaps in the marketing website are filled with supplier-grade content.
6. As an analyst, I want the actual rate-card PDFs downloaded and retained locally, so that
   the source survives even though Wetu's signed links expire within hours.
7. As an analyst, I want live specials captured verbatim with their booking-validity and
   travel-date windows, so that time-sensitive offers are recorded exactly.
8. As an analyst, I want guest reviews from TripAdvisor and Booking.com captured per
   property, so that the later reputation layer has raw material to work from.
9. As an analyst, I want reviews never re-fetched or rewritten, only appended, so that the
   immutable guest record is preserved across runs.
10. As an analyst, I want a re-run to keep fresh sections unchanged and only refresh what has
    gone stale, so that collection is cheap and stable on repeat.
11. As an analyst, I want anything missing, ambiguous, or behind a login recorded explicitly
    in *Collection notes* rather than guessed, so that gaps are visible, not invented.
12. As an analyst, I want a single rate-card PDF that covers several camps attributed
    correctly per camp, so that each dossier carries only its own rates.
13. As an operator of many lodges, I want a `--names-file` batch mode that collects many
    lodge groups concurrently, so that I can build a corpus without babysitting one run at a
    time.
14. As an operator, I want each batch agent to write to its own `data/raw/<slug>/` and log to
    its own `collect.log`, so that concurrent runs are independent and the terminal stays
    readable.
15. As an operator, I want to pass a local PDF rate card or extra source URLs for a single
    lodge, so that material I already have is incorporated rather than re-discovered.
16. As a cost-conscious operator, I want collection to run on the cheapest capable model by
    default, so that building a large corpus is affordable.
17. As a maintainer, I want the CLI to validate inputs up front (rate-card paths exist, skill
    is present, name-or-names-file is provided) and fail fast with a clear message, so that
    misconfiguration is caught before a model is invoked.
18. As a maintainer, I want the skill granted only the tools it needs, so that a collection
    run cannot take unrelated actions.
19. As a maintainer, I want a review manifest written into each dossier's front-matter listing
    its review files, so that the evaluate phase has a single authoritative property→reviews
    mapping it never has to re-guess.

## Implementation Decisions

### Architecture: thin deterministic CLI over a model-driven skill
- The CLI (`spoor/cli.py`, `cmd_collect`) does only what a script does well: validate
  arguments, construct the prompt, and invoke `claude -p` headlessly. All judgement
  (discovery, transcription, attribution) lives in the skill. This is the same split used by
  every other phase (`build-pricing-script`, `evaluate`, `assess`, `categorise`), so the
  pipeline is uniform.
- **Why headless `claude -p`:** the skill needs web access, file writes, and a sub-script
  (the Booking.com scraper), which is exactly what a Claude Code agent provides. The CLI just
  starts one and gets out of the way.

### Tool allow-list (least privilege)
- Collect runs with `Skill,WebFetch,WebSearch,Read,Write,Bash`:
  - `Skill` to invoke collect; `WebFetch` for website/Wetu/TripAdvisor pages; `WebSearch` to
    find review pages; `Read` for local PDFs; `Write` for dossiers; `Bash` for `curl` (large
    Wetu index, signed PDF downloads) and the Booking.com scraper.
- This is broader than the evaluate-phase allow-list (`Skill,Read,Write,Bash`) precisely
  because collect is the only network-touching phase. Keeping the network confined to collect
  is a deliberate boundary: everything downstream is offline and reproducible.

### Model default: Sonnet for collection
- Collect defaults to `claude-sonnet-4-6` — the cheapest model fully capable of faithful
  capture — while the exacting codegen phases (`build-pricing-script`, `evaluate`) default to
  Opus. Collection is high-volume transcription, not high-leverage reasoning, so the cheaper
  model is the right cost/quality trade. `--model` overrides it.

### Property discovery
- A lodge is a **group**; the unit of output is the **bookable property (camp)**. The skill
  enumerates properties from the website's accommodation navigation and reconciles them
  against Wetu (adding any Wetu-only property, noting any mismatch). Room types inside one
  camp are explicitly **not** separate properties.
- One file per property, all under `data/raw/<lodge-slug>/`. Slugs use one documented rule
  (lowercase, runs of non-alphanumerics → single hyphen, trim) applied to the lodge name and,
  separately, the property name. The CLI's `slugify` mirrors the skill's rule so both agree on
  paths.

### Wetu cross-reference (structured second source)
- Wetu's iBrochure provides per-property Fast Facts and prose sections
  (Why-Stay-Here / Room-Types / Facilities / Activities / Documentation / Contact), captured
  faithfully with the iBrochure ID noted.
- **Practical decisions forced by Wetu's mechanics**, documented in the skill so they aren't
  rediscovered each run:
  - The index is ~2 MB and truncates under WebFetch, so it is fetched with `curl` and grepped
    for the lodge name to recover iBrochure IDs.
  - Rate-card and document links are Azure blob URLs with **SAS tokens that expire within
    hours** and are signed binaries WebFetch cannot fetch, so they must be `curl`-downloaded
    **during the run** into `data/raw/<lodge-slug>/_docs/` and retained as the durable copy.
  - A `Specials/List/<ID>` link appears only when a property has live offers; specials are
    transcribed verbatim with their validity and travel windows.

### Rate cards
- Every rate-card PDF (both `--rate-card` inputs and Wetu-downloaded ones) is read with `Read`
  (needs poppler; see README). A single PDF usually covers all camps, so it is downloaded once
  and each rate block attributed to the right property. Numbers are transcribed exactly —
  never rounded or tidied — with the validity period and source PDF noted. Unattributable
  rates go to *Collection notes* rather than being force-fit.

### Reviews: immutable, append-only, per-source stores
- Guest reviews never change, so they live in per-property, per-source stores under
  `data/raw/<lodge-slug>/reviews/` (`<property>-tripadvisor.md`, `<property>-booking.jsonl`)
  and are **only ever appended to**. The dossier's `## Reviews` section is a summary
  (scores, counts, store pointers, a few quotes); the corpus lives in the stores.
- **Two capture paths by necessity** (see also the project's reviews-access memory):
  - **TripAdvisor via WebFetch** — a headless browser is blocked there, but WebFetch works;
    paginate with the `-orN-` offset. Append only reviews not already present (match on
    reviewer + date + title).
  - **Booking.com via a bundled Playwright scraper** (`scripts/booking_reviews.py`) — review
    text loads via JavaScript behind bot protection, so `curl`/WebFetch get an empty shell.
    The scraper renders the page, paginates, and dedupes into the JSONL store by content hash.

### Incremental freshness policy
- Each section carries `<!-- collected: <date>; cadence: <N> -->`. Re-runs decide per section
  against today's date: Website/Wetu 30d, Rate card 14d, Specials 3d (time-sensitive),
  Reviews **never** (append-only). Fresh sections are copied forward unchanged; stale/missing
  ones are refreshed with a new marker. A first run with no prior output is a full collection.
- **Why:** different sources change at different rates; this keeps re-runs cheap and stable
  while guaranteeing the immutable review record is never disturbed.

### Review manifest (the collect→evaluate contract)
- When writing/refreshing a dossier, collect emits a `reviews:` front-matter list of the
  review files captured for that property (filenames relative to `reviews/`), or `reviews: []`
  for the honored "no reviews captured" state. This is the single authoritative mapping the
  evaluate phase reads, decided once at collection time. Front-matter is safe: it sits above
  the body, so it affects neither the freshness hash (keyed on `## Rate card`) nor the
  completeness checklist (keyed on the prose body).

### Batch mode (`--names-file`)
- One agent per lodge name, run concurrently via a thread pool (`--concurrency`, default 3).
  Each agent writes to its own `data/raw/<slug>/` and its combined output is captured to
  `data/raw/<slug>/collect.log` (live interleaving of many agents would be unreadable).
- The per-lodge flags (`--website`, `--rate-card`, `--source`) are **rejected** with
  `--names-file`, because they don't generalise to a flat list of names — each agent
  discovers its own website. The CLI exits non-zero if any agent fails and prints a per-lodge
  ✓/✗ summary.

### Fail-fast validation and provenance discipline
- The CLI checks the collect skill exists under the project, requires a name or
  `--names-file`, and validates that every `--rate-card` path exists before invoking a model.
- The skill's standing rules: raw over polished, provenance always (website vs Wetu kept in
  separate sections), never invent (gaps go to *Collection notes*), never wipe (update in
  place), and always report the directory, files written/updated, and a one-line per-property
  summary including Wetu coverage and review counts (total vs newly added).

## Testing Decisions

Collect is the network- and model-driven phase, so its core logic is not unit-tested the way
the deterministic Python modules are; correctness is enforced by the skill's rules
(faithfulness, provenance, *Collection notes* for gaps) and verified downstream when evaluate
reads the dossiers. The testable surfaces are:

1. **CLI behaviour (deterministic).** The unit-testable parts live in `spoor/cli.py`:
   - `slugify` matches the skill's documented slug rule (and agrees with the property/lodge
     paths the skill writes).
   - `_build_collect_prompt` includes today's date, the name, website, rate cards, sources,
     and the `--no-wetu` / `--no-reviews` toggles correctly.
   - `_read_names_file` ignores blanks and `#`-comments and errors on an empty/missing file.
   - Argument validation: missing name-and-names-file, a non-existent rate card, and per-lodge
     flags combined with `--names-file` each exit non-zero with a clear message.
2. **Booking.com scraper.** The extraction/merge logic (stable content-hash dedupe, JSONL
   append, empty-store handling) is the most fragile piece and benefits from a fixture-based
   test over saved page HTML, asserting that re-running adds nothing.
3. **Manual/sampled verification of a real lodge.** Because faithful transcription is a model
   behaviour, a sampled spot-check (rates and review counts against source) is the practical
   acceptance test, recorded once rather than asserted continuously.

These assert observable CLI outputs and scraper store contents, not private helpers, so the
internals stay refactorable.

## Out of Scope

- **Any structuring, scoring, or pricing maths.** Collect captures raw material only; the
  Benchmark Safari Average Daily Rate, value/fit assessment, and reputation layer belong to
  **evaluate**. Cross-property comparison belongs to **categorise**.
- **Editorialising or summarising source content** beyond the dossier's `## Reviews` summary
  pointer — the rule is verbatim capture.
- **De-duplication or fake-review detection** across platforms (the scraper only dedupes
  identical captures within a store).
- **Sources beyond website, Wetu, rate-card PDFs, TripAdvisor, Booking.com, and explicitly
  passed `--source` inputs.** Other review sites or OTAs are not collected.
- **Re-fetching or rewriting reviews.** Reviews are immutable and append-only by design.
- **Resolving Wetu/website property mismatches automatically** — mismatches are recorded in
  *Collection notes* for a human, not silently reconciled.

## Further Notes

- **Dependencies.** Reading rate-card PDFs needs poppler (`pdftoppm`); the Booking.com scraper
  needs Playwright + Chromium (`pip install playwright && python3 -m playwright install
  chromium`). Both are documented in the README and the project memory.
- **`_docs/` is provenance.** Wetu's signed PDF links expire within hours, so the local copy
  in `data/raw/<lodge-slug>/_docs/` is the durable record — never delete it on a re-run.
- **Provenance for passed rate cards.** A rate card passed to the CLI must end up persisted in
  the raw dossier/`_docs/`, not just read transiently, so the source is reproducible later.
- **Batch logs.** In `--names-file` mode, a failing lodge leaves its diagnostics in
  `data/raw/<slug>/collect.log`; the CLI's exit code and ✓/✗ summary flag which to inspect.
- **Sequencing.** Collect is the first phase; evaluate depends on its dossiers and the review
  manifest, and will warn-and-skip the reputation section for any dossier missing the manifest
  (see reviews-prd.md). Keeping the manifest emission in collect means new collections are
  wired for evaluate by default.
