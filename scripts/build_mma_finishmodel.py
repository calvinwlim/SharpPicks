"""Fit the MMA finish model — P(distance) and P(KO | finish) — from data.

The winner is already a learned logistic; distance and method were still
hand-tuned hazards (own finish rate x opponent durability). This script replays
every UFC bout point-in-time (each fighter's rate profile built only from bouts
*before* the fight — the same no-leakage replay as the winner builder) and fits
two plain logistic regressions:

  - **distance**  : P(the fight reaches a decision), label = method == "dec".
  - **koGivenFinish** : among *finished* fights only, P(KO/TKO vs submission).

Both use SYMMETRIC (combined) features owned by ``backend.mma_analysis``
(``DIST_FEATURE_NAMES`` / ``KO_FEATURE_NAMES``), so the coefficients line up with
inference. The learned models are written to ``backend/data/ufc_finishmodel.json``
and loaded by ``mma_analysis`` at runtime (the per-fighter ``_p_finish`` heuristic
is the fallback when the file is absent).

A temporal holdout is printed for honesty, and — for distance — the learned model
is compared head-to-head against the *current heuristic* so we only ship it if it
actually beats what it replaces.

    python scripts/build_mma_finishmodel.py

Re-run after rebuilding the fighter dataset; then validate with mma_backtest.py.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mma_backtest as B
from backend import mma_analysis as M
# reuse the winner builder's logistic fitter / standardizer / Brier so the two
# learned models are trained the exact same way.
from build_mma_winmodel import fit_logistic, _standardize, _brier, _logistic  # type: ignore

OUT = ROOT / "backend" / "data" / "ufc_finishmodel.json"
MIN_PRIOR = 4


def _bouts(results, event_date):
    out = []
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
        out.append({"date": d, "event": event, "bout": bout, "names": names, "winner": winner,
                    "method": B.classify(row.get("METHOD", "")), "rounds": rounds, "endRound": max(er, 1),
                    "wc": (row.get("WEIGHTCLASS") or "").replace("Bout", "").strip()})
    out.sort(key=lambda x: x["date"])
    return out


def _heur_ko_given(fa, fb, aa, ab, ar, br) -> float:
    """The CURRENT method heuristic's P(KO | finish): KO/Sub finishing tendencies
    weighted by each fighter's win prob (mirrors analyze_fight's fallback)."""
    a_win = M._win_prob(fa, fb, aa, ab, ar, br)
    ko_w = fa.get("koRate", 0) * a_win + fb.get("koRate", 0) * (1 - a_win) + 0.01
    sub_w = fa.get("subRate", 0) * a_win + fb.get("subRate", 0) * (1 - a_win) + 0.01
    return ko_w / (ko_w + sub_w)


def _collect(bouts, box, phys):
    """Replay point-in-time. Returns dist_rows, ko_rows, heur_dist, heur_ko (for A/B)."""
    running: Dict[str, Dict[str, float]] = {}
    last_date: Dict[str, Any] = {}
    dist_rows: List[Tuple[str, List[float], float]] = []
    ko_rows: List[Tuple[str, List[float], float]] = []
    heur_dist: List[Tuple[str, float, float]] = []
    heur_ko: List[Tuple[str, float, float]] = []

    for bt in bouts:
        a, b = bt["names"]
        na, nb = B.norm(a), B.norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        if (acc_a and acc_b and acc_a["fights"] >= MIN_PRIOR and acc_b["fights"] >= MIN_PRIOR
                and sa and sb and bt["method"] in ("ko", "sub", "dec")):
            fa = B.rates(acc_a, phys.get(na, {}))
            fb = B.rates(acc_b, phys.get(nb, {}))
            weight = M.weight_lbs(bt["wc"])
            ds = bt["date"].isoformat()
            is_dist = 1.0 if bt["method"] == "dec" else 0.0
            dist_rows.append((ds, M._dist_features(fa, fb, bt["rounds"], weight), is_dist))
            # current heuristic's distance prob, for a fair head-to-head
            heur = (1.0 - M._p_finish(fa, fb)) * (1.0 - M._p_finish(fb, fa))
            heur_dist.append((ds, heur, is_dist))
            if bt["method"] in ("ko", "sub"):
                is_ko = 1.0 if bt["method"] == "ko" else 0.0
                ko_rows.append((ds, M._ko_features(fa, fb, weight), is_ko))
                aa, ab = M._age(fa.get("dob"), ds), M._age(fb.get("dob"), ds)
                ar = M.rust_value(M.layoff_years(last_date[na].isoformat() if na in last_date else None, ds))
                br = M.rust_value(M.layoff_years(last_date[nb].isoformat() if nb in last_date else None, ds))
                heur_ko.append((ds, _heur_ko_given(fa, fb, aa, ab, ar, br), is_ko))

        last_date[na] = bt["date"]; last_date[nb] = bt["date"]

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
    return dist_rows, ko_rows, heur_dist, heur_ko


def _fit_raw(rows: List[Tuple[str, List[float], float]]):
    """Fit on standardized features, return weights/intercept in RAW space."""
    X = [r[1] for r in rows]
    y = [r[2] for r in rows]
    Z, mean_v, std_v = _standardize(X)
    w_z, b_z = fit_logistic(Z, y)
    w_raw = [w_z[i] / std_v[i] for i in range(len(w_z))]
    b_raw = b_z - sum(w_z[i] * mean_v[i] / std_v[i] for i in range(len(w_z)))
    return w_raw, b_raw


def _holdout(rows, label, heur=None) -> bool:
    """Temporal holdout: train on the older 70%, score the recent 30%. Returns
    True iff the learned model beats the thing it would replace (the current
    heuristic when given, else the base rate) on out-of-sample Brier."""
    cut = sorted(r[0] for r in rows)[int(len(rows) * 0.7)]
    tr = [r for r in rows if r[0] < cut]
    te = [r for r in rows if r[0] >= cut]
    if not te:
        return False
    w, b = _fit_raw(tr)
    preds = [_logistic(b + sum(w[i] * f[i] for i in range(len(f)))) for _, f, _ in te]
    outs = [o for _, _, o in te]
    acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(preds, outs))
    learned_brier = _brier(preds, outs)
    base_brier = _brier([mean(outs)] * len(outs), outs)
    print(f"\n=== Holdout: {label} (train <{cut}, test {len(te)}) ===")
    print(f"  learned   acc {acc:.1%}   Brier {learned_brier:.4f}   (base-rate {base_brier:.4f})")
    bench = base_brier
    if heur is not None:
        hmap = {(d, o): h for d, h, o in heur}
        hpreds = [hmap[(d, o)] for (d, _f, o) in te if (d, o) in hmap]
        houts = [o for (d, _f, o) in te if (d, o) in hmap]
        if hpreds:
            hacc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(hpreds, houts))
            bench = _brier(hpreds, houts)
            print(f"  heuristic acc {hacc:.1%}   Brier {bench:.4f}  <- what the learned model replaces")
    win = learned_brier < bench
    print(f"  -> learned {'BEATS' if win else 'loses to'} the baseline; "
          f"{'shipping' if win else 'keeping the heuristic'} this piece.")
    return win


async def main_async() -> None:
    print("loading ufcstats CSVs...")
    results, box, event_date, phys = await B.load()
    bouts = _bouts(results, event_date)
    dist_rows, ko_rows, heur_dist, heur_ko = _collect(bouts, box, phys)
    print(f"collected {len(dist_rows)} distance rows, {len(ko_rows)} finish rows from {len(bouts)} bouts")

    # Only ship a learned piece if it beats the heuristic it would replace, point-in-time.
    ship_dist = _holdout(dist_rows, "P(distance)", heur=heur_dist)
    ship_ko = _holdout(ko_rows, "P(KO | finish)", heur=heur_ko)

    model: Dict[str, Any] = {}
    if ship_dist:
        dw, db = _fit_raw(dist_rows)
        model["distance"] = {"features": M.DIST_FEATURE_NAMES,
                             "weights": [round(w, 6) for w in dw], "intercept": round(db, 6),
                             "n": len(dist_rows)}
        print("\n=== distance weights (raw space) ===")
        for name, wt in sorted(zip(M.DIST_FEATURE_NAMES, dw), key=lambda kv: -abs(kv[1])):
            print(f"   {name:<14} {wt:+.4f}")
    if ship_ko:
        kw, kb = _fit_raw(ko_rows)
        model["koGivenFinish"] = {"features": M.KO_FEATURE_NAMES,
                                  "weights": [round(w, 6) for w in kw], "intercept": round(kb, 6),
                                  "n": len(ko_rows)}
        print("\n=== KO-given-finish weights (raw space) ===")
        for name, wt in sorted(zip(M.KO_FEATURE_NAMES, kw), key=lambda kv: -abs(kv[1])):
            print(f"   {name:<14} {wt:+.4f}")

    if not model:
        print("\nNeither learned piece beat its heuristic out-of-sample — NOT writing "
              "ufc_finishmodel.json (the heuristic finish hazard stays in force).")
        if OUT.exists():
            OUT.unlink()
            print(f"removed stale {OUT}")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT} ({', '.join(model)})")


if __name__ == "__main__":
    asyncio.run(main_async())
