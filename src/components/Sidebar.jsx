import { useState } from 'react';
import { BET_FILTERS } from '../constants/index.js';

export default function Sidebar({
  date, onDateChange,
  filter, onFilterChange,
  notes, onNotesChange,
  groqKey, onGroqKeyChange,
  oddsKey, onOddsKeyChange,
  oddsUsage,
  rapidApiKey, onRapidApiKeyChange,
  includeProps, onIncludePropsChange,
  sportSupportsProps,
  phase,
  onVisualize,
  loading,
  sport,
  isMMA,
}) {
  const [settingsOpen, setSettingsOpen] = useState(!groqKey);

  const hasData       = ['visualized', 'done'].includes(phase);
  const isAnalyzing   = phase === 'analyzing';
  const isDone        = phase === 'done';
  const btnLabel      = loading
    ? 'Loading...'
    : hasData
      ? `Re-Visualize ${sport} →`
      : `Visualize ${sport} →`;

  return (
    <aside style={{
      width: 272, flexShrink: 0, padding: '24px 18px',
      borderRight: '1px solid var(--border)',
      background: 'var(--surface)', display: 'flex', flexDirection: 'column', gap: 22,
      overflowY: 'auto',
    }}>

      {/* ── Date ── */}
      <div>
        <div className="sidebar-label">Slate Date</div>
        <input
          type="date" value={date}
          onChange={(e) => onDateChange(e.target.value)}
          style={{ width: '100%', padding: '10px 13px', fontFamily: 'var(--font-mono)', fontSize: 13.5 }}
        />
      </div>

      {/* ── Bet type filter — only for team sports ── */}
      {!isMMA && (
        <div>
          <div className="sidebar-label">Bet Type</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {BET_FILTERS.map((f) => (
              <button key={f} onClick={() => onFilterChange(f)} style={{
                padding: '9px 12px', borderRadius: 7, border: 'none', textAlign: 'left',
                fontFamily: 'var(--font-body)', fontSize: 14, fontWeight: 500, cursor: 'pointer',
                transition: 'all 0.12s',
                background: filter === f ? 'var(--green-dim)' : 'transparent',
                color:      filter === f ? 'var(--green)' : 'var(--text-3)',
                outline:    filter === f ? '1px solid rgba(0,232,127,0.22)' : '1px solid transparent',
              }}>{f}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── Context / Notes ── */}
      <div>
        <div className="sidebar-label">{isMMA ? 'Camp & Fight Intel' : 'Context & Intel'}</div>
        <textarea
          value={notes} onChange={(e) => onNotesChange(e.target.value)} rows={6}
          placeholder={isMMA
            ? 'Add fight intel:\n• Training camp news\n• Injury / weight cut issues\n• Sparring reports\n• Odds movement you\'re seeing\n• Any recent fighter news'
            : 'Add context:\n• Injury / lineup news\n• Lines you\'re seeing\n• Specific props\n• Weather or venue notes'
          }
          style={{ width: '100%', padding: '11px 13px', fontSize: 13, color: 'var(--text-2)' }}
        />
        <div style={{ marginTop: 7, fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.5 }}>
          {isMMA
            ? 'Training camp and injury intel significantly improves AI pick accuracy.'
            : 'Paste injury news or live odds here for higher accuracy.'}
        </div>
      </div>

      {/* ── API Settings ── */}
      <div>
        <button onClick={() => setSettingsOpen((o) => !o)} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
        }}>
          <span className="sidebar-label" style={{ marginBottom: 0 }}>API Settings</span>
          <span style={{ color: 'var(--muted)', fontSize: 11 }}>{settingsOpen ? '▲' : '▼'}</span>
        </button>

        {settingsOpen && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
            {/* Groq key */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 5 }}>
                Groq API Key <span style={{ color: 'var(--red)', fontWeight: 700 }}>*</span>
              </div>
              <input type="password" value={groqKey} onChange={(e) => onGroqKeyChange(e.target.value)}
                placeholder="gsk_..."
                style={{ width: '100%', padding: '9px 11px', fontSize: 12.5, fontFamily: 'var(--font-mono)' }} />
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.55 }}>
                Free — no credit card. Sign up at{' '}
                <a href="https://console.groq.com" target="_blank" rel="noreferrer" style={{ color: 'var(--green)', textDecoration: 'none' }}>
                  console.groq.com
                </a>{' '}→ API Keys.
              </div>
            </div>

            {/* Odds API key */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 5 }}>
                The Odds API Key <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(optional)</span>
              </div>
              <input type="password" value={oddsKey} onChange={(e) => onOddsKeyChange(e.target.value)}
                placeholder="Free key at the-odds-api.com"
                style={{ width: '100%', padding: '9px 11px', fontSize: 12.5, fontFamily: 'var(--font-mono)' }} />
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.5 }}>
                Adds live odds from 20+ books. Free: 500 req/month.
                {oddsUsage && <span style={{ color: 'var(--green)', marginLeft: 4 }}>({oddsUsage})</span>}
              </div>

              {/* RapidAPI key — UFC stats (Tier 2) */}
              {isMMA && (
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 5 }}>
                    RapidAPI Key <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(optional)</span>
                  </div>
                  <input type="password" value={rapidApiKey} onChange={(e) => onRapidApiKeyChange(e.target.value)}
                    placeholder="For career stats (Tank01 / MMA APIs)"
                    style={{ width: '100%', padding: '9px 11px', fontSize: 12.5, fontFamily: 'var(--font-mono)' }} />
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.5 }}>
                    Free tier at{' '}
                    <a href="https://rapidapi.com" target="_blank" rel="noreferrer" style={{ color: 'var(--green)', textDecoration: 'none' }}>rapidapi.com</a>
                    {' '}→ search "UFC" or "MMA stats". Unlocks SLpM, TD%, finish rates.
                  </div>
                </div>
              )}

              {/* Player props toggle */}
              {!isMMA && oddsKey && oddsKey.trim() && sportSupportsProps && (
                <label style={{ display: 'flex', alignItems: 'flex-start', gap: 9, marginTop: 10, cursor: 'pointer' }}>
                  <input type="checkbox" checked={includeProps} onChange={(e) => onIncludePropsChange(e.target.checked)}
                    style={{ marginTop: 2, accentColor: 'var(--green)', width: 14, height: 14, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 600, lineHeight: 1.3 }}>
                      Fetch live player prop lines
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3, lineHeight: 1.5 }}>
                      Real DK/FD lines for AI to reference. Uses ~3 extra API requests/game.
                    </div>
                  </div>
                </label>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Free tier notice ── */}
      <div style={{
        background: 'rgba(0,232,127,0.05)', border: '1px solid rgba(0,232,127,0.14)',
        borderRadius: 8, padding: '12px 13px',
      }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'rgba(0,232,127,0.6)', marginBottom: 6 }}>
          100% Free
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.65 }}>
          {isMMA
            ? 'ESPN fight card + fighter profiles · Groq AI (Llama 3.3 70B) · Optional: live odds via The Odds API'
            : 'ESPN slate + rosters + injuries · Groq AI · Optional: live lines & props via The Odds API'
          }
        </div>
      </div>

      {/* ── Buttons ── */}
      <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button className="btn-primary" onClick={onVisualize} disabled={loading} style={{ width: '100%' }}>
          {btnLabel}
        </button>
      </div>
    </aside>
  );
}
