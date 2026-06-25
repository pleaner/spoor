---
name: build-pricing-script
description: Turn one safari property's raw rate card into a self-contained, stdlib-only Python pricing script that brute-forces the cheapest valid room configuration for a party and stay. Reads data/raw/<lodge>/<property>.md (and the source PDF), writes data/evaluated/<lodge>/<property>-pricing.py exposing price(start, end, ages=[...]) plus an argparse CLI. Stamps the rate-card hash for the rebuild policy and self-tests the result. Use when (re)generating a single property's pricing logic.
---

# Build a property pricing script

You convert one property's **raw rate card** into an explicit, deterministic
**pricing script**. This is the single highest-leverage, most error-sensitive step
in the evaluate phase, so it runs on **Opus**. Get the numbers right.

> **Never mutate `data/raw/`.** It is your read-only source of truth. You only ever
> write under `data/evaluated/<lodge>/`.

## Inputs (from the prompt)

- **Lodge slug** and **Property slug**.
- **Raw dossier** path: `data/raw/<lodge>/<property>.md` (read-only).
- **Output** path: `data/evaluated/<lodge>/<property>-pricing.py`.
- **Force rebuild** flag.
- **Today's date.**

## Reference implementations

Two committed scripts are the canonical examples of the exact shape, search engine,
and rules you must follow — **read them first** and mirror their structure:

- `data/evaluated/makanyi-lodge/makanyi-private-game-lodge-pricing.py`
- `data/evaluated/tanda-tula/safari-camp-pricing.py`

They are also covered by golden tests (`tests/test_golden_*.py`); if you regenerate
either, those tests are the acceptance gate — the script must still return the exact
pinned numbers.

## Steps

1. **Freshness check (unless `--force-rebuild`).** Decide whether a rebuild is even
   needed:

   ```bash
   python -c "from spoor.freshness import should_rebuild; \
     print(should_rebuild('data/evaluated/<lodge>/<property>-pricing.py', \
       'data/raw/<lodge>/<property>.md'))"
   ```

   If it prints `(False, ...)` and you were not asked to force, **stop** — report
   that the existing tested script is reused. Otherwise continue.

2. **Read the rate card.** Read the dossier's `## Rate card` section in full, plus
   `## Wetu` Fast Facts for minimum child age, room counts, and check-in/out. If a
   figure is ambiguous in the markdown, `Read` the original PDF under
   `data/raw/<lodge>/_docs/` (needs poppler). Transcribe rates, seasons (with exact
   dates), age bands, single supplements, levies, minimum stay, and specials
   **exactly** — do not round or invent.

3. **Generate the script** following the contract below. Embed every rate-card fact
   as data with the source PDF/section cited in comments. stdlib-only; no network, no
   third-party imports.

4. **Stamp the rate-card hash** so the rebuild policy works. Put this as the second
   line of the file (a comment):

   ```bash
   python -c "from spoor.freshness import rate_card_hash; from pathlib import Path; \
     print(rate_card_hash(Path('data/raw/<lodge>/<property>.md').read_text()))"
   ```

   → `# rate-card-sha256: <hex>`

5. **Self-test.** Run the script's CLI on a few realistic parties (a couple, a single,
   a family, a group; an in-window special; an under-min-age party) and sanity-check
   the JSON. Then load it through the package to confirm the interface:

   ```bash
   python -c "from spoor.pricing import load_pricing; \
     m=load_pricing('data/evaluated/<lodge>/<property>-pricing.py'); \
     print(m.price('2026-06-15','2026-06-20',[40,40])['rack_grand_total'])"
   ```

   If this is Makanyi or Tanda Tula, run `python -m pytest tests/test_golden_*.py`.

6. **Report** the file written, the embedded seasons/rates, the specials encoded, and
   every assumption you had to make (these feed the completeness assessment).

## The script contract

`price(start, end, ages=[...])` takes ISO date strings and a list of guest ages and
returns the **best (cheapest) valid price**, found by brute-forcing every valid way to
seat the party across the property's room types — respecting capacities, max occupancy,
child/age rules, and single-supplement penalties — and taking the minimum. Party sizes
are tiny (≤8) so an exhaustive search is trivial; copy the recursive `_best_for_night`
engine from a reference script.

**Rules the search and pricing must honour:**

- **Per-night season lookup** so a stay straddling a season boundary is priced
  correctly (price each night under its own season, then sum).
- **Best config reported**, not just the price.
- **Specials**: apply only those whose conditions are objectively checkable from the
  request itself — travel-date window, minimum nights, maximum guests, party
  composition. Respect "not combinable" (choose the lowest valid price). **Never**
  assume soft/unverifiable qualifiers (honeymoon proof-of-marriage, etc.) — report
  those as available-but-not-applied with the reason. Report applied vs
  available-not-applied either way.
- **Levies**: itemise mandatory per-person-per-night levies (conservation /
  community / sustainability) separately from the rate; age-band them if the card
  does. Levies are never discounted by specials. **Exclude** conditional per-vehicle
  levies (self-drive gate fees) under the benchmark's fly-in assumption.
- **RACK and STO** both returned.
- **Infeasible** requests (under-min-age guest, under-minimum stay, party that can't
  be seated) return `feasible: False` with a `reason`, not a fabricated price.

**Return dict shape** (keys the benchmark and report modules rely on):

```python
{
  "feasible": bool, "reason": str | None, "currency": "ZAR",
  "start": str, "end": str, "nights": int, "ages": [int, ...],
  "rack_total": float,          # accommodation only, after specials, all nights
  "sto_total": float,
  "levy_total": float,          # mandatory pppn levies, all nights (never discounted)
  "levies": [ {"name","band","per_person_per_night","people","nights","total"} ],
  "rack_grand_total": float,    # rack_total + levy_total
  "sto_grand_total": float,
  "rack_adr": float,            # rack_grand_total / nights
  "sto_adr": float,
  "config": {"rooms": [ {"suite","ages","basis","rack","sto"} ], "summary": str},
  "per_night": [ {"date","season","rack","sto","levy"} ],
  "specials_applied": [ {"name","type","free_nights"?,"saving_rack","saving_sto"} ],
  "specials_available_not_applied": [ {"name","reason"} ],
  "assumptions": [str, ...],    # every assumption made (a missing band, an
                                #   ambiguous boundary) — surfaced for completeness
  "inclusion": str,             # vs the benchmark's "all meals + 1 activity/day" min
}
```

Also expose an argparse CLI (`--start --end --ages 40,40,15`) printing the dict as
JSON, so the script can be spot-checked by hand.

## Rules

- **stdlib-only, self-contained, deterministic.** No network, no third-party imports.
- **Every number traceable** to the rate card via a comment citing the PDF/section.
- **Don't fabricate.** Missing data → an entry in `assumptions` (and, where it blocks
  pricing, an infeasible result) — never a guessed number.
- **Never touch `data/raw/`.**
