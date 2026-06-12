"""THE MODEL.

Pure functions, no I/O — everything here takes plain dicts/lists (already
fetched by ``backend.mlb`` / ``backend.odds``) and returns plain dicts shaped
for the frontend. See CLAUDE.md for the tunable constants and the full pick
dict contract.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from . import odds

# --------------------------------------------------------------------------- tunables

PROJECTION_WINDOW = 10      # starts used for the baseline mean
OPP_FACTOR_FLOOR = 0.85     # clamp on (opponent K rate / league avg K rate)
OPP_FACTOR_CEIL = 1.15
TOP_BUCKET = 10             # top-N teams by K%/BB% rank counts as "elite" for splits
SHRINK_PSEUDO = 8           # pseudo-observations pulling small samples to 0.5
MIN_STARTS = 3              # fewer starts than this -> no pick
HOME_FIELD_EDGE = 0.03      # home win-prob bump applied after log5
PYTHAG_EXP = 1.83           # Pythagorean-expectation exponent

DEFAULT_RUNS_PER_GAME = 4.3


# --------------------------------------------------------------------------- Poisson helpers (no SciPy)

def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_cdf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def poisson_sf(k: int, lam: float) -> float:
    return 1.0 - poisson_cdf(k, lam)


def prob_over(line: float, lam: float) -> float:
    """P(X > line) for a half-integer line (e.g. 7.5)."""
    return poisson_sf(math.floor(line), lam)


def prob_under(line: float, lam: float) -> float:
    """P(X < line) for a half-integer line (e.g. 7.5)."""
    return poisson_cdf(math.floor(line), lam)


# --------------------------------------------------------------------------- small stats helpers

def _hit_rate(rows: List[Dict[str, Any]], hit_fn) -> Tuple[int, int, float]:
    n = len(rows)
    if n == 0:
        return 0, 0, 0.0
    hits = sum(1 for r in rows if hit_fn(r))
    return hits, n, hits / n


def _shrunk(hits: int, n: int, pseudo: float = SHRINK_PSEUDO, base: float = 0.5) -> float:
    """Shrink an observed rate toward ``base`` so small samples don't dominate."""
    return (hits + pseudo * base) / (n + pseudo)


def _streak(rows: List[Dict[str, Any]], hit_fn) -> int:
    """Length of the current hit/miss streak, ending at the most recent start.

    Positive = streak of hits, negative = streak of misses, 0 if no rows.
    """
    if not rows:
        return 0
    last = hit_fn(rows[-1])
    count = 0
    for r in reversed(rows):
        if hit_fn(r) == last:
            count += 1
        else:
            break
    return count if last else -count


def _opp_rank(row: Dict[str, Any], rates_by_season: Dict[int, Dict[str, Any]], key: str) -> Optional[int]:
    rates = rates_by_season.get(row["season"])
    if not rates:
        return None
    team = rates["teams"].get(row["opponentId"])
    if not team:
        return None
    return team.get(key)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# --------------------------------------------------------------------------- shared over/under helpers

def _select_line_and_prob(
    projection: float, market: Optional[Dict[str, Any]]
) -> Tuple[str, float, float]:
    """Pick a side + line + model probability for a Poisson(``projection``) count stat.

    With a live market line, grades that exact line. Without one, tests an over
    just below the projection and an under just above it, and keeps whichever
    side the model favors more strongly.
    """
    if market and market.get("line") is not None:
        line = float(market["line"])
        p_over = prob_over(line, projection)
        if p_over >= 0.5:
            return "over", line, p_over
        return "under", line, 1.0 - p_over

    center = max(round(projection), 0)
    over_line, under_line = center - 0.5, center + 0.5
    p_over = prob_over(over_line, projection)
    p_under = prob_under(under_line, projection)
    if p_over >= p_under:
        return "over", over_line, p_over
    return "under", under_line, p_under


def _build_edge(side: str, model_prob: float, market: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A vig-removed edge dict for ``side`` at ``market``'s line, or ``None`` without a market."""
    if not market or market.get("line") is None or "over" not in market or "under" not in market:
        return None

    price = market["over"] if side == "over" else market["under"]
    fair_over, fair_under = odds.devig_two(market["over"], market["under"])
    fair_prob = fair_over if side == "over" else fair_under

    return {
        "line": market["line"],
        "side": side,
        "price": price,
        "decimal": round(odds.american_to_decimal(price), 4),
        "modelProb": round(model_prob, 4),
        "marketProb": round(odds.implied_prob(price), 4),
        "fairProb": round(fair_prob, 4),
        "evPct": round(odds.ev_pct(model_prob, price), 2),
        "kellyPct": round(odds.kelly_pct(model_prob, price), 2),
    }


# --------------------------------------------------------------------------- strikeout prop

def analyze_strikeouts(
    pitcher_name: str,
    gamelog: List[Dict[str, Any]],
    opponent_id: int,
    opponent_name: str,
    is_home: bool,
    team_rates_by_season: Dict[int, Dict[str, Any]],
    current_season: int,
    market: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade a starter's strikeout prop. Returns ``None`` if there isn't enough history."""

    if len(gamelog) < MIN_STARTS:
        return None

    recent = gamelog[-PROJECTION_WINDOW:]
    baseline = sum(r["strikeOuts"] for r in recent) / len(recent)

    current_rates = team_rates_by_season.get(current_season, {})
    league_avg_k = current_rates.get("leagueAvgK", 0.225) or 0.225
    opp_team = current_rates.get("teams", {}).get(opponent_id, {})
    opp_k_rate = opp_team.get("kRate", league_avg_k)
    opp_factor = _clamp(opp_k_rate / league_avg_k, OPP_FACTOR_FLOOR, OPP_FACTOR_CEIL)

    projection = baseline * opp_factor
    side, line, model_prob = _select_line_and_prob(projection, market)

    def hit(row: Dict[str, Any]) -> bool:
        return row["strikeOuts"] > line if side == "over" else row["strikeOuts"] < line

    # ---- splits ---------------------------------------------------------------------
    splits: List[Dict[str, Any]] = []

    def add_split(label: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        hits, n, rate = _hit_rate(rows, hit)
        splits.append({"label": label, "hits": hits, "n": n, "rate": round(rate, 4), "thin": n < 6})

    add_split("All starts", gamelog)

    vs_opp = [r for r in gamelog if r["opponentId"] == opponent_id]
    add_split(f"vs {opponent_name}", vs_opp)

    add_split(f"Last {len(recent)} starts", recent)

    home_away = [r for r in gamelog if r["isHome"] == is_home]
    add_split("Home starts" if is_home else "Away starts", home_away)

    top_k_offenses = [
        r for r in gamelog
        if (rank := _opp_rank(r, team_rates_by_season, "kRank")) is not None and rank <= TOP_BUCKET
    ]
    add_split("vs top strikeout offenses", top_k_offenses)

    if side == "over":
        top_bb_offenses = [
            r for r in gamelog
            if (rank := _opp_rank(r, team_rates_by_season, "bbRank")) is not None and rank <= TOP_BUCKET
        ]
        add_split("vs top walk offenses", top_bb_offenses)

    streak = _streak(gamelog, hit)
    if streak != 0:
        kind = "hit" if streak > 0 else "miss"
        n_streak = abs(streak)
        plural = "es" if (n_streak != 1 and kind == "miss") else ("s" if n_streak != 1 else "")
        splits.append({
            "label": f"Current streak: {n_streak} {kind}{plural}",
            "hits": n_streak if streak > 0 else 0,
            "n": n_streak,
            "rate": 1.0 if streak > 0 else 0.0,
            "thin": n_streak < 6,
        })

    # ---- spark series for the scorecard chip -----------------------------------------
    spark = [
        {
            "date": r["date"],
            "opp": r.get("opponentName", "")[:3].upper() or "???",
            "k": r["strikeOuts"],
            "home": r["isHome"],
        }
        for r in recent
    ]

    # ---- confidence -------------------------------------------------------------------
    key_splits = [s for s in splits if s["n"] > 0]
    if key_splits:
        shrunk_avg = sum(_shrunk(s["hits"], s["n"]) for s in key_splits) / len(key_splits)
    else:
        shrunk_avg = 0.5
    blended = 0.5 * model_prob + 0.5 * shrunk_avg

    confidence = round(blended * 100)
    if len(gamelog) < PROJECTION_WINDOW:
        confidence = min(confidence, 70)
    confidence = int(_clamp(confidence, 0, 100))

    if confidence >= 75:
        tier = "Premium"
    elif confidence >= 60:
        tier = "Strong"
    else:
        tier = "Lean"

    # ---- edge (only with a live market) -----------------------------------------------
    edge = _build_edge(side, model_prob, market)

    side_label = "Over" if side == "over" else "Under"

    return {
        "propType": "strikeouts",
        "player": pitcher_name,
        "pick": f"{pitcher_name} {side_label} {line} K's",
        "side": side,
        "line": line,
        "projection": round(projection, 2),
        "modelProb": round(model_prob, 4),
        "confidence": confidence,
        "tier": tier,
        "splits": splits,
        "spark": spark,
        "edge": edge,
        "hasMarket": edge is not None,
        "lowSample": len(gamelog) < PROJECTION_WINDOW,
    }


# --------------------------------------------------------------------------- generic pitcher count prop

def analyze_pitcher_count_prop(
    prop_type: str,
    stat_key: str,
    stat_label: str,
    pitcher_name: str,
    gamelog: List[Dict[str, Any]],
    opponent_id: int,
    opponent_name: str,
    is_home: bool,
    team_rates_by_season: Dict[int, Dict[str, Any]],
    current_season: int,
    opp_rate_key: str,
    opp_rank_key: str,
    league_avg_key: str,
    market: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade a pitcher prop that's well-modeled as a Poisson count (walks, outs, etc.).

    Mirrors ``analyze_strikeouts`` but parameterized over which game-log stat,
    opponent rate, and league average to use for the projection.
    """

    if len(gamelog) < MIN_STARTS:
        return None

    recent = gamelog[-PROJECTION_WINDOW:]
    baseline = sum(r.get(stat_key, 0) for r in recent) / len(recent)

    current_rates = team_rates_by_season.get(current_season, {})
    league_avg = current_rates.get(league_avg_key, 0.085) or 0.085
    opp_team = current_rates.get("teams", {}).get(opponent_id, {})
    opp_rate = opp_team.get(opp_rate_key, league_avg)
    opp_factor = _clamp(opp_rate / league_avg, OPP_FACTOR_FLOOR, OPP_FACTOR_CEIL)

    projection = baseline * opp_factor
    side, line, model_prob = _select_line_and_prob(projection, market)

    def hit(row: Dict[str, Any]) -> bool:
        val = row.get(stat_key, 0)
        return val > line if side == "over" else val < line

    splits: List[Dict[str, Any]] = []

    def add_split(label: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        hits, n, rate = _hit_rate(rows, hit)
        splits.append({"label": label, "hits": hits, "n": n, "rate": round(rate, 4), "thin": n < 6})

    add_split("All starts", gamelog)

    vs_opp = [r for r in gamelog if r["opponentId"] == opponent_id]
    add_split(f"vs {opponent_name}", vs_opp)

    add_split(f"Last {len(recent)} starts", recent)

    home_away = [r for r in gamelog if r["isHome"] == is_home]
    add_split("Home starts" if is_home else "Away starts", home_away)

    top_offenses = [
        r for r in gamelog
        if (rank := _opp_rank(r, team_rates_by_season, opp_rank_key)) is not None and rank <= TOP_BUCKET
    ]
    add_split(f"vs top {stat_label.lower()}-prone offenses", top_offenses)

    streak = _streak(gamelog, hit)
    if streak != 0:
        kind = "hit" if streak > 0 else "miss"
        n_streak = abs(streak)
        plural = "es" if (n_streak != 1 and kind == "miss") else ("s" if n_streak != 1 else "")
        splits.append({
            "label": f"Current streak: {n_streak} {kind}{plural}",
            "hits": n_streak if streak > 0 else 0,
            "n": n_streak,
            "rate": 1.0 if streak > 0 else 0.0,
            "thin": n_streak < 6,
        })

    spark = [
        {
            "date": r["date"],
            "opp": r.get("opponentName", "")[:3].upper() or "???",
            "k": r.get(stat_key, 0),
            "home": r["isHome"],
        }
        for r in recent
    ]

    key_splits = [s for s in splits if s["n"] > 0]
    if key_splits:
        shrunk_avg = sum(_shrunk(s["hits"], s["n"]) for s in key_splits) / len(key_splits)
    else:
        shrunk_avg = 0.5
    blended = 0.5 * model_prob + 0.5 * shrunk_avg

    confidence = round(blended * 100)
    if len(gamelog) < PROJECTION_WINDOW:
        confidence = min(confidence, 70)
    confidence = int(_clamp(confidence, 0, 100))

    if confidence >= 75:
        tier = "Premium"
    elif confidence >= 60:
        tier = "Strong"
    else:
        tier = "Lean"

    edge = _build_edge(side, model_prob, market)
    side_label = "Over" if side == "over" else "Under"

    return {
        "propType": prop_type,
        "player": pitcher_name,
        "pick": f"{pitcher_name} {side_label} {line} {stat_label}",
        "side": side,
        "line": line,
        "projection": round(projection, 2),
        "modelProb": round(model_prob, 4),
        "confidence": confidence,
        "tier": tier,
        "splits": splits,
        "spark": spark,
        "edge": edge,
        "hasMarket": edge is not None,
        "lowSample": len(gamelog) < PROJECTION_WINDOW,
    }


def analyze_walks(
    pitcher_name: str,
    gamelog: List[Dict[str, Any]],
    opponent_id: int,
    opponent_name: str,
    is_home: bool,
    team_rates_by_season: Dict[int, Dict[str, Any]],
    current_season: int,
    market: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade a starter's walks-allowed prop."""
    return analyze_pitcher_count_prop(
        prop_type="walks",
        stat_key="baseOnBalls",
        stat_label="BB",
        pitcher_name=pitcher_name,
        gamelog=gamelog,
        opponent_id=opponent_id,
        opponent_name=opponent_name,
        is_home=is_home,
        team_rates_by_season=team_rates_by_season,
        current_season=current_season,
        opp_rate_key="bbRate",
        opp_rank_key="bbRank",
        league_avg_key="leagueAvgBB",
        market=market,
    )


# --------------------------------------------------------------------------- game total (runs)

def analyze_game_total(
    home_proj_runs: float,
    away_proj_runs: float,
    market: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grade the game's total-runs (over/under) market.

    Approximates total runs as Poisson around the combined team projections —
    a simplification (real run totals are over-dispersed), good enough to
    compare a projection to a market total.
    """
    projection = home_proj_runs + away_proj_runs
    side, line, model_prob = _select_line_and_prob(projection, market)
    edge = _build_edge(side, model_prob, market)
    side_label = "Over" if side == "over" else "Under"

    return {
        "market": "total",
        "pick": f"{side_label} {line} (Total Runs)",
        "side": side,
        "line": line,
        "projection": round(projection, 2),
        "modelProb": round(model_prob, 4),
        "edge": edge,
        "hasMarket": edge is not None,
    }


# --------------------------------------------------------------------------- game model

def game_model(
    home_rates: Dict[str, Any],
    away_rates: Dict[str, Any],
    home_run_prevention: Dict[str, Any],
    away_run_prevention: Dict[str, Any],
    home_moneyline: Optional[int] = None,
    away_moneyline: Optional[int] = None,
) -> Dict[str, Any]:
    """Pythagorean expectation + log5 + a small home-field bump."""

    def pyth(runs_for: float, runs_against: float) -> float:
        rf = max(runs_for, 0.1)
        ra = max(runs_against, 0.1)
        return rf ** PYTHAG_EXP / (rf ** PYTHAG_EXP + ra ** PYTHAG_EXP)

    home_rs = home_rates.get("runsPerGame", DEFAULT_RUNS_PER_GAME)
    away_rs = away_rates.get("runsPerGame", DEFAULT_RUNS_PER_GAME)
    home_ra = home_run_prevention.get("runsAllowedPerGame", DEFAULT_RUNS_PER_GAME)
    away_ra = away_run_prevention.get("runsAllowedPerGame", DEFAULT_RUNS_PER_GAME)

    p_home = pyth(home_rs, home_ra)
    p_away = pyth(away_rs, away_ra)

    denom = p_home + p_away - 2 * p_home * p_away
    log5 = (p_home / denom) if denom else 0.5

    home_win = _clamp(log5 + HOME_FIELD_EDGE, 0.01, 0.99)

    result: Dict[str, Any] = {
        "homeWinProb": round(home_win, 4),
        "awayWinProb": round(1 - home_win, 4),
        "homeProjRuns": round((home_rs + away_ra) / 2, 2),
        "awayProjRuns": round((away_rs + home_ra) / 2, 2),
    }

    if home_moneyline is not None and away_moneyline is not None:
        fair_home, fair_away = odds.devig_two(home_moneyline, away_moneyline)
        result["moneyline"] = {
            "home": {
                "price": home_moneyline,
                "marketProb": round(odds.implied_prob(home_moneyline), 4),
                "fairProb": round(fair_home, 4),
                "evPct": round(odds.ev_pct(home_win, home_moneyline), 2),
            },
            "away": {
                "price": away_moneyline,
                "marketProb": round(odds.implied_prob(away_moneyline), 4),
                "fairProb": round(fair_away, 4),
                "evPct": round(odds.ev_pct(1 - home_win, away_moneyline), 2),
            },
        }

    return result
