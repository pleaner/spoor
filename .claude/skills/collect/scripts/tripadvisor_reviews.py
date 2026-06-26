"""Scrape guest reviews from a TripAdvisor hotel-review page into a markdown store.

TripAdvisor blocks headless browsers, so the Playwright trick used for Booking.com
won't work here. Instead this drives **Firecrawl** (https://firecrawl.dev) — a hosted
fetch that gets past the anti-bot wall — and parses the returned markdown
deterministically. Firecrawl is a paid service; the brief explicitly allows it.

Reviews are **append-only**: results merge into a per-property markdown store keyed by
a stable content hash carried in an inline ``<!-- ta-key: … -->`` comment, so re-running
only adds reviews not already captured. Existing entries are never rewritten; only the
header (stated overall + total) is refreshed.

The store format is the same one ``spoor.reputation.parse_tripadvisor`` already reads
(a ``- **Overall rating:** X / 5 bubbles`` header plus ``## Reviewer | Date | r/5``
review blocks), so nothing downstream changes.

This script is bundled with the `collect` skill. Run it from the project root:
    python3 .claude/skills/collect/scripts/tripadvisor_reviews.py \
        --url "https://www.tripadvisor.com/Hotel_Review-g..-d..-Reviews-<slug>.html" \
        --store "data/raw/<lodge>/reviews/<property>-tripadvisor.md"

Needs a Firecrawl key in FIRECRAWL_API_KEY (or --api-key). Prints a JSON summary to
stdout: total in store, newly added, pages read, and TripAdvisor's stated overall/total.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# ── Markdown shapes verified against Firecrawl output for TripAdvisor (June 2026) ──
# TripAdvisor renders reviews in one of two layouts; both are handled by anchoring on
# the reviewer line (reliable in both) and locating the rating relative to it.
#   Layout A — the "recent reviews" carousel:
#       - 5 of 5 bubbles            (rating, with leading dash, ABOVE the reviewer)
#       [Name](…/ClientLink?…)      (reviewer link)
#       ·
#       Jun 2026                    (date)
#       <body> … Read more
#   Layout B — the standard review list:
#       [Name](…/Profile/…) wrote a review Jun 24   (reviewer + date)
#       4 of 5 bubbles              (rating, no dash, BELOW the reviewer)
#       [Title](…/ShowUserReviews…) (optional title link)
#       <body> … Read more          (then per-category subscores, ignored)
_RATING_RE = re.compile(r"^-?\s*(\d(?:\.\d)?)\s+of\s+5\s+bubbles\s*$")
# Layout B reviewer: a Profile link followed by "wrote a review <date>".
_ANCHOR_B_RE = re.compile(
    r"^\[(?P<name>[^\]]+)\]\(https?://[^)]*?/Profile/[^)]+\)\s+wrote a review\s+(?P<date>.+?)\s*$")
# Layout A reviewer: a ClientLink, validated by a following "·" separator at call site.
_ANCHOR_A_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\(https?://[^)]*?/ClientLink[^)]*\)\s*$")
# Layout B review title: a ShowUserReviews link.
_TITLE_RE = re.compile(r"^\[(?P<title>[^\]]+)\]\(https?://[^)]*?ShowUserReviews[^)]*\)\s*$")
# A markdown image link (avatars) — never body text.
_IMG_LINK_RE = re.compile(r"^\[!\[")
# Review date for Layout A's "·"-separated form, e.g. "Jun 2026" or "12 June 2026".
_DATE_RE = re.compile(r"^(?:\d{1,2}\s+)?[A-Z][a-z]{2,8}\.?\s+(?:19|20)\d{2}$")
# Page-level stated aggregates. The first "X of 5 bubbles" is the property overall
# (decimal), ahead of any per-review rating; the first "([\d,]+) reviews" is the count.
_OVERALL_RE = re.compile(r"(\d(?:\.\d)?)\s+of\s+5\s+bubbles", re.I)
_TOTAL_RE = re.compile(r"([\d,]{1,12})\s+reviews", re.I)
# Lines that end a review body (subscores follow these and must not be captured).
_BODY_STOP = {"Read more", "Read less", "Date of stay:"}
# Dedup key carried inline so re-runs append rather than duplicate.
_KEY_COMMENT_RE = re.compile(r"<!--\s*ta-key:\s*([0-9a-f]+)\s*-->")


def _unescape(text: str) -> str:
    """Undo markdown backslash-escapes (e.g. ``Pure\\_Photography`` → ``Pure_Photography``)."""
    return re.sub(r"\\(.)", r"\1", text).strip()


def review_key(r: dict) -> str:
    """Stable identity for a review so re-runs dedupe rather than duplicate.

    TripAdvisor exposes no stable per-review id in the rendered page, so hash the
    immutable content."""
    basis = "|".join(
        (r.get(f) or "").strip()
        for f in ("reviewer", "date", "title", "text")
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _page_url(url: str, offset: int) -> str:
    """TripAdvisor paginates via an ``-orN-`` segment after ``-Reviews-``."""
    if offset == 0:
        return url
    return re.sub(r"-Reviews-", f"-Reviews-or{offset}-", url, count=1)


def property_name_from_url(url: str) -> str:
    """Best-effort human name from the ``-Reviews-<slug>-`` URL segment."""
    m = re.search(r"-Reviews-(?:or\d+-)?([A-Za-z0-9_]+)", url)
    if not m:
        return "TripAdvisor property"
    return m.group(1).replace("_", " ").strip()


def _find_anchors(lines: "list[str]") -> "list[tuple[int, str, str, str]]":
    """All review anchors as (line_index, layout, reviewer, date). Layout 'B' carries
    its date inline; layout 'A' resolves the date later (returns "")."""
    anchors = []
    n = len(lines)
    for i, raw in enumerate(lines):
        s = raw.strip()
        mb = _ANCHOR_B_RE.match(s)
        if mb:
            anchors.append((i, "B", _unescape(mb.group("name")), _unescape(mb.group("date"))))
            continue
        ma = _ANCHOR_A_RE.match(s)
        if ma and not ma.group("name").startswith("!"):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].strip() == "·":  # the carousel separator validates it
                anchors.append((i, "A", _unescape(ma.group("name")), ""))
    return anchors


def _rating_above(lines: "list[str]", i: int) -> str:
    """Layout A: the rating is the first non-blank line above the reviewer."""
    p = i - 1
    while p >= 0 and not lines[p].strip():
        p -= 1
    if p >= 0:
        m = _RATING_RE.match(lines[p].strip())
        if m:
            return m.group(1)
    return ""


def _collect_body(lines: "list[str]", start: int, end: int) -> "tuple[str, str, int]":
    """Gather body prose from ``start`` until a stop marker / next anchor. Captures a
    ShowUserReviews title if present (Layout B), skips images/ratings/separators.
    Returns (title, text, last_index)."""
    title = ""
    body: "list[str]" = []
    p = start
    while p < end:
        s = lines[p].strip()
        p += 1
        if not s:
            continue
        if s in _BODY_STOP or s.startswith("## "):
            break
        mt = _TITLE_RE.match(s)
        if mt:
            if not title:
                title = _unescape(mt.group("title"))
            continue
        if _IMG_LINK_RE.match(s) or _RATING_RE.match(s) or s == "·":
            continue
        if _ANCHOR_B_RE.match(s) or _ANCHOR_A_RE.match(s):
            break
        body.append(s)
    return title, " ".join(body).strip(), p


def extract_reviews(markdown: str) -> "tuple[list[dict], dict]":
    """Parse one Firecrawl markdown page into (reviews, stated-aggregates meta).

    Pure: no network, no IO. Handles both TripAdvisor layouts by anchoring on the
    reviewer line. Each review keeps a ``raw_text`` fallback so nothing is silently
    lost if TripAdvisor's markup drifts."""
    om = _OVERALL_RE.search(markdown)
    tm = _TOTAL_RE.search(markdown)
    meta = {
        "overall_rating": float(om.group(1)) if om else None,
        "total_reviews": int(tm.group(1).replace(",", "")) if tm else None,
    }

    lines = markdown.split("\n")
    n = len(lines)
    anchors = _find_anchors(lines)
    # A page often carries BOTH a "recent reviews" carousel (Layout A) and the full
    # review list (Layout B) for the same reviews. Layout B is canonical and complete,
    # so when it's present, drop the redundant carousel to avoid double-counting.
    if any(layout == "B" for _, layout, _, _ in anchors):
        anchors = [a for a in anchors if a[1] == "B"]
    reviews: "list[dict]" = []

    for idx, (i, layout, reviewer, date) in enumerate(anchors):
        end = anchors[idx + 1][0] if idx + 1 < len(anchors) else n

        if layout == "B":
            # Rating is the first "N of 5 bubbles" after the reviewer; body follows it.
            rating, body_start = "", i + 1
            for p in range(i + 1, end):
                m = _RATING_RE.match(lines[p].strip())
                if m:
                    rating, body_start = m.group(1), p + 1
                    break
        else:
            # Layout A: rating sits above; reviewer → · → date → body.
            rating = _rating_above(lines, i)
            p = i + 1
            while p < end and not lines[p].strip():
                p += 1
            if p < end and lines[p].strip() == "·":
                p += 1
            while p < end and not lines[p].strip():
                p += 1
            if p < end and _DATE_RE.match(lines[p].strip()):
                date = lines[p].strip()
                p += 1
            body_start = p

        title, text, last = _collect_body(lines, body_start, end)
        if not text:
            continue  # an anchor with no recoverable body isn't a usable review
        reviews.append({
            "reviewer": reviewer,
            "date": date,
            "rating": rating,
            "title": title or "(no title)",
            "text": text,
            "raw_text": "\n".join(lines[i:last]).strip(),
        })

    return reviews, meta


def render_header(property_name: str, source_url: str, meta: dict,
                  captured: int, as_of: str) -> str:
    """The store header — matches the shape ``spoor.reputation.parse_tripadvisor`` reads."""
    overall = f"{meta['overall_rating']} / 5 bubbles" if meta.get("overall_rating") is not None else "unknown"
    total = meta.get("total_reviews")
    total_line = f"{total} (as of {as_of})" if total is not None else f"unknown (as of {as_of})"
    return "\n".join([
        f"# TripAdvisor Reviews — {property_name}",
        "",
        f"- **Source:** {source_url}",
        f"- **Overall rating:** {overall}",
        f"- **Total reviews (as of collection):** {total_line}",
        f"- **Reviews captured:** {captured}",
        "- **Store:** append-only via tripadvisor_reviews.py; existing entries never rewritten.",
    ])


def render_review(r: dict) -> str:
    """One review block — heading carries a rating token so the reputation parser
    counts it; the inline key comment drives dedup on re-runs."""
    heading = f"## {r['reviewer']} | {r['date'] or 'n.d.'} | {r['rating']}/5"
    return "\n".join([
        heading,
        f"<!-- ta-key: {review_key(r)} -->",
        f"- **Reviewer:** {r['reviewer']}",
        f"- **Date:** {r['date'] or 'n.d.'}",
        f"- **Rating:** {r['rating']}/5",
        f"- **Title:** {r['title']}",
        f"- **Text:** \"{r['text']}\"",
    ])


def split_existing(store: Path) -> "tuple[list[str], set[str]]":
    """Existing review blocks (verbatim) + their dedup keys, from a prior run.

    Returns ([], set()) for a new store. Keeps existing entries byte-for-byte so a
    rewrite never mutates them — only the header is refreshed."""
    if not store.exists():
        return [], set()
    text = store.read_text(encoding="utf-8")
    parts = re.split(r"\n-{3,}\n", text)
    # parts[0] is the header; the rest are review blocks (any that carry a key).
    blocks = [b.strip() for b in parts[1:] if _KEY_COMMENT_RE.search(b)]
    keys = set(_KEY_COMMENT_RE.findall(text))
    return blocks, keys


def fetch_page(page_url: str, api_key: str) -> dict:
    """POST one page to Firecrawl and return its ``data`` block. Not unit-tested
    (network); kept tiny so the tested surface is the pure parsing above."""
    body = json.dumps({
        "url": page_url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        FIRECRAWL_ENDPOINT, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise SystemExit(f"error: Firecrawl HTTP {exc.code} for {page_url}: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: could not reach Firecrawl: {exc.reason}")
    if not payload.get("success"):
        raise SystemExit(f"error: Firecrawl returned success=false: {str(payload)[:300]}")
    return payload.get("data") or {}


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scrape TripAdvisor reviews into an append-only markdown store via Firecrawl.")
    ap.add_argument("--url", required=True, help="TripAdvisor hotel-review URL (…/Hotel_Review-…-Reviews-<slug>.html).")
    ap.add_argument("--store", required=True, help="Path to the append-only <property>-tripadvisor.md store.")
    ap.add_argument("--max-pages", type=int, default=10, help="Safety cap on pagination (default 10, ~10 reviews/page).")
    ap.add_argument("--api-key", default=os.environ.get("FIRECRAWL_API_KEY"),
                    help="Firecrawl API key (default: FIRECRAWL_API_KEY env var).")
    ap.add_argument("--property-name", help="Human property name for the header (default: derived from the URL).")
    args = ap.parse_args(argv)

    if not args.api_key:
        raise SystemExit(
            "error: TripAdvisor scraping needs a Firecrawl API key.\n"
            "Set FIRECRAWL_API_KEY or pass --api-key. Get one at https://firecrawl.dev"
        )
    if "tripadvisor." not in args.url:
        print(f"warning: URL doesn't look like a TripAdvisor page: {args.url}", file=sys.stderr)

    store = Path(args.store)
    store.parent.mkdir(parents=True, exist_ok=True)
    existing_blocks, existing_keys = split_existing(store)

    # Paginate via the -orN- offset; stop when a page adds no fresh reviews.
    scraped: "list[dict]" = []
    seen_run: "set[str]" = set()
    meta = {"overall_rating": None, "total_reviews": None}
    pages_read = 0
    for page in range(args.max_pages):
        data = fetch_page(_page_url(args.url, page * 10), args.api_key)
        revs, page_meta = extract_reviews(data.get("markdown") or "")
        pages_read += 1
        for key in ("overall_rating", "total_reviews"):
            if meta[key] is None:
                meta[key] = page_meta.get(key)
        fresh = [r for r in revs if review_key(r) not in seen_run]
        if not fresh:
            break
        for r in fresh:
            seen_run.add(review_key(r))
        scraped.extend(fresh)

    new_blocks = [render_review(r) for r in scraped if review_key(r) not in existing_keys]
    total_in_store = len(existing_blocks) + len(new_blocks)

    property_name = args.property_name or property_name_from_url(args.url)
    header = render_header(property_name, args.url, meta, total_in_store,
                           datetime.date.today().isoformat())
    all_blocks = existing_blocks + new_blocks
    content = header + "\n\n---\n\n" + "\n\n---\n\n".join(all_blocks) + "\n" if all_blocks else header + "\n"
    store.write_text(content, encoding="utf-8")

    summary = {
        "url": args.url,
        "store": str(store),
        "pages_read": pages_read,
        "tripadvisor_total_reviews": meta["total_reviews"],
        "overall_rating": meta["overall_rating"],
        "scraped_this_run": len(scraped),
        "newly_added": len(new_blocks),
        "total_in_store": total_in_store,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
