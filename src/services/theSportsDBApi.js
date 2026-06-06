/**
 * TheSportsDB — free public API (key = "3")
 * Supplements ESPN data with nationality, bio text, and birth location.
 * Fully CORS-friendly.
 */

const TSDB = 'https://www.thesportsdb.com/api/v1/json/3';

export async function fetchSportsDBPlayer(playerName) {
  if (!playerName) return null;
  try {
    const params = new URLSearchParams({ p: playerName });
    const res    = await fetch(`${TSDB}/searchplayers.php?${params}`);
    if (!res.ok) return null;
    const data   = await res.json();
    const player = data?.player?.[0];
    if (!player) return null;

    return {
      nationality:   player.strNationality   || '',
      birthLocation: player.strBirthLocation || '',
      // Trim bio to keep AI context compact
      description:   (player.strDescriptionEN || player.strDescriptionDE || '').slice(0, 400).trim(),
    };
  } catch {
    return null;
  }
}
