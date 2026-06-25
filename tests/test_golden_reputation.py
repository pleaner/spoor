"""End-to-end golden for the reputation layer on a real property.

Locks the full reputation pipeline for Tanda Tula Safari Camp against frozen
fixtures under tests/golden/raw/: the collect-authored manifest in the dossier
front-matter → the per-source reputation block → the rendered summary table.

Tanda is the strong end-to-end case: a populated TripAdvisor file (stated 4.9/5
over 588, 40 quoted) plus a genuinely *empty* Booking.com file (record count zero)
— so the merged block exercises both the populated and the zero-record paths.
"""

from __future__ import annotations

from spoor import report, reputation
from spoor.manifest import read_manifest
from conftest import GOLDEN_RAW

LODGE = GOLDEN_RAW / "tanda-tula"
DOSSIER = LODGE / "safari-camp.md"

EXPECTED_BLOCK = {
    "tripadvisor": {
        "overall_rating": 4.9,
        "scale": 5,
        "total_reviews": 588,
        "quoted_sample": 40,
        "files": ["safari-camp-tripadvisor.md"],
        "warnings": [],
    },
    "booking": {
        "average": None,
        "scale": 10,
        "num_records": 0,
        "scored_records": 0,
        "distribution": {"10": 0, "9": 0, "8": 0, "below_8": 0},
        "span": {"first": None, "last": None},
        "files": ["safari-camp-booking.jsonl"],
        "warnings": [],
    },
}


def _block():
    manifest = read_manifest(DOSSIER.read_text(encoding="utf-8"))
    return reputation.build_reputation_block(LODGE / "reviews", manifest)


def test_golden_reputation_block_for_tanda_safari_camp():
    assert _block() == EXPECTED_BLOCK


def test_golden_reputation_table_render():
    md = report.render_reputation_table(_block())
    assert "| TripAdvisor | 4.9 / 5 | 588 total | 40 quoted (partial, top-sorted) |" in md
    assert "| Booking.com | — | 0 records | — |" in md
    assert ("**Booking.com score distribution (0 records):** "
            "10 → 0 · 9 → 0 · 8 → 0 · below 8 → 0") in md
