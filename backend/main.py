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


@app.get("/api/debug/mma")
async def debug_mma(date: str) -> Dict[str, Any]:
    """Return raw ESPN API response structure so we can diagnose parsing issues."""
    import datetime
    import httpx as _httpx
    d = datetime.date.fromisoformat(date)
    next_day = (d + datetime.timedelta(days=1)).isoformat()
    window = f"{(d - datetime.timedelta(days=3)):%Y%m%d}-{(d + datetime.timedelta(days=3)):%Y%m%d}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.espn.com/mma/",
        "Origin": "https://www.espn.com",
    }
    results = {}
    async with _httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as c:
        for label, params in [
            ("range", {"dates": window}),
            ("single", {"dates": date.replace("-", "")}),
            ("no_param", {}),
        ]:
            try:
                r = await c.get(mma.SCOREBOARD, params=params)
                raw = r.text[:800]
                try:
                    data = r.json()
                    events = data.get("events") or []
                    leagues = data.get("leagues") or []
                    league_events = leagues[0].get("events", []) if leagues else []
                    import json as _json
                    ev = events[0] if events else (league_events[0] if league_events else {})
                    comps = ev.get("competitions") or []
                    first_comp = comps[0] if comps else {}
                    first_comp_competitors = first_comp.get("competitors", [])
                    first_comp_competitor_sample = first_comp_competitors[0] if first_comp_competitors else {}
                    results[label] = {
                        "status": r.status_code, "top_keys": list(data.keys()),
                        "event_count": len(events), "league_event_count": len(league_events),
                        "sample_event_keys": list(ev.keys()),
                        "sample_date": ev.get("date"),
                        "competition_count": len(comps),
                        "first_comp_keys": list(first_comp.keys()) if first_comp else None,
                        "first_comp_competitor_count": len(first_comp_competitors),
                        "first_competitor_keys": list(first_comp_competitor_sample.keys()) if first_comp_competitor_sample else None,
                        "first_event_raw": _json.dumps(ev)[:1500] if ev else None,
                    }
                except Exception:
                    results[label] = {"status": r.status_code, "parse_error": True, "raw_preview": raw}
            except Exception as e:
                results[label] = {"fetch_error": str(e)}
    return {"window": window, "date": date, "next_day": next_day, "results": results}


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


# Serve the static frontend — must come after all API routes.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
