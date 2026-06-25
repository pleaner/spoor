# PRD — Reviews in the Evaluate phase (Reputation layer)

> Note on terms: this document spells terms out in full. "Average Daily Rate" is the
> hotel-industry metric the evaluate phase already computes; its machine-readable file is
> named `adr.json` on disk, so that literal filename is kept as-is, but the concept is
> always written out in the prose.

## Problem Statement

The collect phase already gathers guest reviews for every property — TripAdvisor dossiers
(a stated overall rating plus total count, and a quoted sample of reviews) and
Booking.com records (a `.jsonl` file with per-record scores, positive and negative text,
tags, and dates). But the evaluate phase **explicitly ignores `reviews/`**. As a result,
the structured per-property assessment captures *what a stay costs* (the deterministic
Average Daily Rate table) and *what the rate card says*, but says nothing about *what
guests actually experienced*. Two properties at the same price point can be wildly
different in quality, and right now the evaluation is blind to that signal even though the
raw material is already sitting on disk.

The user wants reviews surfaced in the evaluation in a way that is **faithful to what the
data says, skewed neither positive nor negative** — without compromising the phase's
existing discipline: numbers are computed in tested Python, prose is grounded in cited
sources, and `data/raw/` is never modified.

## Solution

Add a **reputation layer** to evaluate that mirrors the existing two-layer architecture
(deterministic numbers, then grounded prose):

1. A new tested Python module computes a **reputation block** from a property's review
   files — counts, stated overalls, the Booking.com score distribution, and date spans —
   keeping the two sources separate (never blending a five-point scale and a ten-point
   scale into one misleading composite). This block is merged into the property's existing
   `adr.json` file.

2. The deterministic parts of that block are rendered into the evaluation markdown as a
   summary table, just as the Average Daily Rate table is rendered today.

3. On top of that scaffold, evaluate writes a new grounded **`## Reputation`** prose
   section that reports what the reviews say — proportionally, with criticisms surfaced in
   line with how often they actually occur, sample limitations made explicit, and recency
   noted qualitatively.

Which review files belong to which property is declared explicitly in a
**collect-authored manifest** written as front-matter in each dossier, so the mapping is
decided once at collection time and never re-guessed at evaluate time. The `assess` phase
is extended to verify the new section against the review files and the reputation block.

From the user's perspective: after this change, every evaluated property carries an
honest, source-traceable picture of its guest reputation alongside its pricing — and
re-running on unchanged inputs reproduces the same numbers.

## User Stories

1. As an analyst, I want each evaluated property to include a reputation summary, so that
   I can judge quality alongside price.
2. As an analyst, I want TripAdvisor and Booking.com scores reported separately on their
   own scales, so that I am never misled by a blended average that hides which platform
   said what.
3. As an analyst, I want the *stated* TripAdvisor overall (for example, 4.9 out of 5
   across 171 reviews) reported rather than an average recomputed from the small quoted
   sample, so that the headline figure is the authoritative one.
4. As an analyst, I want it made explicit that the TripAdvisor sample is partial and
   sorted toward the top (for example, 18 of 171 quoted), so that I treat the quoted
   reviews as a ceiling, not a representative average.
5. As an analyst, I want the Booking.com score distribution (how many tens, nines, eights
   or below), so that I can see the shape of opinion, not just the mean.
6. As an analyst, I want substantive criticisms surfaced in proportion to how often they
   appear (especially the Booking.com negative fields), so that the picture is balanced
   and not cherry-picked praise.
7. As an analyst, I want the absence of criticism stated explicitly when none is found, so
   that I can distinguish "no complaints in the data" from "complaints omitted."
8. As an analyst, I want the recency of the reviews noted (the date span, the newest
   review), so that I can discount a rating built mostly on stays before a renovation.
9. As an analyst, I want every reputation number to match a computed value exactly, so
   that I can trust the figures the same way I trust the Average Daily Rate table.
10. As an analyst, I want every thematic claim backed by a verbatim review quote with
    attribution (source, reviewer, date), so that I can verify it at the source.
11. As an analyst, I want frequency words ("several", "recurring") used only when backed by
    an actual count or multiple cited examples, so that vague aggregate claims cannot creep
    in.
12. As an analyst, I want reviews confined to the Reputation section only, so that the
    objective sections (Value, Completeness, Fit, Self-competitiveness) stay grounded
    purely in the rate card, the dossier facts, and the computed Average Daily Rate.
13. As an analyst, I want the reputation block stored in the property's `adr.json` file, so
    that there is a single machine-readable artifact per property.
14. As a maintainer, I want which review files belong to which property declared explicitly
    in the dossier, so that the mapping is reviewable and not re-guessed on every run.
15. As a maintainer, I want the collect phase to write that manifest whenever it writes or
    refreshes a dossier, so that new collections are correctly wired by default.
16. As a maintainer, I want a one-time local backfill to add the manifest to the existing
    dossiers, so that already-collected lodges work without a full re-collection from the
    web.
17. As a maintainer, I want evaluate to warn loudly and skip only the Reputation section
    when a dossier has no manifest, so that a dossier that has not been backfilled is
    obvious but its Average Daily Rate and other prose are still produced.
18. As a maintainer, I want an empty manifest (`reviews: []`) honored as a legitimate "no
    reviews captured" state, so that properties genuinely without reviews read correctly
    rather than as errors.
19. As a maintainer, I want evaluate to never fall back to guessing the mapping from
    filenames when the manifest is absent, so that a missing manifest is never silently
    papered over.
20. As a maintainer, I want a property with no review files to still produce a clear "No
    reviews captured" reputation note, so that the output is complete and explicit.
21. As a maintainer, I want the review parsing to never crash on malformed or missing
    header fields, recording empty values and reporting a parse warning instead, so that
    one bad file does not break a lodge's evaluation.
22. As a maintainer, I want the freshness and rebuild decision to remain keyed only on the
    rate card, so that refreshing reviews never triggers an expensive pricing-script
    regeneration.
23. As a maintainer, I want the reputation computation to re-run cheaply on every evaluate
    (pure parsing, no model call, no web access), so that the block always reflects the
    current review files.
24. As a reviewer running assess, I want the review files added as a third grounding
    source, so that the new section's claims can be traced like every other claim.
25. As a reviewer running assess, I want reputation numbers checked against the reputation
    block exactly and thematic quotes checked verbatim against the named review file, so
    that the section is held to the same standard as the rest of the evaluation.
26. As a reviewer running assess, I want a frequency-word claim flagged when it lacks a
    count or sufficient cited examples, so that unsupported aggregate claims are caught.
27. As a developer, I want the parsing and aggregation logic in a deep, independently
    tested module, so that the reputation numbers are reproducible and regressions are
    caught by unit tests.
28. As a developer, I want the manifest-reading logic isolated and unit-tested for the
    missing-versus-empty distinction, so that the exact behavior evaluate depends on is
    locked.

## Implementation Decisions

### Architecture
- The reputation layer mirrors the existing pattern: deterministic numbers first, grounded
  prose on top. Reviews are **additive** — they never influence the Average Daily Rate or
  any pricing logic.
- Reviews are **quarantined** to a single new `## Reputation` prose section. The four
  existing sections (Value, Completeness, Fit, Self-competitiveness) remain grounded only
  in the dossier and the `adr.json` numbers.
- The **no cross-property comparison** rule is inherited: the Reputation section is
  descriptive per-property only.

### New deep module: review parsing and aggregation
- A new module owns three things: parsing one TripAdvisor markdown file's header, parsing
  one Booking.com `.jsonl` file, and aggregating the manifest's files into a reputation
  block.
- **TripAdvisor** contributes the *stated* values verbatim: overall rating, scale (five),
  total review count, and the size of the quoted sample. It does **not** compute an average
  from the quoted sample, which is partial and sorted toward the top.
- **Booking.com** contributes computed values from the records present: average score,
  scale (ten), number of records, score distribution, and the date span (earliest and
  latest review date).
- Sources are kept **separate, keyed by source** — there is **no blended composite** across
  scales.
- Multiple files of the same source listed in a manifest aggregate within that source.
- Edge cases: an empty `.jsonl` file yields a record count of zero; missing or malformed
  header fields are recorded as empty values and never raise; a parse problem emits a
  warning rather than failing the lodge.
- **Recency:** the block records the per-source date span and total only. No trailing-window
  sub-average is computed (which would be manufactured precision from a small sample);
  recency is addressed qualitatively in the prose.

### New small module: manifest reading
- A tiny function reads the dossier's front-matter `reviews:` list and returns:
  - nothing (absent) when the field is missing — evaluate then warns and skips the
    Reputation section,
  - an empty list when the field is present but empty — honored as "no reviews captured",
  - the list of filenames otherwise.
- Source type is inferred from the filename suffix (`.jsonl` is Booking.com,
  `-tripadvisor.md` is TripAdvisor).

### Manifest (data contract in `data/raw/`)
- Each dossier gains a **front-matter block** at the top listing its review files (paths
  relative to the property's `reviews/` directory).
- The manifest is **authored by collect** going forward, and by a **one-time local
  backfill** for the nine existing lodges (matching filenames to properties by slug,
  verified against content, with no re-collection from the web).
- Evaluate only **reads** the manifest. It never writes to `data/raw/` (existing rule).
- Adding front-matter is safe: the freshness check keys only on the `## Rate card` section,
  and the completeness checklist keys on the prose body — neither is affected by
  front-matter.

### Output artifact
- The reputation block is **folded into the existing `adr.json` file** as a new top-level
  `reputation` key (alongside `property`, `benchmark`, `benchmark_applicable`, `notes`,
  `inclusion`, `currency`, `fx`, and `personas`).
- **Two-step write into one file:** the benchmark step writes the pricing parts of
  `adr.json` first; a separate reviews step then reads, modifies, and rewrites the file to
  add the reputation block. Pricing and reputation code stay decoupled and independently
  testable even though they share the artifact.

### Rendering (modified report module)
- The report module renders a deterministic **reputation summary table** from the block
  (per-source headline figures and the Booking.com distribution), exactly as it already
  renders the Average Daily Rate table. The skill writes prose on top of this scaffold
  rather than hand-typing numbers.

### Prose rules (evaluate skill)
- The `## Reputation` section must be **faithful to what the data says, skewed neither
  way**: report the computed distribution (not just the headline rating), surface
  criticisms in proportion to their actual frequency, make sample limitations explicit (for
  example, the partial top-sorted TripAdvisor sample), and note recency from the date span.
  Never manufacture or suppress signal in either direction.
- **Two-tier citation:**
  - Quantitative claims (ratings, counts, distribution, span) must match the reputation
    block exactly.
  - Thematic claims must quote a specific review verbatim with attribution (source,
    reviewer, date).
  - Frequency words ("several", "recurring") are allowed only when backed by an actual
    count or several cited examples — no bare "most guests…".

### Evaluate skill wiring
- Remove the "Ignore `reviews/`" instruction.
- Add the reviews merge step after the benchmark step.
- Implement the missing-manifest behavior (warn and skip the section, still produce the
  Average Daily Rate and other prose), the empty-manifest behavior (honored "no reviews"),
  and the never-guess-from-filenames rule.
- Add the `## Reputation` section with the honesty and two-tier citation rules.

### Collect skill change
- When writing or refreshing a dossier, emit the `reviews:` front-matter listing the review
  files captured for that property.

### Assess skill change
- Add the review files as a **third grounding source** (alongside the dossier and the
  `adr.json` numbers).
- Extract claims from the fifth (Reputation) section and trace each to either the reputation
  block (numbers must match exactly) or a verbatim quote in the named review file.
- Flag frequency-word claims lacking a count or sufficient cited examples.

### adr.json schema change
- New top-level `reputation` key. Shape (per source, illustrative):
  - `tripadvisor`: overall rating, scale, total, quoted-sample size.
  - `booking`: average, scale, number of records, distribution, span (first and last
    dates).
  - Missing sources or fields represented explicitly (absent key or empty value); an empty
    Booking.com file yields a record count of zero.

## Testing Decisions

Good tests here exercise **external behavior through the module interface**, not internal
helpers: given representative review files (real fixtures drawn from the existing
`data/raw/` samples), assert the shape and values of the produced block and rendered table.
Prior art: `tests/test_benchmark.py` (unit tests over pure functions) and
`tests/test_golden_*.py` (golden end-to-end output per real property), with shared fixtures
in `tests/conftest.py` and goldens under `tests/golden/`.

Modules to be tested (all four selected):

1. **Review parsing and aggregation (the deep core).** Unit tests for: parsing a stated
   TripAdvisor overall, total, and quoted-sample size; the Booking.com average, record
   count, and distribution; an empty `.jsonl` file yielding a record count of zero; a
   malformed or missing header field yielding an empty value without crashing; two sources
   kept separate by scale (no blended composite); and date-span extraction.
2. **Manifest reading (missing versus empty).** Unit tests for: an absent field returning
   nothing; `reviews: []` returning an empty list; a populated list returning the list; and
   suffix-based source inference.
3. **Reputation summary table rendering.** A direct render test mapping a known block to the
   expected markdown table (the report module currently has no dedicated test; this adds
   one).
4. **Golden update for one property.** Extend an existing golden (for example, makanyi or
   tanda) so its `adr.json` golden includes the reputation block, locking the full pipeline
   output for a real property end-to-end.

Tests assert observable outputs (block fields, rendered markdown, golden files) and avoid
asserting on private helpers, so the internals can be refactored without breaking tests.

## Out of Scope

- **Any influence of reviews on pricing or the Average Daily Rate.** Reviews are strictly
  additive.
- **Cross-property or cross-lodge comparison of reputation** (belongs to a future
  categorize stage).
- **Blended or normalized cross-platform scores** — deliberately excluded.
- **Trailing-window or recency-weighted sub-averages** — excluded as manufactured
  precision; recency is qualitative only.
- **Sentiment scoring or natural-language theme extraction in Python** — thematic synthesis
  stays in the grounded prose, not the deterministic layer.
- **Fixing tswalu-kalahari's missing property dossiers.** That lodge currently has only
  `reviews/` and `_docs/` and no property markdown files, so evaluate enumerates zero
  properties there; it needs a collect pass first. Tracked separately (see Further Notes).
- **De-duplication or fake-review detection** across platforms.

## Further Notes

- **Sequencing.** Recommended build order: (1) the review parsing and aggregation module
  with its unit tests; (2) the manifest-reading module with its unit tests; (3) the one-time
  local backfill of the nine existing dossiers; (4) wire the evaluate skill (merge step,
  section, rules) and update the report rendering; (5) update the collect skill to emit the
  manifest; (6) update the assess skill; (7) extend one golden test end-to-end.
- **Prerequisite for tswalu.** Reputation cannot attach to nonexistent properties; tswalu
  needs property dossiers collected before it can carry a Reputation section. This is a
  blocking gap for that lodge only and is out of scope here.
- **Backfill is a one-time gate.** Until the existing dossiers are backfilled, evaluate will
  warn and skip the Reputation section for them (by design) — their Average Daily Rate and
  other prose are unaffected.
- **Reproducibility.** Because the reputation block lives in the `adr.json` file and reviews
  are append-only, that file will change when reviews are refreshed even if the rate card is
  unchanged. This is still deterministic (the same review files in produce the same block
  out); only the rate card governs pricing-script rebuilds.
- **Data observations from the current raw set.** TripAdvisor files state an authoritative
  overall and total but quote only a partial, top-sorted sample (for example, 18 of 171).
  Booking.com `.jsonl` files appear to be the full captured set with per-record scores and
  explicit positive and negative fields. Some review files are empty (for example, a
  zero-line `.jsonl`) or absent for a source — the parser and prose must handle these
  gracefully.
