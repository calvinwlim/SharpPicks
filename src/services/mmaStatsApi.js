/**
 * Fetches ESPN athlete profiles for every fighter on today's UFC card.
 *
 * DESIGN GOAL: Pre-structure everything so Groq spends its token budget on
 * reasoning, not data organization. We output "FIGHT ANALYSIS WORKSHEETS"
 * that frame each fight as a pre-labeled analysis problem.
 *
 * ESPN provides: height, weight, reach, age, nationality, stance, record.
 * Career performance stats (finish rates, TD%, strike rates) come from Groq's
 * training knowledge — but the worksheet format prompts it to recall them
 * in the right order and with the right context.
 */

const ESPN_MMA_BASE = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc';

// ─── Main export ──────────────────────────────────────────────────────────────

/**
 * @param {Array} fights - Parsed UFC fight objects (homeTeam/awayTeam are fighters)
 * @returns {Promise<string>} Pre-structured analysis worksheets for all fights
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
        fighters.push(ft.id);
      }
    });
  });

  if (!fighters.length) return buildWorksheets(fights, {});

  // Fetch all profiles in parallel — non-fatal per fighter
  const profiles = await Promise.all(fighters.map(fetchAthleteProfile));
  const profileMap = {};
  profiles.forEach((p) => { if (p) profileMap[p.id] = p; });

  return buildWorksheets(fights, profileMap);
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

  const heightIn = parseInt(athlete.height, 10) || 0;
  const reachIn  = parseFloat(athlete.reach)     || 0;
  const dob      = athlete.dateOfBirth || '';
  const age      = dob
    ? Math.floor((Date.now() - new Date(dob).getTime()) / (365.25 * 24 * 60 * 60 * 1000))
    : (parseInt(athlete.age, 10) || 0);

  return {
    id:         String(athlete.id || ''),
    name:       athlete.displayName || athlete.fullName || '',
    record:     athlete.displayRecord || athlete.record || '',
    heightIn,
    reachIn,
    weight:     parseInt(athlete.weight, 10) || 0,
    age,
    nationality:(athlete.birthPlace && athlete.birthPlace.country) || '',
    stance:     athlete.stance || '',
  };
}

// ─── Pre-structured worksheet builder ────────────────────────────────────────

/**
 * Outputs one "FIGHT ANALYSIS WORKSHEET" per fight.
 * Each worksheet pre-computes physical differentials and frames the fight
 * with labeled sections so Groq reasons rather than organizes.
 */
function buildWorksheets(fights, profileMap) {
  const cardName = fights[0] && fights[0].cardName ? fights[0].cardName : 'UFC Card';

  const sections = fights.map((fight, idx) => {
    const position    = getCardPosition(idx, fights.length);
    const f1          = fight.homeTeam;
    const f2          = fight.awayTeam;
    const p1          = profileMap[String(f1.id)] || null;
    const p2          = profileMap[String(f2.id)] || null;
    const rounds      = fight.isTitleFight ? 5 : 3;
    const titleLabel  = fight.isTitleFight ? ' ★ TITLE FIGHT' : '';
    const wc          = fight.weightClass  ? ` | ${fight.weightClass}` : '';

    // Pre-compute differentials
    const reachDiff = (p1 && p2 && p1.reachIn && p2.reachIn)
      ? (p1.reachIn - p2.reachIn).toFixed(1)
      : null;
    const ageDiff = (p1 && p2 && p1.age && p2.age)
      ? p1.age - p2.age
      : null;
    const heightDiff = (p1 && p2 && p1.heightIn && p2.heightIn)
      ? p1.heightIn - p2.heightIn
      : null;

    let out = `\n━━ FIGHT ${idx + 1}${titleLabel} — ${position} | ${rounds} Rounds${wc} ━━\n`;
    out += `${f1.name} vs ${f2.name}\n\n`;

    // Fighter A physical
    out += `${f1.name}:\n`;
    out += formatPhysical(f1.record, p1);

    out += `${f2.name}:\n`;
    out += formatPhysical(f2.record, p2);

    // Physical differentials (pre-computed so Groq doesn't have to subtract)
    if (reachDiff !== null || ageDiff !== null || heightDiff !== null) {
      out += 'Physical edge:\n';
      if (reachDiff !== null) {
        const reachEdge = reachDiff > 0 ? f1.name : reachDiff < 0 ? f2.name : 'Even';
        out += `  Reach: ${reachEdge} +${Math.abs(reachDiff)}" advantage\n`;
      }
      if (ageDiff !== null) {
        const ageEdge  = ageDiff > 0 ? f2.name : ageDiff < 0 ? f1.name : 'Even';
        const ageDelta = Math.abs(ageDiff);
        if (ageDelta >= 3) out += `  Age: ${ageEdge} younger by ${ageDelta} years\n`;
      }
      if (heightDiff !== null) {
        const htEdge = heightDiff > 0 ? f1.name : heightDiff < 0 ? f2.name : 'Even';
        if (Math.abs(heightDiff) >= 2) out += `  Height: ${htEdge} taller by ${Math.abs(heightDiff)}"\n`;
      }
    }

    // Odds if available
    if (fight.odds) {
      const { homeMoneyline, awayMoneyline, total, homeFavorite } = fight.odds;
      if (homeMoneyline) {
        const ml1 = mlString(homeMoneyline, homeFavorite);
        const ml2 = mlString(awayMoneyline, !homeFavorite);
        const ip1 = impliedProb(homeMoneyline).toFixed(1);
        const ip2 = impliedProb(awayMoneyline).toFixed(1);
        out += `Moneylines: ${f1.name} ${ml1} (${ip1}% implied) / ${f2.name} ${ml2} (${ip2}% implied)\n`;
      }
      if (total) out += `Total Rounds: O/U ${total}\n`;
    }

    // Analysis prompts (pre-framed questions Groq fills in its JSON output)
    out += '\nYour analysis tasks for this fight:\n';
    out += '  1. Classify each fighter style + tags + career arc + camp/team\n';
    out += '  2. Matchup vector: where does this fight go? Cite TD def %, shot accuracy\n';
    out += '  3. Historical pattern: each fighter\'s record vs opponent\'s style (name fights)\n';
    out += '  4. Stakes + motivation: who needs this win more?\n';
    out += '  5. Intangibles: run the checklist, flag any that apply\n';
    out += '  6. Probability: implied → your estimate → edge → bet recommendation\n';

    return out;
  });

  return (
    `FIGHT ANALYSIS WORKSHEETS — ${cardName}\n` +
    `${fights.length} fight${fights.length !== 1 ? 's' : ''} | ESPN confirmed\n` +
    'Physical stats are ground truth from ESPN. Career stats from your training knowledge — cite with confidence.\n' +
    sections.join('\n')
  );
}

function formatPhysical(record, profile) {
  let line = `  Record: ${record || '?'}`;
  if (profile) {
    if (profile.heightIn)   line += ` | Height: ${fmtHeight(profile.heightIn)}`;
    if (profile.reachIn)    line += ` | Reach: ${profile.reachIn}"`;
    if (profile.weight)     line += ` | Weight: ${profile.weight} lbs`;
    if (profile.age)        line += ` | Age: ${profile.age}`;
    if (profile.stance)     line += ` | Stance: ${profile.stance}`;
    if (profile.nationality)line += ` | ${profile.nationality}`;
  }
  return line + '\n';
}

function fmtHeight(inches) {
  const ft  = Math.floor(inches / 12);
  const ins = inches % 12;
  return `${ft}'${ins}"`;
}

function getCardPosition(idx, total) {
  if (idx === total - 1) return 'MAIN EVENT';
  if (idx === total - 2) return 'CO-MAIN';
  if (idx <= 2)          return 'PRELIM';
  return 'MAIN CARD';
}

// Moneyline string with + prefix for positives
function mlString(line, isFavorite) {
  if (!line) return '?';
  return line > 0 ? `+${line}` : String(line);
}

// Implied probability from American odds
function impliedProb(line) {
  if (!line) return 50;
  if (line < 0) return Math.abs(line) / (Math.abs(line) + 100) * 100;
  return 100 / (line + 100) * 100;
}
