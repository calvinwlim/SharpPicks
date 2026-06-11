"""FastAPI app: HTTP endpoints + per-game orchestration.

See CLAUDE.md for the API contract. Data flows one direction:
``mlb``/``odds`` fetch -> ``analysis`` grades -> this module serializes JSON
-> ``frontend/app.js`` renders.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import ai as ai_module
from . import analysis, mlb, odds

load_dotenv()

app = FastAPI(title="Sharp Slate")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _flags(ai_requested: bool = False) -> Dict[str, Any]:
    return {
        "hasOdds": odds.has_key(),
        "playerProps": odds.player_props_enabled(),
        "hasAI": ai_requested and bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "flags": _flags()}


@app.get("/api/slate")
async def slate(date: str) -> Dict[str, Any]:
    games = await mlb.get_schedule(date)
    return {"date": date, "count": len(games), "games": games, "flags": _flags()}


def _team_rates_or_default(team_rates: Dict[str, Any], team_id: int) -> Dict[str, Any]:
    return team_rates.get("teams", {}).get(team_id, {"runsPerGame": analysis.DEFAULT_RUNS_PER_GAME})


def _run_prevention_or_default(run_prev: Dict[str, Any], team_id: int) -> Dict[str, Any]:
    return run_prev.get("teams", {}).get(team_id, {"runsAllowedPerGame": analysis.DEFAULT_RUNS_PER_GAME})


@app.get("/api/analyze/{game_pk}")
async def analyze(game_pk: int, date: str, seasons: int = 4, ai: int = 0) -> Dict[str, Any]:
    games = await mlb.get_schedule(date)
    game = next((g for g in games if g["gamePk"] == game_pk), None)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found for that date")

    season = int(date[:4])
    use_ai = bool(ai)

    team_rates = await mlb.get_team_rates(season)
    run_prev = await mlb.get_team_run_prevention(season)

    home, away = game["home"], game["away"]

    # ---- live market (optional) -------------------------------------------------------
    # Network egress to The Odds API may be unavailable in some sandboxes; degrade to
    # "analysis only" rather than failing the whole request.
    market_event: Optional[Dict[str, Any]] = None
    total_market: Optional[Dict[str, Any]] = None
    k_props_by_pitcher: Dict[str, Dict[str, Any]] = {}
    bb_props_by_pitcher: Dict[str, Dict[str, Any]] = {}
    if odds.has_key():
        try:
            c = odds.client()
            events = await odds.get_game_markets(c)
            market_event = odds.match_event(events, home["name"], away["name"])
            if market_event:
                total_market = odds.game_total(market_event)
                if odds.player_props_enabled():
                    k_props_by_pitcher = await odds.get_pitcher_strikeout_props(c, market_event["id"])
                    bb_props_by_pitcher = await odds.get_pitcher_walks_props(c, market_event["id"])
        except Exception:
            market_event = None
            total_market = None
            k_props_by_pitcher = {}
            bb_props_by_pitcher = {}

    # ---- per-pitcher strikeout picks ---------------------------------------------------
    picks: List[Dict[str, Any]] = []
    matchups = [
        (home["probablePitcher"], away, True),   # home pitcher faces the away offense
        (away["probablePitcher"], home, False),  # away pitcher faces the home offense
    ]

    team_rates_by_season: Dict[int, Dict[str, Any]] = {season: team_rates}

    for pitcher, opponent, is_home in matchups:
        if not pitcher:
            continue

        gamelog = await mlb.get_pitcher_gamelog(pitcher["id"], season)
        if not gamelog:
            continue

        seasons_seen = {r["season"] for r in gamelog}
        for s in seasons_seen:
            if s not in team_rates_by_season and s != season:
                team_rates_by_season[s] = await mlb.get_team_rates(s)

        k_market = k_props_by_pitcher.get(odds.norm(pitcher["name"]))
        bb_market = bb_props_by_pitcher.get(odds.norm(pitcher["name"]))

        k_pick = analysis.analyze_strikeouts(
            pitcher_name=pitcher["name"],
            gamelog=gamelog,
            opponent_id=opponent["id"],
            opponent_name=opponent["name"],
            is_home=is_home,
            team_rates_by_season=team_rates_by_season,
            current_season=season,
            market=k_market,
        )
        if k_pick is not None:
            k_pick["narrative"] = await ai_module.generate_narrative(k_pick, use_ai)
            picks.append(k_pick)

        bb_pick = analysis.analyze_walks(
            pitcher_name=pitcher["name"],
            gamelog=gamelog,
            opponent_id=opponent["id"],
            opponent_name=opponent["name"],
            is_home=is_home,
            team_rates_by_season=team_rates_by_season,
            current_season=season,
            market=bb_market,
        )
        if bb_pick is not None:
            bb_pick["narrative"] = await ai_module.generate_narrative(bb_pick, use_ai)
            picks.append(bb_pick)

    # ---- game model ----------------------------------------------------------------------
    home_ml = away_ml = None
    if market_event:
        home_ml = odds.best_moneyline(market_event, home["name"])
        away_ml = odds.best_moneyline(market_event, away["name"])

    game_model = analysis.game_model(
        _team_rates_or_default(team_rates, home["id"]),
        _team_rates_or_default(team_rates, away["id"]),
        _run_prevention_or_default(run_prev, home["id"]),
        _run_prevention_or_default(run_prev, away["id"]),
        home_moneyline=home_ml,
        away_moneyline=away_ml,
    )

    return {
        "gamePk": game_pk,
        "game": game,
        "seasons": seasons,
        "picks": picks,
        "gameModel": game_model,
        "flags": _flags(use_ai),
    }


@app.on_event("shutdown")
async def shutdown() -> None:
    await mlb.close()
    await odds.close()


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
