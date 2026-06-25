"""Golden tests for the Makanyi Private Game Lodge pricing script.

Prices were hand-computed from the rate card (frozen under tests/golden/raw/) and
pin the committed script's behaviour. They double as the acceptance gate for any
regenerated script: "regenerated" must still mean "returns these exact numbers".

Rate card (RACK pppn sharing, ZAR): Luxury R21,000 · Luxury Pool R23,000 · Marula
R23,000. Single supplement 50% (Marula 100%). Third person 12–18 in a Luxury Suite
@ 50% (R10,500). Conservation levy R620 pppn. STO = 25% off. Stay-4-Pay-3 special.

Cases cover: single-supplement, child-band, levy itemisation, a stay-pay special,
and an infeasible/min-age case (the family-suite-vs-multiroom optimisation case
lives in the Tanda Tula suite, where the family suite is price-competitive).
"""

from __future__ import annotations


def test_couple_one_luxury_suite_no_special(makanyi):
    # 2 adults sharing a Luxury Suite, 3 nights, June (no special window).
    # Accom 2×21000×3 = 126,000; levy 2×620×3 = 3,720; grand 129,720.
    r = makanyi.price("2025-06-15", "2025-06-18", [40, 40])
    assert r["feasible"] is True
    assert r["currency"] == "ZAR"
    assert r["nights"] == 3
    assert r["rack_total"] == 126000.0
    assert r["levy_total"] == 3720.0
    assert r["rack_grand_total"] == 129720.0
    assert r["sto_grand_total"] == 98220.0
    assert r["rack_adr"] == 43240.0
    assert r["config"]["summary"] == "Luxury Suite (2 guest(s))"


def test_single_supplement_picks_cheapest_single(makanyi):
    # One adult: cheapest single is a Luxury Suite @ 50% supplement = R31,500/night.
    # 2 nights → 63,000 accom; levy 1×620×2 = 1,240; grand 64,240.
    r = makanyi.price("2025-06-15", "2025-06-17", [40])
    assert r["rack_total"] == 63000.0
    assert r["levy_total"] == 1240.0
    assert r["rack_grand_total"] == 64240.0
    assert r["sto_grand_total"] == 48490.0
    assert r["config"]["rooms"][0]["suite"] == "Luxury Suite"


def test_third_person_child_band_beats_a_second_room(makanyi):
    # 2 adults + one 15-year-old: the 12–18 third-person rate (R10,500) in a single
    # Luxury Suite beats any two-room split. Per night 21000+21000+10500 = 52,500.
    # 2 nights → 105,000 accom; levy 3×620×2 = 3,720; grand 108,720.
    r = makanyi.price("2025-06-15", "2025-06-17", [40, 40, 15])
    assert r["rack_total"] == 105000.0
    assert r["levy_total"] == 3720.0
    assert r["rack_grand_total"] == 108720.0
    assert r["sto_grand_total"] == 82470.0
    assert r["config"]["summary"] == "Luxury Suite (3 guest(s))"


def test_levy_is_itemised_separately_from_rate(makanyi):
    r = makanyi.price("2025-06-15", "2025-06-18", [40, 40])
    assert len(r["levies"]) == 1
    levy = r["levies"][0]
    assert levy["name"] == "Timbavati Conservation Levy"
    assert levy["per_person_per_night"] == 620.0
    assert levy["people"] == 2 and levy["nights"] == 3
    assert levy["total"] == 3720.0


def test_stay4pay3_special_applied_in_window(makanyi):
    # Couple, Luxury Suite, 4 nights within 5 Jan–31 Mar 2026 → 1 free night.
    # Accom 2×21000×4 = 168,000 less one free night (42,000) = 126,000.
    # Levy 2×620×4 = 4,960 (never discounted); grand 130,960.
    r = makanyi.price("2026-01-15", "2026-01-19", [40, 40])
    assert r["rack_total"] == 126000.0
    assert r["levy_total"] == 4960.0
    assert r["rack_grand_total"] == 130960.0
    assert r["sto_grand_total"] == 99460.0
    applied = [s["name"] for s in r["specials_applied"]]
    assert "Stay 4 / Pay 3 (1 free night)" in applied
    assert r["specials_applied"][0]["saving_rack"] == 42000.0


def test_honeymoon_is_available_but_never_auto_applied(makanyi):
    # Soft qualifier (proof of marriage) → reported, never applied.
    r = makanyi.price("2026-01-15", "2026-01-19", [40, 40])
    not_applied = [s["name"] for s in r["specials_available_not_applied"]]
    assert any("Honeymoon" in n for n in not_applied)
    assert all("Honeymoon" not in s["name"] for s in r["specials_applied"])


def test_under_12_child_is_infeasible(makanyi):
    # No children under 12 unless exclusive use (not assumed).
    r = makanyi.price("2025-06-15", "2025-06-17", [40, 40, 8])
    assert r["feasible"] is False
    assert "under 12" in r["reason"]
    assert r["rack_grand_total"] is None


def test_three_adults_take_the_marula_suite(makanyi):
    # A Luxury Suite has no third-adult rate, so three adults can't share one. The
    # search finds the Marula Suite (3 × R23,000 = R69,000/night) cheaper than a
    # Luxury Suite plus a single-supplement second room (R42,000 + R31,500).
    r = makanyi.price("2025-06-15", "2025-06-17", [40, 40, 40])
    assert r["feasible"] is True
    assert r["config"]["summary"] == "Marula Suite (3 guest(s))"
    assert r["rack_total"] == 138000.0
