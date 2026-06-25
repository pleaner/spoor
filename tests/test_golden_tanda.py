"""Golden tests for the Tanda Tula Safari Camp pricing script.

Prices were hand-computed from the rate card (frozen under tests/golden/raw/) and
pin the committed script's behaviour; they double as the acceptance gate for any
regenerated script.

Rate card (RACK, ZAR, 2026): Safari Suite pppn sharing (17+) R31,500 · single
R47,250 · child 6–16 sharing R15,750. Family Suite base (1–3 guests) R94,500 ·
additional adult R31,500 · additional child R15,750. Sustainability levy: 12+
R1,815 pppn, 6–11 R910 pppn. STO25 = 25% off. Min 2-night stay. Stay-3-pay-2 /
stay-4-pay-3 special.

Cases cover: single-supplement, child-band, family-suite-vs-multiroom optimisation,
levy itemisation (age-banded), a stay-pay special, and infeasible (min-age and
min-stay) cases.
"""

from __future__ import annotations


def test_couple_one_safari_suite_no_special(tanda):
    # 2 adults sharing, 3 nights, June. Accom 2×31500×3 = 189,000;
    # levy 2×1815×3 = 10,890; grand 199,890.
    r = tanda.price("2026-06-15", "2026-06-18", [40, 40])
    assert r["feasible"] is True
    assert r["rack_total"] == 189000.0
    assert r["levy_total"] == 10890.0
    assert r["rack_grand_total"] == 199890.0
    assert r["sto_grand_total"] == 152640.0
    assert r["rack_adr"] == 66630.0
    assert r["config"]["summary"] == "Safari Suite (2 guest(s))"


def test_single_supplement(tanda):
    # One adult, Safari Suite single R47,250/night, 2 nights → 94,500 accom;
    # levy 1×1815×2 = 3,630; grand 98,130.
    r = tanda.price("2026-06-15", "2026-06-17", [40])
    assert r["rack_total"] == 94500.0
    assert r["levy_total"] == 3630.0
    assert r["rack_grand_total"] == 98130.0
    assert r["sto_grand_total"] == 74505.0


def test_child_band_in_safari_suite(tanda):
    # 2 adults + one 10-year-old child sharing a Safari Suite: 2×31500 + 15750
    # = 78,750/night. 2 nights → 157,500 accom. This beats a Family Suite (94,500
    # base), so the search keeps them in one Safari Suite.
    # Levy: 2×1815 (adults) + 1×910 (6–11 child) = 4,540/night ×2 = 9,080.
    r = tanda.price("2026-06-15", "2026-06-17", [40, 40, 10])
    assert r["rack_total"] == 157500.0
    assert r["levy_total"] == 9080.0
    assert r["rack_grand_total"] == 166580.0
    assert r["sto_grand_total"] == 127205.0
    assert r["config"]["summary"] == "Safari Suite (3 guest(s))"


def test_family_suite_beats_multiroom_for_three_adults(tanda):
    # Three adults: a Safari Suite has no third-adult rate, so the alternative is
    # two sharing (R63,000) + a single supplement (R47,250) = R110,250/night. The
    # Family Suite base rate (1–3 guests) is R94,500/night — cheaper — so the search
    # picks the single Family Suite. 2 nights → 189,000 accom; levy 3×1815×2 = 10,890.
    r = tanda.price("2026-06-15", "2026-06-17", [40, 40, 40])
    assert r["feasible"] is True
    assert r["config"]["summary"] == "Family Suite (3 guest(s))"
    assert r["rack_total"] == 189000.0
    assert r["levy_total"] == 10890.0
    assert r["rack_grand_total"] == 199890.0
    assert r["sto_grand_total"] == 152640.0


def test_levy_is_age_banded_and_itemised(tanda):
    # 2 adults + children 6 and 10: two levy bands (12+ and 6–11).
    r = tanda.price("2026-06-15", "2026-06-17", [40, 40, 6, 10])
    bands = {l["band"]: l for l in r["levies"]}
    assert bands["12 years and older"]["people"] == 2
    assert bands["12 years and older"]["per_person_per_night"] == 1815.0
    assert bands["6–11 years"]["people"] == 2
    assert bands["6–11 years"]["per_person_per_night"] == 910.0
    # 2 nights: (2×1815 + 2×910) × 2 = 10,900.
    assert r["levy_total"] == 10900.0


def test_stay_longer_for_less_applied_in_window(tanda):
    # Couple, Safari Suite, 3 nights within 1 Nov–15 Dec 2026 → stay 3 pay 2.
    # Accom 2×31500×3 = 189,000 less one free night (63,000) = 126,000.
    # Levy 2×1815×3 = 10,890 (never discounted); grand 136,890.
    r = tanda.price("2026-11-15", "2026-11-18", [40, 40])
    assert r["rack_total"] == 126000.0
    assert r["levy_total"] == 10890.0
    assert r["rack_grand_total"] == 136890.0
    assert r["sto_grand_total"] == 105390.0
    applied = [s["name"] for s in r["specials_applied"]]
    assert "Stay Longer for Less (stay 3 pay 2)" in applied
    assert r["specials_applied"][0]["saving_rack"] == 63000.0


def test_honeymoon_and_aerial_are_never_auto_applied(tanda):
    r = tanda.price("2026-11-15", "2026-11-18", [40, 40])
    not_applied = [s["name"] for s in r["specials_available_not_applied"]]
    assert any("Honeymoon" in n for n in not_applied)
    assert any("Aerial" in n for n in not_applied)


def test_under_six_child_is_infeasible(tanda):
    r = tanda.price("2026-06-15", "2026-06-17", [40, 40, 4])
    assert r["feasible"] is False
    assert "under 6" in r["reason"]


def test_one_night_breaks_minimum_stay(tanda):
    r = tanda.price("2026-06-15", "2026-06-16", [40, 40])
    assert r["feasible"] is False
    assert "minimum stay" in r["reason"]
