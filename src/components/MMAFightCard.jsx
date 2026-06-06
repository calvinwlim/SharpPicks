import { TAG_COLORS } from '../constants/index.js';

// ─── Style tag chip ───────────────────────────────────────────────────────────

function StyleTag({ label }) {
  const c = TAG_COLORS[label] || '#4a9eff';
  return (
    <span style={{
      fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
      letterSpacing: '0.5px', textTransform: 'uppercase',
      padding: '3px 8px', borderRadius: 4,
      background: `${c}18`, color: c, border: `1px solid ${c}28`,
    }}>{label}</span>
  );
}

// ─── Probability meter ────────────────────────────────────────────────────────

function ProbBar({ implied, trueEst, color }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ position: 'relative', height: 6, background: 'rgba(255,255,255,0.07)', borderRadius: 3 }}>
        {/* Implied probability (muted) */}
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${Math.min(implied, 100)}%`,
          background: 'rgba(255,255,255,0.12)', borderRadius: 3,
        }} />
        {/* True estimate (bright) */}
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${Math.min(trueEst, 100)}%`,
          background: color, borderRadius: 3,
          transition: 'width 0.4s ease',
        }} />
      </div>
    </div>
  );
}

// ─── Moneyline section ────────────────────────────────────────────────────────

function MLPick({ ml, isBestBet }) {
  if (!ml) return null;
  const conf = ml.confidence || 70;
  const confColor =
    conf >= 80 ? 'var(--green)' :
    conf >= 70 ? 'var(--gold)'  :
                 'var(--red)';
  const riskColor =
    ml.risk_level === 'low'  ? 'var(--green)' :
    ml.risk_level === 'high' ? 'var(--red)'   :
                               'var(--gold)';
  const edge = ml.edge_pct != null ? `+${Number(ml.edge_pct).toFixed(1)}%` : '';

  return (
    <div style={{
      background: isBestBet ? 'rgba(240,176,32,0.06)' : 'var(--surface)',
      border: `1px solid ${isBestBet ? 'rgba(240,176,32,0.3)' : 'var(--border)'}`,
      borderRadius: 10, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isBestBet && <span style={{ fontSize: 13 }}>⭐</span>}
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 800,
            letterSpacing: '1.5px', textTransform: 'uppercase',
            color: isBestBet ? 'var(--gold)' : 'var(--muted)',
          }}>{isBestBet ? 'Best Bet · Moneyline' : 'Moneyline'}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {edge && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700,
              color: 'var(--green)', background: 'rgba(0,232,127,0.1)',
              padding: '2px 7px', borderRadius: 4,
            }}>{edge} edge</span>
          )}
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
            color: riskColor, textTransform: 'uppercase', letterSpacing: '0.5px',
          }}>{ml.risk_level}</span>
        </div>
      </div>

      <div style={{ padding: '12px 14px' }}>
        {/* Pick name + line */}
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 800,
          textTransform: 'uppercase', color: '#fff', lineHeight: 1.2, marginBottom: 6,
        }}>
          {ml.pick}
          {ml.line && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 400,
              color: 'var(--text-3)', marginLeft: 8, textTransform: 'none',
            }}>{ml.line}</span>
          )}
        </div>

        {/* Probability bar */}
        {ml.implied_prob != null && ml.true_prob_estimate != null && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
              <div style={{ display: 'flex', gap: 14 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--muted)' }}>
                  Implied <strong style={{ color: 'var(--text-3)' }}>{Number(ml.implied_prob).toFixed(1)}%</strong>
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--muted)' }}>
                  Our estimate <strong style={{ color: confColor }}>{Number(ml.true_prob_estimate).toFixed(1)}%</strong>
                </span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: confColor }}>
                {conf}%
              </span>
            </div>
            <ProbBar implied={ml.implied_prob} trueEst={ml.true_prob_estimate} color={confColor} />
          </div>
        )}

        {/* Reasoning */}
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 13.5, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 10 }}>
          {ml.reasoning}
        </p>

        {/* Key factors */}
        {ml.key_factors && ml.key_factors.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 10 }}>
            {ml.key_factors.map((f, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ color: 'var(--green)', fontSize: 9, flexShrink: 0, marginTop: 4 }}>▶</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text)', lineHeight: 1.45 }}>{f}</span>
              </div>
            ))}
          </div>
        )}

        {/* Footer: units + tags */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(ml.tags || []).map((t, i) => <StyleTag key={i} label={t} />)}
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 800, color: 'var(--gold)' }}>
            {ml.units || 1}u
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Props section ────────────────────────────────────────────────────────────

function PropPick({ prop }) {
  if (!prop) return null;
  const conf = prop.confidence || 65;
  const confColor = conf >= 75 ? 'var(--green)' : conf >= 65 ? 'var(--gold)' : 'var(--red)';
  const edge = prop.edge_pct != null ? `+${Number(prop.edge_pct).toFixed(1)}%` : '';

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 8, padding: '11px 13px',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 800,
          textTransform: 'uppercase', color: '#fff', lineHeight: 1.2, flex: 1,
        }}>
          {prop.pick}
          {prop.line && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 400, color: 'var(--text-3)', marginLeft: 7, textTransform: 'none' }}>
              {prop.line}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {edge && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--green)', fontWeight: 700 }}>{edge}</span>
          )}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: confColor }}>{conf}%</span>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 800, color: 'var(--gold)' }}>
            {prop.units || 0.5}u
          </span>
        </div>
      </div>

      {prop.implied_prob != null && prop.true_prob_estimate != null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <ProbBar implied={prop.implied_prob} trueEst={prop.true_prob_estimate} color={confColor} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', flexShrink: 0 }}>
            {Number(prop.implied_prob).toFixed(0)}% → {Number(prop.true_prob_estimate).toFixed(0)}%
          </span>
        </div>
      )}

      <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-2)', lineHeight: 1.65 }}>
        {prop.reasoning}
      </p>
    </div>
  );
}

// ─── Fighter column ───────────────────────────────────────────────────────────

function FighterColumn({ fighter, isEdgeWinner }) {
  if (!fighter) return null;
  return (
    <div style={{ flex: 1 }}>
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 800,
        textTransform: 'uppercase', letterSpacing: '0.3px',
        color: isEdgeWinner ? '#fff' : 'var(--text-2)', lineHeight: 1.1, marginBottom: 4,
      }}>
        {fighter.name}
        {isEdgeWinner && (
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700,
            color: 'var(--green)', background: 'rgba(0,232,127,0.1)',
            padding: '2px 6px', borderRadius: 3, marginLeft: 7, verticalAlign: 'middle',
            textTransform: 'none',
          }}>EDGE</span>
        )}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-3)', marginBottom: 6 }}>
        {fighter.record_breakdown || fighter.record || ''} · {fighter.style || ''}
      </div>

      {/* Style tags */}
      {fighter.style_tags && fighter.style_tags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
          {fighter.style_tags.map((t, i) => <StyleTag key={i} label={t} />)}
        </div>
      )}

      {/* Strengths */}
      {fighter.strengths && fighter.strengths.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {fighter.strengths.slice(0, 3).map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginBottom: 3 }}>
              <span style={{ color: 'var(--green)', fontSize: 8, flexShrink: 0, marginTop: 4 }}>▲</span>
              <span style={{ fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--text-2)', lineHeight: 1.45 }}>{s}</span>
            </div>
          ))}
        </div>
      )}

      {/* Weaknesses */}
      {fighter.weaknesses && fighter.weaknesses.length > 0 && (
        <div>
          {fighter.weaknesses.slice(0, 2).map((w, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginBottom: 3 }}>
              <span style={{ color: 'var(--red)', fontSize: 8, flexShrink: 0, marginTop: 4 }}>▼</span>
              <span style={{ fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.45 }}>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Historical vs style */}
      {fighter.vs_style_record && (
        <div style={{
          marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10.5,
          color: 'var(--text-3)', lineHeight: 1.5,
          background: 'rgba(255,255,255,0.03)', padding: '6px 9px', borderRadius: 6,
        }}>
          {fighter.vs_style_record}
        </div>
      )}
    </div>
  );
}

// ─── Main fight card ──────────────────────────────────────────────────────────

export default function MMAFightCard({ fight, bestBet, animDelay = 0 }) {
  if (!fight) return null;

  const isBestML   = bestBet === `${fight.id}_ml`;
  const edgeWinner = fight.stylistic_edge || '';

  const f1IsEdge = edgeWinner &&
    fight.fighter1 &&
    fight.fighter1.name.toLowerCase().includes(edgeWinner.toLowerCase().split(' ')[0]);

  return (
    <div style={{
      background: 'var(--surface-2)', border: '1px solid var(--border)',
      borderRadius: 14, overflow: 'hidden',
      animationName: 'fadeUp', animationDuration: '0.35s',
      animationTimingFunction: 'cubic-bezier(.2,.8,.3,1)',
      animationDelay: `${animDelay}s`, animationFillMode: 'both',
    }}>

      {/* Fight header */}
      <div style={{
        padding: '12px 18px 10px',
        borderBottom: '1px solid var(--border)',
        background: fight.is_title_fight ? 'rgba(240,176,32,0.05)' : 'transparent',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
          {fight.is_title_fight && (
            <span style={{
              fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 800,
              letterSpacing: '1.5px', textTransform: 'uppercase',
              color: 'var(--gold)', background: 'var(--gold-dim)',
              padding: '3px 8px', borderRadius: 4,
            }}>★ Title Fight</span>
          )}
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
            letterSpacing: '1px', textTransform: 'uppercase', color: 'var(--muted)',
          }}>
            {fight.weight_class || ''}{fight.rounds ? ` · ${fight.rounds} Rounds` : ''}
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>
            {fight.game_time || ''}
          </span>
        </div>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 800,
          textTransform: 'uppercase', letterSpacing: '0.3px', color: '#fff', lineHeight: 1.15,
        }}>
          {fight.fight}
        </div>
      </div>

      {/* Fighter columns */}
      <div style={{
        padding: '16px 18px', borderBottom: '1px solid var(--border)',
        display: 'flex', gap: 20,
      }}>
        <FighterColumn fighter={fight.fighter1} isEdgeWinner={f1IsEdge} />

        <div style={{ width: 1, background: 'var(--border)', flexShrink: 0 }} />

        <FighterColumn
          fighter={fight.fighter2}
          isEdgeWinner={!f1IsEdge && !!edgeWinner}
        />
      </div>

      {/* Stylistic edge + path to victory */}
      {(fight.stylistic_edge_detail || fight.path_to_victory) && (
        <div style={{ padding: '13px 18px', borderBottom: '1px solid var(--border)' }}>
          {fight.stylistic_edge_detail && (
            <div style={{
              fontFamily: 'var(--font-body)', fontSize: 13.5, color: 'var(--text-2)',
              lineHeight: 1.65, marginBottom: 8,
            }}>
              <span style={{
                fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
                letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--green)',
                marginRight: 8,
              }}>STYLISTIC EDGE</span>
              {fight.stylistic_edge_detail}
            </div>
          )}
          {fight.path_to_victory && (
            <div style={{ display: 'flex', gap: 12 }}>
              {Object.entries(fight.path_to_victory).map(([key, val]) => (
                <div key={key} style={{
                  flex: 1, background: 'rgba(255,255,255,0.02)', borderRadius: 7,
                  padding: '8px 10px',
                }}>
                  <div style={{
                    fontFamily: 'var(--font-display)', fontSize: 9.5, fontWeight: 700,
                    letterSpacing: '1px', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4,
                  }}>
                    {key === 'fighter1' ? (fight.fighter1 && fight.fighter1.name) : (fight.fighter2 && fight.fighter2.name)} wins if:
                  </div>
                  <div style={{ fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.55 }}>{val}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* X-Factor / training camp note */}
      {fight.x_factor && (
        <div style={{
          padding: '10px 18px', borderBottom: '1px solid var(--border)',
          background: 'rgba(240,176,32,0.04)',
          display: 'flex', gap: 9, alignItems: 'flex-start',
        }}>
          <span style={{ fontSize: 14, flexShrink: 0 }}>⚡</span>
          <div>
            <span style={{
              fontFamily: 'var(--font-display)', fontSize: 9.5, fontWeight: 700,
              letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--gold)',
              marginRight: 8,
            }}>X-FACTOR</span>
            <span style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-3)', lineHeight: 1.6 }}>
              {fight.x_factor}
            </span>
          </div>
        </div>
      )}

      {/* Moneyline pick */}
      <div style={{ padding: '14px 18px', borderBottom: fight.props && fight.props.length ? '1px solid var(--border)' : 'none' }}>
        <MLPick ml={fight.moneyline} isBestBet={isBestML} />
      </div>

      {/* Props */}
      {fight.props && fight.props.length > 0 && (
        <div style={{ padding: '0 18px 16px' }}>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--muted)',
            marginBottom: 9, paddingTop: 14,
          }}>
            Props & Method Bets
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {fight.props.map((prop, i) => {
              const propId = `${fight.id}_p${i + 1}`;
              return <PropPick key={propId} prop={prop} isBestBet={bestBet === propId} />;
            })}
          </div>
        </div>
      )}
    </div>
  );
}
