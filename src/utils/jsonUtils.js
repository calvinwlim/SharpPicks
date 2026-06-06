/**
 * Extracts the outermost JSON object from a raw string (strips markdown fences, preamble, etc.)
 * and repairs it if it was truncated mid-response (common when max_tokens is hit).
 */
export function extractAndRepairJSON(raw) {
  const cleaned = raw.replace(/```json\n?|```\n?/g, '').trim();

  const start = cleaned.indexOf('{');
  if (start === -1) throw new Error('No JSON object found in response.');

  const end = cleaned.lastIndexOf('}');
  if (end === -1) throw new Error('Malformed JSON — no closing brace found.');

  const candidate = cleaned.slice(start, end + 1);

  try {
    return JSON.parse(candidate);
  } catch {
    return repairTruncatedJSON(candidate);
  }
}

function repairTruncatedJSON(str) {
  // Try MMA fights array first
  const fights = extractCompleteObjects(str, 'fights');
  if (fights.length) {
    const extract = makeExtract(str);
    console.warn(`[SharpEdge] MMA JSON truncated — recovered ${fights.length} fight(s).`);
    return {
      date:         extract('date'),
      sport:        extract('sport'),
      event_name:   extract('event_name'),
      venue:        extract('venue'),
      card_summary: extract('card_summary'),
      fights,
      best_bet:     extract('best_bet') || '1_ml',
    };
  }

  // Fall back to picks array (team sports)
  const picks = extractCompleteObjects(str, 'picks');
  if (!picks.length) {
    throw new Error(
      'Response was too truncated to recover picks. Please try again.'
    );
  }

  const extract   = makeExtract(str);
  const bestBetM  = str.match(/"best_bet"\s*:\s*"?([^",}\s]+)"?/);
  console.warn(`[SharpEdge] JSON truncated — recovered ${picks.length} pick(s).`);

  return {
    date:          extract('date'),
    sport:         extract('sport'),
    slate_summary: extract('slate_summary'),
    picks,
    best_bet:      bestBetM ? bestBetM[1] : '1',
    games_analyzed: [],
  };
}

/** Regex-based scalar extractor */
function makeExtract(str) {
  return (key) => {
    const m = str.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`));
    return m ? m[1].replace(/\\"/g, '"').replace(/\\n/g, '\n') : '';
  };
}

/**
 * Scans a JSON string for a named array and returns every complete, parseable object in it.
 * Works by tracking brace depth — exits cleanly if the array is cut off.
 */
function extractCompleteObjects(str, arrayKey) {
  const search = str.search(new RegExp(`"${arrayKey}"\\s*:\\s*\\[`));
  if (search === -1) return [];

  const arrStart = str.indexOf('[', search);
  if (arrStart === -1) return [];

  const items     = [];
  let depth       = 0;
  let inString    = false;
  let escape      = false;
  let itemStart   = -1;

  for (let i = arrStart + 1; i < str.length; i++) {
    const c = str[i];

    if (escape)                 { escape = false; continue; }
    if (c === '\\' && inString) { escape = true;  continue; }
    if (c === '"')              { inString = !inString; continue; }
    if (inString)               { continue; }

    if (c === '{') {
      if (depth === 0) itemStart = i;
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0 && itemStart !== -1) {
        try { items.push(JSON.parse(str.slice(itemStart, i + 1))); } catch { /* skip */ }
        itemStart = -1;
      }
    } else if (c === ']' && depth === 0) {
      break;
    }
  }

  return items;
}
