"""Pinned foreign-exchange conversion for the evaluate phase.

The Benchmark Safari reports each ADR in the property's **native** currency as
the canonical figure, plus a secondary USD column. To keep the whole pipeline
deterministic, USD is derived from a single rate pinned in a dated config file
(`config/fx.json`) — never a live network lookup (see the PRD's *Out of Scope*).

The config stores **USD per one unit of native currency**, so converting is a
plain multiply. The rate and its date travel into every ADR JSON so a reader
always knows exactly which conversion produced the USD numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

# Default location, relative to the project root (the directory holding config/).
DEFAULT_FX_PATH = Path("config/fx.json")


class FX:
    """A dated table of USD-per-native-unit rates, loaded from `fx.json`."""

    def __init__(self, date: str, rates: "dict[str, float]", base: str = "USD"):
        self.date = date
        self.base = base
        # Normalise currency codes to upper-case so lookups are forgiving.
        self.rates = {k.upper(): float(v) for k, v in rates.items()}

    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "FX":
        p = Path(path) if path is not None else DEFAULT_FX_PATH
        if not p.is_file():
            raise FileNotFoundError(
                f"FX config not found: {p}. Expected a pinned, dated fx.json "
                "(USD-per-native-unit rates)."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(date=data["date"], rates=data["rates"], base=data.get("base", "USD"))

    def to_usd(self, amount: "float | None", currency: str) -> "float | None":
        """Convert ``amount`` in ``currency`` to USD, or None if amount is None.

        Raises KeyError for an unknown currency so a missing rate is loud, not a
        silently-wrong number.
        """
        if amount is None:
            return None
        code = currency.upper()
        if code not in self.rates:
            raise KeyError(
                f"no pinned FX rate for currency {code!r} in fx.json (have: "
                f"{', '.join(sorted(self.rates))}). Add it as an explicit, dated edit."
            )
        return round(amount * self.rates[code], 2)

    def meta(self) -> "dict":
        """The provenance block embedded in ADR output."""
        return {"date": self.date, "base": self.base, "rates": dict(self.rates)}
