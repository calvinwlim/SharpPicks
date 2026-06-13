"""Home-plate umpire zone tendencies.

The home-plate umpire is one of the larger swing factors for strikeout, walk,
and total-runs bets: a tight zone means fewer called strikeouts, more walks,
and more runs; a wide zone is the opposite. The factors below are *relative to
an average umpire* (1.0 = neutral):

- ``kFactor``  > 1.0  -> more strikeouts than average
- ``bbFactor`` > 1.0  -> more walks than average
- ``runFactor`` > 1.0 -> more runs than average

This table is a **maintained seed**, not a live feed. The values approximate
publicly published umpire tendencies (e.g. UmpScorecards) and should be
refreshed periodically; any umpire not in the table falls back to neutral, so
the model degrades gracefully. Keep entries modest — ``analysis._umpire_factor``
clamps them, but the table should not pretend to more precision than the data
supports.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _norm(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


# name -> (kFactor, bbFactor, runFactor). Wide-zone umps cluster high-K/low-BB;
# tight-zone umps the reverse. Seed values; replace with current-season data.
_TENDENCIES: Dict[str, tuple] = {
    "Pat Hoberg": (1.05, 0.93, 0.97),
    "Will Little": (1.04, 0.94, 0.98),
    "Tripp Gibson": (1.03, 0.95, 0.98),
    "Mark Wegner": (1.03, 0.96, 0.99),
    "Quinn Wolcott": (1.02, 0.97, 0.99),
    "Doug Eddings": (0.97, 1.05, 1.02),
    "Angel Hernandez": (0.96, 1.07, 1.03),
    "Phil Cuzzi": (0.97, 1.04, 1.02),
    "Hunter Wendelstedt": (0.98, 1.03, 1.01),
    "CB Bucknor": (0.96, 1.06, 1.03),
}

_BY_NORM: Dict[str, tuple] = {_norm(name): factors for name, factors in _TENDENCIES.items()}


def lookup(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Tendency dict for an umpire, or ``None`` if unknown (-> neutral upstream)."""
    if not name:
        return None
    factors = _BY_NORM.get(_norm(name))
    if not factors:
        return {"name": name, "kFactor": None, "bbFactor": None, "runFactor": None}
    k, bb, run = factors
    return {"name": name, "kFactor": k, "bbFactor": bb, "runFactor": run}
