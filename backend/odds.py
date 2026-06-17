"""The Odds API client + the betting math (de-vig, EV, Kelly).

Everything here is optional: with no ``ODDS_API_KEY`` the app runs fully in
"analysis only" mode (see ``has_key``).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from .cache import cache

ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def has_key(api_key: Optional[str] = None) -> bool:
    return bool(api_key or os.environ.get("ODDS_API_KEY"))


def _key(api_key: Optional[str] = None) -> str:
    return api_key or os.environ.get("ODDS_API_KEY", "")


def player_props_enabled() -> bool:
    return os.environ.get("ODDS_PLAYER_PROPS", "0") == "1"


def norm(name: str) -> str:
    """Normalize a player/team name for fuzzy matching across providers."""
    return "".join(c for c in name.lower() if c.isalnum())


# --------------------------------------------------------------------------- fetches

async def get_game_markets(c: httpx.AsyncClient, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """All of today's MLB events with moneyline (h2h) and totals odds."""
    if not has_key(api_key):
        return []

    async def fetch() -> List[Dict[str, Any]]:
        r = await c.get(
            f"{ODDS_BASE}/sports/{SPORT_KEY}/odds",
            params={
                "apiKey": _key(api_key),
                "regions": "us",
                "markets": "h2h,totals",
                "oddsFormat": "american",
            },
        )
        r.raise_for_status()
        return r.json()

    cache_key = "odds:game_markets" if not api_key else f"odds:game_markets:{api_key[-6:]}"
    return await cache.get_or_set(cache_key, 300, fetch)


async def get_pitcher_props(c: httpx.AsyncClient, event_id: str, market_key: str,
                             api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """``{normalized_pitcher_name: {"line": float, "over": int, "under": int}}`` for ``market_key``.

    ``market_key`` is an Odds API player-prop market, e.g. ``"pitcher_strikeouts"``
    or ``"pitcher_walks"``.
    """
    if not has_key(api_key) or not player_props_enabled():
        return {}

    async def fetch() -> Dict[str, Dict[str, Any]]:
        r = await c.get(
            f"{ODDS_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds",
            params={
                "apiKey": _key(api_key),
                "regions": "us",
                "markets": market_key,
                "oddsFormat": "american",
            },
        )
        r.raise_for_status()
        data = r.json()

        out: Dict[str, Dict[str, Any]] = {}
        for bm in data.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") != market_key:
                    continue
                for outcome in market.get("outcomes", []):
                    name = norm(outcome.get("description", ""))
                    side = outcome.get("name", "").lower()  # "over" / "under"
                    if side not in ("over", "under"):
                        continue
                    entry = out.setdefault(name, {"line": outcome.get("point")})
                    entry["line"] = outcome.get("point", entry.get("line"))
                    entry[side] = outcome.get("price")
            if out:
                # First bookmaker with a usable market wins — keep it simple.
                break
        return {k: v for k, v in out.items() if "over" in v and "under" in v and v.get("line") is not None}

    cache_key = f"odds:props:{market_key}:{event_id}" if not api_key else f"odds:props:{market_key}:{event_id}:{api_key[-6:]}"
    return await cache.get_or_set(cache_key, 300, fetch)


async def get_pitcher_strikeout_props(c: httpx.AsyncClient, event_id: str,
                                       api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    return await get_pitcher_props(c, event_id, "pitcher_strikeouts", api_key)


async def get_pitcher_walks_props(c: httpx.AsyncClient, event_id: str,
                                   api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    return await get_pitcher_props(c, event_id, "pitcher_walks", api_key)


async def get_player_props(c: httpx.AsyncClient, event_id: str, market_key: str,
                            api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Batter (or any player) prop market keyed by player name. ``get_pitcher_props``
    is already position-agnostic — this is just the honest name for batter markets
    like ``batter_hits`` / ``batter_total_bases`` / ``batter_home_runs``."""
    return await get_pitcher_props(c, event_id, market_key, api_key)


def game_total(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``{"line": float, "over": int, "under": int}`` for the game total (O/U runs), or ``None``."""
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "totals":
                continue
            entry: Dict[str, Any] = {}
            for outcome in market.get("outcomes", []):
                side = outcome.get("name", "").lower()
                if side not in ("over", "under"):
                    continue
                entry["line"] = outcome.get("point", entry.get("line"))
                entry[side] = outcome.get("price")
            if "over" in entry and "under" in entry and entry.get("line") is not None:
                return entry
    return None


def _team_matches(api_name: str, mlb_name: str) -> bool:
    """Fuzzy match between Odds API team name and MLB Stats API team name.

    Uses suffix matching to handle city-prefix differences caused by team
    relocations (e.g. "Athletics" from MLB API vs "Oakland Athletics" from
    Odds API — "athletics" is a suffix of "oaklandathletics").
    """
    a, b = norm(api_name), norm(mlb_name)
    return a == b or a.endswith(b) or b.endswith(a)


def match_event(events: List[Dict[str, Any]], home: str, away: str) -> Optional[Dict[str, Any]]:
    for e in events:
        if (_team_matches(e.get("home_team", ""), home) and
                _team_matches(e.get("away_team", ""), away)):
            return e
    return None


def best_moneyline(event: Dict[str, Any], team_name: str) -> Optional[int]:
    """The best (highest) American moneyline price for ``team_name`` across books."""
    best: Optional[int] = None
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                if _team_matches(outcome.get("name", ""), team_name):
                    price = outcome.get("price")
                    if price is not None and (best is None or price > best):
                        best = price
    return best


# --------------------------------------------------------------------------- betting math

def american_to_decimal(price: float) -> float:
    if price > 0:
        return 1 + price / 100.0
    return 1 + 100.0 / abs(price)


def implied_prob(price: float) -> float:
    if price > 0:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def devig_two(price_a: float, price_b: float) -> tuple[float, float]:
    """Vig-removed ("fair") probabilities for a two-outcome market."""
    pa, pb = implied_prob(price_a), implied_prob(price_b)
    total = pa + pb
    if total <= 0:
        return 0.5, 0.5
    return pa / total, pb / total


def ev_pct(model_prob: float, price: float) -> float:
    """Expected value per 1 unit staked, as a percentage."""
    dec = american_to_decimal(price)
    return (model_prob * dec - 1.0) * 100.0


def kelly_pct(model_prob: float, price: float) -> float:
    """Full-Kelly stake as a percentage of bankroll (0 if no edge)."""
    dec = american_to_decimal(price)
    b = dec - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - model_prob
    f = (b * model_prob - q) / b
    return max(f, 0.0) * 100.0
