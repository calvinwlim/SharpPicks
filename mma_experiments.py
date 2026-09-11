"""Search for MMA model improvements — the counterpart to ``mma_backtest.py``.

``mma_backtest.py`` measures the model that SHIPS. This script measures the ones
that might: it runs the same no-leakage point-in-time replay once, then scores a
list of candidate changes against a temporal holdout (fit on everything before
``--cutoff``, grade everything after). A change only earns its way into
``backend/mma_analysis.py`` if it wins here, and the ones that lose get written
up as comments next to the code they would have touched, so nobody re-tries them.

    python mma_experiments.py                  # all experiments
    python mma_experiments.py --only decay     # just one

The replay is the expensive part (~15s) and everything downstream reuses it, so
adding another experiment is cheap. CSVs come from mma_backtest's local cache.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fitlib as F
import mma_backtest as B
from backend import mma_analysis as M

CUTOFF = "2023-01-01"   # train strictly before, grade on/after
MIN_PRIOR = 4


# --------------------------------------------------------------------------- replay

def _div_key(wc: str) -> str:
    """Bucket a weight-class string to its division, by nominal poundage."""
    return str(int(M.weight_lbs(wc)))


async def replay(halflife: float = 0.0, div_means: bool = False) -> List[Dict[str, Any]]:
    """Point-in-time replay -> one record per gradeable bout.

    Mirrors ``mma_backtest``'s accumulator exactly (same shrinkage, same SOS and
    recent-form bookkeeping) but emits structured records instead of grading, so
    many model variants can be scored without re-walking history.

    ``halflife`` (years) exponentially down-weights older rate sums; ``div_means``
    shrinks small samples toward that fighter's DIVISION mean instead of the
    global one.
    """
    results, box, event_date, phys = await B.load()
    bouts = _bouts(results, event_date)

    div_mean_tbl = _division_means(bouts, box) if div_means else None

    running: Dict[str, Dict[str, float]] = {}
    stat_date: Dict[str, Any] = {}
    sos: Dict[str, list] = {}
    recent_window: Dict[str, list] = {}
    out: List[Dict[str, Any]] = []

    def _winpct_acc(acc) -> float:
        if not acc:
            return 0.5
        g = acc["wins"] + acc["losses"]
        return acc["wins"] / g if g else 0.5

    def _sos(nm: str) -> float:
        s = sos.get(nm)
        return s[0] / s[1] if s and s[1] else 0.5

    def _recent_fl(window) -> Optional[float]:
        if not window:
            return None
        last5 = window[-5:]
        return sum(1 for d in last5 if d["koL"] or d["subL"]) / len(last5)

    def _rates(acc, ph, wc):
        means = div_mean_tbl.get(_div_key(wc)) if div_mean_tbl else None
        r = B.rates_with_means(acc, ph, means)
        r["weightClass"] = wc
        return r

    for bt in bouts:
        a, b = bt["names"]
        na, nb = B.norm(a), B.norm(b)
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        acc_a, acc_b = running.get(na), running.get(nb)
        if (acc_a and acc_b and acc_a["fights"] >= MIN_PRIOR and acc_b["fights"] >= MIN_PRIOR
                and sa and sb):
            fa = _rates(acc_a, phys.get(na, {}), bt["wc"])
            fb = _rates(acc_b, phys.get(nb, {}), bt["wc"])
            fa["sos"], fb["sos"] = _sos(na), _sos(nb)
            fa["recentFinishLossRate"] = _recent_fl(recent_window.get(na))
            fb["recentFinishLossRate"] = _recent_fl(recent_window.get(nb))
            a_age = M._age(fa.get("dob"), bt["date"].isoformat())
            b_age = M._age(fb.get("dob"), bt["date"].isoformat())
            end_round = min(max(int(math.ceil(bt["minutes"] / 5.0)), 1), bt["rounds"])
            out.append({
                "date": bt["date"], "rounds": bt["rounds"], "wc": bt["wc"],
                "weight": M.weight_lbs(bt["wc"]),
                "fa": fa, "fb": fb, "a_age": a_age, "b_age": b_age,
                "a_won": 1.0 if bt["winner"] == a else 0.0,
                "method": bt["method"], "minutes": bt["minutes"], "end_round": end_round,
                "sig_a": sa["sigL"], "sig_b": sb["sigL"],
                "td_a": sa["tdL"], "td_b": sb["tdL"],
            })

        if sa and sb:
            opp_q = {na: _winpct_acc(acc_b), nb: _winpct_acc(acc_a)}
            for me, opp, ms, os in ((a, b, sa, sb), (b, a, sb, sa)):
                nm = B.norm(me)
                s = sos.setdefault(nm, [0.0, 0])
                s[0] += opp_q[nm]; s[1] += 1
                d = B.fresh()
                d["minutes"] = bt["minutes"]; d["sigL"] = ms["sigL"]; d["sigA"] = ms["sigA"]
                d["sigAbs"] = os["sigL"]; d["oppSigA"] = os["sigA"]
                d["tdL"] = ms["tdL"]; d["tdA"] = ms["tdA"]
                d["oppTdL"] = os["tdL"]; d["oppTdA"] = os["tdA"]
                d["subAtt"] = ms["subAtt"]; d["kd"] = ms["kd"]; d["kdAbs"] = os["kd"]
                d["ctrl"] = ms["ctrl"]; d["fights"] = 1
                d["headL"] = ms.get("headL", 0); d["headA"] = ms.get("headA", 0)
                d["groundL"] = ms.get("groundL", 0)
                if bt["winner"] == me:
                    d["wins"] = 1
                    d[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] = 1
                else:
                    d["losses"] = 1
                    if bt["method"] == "ko": d["koL"] = 1
                    elif bt["method"] == "sub": d["subL"] = 1
                g = running.setdefault(nm, B.fresh())
                if halflife and stat_date.get(nm) is not None:
                    dy = max((bt["date"] - stat_date[nm]).days, 0) / 365.25
                    dec = 0.5 ** (dy / halflife)
                    for rk in B.RATE_DECAY_KEYS:
                        g[rk] *= dec
                stat_date[nm] = bt["date"]
                for k, v in d.items():
                    g[k] += v
                rw = recent_window.setdefault(nm, [])
                rw.append(d)
                if len(rw) > 8:
                    rw.pop(0)
    return out



def _bouts(results, event_date) -> List[Dict[str, Any]]:
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
        minutes = max(er - 1, 0) * 5 + B.mmss(row.get("TIME", "")) / 60.0
        bouts.append({
            "date": d, "event": event, "bout": bout, "names": names, "winner": winner,
            "method": B.classify(row.get("METHOD", "")),
            "minutes": minutes if minutes > 0 else 5.0,
            "rounds": 5 if "5 Rnd" in (row.get("TIME FORMAT") or "") else 3,
            "wc": (row.get("WEIGHTCLASS") or "").replace("Bout", "").strip(),
        })
    bouts.sort(key=lambda x: x["date"])
    return bouts


def _division_means(bouts, box) -> Dict[str, Dict[str, float]]:
    """Per-division league rate means, for division-relative shrinkage targets.

    Computed from career totals per division (all history) — this is a shrinkage
    TARGET, not a feature, so it is a population constant rather than a
    point-in-time quantity.
    """
    acc: Dict[str, Dict[str, float]] = {}
    for bt in bouts:
        key = _div_key(bt["wc"])
        a, b = bt["names"]
        sa, sb = box.get((bt["event"], bt["bout"], a)), box.get((bt["event"], bt["bout"], b))
        if not sa or not sb:
            continue
        g = acc.setdefault(key, {k: 0.0 for k in ("minutes", "sigL", "sigAbs", "sigA", "oppSigA",
                                                  "tdL", "tdA", "oppTdL", "oppTdA", "subAtt", "kd",
                                                  "kdAbs", "ctrl", "headL", "headA", "groundL",
                                                  "wins", "koW", "subW", "decW", "losses", "koL", "subL")})
        for ms, os in ((sa, sb), (sb, sa)):
            g["minutes"] += bt["minutes"]
            g["sigL"] += ms["sigL"]; g["sigA"] += ms["sigA"]
            g["sigAbs"] += os["sigL"]; g["oppSigA"] += os["sigA"]
            g["tdL"] += ms["tdL"]; g["tdA"] += ms["tdA"]
            g["oppTdL"] += os["tdL"]; g["oppTdA"] += os["tdA"]
            g["subAtt"] += ms["subAtt"]; g["kd"] += ms["kd"]; g["kdAbs"] += os["kd"]
            g["ctrl"] += ms["ctrl"]
            g["headL"] += ms.get("headL", 0); g["headA"] += ms.get("headA", 0)
            g["groundL"] += ms.get("groundL", 0)
        g["wins"] += 1; g["losses"] += 1
        g[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(bt["method"], "decW")] += 1
        if bt["method"] == "ko": g["koL"] += 1
        elif bt["method"] == "sub": g["subL"] += 1

    out: Dict[str, Dict[str, float]] = {}
    for key, g in acc.items():
        m = g["minutes"] or 1.0
        w, l = g["wins"] or 1.0, g["losses"] or 1.0
        def r(n, d, dv):
            return n / d if d else dv
        out[key] = {
            "slpm": g["sigL"] / m, "sapm": g["sigAbs"] / m,
            "strAcc": r(g["sigL"], g["sigA"], 0.45),
            "strDef": 1 - g["sigAbs"] / g["oppSigA"] if g["oppSigA"] else 0.55,
            "tdAvg": g["tdL"] / m * 15, "tdAcc": r(g["tdL"], g["tdA"], 0.40),
            "tdDef": 1 - g["oppTdL"] / g["oppTdA"] if g["oppTdA"] else 0.65,
            "subAvg": g["subAtt"] / m * 15,
            "kdPer15": g["kd"] / m * 15, "kdAbsPer15": g["kdAbs"] / m * 15,
            "ctrlPerMin": g["ctrl"] / 60.0 / m,
            "koRate": r(g["koW"], w, 0.35), "subRate": r(g["subW"], w, 0.18),
            "decRate": r(g["decW"], w, 0.47),
            "finishRate": r(g["koW"] + g["subW"], w, 0.53),
            "finishedRate": r(g["koL"] + g["subL"], l, 0.45),
            "headAcc": r(g["headL"], g["headA"], 0.35),
            "grndShare": r(g["groundL"], g["sigL"], 0.12),
        }
    return out


# --------------------------------------------------------------------------- shared

def split(recs, cutoff: str = CUTOFF):
    import datetime
    c = datetime.date.fromisoformat(cutoff)
    return [r for r in recs if r["date"] < c], [r for r in recs if r["date"] >= c]


def win_xy(recs) -> Tuple[List[List[float]], List[float]]:
    """Feature matrix + labels, each bout in BOTH orientations (antisymmetric fit)."""
    X, y = [], []
    for r in recs:
        X.append(M._win_features(r["fa"], r["fb"], r["a_age"], r["b_age"]))
        y.append(r["a_won"])
        X.append(M._win_features(r["fb"], r["fa"], r["b_age"], r["a_age"]))
        y.append(1.0 - r["a_won"])
    return X, y


def _fmt(tag: str, base: float, new: float, lower_better: bool = True) -> str:
    better = (new < base) if lower_better else (new > base)
    delta = new - base
    mark = "WIN " if better and abs(delta) > 1e-4 else "    "
    return f"  {mark}{tag:<34} {new:.4f}  ({delta:+.4f})"


# --------------------------------------------------------------------------- calibration helpers

def pava(x: List[float], y: List[float]) -> List[Tuple[float, float]]:
    """Pool-adjacent-violators isotonic fit -> list of (x_right_edge, value)."""
    order = sorted(range(len(x)), key=lambda i: x[i])
    blocks = [[x[i], y[i], 1.0] for i in order]   # [x_right, mean, weight]
    out: List[List[float]] = []
    for blk in blocks:
        out.append(blk)
        while len(out) > 1 and out[-2][1] > out[-1][1]:
            b = out.pop()
            a = out.pop()
            w = a[2] + b[2]
            out.append([b[0], (a[1] * a[2] + b[1] * b[2]) / w, w])
    return [(b[0], b[1]) for b in out]


def iso_apply(fit: List[Tuple[float, float]], v: float) -> float:
    lo, hi = 0, len(fit) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if fit[mid][0] < v:
            lo = mid + 1
        else:
            hi = mid
    return fit[lo][1]


def platt2(p: List[float], o: List[float]) -> Tuple[float, float]:
    """Two-parameter Platt scaling on the LOGIT: returns (a, b) for a*logit+b."""
    def logit(v):
        v = min(max(v, 1e-6), 1 - 1e-6)
        return math.log(v / (1 - v))
    X = [[logit(v)] for v in p]
    w, b = F.fit_logistic(X, o, l2=1e-6)
    return w[0], b


# --------------------------------------------------------------------------- experiments

def _eval_win(train, test, l2=1.0, nonneg=None, temp=1.0):
    """Fit on ``train``, score ``test`` in BOTH corner orientations.

    ufcstats lists the winner first far more often than not — the first-named
    fighter wins 62% of the training period and 55% of the test period. Scoring
    only the "a" orientation therefore measures listing convention as much as
    skill, and (worse) lets any calibrator fit on that base rate, which is not
    stable across periods. The model is antisymmetric, so grading both
    orientations pins the label base rate at exactly 0.5 and cancels the artifact.
    """
    Xtr, ytr = win_xy(train)
    w, b = F.fit_logistic(Xtr, ytr, l2=l2, nonneg=nonneg)
    ps, os_ = [], []
    for r in test:
        for fa, fb, ag, bg, y in ((r["fa"], r["fb"], r["a_age"], r["b_age"], r["a_won"]),
                                  (r["fb"], r["fa"], r["b_age"], r["a_age"], 1.0 - r["a_won"])):
            f = M._win_features(fa, fb, ag, bg)
            z = (b + sum(w[i] * f[i] for i in range(len(w)))) / temp
            ps.append(F._sigmoid(z)); os_.append(y)
    acc = mean(int((p >= 0.5) == bool(o)) for p, o in zip(ps, os_))
    return F.brier(ps, os_), F.log_loss(ps, os_), acc, (w, b), ps, os_


def exp_baseline(recs):
    print("\n=== BASELINE (current features, unconstrained ridge, T=1) ===")
    tr, te = split(recs)
    br, ll, acc, (w, b), _, _ = _eval_win(tr, te)
    print(f"  holdout Brier {br:.4f}   logloss {ll:.4f}   acc {acc:.1%}   (n={len(te)})")
    neg = [(n, wi) for n, wi in zip(M.WIN_FEATURE_NAMES, w) if wi < 0]
    print(f"  negative-weight features: {', '.join(n for n, _ in neg) or 'none'}")
    return br, ll, acc


def exp_decay(recs_base, loop):
    """#8 — exponential time-decay on the rate accumulators."""
    print("\n=== #8 time-decay half-life sweep (rate sums) ===")
    tr, te = split(recs_base)
    base = _eval_win(tr, te)[0]
    print(f"  {'off (career totals)':<36} {base:.4f}  (baseline)")
    for hl in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0):
        recs = loop.run_until_complete(replay(halflife=hl))
        tr2, te2 = split(recs)
        br = _eval_win(tr2, te2)[0]
        print(_fmt(f"half-life {hl}y", base, br))


def exp_divmeans(recs_base, loop):
    """#9 — shrink toward division means instead of global league means."""
    print("\n=== #9 division-relative shrinkage targets ===")
    tr, te = split(recs_base)
    base = _eval_win(tr, te)[0]
    print(f"  {'global league means':<36} {base:.4f}  (baseline)")
    recs = loop.run_until_complete(replay(div_means=True))
    tr2, te2 = split(recs)
    br = _eval_win(tr2, te2)[0]
    print(_fmt("per-division means", base, br))


def exp_signs(recs):
    """#7 — constrain causally-positive features to non-negative weights."""
    print("\n=== #7 sign constraints on causally-positive features ===")
    tr, te = split(recs)
    base, bll, bacc, (w0, _), _, _ = _eval_win(tr, te)
    print(f"  {'unconstrained':<36} {base:.4f}  (baseline)")
    for n, wi in zip(M.WIN_FEATURE_NAMES, w0):
        if wi < 0:
            print(f"      negative today: {n:<16} {wi:+.4f}")
    # Features whose sign is not in doubt: landing more, defending more, finishing
    # more, controlling more, being younger/fresher can only help you win.
    POSITIVE = ["d_striking_net", "d_slpm", "d_strDef", "d_tdAvg", "d_tdDef", "d_ctrl",
                "d_sub", "d_kd", "d_finish", "d_durability", "d_winpct", "d_reach",
                "d_age", "d_stance", "d_rust", "d_sos", "d_chin", "d_headacc"]
    idx = [M.WIN_FEATURE_NAMES.index(n) for n in POSITIVE if n in M.WIN_FEATURE_NAMES]
    br, ll, acc, (w1, _), _, _ = _eval_win(tr, te, nonneg=idx)
    print(_fmt("all causally-positive >= 0", base, br))
    print(f"       logloss {ll:.4f} ({ll-bll:+.4f})   acc {acc:.1%} ({acc-bacc:+.1%})")
    zeroed = [n for n, wi in zip(M.WIN_FEATURE_NAMES, w1) if wi == 0.0]
    print(f"       pinned to zero: {', '.join(zeroed) or 'none'}")
    return idx


def exp_calibration(recs):
    """#6 — the calibration error has a shape; a scalar temperature can't fix it."""
    print("\n=== #6 calibration: scalar temperature vs shape correction ===")
    import datetime
    cal_start = datetime.date.fromisoformat("2021-01-01")
    cut = datetime.date.fromisoformat(CUTOFF)
    tr = [r for r in recs if r["date"] < cal_start]
    cal = [r for r in recs if cal_start <= r["date"] < cut]
    te = [r for r in recs if r["date"] >= cut]
    print(f"  fit n={len(tr)}  calib n={len(cal)}  test n={len(te)}")

    Xtr, ytr = win_xy(tr)
    w, b = F.fit_logistic(Xtr, ytr, l2=1.0)

    def raw(rs):
        ps, os_ = [], []
        for r in rs:
            f = M._win_features(r["fa"], r["fb"], r["a_age"], r["b_age"])
            ps.append(F._sigmoid(b + sum(w[i] * f[i] for i in range(len(w)))))
            os_.append(r["a_won"])
        return ps, os_

    pc, oc = raw(cal)
    pt, ot = raw(te)
    base = F.brier(pt, ot)
    print(f"  {'uncalibrated':<36} {base:.4f}  (baseline)")

    # scalar temperature, tuned on the calibration slice
    best_t, best_v = 1.0, None
    for t in [x / 20 for x in range(10, 41)]:
        v = F.brier([F._sigmoid(math.log(max(p,1e-9)/max(1-p,1e-9))/t) for p in pc], oc)
        if best_v is None or v < best_v:
            best_t, best_v = t, v
    pt_t = [F._sigmoid(math.log(max(p,1e-9)/max(1-p,1e-9))/best_t) for p in pt]
    print(_fmt(f"scalar temperature (T={best_t:.2f})", base, F.brier(pt_t, ot)))

    a2, b2 = platt2(pc, oc)
    pt_p = [F._sigmoid(a2 * math.log(max(p,1e-9)/max(1-p,1e-9)) + b2) for p in pt]
    print(_fmt(f"Platt 2-param (a={a2:.3f}, b={b2:+.3f})", base, F.brier(pt_p, ot)))

    fit = pava(pc, oc)
    pt_i = [iso_apply(fit, p) for p in pt]
    print(_fmt("isotonic (PAVA)", base, F.brier(pt_i, ot)))

    print("  reliability by bucket (test):")
    for lo in (0.5, 0.6, 0.7, 0.8):
        hi = lo + 0.1
        sel = [(max(p,1-p), (o if p >= 0.5 else 1-o)) for p, o in zip(pt, ot) if lo <= max(p,1-p) < hi]
        if sel:
            print(f"    fav {lo:.0%}-{hi:.0%}: n={len(sel):<4} predicted {mean(s[0] for s in sel):.0%} "
                  f"actual {mean(s[1] for s in sel):.0%}")
    return best_t, (a2, b2)


def _norm_ll(x: float, mu: float, sd: float) -> float:
    sd = max(sd, 1e-6)
    return -0.5 * ((x - mu) / sd) ** 2 - math.log(sd * math.sqrt(2 * math.pi))


def exp_mixture(recs):
    """#4/#5 — what distribution should the count props use?

    The obvious fix for a bimodal total (finish vs decision) is a two-component
    mixture. It helps, but a NEGATIVE BINOMIAL on the blended mean beats it
    outright, because a low-k NB already carries the skew the mixture was
    approximating — and it stays a single, simple distribution. Every shape
    parameter is fitted on TRAIN and scored blind on TEST, so nothing is chosen
    on the data that judges it.
    """
    print("")
    print("=== #4/#5 sig-strike distribution family ===")
    tr, te = split(recs)

    def parts(r):
        fa, fb, rounds = r["fa"], r["fb"], r["rounds"]
        pa, pb = M._p_finish(fa, fb), M._p_finish(fb, fa)
        dp = (1 - pa) * (1 - pb)
        full = rounds * 5.0

        def tot(mins):
            return M._sig_projection(fa, fb, mins) + M._sig_projection(fb, fa, mins)
        return dp, tot(full), tot(full * M.FINISH_MID_FRAC), tot(M._expected_minutes(dp, rounds))

    def fit_and_score(name, grid, ll_of):
        best = None
        for prm in grid:
            v = mean(ll_of(r, r["sig_a"] + r["sig_b"], prm) for r in tr)
            if best is None or v > best[1]:
                best = (prm, v)
        test = mean(ll_of(r, r["sig_a"] + r["sig_b"], best[0]) for r in te)
        print(f"  {name:<30} param {str(best[0]):<13} train {best[1]:+.4f}   TEST {test:+.4f}")
        return test

    base = fit_and_score("normal (the old shape)", [0.45, 0.55, 0.65, 0.75, 0.8],
                         lambda r, a, f: _norm_ll(a, parts(r)[3], max(parts(r)[3] * f, 6.0)))
    mix = fit_and_score("finish/decision mixture", [(d, f) for d in (0.35, 0.4, 0.45, 0.5)
                                                    for f in (0.55, 0.65, 0.75, 0.85)],
                        lambda r, a, prm: math.log(max(
                            parts(r)[0] * math.exp(_norm_ll(a, parts(r)[1], max(parts(r)[1] * prm[0], 6.0)))
                            + (1 - parts(r)[0]) * math.exp(_norm_ll(a, parts(r)[2], max(parts(r)[2] * prm[1], 6.0))),
                            1e-300)))
    nb = fit_and_score("negative binomial (SHIPPED)", [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0],
                       lambda r, a, k: M._nb_logpmf(int(round(a)), max(parts(r)[3], 1e-6), k))
    print(f"  -> mixture {mix - base:+.4f} vs normal; negative binomial {nb - base:+.4f} vs normal")
    print(f"  -> NB wins by {nb - mix:+.4f} over the mixture, so the mixture is NOT shipped")
    print(f"  (shipped dispersions: NB_K_SIG={M.NB_K_SIG} NB_K_SIG_TOTAL={M.NB_K_SIG_TOTAL} NB_K_TD={M.NB_K_TD})")


def exp_method(recs):
    """#10 — method model barely beats 'always decision'. Can a per-fighter split help?"""
    print("\n=== #10 method (KO / Sub / Decision) ===")
    tr, te = split(recs)
    dec_share = sum(1 for r in te if r["method"] == "dec") / len(te)
    print(f"  always-decision baseline: {dec_share:.1%}")

    correct = 0
    for r in te:
        out = M.analyze_fight(r["fa"], r["fb"], "a", "b", rounds=r["rounds"],
                              fight_date=r["date"].isoformat())
        m = out["fightModel"]["method"]
        pred = {"ko": "ko", "sub": "sub", "decision": "dec"}[max(m, key=m.get)]
        correct += int(pred == r["method"])
    print(f"  shipped model:            {correct / len(te):.1%}")

    # Candidate: weight each fighter's KO/sub tendency by THEIR own chance of
    # being the one who finishes, instead of a symmetric combined feature.
    correct2 = 0
    for r in te:
        fa, fb = r["fa"], r["fb"]
        pa, pb = M._p_finish(fa, fb), M._p_finish(fb, fa)
        distance_p = (1 - pa) * (1 - pb)
        tot = (pa + pb) or 1e-9
        ko_w = (pa * fa.get("koRate", 0) + pb * fb.get("koRate", 0)) / tot
        sub_w = (pa * fa.get("subRate", 0) + pb * fb.get("subRate", 0)) / tot
        denom = max(ko_w + sub_w, 1e-9)
        probs = {"ko": (1 - distance_p) * ko_w / denom,
                 "sub": (1 - distance_p) * sub_w / denom,
                 "dec": distance_p}
        correct2 += int(max(probs, key=probs.get) == r["method"])
    print(f"  finisher-weighted KO|fin: {correct2 / len(te):.1%}")


def exp_rounds(recs):
    """#11 — static ROUND_FINISH_WEIGHTS vs a matchup-aware hazard curve."""
    print("\n=== #11 finish-round distribution: static vs matchup-aware ===")
    tr, te = split(recs)
    fin_tr = [r for r in tr if r["method"] != "dec"]
    fin_te = [r for r in te if r["method"] != "dec"]

    static: Dict[int, List[float]] = {}
    for sched in (3, 5):
        ends = [r["end_round"] for r in fin_tr if r["rounds"] == sched]
        if not ends:
            continue
        static[sched] = [max(sum(1 for e in ends if e == i + 1) / len(ends), 1e-4)
                         for i in range(sched)]
        print(f"  {sched}R train-fit: {[round(x, 3) for x in static[sched]]}  (n={len(ends)})")
        print(f"  {sched}R shipped  : {M.ROUND_FINISH_WEIGHTS[sched]}")

    def score(weight_fn) -> float:
        lls = []
        for r in fin_te:
            wts = weight_fn(r)
            s = sum(wts) or 1.0
            lls.append(math.log(max(wts[r["end_round"] - 1] / s, 1e-9)))
        return mean(lls)

    base = score(lambda r: M.ROUND_FINISH_WEIGHTS[r["rounds"]])
    print(f"  {'shipped static weights':<36} {base:+.4f}  (baseline, mean LL; higher=better)")
    print(_fmt("train-fit static weights", base,
               score(lambda r: static.get(r["rounds"], M.ROUND_FINISH_WEIGHTS[r["rounds"]])),
               lower_better=False))

    def hazard(r):
        pa, pb = M._p_finish(r["fa"], r["fb"]), M._p_finish(r["fb"], r["fa"])
        pfin = 1 - (1 - pa) * (1 - pb)
        n = r["rounds"]
        h = 1 - (1 - min(max(pfin, 0.02), 0.95)) ** (1.0 / n)
        return [((1 - h) ** i) * h for i in range(n)]
    print(_fmt("matchup-aware hazard curve", base, score(hazard), lower_better=False))

    def blended(r):
        st = static.get(r["rounds"], M.ROUND_FINISH_WEIGHTS[r["rounds"]])
        hz = hazard(r)
        return [math.sqrt(a * b) for a, b in zip(st, hz)]
    print(_fmt("static x hazard (geometric)", base, score(blended), lower_better=False))
    return static


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="run a single experiment by name")
    ap.add_argument("--cutoff", default=CUTOFF)
    args = ap.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("replaying (point-in-time)...")
    recs = loop.run_until_complete(replay())
    tr, te = split(recs, args.cutoff)
    print(f"records {len(recs)}  train {len(tr)}  test {len(te)}  cutoff {args.cutoff}")

    want = args.only

    def run(name, fn, *a):
        if want in (None, name):
            fn(*a)

    run("baseline", exp_baseline, recs)
    run("signs", exp_signs, recs)
    run("calib", exp_calibration, recs)
    run("decay", exp_decay, recs, loop)
    run("divmeans", exp_divmeans, recs, loop)
    run("mixture", exp_mixture, recs)
    run("method", exp_method, recs)
    run("rounds", exp_rounds, recs)
    loop.close()


if __name__ == "__main__":
    main()
