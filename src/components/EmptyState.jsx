export default function EmptyState() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: 18, textAlign: 'center', padding: 24,
    }}>
      <div style={{
        width: 80, height: 80, borderRadius: '50%',
        background: 'rgba(0,232,127,0.06)', border: '1px solid rgba(0,232,127,0.12)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 36,
      }}>📊</div>

      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 800,
        color: '#2a3d52', textTransform: 'uppercase', letterSpacing: '1px',
      }}>
        Ready to Find Edges
      </div>

      <div style={{ fontSize: 15, color: '#3a5268', maxWidth: 400, lineHeight: 1.75 }}>
        Select a sport, set the date, add any intel you have, and click{' '}
        <strong style={{ color: '#4a6a50' }}>Analyze</strong> to get sharp, data-backed +EV picks.
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', marginTop: 8 }}>
        {[
          'Real game slate via ESPN',
          'Consensus odds (optional)',
          'H2H historical records',
          'Attempt volume gates',
          'Injury cascade analysis',
          'Situational edges',
          '+EV focus only',
        ].map((f) => (
          <span key={f} style={{
            fontSize: 12.5, padding: '6px 14px', borderRadius: 20,
            background: 'rgba(0,232,127,0.05)', color: '#2a4a36',
            border: '1px solid rgba(0,232,127,0.1)',
            fontFamily: 'var(--font-body)',
          }}>
            {f}
          </span>
        ))}
      </div>
    </div>
  );
}
