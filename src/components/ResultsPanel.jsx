import PickCard from './PickCard.jsx';
import { fmtDate } from '../utils/dateUtils.js';

function SlateRow({ game }) {
  const { awayTeam, homeTeam, gameTime, odds, venue } = game;
  const spreadLabel = odds ? odds.details || '—' : '—';
  const totalLabel  = odds && odds.total ? `O/U ${odds.total}` : '—';

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 90px 110px 90px',
      gap: 8, padding: '8px 14px',
      borderBottom: '1px solid var(--border)',
      fontSize: 12.5, alignItems: 'center',
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)', letterSpacing: '0.3px' }}>
        <span style={{ color: 'var(--text-3)' }}>{awayTeam.abbreviation}</span>
        <span style={{ color: 'var(--muted)', margin: '0 5px' }}>@</span>
        <span style={{ color: 'var(--text)' }}>{homeTeam.abbreviation}</span>
        {venue.name && (
          <span style={{ color: 'var(--text-3)', marginLeft: 8, fontSize: 10.5 }}>
            {venue.name}
          </span>
        )}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)', fontSize: 11.5 }}>{gameTime}</div>
      <div style={{ fontFamily: 'var(--font-mono)', color: odds ? 'var(--text-2)' : 'var(--text-3)', fontSize: 11.5 }}>{spreadLabel}</div>
      <div style={{ fontFamily: 'var(--font-mono)', color: odds ? 'var(--text-2)' : 'var(--text-3)', fontSize: 11.5 }}>{totalLabel}</div>
    </div>
  );
}

function SlatePanel({ games }) {
  if (!games || !games.length) return null;
  return (
    <div style={{
      background: 'var(--surface-2)', border: '1px solid var(--border)',
      borderRadius: 10, overflow: 'hidden', marginBottom: 20,
    }}>
      {/* Column headers */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 90px 110px 90px', gap: 8,
        padding: '8px 14px', borderBottom: '1px solid var(--border)',
        background: 'rgba(255,255,255,0.02)',
      }}>
        {['Matchup / Venue', 'Time (ET)', 'Spread', 'Total'].map((h) => (
          <div key={h} style={{
            fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--muted)',
          }}>{h}</div>
        ))}
      </div>
      {games.map((g) => <SlateRow key={g.id} game={g} />)}
      <div style={{ padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-3)' }}>
          {games.length} game{games.length !== 1 ? 's' : ''} · via ESPN (confirmed)
        </span>
      </div>
    </div>
  );
}

export default function ResultsPanel({ result, games, filter, sport, date, onRegenerate }) {
  if (!result) return null;

  const filtered = (result.picks || []).filter((p) => {
    if (filter === 'All') return true;
    const f = filter.toLowerCase();
    const b = (p.bet_type || '').toLowerCase();
    if (f.includes('prop'))   return b.includes('prop');
    if (f.includes('total'))  return b.includes('total');
    if (f.includes('money'))  return b.includes('money');
    if (f.includes('spread')) return b.includes('spread');
    return true;
  });

  const avgConf    = filtered.length ? Math.round(filtered.reduce((a, p) => a + (p.confidence || 70), 0) / filtered.length) : 0;
  const totalUnits = parseFloat(filtered.reduce((a, p) => a + (parseFloat(p.units) || 1), 0).toFixed(1));
  const confColor  = avgConf >= 75 ? 'var(--green)' : 'var(--gold)';

  return (
    <div style={{ animationName: 'fadeUp', animationDuration: '0.3s', animationFillMode: 'both' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 800,
            textTransform: 'uppercase', letterSpacing: '0.5px', color: '#fff', lineHeight: 1,
          }}>
            {sport} Sharp Picks
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)',
            textTransform: 'uppercase', letterSpacing: '1px', marginTop: 5,
          }}>
            {fmtDate(date)}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end' }}>
          {[
            { v: filtered.length,  l: 'Picks' },
            { v: `${avgConf}%`,    l: 'Avg Conf',    c: confColor },
            { v: `${totalUnits}u`, l: 'Total Units',  c: 'var(--gold)' },
          ].map(({ v, l, c }) => (
            <div key={l} style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 800, color: c || '#fff', lineHeight: 1 }}>{v}</div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 3 }}>{l}</div>
            </div>
          ))}
          <button className="btn-ghost" onClick={onRegenerate}>↺ Regen</button>
        </div>
      </div>

      {/* Slate summary */}
      {result.slate_summary && (
        <div style={{
          background: 'var(--surface-2)', border: '1px solid var(--border)',
          borderLeft: '3px solid var(--green)', borderRadius: 10,
          padding: '14px 18px', marginBottom: 18,
        }}>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--green)',
            marginBottom: 7,
          }}>Slate Overview</div>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7 }}>
            {result.slate_summary}
          </p>
        </div>
      )}

      {/* ESPN slate panel */}
      <SlatePanel games={games} />

      {/* Picks grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
        {filtered.map((pick, i) => (
          <PickCard
            key={pick.id || i}
            pick={pick}
            isBest={pick.id === result.best_bet}
            animDelay={i * 0.06}
          />
        ))}
      </div>

      {filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: 70, color: 'var(--text-3)', fontSize: 15 }}>
          No picks match the &quot;{filter}&quot; filter — switch to &quot;All&quot; to see everything.
        </div>
      )}
    </div>
  );
}
