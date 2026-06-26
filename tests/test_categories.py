"""Tests for the categorise phase's deterministic core.

Two seams, both isolated from any LLM and any real rate card:

  * ``benchmark.persona_adr_range`` — driven with a *fake* ``price_fn`` (the same
    pattern as ``test_benchmark.py``), so we test the USD-range summary across the
    twelve benchmark months without a real script.
  * ``spoor.categories.category_ranges`` — driven against a tiny tmp-dir fixture of
    throwaway ``<property>-pricing.py`` + ``<property>-adr.json`` files, so we test
    discovery + sorting + infeasible-party handling without a real rate card.
"""

from __future__ import annotations

import datetime
import json

import pytest

from spoor import benchmark, categories
from spoor.fx import FX

# Fixed FX so USD assertions are exact: 1 ZAR = 0.05 USD.
FX_FIXED = FX(date="2026-01-01", rates={"USD": 1.0, "ZAR": 0.05})


def make_fake_price(grand_total=500.0, currency="ZAR", infeasible_months=(),
                    max_party=None):
    """A deterministic price_fn. Months in ``infeasible_months`` come back closed;
    a party larger than ``max_party`` is infeasible (over capacity)."""
    def price(start, end, ages):
        month = datetime.date.fromisoformat(start).month
        if month in infeasible_months:
            return {"feasible": False, "reason": "closed", "currency": currency}
        if max_party is not None and len(ages) > max_party:
            return {"feasible": False, "reason": "over capacity", "currency": currency}
        return {
            "feasible": True,
            "currency": currency,
            "rack_grand_total": grand_total,
            "sto_grand_total": grand_total * 0.75,
            "levy_total": 0.0,
            "config": {"summary": "stub"},
            "specials_applied": [],
        }
    return price


# ── persona_adr_range ────────────────────────────────────────────────────────

def test_range_is_min_max_usd_across_feasible_months():
    # Flat 500 grand total over 5 nights → ADR 100 native → USD 5.0 every month.
    rng = benchmark.persona_adr_range(make_fake_price(500.0), FX_FIXED, 2026, [40, 40])
    assert rng["feasible_months"] == 12
    assert rng["low_usd"] == 5
    assert rng["high_usd"] == 5


def test_range_excludes_infeasible_months():
    rng = benchmark.persona_adr_range(
        make_fake_price(500.0, infeasible_months={6, 7}), FX_FIXED, 2026, [40, 40])
    assert rng["feasible_months"] == 10


def test_never_feasible_party_yields_null_range():
    # A party of 8 against a max of 2 is infeasible in every month.
    rng = benchmark.persona_adr_range(
        make_fake_price(500.0, max_party=2), FX_FIXED, 2026, [40] * 8)
    assert rng == {"feasible_months": 0, "low_usd": None, "high_usd": None}


# ── category_ranges (discovery + sorting + infeasibility) ────────────────────

def _write_property(eval_dir, lodge, slug, name, adr_per_night, max_party=None):
    """Write a throwaway <slug>-adr.json + <slug>-pricing.py under eval_dir/lodge."""
    lodge_dir = eval_dir / lodge
    lodge_dir.mkdir(parents=True, exist_ok=True)
    (lodge_dir / f"{slug}-adr.json").write_text(
        json.dumps({"property": name, "benchmark": {"year": 2026}}), encoding="utf-8")
    # grand_total = adr_per_night * NIGHTS so the resulting ADR is adr_per_night.
    grand_total = adr_per_night * benchmark.NIGHTS
    cap_guard = (
        f"    if len(ages) > {max_party}:\n"
        "        return {'feasible': False, 'reason': 'over capacity', 'currency': 'ZAR'}\n"
        if max_party is not None else ""
    )
    (lodge_dir / f"{slug}-pricing.py").write_text(
        "def price(start, end, ages):\n"
        f"{cap_guard}"
        "    return {'feasible': True, 'currency': 'ZAR',\n"
        f"            'rack_grand_total': {grand_total}, 'sto_grand_total': {grand_total * 0.75},\n"
        "            'levy_total': 0.0, 'config': {'summary': 'stub'}, 'specials_applied': []}\n",
        encoding="utf-8")


def test_category_ranges_sorted_by_adr_ascending(tmp_path):
    eval_dir = tmp_path / "evaluated"
    _write_property(eval_dir, "lodge-b", "pricey", "Pricey Camp", 200.0)
    _write_property(eval_dir, "lodge-a", "cheap", "Cheap Camp", 100.0)
    rows = categories.category_ranges("honeymoon-couple", eval_dir, FX_FIXED)
    assert [r["name"] for r in rows] == ["Cheap Camp", "Pricey Camp"]
    assert rows[0]["low_usd"] == 5   # 100 ZAR * 0.05
    assert rows[1]["low_usd"] == 10  # 200 ZAR * 0.05
    assert all(r["feasible_months"] == 12 for r in rows)


def test_infeasible_property_flagged_and_sorted_last(tmp_path):
    eval_dir = tmp_path / "evaluated"
    _write_property(eval_dir, "lodge-a", "small", "Small Camp", 100.0, max_party=2)
    _write_property(eval_dir, "lodge-a", "big", "Big Camp", 300.0)
    rows = categories.category_ranges("corporate-incentive-group", eval_dir, FX_FIXED)
    # Big Camp (feasible) sorts ahead of Small Camp (party of 8 never fits).
    assert [r["name"] for r in rows] == ["Big Camp", "Small Camp"]
    assert rows[-1]["name"] == "Small Camp"
    assert rows[-1]["feasible_months"] == 0
    assert rows[-1]["low_usd"] is None


def test_eval_md_path_points_at_evaluation_markdown(tmp_path):
    eval_dir = tmp_path / "evaluated"
    _write_property(eval_dir, "lodge-a", "camp", "Camp", 100.0)
    rows = categories.category_ranges("honeymoon-couple", eval_dir, FX_FIXED)
    assert rows[0]["eval_md"].endswith("lodge-a/camp.md")


def test_unknown_category_raises(tmp_path):
    with pytest.raises(KeyError):
        categories.category_ranges("nope", tmp_path, FX_FIXED)


def test_all_fourteen_categories_present():
    assert len(categories.CATEGORIES) == 14
    assert "honeymoon-couple" in categories.CATEGORIES
    assert "birding-specialist" in categories.CATEGORIES
