"""Phase 2 database tests: the one-time file→database import.

Driven against a tiny throwaway evaluated/raw tree so it asserts the importer's behaviour
(lodge-label provenance, prose-section parsing, completeness gate) without depending on
the real corpus.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.db

pytest.importorskip("sqlmodel")
pytest.importorskip("psycopg2")

from spoor.db import importer, store  # noqa: E402

EVAL_MD = """# Camp X — Evaluation

### ADR summary (RACK basis)
| something | numbers |

## Value
Strong value at the price.

## Completeness
### Completeness checklist
All fields present.

## Fit
Suits couples and honeymooners.

## Self-competitiveness
Modest seasonal spread.

## Reputation
Consistently high reviews.
"""


def _write_property(evaluated, raw, lodge, slug, name, *, with_pricing=True, with_reviews=True):
    edir = evaluated / lodge
    edir.mkdir(parents=True, exist_ok=True)
    (edir / f"{slug}-adr.json").write_text(
        json.dumps(
            {
                "property": name,
                "currency": "ZAR",
                "benchmark": {"year": 2026},
                "benchmark_applicable": True,
                "inclusion": "Fully inclusive",
                "fx": {"date": "2026-06-24"},
            }
        ),
        encoding="utf-8",
    )
    if with_pricing:
        (edir / f"{slug}-pricing.py").write_text("def price(start, end, ages):\n    return None\n", encoding="utf-8")
    md = EVAL_MD if with_reviews else EVAL_MD.split("## Reputation")[0].rstrip() + "\n"
    (edir / f"{slug}.md").write_text(md.replace("Camp X", name), encoding="utf-8")

    rdir = raw / lodge
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"{slug}.md").write_text(
        f"---\n---\n# {name}\n\n- **Lodge group:** {name} Group (group-slug)\n",
        encoding="utf-8",
    )


# ── parser units ──────────────────────────────────────────────────────────────

def test_parse_prose_sections_keys_and_subsections():
    prose = importer.parse_prose_sections(EVAL_MD)
    assert set(prose) == {"value", "completeness", "fit", "self_competitiveness", "reputation"}
    # An h3 subsection stays in its parent section's body, not promoted to its own key.
    assert "Completeness checklist" in prose["completeness"]
    assert prose["value"].startswith("Strong value")


def test_lodge_label_from_dossier(tmp_path):
    dossier = tmp_path / "d.md"
    dossier.write_text("- **Lodge group:** Tanda Tula (tanda-tula)\n", encoding="utf-8")
    assert importer.lodge_label_from_dossier(dossier) == "Tanda Tula"


# ── import behaviour ───────────────────────────────────────────────────────────

def test_import_loads_property_evaluation_and_lodge_label(session, tmp_path):
    evaluated, raw = tmp_path / "evaluated", tmp_path / "raw"
    _write_property(evaluated, raw, "lodge-a", "camp-x", "Camp X")

    n = importer.import_evaluations(session, evaluated, raw)
    assert n == 1

    corpus = store.read_corpus(session)
    assert len(corpus) == 1
    row = corpus[0]
    assert row["name"] == "Camp X"
    assert row["lodge_label"] == "Camp X Group"            # from the dossier line
    assert row["benchmark_year"] == 2026
    assert row["prose"]["fit"].startswith("Suits couples")  # parsed prose round-trips
    assert row["adr_payload"]["inclusion"] == "Fully inclusive"


def test_import_skips_properties_without_a_pricing_script(session, tmp_path):
    evaluated, raw = tmp_path / "evaluated", tmp_path / "raw"
    _write_property(evaluated, raw, "lodge-a", "complete", "Complete Camp")
    _write_property(evaluated, raw, "lodge-a", "no-pricing", "No Pricing", with_pricing=False)

    n = importer.import_evaluations(session, evaluated, raw)
    assert n == 1
    assert {r["property_slug"] for r in store.read_corpus(session)} == {"complete"}


def test_import_is_idempotent(session, tmp_path):
    evaluated, raw = tmp_path / "evaluated", tmp_path / "raw"
    _write_property(evaluated, raw, "lodge-a", "camp-x", "Camp X")
    importer.import_evaluations(session, evaluated, raw)
    importer.import_evaluations(session, evaluated, raw)  # re-run updates in place
    assert len(store.read_corpus(session)) == 1


def test_import_omits_reputation_when_absent(session, tmp_path):
    evaluated, raw = tmp_path / "evaluated", tmp_path / "raw"
    _write_property(evaluated, raw, "lodge-a", "no-rep", "No Rep Camp", with_reviews=False)
    importer.import_evaluations(session, evaluated, raw)
    row = store.read_corpus(session)[0]
    assert "reputation" not in row["prose"]
    assert "fit" in row["prose"]
