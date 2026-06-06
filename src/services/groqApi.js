import { SYSTEM_PROMPT }     from '../prompts/systemPrompt.js';
import { MMA_SYSTEM_PROMPT } from '../prompts/mmaPrompt.js';
import { extractAndRepairJSON } from '../utils/jsonUtils.js';
import { formatSlateForContext } from './espnApi.js';
import { formatOddsForContext }  from './oddsApi.js';
import { fmtDate } from '../utils/dateUtils.js';

const GROQ_API   = 'https://api.groq.com/openai/v1/chat/completions';
const GROQ_MODEL = 'llama-3.3-70b-versatile';

/**
 * Sends the confirmed slate + all enrichment data to Groq (free tier) for analysis.
 * Routes to the MMA-specific prompt and validation when sport === 'UFC'.
 */
export async function analyzeSlate({
  sport, date, games, odds,
  rosterContext, injuryContext, propsContext,
  fighterContext,   // UFC only — ESPN fighter profiles
  notes, apiKey,
}) {
  if (!apiKey || !apiKey.trim()) {
    throw new Error('Groq API key is required. Get a free key at console.groq.com, then add it in Settings.');
  }

  const isMMA      = sport === 'UFC';
  const systemPmt  = isMMA ? MMA_SYSTEM_PROMPT : SYSTEM_PROMPT;
  const userMsg    = isMMA
    ? buildMMAMessage({ sport, date, games, odds, fighterContext, injuryContext, notes })
    : buildUserMessage({ sport, date, games, odds, rosterContext, injuryContext, propsContext, notes });

  let res;
  try {
    res = await fetch(GROQ_API, {
      method: 'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${apiKey.trim()}`,
      },
      body: JSON.stringify({
        model:       GROQ_MODEL,
        max_tokens:  4096,
        temperature: 0.2,   // lower temp = more factual / less hallucination
        messages: [
          { role: 'system', content: systemPmt },
          { role: 'user',   content: userMsg   },
        ],
      }),
    });
  } catch (err) {
    throw new Error(`Network error reaching Groq API: ${err.message}`);
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    const msg = errData.error ? errData.error.message : `API error ${res.status}`;
    if (res.status === 401) throw new Error('Invalid Groq API key. Check your key in Settings.');
    if (res.status === 429) throw new Error('Groq rate limit hit. Wait a moment and try again (free tier: 30 req/min).');
    throw new Error(msg);
  }

  const data = await res.json();
  const raw  = data.choices && data.choices[0] && data.choices[0].message
    ? data.choices[0].message.content
    : null;

  if (!raw) throw new Error('No analysis returned from Groq. Please try again.');

  let parsed;
  try {
    parsed = extractAndRepairJSON(raw);
  } catch (err) {
    throw new Error(`Could not parse Groq response: ${err.message}`);
  }

  if (isMMA) {
    // Validate MMA structure
    if (!parsed.fights || !parsed.fights.length) {
      throw new Error('No fight analysis returned. The UFC card may not be scheduled yet for this date.');
    }
    // Normalize fight IDs
    parsed.fights = parsed.fights.map((f, i) => ({
      ...f,
      id: String(f.id != null ? f.id : i + 1),
    }));
    return parsed;
  }

  // Team sports validation
  if (!parsed.picks || !parsed.picks.length) {
    throw new Error('No picks found for this slate. The sport may be out of season or no games were scheduled.');
  }
  parsed.picks    = parsed.picks.map((p, i) => ({ ...p, id: String(p.id != null ? p.id : i + 1) }));
  parsed.best_bet = String(parsed.best_bet != null ? parsed.best_bet : '1');
  return parsed;
}

// ─── MMA message builder ──────────────────────────────────────────────────────

function buildMMAMessage({ sport, date, games, odds, fighterContext, injuryContext, notes }) {
  const parts = [];

  parts.push(`Analyze the UFC fight card for ${fmtDate(date)} (${date}).`);
  parts.push('');
  parts.push(formatSlateForContext(games));

  if (odds) {
    parts.push(formatOddsForContext(odds));
  }

  // Fighter profiles — physical ground truth
  if (fighterContext) {
    parts.push(fighterContext);
  }

  if (injuryContext) {
    parts.push(injuryContext);
  }

  if (notes && notes.trim()) {
    parts.push('\nADDITIONAL INTEL FROM USER (training camp news, odds movements, injury reports):');
    parts.push(notes.trim());
  }

  parts.push('');
  parts.push(
    'For each fight: classify both fighters\' styles, analyze the stylistic matchup and historical patterns, ' +
    'apply any training camp modifiers with appropriate skepticism, calculate moneyline edge (implied vs true probability), ' +
    'and identify the highest-value props. ' +
    'List fights in order of moneyline confidence (highest edge first). ' +
    'Only use fighters listed in CONFIRMED FIGHTERS above.'
  );

  return parts.join('\n');
}

// ─── Team sports message builder ─────────────────────────────────────────────

function buildUserMessage({ sport, date, games, odds, rosterContext, injuryContext, propsContext, notes }) {
  const parts = [];

  parts.push(`Analyze the ${sport} slate for ${fmtDate(date)} (${date}).`);
  parts.push('');
  parts.push(formatSlateForContext(games));

  if (odds) {
    parts.push(formatOddsForContext(odds));
  }

  if (propsContext) {
    parts.push(propsContext);
  }

  if (rosterContext) {
    parts.push(rosterContext);
  }

  if (injuryContext) {
    parts.push(injuryContext);
  }

  if (notes && notes.trim()) {
    parts.push('\nADDITIONAL CONTEXT FROM USER:');
    parts.push(notes.trim());
  }

  parts.push('');
  parts.push(
    'Using the slate, confirmed rosters, live lines, and data above, identify 4–6 sharp +EV picks. ' +
    (propsContext
      ? 'Player prop lines have been provided — use those exact lines and odds. '
      : 'No prop lines fetched — note when a line is estimated. ') +
    'ONLY suggest props for athletes listed in CONFIRMED ROSTERS above.'
  );

  return parts.join('\n');
}
