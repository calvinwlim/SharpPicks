"""THE MMA MODEL — fighter rate-stat differentials + finish hazard.

MMA has no possession structure; the predictive signal is each fighter's career
*rate* profile (striking volume/accuracy/defense, grappling, finishing power)
and how it matches the opponent's. From those we derive:

- **Winner** — a logistic on a composite skill differential (striking net,
  grappling, defense, durability, finishing, experience, reach, age). MMA is
  high-variance and the market is sharp, so win probs are clamped — this is a
  lean, not a lock.
- **Distance / method / round** — a per-fighter finish probability (own finish
  rate scaled by the opponent's durability), combined into P(goes the distance),
  a KO/Sub/Decision split, and a round-by-round distribution.
- **Significant strikes (each fighter + total)** — output blended with what the
  opponent absorbs, scaled by the expected fight length.
- **Takedowns** — takedown rate vs the opponent's takedown defense, over the
  expected length.

Every number is paired with a discrepancy *signal* so the user sees the edges.
Pure functions, no I/O.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .analysis import poisson_cdf

# --------------------------------------------------------------------------- league baselines / tunables

LG_SLPM = 3.9          # league-average significant strikes landed per minute
LG_STR_DEF = 0.55
LG_TD_DEF = 0.65
LG_FIN_PER_FIGHT = 0.22  # league-average finishes per fight (for durability scaling)
WIN_PROB_FLOOR, WIN_PROB_CEIL = 0.12, 0.88  # MMA upsets are common — don't overclaim
WIN_DIFF_SCALE = 6.0   # logistic scale on the skill differential (calibrated via mma_backtest.py)
SIG_STD_FRAC = 0.30    # std of a sig-strike projection as a fraction of the mean
FINISH_MID_FRAC = 0.45  # finishes land ~45% of the way through the scheduled time


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _age(dob: Optional[str], fight_date: Optional[str]) -> Optional[float]:
    if not dob or not fight_date:
        return None
    import datetime
    try:
        d = datetime.datetime.strptime(dob, "%b %d, %Y").date()
        f = datetime.date.fromisoformat(fight_date)
        return (f - d).days / 365.25
    except (ValueError, TypeError):
        return None


def _winpct(f: Dict[str, Any]) -> float:
    g = f.get("wins", 0) + f.get("losses", 0)
    return f["wins"] / g if g else 0.5


# --------------------------------------------------------------------------- finish / distance

def _finish_per_fight(f: Dict[str, Any]) -> float:
    """How often this fighter finishes an opponent, per fight."""
    fights = max(f.get("fights", 0), 1)
    return f.get("finishRate", 0.0) * f.get("wins", 0) / fights


def _finished_per_fight(f: Dict[str, Any]) -> float:
    """How often this fighter gets finished, per fight (durability; lower = tougher)."""
    fights = max(f.get("fights", 0), 1)
    return f.get("finishedRate", 0.0) * f.get("losses", 0) / fights


def _p_finish(att: Dict[str, Any], dfn: Dict[str, Any]) -> float:
    """P(``att`` finishes ``dfn`` in the fight): own finish rate scaled by how
    finishable the opponent has been."""
    ability = _finish_per_fight(att)
    vuln = _clamp(_finished_per_fight(dfn) / LG_FIN_PER_FIGHT, 0.55, 1.8)
    return _clamp(ability * vuln, 0.02, 0.85)


ROUND_FINISH_WEIGHTS = {
    3: [0.40, 0.34, 0.26],
    5: [0.27, 0.24, 0.20, 0.16, 0.13],
}


# --------------------------------------------------------------------------- significant strikes / takedowns

def _expected_minutes(distance_p: float, rounds: int) -> float:
    full = rounds * 5.0
    return distance_p * full + (1.0 - distance_p) * full * FINISH_MID_FRAC


def _sig_projection(att: Dict[str, Any], dfn: Dict[str, Any], minutes: float) -> float:
    """Expected significant strikes ``att`` lands: own output blended with what
    the opponent typically absorbs, over the fight's expected length."""
    rate = 0.5 * att.get("slpm", LG_SLPM) + 0.5 * dfn.get("sapm", LG_SLPM)
    return rate * minutes


def _td_projection(att: Dict[str, Any], dfn: Dict[str, Any], minutes: float) -> float:
    base = att.get("tdAvg", 0.0) / 15.0  # per minute
    opp_def = _clamp((1.0 - dfn.get("tdDef", LG_TD_DEF)) / (1.0 - LG_TD_DEF), 0.4, 1.8)
    return base * opp_def * minutes


# --------------------------------------------------------------------------- winner

def _skill_score(f: Dict[str, Any], opp: Dict[str, Any]) -> float:
    """A fighter's composite rating in this matchup (higher = better)."""
    striking_net = (f.get("slpm", 0) - f.get("sapm", 0))
    grappling = f.get("tdAvg", 0) * f.get("tdAcc", 0) + f.get("ctrlPerMin", 0) * 2.0 + f.get("subAvg", 0)
    defense = f.get("strDef", LG_STR_DEF) * 6.0 + f.get("tdDef", LG_TD_DEF) * 3.0
    finishing = f.get("finishRate", 0) * 2.0 + f.get("kdPer15", 0)
    return striking_net + grappling + defense + finishing


def _win_diff(a: Dict[str, Any], b: Dict[str, Any], a_age: Optional[float], b_age: Optional[float]) -> float:
    diff = _skill_score(a, b) - _skill_score(b, a)
    diff += (_winpct(a) - _winpct(b)) * 3.0
    diff += ((a.get("reachIn") or 0) - (b.get("reachIn") or 0)) * 0.05
    if a_age is not None and b_age is not None:
        diff += (b_age - a_age) * 0.06  # youth edge
    return diff


def _win_prob(a: Dict[str, Any], b: Dict[str, Any], a_age: Optional[float], b_age: Optional[float]) -> float:
    return _clamp(_logistic(_win_diff(a, b, a_age, b_age) / WIN_DIFF_SCALE), WIN_PROB_FLOOR, WIN_PROB_CEIL)


# --------------------------------------------------------------------------- pick helpers

def _count_prop(player: str, prop_type: str, noun: str, label: str, projection: float,
                std: float, signals: List[Dict[str, str]]) -> Dict[str, Any]:
    """Frame a counting prop (strikes/takedowns) at the line just below the
    projection as the action-side over, graded with a normal."""
    center = max(round(projection), 1)
    over_line, under_line = center - 0.5, center + 0.5
    p_over = 1.0 - normal_cdf((over_line - projection) / max(std, 1e-6))
    p_under = normal_cdf((under_line - projection) / max(std, 1e-6))
    side, line, prob = ("over", over_line, p_over) if p_over >= p_under else ("under", under_line, p_under)
    conf = int(_clamp(round(prob * 100), 0, 100))
    return {
        "propType": prop_type, "statNoun": noun, "player": player,
        "pick": f"{player} {'Over' if side == 'over' else 'Under'} {line} {label}",
        "side": side, "line": line, "projection": round(projection, 1),
        "modelProb": round(prob, 4), "confidence": conf,
        "tier": "Premium" if conf >= 75 else "Strong" if conf >= 60 else "Lean",
        "splits": [], "spark": [], "signals": signals,
        "edge": None, "hasMarket": False, "lowSample": False,
    }


def _sig(label: str, detail: str, lean: str) -> Dict[str, str]:
    return {"label": label, "detail": detail, "lean": lean}


# --------------------------------------------------------------------------- the model

def analyze_fight(
    a: Dict[str, Any], b: Dict[str, Any], a_name: str, b_name: str,
    rounds: int = 3, fight_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Full fight model + prop picks. ``a`` is treated as the first-listed corner."""
    a_age, b_age = _age(a.get("dob"), fight_date), _age(b.get("dob"), fight_date)

    # ---- winner ----
    win_diff = _win_diff(a, b, a_age, b_age)
    a_win = _win_prob(a, b, a_age, b_age)

    # ---- distance / method / rounds ----
    pa_fin = _p_finish(a, b)
    pb_fin = _p_finish(b, a)
    distance_p = (1.0 - pa_fin) * (1.0 - pb_fin)
    finish_p = 1.0 - distance_p
    # KO vs Sub split from both fighters' finishing tendencies.
    ko_weight = a.get("koRate", 0) * a_win + b.get("koRate", 0) * (1 - a_win) + 0.01
    sub_weight = a.get("subRate", 0) * a_win + b.get("subRate", 0) * (1 - a_win) + 0.01
    ks = ko_weight + sub_weight
    p_ko = finish_p * ko_weight / ks
    p_sub = finish_p * sub_weight / ks

    weights = ROUND_FINISH_WEIGHTS.get(rounds, ROUND_FINISH_WEIGHTS[3])
    round_probs = [round(finish_p * w, 4) for w in weights]
    round_probs_named = {f"R{i+1}": p for i, p in enumerate(round_probs)}
    round_probs_named["decision"] = round(distance_p, 4)

    minutes = _expected_minutes(distance_p, rounds)

    # ---- strikes / takedowns ----
    a_sig = _sig_projection(a, b, minutes)
    b_sig = _sig_projection(b, a, minutes)
    a_td = _td_projection(a, b, minutes)
    b_td = _td_projection(b, a, minutes)

    # ---- fight-level signals ----
    striking_net_a = a.get("slpm", 0) - a.get("sapm", 0)
    striking_net_b = b.get("slpm", 0) - b.get("sapm", 0)
    grap_a = a.get("tdAvg", 0) + a.get("ctrlPerMin", 0) * 5
    grap_b = b.get("tdAvg", 0) + b.get("ctrlPerMin", 0) * 5
    fav = "a" if a_win >= 0.5 else "b"
    signals = [
        _sig("Striking net", f"{a_name} {striking_net_a:+.1f} vs {b_name} {striking_net_b:+.1f} (landed-absorbed/min)",
             "a" if striking_net_a >= striking_net_b else "b"),
        _sig("Volume / accuracy", f"{a_name} {a.get('slpm',0):.1f} SLpM @ {a.get('strAcc',0)*100:.0f}% vs "
             f"{b_name} {b.get('slpm',0):.1f} @ {b.get('strAcc',0)*100:.0f}%",
             "a" if a.get("slpm", 0) >= b.get("slpm", 0) else "b"),
        _sig("Defense", f"{a_name} {a.get('strDef',0)*100:.0f}% str / {a.get('tdDef',0)*100:.0f}% TD def vs "
             f"{b_name} {b.get('strDef',0)*100:.0f}% / {b.get('tdDef',0)*100:.0f}%",
             "a" if (a.get("strDef", 0) + a.get("tdDef", 0)) >= (b.get("strDef", 0) + b.get("tdDef", 0)) else "b"),
        _sig("Grappling", f"{a_name} {grap_a:.1f} vs {b_name} {grap_b:.1f} (TD/15 + control)",
             "a" if grap_a >= grap_b else "b"),
        _sig("Finishing", f"{a_name} {a.get('finishRate',0)*100:.0f}% finish, {a.get('kdPer15',0):.1f} KD/15 vs "
             f"{b_name} {b.get('finishRate',0)*100:.0f}%, {b.get('kdPer15',0):.1f}",
             "a" if a.get("finishRate", 0) >= b.get("finishRate", 0) else "b"),
        _sig("Durability", f"{a_name} finished {a.get('finishedRate',0)*100:.0f}% of losses vs "
             f"{b_name} {b.get('finishedRate',0)*100:.0f}% (lower = tougher)",
             "a" if a.get("finishedRate", 1) <= b.get("finishedRate", 1) else "b"),
        _sig("Experience", f"{a_name} {a.get('wins',0)}-{a.get('losses',0)} vs {b_name} {b.get('wins',0)}-{b.get('losses',0)}",
             "a" if _winpct(a) >= _winpct(b) else "b"),
    ]
    if a.get("reachIn") and b.get("reachIn"):
        signals.append(_sig("Reach", f"{a_name} {a['reachIn']:.0f}\" vs {b_name} {b['reachIn']:.0f}\"",
                            "a" if a["reachIn"] >= b["reachIn"] else "b"))
    if a_age is not None and b_age is not None:
        signals.append(_sig("Age", f"{a_name} {a_age:.0f} vs {b_name} {b_age:.0f}",
                            "a" if a_age <= b_age else "b"))

    fight_model = {
        "aName": a_name, "bName": b_name, "rounds": rounds,
        "aWinProb": round(a_win, 4), "bWinProb": round(1 - a_win, 4),
        "winDiff": round(win_diff, 3),
        "distanceProb": round(distance_p, 4),
        "method": {"ko": round(p_ko, 4), "sub": round(p_sub, 4), "decision": round(distance_p, 4)},
        "roundProbs": round_probs_named,
        "expMinutes": round(minutes, 1),
        "projSigStrikes": {"a": round(a_sig, 1), "b": round(b_sig, 1), "total": round(a_sig + b_sig, 1)},
        "projTakedowns": {"a": round(a_td, 1), "b": round(b_td, 1)},
        "signals": signals,
    }

    # ---- prop picks (board) ----
    picks: List[Dict[str, Any]] = []

    # Distance / total rounds.
    dist_side = "over" if distance_p >= 0.5 else "under"
    rounds_line = rounds - 0.5
    conf = int(_clamp(round(max(distance_p, 1 - distance_p) * 100), 0, 100))
    picks.append({
        "propType": "mma_distance", "statNoun": "rounds", "player": f"{a_name} vs {b_name}",
        "pick": f"{'Over' if dist_side == 'over' else 'Under'} {rounds_line} Rounds "
                f"({'goes the distance' if dist_side == 'over' else 'finish'})",
        "side": dist_side, "line": rounds_line, "projection": round(minutes / 5.0, 1),
        "modelProb": round(max(distance_p, 1 - distance_p), 4), "confidence": conf,
        "tier": "Premium" if conf >= 75 else "Strong" if conf >= 60 else "Lean",
        "splits": [], "spark": [], "edge": None, "hasMarket": False, "lowSample": False,
        "signals": [
            _sig("Goes distance", f"{distance_p*100:.0f}% to reach decision", "over" if distance_p >= 0.5 else "under"),
            _sig("Finish threat", f"{a_name} {pa_fin*100:.0f}% / {b_name} {pb_fin*100:.0f}% to finish",
                 "under" if (pa_fin + pb_fin) > 0.5 else "over"),
            _sig("Method", f"KO {p_ko*100:.0f}% · Sub {p_sub*100:.0f}% · Dec {distance_p*100:.0f}%", "neutral"),
        ],
    })

    # Significant strikes (each fighter + total).
    sig_std = lambda proj: max(proj * SIG_STD_FRAC, 6.0)
    for nm, att, dfn, proj in ((a_name, a, b, a_sig), (b_name, b, a, b_sig)):
        s = [
            _sig("Output vs opp defense",
                 f"{nm} {att.get('slpm',0):.1f} SLpM vs opp {dfn.get('sapm',0):.1f} absorbed/min, {dfn.get('strDef',0)*100:.0f}% str def",
                 "over" if att.get("slpm", 0) >= LG_SLPM else "under"),
            _sig("Expected length", f"~{minutes:.0f} min ({distance_p*100:.0f}% distance)",
                 "over" if distance_p >= 0.5 else "under"),
        ]
        picks.append(_count_prop(nm, "mma_sigstr", "sig. strikes", "Sig. Strikes", proj, sig_std(proj), s))
    total_sig = a_sig + b_sig
    picks.append(_count_prop(f"{a_name} vs {b_name}", "mma_sigstr_total", "total sig. strikes",
                             "Total Sig. Strikes", total_sig, sig_std(total_sig), [
        _sig("Combined pace", f"{a_name} {a.get('slpm',0):.1f} + {b_name} {b.get('slpm',0):.1f} SLpM over ~{minutes:.0f} min", "neutral"),
    ]))

    # Takedowns (each fighter, only if a real grappling threat).
    for nm, att, dfn, proj in ((a_name, a, b, a_td), (b_name, b, a, b_td)):
        if att.get("tdAvg", 0) < 0.8:
            continue
        s = [_sig("TD rate vs defense",
                  f"{nm} {att.get('tdAvg',0):.1f} TD/15 @ {att.get('tdAcc',0)*100:.0f}% vs opp {dfn.get('tdDef',0)*100:.0f}% TD def",
                  "over" if att.get("tdAvg", 0) / 15 * 15 >= 1.0 else "under")]
        picks.append(_td_prop(nm, proj, s))

    return {"fightModel": fight_model, "picks": picks}


def _td_prop(player: str, projection: float, signals: List[Dict[str, str]]) -> Dict[str, Any]:
    """Takedowns prop graded as a Poisson over (low counts)."""
    from .analysis import prob_over
    line = max(round(projection), 1) - 0.5
    p_over = prob_over(line, projection)
    side, prob = ("over", p_over) if p_over >= 0.5 else ("under", 1 - p_over)
    conf = int(_clamp(round(prob * 100), 0, 100))
    return {
        "propType": "mma_td", "statNoun": "takedowns", "player": player,
        "pick": f"{player} {'Over' if side == 'over' else 'Under'} {line} Takedowns",
        "side": side, "line": line, "projection": round(projection, 1),
        "modelProb": round(prob, 4), "confidence": conf,
        "tier": "Premium" if conf >= 75 else "Strong" if conf >= 60 else "Lean",
        "splits": [], "spark": [], "signals": signals,
        "edge": None, "hasMarket": False, "lowSample": False,
    }
