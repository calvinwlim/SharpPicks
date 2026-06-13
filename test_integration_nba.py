"""End-to-end test of the NBA surface with synthetic data (no network).

Monkeypatches the ``backend.nba`` data layer and exercises the real FastAPI app
+ NBA model through HTTP, verifying the ?sport=nba JSON contract the frontend
(app.js renderNbaAnalysis) consumes.
"""
import sys

from fastapi.testclient import TestClient

import backend.nba as nba
import backend.nba_analysis as nba_analysis
from backend.main import app

DATE = "2026-01-15"
HOME_ID, AWAY_ID = 1610612737, 1610612738

GAME = {
    "gameId": "0022500999",
    "date": DATE,
    "gameDate": f"{DATE}T23:30:00Z",
    "status": "Final",
    "statusCode": 3,
    "home": {"id": HOME_ID, "name": "Atlanta Hawks", "abbr": "ATL"},
    "away": {"id": AWAY_ID, "name": "Boston Celtics", "abbr": "BOS"},
    "homeScore": None, "awayScore": None,
}

# Home = strong (high ORtg, low DRtg); Away = weak. Home should be favored.
def _ratings(season, last_n=0):
    teams = {
        HOME_ID: {"name": "Atlanta Hawks", "ortg": 119.0, "drtg": 110.0, "pace": 101.0, "netRtg": 9.0},
        AWAY_ID: {"name": "Boston Celtics", "ortg": 110.0, "drtg": 116.0, "pace": 99.0, "netRtg": -6.0},
    }
    return {"season": season, "lastN": last_n, "teams": teams, "leagueOrtg": 114.0, "leaguePace": 100.0}


# synthetic players: one star per team, enough games logged
def _players(season):
    return {
        201: {"name": "Home Star", "teamId": HOME_ID, "gp": 40, "min": 35.0,
              "pts": 27.0, "reb": 5.0, "ast": 7.0, "fg3m": 2.5},
        202: {"name": "Away Star", "teamId": AWAY_ID, "gp": 40, "min": 34.0,
              "pts": 22.0, "reb": 9.0, "ast": 3.0, "fg3m": 1.0},
    }

def _plog(pid, season):
    base = {201: (27, 5, 7, 2), 202: (22, 9, 3, 1)}[pid]
    rows = []
    for i in range(14):
        rows.append({"date": f"2026-01-{i + 1:02d}", "opponent": "XXX", "isHome": bool(i % 2),
                     "min": 34.0, "pts": base[0] + (i % 5 - 2), "reb": base[1] + (i % 3 - 1),
                     "ast": base[2] + (i % 3 - 1), "fg3m": max(0, base[3] + (i % 3 - 1))})
    return rows

def _opp_stats(season):
    teams = {HOME_ID: {"pts": 112.0, "reb": 43.0, "ast": 25.0, "fg3m": 13.0},
             AWAY_ID: {"pts": 116.0, "reb": 45.0, "ast": 27.0, "fg3m": 14.5}}
    return {"season": season, "teams": teams,
            "league": {"pts": 114.0, "reb": 44.0, "ast": 26.0, "fg3m": 13.5}}


def patch_data():
    async def get_schedule(date): return [GAME] if date == DATE else []
    async def get_team_ratings(season, last_n=0, location=""): return _ratings(season, last_n)
    async def last_game_before(team_id, season, date): return "2026-01-13"  # 2 days' rest
    async def get_team_opp_stats(season): return _opp_stats(season)
    async def get_player_season_stats(season): return _players(season)
    async def get_player_gamelog(pid, season): return _plog(pid, season)
    async def full_schedule(season): return [GAME]
    async def close(): return None
    nba.get_schedule = get_schedule
    nba.get_team_ratings = get_team_ratings
    nba.last_game_before = last_game_before
    nba.get_team_opp_stats = get_team_opp_stats
    nba.get_player_season_stats = get_player_season_stats
    nba.get_player_gamelog = get_player_gamelog
    nba._full_schedule = full_schedule
    nba.close = close
    nba.client = lambda: None


FAIL = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def main():
    patch_data()
    client = TestClient(app)

    print("\n[nba slate]")
    s = client.get(f"/api/slate?date={DATE}&sport=nba").json()
    check(s["sport"] == "nba", "sport tagged nba")
    check(s["count"] == 1, "one game in nba slate")
    g = s["games"][0]
    check(g["home"]["abbr"] == "ATL" and g["away"]["abbr"] == "BOS", "teams parsed")
    check(g["gameId"] == "0022500999", "nba game id present")

    print("\n[nba analyze]")
    a = client.get(f"/api/analyze/{GAME['gameId']}?date={DATE}&sport=nba").json()
    check(a["sport"] == "nba", "analyze tagged nba")
    gm = a["gameModel"]
    check(abs(gm["homeWinProb"] + gm["awayWinProb"] - 1.0) < 1e-6, "win probs sum to 1")
    check(gm["homeWinProb"] > 0.5, f"stronger home team favored: {gm['homeWinProb']}")
    check(gm["homeProjScore"] > gm["awayProjScore"], "home projected to outscore away")
    check(gm["projMargin"] > 0, "positive home margin")
    check(gm["modelHomeSpread"] < 0, f"home is the favorite (negative spread): {gm['modelHomeSpread']}")
    check(gm["projTotal"] > 180 and gm["projTotal"] < 280, f"total in a sane NBA range: {gm['projTotal']}")
    check(gm["pace"] > 90 and gm["pace"] < 110, f"pace in range: {gm['pace']}")

    check(isinstance(gm["signals"], list) and len(gm["signals"]) >= 3, "signals present")
    check(all({"label", "detail", "lean"} <= set(x) for x in gm["signals"]), "signals shaped for UI")
    leans = {x["lean"] for x in gm["signals"]}
    check(leans <= {"home", "away", "over", "under", "neutral"}, f"valid signal leans: {leans}")
    labels = [x["label"] for x in gm["signals"]]
    check(any("Net rating" in l for l in labels), "net-rating signal present")
    check(any("Home court" in l for l in labels), "home-court signal present")
    r = gm["ratings"]
    check(r["home"]["net"] > r["away"]["net"], "ratings block reflects stronger home")
    print(f"    {g['away']['abbr']} {gm['awayProjScore']} - {gm['homeProjScore']} {g['home']['abbr']} "
          f"| home {gm['homeWinProb']:.0%} | spread {gm['modelHomeSpread']} | total {gm['projTotal']}")

    print("\n[nba player props]")
    picks = a.get("picks", [])
    check(len(picks) >= 4, f"player props generated: {len(picks)}")
    types = {p["propType"] for p in picks}
    check("nba_pts" in types, "points props present")
    check(any(t in ("nba_reb", "nba_ast", "nba_fg3m") for t in types), "non-points props present (variety)")
    pp = picks[0]
    check(pp["pick"].startswith("Home Star") or pp["pick"].startswith("Away Star"), f"player pick label: {pp['pick']}")
    check(pp["side"] in ("over", "under") and "line" in pp, "player pick has side + line")
    check(isinstance(pp["spark"], list) and len(pp["spark"]) >= 1, "player spark present")
    check(isinstance(pp["signals"], list) and len(pp["signals"]) >= 2, "player signals present")
    check(any(s["label"] == "Opponent defense" for s in pp["signals"]), "opponent-defense signal present")
    check(all({"label", "detail", "lean"} <= set(s) for s in pp["signals"]), "player signals shaped")

    print("\n[nba added factors — direct]")
    gm2 = nba_analysis.nba_game_model(
        GAME["home"], GAME["away"], _ratings("2025-26"),
        h2h={"games": 3, "homeWins": 2, "homeAvgMargin": 4.5},
        home_split_net=8.0, away_split_net=-3.0)
    glabels = [s["label"] for s in gm2["signals"]]
    check(any("Head-to-head" in l for l in glabels), "H2H signal present")
    check(any("at home" in l for l in glabels), "home-split signal present")
    check(any("on the road" in l for l in glabels), "road-split signal present")

    print("\n[empty nba slate]")
    empty = client.get(f"/api/slate?date=2026-07-04&sport=nba").json()
    check(empty["count"] == 0, "off-day returns no nba games")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
