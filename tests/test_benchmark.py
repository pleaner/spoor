"""Tests for the ADR-table logic, isolated from any real rate card.

These drive ``compute_adr_table`` with a *fake* ``price_fn`` so we test the table
itself — personas × twelve months, ADR = total ÷ nights, native + USD columns,
FX applied from a fixed rate, and Benchmark-N/A handling — without needing a real
generated pricing script.
"""

from __future__ import annotations

import datetime

import pytest

from spoor import benchmark
from spoor.fx import FX

# A fixed FX table so USD assertions are exact: 1 ZAR = 0.05 USD.
FX_FIXED = FX(date="2026-01-01", rates={"USD": 1.0, "ZAR": 0.05})


def make_fake_price(grand_total=500.0, levy_total=100.0, currency="ZAR",
                    infeasible_months=()):
    """A deterministic price_fn: every stay costs the same, except months in
    ``infeasible_months`` which come back infeasible (e.g. a closed season)."""
    def price(start, end, ages):
        month = datetime.date.fromisoformat(start).month
        if month in infeasible_months:
            return {"feasible": False, "reason": "closed", "currency": currency}
        return {
            "feasible": True,
            "currency": currency,
            "rack_grand_total": grand_total,
            "sto_grand_total": grand_total * 0.75,
            "levy_total": levy_total,
            "config": {"summary": "1 suite, 2 sharing"},
            "specials_applied": [],
        }
    return price


def test_table_has_three_personas_and_twelve_months():
    table = benchmark.compute_adr_table(make_fake_price(), FX_FIXED, 2026)
    assert set(table["personas"]) == {"couple", "family", "group"}
    for persona in table["personas"].values():
        assert len(persona["months"]) == 12
        assert [c["month"] for c in persona["months"]] == list(range(1, 13))


def test_personas_use_the_fixed_spec_ages():
    table = benchmark.compute_adr_table(make_fake_price(), FX_FIXED, 2026)
    assert table["personas"]["couple"]["ages"] == [40, 40]
    assert table["personas"]["family"]["ages"] == [40, 40, 6, 10, 14]
    assert table["personas"]["group"]["ages"] == [40] * 8


def test_adr_is_grand_total_divided_by_nights():
    # grand_total 500 over 5 nights → ADR 100 native; USD = 100 * 0.05 = 5.0.
    table = benchmark.compute_adr_table(
        make_fake_price(grand_total=500.0), FX_FIXED, 2026)
    cell = table["personas"]["couple"]["months"][0]
    assert cell["rack_adr_native"] == 100.0
    assert cell["rack_adr_usd"] == 5.0
    # STO grand total 375 → ADR 75 → USD 3.75.
    assert cell["sto_adr_native"] == 75.0
    assert cell["sto_adr_usd"] == 3.75


def test_stay_is_five_nights_arriving_the_15th():
    start, end = benchmark.stay_dates(2026, 3)
    assert start == "2026-03-15"
    assert end == "2026-03-20"
    assert (datetime.date.fromisoformat(end)
            - datetime.date.fromisoformat(start)).days == benchmark.NIGHTS


def test_usd_column_uses_pinned_rate_and_records_provenance():
    table = benchmark.compute_adr_table(make_fake_price(), FX_FIXED, 2026)
    assert table["fx"]["date"] == "2026-01-01"
    assert table["fx"]["rates"]["ZAR"] == 0.05
    assert table["currency"] == "ZAR"


def test_infeasible_months_carry_no_numbers_but_keep_shape():
    table = benchmark.compute_adr_table(
        make_fake_price(infeasible_months={6, 7}), FX_FIXED, 2026)
    months = table["personas"]["couple"]["months"]
    june = months[5]
    assert june["feasible"] is False
    assert june["reason"] == "closed"
    assert june["rack_adr_native"] is None
    assert june["rack_adr_usd"] is None
    # Feasible-month count reflects the two closed months.
    assert table["personas"]["couple"]["feasible_months"] == 10


def test_non_safari_property_still_priced_but_flagged():
    table = benchmark.compute_adr_table(
        make_fake_price(), FX_FIXED, 2026, is_safari=False)
    assert table["benchmark_applicable"] is False
    assert benchmark.BENCHMARK_NA_NOTE in table["notes"]
    # Lodging ADR is still computed.
    assert table["personas"]["couple"]["months"][0]["rack_adr_native"] == 100.0


def test_safari_property_has_no_na_note():
    table = benchmark.compute_adr_table(make_fake_price(), FX_FIXED, 2026)
    assert table["benchmark_applicable"] is True
    assert table["notes"] == []


def test_unknown_currency_raises():
    with pytest.raises(KeyError):
        benchmark.compute_adr_table(
            make_fake_price(currency="EUR"), FX_FIXED, 2026)
