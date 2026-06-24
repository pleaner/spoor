"""Scrape guest reviews from a Booking.com property reviews page.

Booking.com loads review text via JavaScript behind bot protection, so a plain
HTTP fetch (curl/WebFetch) returns an empty shell. This uses a headless Chromium
(Playwright) to render the legacy `/reviews/...` page and extract structured
reviews, paginating via `?page=N`.

Reviews are **append-only**: results are merged into a JSONL store, keyed by a
stable content hash, so re-running only adds reviews not already captured. Guest
reviews never change, so existing entries are never modified.

This script is bundled with the `collect` skill. Run it from the project root:
    python3 .claude/skills/collect/scripts/booking_reviews.py \
        --url "https://www.booking.com/reviews/zw/hotel/victoria-falls-river-lodge.html" \
        --store "data/raw/<lodge>/reviews/<property>-booking.jsonl"

Prints a JSON summary to stdout: total in store, newly added, pages read, and the
review-count/score shown by Booking.com.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Extraction runs in the page; selectors verified against Booking.com's legacy
# reviews markup (June 2026). raw_text is always captured so nothing is lost if a
# named selector drifts.
_EXTRACT_JS = r"""
() => {
  const txt = (el, sel) => { const x = el.querySelector(sel); return x ? x.innerText.trim() : null; };
  const clean = (s) => s ? s.replace(/^[•\s]+/, '').replace(/\s+/g, ' ').trim() : s;
  const items = [...document.querySelectorAll('.review_item')];
  const reviews = items.map(el => ({
    reviewer:   txt(el, '.reviewer_name'),
    country:    txt(el, '.reviewer_country, [class*=country]'),
    score:      txt(el, '.review-score-badge, .review_item_header_score_container'),
    title:      txt(el, '.review_item_header_content, .review_item_review_title'),
    positive:   txt(el, '.review_pos, [class*=review_pos]'),
    negative:   txt(el, '.review_neg, [class*=review_neg]'),
    stayed:     txt(el, '.review_staydate, [class*=staydate]'),
    reviewed:   (txt(el, '.review_item_date') || '').replace(/^Reviewed:\s*/i, '') || null,
    tags:       [...el.querySelectorAll('li.review_info_tag')].map(t => clean(t.innerText)).filter(Boolean),
    raw_text:   el.innerText.trim(),
  }));
  const body = document.body.innerText || '';
  const countMatch = document.title.match(/([\d,]+)\s+Verified/i) || body.match(/([\d,]+)\s+(?:Verified|guest)/i);
  // Page-level aggregate, in the score container (not the per-review badges).
  const cont = document.querySelector('.review_list_score_container');
  const overall = cont ? (txt(cont, '.review-score-badge, [class*=review-score-widget]')) : null;
  const basis = txt(document, '.review_list_score_count');
  // Category subscores: the breakdown list renders as alternating "Label", "9.x"
  // lines, so pair them up from its text rather than relying on item wrappers.
  const subscores = {};
  const bd = document.querySelector('.review_score_breakdown_list');
  if (bd) {
    const parts = bd.innerText.split('\n').map(s => s.trim()).filter(Boolean);
    for (let i = 0; i < parts.length - 1; i++) {
      if (/^\d{1,2}(\.\d)?$/.test(parts[i + 1]) && !/^\d/.test(parts[i])) {
        subscores[parts[i]] = parts[i + 1];
      }
    }
  }
  return {
    reviews,
    pageCount: reviews.length,
    totalShown: countMatch ? parseInt(countMatch[1].replace(/,/g, ''), 10) : null,
    overallScore: overall,
    scoreBasis: basis,
    subscores,
    hasNext: !!document.querySelector('.review_next_page a, a.review_next_page'),
  };
}
"""

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def review_key(r: dict) -> str:
    """Stable identity for a review so re-runs dedupe rather than duplicate.

    Booking.com exposes no per-review id, so hash the immutable content."""
    basis = "|".join(
        (r.get(f) or "").strip()
        for f in ("reviewer", "country", "stayed", "title", "positive", "negative")
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _page_url(url: str, page: int) -> str:
    if page == 1:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={page}"


def load_store(store: Path) -> "tuple[list[dict], set[str]]":
    reviews: list[dict] = []
    seen: set[str] = set()
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            reviews.append(r)
            seen.add(r.get("key") or review_key(r))
    return reviews, seen


def scrape(url: str, max_pages: int = 40, settle_ms: int = 2500) -> "tuple[list[dict], dict]":
    """Return (reviews, meta). Imports Playwright lazily so the module loads even
    when it isn't installed (the CLI surfaces a clear message)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "error: Playwright is required to scrape Booking.com reviews.\n"
            "Install it:  python3 -m pip install playwright && python3 -m playwright install chromium"
        )

    collected: list[dict] = []
    meta = {"pages": 0, "totalShown": None, "overallScore": None, "scoreBasis": None, "subscores": {}}
    seen_on_run: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-US", user_agent=_UA)
        page = ctx.new_page()
        try:
            for n in range(1, max_pages + 1):
                page.goto(_page_url(url, n), wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(settle_ms)
                data = page.evaluate(_EXTRACT_JS)
                meta["pages"] = n
                if meta["totalShown"] is None:
                    meta["totalShown"] = data.get("totalShown")
                    meta["overallScore"] = data.get("overallScore")
                    meta["scoreBasis"] = data.get("scoreBasis")
                    meta["subscores"] = data.get("subscores") or {}
                rows = data.get("reviews") or []
                fresh = [r for r in rows if review_key(r) not in seen_on_run]
                if not fresh:
                    break  # empty page or a page we've already seen → done
                for r in fresh:
                    seen_on_run.add(review_key(r))
                collected.extend(fresh)
        finally:
            browser.close()
    return collected, meta


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Scrape Booking.com reviews into an append-only JSONL store.")
    ap.add_argument("--url", required=True, help="Booking.com reviews URL (…/reviews/<cc>/hotel/<slug>.html).")
    ap.add_argument("--store", required=True, help="Path to the append-only JSONL store for this property/source.")
    ap.add_argument("--max-pages", type=int, default=40, help="Safety cap on pagination (default 40).")
    args = ap.parse_args(argv)

    if not re.search(r"booking\.com/reviews/", args.url):
        print(f"warning: URL doesn't look like a Booking.com reviews page: {args.url}", file=sys.stderr)

    store = Path(args.store)
    store.parent.mkdir(parents=True, exist_ok=True)
    existing, seen = load_store(store)

    scraped, meta = scrape(args.url, max_pages=args.max_pages)

    added = 0
    with store.open("a", encoding="utf-8") as fh:
        for r in scraped:
            k = review_key(r)
            if k in seen:
                continue
            r = {"key": k, "source": "booking.com", **r}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            seen.add(k)
            added += 1

    summary = {
        "url": args.url,
        "store": str(store),
        "pages_read": meta["pages"],
        "booking_total_reviews": meta["totalShown"],
        "overall_score": meta["overallScore"],
        "score_basis": meta["scoreBasis"],
        "subscores": meta["subscores"],
        "scraped_this_run": len(scraped),
        "newly_added": added,
        "total_in_store": len(existing) + added,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
