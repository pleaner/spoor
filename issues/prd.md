# PRD — Evaluate phase

## Problem Statement

I've finished the **collect** phase: `spoor collect` gathers faithful, raw, per-property
dossiers for each safari lodge group under `data/raw/<lodge>/<property>.md` — including
exactly-transcribed rate cards, specials, inclusions, levies, and policies. That raw
material is rich but inert. I can't yet answer the questions that actually matter about a
property:

- **What does it cost?** The rate cards are dense and human-oriented: per-person-per-night
  sharing rates, age-banded child rates, 50%/100% single supplements, third/fourth-person
  rules, mandatory per-person and per-vehicle levies, minimum-stay rules, family-suite
  base-rate-plus-additional models, and "stay 4 pay 3" style specials. Working out the real
  price for a given party and set of dates by hand is slow and error-prone, and there's no
  consistent, comparable number across properties.
- **Is the rate sheet complete?** I don't have a systematic way to know whether a rate card
  is missing something I'd need to actually book (a season with no end date, no child policy,
  no cancellation terms, etc.).
- **What's the value and the fit?** What does a guest get at each price tier, and which kind
  of traveller (couple, family, group) does each camp actually suit?

I need an **evaluate** phase that turns raw dossiers into a structured, reproducible
assessment of each property — without ever mutating the raw data — and that does the pricing
maths deterministically so the numbers can be trusted, tested, and reused by a later stage.

This is the **E** in the project's Collect → Evaluate → Categorize ETL (see `ADR.md`).
Cross-property and market comparison belong to the future **categorize** stage, not here.

## Solution

A new **evaluate** phase, built in the same thin-wrapper style as collect: small `spoor`
subcommands that shell out to `claude -p` with a skill, reading `data/raw/` (never mutating
it) and writing to `data/evaluated/<lodge>/`, mirroring the raw per-property layout.

The phase is **two layers**:

1. **A deterministic numeric core.** For each property, an LLM generates a self-contained
   Python pricing script from the raw rate card. Deterministic Python in the `spoor` package
   then drives that script across a fixed **Benchmark Safari** to produce a reproducible
   Average Daily Rate (ADR) table — same raw in, same numbers out.
2. **Grounded prose.** An LLM writes the qualitative evaluation (value, completeness, fit,
   and a self-only competitiveness note) where every claim must cite the computed numbers or
   quote the raw dossier.

Concretely, the operator runs:

- `spoor build-pricing-script <lodge> <property>` — (re)generate one property's pricing
  script from its raw rate card. Also invoked internally by evaluate.
- `spoor evaluate <lodge>` — generate any missing/stale pricing scripts, compute the ADR
  table deterministically, and write the evaluation. Produces three files per property.
- `spoor assess <lodge>` — a grounding-only QA pass: every prose claim must trace back to
  the raw dossier or the computed numbers; flags anything unsupported.

The generated pricing script answers the core question — *given a start date, end date, and
a list of guests with their ages, what is the best price for this property, applying the rate
card's rules and any qualifying special?* — by brute-forcing the cheapest valid room
configuration. The Benchmark Safari standardises this into a comparable ADR for three
personas (Couple, Family, Group) across all twelve months.

## User Stories

1. As a lodge analyst, I want an `evaluate` subcommand that reads `data/raw/<lodge>/` and
   writes to `data/evaluated/<lodge>/`, so that evaluation output is cleanly separated from
   raw source material.
2. As a lodge analyst, I want evaluate to never modify anything under `data/raw/`, so that my
   collected source of truth stays pristine and re-runnable.
3. As a lodge analyst, I want the evaluate output laid out per-property (mirroring raw), so
   that the two stages line up file-for-file and are easy to navigate.
4. As a lodge analyst, I want each property's rate card turned into a self-contained Python
   pricing script, so that pricing logic is explicit, inspectable, and reusable rather than
   locked in a one-off calculation.
5. As a lodge analyst, I want the pricing script to accept a start date, an end date, and a
   list of guests with their ages, so that I can price any realistic party and stay.
6. As a lodge analyst, I want the script to return the **best** (cheapest) valid price for
   that request, so that I see the price a savvy guest would actually achieve.
7. As a lodge analyst, I want "best price" to be found by enumerating every valid way to seat
   the party across the property's room types (respecting capacities, max occupancy, child/age
   rules, and single-supplement penalties) and taking the minimum, so that I don't miss a
   cheaper configuration (e.g. a family suite beating two rooms plus a supplement).
8. As a lodge analyst, I want the chosen room configuration reported alongside the price, so
   that I can see *how* the best price is achieved.
9. As a lodge analyst, I want the script to apply only specials whose conditions are
   objectively checkable from the request itself (travel-date window, minimum nights, maximum
   guests, party composition), so that discounts reflect eligibility the benchmark guest
   genuinely has.
10. As a lodge analyst, I want the script to respect "not combinable" rules and choose the
    discount combination giving the lowest valid price, so that specials are applied correctly.
11. As a lodge analyst, I want the script to NOT assume soft/unverifiable qualifiers (e.g.
    honeymoon proof-of-marriage) for a generic persona, so that prices aren't fabricated as
    lower than reality.
12. As a lodge analyst, I want the script to report both the specials it applied and the ones
    that were available but not applied (with the reason), so that I understand the full
    discount picture.
13. As a lodge analyst, I want the script to return both RACK and STO/trade prices, so that I
    can see the public price and the (confidential) trade price side by side.
14. As a lodge analyst, I want mandatory per-person-per-night levies (conservation /
    community / sustainability) itemised separately from the nightly rate, so that I see both
    the rate and the unavoidable add-ons.
15. As a lodge analyst, I want conditional per-vehicle levies (e.g. self-drive gate fees)
    excluded from the benchmark price under a fly-in assumption, so that comparability isn't
    distorted by an assumed travel mode.
16. As a lodge analyst, I want each generated pricing script to be self-contained and
    stdlib-only (no network, no third-party imports), so that it's deterministic and trivially
    testable.
17. As a lodge analyst, I want the rate-card facts (seasons with exact dates, per-room rates,
    age bands, supplements, levies, specials) embedded in the script as data with the source
    PDF/section cited in comments, so that every number is traceable to its origin.
18. As a lodge analyst, I want each pricing script to expose both an importable `price(start,
    end, ages=[...])` function and an argparse CLI emitting JSON, so that it can be driven by
    code (the benchmark) and spot-checked by hand.
19. As a lodge analyst, I want the script's result to include the best total, the ADR, the
    currency, the chosen room configuration, a per-night breakdown, itemised levies, applied
    and available specials, and both RACK and STO figures, so that the output is fully
    explainable.
20. As a lodge analyst, I want a fixed **Benchmark Safari** of 5 nights, so that ADRs are
    directly comparable across properties.
21. As a lodge analyst, I want the benchmark priced for three personas — Couple (2 adults),
    Family (2 adults + children aged 6, 10, and 14), and Group (8 adults) — so that I see how
    each property serves different traveller types.
22. As a lodge analyst, I want the family persona's child ages to span the typical age bands
    (under-12 / teen / near-adult), so that age-based rate rules actually exercise.
23. As a lodge analyst, I want the benchmark computed for every one of the twelve months
    (a 5-night stay arriving the 15th), so that I capture seasonality.
24. As a lodge analyst, I want the pricing script to do per-night season lookups, so that a
    stay straddling a season boundary is priced correctly.
25. As a lodge analyst, I want ADR defined as the total cost (rate + mandatory pppn levies)
    divided by nights, so that the headline number is a true daily cost.
26. As a lodge analyst, I want the Benchmark Safari's "all meals + one activity per day"
    treated as a **minimum** inclusion spec, so that fully-inclusive camps (which bundle more)
    are priced on their standard rate without me having to unbundle anything.
27. As a lodge analyst, when a property includes *less* than the benchmark, I want the cheapest
    priced meal/activity add-ons added if the rate card quotes them, and a completeness gap
    flagged if it doesn't, so that the ADR is honest about what it does and doesn't cover.
28. As a lodge analyst, for non-safari properties (e.g. a wine farm or city guesthouse), I
    want the lodging ADR still computed but clearly marked "Benchmark N/A — not a safari
    product", so that I'm not misled into comparing unlike things.
29. As a lodge analyst, I want each ADR reported in the property's native currency as the
    canonical figure, with a secondary USD column derived from a single FX rate pinned in a
    dated config file, so that comparison is possible without sacrificing determinism.
30. As a lodge analyst, I want the FX rate and its date shown in the output, so that I know
    exactly which conversion produced the USD figures.
31. As a lodge analyst, I want the ADR table computed by tested Python (not hand-assembled by
    the LLM), so that the 36-cell table is reproducible and independently verifiable.
32. As a lodge analyst, I want a **value** assessment describing what a guest gets at each
    price tier, so that I understand the price-to-offering relationship within the property.
33. As a lodge analyst, I want a **completeness** assessment with a deterministic spine: a
    fixed checklist of fields a usable rate card must have (seasons + exact date ranges,
    per-room rates, currency, child/age policy, single supplement, levies, minimum stay,
    check-in/out, cancellation, validity period, inclusions/exclusions) marked present/absent,
    so that gaps are caught systematically rather than by vibes.
34. As a lodge analyst, I want every assumption the pricing-script generation had to make
    (a missing band, an ambiguous date boundary) logged and surfaced as a concrete
    completeness finding, so that the act of pricing reveals real holes in the rate sheet.
35. As a lodge analyst, I want a **fit** assessment of which traveller/group each camp suits,
    derived from the property's own room types, capacities, child policy, and positioning, so
    that I can match camps to travellers.
36. As a lodge analyst, I want a **self-only competitiveness note** (rack-vs-trade spread,
    seasonal price spread, single-supplement burden) that needs no other properties, so that I
    capture intra-property pricing signals now while leaving cross-property ranking to the
    categorize stage.
37. As a lodge analyst, I want evaluate to write three files per property — the generated
    pricing script, a machine-readable ADR JSON (the reproducible source of truth), and a
    human-readable evaluation markdown (an ADR table rendered from the JSON plus the grounded
    prose) — so that both machines and people can consume the result.
38. As a lodge analyst, I want every claim in the evaluation markdown to cite the computed
    numbers or quote the raw dossier, so that the prose is grounded and auditable.
39. As a lodge analyst, I want re-running evaluate on an unchanged lodge to reuse the existing,
    tested pricing script and merely recompute the ADR, so that the pipeline is reproducible
    run-to-run and I don't pay for needless code generation.
40. As a lodge analyst, I want a pricing script regenerated only when it's missing or the raw
    rate-card section has changed (detected via a stored hash/marker), so that script
    regeneration is tied to actual rate changes.
41. As a lodge analyst, I want a `--force-rebuild` flag, so that I can deliberately regenerate
    a script when I need to.
42. As a lodge analyst, I want a `build-pricing-script` subcommand, so that I can regenerate or
    debug a single property's script without running the whole evaluate stage.
43. As a lodge analyst, I want build-pricing-script (and thus evaluate, which generates scripts
    in-process) to run on Opus — the most exacting, highest-leverage step — while the lighter
    QA work runs on cheaper Sonnet, so that I spend model budget where it matters.
44. As a lodge analyst, I want an `assess` subcommand that checks grounding — does every prose
    claim in the evaluation trace to the raw dossier or the ADR JSON? — and flags unsupported
    claims without writing any evaluation content, so that I have a QA layer over the prose.
45. As a developer, I want the ADR computation extracted into a deep, tested Python module that
    takes a `price` callable and the benchmark spec and returns the table, so that the core
    maths is verifiable in isolation from any LLM.
46. As a developer, I want a golden test suite that pins hand-verified expected prices for the
    two richest rate cards (Makanyi and Tanda Tula Safari Camp), so that the generated pricing
    scripts have a concrete correctness gate.
47. As a developer, I want the golden cases to cover single-supplement, child-band,
    family-suite-vs-multiroom optimisation, levy itemisation, a stay-pay special, and an
    infeasible/min-age case, so that the full range of rate-card rules is exercised.
48. As a developer, I want the golden cases to double as the acceptance spec for any
    regenerated script, so that "regenerated" always means "still correct."
49. As a future categorize-stage consumer, I want each property's ADR table as clean,
    machine-readable JSON in native and USD currency, so that I can group peers and rank them
    later without re-parsing prose.

## Implementation Decisions

**Overall architecture**
- Same thin-wrapper pattern as collect: each `spoor` subcommand builds a prompt and shells out
  to `claude -p` with an allowed-tools set; the real work lives in `.claude/skills/`.
- Reads `data/raw/<lodge>/` (read-only) and writes `data/evaluated/<lodge>/`, mirroring raw's
  per-property layout. `data/evaluated/` outputs (including generated scripts) are committed to
  git, consistent with `data/raw/`.
- Two-layer determinism: a reproducible numeric core (generated pricing script + tested Python
  benchmark → ADR table) with LLM-authored prose on top that must cite the numbers/raw.

**Components (skills + subcommands)**
- `build-pricing-script` skill → `spoor build-pricing-script <lodge> <property>`; also invoked
  in-process by evaluate. Runs on **Opus**.
- `evaluate` skill → `spoor evaluate <lodge>`. Runs the whole stage on **Opus** (so the
  in-process script generation gets Opus too).
- `assess` skill → `spoor assess <lodge>`. Runs on **Sonnet**.
- No `compare` skill — cross-property/market competitiveness is deferred to the future
  categorize stage.

**Generated pricing script (the LLM artifact) — interface and behaviour**
- One self-contained, stdlib-only file per property at `data/evaluated/<lodge>/`. Rate-card
  facts embedded as data with source PDF/section cited in comments.
- Exposes `price(start, end, ages=[...])` returning a structured dict, plus an argparse CLI
  emitting the same dict as JSON.
- "Best price" = brute-force the cheapest valid room configuration (capacities, max occupancy,
  child/age rules, single supplements all respected); party sizes are tiny (≤8) so the search
  is trivial. The chosen configuration is reported.
- Applies only objectively-qualifying specials (date window / min-nights / max-guests / party
  composition), respects "not combinable", and reports applied vs available-but-not-applied
  (with reasons). Soft/unverifiable qualifiers are never assumed.
- Mandatory per-person-per-night levies are itemised; conditional per-vehicle levies are
  excluded under a fly-in assumption.
- Result dict includes: best total, ADR, currency, chosen room config, per-night breakdown,
  itemised levies, specials (applied + available-not-applied), and both RACK and STO figures.
- Generation logs every assumption it had to make; assumptions live in the script header and
  are surfaced into the ADR JSON so completeness can read them without an LLM.

**Benchmark Safari (fixed spec)**
- 5 nights; arrival on the 15th of each of the 12 months. ADR = (rate + mandatory pppn levies)
  ÷ 5. RACK basis (STO exposed as a secondary field).
- Personas: Couple = 2 adults; Family = 2 adults + children aged 6, 10, 14; Group = 8 adults.
- "All meals + 1 activity/day" is a minimum inclusion spec: meet-or-exceed → use standard rate
  as-is (never unbundle); includes less → add cheapest priced add-ons or flag a gap; non-safari
  property → compute lodging ADR but mark "Benchmark N/A — not a safari product".
- Native currency canonical; secondary USD column from a single FX rate pinned in a dated
  config file; FX rate + date shown in output.

**Deep modules (in the `spoor` package — pure, deterministic, LLM-free)**
- `benchmark` — owns the Benchmark Safari spec and `compute_adr_table(price_callable, fx)` →
  the full native+USD ADR table across personas × months, including Benchmark-N/A handling.
  Drives the generated `price()` so the LLM never hand-assembles the 36-cell table.
- `fx` — loads the dated `fx.json` and converts native → USD.
- `freshness` — given an existing script and the raw rate-card section, decides
  rebuild-or-reuse via a stored hash/marker; honours `--force-rebuild`.
- `pricing` — the generated `<property>-pricing.py`; a pure module whose single interface is
  `price(start, end, ages)`, loaded via importlib to feed the benchmark.
- CLI subcommands in `cli.py` — thin orchestration that wires freshness → (optional)
  build-pricing-script → benchmark computation → evaluate prose.

**Output artifacts (per property, under `data/evaluated/<lodge>/`)**
- `<property>-pricing.py` — the generated pricing script.
- `<property>-adr.json` — the machine-readable Benchmark Safari result (personas × 12 months,
  itemised rate/levies/specials, native + pinned-USD, chosen config, surfaced assumptions). The
  reproducible source of truth.
- `<property>.md` — the human evaluation: an ADR summary table rendered from the JSON plus
  grounded value / completeness / fit / self-competitiveness prose.

**Evaluation dimensions (this phase, intra-property only)**
- Value — what guests get per price tier.
- Completeness — fixed rate-card field checklist (present/absent) + the script-generation
  assumptions log as concrete findings.
- Fit — which traveller/group each camp suits, from its own rooms/capacities/child policy/
  positioning.
- Self-only competitiveness note — rack-vs-trade spread, seasonal spread, single-supplement
  burden. Cross-property competitiveness deferred to categorize.

**Regeneration policy**
- evaluate (re)generates a script only when it is missing or the raw rate-card section changed
  since last generation (compare a stored hash / `collected:` marker); otherwise it reuses the
  existing, tested script and just recomputes the ADR. `--force-rebuild` overrides.

**`assess` scope**
- Grounding only: every prose claim in `<property>.md` must trace to the raw dossier or
  `<property>-adr.json`; flag unsupported/unverifiable claims. Writes no evaluation content.
  (Arithmetic is already guarded by deterministic compute + golden tests; coverage is
  structural.)

## Testing Decisions

**What makes a good test here:** tests assert *external behaviour* through a module's public
interface — the price a script returns for a given request, or the ADR table the benchmark
module produces for a given `price` callable — never internal structure or how the number was
derived. Tests are deterministic (stdlib-only scripts, no network, no LLM in the test path).

**Modules to be tested this phase:**
- **Generated pricing scripts (golden tests).** Freeze a copy of the relevant `data/raw` under
  `tests/golden/`. For the two richest rate cards — **Makanyi** (50%/100% single supplement,
  12–18 third-person at 50%, Marula family suite, conservation levy, Stay-4-Pay-3, honeymoon)
  and **Tanda Tula Safari Camp** (pppn vs family base+additional, 6–16 / 17+ bands, age-banded
  sustainability levy, stay-pay specials) — hand-compute ~6–10 expected prices each by reading
  the PDF. Cases must cover single-supplement, child-band, family-suite-vs-multiroom
  optimisation, levy itemisation, a stay-pay special, and an infeasible/min-age case. `pytest`
  asserts the committed `<property>-pricing.py` returns those exact numbers. These cases are
  also the acceptance gate for any regenerated script.
- **`benchmark` (ADR table).** Test `compute_adr_table` with a *fake* `price_fn`: correct
  personas × 12 months, ADR = total ÷ 5, native + USD columns present, FX applied from a fixed
  rate, and Benchmark-N/A handling for non-safari input. No real script needed — the fake
  isolates the table logic from any rate card.

**Not given dedicated unit tests this phase** (still built, just not separately tested now):
`fx` and `freshness`. The `assess` grounding pass and the evaluation prose are LLM-mediated and
not unit-tested.

**Prior art:** the repo's existing pattern is a thin CLI shelling out to skills; the bundled
`scripts/booking_reviews.py` is the precedent for a self-contained, directly-runnable Python
script with a CLI — the generated pricing scripts follow that shape. `pytest` is the test
runner; tests live under `tests/` with golden fixtures under `tests/golden/`.

## Out of Scope

- **Cross-property and market competitiveness / peer grouping / ranking** — deferred to the
  future **categorize** stage, which owns comparing like with like across the corpus.
- A `compare` skill or subcommand.
- **Live FX lookups** — the USD column uses a pinned, dated rate in config; refreshing it is an
  explicit, auditable config edit, never a runtime network call.
- **Conditional per-vehicle / self-drive levies and transfer costs** in the benchmark ADR
  (fly-in assumed).
- **Assuming soft special qualifiers** (honeymoon proof-of-marriage, etc.) for benchmark
  personas.
- **Unit tests for `fx` and `freshness`**, and any automated testing of the LLM-authored prose
  or the `assess` grounding pass.
- **Re-running the generator inside the test suite** — golden tests run against committed
  scripts; regenerating-and-checking is an occasional manual acceptance step, not CI.
- **Modifying `data/raw/`** in any way.

## Further Notes

- The single non-deterministic step in an otherwise deterministic pipeline is the LLM
  generation of the pricing script; the regeneration policy (rebuild only on missing/changed
  rate card) plus the golden tests (correctness gate for any generated script) are what keep
  the overall pipeline trustworthy and reproducible.
- Generating the pricing script is what *surfaces* completeness gaps: anything the script had
  to assume to make pricing work becomes a concrete completeness finding, so completeness is a
  by-product of pricing rather than a separate guess.
- The model split (Opus for the exacting script generation that evaluate performs in-process,
  Sonnet for the lighter `assess` QA) mirrors collect's cost-conscious default of using the
  cheapest model that does the job — here the golden tests make a cheaper model *safe* for the
  codegen, but we still default the generation step to Opus given its leverage and error cost.
- Makanyi (`data/raw/makanyi-lodge/`) is currently uncommitted/new on the working tree; it and
  Tanda Tula are the two properties chosen as the golden test set because their rate cards
  exercise the widest range of rules.
- This PRD is the **evaluate** phase only; **categorize** is a separate, later phase.
