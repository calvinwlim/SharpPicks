import { SYSTEM_PROMPT } from '../prompts/systemPrompt.js';
import { extractAndRepairJSON } from '../utils/jsonUtils.js';
import { formatSlateForContext } from './espnApi.js';
import { formatOddsForContext } from './oddsApi.js';
import { fmtDate } from '../utils/dateUtils.js';

const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';

/**
 * Sends the confirmed game slate + live odds to Claude for sharp pick analysis.
 * Using real game data (from ESPN/Odds API) means Claude can focus all web
 * searches on stats and injury research rather than wasting calls on slate discovery.
 *
 * @param {Object} params
 * @param {string}   params.sport
 * @param {string}   params.date        - ISO "YYYY-MM-DD"
 * @param {Array}    params.games       - Parsed ESPN games
 * @param {Array}    params.odds        - Parsed Odds API data (or null)
 * @param {string}   params.notes       - User-supplied context
 * @param {string}   params.apiKey      - Anthropic API key
 */
export async function analyzeSlate({ sport, date, games, odds, notes, apiKey }) {
  if (!apiKey?.trim()) {
    throw new Error(
      'Anthropic API key is required. Add it to .env.local as VITE_ANTHROPIC_API_KEY, ' +
      'or enter it in the Settings panel.'
    );
  }

  const userMsg = buildUserMessage({ sport, date, games, odds, notes });

  let res;
  try {
    res = await fetch(ANTHROPIC_API, {
      method: 'POST',
      headers: {
        'Content-Type':      'application/json',
        'x-api-key':         apiKey.trim(),
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model:      'claude-sonnet-4-20250514',
        max_tokens: 6000,
        system:     SYSTEM_PROMPT,
        tools:      [{ type: 'web_search_20250305', name: 'web_search' }],
        messages:   [{ role: 'user', content: userMsg }],
      }),
    });
  } catch (err) {
    throw new Error(`Network error reaching Anthropic API: ${err.message}`);
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    const msg = errData.error?.message ?? `API error ${res.status}`;
    if (res.status === 401) throw new Error('Invalid Anthropic API key. Check your key in Settings.');
    if (res.status === 529) throw new Error('Anthropic API is overloaded. Please try again in a moment.');
    throw new Error(msg);
  }

  const data = await res.json();

  // The response may contain multiple content blocks: text (preambles), tool_use (web
  // search invocations), tool_result blocks, then a final text block with the JSON.
  const textBlocks = (data.content ?? []).filter((b) => b.type === 'text');

  if (!textBlocks.length) {
    throw new Error('No analysis text returned. Please try again.');
  }

  // The final text block should contain the JSON answer
  const raw = textBlocks[textBlocks.length - 1].text;

  let parsed;
  try {
    parsed = extractAndRepairJSON(raw);
  } catch (err) {
    throw new Error(`Could not parse Claude's response: ${err.message}`);
  }

  if (!parsed.picks?.length) {
    throw new Error('No picks found for this slate. The sport may be out of season or no games were scheduled.');
  }

  // Normalize IDs to strings so comparisons work regardless of JSON number vs string
  parsed.picks    = parsed.picks.map((p, i) => ({ ...p, id: String(p.id ?? i + 1) }));
  parsed.best_bet = String(parsed.best_bet ?? '1');

  return parsed;
}

/** Constructs the user message with full context block */
function buildUserMessage({ sport, date, games, odds, notes }) {
  const parts = [];

  parts.push(`Analyze the ${sport} slate for ${fmtDate(date)} (${date}).`);
  parts.push('');
  parts.push(formatSlateForContext(games));

  if (odds?.length) {
    parts.push(formatOddsForContext(odds));
  }

  if (notes?.trim()) {
    parts.push('\nADDITIONAL CONTEXT FROM USER:');
    parts.push(notes.trim());
  }

  parts.push('');
  parts.push(
    'Use web search to find injury/lineup news, recent player trends, and historical H2H stats for these specific games. Then identify 4–6 sharp +EV betting picks.'
  );

  return parts.join('\n');
}
