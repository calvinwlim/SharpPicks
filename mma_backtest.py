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


# Time-decay (EWMA): exponentially down-weight older fights when accumulating
# rate stats. TESTED at a 2yr half-life and it HURT (winner Brier 0.2128->0.2139,
# holdout 0.2211->0.2220) — more data beats recency here, the third recency idea
# to fail (after last-5 momentum and the recent-form blend). Left at 0.0 (off);
# flip the half-life to retest. Applied to rate sums only, not win/loss counts.
DECAY_HALFLIFE_YRS = 0.0  # set >0 to enable (e.g. 2.0 = half weight after 2 years)
RATE_DECAY_KEYS = ("minutes", "sigL", "sigA", "sigAbs", "oppSigA", "tdL", "tdA", "oppTdL",
                   "oppTdA", "subAtt", "kd", "kdAbs", "ctrl", "headL", "headA", "groundL")


def decay_factor(prev_date, cur_date) -> float:
    if not DECAY_HALFLIFE_YRS or prev_date is None:
        return 1.0
    dy = max((cur_date - prev_date).days, 0) / 365.25
    return 0.5 ** (dy / DECAY_HALFLIFE_YRS)


def fresh() -> Dict[str, float]:
    return {k: 0.0 for k in ("minutes", "sigL", "sigA", "sigAbs", "oppSigA", "tdL", "tdA", "oppTdL", "oppTdA",
                             "subAtt", "kd", "kdAbs", "ctrl", "fights", "wins", "losses", "koW", "subW", "decW", "koL", "subL",
                             "headL", "headA", "groundL")}


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
        "headAcc": r(acc.get("headL", 0), acc.get("headA", 0)),
        "grndShare": r(acc.get("groundL", 0), acc["sigL"]),
    }
    M.shrink_rate_profile(out, acc["fights"])
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
        b = box.setdefault(key, {k: 0.0 for k in ("sigL", "sigA", "tdL", "tdA", "subAtt", "kd", "ctrl",
                                                  "headL", "headA", "groundL")})
        sl, sa = x_of_y(row.get("SIG.STR.", "")); tl, ta = x_of_y(row.get("TD", ""))
        hl, ha = x_of_y(row.get("HEAD", "")); gl, _ga = x_of_y(row.get("GROUND", ""))
        b["sigL"] += sl; b["sigA"] += sa; b["tdL"] += tl; b["tdA"] += ta
        b["headL"] += hl; b["headA"] += ha; b["groundL"] += gl
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
    stat_date: Dict[str, Any] = {}       # norm -> last bout added to the accumulator (for time-decay)
    sos: Dict[str, list] = {}            # norm -> [sum(opp win% faced), count] (A/B: strength of schedule)
    RECENT_K, RECENT_W = 5, 0.40

    def _winpct_acc(acc: Optional[Dict[str, float]]) -> float:
        if not acc:
            return 0.5
        g = acc["wins"] + acc["losses"]
        return acc["wins"] / g if g else 0.5

    def _sos(nm: str) -> float:
        s = sos.get(nm)
        return s[0] / s[1] if s and s[1] else 0.5

    def _recent_fl(window) -> Optional[float]:
        """Recent finish-loss rate: share of the last 5 fights this fighter was
        finished (KO/sub loss) — chin erosion. None when no history."""
        if not window:
            return None
        last5 = window[-5:]
        return sum(1 for d in last5 if d["koL"] or d["subL"]) / len(last5)
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
    sos_eval = []  # (winDiff, sos_diff, a_won) for the strength-of-schedule A/B sweep
    win_correct = 0
    dist_p, dist_o = [], []
    method_correct = method_n = 0
    sig_err = []
    sig_eval = []  # (slpm_a, sapm_a, slpm_b, sapm_b, model_min, actual_min, actual_sig, model_pred)
    td_eval = []   # (projected_td, actual_td) per fighter

    for bt in bouts:
        a, b = bt["names"]
        na, nb = norm(a), norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        gradeable = (bt["date"] >= since_date and acc_a and acc_b
                     and acc_a["fights"] >= MIN_PRIOR and acc_b["fights"] >= MIN_PRIOR and sa and sb)
        if gradeable:
            fa = rates(acc_a, phys.get(na, {})); fb = rates(acc_b, phys.get(nb, {}))
            fa["sos"], fb["sos"] = _sos(na), _sos(nb)
            fa["recentFinishLossRate"] = _recent_fl(recent_window.get(na))
            fb["recentFinishLossRate"] = _recent_fl(recent_window.get(nb))
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
            sos_eval.append((fm["winDiff"], _sos(na) - _sos(nb), a_won))
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
                sig_eval.append((fa["slpm"], fa["sapm"], fb["slpm"], fb["sapm"],
                                 fm["expMinutes"], bt["minutes"], actual_sig, fm["projSigStrikes"]["total"],
                                 fm["distanceProb"], bt["rounds"] * 5.0,
                                 bt["minutes"] / (bt["rounds"] * 5.0) if bt["method"] != "dec" else None))
                td_eval.append((fm["projTakedowns"]["a"], sa["tdL"]))
                td_eval.append((fm["projTakedowns"]["b"], sb["tdL"]))

        # update running accumulators with this bout (pair opponents)
        if sa and sb:
            # strength-of-schedule: record each fighter's opponent quality (the
            # opponent's *pre-bout* win%) before the accumulators advance.
            opp_q = {na: _winpct_acc(acc_b), nb: _winpct_acc(acc_a)}
            for me, opp, ms, os in ((a, b, sa, sb), (b, a, sb, sa)):
                nm0 = norm(me)
                s = sos.setdefault(nm0, [0.0, 0])
                s[0] += opp_q[nm0]; s[1] += 1
                d = fresh()
                d["minutes"] = bt["minutes"]; d["sigL"] = ms["sigL"]; d["sigA"] = ms["sigA"]
                d["sigAbs"] = os["sigL"]; d["oppSigA"] = os["sigA"]; d["tdL"] = ms["tdL"]; d["tdA"] = ms["tdA"]
                d["oppTdL"] = os["tdL"]; d["oppTdA"] = os["tdA"]; d["subAtt"] = ms["subAtt"]
                d["kd"] = ms["kd"]; d["kdAbs"] = os["kd"]; d["ctrl"] = ms["ctrl"]; d["fights"] = 1
                d["headL"] = ms.get("headL", 0); d["headA"] = ms.get("headA", 0); d["groundL"] = ms.get("groundL", 0)
                if bt["winner"] == me:
                    d["wins"] = 1; d[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] = 1
                else:
                    d["losses"] = 1
                    if bt["method"] == "ko": d["koL"] = 1
                    elif bt["method"] == "sub": d["subL"] = 1
                nm = norm(me)
                g = running.setdefault(nm, fresh())
                dec = decay_factor(stat_date.get(nm), bt["date"])
                if dec != 1.0:
                    for rk in RATE_DECAY_KEYS:
                        g[rk] *= dec
                stat_date[nm] = bt["date"]
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
    # selectivity: accuracy if we only ACT on picks at/above a confidence threshold.
    # Raw accuracy includes coin-flips; confident picks are what you'd actually bet.
    print("  selectivity (only pick fights at/above a confidence floor):")
    for thr in (0.50, 0.55, 0.60, 0.65, 0.70):
        idx = [i for i, p in enumerate(win_p) if max(p, 1 - p) >= thr]
        if idx:
            acc = mean(int((win_p[i] >= 0.5) == bool(win_o[i])) for i in idx)
            print(f"    >= {thr:.0%}: {acc:.1%} accuracy on {len(idx)} picks ({len(idx)/n:.0%} of slate)")

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

    # A/B: would a strength-of-schedule differential improve the winner? Sweep how
    # much SOS (avg opponent win% faced, a-b) added to the logit changes Brier. If
    # the best coefficient is ~0, career rates already price competition level in.
    print("\n=== A/B: strength-of-schedule on the win logit (Brier; lower=better) ===")
    sbest = None
    for k in (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0):
        preds = [min(max(1 / (1 + math.exp(-(d + k * s))), M.WIN_PROB_FLOOR), M.WIN_PROB_CEIL)
                 for d, s, _ in sos_eval]
        br = _brier(preds, [o for _, _, o in sos_eval])
        if sbest is None or br < sbest[1]:
            sbest = (k, br)
        print(f"  k={k:>5}: Brier {br:.4f}")
    print(f"  -> best SOS coefficient {sbest[0]} (Brier {sbest[1]:.4f}); k=0 = SOS adds nothing")

    print("\n=== Distance (goes to decision) ===")
    print(f"  accuracy  {mean(int((p>=0.5)==bool(o)) for p,o in zip(dist_p,dist_o)):.1%}")
    print(f"  Brier  {_brier(dist_p, dist_o):.4f}   (base-rate {_brier([mean(dist_o)]*len(dist_o), dist_o):.4f})")
    print(f"  actual decision rate {mean(dist_o):.1%} vs model avg {mean(dist_p):.1%}")

    print("\n=== Method (argmax KO/Sub/Dec) ===")
    print(f"  accuracy  {method_correct / method_n:.1%}  (n={method_n})")

    print("\n=== Total significant strikes ===")
    print(f"  current model MAE {mean(sig_err):.1f}   bias {mean(t[7]-t[6] for t in sig_eval):+.1f}")
    # Decompose error: rate model (own SLpM vs opp SApM blend) vs the minutes/finish
    # model. MAE(actual-min) uses the *real* fight length, so it isolates the rate;
    # the gap up to MAE(model-min) is what the distance/finish-timing model costs.
    actual_min_mae = mean(abs((0.5*(t[0]+t[2]) + 0.5*(t[1]+t[3])) * t[5] - t[6]) for t in sig_eval)
    print(f"  with ACTUAL fight length (isolates rate model): MAE {actual_min_mae:.1f}")
    ff = [t[10] for t in sig_eval if t[10] is not None]  # finish time as a fraction of full
    if ff:
        print(f"  finish timing: actual mean {mean(ff):.2f} of full vs FINISH_MID_FRAC={M.FINISH_MID_FRAC} (n={len(ff)})")
    print("  rate model (MAE at actual fight length, lower=better):")
    for w in (0.3, 0.4, 0.5, 0.6, 0.7):
        mae_actual = mean(abs((w*(t[0]+t[2]) + (1-w)*(t[1]+t[3])) * t[5] - t[6]) for t in sig_eval)
        print(f"    additive w={w}: MAE {mae_actual:.1f}")
    # log5 / multiplicative: own output x opp porousness / league mean (offense x defense)
    lg = M.LG_SLPM
    mae_log5 = mean(abs((t[0]*t[3]/lg + t[2]*t[1]/lg) * t[5] - t[6]) for t in sig_eval)
    print(f"    log5 (slpm*opp_sapm/lg):  MAE {mae_log5:.1f}")

    # Over/under prop calibration: how well a normal centered on the projection
    # fits the actual totals, swept over the std fraction (SIG_STD_FRAC). The point
    # MAE is dominated by fight-length bimodality, but the *prob* the total clears a
    # line just needs the spread right. (A finish/distance mixture was tested and
    # did NOT beat a well-tuned single normal — the wide σ already covers it.)
    def _lognorm(x, mu, sig):
        sig = max(sig, 1e-6)
        return -0.5 * math.log(2 * math.pi * sig * sig) - (x - mu) ** 2 / (2 * sig * sig)
    print("  prop calibration (mean log-likelihood of actual totals, higher=better):")
    for sf in (0.3, 0.4, 0.5, 0.6, 0.7):
        lls = [_lognorm(t[6], (0.5*(t[0]+t[2]) + 0.5*(t[1]+t[3])) * t[4],
                        max(sf * (0.5*(t[0]+t[2]) + 0.5*(t[1]+t[3])) * t[4], 6.0)) for t in sig_eval]
        tag = "  <- current SIG_STD_FRAC" if abs(sf - M.SIG_STD_FRAC) < 1e-6 else ""
        print(f"    sig_frac={sf}: {mean(lls):.3f}{tag}")

    print("\n=== Takedowns (per fighter) ===")
    print(f"  MAE {mean(abs(p - o) for p, o in td_eval):.2f}   bias {mean(p - o for p, o in td_eval):+.2f}"
          f"   (predicted mean {mean(p for p, _ in td_eval):.2f} vs actual {mean(o for _, o in td_eval):.2f})")
    print("\n(measures model accuracy + calibration, not betting ROI)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2022-01-01", help="grade fights on/after this date")
    asyncio.run(main_async(ap.parse_args().since))


if __name__ == "__main__":
    main()
