#!/usr/bin/env python3
# rate-card-sha256: 9d6e920db2d898416999ece8c301ec641aaa960ea77ccb5c5aa2d7e58e2eb3fe
"""Pricing script for Londolozi Pioneer Camp (londolozi).

Self-contained and stdlib-only. Turns the property's raw rate card into:

    price(start, end, ages=[...]) -> dict

It brute-forces the cheapest valid way to seat a party across Pioneer Camp's
three suites (one inter-leading pair), itemises the (3-night-capped) Guest
Conservation Contribution, and returns both RACK and STO (trade) figures with
the chosen configuration.

This mirrors the CANONICAL Londolozi pricing script
(data/evaluated/londolozi/tree-camp-pricing.py) — same two-card-per-night
engine, levy helper, infeasible shape and CLI — and adds Pioneer Camp's
published child policy.

Source rate cards (transcribed in data/raw/londolozi/pioneer-camp.md → "## Rate
card"; original PDFs: londolozi-rack-rates-2026.pdf and -2027.pdf, ZAR, per
person sharing per night, "PIONEER CAMP" block).

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

PIONEER CAMP SPECIFICS / ASSUMPTIONS (surfaced for the completeness assessment):
  * One room type, the "Pioneer Suite", inventory 3. The whole camp converts to a
    private homestead for up to 12 people (up to 6 ADULTS + 6 CHILDREN), i.e.
    2 adults + 2 children per suite (6+6 across three suites). A standard suite is
    therefore modelled as max 2 adults PLUS up to 2 children (a small single kids'
    bedroom + a second child in the lounge area), max 4 occupants.
  * Suites No. 2 and No. 3 INTER-LEAD; the published child policy gives special
    child-only rates that apply only in such an inter-leading suite. We model the
    camp as having ONE inter-leading suite slot (the No.2↔No.3 pair lets a
    children-only room sit beside the parents), so at most one child-only suite may
    use the inter-leading rates per night.
  * Child rules encoded verbatim from the card (the brute-force search picks the
    cheapest valid seating):
      - Adult rate applies to guests 12+ ("Children 12 years and older pay adult
        rates"), so a 12+ "child" is seated and priced exactly as an adult and
        counts against the 2-adults-per-suite cap.
      - Children 6–11 sharing with two adults: each pays the child rate (50%).
      - One child 6–11 sharing with one adult: the child pays the child rate (50%).
      - One child 6–11 alone in the inter-leading suite: pays the adult pps rate
        (no single supplement).
      - Two children 6–11 in the inter-leading suite: one adult rate + one child
        rate.
      - Three children 6–11 in the inter-leading suite: each pays the child rate.
  * MIN_GUEST_AGE = 6 (Wetu "Minimum Child Age: 6"); any guest under 6 is
    infeasible.
"""

from __future__ import annotations

import argparse
import datetime
import json

CURRENCY = "ZAR"
MIN_GUEST_AGE = 6          # Wetu minimum child age 6
CHILD_MAX_AGE = 11         # 6–11 = child rate band; 12+ pay adult rates
LEVY_CAP_NIGHTS = 3        # Guest Conservation Contribution capped at 3 nights
LEVY_NAME = "Guest Conservation Contribution"

# Per-night rate cards. (pps = adult per person sharing; child = per child sharing
# = 50% of pps; single = single occupancy incl. the 25% single supplement;
# levy = Guest Conservation Contribution pppn.)
CARD_2026 = {"pps": 48450.0, "child": 24225.0, "single": 60562.50, "levy": 957.50}   # -2026.pdf
CARD_2027 = {"pps": 54750.0, "child": 27375.0, "single": 68437.50, "levy": 1015.00}  # -2027.pdf
BOUNDARY = datetime.date(2026, 12, 15)  # nights on/before → 2026 card, after → 2027

# One room type. The camp holds up to 6 adults + 6 children across the three
# suites, i.e. up to 2 adults + 2 children per suite.
SUITES = {"Pioneer Suite": {"inventory": 3, "max_adults": 2, "max_children": 2}}
# Suites No.2 and No.3 inter-lead, enabling exactly one children-only suite at the
# inter-leading child rates per night.
INTERLEADING_SUITES = 1


def card_for(d: datetime.date) -> dict:
    return CARD_2026 if d <= BOUNDARY else CARD_2027


def season_for(d: datetime.date) -> str:
    return "2026" if d <= BOUNDARY else "2027"


def _is_adult(age) -> bool:
    return age >= CHILD_MAX_AGE + 1  # 12+ pay adult rates


def _is_young_child(age) -> bool:
    return MIN_GUEST_AGE <= age <= CHILD_MAX_AGE  # 6–11 child-rate band


def room_cost(card, suite, ages, interleading=False):
    """Per-night (rack, sto, basis) for seating ``ages`` in ``suite``, or None.

    STO == RACK (no trade rate published), so both elements are equal. ``ages``
    are the occupants of this one suite; ``interleading`` is True only when this
    suite uses the No.2↔No.3 inter-leading slot (which unlocks the child-only
    rates). Returns None for any invalid occupancy.
    """
    if suite != "Pioneer Suite":
        return None
    if any(a < MIN_GUEST_AGE for a in ages):
        return None
    if not ages:
        return None

    adults = [a for a in ages if _is_adult(a)]
    children = [a for a in ages if _is_young_child(a)]
    na, nc = len(adults), len(children)

    pps, child, single = card["pps"], card["child"], card["single"]

    # --- Adult-only occupancies -------------------------------------------------
    if nc == 0:
        if na == 1:
            return (single, single, ["single occupancy (25% supplement)"])
        if na == 2:
            return (2 * pps, 2 * pps, ["adult pps ×2"])
        return None  # max 2 adults per suite

    # --- Children present -------------------------------------------------------
    if na > SUITES[suite]["max_adults"]:
        return None
    if nc > SUITES[suite]["max_children"]:
        # The only place >2 children may sleep is the inter-leading child-only
        # suite (up to three children); handled below.
        if not (na == 0 and interleading and nc == 3):
            return None

    if na == 2:
        # "Children (6–11) sharing a suite with two adults each pay 50%."
        if nc <= SUITES[suite]["max_children"]:
            return (2 * pps + nc * child, 2 * pps + nc * child,
                    [f"adult pps ×2 + child rate ×{nc}"])
        return None

    if na == 1:
        # "One child (6–11) sharing with one adult pays 50% of the adult rate."
        # A second child (lounge) is treated under the same child-rate band; the
        # card only spells out the single child case, so additional 6–11 children
        # sharing with the lone adult also pay the child rate (assumption, and the
        # conservative reading — it is the lowest rate available to a child).
        if nc <= SUITES[suite]["max_children"]:
            return (pps + nc * child, pps + nc * child,
                    [f"adult pps ×1 + child rate ×{nc}"])
        return None

    # na == 0: children only. Allowed only in the inter-leading suite.
    if not interleading:
        return None
    if nc == 1:
        # "One child (6–11) alone in an inter-leading suite pays the adult pps."
        return (pps, pps, ["one child alone (adult pps, no single supplement)"])
    if nc == 2:
        # "Two children (6–11) sharing an inter-leading suite pay one adult rate
        #  and one child rate."
        return (pps + child, pps + child, ["two children (adult rate + child rate)"])
    if nc == 3:
        # "Three children (6–11) sharing an inter-leading suite each pay the child
        #  rate."
        return (3 * child, 3 * child, ["three children (child rate ×3)"])
    return None


def _best_for_night(card, ages):
    """Cheapest valid seating of ``ages`` for one night → (rack, sto, rooms)|None.

    Exhaustive search over partitions of the party into suites, respecting the
    per-suite adult/children caps, the single inter-leading child-only slot, the
    child rules and inventory; minimised on RACK. Party sizes are tiny (≤12) so
    this is trivial.
    """
    import itertools

    ages = tuple(sorted(ages, reverse=True))  # adults first
    suite = "Pioneer Suite"
    inventory = SUITES[suite]["inventory"]
    # Per-suite occupancy cap (used to bound the partition search): a standard
    # suite holds up to 2 adults + 2 children = 4; the inter-leading child-only
    # suite holds up to 3 children.
    max_room = max(SUITES[suite]["max_adults"] + SUITES[suite]["max_children"], 3)
    memo = {}

    def search(remaining, rooms_left, inter_left):
        if not remaining:
            return (0.0, 0.0, [])
        if rooms_left <= 0:
            return None
        key = (remaining, rooms_left, inter_left)
        if key in memo:
            return memo[key]
        first, rest = remaining[0], remaining[1:]
        best = None
        for k in range(0, min(max_room - 1, len(rest)) + 1):
            for combo in itertools.combinations(range(len(rest)), k):
                room = (first,) + tuple(rest[i] for i in combo)
                leftover = tuple(rest[i] for i in range(len(rest)) if i not in combo)
                # Try as a standard suite, and (if an inter-leading slot remains)
                # as the inter-leading suite — the latter only matters for
                # children-only rooms.
                options = [(False, inter_left)]
                if inter_left > 0:
                    options.append((True, inter_left - 1))
                for inter, inter_after in options:
                    rc = room_cost(card, suite, list(room), interleading=inter)
                    if rc is None:
                        continue
                    rack, sto, basis = rc
                    sub = search(leftover, rooms_left - 1, inter_after)
                    if sub is None:
                        continue
                    cand = (rack + sub[0], sto + sub[1],
                            [{"suite": suite, "ages": list(room), "basis": basis,
                              "rack": rack, "sto": sto,
                              "interleading": inter}] + sub[2])
                    if best is None or cand[0] < best[0]:
                        best = cand
        memo[key] = best
        return best

    return search(ages, inventory, INTERLEADING_SUITES)


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
    "Pioneer Suite max occupancy 2 adults + 2 children (kids' bedroom + a second "
    "child in the lounge); the whole camp holds up to 6 adults + 6 children (12).",
    "Suites No.2 and No.3 inter-lead, modelled as one inter-leading slot per night "
    "that unlocks the card's child-only rates (1 child = adult pps; 2 children = "
    "adult rate + child rate; 3 children = child rate ×3).",
    "Guests 12+ pay adult rates and are seated and capped as adults; children 6–11 "
    "pay the child rate (50% of adult pps).",
    "A lone adult sharing with two 6–11 children: each child pays the child rate "
    "(card spells out only the single-child case; lowest available child rate used).",
    "Minimum guest age 6 (Wetu); under-6 parties are infeasible.",
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
                           f"Pioneer Camp does not accept guests under {MIN_GUEST_AGE}")

    dates = [s + datetime.timedelta(days=i) for i in range(nights)]
    per_night = []
    rack_total = sto_total = 0.0
    rooms0 = None
    for d in dates:
        best = _best_for_night(card_for(d), ages)
        if best is None:
            return _infeasible(start, end, ages,
                               "cannot seat this party in the three Pioneer suites "
                               "(max 2 adults + 2 children per suite; 6 adults / 12 "
                               f"people camp-wide) ({d})")
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
    ap = argparse.ArgumentParser(description="Price a stay at Londolozi Pioneer Camp.")
    ap.add_argument("--start", required=True, help="Arrival date YYYY-MM-DD.")
    ap.add_argument("--end", required=True, help="Departure date YYYY-MM-DD.")
    ap.add_argument("--ages", required=True, help="Comma-separated guest ages, e.g. 40,40.")
    args = ap.parse_args(argv)
    ages = [int(a) for a in args.ages.split(",") if a.strip()]
    print(json.dumps(price(args.start, args.end, ages), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
