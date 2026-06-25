"""Direct render tests mapping a known reputation block to its markdown table."""

from __future__ import annotations

from spoor import report

BLOCK = {
    "tripadvisor": {
        "overall_rating": 5.0, "scale": 5, "total_reviews": 235,
        "quoted_sample": 10, "files": ["x-tripadvisor.md"], "warnings": [],
    },
    "booking": {
        "average": 9.8, "scale": 10, "num_records": 49, "scored_records": 49,
        "distribution": {"10": 40, "9": 8, "8": 1, "below_8": 0},
        "span": {"first": "2023-08-22", "last": "2026-06-14"},
        "files": ["x-booking.jsonl"], "warnings": [],
    },
}


def test_table_reports_both_sources_on_their_own_scales():
    md = report.render_reputation_table(BLOCK)
    assert "| TripAdvisor | 5 / 5 | 235 total | 10 quoted (partial, top-sorted) |" in md
    assert "| Booking.com | 9.8 / 10 | 49 records | 2023-08-22 → 2026-06-14 |" in md
    # No blended composite line.
    assert "composite" not in md.lower()


def test_table_renders_booking_distribution():
    md = report.render_reputation_table(BLOCK)
    assert ("**Booking.com score distribution (49 records):** "
            "10 → 40 · 9 → 8 · 8 → 1 · below 8 → 0") in md


def test_empty_block_renders_no_reviews_captured():
    assert report.render_reputation_table({}) == "_No reviews captured._"


def test_empty_booking_file_renders_zero_records():
    block = {"booking": {"average": None, "scale": 10, "num_records": 0,
                         "distribution": {"10": 0, "9": 0, "8": 0, "below_8": 0},
                         "span": {"first": None, "last": None}, "files": [], "warnings": []}}
    md = report.render_reputation_table(block)
    assert "| Booking.com | — | 0 records | — |" in md


def test_scaffold_includes_reputation_section_only_when_block_present():
    base = {"property": "X", "benchmark": {"nights": 5}, "currency": "ZAR",
            "fx": {"rates": {"ZAR": 0.05}, "date": "2026-01-01"},
            "personas": {"couple": {"label": "Couple", "months": []}}}
    assert "## Reputation" not in report.render_scaffold(dict(base))
    with_rep = dict(base)
    with_rep["reputation"] = BLOCK
    out = report.render_scaffold(with_rep)
    assert "## Reputation" in out
    # Reputation is the last (fifth) section, after Self-competitiveness.
    assert out.index("## Self-competitiveness") < out.index("## Reputation")
