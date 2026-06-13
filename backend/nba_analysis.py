"""THE NBA MODEL — possession/efficiency based.

Basketball isn't a discrete-event game like baseball; the sound approach is the
Dean Oliver / power-rating standard: project each team's points from its
offensive rating vs the opponent's defensive rating (relative to league),
scaled by the expected pace (possessions). The margin maps to a win
probability through a normal distribution (NBA game margins have SD ~ 11.5).

Pure functions, no I/O — takes the dicts ``backend.nba`` fetched and returns a
plain dict for the frontend. Adjustments (home court, rest/back-to-back, recent
form) are modest and explained via ``signals`` so the user sees *why* the model
leans the way it does.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- tunables

NBA_HCA = 2.8              # home-court advantage in points (well-established ~2.5-3)
NBA_MARGIN_SD = 11.5       # std dev of NBA game margins -> win prob from the spread
NBA_TOTAL_SD = 15.0        # std dev of game totals -> over/under prob
NBA_B2B_PENALTY = 1.4      # points docked for playing on zero days' rest (back-to-back)
NBA_REST_BONUS = 0.5       # points for a long rest (4+ days)
NBA_RECENT_WEIGHT = 0.30   # weight on last-10 form vs full-season rating
DEFAULT_ORTG = 114.0
DEFAULT_PACE = 99.5


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _rest_adj(gap_days: Optional[int]) -> float:
    """Points adjustment from rest: penalize back-to-backs, small boost for long rest."""
    if gap_days is None:
        return 0.0
    if gap_days <= 1:
        return -NBA_B2B_PENALTY
    if gap_days >= 4:
        return NBA_REST_BONUS
    return 0.0


def _blend(season_val: Optional[float], recent_val: Optional[float], default: float) -> float:
    if season_val is None:
        return default
    if recent_val is None:
        return season_val
    return (1.0 - NBA_RECENT_WEIGHT) * season_val + NBA_RECENT_WEIGHT * recent_val


def _team_view(team_id: int, ratings: Dict[str, Any], recent: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Season rating blended with recent (last-N) form for one team."""
    lg_o = ratings.get("leagueOrtg", DEFAULT_ORTG)
    lg_p = ratings.get("leaguePace", DEFAULT_PACE)
    s = ratings.get("teams", {}).get(team_id, {})
    r = (recent or {}).get("teams", {}).get(team_id, {}) if recent else {}
    return {
        "ortg": _blend(s.get("ortg"), r.get("ortg"), lg_o),
        "drtg": _blend(s.get("drtg"), r.get("drtg"), lg_o),
        "pace": _blend(s.get("pace"), r.get("pace"), lg_p),
        "seasonNet": (s.get("ortg", lg_o) - s.get("drtg", lg_o)),
        "recentNet": ((r.get("ortg") - r.get("drtg")) if r.get("ortg") is not None else None),
        "name": s.get("name", ""),
    }


# --------------------------------------------------------------------------- signals

def _signal(label: str, detail: str, lean: str) -> Dict[str, str]:
    return {"label": label, "detail": detail, "lean": lean}


def _build_signals(
    home: Dict[str, Any], away: Dict[str, Any], hv: Dict[str, float], av: Dict[str, float],
    exp_pace: float, lg_pace: float, home_rest: Optional[int], away_rest: Optional[int],
    margin: float, market: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    fav = "home" if margin >= 0 else "away"
    signals: List[Dict[str, str]] = []

    # Net rating (season) — the headline team-strength gap.
    signals.append(_signal(
        "Net rating", f"{home['abbr']} {hv['seasonNet']:+.1f} vs {away['abbr']} {av['seasonNet']:+.1f} per 100",
        "home" if hv["seasonNet"] >= av["seasonNet"] else "away"))

    # Offense-vs-defense matchups (style edge): who attacks the weaker defense.
    home_matchup = hv["ortg"] - av["drtg"]
    away_matchup = av["ortg"] - hv["drtg"]
    signals.append(_signal(
        "Matchup edge",
        f"{home['abbr']} O {hv['ortg']:.1f} vs {away['abbr']} D {av['drtg']:.1f} "
        f"({home_matchup:+.1f}); {away['abbr']} O {av['ortg']:.1f} vs {home['abbr']} D {hv['drtg']:.1f} ({away_matchup:+.1f})",
        "home" if home_matchup >= away_matchup else "away"))

    # Recent form vs season (last-10 trend).
    for side, v, ab in (("home", hv, home["abbr"]), ("away", av, away["abbr"])):
        if v["recentNet"] is not None:
            delta = v["recentNet"] - v["seasonNet"]
            if abs(delta) >= 1.5:
                signals.append(_signal(
                    f"{ab} form (L10)",
                    f"recent net {v['recentNet']:+.1f} vs season {v['seasonNet']:+.1f} ({delta:+.1f})",
                    side if delta > 0 else ("away" if side == "home" else "home")))

    # Pace -> total lean.
    pace_lean = "over" if exp_pace > lg_pace else "under"
    signals.append(_signal(
        "Pace", f"projected {exp_pace:.1f} poss vs league {lg_pace:.1f}", pace_lean))

    # Rest / back-to-backs.
    for side, rest, ab, opp_side in (("home", home_rest, home["abbr"], "away"),
                                     ("away", away_rest, away["abbr"], "home")):
        if rest is not None and rest <= 1:
            signals.append(_signal(f"{ab} rest", "on a back-to-back (0 days' rest)", opp_side))

    # Home court.
    signals.append(_signal("Home court", f"+{NBA_HCA:.1f} pts to {home['abbr']}", "home"))

    # Model vs market spread (only when a line is supplied).
    if market and market.get("spread") is not None:
        model_home_spread = -margin
        mkt = float(market["spread"])
        edge = mkt - model_home_spread  # >0 => model likes home more than the market does
        signals.append(_signal(
            "Model vs market spread",
            f"model {home['abbr']} {model_home_spread:+.1f} vs market {mkt:+.1f} ({edge:+.1f} pt edge)",
            "home" if edge > 0 else "away"))

    return signals


# --------------------------------------------------------------------------- game model

def nba_game_model(
    home: Dict[str, Any],
    away: Dict[str, Any],
    ratings: Dict[str, Any],
    recent: Optional[Dict[str, Any]] = None,
    home_rest: Optional[int] = None,
    away_rest: Optional[int] = None,
    market: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project score / spread / total / win probability for an NBA game."""
    lg_ortg = ratings.get("leagueOrtg", DEFAULT_ORTG)
    lg_pace = ratings.get("leaguePace", DEFAULT_PACE)

    hv = _team_view(home["id"], ratings, recent)
    av = _team_view(away["id"], ratings, recent)

    exp_pace = hv["pace"] * av["pace"] / lg_pace if lg_pace else (hv["pace"] + av["pace"]) / 2

    # Matchup efficiency: own offense vs opponent defense, relative to league.
    home_eff = hv["ortg"] * av["drtg"] / lg_ortg
    away_eff = av["ortg"] * hv["drtg"] / lg_ortg
    home_pts = home_eff * exp_pace / 100.0 + _rest_adj(home_rest) + NBA_HCA / 2.0
    away_pts = away_eff * exp_pace / 100.0 + _rest_adj(away_rest) - NBA_HCA / 2.0

    margin = home_pts - away_pts                 # >0 => home favored
    total = home_pts + away_pts
    home_win = normal_cdf(margin / NBA_MARGIN_SD)

    signals = _build_signals(home, away, hv, av, exp_pace, lg_pace, home_rest, away_rest, margin, market)

    result: Dict[str, Any] = {
        "homeWinProb": round(home_win, 4),
        "awayWinProb": round(1.0 - home_win, 4),
        "homeProjScore": round(home_pts, 1),
        "awayProjScore": round(away_pts, 1),
        "projMargin": round(margin, 1),
        "modelHomeSpread": round(-margin * 2) / 2.0,   # rounded to the nearest half-point
        "projTotal": round(total, 1),
        "pace": round(exp_pace, 1),
        "ratings": {
            "home": {"ortg": round(hv["ortg"], 1), "drtg": round(hv["drtg"], 1),
                     "net": round(hv["seasonNet"], 1), "pace": round(hv["pace"], 1)},
            "away": {"ortg": round(av["ortg"], 1), "drtg": round(av["drtg"], 1),
                     "net": round(av["seasonNet"], 1), "pace": round(av["pace"], 1)},
        },
        "rest": {"home": home_rest, "away": away_rest},
        "signals": signals,
    }

    # Spread / total cover probabilities (and EV when prices are supplied).
    if market and market.get("spread") is not None:
        hs = float(market["spread"])  # home spread, e.g. -5.5
        cover = normal_cdf((margin + hs) / NBA_MARGIN_SD)  # P(home covers -hs)
        side = "home" if cover >= 0.5 else "away"
        result["spread"] = {
            "line": hs, "side": side,
            "modelProb": round(cover if side == "home" else 1.0 - cover, 4),
        }
    if market and market.get("total") is not None:
        t = float(market["total"])
        p_over = 1.0 - normal_cdf((t - total) / NBA_TOTAL_SD)
        side = "over" if p_over >= 0.5 else "under"
        result["total"] = {
            "line": t, "side": side,
            "modelProb": round(p_over if side == "over" else 1.0 - p_over, 4),
        }

    return result
