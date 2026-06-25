"""Tests for the reputation parsing and aggregation core.

These exercise external behavior through the module interface — given review text
(inline fixtures shaped like the real ``data/raw/`` samples), assert the shape and
values of the produced block. No private helpers are asserted on.
"""

from __future__ import annotations

import json

import pytest

from spoor import reputation

# ── TripAdvisor: stated values are taken verbatim, sample is counted ─────────

# Two header shapes seen in the real data: a labelled bullet list (makanyi) and a
# compact "Overall: X/5 · N reviews" line (babylonstoren).
TA_BULLET = """# TripAdvisor Reviews — Example Lodge

- **Overall rating:** 4.9 / 5 bubbles
- **Total reviews on TripAdvisor:** 171 (as of 2026-06-24)

---

**Reviewer:** Sarah C
**Date:** November 2025
**Rating:** ⭐⭐⭐⭐⭐
Great stay.

---

**Reviewer:** Sue H
**Date:** December 2025
Lovely.
"""

TA_COMPACT = """# Example — TripAdvisor Reviews
# Overall: 4.5/5 · 971 reviews (as of 2026-06-24)

## Anne W | January 2026 | 5/5
"Excellent."

## Bob T | February 2026 | 4/5
"Good."

## Collection notes
Pages or0, or10 collected.
"""


def test_tripadvisor_reports_stated_overall_and_total():
    block = reputation.parse_tripadvisor(TA_BULLET)
    assert block["overall_rating"] == 4.9
    assert block["scale"] == 5
    assert block["total_reviews"] == 171


def test_tripadvisor_counts_quoted_sample_from_reviewer_lines():
    block = reputation.parse_tripadvisor(TA_BULLET)
    assert block["quoted_sample"] == 2


def test_tripadvisor_compact_header_and_heading_delimited_reviews():
    block = reputation.parse_tripadvisor(TA_COMPACT)
    assert block["overall_rating"] == 4.5
    assert block["total_reviews"] == 971
    # Two real reviews; the "## Collection notes" meta heading is not counted.
    assert block["quoted_sample"] == 2


TA_H3 = """# TripAdvisor reviews — Example

- **Overall rating:** 4.8 of 5 bubbles
- **Total reviews (as displayed):** 938

---

## Page 1 (or0) — captured verbatim

### Melanie W — May 2026 — 5/5
**A Wonderful Stay**

Outstanding from start to finish.

### Travelmonster — March 2026 — 5/5
**An Unforgettable Escape**

Pure luxury.
"""


def test_tripadvisor_counts_h3_reviews_under_section_headers():
    # Reviews delimited by "### Name — date — rating"; the "## Page 1" section
    # header must not be counted as a review.
    block = reputation.parse_tripadvisor(TA_H3)
    assert block["overall_rating"] == 4.8
    assert block["total_reviews"] == 938
    assert block["quoted_sample"] == 2


def test_tripadvisor_does_not_recompute_overall_from_sample():
    # Every quoted review is 5/5, but the stated overall (4.9) must be reported,
    # not an average of the top-sorted sample.
    block = reputation.parse_tripadvisor(TA_BULLET)
    assert block["overall_rating"] == 4.9


def test_tripadvisor_missing_fields_yield_none_and_warn_without_raising():
    block = reputation.parse_tripadvisor("# Just a title, no header values\n")
    assert block["overall_rating"] is None
    assert block["total_reviews"] is None
    assert block["quoted_sample"] == 0
    assert block["warnings"]  # at least one warning recorded


# ── Booking.com: computed values from the per-record JSONL ───────────────────
def _jsonl(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records)


BOOKING = _jsonl(
    {"reviewer": "Euan", "score": "10", "reviewed": "2 June 2026",
     "positive": "Lovely", "negative": "Pricey wine"},
    {"reviewer": "Laura", "score": "9.0", "reviewed": "24 May 2026",
     "positive": "Great", "negative": None},
    {"reviewer": "Mo", "score": "8", "reviewed": "20 March 2026"},
    {"reviewer": "Pat", "score": "6.0", "reviewed": "20 November 2025"},
)


def test_booking_average_record_count_and_scale():
    block = reputation.parse_booking(BOOKING)
    # (10 + 9 + 8 + 6) / 4 = 8.25 → 8.2 (banker's rounding on .25 in Python).
    assert block["average"] == round((10 + 9 + 8 + 6) / 4, 1)
    assert block["num_records"] == 4
    assert block["scale"] == 10


def test_booking_score_distribution():
    block = reputation.parse_booking(BOOKING)
    assert block["distribution"] == {"10": 1, "9": 1, "8": 1, "below_8": 1}


def test_booking_date_span_is_earliest_to_latest():
    block = reputation.parse_booking(BOOKING)
    assert block["span"]["first"] == "2025-11-20"
    assert block["span"]["last"] == "2026-06-02"


def test_booking_empty_file_yields_zero_records():
    block = reputation.parse_booking("")
    assert block["num_records"] == 0
    assert block["average"] is None
    assert block["distribution"] == {"10": 0, "9": 0, "8": 0, "below_8": 0}
    assert block["span"] == {"first": None, "last": None}


def test_booking_skips_malformed_lines_without_raising():
    text = BOOKING + "\nthis is not json\n" + _jsonl({"score": "10", "reviewed": "1 January 2026"})
    block = reputation.parse_booking(text)
    assert block["num_records"] == 5  # the four good + the one extra valid record
    assert any("not valid JSON" in w for w in block["warnings"])


# ── Aggregation: sources stay separate, keyed by source ──────────────────────
def test_build_block_keeps_sources_separate_no_composite(tmp_path):
    (tmp_path / "x-tripadvisor.md").write_text(TA_BULLET, encoding="utf-8")
    (tmp_path / "x-booking.jsonl").write_text(BOOKING, encoding="utf-8")
    block = reputation.build_reputation_block(
        tmp_path, ["x-tripadvisor.md", "x-booking.jsonl"])
    assert set(block) >= {"tripadvisor", "booking"}
    assert block["tripadvisor"]["scale"] == 5
    assert block["booking"]["scale"] == 10
    # No blended/composite key spanning the two scales.
    assert "overall" not in block and "composite" not in block
    assert block["tripadvisor"]["overall_rating"] == 4.9
    assert block["booking"]["num_records"] == 4


def test_build_block_empty_manifest_is_empty_block(tmp_path):
    assert reputation.build_reputation_block(tmp_path, []) == {}


def test_build_block_empty_booking_file_counts_zero(tmp_path):
    (tmp_path / "x-booking.jsonl").write_text("", encoding="utf-8")
    block = reputation.build_reputation_block(tmp_path, ["x-booking.jsonl"])
    assert "tripadvisor" not in block
    assert block["booking"]["num_records"] == 0


def test_source_inference_from_suffix():
    assert reputation.infer_source("a-tripadvisor.md") == "tripadvisor"
    assert reputation.infer_source("a-booking.jsonl") == "booking"
    assert reputation.infer_source("a.jsonl") == "booking"
    assert reputation.infer_source("notes.md") is None
