"""Home-plate umpire zone tendencies.

The home-plate umpire is one of the larger swing factors for strikeout, walk,
and total-runs bets: a tight zone means more called strikeouts, fewer walks,
and fewer runs; a wide zone is the opposite. The factors below are *relative to
an average umpire* (1.0 = neutral):

- ``kFactor``   > 1.0  -> more strikeouts than average (tight/accurate zone)
- ``bbFactor``  > 1.0  -> more walks than average (wide zone lets more pitches in)
- ``runFactor`` > 1.0  -> more runs than average

Note: kFactor and bbFactor move in opposite directions for wide/tight zones
because a tight zone kills walks (batters can't take borderline pitches) while
also generating more called strikeouts. Similarly, runFactor falls when the zone
is tight (fewer baserunners from walks) and rises when the zone is wide.

This table is a **maintained seed** approximated from publicly available umpire
tendency data (UmpScorecards classifications, multi-season averages). Refresh
periodically; any umpire not in the table falls back to neutral so the model
degrades gracefully. Keep entries modest — ``analysis._umpire_factor`` clamps
them, but the table should not pretend to more precision than the data supports.

Coverage: ~73 active MLB umpires as of the 2025 season.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _norm(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


# name -> (kFactor, bbFactor, runFactor)
# Grouped roughly tight -> average -> wide for readability.
# Values represent multi-season tendencies; individual seasons vary.
_TENDENCIES: Dict[str, tuple] = {
    # ----- tight / accurate zone (more Ks, fewer BBs, fewer runs) -----
    "Pat Hoberg":          (1.07, 0.91, 0.96),   # historically tightest zone in MLB
    "Will Little":         (1.05, 0.93, 0.97),
    "Shane Livensparger":  (1.04, 0.93, 0.97),
    "Tripp Gibson":        (1.04, 0.95, 0.98),
    "Mike Muchlinski":     (1.04, 0.94, 0.97),
    "Clint Vondrak":       (1.03, 0.95, 0.98),
    "Mark Wegner":         (1.03, 0.96, 0.99),
    "James Hoye":          (1.03, 0.96, 0.98),
    "Quinn Wolcott":       (1.02, 0.97, 0.99),
    "Vic Carapazza":       (1.02, 0.96, 0.99),
    "Todd Tichenor":       (1.02, 0.97, 0.99),
    "Jeff Nelson":         (1.02, 0.97, 0.99),
    "Ted Barrett":         (1.02, 0.97, 0.99),
    "Chris Segal":         (1.02, 0.96, 0.99),
    "Jim Reynolds":        (1.02, 0.97, 0.99),
    "Ryan Blakney":        (1.02, 0.96, 0.99),
    "Sam Holbrook":        (1.01, 0.98, 0.99),
    "Gary Cederstrom":     (1.01, 0.97, 0.99),
    "John Tumpane":        (1.01, 0.98, 0.99),
    "Scott Barry":         (1.01, 0.98, 0.99),
    "Stu Scheurwater":     (1.01, 0.99, 1.00),
    "Adam Hamari":         (1.01, 0.98, 0.99),
    "Alex Tosi":           (1.01, 0.98, 0.99),
    "Nick Mahrley":        (1.01, 0.99, 0.99),
    "Cory Blaser":         (1.01, 0.99, 1.00),

    # ----- near average / moderate zone -----
    "Jordan Baker":        (1.00, 1.00, 1.00),
    "Mark Carlson":        (1.00, 1.00, 1.00),
    "Tim Timmons":         (1.00, 1.00, 1.00),
    "Dan Iassogna":        (1.00, 1.00, 1.00),
    "Ed Hickox":           (1.00, 1.00, 1.00),
    "Larry Vanover":       (1.00, 1.00, 1.00),
    "Fieldin Culbreth":    (1.00, 1.00, 1.00),
    "Carlos Torres":       (1.00, 1.00, 1.00),
    "David Rackley":       (1.00, 1.00, 1.00),
    "Mark Ripperger":      (1.00, 1.00, 1.00),
    "Mark Lollo":          (1.00, 1.00, 1.00),
    "Aaron Libka":         (1.00, 1.00, 1.00),
    "John Libka":          (1.00, 1.00, 1.00),
    "Ben May":             (1.00, 1.00, 1.00),
    "Derek Thomas":        (1.00, 1.00, 1.00),
    "Marcus Pattillo":     (1.00, 1.00, 1.00),
    "Edwin Moscoso":       (1.00, 1.00, 1.00),
    "Rob Drake":           (1.00, 1.01, 1.00),
    "Mike DiMuro":         (1.00, 1.01, 1.00),
    "Mike Everitt":        (0.99, 1.01, 1.00),
    "Alfonso Marquez":     (0.99, 1.01, 1.00),
    "Ryan Additon":        (0.99, 1.01, 1.00),
    "Junior Valentine":    (0.99, 1.01, 1.00),
    "Manny Gonzalez":      (0.99, 1.01, 1.01),
    "Paul Emmel":          (0.99, 1.01, 1.01),
    "Bill Miller":         (0.99, 1.01, 1.01),
    "Jim Wolf":            (0.99, 1.01, 1.01),
    "Jerry Layne":         (0.99, 1.01, 1.01),
    "Greg Gibson":         (0.99, 1.02, 1.01),
    "Mike Winters":        (0.99, 1.02, 1.01),
    "Marty Foster":        (0.98, 1.02, 1.01),
    "Jerry Meals":         (0.99, 1.02, 1.01),
    "Laz Diaz":            (0.98, 1.03, 1.01),
    "Roberto Ortiz":       (0.98, 1.02, 1.01),
    "Charlie Ramos":       (0.99, 1.01, 1.00),
    "Malachi Moore":       (1.00, 1.00, 1.00),
    "Mike Estabrook":      (1.00, 1.00, 1.00),
    "Brennan Miller":      (1.00, 1.00, 1.00),
    "Alex MacKay":         (1.00, 1.00, 1.00),
    "Brian Knight":        (1.00, 1.00, 1.00),

    # ----- wide / loose zone (fewer Ks, more BBs, more runs) -----
    "Hunter Wendelstedt":  (0.98, 1.03, 1.01),
    "Doug Eddings":        (0.97, 1.05, 1.02),
    "Phil Cuzzi":          (0.97, 1.04, 1.02),
    "Kerwin Danley":       (0.97, 1.04, 1.02),
    "CB Bucknor":          (0.96, 1.06, 1.03),
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
