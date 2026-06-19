"""Loader for the bundled UFC fighter dataset (career rate stats).

The data file is generated offline by ``scripts/build_ufc_dataset.py`` (there is
no free live API for fighter rate-stats). Loaded once into memory and matched by
normalized name. Missing fighters return ``None`` so the model degrades.

Name matching is the main coverage risk: the schedule comes from ESPN but the
rate stats come from ufcstats, and the two spell names differently (accents,
dropped middle names, "Jr"). ``get_fighter`` therefore (1) normalizes
accent-insensitively and (2) falls back to a *uniqueness-guarded* fuzzy match
(surname + first initial) so near-miss spellings resolve — but only when exactly
one fighter fits, so we never silently pick the wrong "Silva".
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_FILE = Path(__file__).resolve().parent / "data" / "ufc_fighters.json"

_cache: Optional[Dict[str, Any]] = None
_token_index: Optional[List[Tuple[str, List[str]]]] = None


def norm(name: str) -> str:
    """Accent-insensitive alphanumeric key (so 'José Aldo' == 'Jose Aldo')."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def _tokens(name: str) -> List[str]:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in "".join(c if c.isalnum() else " " for c in s.lower()).split() if t]


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _index() -> List[Tuple[str, List[str]]]:
    global _token_index
    if _token_index is None:
        _token_index = [(key, _tokens(rec.get("name", ""))) for key, rec in _load().items()]
    return _token_index


def get_fighter(name: str) -> Optional[Dict[str, Any]]:
    data = _load()
    rec = data.get(norm(name))
    if rec:
        return rec
    # Fuzzy fallback: surname + first-initial, accepted only when it's UNIQUE in
    # the dataset (so two different "A. Silva"s never resolve to a confident
    # wrong match). Also accept an exact token-set match (re-ordering/punctuation).
    toks = _tokens(name)
    if not toks:
        return None
    tset = set(toks)
    surname_hits: List[str] = []
    for key, ktoks in _index():
        if not ktoks:
            continue
        if set(ktoks) == tset:
            return data[key]
        if ktoks[-1] == toks[-1] and ktoks[0][:1] == toks[0][:1]:
            surname_hits.append(key)
    if len(surname_hits) == 1:
        return data[surname_hits[0]]
    return None


def available() -> bool:
    return bool(_load())
