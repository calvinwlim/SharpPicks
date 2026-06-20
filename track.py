"""Track today's picks and grade them against the day's actual results.

This is the *live* counterpart to ``backtest.py`` (which replays past seasons):
it records the predictions the app makes today, then — once games go final —
compares them to what actually happened. Two steps, no database; just dated
JSON snapshots under ``tracking/``:

    python track.py snapshot                 # save today's predictions + bet prices
    python track.py close                     # (optional) re-capture closing lines, for CLV
    python track.py grade                     # score the snapshot vs results
    python track.py grade --date 2026-06-14

``snapshot`` reuses the exact app analysis (``backend.main._analyze_mlb``), so
what you grade is what the UI showed — and now stores the matched **price** of
each pick. ``grade`` pulls final scores + boxscores and reports, per market:
W-L + Brier (accuracy), **ROI** (flat 1-unit on every +EV pick at the captured
price), and — if you ran ``close`` near game time — **CLV** (how much your price
beat the closing line, and how often). Needs network (statsapi.mlb.com); run
``grade`` after games are final. Pending games can be re-graded later.

Graded markets: pitcher strikeout props, the game total, and the moneyline. ROI
is at the prices we captured (not guaranteed your book's); CLV is the real test
of whether the picks are sharp.
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
from backend import mma
from backend import odds

TRACK_DIR = "tracking"


def _today() -> str:
    return datetime.date.today().isoformat()


def _suffix(sport: str) -> str:
    # MLB keeps the original bare filenames (back-compat); other sports get a tag
    # so e.g. an MLB and a UFC card on the same date don't overwrite each other.
    return "" if sport == "mlb" else f".{sport}"


def _path(date: str, sport: str = "mlb") -> str:
    return os.path.join(TRACK_DIR, f"{date}{_suffix(sport)}.json")


def _graded_path(date: str, sport: str = "mlb") -> str:
    return os.path.join(TRACK_DIR, f"{date}{_suffix(sport)}.graded.json")


def _close_path(date: str, sport: str = "mlb") -> str:
    return os.path.join(TRACK_DIR, f"{date}{_suffix(sport)}.close.json")


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

    def price(pick: Dict[str, Any]) -> Optional[int]:
        edge = pick.get("edge")
        return edge.get("price") if edge else None

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
            "price": price(p),
        })

    gm = res.get("gameModel", {}) or {}
    total = None
    if gm.get("total"):
        t = gm["total"]
        total = {
            "side": t["side"], "line": t["line"], "projection": t["projection"],
            "modelProb": t["modelProb"], "evPct": ev(t), "price": price(t),
        }

    moneyline = None
    if gm.get("homeWinProb") is not None:
        home_wp = gm["homeWinProb"]
        pick_side = "home" if home_wp >= 0.5 else "away"
        ml = gm.get("moneyline") or {}
        ml_side = ml.get(pick_side) or {}
        moneyline = {
            "pick": pick_side,
            "modelProb": round(max(home_wp, 1 - home_wp), 4),
            "homeWinProb": home_wp,
            "evPct": ml_side.get("evPct"),
            "price": ml_side.get("price"),
        }

    return {
        "gamePk": game["gamePk"],
        "away": game["away"]["abbr"], "home": game["home"]["abbr"],
        "strikeouts": strikeouts, "total": total, "moneyline": moneyline,
    }


async def _capture_mlb(date: str, as_close: bool = False) -> None:
    """Run the full app analysis over the slate and save the gradeable picks.

    ``snapshot`` saves them as the *bet* (opening) lines; ``close`` re-runs near
    game time and saves the *closing* lines, so grade can measure CLV."""
    games = await mlb.get_schedule(date)
    if not games:
        print(f"No games scheduled on {date}.")
        return

    what = "closing lines" if as_close else "predictions"
    print(f"Capturing {what} for {len(games)} games on {date} (running full analysis)...")
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
    path = _close_path(date) if as_close else _path(date)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    if as_close:
        print(f"\nSaved {path}: closing lines for {len(entries)} games — CLV grades against these.")
    else:
        n_k = sum(len(e["strikeouts"]) for e in entries)
        print(f"\nSaved {path}: {len(entries)} games, {n_k} strikeout picks. Optionally run "
              f"`python track.py close --date {date}` near game time (for CLV), then "
              f"`python track.py grade --date {date}` once final.")
    await mlb.close()


async def snapshot(date: str, sport: str = "mlb") -> None:
    await (_capture_mma(date, False) if sport == "mma" else _capture_mlb(date, False))


async def close(date: str, sport: str = "mlb") -> None:
    await (_capture_mma(date, True) if sport == "mma" else _capture_mlb(date, True))


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
    """Win/loss/push + Brier + betting record (ROI, CLV) for one market.

    ROI assumes a flat 1-unit bet on every **+EV** pick at the captured price.
    CLV (closing line value) needs ``track.py close`` to have stored the closing
    price; it's the % your taken price beat the close, plus how often you did."""

    def __init__(self) -> None:
        self.w = self.l = self.p = 0
        self.briers: List[float] = []
        self.units = 0.0      # net units on +EV bets (flat 1u stake)
        self.staked = 0.0
        self.clv: List[float] = []
        self.beat_close = 0
        self.clv_n = 0

    def add(self, won: Optional[bool], model_prob: Optional[float],
            price: Optional[int] = None, ev: Optional[float] = None,
            close_price: Optional[int] = None) -> None:
        if won is None:
            self.p += 1
        elif won:
            self.w += 1
        else:
            self.l += 1
        if model_prob is not None and won is not None:
            self.briers.append((model_prob - (1.0 if won else 0.0)) ** 2)
        # Betting record: only +EV picks with a real price and a decided result.
        if price is not None and ev is not None and ev > 0 and won is not None:
            self.staked += 1.0
            dec = odds.american_to_decimal(price)
            self.units += (dec - 1.0) if won else -1.0
            if close_price is not None:
                self.clv_n += 1
                cdec = odds.american_to_decimal(close_price)
                if dec > cdec:
                    self.beat_close += 1
                self.clv.append((dec / cdec - 1.0) * 100.0)

    def summary(self) -> Dict[str, Any]:
        return {
            "w": self.w, "l": self.l, "p": self.p,
            "brier": round(mean(self.briers), 4) if self.briers else None,
            "bets": int(self.staked),
            "units": round(self.units, 2) if self.staked else None,
            "roi": round(self.units / self.staked * 100, 1) if self.staked else None,
            "clv": round(mean(self.clv), 2) if self.clv else None,
            "beatClose": round(self.beat_close / self.clv_n, 3) if self.clv_n else None,
            # raw counts so the UI can re-aggregate ROI/CLV across many days
            "clvN": self.clv_n, "clvSum": round(sum(self.clv), 4), "beatN": self.beat_close,
        }

    def line(self, label: str) -> str:
        graded = self.w + self.l
        wr = f"{self.w / graded:.0%}" if graded else "—"
        brier = f"{mean(self.briers):.3f}" if self.briers else "—"
        push = f", {self.p} push" if self.p else ""
        roi = f"  ROI {self.units / self.staked * 100:+.1f}% ({self.units:+.1f}u/{int(self.staked)})" if self.staked else ""
        clv = f"  CLV {mean(self.clv):+.1f}% (beat {self.beat_close}/{self.clv_n})" if self.clv else ""
        return f"  {label:<12} {self.w}-{self.l}{push}  (win {wr}, Brier {brier}){roi}{clv}"


async def grade(date: str, sport: str = "mlb") -> None:
    if sport == "mma":
        await _grade_mma(date)
    else:
        await _grade_mlb(date)


async def _grade_mlb(date: str) -> None:
    try:
        with open(_path(date), encoding="utf-8") as f:
            snap = json.load(f)
    except FileNotFoundError:
        print(f"No snapshot at {_path(date)}. Run `python track.py snapshot --date {date}` first.")
        return

    # Closing lines (if `track.py close` was run) -> CLV. Keyed per pick.
    close_map: Dict[Any, Optional[int]] = {}
    try:
        with open(_close_path(date), encoding="utf-8") as f:
            for e in json.load(f)["games"]:
                pk = e["gamePk"]
                if e.get("total"):
                    close_map[(pk, "total")] = e["total"].get("price")
                if e.get("moneyline"):
                    close_map[(pk, "ml")] = e["moneyline"].get("price")
                for k in e.get("strikeouts", []):
                    close_map[(pk, "k", k["player"])] = k.get("price")
    except FileNotFoundError:
        pass

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
            total_tally.add(won, t["modelProb"], t.get("price"), t.get("evPct"), close_map.get((pk, "total")))
            total_proj.append(t["projection"])
            total_actual.append(runs)
            mark = "PUSH" if won is None else ("WIN " if won else "LOSS")
            print(f"    total   {t['side']} {t['line']} (proj {t['projection']}) -> {runs}  [{mark}]")

        if e["moneyline"]:
            m = e["moneyline"]
            won = m["pick"] == winner
            ml_tally.add(won, m["modelProb"], m.get("price"), m.get("evPct"), close_map.get((pk, "ml")))
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
                k_tally.add(won, k["modelProb"], k.get("price"), k.get("evPct"),
                            close_map.get((pk, "k", k["player"])))
                mark = "PUSH" if won is None else ("WIN " if won else "LOSS")
                print(f"    K  {k['player']} {k['side']} {k['line']} "
                      f"(proj {k['projection']}) -> {actual}  [{mark}]")
        print()

    # Overall betting record = all +EV bets combined across markets.
    o_units = k_tally.units + total_tally.units + ml_tally.units
    o_staked = k_tally.staked + total_tally.staked + ml_tally.staked
    o_clv = k_tally.clv + total_tally.clv + ml_tally.clv
    o_beat = k_tally.beat_close + total_tally.beat_close + ml_tally.beat_close
    o_clvn = k_tally.clv_n + total_tally.clv_n + ml_tally.clv_n

    print("=" * 56)
    print(k_tally.line("Strikeouts"))
    print(total_tally.line("Game total"))
    print(ml_tally.line("Moneyline"))
    if o_staked:
        roi = o_units / o_staked * 100
        line = f"  {'Overall':<12} {int(o_staked)} +EV bets  ROI {roi:+.1f}% ({o_units:+.1f}u)"
        if o_clv:
            line += f"  CLV {mean(o_clv):+.1f}% (beat close {o_beat}/{o_clvn})"
        print("  " + "-" * 52)
        print(line)
    if total_actual:
        bias = mean(total_proj) - mean(total_actual)
        print(f"  total bias   {bias:+.2f} runs (proj {mean(total_proj):.1f} vs actual {mean(total_actual):.1f})")
    if pending:
        print(f"\n  {pending} game(s) still pending — re-run grade later.")
    if not o_clvn:
        print("\nROI is at the captured prices. For CLV, run `track.py close` near game time.")

    summary = {
        "date": date,
        "sport": "mlb",
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "strikeouts": k_tally.summary(),
        "total": total_tally.summary(),
        "moneyline": ml_tally.summary(),
        "overall": {
            "bets": int(o_staked),
            "units": round(o_units, 2) if o_staked else None,
            "roi": round(o_units / o_staked * 100, 1) if o_staked else None,
            "clv": round(mean(o_clv), 2) if o_clv else None,
            "beatClose": round(o_beat / o_clvn, 3) if o_clvn else None,
            "clvN": o_clvn, "clvSum": round(sum(o_clv), 4), "beatN": o_beat,
        },
        "totalBias": round(mean(total_proj) - mean(total_actual), 2) if total_actual else None,
        "pending": pending,
        "games": len(snap["games"]),
    }
    os.makedirs(TRACK_DIR, exist_ok=True)
    with open(_graded_path(date), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    await mlb.close()


# --------------------------------------------------------------------------- MMA

def _extract_mma_predictions(res: Dict[str, Any], fight: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Gradeable picks from one ``_analyze_mma`` result: winner (moneyline, the
    only priced market), method (KO/Sub/Dec argmax), and distance (over/under)."""
    fm = res.get("fightModel")
    if not fm:
        return None
    a, b = fm["aName"], fm["bName"]
    pick = fm.get("pick") or {}
    pick_fighter = pick.get("fighter")
    ml_side = (fm.get("moneyline") or {}).get("a" if pick_fighter == a else "b") or {}
    moneyline = {
        "pick": pick_fighter, "modelProb": pick.get("prob"), "tier": pick.get("tier"),
        "evPct": ml_side.get("evPct"), "price": ml_side.get("price"),
    }
    method = fm.get("method") or {}
    name_map = {"ko": "ko", "sub": "sub", "decision": "dec"}
    pred = max(method, key=method.get) if method else None
    method_pred = {"pick": name_map.get(pred), "modelProb": method.get(pred)} if pred else None
    dp = fm.get("distanceProb")
    distance = ({"side": "over" if dp >= 0.5 else "under", "modelProb": round(max(dp, 1 - dp), 4)}
               if dp is not None else None)
    return {
        "gameId": fight["gameId"], "away": fight["away"]["abbr"], "home": fight["home"]["abbr"],
        "moneyline": moneyline, "method": method_pred, "distance": distance,
    }


async def _capture_mma(date: str, as_close: bool = False) -> None:
    fights = await mma.get_schedule(date)
    if not fights:
        print(f"No UFC fights on {date}.")
        return
    what = "closing lines" if as_close else "predictions"
    print(f"Capturing {what} for {len(fights)} UFC fights on {date} (running full analysis)...")
    entries: List[Dict[str, Any]] = []
    for fight in fights:
        label = f"{fight['away']['abbr']} vs {fight['home']['abbr']}"
        try:
            res = await app._analyze_mma(fight["gameId"], date)
            pred = _extract_mma_predictions(res, fight)
            if pred:
                entries.append(pred)
                print(f"  ok   {label}")
            else:
                print(f"  skip {label}: no model (missing fighter data)")
        except Exception as e:
            print(f"  skip {label}: {e!r}")

    os.makedirs(TRACK_DIR, exist_ok=True)
    payload = {
        "date": date, "sport": "mma",
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "fights": entries,
    }
    path = _close_path(date, "mma") if as_close else _path(date, "mma")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    if as_close:
        print(f"\nSaved {path}: closing lines for {len(entries)} fights.")
    else:
        print(f"\nSaved {path}: {len(entries)} fights. Optionally run "
              f"`python track.py close --sport mma --date {date}` near card time, then "
              f"`python track.py grade --sport mma --date {date}` once final.")
    await mma.close()


def _mma_method(details: Any) -> Optional[str]:
    """KO/Sub/Dec from an ESPN competition's ``details`` list (the
    'Unofficial Winner <method>' play; 'Kotko' = KO/TKO)."""
    for d in details or []:
        text = ((d.get("type") or {}).get("text") or "")
        if text.startswith("Unofficial Winner"):
            s = text[len("Unofficial Winner"):].strip().lower()
            if "sub" in s:
                return "sub"
            if "ko" in s or "tko" in s:
                return "ko"
            if "dec" in s:
                return "dec"
    return None


async def _mma_results(date: str) -> Dict[str, Dict[str, Any]]:
    """``{competitionId: {final, winner, method, endRound}}`` from ESPN."""
    d = datetime.date.fromisoformat(date)
    window = f"{(d - datetime.timedelta(days=1)):%Y%m%d}-{(d + datetime.timedelta(days=1)):%Y%m%d}"
    r = await mma.client().get(mma.SCOREBOARD, params={"dates": window})
    r.raise_for_status()
    out: Dict[str, Dict[str, Any]] = {}
    for ev in r.json().get("events", []):
        for comp in ev.get("competitions", []):
            cs = comp.get("competitors", [])
            if len(cs) != 2:
                continue
            st = comp.get("status", {}).get("type", {})
            winner = next(((c.get("athlete") or {}).get("displayName") for c in cs if c.get("winner")), None)
            out[str(comp.get("id"))] = {
                "final": bool(st.get("completed")),
                "winner": winner,
                "method": _mma_method(comp.get("details")),
                "endRound": comp.get("status", {}).get("period"),
            }
    return out


async def _grade_mma(date: str) -> None:
    try:
        with open(_path(date, "mma"), encoding="utf-8") as f:
            snap = json.load(f)
    except FileNotFoundError:
        print(f"No MMA snapshot at {_path(date, 'mma')}. "
              f"Run `python track.py snapshot --sport mma --date {date}` first.")
        return

    close_map: Dict[str, Optional[int]] = {}
    try:
        with open(_close_path(date, "mma"), encoding="utf-8") as f:
            for e in json.load(f)["fights"]:
                if e.get("moneyline"):
                    close_map[e["gameId"]] = e["moneyline"].get("price")
    except FileNotFoundError:
        pass

    results = await _mma_results(date)
    ml_tally, method_tally, dist_tally = Tally(), Tally(), Tally()
    pending = 0

    print(f"Grading UFC {date} (snapshotted {snap.get('generatedAt', '?')})\n")
    for e in snap["fights"]:
        gid = e["gameId"]
        rec = results.get(gid)
        label = f"{e['away']} vs {e['home']}"
        if not rec or not rec["final"] or not rec["winner"]:
            print(f"{label}: pending")
            pending += 1
            continue
        winner, method, rnd = rec["winner"], rec["method"], rec["endRound"]
        print(f"{label}: {winner} won by {method or '?'} (R{rnd})")

        ml = e.get("moneyline")
        if ml and ml.get("pick"):
            won = ml["pick"] == winner
            ml_tally.add(won, ml.get("modelProb"), ml.get("price"), ml.get("evPct"), close_map.get(gid))
            print(f"    winner   {ml['pick']} ({(ml.get('modelProb') or 0):.0%}) -> [{'WIN ' if won else 'LOSS'}]")
        mp = e.get("method")
        if mp and mp.get("pick") and method:
            won = mp["pick"] == method
            method_tally.add(won, mp.get("modelProb"))
            print(f"    method   {mp['pick']} -> {method}  [{'WIN ' if won else 'LOSS'}]")
        dp = e.get("distance")
        if dp and method:
            actual_dist = method == "dec"
            won = (dp["side"] == "over") == actual_dist
            dist_tally.add(won, dp.get("modelProb"))
            print(f"    distance {dp['side']} -> {'decision' if actual_dist else 'finish'}  [{'WIN ' if won else 'LOSS'}]")
        print()

    # Only the moneyline (winner) carries prices, so it owns the betting record.
    o_units, o_staked = ml_tally.units, ml_tally.staked
    o_clv, o_beat, o_clvn = ml_tally.clv, ml_tally.beat_close, ml_tally.clv_n
    print("=" * 56)
    print(ml_tally.line("Winner"))
    print(method_tally.line("Method"))
    print(dist_tally.line("Distance"))
    if pending:
        print(f"\n  {pending} fight(s) still pending — re-run grade later.")
    if not o_clvn:
        print("\nROI is at the captured prices. For CLV, run `track.py close --sport mma` near card time.")

    summary = {
        "date": date, "sport": "mma",
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "moneyline": ml_tally.summary(),
        "method": method_tally.summary(),
        "distance": dist_tally.summary(),
        "overall": {
            "bets": int(o_staked),
            "units": round(o_units, 2) if o_staked else None,
            "roi": round(o_units / o_staked * 100, 1) if o_staked else None,
            "clv": round(mean(o_clv), 2) if o_clv else None,
            "beatClose": round(o_beat / o_clvn, 3) if o_clvn else None,
            "clvN": o_clvn, "clvSum": round(sum(o_clv), 4), "beatN": o_beat,
        },
        "pending": pending,
        "games": len(snap["fights"]),
    }
    os.makedirs(TRACK_DIR, exist_ok=True)
    with open(_graded_path(date, "mma"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    await mma.close()


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot today's picks and grade them vs results.")
    ap.add_argument("command", choices=["snapshot", "close", "grade"])
    ap.add_argument("--date", default=_today(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--sport", default="mlb", choices=["mlb", "mma"], help="sport to track (default: mlb)")
    args = ap.parse_args()
    if args.command == "snapshot":
        asyncio.run(snapshot(args.date, args.sport))
    elif args.command == "close":
        asyncio.run(close(args.date, args.sport))
    else:
        asyncio.run(grade(args.date, args.sport))


if __name__ == "__main__":
    main()
