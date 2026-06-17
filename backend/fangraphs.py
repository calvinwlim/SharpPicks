"""FanGraphs pitcher discipline stats — no API key required.

Fetches the FanGraphs major-league pitching leaderboard (type=8, which includes
Statcast-derived SwStr%, O-Swing%, CStr%, K%, etc.) and returns a dict keyed by
MLBAM player ID for fast per-pitcher lookup.

Cached for 6 hours — the leaderboard updates daily so there's no point hitting
it more than once per server session.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import httpx

from .cache import cache

# FanGraphs type=8 includes plate discipline: SwStr%, O-Swing%, CStr%, K%, etc.
_FG_URL = (
    "https://www.fangraphs.com/api/leaders/major-league/data"
    "?pos=all&stats=pit&lg=all&qual=1&season={year}&season1={year}"
    "&startdate=&enddate=&month=0&hand=&team=0&pageitems=2000&pagenum=1"
    "&ind=0&rost=0&players=&type=8&postseason=&sortdir=default&sortstat=SwStr%25"
)

_FG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.fangraphs.com/leaders/major-league",
    "Accept": "application/json",
}

# Minimum batters faced before we trust the Statcast numbers
_MIN_TBF = 75


async def get_pitcher_discipline(season: int) -> Dict[int, Dict[str, float]]:
    """Return ``{mlbam_id: {swstr, o_swing, cstr, csw, k_pct}}`` for all pitchers
    with at least ``_MIN_TBF`` batters faced this season.

    All values are fractions (0–1). Returns an empty dict on any network error
    so callers degrade gracefully to the historical-only projection.
    """
    async def _fetch() -> Dict[int, Dict[str, float]]:
        url = _FG_URL.format(year=season)
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(url, headers=_FG_HEADERS)
                r.raise_for_status()
                payload = r.json()
        except Exception:
            return {}

        rows = payload.get("data", [])
        out: Dict[int, Dict[str, float]] = {}
        for row in rows:
            mlbam = row.get("xMLBAMID")
            if not mlbam:
                continue
            tbf = row.get("TBF") or 0
            if tbf < _MIN_TBF:
                continue

            def _f(key: str) -> Optional[float]:
                v = row.get(key)
                return float(v) if v is not None else None

            swstr = _f("SwStr%")
            o_swing = _f("O-Swing%")
            cstr = _f("CStr%")
            csw = _f("C+SwStr%")
            k_pct = _f("K%")

            if swstr is None:
                continue

            out[int(mlbam)] = {
                "swstr": swstr,       # swinging strike rate (primary K predictor)
                "o_swing": o_swing,   # chase rate
                "cstr": cstr,         # called strike rate
                "csw": csw,           # called strike + whiff (CSW rate)
                "k_pct": k_pct,       # actual K% (validation)
                "tbf": int(tbf),
            }
        return out

    return await cache.get_or_set(f"fangraphs:discipline:{season}", 21600, _fetch)
