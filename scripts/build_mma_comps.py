"""Build the MMA "comps" dataset: every historical UFC fight as a point-in-time
matchup vector + its actual outcome, for nearest-neighbor matching.

Reuses the chronological, no-leakage aggregation from ``mma_backtest`` (each
fight's vector is built from the two fighters' stats *before* that bout) and the
shared feature builder in ``backend.mma_comps``. Writes
``backend/data/ufc_fight_vectors.json`` and runs a holdout validation that
predicts each recent fight from earlier comps only.

    python scripts/build_mma_comps.py
"""
from __future__ import annotations

import asyncio
import datetime
import json
import sys
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mma_backtest as B
from backend import mma_comps as C

OUT = ROOT / "backend" / "data" / "ufc_fight_vectors.json"
MIN_PRIOR = 4


async def main_async() -> None:
    print("loading ufcstats CSVs...")
    results, box, event_date, phys = await B.load()

    bouts: List[Dict[str, Any]] = []
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
        try:
            er = int(row.get("ROUND") or 0)
        except ValueError:
            er = 0
        rounds = 5 if "5 Rnd" in (row.get("TIME FORMAT") or "") else 3
        bouts.append({"date": d, "event": event, "bout": bout, "names": names, "winner": winner,
                      "method": B.classify(row.get("METHOD", "")), "endRound": max(er, 1), "rounds": rounds})
    bouts.sort(key=lambda x: x["date"])

    running: Dict[str, Dict[str, float]] = {}
    vectors: List[Dict[str, Any]] = []

    for bt in bouts:
        a, b = bt["names"]
        na, nb = B.norm(a), B.norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        if acc_a and acc_b and acc_a["fights"] >= MIN_PRIOR and acc_b["fights"] >= MIN_PRIOR and sa and sb:
            fa = B.rates(acc_a, phys.get(na, {}))
            fb = B.rates(acc_b, phys.get(nb, {}))
            vec, fav_is_a = C.build_vector(fa, fb, bt["rounds"], bt["date"].isoformat())
            fav = a if fav_is_a else b
            dog = b if fav_is_a else a
            total_sig = sa["sigL"] + sb["sigL"]
            vectors.append({
                "vec": [round(x, 4) for x in vec],
                "out": {"favWon": int(bt["winner"] == fav), "method": bt["method"],
                        "distance": int(bt["method"] == "dec"), "totalSig": total_sig,
                        "endRound": bt["endRound"]},
                "meta": {"fav": fav, "dog": dog, "event": bt["event"], "date": bt["date"].isoformat()},
            })

        # advance the running accumulators (same pairing as the backtest)
        if sa and sb:
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

    # standardization stats
    dim = len(C.FEATURE_NAMES)
    cols = [[v["vec"][i] for v in vectors] for i in range(dim)]
    mean_v = [round(mean(c), 5) for c in cols]
    std_v = [round(pstdev(c) or 1.0, 5) for c in cols]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"featNames": C.FEATURE_NAMES, "mean": mean_v, "std": std_v, "vectors": vectors},
                              separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(vectors)} fight vectors -> {OUT} ({OUT.stat().st_size // 1024} KB)")

    _validate(vectors, mean_v, std_v)


def _validate(vectors, mean_v, std_v, k=60, since="2023-01-01"):
    """Holdout: predict each fight since `since` from earlier comps only."""
    dim = len(mean_v)
    z = [[(v["vec"][i] - mean_v[i]) / std_v[i] for i in range(dim)] for v in vectors]
    since_d = since
    fav_p, fav_o, dist_p, dist_o, method_correct, method_n = [], [], [], [], 0, 0
    for i, v in enumerate(vectors):
        if v["meta"]["date"] < since_d or i < 200:
            continue
        zi = z[i]
        # neighbors strictly earlier (vectors are in chronological order)
        scored = sorted(((sum((zi[d] - z[j][d]) ** 2 for d in range(dim)), j) for j in range(i)),
                        key=lambda x: x[0])[:k]
        comps = [vectors[j] for _, j in scored]
        p = sum(c["out"]["favWon"] for c in comps) / len(comps)
        fav_p.append(p); fav_o.append(v["out"]["favWon"])
        dp = sum(c["out"]["distance"] for c in comps) / len(comps)
        dist_p.append(dp); dist_o.append(v["out"]["distance"])
        mc = {"ko": 0, "sub": 0, "dec": 0}
        for c in comps:
            if c["out"]["method"] in mc:
                mc[c["out"]["method"]] += 1
        if v["out"]["method"] in ("ko", "sub", "dec"):
            method_n += 1
            method_correct += int(max(mc, key=mc.get) == v["out"]["method"])

    def brier(pp, oo):
        return mean((a - b) ** 2 for a, b in zip(pp, oo))

    n = len(fav_p)
    print(f"\n=== Comps holdout validation ({n} fights since {since}, k={k}) ===")
    print(f"  favorite-by-comps wins   {mean(int((p >= 0.5) == bool(o)) for p, o in zip(fav_p, fav_o)):.1%} "
          f"(Brier {brier(fav_p, fav_o):.4f} vs always-50% {brier([0.5]*n, fav_o):.4f})")
    print(f"  distance                 Brier {brier(dist_p, dist_o):.4f} "
          f"(base {brier([mean(dist_o)]*n, dist_o):.4f}); comp avg {mean(dist_p):.1%} vs actual {mean(dist_o):.1%}")
    print(f"  method (argmax of comps) {method_correct / method_n:.1%} acc (n={method_n})")
    print("\n(comps are case-based, not betting ROI)")


if __name__ == "__main__":
    asyncio.run(main_async())
