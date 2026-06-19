"""End-to-end test of the MMA/UFC surface with synthetic data (no network).

Patches the ESPN card client + the bundled fighter dataset and exercises the
real FastAPI app + MMA model through HTTP (?sport=mma).
"""
import sys

from fastapi.testclient import TestClient

import backend.mma as mma
import backend.mma_data as mma_data
import backend.mma_analysis as mma_analysis
import backend.odds as odds
from backend.main import app

DATE = "2026-06-15"
FIGHT = {
    "gameId": "401700001", "date": DATE, "event": "UFC Test: A vs. B",
    "weightClass": "Lightweight", "rounds": 5, "status": "Sat, 7:00 PM",
    "away": {"name": "Alpha Striker", "abbr": "Striker", "record": "20-1-0"},
    "home": {"name": "Bravo Grappler", "abbr": "Grappler", "record": "15-6-0"},
}

# Alpha = elite striker/finisher; Bravo = weaker, gets finished often -> A favored.
def _fighter(strong):
    if strong:
        return {"name": "Alpha Striker", "fights": 21, "wins": 20, "losses": 1, "minutes": 250.0,
                "slpm": 5.5, "sapm": 3.0, "strAcc": 0.55, "strDef": 0.65,
                "tdAvg": 1.5, "tdAcc": 0.5, "tdDef": 0.85, "subAvg": 0.5,
                "kdPer15": 1.2, "kdAbsPer15": 0.2, "ctrlPerMin": 0.3,
                "koRate": 0.6, "subRate": 0.2, "decRate": 0.2, "finishRate": 0.8, "finishedRate": 0.0,
                "weightClass": "Lightweight", "reachIn": 72.0, "stance": "Orthodox", "dob": "Jan 01, 1997"}
    return {"name": "Bravo Grappler", "fights": 21, "wins": 15, "losses": 6, "minutes": 300.0,
            "slpm": 3.0, "sapm": 4.5, "strAcc": 0.42, "strDef": 0.50,
            "tdAvg": 2.5, "tdAcc": 0.4, "tdDef": 0.55, "subAvg": 1.2,
            "kdPer15": 0.3, "kdAbsPer15": 0.9, "ctrlPerMin": 0.8,
            "koRate": 0.2, "subRate": 0.4, "decRate": 0.4, "finishRate": 0.6, "finishedRate": 0.8,
            "weightClass": "Lightweight", "reachIn": 70.0, "stance": "Southpaw", "dob": "Jan 01, 1990"}


def patch_data():
    async def get_schedule(date): return [FIGHT] if date == DATE else []
    async def close(): return None
    mma.get_schedule = get_schedule
    mma.close = close
    mma.client = lambda: None
    mma_data.get_fighter = lambda name: _fighter("Alpha" in name)


FAIL = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def main():
    patch_data()
    client = TestClient(app)

    print("\n[mma slate]")
    s = client.get(f"/api/slate?date={DATE}&sport=mma").json()
    check(s["sport"] == "mma", "sport tagged mma")
    check(s["count"] == 1, "one fight in slate")
    check(s["games"][0]["rounds"] == 5, "main-event rounds parsed")

    print("\n[mma analyze]")
    a = client.get(f"/api/analyze/{FIGHT['gameId']}?date={DATE}&sport=mma").json()
    check(a["sport"] == "mma", "analyze tagged mma")
    fm = a["fightModel"]
    check(fm is not None, "fight model present")
    check(abs(fm["aWinProb"] + fm["bWinProb"] - 1.0) < 1e-6, "win probs sum to 1")
    check(fm["aWinProb"] > 0.5, f"stronger fighter favored: {fm['aWinProb']}")
    pick = fm["pick"]
    check(pick["fighter"] == fm["aName"], "winner pick is the favoured fighter")
    check(pick["tier"] in ("Strong", "Lean", "Pass"), f"pick tier valid: {pick['tier']}")
    check(pick["tier"] == "Strong" and not pick["coinFlip"], "heavy favourite -> Strong, not a coin flip")
    check(0 <= pick["confidence"] <= 100, "pick confidence in range")
    m = fm["method"]
    check(abs(m["ko"] + m["sub"] + m["decision"] - 1.0) < 1e-6, "method probs sum to 1")
    check(0.0 <= fm["distanceProb"] <= 1.0, "distance prob in range")
    check(fm["projSigStrikes"]["total"] > 0, "sig-strike projection present")
    check(isinstance(fm["signals"], list) and len(fm["signals"]) >= 5, "fight signals present")
    leans = {x["lean"] for x in fm["signals"]}
    check(leans <= {"a", "b", "over", "under", "neutral"}, f"valid signal leans: {leans}")

    picks = a["picks"]
    ptypes = {p["propType"] for p in picks}
    check("mma_distance" in ptypes, "distance/round prop present")
    check("mma_sigstr" in ptypes, "sig-strikes prop present")
    check(any(t == "mma_sigstr_total" for t in ptypes), "total sig-strikes prop present")
    check(all({"pick", "side", "line", "modelProb", "confidence", "signals"} <= set(p) for p in picks),
          "props shaped for the pick card")
    print(f"    {fm['aName']} {fm['aWinProb']:.0%} vs {fm['bName']} {fm['bWinProb']:.0%} | "
          f"KO {m['ko']:.0%} Sub {m['sub']:.0%} Dec {m['decision']:.0%} | picks {len(picks)}")

    # Comps (nearest-neighbor) — present + shaped when the vectors dataset exists.
    comps = a.get("comps")
    if comps is not None:
        check(comps["favorite"] in (FIGHT["away"]["name"], FIGHT["home"]["name"]), "comps favorite is one of the fighters")
        check(0.0 <= comps["favWinPct"] <= 1.0, "comps favorite win pct in range")
        check(abs(sum(comps["method"].values()) - 1.0) < 0.05, "comps method dist ~sums to 1")
        check(isinstance(comps["similar"], list) and len(comps["similar"]) >= 1, "comps lists similar fights")
        print(f"    comps: {comps['favorite']} won {comps['favWinPct']:.0%} of {comps['n']} comps; distance {comps['distancePct']:.0%}")
    else:
        print("    comps: none (vectors dataset not built)")

    print("\n[moneyline EV with synthetic odds]")
    # Synthetic h2h: Alpha -200 (fair ~64%), but the model has Alpha ~81% -> +EV on Alpha.
    EVENT = {"id": "evt1", "home_team": "Bravo Grappler", "away_team": "Alpha Striker",
             "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                 {"name": "Alpha Striker", "price": -200},
                 {"name": "Bravo Grappler", "price": 170}]}]}]}
    _orig_has_key, _orig_fetch = odds.has_key, odds.get_mma_markets
    odds.has_key = lambda *a, **k: True
    async def _fake_markets(c, api_key=None): return [EVENT]
    odds.get_mma_markets = _fake_markets
    try:
        am = client.get(f"/api/analyze/{FIGHT['gameId']}?date={DATE}&sport=mma").json()
    finally:
        odds.has_key, odds.get_mma_markets = _orig_has_key, _orig_fetch
    ml = am["fightModel"].get("moneyline")
    check(ml is not None, "moneyline edges attached to fight model")
    check(ml["a"]["price"] == -200 and ml["b"]["price"] == 170, "fighter prices matched by name")
    check(ml["a"]["evPct"] > 0, f"+EV flagged on the model's favorite ({ml['a']['evPct']}%)")
    check(abs(ml["a"]["fairProb"] + ml["b"]["fairProb"] - 1.0) < 1e-6, "moneyline de-vigged to fair probs")
    mlp = [p for p in am["picks"] if p["propType"] == "mma_moneyline"]
    check(len(mlp) == 2, "a moneyline pick per fighter on the board")
    check(all(p["hasMarket"] and p["edge"] for p in mlp), "moneyline picks carry a market edge")

    print("\n[one fighter missing -> league-average fallback, flagged]")
    # Odds enabled here so we verify the guard actually suppresses EV for a synthetic fighter.
    mma_data.get_fighter = lambda name: _fighter("Alpha" in name) if "Alpha" in name else None
    odds.has_key = lambda *a, **k: True
    odds.get_mma_markets = _fake_markets
    try:
        a2 = client.get(f"/api/analyze/{FIGHT['gameId']}?date={DATE}&sport=mma").json()
    finally:
        odds.has_key, odds.get_mma_markets = _orig_has_key, _orig_fetch
    check(a2["fightModel"] is not None, "one-missing still produces a model")
    check(a2.get("lowData") is True and a2.get("note"), "low-data flag + note set")
    check(not a2["fightModel"].get("moneyline"), "no moneyline edge computed off a synthetic fighter")
    check(not any(p["propType"] == "mma_moneyline" for p in a2["picks"]), "no moneyline pick when low-data")

    print("\n[both fighters missing -> graceful blank]")
    mma_data.get_fighter = lambda name: None
    a3 = client.get(f"/api/analyze/{FIGHT['gameId']}?date={DATE}&sport=mma").json()
    check(a3["fightModel"] is None and "note" in a3, "both-missing returns a graceful note")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
