# How We Document

How to write and maintain documentation in `spoor`. Adapted from the Magic Lake
documentation standards.

## Table of Contents

- [Table of contents requirement](#table-of-contents-requirement)
- [Plain words, not acronyms](#plain-words-not-acronyms)
- [Documentation altitude](#documentation-altitude)
- [Writing an overview doc](#writing-an-overview-doc)
- [Where docs live](#where-docs-live)
- [File naming](#file-naming)

## Table of contents requirement

Every documentation file (`.md`) starts with a table of contents. Update it
whenever the structure changes. Very short files (under ~30 lines) are exempt.

## Plain words, not acronyms

Spell things out. Early docs leaned on acronyms and it cost readers — someone new
should not have to decode initials to follow a sentence.

- Write **average daily rate**, **architecture decisions**, **product requirements
  document** in full.
- If a short form genuinely earns its keep, introduce it once in parentheses, then
  stay consistent.
- Universally standard ones are fine as-is: US dollar / USD, PDF, JSON, URL.

## Documentation altitude

A doc states **intent, contracts, invariants, and the reasons behind them** — the
things the code cannot say — and **points into the code** for everything else. It
never reproduces what a file or function already contains.

**Do write:**
- Why the system is shaped this way — the decisions, the trade-offs, the rejected
  alternatives.
- The contracts between parts: who owns what, what is frozen when, the ordering rules
  and why they exist.
- The invariants and operating rules: the determinism guarantee, "the raw tree is
  never mutated", and the like.
- Pointers: "see `spoor/categories.py`", "the skill's `SKILL.md` is authoritative".

**Don't write:**
- Directory trees annotated file by file — they restate the code and rot on the next
  refactor.
- Function signatures, schema dumps, or field lists that duplicate the source — link
  the file instead.
- A wall of `file:line` citations. Link the **file**, not the line. A line-number wall
  is the tell that a doc has dropped to code altitude.

The test: if a behaviour-preserving refactor would make the doc wrong, the doc is
written at the wrong altitude.

## Writing an overview doc

An overview doc explains an architecture or a stage to someone who needs the mental
model, not the code:

- **Lead with the model.** Open with the core concepts and the end-to-end flow; detail
  follows.
- **Explain what and why, not how.** The code carries the how.
- **Define every term on first use**, in plain language.
- **Describe the present** — no change history, no "as-built" status blocks.
- **Ground each concept in its main file**, linked once, so the doc is a map into the
  codebase.
- **Keep paragraphs short**; break dense ones into bullets.
- **Teach by example** — one concrete walk-through beats abstract description.
- **Use diagrams for flow and concepts, not code** — clean and captioned.

## Where docs live

- `README.md` — the canonical, run-it description of the tool.
- `architecture_decisions.md` — the decisions and their reasons.
- `CLAUDE.md` — the entry point and rules for Claude Code; an index, not the
  documentation itself.
- `docs/` — longer-form guides and design docs (this file; the database-migration
  design under `docs/db-migration/`).

## File naming

Descriptive, underscore-separated: `how_we_doc.md`, `architecture_decisions.md`. Be
specific over short.
