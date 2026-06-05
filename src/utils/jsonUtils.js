/**
 * Extracts the outermost JSON object from a raw string (strips markdown fences, preamble, etc.)
 * and repairs it if it was truncated mid-response (common when max_tokens is hit).
 */
export function extractAndRepairJSON(raw) {
  // Strip markdown code fences
  const cleaned = raw.replace(/```json\n?|```\n?/g, '').trim();

  const start = cleaned.indexOf('{');
  if (start === -1) throw new Error('No JSON object found in response.');

  const end = cleaned.lastIndexOf('}');
  if (end === -1) throw new Error('Malformed JSON — no closing brace found.');

  const candidate = cleaned.slice(start, end + 1);

  // Happy path — valid JSON
  try {
    return JSON.parse(candidate);
  } catch {
    // Fallback: recover individual pick objects and reconstruct result
    return repairTruncatedJSON(candidate);
  }
}

/**
 * Recovers as many complete pick objects as possible from a truncated JSON string,
 * then reconstructs a valid result object around them.
 */
function repairTruncatedJSON(str) {
  const picks = extractCompletePicks(str);
  if (!picks.length) {
    throw new Error(
      'Response was too truncated to recover picks. Please try again — the analysis will usually complete on the second attempt.'
    );
  }

  // Extract scalar fields with regex (safe for simple string values)
  const extract = (key) => {
    const m = str.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`));
    return m ? m[1].replace(/\\"/g, '"').replace(/\\n/g, '\n') : '';
  };

  const bestBetM = str.match(/"best_bet"\s*:\s*"?(\d+)"?/);

  console.warn(
    `[SharpEdge] JSON was truncated — recovered ${picks.length} pick(s). ` +
    'Consider shortening reasoning in the prompt or increasing max_tokens.'
  );

  return {
    date:          extract('date'),
    sport:         extract('sport'),
    slate_summary: extract('slate_summary'),
    picks,
    best_bet:      bestBetM?.[1] ?? '1',
    games_analyzed: [],
  };
}

/**
 * Scans a JSON string for the picks array and returns every complete, parseable pick object.
 * Works by tracking brace depth — exits cleanly if the array is cut off.
 */
function extractCompletePicks(str) {
  // Find the opening of the picks array
  const picksSearch = str.search(/"picks"\s*:\s*\[/);
  if (picksSearch === -1) return [];

  const arrStart = str.indexOf('[', picksSearch);
  if (arrStart === -1) return [];

  const picks = [];
  let depth    = 0;
  let inString = false;
  let escape   = false;
  let pickStart = -1;

  for (let i = arrStart + 1; i < str.length; i++) {
    const c = str[i];

    if (escape)                     { escape = false; continue; }
    if (c === '\\' && inString)     { escape = true;  continue; }
    if (c === '"')                  { inString = !inString; continue; }
    if (inString)                   { continue; }

    if (c === '{') {
      if (depth === 0) pickStart = i;
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0 && pickStart !== -1) {
        try {
          picks.push(JSON.parse(str.slice(pickStart, i + 1)));
        } catch { /* skip malformed */ }
        pickStart = -1;
      }
    } else if (c === ']' && depth === 0) {
      break; // Clean end of array
    }
  }

  return picks;
}
