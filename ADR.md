# Architecture Decision Records

## Architecture

- **Implementation:** Markdown files + Claude Code skills, not Python + the Agents SDK.
  - Pros: simplicity, velocity, reuse of the Claude Code harness rather than building one; effort goes into the skills.
  - Cons: less control over direction (trusting Claude's judgement); longer routes to results, potentially more tokens.
- **Pattern:** Classic ETL — **Collect → Evaluate → Classify** — using the ubiquitous language from the brief.
- **Style:** Thin wrappers; each phase shells out to `claude -p` with a skill. Reads upstream data read-only, writes its own stage directory.

## Collect

- **Collect skill** takes the inputs (name, website, rate card) and faithfully extracts source material to `data/raw/<lodge>/` **without processing**.
- One verbatim dossier per bookable property; reviews stored alongside.
- Sources: group website, Wetu Content Central, PDF rate cards, TripAdvisor, Booking.com.
- Incremental and append-only: re-runs refresh stale sources and add reviews without discarding prior data.

## Evaluate

Two-layer phase — a deterministic numeric core with LLM-authored prose on top. Reads `data/raw/` read-only, writes `data/evaluated/`.

- **Numeric core:** per property, an LLM (Opus) generates a self-contained, stdlib-only pricing script from the rate card; tested Python (`spoor.benchmark`) drives it across a fixed Benchmark Safari → a reproducible ADR table. The LLM never hand-assembles the table.
- **Why a script per property** (vs. one parametric pricer): rate cards vary wildly (single supplements, age bands, family-suite base+additional, stay-pay specials), so explicit per-property code is more honest than a config schema — and generating it *surfaces* completeness gaps.
- **Trust model:** the one non-deterministic step (codegen) is gated by golden tests (hand-verified prices for the two richest cards: Makanyi, Tanda Tula) and a regenerate-only-on-rate-change policy (rate-card hash). "Regenerated" always means "still correct"; unchanged lodges reuse the tested script.
- **Determinism:** ADR = (rate + mandatory pppn levies) ÷ nights, RACK basis; native currency canonical with USD from a pinned, dated `fx.json` (no live FX); per-vehicle levies and soft special qualifiers excluded; fly-in assumed.
- **Model split:** Opus for codegen (high leverage, high error cost), Sonnet for the lighter `assess` grounding QA.

## Catagorise

- Final stage: turn the evaluated corpus into a per-traveller-archetype view. Reads `data/evaluated/` read-only across all lodges; never mutates upstream data.
- For each fixed traveller category, writes `data/categorised/<category>.md` listing the properties that genuinely suit it, with a deterministically computed USD ADR range (`spoor.categories`) and one grounded paragraph per property linking back to its evaluation.
- **Out of scope until here:** cross-property comparison, peer grouping, ranking.
