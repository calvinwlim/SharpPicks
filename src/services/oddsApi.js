import { ODDS_SPORT_KEYS } from '../constants/index.js';

const ODDS_BASE = 'https://api.the-odds-api.com/v4';

/**
 * Fetches upcoming game odds from The Odds API (free tier: 500 req/month).
 * Returns null silently if no key is provided or on non-fatal errors,
 * so the app continues without odds rather than crashing.
 *
 * @param {string} sport   - One of: NBA, MLB, NFL, NHL, NCAAB
 * @param {string} apiKey  - The Odds API key
 * @returns {Promise<OddsGame[] | null>}
 */
export async function fetchOdds(sport, apiKey) {
  if (!apiKey?.trim()) return null;

  const sportKey = ODDS_SPORT_KEYS[sport];
  if (!sportKey) return null;

  const params = new URLSearchParams({
    apiKey,
    regions:     'us',
    markets:     'h2h,spreads,totals',
    oddsFormat:  'american',
    dateFormat:  'iso',
  });

  try {
    const res = await fetch(`${ODDS_BASE}/sports/${sportKey}/odds/?${params}`);

    if (res.status === 401) {
      console.warn('[OddsAPI] Invalid API key — continuing without odds.');
      return null;
    }
    if (res.status === 422) {
      console.warn('[OddsAPI] Sport may be out of season — continuing without odds.');
      return null;
    }
    if (!res.ok) {
      console.warn(`[OddsAPI] Non-fatal error ${res.status}`);
      return null;
    }

    const data = await res.json();

    // Log remaining quota so user knows their usage
    const remaining = res.headers.get('x-requests-remaining');
    const used      = res.headers.get('x-requests-used');
    if (remaining) console.info(`[OddsAPI] Requests used: ${used} / remaining: ${remaining}`);

    return Array.isArray(data) ? data.map(parseOddsGame) : null;
  } catch (err) {
    console.warn('[OddsAPI] Network error:', err.message);
    return null;
  }
}

function parseOddsGame(game) {
  return {
    id:           game.id,
    homeTeam:     game.home_team,
    awayTeam:     game.away_team,
    commenceTime: game.commence_time,
    bookmakers:   (game.bookmakers ?? []).map((b) => ({
      name:    b.title,
      markets: (b.markets ?? []).reduce((acc, m) => {
        acc[m.key] = m.outcomes;
        return acc;
      }, {}),
    })),
  };
}

/**
 * Formats odds data into a readable context block for Claude.
 * Shows consensus lines from the top 3 books (saves tokens while keeping it actionable).
 */
export function formatOddsForContext(oddsGames) {
  if (!oddsGames?.length) return '';

  let ctx = '\nCONSENSUS ODDS (The Odds API — Multiple Books):\n';

  oddsGames.forEach((game) => {
    ctx += `\n${game.awayTeam} @ ${game.homeTeam}:\n`;

    const books = game.bookmakers.slice(0, 4); // top 4 books
    books.forEach((book) => {
      const parts = [];

      const spreads = book.markets.spreads ?? [];
      const totals  = book.markets.totals  ?? [];
      const h2h     = book.markets.h2h     ?? [];

      const awaySpread = spreads.find((o) => o.name === game.awayTeam);
      const overLine   = totals.find((o) => o.name === 'Over');
      const awayML     = h2h.find((o) => o.name === game.awayTeam)?.price;
      const homeML     = h2h.find((o) => o.name === game.homeTeam)?.price;

      if (awaySpread) parts.push(`Spread: ${game.awayTeam} ${awaySpread.point > 0 ? '+' : ''}${awaySpread.point} (${awaySpread.price})`);
      if (overLine)   parts.push(`Total: ${overLine.point}`);
      if (awayML != null) {
        parts.push(`ML: Away ${awayML > 0 ? '+' : ''}${awayML} / Home ${homeML > 0 ? '+' : ''}${homeML}`);
      }

      if (parts.length) ctx += `  ${book.name}: ${parts.join(' | ')}\n`;
    });

    // Show line spread across books (indicates market uncertainty)
    const allSpreads = game.bookmakers
      .flatMap((b) => b.markets.spreads ?? [])
      .filter((o) => o.name === game.awayTeam)
      .map((o) => o.point);

    if (allSpreads.length > 1) {
      const min = Math.min(...allSpreads);
      const max = Math.max(...allSpreads);
      if (min !== max) ctx += `  ⚠ Spread range across books: ${min} to ${max} (soft line — possible edge)\n`;
    }
  });

  return ctx;
}

/**
 * Returns a human-readable summary of The Odds API usage for display in the UI.
 */
export function getOddsApiUsageSummary(headers) {
  const remaining = headers?.get?.('x-requests-remaining');
  if (!remaining) return null;
  return `${remaining} req remaining this month`;
}
