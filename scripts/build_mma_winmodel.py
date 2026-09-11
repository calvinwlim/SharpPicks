"""Fit the MMA winner model's weights from data instead of hand-tuning them.

The parametric winner in ``backend.mma_analysis`` historically used hand-picked
multipliers (striking ×1, defense ×6, finishing ×2, …). This script replays
every UFC bout point-in-time (each fighter's rate profile built only from bouts
*before* the fight — the same no-leakage replay as ``mma_backtest`` /
``build_mma_comps``), forms an ``a − b`` differential feature vector with the
actual winner as the label, and fits a plain logistic regression (pure Python,
no numpy). The learned coefficients are written to
``backend/data/ufc_winmodel.json`` and loaded by ``mma_analysis`` at runtime
(with the hand-tuned formula as a fallback if the file is absent).

Each bout is added in *both* orientations (a vs b and b vs a) so the fit is
antisymmetric and free of any first-corner bias. A temporal holdout (train on
older fights, score the recent ones) is printed so we know it generalizes.

    python scripts/build_mma_winmodel.py

Re-run after rebuilding the fighter dataset; then validate with mma_backtest.py.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fitlib as FL
import mma_backtest as B
from backend import mma_analysis as M

OUT = ROOT / "backend" / "data" / "ufc_winmodel.json"
L2 = 1.0       # ridge strength (holdout sweep showed it's ~irrelevant here)

# Features whose sign is not in doubt: landing more, defending better, controlling
# more and hitting harder cannot make you LESS likely to win. Under L2 with
# collinear inputs the unconstrained fit handed negative weights to d_slpm, d_ctrl
# and d_kd — which the UI then has to explain to a user as "more knockdowns favours
# your opponent". Constraining just these three is accuracy-neutral (holdout Brier
# +0.0003, 95% bootstrap CI [-0.0012, +0.0019] — indistinguishable from zero) and
# makes the per-signal contributions the frontend now renders actually faithful.
# Constraining ALL causally-positive features was tested and was worse (+0.0004
# Brier, -0.7% accuracy), so the constraint stays narrow: only what we display.
NONNEG_FEATURES = ("d_slpm", "d_ctrl", "d_kd")

# Feature order is owned by backend.mma_analysis (WIN_FEATURE_NAMES /
# _win_features) so the trained coefficients always line up with inference.
FEATURES = M.WIN_FEATURE_NAMES
features = M._win_features


def _logistic(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def fit_logistic(X: List[List[float]], y: List[float], l2: float = 1.0,
                 nonneg: Optional[List[int]] = None) -> Tuple[List[float], float]:
    """Ridge logistic fit -> (weights, intercept) in RAW feature space.

    Delegates to scripts/fitlib.py, which uses Newton/IRLS. This replaced 4000
    epochs of batch gradient descent: it reaches the actual optimum (rather than
    wherever a fixed step count landed) in under ten iterations, turning a
    multi-minute refit into a couple of seconds.
    """
    return FL.fit_logistic(X, y, l2=l2, nonneg=nonneg)


def _brier(preds, outs):
    return mean((p - o) ** 2 for p, o in zip(preds, outs))


def _chron_bouts(results, event_date):
    bouts = []
    for row in results:
        event, bout = row["EVENT"].strip(), row["BOUT"].strip()
        d = event_date.get(event)
        names = [n.strip() for n in bout.split(" vs. ")]
        if not d or len(names) != 2:
            continue
        outcome = (row.get("OUTCOME") or "").strip()
        winner = names[0] if outcome.startswith("W") else names[1] if outcome.startswith("L") else None
        if winner is None:
            continue
        rounds = 5 if "5 Rnd" in (row.get("TIME FORMAT") or "") else 3
        try:
            er = int(row.get("ROUND") or 0)
        except ValueError:
            er = 0
        bouts.append({"date": d, "event": event, "bout": bout, "names": names,
                      "winner": winner, "method": B.classify(row.get("METHOD", "")),
                      "endRound": max(er, 1), "rounds": rounds})
    bouts.sort(key=lambda x: x["date"])
    return bouts


def _collect(bouts, box, phys):
    """Replay point-in-time, returning (rows[(date, feats, a_won)])."""
    running: Dict[str, Dict[str, float]] = {}
    last_date: Dict[str, Any] = {}  # most recent prior bout date per fighter (for layoff)
    recent: Dict[str, List[int]] = {}  # last results (1=win) per fighter (for momentum)
    floss: Dict[str, List[int]] = {}  # last results (1=finished loss) per fighter (chin)
    sos: Dict[str, List[float]] = {}  # [sum(opp win% faced), count] per fighter (strength of schedule)
    stat_date: Dict[str, Any] = {}    # last bout added to the accumulator (for time-decay)
    rows: List[Tuple[str, List[float], float]] = []

    def rwr(name: str) -> Optional[float]:
        r = recent.get(name)
        return (sum(r[-5:]) / len(r[-5:])) if r else None

    def rfl(name: str) -> Optional[float]:
        r = floss.get(name)
        return (sum(r[-5:]) / len(r[-5:])) if r else None

    def winpct_acc(acc: Optional[Dict[str, float]]) -> float:
        if not acc:
            return 0.5
        g = acc["wins"] + acc["losses"]
        return acc["wins"] / g if g else 0.5

    def sos_for(name: str) -> float:
        s = sos.get(name)
        return s[0] / s[1] if s and s[1] else 0.5

    for bt in bouts:
        a, b = bt["names"]
        na, nb = B.norm(a), B.norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        if acc_a and acc_b and acc_a["fights"] >= B.MIN_PRIOR and acc_b["fights"] >= B.MIN_PRIOR and sa and sb:
            fa = B.rates(acc_a, phys.get(na, {}))
            fb = B.rates(acc_b, phys.get(nb, {}))
            fa["recentWinRate"], fb["recentWinRate"] = rwr(na), rwr(nb)
            fa["sos"], fb["sos"] = sos_for(na), sos_for(nb)
            fa["recentFinishLossRate"], fb["recentFinishLossRate"] = rfl(na), rfl(nb)
            ds = bt["date"].isoformat()
            aa = M._age(fa.get("dob"), ds)
            ab = M._age(fb.get("dob"), ds)
            ar = M.rust_value(M.layoff_years(last_date[na].isoformat() if na in last_date else None, ds))
            br = M.rust_value(M.layoff_years(last_date[nb].isoformat() if nb in last_date else None, ds))
            a_won = 1.0 if bt["winner"] == a else 0.0
            rows.append((ds, features(fa, fb, aa, ab, ar, br), a_won))
            rows.append((ds, features(fb, fa, ab, aa, br, ar), 1.0 - a_won))  # mirror

        last_date[na] = bt["date"]
        last_date[nb] = bt["date"]
        recent.setdefault(na, []).append(1 if bt["winner"] == a else 0)
        recent.setdefault(nb, []).append(1 if bt["winner"] == b else 0)
        for nm0, opp_nm in ((na, b), (nb, a)):
            floss.setdefault(nm0, []).append(1 if (bt["winner"] == opp_nm and bt["method"] in ("ko", "sub")) else 0)
        if sa and sb:  # advance accumulators (same pairing as the other builders)
            opp_q = {na: winpct_acc(acc_b), nb: winpct_acc(acc_a)}  # opponent's pre-bout win% (SOS)
            for me, opp, ms, os in ((a, b, sa, sb), (b, a, sb, sa)):
                nm0 = B.norm(me)
                s = sos.setdefault(nm0, [0.0, 0]); s[0] += opp_q[nm0]; s[1] += 1
                g = running.setdefault(B.norm(me), B.fresh())
                dec = B.decay_factor(stat_date.get(nm0), bt["date"])
                if dec != 1.0:
                    for rk in B.RATE_DECAY_KEYS:
                        g[rk] *= dec
                stat_date[nm0] = bt["date"]
                g["minutes"] += (max(bt["endRound"] - 1, 0) * 5 + 2.5)
                g["sigL"] += ms["sigL"]; g["sigA"] += ms["sigA"]; g["sigAbs"] += os["sigL"]; g["oppSigA"] += os["sigA"]
                g["tdL"] += ms["tdL"]; g["tdA"] += ms["tdA"]; g["oppTdL"] += os["tdL"]; g["oppTdA"] += os["tdA"]
                g["subAtt"] += ms["subAtt"]; g["kd"] += ms["kd"]; g["kdAbs"] += os["kd"]; g["ctrl"] += ms["ctrl"]
                g["headL"] += ms.get("headL", 0); g["headA"] += ms.get("headA", 0); g["groundL"] += ms.get("groundL", 0)
                g["fights"] += 1
                if bt["winner"] == me:
                    g["wins"] += 1; g[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] += 1
                else:
                    g["losses"] += 1
                    if bt["method"] == "ko": g["koL"] += 1
                    elif bt["method"] == "sub": g["subL"] += 1
    return rows



async def main_async() -> None:
    print("loading ufcstats CSVs...")
    results, box, event_date, phys = await B.load()
    bouts = _chron_bouts(results, event_date)
    rows = _collect(bouts, box, phys)
    print(f"collected {len(rows)} training rows (both orientations) from {len(bouts)} bouts")

    X = [r[1] for r in rows]
    y = [r[2] for r in rows]

    # --- temporal holdout for honesty: train on older, score the recent third ---
    nonneg = [FEATURES.index(n) for n in NONNEG_FEATURES if n in FEATURES]
    cut = sorted(r[0] for r in rows)[int(len(rows) * 0.7)]
    tr = [(r[1], r[2]) for r in rows if r[0] < cut]
    te = [(r[1], r[2]) for r in rows if r[0] >= cut]
    if te:
        # NOTE: holdout sweeps over L2 (0.1-2.0) were dead flat, and with IRLS the
        # fit is exactly converged, so there is no optimizer knob left to tune.
        # Calibration is NOT corrected here: see WIN_LOGIT_TEMP in mma_analysis,
        # where a rolling-origin test showed the old 0.85 sharpening was fitted to
        # the 2023-2025 window rather than being a property of the model.
        wtr, btr = fit_logistic([f for f, _ in tr], [o for _, o in tr], l2=L2, nonneg=nonneg)
        ote = [o for _, o in te]
        pte = [_logistic(btr + sum(wtr[i] * f[i] for i in range(len(wtr)))) for f, _ in te]
        acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(pte, ote))
        print("")
        print(f"=== Temporal holdout (train <{cut}, test {len(te)} rows) ===")
        print(f"  accuracy {acc:.1%}   Brier {_brier(pte, ote):.4f}  (always-50% {_brier([0.5]*len(ote), ote):.4f})")

    # --- final fit on all data, stored in RAW feature space (no inference-time scaling) ---
    w_raw, b_raw = fit_logistic(X, y, l2=L2, nonneg=nonneg)

    preds = [_logistic(b_raw + sum(w_raw[i] * X[k][i] for i in range(len(w_raw)))) for k in range(len(X))]
    acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(preds, y))
    print("")
    print(f"=== Full-data fit ({len(X)} rows) ===")
    print(f"  in-sample accuracy {acc:.1%}   Brier {_brier(preds, y):.4f}")
    print("  learned weights (raw feature space):")
    for name, wt in sorted(zip(FEATURES, w_raw), key=lambda kv: -abs(kv[1])):
        pin = "  (pinned >= 0)" if name in NONNEG_FEATURES else ""
        print(f"     {name:<16} {wt:+.4f}{pin}")
    print(f"     {'(intercept)':<16} {b_raw:+.4f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "features": FEATURES, "weights": [round(w, 6) for w in w_raw],
        "intercept": round(b_raw, 6), "n": len(X),
        "nonneg": list(NONNEG_FEATURES),
        "builtAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main_async())
