"""Loader for the bundled UFC fighter dataset (career rate stats).

The data file is generated offline by ``scripts/build_ufc_dataset.py`` (there is
no free live API for fighter rate-stats). Loaded once into memory and matched by
normalized name. Missing fighters return ``None`` so the model degrades.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

DATA_FILE = Path(__file__).resolve().parent / "data" / "ufc_fighters.json"

_cache: Optional[Dict[str, Any]] = None


def norm(name: str) -> str:
    return "".join(c for c in (name or "").lower() if c.isalnum())


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def get_fighter(name: str) -> Optional[Dict[str, Any]]:
    return _load().get(norm(name))


def available() -> bool:
    return bool(_load())
