"""Offline MMA backtest — measures the fight model against real results.

Point-in-time / no leakage: fights are replayed in chronological order; each
fighter's rate profile is built only from their bouts *before* the fight being
predicted (a running accumulator updated after each prediction). We then grade
the winner, distance (decision vs finish), method, and significant-strike
projection against what actually happened, and sweep the win-probability scale
to find its best calibration.

    python mma_backtest.py --since 2022-01-01

Not betting ROI (needs closing lines) — this measures model accuracy/calibration.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import io
import math
import re
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend import mma_analysis as M

RAW = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main"
UA = {"User-Agent": "Mozilla/5.0"}
MIN_PRIOR = 4  # both fighters need this many prior bouts to be graded


def norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def x_of_y(s: str) -> Tuple[int, int]:
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def mmss(s: str) -> int:
    m = re.match(r"\s*(\d+):(\d+)", s or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def reach_in(s: str) -> Optional[float]:
    m = re.match(r"(\d+(?:\.\d+)?)", (s or "").replace('"', "").strip())
    return float(m.group(1)) if m else None


def classify(method: str) -> str:
    m = (method or "").lower()
    return "ko" if ("ko" in m or "tko" in m) else "sub" if "sub" in m else "dec" if "dec" in m else "other"


def fresh() -> Dict[str, float]:
    return {k: 0.0 for k in ("minutes", "sigL", "sigA", "sigAbs", "oppSigA", "tdL", "tdA", "oppTdL", "oppTdA",
                             "subAtt", "kd", "kdAbs", "ctrl", "fights", "wins", "losses", "koW", "subW", "decW", "koL", "subL")}


def rates(acc: Dict[str, float], phys: Dict[str, Any]) -> Dict[str, Any]:
    m = acc["minutes"] or 1.0
    w, l = acc["wins"], acc["losses"]
    def r(n, d, dv=0.0): return n / d if d else dv
    out = {
        "fights": acc["fights"], "wins": w, "losses": l, "minutes": m,
        "slpm": acc["sigL"] / m, "sapm": acc["sigAbs"] / m,
        "strAcc": r(acc["sigL"], acc["sigA"]), "strDef": (1 - acc["sigAbs"] / acc["oppSigA"]) if acc["oppSigA"] else 0.5,
        "tdAvg": acc["tdL"] / m * 15, "tdAcc": r(acc["tdL"], acc["tdA"]),
        "tdDef": (1 - acc["oppTdL"] / acc["oppTdA"]) if acc["oppTdA"] else 0.65,
        "subAvg": acc["subAtt"] / m * 15, "kdPer15": acc["kd"] / m * 15, "kdAbsPer15": acc["kdAbs"] / m * 15,
        "ctrlPerMin": acc["ctrl"] / 60.0 / m,
        "koRate": r(acc["koW"], w), "subRate": r(acc["subW"], w), "decRate": r(acc["decW"], w),
        "finishRate": r(acc["koW"] + acc["subW"], w), "finishedRate": r(acc["koL"] + acc["subL"], l),
    }
    out.update(phys)
    return out


async def load() -> Tuple[list, list, dict, dict]:
    async with httpx.AsyncClient(timeout=60.0, headers=UA, follow_redirects=True) as c:
        async def csvrows(name):
            r = await c.get(f"{RAW}/{name}"); r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        results, fstats, events, tott = await asyncio.gather(
            csvrows("ufc_fight_results.csv"), csvrows("ufc_fight_stats.csv"),
            csvrows("ufc_event_details.csv"), csvrows("ufc_fighter_tott.csv"))
    event_date = {}
    for e in events:
        raw = (e.get("DATE") or "").strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):  # event_details uses full month names
            try:
                event_date[e["EVENT"].strip()] = datetime.datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
    phys = {}
    for row in tott:
        phys[norm(row["FIGHTER"])] = {"reachIn": reach_in(row.get("REACH", "")),
                                      "dob": (row.get("DOB") or "").strip() or None,
                                      "stance": (row.get("STANCE") or "").strip() or None}
    # per (event,bout,fighter) box sums
    box: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for row in fstats:
        key = (row["EVENT"].strip(), row["BOUT"].strip(), row["FIGHTER"].strip())
        b = box.setdefault(key, {k: 0.0 for k in ("sigL", "sigA", "tdL", "tdA", "subAtt", "kd", "ctrl")})
        sl, sa = x_of_y(row.get("SIG.STR.", "")); tl, ta = x_of_y(row.get("TD", ""))
        b["sigL"] += sl; b["sigA"] += sa; b["tdL"] += tl; b["tdA"] += ta
        b["subAtt"] += float(row.get("SUB.ATT") or 0); b["kd"] += float(row.get("KD") or 0); b["ctrl"] += mmss(row.get("CTRL", ""))
    return results, box, event_date, phys


def _brier(preds, outs):
    return mean((p - o) ** 2 for p, o in zip(preds, outs))


def _sum_recent(window, k):
    """Sum the last ``k`` per-fight deltas into one accumulator (recent form)."""
    if not window:
        return None
    acc = fresh()
    for d in window[-k:]:
        for key, v in d.items():
            acc[key] += v
    return acc


async def main_async(since: str) -> None:
    print("loading ufcstats CSVs...")
    results, box, event_date, phys = await load()
    since_date = datetime.date.fromisoformat(since)

    # chronological bout list
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
        try:
            er = int(row.get("ROUND") or 0)
        except ValueError:
            er = 0
        minutes = max(er - 1, 0) * 5 + mmss(row.get("TIME", "")) / 60.0
        rounds = 5 if "5 Rnd" in (row.get("TIME FORMAT") or "") else 3
        bouts.append({"date": d, "event": event, "bout": bout, "names": names, "winner": winner,
                      "method": classify(row.get("METHOD", "")), "minutes": minutes if minutes > 0 else 5.0, "rounds": rounds})
    bouts.sort(key=lambda x: x["date"])

    running: Dict[str, Dict[str, float]] = {}
    recent_window: Dict[str, list] = {}  # norm -> list of recent per-fight deltas (A/B: recent-form blend)
    RECENT_K, RECENT_W = 5, 0.40
    blend_keys = ("slpm", "sapm", "strAcc", "strDef", "tdAvg", "tdAcc", "tdDef", "subAvg",
                  "kdPer15", "kdAbsPer15", "ctrlPerMin", "koRate", "subRate", "decRate",
                  "finishRate", "finishedRate")

    def blended(career: Dict[str, Any], recent_acc: Optional[Dict[str, float]], ph: Dict[str, Any]) -> Dict[str, Any]:
        if not recent_acc or recent_acc["minutes"] <= 0:
            return career
        rec = rates(recent_acc, ph)
        out = dict(career)
        for k in blend_keys:
            out[k] = (1 - RECENT_W) * career[k] + RECENT_W * rec[k]
        return out

    win_p, win_o, win_diff_pairs = [], [], []
    win_p_recent = []
    win_correct = 0
    dist_p, dist_o = [], []
    method_correct = method_n = 0
    sig_err = []

    for bt in bouts:
        a, b = bt["names"]
        na, nb = norm(a), norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        gradeable = (bt["date"] >= since_date and acc_a and acc_b
                     and acc_a["fights"] >= MIN_PRIOR and acc_b["fights"] >= MIN_PRIOR and sa and sb)
        if gradeable:
            fa = rates(acc_a, phys.get(na, {})); fb = rates(acc_b, phys.get(nb, {}))
            model = M.analyze_fight(fa, fb, a, b, rounds=bt["rounds"], fight_date=bt["date"].isoformat())
            fm = model["fightModel"]
            a_won = 1.0 if bt["winner"] == a else 0.0
            win_p.append(fm["aWinProb"]); win_o.append(a_won)
            win_diff_pairs.append((fm["winDiff"], a_won))
            # A/B: recent-form-blended prediction
            ra = _sum_recent(recent_window.get(na), RECENT_K)
            rb = _sum_recent(recent_window.get(nb), RECENT_K)
            mr = M.analyze_fight(blended(fa, ra, phys.get(na, {})), blended(fb, rb, phys.get(nb, {})),
                                 a, b, rounds=bt["rounds"], fight_date=bt["date"].isoformat())
            win_p_recent.append(mr["fightModel"]["aWinProb"])
            win_correct += int((fm["aWinProb"] >= 0.5) == bool(a_won))
            actual_dist = 1.0 if bt["method"] == "dec" else 0.0
            dist_p.append(fm["distanceProb"]); dist_o.append(actual_dist)
            pred_method = max(fm["method"], key=fm["method"].get)
            pred_method = {"ko": "ko", "sub": "sub", "decision": "dec"}[pred_method]
            if bt["method"] in ("ko", "sub", "dec"):
                method_n += 1; method_correct += int(pred_method == bt["method"])
            if sa and sb:
                actual_sig = sa["sigL"] + sb["sigL"]
                sig_err.append(abs(fm["projSigStrikes"]["total"] - actual_sig))

        # update running accumulators with this bout (pair opponents)
        if sa and sb:
            for me, opp, ms, os in ((a, b, sa, sb), (b, a, sb, sa)):
                d = fresh()
                d["minutes"] = bt["minutes"]; d["sigL"] = ms["sigL"]; d["sigA"] = ms["sigA"]
                d["sigAbs"] = os["sigL"]; d["oppSigA"] = os["sigA"]; d["tdL"] = ms["tdL"]; d["tdA"] = ms["tdA"]
                d["oppTdL"] = os["tdL"]; d["oppTdA"] = os["tdA"]; d["subAtt"] = ms["subAtt"]
                d["kd"] = ms["kd"]; d["kdAbs"] = os["kd"]; d["ctrl"] = ms["ctrl"]; d["fights"] = 1
                if bt["winner"] == me:
                    d["wins"] = 1; d[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] = 1
                else:
                    d["losses"] = 1
                    if bt["method"] == "ko": d["koL"] = 1
                    elif bt["method"] == "sub": d["subL"] = 1
                nm = norm(me)
                g = running.setdefault(nm, fresh())
                for k, v in d.items():
                    g[k] += v
                rw = recent_window.setdefault(nm, [])
                rw.append(d)
                if len(rw) > 8:
                    rw.pop(0)

    n = len(win_p)
    print(f"\nGraded {n} fights since {since} (>= {MIN_PRIOR} prior bouts each)\n")
    if not n:
        return
    base = mean(win_o)
    print("=== Winner ===")
    print(f"  accuracy (model favorite wins)  {win_correct / n:.1%}")
    print(f"  Brier  {_brier(win_p, win_o):.4f}   (always-50% {_brier([0.5]*n, win_o):.4f}; lower=better)")
    # reliability
    for lo in (0.5, 0.6, 0.7, 0.8):
        hi = lo + 0.1
        idx = [i for i, p in enumerate(win_p) if lo <= max(p, 1 - p) < hi]
        if idx:
            favw = mean((win_o[i] if win_p[i] >= 0.5 else 1 - win_o[i]) for i in idx)
            print(f"    fav {lo:.0%}-{hi:.0%}: n={len(idx):<4} predicted ~{mean(max(win_p[i],1-win_p[i]) for i in idx):.0%} actual {favw:.0%}")

    print("\n=== A/B: recent-form blend (last 5 fights, 40% weight) ===")
    print(f"  career-only  Brier {_brier(win_p, win_o):.4f}   acc {win_correct/n:.1%}")
    rec_acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(win_p_recent, win_o))
    print(f"  recent-blend Brier {_brier(win_p_recent, win_o):.4f}   acc {rec_acc:.1%}")

    # winDiff is the decision logit (learned model or hand-tuned/scale); a
    # temperature sweep should bottom out near T=1.0 if it's well-calibrated.
    model_tag = "learned coefficients" if M._WINMODEL else f"hand-tuned (WIN_DIFF_SCALE={M.WIN_DIFF_SCALE})"
    print(f"\n=== Win-prob logit-temperature sweep (Brier; lower=better) — {model_tag} ===")
    best = None
    for temp in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
        preds = [min(max(1 / (1 + math.exp(-d / temp)), M.WIN_PROB_FLOOR), M.WIN_PROB_CEIL) for d, _ in win_diff_pairs]
        br = _brier(preds, [o for _, o in win_diff_pairs])
        if best is None or br < best[1]:
            best = (temp, br)
        print(f"  T={temp:>4}: Brier {br:.4f}")
    print(f"  -> best temperature {best[0]} (Brier {best[1]:.4f}); 1.0 = as-calibrated")

    print("\n=== Distance (goes to decision) ===")
    print(f"  accuracy  {mean(int((p>=0.5)==bool(o)) for p,o in zip(dist_p,dist_o)):.1%}")
    print(f"  Brier  {_brier(dist_p, dist_o):.4f}   (base-rate {_brier([mean(dist_o)]*len(dist_o), dist_o):.4f})")
    print(f"  actual decision rate {mean(dist_o):.1%} vs model avg {mean(dist_p):.1%}")

    print("\n=== Method (argmax KO/Sub/Dec) ===")
    print(f"  accuracy  {method_correct / method_n:.1%}  (n={method_n})")

    print("\n=== Total significant strikes ===")
    print(f"  MAE  {mean(sig_err):.1f}")
    print("\n(measures model accuracy + calibration, not betting ROI)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2022-01-01", help="grade fights on/after this date")
    asyncio.run(main_async(ap.parse_args().since))


if __name__ == "__main__":
    main()
