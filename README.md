# Sharp Slate ⚾

**Aggregate free MLB data, grade every probable pitcher's strikeout prop in a
sharp-bettor style, and — when live odds are available — surface the bets where
the model genuinely disagrees with the market.**

Pick a date, hit **Visualize**, and Sharp Slate pulls that day's slate, projects
each starter's strikeouts, walks the historical splits that sharp bettors lean
on (hit rate vs this opponent, vs high-strikeout offenses, vs high-walk
offenses, home/away, recent form, current streak), and ranks the day's best
edges on a live **Top Board**.

---

## ⚠️ Read this first — what this tool is and isn't

Sports betting is gambling. It carries real financial risk and a lot of
variance, and **no model can tell you the outcome of a game**. Sharp Slate does
**not** predict winners or promise profit. What it does is more modest and more
honest:

- It estimates a probability for each prop from data, and
- when you supply real betting lines, it removes the bookmaker's margin (the
  "vig") and tells you whether the model's probability is high enough to make the
  bet **+EV** (positive expected value) over the long run.

A positive edge can — and regularly will — still lose on any given night. Expected
value is a long-run average, not a guarantee. A projection on its own is **not** an
edge; an edge only exists relative to a price. Treat every number here as an input
to your own judgment.

**Bet only what you can afford to lose. 21+, and only where betting is legal in
your jurisdiction. This is not financial advice.** If gambling stops being fun,
in the US call **1-800-GAMBLER**.

---

## Features

- **Daily slate view** — every MLB game for any date you choose, with start
  time, day/night, venue, and both probable pitchers.
- **Strikeout prop model** — a strikeout projection per starter, adjusted for the
  opponent's strikeout tendencies, then graded against the prop line.
- **Sharp-style splits** — the same matchup history a sharp bettor cites, with
  small samples visibly flagged so a "5/6" mirage doesn't fool you.
- **Scorecard chip** — a compact bar chart of each pitcher's recent strikeouts
  with the prop line drawn as a dashed rule, so over/under is readable at a glance.
- **True EV + Kelly** *(when you add a free odds key)* — vig-removed market
  probability, expected value %, and a Kelly stake suggestion (with a fractional-
  Kelly warning baked in).
- **Game model** — a Pythagorean + log5 win-probability estimate per game, and a
  moneyline EV read when odds are present.
- **Top Board** — the slate's best edges ranked by EV (or by model confidence in
  analysis-only mode).
- **Optional AI write-ups** — Claude can rephrase each pick into natural prose,
  constrained to the numbers the model actually computed.

Everything runs from **one process** with **no build step**, and **works with
zero API keys**.

---

## Free data sources

| Source | Used for | Key required |
| --- | --- | --- |
| [MLB Stats API](https://statsapi.mlb.com) | schedule, probable pitchers, team strikeout/walk rates, pitcher game logs, run prevention | **No** |
| [The Odds API](https://the-odds-api.com/) | live moneylines and (optionally) strikeout prop lines | Optional (free tier: 500 req/mo) |
| [Anthropic API](https://console.anthropic.com/) | optional AI-written pick explanations | Optional |

---

## Quick start

You need **Python 3.10+**.

```bash
# from the project folder
./run.sh
```

That script creates a virtualenv, installs dependencies, copies `.env.example`
to `.env` if you don't have one, and starts the server. Then open:

```
http://localhost:8000
```

Prefer to do it by hand?

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional; blanks are fine
uvicorn backend.main:app --reload
```

### Running with no keys (default)

Out of the box, Sharp Slate uses only the free MLB Stats API. You get the full
slate, projections, splits, scorecard charts, and the game model. Picks are
labeled **"analysis only"** because there's no market line to measure an edge
against. This is the honest default: real model, no pretend edges.

### Unlocking true expected-value mode

1. Get a free key at <https://the-odds-api.com/>.
2. Put it in `.env`:
   ```
   ODDS_API_KEY=your_key_here
   ```
3. Restart. The **Odds** pill in the header lights up, and picks now show
   vig-removed market probability, **EV %**, and a **Kelly** stake.

Strikeout **prop** lines are a separate, quota-hungrier market. Keep them off
(moneylines only) or turn them on explicitly:

```
ODDS_PLAYER_PROPS=1
```

### Optional AI explanations

Add an Anthropic key to have Claude rewrite each pick in natural language
(constrained to the computed numbers — it invents nothing):

```
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-4-6
```

Without it, a clean deterministic template is used instead. The **AI** pill shows
which mode you're in.

---

## How the model works

### 1. Projection
The starter's baseline is his mean strikeouts over his last 10 starts. That's
scaled by an **opponent factor** = the opponent's team strikeout rate ÷ league
average, clamped to a sane band so a single extreme matchup can't run away with
the number. The result is the projected mean (λ) of a Poisson distribution.

### 2. Probability
From λ, a hand-rolled Poisson CDF/survival function gives the probability of
going over or under a given strikeout line (no SciPy dependency). With a live
line, that exact line is used. Without one, the model tests an over just below
the projection and an under just above it, and keeps whichever side it favors
more strongly.

### 3. Situational splits
At the chosen line and side, Sharp Slate computes the pitcher's hit rate across
the splits sharp bettors actually cite — all starts, this specific opponent,
top-strikeout offenses, top-walk offenses (for overs), home/away, last 10, and
the current streak — using **per-season** opponent ranks so a team that was elite
two years ago is judged by that year's rank, not today's.

### 4. Confidence
A 0–100 score blends the model probability with a **sample-size-shrunk** average
of the key splits (each pulled toward a coin flip by a pseudo-count, so 5/6 in a
tiny sample doesn't masquerade as 83%). Confidence is capped when a pitcher has
very few starts, and small samples are flagged in the UI.

### 5. Edge (only with a market)
This is the part that actually matters for betting. Both sides' prices are
converted to implied probabilities and the bookmaker's margin is removed
(**de-vig**) to get the fair market probability. If the model's probability beats
that, the bet is **+EV**, and the app reports the EV % and a **Kelly** stake.

> **On Kelly:** full Kelly maximizes long-run growth but is wildly volatile and
> assumes your probability is exactly right (it never is). The UI recommends
> staking a **fraction** (around a quarter) of the Kelly number. When the model
> sees no edge, it says so and recommends passing.

### Game model
Separately, each game gets a win-probability estimate from team runs
scored/allowed (a Pythagorean expectation) combined via log5 with a small home-
field adjustment, plus a moneyline EV read when odds are present.

---

## Analysis-only vs. market mode at a glance

| | No odds key | With odds key |
| --- | --- | --- |
| Slate, probables, projections | ✅ | ✅ |
| Situational splits + scorecard chips | ✅ | ✅ |
| Game win-probability model | ✅ | ✅ |
| Vig-removed market probability | — | ✅ |
| Expected value (EV %) | — | ✅ |
| Kelly stake suggestion | — | ✅ |
| Top Board ranked by | confidence | expected value |

---

## Project structure

```
sharp-slate/
├── backend/
│   ├── main.py         FastAPI endpoints; per-game orchestration
│   ├── mlb.py          MLB Stats API client (no key)
│   ├── odds.py         The Odds API client + betting math (EV, Kelly, de-vig)
│   ├── analysis.py     the model (projection, splits, confidence, EV, game model)
│   ├── ai.py           narrative: deterministic template + optional Claude
│   └── cache.py        in-process TTL cache with per-key locks
├── frontend/
│   ├── index.html      structure + templates + fonts + Chart.js (CDN)
│   ├── styles.css      design system
│   └── app.js          UI logic, charts, Top Board
├── test_integration.py end-to-end test with synthetic data (no network)
├── requirements.txt
├── .env.example
├── run.sh
└── CLAUDE.md           orientation for Claude Code / contributors
```

---

## Using with Claude Code

This repo ships a [`CLAUDE.md`](./CLAUDE.md) that gives Claude Code an accurate
map of the architecture, the API contract, and step-by-step recipes for the
common changes (tuning the model, adding a prop type, adding a sport, restyling).
Point Claude Code at the project root and ask it to, say, "add a batter
total-bases prop" — the conventions it needs are written down.

---

## Extending it

The frontend is deliberately **sport- and prop-agnostic**: it renders any pick
that follows the documented dict shape. To add a market, write an
`analyze_<prop>(...)` in `backend/analysis.py` that returns that shape, fetch the
needed logs in `backend/mlb.py`, and append the result to `picks` in
`backend/main.py`. See CLAUDE.md for the full checklist.

## Roadmap

- Batter props (hits, total bases, home runs) using the same split engine.
- More sports (the NBA made-threes style of pick maps cleanly onto this model).
- Lightweight backtesting so you can see how a class of pick has actually done.
- Pitch-level and park-factor adjustments to sharpen the projection.

---

## Caveats & limitations

- Projections regress to recent form and a team-level opponent factor; they don't
  yet model individual batter matchups, weather, catcher framing, or umpire
  tendencies.
- Free data has gaps — probable pitchers can be unconfirmed until close to game
  time, and early-season samples are thin (and flagged).
- The Odds API free tier is rate-limited; responses are cached to stretch it.
- This is a decision-support tool, not an autobettor and not financial advice.

---

*Built to find spots where the numbers disagree with the price — not to promise
winners. Bet responsibly.*
