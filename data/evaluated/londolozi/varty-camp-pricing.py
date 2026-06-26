#!/usr/bin/env python3
# rate-card-sha256: 1224557389517a891cb0dc44ec06c70ab83607a0c17e3c774498899dbfbcbb7f
"""Pricing script for Londolozi Varty Camp (londolozi).

Self-contained and stdlib-only. Turns the property's raw rate card into:

    price(start, end, ages=[...]) -> dict

It brute-forces the cheapest valid way to seat a party across the camp's eight
Standard Chalets and two Superior Chalets, itemises the (3-night-capped) Guest
Conservation Contribution, and returns both RACK and STO (trade) figures with
the chosen configuration.

This mirrors the CANONICAL Londolozi pricing script (tree-camp-pricing.py) and
shares its group conventions; the differences are that Varty Camp has TWO room
types, a lower minimum guest age, and a published child policy.

Source rate cards (transcribed in data/raw/londolozi/varty-camp.md → "## Rate
card"; original PDFs: londolozi-rack-rates-2026.pdf and -2027.pdf, ZAR, per
person sharing per night, "VARTY CAMP" block).

LONDOLOZI GROUP CONVENTIONS (shared by all five camps):
  * TWO rate cards apply and a stay can straddle them. The 2026 card is valid for
    the booking period 16 Dec 2025 – 15 Dec 2026; the 2027 card 16 Dec 2026 –
    15 Dec 2027. Each NIGHT is priced under the card whose validity covers it
    (boundary: nights dated on/before 15 Dec 2026 → 2026 card, later → 2027 card),
    so a 15-Dec arrival is priced correctly across the boundary.
  * NO trade / STO rate is published anywhere on the Londolozi cards (RACK only),
    so STO == RACK for every figure. Surfaced as an assumption.
  * Single occupancy uses the card's published single rate, which is the per
    person sharing rate + the stated 25% single supplement.
  * The Guest Conservation Contribution is a flat per-person-per-night levy
    "capped at 3 nights" — it is charged for only the first min(nights, 3) nights,
    each at that night's card value, and is never discounted. The card does not
    age-band it or exempt children, so it is applied to all guests (assumption).
  * No minimum-stay requirement appears on the card (min 1 night).
  * Wetu shows no active specials (2026-06-23), so none are applied.
  * Excluded under the benchmark's fly-in assumption: park entrance fees ("to be
    advised", unquantified), the Londolozi/Skukuza road transfer (airstrip
    transfers ARE included), the conditional noise-impact levy, private vehicles
    and pilot rooms.

VARTY CAMP SPECIFICS / ASSUMPTIONS (surfaced for the completeness assessment):
  * TWO room types: eight Standard Chalets and two Superior Chalets. Both are
    priced per person sharing; the cheapest valid seating is searched over all
    ten chalets.
  * Children 6+ are welcome ("children always have a place at Varty Camp"); the
    minimum guest age is 6. The published child policy is encoded verbatim:
      - Two children (6–11) sharing an inter-leading chalet each pay 50% of the
        adult rate (= the card's "per child sharing" rate).
      - One child (6–11) alone in an inter-leading chalet pays the full adult
        rate (no single supplement).
      - One child 12+ pays adult rates.
  * CAPACITY: the dossier states no explicit per-chalet guest capacity — the
    chalets are couple/family oriented and "all can become inter-leading". We
    model a defensible max occupancy of 2 adults + up to 2 children (6–11) per
    chalet, with a hard cap of 2 adults per chalet (couple-oriented; no
    third-adult rate is published). DOCUMENTED as an assumption.
"""

from __future__ import annotations

import argparse
import datetime
import json

CURRENCY = "ZAR"
MIN_GUEST_AGE = 6         # children 6 and older welcome at Varty Camp
CHILD_MAX_AGE = 11        # 6–11 = child band; 12+ pays adult rates
LEVY_CAP_NIGHTS = 3       # Guest Conservation Contribution capped at 3 nights
LEVY_NAME = "Guest Conservation Contribution"

# Per-night rate cards. (pps = adult per person sharing; child = per child sharing
# (6–11), which equals 50% of pps; single = single occupancy incl. the 25% single
# supplement; levy = Guest Conservation Contribution pppn, Founders & Varty band.)
CARD_2026 = {
    "Standard Chalet": {"pps": 27950.0, "child": 13975.0, "single": 34937.50},
    "Superior Chalet": {"pps": 34200.0, "child": 17100.0, "single": 42750.0},
    "levy": 573.99,
}  # -2026.pdf
CARD_2027 = {
    "Standard Chalet": {"pps": 31500.0, "child": 15750.0, "single": 39375.0},
    "Superior Chalet": {"pps": 38650.0, "child": 19325.0, "single": 48312.50},
    "levy": 610.00,
}  # -2027.pdf
BOUNDARY = datetime.date(2026, 12, 15)  # nights on/before → 2026 card, after → 2027

# Eight Standard + two Superior chalets. max = total guests; max_adults caps the
# couple-oriented adult count (no third-adult rate published).
CHALETS = {
    "Standard Chalet": {"inventory": 8, "max": 4, "max_adults": 2},
    "Superior Chalet": {"inventory": 2, "max": 4, "max_adults": 2},
}


def card_for(d: datetime.date) -> dict:
    return CARD_2026 if d <= BOUNDARY else CARD_2027


def season_for(d: datetime.date) -> str:
    return "2026" if d <= BOUNDARY else "2027"


def _is_child(age) -> bool:
    """6–11 inclusive is a child for pricing; 12+ pays adult rates."""
    return MIN_GUEST_AGE <= age <= CHILD_MAX_AGE


def room_cost(card, chalet, ages):
    """Per-night (rack, sto, basis) for seating ``ages`` in ``chalet``, or None.

    STO == RACK (no trade rate published), so both elements are equal. Applies the
    verbatim Varty Camp child policy. ``ages`` are the guests in one chalet.
    """
    n = len(ages)
    if n == 0:
        return None
    if any(a < MIN_GUEST_AGE for a in ages):
        return None  # no guests under 6
    rate = card[chalet]
    adults = [a for a in ages if a > CHILD_MAX_AGE]   # 12+ pays adult rates
    children = [a for a in ages if _is_child(a)]      # 6–11

    spec = CHALETS[chalet]
    if n > spec["max"] or len(adults) > spec["max_adults"]:
        return None

    # Single occupancy: exactly one guest who is charged at the single rate.
    if n == 1:
        if adults:
            return (rate["single"], rate["single"], ["single occupancy (25% supplement)"])
        # One child (6–11) alone in an inter-leading chalet pays the full adult
        # rate (no single supplement) per the published policy.
        return (rate["pps"], rate["pps"], ["one child 6–11, full adult rate (no single supplement)"])

    # Shared chalet (2+ guests). Each adult/12+ pays pps.
    cost = 0.0
    basis = []
    if adults:
        cost += len(adults) * rate["pps"]
        basis.append(f"adult pps ×{len(adults)}")
    if children:
        # Two children (6–11) sharing pay 50% of the adult rate each (= card child
        # rate). A lone child sharing with adults likewise pays the child rate.
        cost += len(children) * rate["child"]
        basis.append(f"child 6–11 (50%) ×{len(children)}")
    return (cost, cost, basis)


def _best_for_night(card, ages):
    """Cheapest valid seating of ``ages`` for one night → (rack, sto, rooms)|None.

    Exhaustive search over partitions of the party into chalets and chalet-type
    assignments, respecting capacities, the child policy and inventory; minimised
    on RACK. Party sizes are tiny (≤8) so this is trivial.
    """
    import itertools

    ages = tuple(sorted(ages, reverse=True))
    inv0 = tuple(sorted({s: CHALETS[s]["inventory"] for s in CHALETS}.items()))
    memo = {}
    max_room = max(s["max"] for s in CHALETS.values())

    def search(remaining, inv_tuple):
        if not remaining:
            return (0.0, 0.0, [])
        key = (remaining, inv_tuple)
        if key in memo:
            return memo[key]
        inv = dict(inv_tuple)
        first, rest = remaining[0], remaining[1:]
        best = None
        max_extra = max_room - 1
        for k in range(0, min(max_extra, len(rest)) + 1):
            for combo in itertools.combinations(range(len(rest)), k):
                room = (first,) + tuple(rest[i] for i in combo)
                leftover = tuple(rest[i] for i in range(len(rest)) if i not in combo)
                for chalet in CHALETS:
                    if inv.get(chalet, 0) <= 0 or len(room) > CHALETS[chalet]["max"]:
                        continue
                    rc = room_cost(card, chalet, list(room))
                    if rc is None:
                        continue
                    rack, sto, basis = rc
                    inv2 = dict(inv)
                    inv2[chalet] -= 1
                    sub = search(leftover, tuple(sorted(inv2.items())))
                    if sub is None:
                        continue
                    cand = (rack + sub[0], sto + sub[1],
                            [{"suite": chalet, "ages": list(room), "basis": basis,
                              "rack": rack, "sto": sto}] + sub[2])
                    if best is None or cand[0] < best[0]:
                        best = cand
        memo[key] = best
        return best

    return search(ages, inv0)


_INCLUSION = ("meets-or-exceeds benchmark — fully inclusive: all meals, all drinks "
              "(excl. champagne, cellar wines & premium spirits), two daily game "
              "drives, nature walks, airstrip transfers, laundry & WiFi; conservation "
              "levy itemised separately")
_ASSUMPTIONS = [
    "Two rate cards apply; each night priced under its own card (2026 through 15 Dec "
    "2026, 2027 thereafter), so a 15-Dec stay straddles the boundary.",
    "No trade/STO rate published on the Londolozi cards; STO shown equal to RACK.",
    "Guest Conservation Contribution capped at 3 nights and applied to all guests "
    "(the card neither age-bands nor exempts children).",
    "Varty Camp has two room types (8 Standard Chalets, 2 Superior Chalets); the "
    "cheapest valid seating across all ten chalets is chosen.",
    "Children 6+ welcome (minimum guest age 6). Child policy encoded verbatim: two "
    "children 6–11 sharing each pay 50% of the adult rate; one child 6–11 alone in an "
    "inter-leading chalet pays the full adult rate (no single supplement); a child "
    "12+ pays adult rates.",
    "No explicit per-chalet capacity is published; modelled as max 2 adults plus up "
    "to 2 children (6–11) per chalet (couple/family oriented, no third-adult rate).",
    "Park entrance fees, road transfers, the noise-impact levy and private vehicles "
    "are excluded under the benchmark's fly-in assumption.",
]


def _infeasible(start, end, ages, reason):
    return {
        "feasible": False, "reason": reason, "currency": CURRENCY,
        "start": start, "end": end, "ages": list(ages),
        "rack_total": 0.0, "sto_total": 0.0, "levy_total": 0.0, "levies": [],
        "rack_grand_total": None, "sto_grand_total": None,
        "rack_adr": None, "sto_adr": None,
        "config": {"rooms": [], "summary": None}, "per_night": [],
        "specials_applied": [], "specials_available_not_applied": [],
        "assumptions": _ASSUMPTIONS, "inclusion": _INCLUSION,
    }


def _levy(dates, ages):
    """(levy_total, levies, per_night_levy_list) — capped at 3 nights, all guests,
    each capped night at its own card's value. Never discounted."""
    people = len(ages)
    capped = dates[:LEVY_CAP_NIGHTS]
    # Per-night levy charge for the whole party (0 once past the 3-night cap).
    per_night = [card_for(d)["levy"] * people if i < LEVY_CAP_NIGHTS else 0.0
                 for i, d in enumerate(dates)]
    # Itemise grouped by the distinct pppn value used within the capped window.
    grouped: dict = {}
    for d in capped:
        v = card_for(d)["levy"]
        grouped[v] = grouped.get(v, 0) + 1
    levies = []
    for v in sorted(grouped, reverse=True):
        nights = grouped[v]
        levies.append({"name": LEVY_NAME, "band": "per person per night (all ages)",
                       "per_person_per_night": v, "people": people,
                       "nights": nights, "total": v * people * nights})
    levy_total = sum(l["total"] for l in levies)
    return levy_total, levies, per_night


def price(start, end, ages=None):
    """Best (cheapest) price for a party and stay. See module docstring."""
    ages = list(ages or [])
    try:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(f"start/end must be ISO dates (YYYY-MM-DD): {exc}")
    nights = (e - s).days
    if nights <= 0:
        return _infeasible(start, end, ages, "end date must be after start date")
    if not ages:
        return _infeasible(start, end, ages, "no guests supplied")
    if any(a < MIN_GUEST_AGE for a in ages):
        return _infeasible(start, end, ages,
                           f"Varty Camp does not accept guests under {MIN_GUEST_AGE}")

    dates = [s + datetime.timedelta(days=i) for i in range(nights)]
    per_night = []
    rack_total = sto_total = 0.0
    rooms0 = None
    for d in dates:
        best = _best_for_night(card_for(d), ages)
        if best is None:
            return _infeasible(start, end, ages,
                               f"cannot seat this party in the available chalets ({d})")
        rack_total += best[0]
        sto_total += best[1]
        per_night.append({"date": d.isoformat(), "season": season_for(d),
                          "rack": best[0], "sto": best[1]})
        if rooms0 is None:
            rooms0 = best[2]

    levy_total, levies, per_night_levy = _levy(dates, ages)
    for pn, lv in zip(per_night, per_night_levy):
        pn["levy"] = lv

    rack_grand = rack_total + levy_total
    sto_grand = sto_total + levy_total

    return {
        "feasible": True, "reason": None, "currency": CURRENCY,
        "start": start, "end": end, "nights": nights, "ages": list(ages),
        "rack_total": round(rack_total, 2), "sto_total": round(sto_total, 2),
        "levy_total": round(levy_total, 2), "levies": levies,
        "rack_grand_total": round(rack_grand, 2), "sto_grand_total": round(sto_grand, 2),
        "rack_adr": round(rack_grand / nights, 2), "sto_adr": round(sto_grand / nights, 2),
        "config": {"rooms": rooms0,
                   "summary": "; ".join(f"{r['suite']} ({len(r['ages'])} guest(s))" for r in rooms0)},
        "per_night": per_night,
        "specials_applied": [],
        "specials_available_not_applied": [],
        "assumptions": _ASSUMPTIONS, "inclusion": _INCLUSION,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price a stay at Londolozi Varty Camp.")
    ap.add_argument("--start", required=True, help="Arrival date YYYY-MM-DD.")
    ap.add_argument("--end", required=True, help="Departure date YYYY-MM-DD.")
    ap.add_argument("--ages", required=True, help="Comma-separated guest ages, e.g. 40,40.")
    args = ap.parse_args(argv)
    ages = [int(a) for a in args.ages.split(",") if a.strip()]
    print(json.dumps(price(args.start, args.end, ages), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
