"""Backfill the History view for days that were never tracked live.

WHAT THIS IS — AND IS NOT
=========================
``track.py`` records what the model predicted *and the price it could have been
bet at*, which is what makes ROI and CLV meaningful. Neither can be recovered
after the fact: The Odds API's free plan serves upcoming events only, so a past
date matches no market at all.

So this script backfills **accuracy only**. Every entry it writes is stamped
``accuracyOnly: true`` / ``backfilled: true``, carries ``bets: 0`` with null
units/ROI/CLV, and the UI labels those days so they can never be mistaken for a
real betting record. What you get is W-L and Brier — "was the model right" — not
"did following it make money".

NO LOOK-AHEAD
=============
The naive version of this is worthless: ``track.py snapshot --date <past>`` calls
the live analyze path, which pulls a pitcher's FULL season game log. Backfilling
July with it would project a start using outings from the following August. This
script instead reuses ``backtest.py``'s point-in-time replay:

  * a pitcher's game log is truncated to rows strictly BEFORE the game date
  * opponent offense (K%/BB%/runs) is accumulated as of that date
  * starter RA9 comes from prior starts only
  * run-prevention and league baselines come from the PRIOR season
  * MMA fighter rate profiles are rebuilt bout-by-bout in date order

Usage:

    python scripts/backfill_history.py --start 2026-06-28 --end 2026-09-10
    python scripts/backfill_history.py --start 2026-06-28 --end 2026-09-10 --sport mma
    python scripts/backfill_history.py --start ... --end ... --dry-run

Existing graded files are never overwritten unless --force is passed: a day that
was tracked live is strictly better evidence than anything reconstructed here.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backtest as BT
import track as T
from backend import analysis, mlb


def _dates(start: str, end: str) -> List[str]:
    d0 = datetime.date.fromisoformat(start)
    d1 = datetime.date.fromisoformat(end)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _payload(date: str, sport: str, markets: Dict[str, T.Tally],
             n_events: int, note: str) -> Dict[str, Any]:
    """Graded-file payload in the same shape track.py writes, minus any betting
    record (there are no historical prices to bet at)."""
    out: Dict[str, Any] = {
        "date": date,
        "sport": sport,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        # The flags the UI keys off to label these days. Without them a
        # reconstructed day is indistinguishable from one we actually tracked.
        "backfilled": True,
        "accuracyOnly": True,
        "backfillNote": note,
    }
    for name, tally in markets.items():
        out[name] = tally.summary()
    out["overall"] = {"bets": 0, "units": None, "roi": None, "clv": None,
                      "beatClose": None, "clvN": 0, "clvSum": 0, "beatN": 0}
    out["pending"] = 0
    out["games"] = n_events
    return out


# --------------------------------------------------------------------------- MLB

async def backfill_mlb_date(date: str, season_cache: Dict[int, Any]) -> Optional[Dict[str, Any]]:
    """One day of MLB, projected point-in-time and graded against the box scores."""
    season = int(date[:4])
    if season not in season_cache:
        prior_rates = await mlb.get_team_rates(season - 1)
        prior_prev = await mlb.get_team_run_prevention(season - 1)
        season_cache[season] = {
            "lg_k": prior_rates.get("leagueAvgK", 0.225) or 0.225,
            "lg_bb": prior_rates.get("leagueAvgBB", 0.085) or 0.085,
            "teams": prior_rates.get("teams", {}),
            "prev": prior_prev.get("teams", {}),
        }
    ctx = season_cache[season]

    games = await BT._scored_games(date)   # Final games only, both starters named
    if not games:
        return None

    k_tally, total_tally, ml_tally = T.Tally(), T.Tally(), T.Tally()
    bias: List[float] = []
    graded_any = False

    for g in games:
        home_off = await BT.team_offense_asof(g["homeId"], season, date, ctx["teams"], ctx["lg_k"], ctx["lg_bb"])
        away_off = await BT.team_offense_asof(g["awayId"], season, date, ctx["teams"], ctx["lg_k"], ctx["lg_bb"])

        # ---- strikeouts, per starter, from starts BEFORE this date ----
        try:
            box = await mlb.get_boxscore(g["gamePk"])
        except Exception:
            box = None
        for pid, opp_id, opp_off, is_home in (
            (g["homePid"], g["awayId"], away_off, True),
            (g["awayPid"], g["homeId"], home_off, False),
        ):
            try:
                glog = await mlb.get_pitcher_gamelog(pid, season)
            except Exception:
                continue
            before = [r for r in glog if (r.get("date") or "") < date]
            if len(before) < analysis.MIN_STARTS:
                continue
            team_rates = {season: {
                "teams": {opp_id: {"kRate": opp_off["kRate"], "bbRate": opp_off["bbRate"]}},
                "leagueAvgK": ctx["lg_k"], "leagueAvgBB": ctx["lg_bb"],
            }}
            pick = analysis.analyze_strikeouts(
                pitcher_name="bf", gamelog=before, opponent_id=opp_id,
                opponent_name="", is_home=is_home,
                team_rates_by_season=team_rates, current_season=season,
            )
            if pick is None:
                continue
            actual = _actual_k(box, pid)
            if actual is None:
                continue
            won = T._won(pick["side"], pick["line"], actual)
            k_tally.add(won, pick.get("modelProb"))
            graded_any = True

        # ---- game model: total + moneyline, all inputs as-of ----
        home_sra = await BT._starter_ra9_asof(g["homePid"], season, date)
        away_sra = await BT._starter_ra9_asof(g["awayPid"], season, date)
        gm = analysis.game_model(
            {"runsPerGame": home_off["runsPerGame"]}, {"runsPerGame": away_off["runsPerGame"]},
            {"runsAllowedPerGame": ctx["prev"].get(g["homeId"], {}).get(
                "runsAllowedPerGame", analysis.DEFAULT_RUNS_PER_GAME)},
            {"runsAllowedPerGame": ctx["prev"].get(g["awayId"], {}).get(
                "runsAllowedPerGame", analysis.DEFAULT_RUNS_PER_GAME)},
            home_starter_ra9=home_sra, away_starter_ra9=away_sra,
        )
        proj_total = gm["homeProjRuns"] + gm["awayProjRuns"]
        actual_total = float(g["homeScore"] + g["awayScore"])
        bias.append(proj_total - actual_total)

        # Graded at the standard 8.5 line, the same reference backtest.py uses;
        # with no market there is no real line to grade against.
        side = "over" if proj_total >= 8.5 else "under"
        p_over = analysis.count_prob_over(8.5, proj_total, analysis.TOTAL_DISPERSION)
        prob = p_over if side == "over" else 1.0 - p_over
        total_tally.add(T._won(side, 8.5, actual_total), prob)

        home_won = g["homeScore"] > g["awayScore"]
        pick_home = gm["homeWinProb"] >= 0.5
        ml_tally.add(pick_home == home_won,
                     gm["homeWinProb"] if pick_home else 1 - gm["homeWinProb"])
        graded_any = True

    if not graded_any:
        return None

    payload = _payload(date, "mlb",
                       {"strikeouts": k_tally, "total": total_tally, "moneyline": ml_tally},
                       len(games),
                       "Reconstructed point-in-time (game logs truncated to before this date, "
                       "opponent offense as-of, prior-season baselines). Accuracy only — no "
                       "historical prices exist for past dates, so no ROI or CLV. Totals and "
                       "moneyline are graded at a reference 8.5 line / 50% threshold, not a "
                       "real market line.")
    payload["totalBias"] = round(mean(bias), 3) if bias else None
    return payload


def _actual_k(box: Optional[Dict[str, Any]], pid: int) -> Optional[int]:
    return T._pitcher_k(box, pid) if box else None


# --------------------------------------------------------------------------- MMA

async def backfill_mma(dates: List[str]) -> Dict[str, Dict[str, Any]]:
    """All UFC cards in the window, from mma_experiments' point-in-time replay.

    That replay rebuilds each fighter's rate profile from bouts *before* the one
    being predicted, which is exactly the guarantee this backfill needs.
    """
    import mma_experiments as E
    from backend import mma_analysis as M

    recs = await E.replay()
    wanted = set(dates)
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in recs:
        d = r["date"].isoformat()
        if d in wanted:
            by_date.setdefault(d, []).append(r)

    out: Dict[str, Dict[str, Any]] = {}
    for date, rows in sorted(by_date.items()):
        ml, method, distance = T.Tally(), T.Tally(), T.Tally()
        for r in rows:
            res = M.analyze_fight(r["fa"], r["fb"], "a", "b", rounds=r["rounds"],
                                  fight_date=date)
            fm = res["fightModel"]
            # winner
            pick_a = fm["aWinProb"] >= 0.5
            a_won = bool(r["a_won"])
            ml.add(pick_a == a_won, fm["aWinProb"] if pick_a else fm["bWinProb"])
            # method (argmax of KO / Sub / Decision)
            mp = fm["method"]
            pred = {"ko": "ko", "sub": "sub", "decision": "dec"}[max(mp, key=mp.get)]
            method.add(pred == r["method"], max(mp.values()))
            # distance (did it reach the judges)
            went = r["method"] == "dec"
            pick_dist = fm["distanceProb"] >= 0.5
            distance.add(pick_dist == went,
                         fm["distanceProb"] if pick_dist else 1 - fm["distanceProb"])
        out[date] = _payload(date, "mma",
                             {"moneyline": ml, "method": method, "distance": distance},
                             len(rows),
                             "Reconstructed point-in-time (fighter profiles built from prior bouts only). "
                             "Accuracy only — no historical prices, so no ROI or CLV. "
                             "Caveat: the winner model's coefficients were fit on a bout set that "
                             "includes these fights (~1% of training rows), so this is mildly "
                             "in-sample — the same property mma_backtest.py has.")
    return out


# --------------------------------------------------------------------------- driver

async def main_async(args: argparse.Namespace) -> None:
    dates = _dates(args.start, args.end)
    print(f"Backfilling {len(dates)} days: {args.start} -> {args.end}  (sport={args.sport})")
    print("Accuracy only: no historical prices exist, so ROI/CLV stay null.\n")
    written = skipped = empty = 0

    def _write(path: Path, payload: Dict[str, Any], label: str) -> None:
        nonlocal written, skipped
        if path.exists() and not args.force:
            print(f"  skip {label}: already graded (live record wins)")
            skipped += 1
            return
        if args.dry_run:
            print(f"  DRY  {label}: {_summarize(payload)}")
            written += 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  ok   {label}: {_summarize(payload)}")
        written += 1

    if args.sport in ("mlb", "both"):
        season_cache: Dict[int, Any] = {}
        for date in dates:
            try:
                payload = await backfill_mlb_date(date, season_cache)
            except Exception as e:
                print(f"  err  {date} mlb: {e!r}")
                continue
            if payload is None:
                empty += 1
                continue
            _write(Path(T._graded_path(date, "mlb")), payload, f"{date} mlb")

    if args.sport in ("mma", "both"):
        cards = await backfill_mma(dates)
        for date, payload in cards.items():
            _write(Path(T._graded_path(date, "mma")), payload, f"{date} mma")
        empty += len(dates) - len(cards)

    await mlb.close()
    print(f"\n{written} written{' (dry run)' if args.dry_run else ''}, "
          f"{skipped} skipped (already graded), {empty} days with nothing to grade.")


def _summarize(p: Dict[str, Any]) -> str:
    bits = []
    for k in ("strikeouts", "total", "moneyline", "method", "distance"):
        m = p.get(k)
        if m and (m["w"] + m["l"]):
            bits.append(f"{k[:4]} {m['w']}-{m['l']}")
    return ", ".join(bits) or "nothing graded"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--sport", default="both", choices=["mlb", "mma", "both"])
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing graded files (they are live records — think twice)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
