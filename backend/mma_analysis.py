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

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .analysis import poisson_cdf

# --------------------------------------------------------------------------- league baselines / tunables

LG_SLPM = 3.9          # league-average significant strikes landed per minute
LG_STR_DEF = 0.55
LG_TD_DEF = 0.65
LG_FIN_PER_FIGHT = 0.22  # league-average finishes per fight (for durability scaling)
WIN_PROB_FLOOR, WIN_PROB_CEIL = 0.12, 0.88  # MMA upsets are common — don't overclaim
WIN_DIFF_SCALE = 6.0   # logistic scale on the hand-tuned differential (fallback when no learned model)
SIG_STD_FRAC = 0.30    # std of a sig-strike projection as a fraction of the mean
FINISH_MID_FRAC = 0.45  # finishes land ~45% of the way through the scheduled time
ENSEMBLE_COMP_WEIGHT = 0.0   # weight on the k-NN comps lens when blending the win prob.
                             # build_mma_comps._validate found the learned parametric model
                             # (Brier ~0.220) cleanly beats the comps lens (~0.240) and every
                             # nonzero blend weight is worse — so comps stay a *separate* lens
                             # (shown as aWinProbComps) rather than diluting the headline prob.
                             # Raise this only if a future comps build closes that gap.

# Learned winner model (coefficients fit by scripts/build_mma_winmodel.py on
# point-in-time bouts). When present we use it; otherwise the hand-tuned formula
# in _win_diff is the fallback, so the model degrades gracefully.
_WINMODEL_FILE = Path(__file__).resolve().parent / "data" / "ufc_winmodel.json"
try:
    _WINMODEL: Optional[Dict[str, Any]] = json.loads(_WINMODEL_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _WINMODEL = None


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
    """A fighter's composite rating in this matchup (higher = better).

    Used by the hand-tuned fallback and still surfaced in the signals.
    """
    striking_net = (f.get("slpm", 0) - f.get("sapm", 0))
    grappling = f.get("tdAvg", 0) * f.get("tdAcc", 0) + f.get("ctrlPerMin", 0) * 2.0 + f.get("subAvg", 0)
    defense = f.get("strDef", LG_STR_DEF) * 6.0 + f.get("tdDef", LG_TD_DEF) * 3.0
    finishing = f.get("finishRate", 0) * 2.0 + f.get("kdPer15", 0)
    return striking_net + grappling + defense + finishing


# Canonical learned-model feature order. scripts/build_mma_winmodel.py imports
# this and _win_features, so the trained coefficients always line up.
# NOTE: recent form (momentum) was tested as a learned feature but did not
# improve out-of-sample calibration (career rates already price it in), so it is
# surfaced as a UI signal only, not a probability input. See _momentum / signals.
WIN_FEATURE_NAMES = [
    "d_striking_net", "d_slpm", "d_strDef", "d_tdAvg", "d_tdDef", "d_ctrl",
    "d_sub", "d_kd", "d_finish", "d_durability", "d_winpct", "d_reach", "d_age",
    "d_age_cliff", "d_stance", "d_rust",
]

_SOUTHPAW, _ORTHODOX = "southpaw", "orthodox"


def _stance_edge(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """+1 when ``a`` is the southpaw vs an orthodox ``b`` (the known small edge),
    -1 in the reverse, 0 when stances match or are unknown/switch."""
    sa = (a.get("stance") or "").strip().lower()
    sb = (b.get("stance") or "").strip().lower()
    if sa == _SOUTHPAW and sb == _ORTHODOX:
        return 1.0
    if sa == _ORTHODOX and sb == _SOUTHPAW:
        return -1.0
    return 0.0


def _age_cliff(age: Optional[float]) -> float:
    """Years past 35 (the rough decline cliff); 0 below it or when unknown."""
    return max(age - 35.0, 0.0) if age is not None else 0.0


def _momentum(f: Dict[str, Any]) -> float:
    """Trajectory: recent (last-5) win rate minus career win rate. Positive = on
    the rise. 0 when no recent-form data (so it falls back to career)."""
    rwr = f.get("recentWinRate")
    return (rwr - _winpct(f)) if rwr is not None else 0.0


def rust_value(layoff_years: Optional[float]) -> float:
    """Ring-rust penalty input: years of layoff beyond 1, capped at 2."""
    if layoff_years is None:
        return 0.0
    return _clamp(layoff_years - 1.0, 0.0, 2.0)


def layoff_years(last_fight_date: Optional[str], fight_date: Optional[str]) -> Optional[float]:
    if not last_fight_date or not fight_date:
        return None
    import datetime
    try:
        d0 = datetime.date.fromisoformat(last_fight_date)
        d1 = datetime.date.fromisoformat(fight_date)
        return max((d1 - d0).days, 0) / 365.25
    except (ValueError, TypeError):
        return None


def _win_features(a: Dict[str, Any], b: Dict[str, Any],
                  a_age: Optional[float], b_age: Optional[float],
                  a_rust: float = 0.0, b_rust: float = 0.0) -> List[float]:
    """``a − b`` differentials, in WIN_FEATURE_NAMES order (each oriented so a
    higher value favours fighter ``a``)."""
    reach = ((a.get("reachIn") or 0) - (b.get("reachIn") or 0)) if (a.get("reachIn") and b.get("reachIn")) else 0.0
    age = (b_age - a_age) if (a_age is not None and b_age is not None) else 0.0
    return [
        (a.get("slpm", 0) - a.get("sapm", 0)) - (b.get("slpm", 0) - b.get("sapm", 0)),
        a.get("slpm", 0) - b.get("slpm", 0),
        a.get("strDef", LG_STR_DEF) - b.get("strDef", LG_STR_DEF),
        a.get("tdAvg", 0) - b.get("tdAvg", 0),
        a.get("tdDef", LG_TD_DEF) - b.get("tdDef", LG_TD_DEF),
        a.get("ctrlPerMin", 0) - b.get("ctrlPerMin", 0),
        a.get("subAvg", 0) - b.get("subAvg", 0),
        a.get("kdPer15", 0) - b.get("kdPer15", 0),
        a.get("finishRate", 0) - b.get("finishRate", 0),
        b.get("finishedRate", 0) - a.get("finishedRate", 0),  # durability: a tougher -> positive
        _winpct(a) - _winpct(b),
        reach,
        age,
        _age_cliff(b_age) - _age_cliff(a_age),  # a past the cliff -> negative
        _stance_edge(a, b),
        b_rust - a_rust,  # b rustier -> favours a
    ]


def _win_logit(a: Dict[str, Any], b: Dict[str, Any], a_age: Optional[float], b_age: Optional[float],
               a_rust: float = 0.0, b_rust: float = 0.0) -> float:
    """Logit for P(a beats b): learned coefficients when available, else the
    hand-tuned composite scaled by WIN_DIFF_SCALE."""
    if _WINMODEL:
        feats = _win_features(a, b, a_age, b_age, a_rust, b_rust)
        w = _WINMODEL["weights"]
        return _WINMODEL["intercept"] + sum(w[i] * feats[i] for i in range(len(w)))
    diff = _skill_score(a, b) - _skill_score(b, a)
    diff += (_winpct(a) - _winpct(b)) * 3.0
    diff += ((a.get("reachIn") or 0) - (b.get("reachIn") or 0)) * 0.05
    if a_age is not None and b_age is not None:
        diff += (b_age - a_age) * 0.06  # youth edge
    return diff / WIN_DIFF_SCALE


# Back-compat alias: ``winDiff`` in the fight model is the decision logit.
def _win_diff(a: Dict[str, Any], b: Dict[str, Any], a_age: Optional[float], b_age: Optional[float],
              a_rust: float = 0.0, b_rust: float = 0.0) -> float:
    return _win_logit(a, b, a_age, b_age, a_rust, b_rust)


def _win_prob(a: Dict[str, Any], b: Dict[str, Any], a_age: Optional[float], b_age: Optional[float],
              a_rust: float = 0.0, b_rust: float = 0.0) -> float:
    return _clamp(_logistic(_win_logit(a, b, a_age, b_age, a_rust, b_rust)), WIN_PROB_FLOOR, WIN_PROB_CEIL)


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
    comp_win_prob: Optional[float] = None,
) -> Dict[str, Any]:
    """Full fight model + prop picks. ``a`` is treated as the first-listed corner.

    ``comp_win_prob`` is P(a wins) from the historical k-NN comps lens; when
    supplied the reported win prob is an ensemble of the parametric model and the
    comps (two partly-decorrelated estimators usually calibrate better together).
    """
    a_age, b_age = _age(a.get("dob"), fight_date), _age(b.get("dob"), fight_date)
    a_layoff = layoff_years(a.get("lastFightDate"), fight_date)
    b_layoff = layoff_years(b.get("lastFightDate"), fight_date)
    a_rust, b_rust = rust_value(a_layoff), rust_value(b_layoff)

    # ---- winner (parametric model, optionally ensembled with the comps lens) ----
    win_diff = _win_diff(a, b, a_age, b_age, a_rust, b_rust)
    a_win_model = _win_prob(a, b, a_age, b_age, a_rust, b_rust)
    if comp_win_prob is not None:
        a_win = _clamp((1 - ENSEMBLE_COMP_WEIGHT) * a_win_model + ENSEMBLE_COMP_WEIGHT * comp_win_prob,
                       WIN_PROB_FLOOR, WIN_PROB_CEIL)
    else:
        a_win = a_win_model

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
        cliff = " (one past the ~35 decline)" if (_age_cliff(a_age) or _age_cliff(b_age)) else ""
        signals.append(_sig("Age", f"{a_name} {a_age:.0f} vs {b_name} {b_age:.0f}{cliff}",
                            "a" if a_age <= b_age else "b"))
    stance_edge = _stance_edge(a, b)
    if stance_edge:
        signals.append(_sig("Stance", f"{a_name} {a.get('stance')} vs {b_name} {b.get('stance')} "
                            f"(southpaw edge)", "a" if stance_edge > 0 else "b"))
    if (a_layoff and a_layoff >= 1.0) or (b_layoff and b_layoff >= 1.0):
        signals.append(_sig("Layoff", f"{a_name} {a_layoff or 0:.1f}y vs {b_name} {b_layoff or 0:.1f}y since last bout "
                            f"(ring rust)", "a" if a_rust <= b_rust else "b"))
    ma, mb = _momentum(a), _momentum(b)
    if (a.get("recentWinRate") is not None or b.get("recentWinRate") is not None) and abs(ma - mb) > 0.05:
        signals.append(_sig("Momentum", f"{a_name} {(a.get('recentWinRate') or _winpct(a))*100:.0f}% vs "
                            f"{b_name} {(b.get('recentWinRate') or _winpct(b))*100:.0f}% recent (last 5 vs career)",
                            "a" if ma >= mb else "b"))

    fight_model = {
        "aName": a_name, "bName": b_name, "rounds": rounds,
        "aWinProb": round(a_win, 4), "bWinProb": round(1 - a_win, 4),
        "aWinProbModel": round(a_win_model, 4),
        "aWinProbComps": round(comp_win_prob, 4) if comp_win_prob is not None else None,
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
