"""Offline backtesting harness — measures how accurate the model's projections
and probabilities actually are against real results.

No look-ahead / data leakage:
  * Pitcher/batter starts on date D are projected from game-log rows **before D**.
  * Opponent offense (K%/BB%/runs) is accumulated **as of D** from the team's
    game log (point-in-time), not season-final totals.
  * "Skill" (Statcast K%) and the run-prevention/league-average fallbacks come
    from the **prior** season — fully known before the backtest season starts.

What it measures (per market): projection MAE & bias, and probability
calibration (Brier score + a reliability table). It is NOT a betting-ROI
backtest — that needs historical closing lines (a paid odds feed). 

Usage:
    python backtest.py --season 2025 --pitchers 25
    python backtest.py --sweep           # tune the walk negative-binomial dispersion
    python backtest.py --games 40 --batters 20
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from backend import analysis, mlb, savant


# --------------------------------------------------------------------------- point-in-time helpers

async def team_offense_asof(
    team_id: int, season: int, date: str, prior_teams: Dict[int, Any], lg_k: float, lg_bb: float
) -> Dict[str, float]:
    """A team's offensive rates as of ``date`` (sum of prior games), falling back
    to prior-season figures before there's enough sample."""
    try:
        log = await mlb.get_team_hitting_log(team_id, season)
    except Exception:
        log = []
    prior = [g for g in log if (g.get("date") or "") < date]
    pa = sum(g["plateAppearances"] for g in prior)
    games = len(prior)
    if pa >= 60 and games >= 10:
        return {
            "kRate": sum(g["strikeOuts"] for g in prior) / pa,
            "bbRate": sum(g["baseOnBalls"] for g in prior) / pa,
            "runsPerGame": sum(g["runs"] for g in prior) / games,
        }
    t = prior_teams.get(team_id, {})
    return {
        "kRate": t.get("kRate", lg_k),
        "bbRate": t.get("bbRate", lg_bb),
        "runsPerGame": t.get("runsPerGame", analysis.DEFAULT_RUNS_PER_GAME),
    }


# --------------------------------------------------------------------------- data collection

async def collect_starter_gamelogs(season: int, n: int) -> List[Tuple[int, List[Dict[str, Any]]]]:
    """Sample ``n`` starting pitchers (from the Statcast leaderboard — used only
    to pick who to test) with enough starts to replay."""
    try:
        board = await savant._load_leaderboard(season)
    except Exception as e:
        print(f"  could not load pitcher list from Savant: {e!r}")
        return []
    pairs: List[Tuple[int, List[Dict[str, Any]]]] = []
    for pid in sorted(board.keys()):
        if len(pairs) >= n:
            break
        try:
            glog = await mlb.get_pitcher_gamelog(pid, season)
        except Exception:
            continue
        if len(glog) >= analysis.MIN_STARTS + 8:
            pairs.append((pid, glog))
    return pairs


# --------------------------------------------------------------------------- pitcher prop replay

async def replay_pitcher_prop(
    pairs: List[Tuple[int, List[Dict[str, Any]]]],
    season: int,
    prior_rates: Dict[str, Any],
    stat_key: str,
    use_skill: bool,
) -> List[Tuple[float, float, float, Optional[float]]]:
    """``(projection, actual, naive, trials)`` for every replayed start, point-in-time.

    ``trials`` is the model's expected batters faced (binomial ``n`` for the
    strikeout law); ``None`` for walks (which use the negative binomial)."""
    lg_k = prior_rates.get("leagueAvgK", 0.225) or 0.225
    lg_bb = prior_rates.get("leagueAvgBB", 0.085) or 0.085
    prior_teams = prior_rates.get("teams", {})

    records: List[Tuple[float, float, float, Optional[float]]] = []
    for pid, glog in pairs:
        prior_skill = None
        if use_skill:
            try:
                prior_skill = await savant.get_pitcher_skill(pid, season - 1)
            except Exception:
                prior_skill = None

        for i in range(analysis.MIN_STARTS, len(glog)):
            before, actual_row = glog[:i], glog[i]
            opp_id = actual_row.get("opponentId")
            date = actual_row.get("date") or ""
            off = await team_offense_asof(opp_id, season, date, prior_teams, lg_k, lg_bb)
            team_rates = {season: {
                "teams": {opp_id: {"kRate": off["kRate"], "bbRate": off["bbRate"]}},
                "leagueAvgK": lg_k, "leagueAvgBB": lg_bb,
            }}
            kwargs: Dict[str, Any] = dict(
                pitcher_name="bt", gamelog=before, opponent_id=opp_id,
                opponent_name=actual_row.get("opponentName", ""), is_home=actual_row.get("isHome", False),
                team_rates_by_season=team_rates, current_season=season,
            )
            pick = (analysis.analyze_strikeouts(pitcher_skill=prior_skill, **kwargs)
                    if use_skill else analysis.analyze_walks(**kwargs))
            if pick is None:
                continue
            naive = mean(r.get(stat_key, 0) for r in before)
            records.append((pick["projection"], float(actual_row.get(stat_key, 0)),
                            naive, pick.get("expectedBF")))
    return records


# --------------------------------------------------------------------------- batter prop replay

# (prop_type, stat_key, line, bernoulli) — mirrors backend.main.BATTER_PROPS,
# minus the odds-market/park-factor wiring (neutral here: tests the core
# recent-form projection point-in-time).
BATTER_PROP_SPECS = [
    ("hits", "hits", 0.5, True),
    ("totalBases", "totalBases", 1.5, False),
    ("homeRuns", "homeRuns", 0.5, True),
]


async def replay_batter_prop(
    season: int, n_batters: int, prop_type: str, stat_key: str, line: float, bernoulli: bool
) -> Tuple[List[Tuple[float, float, float]], List[float]]:
    """Projection accuracy for a sample of qualified hitters (opponent starter /
    park neutral — tests the core recent-form projection).

    Returns ``(records, model_probs)`` where ``model_probs`` are the model's own
    P(Over ``line``) for ``prop_type`` (binomial for hits/HR, Poisson for TB), so
    calibration reflects the real model rather than a re-derived distribution."""
    try:
        c = mlb.client()
        r = await c.get("/stats", params={
            "stats": "season", "group": "hitting", "season": season, "sportId": 1,
            "playerPool": "qualified", "limit": n_batters * 2,
        })
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
    except Exception as e:
        print(f"  could not load hitter list: {e!r}")
        return [], []

    records: List[Tuple[float, float, float]] = []
    model_probs: List[float] = []
    count = 0
    for sp in splits:
        if count >= n_batters:
            break
        pid = sp.get("player", {}).get("id")
        if not pid:
            continue
        try:
            glog = await mlb.get_batter_gamelog(pid, season)
        except Exception:
            continue
        if len(glog) < analysis.BATTER_MIN_GAMES + 10:
            continue
        count += 1
        for i in range(analysis.BATTER_MIN_GAMES, len(glog)):
            before, actual_row = glog[:i], glog[i]
            pick = analysis.analyze_batter_prop(
                prop_type, stat_key, stat_key, stat_key, "bt", before,
                opp_team_id=actual_row.get("opponentId"), opp_pitcher_name="x",
                is_home=actual_row.get("isHome", False),
                default_line=line, bernoulli=bernoulli,
            )
            if pick is None:
                continue
            naive = mean(r.get(stat_key, 0) for r in before)
            records.append((pick["projection"], float(actual_row.get(stat_key, 0)), naive))
            model_probs.append(pick["modelProb"])  # P(Over `line`), as graded in production
    return records, model_probs


# --------------------------------------------------------------------------- game (total + moneyline) replay

def _sample_dates(season: int, n: int) -> List[str]:
    start, end = datetime.date(season, 4, 1), datetime.date(season, 9, 26)
    span = (end - start).days
    return [(start + datetime.timedelta(days=int(span * i / max(n - 1, 1)))).isoformat() for i in range(n)]


async def _scored_games(date: str) -> List[Dict[str, Any]]:
    c = mlb.client()
    r = await c.get("/schedule", params={"sportId": 1, "date": date, "hydrate": "probablePitcher,team"})
    r.raise_for_status()
    out: List[Dict[str, Any]] = []
    for d in r.json().get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            t = g.get("teams", {})
            h, a = t.get("home", {}), t.get("away", {})
            hp, ap = h.get("probablePitcher"), a.get("probablePitcher")
            if h.get("score") is None or a.get("score") is None or not hp or not ap:
                continue
            out.append({
                "date": date,
                "homeId": h.get("team", {}).get("id"), "awayId": a.get("team", {}).get("id"),
                "homeScore": h["score"], "awayScore": a["score"],
                "homePid": hp.get("id"), "awayPid": ap.get("id"),
            })
    return out


async def _starter_ra9_asof(pid: int, season: int, date: str) -> Optional[float]:
    try:
        glog = await mlb.get_pitcher_gamelog(pid, season)
    except Exception:
        return None
    before = [r for r in glog if (r.get("date") or "") < date]
    return analysis._starter_ra9_projection(before)


async def replay_games(season: int, n_games: int) -> Tuple[List[Tuple[float, float]], List[Tuple[float, int]]]:
    """Returns (total_records[(proj,actual)], ml_records[(home_win_prob, home_won)])."""
    prior_rates = await mlb.get_team_rates(season - 1)
    prior_prev = await mlb.get_team_run_prevention(season - 1)
    lg_k = prior_rates.get("leagueAvgK", 0.225) or 0.225
    lg_bb = prior_rates.get("leagueAvgBB", 0.085) or 0.085
    prior_teams = prior_rates.get("teams", {})
    prior_prev_teams = prior_prev.get("teams", {})

    games: List[Dict[str, Any]] = []
    for date in _sample_dates(season, 16):
        if len(games) >= n_games:
            break
        try:
            games.extend(await _scored_games(date))
        except Exception:
            continue
    games = games[:n_games]

    totals: List[Tuple[float, float]] = []
    mls: List[Tuple[float, int]] = []
    for g in games:
        date = g["date"]
        home_off = await team_offense_asof(g["homeId"], season, date, prior_teams, lg_k, lg_bb)
        away_off = await team_offense_asof(g["awayId"], season, date, prior_teams, lg_k, lg_bb)
        home_sra = await _starter_ra9_asof(g["homePid"], season, date)
        away_sra = await _starter_ra9_asof(g["awayPid"], season, date)
        home_prev = {"runsAllowedPerGame": prior_prev_teams.get(g["homeId"], {}).get(
            "runsAllowedPerGame", analysis.DEFAULT_RUNS_PER_GAME)}
        away_prev = {"runsAllowedPerGame": prior_prev_teams.get(g["awayId"], {}).get(
            "runsAllowedPerGame", analysis.DEFAULT_RUNS_PER_GAME)}

        gm = analysis.game_model(
            {"runsPerGame": home_off["runsPerGame"]}, {"runsPerGame": away_off["runsPerGame"]},
            home_prev, away_prev, home_starter_ra9=home_sra, away_starter_ra9=away_sra,
        )
        totals.append((gm["homeProjRuns"] + gm["awayProjRuns"], float(g["homeScore"] + g["awayScore"])))
        mls.append((gm["homeWinProb"], 1 if g["homeScore"] > g["awayScore"] else 0))
    return totals, mls


# --------------------------------------------------------------------------- metrics / reporting

def _brier(preds: List[float], outs: List[float]) -> float:
    return mean((p - o) ** 2 for p, o in zip(preds, outs))


def reliability_table(preds: List[float], outs: List[float], bins: int = 5) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(preds) if (lo <= p < hi or (b == bins - 1 and p >= hi))]
        if idx:
            rows.append({"range": f"{lo:.0%}-{hi:.0%}", "n": len(idx),
                         "pred": mean(preds[i] for i in idx), "actual": mean(outs[i] for i in idx)})
    return rows


def report_count(label: str, records: List[Tuple], line: float,
                 dispersion: Optional[float], model_preds: Optional[List[float]] = None,
                 dist_label: Optional[str] = None) -> None:
    if not records:
        print(f"\n=== {label} ===\n  no replayed samples")
        return
    projs = [r[0] for r in records]
    actuals = [r[1] for r in records]
    naives = [r[2] for r in records]
    # Per-record binomial trials (expected BF), when the replay captured them.
    trials = [(int(round(r[3])) if len(r) > 3 and r[3] else None) for r in records]
    used_binom = any(t is not None for t in trials)
    mae = mean(abs(p - a) for p, a in zip(projs, actuals))
    bias = mean(p - a for p, a in zip(projs, actuals))
    naive_mae = mean(abs(nv - a) for nv, a in zip(naives, actuals))
    # Probability precedence: caller-supplied model_preds (e.g. batter binomial)
    # > per-record binomial trials (strikeouts) > the projection's distribution.
    if model_preds is not None:
        preds = model_preds
    elif used_binom:
        preds = [analysis.count_prob_over(line, p, dispersion, t) for p, t in zip(projs, trials)]
    else:
        preds = [analysis.count_prob_over(line, p, dispersion) for p in projs]
    outs = [1.0 if a > line else 0.0 for a in actuals]
    brier = _brier(preds, outs)
    base = mean(outs)
    brier_base = _brier([base] * len(outs), outs)
    if dist_label:
        dist = dist_label
    else:
        dist = "Binomial(BF)" if used_binom else ("Poisson" if dispersion is None else f"neg-binom r={dispersion}")
    print(f"\n=== {label} ({len(records)} samples, {dist}) ===")
    print(f"  projection MAE  {mae:.2f}   (naive {naive_mae:.2f})")
    print(f"  bias            {bias:+.2f}   ({'over' if bias > 0 else 'under'}-projecting)")
    print(f"  calibration @ {line}:  Brier {brier:.4f}  (base-rate {brier_base:.4f}; lower & < base = good)")
    for row in reliability_table(preds, outs):
        flag = "" if abs(row["pred"] - row["actual"]) < 0.07 else "  <- off"
        print(f"     {row['range']:>9} n={row['n']:<5} pred {row['pred']:.0%} actual {row['actual']:.0%}{flag}")


def report_total(totals: List[Tuple[float, float]], line: float = 8.5) -> None:
    if not totals:
        print("\n=== Game Total ===\n  no games")
        return
    projs = [t[0] for t in totals]
    actuals = [t[1] for t in totals]
    mae = mean(abs(p - a) for p, a in zip(projs, actuals))
    bias = mean(p - a for p, a in zip(projs, actuals))
    preds = [analysis.prob_over(line, p) for p in projs]
    outs = [1.0 if a > line else 0.0 for a in actuals]
    print(f"\n=== Game Total ({len(totals)} games, calibration ×{analysis.TOTAL_CALIBRATION}) ===")
    print(f"  total MAE  {mae:.2f}   bias {bias:+.2f}   (target ~0; nudge TOTAL_CALIBRATION if biased)")
    # What calibration factor would zero out the residual bias on this sample.
    proj_mean = mean(projs)
    if proj_mean > 0:
        suggested = analysis.TOTAL_CALIBRATION * (proj_mean - bias) / proj_mean
        print(f"  suggested TOTAL_CALIBRATION for zero bias here: ×{suggested:.3f}")
    print(f"  calibration @ {line}:  Brier {_brier(preds, outs):.4f}  (over rate {mean(outs):.0%})")
    print("  dispersion sweep (Brier @ line; lower=better — run totals are over-dispersed):")
    for r in (None, 20.0, 14.0, 10.0, 8.0, 6.0):
        sp = [analysis.count_prob_over(line, p, r) for p in projs]
        tag = "Poisson" if r is None else f"NB r={r}"
        print(f"     {tag:>10}: {_brier(sp, outs):.4f}")


def report_moneyline(mls: List[Tuple[float, int]]) -> None:
    if not mls:
        print("\n=== Moneyline ===\n  no games")
        return
    preds = [m[0] for m in mls]
    outs = [float(m[1]) for m in mls]
    brier = _brier(preds, outs)
    base = mean(outs)
    print(f"\n=== Moneyline / Home win ({len(mls)} games) ===")
    print(f"  predicted home win {mean(preds):.1%}  | actual {base:.1%}")
    print(f"  Brier {brier:.4f}  (base-rate {_brier([base] * len(outs), outs):.4f})")
    for row in reliability_table(preds, outs, bins=4):
        flag = "" if abs(row["pred"] - row["actual"]) < 0.10 else "  <- off"
        print(f"     {row['range']:>9} n={row['n']:<4} pred {row['pred']:.0%} actual {row['actual']:.0%}{flag}")


# --------------------------------------------------------------------------- main

async def main_async(args: argparse.Namespace) -> None:
    season = args.season
    print(f"Backtesting {season} (point-in-time; prior-season skill/fallbacks)...")
    prior_rates = await mlb.get_team_rates(season - 1)

    pairs = await collect_starter_gamelogs(season, args.pitchers)
    print(f"  {len(pairs)} starters sampled")

    k_recs = await replay_pitcher_prop(pairs, season, prior_rates, "strikeOuts", use_skill=True)
    report_count("Strikeouts", k_recs, line=5.5, dispersion=analysis.K_DISPERSION)

    bb_recs = await replay_pitcher_prop(pairs, season, prior_rates, "baseOnBalls", use_skill=False)
    if args.sweep:
        print("\n=== Walk dispersion sweep (Brier @ 1.5; lower is better) ===")
        line = 1.5
        outs = [1.0 if rec[1] > line else 0.0 for rec in bb_recs]
        for r in (None, 8.0, 5.0, 4.0, 3.0, 2.5, 2.0, 1.5):
            preds = [analysis.count_prob_over(line, rec[0], r) for rec in bb_recs]
            tag = "Poisson" if r is None else f"r={r}"
            print(f"  {tag:>9}:  Brier {_brier(preds, outs):.4f}")
    report_count("Walks", bb_recs, line=1.5, dispersion=analysis.BB_DISPERSION)

    if not args.quick:
        labels = {"hits": "Batter Hits", "totalBases": "Batter Total Bases", "homeRuns": "Batter Home Runs"}
        for prop_type, stat_key, line, bernoulli in BATTER_PROP_SPECS:
            bat_recs, bat_preds = await replay_batter_prop(season, args.batters, prop_type, stat_key, line, bernoulli)
            dist_label = "Binomial(AB)" if bernoulli else "Poisson"
            report_count(labels[prop_type], bat_recs, line=line, dispersion=None, model_preds=bat_preds,
                          dist_label=dist_label)

        totals, mls = await replay_games(season, args.games)
        report_total(totals)
        report_moneyline(mls)

    print("\nMeasures projection accuracy + calibration, not betting ROI (needs paid closing lines).")
    await mlb.close()
    await savant.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest the Sharp Slate model against real results.")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--pitchers", type=int, default=25)
    ap.add_argument("--batters", type=int, default=15)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--sweep", action="store_true", help="sweep the walk negative-binomial dispersion")
    ap.add_argument("--quick", action="store_true", help="pitcher props only (skip batter/game replays)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
