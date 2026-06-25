"""Read the collect-authored review manifest from a dossier's front-matter.

Which review files belong to which property is decided once, at collection time,
and written as a YAML front-matter block at the top of each dossier:

    ---
    reviews:
      - <property>-tripadvisor.md
      - <property>-booking.jsonl
    ---
    # <Property name>
    ...

Evaluate only *reads* this. The one distinction it depends on is **missing versus
empty**, so that is what this module makes crisp and unit-tests lock:

  * **absent** — no front-matter, or front-matter without a ``reviews:`` key —
    returns ``None``. Evaluate then warns and skips the Reputation section; it
    never falls back to guessing the mapping from filenames.
  * **empty** — ``reviews:`` present but with no entries (``reviews: []`` or an
    empty block) — returns ``[]``, the honored "no reviews captured" state.
  * **populated** — returns the list of filenames (relative to ``reviews/``).

Parsing is stdlib-only and deliberately minimal: it reads just the ``reviews:``
list, not arbitrary YAML.
"""

from __future__ import annotations

import re

_FRONT_MATTER_RE = re.compile(r"\A﻿?\s*---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


def front_matter(dossier_md: str) -> "str | None":
    """The text inside the leading ``---`` … ``---`` block, or None if absent."""
    m = _FRONT_MATTER_RE.match(dossier_md)
    return m.group(1) if m else None


def read_manifest(dossier_md: str) -> "list[str] | None":
    """The dossier's ``reviews:`` list: None if absent, ``[]`` if empty, else names.

    See the module docstring for the missing-versus-empty contract.
    """
    fm = front_matter(dossier_md)
    if fm is None:
        return None

    lines = fm.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^reviews\s*:\s*(.*)$", line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            # Inline form: "reviews: []" or "reviews: [a, b]".
            inner = inline.strip()
            if inner.startswith("[") and inner.endswith("]"):
                inner = inner[1:-1].strip()
            if not inner:
                return []
            return [_clean(item) for item in inner.split(",") if _clean(item)]
        # Block form: collect subsequent "  - item" lines.
        items = []
        for follow in lines[i + 1:]:
            entry = re.match(r"^\s*-\s+(.*)$", follow)
            if entry:
                value = _clean(entry.group(1))
                if value:
                    items.append(value)
                continue
            if follow.strip() == "":
                continue
            # A non-list, non-blank line ends the reviews block.
            break
        return items
    return None


def _clean(value: str) -> str:
    """Strip whitespace and surrounding quotes from one manifest entry."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()
