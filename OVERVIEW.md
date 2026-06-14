# Sharp Slate — What This Repo Does

Sharp Slate aggregates **free** sports data, runs a transparent statistical model
for each sport, and surfaces where the model **disagrees with the betting market**
— framed honestly as analysis, never as guaranteed winners. It grades three
sports today: **MLB ⚾, NBA 🏀, and UFC/MMA 🥊**.

The guiding principle throughout: *a projection is not an edge.* The app shows
the numbers behind every pick (the "discrepancy signals") so you can form your
own read, and only computes real expected value (EV) when a live betting line is
supplied.

---

## How it's put together

```
backend/        FastAPI app — fetches data, runs the models, serves JSON + the static UI
frontend/       Static single-page UI (no build step): index.html + styles.css + app.js
scripts/        Offline data builders (e.g. the UFC dataset)
*backtest*.py   Offline accuracy/calibration harnesses
test_integration*.py   Hermetic end-to-end tests (no network)
```

One FastAPI process serves both the JSON API and the static frontend. All API
keys stay server-side. Data flows one direction: **client fetch → model grades →
JSON → the UI renders**. The frontend is sport-aware via a `?sport=` parameter
and renders each sport from a shared set of card components.

**API surface**
- `GET /api/health` → `{ ok, flags }`
- `GET /api/slate?date=YYYY-MM-DD&sport=mlb|nba|mma` → the day's games/fights
- `GET /api/analyze/{id}?date=&sport=mlb|nba|mma` → the full model output for one game/fight

Every pick carries a `signals[]` list — the discrepant inputs behind the number,
each tagged with which side it leans — so the UI can flag where the evidence
agrees or conflicts with the model.

---

## ⚾ MLB

**Data (no key):** MLB Stats API (`statsapi.mlb.com`) — schedule, team
offensive/run-prevention rates, pitcher game logs, platoon splits, lineup, and
bullpen. Open-Meteo for weather. The Odds API (optional, needs a key) for live
lines. Baseball Savant for pitcher Statcast skill.

**What it grades**
- **Pitcher props** — strikeouts (Poisson, blended with Statcast season K%) and
  walks (negative-binomial, tuned by backtest).
- **Batter props** — hits / total bases / home runs (binomial for the per-at-bat
  hit & HR; Poisson for total bases), for the confirmed lineup.
- **Game model** — pitcher-aware run projection (each team's offense vs the
  opposing **starter** + bullpen), Pythagorean win probability, total, and
  moneyline.
- **NRFI/YRFI** and **F5 (first-5-innings)** — derived from the starters.

**Key adjustments:** opponent K%/BB% (lineup-aware), platoon (vs LHB/RHB),
home-plate umpire tendencies, park factors, wind direction relative to field
orientation, weather/temperature, bullpen quality, rest. Each is clamped and
neutral when its data is missing.

**Honesty layer:** EV/Kelly only appear when a real line is matched (vig removed
via de-vig). Backtested for accuracy — see commands below.

---

## 🏀 NBA

**Data (no key):** `cdn.nba.com` for the schedule; `stats.nba.com` (browser
headers required) for advanced team ratings (offensive/defensive rating, pace),
season + last-10 splits, home/road splits, opponent stat-defense, and player
game logs.

**What it grades**
- **Game model** — the possession/efficiency standard: projected points =
  (your offensive rating vs their defensive rating, relative to league) ×
  expected pace; margin → win probability via a normal distribution. Adjusted
  for **home court**, **rest / back-to-backs**, and a recent-form blend. Outputs
  projected score, spread, total, and win probability.
- **Player props** — points / rebounds / assists / threes for the rotation.
  Projection = season average blended with recent form, scaled by the
  **opponent's stat-defense** (how much they allow of that stat) and **pace**;
  graded with a normal using the player's own game-to-game variance.

**Discrepancy signals:** net-rating gap, offense-vs-defense matchup edge, L10
form trend, pace, rest, home court, head-to-head, home/road splits.

---

## 🥊 UFC / MMA

**Data:** ESPN's MMA API (no key) for the card — fighters, records, rounds.
Granular fighter **rate stats are bundled** in `backend/data/ufc_fighters.json`
because there's no free live API for them; that file is generated offline by
aggregating the public ufcstats mirror (per-fight significant strikes,
takedowns, knockdowns, control time, and methods → career rates).

**What it grades (per fight)**
- **Winner** — a logistic on a composite skill differential (striking net,
  grappling, defense, durability, finishing, experience, reach, age). MMA is
  high-variance, so win probabilities are clamped — a lean, not a lock.
- **Method** — KO/TKO vs Submission vs Decision.
- **Distance / round betting** — per-minute finish hazard → P(goes the
  distance) and a round-by-round finish distribution.
- **Significant strikes** (each fighter + total) and **takedowns** — output
  blended with what the opponent absorbs/allows, over the expected fight length.

**Discrepancy signals:** striking net, volume/accuracy, defense, grappling,
finishing power, durability, experience, reach, age.

**Comps (nearest-neighbor):** alongside the parametric model, every historical
UFC fight is encoded as a *style-differential vector* (favorite minus underdog,
plus combined finish/pace context). An upcoming fight is matched to its most
similar past "variants" and the app reports how those actually turned out —
favorite win %, KO/Sub/Dec split, distance %, typical significant strikes — plus
the named most-similar bouts. A case-based second opinion that often disagrees
usefully with the parametric model (and is independently backtested ~61%
favorite accuracy on holdout).

**Backtested** point-in-time on 1,000+ historical fights (62.9% winner accuracy,
well-calibrated distance). Recent-form weighting was A/B-tested and *rejected* —
fighters have too few bouts for recency to beat the full career.

---

## Console commands

Run everything from the repo root. On this Windows setup the project venv is at
`.venv` — use `.venv\Scripts\python.exe` (or activate the venv and use `python`).

### Run the app
```
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```
Then open <http://localhost:8000>. Pick a date, choose the ⚾/🏀/🥊 tab, and hit
Visualize. (`./run.sh` does venv + deps + server on Unix.)

### Tests (synthetic data, no network)
```
.venv\Scripts\python.exe test_integration.py        # MLB end-to-end
.venv\Scripts\python.exe test_integration_nba.py    # NBA end-to-end
.venv\Scripts\python.exe test_integration_mma.py    # MMA end-to-end
```

### UFC fighter dataset (rebuild/refresh after new events)
```
.venv\Scripts\python.exe scripts\build_ufc_dataset.py
```
Fetches the ufcstats CSV mirror, aggregates career rate stats, and writes
`backend/data/ufc_fighters.json` (~2,700 fighters, ~10–20s).

UFC comps dataset (matchup vectors for nearest-neighbor matching; rebuild after
new events). Prints a holdout validation when it finishes:
```
.venv\Scripts\python.exe scripts\build_mma_comps.py
```
Writes `backend/data/ufc_fight_vectors.json` (~3,000 point-in-time fight vectors).

### Backtests (live data — measure model accuracy/calibration, not betting ROI)
```
.venv\Scripts\python.exe backtest.py --season 2025 --pitchers 25   # MLB projection MAE + calibration
.venv\Scripts\python.exe backtest.py --sweep                       # tune the walk distribution
.venv\Scripts\python.exe mma_backtest.py --since 2022-01-01        # MMA winner/distance/method point-in-time
```

### Optional configuration (environment variables / `.env`)
- `ODDS_API_KEY` — enables live odds + EV/Kelly (The Odds API).
- `ODDS_PLAYER_PROPS=1` — fetch player-prop markets too.
- `ANTHROPIC_API_KEY` (+ `ANTHROPIC_MODEL`) — AI-rephrased pick narratives.

Without any keys the app runs fully in "analysis only" mode — projections and
discrepancy signals, just no EV (which requires a real market price).
