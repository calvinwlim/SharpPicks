"""End-to-end test of the API surface with synthetic data.

The sandbox can't reach statsapi.mlb.com, so we monkeypatch the data-layer
functions and exercise the real FastAPI app + analysis engine through HTTP.
This verifies the exact JSON contract the frontend (app.js) consumes.
"""
import asyncio
import sys

from fastapi.testclient import TestClient

import backend.analysis as analysis
import backend.mlb as mlb
import backend.odds as odds
import backend.savant as savant
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
    bbs = [2, 1, 3, 2, 1, 2, 3, 1, 2, 1, 2, 3, 1, 2, 1]
    ers = [2, 3, 1, 2, 4, 2, 1, 0, 3, 2, 2, 1, 3, 2, 1]
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
            "baseOnBalls": bbs[i],
            "inningsPitched": 6.0,
            "battersFaced": 24,
            "earnedRuns": ers[i],
            "runs": ers[i],
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

    # Tier 1 signal fetches — patched to neutral so the suite stays hermetic
    # (no network). The factor *math* is exercised directly in check_factors().
    async def get_umpire(game_pk): return None
    async def get_lineup(game_pk, team_id): return None
    async def get_bullpen(team_id, season): return {"era": None, "ip": 0.0, "fatigued": False}
    async def get_pitcher_skill(pid, season): return None
    async def get_lineup_batters(game_pk, team_id): return None
    async def get_batter_gamelog(pid, season): return []
    async def get_player_props(client, event_id, market_key, api_key=None): return {}
    mlb.get_umpire = get_umpire
    mlb.get_lineup = get_lineup
    mlb.get_bullpen = get_bullpen
    mlb.get_lineup_batters = get_lineup_batters
    mlb.get_batter_gamelog = get_batter_gamelog
    savant.get_pitcher_skill = get_pitcher_skill
    odds.get_player_props = get_player_props


def enable_market():
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    odds.has_key = lambda *a, **k: True
    odds.player_props_enabled = lambda: True
    async def get_game_markets(client, api_key=None): return [{"id": "evt1"}]
    odds.get_game_markets = get_game_markets
    odds.match_event = lambda events, home, away: {"id": "evt1"}
    odds.best_moneyline = lambda event, team: -120 if "Red Sox" in team else 130
    async def props(client, event_id, api_key=None):
        # Offer a soft line below the projection so the model likes the OVER.
        return {norm("Test Ace"): {"line": 5.5, "over": -115, "under": -105}}
    odds.get_pitcher_strikeout_props = props


def disable_market():
    odds.has_key = lambda *a, **k: False
    odds.player_props_enabled = lambda: False


FAIL = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def check_factors():
    """Exercise the Tier 1 factor math directly against analysis.* (no HTTP)."""
    trs = {SEASON: _team_rates(SEASON)}
    log = _gamelog(700, SEASON)

    def proj(**kw):
        return analysis.analyze_strikeouts(
            pitcher_name="Test Ace", gamelog=log, opponent_id=110,
            opponent_name="Baltimore Orioles", is_home=True,
            team_rates_by_season=trs, current_season=SEASON, **kw)

    base = proj()

    # --- umpire: wide zone -> more Ks, tight zone -> fewer -----------------------
    wide = {"name": "Wide Zone", "kFactor": 1.08, "bbFactor": 0.90, "runFactor": 0.96}
    tight = {"name": "Tight Zone", "kFactor": 0.92, "bbFactor": 1.12, "runFactor": 1.05}
    up, down = proj(umpire=wide), proj(umpire=tight)
    check(up["projection"] > base["projection"] > down["projection"], "umpire scales K projection")
    check(up["umpire"]["factor"] == 1.08, "umpire info surfaced on pick")

    # --- Statcast skill blend nudges the projection and reports itself -----------
    skilled = proj(pitcher_skill={"kPct": 0.40, "swStrPct": 0.16})
    check(skilled["skill"] is not None and skilled["skill"]["kPct"] == 0.40, "skill info surfaced")
    check(skilled["projection"] > base["projection"], "high-K skill raises projection")

    # --- confirmed lineup overrides team-season rate; unconfirmed is ignored -----
    lconf = proj(opp_lineup={"confirmed": True, "kRate": 0.18, "bbRate": 0.05})
    check(lconf["lineupConfirmed"] is True, "confirmed lineup used")
    check(lconf["projection"] < base["projection"], "low-K lineup lowers projection")
    unconf = proj(opp_lineup={"confirmed": False, "kRate": 0.18})
    check(unconf["lineupConfirmed"] is False and unconf["projection"] == base["projection"],
          "unconfirmed lineup ignored")

    # --- umpire run factor on the game total -------------------------------------
    neutral_total = analysis.analyze_game_total(4.5, 4.5)
    tight_total = analysis.analyze_game_total(4.5, 4.5, umpire=tight)
    check(tight_total["umpFactor"] > 1.0, "tight-zone ump raises run total")

    # --- Tier 2: park factor + wind direction ------------------------------------
    coors = analysis.analyze_game_total(
        4.5, 4.5, park={"venue": "Coors Field", "runFactor": 1.15, "hrFactor": 1.12, "cfAzimuth": None})
    oracle = analysis.analyze_game_total(
        4.5, 4.5, park={"venue": "Oracle Park", "runFactor": 0.92, "hrFactor": 0.81, "cfAzimuth": 92})
    check(coors["projection"] > neutral_total["projection"], "hitter park (Coors) raises total")
    check(oracle["projection"] < neutral_total["projection"], "pitcher park (Oracle) lowers total")
    check(coors["parkFactor"] > 1.0 and oracle["parkFactor"] < 1.0, "park factors applied")

    # Wrigley faces ~NE (CF azimuth 36). A SW wind blows out to center (more
    # runs); a NE wind blows in (fewer). tempF 70 keeps the weather factor neutral.
    wpark = {"venue": "Wrigley Field", "runFactor": 1.0, "hrFactor": 1.02, "cfAzimuth": 36}
    out_w = {"isDome": False, "tempF": 70, "windMph": 15, "windDir": 216}
    in_w = {"isDome": False, "tempF": 70, "windMph": 15, "windDir": 36}
    out_t = analysis.analyze_game_total(4.5, 4.5, weather=out_w, park=wpark)
    in_t = analysis.analyze_game_total(4.5, 4.5, weather=in_w, park=wpark)
    check(out_t["wind"]["blowing"] == "out" and out_t["windFactor"] > 1.0, "wind out raises total")
    check(in_t["wind"]["blowing"] == "in" and in_t["windFactor"] < 1.0, "wind in lowers total")
    check(out_t["projection"] > in_t["projection"], "out-wind total > in-wind total")
    # A dome ignores wind even with an azimuth on file.
    domed = analysis.analyze_game_total(4.5, 4.5, weather={"isDome": True}, park=wpark)
    check(domed["windFactor"] == 1.0, "dome ignores wind")

    # --- pitcher-aware run model: starters + bullpen move win prob & total -------
    rates = {"runsPerGame": 4.5}
    prev = {"runsAllowedPerGame": 4.3}
    ace = analysis.game_model(rates, rates, prev, prev, home_starter_ra9=2.0, away_starter_ra9=5.5)
    scrub = analysis.game_model(rates, rates, prev, prev, home_starter_ra9=5.5, away_starter_ra9=2.0)
    check(ace["homeWinProb"] > scrub["homeWinProb"], "home ace start raises home win prob")
    check(ace["awayProjRuns"] < scrub["awayProjRuns"], "home ace suppresses away projected runs")
    weak_pen = analysis.game_model(rates, rates, prev, prev, away_bullpen={"era": 6.5})
    base_gm = analysis.game_model(rates, rates, prev, prev)
    check(weak_pen["homeProjRuns"] > base_gm["homeProjRuns"], "weak away bullpen raises home runs")

    # --- Phase 3a: F5 + NRFI ------------------------------------------------------
    check(abs(mlb.parse_ip("5.2") - (5 + 2 / 3)) < 1e-9, "IP 5.2 parses to 5 + 2/3")
    check(abs(mlb.parse_ip("6.0") - 6.0) < 1e-9, "IP 6.0 parses to 6.0")

    ace_f5 = analysis.analyze_f5(4.5, 4.5, 2.0, 2.0)      # two aces
    bad_f5 = analysis.analyze_f5(4.5, 4.5, 6.5, 6.5)      # two batting-practice arms
    check(ace_f5["projection"] < bad_f5["projection"], "stingy starters lower the F5 total")
    check(abs(ace_f5["homeWinProb"] + ace_f5["awayWinProb"] + ace_f5["tieProb"] - 1.0) < 1e-6,
          "F5 win probs sum to 1")

    ace_nrfi = analysis.analyze_nrfi(4.5, 4.5, 2.0, 2.0)
    bad_nrfi = analysis.analyze_nrfi(4.5, 4.5, 6.5, 6.5)
    check(ace_nrfi["nrfiProb"] > bad_nrfi["nrfiProb"], "stingy starters raise NRFI")
    league_nrfi = analysis.analyze_nrfi(4.3, 4.3, 4.1, 4.1)["nrfiProb"]
    check(0.30 < league_nrfi < 0.70, f"league-ish NRFI in a sane band: {league_nrfi}")

    # --- Phase 3b: batter prop ---------------------------------------------------
    blog = [{
        "season": 2025, "date": f"2025-05-{10 + i:02d}", "isHome": bool(i % 2),
        "opponentId": 110 if i % 2 == 0 else 444, "opponentName": "x",
        "hits": h, "totalBases": h, "homeRuns": 0, "atBats": 4, "plateAppearances": 4, "strikeOuts": 1,
    } for i, h in enumerate([1, 2, 0, 1, 1, 0, 2, 1, 1, 0])]
    bp = analysis.analyze_batter_prop("hits", "hits", "Hits", "hits", "Slugger", blog, 110, "Some Arm", True)
    check(bp is not None and bp["propType"] == "hits", "batter hits prop graded")
    check(bp["pick"].startswith("Slugger ") and bp["statNoun"] == "hits", "batter pick label + noun")
    hi = analysis.analyze_batter_prop("hits", "hits", "Hits", "hits", "S", blog, 110, "x", True, opp_factor=1.1)
    lo = analysis.analyze_batter_prop("hits", "hits", "Hits", "hits", "S", blog, 110, "x", True, opp_factor=0.9)
    check(hi["projection"] > lo["projection"], "hittable starter raises batter projection")
    thin = analysis.analyze_batter_prop("hits", "hits", "Hits", "hits", "S", blog[:5], 110, "x", True)
    check(thin is None, "too few games -> no batter pick")

    # --- discrepancy signals ------------------------------------------------------
    sig_pick = proj()
    labels = [s["label"] for s in sig_pick["signals"]]
    check("Projection vs line" in labels and "Recent form" in labels, "core signals present")
    check(all(s["lean"] in ("over", "under", "neutral") for s in sig_pick["signals"]),
          "every signal has a valid lean")
    check(any(s["label"] == "Opponent" for s in sig_pick["signals"]), "opponent signal present")
    check(any(s["label"] == "Recent form" for s in bp["signals"]), "batter signals present")


def check_batter_props(client):
    """Post a synthetic lineup + batter logs and confirm batter props are graded
    end-to-end through the analyze endpoint (analysis-only mode)."""
    async def lineup_batters(game_pk, team_id):
        return [{"id": 900, "name": "Test Slugger"}] if team_id == 111 else None

    def synth_log(season):
        hits = [1, 2, 0, 1, 1, 0, 2, 1, 1, 0, 1, 2, 1, 0, 1]
        hrs = [0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1]
        return [{
            "season": season, "date": f"{season}-05-{10 + i:02d}", "isHome": bool(i % 2),
            "opponentId": 110 if i % 2 == 0 else 444,
            "opponentName": "Baltimore Orioles" if i % 2 == 0 else "Other Team",
            "hits": h, "totalBases": h + hrs[i] * 3, "homeRuns": hrs[i],
            "atBats": 4, "plateAppearances": 4, "strikeOuts": 1,
        } for i, h in enumerate(hits)]

    async def batter_gamelog(pid, season): return synth_log(season)
    mlb.get_lineup_batters = lineup_batters
    mlb.get_batter_gamelog = batter_gamelog

    a = client.get(f"/api/analyze/{GAME['gamePk']}?date={DATE}&ai=0").json()
    btypes = {p["propType"] for p in a["picks"]}
    check({"hits", "totalBases", "homeRuns"} & btypes != set(), "batter props generated for confirmed lineup")
    bp = next(p for p in a["picks"] if p["propType"] in ("hits", "totalBases", "homeRuns"))
    check(bp["player"] == "Test Slugger", "batter pick player name")
    check(bp["pick"].startswith("Test Slugger "), f"batter pick label: {bp['pick']}")
    check(isinstance(bp["spark"], list) and len(bp["spark"]) >= 1, "batter spark present")
    check("opponentPitcher" in bp, "batter pick records opposing pitcher")
    check(isinstance(bp.get("narrative"), str) and bp["narrative"], "batter narrative present")
    check(bp["statNoun"] in bp["narrative"] and "strikeouts" not in bp["narrative"],
          "narrative uses the prop's noun, not 'strikeouts'")

    # restore neutral so later sections see no lineup
    async def none_lineup(game_pk, team_id): return None
    async def empty_log(pid, season): return []
    mlb.get_lineup_batters = none_lineup
    mlb.get_batter_gamelog = empty_log


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
    check(len(a["picks"]) == 2, "two graded picks for Test Ace (K's + walks; away SP has no logs)")
    picks_by_type = {pk["propType"]: pk for pk in a["picks"]}
    check("strikeouts" in picks_by_type and "walks" in picks_by_type, "both prop types present")

    p = picks_by_type["strikeouts"]
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

    bb = picks_by_type["walks"]
    check(bb["pick"].endswith("BB"), f"walks pick label: {bb['pick']}")
    check(bb["side"] in ("over", "under"), f"walks model picked a side: {bb['side']}")
    check(isinstance(bb["splits"], list) and len(bb["splits"]) >= 4, "walks splits present")

    check(a["gameModel"] is not None, "game model present")
    gm = a["gameModel"]
    check(abs((gm["homeWinProb"] + gm["awayWinProb"]) - 1.0) < 1e-6, "win probs sum to 1")
    total = gm["total"]
    check(total["side"] in ("over", "under"), f"total side: {total['side']}")
    check(total["edge"] is None and total["hasMarket"] is False, "no total edge without odds")

    f5 = gm["f5"]
    check(f5["side"] in ("over", "under"), f"f5 total side: {f5['side']}")
    check(abs(f5["homeWinProb"] + f5["awayWinProb"] + f5["tieProb"] - 1.0) < 1e-6, "f5 win probs sum to 1")
    check(f5["projection"] < total["projection"], "f5 total < full-game total")
    nrfi = gm["nrfi"]
    check(nrfi["side"] in ("nrfi", "yrfi"), f"nrfi side: {nrfi['side']}")
    check(abs(nrfi["nrfiProb"] + nrfi["yrfiProb"] - 1.0) < 1e-6, "nrfi + yrfi = 1")

    # Tier 1 factors present and neutral when their data sources are absent.
    check(p["umpire"] is None, "no umpire info when unassigned")
    check(p["skill"] is None, "no skill info without Statcast")
    check(p["lineupConfirmed"] is False, "lineup not confirmed -> team rates used")
    check(total["umpFactor"] == 1.0, "neutral umpire run factor")

    # Discrepancy signals attached to every pick.
    check(isinstance(p.get("signals"), list) and len(p["signals"]) >= 2, "strikeout pick has signals")
    check(all({"label", "detail", "lean"} <= set(s) for s in p["signals"]), "signals shaped for UI")
    print("    narrative:", p["narrative"][:140])

    print("\n[batter props — confirmed lineup]")
    check_batter_props(client)

    print("\n[analyze — with live market]")
    enable_market()
    a2 = client.get(f"/api/analyze/{GAME['gamePk']}?date={DATE}&ai=0").json()
    check(a2["flags"]["hasOdds"] is True, "odds flag on")
    p2 = next(pk for pk in a2["picks"] if pk["propType"] == "strikeouts")
    check(p2["hasMarket"] is True and p2["edge"] is not None, "edge present with market")
    e = p2["edge"]
    for k in ("line", "side", "price", "decimal", "modelProb", "marketProb", "fairProb", "evPct", "kellyPct"):
        check(k in e, f"edge has {k}")
    check(e["line"] == 5.5, "edge uses the market line")
    check(isinstance(e["evPct"], (int, float)), "evPct numeric")

    # moneyline block must carry the full edge shape the frontend's edgeLine()
    # renders (modelProb + kellyPct), and win prob must be sane (log5, not clamped).
    ml = a2["gameModel"].get("moneyline")
    check(ml is not None, "moneyline present with market")
    for side in ("home", "away"):
        for k in ("price", "modelProb", "marketProb", "fairProb", "evPct", "kellyPct"):
            check(k in ml[side], f"moneyline.{side} has {k}")
    wp = a2["gameModel"]["homeWinProb"]
    check(0.05 < wp < 0.95, f"home win prob is sane (log5), not clamped: {wp}")
    print(f"    edge: line {e['line']} side {e['side']} model {e['modelProb']} "
          f"market {e['marketProb']} EV {e['evPct']}% kelly {e['kellyPct']}%")

    print("\n[Tier 1 factors — direct]")
    check_factors()

    print("\n[empty slate]")
    empty = client.get("/api/slate?date=2025-01-01").json()
    check(empty["count"] == 0, "off-season date returns no games")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
