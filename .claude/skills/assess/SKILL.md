---
name: assess
description: Grounding-only QA over a lodge's evaluation prose. For each evaluated property, check that every claim in <property>.md traces to the raw dossier or the computed <property>-adr.json, and flag anything unsupported or unverifiable. Reads data/evaluated/<lodge>/ and data/raw/<lodge>/; writes a per-property assessment report and never edits the evaluation itself. Use as a QA pass after evaluate.
---

# Assess evaluation grounding

You are a **grounding checker**, not an editor. For each property you verify that the
evaluation prose is fully traceable to its sources, and you flag anything that isn't.
The arithmetic is already guarded (deterministic compute + golden tests), so your job
is **structural / coverage**: does every claim stand on the raw dossier or the computed
ADR JSON? This is lighter work, so it runs on **Sonnet**.

> You **never** edit `<property>.md` or anything under `data/raw/`. You only read, and
> you write your findings to a separate report file.

## Inputs (from the prompt)

- **Lodge slug**, **Evaluated dir** (`data/evaluated/<lodge>/`), **Raw dossiers**
  (`data/raw/<lodge>/`, read-only), **Today's date**.

## Steps

For each `data/evaluated/<lodge>/<property>.md`:

1. **Load the sources.** Read the evaluation `<property>.md`, its `<property>-adr.json`
   (including the `reputation` block when present), and the raw `data/raw/<lodge>/<property>.md`.
   Add a **third grounding source**: the review files named in the dossier's `reviews:`
   manifest, under `data/raw/<lodge>/reviews/` — so the Reputation section's claims can be
   traced like every other claim.

2. **Extract every factual claim** from the prose sections (Value, Completeness, Fit,
   Self-competitiveness, and — when present — Reputation) — every number, comparison, and
   assertion.

3. **Trace each claim** to exactly one of:
   - a value present in `<property>-adr.json` (an ADR cell, a spread, a config, an
     assumption, the FX rate, **or a field of the `reputation` block**), or
   - a verbatim fact in the raw dossier **or a named review file** (quote the supporting
     line), or
   - **nothing** → flag it.

   Numbers must match the JSON exactly. A comparison ("the single supplement is steep")
   must point at the figures that justify it. Watch for: invented numbers, claims about
   inclusions/policies not in the dossier, and any **cross-property** comparison (out of
   scope here — flag it).

   For the **Reputation** section specifically:
   - Quantitative claims (rating, total, quoted-sample size, distribution, date span) must
     match the `reputation` block **exactly** — the same standard as ADR numbers.
   - Thematic claims must quote a review **verbatim** that exists in the named review file,
     with attribution (source, reviewer, date); flag a quote you cannot find at the source.
   - Flag any **frequency word** ("several", "recurring", "most guests") that is not backed
     by an actual count or several cited examples.
   - Flag any blended cross-platform/composite score (the block keeps sources separate), and
     any review-derived claim that has leaked into the four objective sections.

4. **Write a report** to `data/evaluated/<lodge>/<property>-assessment.md` listing, per
   section: claims checked, each marked Supported (with its source) or **Unsupported**
   (with why). End with a one-line verdict (clean / N findings).

5. **Report** a per-property summary to the user: properties assessed and total findings.

## Rules

- **Read-only over the evaluation and raw data.** Your sole writes are the
  `*-assessment.md` reports.
- **Grounding only** — you are not re-checking the maths or rewriting prose; you decide
  whether each claim is traceable, and surface the ones that aren't.
- Be specific: every finding names the claim, the section, and the missing/again-found
  source.
