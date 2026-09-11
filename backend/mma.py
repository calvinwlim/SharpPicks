"""MMA/UFC card client — ESPN's free MMA API (no key).

ESPN provides the event card: fighters + win-loss records + status. The granular
rate stats the model needs live in the bundled dataset (``backend.mma_data``);
this module only supplies the schedule/matchups, keyed so each *fight* is an
analyzable unit (like a game in the other sports).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .cache import cache

log = logging.getLogger(__name__)

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
# ESPN sits behind Akamai, which 403s a browser User-Agent arriving without the rest
# of a browser's header set (a Chrome UA + bare Accept is an obvious bot fingerprint).
# A plain, honest UA is allowed straight through — do NOT "upgrade" this to a Mozilla
# string: doing so silently blocks every UFC card fetch.
UA = {"User-Agent": "sharp-slate/1.0 (+https://github.com/pengoof/SharpPicks)",
      "Accept": "application/json"}

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0, headers=UA, follow_redirects=True)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _last_name(name: str) -> str:
    return (name or "").split()[-1] if name else ""


def _competitor(c: Dict[str, Any]) -> Dict[str, Any]:
    ath = c.get("athlete", {})
    name = ath.get("displayName") or ath.get("fullName") or ""
    recs = c.get("records") or []
    return {"name": name, "abbr": _last_name(name),
            "record": (recs[0].get("summary") if recs else None)}


async def get_schedule(date: str) -> List[Dict[str, Any]]:
    """Every fight on the card(s) for ``date`` (YYYY-MM-DD), each an analyzable unit.

    ESPN's single-date MMA filter returns nothing, so we query a small window
    around the date and keep events whose card date matches.

    UFC events start late evening US time (10pm ET / 7pm PT), which is 2–3am UTC
    the following calendar day. ESPN stores timestamps in UTC, so an Aug 22 US
    event commonly appears with date "2026-08-23" in the API. We accept events
    whose UTC date is the requested date OR the next calendar day to handle this.
    """
    import datetime
    d = datetime.date.fromisoformat(date)
    next_day = (d + datetime.timedelta(days=1)).isoformat()
    window = f"{(d - datetime.timedelta(days=3)):%Y%m%d}-{(d + datetime.timedelta(days=3)):%Y%m%d}"

    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        raw_events: List[Dict[str, Any]] = []
        # Try date-range query first; if ESPN returns nothing (common for current/upcoming
        # events), fall back to the no-param call which always returns the live card.
        for params in ({"dates": window}, {}):
            try:
                r = await c.get(SCOREBOARD, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("ESPN MMA fetch failed (params=%s): %s", params, e)
                continue
            evs = data.get("events") or []
            if not evs:
                leagues = data.get("leagues") or []
                evs = leagues[0].get("events", []) if leagues else []
            raw_events = evs
            if raw_events:
                break
        fights: List[Dict[str, Any]] = []
        for event in raw_events:
            event_utc_date = (event.get("date") or "")[:10]
            if event_utc_date not in (date, next_day):
                continue
            card = event.get("name", "")
            headliner = card.split(":")[-1].lower() if ":" in card else ""
            for comp in event.get("competitions", []):
                cs = comp.get("competitors", [])
                if len(cs) != 2:
                    continue
                a, b = _competitor(cs[0]), _competitor(cs[1])
                # 5 rounds for the headliner (both names in the title), else 3.
                rounds = 5 if (a["abbr"].lower() in headliner and b["abbr"].lower() in headliner) else 3
                fights.append({
                    "gameId": str(comp.get("id")),
                    "date": date,  # normalize to requested date regardless of UTC offset
                    "event": card,
                    "weightClass": ((comp.get("type") or {}).get("text") or (comp.get("type") or {}).get("abbreviation")) if isinstance(comp.get("type"), dict) else None,
                    "rounds": rounds,
                    "status": comp.get("status", {}).get("type", {}).get("shortDetail", ""),
                    "away": a, "home": b,
                })
        return fights

    key = f"mma:schedule:{date}"
    fights = await cache.get_or_set(key, 3600, fetch)
    # Never cache an empty card: a transient ESPN failure would otherwise show
    # "no fights" for a full hour even once ESPN recovers.
    if not fights:
        cache.invalidate(key)
    return fights
