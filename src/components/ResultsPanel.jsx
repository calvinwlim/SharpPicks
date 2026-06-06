import PickCard from './PickCard.jsx';
import { fmtDate } from '../utils/dateUtils.js';

// ─── Slate panel (team sports) ────────────────────────────────────────────────

function SlateRow({ game }) {
  const { awayTeam, homeTeam, gameTime, odds, venue } = game;
  const spreadLabel = odds ? odds.details || '—' : '—';
  const totalLabel  = odds && odds.total != null ? `O/U ${odds.total}` : '—';

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 90px 110px 90px',
      gap: 8, padding: '8px 14px', borderBottom: '1px solid var(--border)',
      fontSize: 12.5, alignItems: 'center',
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
        <span style={{ color: 'var(--text-3)' }}>{awayTeam.abbreviation}</span>
        <span style={{ color: 'var(--muted)', margin: '0 5px' }}>@</span>
        <span>{homeTeam.abbreviation}</span>
        {venue.name && (
          <span style={{ color: 'var(--text-3)', marginLeft: 8, fontSize: 10.5 }}>{venue.name}</span>
        )}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)', fontSize: 11.5 }}>{gameTime}</div>
      <div style={{ fontFamily: 'var(--font-mono)', color: odds ? 'var(--text-2)' : 'var(--text-3)', fontSize: 11.5 }}>{spreadLabel}</div>
      <div style={{ fontFamily: 'var(--font-mono)', color: odds ? 'var(--text-2)' : 'var(--text-3)', fontSize: 11.5 }}>{totalLabel}</div>
    </div>
  );
}

function SlatePanel({ games, oddsTimestamp, propsTimestamp }) {
  if (!games || !games.length) return null;
  const isMMA = games[0] && games[0].isMMA;

  return (
    <div style={{
      background: 'var(--surface-2)', border: '1px solid var(--border)',
      borderRadius: 10, overflow: 'hidden', marginBottom: 20,
    }}>
      {isMMA ? (
        <MMASlateTable games={games} />
      ) : (
        <>
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
        </>
      )}

      {/* Footer: source + timestamps */}
      <div style={{
        padding: '8px 14px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', flexWrap: 'wrap', gap: 6,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-3)' }}>
            {games.length} {isMMA ? 'fight' : 'game'}{games.length !== 1 ? 's' : ''} · ESPN (confirmed)
          </span>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          {oddsTimestamp && (
            <DataFreshness label="Lines" time={oddsTimestamp} />
          )}
          {propsTimestamp && (
            <DataFreshness label="Props" time={propsTimestamp} />
          )}
          {!oddsTimestamp && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)' }}>
              No live lines — add Odds API key for real-time data
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function DataFreshness({ label, time }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{ width: 5, height: 5, borderRadius: '50%', background: '#00e87f' }} />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>
        {label} as of <span style={{ color: 'var(--green)' }}>{time}</span>
      </span>
    </div>
  );
}

// ─── MMA fight card table ─────────────────────────────────────────────────────

function MMASlateTable({ games }) {
  const cardName = games[0] && games[0].cardName ? games[0].cardName : 'Fight Card';
  return (
    <>
      <div style={{
        padding: '8px 14px', borderBottom: '1px solid var(--border)',
        background: 'rgba(255,255,255,0.02)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 800,
          textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text)',
        }}>{cardName}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)' }}>
          {games[0] && games[0].gameTime}
        </div>
      </div>
      {games.map((f) => <MMAFightRow key={f.id} fight={f} />)}
    </>
  );
}

function MMAFightRow({ fight }) {
  const f1 = fight.homeTeam;
  const f2 = fight.awayTeam;
  const ml1 = fight.odds ? (fight.odds.homeFavorite ? '' : '+') + fight.odds.homeMoneyline : null;
  const ml2 = fight.odds ? (!fight.odds.homeFavorite ? '' : '+') + fight.odds.awayMoneyline : null;

  return (
    <div style={{
      padding: '9px 14px', borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {fight.isTitleFight && (
            <span style={{
              fontFamily: 'var(--font-display)', fontSize: 9, fontWeight: 800,
              letterSpacing: '1px', textTransform: 'uppercase',
              color: 'var(--gold)', background: 'var(--gold-dim)',
              padding: '2px 6px', borderRadius: 4,
            }}>TITLE</span>
          )}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--text)' }}>
            {f1.name}
          </span>
          <span style={{ color: 'var(--muted)', fontSize: 11 }}>({f1.record})</span>
          <span style={{ color: 'var(--text-3)', fontSize: 11 }}>vs</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--text)' }}>
            {f2.name}
          </span>
          <span style={{ color: 'var(--muted)', fontSize: 11 }}>({f2.record})</span>
        </div>
        {fight.weightClass && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-3)', marginTop: 3 }}>
            {fight.weightClass}
          </div>
        )}
      </div>
      {ml1 && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-2)', flexShrink: 0 }}>
          {ml1} / {ml2}
        </div>
      )}
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function ResultsPanel({ result, games, filter, sport, date, oddsTimestamp, propsTimestamp, onRegenerate, onRevisualize }) {
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
            { v: `${avgConf}%`,    l: 'Avg Conf',   c: confColor },
            { v: `${totalUnits}u`, l: 'Total Units', c: 'var(--gold)' },
          ].map(({ v, l, c }) => (
            <div key={l} style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 800, color: c || '#fff', lineHeight: 1 }}>{v}</div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 3 }}>{l}</div>
            </div>
          ))}
          {onRevisualize && (
            <button className="btn-ghost" onClick={onRevisualize} style={{ borderColor: 'rgba(88,166,255,0.3)', color: 'var(--blue)' }}>
              ← Data View
            </button>
          )}
          <button className="btn-ghost" onClick={onRegenerate}>↺ Regen Picks</button>
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
            letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 7,
          }}>Slate Overview</div>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7 }}>
            {result.slate_summary}
          </p>
        </div>
      )}

      {/* Slate panel (games or fights) with freshness indicators */}
      <SlatePanel
        games={games}
        oddsTimestamp={oddsTimestamp}
        propsTimestamp={propsTimestamp}
      />

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
