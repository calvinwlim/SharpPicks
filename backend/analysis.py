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

PLATOON_FACTOR_FLOOR = 0.95   # clamp on the platoon adjustment to a pitcher's projection
PLATOON_FACTOR_CEIL = 1.05
PLATOON_MIN_BF = 20           # minimum batters-faced per split to trust it

WEATHER_TEMP_RUNS_PER_DEGREE = 0.0015  # warmer air -> ball carries -> more runs
WEATHER_RUN_FACTOR_FLOOR = 0.92
WEATHER_RUN_FACTOR_CEIL = 1.08
WEATHER_BASELINE_TEMP_F = 70.0

# ---- Tier 1 signals (umpire, lineup, pitcher skill, bullpen) ------------------
# All four are optional: when the upstream fetch fails or returns nothing the
# factor collapses to a neutral 1.0 (or the projection falls back to the
# results-only baseline), so the model degrades gracefully exactly like weather
# and odds do.

UMP_K_FACTOR_FLOOR = 0.92      # home-plate ump zone size scales called strikeouts
UMP_K_FACTOR_CEIL = 1.08
UMP_BB_FACTOR_FLOOR = 0.90     # ... and walks the other way (wide zone -> fewer BB)
UMP_BB_FACTOR_CEIL = 1.12
UMP_RUN_FACTOR_FLOOR = 0.95    # ... and the run environment (tight zone -> more runs)
UMP_RUN_FACTOR_CEIL = 1.05

SKILL_BLEND_WEIGHT = 0.35      # weight on the skill (season-rate) projection vs recent results
SKILL_MIN_BF = 10             # need at least this many recent BF to trust expected-BF

BULLPEN_INNINGS_SHARE = 0.33   # ~3 of 9 innings are thrown by the bullpen
BULLPEN_LEAGUE_ERA = 4.05      # league-average bullpen ERA, the neutral reference
BULLPEN_RUN_FACTOR_FLOOR = 0.94
BULLPEN_RUN_FACTOR_CEIL = 1.08
BULLPEN_FATIGUE_BUMP = 0.04    # extra run-factor nudge when a pen is gassed

# ---- Tier 2 signals (park factor, wind direction) ----------------------------
PARK_RUN_FACTOR_FLOOR = 0.90   # safety clamp on the venue's run park factor
PARK_RUN_FACTOR_CEIL = 1.18
WIND_RUNS_PER_MPH = 0.006      # each mph of "out" wind nudges the run total ~0.6%
WIND_RUN_FACTOR_FLOOR = 0.94
WIND_RUN_FACTOR_CEIL = 1.06


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


# --------------------------------------------------------------------------- platoon adjustment

def _platoon_factor(
    platoon_splits: Optional[Dict[str, Any]], opp_handedness: Optional[Dict[str, Any]]
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """How much to scale a projection given the pitcher's K rate vs LHB/RHB and the
    opponent's batting-handedness mix. Returns ``(factor, info)``; ``info`` is
    ``None`` when there isn't enough data to bother.
    """
    if not platoon_splits or not opp_handedness:
        return 1.0, None

    vl = platoon_splits.get("vsLHB")
    vr = platoon_splits.get("vsRHB")
    if not vl or not vr or vl.get("bf", 0) < PLATOON_MIN_BF or vr.get("bf", 0) < PLATOON_MIN_BF:
        return 1.0, None

    total_bf = vl["bf"] + vr["bf"]
    overall_rate = (vl["k"] + vr["k"]) / total_bf if total_bf else 0.0
    if overall_rate <= 0:
        return 1.0, None

    weighted_rate = opp_handedness["lhbPct"] * vl["kRate"] + opp_handedness["rhbPct"] * vr["kRate"]
    factor = _clamp(weighted_rate / overall_rate, PLATOON_FACTOR_FLOOR, PLATOON_FACTOR_CEIL)

    info = {
        "vsLHB": round(vl["kRate"], 4),
        "vsRHB": round(vr["kRate"], 4),
        "oppLHBPct": round(opp_handedness["lhbPct"], 3),
        "factor": round(factor, 4),
    }
    return factor, info


# --------------------------------------------------------------------------- umpire adjustment

def _umpire_factor(umpire: Optional[Dict[str, Any]], kind: str) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Scale a projection by the home-plate umpire's zone tendency.

    ``umpire`` is ``{"name", "kFactor", "bbFactor", "runFactor"}`` (see
    ``backend.umpires``); ``kind`` selects which of those to apply. A missing
    umpire, or one with no recorded tendency, yields a neutral ``1.0``.
    """
    if not umpire:
        return 1.0, None

    key = {"k": "kFactor", "bb": "bbFactor", "run": "runFactor"}.get(kind)
    if key is None:
        return 1.0, None
    raw = umpire.get(key)
    if raw is None:
        return 1.0, None

    bounds = {
        "k": (UMP_K_FACTOR_FLOOR, UMP_K_FACTOR_CEIL),
        "bb": (UMP_BB_FACTOR_FLOOR, UMP_BB_FACTOR_CEIL),
        "run": (UMP_RUN_FACTOR_FLOOR, UMP_RUN_FACTOR_CEIL),
    }[kind]
    factor = _clamp(float(raw), *bounds)
    info = {"name": umpire.get("name", "Umpire"), "kind": kind, "factor": round(factor, 4)}
    return factor, info


# --------------------------------------------------------------------------- opponent K-rate (lineup-aware)

def _opp_k_rate(
    opp_team: Dict[str, Any], opp_lineup: Optional[Dict[str, Any]], league_avg: float, rate_key: str = "kRate"
) -> Tuple[float, bool]:
    """Opponent strikeout (or walk) rate, preferring a confirmed lineup over team-season.

    Returns ``(rate, used_lineup)``. The lineup's PA-weighted rate is a much
    sharper read than the team-season rate (regulars rest, call-ups start), but
    we only trust it once the card is actually posted.
    """
    if opp_lineup and opp_lineup.get("confirmed") and opp_lineup.get(rate_key) is not None:
        return float(opp_lineup[rate_key]), True
    return opp_team.get(rate_key, league_avg), False


# --------------------------------------------------------------------------- pitcher-skill blend

def _skill_projection(
    baseline: float, recent: List[Dict[str, Any]], pitcher_skill: Optional[Dict[str, Any]]
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend a results-based baseline (recent-window mean) with a skill-based
    projection (season K-per-BF * expected batters faced).

    Season K rate stabilizes far faster than per-game K *counts*, so a pitcher
    with two unlucky low-K starts but a strong underlying rate isn't dragged
    down as hard. Returns ``(blended_mean, info)``; ``info`` is ``None`` when we
    have no usable skill data and the baseline passes through unchanged.
    """
    if not pitcher_skill or pitcher_skill.get("kPct") is None:
        return baseline, None

    bfs = [r.get("battersFaced", 0) for r in recent if r.get("battersFaced")]
    if not bfs or sum(bfs) < SKILL_MIN_BF:
        return baseline, None
    expected_bf = sum(bfs) / len(bfs)

    skill_mean = float(pitcher_skill["kPct"]) * expected_bf
    blended = (1.0 - SKILL_BLEND_WEIGHT) * baseline + SKILL_BLEND_WEIGHT * skill_mean

    info = {
        "kPct": round(float(pitcher_skill["kPct"]), 4),
        "expectedBF": round(expected_bf, 1),
        "skillProj": round(skill_mean, 2),
        "resultsProj": round(baseline, 2),
        "blended": round(blended, 2),
    }
    for k in ("swStrPct", "cswPct"):
        if pitcher_skill.get(k) is not None:
            info[k] = round(float(pitcher_skill[k]), 4)
    return blended, info


# --------------------------------------------------------------------------- bullpen run factor

def _bullpen_run_factor(bullpen: Optional[Dict[str, Any]]) -> float:
    """One team's bullpen multiplier on the runs it allows (>1 = weak/gassed pen)."""
    if not bullpen or bullpen.get("era") is None:
        return 1.0
    factor = _clamp(
        float(bullpen["era"]) / BULLPEN_LEAGUE_ERA,
        BULLPEN_RUN_FACTOR_FLOOR,
        BULLPEN_RUN_FACTOR_CEIL,
    )
    if bullpen.get("fatigued"):
        factor = _clamp(factor + BULLPEN_FATIGUE_BUMP, BULLPEN_RUN_FACTOR_FLOOR, BULLPEN_RUN_FACTOR_CEIL)
    return factor


def _combined_bullpen_factor(
    home_bullpen: Optional[Dict[str, Any]], away_bullpen: Optional[Dict[str, Any]]
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Total-runs multiplier from both bullpens, applied only to the ~1/3 of
    innings the pens actually throw."""
    hf = _bullpen_run_factor(home_bullpen)
    af = _bullpen_run_factor(away_bullpen)
    if hf == 1.0 and af == 1.0:
        return 1.0, None
    pen_factor = (hf + af) / 2.0
    # Only the bullpen share of the game moves; starters cover the rest.
    total_factor = (1.0 - BULLPEN_INNINGS_SHARE) + BULLPEN_INNINGS_SHARE * pen_factor
    info = {
        "homeFactor": round(hf, 4),
        "awayFactor": round(af, 4),
        "homeFatigued": bool((home_bullpen or {}).get("fatigued")),
        "awayFatigued": bool((away_bullpen or {}).get("fatigued")),
    }
    return total_factor, info


# --------------------------------------------------------------------------- park + wind factors

def _park_factor(park: Optional[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Venue run park factor (clamped), or neutral when unknown."""
    if not park or park.get("runFactor") is None:
        return 1.0, None
    factor = _clamp(float(park["runFactor"]), PARK_RUN_FACTOR_FLOOR, PARK_RUN_FACTOR_CEIL)
    if factor == 1.0:
        return 1.0, None
    return factor, {"venue": park.get("venue", ""), "factor": round(factor, 4)}


def _wind_factor(
    weather: Optional[Dict[str, Any]], park: Optional[Dict[str, Any]]
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Run multiplier from the wind blowing out to (or in from) center field.

    Needs both a live wind vector (outdoor, non-dome) and a known field
    orientation; missing either yields a neutral ``1.0``.
    """
    from . import parks  # local import keeps analysis import-light / dependency-free at top

    if not weather or weather.get("isDome") or not park:
        return 1.0, None
    wind_dir = weather.get("windDir")
    wind_mph = weather.get("windMph")
    cf_az = park.get("cfAzimuth")
    if wind_dir is None or wind_mph is None or cf_az is None:
        return 1.0, None

    out_mph = parks.wind_out_mph(float(wind_dir), float(wind_mph), float(cf_az))
    factor = _clamp(1.0 + out_mph * WIND_RUNS_PER_MPH, WIND_RUN_FACTOR_FLOOR, WIND_RUN_FACTOR_CEIL)
    if factor == 1.0:
        return 1.0, None
    return factor, {
        "outMph": round(out_mph, 1),
        "blowing": "out" if out_mph >= 0 else "in",
        "factor": round(factor, 4),
    }


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

    center = round(projection)
    if center <= 0:
        # Sub-1 mean (e.g. home runs): the only meaningful line is the "will it
        # happen" Over 0.5, reported at its true (low) probability — never a
        # nonsensical negative line or a trivial near-lock under.
        return "over", 0.5, prob_over(0.5, projection)
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
    platoon_splits: Optional[Dict[str, Any]] = None,
    opp_handedness: Optional[Dict[str, Any]] = None,
    umpire: Optional[Dict[str, Any]] = None,
    opp_lineup: Optional[Dict[str, Any]] = None,
    pitcher_skill: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade a starter's strikeout prop. Returns ``None`` if there isn't enough history."""

    if len(gamelog) < MIN_STARTS:
        return None

    recent = gamelog[-PROJECTION_WINDOW:]
    results_baseline = sum(r["strikeOuts"] for r in recent) / len(recent)
    baseline, skill_info = _skill_projection(results_baseline, recent, pitcher_skill)

    current_rates = team_rates_by_season.get(current_season, {})
    league_avg_k = current_rates.get("leagueAvgK", 0.225) or 0.225
    opp_team = current_rates.get("teams", {}).get(opponent_id, {})
    opp_k_rate, used_lineup = _opp_k_rate(opp_team, opp_lineup, league_avg_k, "kRate")
    opp_factor = _clamp(opp_k_rate / league_avg_k, OPP_FACTOR_FLOOR, OPP_FACTOR_CEIL)

    platoon_factor, platoon_info = _platoon_factor(platoon_splits, opp_handedness)
    ump_factor, ump_info = _umpire_factor(umpire, "k")

    projection = baseline * opp_factor * platoon_factor * ump_factor
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
        "statNoun": "strikeouts",
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
        "platoon": platoon_info,
        "umpire": ump_info,
        "skill": skill_info,
        "lineupConfirmed": used_lineup,
    }


# --------------------------------------------------------------------------- generic pitcher count prop

def analyze_pitcher_count_prop(
    prop_type: str,
    stat_key: str,
    stat_label: str,
    stat_noun: str,
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
    platoon_splits: Optional[Dict[str, Any]] = None,
    opp_handedness: Optional[Dict[str, Any]] = None,
    umpire: Optional[Dict[str, Any]] = None,
    ump_kind: str = "k",
    opp_lineup: Optional[Dict[str, Any]] = None,
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
    opp_rate, used_lineup = _opp_k_rate(opp_team, opp_lineup, league_avg, opp_rate_key)
    opp_factor = _clamp(opp_rate / league_avg, OPP_FACTOR_FLOOR, OPP_FACTOR_CEIL)

    platoon_factor, platoon_info = _platoon_factor(platoon_splits, opp_handedness)
    ump_factor, ump_info = _umpire_factor(umpire, ump_kind)

    projection = baseline * opp_factor * platoon_factor * ump_factor
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
        "statNoun": stat_noun,
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
        "platoon": platoon_info,
        "umpire": ump_info,
        "lineupConfirmed": used_lineup,
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
    platoon_splits: Optional[Dict[str, Any]] = None,
    opp_handedness: Optional[Dict[str, Any]] = None,
    umpire: Optional[Dict[str, Any]] = None,
    opp_lineup: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Grade a starter's walks-allowed prop."""
    return analyze_pitcher_count_prop(
        prop_type="walks",
        stat_key="baseOnBalls",
        stat_label="BB",
        stat_noun="walks",
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
        platoon_splits=platoon_splits,
        opp_handedness=opp_handedness,
        umpire=umpire,
        ump_kind="bb",
        opp_lineup=opp_lineup,
    )


# --------------------------------------------------------------------------- batter props (hits / TB / HR)

BATTER_WINDOW = 15            # recent games for a batter's baseline
BATTER_MIN_GAMES = 8          # fewer logged games than this -> no pick
BATTER_OPP_FACTOR_FLOOR = 0.90
BATTER_OPP_FACTOR_CEIL = 1.10


def batter_opp_factor(opp_starter_ra9: Optional[float]) -> float:
    """How hittable the opposing starter is: >1 inflates batter projections."""
    ra9 = opp_starter_ra9 if opp_starter_ra9 is not None else STARTER_RA9_DEFAULT
    return _clamp((ra9 / STARTER_RA9_DEFAULT) ** 0.5, BATTER_OPP_FACTOR_FLOOR, BATTER_OPP_FACTOR_CEIL)


def analyze_batter_prop(
    prop_type: str,
    stat_key: str,
    stat_label: str,
    stat_noun: str,
    batter_name: str,
    gamelog: List[Dict[str, Any]],
    opp_team_id: int,
    opp_pitcher_name: str,
    is_home: bool,
    market: Optional[Dict[str, Any]] = None,
    opp_factor: float = 1.0,
    park_factor: float = 1.0,
    default_line: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Grade a batter counting prop (hits / total bases / home runs) as a Poisson.

    Projection = recent-game baseline, scaled by how hittable the opposing
    starter is (``opp_factor``) and the park (``park_factor``, mainly for HR/TB).
    Same pick-dict shape as the pitcher props so the frontend renders it
    unchanged.

    With a live market line we grade that exact number. Without one we frame the
    *action side* — the Over on the prop's primary line (``default_line``: 0.5
    hits/HR, 1.5 TB) — at its true probability, rather than auto-flipping to a
    trivial near-lock under (almost every hitter is "under 1.5 hits").
    """
    if len(gamelog) < BATTER_MIN_GAMES:
        return None

    recent = gamelog[-BATTER_WINDOW:]
    baseline = sum(r.get(stat_key, 0) for r in recent) / len(recent)
    projection = baseline * opp_factor * park_factor

    if market and market.get("line") is not None:
        side, line, model_prob = _select_line_and_prob(projection, market)
    else:
        side, line, model_prob = "over", default_line, prob_over(default_line, projection)

    def hit(row: Dict[str, Any]) -> bool:
        val = row.get(stat_key, 0)
        return val > line if side == "over" else val < line

    splits: List[Dict[str, Any]] = []

    def add_split(label: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        hits, n, rate = _hit_rate(rows, hit)
        splits.append({"label": label, "hits": hits, "n": n, "rate": round(rate, 4), "thin": n < 6})

    add_split("All games", gamelog)
    add_split(f"Last {len(recent)} games", recent)
    vs_opp = [r for r in gamelog if r["opponentId"] == opp_team_id]
    add_split("vs this team", vs_opp)
    home_away = [r for r in gamelog if r["isHome"] == is_home]
    add_split("Home games" if is_home else "Away games", home_away)

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
    shrunk_avg = (
        sum(_shrunk(s["hits"], s["n"]) for s in key_splits) / len(key_splits) if key_splits else 0.5
    )
    blended = 0.5 * model_prob + 0.5 * shrunk_avg
    confidence = int(_clamp(round(blended * 100), 0, 100))
    low_sample = len(gamelog) < BATTER_WINDOW
    if low_sample:
        confidence = min(confidence, 70)

    tier = "Premium" if confidence >= 75 else "Strong" if confidence >= 60 else "Lean"
    edge = _build_edge(side, model_prob, market)
    side_label = "Over" if side == "over" else "Under"

    return {
        "propType": prop_type,
        "statNoun": stat_noun,
        "player": batter_name,
        "pick": f"{batter_name} {side_label} {line} {stat_label}",
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
        "lowSample": low_sample,
        "opponentPitcher": opp_pitcher_name,
    }


# --------------------------------------------------------------------------- game total (runs)

def analyze_game_total(
    home_proj_runs: float,
    away_proj_runs: float,
    market: Optional[Dict[str, Any]] = None,
    weather: Optional[Dict[str, Any]] = None,
    umpire: Optional[Dict[str, Any]] = None,
    home_bullpen: Optional[Dict[str, Any]] = None,
    away_bullpen: Optional[Dict[str, Any]] = None,
    park: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grade the game's total-runs (over/under) market.

    Approximates total runs as Poisson around the combined team projections —
    a simplification (real run totals are over-dispersed), good enough to
    compare a projection to a market total. Five environment factors nudge it,
    each neutral when its data is missing: temperature (warmer air -> the ball
    carries), the home-plate umpire's zone (tight zone -> more baserunners),
    bullpen quality/fatigue (applied only to the innings the pens throw), the
    venue's park factor, and the wind blowing out to / in from center field.
    """
    projection = home_proj_runs + away_proj_runs

    weather_factor = 1.0
    if weather and not weather.get("isDome") and weather.get("tempF") is not None:
        delta = weather["tempF"] - WEATHER_BASELINE_TEMP_F
        weather_factor = _clamp(
            1.0 + delta * WEATHER_TEMP_RUNS_PER_DEGREE,
            WEATHER_RUN_FACTOR_FLOOR,
            WEATHER_RUN_FACTOR_CEIL,
        )

    ump_factor, ump_info = _umpire_factor(umpire, "run")
    bullpen_factor, bullpen_info = _combined_bullpen_factor(home_bullpen, away_bullpen)
    park_factor, park_info = _park_factor(park)
    wind_factor, wind_info = _wind_factor(weather, park)

    projection *= weather_factor * ump_factor * bullpen_factor * park_factor * wind_factor

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
        "weatherFactor": round(weather_factor, 4),
        "umpFactor": round(ump_factor, 4),
        "umpire": ump_info,
        "bullpenFactor": round(bullpen_factor, 4),
        "bullpen": bullpen_info,
        "parkFactor": round(park_factor, 4),
        "park": park_info,
        "windFactor": round(wind_factor, 4),
        "wind": wind_info,
    }


# --------------------------------------------------------------------------- F5 + NRFI shared

F5_INNINGS = 5
LEAGUE_RUNS_REF = 4.3          # league-average runs per team per game (normalizer)
STARTER_RA9_DEFAULT = 4.1      # fallback / league-average starter runs allowed per 9
RA9_WINDOW = 8                 # recent starts used for a starter's RA/9
NRFI_LEAGUE_P_SCORE = 0.27     # league-average chance a given team scores in the 1st
NRFI_FACTOR_FLOOR = 0.55
NRFI_FACTOR_CEIL = 1.7
NRFI_P_FLOOR = 0.05
NRFI_P_CEIL = 0.60


def _starter_ra9(gamelog: List[Dict[str, Any]], window: int = RA9_WINDOW) -> Optional[float]:
    """A starter's recent runs-allowed per 9 IP, or ``None`` without usable data."""
    if not gamelog:
        return None
    recent = gamelog[-window:]
    er = sum(r.get("earnedRuns", 0) for r in recent)
    ip = sum(r.get("inningsPitched", 0.0) for r in recent)
    if ip <= 0:
        return None
    return 9.0 * er / ip


def _poisson_win_prob(lam_a: float, lam_b: float, max_runs: int = 18) -> Tuple[float, float, float]:
    """``(P(A>B), P(B>A), P(tie))`` for two independent Poisson run counts."""
    pa = [poisson_pmf(i, lam_a) for i in range(max_runs + 1)]
    pb = [poisson_pmf(j, lam_b) for j in range(max_runs + 1)]
    p_a = p_b = p_tie = 0.0
    for i in range(max_runs + 1):
        for j in range(max_runs + 1):
            p = pa[i] * pb[j]
            if i > j:
                p_a += p
            elif j > i:
                p_b += p
            else:
                p_tie += p
    return p_a, p_b, p_tie


def _half_inning_runs(offense_rpg: float, opp_starter_ra9: Optional[float]) -> float:
    """Expected runs per inning for a team: its scoring pace blended 50/50 with
    the opposing starter's runs-allowed pace."""
    ra9 = opp_starter_ra9 if opp_starter_ra9 is not None else STARTER_RA9_DEFAULT
    return 0.5 * (offense_rpg / 9.0) + 0.5 * (ra9 / 9.0)


# --------------------------------------------------------------------------- first 5 innings (F5)

def analyze_f5(
    home_rpg: float,
    away_rpg: float,
    home_starter_ra9: Optional[float],
    away_starter_ra9: Optional[float],
    market: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """First-5-innings total + win probabilities, driven by the two starters.

    The bullpen never enters, so F5 is essentially a starters-only game: each
    team's F5 runs blend its own offense with the *opposing starter's* recent
    runs-allowed rate, projected over five innings. The total is graded as a
    Poisson; the win probabilities come from the Skellam of the two run counts
    (ties are a real F5 outcome and reported alongside).
    """
    home_f5 = _half_inning_runs(home_rpg, away_starter_ra9) * F5_INNINGS
    away_f5 = _half_inning_runs(away_rpg, home_starter_ra9) * F5_INNINGS
    total = home_f5 + away_f5

    side, line, model_prob = _select_line_and_prob(total, market)
    edge = _build_edge(side, model_prob, market)
    side_label = "Over" if side == "over" else "Under"

    p_home, p_away, p_tie = _poisson_win_prob(home_f5, away_f5)

    return {
        "market": "f5",
        "pick": f"F5 {side_label} {line} (First 5 Runs)",
        "side": side,
        "line": line,
        "projection": round(total, 2),
        "modelProb": round(model_prob, 4),
        "homeRuns": round(home_f5, 2),
        "awayRuns": round(away_f5, 2),
        "homeWinProb": round(p_home, 4),
        "awayWinProb": round(p_away, 4),
        "tieProb": round(p_tie, 4),
        "edge": edge,
        "hasMarket": edge is not None,
    }


# --------------------------------------------------------------------------- NRFI / YRFI

def _p_score_first(offense_rpg: float, opp_starter_ra9: Optional[float]) -> float:
    """Probability a team plates a run in the first inning."""
    ra9 = opp_starter_ra9 if opp_starter_ra9 is not None else STARTER_RA9_DEFAULT
    offense_factor = offense_rpg / LEAGUE_RUNS_REF
    pitch_factor = ra9 / STARTER_RA9_DEFAULT
    factor = _clamp((offense_factor * pitch_factor) ** 0.5, NRFI_FACTOR_FLOOR, NRFI_FACTOR_CEIL)
    return _clamp(NRFI_LEAGUE_P_SCORE * factor, NRFI_P_FLOOR, NRFI_P_CEIL)


def analyze_nrfi(
    home_rpg: float,
    away_rpg: float,
    home_starter_ra9: Optional[float],
    away_starter_ra9: Optional[float],
    market: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """No-Runs-First-Inning vs Yes-Runs-First-Inning.

    Models each team's chance of scoring in the top/bottom of the first from its
    offense and the opposing starter's run rate (calibrated to the league NRFI
    baseline, since per-inning runs are too zero-inflated for a raw Poisson).
    NRFI is the joint no-score of both halves.
    """
    p_home = _p_score_first(home_rpg, away_starter_ra9)
    p_away = _p_score_first(away_rpg, home_starter_ra9)

    nrfi = (1.0 - p_home) * (1.0 - p_away)
    yrfi = 1.0 - nrfi
    side = "nrfi" if nrfi >= yrfi else "yrfi"
    model_prob = nrfi if side == "nrfi" else yrfi

    # A NRFI/YRFI market is a two-outcome book; reuse the over/under edge plumbing
    # by mapping nrfi->over, yrfi->under when a line is supplied.
    edge = None
    if market and "over" in market and "under" in market:
        edge = _build_edge("over" if side == "nrfi" else "under", model_prob,
                           {"line": market.get("line", 0.5), "over": market["over"], "under": market["under"]})

    return {
        "market": "nrfi",
        "pick": "NRFI (No Runs 1st Inning)" if side == "nrfi" else "YRFI (Run in 1st Inning)",
        "side": side,
        "nrfiProb": round(nrfi, 4),
        "yrfiProb": round(yrfi, 4),
        "pScoreHome": round(p_home, 4),
        "pScoreAway": round(p_away, 4),
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

    # log5: P(home beats away) = (pH - pH*pA) / (pH + pA - 2*pH*pA).
    denom = p_home + p_away - 2 * p_home * p_away
    log5 = (p_home * (1 - p_away) / denom) if denom else 0.5

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
                "modelProb": round(home_win, 4),
                "marketProb": round(odds.implied_prob(home_moneyline), 4),
                "fairProb": round(fair_home, 4),
                "evPct": round(odds.ev_pct(home_win, home_moneyline), 2),
                "kellyPct": round(odds.kelly_pct(home_win, home_moneyline), 2),
            },
            "away": {
                "price": away_moneyline,
                "modelProb": round(1 - home_win, 4),
                "marketProb": round(odds.implied_prob(away_moneyline), 4),
                "fairProb": round(fair_away, 4),
                "evPct": round(odds.ev_pct(1 - home_win, away_moneyline), 2),
                "kellyPct": round(odds.kelly_pct(1 - home_win, away_moneyline), 2),
            },
        }

    return result
