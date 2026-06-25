---
name: evaluate
description: Evaluate every property in a safari lodge group. For each property, ensure a current pricing script exists (generating it when missing or the rate card changed), compute the Benchmark Safari ADR table deterministically with the spoor Python modules, and write a grounded evaluation. Reads data/raw/<lodge>/ read-only and writes three files per property under data/evaluated/<lodge>/. Use to turn raw dossiers into a structured, reproducible assessment.
---

# Evaluate a lodge

You turn each property's raw dossier into a **structured, reproducible assessment** —
without ever mutating the raw data. The phase is two layers: a **deterministic numeric
core** (a generated pricing script driven by tested Python to produce an ADR table)
and **grounded prose** on top whose every claim cites the computed numbers or quotes
the raw dossier. This whole stage runs on **Opus** so the in-process script generation
gets Opus too.

> **Never mutate `data/raw/`.** Read it; write only under `data/evaluated/<lodge>/`.

## Inputs (from the prompt)

- **Lodge slug**, **Raw input dir** (`data/raw/<lodge>/`, read-only), **Evaluated output
  dir** (`data/evaluated/<lodge>/`), **FX config** (`config/fx.json`), **Force rebuild**
  flag, **Today's date**.

## Per-property output (mirroring raw, three files)

- `<property>-pricing.py` — the generated pricing script.
- `<property>-adr.json` — the machine-readable Benchmark Safari result (the reproducible
  source of truth), including the `reputation` block when the property has a manifest.
- `<property>.md` — the human evaluation: the ADR table rendered from the JSON plus
  grounded value / completeness / fit / self-competitiveness prose, and a `## Reputation`
  section when reviews are present.

## Steps

1. **Enumerate properties.** Each `data/raw/<lodge>/<property>.md` is one property.
   `_docs/` and `*.log` are not properties. `reviews/` is **not** a property either, but
   it is no longer ignored: it feeds the reputation step (4) via the dossier's manifest.

2. **Per property — ensure a current pricing script.** Use the freshness policy:

   ```bash
   python -c "from spoor.freshness import should_rebuild; \
     print(should_rebuild('data/evaluated/<lodge>/<property>-pricing.py', \
       'data/raw/<lodge>/<property>.md'))"
   ```

   If it says rebuild (missing / changed rate card), or `--force-rebuild` was set,
   invoke the **`build-pricing-script`** skill for this property. Otherwise reuse the
   existing, tested script unchanged and just recompute the ADR.

3. **Per property — compute the ADR table deterministically.** Do NOT hand-assemble the
   36-cell table. Pick the benchmark **year** from the rate card's validity, decide
   whether it is a safari product (a wine farm or city guesthouse is not), then:

   ```bash
   python -m spoor.benchmark \
     --script data/evaluated/<lodge>/<property>-pricing.py \
     --year <YYYY> --fx config/fx.json \
     --property-name "<Property Name>" \
     [--non-safari] [--inclusion "<one-line inclusion note>"] \
     --out data/evaluated/<lodge>/<property>-adr.json
   ```

   The Benchmark Safari is fixed (5 nights from the 15th of each month; Couple / Family
   / Group personas). "All meals + 1 activity/day" is a **minimum** inclusion spec:
   fully-inclusive camps are priced on their standard rate as-is; if a property includes
   *less*, note the cheapest add-on or flag a gap; a non-safari property gets the
   `--non-safari` flag (lodging ADR still computed, marked N/A).

4. **Per property — merge the reputation block into the ADR JSON** (the second of the
   two-step write; pricing parts were written in step 3). This is pure parsing — no model
   call, no web access — so it re-runs cheaply on every evaluate and always reflects the
   current review files:

   ```bash
   python -m spoor.reputation \
     --dossier data/raw/<lodge>/<property>.md \
     --reviews-dir data/raw/<lodge>/reviews \
     --adr data/evaluated/<lodge>/<property>-adr.json
   ```

   It reads the **collect-authored manifest** in the dossier front-matter (`reviews:`) and
   prints one of `merged` / `empty` / `skipped` to stdout:

   - **`merged`** — the block (per-source, never blended across scales) is now in the JSON
     under `reputation`. Write the `## Reputation` section (below).
   - **`empty`** — the manifest is present but empty (`reviews: []`): honored "no reviews
     captured". The section renders that explicitly; keep it.
   - **`skipped`** — the dossier has **no manifest** (not yet backfilled). It warns loudly
     and leaves the JSON untouched; the rendered scaffold then omits the Reputation section
     entirely. The ADR table and the other prose are still produced as normal. **Never
     guess the mapping from filenames** to paper over a missing manifest.

5. **Per property — render the deterministic scaffold**, then write the prose on top:

   ```bash
   python -m spoor.report \
     --adr data/evaluated/<lodge>/<property>-adr.json \
     --dossier data/raw/<lodge>/<property>.md \
     --out data/evaluated/<lodge>/<property>.md
   ```

   This gives you the ADR table, the completeness checklist + surfaced assumptions, and —
   when the merge wrote a `reputation` block — the reputation summary table under a
   `## Reputation` heading. Then edit `<property>.md` to fill the prose sections. **Every
   claim must cite a computed number (from the ADR JSON) or quote the raw dossier:**

   - **Value** — what a guest gets at each price tier (cite ADRs).
   - **Completeness** — confirm/correct the rendered checklist against the raw dossier;
     discuss the surfaced pricing-script assumptions as concrete gaps.
   - **Fit** — which traveller/group the camp suits, from its own room types, capacities,
     child policy, and positioning.
   - **Self-competitiveness** (this property only): rack-vs-trade spread, seasonal price
     spread, single-supplement burden — all computable from the ADR JSON. **No
     cross-property comparison** (that is the future categorize stage).
   - **Reputation** (only when the merge wrote a block; reviews are confined to *this*
     section so the four objective sections above stay grounded purely in the rate card,
     dossier facts and computed ADR). Be **faithful to what the data says, skewed neither
     way**:
     - Report the computed **distribution**, not just the headline rating; keep TripAdvisor
       (five-point) and Booking.com (ten-point) **separate** — never a blended composite.
     - Report the TripAdvisor **stated overall** (e.g. 4.9/5 over 588), and make explicit
       that the quoted sample is **partial and sorted toward the top** (e.g. 40 of 588) —
       a ceiling, not a representative average.
     - Surface criticisms **in proportion to their actual frequency** (mine the Booking.com
       `negative` fields). State plainly when **no criticism is found** in the data, so
       "no complaints captured" is distinguishable from "complaints omitted".
     - Note **recency** qualitatively from the date span / newest review.
     - **Two-tier citation:** every quantitative claim (rating, count, distribution, span)
       must match the reputation block **exactly**; every thematic claim must quote a review
       **verbatim with attribution** (source, reviewer, date). Frequency words ("several",
       "recurring") are allowed **only** when backed by an actual count or several cited
       examples — never a bare "most guests…".
     - When the block is empty ("no reviews captured"), say exactly that; do not invent.

6. **Report** per property: whether the script was rebuilt or reused, the ADR ranges, the
   reputation merge outcome (`merged` / `empty` / `skipped`), and the three files written.

## Rules

- **Reproducible:** re-running on an unchanged lodge reuses the tested scripts and only
  recomputes the ADR — same raw in, same numbers out.
- **Numbers are computed, prose is grounded.** Never let the LLM invent an ADR; never
  let a prose claim float free of the JSON or the raw dossier.
- **Reviews are additive.** The reputation block never influences the ADR or any pricing
  logic, and freshness/rebuild stays keyed only on the rate card — refreshing reviews
  never triggers a pricing-script regeneration. (The `adr.json` will still change when
  reviews change, since the block lives there; that is deterministic — same review files
  in, same block out.)
- **Never modify `data/raw/`.**
