"""MLB Stats API client (https://statsapi.mlb.com) — no key required.

Every public function returns plain dicts/lists already shaped for
``backend.analysis``, and is cached via ``backend.cache.cache`` so a busy
slate doesn't refetch the same team stats per game.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .cache import cache

BASE_URL = "https://statsapi.mlb.com/api/v1"
SPORT_ID = 1  # MLB

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# --------------------------------------------------------------------------- schedule

def _team_side(side: Dict[str, Any]) -> Dict[str, Any]:
    team = side.get("team", {})
    pp = side.get("probablePitcher")
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "abbr": team.get("abbreviation", ""),
        "probablePitcher": (
            {"id": pp["id"], "name": pp.get("fullName", pp.get("name", ""))}
            if pp
            else None
        ),
    }


def _parse_game(g: Dict[str, Any]) -> Dict[str, Any]:
    teams = g.get("teams", {})
    return {
        "gamePk": g["gamePk"],
        "gameDate": g.get("gameDate"),
        "dayNight": g.get("dayNight", "day"),
        "status": g.get("status", {}).get("detailedState", ""),
        "venue": g.get("venue", {}).get("name", ""),
        "home": _team_side(teams.get("home", {})),
        "away": _team_side(teams.get("away", {})),
    }


async def get_schedule(date: str) -> List[Dict[str, Any]]:
    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(
            "/schedule",
            params={"sportId": SPORT_ID, "date": date, "hydrate": "probablePitcher,team"},
        )
        r.raise_for_status()
        data = r.json()
        games: List[Dict[str, Any]] = []
        for d in data.get("dates", []):
            for g in d.get("games", []):
                games.append(_parse_game(g))
        return games

    return await cache.get_or_set(f"schedule:{date}", 60, fetch)


# --------------------------------------------------------------------------- team rates

async def get_team_rates(season: int) -> Dict[str, Any]:
    """Team-level K%/BB% (offense), runs/game, and 1..N ranks within the league."""

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            "/teams/stats",
            params={"stats": "season", "group": "hitting", "season": season, "sportId": SPORT_ID},
        )
        r.raise_for_status()
        data = r.json()

        rows: List[Dict[str, Any]] = []
        total_k = total_bb = total_pa = 0
        for split in data.get("stats", [{}])[0].get("splits", []):
            team = split.get("team", {})
            stat = split.get("stat", {})
            pa = int(stat.get("plateAppearances", 0) or 0) or 1
            k = int(stat.get("strikeOuts", 0) or 0)
            bb = int(stat.get("baseOnBalls", 0) or 0)
            runs = int(stat.get("runs", 0) or 0)
            games = int(stat.get("gamesPlayed", 0) or 0) or 1
            rows.append(
                {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "abbr": team.get("abbreviation", ""),
                    "kRate": k / pa,
                    "bbRate": bb / pa,
                    "runsPerGame": runs / games,
                    "pa": pa,
                }
            )
            total_k += k
            total_bb += bb
            total_pa += pa

        rows.sort(key=lambda x: x["kRate"], reverse=True)
        for i, row in enumerate(rows, start=1):
            row["kRank"] = i
        rows.sort(key=lambda x: x["bbRate"], reverse=True)
        for i, row in enumerate(rows, start=1):
            row["bbRank"] = i

        return {
            "season": season,
            "teams": {row["id"]: row for row in rows},
            "leagueAvgK": (total_k / total_pa) if total_pa else 0.225,
            "leagueAvgBB": (total_bb / total_pa) if total_pa else 0.085,
            "nTeams": len(rows),
        }

    return await cache.get_or_set(f"team_rates:{season}", 6 * 3600, fetch)


# --------------------------------------------------------------------------- run prevention

async def get_team_run_prevention(season: int) -> Dict[str, Any]:
    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            "/teams/stats",
            params={"stats": "season", "group": "pitching", "season": season, "sportId": SPORT_ID},
        )
        r.raise_for_status()
        data = r.json()

        teams: Dict[int, Dict[str, Any]] = {}
        for split in data.get("stats", [{}])[0].get("splits", []):
            team = split.get("team", {})
            stat = split.get("stat", {})
            games = int(stat.get("gamesPlayed", 0) or 0) or 1
            runs = int(stat.get("runs", 0) or 0)
            teams[team.get("id")] = {
                "runsAllowedPerGame": runs / games,
                "era": float(stat.get("era", 0) or 0),
            }
        return {"season": season, "teams": teams}

    return await cache.get_or_set(f"run_prevention:{season}", 6 * 3600, fetch)


# --------------------------------------------------------------------------- pitcher game logs

async def get_pitcher_gamelog(person_id: int, season: int) -> List[Dict[str, Any]]:
    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(
            f"/people/{person_id}/stats",
            params={"stats": "gameLog", "group": "pitching", "season": season, "sportId": SPORT_ID},
        )
        r.raise_for_status()
        data = r.json()

        rows: List[Dict[str, Any]] = []
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            opp = split.get("opponent", {})
            # Only count starts (skip relief appearances mixed into a season log).
            if not split.get("isStartingPitcher", split.get("gamesStarted", stat.get("gamesStarted", 0))):
                continue
            rows.append(
                {
                    "season": season,
                    "date": split.get("date"),
                    "isHome": bool(split.get("isHome", False)),
                    "opponentId": opp.get("id"),
                    "opponentName": opp.get("name", ""),
                    "strikeOuts": int(stat.get("strikeOuts", 0) or 0),
                    "baseOnBalls": int(stat.get("baseOnBalls", 0) or 0),
                    "inningsPitched": float(stat.get("inningsPitched", 0) or 0),
                    "battersFaced": int(stat.get("battersFaced", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["date"] or "")
        return rows

    return await cache.get_or_set(f"gamelog:{person_id}:{season}", 3600, fetch)
