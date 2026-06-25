"""Decide whether a property's pricing script must be regenerated.

Regeneration is tied to *actual rate changes*, not run-to-run churn: a script is
rebuilt only when it's missing or the raw rate-card section it was generated from
has changed since. Otherwise the existing, golden-tested script is reused and the
ADR is merely recomputed — keeping the pipeline reproducible and avoiding needless
(and expensive) code generation.

The signal is a sha256 of the raw dossier's ``## Rate card`` section, stamped into
the generated script's header as ``# rate-card-sha256: <hex>``. On each run we
re-hash the current section and compare. ``--force-rebuild`` overrides everything.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Marker the generator writes into each script header so freshness can read back
# exactly which rate-card text the script was built from.
HASH_MARKER = "rate-card-sha256"
_HASH_RE = re.compile(rf"^#\s*{re.escape(HASH_MARKER)}:\s*([0-9a-f]{{64}})\s*$", re.M)


def rate_card_section(dossier_md: str) -> str:
    """Return the raw ``## Rate card`` section text (heading to next ``## ``).

    The rate card is the only part of a dossier that drives pricing, so freshness
    keys on it alone — refreshing reviews or website prose won't trigger a rebuild.
    Returns "" if there is no rate-card section.
    """
    m = re.search(r"^##\s+Rate card\s*$", dossier_md, re.M | re.I)
    if not m:
        return ""
    start = m.start()
    nxt = re.search(r"^##\s+", dossier_md[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(dossier_md)
    return dossier_md[start:end].strip()


def rate_card_hash(dossier_md: str) -> str:
    """sha256 of the normalised rate-card section (stable across trivial whitespace)."""
    section = rate_card_section(dossier_md)
    normalised = "\n".join(line.rstrip() for line in section.splitlines()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def stored_hash(script_text: str) -> "str | None":
    """The rate-card hash a script was generated from, or None if unstamped."""
    m = _HASH_RE.search(script_text)
    return m.group(1) if m else None


def should_rebuild(
    script_path: "str | Path",
    dossier_path: "str | Path",
    *,
    force: bool = False,
) -> "tuple[bool, str]":
    """Return ``(rebuild, reason)`` for one property.

    Rebuild when forced, when the script is missing, when it carries no hash
    marker, or when the current rate-card hash differs from the stamped one.
    """
    script_path = Path(script_path)
    dossier_path = Path(dossier_path)
    if force:
        return True, "forced (--force-rebuild)"
    if not script_path.is_file():
        return True, "no existing pricing script"

    current = rate_card_hash(dossier_path.read_text(encoding="utf-8"))
    stamped = stored_hash(script_path.read_text(encoding="utf-8"))
    if stamped is None:
        return True, "existing script has no rate-card hash marker"
    if stamped != current:
        return True, "rate-card section changed since the script was generated"
    return False, "rate card unchanged — reusing tested script"
