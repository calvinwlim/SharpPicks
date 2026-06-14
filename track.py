"""Track today's picks and grade them against the day's actual results.

This is the *live* counterpart to ``backtest.py`` (which replays past seasons):
it records the predictions the app makes today, then — once games go final —
compares them to what actually happened. Two steps, no database; just dated
JSON snapshots under ``tracking/``:

    python track.py snapshot                 # save today's predictions
    python track.py snapshot --date 2026-06-14
    python track.py grade                     # score today's snapshot vs results
    python track.py grade --date 2026-06-14

``snapshot`` reuses the exact app analysis (``backend.main._analyze_mlb``), so
what you grade is what the UI showed. ``grade`` pulls final scores from the
schedule and actual strikeouts from each game's boxscore. It needs network
(statsapi.mlb.com); run ``grade`` after the games are final (late night / next
morning). Games not yet final are reported as pending and can be re-graded.

Graded markets: pitcher strikeout props, the game total, and the moneyline
(the model's pick = whichever side it gives the higher win probability). Like
the backtest, this measures model accuracy, not betting ROI.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
from statistics import mean
from typing import Any, Dict, List, Optional

from backend import main as app
from backend import mlb

TRACK_DIR = "tracking"


def _today() -> str:
    return datetime.date.today().isoformat()


def _path(date: str) -> str:
    return os.path.join(TRACK_DIR, f"{date}.json")


# --------------------------------------------------------------------------- snapshot

def _extract_predictions(res: Dict[str, Any], game: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the gradeable predictions out of one ``_analyze_mlb`` result."""
    # Map probable-pitcher name -> id so strikeout picks can be matched to a
    # boxscore line at grade time.
    name_to_id: Dict[str, int] = {}
    for side in ("home", "away"):
        pp = game[side].get("probablePitcher")
        if pp and pp.get("id") is not None:
            name_to_id[pp["name"]] = pp["id"]

    def ev(pick: Dict[str, Any]) -> Optional[float]:
        edge = pick.get("edge")
        return edge.get("evPct") if edge else None

    strikeouts = []
    for p in res.get("picks", []):
        if p.get("propType") != "strikeouts":
            continue
        strikeouts.append({
            "player": p["player"],
            "pitcherId": name_to_id.get(p["player"]),
            "side": p["side"],
            "line": p["line"],
            "projection": p["projection"],
            "modelProb": p["modelProb"],
            "evPct": ev(p),
        })

    gm = res.get("gameModel", {}) or {}
    total = None
    if gm.get("total"):
        t = gm["total"]
        total = {
            "side": t["side"], "line": t["line"], "projection": t["projection"],
            "modelProb": t["modelProb"], "evPct": ev(t),
        }

    moneyline = None
    if gm.get("homeWinProb") is not None:
        home_wp = gm["homeWinProb"]
        pick_side = "home" if home_wp >= 0.5 else "away"
        ml = gm.get("moneyline") or {}
        moneyline = {
            "pick": pick_side,
            "modelProb": round(max(home_wp, 1 - home_wp), 4),
            "homeWinProb": home_wp,
            "evPct": (ml.get(pick_side) or {}).get("evPct"),
        }

    return {
        "gamePk": game["gamePk"],
        "away": game["away"]["abbr"], "home": game["home"]["abbr"],
        "strikeouts": strikeouts, "total": total, "moneyline": moneyline,
    }


async def snapshot(date: str) -> None:
    games = await mlb.get_schedule(date)
    if not games:
        print(f"No games scheduled on {date}.")
        return

    print(f"Snapshotting {len(games)} games for {date} (running full analysis)...")
    entries: List[Dict[str, Any]] = []
    for g in games:
        label = f"{g['away']['abbr']} @ {g['home']['abbr']}"
        try:
            res = await app._analyze_mlb(g["gamePk"], date)
            entries.append(_extract_predictions(res, g))
            print(f"  ok   {label}")
        except Exception as e:
            print(f"  skip {label}: {e!r}")

    os.makedirs(TRACK_DIR, exist_ok=True)
    payload = {
        "date": date,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "games": entries,
    }
    with open(_path(date), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    n_k = sum(len(e["strikeouts"]) for e in entries)
    print(f"\nSaved {_path(date)}: {len(entries)} games, {n_k} strikeout picks. "
          f"Run `python track.py grade --date {date}` once games are final.")
    await mlb.close()


# --------------------------------------------------------------------------- grade

async def _final_scores(date: str) -> Dict[int, Dict[str, Any]]:
    """``{gamePk: {home, away, final}}`` for the date (scores when available)."""
    c = mlb.client()
    r = await c.get("/schedule", params={"sportId": 1, "date": date, "hydrate": "team"})
    r.raise_for_status()
    out: Dict[int, Dict[str, Any]] = {}
    for d in r.json().get("dates", []):
        for g in d.get("games", []):
            t = g.get("teams", {})
            out[g["gamePk"]] = {
                "home": t.get("home", {}).get("score"),
                "away": t.get("away", {}).get("score"),
                "final": g.get("status", {}).get("abstractGameState") == "Final",
            }
    return out


def _pitcher_k(box: Dict[str, Any], pid: int) -> Optional[int]:
    """Actual strikeouts thrown by ``pid`` in a boxscore, or ``None`` if they
    didn't pitch (scratched / not in this game)."""
    for side in ("home", "away"):
        player = box.get("teams", {}).get(side, {}).get("players", {}).get(f"ID{pid}")
        if player:
            pit = player.get("stats", {}).get("pitching", {})
            if pit:
                return int(pit.get("strikeOuts", 0) or 0)
    return None


def _won(side: str, line: float, actual: float) -> Optional[bool]:
    """Over/under result; ``None`` is a push (actual lands exactly on the line)."""
    if actual == line:
        return None
    return (actual > line) if side == "over" else (actual < line)


class Tally:
    """Win/loss/push record + Brier accumulator for one market."""

    def __init__(self) -> None:
        self.w = self.l = self.p = 0
        self.briers: List[float] = []

    def add(self, won: Optional[bool], model_prob: Optional[float]) -> None:
        if won is None:
            self.p += 1
        elif won:
            self.w += 1
        else:
            self.l += 1
        if model_prob is not None and won is not None:
            self.briers.append((model_prob - (1.0 if won else 0.0)) ** 2)

    def line(self, label: str) -> str:
        graded = self.w + self.l
        wr = f"{self.w / graded:.0%}" if graded else "—"
        brier = f"{mean(self.briers):.3f}" if self.briers else "—"
        push = f", {self.p} push" if self.p else ""
        return f"  {label:<12} {self.w}-{self.l}{push}  (win rate {wr}, Brier {brier})"


async def grade(date: str) -> None:
    try:
        with open(_path(date), encoding="utf-8") as f:
            snap = json.load(f)
    except FileNotFoundError:
        print(f"No snapshot at {_path(date)}. Run `python track.py snapshot --date {date}` first.")
        return

    finals = await _final_scores(date)
    k_tally, total_tally, ml_tally = Tally(), Tally(), Tally()
    total_proj: List[float] = []
    total_actual: List[float] = []
    pending = 0

    print(f"Grading {date} (snapshotted {snap.get('generatedAt', '?')})\n")
    for e in snap["games"]:
        pk = e["gamePk"]
        fin = finals.get(pk)
        label = f"{e['away']} @ {e['home']}"
        if not fin or not fin["final"] or fin["home"] is None:
            print(f"{label}: pending")
            pending += 1
            continue

        runs = fin["home"] + fin["away"]
        winner = "home" if fin["home"] > fin["away"] else "away"
        print(f"{label}: final {fin['away']}-{fin['home']} ({runs} runs, {winner} won)")

        if e["total"]:
            t = e["total"]
            won = _won(t["side"], t["line"], runs)
            total_tally.add(won, t["modelProb"])
            total_proj.append(t["projection"])
            total_actual.append(runs)
            mark = "PUSH" if won is None else ("WIN " if won else "LOSS")
            print(f"    total   {t['side']} {t['line']} (proj {t['projection']}) -> {runs}  [{mark}]")

        if e["moneyline"]:
            m = e["moneyline"]
            won = m["pick"] == winner
            ml_tally.add(won, m["modelProb"])
            print(f"    ML      {m['pick']} ({m['modelProb']:.0%}) -> {winner} won  "
                  f"[{'WIN ' if won else 'LOSS'}]")

        if e["strikeouts"]:
            box = await mlb.get_boxscore(pk)
            for k in e["strikeouts"]:
                pid = k.get("pitcherId")
                actual = _pitcher_k(box, pid) if pid else None
                if actual is None:
                    print(f"    K  {k['player']}: did not pitch — skipped")
                    continue
                won = _won(k["side"], k["line"], actual)
                k_tally.add(won, k["modelProb"])
                mark = "PUSH" if won is None else ("WIN " if won else "LOSS")
                print(f"    K  {k['player']} {k['side']} {k['line']} "
                      f"(proj {k['projection']}) -> {actual}  [{mark}]")
        print()

    print("=" * 56)
    print(k_tally.line("Strikeouts"))
    print(total_tally.line("Game total"))
    print(ml_tally.line("Moneyline"))
    if total_actual:
        bias = mean(total_proj) - mean(total_actual)
        print(f"  total bias   {bias:+.2f} runs (proj {mean(total_proj):.1f} vs actual {mean(total_actual):.1f})")
    if pending:
        print(f"\n  {pending} game(s) still pending — re-run grade later.")
    print("\nMeasures model accuracy, not betting ROI (needs paid closing lines).")
    await mlb.close()


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot today's picks and grade them vs results.")
    ap.add_argument("command", choices=["snapshot", "grade"])
    ap.add_argument("--date", default=_today(), help="YYYY-MM-DD (default: today)")
    args = ap.parse_args()
    if args.command == "snapshot":
        asyncio.run(snapshot(args.date))
    else:
        asyncio.run(grade(args.date))


if __name__ == "__main__":
    main()
