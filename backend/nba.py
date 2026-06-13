"""NBA data client — schedule (cdn.nba.com, no auth) + advanced team ratings
(stats.nba.com, browser headers required). No API key.

Mirrors ``backend.mlb``: every public function returns plain dicts already
shaped for ``backend.nba_analysis`` and is cached. stats.nba.com gates requests
behind browser-like headers and may rate-limit cloud IPs; calls degrade
gracefully (return empty / neutral) so the app never hard-fails.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .cache import cache

CDN_BASE = "https://cdn.nba.com/static/json"
STATS_BASE = "https://stats.nba.com/stats"

# stats.nba.com refuses requests without these.
STATS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20.0, headers=STATS_HEADERS)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def season_for_date(date_iso: str) -> str:
    """NBA season string ('2025-26') containing the given date (seasons span Oct->Jun)."""
    y, m = int(date_iso[:4]), int(date_iso[5:7])
    start = y if m >= 10 else y - 1
    return f"{start}-{(start + 1) % 100:02d}"


# --------------------------------------------------------------------------- schedule

def _us_to_iso(us_date: str) -> str:
    """'MM/DD/YYYY 00:00:00' -> 'YYYY-MM-DD'."""
    head = (us_date or "").split(" ")[0]
    parts = head.split("/")
    if len(parts) != 3:
        return ""
    mm, dd, yyyy = parts
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


def _team_side(side: Dict[str, Any]) -> Dict[str, Any]:
    city = side.get("teamCity", "")
    name = side.get("teamName", "")
    return {
        "id": side.get("teamId"),
        "name": f"{city} {name}".strip(),
        "abbr": side.get("teamTricode", ""),
    }


async def _full_schedule(season: str) -> List[Dict[str, Any]]:
    """All games for the season, slimmed and date-stamped (cached; the raw file is ~8MB)."""

    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(f"{CDN_BASE}/staticData/scheduleLeagueV2_1.json")
        r.raise_for_status()
        data = r.json()
        games: List[Dict[str, Any]] = []
        for gd in data.get("leagueSchedule", {}).get("gameDates", []):
            iso = _us_to_iso(gd.get("gameDate", ""))
            for g in gd.get("games", []):
                games.append({
                    "gameId": g.get("gameId"),
                    "date": iso,
                    "gameDate": g.get("gameDateTimeUTC"),
                    "status": g.get("gameStatusText", ""),
                    "statusCode": g.get("gameStatus"),  # 1 scheduled, 2 live, 3 final
                    "home": _team_side(g.get("homeTeam", {})),
                    "away": _team_side(g.get("awayTeam", {})),
                    "homeScore": g.get("homeTeam", {}).get("score"),
                    "awayScore": g.get("awayTeam", {}).get("score"),
                })
        return games

    return await cache.get_or_set(f"nba:schedule:{season}", 6 * 3600, fetch)


async def get_schedule(date: str) -> List[Dict[str, Any]]:
    season = season_for_date(date)
    games = await _full_schedule(season)
    return [g for g in games if g["date"] == date]


async def last_game_before(team_id: int, season: str, date: str) -> Optional[str]:
    """ISO date of a team's most recent game strictly before ``date`` (for rest/B2B)."""
    games = await _full_schedule(season)
    dates = [g["date"] for g in games
             if g["date"] and g["date"] < date
             and (g["home"]["id"] == team_id or g["away"]["id"] == team_id)]
    return max(dates) if dates else None


# --------------------------------------------------------------------------- team ratings

async def get_team_ratings(season: str, last_n: int = 0) -> Dict[str, Any]:
    """Advanced ratings keyed by team id: ORtg / DRtg / Pace, plus league averages.

    ``last_n`` = 0 -> full season; e.g. 10 -> last 10 games (recent form).
    """

    async def fetch() -> Dict[str, Any]:
        c = client()
        params = {
            "LeagueID": "00", "Season": season, "SeasonType": "Regular Season",
            "MeasureType": "Advanced", "PerMode": "PerGame", "PlusMinus": "N",
            "PaceAdjust": "N", "Rank": "N", "Outcome": "", "Location": "", "Month": "0",
            "SeasonSegment": "", "DateFrom": "", "DateTo": "", "OpponentTeamID": "0",
            "VsConference": "", "VsDivision": "", "GameSegment": "", "Period": "0",
            "LastNGames": str(last_n), "GameScope": "", "PlayerExperience": "",
            "PlayerPosition": "", "StarterBench": "", "TwoWay": "0", "TeamID": "0",
            "Conference": "", "Division": "",
        }
        r = await c.get(f"{STATS_BASE}/leaguedashteamstats", params=params)
        r.raise_for_status()
        rs = r.json()["resultSets"][0]
        hdr = rs["headers"]
        idx = {h: i for i, h in enumerate(hdr)}
        teams: Dict[int, Dict[str, Any]] = {}
        ortgs: List[float] = []
        paces: List[float] = []
        for row in rs["rowSet"]:
            tid = row[idx["TEAM_ID"]]
            ortg = float(row[idx["OFF_RATING"]])
            drtg = float(row[idx["DEF_RATING"]])
            pace = float(row[idx["PACE"]])
            teams[tid] = {
                "name": row[idx["TEAM_NAME"]],
                "ortg": ortg, "drtg": drtg, "pace": pace,
                "netRtg": round(ortg - drtg, 2),
            }
            ortgs.append(ortg)
            paces.append(pace)
        league_ortg = sum(ortgs) / len(ortgs) if ortgs else 114.0
        league_pace = sum(paces) / len(paces) if paces else 99.5
        return {"season": season, "lastN": last_n, "teams": teams,
                "leagueOrtg": round(league_ortg, 2), "leaguePace": round(league_pace, 2)}

    return await cache.get_or_set(f"nba:ratings:{season}:{last_n}", 6 * 3600, fetch)
