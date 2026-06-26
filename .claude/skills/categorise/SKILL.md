---
name: categorise
description: Categorise the whole evaluated corpus into a per-traveller-archetype view. For each of 14 fixed categories, writes data/categorised/<category>.md listing the properties that genuinely suit it, with a deterministically computed USD ADR range (from spoor.categories) and one grounded paragraph per property linking back to its evaluation. Reads data/evaluated/ read-only across all lodges; never mutates upstream data. Use as the final Collect → Evaluate → Categorise step.
---

# Categorise the evaluated corpus

You invert the per-property evaluation into a **per-category** view. There is a **fixed
taxonomy of 14 traveller archetypes**; you produce one markdown file per category listing
the properties that genuinely suit it. This is the only cross-property step.

> You **never** edit anything under `data/evaluated/` or `data/raw/`. You only read them,
> and you write the category files under `data/categorised/`.

Two responsibilities are split cleanly:

- **The numbers and the candidate list are deterministic** — they come from `spoor.categories`
  (which prices each property's own `price()` script for the category's party). You **never**
  hand-compute or adjust an ADR.
- **Membership and prose are yours** — you decide which candidates genuinely fit, grounded only
  in each property's evaluation, and write one paragraph each.

## Inputs (from the prompt)

- **Evaluated dir** (`data/evaluated/`, read-only, all lodges), **Categorised dir**
  (`data/categorised/`), **FX config** (`config/fx.json`), **Today's date**.

## The 14 categories

Run `python -m spoor.categories --list` to get the authoritative slug → label map. The party
shape per category is fixed in `spoor.categories`; you do not choose it.

## Steps

For **each** category slug:

1. **Get the candidates + numbers.** Run:

   ```
   python -m spoor.categories --category <slug> --evaluated data/evaluated --fx config/fx.json
   ```

   This emits JSON: the category label, the party ages, and a `properties` list already sorted
   by ADR ascending, each with `name`, `lodge`, `low_usd`, `high_usd`, `feasible_months`, and
   `eval_md` (the path to that property's evaluation markdown). **Use these numbers verbatim.**

2. **Drop the infeasible.** A property with `feasible_months == 0` cannot host this category's
   party (over capacity / no valid configuration) — exclude it on capacity grounds.

3. **Decide membership from evidence.** For each remaining candidate, read its evaluation
   markdown (`eval_md` — its Fit / Value / Reputation / Self-competitiveness sections). Include
   the property **only when the evaluation gives positive evidence it suits this archetype**
   (e.g. honeymoon → seclusion/romance/private dining; birding → birding activity/habitat;
   multi-gen family → family suites + child policy). A property may end up in many categories or
   none. Price alone is never the reason for inclusion.

4. **Write `data/categorised/<slug>.md`** with this shape:

   ```markdown
   # <Category label>
   <!-- categorised: <today> -->

   ADR basis: <party shape, e.g. 2 adults>, RACK, USD, low–high across feasible benchmark months.

   | Property | Lodge group | ADR (USD) |
   |---|---|---|
   | <Cheapest property> | <lodge> | <low>–<high> |
   | ... | ... | ... |

   ## <Property name>
   <Exactly one paragraph on why this property suits this archetype.> [source](../evaluated/<lodge>/<property>.md)

   ## <Next property>
   ...
   ```

   - Header table lists only the **included** properties, kept in the ascending-ADR order from
     the JSON. Format the range as `low–high` (e.g. `2,901–3,578`); if `low == high`, show one
     number.
   - One `##` section per included property, in the same order, each with **exactly one**
     paragraph and a `[source]` link to its evaluation markdown.
   - **Empty category** (no candidate feasible *and* suitable): still write the file with the
     header and a single line: `No evaluated properties currently suit this category.`

5. **Report** to the user: per category, how many properties were included (and note categories
   that came out empty).

## Rules

- **Numbers only from `spoor.categories`.** Never compute, round, or adjust an ADR yourself.
- **Grounding is evaluated-only.** Every claim in a paragraph must trace to that property's
  evaluation output (its `<property>.md` sections or `<property>-adr.json`). Do not read
  `data/raw/` and do not introduce facts from elsewhere.
- **One paragraph per property** — short and comparable, not a re-run of the evaluation.
- **No cross-category aggregation, ranking beyond the ADR sort, or "best overall" picks.**
- **Read-only upstream.** Your sole writes are `data/categorised/<slug>.md`.
