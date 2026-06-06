import { ESPN_SPORT_LEAGUES } from '../constants/index.js';

const ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports';

/**
 * Fetches current ESPN rosters for every team in today's slate.
 * Returns a formatted context block that grounds the LLM to real, current players.
 * Fully free — no API key required.
 *
 * This is the primary guard against hallucinated picks (e.g. suggesting a player
 * who was traded away). The system prompt instructs the model to ONLY suggest
 * props for players explicitly listed here.
 *
 * @param {string} sport  - NBA, MLB, NFL, NHL, NCAAB
 * @param {Array}  games  - Parsed ESPN games (each with homeTeam.id / awayTeam.id)
 * @returns {Promise<string>}  Formatted roster block, or '' on failure
 */
export async function fetchRosterContext(sport, games) {
  // UFC fighters are already listed in the game slate — no team roster needed
  if (sport === 'UFC') return buildUFCFighterContext(games);

  const sl = ESPN_SPORT_LEAGUES[sport];
  if (!sl || !games.length) return '';

  // Unique teams from today's slate
  const teams = [];
  const seen  = new Set();
  games.forEach((g) => {
    [g.homeTeam, g.awayTeam].forEach((t) => {
      if (t.id && !seen.has(t.id)) {
        seen.add(t.id);
        teams.push(t);
      }
    });
  });

  if (!teams.length) return '';

  // Fetch all rosters in parallel
  const results = await Promise.all(
    teams.map((t) => fetchTeamRoster(sl.sport, sl.league, t.id, t.name))
  );

  const sections = results.filter(Boolean);
  if (!sections.length) return '';

  return (
    '\nCONFIRMED ROSTERS (ESPN — current season):\n' +
    'IMPORTANT: Only suggest player props for athletes listed below. ' +
    'Do not suggest picks for players not on these rosters — rosters change via trades and injuries.\n\n' +
    sections.join('\n\n')
  );
}

async function fetchTeamRoster(sport, league, teamId, teamName) {
  try {
    const url  = `${ESPN_BASE}/${sport}/${league}/teams/${teamId}/roster`;
    const res  = await fetch(url);
    if (!res.ok) return null;

    const data     = await res.json();
    const athletes = data.athletes || [];

    // ESPN returns athletes grouped by position group for some sports
    // Flatten if needed (NBA returns flat array, MLB returns position groups)
    const flat = athletes.flatMap((entry) =>
      Array.isArray(entry.items) ? entry.items : [entry]
    );

    if (!flat.length) return null;

    // Format each player as "Name (POS)" — keep it tight for context length
    const players = flat
      .filter((a) => a.fullName || a.displayName)
      .map((a) => {
        const name = a.fullName || a.displayName;
        const pos  = a.position ? a.position.abbreviation || a.position.name : '';
        return pos ? `${name} (${pos})` : name;
      });

    if (!players.length) return null;

    return `${teamName}:\n  ${players.join(', ')}`;
  } catch {
    return null;
  }
}

/**
 * For UFC, fighter info is already in the game slate.
 * Build a compact confirmation block so the LLM knows exactly who is fighting.
 */
function buildUFCFighterContext(fights) {
  if (!fights || !fights.length) return '';
  const lines = fights.map((f) => {
    const f1 = f.homeTeam;
    const f2 = f.awayTeam;
    const wc = f.weightClass ? ` — ${f.weightClass}` : '';
    return `  ${f1.name} (${f1.record}) vs ${f2.name} (${f2.record})${wc}`;
  });
  return (
    '\nCONFIRMED FIGHTERS (ESPN):\n' +
    'Only suggest picks involving the fighters listed below.\n\n' +
    lines.join('\n')
  );
}
