"""MMA/UFC card client — ESPN's free MMA API (no key).

ESPN provides the event card: fighters + win-loss records + status. The granular
rate stats the model needs live in the bundled dataset (``backend.mma_data``);
this module only supplies the schedule/matchups, keyed so each *fight* is an
analyzable unit (like a game in the other sports).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .cache import cache

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
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
        try:
            r = await c.get(SCOREBOARD, params={"dates": window})
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []
        fights: List[Dict[str, Any]] = []
        for event in data.get("events", []):
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
                    "weightClass": (comp.get("type") or {}).get("text") if isinstance(comp.get("type"), dict) else None,
                    "rounds": rounds,
                    "status": comp.get("status", {}).get("type", {}).get("shortDetail", ""),
                    "away": a, "home": b,
                })
        return fights

    return await cache.get_or_set(f"mma:schedule:{date}", 3600, fetch)
