/**
 * Team-sports data visualization (NBA, MLB, NFL, NHL, NCAAB).
 * Shows everything we've fetched — no AI, pure data — so the user can
 * form their own read before requesting AI picks.
 */

import { fmtDate } from '../utils/dateUtils.js';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function impliedProb(ml) {
  if (!ml) return 50;
  return ml < 0
    ? (Math.abs(ml) / (Math.abs(ml) + 100)) * 100
    : (100 / (ml + 100)) * 100;
}

function fmtML(ml) {
  if (!ml) return '—';
  return ml > 0 ? `+${ml}` : String(ml);
}

// ─── Odds bar ─────────────────────────────────────────────────────────────────

function OddsBar({ awayML, homeML, awayName, homeName }) {
  if (!awayML || !homeML) return null;
  const awayP = impliedProb(awayML);
  const homeP = impliedProb(homeML);
  const total = awayP + homeP;
  const awayPct = ((awayP / total) * 100).toFixed(0);
  const homePct = ((homeP / total) * 100).toFixed(0);

  return (
    <div>
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
        <div style={{ width: `${awayPct}%`, background: 'var(--blue)', borderRadius: '4px 0 0 4px' }} />
        <div style={{ width: `${homePct}%`, background: 'rgba(255,255,255,0.12)', borderRadius: '0 4px 4px 0' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10.5 }}>
        <span style={{ color: 'var(--blue)' }}>
          {awayName} {fmtML(awayML)} <span style={{ color: 'var(--text-3)' }}>({awayP.toFixed(0)}%)</span>
        </span>
        <span style={{ color: 'var(--text-3)' }}>
          {homeName} {fmtML(homeML)} ({homeP.toFixed(0)}%)
        </span>
      </div>
    </div>
  );
}

// ─── Game card ────────────────────────────────────────────────────────────────

function GameCard({ game, oddsGames }) {
  const away = game.awayTeam;
  const home = game.homeTeam;
  const espnOdds = game.odds;

  // Match this game to Odds API data (fuzzy team name match)
  const oddsMatch = (oddsGames || []).find((og) =>
    og.homeTeam && home.name && og.homeTeam.toLowerCase().includes(home.name.toLowerCase().split(' ').pop())
  );

  const books = oddsMatch ? oddsMatch.bookmakers.slice(0, 4) : [];

  return (
    <div style={{
      background: 'var(--surface-2)', border: '1px solid var(--border)',
      borderRadius: 12, overflow: 'hidden',
      animationName: 'fadeUp', animationDuration: '0.3s', animationFillMode: 'both',
    }}>
      {/* Header */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
          {/* Teams */}
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text)', letterSpacing: '0.3px' }}>
                {away.abbreviation || away.name}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>{away.record}</span>
              <span style={{ fontFamily: 'var(--font-display)', fontSize: 13, color: 'var(--muted)', fontWeight: 700 }}>@</span>
              <span style={{ fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text)', letterSpacing: '0.3px' }}>
                {home.abbreviation || home.name}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>{home.record}</span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>
              {game.gameTime}
              {game.venue && game.venue.name && (
                <span style={{ color: 'var(--muted)', marginLeft: 8 }}>· {game.venue.name}{game.venue.city ? `, ${game.venue.city}` : ''}</span>
              )}
              {game.venue && !game.venue.indoor && (
                <span style={{ color: 'var(--gold)', marginLeft: 6 }}>OUTDOOR</span>
              )}
            </div>
          </div>
          {/* Weather */}
          {game.weather && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', background: 'var(--surface-3)', padding: '3px 8px', borderRadius: 5 }}>
              🌡 {game.weather.temperature}°F
            </span>
          )}
        </div>
      </div>

      {/* ESPN Bet line */}
      {espnOdds && (
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>ESPN Bet</div>
          <div style={{ display: 'flex', gap: 20, marginBottom: 8 }}>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>SPREAD</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, fontWeight: 700, color: 'var(--text-2)' }}>{espnOdds.details || '—'}</div>
            </div>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>TOTAL</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, fontWeight: 700, color: 'var(--text-2)' }}>
                {espnOdds.total != null ? `O/U ${espnOdds.total}` : '—'}
              </div>
            </div>
            {espnOdds.homeMoneyline && (
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginBottom: 6 }}>MONEYLINE</div>
                <OddsBar
                  awayML={espnOdds.awayMoneyline} homeML={espnOdds.homeMoneyline}
                  awayName={away.abbreviation || away.name}
                  homeName={home.abbreviation || home.name}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Multi-book odds */}
      {books.length > 0 && (
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>Consensus Lines</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr 1fr 1fr', gap: '4px 12px', alignItems: 'center' }}>
            {/* Header row */}
            {['', 'Spread', 'Total', 'ML (Away)'].map((h) => (
              <div key={h} style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{h}</div>
            ))}
            {books.map((book) => {
              const spreads = book.markets.spreads || [];
              const totals  = book.markets.totals  || [];
              const h2h     = book.markets.h2h     || [];
              const awaySpread = spreads.find((o) => o.name === oddsMatch.awayTeam);
              const overTotal  = totals.find((o)  => o.name === 'Over');
              const awayMLv    = h2h.find((o) => o.name === oddsMatch.awayTeam);
              return [
                <div key={`${book.name}-lbl`} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>{book.name}</div>,
                <div key={`${book.name}-spr`} style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-2)' }}>
                  {awaySpread ? `${awaySpread.point > 0 ? '+' : ''}${awaySpread.point} (${awaySpread.price})` : '—'}
                </div>,
                <div key={`${book.name}-tot`} style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-2)' }}>
                  {overTotal ? overTotal.point : '—'}
                </div>,
                <div key={`${book.name}-ml`} style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-2)' }}>
                  {awayMLv ? fmtML(awayMLv.price) : '—'}
                </div>,
              ];
            })}
          </div>

          {/* Line range alert */}
          {(() => {
            const allSpreads = oddsMatch.bookmakers
              .flatMap((b) => b.markets.spreads || [])
              .filter((o) => o.name === oddsMatch.awayTeam)
              .map((o) => o.point);
            if (allSpreads.length > 1) {
              const mn = Math.min(...allSpreads), mx = Math.max(...allSpreads);
              if (mn !== mx) return (
                <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--gold)', background: 'var(--gold-dim)', padding: '4px 9px', borderRadius: 5, display: 'inline-block' }}>
                  ⚠ Spread range: {mn} to {mx} — soft line, possible edge
                </div>
              );
            }
            return null;
          })()}
        </div>
      )}

      {/* No odds message */}
      {!espnOdds && !books.length && (
        <div style={{ padding: '10px 16px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
          Lines not yet posted — add an Odds API key in Settings for live data
        </div>
      )}
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function VisualizationPanel({ games, oddsData, injuryContext, sport, date, oddsTimestamp, onGeneratePicks, loading }) {
  if (!games || !games.length) return null;

  const oddsGames = oddsData ? oddsData.games : null;

  return (
    <div style={{ animationName: 'fadeUp', animationDuration: '0.3s', animationFillMode: 'both' }}>

      {/* ── AI CTA banner ── */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(240,176,32,0.12), rgba(240,176,32,0.06))',
        border: '1px solid rgba(240,176,32,0.3)',
        borderRadius: 12, padding: '14px 20px', marginBottom: 22,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
      }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--gold)', marginBottom: 3 }}>
            Data loaded — ready for AI analysis
          </div>
          <div style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-3)' }}>
            Review the matchup data below, add any intel to the Context box, then generate sharp +EV picks.
          </div>
        </div>
        <button className="btn-gold" onClick={onGeneratePicks} disabled={loading} style={{ flexShrink: 0, padding: '11px 22px' }}>
          {loading ? 'Analyzing...' : 'Generate AI Picks →'}
        </button>
      </div>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 18 }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text)', lineHeight: 1 }}>
            {sport} Slate
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
            {fmtDate(date)} · {games.length} game{games.length !== 1 ? 's' : ''} · ESPN confirmed
            {oddsTimestamp && <span style={{ color: 'var(--green)', marginLeft: 8 }}>· Odds as of {oddsTimestamp}</span>}
          </div>
        </div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)' }}>
          {oddsGames ? `${oddsGames.length} books loaded` : 'ESPN odds only'}
        </div>
      </div>

      {/* ── Game cards ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {games.map((game, i) => (
          <GameCard key={game.id || i} game={game} oddsGames={oddsGames} />
        ))}
      </div>

      {/* ── Injury context ── */}
      {injuryContext && (
        <div style={{
          marginTop: 20, background: 'var(--surface-2)', border: '1px solid var(--border)',
          borderLeft: '3px solid var(--red)', borderRadius: 10, padding: '14px 18px',
        }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--red)', marginBottom: 8 }}>
            Injury & Roster News
          </div>
          <pre style={{ fontFamily: 'var(--font-body)', fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {injuryContext.replace(/INJURY \/ ROSTER NEWS \(ESPN — live feed\):\n/, '').trim()}
          </pre>
        </div>
      )}

      {/* ── Bottom CTA ── */}
      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <button className="btn-gold" onClick={onGeneratePicks} disabled={loading} style={{ padding: '14px 36px', fontSize: 17 }}>
          {loading ? 'Analyzing...' : 'Generate AI Picks →'}
        </button>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
          AI will analyze these matchups and surface the highest +EV bets
        </div>
      </div>
    </div>
  );
}
