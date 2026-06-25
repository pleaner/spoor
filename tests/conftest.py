"""Shared paths and helpers for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from spoor.pricing import load_pricing

REPO = Path(__file__).resolve().parent.parent
EVALUATED = REPO / "data" / "evaluated"
GOLDEN_RAW = Path(__file__).resolve().parent / "golden" / "raw"


@pytest.fixture(scope="session")
def makanyi():
    """The committed Makanyi pricing module."""
    return load_pricing(EVALUATED / "makanyi-lodge" / "makanyi-private-game-lodge-pricing.py")


@pytest.fixture(scope="session")
def tanda():
    """The committed Tanda Tula Safari Camp pricing module."""
    return load_pricing(EVALUATED / "tanda-tula" / "safari-camp-pricing.py")
