"""Tests for manifest reading — the missing-versus-empty distinction evaluate
depends on, plus the front-matter list forms collect may write."""

from __future__ import annotations

from spoor.manifest import read_manifest


def _dossier(front_matter: "str | None") -> str:
    body = "# Property Name\n\n- **Property slug:** x\n\n## Rate card\n\nR1000 pppn.\n"
    if front_matter is None:
        return body
    return f"---\n{front_matter}\n---\n{body}"


def test_absent_front_matter_returns_none():
    assert read_manifest(_dossier(None)) is None


def test_front_matter_without_reviews_key_returns_none():
    assert read_manifest(_dossier("title: Property Name\nslug: x")) is None


def test_empty_inline_list_returns_empty_list():
    assert read_manifest(_dossier("reviews: []")) == []


def test_empty_block_list_returns_empty_list():
    # "reviews:" present, no entries follow before the next key.
    assert read_manifest(_dossier("reviews:\nother: value")) == []


def test_populated_block_list_returns_filenames():
    fm = "reviews:\n  - x-tripadvisor.md\n  - x-booking.jsonl"
    assert read_manifest(_dossier(fm)) == ["x-tripadvisor.md", "x-booking.jsonl"]


def test_populated_inline_list_returns_filenames():
    fm = "reviews: [x-tripadvisor.md, x-booking.jsonl]"
    assert read_manifest(_dossier(fm)) == ["x-tripadvisor.md", "x-booking.jsonl"]


def test_quoted_entries_are_unquoted():
    fm = 'reviews:\n  - "x-tripadvisor.md"\n  - \'x-booking.jsonl\''
    assert read_manifest(_dossier(fm)) == ["x-tripadvisor.md", "x-booking.jsonl"]


def test_reviews_block_stops_at_next_key():
    fm = "reviews:\n  - x-tripadvisor.md\nlast_updated: 2026-06-24"
    assert read_manifest(_dossier(fm)) == ["x-tripadvisor.md"]
