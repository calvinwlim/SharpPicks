"""FastAPI app: HTTP endpoints + per-game orchestration.

See CLAUDE.md for the API contract. Data flows one direction:
``mlb``/``odds`` fetch -> ``analysis`` grades -> this module serializes JSON
-> ``frontend/app.js`` renders.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from . import ai as ai_module
from . import (analysis, mlb, mma, mma_analysis, mma_comps, mma_data, nba,
               nba_analysis, odds, parks, savant, umpires, weather as weather_module)

load_dotenv()

app = FastAPI(title="Sharp Slate")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Batter prop specs: (propType, gamelog stat key, label, noun, Odds API market,
# park HR factor application, default Over line, bernoulli?). ``bernoulli`` marks
# at-most-one-per-AB stats (hits/HR -> binomial); total bases stays Poisson.
BATTER_PROPS = [
    ("hits", "hits", "Hits", "hits", "batter_hits", lambda hrf: 1.0, 0.5, True),
    # totalBases suppressed: backtest (2725 samples) showed Brier 0.269 vs 0.247 base-rate —
    # Poisson gives zero discriminative power on TB; model can't beat coin-flip here.
    ("homeRuns", "homeRuns", "HR", "home runs", "batter_home_runs", lambda hrf: hrf, 0.5, True),
]
BATTER_PICK_CAP = 8       # most batter props to surface per game (keeps the board readable)
BATTER_PER_TYPE_CAP = 3   # max analysis-only picks of one prop type (variety on the board)


# Optional per-request key overrides, sent from the frontend's settings panel
# (header names chosen to match what app.js sends). Falls back to env vars.
OddsKeyHeader = Header(None, alias="X-Odds-Api-Key")
AnthropicKeyHeader = Header(None, alias="X-Anthropic-Api-Key")
PlayerPropsHeader = Header(None, alias="X-Odds-Player-Props")  # "1"/"0" per-request props toggle


def _flags(ai_requested: bool = False, odds_key: Optional[str] = None,
           anthropic_key: Optional[str] = None, props_override: Optional[str] = None) -> Dict[str, Any]:
    return {
        "hasOdds": odds.has_key(odds_key),
        "playerProps": odds.player_props_enabled(props_override),
        "hasAI": ai_requested and bool(anthropic_key or os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.get("/api/health")
async def health(x_odds_api_key: Optional[str] = OddsKeyHeader,
                  x_anthropic_api_key: Optional[str] = AnthropicKeyHeader,
                  x_odds_player_props: Optional[str] = PlayerPropsHeader) -> Dict[str, Any]:
    return {"ok": True, "flags": _flags(odds_key=x_odds_api_key, anthropic_key=x_anthropic_api_key,
                                        props_override=x_odds_player_props)}


@app.get("/api/slate")
async def slate(date: str, sport: str = "mlb",
                 x_odds_api_key: Optional[str] = OddsKeyHeader,
                 x_anthropic_api_key: Optional[str] = AnthropicKeyHeader,
                 x_odds_player_props: Optional[str] = PlayerPropsHeader) -> Dict[str, Any]:
    flags = _flags(odds_key=x_odds_api_key, anthropic_key=x_anthropic_api_key,
                   props_override=x_odds_player_props)
    if sport == "nba":
        games = await nba.get_schedule(date)
        return {"date": date, "sport": "nba", "count": len(games), "games": games, "flags": flags}
    if sport == "mma":
        games = await mma.get_schedule(date)
        return {"date": date, "sport": "mma", "count": len(games), "games": games, "flags": flags}
    games = await mlb.get_schedule(date)
    return {"date": date, "sport": "mlb", "count": len(games), "games": games, "flags": flags}


_REPO_ROOT = Path(__file__).parent.parent
_TRACK_DIR = _REPO_ROOT / "tracking"


@app.get("/api/track/history")
async def track_history() -> Dict[str, Any]:
    import json as _json
    entries = []
    if _TRACK_DIR.exists():
        for p in sorted(_TRACK_DIR.glob("*.graded.json")):
            try:
                data = _json.loads(p.read_text(encoding="utf-8"))
                data["graded"] = True
                entries.append(data)
            except Exception:
                pass
    return {"entries": entries}


@app.get("/api/track/{date}")
async def track_summary(date: str) -> Dict[str, Any]:
    path = _TRACK_DIR / f"{date}.graded.json"
    if not path.exists():
        return {"date": date, "graded": False}
    import json as _json
    summary = _json.loads(path.read_text(encoding="utf-8"))
    summary["graded"] = True
    return summary


def _team_rates_or_default(team_rates: Dict[str, Any], team_id: int) -> Dict[str, Any]:
    return team_rates.get("teams", {}).get(team_id, {"runsPerGame": analysis.DEFAULT_RUNS_PER_GAME})


def _run_prevention_or_default(run_prev: Dict[str, Any], team_id: int) -> Dict[str, Any]:
    return run_prev.get("teams", {}).get(team_id, {"runsAllowedPerGame": analysis.DEFAULT_RUNS_PER_GAME})


def _days(iso: str) -> int:
    from datetime import date as _date
    return _date.fromisoformat(iso).toordinal()


@app.get("/api/analyze/{game_id}")
async def analyze(game_id: str, date: str, seasons: int = 4, ai: int = 0, sport: str = "mlb",
                   x_odds_api_key: Optional[str] = OddsKeyHeader,
                   x_anthropic_api_key: Optional[str] = AnthropicKeyHeader,
                   x_odds_player_props: Optional[str] = PlayerPropsHeader) -> Dict[str, Any]:
    if sport == "nba":
        return await _analyze_nba(game_id, date, x_odds_api_key, x_anthropic_api_key,
                                  props_override=x_odds_player_props)
    if sport == "mma":
        return await _analyze_mma(game_id, date, x_odds_api_key, x_anthropic_api_key)
    return await _analyze_mlb(int(game_id), date, seasons, ai, x_odds_api_key, x_anthropic_api_key,
                              props_override=x_odds_player_props)


async def _analyze_mma(game_id: str, date: str, odds_key: Optional[str] = None,
                        anthropic_key: Optional[str] = None) -> Dict[str, Any]:
    fights = await mma.get_schedule(date)
    fight = next((f for f in fights if f["gameId"] == game_id), None)
    if fight is None:
        raise HTTPException(status_code=404, detail="fight not found for that date")

    a_name, b_name = fight["away"]["name"], fight["home"]["name"]
    a, b = mma_data.get_fighter(a_name), mma_data.get_fighter(b_name)
    # Both unknown -> nothing to anchor a read on. One unknown (debut / short-notice
    # replacement) -> model the missing fighter as league-average and flag it hard;
    # a directional read on the known fighter beats a blank, but we do NOT compute a
    # betting edge off a synthetic profile (see the odds guard below).
    low_data_note: Optional[str] = None
    if not a and not b:
        return {"gameId": game_id, "sport": "mma", "fight": fight, "fightModel": None,
                "picks": [], "note": f"No rate-stat data for {a_name} or {b_name} — both look like UFC debutants "
                                     f"(not in ufcstats). Re-run scripts/build_ufc_dataset.py after the next events to refresh.",
                "flags": _flags(odds_key=odds_key, anthropic_key=anthropic_key)}
    if not a or not b:
        missing = a_name if not a else b_name
        wc = fight.get("weightClass")
        if not a:
            a = _neutral_fighter(wc)
        if not b:
            b = _neutral_fighter(wc)
        low_data_note = (f"Limited data: {missing} isn't in the ufcstats dataset (likely a debut or short-notice "
                         f"replacement), so they're modeled as a league-average fighter. Treat this as a directional "
                         f"read only — no betting edge is computed.")

    rounds = fight.get("rounds", 3)
    try:
        comps = mma_comps.find_comps(a, b, a_name, b_name, rounds=rounds, fight_date=date)
    except Exception:
        comps = None
    # Ensemble the parametric model with the historical comps lens (when present).
    comp_p = mma_comps.comp_win_prob_for(comps, a_name)
    model = mma_analysis.analyze_fight(a, b, a_name, b_name, rounds=rounds, fight_date=date,
                                       comp_win_prob=comp_p)
    fm = model["fightModel"]
    picks = model["picks"]

    # ---- moneyline EV (h2h) — the model's win prob vs the vig-removed market ----
    # Suppressed when a fighter is synthetic: an edge off a league-average stand-in
    # would be fiction.
    odds_note: Optional[str] = None
    if odds.has_key(odds_key) and not low_data_note:
        try:
            events = await odds.get_mma_markets(odds.client(), odds_key)
            market_event = odds.match_mma_event(events, a_name, b_name) if events else None
            if not events:
                odds_note = "No upcoming MMA events returned from Odds API — the card may be over or your quota is exhausted."
            elif market_event is None:
                odds_note = f"Fight not found in Odds API ({len(events)} MMA events available)."
            else:
                a_price = odds.best_mma_moneyline(market_event, a_name)
                b_price = odds.best_mma_moneyline(market_event, b_name)
                if a_price is not None and b_price is not None:
                    fair_a, fair_b = odds.devig_two(a_price, b_price)
                    ml = {"a": odds.moneyline_edge(fm["aWinProb"], a_price, fair_a),
                          "b": odds.moneyline_edge(fm["bWinProb"], b_price, fair_b)}
                    fm["moneyline"] = ml
                    picks = _mma_moneyline_picks(a_name, b_name, fm["aWinProb"], fm["bWinProb"], ml) + picks
                else:
                    odds_note = "Matched the fight but no moneyline was priced at the US books."
        except Exception as exc:
            err = str(exc).lower()
            if "401" in err or "unauthorized" in err:
                odds_note = "Odds API key rejected (401) — check that the key is correct."
            elif "402" in err or "quota" in err:
                odds_note = "Odds API quota exceeded — your monthly request limit may be exhausted."
            elif "429" in err:
                odds_note = "Odds API rate limit hit — too many requests in a short period."
            else:
                odds_note = "Could not fetch MMA odds (network error) — showing analysis only."

    return {"gameId": game_id, "sport": "mma", "fight": fight, "fightModel": fm,
            "picks": picks, "comps": comps, "oddsNote": odds_note,
            "lowData": low_data_note is not None, "note": low_data_note,
            "flags": _flags(odds_key=odds_key, anthropic_key=anthropic_key)}


# A league-average UFC fighter, used as a stand-in for a debutant/short-notice
# replacement absent from ufcstats. Win% is held neutral (we ignore regional
# records, which are inflated) and physicals are left unknown so the reach / age /
# stance signals correctly stay silent. Rates track the model's league baselines.
def _neutral_fighter(weight_class: Optional[str]) -> Dict[str, Any]:
    return {
        "name": "(league average)", "fights": 14, "wins": 7, "losses": 7, "minutes": 70.0,
        "slpm": mma_analysis.LG_SLPM, "sapm": mma_analysis.LG_SLPM, "strAcc": 0.45,
        "strDef": mma_analysis.LG_STR_DEF, "tdAvg": 1.4, "tdAcc": 0.40,
        "tdDef": mma_analysis.LG_TD_DEF, "subAvg": 0.6, "kdPer15": 0.45, "kdAbsPer15": 0.45,
        "ctrlPerMin": 0.6, "koRate": 0.35, "subRate": 0.15, "decRate": 0.50,
        "finishRate": 0.50, "finishedRate": 0.50, "weightClass": weight_class,
        "reachIn": None, "stance": None, "dob": None, "lastFightDate": None, "recentWinRate": None,
        "sos": 0.5, "headAcc": 0.35, "grndShare": 0.12, "recentFinishLossRate": 0.25,
    }


def _mma_moneyline_picks(a_name: str, b_name: str, a_win: float, b_win: float,
                         ml: Dict[str, Any]) -> list:
    """Build a board-ready moneyline pick per fighter from the matched edges."""
    out = []
    for name, win, edge in ((a_name, a_win, ml["a"]), (b_name, b_win, ml["b"])):
        ev = edge["evPct"]
        out.append({
            "propType": "mma_moneyline", "statNoun": "moneyline", "player": name,
            "pick": f"{name} ML ({edge['price']:+d})",
            "side": "win", "line": None, "projection": round(win, 3),
            "modelProb": round(win, 4), "confidence": int(max(0, min(100, round(win * 100)))),
            "tier": "Premium" if ev >= 8 else "Strong" if ev > 0 else "Lean",
            "splits": [], "spark": [], "signals": [],
            "edge": edge, "hasMarket": True, "lowSample": False,
        })
    return out


NBA_PROP_MARKETS = {  # our prop propType -> Odds API market key
    "nba_pts": "player_points", "nba_reb": "player_rebounds",
    "nba_ast": "player_assists", "nba_fg3m": "player_threes",
}


async def _analyze_nba(game_id: str, date: str, odds_key: Optional[str] = None,
                        anthropic_key: Optional[str] = None,
                        props_override: Optional[str] = None) -> Dict[str, Any]:
    games = await nba.get_schedule(date)
    game = next((g for g in games if g["gameId"] == game_id), None)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found for that date")

    season = nba.season_for_date(date)
    home, away = game["home"], game["away"]

    def _ok(v, default):
        return default if isinstance(v, Exception) else v

    # All team-level fetches are independent — run them concurrently (stats.nba.com
    # is slow per request, so sequential calls here are what made the tab hang).
    ratings, recent, opp_stats, players, home_loc, away_loc = await asyncio.gather(
        nba.get_team_ratings(season),
        nba.get_team_ratings(season, last_n=10),
        nba.get_team_opp_stats(season),
        nba.get_player_season_stats(season),
        nba.get_team_ratings(season, location="Home"),
        nba.get_team_ratings(season, location="Road"),
        return_exceptions=True,
    )
    ratings = _ok(ratings, {"teams": {}, "leagueOrtg": nba_analysis.DEFAULT_ORTG,
                            "leaguePace": nba_analysis.DEFAULT_PACE})
    recent = _ok(recent, None)
    opp_stats = _ok(opp_stats, {"teams": {}, "league": {}})
    players = _ok(players, {})
    home_split_net = home_loc["teams"].get(home["id"], {}).get("netRtg") if not isinstance(home_loc, Exception) else None
    away_split_net = away_loc["teams"].get(away["id"], {}).get("netRtg") if not isinstance(away_loc, Exception) else None

    # Rest (schedule already cached by get_schedule above) + H2H.
    home_rest = away_rest = None
    try:
        hg, ag = await asyncio.gather(
            nba.last_game_before(home["id"], season, date),
            nba.last_game_before(away["id"], season, date),
        )
        home_rest = (_days(date) - _days(hg)) if hg else None
        away_rest = (_days(date) - _days(ag)) if ag else None
    except Exception:
        pass
    try:
        h2h = await _nba_h2h(home["id"], away["id"], season, date)
    except Exception:
        h2h = None

    # ---- odds: match the event, get game lines + (gated) player-prop lines ----
    props_on = odds.player_props_enabled(props_override)
    market_event: Optional[Dict[str, Any]] = None
    game_lines: Dict[str, Any] = {}
    prop_markets: Dict[str, Dict[str, Any]] = {}
    odds_note: Optional[str] = None
    if odds.has_key(odds_key):
        try:
            events = await odds.get_nba_game_markets(odds.client(), odds_key)
            if not events:
                odds_note = "No upcoming NBA events from Odds API — games may be over or your quota is exhausted."
            else:
                market_event = odds.match_event(events, home["name"], away["name"])
                if market_event is None:
                    odds_note = f"Game not found in Odds API ({len(events)} NBA events available)."
                else:
                    game_lines = odds.nba_game_lines(market_event, home["name"], away["name"])
                    if props_on:
                        eid = market_event["id"]
                        results = await asyncio.gather(*[
                            odds.get_nba_player_props(odds.client(), eid, mk, odds_key, enabled=True)
                            for mk in NBA_PROP_MARKETS.values()], return_exceptions=True)
                        for ptype, res in zip(NBA_PROP_MARKETS, results):
                            prop_markets[ptype] = res if not isinstance(res, Exception) else {}
        except Exception as exc:
            err = str(exc).lower()
            if "401" in err or "unauthorized" in err:
                odds_note = "Odds API key rejected (401) — check that the key is correct."
            elif "402" in err or "quota" in err:
                odds_note = "Odds API quota exceeded — your monthly request limit may be exhausted."
            elif "429" in err:
                odds_note = "Odds API rate limit hit — too many requests in a short period."
            else:
                odds_note = "Could not fetch NBA odds (network error) — showing analysis only."

    gm_market = {}
    if game_lines.get("spread"):
        gm_market["spread"] = game_lines["spread"]["line"]
    if game_lines.get("total"):
        gm_market["total"] = game_lines["total"]["line"]

    game_model = nba_analysis.nba_game_model(
        home, away, ratings, recent=recent, home_rest=home_rest, away_rest=away_rest,
        market=gm_market or None, h2h=h2h, home_split_net=home_split_net, away_split_net=away_split_net,
    )

    # Moneyline EV (vig-removed) — the model's win prob vs the price.
    ml = game_lines.get("moneyline")
    if ml and ml.get("home") is not None and ml.get("away") is not None:
        fair_h, fair_a = odds.devig_two(ml["home"], ml["away"])
        hw = game_model["homeWinProb"]
        game_model["moneyline"] = {
            "home": odds.moneyline_edge(hw, ml["home"], fair_h),
            "away": odds.moneyline_edge(1 - hw, ml["away"], fair_a),
        }

    picks: List[Dict[str, Any]] = []
    if players:
        picks = await _nba_player_picks(home, away, season, ratings, opp_stats, players,
                                        game_model["pace"], prop_markets)

    return {"gameId": game_id, "sport": "nba", "game": game, "gameModel": game_model,
            "picks": picks, "oddsNote": odds_note,
            "flags": _flags(odds_key=odds_key, anthropic_key=anthropic_key)}


async def _nba_h2h(home_id: int, away_id: int, season: str, before_date: str):
    """This-season head-to-head from the schedule (needs final scores)."""
    games = await nba._full_schedule(season)
    margins: List[float] = []
    wins = 0
    for g in games:
        if g.get("statusCode") != 3 or g["date"] >= before_date:
            continue
        ids = {g["home"]["id"], g["away"]["id"]}
        if ids != {home_id, away_id} or g.get("homeScore") is None or g.get("awayScore") is None:
            continue
        # margin from the perspective of *this game's* home team
        m = (g["homeScore"] - g["awayScore"]) if g["home"]["id"] == home_id else (g["awayScore"] - g["homeScore"])
        margins.append(m)
        if m > 0:
            wins += 1
    if not margins:
        return None
    return {"games": len(margins), "homeWins": wins, "homeAvgMargin": round(sum(margins) / len(margins), 1)}


NBA_PLAYER_PICK_CAP = 14
NBA_PLAYERS_PER_TEAM = 6


async def _nba_player_picks(home, away, season, ratings, opp_stats, players, exp_pace, prop_markets=None):
    prop_markets = prop_markets or {}
    # Select the rotation (top by minutes) for both teams, then fetch all their
    # game logs concurrently (a semaphore keeps stats.nba.com from throttling).
    selected = []  # (team, opp, pid, player)
    for team, opp in ((home, away), (away, home)):
        roster = sorted(
            [(pid, p) for pid, p in players.items() if p["teamId"] == team["id"] and p["gp"] >= 5],
            key=lambda kp: kp[1]["min"], reverse=True)[:NBA_PLAYERS_PER_TEAM]
        for pid, p in roster:
            selected.append((team, opp, pid, p))

    sem = asyncio.Semaphore(6)

    async def fetch(pid):
        async with sem:
            try:
                return pid, await nba.get_player_gamelog(pid, season)
            except Exception:
                return pid, None

    logs = dict(await asyncio.gather(*[fetch(pid) for _, _, pid, _ in selected]))

    picks: List[Dict[str, Any]] = []
    for team, opp, pid, p in selected:
        glog = logs.get(pid)
        if not glog:
            continue
        team_pace = ratings.get("teams", {}).get(team["id"], {}).get("pace")
        for stat_key, label, noun, opp_key, std_floor, thresh in nba_analysis.PLAYER_PROP_SPECS:
            if p.get(stat_key, 0) < thresh:
                continue
            market = prop_markets.get(f"nba_{stat_key}", {}).get(odds.norm(p["name"]))
            pick = nba_analysis.analyze_nba_player_prop(
                player_name=p["name"], stat_key=stat_key, stat_label=label, stat_noun=noun,
                gamelog=glog, season_avg=p[stat_key],
                opp_allowed=opp_stats.get("teams", {}).get(opp["id"], {}).get(opp_key),
                league_allowed=opp_stats.get("league", {}).get(opp_key),
                opp_abbr=opp["abbr"], exp_pace=exp_pace, team_pace=team_pace, std_floor=std_floor,
                market=market)
            if pick is not None:
                picks.append(pick)

    # Cap per stat type so low-variance threes don't crowd out points/reb/ast,
    # then group by type for a readable board (points first).
    type_caps = {"nba_pts": 6, "nba_reb": 3, "nba_ast": 3, "nba_fg3m": 3}
    type_order = {"nba_pts": 0, "nba_reb": 1, "nba_ast": 2, "nba_fg3m": 3}
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for p in picks:
        by_type.setdefault(p["propType"], []).append(p)
    selected: List[Dict[str, Any]] = []
    for ptype, lst in by_type.items():
        lst.sort(key=lambda p: p["confidence"], reverse=True)
        selected.extend(lst[:type_caps.get(ptype, 3)])
    selected.sort(key=lambda p: (type_order.get(p["propType"], 9), -p["confidence"]))
    return selected[:NBA_PLAYER_PICK_CAP]


async def _analyze_mlb(game_pk: int, date: str, seasons: int = 4, ai: int = 0,
                        odds_key: Optional[str] = None, anthropic_key: Optional[str] = None,
                        props_override: Optional[str] = None) -> Dict[str, Any]:
    games = await mlb.get_schedule(date)
    game = next((g for g in games if g["gamePk"] == game_pk), None)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found for that date")

    season = int(date[:4])
    use_ai = bool(ai)
    props_on = odds.player_props_enabled(props_override)

    team_rates = await mlb.get_team_rates(season)
    run_prev = await mlb.get_team_run_prevention(season)

    home, away = game["home"], game["away"]

    # ---- weather (optional) -------------------------------------------------------------
    try:
        weather = await weather_module.get_weather(game["venue"], game["gameDate"])
    except Exception:
        weather = dict(weather_module.NEUTRAL)

    # ---- home-plate umpire (optional) ---------------------------------------------------
    # Assigned a few hours pre-game; unknown/unposted -> neutral factors downstream.
    try:
        ump_name = await mlb.get_umpire(game_pk)
        umpire = umpires.lookup(ump_name)
    except Exception:
        umpire = None

    # ---- bullpens (optional) ------------------------------------------------------------
    try:
        home_bullpen = await mlb.get_bullpen(home["id"], season)
    except Exception:
        home_bullpen = None
    try:
        away_bullpen = await mlb.get_bullpen(away["id"], season)
    except Exception:
        away_bullpen = None

    # ---- team recent form (rolling 15 games) --------------------------------------------
    try:
        home_recent_form = await mlb.get_team_recent_form(home["id"], season)
    except Exception:
        home_recent_form = None
    try:
        away_recent_form = await mlb.get_team_recent_form(away["id"], season)
    except Exception:
        away_recent_form = None

    # ---- live market (optional) -------------------------------------------------------
    # Network egress to The Odds API may be unavailable in some sandboxes; degrade to
    # "analysis only" rather than failing the whole request.
    market_event: Optional[Dict[str, Any]] = None
    total_market: Optional[Dict[str, Any]] = None
    k_props_by_pitcher: Dict[str, Dict[str, Any]] = {}
    odds_note: Optional[str] = None
    if odds.has_key(odds_key):
        try:
            c = odds.client()
            events = await odds.get_game_markets(c, odds_key)
            if not events:
                odds_note = "No upcoming MLB events returned from Odds API — the game may have already started or your quota is exhausted."
            else:
                market_event = odds.match_event(events, home["name"], away["name"])
                if market_event is None:
                    event_names = [f"{e.get('away_team')} @ {e.get('home_team')}" for e in events[:5]]
                    odds_note = f"Game not found in Odds API ({len(events)} events available). First 5: {', '.join(event_names) or 'none'}."
        except Exception as exc:
            market_event = None
            err = str(exc)
            if "401" in err or "Unauthorized" in err.lower():
                odds_note = "Odds API key rejected (401 Unauthorized) — check that the key is correct."
            elif "402" in err or "quota" in err.lower():
                odds_note = "Odds API quota exceeded — your monthly request limit may be exhausted."
            elif "429" in err:
                odds_note = "Odds API rate limit hit — too many requests in a short period."
            else:
                odds_note = f"Odds API request failed: {err[:120]}"

        if market_event:
            try:
                total_market = odds.game_total(market_event)
            except Exception:
                total_market = None

            if props_on:
                try:
                    k_props_by_pitcher = await odds.get_pitcher_strikeout_props(
                        c, market_event["id"], odds_key, enabled=True)
                except Exception:
                    k_props_by_pitcher = {}

    # ---- per-pitcher strikeout picks ---------------------------------------------------
    picks: List[Dict[str, Any]] = []
    matchups = [
        (home["probablePitcher"], away, True),   # home pitcher faces the away offense
        (away["probablePitcher"], home, False),  # away pitcher faces the home offense
    ]

    team_rates_by_season: Dict[int, Dict[str, Any]] = {season: team_rates}
    starter_ra9: Dict[str, Optional[float]] = {"home": None, "away": None}
    starter_h9: Dict[str, Optional[float]] = {"home": None, "away": None}

    pitchers_announced = any(p for p, _, _ in matchups)
    short_sample_pitchers = 0  # probable pitchers with < MIN_STARTS gamelog rows so far

    for pitcher, opponent, is_home in matchups:
        if not pitcher:
            continue

        gamelog = await mlb.get_pitcher_gamelog(pitcher["id"], season)
        if len(gamelog) < analysis.MIN_STARTS:
            short_sample_pitchers += 1
        if not gamelog:
            continue

        side_key = "home" if is_home else "away"
        # FIP-regressed forward estimate (less noisy than raw 8-start ERA) drives
        # the run-based markets: total, F5, NRFI, moneyline.
        starter_ra9[side_key] = analysis._starter_ra9_projection(gamelog)
        starter_h9[side_key] = analysis._pitcher_h9(gamelog)

        seasons_seen = {r["season"] for r in gamelog}
        for s in seasons_seen:
            if s not in team_rates_by_season and s != season:
                team_rates_by_season[s] = await mlb.get_team_rates(s)

        k_market = k_props_by_pitcher.get(odds.norm(pitcher["name"]))

        try:
            platoon_splits = await mlb.get_pitcher_platoon_splits(pitcher["id"], season)
        except Exception:
            platoon_splits = None
        try:
            opp_handedness = await mlb.get_team_handedness(opponent["id"], season)
        except Exception:
            opp_handedness = None
        try:
            opp_lineup = await mlb.get_lineup(game_pk, opponent["id"])
        except Exception:
            opp_lineup = None
        try:
            pitcher_skill = await savant.get_pitcher_skill(pitcher["id"], season)
        except Exception:
            pitcher_skill = None

        k_pick = analysis.analyze_strikeouts(
            pitcher_name=pitcher["name"],
            gamelog=gamelog,
            opponent_id=opponent["id"],
            opponent_name=opponent["name"],
            is_home=is_home,
            team_rates_by_season=team_rates_by_season,
            current_season=season,
            market=k_market,
            platoon_splits=platoon_splits,
            opp_handedness=opp_handedness,
            umpire=umpire,
            opp_lineup=opp_lineup,
            pitcher_skill=pitcher_skill,
        )
        if k_pick is not None:
            k_pick["narrative"] = await ai_module.generate_narrative(k_pick, use_ai, anthropic_key)
            picks.append(k_pick)

        # Walk picks suppressed: 1743-sample backtest showed MAE worse than naive (1.06 vs 1.03)
        # and Brier worse than base rate — walk count has too much game-to-game variance to model.
        # bb_pick = analysis.analyze_walks(...)

    # ---- game model ----------------------------------------------------------------------
    home_ml = away_ml = None
    if market_event:
        home_ml = odds.best_moneyline(market_event, home["name"])
        away_ml = odds.best_moneyline(market_event, away["name"])

    park_data = parks.get_park(game["venue"])

    game_model = analysis.game_model(
        _team_rates_or_default(team_rates, home["id"]),
        _team_rates_or_default(team_rates, away["id"]),
        _run_prevention_or_default(run_prev, home["id"]),
        _run_prevention_or_default(run_prev, away["id"]),
        home_starter_ra9=starter_ra9["home"],
        away_starter_ra9=starter_ra9["away"],
        home_bullpen=home_bullpen,
        away_bullpen=away_bullpen,
        home_moneyline=home_ml,
        away_moneyline=away_ml,
        home_recent_form=home_recent_form,
        away_recent_form=away_recent_form,
        umpire=umpire,
        park=park_data,
    )
    game_model["total"] = analysis.analyze_game_total(
        game_model["homeProjRuns"],
        game_model["awayProjRuns"],
        market=total_market,
        weather=weather,
        umpire=umpire,
        park=park_data,
    )
    # F5 and NRFI use the blended (recent-form-aware) RPG from game_model rather
    # than re-reading the raw season rate, so recent hot/cold streaks flow through.
    game_model["f5"] = analysis.analyze_f5(
        game_model["homeOffenseRPG"],
        game_model["awayOffenseRPG"],
        starter_ra9["home"],
        starter_ra9["away"],
        umpire=umpire,
        park=park_data,
    )
    game_model["nrfi"] = analysis.analyze_nrfi(
        game_model["homeOffenseRPG"],
        game_model["awayOffenseRPG"],
        starter_ra9["home"],
        starter_ra9["away"],
        umpire=umpire,
        park=park_data,
    )

    # ---- batter props (hits / total bases / HR) ----------------------------------------
    # Requires a posted lineup (we need to know who's batting). With player-prop
    # odds available we only grade batters with a matched line; otherwise we grade
    # the whole lineup as analysis-only. Either way the board is capped so a slate
    # of 18 hitters x 3 props doesn't bury the pitcher picks.
    batter_markets: Dict[str, Dict[str, Any]] = {}
    if market_event and props_on:
        for _, _, _, _, mkey, _, _, _ in BATTER_PROPS:
            try:
                batter_markets[mkey] = await odds.get_player_props(
                    odds.client(), market_event["id"], mkey, odds_key, enabled=True)
            except Exception:
                batter_markets[mkey] = {}

    hr_factor = parks.get_park(game["venue"]).get("hrFactor", 1.0)
    batter_candidates: List[Dict[str, Any]] = []
    sides = [
        (True, home, away.get("probablePitcher"), away["id"], starter_ra9["away"], starter_h9["away"]),
        (False, away, home.get("probablePitcher"), home["id"], starter_ra9["home"], starter_h9["home"]),
    ]
    any_lineup_found = False
    for is_home_bat, team, opp_pitcher, opp_team_id, opp_ra9, opp_h9 in sides:
        lineup_confirmed = True
        try:
            batters = await mlb.get_lineup_batters(game_pk, team["id"])
        except Exception:
            batters = None
        if not batters:
            # Lineup not posted yet — fall back to the team's last completed
            # game's batting order as a "projected" lineup so the board isn't
            # empty all morning.
            lineup_confirmed = False
            try:
                batters = await mlb.get_recent_lineup_batters(team["id"], date, season)
            except Exception:
                batters = None
        if not batters:
            continue
        any_lineup_found = True

        # H/9 is a more direct hit-suppression signal than RA9; fall back to RA9 only
        # when H/9 isn't available (pitcher gamelog too short to compute).
        opp_factor = (analysis.batter_opp_factor_h9(opp_h9) if opp_h9 is not None
                      else analysis.batter_opp_factor(opp_ra9))
        opp_pitcher_name = opp_pitcher["name"] if opp_pitcher else "TBD"

        # Pitcher hand — fetched once per side, cached a full day.
        opp_pitcher_hand: Optional[str] = None
        if opp_pitcher:
            try:
                opp_pitcher_hand = await mlb.get_pitcher_hand(opp_pitcher["id"])
            except Exception:
                pass

        for b in batters:
            specs = []
            for prop_type, stat_key, stat_label, stat_noun, mkey, park_fn, default_line, bern in BATTER_PROPS:
                mkt = batter_markets.get(mkey, {}).get(odds.norm(b["name"]))
                if props_on and not mkt:
                    continue  # with odds available, only grade posted lines
                specs.append((prop_type, stat_key, stat_label, stat_noun, mkt, park_fn, default_line, bern))
            if not specs:
                continue

            try:
                blog = await mlb.get_batter_gamelog(b["id"], season)
            except Exception:
                blog = None
            if not blog:
                continue

            batter_platoon: Optional[Dict[str, Any]] = None
            try:
                batter_platoon = await mlb.get_batter_platoon_splits(b["id"], season)
            except Exception:
                pass

            for prop_type, stat_key, stat_label, stat_noun, mkt, park_fn, default_line, bern in specs:
                bp = analysis.analyze_batter_prop(
                    prop_type=prop_type,
                    stat_key=stat_key,
                    stat_label=stat_label,
                    stat_noun=stat_noun,
                    batter_name=b["name"],
                    gamelog=blog,
                    opp_team_id=opp_team_id,
                    opp_pitcher_name=opp_pitcher_name,
                    is_home=is_home_bat,
                    market=mkt,
                    opp_factor=opp_factor,
                    park_factor=park_fn(hr_factor),
                    default_line=default_line,
                    bernoulli=bern,
                    batter_platoon=batter_platoon,
                    opp_pitcher_hand=opp_pitcher_hand,
                )
                if bp is not None:
                    bp["lineupConfirmed"] = lineup_confirmed
                    batter_candidates.append(bp)

    # Matched-market edges first (ranked by EV, no type cap so the best prices win).
    # Then analysis-only leans, capped per prop type so the board isn't 8 copies of
    # "Over 0.5 Hits" (hits always out-confidence TB/HR for a common event).
    market_picks = [p for p in batter_candidates if p.get("hasMarket") and p.get("edge")]
    analysis_picks = [p for p in batter_candidates if not (p.get("hasMarket") and p.get("edge"))]
    market_picks.sort(key=lambda p: p["edge"]["evPct"], reverse=True)
    analysis_picks.sort(key=lambda p: p["confidence"], reverse=True)

    per_type: Dict[str, int] = {}
    varied: List[Dict[str, Any]] = []
    for p in analysis_picks:
        if per_type.get(p["propType"], 0) >= BATTER_PER_TYPE_CAP:
            continue
        per_type[p["propType"]] = per_type.get(p["propType"], 0) + 1
        varied.append(p)

    for bp in (market_picks + varied)[:BATTER_PICK_CAP]:
        bp["narrative"] = await ai_module.generate_narrative(bp, use_ai, anthropic_key)
        picks.append(bp)

    pick_note = None
    if not picks:
        if not pitchers_announced:
            pick_note = "Probable pitchers haven't been announced for this game yet — check back closer to first pitch."
        elif short_sample_pitchers:
            pick_note = "The starting pitcher(s) don't have enough starts yet this season to grade strikeout/walk props."
        elif not any_lineup_found:
            pick_note = "No lineup data available yet (neither today's nor a recent game's) — check back closer to first pitch."
        else:
            pick_note = "Not enough data to grade this matchup yet."

    return {
        "gamePk": game_pk,
        "game": game,
        "seasons": seasons,
        "picks": picks,
        "pickNote": pick_note,
        "gameModel": game_model,
        "weather": weather,
        "umpire": umpire,
        "oddsNote": odds_note,
        "flags": _flags(use_ai, odds_key, anthropic_key, props_override=props_override),
    }


@app.on_event("shutdown")
async def shutdown() -> None:
    await mlb.close()
    await odds.close()
    await weather_module.close()
    await savant.close()
    await nba.close()
    await mma.close()


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
