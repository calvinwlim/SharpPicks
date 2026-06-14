"""Build the bundled UFC fighter dataset from per-fight ufcstats data.

There is no free live API for fighter rate-stats, so we aggregate them ourselves
from the public ufcstats mirror (Greco1899/scrape_ufc_stats), which exposes the
per-round, per-fighter box scores as CSV. For each fighter we compute career
rates the model needs — striking (SLpM, SApM, accuracy, defense), grappling
(takedown avg/accuracy/defense, sub avg, control), power/durability (knockdowns
landed/absorbed) and finish breakdown (KO/Sub/Dec wins, finished-loss rate) —
plus physicals from the tale-of-the-tape file.

Run it to (re)generate ``backend/data/ufc_fighters.json``:

    python scripts/build_ufc_dataset.py

Reachable from this machine and from yours; rerun periodically to refresh.
"""
from __future__ import annotations

import asyncio
import csv
import datetime
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

RAW = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main"
OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "ufc_fighters.json"
UA = {"User-Agent": "Mozilla/5.0"}


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _x_of_y(s: str) -> Tuple[int, int]:
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _mmss(s: str) -> int:
    m = re.match(r"\s*(\d+):(\d+)", s or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def _height_in(s: str) -> Optional[float]:
    m = re.match(r"(\d+)'\s*(\d+)", s or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _reach_in(s: str) -> Optional[float]:
    m = re.match(r"(\d+(?:\.\d+)?)", (s or "").replace('"', "").strip())
    return float(m.group(1)) if m else None


def _fresh() -> Dict[str, Any]:
    g = {k: 0.0 for k in (
        "minutes", "sigL", "sigA", "sigAbs", "oppSigA", "tdL", "tdA", "oppTdL", "oppTdA",
        "subAtt", "kd", "kdAbs", "ctrl", "fights", "wins", "losses",
        "koW", "subW", "decW", "koL", "subL")}
    g["name"] = ""
    g["wc"] = {}
    return g


async def fetch_csv(c: httpx.AsyncClient, name: str):
    r = await c.get(f"{RAW}/{name}")
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def classify_method(method: str) -> str:
    m = (method or "").lower()
    if "ko" in m or "tko" in m:
        return "ko"
    if "sub" in m:
        return "sub"
    if "dec" in m:
        return "dec"
    return "other"


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0, headers=UA, follow_redirects=True) as c:
        print("fetching results, stats, tale-of-the-tape, events...")
        results, fstats, tott, events = await asyncio.gather(
            fetch_csv(c, "ufc_fight_results.csv"),
            fetch_csv(c, "ufc_fight_stats.csv"),
            fetch_csv(c, "ufc_fighter_tott.csv"),
            fetch_csv(c, "ufc_event_details.csv"),
        )

    # Event -> date, so we can record each fighter's most recent bout (for layoff).
    event_date: Dict[str, datetime.date] = {}
    for e in events:
        raw = (e.get("DATE") or "").strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                event_date[e["EVENT"].strip()] = datetime.datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue

    # Bout metadata: winner, method, ending round/time -> fight minutes.
    bouts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in results:
        event, bout = row["EVENT"].strip(), row["BOUT"].strip()
        names = [n.strip() for n in bout.split(" vs. ")]
        if len(names) != 2:
            continue
        outcome = (row.get("OUTCOME") or "").strip()
        winner = names[0] if outcome.startswith("W") else names[1] if outcome.startswith("L") else None
        try:
            end_round = int(row.get("ROUND") or 0)
        except ValueError:
            end_round = 0
        minutes = (max(end_round - 1, 0)) * 5 + _mmss(row.get("TIME", "")) / 60.0
        bouts[(event, bout)] = {
            "names": names, "winner": winner, "method": classify_method(row.get("METHOD", "")),
            "minutes": minutes if minutes > 0 else 5.0,
            "wc": (row.get("WEIGHTCLASS") or "").replace("Bout", "").strip(),
        }

    # Per (bout, fighter) box-score sums across rounds.
    box: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for row in fstats:
        key = (row["EVENT"].strip(), row["BOUT"].strip(), row["FIGHTER"].strip())
        b = box.setdefault(key, {k: 0.0 for k in ("sigL", "sigA", "tdL", "tdA", "subAtt", "kd", "ctrl")})
        sl, sa = _x_of_y(row.get("SIG.STR.", ""))
        tl, ta = _x_of_y(row.get("TD", ""))
        b["sigL"] += sl; b["sigA"] += sa; b["tdL"] += tl; b["tdA"] += ta
        b["subAtt"] += float(row.get("SUB.ATT") or 0)
        b["kd"] += float(row.get("KD") or 0)
        b["ctrl"] += _mmss(row.get("CTRL", ""))

    # Aggregate per fighter, pairing opponents within each bout.
    agg: Dict[str, Dict[str, Any]] = {}
    last_date: Dict[str, datetime.date] = {}  # most recent bout per fighter (for layoff)
    for (event, bout), meta in bouts.items():
        a, bb = meta["names"]
        sa, sb = box.get((event, bout, a)), box.get((event, bout, bb))
        if not sa or not sb:
            continue
        minutes = meta["minutes"]
        d = event_date.get(event)
        if d:
            for nm in (a, bb):
                key = _norm(nm)
                if key not in last_date or d > last_date[key]:
                    last_date[key] = d
        for me, opp, ms, os in ((a, bb, sa, sb), (bb, a, sb, sa)):
            g = agg.setdefault(_norm(me), _fresh())
            g["name"] = me
            g["minutes"] += minutes
            g["sigL"] += ms["sigL"]; g["sigA"] += ms["sigA"]
            g["sigAbs"] += os["sigL"]; g["oppSigA"] += os["sigA"]
            g["tdL"] += ms["tdL"]; g["tdA"] += ms["tdA"]
            g["oppTdL"] += os["tdL"]; g["oppTdA"] += os["tdA"]
            g["subAtt"] += ms["subAtt"]; g["kd"] += ms["kd"]; g["kdAbs"] += os["kd"]
            g["ctrl"] += ms["ctrl"]; g["fights"] += 1
            if meta["wc"]:
                g["wc"][meta["wc"]] = g["wc"].get(meta["wc"], 0) + 1
            if meta["winner"] == me:
                g["wins"] += 1
                g[{"ko": "koW", "sub": "subW", "dec": "decW"}.get(meta["method"], "decW")] += 1
            elif meta["winner"] == opp:
                g["losses"] += 1
                if meta["method"] == "ko":
                    g["koL"] += 1
                elif meta["method"] == "sub":
                    g["subL"] += 1

    # Physicals.
    phys: Dict[str, Dict[str, Any]] = {}
    for row in tott:
        phys[_norm(row["FIGHTER"])] = {
            "heightIn": _height_in(row.get("HEIGHT", "")),
            "reachIn": _reach_in(row.get("REACH", "")),
            "stance": (row.get("STANCE") or "").strip() or None,
            "dob": (row.get("DOB") or "").strip() or None,
        }

    def rate(n: float, d: float, default: float = 0.0) -> float:
        return round(n / d, 4) if d else default

    out: Dict[str, Any] = {}
    for key, g in agg.items():
        m = g["minutes"] or 1.0
        wins, losses = g["wins"], g["losses"]
        rec = {
            "name": g["name"],
            "fights": int(g["fights"]), "wins": int(wins), "losses": int(losses),
            "minutes": round(m, 1),
            "slpm": rate(g["sigL"], m), "sapm": rate(g["sigAbs"], m),
            "strAcc": rate(g["sigL"], g["sigA"]), "strDef": round(1 - g["sigAbs"] / g["oppSigA"], 4) if g["oppSigA"] else 0.0,
            "tdAvg": round(g["tdL"] / m * 15, 4), "tdAcc": rate(g["tdL"], g["tdA"]),
            "tdDef": round(1 - g["oppTdL"] / g["oppTdA"], 4) if g["oppTdA"] else 0.0,
            "subAvg": round(g["subAtt"] / m * 15, 4),
            "kdPer15": round(g["kd"] / m * 15, 4), "kdAbsPer15": round(g["kdAbs"] / m * 15, 4),
            "ctrlPerMin": round(g["ctrl"] / 60.0 / m, 4),
            "koRate": rate(g["koW"], wins), "subRate": rate(g["subW"], wins), "decRate": rate(g["decW"], wins),
            "finishRate": rate(g["koW"] + g["subW"], wins),
            "finishedRate": rate(g["koL"] + g["subL"], losses),
            "weightClass": max(g["wc"], key=g["wc"].get) if g["wc"] else None,
            "lastFightDate": last_date[key].isoformat() if key in last_date else None,
        }
        rec.update(phys.get(key, {}))
        out[key] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(out)} fighters -> {OUT}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
