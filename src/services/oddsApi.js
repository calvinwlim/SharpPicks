import { ODDS_SPORT_KEYS, PROP_MARKETS } from '../constants/index.js';

const ODDS_BASE = 'https://api.the-odds-api.com/v4';

/** Returns "2:34 PM ET" timestamp string for the current moment */
function nowET() {
  return new Date().toLocaleTimeString('en-US', {
    hour:       'numeric',
    minute:     '2-digit',
    timeZone:   'America/New_York',
    timeZoneName: 'short',
  });
}

// ─── Game lines (spread / total / moneyline) ──────────────────────────────────

/**
 * Fetches upcoming game odds from The Odds API (free tier: 500 req/month).
 * Returns null silently if no key is provided or on non-fatal errors.
 *
 * @returns {Promise<{ games: OddsGame[], fetchedAt: string } | null>}
 */
export async function fetchOdds(sport, apiKey) {
  if (!apiKey || !apiKey.trim()) return null;

  const sportKey = ODDS_SPORT_KEYS[sport];
  if (!sportKey) return null;

  const params = new URLSearchParams({
    apiKey,
    regions:    'us',
    markets:    'h2h,spreads,totals',
    oddsFormat: 'american',
    dateFormat: 'iso',
  });

  try {
    const res = await fetch(`${ODDS_BASE}/sports/${sportKey}/odds/?${params}`);

    if (res.status === 401) { console.warn('[OddsAPI] Invalid key'); return null; }
    if (res.status === 422) { console.warn('[OddsAPI] Sport out of season'); return null; }
    if (!res.ok)            { console.warn(`[OddsAPI] Error ${res.status}`); return null; }

    const data      = await res.json();
    const remaining = res.headers.get('x-requests-remaining');
    const used      = res.headers.get('x-requests-used');
    if (remaining) console.info(`[OddsAPI] Used: ${used} / Remaining: ${remaining}`);

    return Array.isArray(data)
      ? { games: data.map(parseOddsGame), fetchedAt: nowET() }
      : null;
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
    bookmakers:   (game.bookmakers || []).map((b) => ({
      name:    b.title,
      markets: (b.markets || []).reduce((acc, m) => {
        acc[m.key] = m.outcomes;
        return acc;
      }, {}),
    })),
  };
}

// ─── Player props ─────────────────────────────────────────────────────────────

/**
 * Fetches player prop lines for every game in today's slate.
 * Uses 2 API requests per game (events list + odds per event).
 * Only runs when the user has opted in (saves free-tier quota).
 *
 * @param {string} sport    - NBA, MLB, NFL, NHL
 * @param {string} date     - ISO "YYYY-MM-DD"
 * @param {string} apiKey
 * @returns {Promise<{ context: string, fetchedAt: string } | null>}
 */
export async function fetchPlayerProps(sport, date, apiKey) {
  if (!apiKey || !apiKey.trim()) return null;
  const sportKey = ODDS_SPORT_KEYS[sport];
  const markets  = PROP_MARKETS[sport];
  if (!sportKey || !markets) return null;

  try {
    // Step 1: get event IDs for this date
    const from   = `${date}T00:00:00Z`;
    const to     = `${date}T23:59:59Z`;
    const eParams = new URLSearchParams({ apiKey: apiKey.trim(), commenceTimeFrom: from, commenceTimeTo: to });
    const eRes    = await fetch(`${ODDS_BASE}/sports/${sportKey}/events?${eParams}`);
    if (!eRes.ok) return null;

    const events = await eRes.json();
    if (!Array.isArray(events) || !events.length) return null;

    const remaining = parseInt(eRes.headers.get('x-requests-remaining') || '999', 10);
    // Each event props call costs ~2-3 credits. Bail if quota is low.
    if (remaining < events.length * 3 + 5) {
      console.warn('[OddsAPI] Low quota — skipping player props to preserve requests');
      return null;
    }

    // Step 2: fetch props for each event in parallel
    const propResults = await Promise.all(
      events.map((ev) => fetchEventProps(sportKey, ev.id, markets, apiKey.trim()))
    );

    // Combine into a single context block
    const lines = [];
    events.forEach((ev, i) => {
      const props = propResults[i];
      if (props && props.length) {
        lines.push(`${ev.away_team} @ ${ev.home_team}:`);
        props.forEach((p) => lines.push(`  ${p}`));
      }
    });

    if (!lines.length) return null;

    const fetchedAt = nowET();
    const context = (
      `\nPLAYER PROP LINES — fetched at ${fetchedAt} (The Odds API):\n` +
      'Use these exact lines in your pick descriptions.\n\n' +
      lines.join('\n')
    );

    return { context, fetchedAt };
  } catch (err) {
    console.warn('[OddsAPI] Props error:', err.message);
    return null;
  }
}

async function fetchEventProps(sportKey, eventId, markets, apiKey) {
  try {
    const params = new URLSearchParams({
      apiKey,
      regions:    'us',
      markets,
      oddsFormat: 'american',
      // limit to top 3 books to reduce noise
      bookmakers: 'draftkings,fanduel,betmgm',
    });
    const res = await fetch(`${ODDS_BASE}/sports/${sportKey}/events/${eventId}/odds?${params}`);
    if (!res.ok) return [];

    const data = await res.json();
    return formatPropLines(data);
  } catch {
    return [];
  }
}

/**
 * Turns raw Odds API event odds into compact readable lines.
 * Output: ["Jalen Brunson — Points: O 28.5 (-115) / U (-105)", ...]
 */
function formatPropLines(event) {
  if (!event || !event.bookmakers) return [];

  // Collect all prop outcomes across all books, keyed by "player:market"
  const propMap = {};

  event.bookmakers.forEach((book) => {
    (book.markets || []).forEach((market) => {
      const marketLabel = market.key
        .replace('player_', '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());

      (market.outcomes || []).forEach((outcome) => {
        // Each outcome: { name: "Player Name", description: "Over"/"Under", price: -115, point: 28.5 }
        const player = outcome.name || outcome.description;
        const side   = outcome.description || '';
        const key    = `${player}||${marketLabel}`;
        if (!propMap[key]) propMap[key] = { player, label: marketLabel, over: null, under: null, point: outcome.point };
        if (side === 'Over')  propMap[key].over  = outcome.price;
        if (side === 'Under') propMap[key].under = outcome.price;
        if (outcome.point != null) propMap[key].point = outcome.point;
      });
    });
  });

  // Format each prop as one line
  const lines = [];
  Object.values(propMap).forEach(({ player, label, over, under, point }) => {
    if (!player || point == null) return;
    const overStr  = over  != null ? `${over  > 0 ? '+' : ''}${over}`  : '—';
    const underStr = under != null ? `${under > 0 ? '+' : ''}${under}` : '—';
    lines.push(`${player} — ${label}: O/U ${point}  (O ${overStr} / U ${underStr})`);
  });

  // Sort alphabetically by player name for readability
  lines.sort();
  return lines;
}

// ─── Game odds context formatter ──────────────────────────────────────────────

/**
 * Formats game-level odds into a context block for the LLM.
 */
export function formatOddsForContext(oddsResult) {
  if (!oddsResult) return '';
  const { games, fetchedAt } = oddsResult;
  if (!games || !games.length) return '';

  let ctx = `\nCONSENSUS GAME LINES — fetched at ${fetchedAt} (The Odds API):\n`;

  games.forEach((game) => {
    ctx += `\n${game.awayTeam} @ ${game.homeTeam}:\n`;

    const books = game.bookmakers.slice(0, 4);
    books.forEach((book) => {
      const parts = [];
      const spreads = book.markets.spreads || [];
      const totals  = book.markets.totals  || [];
      const h2h     = book.markets.h2h     || [];

      const awaySpread = spreads.find((o) => o.name === game.awayTeam);
      const overLine   = totals.find((o)  => o.name === 'Over');
      const awayML     = (h2h.find((o)    => o.name === game.awayTeam) || {}).price;
      const homeML     = (h2h.find((o)    => o.name === game.homeTeam) || {}).price;

      if (awaySpread) parts.push(`Spread: ${game.awayTeam} ${awaySpread.point > 0 ? '+' : ''}${awaySpread.point} (${awaySpread.price})`);
      if (overLine)   parts.push(`Total: ${overLine.point}`);
      if (awayML != null) parts.push(`ML: Away ${awayML > 0 ? '+' : ''}${awayML} / Home ${homeML > 0 ? '+' : ''}${homeML}`);

      if (parts.length) ctx += `  ${book.name}: ${parts.join(' | ')}\n`;
    });

    // Flag soft lines (spread range across books)
    const allSpreads = game.bookmakers
      .flatMap((b) => b.markets.spreads || [])
      .filter((o) => o.name === game.awayTeam)
      .map((o) => o.point);

    if (allSpreads.length > 1) {
      const min = Math.min(...allSpreads);
      const max = Math.max(...allSpreads);
      if (min !== max) ctx += `  ⚠ Spread range: ${min} to ${max} across books (soft line)\n`;
    }
  });

  return ctx;
}
