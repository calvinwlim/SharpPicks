# SharpEdge — AI Sports Betting Analysis

AI-powered sharp betting analysis using real game data, live odds, and Claude AI.

## Data Sources

| Source | Cost | What it provides |
|--------|------|-----------------|
| **ESPN API** | Free, no key | Game schedule, venue, basic lines |
| **The Odds API** | Free tier (500 req/mo) | Consensus lines from 20+ books |
| **Claude AI** | Pay-per-use | H2H stats, injury research, +EV picks |

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Set up environment variables
cp .env.example .env.local
# Edit .env.local with your API keys

# 3. Start the dev server
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

## API Keys

### Required — Anthropic (Claude AI)
Get your key at [console.anthropic.com](https://console.anthropic.com).
Add to `.env.local` as `VITE_ANTHROPIC_API_KEY`.
You can also enter it directly in the app's Settings panel.

### Optional — The Odds API
Free tier at [the-odds-api.com](https://the-odds-api.com) — 500 requests/month.
Provides real consensus lines from DraftKings, FanDuel, BetMGM, and 17+ other books.
Without this key, the app uses ESPN's single-book odds.
Add to `.env.local` as `VITE_ODDS_API_KEY`.

## How It Works

1. **Slate fetch** — The app queries ESPN's free API to get the confirmed game schedule, venues, records, and basic odds. No hallucinated games.
2. **Odds enrichment** — If you've provided an Odds API key, it fetches consensus lines from multiple sportsbooks, enabling line-shopping analysis.
3. **AI analysis** — Claude receives the confirmed slate + real odds and uses web search to find injury reports, advanced stats, and H2H trends. It then generates sharp picks with convergent edge analysis.

## Context Box

The sidebar "Context & Intel" box is your most powerful prompt tool:
- Paste injury news ("LeBron questionable with knee soreness")
- Paste specific lines ("I'm seeing Celtics -7.5 at BetMGM")
- Name players/props you want focus on
- Add situational intel ("back-to-back, flew in from LA last night")

## Additional Free APIs (for future integration)

- **MLB Stats API** — `statsapi.web.nlb.com` — pitcher/hitter splits, game logs
- **Ball Don't Lie** — `api.balldontlie.io` — NBA player averages (free key at balldontlie.io)
- **ESPN CDN Stats** — `cdn.espn.com/core` — team and player advanced stats
