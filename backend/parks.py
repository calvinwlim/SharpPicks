"""Ballpark run/HR park factors and field orientation.

Two environment signals for run-total (and, soon, home-run) bets:

- **Park factor** — how much a venue inflates or suppresses scoring relative to
  a league-average park (``1.00`` = neutral). Coors thins the air and plays
  huge; Oracle and Petco swallow fly balls. ``runFactor``/``hrFactor`` are
  multipliers on expected runs / home runs.
- **Center-field azimuth** — the compass bearing (degrees, 0 = due north) from
  home plate out toward center field. Combined with the live wind vector it
  tells whether the wind is blowing *out* (carries balls, more runs) or *in*
  (knocks them down). Wind only helps or hurts relative to which way the park
  faces, so a park with no recorded orientation gets no wind adjustment.

Both tables are **maintained seeds** that approximate public data (Statcast
park factors; published park orientations). They are intentionally modest and
clamped downstream in ``analysis``. Anything missing falls back to neutral, so
the model degrades gracefully. ``hrFactor`` is staged for the home-run prop and
currently informs only the total via ``runFactor``.

Azimuths are approximate — verify before leaning on the wind factor hard. Domed
parks carry ``cfAzimuth = None`` (no outdoor wind).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

NEUTRAL: Dict[str, Any] = {"runFactor": 1.0, "hrFactor": 1.0, "cfAzimuth": None}

# venue name -> (runFactor, hrFactor, cfAzimuth degrees or None)
_PARKS: Dict[str, tuple] = {
    "Coors Field": (1.15, 1.12, None),
    "Fenway Park": (1.06, 0.97, 47),
    "Great American Ball Park": (1.05, 1.16, 60),
    "Citizens Bank Park": (1.03, 1.08, 15),
    "Chase Field": (1.03, 1.04, None),         # retractable; treated as dome
    "Globe Life Field": (1.02, 1.03, None),    # retractable; treated as dome
    "Guaranteed Rate Field": (1.02, 1.06, 70),
    "Yankee Stadium": (1.02, 1.12, 78),
    "Truist Park": (1.01, 1.03, 65),
    "Wrigley Field": (1.01, 1.02, 36),         # the wind park — orientation matters most here
    "Rogers Centre": (1.01, 1.04, None),       # retractable; treated as dome
    "Daikin Park": (1.01, 1.04, None),         # retractable; treated as dome
    "Minute Maid Park": (1.01, 1.04, None),
    "Nationals Park": (1.01, 1.02, 30),
    "American Family Field": (1.00, 1.03, None),  # retractable; treated as dome
    "Oriole Park at Camden Yards": (1.00, 1.00, 60),
    "Target Field": (1.00, 1.00, 70),
    "Angel Stadium": (0.99, 1.01, 50),
    "Dodger Stadium": (0.98, 1.05, 25),
    "Citi Field": (0.98, 0.97, 30),
    "Progressive Field": (0.98, 0.99, None),
    "PNC Park": (0.98, 0.95, None),
    "Comerica Park": (0.98, 0.93, 60),
    "Busch Stadium": (0.97, 0.93, 60),
    "loanDepot park": (0.97, 0.95, None),      # retractable; treated as dome
    "Tropicana Field": (0.97, 0.96, None),     # dome
    "Kauffman Stadium": (1.01, 0.93, 60),
    "Petco Park": (0.95, 0.94, 60),
    "T-Mobile Park": (0.94, 0.93, 60),
    "Oakland Coliseum": (0.94, 0.92, 60),
    "Sutter Health Park": (1.02, 1.04, None),  # new A's park — limited data
    "Oracle Park": (0.92, 0.81, 92),           # cavernous right field
}


def get_park(venue: Optional[str]) -> Dict[str, Any]:
    """Park-factor + orientation dict for a venue, or neutral if unknown."""
    if not venue:
        return dict(NEUTRAL)
    row = _PARKS.get(venue)
    if not row:
        return dict(NEUTRAL)
    run, hr, az = row
    return {"venue": venue, "runFactor": run, "hrFactor": hr, "cfAzimuth": az}


def wind_out_mph(wind_dir_deg: float, wind_mph: float, cf_azimuth: float) -> float:
    """Component of the wind blowing *toward* center field, in mph.

    ``wind_dir_deg`` is the meteorological direction the wind comes *from*; the
    direction it blows *toward* is that plus 180°. Projecting that onto the
    home-plate -> center-field bearing gives a signed value: positive = blowing
    out (helps carry), negative = blowing in.
    """
    blowing_toward = wind_dir_deg + 180.0
    return wind_mph * math.cos(math.radians(blowing_toward - cf_azimuth))
