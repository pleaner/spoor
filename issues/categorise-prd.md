# PRD — Categorise phase

## Problem Statement

I've finished **collect** and **evaluate**. `spoor evaluate` turns each raw dossier into a
structured, reproducible per-property assessment under `data/evaluated/<lodge>/`: a generated
pricing script, a deterministic Benchmark Safari ADR table (`<property>-adr.json`), and a
grounded evaluation (`<property>.md`). That output is excellent for understanding **one
property at a time**, but it's organised the wrong way around for the question I actually want
to answer next:

- **"If I'm planning *this kind of trip*, where should I go?"** A honeymooning couple, a
  multi-generational family, a wildlife photographer, a school group — each is a distinct kind
  of traveller with a distinct party shape and distinct needs. Today I'd have to open every
  property's evaluation and mentally re-sort them by traveller type.
- **"What would it actually cost *that* traveller?"** The evaluated ADRs are computed for three
  fixed personas (couple / family / group). A real traveller archetype doesn't always match one
  of those party shapes — a solo adventurer, a corporate incentive group of eight, a school
  group of students-plus-teachers — so I can't just read a number off the existing table.
- **"Which properties genuinely suit that traveller, and why?"** I want a short, honest,
  sourced justification per property, not a vibe.

This is the **C** in the project's Collect → Evaluate → Categorise ETL (see `ADR.md`). It is
the first and only cross-property step; the earlier phases are deliberately per-property.

## Solution

A new **categorise** phase, built in the same thin-wrapper style as collect/evaluate: a small
`spoor categorise` subcommand that shells out to `claude -p` with a `categorise` skill, reading
`data/evaluated/` (never mutating it) and writing one markdown file per traveller category to
`data/categorised/<category>.md`.

It **inverts** the per-property evaluation into a **per-category** view. There is a **fixed
taxonomy of 14 traveller archetypes**. For each archetype, the phase produces a single file
that lists the properties which genuinely suit that archetype, each with a deterministically
computed price range and a one-paragraph grounded justification linking back to the property's
evaluation.

Two layers, mirroring evaluate's discipline:

1. **A deterministic numeric core.** Each category defines its own **party composition (ages)**.
   Rather than reusing one of the three precomputed personas, the phase invokes each property's
   already-generated, deterministic `price()` script with that category's party across the
   Benchmark Safari spec (5 nights from the 15th, all twelve months) and reports the **low–high
   range of the RACK ADR in USD** across the feasible months. The LLM never hand-assembles a
   number — the same tested Python that drives the evaluate ADR table drives this.
2. **Grounded prose and membership.** An LLM decides which properties belong in each category
   and writes the one-paragraph justification, where every claim must trace to the property's
   evaluation output (`<property>.md` / `<property>-adr.json`). A property is included only with
   positive supporting evidence; it may appear in many categories or none.

Concretely, the operator runs:

- `spoor categorise` — process the whole `data/evaluated/` tree once and (re)write the 14
  category files under `data/categorised/`.

## User Stories

1. As a lodge analyst, I want a `categorise` subcommand that reads `data/evaluated/` and writes
   `data/categorised/`, so that the cross-property view is cleanly separated from the
   per-property evaluation.
2. As a lodge analyst, I want categorise to never modify anything under `data/evaluated/` or
   `data/raw/`, so that my upstream source of truth stays pristine and re-runnable.
3. As a lodge analyst, I want categorise to process the entire evaluated corpus in one run
   (no per-lodge argument), so that every category file reflects all available properties at
   once.
4. As a lodge analyst, I want one markdown file per traveller category under
   `data/categorised/<category-slug>.md`, so that I can open a single file to see everywhere a
   given kind of trip can be taken.
5. As a lodge analyst, I want a **fixed taxonomy of 14 traveller archetypes** that's the same on
   every run, so that category files are stable and diffable as the corpus grows.
6. As a lodge analyst, I want the 14 categories to be: Honeymoon couple, Multi-gen family,
   Wildlife photographer, Citizen scientist / conservationist, Ultra-HNW collector, Budget
   backpacker, Solo adventure traveller, Corporate incentive group, Returning safari devotee,
   Eco-conscious traveller, Social media influencer, Medical / wellness retreat guest,
   School / student group, and Birding specialist, so that the common archetypes are covered.
7. As a lodge analyst, I want each category to define its **own party composition (ages)** that
   reflects that archetype, so that the price shown is for a party that traveller would actually
   bring.
8. As a lodge analyst, I want the price for each category computed by **invoking the property's
   existing deterministic pricing script** with the category's party — not by borrowing one of
   the three precomputed personas — so that the number is accurate for that party shape and
   still fully deterministic.
9. As a lodge analyst, I want the category party to be priced across the same Benchmark Safari
   spec (5 nights arriving the 15th, all twelve months), so that category ADRs are computed on
   the same comparable basis as the evaluate ADRs.
10. As a lodge analyst, I want each property's category price expressed as a **low–high range of
    the RACK ADR across the feasible months**, so that a single line captures seasonal spread
    without me reading twelve cells.
11. As a lodge analyst, I want that range reported in **USD**, so that properties priced in
    different native currencies (ZAR, BWP, etc.) are comparable within one category file.
12. As a lodge analyst, I want a property whose suites cannot seat the category's party (over
    capacity / no valid configuration in any month) treated as **infeasible** and excluded from
    that category on capacity grounds, so that I'm never shown a category a property can't host.
13. As a lodge analyst, I want a property included in a category **only when its evaluation gives
    positive evidence it fits**, so that membership is honest rather than a property appearing
    everywhere.
14. As a lodge analyst, I want a property to be able to appear in **several categories, or none**,
    so that genuine multi-fit and genuine non-fit are both represented.
15. As a lodge analyst, I want a category with no qualifying property to still produce a file
    with a clear "no suitable properties" note, so that the absence is explicit rather than a
    missing file.
16. As a lodge analyst, I want each category file to open with a header table of the suitable
    properties (property, lodge group, USD ADR range), **sorted by ADR ascending**, so that I
    can scan from most to least affordable at a glance.
17. As a lodge analyst, I want the header to state the ADR basis (the category's party shape,
    RACK, USD), so that I know exactly what the numbers represent.
18. As a lodge analyst, I want the body to contain one `##` section per included property with
    **exactly one paragraph** on why it suits that traveller, so that the justification is short
    and comparable across properties.
19. As a lodge analyst, I want each property's paragraph to carry a `[source]` link to that
    property's evaluation markdown, so that I can jump straight to the evidence behind the claim.
20. As a lodge analyst, I want every claim in a paragraph to trace to the property's evaluation
    output (its Fit / Value / Reputation / Self-competitiveness sections or its ADR JSON), so
    that the prose is grounded and auditable — no facts invented at the categorise stage.
21. As a lodge analyst, I want categorise to ground suitability **only in `data/evaluated/`**
    (not `data/raw/`), so that the phase depends solely on the evaluate output and never
    re-derives facts from raw dossiers.
22. As a lodge analyst, I want each category file to carry a dated `categorised` marker, so that
    I know when it was last generated.
23. As a lodge analyst, I want the numbers in every category file produced only by the tested
    deterministic core (never hand-computed by the LLM), so that the ranges are reproducible and
    verifiable.
24. As a lodge analyst, I want `categorise` to run on Opus (cross-property synthesis), like
    evaluate, so that the judgement-heavy membership and prose get the stronger model.
25. As a developer, I want the category-party ADR-range computation extracted into a tested
    Python function that takes a `price` callable plus a party, so that the range maths is
    verifiable in isolation from any real script or LLM.
26. As a developer, I want a `spoor.categories` module that owns the fixed taxonomy, discovers
    evaluated properties, and computes each property's category range, so that the deterministic
    core of the phase is a single inspectable, testable unit.
27. As a developer, I want `spoor.categories` to expose a CLI that emits the candidate
    properties + ranges for a category as JSON, so that the skill consumes computed numbers
    rather than computing them itself.
28. As a future consumer, I want the category files to be plain, stable markdown with sourced
    links, so that they can feed a site or further analysis without re-parsing the evaluations.

## Implementation Decisions

**Overall architecture**
- Same thin-wrapper pattern as collect/evaluate: the `spoor categorise` subcommand builds a
  prompt and shells out to `claude -p` with an allowed-tools set (`Skill,Read,Write,Bash`, no
  network); the real work lives in `.claude/skills/categorise/`.
- Reads `data/evaluated/` (read-only, all lodges) and writes `data/categorised/<category>.md`.
  Outputs are committed to git, consistent with the other phases.
- Two-layer determinism, mirroring evaluate: a tested numeric core (party-specific ADR range
  from each property's existing `price()` script) with LLM-authored membership + prose on top
  that must cite the evaluation output.

**Taxonomy and party shapes (fixed config in `spoor.categories` / the skill)**

The 14 categories, each with the party (ages) handed to the property's `price()`. Exact adult
ages don't matter — the pricing scripts treat any age at/above the adult threshold identically —
so only party size and children's ages are significant:

```
honeymoon-couple           Honeymoon couple                    [40,40]
multi-gen-family           Multi-gen family                    [40,40,40,40,10,14]
wildlife-photographer      Wildlife photographer               [40,40]
citizen-scientist          Citizen scientist / conservationist [40,40]
ultra-hnw-collector        Ultra-HNW collector                 [40,40]
budget-backpacker          Budget backpacker                   [40]
solo-adventure-traveller   Solo adventure traveller            [40]
corporate-incentive-group  Corporate incentive group           [40,40,40,40,40,40,40,40]
returning-safari-devotee   Returning safari devotee            [40,40]
eco-conscious-traveller    Eco-conscious traveller             [40,40]
social-media-influencer    Social media influencer             [40]
wellness-retreat-guest     Medical / wellness retreat guest    [40,40]
school-student-group       School / student group              [16,16,16,16,40,40]
birding-specialist         Birding specialist                  [40,40]
```

**The ADR number (deterministic)**
- For a category's party, drive the property's existing `price()` across the Benchmark Safari
  spec (5 nights, arrival the 15th, all twelve months — reused, not redefined).
- The displayed figure is the **low–high range of the RACK ADR in USD** across the feasible
  months. RACK basis (consistent with the benchmark headline); USD for cross-currency
  comparability within a file.
- A party that yields **zero feasible months** (over capacity / no valid configuration) excludes
  that property from the category on capacity grounds.

**Deep modules (in the `spoor` package — pure, deterministic, LLM-free)**
- `benchmark` — gains a small public helper, `persona_adr_range(price_fn, fx, year, ages)`, that
  drives a `price` callable across the twelve benchmark months for an **arbitrary** party and
  returns `{feasible_months, low_usd, high_usd}` (from `rack_adr_usd`). It reuses the existing
  per-month ADR arithmetic so the maths has a single source. This generalises the same machinery
  that `compute_adr_table` already uses for the three fixed personas.
- `categories` (new) — owns the fixed 14-category taxonomy (`slug → {label, party ages}`);
  discovers evaluated properties (a property is one with both `<property>-adr.json` and
  `<property>-pricing.py`, reading its name and benchmark year from the ADR JSON); and computes,
  per category, the candidate properties with their USD ADR ranges, **sorted ascending**, with
  infeasible parties flagged. Exposes a CLI emitting that as JSON for the skill to consume.
- `pricing` and `fx` — reused as-is (load each `<property>-pricing.py`; convert native → USD
  from the pinned dated rate).
- `cli.py` — a new `categorise` subcommand: thin orchestration that requires `data/evaluated/`
  to exist and invokes the `categorise` skill over the whole tree; default model Opus.

**The `categorise` skill (the LLM layer)**
- Inputs: read-only `data/evaluated/`; output `data/categorised/<slug>.md`; the fixed taxonomy;
  and the grounding rule (evaluated-only; numbers come only from `spoor.categories`).
- Per category: run `spoor.categories` to get the candidate properties + computed ranges; read
  each candidate's evaluation markdown for suitability evidence; include a property only with
  positive evidence and at least one feasible month.
- Output file: dated `categorised` marker; an ADR-basis line (party shape, RACK, USD); a header
  table (Property | Lodge group | ADR USD range) sorted by ADR ascending; then one `##` section
  per included property with exactly one grounded paragraph and a `[source]` link to that
  property's evaluation markdown. Empty category → a "no suitable properties" note.

**Determinism boundary**
- `spoor.categories` produces **all numbers and the candidate list**; the skill (LLM) decides
  **membership** from the evaluation prose and writes the **paragraphs**. No number in any
  category file is hand-assembled by the LLM.

## Testing Decisions

**What makes a good test here:** tests assert *external behaviour* through the deterministic
core's public interface — the USD ADR range a party produces for a given `price` callable, and
the candidate list the categories module returns for a given evaluated directory — never
internal structure. Tests are deterministic (fake `price_fn` and throwaway fixtures, no network,
no LLM in the test path). Membership and prose are LLM-mediated and are **not** unit-tested,
consistent with the evaluate phase.

**Single seam family, reusing existing prior art.** The new tests use the same fake-`price_fn`
seam already established in `tests/test_benchmark.py` (its `make_fake_price` helper and fixed
`FX` table), so there is effectively one seam shared with the existing benchmark tests.

**Modules to be tested this phase (in `tests/test_categories.py`):**
- **`benchmark.persona_adr_range`.** Driven with a fake `price_fn` (including some infeasible
  months, exactly as `test_benchmark.py` does): assert the returned `low_usd` / `high_usd` are
  the min/max of the per-month RACK ADR in USD over the feasible months, and that
  `feasible_months` reflects the closed months. A never-feasible party returns
  `feasible_months: 0` with null low/high.
- **`spoor.categories.category_ranges` (and discovery).** Against a tiny tmp-dir fixture of two
  or three throwaway `<property>-pricing.py` + `<property>-adr.json` files: assert the candidate
  list is sorted by ADR ascending and that a property whose party is infeasible is flagged/
  excluded. The fixture scripts are trivial stdlib `price()` stubs — no real rate card needed.

**Not given dedicated tests this phase:** the `categorise` skill's membership decisions and the
one-paragraph justifications (LLM-mediated, like the evaluate prose and `assess` pass), and the
`spoor categorise` CLI orchestration (a thin shell-out, like the other subcommands).

**Prior art:** `tests/test_benchmark.py` is the direct precedent — a fake `price_fn` and a fixed
`FX` table isolate the table/range logic from any real script. `pytest` is the runner; tests
live under `tests/`.

## Out of Scope

- **Extending evaluate with new personas.** Category party shapes are priced by invoking the
  existing per-property scripts at categorise time; the three fixed evaluate personas and the
  evaluate output are not changed.
- **Reading `data/raw/` at the categorise stage.** Suitability and prose are grounded solely in
  `data/evaluated/`.
- **A derived/dynamic taxonomy.** The 14 categories are fixed config; inferring categories per
  run is not in scope.
- **Ranking or scoring within a category beyond the ascending-ADR sort**, and any cross-category
  aggregation, "best overall" list, or site/export generation.
- **Per-property or per-lodge invocation** — categorise always processes the whole evaluated
  tree at once.
- **Unit tests for the LLM-authored membership/prose, the CLI orchestration, and `fx`/`pricing`**
  (the latter are reused as-is and already exercised by the evaluate tests).
- **A grounding/QA pass analogous to `assess`** for the category files — out of scope for now;
  the `[source]` links and evaluated-only grounding are the discipline.
- **Modifying `data/raw/` or `data/evaluated/`** in any way.

## Further Notes

- The key design choice the user steered: rather than mapping each archetype to one of the three
  precomputed personas, categorise **re-uses the deterministic pricing scripts** with a
  party-shape that genuinely fits each archetype. This keeps the numbers honest (true party) and
  fully deterministic (tested Python, not LLM arithmetic), at the cost of re-running each
  property's `price()` across twelve months per category — trivial, since party sizes are tiny.
- Because adult ages above the pricing scripts' adult threshold are indistinguishable, only party
  size and children's ages carry pricing signal; the several "single adult" and "two adult"
  archetypes therefore share party shapes but differ entirely in their (LLM-authored, grounded)
  suitability prose.
- Infeasibility is informative: e.g. an eight-person corporate group or a six-person school party
  simply won't fit some small luxury camps, and those camps correctly drop out of those
  categories rather than showing a misleading price.
- This PRD is the **categorise** phase only — the final stage of the Collect → Evaluate →
  Categorise ETL described in `ADR.md`.
