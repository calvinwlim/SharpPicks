"""End-to-end test of the API surface with synthetic data.

The sandbox can't reach statsapi.mlb.com, so we monkeypatch the data-layer
functions and exercise the real FastAPI app + analysis engine through HTTP.
This verifies the exact JSON contract the frontend (app.js) consumes.
"""
import asyncio
import sys

from fastapi.testclient import TestClient

import backend.mlb as mlb
import backend.odds as odds
from backend.main import app

SEASON = 2025
DATE = "2025-07-15"

# --- synthetic schedule -------------------------------------------------------
GAME = {
    "gamePk": 99001,
    "gameDate": f"{DATE}T17:10:00Z",
    "dayNight": "day",
    "status": "Scheduled",
    "venue": "Fenway Park",
    "home": {"id": 111, "name": "Boston Red Sox", "abbr": "BOS",
             "probablePitcher": {"id": 700, "name": "Test Ace"}},
    "away": {"id": 110, "name": "Baltimore Orioles", "abbr": "BAL",
             "probablePitcher": {"id": 701, "name": "Spot Starter"}},
}

# --- synthetic team rates (BAL = high-K offense, ranked near top) -------------
def _team_rates(season):
    teams = {
        110: {"id": 110, "name": "Baltimore Orioles", "abbr": "BAL",
              "kRate": 0.262, "bbRate": 0.095, "runsPerGame": 4.8, "pa": 6000,
              "kRank": 5, "bbRank": 8},
        111: {"id": 111, "name": "Boston Red Sox", "abbr": "BOS",
              "kRate": 0.221, "bbRate": 0.082, "runsPerGame": 4.6, "pa": 6000,
              "kRank": 20, "bbRank": 18},
    }
    return {"season": season, "teams": teams,
            "leagueAvgK": 0.225, "leagueAvgBB": 0.085, "nTeams": 30}

def _run_prev(season):
    return {"season": season, "teams": {
        110: {"id": 110, "runsAllowedPerGame": 4.5, "era": 4.10},
        111: {"id": 111, "runsAllowedPerGame": 4.2, "era": 3.90},
    }}

# --- synthetic game logs: Test Ace racks up Ks, mostly vs BAL ----------------
def _gamelog(person_id, season):
    if person_id != 700:
        return []  # away starter has no usable history -> no pick (tests that path)
    ks = [7, 8, 6, 9, 7, 5, 8, 10, 6, 7, 8, 9, 7, 6, 8]
    rows = []
    for i, k in enumerate(ks):
        opp = 110 if i % 2 == 0 else 444  # alternate BAL / some other team
        rows.append({
            "season": season,
            "date": f"{season}-0{(i % 9) + 1}-1{i % 9}",
            "isHome": bool(i % 2),
            "opponentId": opp,
            "opponentName": "Baltimore Orioles" if opp == 110 else "Other Team",
            "strikeOuts": k,
            "inningsPitched": 6.0,
            "battersFaced": 24,
        })
    return rows


def patch_data(monkeyless=True):
    async def get_schedule(date): return [GAME] if date == DATE else []
    async def get_team_rates(season): return _team_rates(season)
    async def get_team_run_prevention(season): return _run_prev(season)
    async def get_pitcher_gamelog(pid, season): return _gamelog(pid, season)
    async def close(): return None
    mlb.get_schedule = get_schedule
    mlb.get_team_rates = get_team_rates
    mlb.get_team_run_prevention = get_team_run_prevention
    mlb.get_pitcher_gamelog = get_pitcher_gamelog
    mlb.close = close
    mlb.client = lambda: None


def enable_market():
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    odds.has_key = lambda: True
    odds.player_props_enabled = lambda: True
    async def get_game_markets(client): return [{"id": "evt1"}]
    odds.get_game_markets = get_game_markets
    odds.match_event = lambda events, home, away: {"id": "evt1"}
    odds.best_moneyline = lambda event, team: -120 if "Red Sox" in team else 130
    async def props(client, event_id):
        # Offer a soft line below the projection so the model likes the OVER.
        return {norm("Test Ace"): {"line": 5.5, "over": -115, "under": -105}}
    odds.get_pitcher_strikeout_props = props


def disable_market():
    odds.has_key = lambda: False
    odds.player_props_enabled = lambda: False


FAIL = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def main():
    patch_data()
    client = TestClient(app)

    print("\n[health]")
    r = client.get("/api/health").json()
    check(r.get("ok") is True, "health ok")
    check("flags" in r, "health has flags")

    print("\n[slate]")
    disable_market()
    s = client.get(f"/api/slate?date={DATE}").json()
    check(s["count"] == 1, "one game in slate")
    g = s["games"][0]
    check(g["home"]["abbr"] == "BOS" and g["away"]["abbr"] == "BAL", "teams parsed")
    check(g["home"]["probablePitcher"]["name"] == "Test Ace", "home probable parsed")
    check(s["flags"]["hasOdds"] is False, "analysis-only flag")

    print("\n[analyze — analysis only]")
    a = client.get(f"/api/analyze/{GAME['gamePk']}?date={DATE}&ai=0").json()
    check(len(a["picks"]) == 1, "exactly one graded pick (away SP has no logs)")
    p = a["picks"][0]
    check(p["player"] == "Test Ace", "pick is for Test Ace")
    check(p["side"] in ("over", "under"), f"model picked a side: {p['side']}")
    check(p["pick"].startswith("Test Ace "), f"pick label: {p['pick']}")
    check(0 <= p["confidence"] <= 100, "confidence in range")
    check(p["tier"] in ("Premium", "Strong", "Lean"), f"tier: {p['tier']}")
    check(isinstance(p["splits"], list) and len(p["splits"]) >= 4, "splits present")
    labels = [s["label"] for s in p["splits"]]
    check(any("Baltimore" in l for l in labels), "has vs-opponent split")
    check(any("offenses" in l for l in labels), "has K-rate-bucket split")
    check(isinstance(p["spark"], list) and len(p["spark"]) >= 1, "spark series present")
    check(all({"date", "opp", "k", "home"} <= set(x) for x in p["spark"]), "spark rows shaped for chart")
    check(p["edge"] is None and p["hasMarket"] is False, "no edge without odds")
    check(isinstance(p.get("narrative"), str) and p["narrative"], "template narrative present")
    check(a["gameModel"] is not None, "game model present")
    gm = a["gameModel"]
    check(abs((gm["homeWinProb"] + gm["awayWinProb"]) - 1.0) < 1e-6, "win probs sum to 1")
    print("    narrative:", p["narrative"][:140])

    print("\n[analyze — with live market]")
    enable_market()
    a2 = client.get(f"/api/analyze/{GAME['gamePk']}?date={DATE}&ai=0").json()
    check(a2["flags"]["hasOdds"] is True, "odds flag on")
    p2 = a2["picks"][0]
    check(p2["hasMarket"] is True and p2["edge"] is not None, "edge present with market")
    e = p2["edge"]
    for k in ("line", "side", "price", "decimal", "modelProb", "marketProb", "fairProb", "evPct", "kellyPct"):
        check(k in e, f"edge has {k}")
    check(e["line"] == 5.5, "edge uses the market line")
    check(isinstance(e["evPct"], (int, float)), "evPct numeric")
    print(f"    edge: line {e['line']} side {e['side']} model {e['modelProb']} "
          f"market {e['marketProb']} EV {e['evPct']}% kelly {e['kellyPct']}%")

    print("\n[empty slate]")
    empty = client.get("/api/slate?date=2025-01-01").json()
    check(empty["count"] == 0, "off-season date returns no games")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
