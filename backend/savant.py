"""Baseball Savant (Statcast) pitcher-skill leaderboard — no key required.

Season strikeout rate and whiff rate are far more stable game-to-game than raw
K *counts*, so blending them into the projection (see
``analysis._skill_projection``) keeps a couple of unlucky low-K starts from
dragging a good pitcher's number down. We pull the league-wide custom
leaderboard once (cached) and index it by MLBAM player id.

Network egress to baseballsavant.mlb.com may be unavailable in some sandboxes;
every public function degrades to ``None`` so the model falls back to the
results-only baseline.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, Optional

import httpx

from .cache import cache

LEADERBOARD_URL = "https://baseballsavant.mlb.com/leaderboard/custom"

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _pct(value: Any) -> Optional[float]:
    """Savant reports percentages as e.g. ``24.5``; return ``0.245`` or ``None``."""
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


async def _load_leaderboard(season: int) -> Dict[int, Dict[str, Any]]:
    """``{mlbam_id: {"kPct", "bbPct", "whiffPct"}}`` for all qualified pitchers."""

    async def fetch() -> Dict[int, Dict[str, Any]]:
        c = client()
        r = await c.get(
            LEADERBOARD_URL,
            params={
                "year": season,
                "type": "pitcher",
                "filter": "",
                "min": "1",
                "selections": "k_percent,bb_percent,whiff_percent",
                "sort": "k_percent",
                "sortDir": "desc",
                "csv": "true",
            },
        )
        r.raise_for_status()
        # Savant prepends a UTF-8 BOM; decoding with utf-8-sig strips it so the
        # csv reader doesn't mis-split the quoted "last_name, first_name" header.
        reader = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")))

        out: Dict[int, Dict[str, Any]] = {}
        for row in reader:
            pid_raw = row.get("player_id") or row.get("mlbam_id")
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            out[pid] = {
                "kPct": _pct(row.get("k_percent")),
                "bbPct": _pct(row.get("bb_percent")),
                "whiffPct": _pct(row.get("whiff_percent")),
            }
        return out

    return await cache.get_or_set(f"savant:pitchers:{season}", 12 * 3600, fetch)


async def get_pitcher_skill(person_id: int, season: int) -> Optional[Dict[str, Any]]:
    """Skill row for one pitcher, shaped for ``analysis._skill_projection``.

    Returns ``{"kPct", "swStrPct", "cswPct"}`` (the latter two may be ``None``),
    or ``None`` when the pitcher isn't on the leaderboard / the fetch fails.
    """
    try:
        board = await _load_leaderboard(season)
    except Exception:
        return None
    row = board.get(person_id)
    if not row or row.get("kPct") is None:
        return None
    return {
        "kPct": row["kPct"],
        "swStrPct": row.get("whiffPct"),  # whiffs/swing — proxy for swinging-strike skill
        "cswPct": None,                    # not exposed by this leaderboard
    }
