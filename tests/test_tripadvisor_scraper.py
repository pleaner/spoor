"""Tests for the bundled TripAdvisor scraper's pure logic.

Mirrors the inline-fixture style of test_reputation.py. The network call
(``fetch_page``) is deliberately untested — same stance as the Booking.com
scraper — so the tested surface is the deterministic parsing, key, render and
dedup. A round-trip test locks the scraper's output format to its downstream
consumer, ``spoor.reputation.parse_tripadvisor``.
"""
import importlib.util
from pathlib import Path

from spoor import reputation

REPO = Path(__file__).resolve().parent.parent
_SCRIPT = REPO / ".claude" / "skills" / "collect" / "scripts" / "tripadvisor_reviews.py"


def _load_scraper():
    spec = importlib.util.spec_from_file_location("tripadvisor_reviews", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ta = _load_scraper()

# A minimal page mirroring the real Firecrawl markdown shape for TripAdvisor.
TA_MD = """\
TANDA TULA SAFARI CAMP

4.9 of 5 bubbles

[(171 reviews)](https://www.tripadvisor.com/Hotel_Review-g1-d1-Reviews-X.html)

- 5 of 5 bubbles

[Jane D](https://www.tripadvisor.com/ClientLink?value=abc123)
·
Jun 2026

Wonderful stay, the guides were superb.

The food was incredible and the staff warm.

Read more

- 4 of 5 bubbles

[Bob K](https://www.tripadvisor.com/ClientLink?value=def456)
·
May 2026

Great location but a bit pricey for what you get.

Read more

## About
"""


# The "standard list" layout (Layout B): "[Name](/Profile/..) wrote a review <date>",
# then the rating, an optional ShowUserReviews title link, body, "Read more", subscores.
TA_MD_LAYOUT_B = """\
ISLAND SAFARI LODGE

3.7 of 5 bubbles

[(368 reviews)](https://www.tripadvisor.com/Hotel_Review-g1-d1-Reviews-X.html)

[![](https://dynamic-media-cdn.tripadvisor.com/avatar.jpg)](https://www.tripadvisor.com/Profile/janed)

[Jane D](https://www.tripadvisor.com/Profile/janed) wrote a review Jun 24

4 of 5 bubbles

[A lovely lodge](https://www.tripadvisor.com/ShowUserReviews-g1-d1-r99-X.html)

Beautiful lodge with stunning views and excellent staff.

Read more

Value

4 of 5 bubbles

Date of stay:

June 2026

[![](https://dynamic-media-cdn.tripadvisor.com/avatar2.jpg)](https://www.tripadvisor.com/Profile/bobk)

[Bob K](https://www.tripadvisor.com/Profile/bobk) wrote a review May 2026

5 of 5 bubbles

[A wonderful place](https://www.tripadvisor.com/ShowUserReviews-g1-d1-r98-X.html)

First night in Botswana and they collected us from the airport at short notice.

Read more

## About
"""


def test_extract_reviews_layout_b_list():
    reviews, meta = ta.extract_reviews(TA_MD_LAYOUT_B)
    assert meta == {"overall_rating": 3.7, "total_reviews": 368}
    assert len(reviews) == 2

    jane = reviews[0]
    assert jane["reviewer"] == "Jane D"
    assert jane["date"] == "Jun 24"
    assert jane["rating"] == "4"
    assert jane["title"] == "A lovely lodge"           # ShowUserReviews link text
    assert "stunning views" in jane["text"]
    # subscores after "Read more" must not leak into the body
    assert "Value" not in jane["text"]
    assert "Date of stay" not in jane["text"]

    assert reviews[1]["reviewer"] == "Bob K"
    assert reviews[1]["rating"] == "5"


def test_carousel_dropped_when_list_present():
    """A page with both a Layout A carousel and a Layout B list keeps only the
    canonical list, so the duplicated recent reviews aren't double-counted."""
    combined = TA_MD + "\n" + TA_MD_LAYOUT_B
    reviews, _ = ta.extract_reviews(combined)
    # Only the two Layout B reviews survive; the Layout A carousel is dropped.
    assert [r["reviewer"] for r in reviews] == ["Jane D", "Bob K"]


def test_extract_reviews_parses_meta_and_reviews():
    reviews, meta = ta.extract_reviews(TA_MD)
    assert meta == {"overall_rating": 4.9, "total_reviews": 171}
    assert len(reviews) == 2

    first = reviews[0]
    assert first["reviewer"] == "Jane D"
    assert first["date"] == "Jun 2026"
    assert first["rating"] == "5"
    assert first["title"] == "(no title)"
    # Body paragraphs joined; the "Read more" terminator is excluded.
    assert "guides were superb" in first["text"]
    assert "food was incredible" in first["text"]
    assert "Read more" not in first["text"]
    assert first["raw_text"]  # fallback always retained

    assert reviews[1]["reviewer"] == "Bob K"
    assert reviews[1]["rating"] == "4"


def test_review_key_is_stable_and_content_based():
    r = {"reviewer": "Jane D", "date": "Jun 2026", "title": "(no title)", "text": "Lovely."}
    assert ta.review_key(r) == ta.review_key(dict(r))
    changed = dict(r, text="Different review body.")
    assert ta.review_key(changed) != ta.review_key(r)


def test_page_url_inserts_offset_segment():
    base = "https://www.tripadvisor.com/Hotel_Review-g1-d1-Reviews-X.html"
    assert ta._page_url(base, 0) == base
    assert ta._page_url(base, 10) == (
        "https://www.tripadvisor.com/Hotel_Review-g1-d1-Reviews-or10-X.html"
    )


def _render_store(reviews, meta):
    header = ta.render_header("Tanda Tula", "https://x", meta, len(reviews), "2026-06-26")
    blocks = "\n\n---\n\n".join(ta.render_review(r) for r in reviews)
    return header + "\n\n---\n\n" + blocks + "\n"


def test_roundtrip_through_reputation_parser():
    """The rendered store must parse cleanly back through the consumer."""
    reviews, meta = ta.extract_reviews(TA_MD)
    store = _render_store(reviews, meta)
    block = reputation.parse_tripadvisor(store)
    assert block["overall_rating"] == 4.9
    assert block["total_reviews"] == 171
    assert block["quoted_sample"] == 2
    assert block["warnings"] == []


def test_split_existing_recovers_blocks_and_keys(tmp_path):
    reviews, meta = ta.extract_reviews(TA_MD)
    store = tmp_path / "x-tripadvisor.md"
    store.write_text(_render_store(reviews, meta), encoding="utf-8")

    blocks, keys = ta.split_existing(store)
    assert len(blocks) == 2
    assert keys == {ta.review_key(r) for r in reviews}


def test_dedup_appends_only_new(tmp_path):
    reviews, meta = ta.extract_reviews(TA_MD)
    store = tmp_path / "x-tripadvisor.md"
    store.write_text(_render_store(reviews[:1], meta), encoding="utf-8")  # only Jane

    _, existing_keys = ta.split_existing(store)
    # Re-scrape Jane (dup) + Bob (new): only Bob is fresh.
    fresh = [r for r in reviews if ta.review_key(r) not in existing_keys]
    assert [r["reviewer"] for r in fresh] == ["Bob K"]
