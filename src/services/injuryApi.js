import { ESPN_SPORT_LEAGUES } from '../constants/index.js';

const ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports';

const INJURY_KEYWORDS = [
  'injured', 'injury', 'questionable', 'doubtful', 'out ', ' out,', 'day-to-day',
  'dtd', 'ir ', 'suspended', 'illness', 'soreness', 'sprain', 'strain', 'fracture',
  'concussion', 'knee', 'ankle', 'hamstring', 'shoulder', 'back', 'listed',
  'will not play', 'ruled out', 'scratched', 'starting pitcher',
];

/**
 * Fetches ESPN news for all teams in today's slate and extracts injury-relevant headlines.
 * Fully free — no API key required. Silently returns empty string on any error.
 *
 * @param {string} sport  - NBA, MLB, NFL, NHL, NCAAB
 * @param {Array}  games  - Parsed ESPN games (each with homeTeam.id / awayTeam.id)
 * @returns {Promise<string>}  Formatted injury context block, or '' if none found
 */
export async function fetchInjuryContext(sport, games) {
  const sl = ESPN_SPORT_LEAGUES[sport];
  if (!sl || !games.length) return '';

  // Collect unique team IDs from today's games
  const teamIds = [
    ...new Set(
      games.flatMap((g) => [g.homeTeam.id, g.awayTeam.id]).filter(Boolean)
    ),
  ];

  if (!teamIds.length) return '';

  // Fetch news for all teams in parallel (non-fatal per team)
  const results = await Promise.all(
    teamIds.map((id) => fetchTeamNews(sl.sport, sl.league, id))
  );

  // Build a map of teamId → headline bullets
  const teamMap = {};
  games.forEach((g) => {
    if (g.homeTeam.id) teamMap[g.homeTeam.id] = g.homeTeam.name;
    if (g.awayTeam.id) teamMap[g.awayTeam.id] = g.awayTeam.name;
  });

  const sections = [];
  teamIds.forEach((id, i) => {
    const articles = results[i];
    if (!articles.length) return;

    const teamName = teamMap[id] || `Team ${id}`;
    const bullets = articles.map((a) => `  • ${a}`);
    sections.push(`${teamName}:\n${bullets.join('\n')}`);
  });

  if (!sections.length) return '';

  return '\nINJURY / ROSTER NEWS (ESPN — live feed):\n' + sections.join('\n\n');
}

async function fetchTeamNews(sport, league, teamId) {
  try {
    const url = `${ESPN_BASE}/${sport}/${league}/teams/${teamId}/news`;
    const res = await fetch(url);
    if (!res.ok) return [];

    const data = await res.json();
    const articles = data.articles || [];

    return articles
      .slice(0, 8) // limit per team
      .filter((a) => {
        const text = ((a.headline || '') + ' ' + (a.description || '')).toLowerCase();
        return INJURY_KEYWORDS.some((kw) => text.includes(kw));
      })
      .map((a) => a.headline || '')
      .filter(Boolean)
      .slice(0, 4); // max 4 injury headlines per team
  } catch {
    return [];
  }
}
