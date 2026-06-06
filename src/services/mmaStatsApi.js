/**
 * MMA data aggregator — merges three free sources before the AI sees anything:
 *
 *   1. ESPN MMA API     — physical profile, rankings, nickname (no key)
 *   2. TheSportsDB      — nationality, bio text (no key, key="3")
 *   3. UFCStats proxy   — career striking/grappling stats, win methods,
 *                         recent fight history (Vercel /api/ufcstats)
 *
 * The AI context block is built from the merged profile so the model
 * only needs to reason — never search.
 */

import { fetchSportsDBPlayer } from './theSportsDBApi.js';
import { fetchUFCStats }        from './ufcStatsApi.js';

const ESPN_MMA_BASE = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc';

// ─── Main exports ─────────────────────────────────────────────────────────────

export async function fetchFighterData(fights, rapidApiKey = '') {
  if (!fights || !fights.length) return { context: '', profiles: {} };

  const seenIds = new Set();
  const fighters = [];
  fights.forEach((f) => {
    [f.homeTeam, f.awayTeam].forEach((ft) => {
      if (ft && ft.id && !seenIds.has(ft.id)) {
        seenIds.add(ft.id);
        fighters.push({ id: ft.id, name: ft.name });
      }
    });
  });

  const profileList = await Promise.all(fighters.map((f) => fetchFullProfile(f.id, f.name)));
  const profiles    = {};
  profileList.forEach((p) => { if (p) profiles[p.id] = p; });

  const context = buildWorksheets(fights, profiles);
  return { context, profiles };
}

export async function fetchFighterContext(fights) {
  const { context } = await fetchFighterData(fights);
  return context;
}

// ─── Per-fighter aggregation ──────────────────────────────────────────────────

async function fetchFullProfile(athleteId, fighterName) {
  // All three sources fire in parallel per fighter
  const [espnProfile, sportsDB, ufcStats] = await Promise.all([
    fetchAthleteProfile(athleteId),
    fetchSportsDBPlayer(fighterName),
    fetchUFCStats(fighterName),
  ]);

  if (!espnProfile) return null;

  return mergeProfile(espnProfile, sportsDB, ufcStats);
}

function mergeProfile(espn, tsdb, ufc) {
  // UFCStats is authoritative for career stats; ESPN is authoritative for physical/bio
  return {
    ...espn,

    // Bio supplements — TheSportsDB fills gaps ESPN leaves blank
    nationality:   espn.nationality   || (tsdb && tsdb.nationality)   || '',
    birthLocation: espn.birthLocation || (tsdb && tsdb.birthLocation) || '',
    description:   espn.bio           || (tsdb && tsdb.description)   || '',

    // Career stats — UFCStats wins if present, else keep ESPN values
    slpm:   (ufc && ufc.slpm   > 0) ? ufc.slpm   : espn.slpm,
    sapm:   (ufc && ufc.sapm   > 0) ? ufc.sapm   : espn.sapm,
    strAcc: (ufc && ufc.strAcc > 0) ? ufc.strAcc : espn.strAcc,
    strDef: (ufc && ufc.strDef > 0) ? ufc.strDef : espn.strDef,
    tdAvg:  (ufc && ufc.tdAvg  > 0) ? ufc.tdAvg  : espn.tdAvg,
    tdAcc:  (ufc && ufc.tdAcc  > 0) ? ufc.tdAcc  : espn.tdAcc,
    tdDef:  (ufc && ufc.tdDef  > 0) ? ufc.tdDef  : espn.tdDef,
    subAvg: (ufc && ufc.subAvg > 0) ? ufc.subAvg : espn.subAvg,

    // Win breakdown — prefer UFCStats method-level counts
    wins:   (ufc && ufc.wins   > 0) ? ufc.wins   : espn.wins,
    losses: (ufc && ufc.losses > 0) ? ufc.losses : espn.losses,
    winsKO:  (ufc && ufc.winsKO  > 0) ? ufc.winsKO  : espn.winsKO,
    winsSub: (ufc && ufc.winsSub > 0) ? ufc.winsSub : espn.winsSub,
    winsDec: (ufc && ufc.winsDec > 0) ? ufc.winsDec : espn.winsDec,

    // Recent fights — only from UFCStats
    recentFights: (ufc && ufc.recentFights) || [],
  };
}

// ─── ESPN fetch ───────────────────────────────────────────────────────────────

async function fetchAthleteProfile(athleteId) {
  const candidates = [
    `${ESPN_MMA_BASE}/athletes/${athleteId}`,
    `https://site.api.espn.com/apis/site/v2/sports/mma/athletes/${athleteId}`,
    `https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/${athleteId}`,
  ];

  for (const url of candidates) {
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const data    = await res.json();
      const profile = parseAthleteProfile(data.athlete || data);
      if (profile && profile.name && profile.name !== 'TBD') return profile;
    } catch { /* try next */ }
  }
  return null;
}

// ─── ESPN profile parser ──────────────────────────────────────────────────────

/** ESPN sometimes returns objects {id, name} instead of plain strings */
const str = (v) => {
  if (!v) return '';
  if (typeof v === 'string') return v;
  return v.description || v.name || v.text || v.displayName || '';
};

/** Normalize a value ESPN might store as 0-1 or 0-100 */
const normPct = (v) => { const n = parseFloat(v || 0); return n > 1 ? n / 100 : n; };

/** Build a lookup helper that checks the stats object then displayStats map */
function makeStatHelper(s, ds) {
  return (...keys) => {
    for (const k of keys) {
      const fromS  = parseFloat(s[k] ?? 0);
      if (fromS > 0) return fromS;
      const dsKey  = k.toLowerCase().replace(/[^a-z]/g, '');
      const fromDs = parseFloat(ds[dsKey] ?? 0);
      if (fromDs > 0) return fromDs;
    }
    return 0;
  };
}

function parseDisplayStats(arr) {
  if (!Array.isArray(arr)) return {};
  const map = {};
  arr.forEach((s) => {
    const key = (s.name || s.label || '').toLowerCase().replace(/[^a-z]/g, '');
    const val = parseFloat(s.value ?? s.displayValue ?? s.stat ?? 0);
    if (key && !Number.isNaN(val)) map[key] = val;
  });
  return map;
}

function parseRanking(a) {
  // ESPN ranking might be in: a.rankings[], a.rank, a.college (weird ESPN quirk)
  if (Array.isArray(a.rankings)) {
    // Look for a ranking that mentions the weight class
    const r = a.rankings.find(
      (x) => x.displayValue && /\d/.test(x.displayValue)
    );
    if (r) return r.displayValue; // e.g. "#5 Featherweight"
  }
  if (a.rank) return `#${a.rank}`;
  return '';
}

function parseAthleteProfile(a) {
  if (!a) return null;

  const heightIn = parseInt(a.height, 10) || 0;
  const reachIn  = parseFloat(a.reach) || parseFloat(a.armLength) || 0;

  const dob = a.dateOfBirth || '';
  const age  = dob
    ? Math.floor((Date.now() - new Date(dob).getTime()) / (365.25 * 24 * 60 * 60 * 1000))
    : (parseInt(a.age, 10) || 0);

  const record =
    a.displayRecord || a.record ||
    (a.records && a.records[0] && a.records[0].summary) || '';

  const s  = a.statistics || a.stats || {};
  const ds = parseDisplayStats(a.displayStats);
  const tryF = makeStatHelper(s, ds);
  const tryI = (...keys) => {
    for (const k of keys) {
      const v = parseInt(a[k] || s[k] || ds[k.toLowerCase().replace(/[^a-z]/g, '')] || 0, 10);
      if (v > 0) return v;
    }
    return 0;
  };

  // Win breakdown — fall back to parsing record string
  let wins   = tryI('wins');
  let losses = tryI('losses');
  let draws  = tryI('draws');
  if (!wins && record) {
    const m = record.match(/^(\d+)-(\d+)(?:-(\d+))?/);
    if (m) { wins = parseInt(m[1], 10) || 0; losses = parseInt(m[2], 10) || 0; draws = parseInt(m[3], 10) || 0; }
  }

  return {
    id:           String(a.id || ''),
    name:         a.displayName || a.fullName || '',
    record,
    heightIn,
    reachIn,
    legReachIn:   parseFloat(a.legLength || a.leg || 0) || 0,
    weight:       parseInt(a.weight, 10) || 0,
    age,
    nationality:  str(a.birthPlace && a.birthPlace.country) || str(a.citizenship),
    birthLocation:'',
    stance:       str(a.stance) || str(a.preferredHand),
    nickname:     str(a.nickname) || str(a.shortName) || '',
    ranking:      parseRanking(a),
    bio:          str(a.description) || str(a.bio) || '',

    // Striking (ESPN rarely provides these; UFCStats proxy fills them in)
    slpm:   tryF('significantStrikesLandedPerMinute', 'slpm'),
    sapm:   tryF('significantStrikesAbsorbedPerMinute', 'sapm'),
    strAcc: normPct(tryF('significantStrikingAccuracy', 'strAcc')),
    strDef: normPct(tryF('significantStrikeDefense', 'strDef')),

    // Grappling
    tdAvg:  tryF('takedownAverage', 'takedownAveragePerFifteenMinutes', 'tdAvg'),
    tdAcc:  normPct(tryF('takedownAccuracy', 'tdAcc')),
    tdDef:  normPct(tryF('takedownDefense', 'tdDef')),
    subAvg: tryF('submissionAverage', 'submissionAveragePerFifteenMinutes', 'subAvg'),

    wins, losses, draws,
    winsKO:  tryI('winsKO', 'winsKo', 'koWins'),
    winsSub: tryI('winsSubmission', 'winsSub', 'submissionWins'),
    winsDec: tryI('winsDecision', 'winsDec', 'decisionWins'),

    recentFights: [],
  };
}

// ─── AI worksheet builder ─────────────────────────────────────────────────────

function buildWorksheets(fights, profiles) {
  const cardName = (fights[0] && fights[0].cardName) || 'UFC Card';

  const sections = fights.map((fight, idx) => {
    const pos    = getCardPos(idx, fights.length);
    const f1     = fight.homeTeam;
    const f2     = fight.awayTeam;
    const p1     = profiles[String(f1.id)] || null;
    const p2     = profiles[String(f2.id)] || null;
    const rounds = fight.isTitleFight ? 5 : 3;
    const title  = fight.isTitleFight ? ' ★ TITLE' : '';
    const wc     = fight.weightClass  ? ` | ${fight.weightClass}` : '';
    const n1     = p1 ? p1.name.split(' ').pop() : f1.name.split(' ').pop();
    const n2     = p2 ? p2.name.split(' ').pop() : f2.name.split(' ').pop();

    let out = `\n━━ FIGHT ${idx + 1}${title} — ${pos} | ${rounds}R${wc} ━━\n`;
    out += `${f1.name} vs ${f2.name}\n`;
    out += physLine(f1.name, f1.record, p1);
    out += physLine(f2.name, f2.record, p2);

    // Physical differentials
    if (p1 && p2) {
      const rd = p1.reachIn && p2.reachIn ? p1.reachIn - p2.reachIn : null;
      const ad = p1.age && p2.age ? p1.age - p2.age : null;
      if (rd !== null) out += `Reach edge: ${rd > 0 ? n1 : rd < 0 ? n2 : 'Even'} +${Math.abs(rd)}"\n`;
      if (ad !== null && Math.abs(ad) >= 3) out += `Age: ${ad > 0 ? n2 : n1} younger by ${Math.abs(ad)} years\n`;
    }

    // Career stats block (compact — saves tokens)
    const hasSt = (p1 && (p1.slpm > 0 || p1.strAcc > 0)) || (p2 && (p2.slpm > 0 || p2.strAcc > 0));
    if (hasSt) {
      const f = (p, k, pct) => !p || !p[k] ? '?' : pct ? `${Math.round(p[k]*100)}%` : p[k].toFixed(2);
      out += `Striking [SLpM/Str%/StrDef/SApM]: ${n1} ${f(p1,'slpm')}/${f(p1,'strAcc',1)}/${f(p1,'strDef',1)}/${f(p1,'sapm')} | ${n2} ${f(p2,'slpm')}/${f(p2,'strAcc',1)}/${f(p2,'strDef',1)}/${f(p2,'sapm')}\n`;
    }

    const hasGr = (p1 && (p1.tdAvg > 0 || p1.tdAcc > 0)) || (p2 && (p2.tdAvg > 0 || p2.tdAcc > 0));
    if (hasGr) {
      const f = (p, k, pct) => !p || !p[k] ? '?' : pct ? `${Math.round(p[k]*100)}%` : p[k].toFixed(2);
      out += `Grappling [TD/15/TD%/TDDef/Sub]: ${n1} ${f(p1,'tdAvg')}/${f(p1,'tdAcc',1)}/${f(p1,'tdDef',1)}/${f(p1,'subAvg')} | ${n2} ${f(p2,'tdAvg')}/${f(p2,'tdAcc',1)}/${f(p2,'tdDef',1)}/${f(p2,'subAvg')}\n`;
    }

    if ((p1 && p1.wins > 0) || (p2 && p2.wins > 0)) {
      const fmtFin = (p) => (!p || !p.wins) ? '?/?'
        : `${Math.round((p.winsKO/p.wins)*100)}%KO/${Math.round((p.winsSub/p.wins)*100)}%Sub`;
      out += `Finish rates: ${n1} ${fmtFin(p1)} | ${n2} ${fmtFin(p2)}\n`;
    }

    // Recent fights — last 5 in compact format
    if (p1 && p1.recentFights && p1.recentFights.length) {
      out += `${n1} last ${p1.recentFights.length}: ${p1.recentFights.map(fmtFight).join(' · ')}\n`;
    }
    if (p2 && p2.recentFights && p2.recentFights.length) {
      out += `${n2} last ${p2.recentFights.length}: ${p2.recentFights.map(fmtFight).join(' · ')}\n`;
    }

    // Odds
    if (fight.odds && fight.odds.homeMoneyline) {
      const i1 = ip(fight.odds.homeMoneyline).toFixed(1);
      const i2 = ip(fight.odds.awayMoneyline).toFixed(1);
      out += `Odds: ${f1.name} ${mlStr(fight.odds.homeMoneyline)} (${i1}% implied) / ${f2.name} ${mlStr(fight.odds.awayMoneyline)} (${i2}% implied)\n`;
    }
    if (fight.odds && fight.odds.total) out += `Rounds O/U: ${fight.odds.total}\n`;

    out += `Tasks: style+arc+camp | matchup vector | historical pattern | stakes | intangibles | prob calc\n`;
    return out;
  });

  return (
    `FIGHT WORKSHEETS — ${cardName} (${fights.length} fights)\n` +
    `Physical stats = ESPN. Career stats = UFCStats/ESPN (flag approx if sourced from training knowledge).\n` +
    sections.join('\n')
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function physLine(name, record, p) {
  let s = `  ${name}: ${record || '?'}`;
  if (p) {
    if (p.ranking)    s += ` | ${p.ranking}`;
    if (p.nickname)   s += ` "${p.nickname}"`;
    if (p.heightIn)   s += ` | ${fmtH(p.heightIn)}`;
    if (p.reachIn)    s += ` | reach ${p.reachIn}"`;
    if (p.weight)     s += ` | ${p.weight}lbs`;
    if (p.age)        s += ` | age ${p.age}`;
    if (p.stance)     s += ` | ${p.stance}`;
    if (p.nationality)s += ` | ${p.nationality}`;
  }
  return s + '\n';
}

function fmtFight(f) {
  const method = f.method === 'Decision' || f.method?.startsWith('DEC') ? 'Dec'
               : f.method?.includes('TKO') ? 'TKO'
               : f.method?.includes('KO')  ? 'KO'
               : f.method?.includes('Sub') ? 'Sub'
               : f.method || '?';
  return `${f.result}(${method}${f.round ? ',R'+f.round : ''})`;
}

function fmtH(ins)          { return `${Math.floor(ins/12)}'${ins%12}"`; }
function getCardPos(i, tot) { return i===tot-1?'MAIN EVENT':i===tot-2?'CO-MAIN':i>=tot-5?'MAIN CARD':'PRELIM'; }
function mlStr(l)            { return l==null?'?':l>0?`+${l}`:String(l); }
function ip(l)               { if(!l)return 50; return l<0?Math.abs(l)/(Math.abs(l)+100)*100:100/(l+100)*100; }
