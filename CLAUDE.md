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
python3 test_integration_mma.py   # MMA/UFC API end-to-end (?sport=mma)
```

UFC fighter dataset (the MMA model reads `backend/data/ufc_fighters.json`;
there is no live free rate-stat API). (Re)build it by aggregating the public
ufcstats mirror — run after new events:

```bash
python3 scripts/build_ufc_dataset.py     # fighter rate stats (+ sos, headAcc, grndShare, recentFinishLossRate, sample-shrunk) -> backend/data/ufc_fighters.json
python3 scripts/build_mma_winmodel.py    # fit the winner logistic -> backend/data/ufc_winmodel.json
python3 scripts/build_mma_finishmodel.py # fit P(distance) & P(KO|finish) -> backend/data/ufc_finishmodel.json
python3 scripts/build_mma_comps.py       # matchup vectors -> backend/data/ufc_fight_vectors.json (+ holdout + ensemble validation)
```

Or just run all four in order with one command (also what the weekly
`SharpPicks-MMA-refresh` Windows scheduled task runs — see the script header for
the schtasks/cron line):

```bash
python3 scripts/refresh_mma_data.py
```

Run them in that order after new events: the dataset feeds the win-model fit,
and the comps validation reads the winner model. The **winner is a learned
logistic** — `build_mma_winmodel.py` replays every bout point-in-time, fits
`a − b` differential coefficients and writes `ufc_winmodel.json`, which
`mma_analysis` loads (falling back to the hand-tuned `_skill_score` formula if the
file is absent). Strongest features: striking defense, **head-strike accuracy**
(`d_headacc`), **strength-of-schedule** (`d_sos` = avg opponent win%), career win%,
finish rate; plus recent **chin** (`d_chin` = recent finish-loss rate), ground-
strike share, grappling defense, ring-rust, stance. All career rates are
**sample-size-shrunk** toward league means (`shrink_rate_profile`, `SHRINK_K`) so a
4-fight sample doesn't dominate — applied identically in the dataset and
`mma_backtest.rates` for train/serve parity. The learned win prob is sharpened by
`WIN_LOGIT_TEMP` (≈0.85; the L2 fit is mildly under-confident).
`WIN_FEATURE_NAMES`/`_win_features` own the feature order (new features appended so
an older model file degrades gracefully); the builder imports them so the two
never drift. **Tested and left out** (measured non-wins, in code comments):
multiplicative style-matchup interactions and pruning the near-zero features —
both regressed out-of-sample (collinearity; L2 already neutralizes dead weights). **Distance/method:** `build_mma_finishmodel.py` fits
`P(distance)` and `P(KO|finish)` point-in-time but only writes the piece that
*beats the existing heuristic* out-of-sample — currently the per-fighter
finish-hazard product wins for distance (it captures an A-power×B-chin
interaction a linear model can't), while the learned `koGivenFinish` ships
(`mma_analysis` gates each piece independently, heuristic when absent). Recent
form (momentum) and the k-NN comps lens were both measured and **left out of the
win probability** (they didn't improve out-of-sample) — momentum shows as a
signal, comps as a separate `aWinProbComps` number (`ENSEMBLE_COMP_WEIGHT=0`).

Coverage: `mma_data.get_fighter` matches ESPN card names against the ufcstats
dataset accent-insensitively, with a uniqueness-guarded surname+initial fuzzy
fallback. A fighter genuinely absent (debut / short-notice replacement) is
modeled as a league-average stand-in and flagged (`lowData`) — **no betting edge
is computed** off a synthetic profile. With odds present, `_analyze_mma` matches
the `mma_mixed_martial_arts` h2h market and reports moneyline EV/Kelly (the same
de-vig math as MLB) as `fightModel.moneyline` + per-fighter `mma_moneyline` picks.

`fightModel.pick` (`_winner_pick`) is the **selectivity** verdict: who to lean,
the confidence %, a tier (`Strong` ≥70% / `Lean` ≥60% / `Pass` coin-flip below
`WIN_LEAN_FLOOR`), and that band's measured hit rate. Confidence is well-calibrated,
so filtering to confident picks is the biggest free accuracy lever (raw 66% →
~77% at ≥65%); the frontend renders it as a colour-coded verdict card.

Backtests (live data, measure model accuracy — needs network):

```bash
python3 backtest.py --season 2025 --pitchers 25   # MLB projection accuracy + calibration
python3 mma_backtest.py --since 2022-01-01         # MMA winner/distance/method point-in-time
```

`backtest.py` replays each pitcher start point-in-time (game log filtered to
before the game date — no look-ahead) and reports projection MAE/bias and
probability calibration (Brier + reliability) vs actual results. It measures
whether the *model* is accurate, not betting ROI (that needs paid historical
closing lines).

Live tracking (record today's picks, grade them tonight):

```bash
python3 track.py snapshot                       # MLB: save today's predictions + bet prices -> tracking/<date>.json
python3 track.py close                           # (optional) re-capture closing lines near game time, for CLV
python3 track.py grade                           # once games are final, score them vs results
python3 track.py snapshot --sport mma            # UFC: snapshot a card -> tracking/<date>.mma.json
python3 track.py grade --sport mma --date 2026-06-14   # grade a UFC card vs ESPN results
```

`track.py` is the going-forward counterpart to the backtest. `--sport mlb`
(default) and `--sport mma` are supported; MMA writes `.mma`-suffixed files so a
ballgame and a UFC card on the same date don't collide. `snapshot` runs the exact
app analysis over the slate/card and saves each prediction **with the matched
price**; `grade` pulls results and writes `tracking/<date>[.mma].graded.json` with,
per market, W-L + Brier (accuracy), **ROI** (flat 1u on every +EV pick at the
captured price), and **CLV** (how much the price beat the close — only if `close`
ran). MLB markets = strikeouts/total/moneyline (+ run bias); MMA = moneyline
(winner, from ESPN's `winner` flag), method (KO/Sub/Dec parsed from the
competition `details`), distance (ESPN `status.period`/method). An `overall` block
holds the +EV betting record. The History view tags each graded day with its
`sport`; `renderStatsBar`/the calendar are market-generic and filter by sport
(`historySport`), so the same date can show an MLB *and* a UFC record. Snapshots
live under `tracking/` (gitignored).

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
`MIN_STARTS`, `HOME_FIELD_RUNS` (home edge as projected runs, feeds the Skellam
win prob), `TOTAL_CALIBRATION` (multiplicative run-total correction — the raw
model over-projected totals; `backtest.py` prints a suggested value), and the
count-prop distributions `K_BINOMIAL` / `BB_DISPERSION` / `TOTAL_DISPERSION`.
Change them there; nothing else hard-codes these values.

The game-level win probability is the single-game Poisson/Skellam P(home
outscores away) — not a season-level Pythagorean — so an ace start moves the
moneyline and the total together.

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
- The only browser storage used is `sessionStorage` for optional user-supplied
  API keys (Odds API / Anthropic) and the player-props toggle, entered via the
  "⚙️ Keys" panel and sent as `X-Odds-Api-Key` / `X-Anthropic-Api-Key` /
  `X-Odds-Player-Props` (`"1"`/`"0"`) headers; they override the server's env
  vars for that request and are never persisted server-side. `player_props_enabled`
  takes that per-request override, falling back to `ODDS_PLAYER_PROPS`. Don't add
  other browser storage (not available in all embeds).

## Honest-modeling notes

- A projection alone is not betting value. Positive EV requires the model
  probability to beat the **vig-removed** market probability (`devig_two` in
  `odds.py`). The EV/Kelly block only appears when a real line is matched.
- Kelly is a ceiling, not a target. The UI recommends staking a fraction
  (~¼ Kelly) to tame variance. Small samples are shrunk toward 0.5 so a 5/6
  mirage doesn't dominate confidence.
