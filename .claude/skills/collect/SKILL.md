---
name: collect
description: Collect raw information about a safari lodge group and its individual properties (camps) from the group website, Wetu Content Central, PDF rate cards, TripAdvisor and Booking.com reviews, and any other sources. Discovers each bookable property and stores one verbatim dossier per property in data/raw/<lodge-slug>/<property-slug>.md, with reviews in data/raw/<lodge-slug>/reviews/. Incremental and append-only — re-runs refresh stale sources and add new reviews without discarding prior data. Use when gathering source material about a named lodge.
---

# Collect safari property dossiers

A safari **lodge** (e.g. "Londolozi") is usually a group that operates several
distinct **properties** — separate camps, each a bookable product with its own
value proposition, accommodation, and rates. Your job is to discover every property
in the group and gather **raw, faithful** source material for each one, writing
**one file per property**.

This is the collection stage — capture, don't editorialize. A later stage refines
and structures this material, so preserve detail, numbers, and exact wording.

> **Model:** this skill is designed to run on **Claude Sonnet 4.6** — the cheapest model
> fully capable of the collection work. The `spoor collect` CLI passes
> `--model claude-sonnet-4-6` by default.

## Inputs

You will be given:

- **Name** (required) — the lodge / group name, e.g. "Londolozi".
- **Website** (optional) — the group's official site URL.
- **Rate cards** (optional, repeatable) — paths to local PDFs. A single PDF often
  covers several properties; there may also be one per property.
- **Sources** (optional, repeatable) — additional URLs or local file paths.
- **Wetu** — unless told otherwise, always cross-reference Wetu Content Central
  (see step 3). It needs no input beyond the lodge name.
- **Reviews** — unless told otherwise, always collect TripAdvisor + Booking.com reviews
  (see step 7). Found via search from the property name; no input needed.

If the name is missing, stop and report what is needed.

## Freshness policy (incremental collection)

Collection is **incremental and append-first**, not a wipe-and-rebuild. Different
sources change at different rates, so each section of a dossier carries a marker
recording when it was collected:

```
<!-- collected: 2026-06-23; cadence: 30d -->
```

When a property dossier already exists, read it first and decide per section using
**today's date** (given in the prompt) against the cadence:

| Section | Cadence | On re-run |
|---|---|---|
| Website | 30d | Re-fetch only if older than 30 days; else keep verbatim. |
| Wetu (iBrochure content) | 30d | Re-fetch only if older than 30 days; else keep verbatim. |
| Rate card | 14d | Re-check Wetu/inputs only if older than 14 days; else keep verbatim. |
| Specials | 3d | Re-fetch if older than 3 days (they're time-sensitive); else keep. |
| Reviews | **never** | **Never re-fetch existing reviews.** Append-only — add new ones. |

Rules:
- If a section is **still fresh**, copy its existing content forward unchanged (keep its
  marker date). Don't re-fetch and don't reword.
- If a section is **stale or missing**, collect that source and rewrite the section with
  a fresh `collected:` marker (today).
- **Reviews are immutable and append-only**: never overwrite or re-summarise prior
  reviews. Run the incremental review collection (step 7) every time — it only adds
  reviews not already stored.
- For a **brand-new property** (no existing dossier), collect everything fresh.
- A run with no prior output behaves like a full first collection.

## Steps

1. **Compute the lodge slug.** Lowercase the name, replace any run of non-alphanumeric
   characters with a single hyphen, strip leading/trailing hyphens.
   `"Londolozi"` → `londolozi`. All output lives under `data/raw/<lodge-slug>/`. Create the
   directory if missing; **do not wipe it** — collection is incremental (see *Freshness
   policy* below). If a property's dossier already exists, you will update it in place,
   keeping still-fresh sections and never discarding collected reviews.

2. **Discover the properties from the website.** Use `WebFetch` on the website and
   follow its accommodation / camps / lodges navigation to enumerate every distinct
   bookable property. List them before writing anything. A property is a separately
   bookable camp (e.g. Londolozi has Founders Camp, Varty Camp, Tree Camp, Granite
   Suites, Private Granite Suites). Do **not** treat individual room types within one
   camp as separate properties. If the group has only one property, you write one file.

3. **Cross-reference Wetu Content Central.** Wetu (https://content.wetu.com/Africa) is
   a B2B supplier-content database with a rich per-property "iBrochure". Use it as a
   structured second source for every property.

   a. **Find the iBrochure IDs.** The index page is ~2 MB, so `WebFetch` truncates it —
      fetch it with `Bash`/`curl` and grep for the lodge name. Each matching row links
      to `//wetu.com/iBrochure/<ID>`. For example:

      ```bash
      curl -sL "https://content.wetu.com/Africa" -o /tmp/wetu.html
      python3 - "$LODGE_NAME" <<'PY'
      import re, sys
      html = open('/tmp/wetu.html', encoding='utf-8', errors='replace').read()
      name = sys.argv[1]
      for m in re.finditer(re.escape(name) + r'[^<]*', html):
          label = m.group(0).strip()
          if not label or 'Game Reserve' in label or 'Reserve' == label.split()[-1]:
              continue
          seg = html[m.start():m.start() + 1800]
          ib = re.search(r'iBrochure/(\d+)', seg)
          sp = re.search(r'Specials/List/(\d+)', seg)   # present only if the property has specials
          if ib:
              print(f"{ib.group(1)}\t{'specials:' + sp.group(1) if sp else 'no-specials'}\t{label}")
      PY
      ```

      This yields one row per property: `(iBrochure ID, specials flag, Wetu property
      name)`. Match each to the properties found in step 2 by name (they usually align
      closely, e.g. Wetu "Londolozi Tree Camp" ↔ website "Tree Camp"). If Wetu lists a
      property the website didn't, add it as its own property. Note any that don't match
      in *Collection notes*. A property only has a `Specials/List/<ID>` link when it has
      live specials, and that ID equals its iBrochure ID.

   b. **Fetch each property's content** (slug segment can be a throwaway like `x`):
      - **Fast Facts & overview:** `WebFetch https://wetu.com/iBrochure/en/Home/<ID>/x`
        — captures type, number of rooms, check-in/out times, minimum child age,
        spoken languages, special interests.
      - **Detail sections:** `WebFetch https://wetu.com/iBrochure/en/Information/<ID>/x/<Section>`
        for each of: `Why-Stay-Here`, `Room-Types`, `Facilities`, `Activities`,
        `Documentation`, `Contact`. Each is server-rendered with the real prose.
      Capture the values and prose faithfully, noting the iBrochure ID and section.

   c. **Download Wetu documents — especially rate cards.** The `Documentation` section
      HTML contains direct download links to Azure blob storage
      (`https://stwetuproduction.blob.core.windows.net/...`) for files like
      `RACK-RATES-2026.pdf`, `RACK-RATES-2027.pdf`, camp facts sheets, and brochures.
      These links carry **time-limited SAS tokens that expire within hours**, so you
      must download them during this run — `WebFetch` cannot fetch them (signed binary).
      Fetch the Documentation HTML with `curl`, extract the blob URLs, decode HTML
      entities (`&amp;` → `&`), and download any rate-card PDFs (filename matching
      `rack-rate` / `rate`) with `curl` into `data/raw/<lodge-slug>/_docs/`. For example:

      ```bash
      mkdir -p data/raw/<lodge-slug>/_docs
      curl -sL "https://wetu.com/iBrochure/en/Information/<ID>/x/Documentation" -o /tmp/doc.html
      python3 - <<'PY'
      import re, html
      h = open('/tmp/doc.html', encoding='utf-8', errors='replace').read()
      urls = {html.unescape(u) for u in re.findall(r'href="(https://stwetuproduction\.blob[^"]+)"', h)}
      for u in sorted(urls):
          if re.search(r'rack-rate|rate', u, re.I):
              print(u)
      PY
      # download each printed URL with: curl -sL "<url>" -o data/raw/<lodge-slug>/_docs/<name>.pdf
      ```

      A single Wetu rate-card PDF usually covers **all** camps in the group, so download
      it once. Then read it per step 5.

   d. **Specials (special offers).** If the property's index row had a `Specials/List`
      link (the `specials:<ID>` flag above), it has live offers — capture them. The list
      lives at `https://wetu.com/Specials/List/<ID>` (ID = iBrochure ID) and each offer
      has a detail page at `https://wetu.com/Specials/View/<specialID>`. Enumerate the
      detail IDs from the list, then `WebFetch` each detail page:

      ```bash
      curl -sL "https://wetu.com/Specials/List/<ID>" -o /tmp/specials.html
      grep -oiE 'Specials/View/[0-9]+' /tmp/specials.html | sort -u
      ```

      For each `Specials/View/<specialID>`, `WebFetch` it and capture **verbatim**:
      title, special type and category, **booking-validity window**, **travel/stay
      dates**, the full description (all bullet points), and terms & conditions. Note the
      `Specials/View/<specialID>` URL per offer. Specials are time-sensitive, so the
      validity and travel date ranges matter — transcribe them exactly.

4. **Gather per-property detail from the website.** For each property, capture
   faithfully: its value proposition / positioning, room/suite names and capacities,
   inclusions, activity lists, location and access (shared across the group is fine to
   repeat), seasons, and policies. Note the sub-page URL each fact came from.

5. **Rate cards.** Read every rate-card PDF — both those passed as input **and** any
   downloaded from Wetu in step 3c (`data/raw/<lodge-slug>/_docs/`). Use `Read` on each PDF
   (this needs poppler installed; see the project README). Rate cards usually list
   multiple properties — attribute each rate block to the correct property. Transcribe
   pricing **exactly**: per-night / per-person rates, currency, seasons and their date
   ranges, single supplements, child policies, inclusions/exclusions, minimum-stay
   rules, and any conservation/community levies. Do not round or "tidy" numbers. Note
   the validity period and source PDF for each block. If you cannot tell which property
   a rate belongs to, record it under that property's *Collection notes*.

6. **Other sources.** `WebFetch` URLs, `Read` local file paths. Attribute detail to the
   relevant property (or to all, if group-wide).

7. **Reviews (TripAdvisor + Booking.com) — append-only.** Guest reviews never change,
   so they are collected into per-property, per-source stores under
   `data/raw/<lodge-slug>/reviews/` and only ever appended to. Collect them every run; the
   stores dedupe so nothing is duplicated. For each property:

   a. **Find the review pages.** Use `WebSearch` to locate the property's TripAdvisor
      hotel-review page and its Booking.com reviews page. Confirm the result is the
      right property (name + location). Typical URLs:
      - TripAdvisor: `https://www.tripadvisor.com/Hotel_Review-g<geo>-d<id>-Reviews-<slug>.html`
      - Booking.com: `https://www.booking.com/reviews/<cc>/hotel/<slug>.html`

   b. **Booking.com — use the bundled scraper (headless browser).** Booking.com loads
      review text via JavaScript behind bot protection, so `WebFetch`/`curl` return
      nothing. This skill bundles a Playwright scraper at `scripts/booking_reviews.py`
      that paginates and appends to a JSONL store. Run it from the project root:

      ```bash
      python3 .claude/skills/collect/scripts/booking_reviews.py \
        --url "<booking reviews URL>" \
        --store "data/raw/<lodge-slug>/reviews/<property-slug>-booking.jsonl"
      ```

      (Needs Playwright + Chromium — `pip install playwright && python3 -m playwright install chromium`.)

      It prints a JSON summary (`booking_total_reviews`, `newly_added`, `total_in_store`).
      Use those counts; the full reviews live in the JSONL store.

   c. **TripAdvisor — use the bundled scraper (Firecrawl).** TripAdvisor blocks headless
      browsers, so the Booking.com Playwright trick won't work here. This skill bundles a
      Firecrawl-backed scraper at `scripts/tripadvisor_reviews.py` that pages through the
      `-orN-` offsets and appends to the markdown store, deduping automatically. Run it
      from the project root:

      ```bash
      python3 .claude/skills/collect/scripts/tripadvisor_reviews.py \
        --url "<tripadvisor reviews URL>" \
        --store "data/raw/<lodge-slug>/reviews/<property-slug>-tripadvisor.md"
      ```

      (Needs a Firecrawl key in `FIRECRAWL_API_KEY` — Firecrawl is a paid service, allowed
      by the brief. Get one at https://firecrawl.dev.)

      It prints a JSON summary (`tripadvisor_total_reviews`, `overall_rating`,
      `newly_added`, `total_in_store`). Use those counts; the full reviews live in the
      markdown store.

   d. The dossier's `## Reviews` section is a **summary** (scores, counts, store
      pointers, a few representative quotes) — the bulk lives in the `reviews/` stores.

8. **Write or update one dossier per property** at `data/raw/<lodge-slug>/<property-slug>.md`
   using `Write`, following the structure below. The property slug uses the same rule as
   the lodge slug, applied to the property name (`"Private Granite Suites"` →
   `private-granite-suites`). Apply the *Freshness policy*: keep fresh sections verbatim,
   rewrite stale/missing ones, and stamp each section's `collected:` marker.

   **Emit the review manifest** as a front-matter block at the very top of the dossier
   (before the `# <Property Name>` heading): a `reviews:` list of the review files
   captured for *this* property, as filenames relative to the lodge's `reviews/` dir. This
   is the single authoritative mapping the evaluate phase reads — write it whenever you
   write or refresh a dossier, so new collections are wired by default. If this property
   has no review files, write `reviews: []` (the honored "no reviews captured" state).
   Front-matter is safe: it sits above the body, so it affects neither the freshness hash
   (keyed on `## Rate card`) nor the completeness checklist (keyed on the prose body).

## Output format — `data/raw/<lodge-slug>/<property-slug>.md`

```markdown
---
reviews:
  - <property-slug>-tripadvisor.md
  - <property-slug>-booking.jsonl
---
# <Property Name>

- **Lodge group:** <Lodge Name> (<lodge-slug>)
- **Property slug:** <property-slug>
- **First collected:** <date this dossier was first created>
- **Last updated:** <today's date>
- **Sources:**
  - website: <url or "none provided">
  - wetu: <iBrochure URL/ID or "not found">
  - rate cards: <input paths, and/or Wetu PDFs in _docs/, or "none found">
  - specials: <Wetu Specials/List URL, or "none">
  - reviews: <TripAdvisor URL; Booking.com URL; or "none found">
  - <any other sources>

## Positioning
<this property's value proposition / what makes it distinct within the group>

## Website
<!-- collected: <date>; cadence: 30d -->
<faithful raw capture relevant to this property, with sub-page URLs noted inline>

## Wetu
<!-- collected: <date>; cadence: 30d -->
<Fast Facts (type, rooms, check-in/out, min child age, languages, special interests)
and faithful capture of the Why-Stay-Here / Room-Types / Facilities / Activities /
Documentation / Contact sections, with the iBrochure ID noted>

## Rate card
<!-- collected: <date>; cadence: 14d -->
<exact transcription of this property's pricing and policies, with the validity period
and source PDF noted for each rate block>

## Specials
<!-- collected: <date>; cadence: 3d -->
<one subsection per live Wetu special: title, type/category, booking-validity window,
travel/stay dates, full description (verbatim bullets), terms & conditions, and the
Specials/View URL. Omit the section or write "None" if the property has no specials.>

## Reviews
<!-- collected: <date>; cadence: never (append-only) -->
<summary only — the full corpora live in data/raw/<lodge-slug>/reviews/. Include:
- **TripAdvisor:** overall rating, total review count, how many captured, store file
  (<property-slug>-tripadvisor.md), and 1–3 representative recent quotes.
- **Booking.com:** overall score, Booking's total review count, how many captured with
  text, store file (<property-slug>-booking.jsonl), and 1–3 representative quotes.
Write "None found" for a source with no reviews page.>

## Other sources
<one subsection per additional source, headed by its URL/path>

## Collection notes
<anything missing, ambiguous, behind a login/paywall, failed to fetch, rates that
could not be confidently attributed, or website/Wetu properties that didn't match —
be explicit about gaps>
```

## Rules

- **One file per bookable property**, all under `data/raw/<lodge-slug>/`. Room types within a
  single camp are not separate properties.
- **Incremental, never wipe.** Update dossiers in place per the *Freshness policy*: keep
  fresh sections verbatim, refresh stale ones, and **append reviews** — never destroy
  previously collected data.
- **Reviews are append-only and immutable.** They live in `data/raw/<lodge-slug>/reviews/`
  (`<property-slug>-booking.jsonl`, `<property-slug>-tripadvisor.md`) and are only ever
  added to. Both bundled scrapers dedupe automatically (Booking.com via Playwright,
  TripAdvisor via Firecrawl), so re-runs add only reviews not already stored.
- **Downloaded source documents** (Wetu rate cards, etc.) go in `data/raw/<lodge-slug>/_docs/`
  and are retained as provenance — their Wetu links expire, so the local copy is the
  durable record.
- **Raw over polished.** Preserve exact figures, dates, currencies, and proper nouns.
  Quote rather than paraphrase when wording matters (policies, inclusions).
- **Provenance always.** Every fact must be attributable to a listed source; keep
  website and Wetu detail in their own sections so the origin stays clear.
- **Don't invent.** If something isn't in the sources, it goes in *Collection notes* as
  a gap — never guess.
- When done, report the lodge directory, the list of property files written/updated, and
  a one-line summary per property of what was found, refreshed, or kept (including Wetu
  coverage and review counts — total vs newly added).
