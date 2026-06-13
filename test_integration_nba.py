"""End-to-end test of the NBA surface with synthetic data (no network).

Monkeypatches the ``backend.nba`` data layer and exercises the real FastAPI app
+ NBA model through HTTP, verifying the ?sport=nba JSON contract the frontend
(app.js renderNbaAnalysis) consumes.
"""
import sys

from fastapi.testclient import TestClient

import backend.nba as nba
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


def patch_data():
    async def get_schedule(date): return [GAME] if date == DATE else []
    async def get_team_ratings(season, last_n=0): return _ratings(season, last_n)
    async def last_game_before(team_id, season, date): return "2026-01-13"  # 2 days' rest
    async def close(): return None
    nba.get_schedule = get_schedule
    nba.get_team_ratings = get_team_ratings
    nba.last_game_before = last_game_before
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

    print("\n[empty nba slate]")
    empty = client.get(f"/api/slate?date=2026-07-04&sport=nba").json()
    check(empty["count"] == 0, "off-day returns no nba games")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
