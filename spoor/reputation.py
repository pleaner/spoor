"""The reputation layer: parse a property's review files into a deterministic block.

This mirrors :mod:`spoor.benchmark` — pure, tested parsing that the LLM never
hand-assembles. It owns three things:

  * parsing one TripAdvisor markdown file's *stated* header values (overall rating,
    five-point scale, total review count) plus the size of the quoted sample,
  * parsing one Booking.com ``.jsonl`` file into computed values (average score,
    ten-point scale, record count, score distribution, date span), and
  * aggregating a manifest's files into a per-source reputation block.

Two hard rules from the PRD live here:

  * **Sources stay separate, keyed by source.** A five-point TripAdvisor rating and
    a ten-point Booking.com score are never blended into one composite.
  * **TripAdvisor's overall is taken verbatim, not recomputed.** The quoted sample
    is partial and sorted toward the top, so averaging it would manufacture a
    misleadingly high figure; the stated overall is the authoritative one.

Parsing never raises on malformed input: a missing header field is recorded as
``None`` (or an empty value) with a warning, and a bad ``.jsonl`` line is skipped
with a warning — one bad file must not break a lodge's evaluation.

A merge CLI folds the block into the property's existing ``adr.json`` as a new
top-level ``reputation`` key (the second of the two-step write; the benchmark step
writes the pricing parts first). See :func:`main`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

TRIPADVISOR_SCALE = 5
BOOKING_SCALE = 10

# Suffixes that identify a review file's source. Order matters: check the longer,
# more specific TripAdvisor suffix; ``.jsonl`` is unambiguous for Booking.com.
_TRIPADVISOR_SUFFIX = "-tripadvisor.md"
_BOOKING_SUFFIX = ".jsonl"


def infer_source(filename: str) -> "str | None":
    """Source for a review file from its suffix, or None if unrecognised."""
    name = str(filename).strip()
    if name.endswith(_BOOKING_SUFFIX):
        return "booking"
    if name.endswith(_TRIPADVISOR_SUFFIX):
        return "tripadvisor"
    return None


# ── TripAdvisor: stated header values + quoted-sample size ───────────────────
# Headers are not uniform across collected files, so each field is matched with a
# tolerant set of patterns and falls back to None (+ a warning) when absent.

# A float 1–5, near an "overall"/"rating"/"bubbles" cue. We take the first match.
_OVERALL_RE = re.compile(
    r"overall[^0-9\n]*?(\d(?:\.\d)?)\s*(?:/|of)\s*5"     # "Overall rating: 4.9 / 5", "4.9 of 5"
    r"|overall[^0-9\n]*?(\d(?:\.\d)?)\s*(?:/\s*5|bubbles)"  # "Overall: 4.9/5", "4.9 of 5 bubbles"
    r"|(\d(?:\.\d)?)\s*(?:/|of)\s*5\s*bubbles",          # bare "4.9 of 5 bubbles"
    re.I,
)
# "Total reviews ...: 235", preferred over a bare "971 reviews".
_TOTAL_LABELLED_RE = re.compile(r"total\s+reviews[^\n]*?([\d,]{1,12})", re.I)
_TOTAL_BARE_RE = re.compile(r"([\d,]{1,12})\s+reviews", re.I)

# A quoted review block is delimited by a "**Reviewer:**" line, or a heading
# (## or ###) that looks like a review entry rather than a section/meta header.
_REVIEWER_LINE_RE = re.compile(r"^\*\*Reviewer:\*\*", re.M)
_HEADING_RE = re.compile(r"^#{2,3}\s+(.*)$", re.M)
# Plural "Reviews", "Page", etc. are section headers; singular "Review N" is an entry.
_META_HEADING_RE = re.compile(
    r"^(batch|collection|sources?|reviews|page|notes?|coverage|category|store"
    r"|append|summary|listing)\b",
    re.I,
)
_REVIEW_ENTRY_RE = re.compile(r"^review\b", re.I)            # "Review 1", "Review FC-1"
_RATING_TOKEN_RE = re.compile(r"\d(?:\.\d)?\s*/\s*\d")       # "5/5", "4.5/5"
_DATE_CUE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\b|\b(?:19|20)\d{2}\b",
    re.I,
)


def _is_review_heading(text: str) -> bool:
    """Whether a heading delimits a quoted review (vs a section/meta header).

    Review headings take shapes like ``Review 3``, ``Melanie W — May 2026 — 5/5``
    or ``Anne W | January 2026 | 5/5``; section headers (``Reviews — Listing A``,
    ``Page 1``, ``Collection notes``) do not.
    """
    t = text.strip()
    if _META_HEADING_RE.match(t):
        return False
    if _REVIEW_ENTRY_RE.match(t):
        return True
    if _RATING_TOKEN_RE.search(t):
        return True
    if ("|" in t or "—" in t or "–" in t) and _DATE_CUE_RE.search(t):
        return True
    return False


def _first_group(match: "re.Match | None") -> "str | None":
    """First non-None capture group of a match, or None."""
    if match is None:
        return None
    for g in match.groups():
        if g is not None:
            return g
    return None


def find_overall_rating(text: str) -> "float | None":
    """The *stated* TripAdvisor overall on its five-point scale, or None."""
    raw = _first_group(_OVERALL_RE.search(text))
    return float(raw) if raw is not None else None


def find_total_reviews(text: str) -> "int | None":
    """The *stated* total review count on TripAdvisor, or None."""
    m = _TOTAL_LABELLED_RE.search(text)
    if m is None:
        m = _TOTAL_BARE_RE.search(text)
    if m is None:
        return None
    return int(m.group(1).replace(",", ""))


def count_quoted_reviews(text: str) -> int:
    """Number of review entries actually quoted in the file (the partial sample).

    Files use one of two delimiters — ``**Reviewer:**`` lines or per-review ``## ``
    headings — and some use both for the same entries. We take the larger of the
    two non-meta counts, which equals the entry count in every observed format.
    """
    reviewer_lines = len(_REVIEWER_LINE_RE.findall(text))
    heading_reviews = sum(1 for h in _HEADING_RE.findall(text) if _is_review_heading(h))
    return max(reviewer_lines, heading_reviews)


def parse_tripadvisor(text: str) -> dict:
    """Parse one TripAdvisor markdown file into its stated values + sample size."""
    warnings: "list[str]" = []
    overall = find_overall_rating(text)
    if overall is None:
        warnings.append("tripadvisor: stated overall rating not found")
    total = find_total_reviews(text)
    if total is None:
        warnings.append("tripadvisor: stated total review count not found")
    quoted = count_quoted_reviews(text)
    if quoted == 0:
        warnings.append("tripadvisor: no quoted reviews found in file")
    return {
        "source": "tripadvisor",
        "overall_rating": overall,
        "scale": TRIPADVISOR_SCALE,
        "total_reviews": total,
        "quoted_sample": quoted,
        "warnings": warnings,
    }


# ── Booking.com: computed values from the per-record JSONL ───────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}
# Two observed Booking 'reviewed' shapes: "2 June 2026" and "February 2, 2026".
_DATE_DMY_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_DATE_MDY_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")


def _to_float(value) -> "float | None":
    """Coerce a Booking score ('10', '9.0') to float, or None if unusable."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_booking_date(value) -> "str | None":
    """A Booking 'reviewed' string ('2 June 2026') to an ISO date, or None."""
    if not value:
        return None
    text = str(value)
    m = _DATE_DMY_RE.search(text)
    if m:
        day, month_name, year = m.group(1), m.group(2), m.group(3)
    else:
        m = _DATE_MDY_RE.search(text)
        if not m:
            return None
        month_name, day, year = m.group(1), m.group(2), m.group(3)
    month = _MONTHS.get(month_name.capitalize())
    if month is None:
        return None
    try:
        return datetime.date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None


def _score_distribution(scores: "list[float]") -> dict:
    """Counts of tens, nines, eights, and everything below eight."""
    dist = {"10": 0, "9": 0, "8": 0, "below_8": 0}
    for s in scores:
        if s >= 10:
            dist["10"] += 1
        elif s >= 9:
            dist["9"] += 1
        elif s >= 8:
            dist["8"] += 1
        else:
            dist["below_8"] += 1
    return dist


def parse_booking(text: str) -> dict:
    """Parse one Booking.com ``.jsonl`` file into computed reputation values.

    An empty file yields a record count of zero (and a null average). Non-JSON
    lines are skipped with a warning rather than raising.
    """
    warnings: "list[str]" = []
    records = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            warnings.append(f"booking: line {lineno} is not valid JSON; skipped")

    scores = [s for s in (_to_float(r.get("score")) for r in records) if s is not None]
    dates = sorted(d for d in (parse_booking_date(r.get("reviewed")) for r in records) if d)
    average = round(sum(scores) / len(scores), 1) if scores else None

    return {
        "source": "booking",
        "average": average,
        "scale": BOOKING_SCALE,
        "num_records": len(records),
        "scored_records": len(scores),
        "distribution": _score_distribution(scores),
        "span": {
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        },
        "warnings": warnings,
    }


# ── Aggregation: a manifest's files → one per-source reputation block ─────────
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _aggregate_tripadvisor(reviews_dir: Path, names: "list[str]") -> dict:
    """Combine one or more TripAdvisor files within the TripAdvisor source.

    The single-file case (every property in the current data) returns that file's
    values exactly. Multiple files sum the counts and weight the stated overall by
    each file's total so the headline stays on the five-point scale.
    """
    parsed = []
    warnings: "list[str]" = []
    for name in names:
        try:
            p = parse_tripadvisor(_read(reviews_dir / name))
        except OSError as exc:
            warnings.append(f"tripadvisor: could not read {name}: {exc}")
            continue
        p["file"] = name
        warnings.extend(f"{name}: {w}" for w in p["warnings"])
        parsed.append(p)

    if not parsed:
        return {"scale": TRIPADVISOR_SCALE, "files": [], "warnings": warnings}
    if len(parsed) == 1:
        only = parsed[0]
        return {
            "overall_rating": only["overall_rating"],
            "scale": TRIPADVISOR_SCALE,
            "total_reviews": only["total_reviews"],
            "quoted_sample": only["quoted_sample"],
            "files": [only["file"]],
            "warnings": warnings,
        }

    totals = [p["total_reviews"] for p in parsed if p["total_reviews"] is not None]
    total_reviews = sum(totals) if totals else None
    quoted_sample = sum(p["quoted_sample"] for p in parsed)
    weighted = [(p["overall_rating"], p["total_reviews"]) for p in parsed
                if p["overall_rating"] is not None and p["total_reviews"]]
    if weighted:
        overall = round(sum(r * n for r, n in weighted) / sum(n for _, n in weighted), 2)
    else:
        rated = [p["overall_rating"] for p in parsed if p["overall_rating"] is not None]
        overall = round(sum(rated) / len(rated), 2) if rated else None
    return {
        "overall_rating": overall,
        "scale": TRIPADVISOR_SCALE,
        "total_reviews": total_reviews,
        "quoted_sample": quoted_sample,
        "files": [p["file"] for p in parsed],
        "warnings": warnings,
    }


def _aggregate_booking(reviews_dir: Path, names: "list[str]") -> dict:
    """Combine one or more Booking.com files by parsing their concatenation."""
    warnings: "list[str]" = []
    texts = []
    for name in names:
        try:
            texts.append(_read(reviews_dir / name))
        except OSError as exc:
            warnings.append(f"booking: could not read {name}: {exc}")
    block = parse_booking("\n".join(texts))
    warnings.extend(block.pop("warnings"))
    block.pop("source", None)
    block["files"] = list(names)
    block["warnings"] = warnings
    return block


def build_reputation_block(reviews_dir, filenames: "list[str]") -> dict:
    """Aggregate the manifest's review files into a per-source reputation block.

    Sources are kept separate, keyed by source. An empty ``filenames`` yields an
    empty block (``{}``) — the legitimate "no reviews captured" state. Files with
    an unrecognised suffix are skipped with a top-level warning.
    """
    reviews_dir = Path(reviews_dir)
    ta_files, bk_files, warnings = [], [], []
    for name in filenames:
        source = infer_source(name)
        if source == "booking":
            bk_files.append(name)
        elif source == "tripadvisor":
            ta_files.append(name)
        else:
            warnings.append(f"unrecognised review file (no known suffix): {name}")

    block: dict = {}
    if ta_files:
        block["tripadvisor"] = _aggregate_tripadvisor(reviews_dir, ta_files)
    if bk_files:
        block["booking"] = _aggregate_booking(reviews_dir, bk_files)
    if warnings:
        block["warnings"] = warnings
    return block


# ── Merge CLI: fold the block into adr.json (step two of the two-step write) ──
# Invoked by the evaluate skill via Bash after the benchmark step has written the
# pricing parts of adr.json:
#   python -m spoor.reputation --dossier <d.md> --reviews-dir <dir> --adr <adr.json>
def main(argv: "list[str] | None" = None) -> int:
    from spoor.manifest import read_manifest

    ap = argparse.ArgumentParser(
        description="Merge a property's review files into its adr.json as a reputation block."
    )
    ap.add_argument("--dossier", required=True, help="Path to the raw <property>.md dossier (read-only).")
    ap.add_argument("--reviews-dir", required=True, help="Path to the lodge's data/raw/<lodge>/reviews/ dir.")
    ap.add_argument("--adr", required=True, help="Path to the existing <property>-adr.json to update.")
    ap.add_argument("--out", help="Write the updated JSON here (default: overwrite --adr).")
    args = ap.parse_args(argv)

    manifest = read_manifest(_read(Path(args.dossier)))
    if manifest is None:
        # Absent manifest: never guess from filenames. Warn loudly and leave
        # adr.json untouched so the evaluate skill skips only the Reputation section.
        print("reputation: SKIPPED — no review manifest (front-matter 'reviews:') in "
              f"{args.dossier}", file=sys.stderr)
        print("skipped", end="")
        return 0

    block = build_reputation_block(args.reviews_dir, manifest)
    adr_path = Path(args.adr)
    adr = json.loads(_read(adr_path))
    adr["reputation"] = block
    out = Path(args.out) if args.out else adr_path
    out.write_text(json.dumps(adr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sources = [s for s in ("tripadvisor", "booking") if s in block]
    if not sources:
        print(f"reputation: no reviews captured (empty manifest) → wrote {out}", file=sys.stderr)
        print("empty", end="")
    else:
        print(f"reputation: merged (sources: {', '.join(sources)}) → wrote {out}", file=sys.stderr)
        print("merged", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
