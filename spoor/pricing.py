"""Load a generated per-property pricing script as a module.

Each property's rate card is turned into a self-contained, stdlib-only
``<property>-pricing.py`` exposing ``price(start, end, ages=[...])``. This loads
one by path via importlib so the benchmark can drive its ``price()`` without the
script having to live on ``sys.path`` or be importable by name.

The script is the single non-deterministic artifact in the pipeline (an LLM wrote
it); loading it here is the seam where deterministic Python takes over.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_pricing(path: "str | Path") -> ModuleType:
    """Import ``path`` as a module and return it.

    Raises FileNotFoundError if the script is missing, or AttributeError if it
    doesn't expose the required ``price`` callable — failing loudly beats a
    confusing error deep inside the benchmark.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"pricing script not found: {p}")

    # A unique module name avoids clobbering sys.modules when several properties
    # are loaded in one process (e.g. evaluate over a whole lodge).
    mod_name = f"_spoor_pricing_{p.stem.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load pricing script as a module: {p}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not callable(getattr(module, "price", None)):
        raise AttributeError(
            f"pricing script {p} must expose a callable price(start, end, ages=[...])"
        )
    return module
