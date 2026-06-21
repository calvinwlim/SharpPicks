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

from . import odds

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
    h2h: Optional[Dict[str, Any]] = None,
    home_split_net: Optional[float] = None,
    away_split_net: Optional[float] = None,
) -> Dict[str, Any]:
    """Project score / spread / total / win probability for an NBA game.

    ``h2h`` (this-season head-to-head record/margin), ``home_split_net`` (home
    team's net rating *at home*) and ``away_split_net`` (away team's net *on the
    road*) are surfaced as signals only — they're either small-sample or already
    captured by the flat home-court term, so they inform the reader without
    double-counting in the projection.
    """
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

    # Home/road venue splits (team-specific strength, beyond the flat home court).
    if home_split_net is not None:
        delta = home_split_net - hv["seasonNet"]
        signals.append(_signal(
            f"{home['abbr']} at home",
            f"{home_split_net:+.1f} net at home vs {hv['seasonNet']:+.1f} overall ({delta:+.1f})",
            "home" if delta >= 0 else "away"))
    if away_split_net is not None:
        delta = away_split_net - av["seasonNet"]
        signals.append(_signal(
            f"{away['abbr']} on the road",
            f"{away_split_net:+.1f} net on road vs {av['seasonNet']:+.1f} overall ({delta:+.1f})",
            "away" if delta >= 0 else "home"))

    # Head-to-head this season.
    if h2h and h2h.get("games"):
        n = h2h["games"]
        hw = h2h.get("homeWins", 0)
        margin_h = h2h.get("homeAvgMargin", 0.0)
        signals.append(_signal(
            "Head-to-head (season)",
            f"{home['abbr']} {hw}-{n - hw} vs {away['abbr']}, avg margin {margin_h:+.1f} ({n} mtg)",
            "home" if margin_h >= 0 else "away"))

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


# --------------------------------------------------------------------------- player props

NBA_PLAYER_WINDOW = 12        # recent games for a player's baseline/std
NBA_PLAYER_MIN_GAMES = 8
NBA_PLAYER_RECENT_WEIGHT = 0.40
NBA_OPP_FACTOR_FLOOR, NBA_OPP_FACTOR_CEIL = 0.85, 1.15
NBA_PACE_FACTOR_FLOOR, NBA_PACE_FACTOR_CEIL = 0.92, 1.08

# (statKey in gamelog, label, noun, opp-allowed key, std floor, min season avg to surface)
PLAYER_PROP_SPECS = [
    ("pts", "Points", "points", "pts", 4.0, 0.0),
    ("reb", "Rebounds", "rebounds", "reb", 1.8, 4.0),
    ("ast", "Assists", "assists", "ast", 1.5, 3.5),
    ("fg3m", "Threes", "threes", "fg3m", 0.9, 1.2),
]


def _stdev(vals: List[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def analyze_nba_player_prop(
    player_name: str,
    stat_key: str,
    stat_label: str,
    stat_noun: str,
    gamelog: List[Dict[str, Any]],
    season_avg: float,
    opp_allowed: Optional[float],
    league_allowed: Optional[float],
    opp_abbr: str,
    exp_pace: Optional[float],
    team_pace: Optional[float],
    std_floor: float,
    market: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade an NBA player counting prop (points/rebounds/assists/threes).

    Projection = season average blended with recent form, scaled by how much the
    opponent allows of this stat (relative to league) and the expected pace
    (more possessions -> more counting stats). Over/under via a normal with the
    player's own game-to-game std (floored). When ``market`` (a real book line +
    over/under prices) is supplied, the projection is graded against *that* line
    and a vig-removed EV/Kelly edge is attached; otherwise the line is centered on
    the projection (analysis only). Same pick-dict shape as MLB props.
    """
    if len(gamelog) < NBA_PLAYER_MIN_GAMES:
        return None

    recent = gamelog[-NBA_PLAYER_WINDOW:]
    recent_avg = sum(r.get(stat_key, 0.0) for r in recent) / len(recent)
    baseline = (1.0 - NBA_PLAYER_RECENT_WEIGHT) * season_avg + NBA_PLAYER_RECENT_WEIGHT * recent_avg

    opp_factor = 1.0
    if opp_allowed is not None and league_allowed:
        opp_factor = _clamp(opp_allowed / league_allowed, NBA_OPP_FACTOR_FLOOR, NBA_OPP_FACTOR_CEIL)
    pace_factor = 1.0
    if exp_pace and team_pace:
        pace_factor = _clamp(exp_pace / team_pace, NBA_PACE_FACTOR_FLOOR, NBA_PACE_FACTOR_CEIL)

    projection = baseline * opp_factor * pace_factor
    std = max(_stdev([r.get(stat_key, 0.0) for r in recent]), std_floor)

    edge: Optional[Dict[str, Any]] = None
    has_market = False
    if market and market.get("over") is not None and market.get("under") is not None and market.get("line") is not None:
        # Grade the real book line and attach a vig-removed EV/Kelly edge.
        line = float(market["line"])
        p_over = 1.0 - normal_cdf((line - projection) / std)
        p_under = 1.0 - p_over
        side, model_prob = ("over", p_over) if p_over >= p_under else ("under", p_under)
        price = market["over"] if side == "over" else market["under"]
        fair_over, fair_under = odds.devig_two(market["over"], market["under"])
        fair_prob = fair_over if side == "over" else fair_under
        edge = {
            "decimal": round(odds.american_to_decimal(price), 3), "price": price,
            "modelProb": round(model_prob, 4), "marketProb": round(odds.implied_prob(price), 4),
            "fairProb": round(fair_prob, 4), "evPct": round(odds.ev_pct(model_prob, price), 2),
            "kellyPct": round(odds.kelly_pct(model_prob, price), 2),
        }
        has_market = True
    else:
        # No line: center on the projection (analysis only).
        center = max(round(projection), 1)
        over_line, under_line = center - 0.5, center + 0.5
        p_over = 1.0 - normal_cdf((over_line - projection) / std)
        p_under = normal_cdf((under_line - projection) / std)
        if p_over >= p_under:
            side, line, model_prob = "over", over_line, p_over
        else:
            side, line, model_prob = "under", under_line, p_under

    # Splits.
    def hit(r: Dict[str, Any]) -> bool:
        v = r.get(stat_key, 0.0)
        return v > line if side == "over" else v < line

    def split(label: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        h = sum(1 for r in rows if hit(r))
        return {"label": label, "hits": h, "n": len(rows), "rate": round(h / len(rows), 4), "thin": len(rows) < 5}

    splits = [s for s in [
        split("All games", gamelog),
        split(f"Last {len(recent)}", recent),
        split(f"vs {opp_abbr}", [r for r in gamelog if r.get("opponent") == opp_abbr]),
    ] if s]

    spark = [{"date": r["date"], "opp": r.get("opponent", "")[:3].upper() or "???",
              "k": r.get(stat_key, 0.0), "home": r.get("isHome", False)} for r in recent]

    # Discrepancy signals.
    signals = [
        {"label": "Projection vs line", "detail": f"{projection:.1f} projected vs {line} line",
         "lean": "over" if projection > line else "under"},
        {"label": "Recent form", "detail": f"L{len(recent)} avg {recent_avg:.1f} vs season {season_avg:.1f}",
         "lean": "over" if recent_avg >= season_avg else "under"},
    ]
    if opp_allowed is not None and league_allowed:
        signals.append({
            "label": "Opponent defense",
            "detail": f"{opp_abbr} allows {opp_allowed:.1f} {stat_noun}/g vs league {league_allowed:.1f} (×{opp_factor:.2f})",
            "lean": "over" if opp_factor > 1.0 else "under"})
    if exp_pace and team_pace:
        signals.append({
            "label": "Pace", "detail": f"game pace {exp_pace:.1f} vs team {team_pace:.1f} (×{pace_factor:.2f})",
            "lean": "over" if pace_factor > 1.0 else "under"})

    low_sample = len(gamelog) < NBA_PLAYER_WINDOW
    confidence = int(_clamp(round(model_prob * 100), 0, 100))
    if low_sample:
        confidence = min(confidence, 70)
    tier = "Premium" if confidence >= 75 else "Strong" if confidence >= 60 else "Lean"
    side_label = "Over" if side == "over" else "Under"

    return {
        "propType": f"nba_{stat_key}",
        "statNoun": stat_noun,
        "player": player_name,
        "pick": f"{player_name} {side_label} {line} {stat_label}",
        "side": side, "line": line,
        "projection": round(projection, 1),
        "modelProb": round(model_prob, 4),
        "confidence": confidence, "tier": tier,
        "splits": splits, "spark": spark, "signals": signals,
        "edge": edge, "hasMarket": has_market, "lowSample": low_sample,
        "opponent": opp_abbr,
    }
