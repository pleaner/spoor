Descisions:

1. Implementation

Desicions: markup files and claude code.
Alternative: Python and Agents SDK
Advantages:
 - Simplicity and velocity. 
 - leveraging the power and capability of Claude Code without having to allocate effort at re-inventing a harness.
 - Energy invested into creating the skills.
Limitation: 
 - Less control over direction, trusting Claudes "Judgement"
 - Longer routes to the same results, potentially more token consumtions

2. Architecure

 - Classic ETL pattern
 - Collect, Evaluate, Catagorise to use ubiquitous language as defined in the brief

3. Collect

  - Collect Skill, given the inputs (Name, Website, Rate Card),
  - collect failthfully extracted infomation to the raw file without processing.
  - Website
  - Wetu (Challanging with)

4. Evaluate

  Decision: a two-layer phase — a deterministic numeric core with LLM-authored prose
  on top — built in the same thin-wrapper style as collect (subcommands shell out to
  `claude -p` with a skill). Reads `data/raw/` read-only, writes `data/evaluated/`.

  - Numeric core: per property, an LLM (Opus) generates a self-contained, stdlib-only
    pricing script from the rate card; tested Python (`spoor.benchmark`) drives it
    across a fixed Benchmark Safari → a reproducible ADR table. The LLM never
    hand-assembles the table.
  - Why generate a script per property (vs. one parametric pricer): rate cards vary
    wildly (single supplements, age bands, family-suite base+additional, stay-pay
    specials), so explicit per-property code is more honest than a config schema — and
    the act of generating it *surfaces* completeness gaps (every assumption becomes a
    finding).
  - Trust model: the single non-deterministic step (script generation) is gated by
    golden tests (hand-verified prices for the two richest cards: Makanyi, Tanda Tula)
    and a regenerate-only-on-rate-change policy (rate-card hash marker). So "regenerated"
    always means "still correct", and unchanged lodges reuse the tested script.
  - Determinism choices: ADR = (rate + mandatory pppn levies) ÷ nights, RACK basis;
    native currency canonical with USD from a pinned, dated `fx.json` (no live FX);
    per-vehicle levies and soft special qualifiers excluded; fly-in assumed.
  - Model split: Opus for codegen (high leverage, high error cost), Sonnet for the
    lighter `assess` grounding QA — mirroring collect's "cheapest model that does the job".
  - Out of scope (→ categorize): cross-property comparison, peer grouping, ranking.