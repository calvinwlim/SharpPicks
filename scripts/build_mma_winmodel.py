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
import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mma_backtest as B
from backend import mma_analysis as M

OUT = ROOT / "backend" / "data" / "ufc_winmodel.json"

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
                 lr: float = 0.3, epochs: int = 4000) -> Tuple[List[float], float]:
    """Plain batch gradient-descent logistic regression on standardized X."""
    n, dim = len(X), len(X[0])
    w = [0.0] * dim
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * dim
        gb = 0.0
        for xi, yi in zip(X, y):
            p = _logistic(b + sum(w[d] * xi[d] for d in range(dim)))
            err = p - yi
            for d in range(dim):
                gw[d] += err * xi[d]
            gb += err
        for d in range(dim):
            w[d] -= lr * (gw[d] / n + l2 * w[d] / n)
        b -= lr * gb / n
    return w, b


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
    rows: List[Tuple[str, List[float], float]] = []

    def rwr(name: str) -> Optional[float]:
        r = recent.get(name)
        return (sum(r[-5:]) / len(r[-5:])) if r else None

    for bt in bouts:
        a, b = bt["names"]
        na, nb = B.norm(a), B.norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        if acc_a and acc_b and acc_a["fights"] >= B.MIN_PRIOR and acc_b["fights"] >= B.MIN_PRIOR and sa and sb:
            fa = B.rates(acc_a, phys.get(na, {}))
            fb = B.rates(acc_b, phys.get(nb, {}))
            fa["recentWinRate"], fb["recentWinRate"] = rwr(na), rwr(nb)
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
        if sa and sb:  # advance accumulators (same pairing as the other builders)
            for me, opp, ms, os in ((a, b, sa, sb), (b, a, sb, sa)):
                g = running.setdefault(B.norm(me), B.fresh())
                g["minutes"] += (max(bt["endRound"] - 1, 0) * 5 + 2.5)
                g["sigL"] += ms["sigL"]; g["sigA"] += ms["sigA"]; g["sigAbs"] += os["sigL"]; g["oppSigA"] += os["sigA"]
                g["tdL"] += ms["tdL"]; g["tdA"] += ms["tdA"]; g["oppTdL"] += os["tdL"]; g["oppTdA"] += os["tdA"]
                g["subAtt"] += ms["subAtt"]; g["kd"] += ms["kd"]; g["kdAbs"] += os["kd"]; g["ctrl"] += ms["ctrl"]
                g["fights"] += 1
                if bt["winner"] == me:
                    g["wins"] += 1; g[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] += 1
                else:
                    g["losses"] += 1
                    if bt["method"] == "ko": g["koL"] += 1
                    elif bt["method"] == "sub": g["subL"] += 1
    return rows


def _standardize(X):
    dim = len(X[0])
    cols = [[r[i] for r in X] for i in range(dim)]
    mean_v = [mean(c) for c in cols]
    std_v = [(sum((x - mean_v[i]) ** 2 for x in cols[i]) / len(cols[i])) ** 0.5 or 1.0 for i in range(dim)]
    Z = [[(r[i] - mean_v[i]) / std_v[i] for i in range(dim)] for r in X]
    return Z, mean_v, std_v


async def main_async() -> None:
    print("loading ufcstats CSVs...")
    results, box, event_date, phys = await B.load()
    bouts = _chron_bouts(results, event_date)
    rows = _collect(bouts, box, phys)
    print(f"collected {len(rows)} training rows (both orientations) from {len(bouts)} bouts")

    X = [r[1] for r in rows]
    y = [r[2] for r in rows]

    # --- temporal holdout for honesty: train on older, score the recent third ---
    cut = sorted(r[0] for r in rows)[int(len(rows) * 0.7)]
    tr = [(r[1], r[2]) for r in rows if r[0] < cut]
    te = [(r[1], r[2]) for r in rows if r[0] >= cut]
    if te:
        Ztr, mtr, str_ = _standardize([f for f, _ in tr])
        wtr, btr = fit_logistic(Ztr, [o for _, o in tr])
        zte = [[(f[i] - mtr[i]) / str_[i] for i in range(len(f))] for f, _ in te]
        pte = [_logistic(btr + sum(wtr[i] * z[i] for i in range(len(z)))) for z in zte]
        ote = [o for _, o in te]
        acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(pte, ote))
        print(f"\n=== Temporal holdout (train <{cut}, test {len(te)} rows) ===")
        print(f"  accuracy {acc:.1%}   Brier {_brier(pte, ote):.4f}  (always-50% {_brier([0.5]*len(ote), ote):.4f})")

    # --- final fit on all data, stored in RAW feature space (no inference-time scaling) ---
    Z, mean_v, std_v = _standardize(X)
    w_z, b_z = fit_logistic(Z, y)
    w_raw = [w_z[i] / std_v[i] for i in range(len(w_z))]
    b_raw = b_z - sum(w_z[i] * mean_v[i] / std_v[i] for i in range(len(w_z)))

    preds = [_logistic(b_raw + sum(w_raw[i] * X[k][i] for i in range(len(w_raw)))) for k in range(len(X))]
    acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(preds, y))
    print(f"\n=== Full-data fit ({len(X)} rows) ===")
    print(f"  in-sample accuracy {acc:.1%}   Brier {_brier(preds, y):.4f}")
    print("  learned weights (raw feature space):")
    for name, wt in sorted(zip(FEATURES, w_raw), key=lambda kv: -abs(kv[1])):
        print(f"     {name:<16} {wt:+.4f}")
    print(f"     {'(intercept)':<16} {b_raw:+.4f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "features": FEATURES, "weights": [round(w, 6) for w in w_raw],
        "intercept": round(b_raw, 6), "n": len(X),
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main_async())
