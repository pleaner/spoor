"""Synthetic evaluated/ + raw/ corpus builder for spike_db tests.

Mirrors ``tests/test_categories.py::_write_property`` but adds the fields the
importer reads (currency, inclusion, benchmark_applicable, fx date) and can omit
the pricing script — to exercise the importer's incomplete-evaluation skip — or
the dossier. Pricing always returns native ZAR so USD assertions stay exact under
a fixed FX of 1 ZAR = 0.05 USD.
"""

from __future__ import annotations

import json
from pathlib import Path

from spoor import benchmark


def write_property(eval_dir: Path, raw_dir: Path | None, lodge: str, slug: str,
                   name: str, *, adr_per_night: float = 100.0,
                   currency: str | None = "ZAR", inclusion: str | None = "Fully inclusive",
                   benchmark_applicable: bool = True, benchmark_year: int | None = 2026,
                   fx_date: str | None = "2026-06-24", max_party: int | None = None,
                   with_pricing: bool = True, with_dossier: bool = True) -> None:
    """Write a throwaway property under ``eval_dir/lodge`` (+ optional dossier)."""
    lodge_dir = eval_dir / lodge
    lodge_dir.mkdir(parents=True, exist_ok=True)

    adr: dict = {"property": name, "benchmark_applicable": benchmark_applicable}
    if currency is not None:
        adr["currency"] = currency
    if benchmark_year is not None:
        adr["benchmark"] = {"year": benchmark_year}
    if inclusion is not None:
        adr["inclusion"] = inclusion
    if fx_date is not None:
        adr["fx"] = {"date": fx_date}
    (lodge_dir / f"{slug}-adr.json").write_text(json.dumps(adr), encoding="utf-8")

    if with_pricing:
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

    if with_dossier and raw_dir is not None:
        rd = raw_dir / lodge
        rd.mkdir(parents=True, exist_ok=True)
        (rd / f"{slug}.md").write_text(f"# {name}\n", encoding="utf-8")


def build_corpus(tmp_path: Path, specs: list[dict]) -> tuple[Path, Path]:
    """Build an evaluated/ + raw/ tree from ``specs`` (kwargs for write_property)."""
    eval_dir = tmp_path / "evaluated"
    raw_dir = tmp_path / "raw"
    eval_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        write_property(eval_dir, raw_dir, **spec)
    return eval_dir, raw_dir
