/**
 * Fetches ESPN athlete profiles for every fighter on today's UFC card.
 * Provides height, weight, reach, record, nationality, weight class —
 * physical ground-truth that the LLM uses alongside its training knowledge
 * of career stats, fighting styles, and historical H2H patterns.
 */

const ESPN_MMA_BASE = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc';

// ─── Main export ──────────────────────────────────────────────────────────────

/**
 * Fetches profiles for all fighters on the card and returns a formatted
 * context block for the LLM.
 *
 * @param {Array} fights - Parsed UFC fight objects (homeTeam/awayTeam are fighters)
 * @returns {Promise<string>}
 */
export async function fetchFighterContext(fights) {
  if (!fights || !fights.length) return '';

  // Collect unique fighter IDs
  const fighters = [];
  const seen     = new Set();
  fights.forEach((f) => {
    [f.homeTeam, f.awayTeam].forEach((ft) => {
      if (ft && ft.id && !seen.has(ft.id)) {
        seen.add(ft.id);
        fighters.push({ id: ft.id, name: ft.name });
      }
    });
  });

  if (!fighters.length) return '';

  // Fetch all profiles in parallel, non-fatal per fighter
  const profileResults = await Promise.all(
    fighters.map(({ id }) => fetchAthleteProfile(id))
  );

  // Map id → profile
  const profileMap = {};
  profileResults.forEach((p) => { if (p) profileMap[p.id] = p; });

  return buildFighterContext(fights, profileMap);
}

// ─── ESPN athlete fetch ───────────────────────────────────────────────────────

async function fetchAthleteProfile(athleteId) {
  try {
    const res = await fetch(`${ESPN_MMA_BASE}/athletes/${athleteId}`);
    if (!res.ok) return null;
    const data = await res.json();
    return parseAthleteProfile(data.athlete || data);
  } catch {
    return null;
  }
}

function parseAthleteProfile(athlete) {
  if (!athlete) return null;

  const heightIn = athlete.height;
  let heightStr  = '';
  if (heightIn) {
    const ft  = Math.floor(heightIn / 12);
    const ins = heightIn % 12;
    heightStr = `${ft}'${ins}"`;
  }

  return {
    id:         String(athlete.id || ''),
    name:       athlete.displayName || athlete.fullName || '',
    record:     athlete.displayRecord || athlete.record || '',
    height:     heightStr,
    weight:     athlete.weight     ? `${athlete.weight} lbs`  : '',
    reach:      athlete.reach      ? `${athlete.reach}"`      : '',
    weightClass:(athlete.position && athlete.position.name) || '',
    age:        athlete.age        ? `${athlete.age}`          : '',
    nationality:(athlete.birthPlace && athlete.birthPlace.country) || '',
    stance:     athlete.stance     || '',
    debut:      athlete.debutDate  || '',
  };
}

// ─── Context builder ──────────────────────────────────────────────────────────

function buildFighterContext(fights, profileMap) {
  const sections = [];

  fights.forEach((fight, i) => {
    const f1Profile = profileMap[String(fight.homeTeam.id)] || null;
    const f2Profile = profileMap[String(fight.awayTeam.id)] || null;

    const f1Name = fight.homeTeam.name;
    const f2Name = fight.awayTeam.name;
    const wc     = fight.weightClass ? ` — ${fight.weightClass}` : '';
    const title  = fight.isTitleFight ? ' ★ TITLE FIGHT' : '';
    const rounds = fight.isTitleFight ? '5 rounds' : '3 rounds';

    let section = `Fight ${i + 1}${title}: ${f1Name} vs ${f2Name}${wc} (${rounds})\n`;

    section += formatFighterLine(f1Name, fight.homeTeam.record, f1Profile);
    section += formatFighterLine(f2Name, fight.awayTeam.record, f2Profile);

    sections.push(section);
  });

  return (
    '\nFIGHTER PROFILES (ESPN — confirmed):\n' +
    'Use these physical stats alongside your knowledge of each fighter\'s career stats, style, and tendencies.\n\n' +
    sections.join('\n')
  );
}

function formatFighterLine(name, record, profile) {
  const parts = [`Record: ${record || '?'}`];
  if (profile) {
    if (profile.height)      parts.push(`Height: ${profile.height}`);
    if (profile.weight)      parts.push(`Weight: ${profile.weight}`);
    if (profile.reach)       parts.push(`Reach: ${profile.reach}`);
    if (profile.age)         parts.push(`Age: ${profile.age}`);
    if (profile.nationality) parts.push(`From: ${profile.nationality}`);
    if (profile.stance)      parts.push(`Stance: ${profile.stance}`);
  }
  return `  ${name}: ${parts.join(' | ')}\n`;
}
