import { ESPN_SPORT_PATHS } from '../constants/index.js';
import { toEasternTime, toESPNDate } from '../utils/dateUtils.js';

const ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports';

// ─── Main entry point ─────────────────────────────────────────────────────────

/**
 * Fetches and parses the game/fight slate for a sport and date from ESPN's free API.
 * For UFC, flattens the fight card into individual fights.
 *
 * @param {string} sport  - NBA, MLB, NFL, NHL, NCAAB, UFC
 * @param {string} date   - ISO "YYYY-MM-DD"
 * @returns {Promise<Game[]>}
 */
export async function fetchGameSlate(sport, date) {
  const path = ESPN_SPORT_PATHS[sport];
  if (!path) throw new Error(`Sport "${sport}" is not supported.`);

  const url = `${ESPN_BASE}/${path}/scoreboard?dates=${toESPNDate(date)}`;

  let data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`ESPN returned ${res.status}`);
    data = await res.json();
  } catch (err) {
    throw new Error(`Could not reach ESPN API: ${err.message}`);
  }

  const events = data.events || [];

  if (sport === 'UFC') {
    // Each ESPN event is a fight card. Flatten all competitions (individual fights)
    return events.flatMap(parseMMACard).filter(Boolean);
  }

  return events.map(parseESPNEvent).filter(Boolean);
}

// ─── Standard team-sport parser ───────────────────────────────────────────────

function parseESPNEvent(event) {
  try {
    const comp = event.competitions && event.competitions[0];
    if (!comp) return null;

    const competitors = comp.competitors || [];
    const home = competitors.find((c) => c.homeAway === 'home');
    const away = competitors.find((c) => c.homeAway === 'away');
    const teamA = home || competitors[0];
    const teamB = away || competitors[1];

    const espnOdds = comp.odds && comp.odds[0] ? comp.odds[0] : null;

    return {
      id:        event.id,
      name:      event.name,
      shortName: event.shortName,
      date:      event.date,
      gameTime:  toEasternTime(event.date),
      status:    (event.status && event.status.type && event.status.type.description) || 'Scheduled',
      isMMA:     false,

      homeTeam: parseTeam(teamA),
      awayTeam: parseTeam(teamB),

      venue: {
        name:   (comp.venue && comp.venue.fullName) || '',
        city:   (comp.venue && comp.venue.city)     || '',
        state:  (comp.venue && comp.venue.state)    || '',
        indoor: comp.venue ? comp.venue.indoor !== false : true,
      },

      odds: espnOdds ? {
        provider:      (espnOdds.provider && espnOdds.provider.name) || 'ESPN Bet',
        details:       espnOdds.details     || '',
        spread:        espnOdds.spread      || null,
        total:         espnOdds.overUnder   || null,
        homeMoneyline: (espnOdds.homeTeamOdds && espnOdds.homeTeamOdds.moneyLine) || null,
        awayMoneyline: (espnOdds.awayTeamOdds && espnOdds.awayTeamOdds.moneyLine) || null,
        homeFavorite:  (espnOdds.homeTeamOdds && espnOdds.homeTeamOdds.favorite)  || false,
      } : null,

      weather: comp.weather
        ? { temperature: comp.weather.temperature, conditionId: comp.weather.conditionId }
        : null,

      broadcasts: (comp.broadcasts || []).flatMap((b) => b.names || []),
    };
  } catch {
    return null;
  }
}

function parseTeam(competitor) {
  if (!competitor) return { id: null, name: 'TBD', abbreviation: 'TBD', record: '' };
  return {
    id:           (competitor.team && competitor.team.id)           || null,
    name:         (competitor.team && competitor.team.displayName)  || 'TBD',
    abbreviation: (competitor.team && competitor.team.abbreviation) || '',
    color:        (competitor.team && competitor.team.color)        || '',
    record:       (competitor.records && competitor.records[0] && competitor.records[0].summary) || '',
    score:        competitor.score || null,
  };
}

// ─── MMA/UFC parser ───────────────────────────────────────────────────────────

/**
 * Parses a UFC fight card event into individual fight "games".
 * One ESPN event (the card) → many competitions (fights) → many game objects.
 */
function parseMMACard(event) {
  const cardName  = event.name || 'UFC Event';
  const cardDate  = event.date;
  const cardVenue = event.competitions && event.competitions[0] && event.competitions[0].venue
    ? event.competitions[0].venue
    : {};

  return (event.competitions || []).map((comp) => parseMMAFight(comp, cardName, cardDate, cardVenue));
}

function parseMMAFight(comp, cardName, cardDate, cardVenue) {
  try {
    const fighters   = comp.competitors || [];
    const fighter1   = parseFighter(fighters[0]);
    const fighter2   = parseFighter(fighters[1]);
    if (!fighter1 || !fighter2) return null;

    // Weight class from competition type or headlines
    const weightClass = (comp.type && comp.type.text)
      || ((comp.headlines || []).find((h) => h.description && h.description.includes('lbs')) || {}).description
      || '';

    const isTitleFight = (comp.headlines || []).some((h) => {
      const t = ((h.shortLinkText || '') + (h.description || '')).toLowerCase();
      return t.includes('title') || t.includes('championship') || t.includes('belt');
    });

    const espnOdds = comp.odds && comp.odds[0] ? comp.odds[0] : null;

    return {
      id:          comp.id,
      name:        `${fighter1.name} vs ${fighter2.name}`,
      shortName:   `${fighter1.abbreviation} vs ${fighter2.abbreviation}`,
      cardName,
      date:        cardDate,
      gameTime:    toEasternTime(cardDate),
      status:      (comp.status && comp.status.type && comp.status.type.description) || 'Scheduled',
      isMMA:       true,
      isTitleFight,
      weightClass,

      // Reuse homeTeam/awayTeam slots for fighter1/fighter2 so the rest of the app is compatible
      homeTeam: fighter1,
      awayTeam: fighter2,

      venue: {
        name:   cardVenue.fullName || '',
        city:   cardVenue.city    || '',
        state:  cardVenue.state   || '',
        indoor: true,
      },

      odds: espnOdds ? {
        provider:      (espnOdds.provider && espnOdds.provider.name) || 'ESPN Bet',
        details:       espnOdds.details   || '',
        homeMoneyline: (espnOdds.homeTeamOdds && espnOdds.homeTeamOdds.moneyLine) || null,
        awayMoneyline: (espnOdds.awayTeamOdds && espnOdds.awayTeamOdds.moneyLine) || null,
        homeFavorite:  (espnOdds.homeTeamOdds && espnOdds.homeTeamOdds.favorite)  || false,
        total:         espnOdds.overUnder || null,   // rounds total
      } : null,

      weather:    null,
      broadcasts: (comp.broadcasts || []).flatMap((b) => b.names || []),
    };
  } catch {
    return null;
  }
}

function parseFighter(competitor) {
  if (!competitor) return null;
  const athlete = competitor.athlete || {};
  const name    = athlete.displayName || athlete.fullName || 'TBD';
  // Abbreviation = last name, max 8 chars
  const lastName = name.split(' ').pop().slice(0, 8).toUpperCase();
  return {
    id:           athlete.id    || null,
    name,
    abbreviation: lastName,
    record:       athlete.record || '',
    color:        '',
    score:        competitor.score || null,
    country:      (athlete.flag && athlete.flag.alt) || '',
  };
}

// ─── Context formatters ───────────────────────────────────────────────────────

/**
 * Formats the ESPN game/fight slate into a readable LLM context block.
 */
export function formatSlateForContext(games) {
  if (!games || !games.length) return 'No games found for this date.';

  // Detect MMA slate
  if (games[0] && games[0].isMMA) {
    return formatMMASlateForContext(games);
  }

  const lines = games.map((g, i) => {
    let line = `Game ${i + 1}: ${g.awayTeam.name} (${g.awayTeam.record}) @ ${g.homeTeam.name} (${g.homeTeam.record})\n`;
    line += `  Time:  ${g.gameTime}\n`;

    if (g.venue.name) {
      line += `  Venue: ${g.venue.name}${g.venue.city ? ', ' + g.venue.city : ''}${g.venue.state ? ', ' + g.venue.state : ''}`;
      line += g.venue.indoor ? '' : ' [OUTDOOR]';
      line += '\n';
    }

    if (g.odds) {
      const { details, total, homeMoneyline, awayMoneyline, homeFavorite, provider } = g.odds;
      line += `  Lines (${provider}): ${details || '—'}  |  Total: ${total != null ? total : '—'}\n`;
      if (homeMoneyline) {
        const homeML = (homeFavorite ? '' : '+') + homeMoneyline;
        const awayML = (!homeFavorite ? '' : '+') + awayMoneyline;
        line += `  Moneylines: ${g.homeTeam.name} ${homeML}  /  ${g.awayTeam.name} ${awayML}\n`;
      }
    } else {
      line += `  Lines: [not yet posted]\n`;
    }

    if (g.weather) line += `  Weather: ${g.weather.temperature}°F\n`;
    if (g.broadcasts && g.broadcasts.length) line += `  TV: ${g.broadcasts.join(', ')}\n`;

    return line;
  });

  return `CONFIRMED SLATE — ${games.length} GAME${games.length !== 1 ? 'S' : ''} (ESPN)\n\n` + lines.join('\n');
}

function formatMMASlateForContext(fights) {
  const cardName = fights[0] && fights[0].cardName ? fights[0].cardName : 'UFC Event';
  const venue    = fights[0] ? `${fights[0].venue.name}${fights[0].venue.city ? ', ' + fights[0].venue.city : ''}` : '';

  const lines = fights.map((f, i) => {
    const f1    = f.homeTeam;
    const f2    = f.awayTeam;
    const title = f.isTitleFight ? ' ★ TITLE FIGHT' : '';
    const wc    = f.weightClass   ? ` (${f.weightClass})` : '';

    let line = `Fight ${i + 1}${title}: ${f1.name} (${f1.record}) vs ${f2.name} (${f2.record})${wc}\n`;
    line += `  Time: ${f.gameTime}\n`;

    if (f.odds) {
      const f1ML = f.odds.homeFavorite ? f.odds.homeMoneyline : (f.odds.homeMoneyline > 0 ? '+' : '') + f.odds.homeMoneyline;
      const f2ML = (!f.odds.homeFavorite ? '' : '+') + f.odds.awayMoneyline;
      if (f.odds.homeMoneyline) line += `  Moneylines: ${f1.name} ${f1ML}  /  ${f2.name} ${f2ML}\n`;
      if (f.odds.total)         line += `  Total Rounds: ${f.odds.total}\n`;
    }

    return line;
  });

  return (
    `CONFIRMED FIGHT CARD — ${cardName} (ESPN)\n` +
    (venue ? `Venue: ${venue}\n` : '') +
    `${fights.length} fight${fights.length !== 1 ? 's' : ''} on card\n\n` +
    lines.join('\n')
  );
}
