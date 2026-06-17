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


def parse_ip(value: Any) -> float:
    """Convert MLB's innings-pitched notation to true innings.

    The API reports ``"5.2"`` to mean 5 innings + 2 outs (= 5 + 2/3), not 5.2.
    Decimal IP feeds run-rate math (RA/9), where the difference is material.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    whole = int(f)
    outs = round((f - whole) * 10)  # the digit after the point is outs (0/1/2)
    return whole + outs / 3.0


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

async def get_pitcher_platoon_splits(person_id: int, season: int) -> Dict[str, Any]:
    """Season-to-date K rate vs LHB / RHB: ``{"vsLHB": {...}, "vsRHB": {...}}``."""

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            f"/people/{person_id}/stats",
            params={
                "stats": "statSplits",
                "group": "pitching",
                "season": season,
                "sportId": SPORT_ID,
                "sitCodes": "vl,vr",
            },
        )
        r.raise_for_status()
        data = r.json()

        out: Dict[str, Any] = {}
        code_map = {"vl": "vsLHB", "vr": "vsRHB"}
        for split in data.get("stats", [{}])[0].get("splits", []):
            code = split.get("split", {}).get("code")
            key = code_map.get(code)
            if not key:
                continue
            stat = split.get("stat", {})
            bf = int(stat.get("battersFaced", 0) or 0)
            k = int(stat.get("strikeOuts", 0) or 0)
            out[key] = {"k": k, "bf": bf, "kRate": (k / bf) if bf else 0.0}
        return out

    return await cache.get_or_set(f"platoon:{person_id}:{season}", 6 * 3600, fetch)


async def get_team_handedness(team_id: int, season: int) -> Dict[str, Any]:
    """Approximate batting-handedness mix of a team's active roster: ``{"lhbPct", "rhbPct"}``."""

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            f"/teams/{team_id}/roster",
            params={"rosterType": "active", "season": season, "hydrate": "person(batSide)"},
        )
        r.raise_for_status()
        data = r.json()

        lhb = rhb = total = 0.0
        for entry in data.get("roster", []):
            person = entry.get("person", {})
            side = (person.get("batSide") or {}).get("code")
            if side == "L":
                lhb += 1
            elif side == "R":
                rhb += 1
            elif side == "S":  # switch hitter — counts as half left, half right
                lhb += 0.5
                rhb += 0.5
            else:
                continue
            total += 1

        if total == 0:
            return {"lhbPct": 0.5, "rhbPct": 0.5}
        return {"lhbPct": lhb / total, "rhbPct": rhb / total}

    return await cache.get_or_set(f"handedness:{team_id}:{season}", 6 * 3600, fetch)


# --------------------------------------------------------------------------- boxscore (ump + lineups)

async def get_boxscore(game_pk: int) -> Dict[str, Any]:
    """Raw boxscore for a game (officials + posted lineups + season stats).

    Short TTL because lineups and officials are filled in over the hours before
    first pitch. Shared by ``get_umpire`` and ``get_lineup`` so we only hit the
    endpoint once per game.
    """

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(f"/game/{game_pk}/boxscore")
        r.raise_for_status()
        return r.json()

    return await cache.get_or_set(f"boxscore:{game_pk}", 120, fetch)


async def get_umpire(game_pk: int) -> Optional[str]:
    """Full name of the assigned home-plate umpire, or ``None`` if not yet posted."""
    box = await get_boxscore(game_pk)
    for off in box.get("officials", []):
        if off.get("officialType") == "Home Plate":
            return off.get("official", {}).get("fullName")
    return None


def _lineup_for_team(box: Dict[str, Any], team_id: int) -> Optional[Dict[str, Any]]:
    teams = box.get("teams", {})
    for side in ("home", "away"):
        sd = teams.get(side, {})
        if sd.get("team", {}).get("id") != team_id:
            continue
        order = sd.get("battingOrder", []) or []
        players = sd.get("players", {})
        if len(order) < 9:
            return {"confirmed": False, "kRate": None, "bbRate": None, "n": len(order)}

        k = bb = pa = 0
        for pid in order:
            p = players.get(f"ID{pid}", {})
            bat = p.get("seasonStats", {}).get("batting", {})
            k += int(bat.get("strikeOuts", 0) or 0)
            bb += int(bat.get("baseOnBalls", 0) or 0)
            pa += int(bat.get("plateAppearances", 0) or 0)
        if pa <= 0:
            return {"confirmed": False, "kRate": None, "bbRate": None, "n": len(order)}
        return {
            "confirmed": True,
            "kRate": k / pa,
            "bbRate": bb / pa,
            "n": len(order),
        }
    return None


async def get_lineup(game_pk: int, team_id: int) -> Optional[Dict[str, Any]]:
    """Confirmed-lineup K%/BB% for a team, or an unconfirmed marker / ``None``.

    Aggregates the posted batting order's season strikeout and walk rates
    (PA-weighted). ``confirmed`` is ``False`` until all nine spots are set.
    """
    box = await get_boxscore(game_pk)
    return _lineup_for_team(box, team_id)


async def get_lineup_batters(game_pk: int, team_id: int) -> Optional[List[Dict[str, Any]]]:
    """The posted batting order as ``[{"id", "name"}]``, or ``None`` if not set."""
    box = await get_boxscore(game_pk)
    teams = box.get("teams", {})
    for side in ("home", "away"):
        sd = teams.get(side, {})
        if sd.get("team", {}).get("id") != team_id:
            continue
        order = sd.get("battingOrder", []) or []
        if len(order) < 9:
            return None
        players = sd.get("players", {})
        out: List[Dict[str, Any]] = []
        for pid in order:
            person = players.get(f"ID{pid}", {}).get("person", {})
            out.append({"id": pid, "name": person.get("fullName", "")})
        return out
    return None


async def get_recent_lineup_batters(team_id: int, before_date: str, season: int) -> Optional[List[Dict[str, Any]]]:
    """A "projected" lineup: the batting order from this team's most recent
    *completed* game before ``before_date``, used as a stand-in when today's
    lineup hasn't posted yet. Returns ``None`` if no recent final game has a
    full 9-spot order on file.
    """
    from datetime import date as _date, timedelta

    end = _date.fromisoformat(before_date) - timedelta(days=1)
    start = end - timedelta(days=10)

    async def fetch_schedule() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(
            "/schedule",
            params={"sportId": SPORT_ID, "teamId": team_id, "startDate": start.isoformat(),
                    "endDate": end.isoformat()},
        )
        r.raise_for_status()
        data = r.json()
        pks: List[int] = []
        for d in data.get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") == "Final":
                    pks.append(g["gamePk"])
        return pks

    pks = await cache.get_or_set(f"recentgames:{team_id}:{before_date}", 3600, fetch_schedule)
    for game_pk in reversed(pks):  # most recent first
        batters = await get_lineup_batters(game_pk, team_id)
        if batters:
            return batters
    return None


async def get_team_hitting_log(team_id: int, season: int) -> List[Dict[str, Any]]:
    """A team's game-by-game hitting log (for point-in-time offensive rates).

    Used by the backtester to compute an opponent's K%/BB% *as of* a game date
    (summing only prior games) instead of the season-final figure.
    """

    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(
            f"/teams/{team_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": season, "sportId": SPORT_ID},
        )
        r.raise_for_status()
        data = r.json()

        rows: List[Dict[str, Any]] = []
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            rows.append(
                {
                    "date": split.get("date"),
                    "strikeOuts": int(stat.get("strikeOuts", 0) or 0),
                    "baseOnBalls": int(stat.get("baseOnBalls", 0) or 0),
                    "plateAppearances": int(stat.get("plateAppearances", 0) or 0),
                    "runs": int(stat.get("runs", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["date"] or "")
        return rows

    return await cache.get_or_set(f"teamhitlog:{team_id}:{season}", 12 * 3600, fetch)


async def get_team_recent_form(team_id: int, season: int, n: int = 15) -> Dict[str, Any]:
    """Last-N completed games: rolling run rates and W/L streak.

    Returns ``{"recentRPG": float|None, "recentRA": float|None, "streak": int, "n": int}``.
    Positive streak = wins (e.g. +4 = 4-game winning streak), negative = losses.
    """
    from datetime import date as _date, timedelta

    today = _date.today()
    start = today - timedelta(days=60)

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            "/schedule",
            params={
                "sportId": SPORT_ID,
                "teamId": team_id,
                "startDate": start.isoformat(),
                "endDate": today.isoformat(),
                "hydrate": "linescore",
            },
        )
        r.raise_for_status()
        data = r.json()

        games: List[Dict[str, Any]] = []
        for d in data.get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                teams = g.get("teams", {})
                for side in ("home", "away"):
                    t = teams.get(side, {})
                    if t.get("team", {}).get("id") != team_id:
                        continue
                    opp_side = "away" if side == "home" else "home"
                    rs = int(t.get("score") or 0)
                    ra = int((teams.get(opp_side) or {}).get("score") or 0)
                    won = bool(t.get("isWinner", False))
                    games.append({"won": won, "rs": rs, "ra": ra})

        recent = games[-n:]
        if not recent:
            return {"recentRPG": None, "recentRA": None, "streak": 0, "n": 0}

        recent_rpg = sum(g["rs"] for g in recent) / len(recent)
        recent_ra = sum(g["ra"] for g in recent) / len(recent)

        streak = 0
        last_won = recent[-1]["won"]
        for g in reversed(recent):
            if g["won"] == last_won:
                streak += 1
            else:
                break
        if not last_won:
            streak = -streak

        return {
            "recentRPG": round(recent_rpg, 2),
            "recentRA": round(recent_ra, 2),
            "streak": streak,
            "n": len(recent),
        }

    return await cache.get_or_set(f"recent_form:{team_id}:{season}", 1800, fetch)


async def get_batter_gamelog(person_id: int, season: int) -> List[Dict[str, Any]]:
    """A hitter's game log shaped for ``analysis.analyze_batter_prop``."""

    async def fetch() -> List[Dict[str, Any]]:
        c = client()
        r = await c.get(
            f"/people/{person_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": season, "sportId": SPORT_ID},
        )
        r.raise_for_status()
        data = r.json()

        rows: List[Dict[str, Any]] = []
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            opp = split.get("opponent", {})
            rows.append(
                {
                    "season": season,
                    "date": split.get("date"),
                    "isHome": bool(split.get("isHome", False)),
                    "opponentId": opp.get("id"),
                    "opponentName": opp.get("name", ""),
                    "hits": int(stat.get("hits", 0) or 0),
                    "totalBases": int(stat.get("totalBases", 0) or 0),
                    "homeRuns": int(stat.get("homeRuns", 0) or 0),
                    "atBats": int(stat.get("atBats", 0) or 0),
                    "plateAppearances": int(stat.get("plateAppearances", 0) or 0),
                    "strikeOuts": int(stat.get("strikeOuts", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["date"] or "")
        return rows

    return await cache.get_or_set(f"batterlog:{person_id}:{season}", 3600, fetch)


# --------------------------------------------------------------------------- bullpen

async def get_bullpen(team_id: int, season: int) -> Dict[str, Any]:
    """Bullpen-only ERA for a team, derived from relief-role pitchers.

    A pitcher counts as a reliever when fewer than half of his appearances were
    starts. ERA = 9 * earned runs / innings pitched over that group.
    """

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            "/stats",
            params={
                "stats": "season",
                "group": "pitching",
                "season": season,
                "sportId": SPORT_ID,
                "teamId": team_id,
                "playerPool": "ALL",
                "limit": 200,
            },
        )
        r.raise_for_status()
        data = r.json()

        er = ip = 0.0
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            gp = int(stat.get("gamesPlayed", 0) or 0)
            gs = int(stat.get("gamesStarted", 0) or 0)
            if gp == 0 or gs / gp >= 0.5:
                continue  # starter (or no appearances) — skip
            er += float(stat.get("earnedRuns", 0) or 0)
            ip += parse_ip(stat.get("inningsPitched", 0))

        era = (9.0 * er / ip) if ip > 0 else None
        return {"era": era, "ip": round(ip, 1), "fatigued": False}

    return await cache.get_or_set(f"bullpen:{team_id}:{season}", 6 * 3600, fetch)


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
                    "inningsPitched": parse_ip(stat.get("inningsPitched", 0)),
                    "battersFaced": int(stat.get("battersFaced", 0) or 0),
                    "earnedRuns": int(stat.get("earnedRuns", 0) or 0),
                    "runs": int(stat.get("runs", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["date"] or "")
        return rows

    return await cache.get_or_set(f"gamelog:{person_id}:{season}", 3600, fetch)
