"""Acceptance check: each committed pricing script is stamped with the hash of the
rate-card section it was generated from.

This keeps the regeneration policy honest — if a script's stamped hash didn't match
its rate card, ``should_rebuild`` would silently want to rebuild on every run. We
check against the *frozen* golden fixtures so the assertion is stable.
"""

from __future__ import annotations

from spoor import freshness
from conftest import EVALUATED, GOLDEN_RAW

CASES = [
    (EVALUATED / "makanyi-lodge" / "makanyi-private-game-lodge-pricing.py",
     GOLDEN_RAW / "makanyi-lodge" / "makanyi-private-game-lodge.md"),
    (EVALUATED / "tanda-tula" / "safari-camp-pricing.py",
     GOLDEN_RAW / "tanda-tula" / "safari-camp.md"),
]


def test_committed_scripts_match_their_rate_cards():
    for script, dossier in CASES:
        rebuild, reason = freshness.should_rebuild(script, dossier)
        assert rebuild is False, f"{script.name}: would rebuild ({reason})"
