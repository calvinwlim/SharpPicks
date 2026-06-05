import { SYSTEM_PROMPT } from '../prompts/systemPrompt.js';
import { extractAndRepairJSON } from '../utils/jsonUtils.js';
import { formatSlateForContext } from './espnApi.js';
import { formatOddsForContext } from './oddsApi.js';
import { fmtDate } from '../utils/dateUtils.js';

const GROQ_API   = 'https://api.groq.com/openai/v1/chat/completions';
const GROQ_MODEL = 'llama-3.3-70b-versatile';

/**
 * Sends the confirmed game slate, live odds, and injury context to Groq (free tier)
 * for sharp pick analysis using Llama 3.3 70B.
 *
 * Free tier limits: 30 req/min, 6000 tokens/min, 14400 req/day.
 * Get a free key at: https://console.groq.com
 *
 * @param {Object} params
 * @param {string}   params.sport
 * @param {string}   params.date          - ISO "YYYY-MM-DD"
 * @param {Array}    params.games         - Parsed ESPN games
 * @param {Array}    params.odds          - Parsed Odds API data (or null)
 * @param {string}   params.rosterContext - ESPN confirmed rosters (or '')
 * @param {string}   params.injuryContext - ESPN injury feed (or '')
 * @param {string}   params.notes         - User-supplied intel
 * @param {string}   params.apiKey        - Groq API key
 */
export async function analyzeSlate({ sport, date, games, odds, rosterContext, injuryContext, notes, apiKey }) {
  if (!apiKey || !apiKey.trim()) {
    throw new Error(
      'Groq API key is required. Get a free key at console.groq.com, then add it in Settings.'
    );
  }

  const userMsg = buildUserMessage({ sport, date, games, odds, rosterContext, injuryContext, notes });

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
        temperature: 0.25,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user',   content: userMsg },
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

  if (!parsed.picks || !parsed.picks.length) {
    throw new Error('No picks found for this slate. The sport may be out of season or no games were scheduled.');
  }

  parsed.picks    = parsed.picks.map((p, i) => ({ ...p, id: String(p.id != null ? p.id : i + 1) }));
  parsed.best_bet = String(parsed.best_bet != null ? parsed.best_bet : '1');

  return parsed;
}

function buildUserMessage({ sport, date, games, odds, rosterContext, injuryContext, notes }) {
  const parts = [];

  parts.push(`Analyze the ${sport} slate for ${fmtDate(date)} (${date}).`);
  parts.push('');
  parts.push(formatSlateForContext(games));

  if (odds && odds.length) {
    parts.push(formatOddsForContext(odds));
  }

  // Rosters go first — they are the ground truth for player props
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
    'Using the slate, confirmed rosters, and data above, plus your training knowledge of ' +
    'historical H2H patterns and team tendencies, identify 4–6 sharp +EV betting picks. ' +
    'Remember: ONLY suggest player props for athletes listed in CONFIRMED ROSTERS above.'
  );

  return parts.join('\n');
}
