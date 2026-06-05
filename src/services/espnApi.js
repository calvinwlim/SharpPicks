import { ESPN_SPORT_PATHS } from '../constants/index.js';
import { toEasternTime, toESPNDate } from '../utils/dateUtils.js';

const ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports';

/**
 * Fetches and parses the game slate for a given sport and date from ESPN's free public API.
 * No API key required.
 *
 * @param {string} sport  - One of: NBA, MLB, NFL, NHL, NCAAB
 * @param {string} date   - ISO date string "YYYY-MM-DD"
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

  const events = data.events ?? [];
  return events.map(parseESPNEvent).filter(Boolean);
}

/** Parses a single ESPN event into a normalized Game object */
function parseESPNEvent(event) {
  try {
    const comp = event.competitions?.[0];
    if (!comp) return null;

    const competitors = comp.competitors ?? [];
    const home = competitors.find((c) => c.homeAway === 'home');
    const away = competitors.find((c) => c.homeAway === 'away');

    // Handle sports where home/away isn't set (rare)
    const teamA = home ?? competitors[0];
    const teamB = away ?? competitors[1];

    const espnOdds = comp.odds?.[0] ?? null;

    return {
      id: event.id,
      name: event.name,
      shortName: event.shortName,
      date: event.date,
      gameTime: toEasternTime(event.date),
      status: event.status?.type?.description ?? 'Scheduled',

      homeTeam: parseTeam(teamA),
      awayTeam: parseTeam(teamB),

      venue: {
        name:   comp.venue?.fullName ?? '',
        city:   comp.venue?.city ?? '',
        state:  comp.venue?.state ?? '',
        indoor: comp.venue?.indoor !== false,
      },

      // ESPN provides single-book odds (ESPN Bet)
      odds: espnOdds
        ? {
            provider:        espnOdds.provider?.name ?? 'ESPN Bet',
            details:         espnOdds.details ?? '',          // e.g. "IND -3.5"
            spread:          espnOdds.spread ?? null,
            total:           espnOdds.overUnder ?? null,
            homeMoneyline:   espnOdds.homeTeamOdds?.moneyLine ?? null,
            awayMoneyline:   espnOdds.awayTeamOdds?.moneyLine ?? null,
            homeFavorite:    espnOdds.homeTeamOdds?.favorite ?? false,
          }
        : null,

      weather: comp.weather
        ? { temperature: comp.weather.temperature, conditionId: comp.weather.conditionId }
        : null,

      broadcasts: (comp.broadcasts ?? []).flatMap((b) => b.names ?? []),
    };
  } catch {
    return null;
  }
}

function parseTeam(competitor) {
  if (!competitor) return { id: null, name: 'TBD', abbreviation: 'TBD', record: '' };
  return {
    id:           competitor.team?.id ?? null,
    name:         competitor.team?.displayName ?? 'TBD',
    abbreviation: competitor.team?.abbreviation ?? '',
    color:        competitor.team?.color ?? '',
    record:       competitor.records?.[0]?.summary ?? '',
    score:        competitor.score ?? null,
  };
}

/**
 * Formats the ESPN game slate into a readable context block for Claude.
 * Includes matchup, time, venue, and ESPN odds where available.
 */
export function formatSlateForContext(games) {
  if (!games?.length) return 'No games found for this date.';

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
      line += `  Lines (${provider}): ${details || '—'}  |  Total: ${total ?? '—'}\n`;
      if (homeMoneyline) {
        const homeML = (homeFavorite ? '' : '+') + homeMoneyline;
        const awayML = (!homeFavorite ? '' : '+') + awayMoneyline;
        line += `  Moneylines: ${g.homeTeam.name} ${homeML}  /  ${g.awayTeam.name} ${awayML}\n`;
      }
    } else {
      line += `  Lines: [not yet posted]\n`;
    }

    if (g.weather) {
      line += `  Weather: ${g.weather.temperature}°F\n`;
    }

    if (g.broadcasts?.length) {
      line += `  TV: ${g.broadcasts.join(', ')}\n`;
    }

    return line;
  });

  return `CONFIRMED SLATE — ${games.length} GAME${games.length !== 1 ? 'S' : ''} (ESPN)\n\n` + lines.join('\n');
}
