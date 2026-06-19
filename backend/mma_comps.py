"""MMA "comps" — case-based matching of a fight to its historical variants.

Styles make fights: rather than only producing a parametric projection, this
represents a matchup as a vector of *style differentials* (favorite minus
underdog) plus shared context (combined finish tendency, combined pace, rounds),
then finds the most similar past fights and reports how those actually turned
out — an empirical outcome distribution (favorite win %, KO/Sub/Dec split,
distance %, typical significant strikes) plus the named most-similar bouts.

The historical vectors are built point-in-time (each fight uses the two
fighters' stats *before* it) by ``scripts/build_mma_comps.py`` ->
``backend/data/ufc_fight_vectors.json``. This module builds the query vector the
same way and does the k-NN match. Pure Python (no numpy).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mma_analysis import _age, _winpct, weight_lbs

VECTORS_FILE = Path(__file__).resolve().parent / "data" / "ufc_fight_vectors.json"

# Feature vector = absolute STYLE descriptors (what kind of fight) + GAP
# descriptors (how lopsided). Style is weighted far higher so comps are
# stylistically similar first; the gap still informs the favorite win %.
FEATURE_NAMES = [
    # --- style (absolute, order-invariant) ---
    "weight",        # division size (lbs) — a heavyweight slugfest != a flyweight match
    "c_volume",      # combined SLpM (high-output vs low-output fight)
    "c_power",       # combined knockdowns/15 (KO-prone)
    "c_grappling",   # combined takedowns/15 (wrestling-heavy)
    "c_control",     # combined control time/min (grind)
    "c_sub",         # combined sub attempts/15 (submission threat)
    "c_finish",      # combined finish rate (does this style finish?)
    "c_strDef",      # combined striking defense (technical vs sloppy)
    "c_durability",  # combined finished-loss rate (how finishable)
    "rounds",        # 3 vs 5
    # --- gap (favorite minus underdog) ---
    "d_winpct", "d_slpm", "d_strDef", "d_tdAvg", "d_kdPer15", "d_finishRate", "d_reach", "d_age",
]

# Weighted Euclidean: style dimensions dominate so we match the *kind* of fight,
# then the gap breaks ties / drives the win %.
FEATURE_WEIGHTS = [
    3.0, 1.6, 1.6, 1.6, 1.1, 1.1, 1.4, 1.1, 1.2, 0.8,        # style
    0.5, 0.5, 0.4, 0.5, 0.5, 0.5, 0.4, 0.4,                  # gap
]

def build_vector(a: Dict[str, Any], b: Dict[str, Any], rounds: int,
                 fight_date: Optional[str] = None) -> Tuple[List[float], bool]:
    """Matchup feature vector. Style features are symmetric; gap features are
    oriented favorite-minus-underdog (favorite = higher win%). Returns
    ``(vector, fav_is_a)``."""
    fav_is_a = _winpct(a) >= _winpct(b)
    fav, dog = (a, b) if fav_is_a else (b, a)
    fa, da = _age(fav.get("dob"), fight_date), _age(dog.get("dob"), fight_date)
    d_age = (fa - da) if (fa is not None and da is not None) else 0.0

    def g(f, k):
        return float(f.get(k, 0.0) or 0.0)

    weight = (weight_lbs(a.get("weightClass")) + weight_lbs(b.get("weightClass"))) / 2.0
    vec = [
        # style (absolute)
        weight,
        g(a, "slpm") + g(b, "slpm"),
        g(a, "kdPer15") + g(b, "kdPer15"),
        g(a, "tdAvg") + g(b, "tdAvg"),
        g(a, "ctrlPerMin") + g(b, "ctrlPerMin"),
        g(a, "subAvg") + g(b, "subAvg"),
        g(a, "finishRate") + g(b, "finishRate"),
        g(a, "strDef") + g(b, "strDef"),
        g(a, "finishedRate") + g(b, "finishedRate"),
        float(rounds),
        # gap (favorite - underdog)
        _winpct(fav) - _winpct(dog),
        g(fav, "slpm") - g(dog, "slpm"),
        g(fav, "strDef") - g(dog, "strDef"),
        g(fav, "tdAvg") - g(dog, "tdAvg"),
        g(fav, "kdPer15") - g(dog, "kdPer15"),
        g(fav, "finishRate") - g(dog, "finishRate"),
        (fav.get("reachIn") or 0.0) - (dog.get("reachIn") or 0.0),
        d_age,
    ]
    return vec, fav_is_a


_cache: Optional[Dict[str, Any]] = None


def _load() -> Optional[Dict[str, Any]]:
    global _cache
    if _cache is None:
        try:
            data = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
            mean, std = data["mean"], data["std"]
            # pre-standardize the historical vectors once
            for row in data["vectors"]:
                row["z"] = [(row["vec"][i] - mean[i]) / std[i] for i in range(len(mean))]
            _cache = data
        except Exception:
            _cache = {}
    return _cache or None


def available() -> bool:
    return _load() is not None


def comp_win_prob_for(comps: Optional[Dict[str, Any]], a_name: str) -> Optional[float]:
    """P(``a_name`` wins) from a ``find_comps`` result, oriented to that fighter
    (the result stores the *favorite*'s win %); ``None`` if comps are unavailable."""
    if not comps or comps.get("favWinPct") is None:
        return None
    return comps["favWinPct"] if comps.get("favorite") == a_name else 1.0 - comps["favWinPct"]


def find_comps(a: Dict[str, Any], b: Dict[str, Any], a_name: str, b_name: str,
               rounds: int, fight_date: Optional[str] = None, k: int = 60) -> Optional[Dict[str, Any]]:
    data = _load()
    if not data:
        return None
    mean, std, rows = data["mean"], data["std"], data["vectors"]
    vec, fav_is_a = build_vector(a, b, rounds, fight_date)
    zq = [(vec[i] - mean[i]) / std[i] for i in range(len(mean))]
    w = FEATURE_WEIGHTS

    scored = sorted(
        ((sum(w[i] * (zq[i] - row["z"][i]) ** 2 for i in range(len(zq))), row) for row in rows),
        key=lambda x: x[0])[:k]
    if not scored:
        return None

    comps = [r for _, r in scored]
    n = len(comps)
    fav_won = sum(1 for c in comps if c["out"]["favWon"]) / n
    methods = {"ko": 0, "sub": 0, "dec": 0}
    for c in comps:
        m = c["out"]["method"]
        if m in methods:
            methods[m] += 1
    method_pct = {m: methods[m] / n for m in methods}
    distance_pct = sum(1 for c in comps if c["out"]["distance"]) / n
    avg_sig = sum(c["out"]["totalSig"] for c in comps) / n
    avg_round = sum(c["out"]["endRound"] for c in comps) / n

    fav_name, dog_name = (a_name, b_name) if fav_is_a else (b_name, a_name)

    def result_str(c):
        o = c["out"]
        who = "Fav" if o["favWon"] else "Dog"
        how = {"ko": "KO/TKO", "sub": "Sub", "dec": "Dec"}.get(o["method"], o["method"])
        return f"{who} by {how} R{o['endRound']}"

    similar = [{
        "fav": c["meta"]["fav"], "dog": c["meta"]["dog"], "event": c["meta"]["event"],
        "date": c["meta"]["date"], "result": result_str(c), "dist": round(d ** 0.5, 2),
    } for d, c in scored[:6]]

    return {
        "favorite": fav_name, "underdog": dog_name, "n": n,
        "favWinPct": round(fav_won, 3),
        "method": {m: round(v, 3) for m, v in method_pct.items()},
        "distancePct": round(distance_pct, 3),
        "avgSigStrikes": round(avg_sig, 1),
        "avgEndRound": round(avg_round, 1),
        "similar": similar,
    }
