# CLAUDE.md

Guidance for Claude Code (and any developer) working in this repo.

## What this is

**Sharp Slate** aggregates free MLB data and grades pitcher **strikeout prop**
bets in a sharp-bettor style (historical hit rates + matchup splits), plus a
game-level win-probability model. When live odds are supplied it computes real
**expected value (EV)** and **Kelly** stake; without odds it still produces the
full analysis but labels it "analysis only" (a projection is not an edge).

## Run it

```bash
./run.sh                      # venv + deps + server on :8000
# or
uvicorn backend.main:app --reload
```

Open http://localhost:8000. No build step — the frontend is static files served
by the same FastAPI process.

Tests (synthetic data, no network needed):

```bash
python3 test_integration.py       # MLB API end-to-end
python3 test_integration_nba.py   # NBA API end-to-end (?sport=nba)
```

Backtesting (live data, measures model accuracy — needs network):

```bash
python3 backtest.py --season 2025 --pitchers 25
```

`backtest.py` replays each pitcher start point-in-time (game log filtered to
before the game date — no look-ahead) and reports projection MAE/bias and
probability calibration (Brier + reliability) vs actual results. It measures
whether the *model* is accurate, not betting ROI (that needs paid historical
closing lines).

## Architecture

```
backend/                FastAPI app + the model (Python, async)
  main.py               HTTP endpoints; ?sport=mlb|nba routing; orchestration
  mlb.py                MLB Stats API client (statsapi.mlb.com, no key)
  odds.py               The Odds API client + betting math (EV, Kelly, de-vig)
  analysis.py           THE MLB MODEL: projection, splits, confidence, EV, game model
  nba.py                NBA client (cdn.nba.com schedule + stats.nba.com ratings, no key)
  nba_analysis.py       THE NBA MODEL: efficiency+pace -> score/spread/total/winprob + signals
  mma.py                UFC card client (ESPN MMA API, no key)
  mma_data.py           loader for the bundled fighter rate-stat dataset
  mma_analysis.py       THE MMA MODEL: rate-stat diffs + finish hazard -> winner/method/distance/strikes/TD + signals
  data/ufc_fighters.json  bundled fighter career rate stats (built by scripts/build_ufc_dataset.py)
  ai.py                 narrative: deterministic template + optional Claude rephrase
  cache.py              in-process TTL cache with per-key locks
frontend/               static single-page UI (no framework, no build)
  index.html            structure + <template>s + Google Fonts + Chart.js (CDN)
  styles.css            design system ("ballpark at night")
  app.js                fetches the API, renders cards + Top Board + chip charts
```

Data flows in one direction: `mlb.py`/`odds.py` fetch → `analysis.py` grades →
`main.py` serializes JSON → `app.js` renders. The frontend holds no secrets;
all keys stay server-side.

## API contract

- `GET /api/health` → `{ ok, flags }`
- `GET /api/slate?date=YYYY-MM-DD&sport=mlb|nba` → `{ date, sport, count, games[], flags }` (fast; schedule only)
- `GET /api/analyze/{gameId}?date=&sport=mlb|nba&seasons=4&ai=0` → MLB: `{ gamePk, game, picks[], gameModel, ... }`; NBA: `{ gameId, sport, game, gameModel }`

`flags = { hasOdds, playerProps, hasAI }` drives the UI status pills. `sport`
defaults to `mlb`. The NBA `gameModel` carries `homeWinProb`/`awayWinProb`,
`home/awayProjScore`, `projMargin`, `modelHomeSpread`, `projTotal`, `pace`,
`ratings`, `rest`, and `signals[]` (`{label,detail,lean}`, lean ∈
home/away/over/under/neutral). NBA is game-level only so far (no player props yet).

A **pick** (see `analyze_strikeouts`) carries: `pick`, `side`, `line`,
`projection`, `modelProb`, `confidence`, `tier`, `splits[]` (`{label,hits,n,rate}`),
`spark[]` (`{date,opp,k,home}` for the chip chart), and `edge` (null unless a
live line was matched: `{decimal,modelProb,marketProb,fairProb,evPct,kellyPct,...}`).

## Common tasks

**Tune the model.** All knobs are constants at the top of `backend/analysis.py`:
`PROJECTION_WINDOW`, `OPP_FACTOR_FLOOR/CEIL`, `TOP_BUCKET`, `SHRINK_PSEUDO`,
`MIN_STARTS`, `HOME_FIELD_EDGE`, `PYTHAG_EXP`. Change them there; nothing else
hard-codes these values.

**Add a new prop type (e.g. batter hits, total bases).**
1. Add a fetch in `backend/mlb.py` for the needed game logs (mirror
   `get_pitcher_gamelog`).
2. Write `analyze_<prop>(...)` in `backend/analysis.py` returning the same dict
   shape as `analyze_strikeouts` (so the frontend renders it unchanged): include
   `pick`, `side`, `line`, `projection`, `confidence`, `tier`, `splits`, `spark`,
   `edge`. Reuse `_hit_rate`, `_shrunk`, `_streak`, and the Poisson helpers.
3. Call it from the pick-building loop in `backend/main.py` and append to `picks`.
4. If a market exists, add a matching props fetch in `backend/odds.py` and pass
   the `{line, over, under}` dict in as `market`.

**Add a new sport.** Keep the shape: a `*_<sport>.py` client + `analyze_*`
functions returning the same pick dict. The frontend is sport-agnostic — it only
reads the documented fields. A sport selector would go in `index.html` /
`app.js` and a `?sport=` param on the endpoints.

**Change the look.** Everything visual is tokenized at the top of
`frontend/styles.css` (`:root`). The signature element is the per-pick
"scorecard chip" (recent strikeouts as bars with the prop line drawn as a dashed
rule) — see `drawChip()` in `app.js`.

## Conventions

- The package is imported as `backend.*`. The project directory is `sharp-slate`
  (a hyphen) which is **not** a valid module name, so always run from the repo
  root and import `backend.xxx`, never `sharp_slate.backend`.
- Network egress in some sandboxes is restricted; `statsapi.mlb.com` may be
  unreachable. Develop the engine against `test_integration.py`'s synthetic data.
- Be honest in copy and output: surface where the model disagrees with the
  market, never promise winners. Flag low samples (`lowSample`, `split--thin`).
- No browser storage in the frontend (it isn't available in all embeds).

## Honest-modeling notes

- A projection alone is not betting value. Positive EV requires the model
  probability to beat the **vig-removed** market probability (`devig_two` in
  `odds.py`). The EV/Kelly block only appears when a real line is matched.
- Kelly is a ceiling, not a target. The UI recommends staking a fraction
  (~¼ Kelly) to tame variance. Small samples are shrunk toward 0.5 so a 5/6
  mirage doesn't dominate confidence.
