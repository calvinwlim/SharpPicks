/**
 * Vercel Serverless Function — UFCStats.com proxy
 *
 * UFCStats is CORS-blocked for browser clients, so this thin proxy
 * fetches and parses the HTML server-side and returns structured JSON.
 *
 * Usage:  GET /api/ufcstats?name=Jon+Jones
 *
 * Response: { slpm, sapm, strAcc, strDef, tdAvg, tdAcc, tdDef, subAvg,
 *             winsKO, winsSub, winsDec, wins, losses,
 *             recentFights: [{result, opponent, method, round, date}] }
 */

const UA = 'Mozilla/5.0 (compatible; SharpPicks/1.0)';
const USTAT = 'http://www.ufcstats.com';

// ─── Entry point ──────────────────────────────────────────────────────────────

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate');

  const name = (req.query.name || '').trim();
  if (!name) return res.status(400).json({ error: 'name param required' });

  try {
    const result = await getFighterStats(name);
    if (!result) return res.status(404).json({ error: 'Fighter not found on UFCStats' });
    return res.json(result);
  } catch (err) {
    console.error('[ufcstats] error:', err.message);
    return res.status(500).json({ error: err.message });
  }
}

// ─── Main scraping logic ───────────────────────────────────────────────────────

async function getFighterStats(fullName) {
  const parts    = fullName.trim().split(/\s+/);
  const lastName = parts[parts.length - 1];
  const initial  = lastName[0].toLowerCase();

  // Step 1 — fetch fighter list for this initial letter
  const listUrl  = `${USTAT}/statistics/fighters?char=${initial}&page=all`;
  const listHtml = await fetchHtml(listUrl);
  if (!listHtml) return null;

  // Step 2 — find the detail page URL by fuzzy name match
  const detailUrl = findFighterUrl(listHtml, fullName);
  if (!detailUrl) return null;

  // Step 3 — fetch and parse the detail page
  const detailHtml = await fetchHtml(detailUrl);
  if (!detailHtml) return null;

  return parseDetailPage(detailHtml, fullName);
}

async function fetchHtml(url) {
  try {
    const res = await fetch(url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(6000) });
    if (!res.ok) return null;
    return res.text();
  } catch { return null; }
}

// ─── Fighter URL lookup ───────────────────────────────────────────────────────

function findFighterUrl(html, fullName) {
  const parts     = fullName.toLowerCase().trim().split(/\s+/);
  const firstName = parts[0];
  const lastName  = parts[parts.length - 1];

  // Collect all fighter-details href + link text pairs in document order
  const linkRe = /href="(https?:\/\/www\.ufcstats\.com\/fighter-details\/[a-f0-9]+)"[^>]*>\s*([^<\n]+)\s*<\/a>/gi;
  const links  = [];
  let m;
  while ((m = linkRe.exec(html)) !== null) {
    links.push({ url: m[1], text: m[2].trim().toLowerCase() });
  }

  // On the list page each fighter appears as two consecutive links
  // (first name then last name) pointing to the same URL.
  for (let i = 0; i < links.length - 1; i++) {
    const a = links[i];
    const b = links[i + 1];
    if (a.url !== b.url) continue;

    const combined = `${a.text} ${b.text}`;
    if (combined.includes(firstName) && combined.includes(lastName)) {
      return a.url;
    }
    // Also accept reverse order (some pages vary)
    const reversed = `${b.text} ${a.text}`;
    if (reversed.includes(firstName) && reversed.includes(lastName)) {
      return a.url;
    }
  }

  return null;
}

// ─── Detail page parser ───────────────────────────────────────────────────────

function parseDetailPage(html, fighterName) {
  // Extract a stat by its label text from the career stats boxes
  const getStat = (label) => {
    const esc = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const m   = html.match(new RegExp(`>${esc}</i>\\s*([\\d.%]+)`));
    return m ? m[1].trim() : null;
  };

  const pct = (s) => {
    if (!s) return 0;
    const v = parseFloat(s.replace('%', ''));
    return isNaN(v) ? 0 : v / 100;
  };
  const num = (s) => parseFloat(s || 0) || 0;

  // Career averages
  const slpm   = num(getStat('SLpM:'));
  const sapm   = num(getStat('SApM:'));
  const strAcc = pct(getStat('Str. Acc.:'));
  const strDef = pct(getStat('Str. Def.:') || getStat('Str. Def:'));
  const tdAvg  = num(getStat('TD Avg.:'));
  const tdAcc  = pct(getStat('TD Acc.:'));
  const tdDef  = pct(getStat('TD Def.:'));
  const subAvg = num(getStat('Sub. Avg.:'));

  // Win/loss record from bio section
  const recMatch = html.match(/>\s*(\d+)-(\d+)-(\d+)\s*</);
  const wins     = recMatch ? parseInt(recMatch[1], 10) : 0;
  const losses   = recMatch ? parseInt(recMatch[2], 10) : 0;

  // Win breakdown from record table (W-L-NC by method)
  const winsKO  = countWinsByMethod(html, fighterName, ['KO', 'TKO']);
  const winsSub = countWinsByMethod(html, fighterName, ['Submission', 'Sub']);
  const winsDec = countWinsByMethod(html, fighterName, ['Decision', 'DEC']);

  // Recent fights
  const recentFights = parseFightHistory(html, fighterName);

  return { slpm, sapm, strAcc, strDef, tdAvg, tdAcc, tdDef, subAvg, wins, losses, winsKO, winsSub, winsDec, recentFights };
}

// ─── Win method counter ───────────────────────────────────────────────────────

function countWinsByMethod(html, fighterName, methodKeywords) {
  const lastNameLc = fighterName.split(' ').pop().toLowerCase();
  let count = 0;

  // Fight history rows: each has a result (win/loss) and a method
  const rowRe  = /b-fight-details__table-row__hover[\s\S]*?<\/tr>/gi;
  let rowMatch;
  while ((rowMatch = rowRe.exec(html)) !== null) {
    const rowHtml = rowMatch[0];
    // Check it's a WIN for this fighter
    if (!rowHtml.includes('alt="win"') && !rowHtml.includes('alt="Win"')) continue;
    // Verify this fighter appears in the row
    if (!rowHtml.toLowerCase().includes(lastNameLc)) continue;
    // Check method
    const methodRe = /<p[^>]*>\s*([^<\n]+)\s*<\/p>/gi;
    let mMatch;
    while ((mMatch = methodRe.exec(rowHtml)) !== null) {
      const text = mMatch[1].trim();
      if (methodKeywords.some((kw) => text.toUpperCase().includes(kw.toUpperCase()))) {
        count++;
        break;
      }
    }
  }
  return count;
}

// ─── Fight history parser ─────────────────────────────────────────────────────

function parseFightHistory(html, fighterName) {
  const fights      = [];
  const selfLastLc  = fighterName.split(' ').pop().toLowerCase();

  // Iterate over all expandable fight rows
  const rowRe = /b-fight-details__table-row__hover([\s\S]*?)<\/tr>/gi;
  let rowMatch;

  while ((rowMatch = rowRe.exec(html)) !== null && fights.length < 5) {
    const row = rowMatch[1];

    // Result: look for img alt="win" / "loss" / "no contest"
    const imgAlt  = (row.match(/alt="([^"]+)"/i) || [])[1] || '';
    const result  = imgAlt.toLowerCase().startsWith('win') ? 'W'
                  : imgAlt.toLowerCase().startsWith('loss') ? 'L' : 'NC';

    // Fighters in the row — pick the one that isn't our fighter
    const nameMatches = [...row.matchAll(/<a[^>]+href[^>]+class="b-link[^"]*"[^>]*>\s*([A-Z][^<]+?)\s*<\/a>/gi)];
    const opponent = nameMatches
      .map((m) => m[1].trim())
      .find((n) => !n.toLowerCase().includes(selfLastLc)) || '';

    if (!opponent) continue;

    // Method: first text in the method cell (column index 6 approximately)
    const cellTexts = [...row.matchAll(/<p[^>]*class="b-fight-details__table-text"[^>]*>\s*([^<\n]{2,}?)\s*<\/p>/gi)].map((m) => m[1].trim());

    // Cells appear in order; method is roughly 5th–7th non-empty cell
    const method = cellTexts.find((t) => /KO|TKO|Sub|Decision|DEC|Draw/i.test(t)) || '?';

    // Round (1-digit number among the last few cells)
    const roundMatch = row.match(/<p[^>]*>\s*([1-5])\s*<\/p>/g);
    const round = roundMatch ? roundMatch[roundMatch.length - 1].replace(/<[^>]+>/g, '').trim() : '';

    // Date (Month. DD, YYYY)
    const dateMatch = row.match(/([A-Z][a-z]+\.\s+\d+,\s+\d{4})/);
    const date = dateMatch ? dateMatch[1] : '';

    fights.push({ result, opponent, method, round, date });
  }

  return fights;
}
