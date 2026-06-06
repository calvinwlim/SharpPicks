/**
 * UFC fight card visualization — stats-first, no AI required.
 * Shows physical profile, striking/grappling metrics, finish rates,
 * computed matchup insights, and live odds.
 */

// ─── Pure helpers ──────────────────────────────────────────────────────────────

function impliedProb(ml) {
  if (ml == null || ml === 0) return 50;
  return ml < 0
    ? (Math.abs(ml) / (Math.abs(ml) + 100)) * 100
    : (100 / (ml + 100)) * 100;
}

function fmtML(ml) {
  if (ml == null) return null;
  return ml > 0 ? `+${ml}` : String(ml);
}

function fmtHeight(inches) {
  if (!inches) return '';
  return `${Math.floor(inches / 12)}'${inches % 12}"`;
}

function getCardLabel(idx, total) {
  if (idx === total - 1) return { text: 'Main Event', hex: '#f0b020' };
  if (idx === total - 2) return { text: 'Co-Main',    hex: '#a78bfa' };
  if (idx >= total - 5)  return { text: 'Main Card',  hex: '#58a6ff' };
  return                        { text: 'Prelim',      hex: '#6e7681' };
}

function findOddsMatch(fight, oddsGames) {
  if (!oddsGames || !oddsGames.length) return null;
  const f1 = fight.homeTeam;
  const f2 = fight.awayTeam;
  if (!f1 || !f2) return null;
  const ln1 = (f1.name || '').split(' ').pop().toLowerCase();
  const ln2 = (f2.name || '').split(' ').pop().toLowerCase();
  if (!ln1 || !ln2) return null;
  return oddsGames.find((og) => {
    if (!og || !og.homeTeam || !og.awayTeam) return false;
    const ht = String(og.homeTeam).toLowerCase();
    const at = String(og.awayTeam).toLowerCase();
    return (ht.includes(ln1) && at.includes(ln2)) || (ht.includes(ln2) && at.includes(ln1));
  }) || null;
}

function getMLFromOdds(oddsMatch, fighterName) {
  if (!oddsMatch || !oddsMatch.bookmakers) return null;
  try {
    const ln      = (fighterName || '').split(' ').pop().toLowerCase();
    const allH2H  = oddsMatch.bookmakers.flatMap((b) => (b.markets && b.markets.h2h) || []);
    const prices  = allH2H
      .filter((o) => o && o.name && o.name.toLowerCase().includes(ln))
      .map((o) => o.price)
      .filter((p) => p != null && p !== 0);
    if (!prices.length) return null;
    prices.sort((a, b) => a - b);
    return prices[Math.floor(prices.length / 2)];
  } catch { return null; }
}

function getRoundsOU(oddsMatch) {
  if (!oddsMatch || !oddsMatch.bookmakers) return null;
  try {
    const pts = oddsMatch.bookmakers
      .flatMap((b) => (b.markets && b.markets.totals) || [])
      .filter((o) => o && o.name === 'Over' && o.point != null)
      .map((o) => o.point);
    if (!pts.length) return null;
    pts.sort((a, b) => a - b);
    return pts[Math.floor(pts.length / 2)];
  } catch { return null; }
}

// ─── Computed matchup insights (no AI — pure stats logic) ────────────────────

function computeMatchupInsights(f1, p1, f2, p2) {
  if (!f1 || !f2) return [];
  const insights = [];
  const ln1 = f1.name.split(' ').pop();
  const ln2 = f2.name.split(' ').pop();

  // Reach advantage
  if (p1 && p2 && p1.reachIn > 0 && p2.reachIn > 0) {
    const d = p1.reachIn - p2.reachIn;
    if (Math.abs(d) >= 2) {
      const who = d > 0 ? ln1 : ln2;
      insights.push({
        icon: '📏', edge: d > 0 ? 'f1' : 'f2',
        text: `${who} +${Math.abs(d)}" reach — range control advantage at distance`,
      });
    }
  }

  // Net striking edge (SLpM - SApM)
  if (p1 && p2 && (p1.slpm > 0 || p2.slpm > 0)) {
    const net1 = (p1.slpm || 0) - (p1.sapm || 0);
    const net2 = (p2.slpm || 0) - (p2.sapm || 0);
    const diff = net1 - net2;
    if (Math.abs(diff) >= 1.0) {
      const who = diff > 0 ? ln1 : ln2;
      const val = Math.abs(diff).toFixed(1);
      insights.push({
        icon: '⚡', edge: diff > 0 ? 'f1' : 'f2',
        text: `${who} nets +${val} strikes/min — dominant striking differential`,
      });
    } else if (p1.slpm > 0 && p2.slpm > 0) {
      const vDiff = (p1.slpm || 0) - (p2.slpm || 0);
      if (Math.abs(vDiff) >= 1.2) {
        const who = vDiff > 0 ? ln1 : ln2;
        insights.push({
          icon: '🥊', edge: vDiff > 0 ? 'f1' : 'f2',
          text: `${who} lands +${Math.abs(vDiff).toFixed(1)} sig strikes/min more — volume edge`,
        });
      }
    }
  }

  // Striking accuracy edge
  if (p1 && p2 && p1.strAcc > 0 && p2.strAcc > 0) {
    const d = (p1.strAcc - p2.strAcc) * 100;
    if (Math.abs(d) >= 8) {
      const who = d > 0 ? ln1 : ln2;
      insights.push({
        icon: '🎯', edge: d > 0 ? 'f1' : 'f2',
        text: `${who} strikes at +${Math.round(Math.abs(d))}pp higher accuracy — cleaner shots`,
      });
    }
  }

  // TD wrestling mismatch
  if (p1 && p2) {
    const tdThreat1 = p1.tdAvg || 0;
    const tdDef2    = p2.tdDef || 0;
    const tdThreat2 = p2.tdAvg || 0;
    const tdDef1    = p1.tdDef || 0;

    if (tdThreat1 >= 2 && tdDef2 > 0 && tdDef2 < 0.55) {
      insights.push({
        icon: '🤼', edge: 'f1',
        text: `${ln1}'s TD avg (${tdThreat1.toFixed(1)}/15) vs ${ln2}'s ${Math.round(tdDef2*100)}% TD def — wrestling dominance expected`,
      });
    } else if (tdThreat2 >= 2 && tdDef1 > 0 && tdDef1 < 0.55) {
      insights.push({
        icon: '🤼', edge: 'f2',
        text: `${ln2}'s TD avg (${tdThreat2.toFixed(1)}/15) vs ${ln1}'s ${Math.round(tdDef1*100)}% TD def — wrestling dominance expected`,
      });
    } else if (tdThreat1 >= 2 && tdThreat2 < 0.5 && tdDef2 === 0) {
      insights.push({
        icon: '🤼', edge: 'f1',
        text: `${ln1} averages ${tdThreat1.toFixed(1)} TDs/15min — grappling volume edge`,
      });
    }
  }

  // Finish rate direction (rounds O/U lean)
  if (p1 && p2 && (p1.wins > 0 || p2.wins > 0)) {
    const fin1 = p1.wins > 0 ? (p1.winsKO + p1.winsSub) / p1.wins : null;
    const fin2 = p2.wins > 0 ? (p2.winsKO + p2.winsSub) / p2.wins : null;
    const bothKnown = fin1 !== null && fin2 !== null;

    if (bothKnown) {
      const avgFin = (fin1 + fin2) / 2;
      if (avgFin > 0.65) {
        insights.push({
          icon: '🔥', edge: 'neutral',
          text: `Combined ${Math.round(avgFin*100)}% finish rate — lean UNDER rounds, KO/TKO method`,
        });
      } else if (avgFin < 0.28) {
        insights.push({
          icon: '📋', edge: 'neutral',
          text: `Decision-heavy matchup (avg ${Math.round((1-avgFin)*100)}% go distance) — lean OVER rounds`,
        });
      }
    }

    // One fighter KO threat
    const ko1 = p1.wins > 0 ? p1.winsKO / p1.wins : null;
    const ko2 = p2.wins > 0 ? p2.winsKO / p2.wins : null;
    if (ko1 !== null && ko2 !== null && Math.abs(ko1 - ko2) > 0.2) {
      const whoKO  = ko1 > ko2 ? ln1 : ln2;
      const koRate = Math.round(Math.max(ko1, ko2) * 100);
      insights.push({
        icon: '👊', edge: ko1 > ko2 ? 'f1' : 'f2',
        text: `${whoKO} finishes ${koRate}% by KO/TKO — method prop value if favorite`,
      });
    }
  }

  // Age dynamic
  if (p1 && p2 && p1.age > 0 && p2.age > 0) {
    const d = Math.abs(p1.age - p2.age);
    if (d >= 5) {
      const older   = p1.age > p2.age ? ln1 : ln2;
      const younger = p1.age > p2.age ? ln2 : ln1;
      insights.push({
        icon: '📅', edge: p1.age > p2.age ? 'f2' : 'f1',
        text: `${older} is ${d} years older than ${younger} — late-round cardio risk in extended fights`,
      });
    }
  }

  // Orthodox vs Southpaw
  const s1lc = (typeof p1?.stance === 'string') ? p1.stance.toLowerCase() : '';
  const s2lc = (typeof p2?.stance === 'string') ? p2.stance.toLowerCase() : '';
  if (s1lc && s2lc && s1lc !== s2lc) {
    const one = s1lc.includes('southpaw') ? ln1 : ln2;
    const other = one === ln1 ? ln2 : ln1;
    insights.push({
      icon: '↔️', edge: 'neutral',
      text: `${one} southpaw vs ${other} orthodox — outside leg open, angle game matters`,
    });
  }

  return insights.slice(0, 5);
}

// ─── Small UI components ───────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: 10, fontWeight: 700, letterSpacing: '1.5px',
      textTransform: 'uppercase', color: '#6e7681', marginBottom: 9,
    }}>
      {children}
    </div>
  );
}

function ProbBar({ ml1, ml2, name1, name2 }) {
  if (!ml1 && !ml2) return null;
  const p1  = impliedProb(ml1);
  const p2  = impliedProb(ml2);
  const sum = p1 + p2 || 100;
  const w1  = Math.round((p1 / sum) * 100);
  const w2  = 100 - w1;
  const fav = p1 > p2;

  return (
    <div>
      <div style={{ height: 10, display: 'flex', borderRadius: 5, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{ width: `${w1}%`, background: fav ? '#00e87f' : 'rgba(255,255,255,0.15)', transition: 'width 0.4s' }} />
        <div style={{ width: `${w2}%`, background: !fav ? '#00e87f' : 'rgba(255,255,255,0.15)' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5 }}>
        <span>
          <span style={{ fontWeight: 700, color: fav ? '#e6edf3' : '#6e7681' }}>{name1}</span>
          <span style={{ color: fav ? '#00e87f' : '#6e7681', marginLeft: 8 }}>
            {fmtML(ml1)} · {p1.toFixed(0)}%
          </span>
        </span>
        <span>
          <span style={{ color: !fav ? '#00e87f' : '#6e7681', marginRight: 8 }}>
            {p2.toFixed(0)}% · {fmtML(ml2)}
          </span>
          <span style={{ fontWeight: 700, color: !fav ? '#e6edf3' : '#6e7681' }}>{name2}</span>
        </span>
      </div>
    </div>
  );
}

// unit: '"' for inches, 'yr' for age, '/m' for per-minute, 'pp' for pct-points, '' for none
function StatRow({ label, raw1, raw2, display1, display2, name1, name2, lowerIsBetter, unit }) {
  const n1 = parseFloat(raw1) || 0;
  const n2 = parseFloat(raw2) || 0;
  if (!n1 && !n2) return null;

  const max  = Math.max(n1, n2) || 1;
  let winner = null;
  if (n1 !== n2) winner = lowerIsBetter ? (n1 < n2 ? name1 : name2) : (n1 > n2 ? name1 : name2);
  const diff = Math.abs(n1 - n2);

  const diffStr = (() => {
    const u = unit !== undefined ? unit : '"';
    if (u === 'yr') return `${Math.round(diff)}yr`;
    if (u === 'pp') return `${Math.round(diff * 100)}pp`;
    if (u === '/m') return `${diff.toFixed(2)}/m`;
    if (u === '')   return diff.toFixed(2);
    return `${diff.toFixed(1)}${u}`;
  })();

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <div style={{ width: 56, fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#6e7681', flexShrink: 0 }}>
        {label}
      </div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: winner === name1 ? '#e6edf3' : '#8b949e', width: 52, textAlign: 'right', flexShrink: 0 }}>
        {display1 || (n1 ? String(n1) : '—')}
      </div>
      <div style={{ flex: 1, position: 'relative', height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3 }}>
        {n1 > 0 && (
          <div style={{
            position: 'absolute', left: 0, top: 0, bottom: 0,
            width: `${(n1 / max) * 48}%`,
            background: winner === name1 ? '#00e87f' : 'rgba(255,255,255,0.18)',
            borderRadius: '3px 0 0 3px',
          }} />
        )}
        {n2 > 0 && (
          <div style={{
            position: 'absolute', right: 0, top: 0, bottom: 0,
            width: `${(n2 / max) * 48}%`,
            background: winner === name2 ? '#00e87f' : 'rgba(255,255,255,0.18)',
            borderRadius: '0 3px 3px 0',
          }} />
        )}
      </div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: winner === name2 ? '#e6edf3' : '#8b949e', width: 52, flexShrink: 0 }}>
        {display2 || (n2 ? String(n2) : '—')}
      </div>
      {winner && diff > 0 && (
        <div style={{ width: 68, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#00e87f', fontWeight: 700, flexShrink: 0 }}>
          {winner.split(' ').pop()} +{diffStr}
        </div>
      )}
    </div>
  );
}

// Finish-rate bar for win methods section
function MethodBar({ label, pct1, pct2, name1, name2, color }) {
  if (!pct1 && !pct2) return null;
  const max = Math.max(pct1 || 0, pct2 || 0, 0.01);
  const edge1 = (pct1 || 0) > (pct2 || 0);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
      <div style={{ width: 56, fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#6e7681', flexShrink: 0 }}>
        {label}
      </div>
      {/* F1 bar */}
      <div style={{ flex: 1 }}>
        <div style={{ position: 'relative', height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3 }}>
          {(pct1 || 0) > 0 && (
            <div style={{
              position: 'absolute', left: 0, top: 0, bottom: 0,
              width: `${((pct1||0) / max) * 100}%`,
              background: edge1 ? (color || '#00e87f') : 'rgba(255,255,255,0.18)',
              borderRadius: 3,
            }} />
          )}
        </div>
        <div style={{ textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: edge1 ? '#e6edf3' : '#8b949e', marginTop: 2 }}>
          {pct1 != null ? `${Math.round(pct1 * 100)}%` : '—'}
        </div>
      </div>
      <div style={{ width: 1, background: 'rgba(255,255,255,0.1)', height: 18, flexShrink: 0 }} />
      {/* F2 bar */}
      <div style={{ flex: 1 }}>
        <div style={{ position: 'relative', height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3 }}>
          {(pct2 || 0) > 0 && (
            <div style={{
              position: 'absolute', left: 0, top: 0, bottom: 0,
              width: `${((pct2||0) / max) * 100}%`,
              background: !edge1 ? (color || '#00e87f') : 'rgba(255,255,255,0.18)',
              borderRadius: 3,
            }} />
          )}
        </div>
        <div style={{ textAlign: 'left', fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: !edge1 ? '#e6edf3' : '#8b949e', marginTop: 2 }}>
          {pct2 != null ? `${Math.round(pct2 * 100)}%` : '—'}
        </div>
      </div>
    </div>
  );
}

// ─── Single fight card ────────────────────────────────────────────────────────

function FightCard({ fight, profiles, oddsGames, originalIdx, totalFights }) {
  if (!fight || !fight.homeTeam || !fight.awayTeam) return null;

  const f1    = fight.homeTeam;
  const f2    = fight.awayTeam;
  const p1    = profiles && f1.id ? profiles[String(f1.id)] : null;
  const p2    = profiles && f2.id ? profiles[String(f2.id)] : null;
  const label = getCardLabel(originalIdx, totalFights);
  const rounds = fight.isTitleFight ? 5 : 3;

  // Records
  const rec1 = f1.record || (p1 && p1.record) || '';
  const rec2 = f2.record || (p2 && p2.record) || '';

  // ── Odds (defensive — wrapped so a bad odds payload never crashes the card) ──
  let ml1 = null, ml2 = null, ouRounds = null, oddsLabel = null;
  try {
    const oddsMatch = findOddsMatch(fight, oddsGames);
    const espnML1   = fight.odds && fight.odds.homeMoneyline;
    const espnML2   = fight.odds && fight.odds.awayMoneyline;
    ml1 = espnML1 || getMLFromOdds(oddsMatch, f1.name);
    ml2 = espnML2 || getMLFromOdds(oddsMatch, f2.name);
    ouRounds = (fight.odds && fight.odds.total) || getRoundsOU(oddsMatch);
    oddsLabel = fight.odds ? 'ESPN Bet' : oddsMatch ? 'The Odds API' : null;
  } catch (err) {
    console.warn('[FightCard] odds error:', err.message);
  }

  // ── Decide which stat sections to show ──
  const hasPhysical  = p1 || p2;
  const hasStriking  = (p1 && (p1.slpm > 0 || p1.strAcc > 0)) || (p2 && (p2.slpm > 0 || p2.strAcc > 0));
  const hasGrappling = (p1 && (p1.tdAvg > 0 || p1.tdAcc > 0)) || (p2 && (p2.tdAvg > 0 || p2.tdAcc > 0));

  // Finish rates (need wins to compute)
  const finR1Ko  = p1 && p1.wins > 0 ? p1.winsKO  / p1.wins : null;
  const finR1Sub = p1 && p1.wins > 0 ? p1.winsSub / p1.wins : null;
  const finR1Dec = p1 && p1.wins > 0 ? 1 - (finR1Ko || 0) - (finR1Sub || 0) : null;
  const finR2Ko  = p2 && p2.wins > 0 ? p2.winsKO  / p2.wins : null;
  const finR2Sub = p2 && p2.wins > 0 ? p2.winsSub / p2.wins : null;
  const finR2Dec = p2 && p2.wins > 0 ? 1 - (finR2Ko || 0) - (finR2Sub || 0) : null;
  const hasFinish = finR1Ko !== null || finR2Ko !== null;

  // Computed insights
  const insights = computeMatchupInsights(f1, p1, f2, p2);

  // Props lean from finish rates
  const propsLean = [];
  if (hasFinish) {
    const avg = ((finR1Ko||0) + (finR1Sub||0) + (finR2Ko||0) + (finR2Sub||0)) / 2;
    if (avg > 0.65) propsLean.push({ tag: `UNDER ${rounds - 0.5} rounds`, why: `${Math.round(avg*100)}% combined finish rate` });
    else if (avg < 0.30) propsLean.push({ tag: `OVER ${rounds - 0.5} rounds`, why: `${Math.round((1-avg)*100)}% go distance` });
    const koAvg = ((finR1Ko||0) + (finR2Ko||0)) / 2;
    if (koAvg > 0.45) propsLean.push({ tag: 'KO/TKO method', why: `${Math.round(koAvg*100)}% avg KO rate` });
    const subAvg = ((finR1Sub||0) + (finR2Sub||0)) / 2;
    if (subAvg > 0.20) propsLean.push({ tag: 'Submission', why: `${Math.round(subAvg*100)}% avg sub rate` });
  }

  const edgeColor = (e) => e === 'f1' ? '#58a6ff' : e === 'f2' ? '#a78bfa' : '#8b949e';

  const S = { padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.07)' };

  return (
    <div style={{ background: '#21262d', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 12, overflow: 'hidden' }}>

      {/* ── Fight header ── */}
      <div style={{
        padding: '12px 18px 10px',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        background: fight.isTitleFight ? 'rgba(240,176,32,0.06)' : 'rgba(0,0,0,0.12)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7, flexWrap: 'wrap' }}>
          <span style={{
            fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 800,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: label.hex,
            background: `${label.hex}22`, padding: '3px 9px', borderRadius: 4,
          }}>{label.text}</span>
          {fight.isTitleFight && (
            <span style={{
              fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 800,
              letterSpacing: '1.5px', textTransform: 'uppercase', color: '#f0b020',
              background: 'rgba(240,176,32,0.15)', padding: '3px 9px', borderRadius: 4,
            }}>★ Title Fight</span>
          )}
          <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 11, fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase', color: '#8b949e' }}>
            {fight.weightClass ? `${fight.weightClass} · ` : ''}{rounds}R
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#8b949e' }}>
            {fight.gameTime || ''}
          </span>
        </div>
        {/* Ranking badges */}
        {(p1?.ranking || p2?.ranking) && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 5 }}>
            {p1?.ranking && <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 800, letterSpacing: '1px', textTransform: 'uppercase', color: '#f0b020', background: 'rgba(240,176,32,0.12)', padding: '2px 8px', borderRadius: 4 }}>{p1.ranking}</span>}
            {p2?.ranking && <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 800, letterSpacing: '1px', textTransform: 'uppercase', color: '#f0b020', background: 'rgba(240,176,32,0.12)', padding: '2px 8px', borderRadius: 4 }}>{p2.ranking}</span>}
          </div>
        )}
        <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 22, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.3px', color: '#e6edf3', lineHeight: 1.1 }}>
          {f1.name}{p1?.nickname ? <span style={{ fontSize: 14, fontWeight: 500, color: '#8b949e', textTransform: 'none', marginLeft: 6 }}>"{p1.nickname}"</span> : ''}
          <span style={{ color: '#6e7681', margin: '0 10px', fontSize: 16, fontWeight: 400 }}>vs</span>
          {f2.name}{p2?.nickname ? <span style={{ fontSize: 14, fontWeight: 500, color: '#8b949e', textTransform: 'none', marginLeft: 6 }}>"{p2.nickname}"</span> : ''}
        </div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#8b949e', marginTop: 4 }}>
          {rec1 || '—'}<span style={{ color: '#6e7681', margin: '0 8px' }}>·</span>{rec2 || '—'}
        </div>
      </div>

      {/* ── Physical comparison ── */}
      {hasPhysical && (
        <div style={S}>
          <SectionLabel>Physical Profile</SectionLabel>
          <StatRow label="Reach" raw1={p1?.reachIn || 0} raw2={p2?.reachIn || 0}
            display1={p1?.reachIn ? `${p1.reachIn}"` : ''} display2={p2?.reachIn ? `${p2.reachIn}"` : ''}
            name1={f1.name} name2={f2.name} unit='"' />
          <StatRow label="Height" raw1={p1?.heightIn || 0} raw2={p2?.heightIn || 0}
            display1={p1?.heightIn ? fmtHeight(p1.heightIn) : ''} display2={p2?.heightIn ? fmtHeight(p2.heightIn) : ''}
            name1={f1.name} name2={f2.name} unit='"' />
          {(p1?.legReachIn > 0 || p2?.legReachIn > 0) && (
            <StatRow label="Leg" raw1={p1?.legReachIn || 0} raw2={p2?.legReachIn || 0}
              display1={p1?.legReachIn ? `${p1.legReachIn}"` : ''} display2={p2?.legReachIn ? `${p2.legReachIn}"` : ''}
              name1={f1.name} name2={f2.name} unit='"' />
          )}
          <StatRow label="Weight" raw1={p1?.weight || 0} raw2={p2?.weight || 0}
            display1={p1?.weight ? `${p1.weight}` : ''} display2={p2?.weight ? `${p2.weight}` : ''}
            name1={f1.name} name2={f2.name} unit='lbs' />
          <StatRow label="Age" raw1={p1?.age || 0} raw2={p2?.age || 0}
            name1={f1.name} name2={f2.name} lowerIsBetter unit='yr' />
          <div style={{ display: 'flex', gap: 24, marginTop: 10, flexWrap: 'wrap' }}>
            {[
              { label: 'Stance', v1: p1?.stance,      v2: p2?.stance      },
              { label: 'From',   v1: p1?.nationality,  v2: p2?.nationality },
            ].map(({ label, v1, v2 }) => (!v1 && !v2) ? null : (
              <div key={label}>
                <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 9.5, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#6e7681', marginBottom: 3 }}>{label}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, color: '#adbac7' }}>
                  {v1 || '?'}<span style={{ color: '#6e7681', margin: '0 6px' }}>vs</span>{v2 || '?'}
                  {label === 'Stance' && v1 && v2 && typeof v1 === 'string' && typeof v2 === 'string' && v1.toLowerCase() !== v2.toLowerCase() && (
                    <span style={{ color: '#58a6ff', marginLeft: 6, fontSize: 10 }}>Southpaw matchup</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Striking profile ── */}
      {hasStriking && (
        <div style={S}>
          <SectionLabel>Striking Profile</SectionLabel>
          <StatRow label="SLpM" raw1={p1?.slpm || 0} raw2={p2?.slpm || 0}
            display1={p1?.slpm ? p1.slpm.toFixed(2) : ''} display2={p2?.slpm ? p2.slpm.toFixed(2) : ''}
            name1={f1.name} name2={f2.name} unit='/m' />
          <StatRow label="Str%" raw1={p1?.strAcc || 0} raw2={p2?.strAcc || 0}
            display1={p1?.strAcc ? `${Math.round(p1.strAcc*100)}%` : ''} display2={p2?.strAcc ? `${Math.round(p2.strAcc*100)}%` : ''}
            name1={f1.name} name2={f2.name} unit='pp' />
          <StatRow label="StrDef" raw1={p1?.strDef || 0} raw2={p2?.strDef || 0}
            display1={p1?.strDef ? `${Math.round(p1.strDef*100)}%` : ''} display2={p2?.strDef ? `${Math.round(p2.strDef*100)}%` : ''}
            name1={f1.name} name2={f2.name} unit='pp' />
          <StatRow label="SApM" raw1={p1?.sapm || 0} raw2={p2?.sapm || 0}
            display1={p1?.sapm ? p1.sapm.toFixed(2) : ''} display2={p2?.sapm ? p2.sapm.toFixed(2) : ''}
            name1={f1.name} name2={f2.name} lowerIsBetter unit='/m' />
          {/* Net striking differential */}
          {(p1?.slpm > 0 && p1?.sapm > 0) || (p2?.slpm > 0 && p2?.sapm > 0) ? (
            <StatRow
              label="Net±"
              raw1={Math.max(0, (p1?.slpm||0) - (p1?.sapm||0))}
              raw2={Math.max(0, (p2?.slpm||0) - (p2?.sapm||0))}
              display1={(p1?.slpm > 0 && p1?.sapm > 0) ? `${((p1.slpm||0)-(p1.sapm||0)).toFixed(2)}` : ''}
              display2={(p2?.slpm > 0 && p2?.sapm > 0) ? `${((p2.slpm||0)-(p2.sapm||0)).toFixed(2)}` : ''}
              name1={f1.name} name2={f2.name} unit='/m'
            />
          ) : null}
        </div>
      )}

      {/* ── Grappling profile ── */}
      {hasGrappling && (
        <div style={S}>
          <SectionLabel>Grappling Profile</SectionLabel>
          <StatRow label="TD/15" raw1={p1?.tdAvg || 0} raw2={p2?.tdAvg || 0}
            display1={p1?.tdAvg ? p1.tdAvg.toFixed(2) : ''} display2={p2?.tdAvg ? p2.tdAvg.toFixed(2) : ''}
            name1={f1.name} name2={f2.name} unit='' />
          <StatRow label="TD%" raw1={p1?.tdAcc || 0} raw2={p2?.tdAcc || 0}
            display1={p1?.tdAcc ? `${Math.round(p1.tdAcc*100)}%` : ''} display2={p2?.tdAcc ? `${Math.round(p2.tdAcc*100)}%` : ''}
            name1={f1.name} name2={f2.name} unit='pp' />
          <StatRow label="TDDef" raw1={p1?.tdDef || 0} raw2={p2?.tdDef || 0}
            display1={p1?.tdDef ? `${Math.round(p1.tdDef*100)}%` : ''} display2={p2?.tdDef ? `${Math.round(p2.tdDef*100)}%` : ''}
            name1={f1.name} name2={f2.name} unit='pp' />
          <StatRow label="Sub/15" raw1={p1?.subAvg || 0} raw2={p2?.subAvg || 0}
            display1={p1?.subAvg ? p1.subAvg.toFixed(2) : ''} display2={p2?.subAvg ? p2.subAvg.toFixed(2) : ''}
            name1={f1.name} name2={f2.name} unit='' />
        </div>
      )}

      {/* ── Win methods / finish rates ── */}
      {hasFinish && (
        <div style={S}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 9 }}>
            <SectionLabel>Win Methods</SectionLabel>
            <div style={{ display: 'flex', gap: 20, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#6e7681' }}>
              <span>{f1.name.split(' ').pop()}{p1?.wins ? ` (${p1.wins}W)` : ''}</span>
              <span>{f2.name.split(' ').pop()}{p2?.wins ? ` (${p2.wins}W)` : ''}</span>
            </div>
          </div>
          <MethodBar label="KO/TKO"  pct1={finR1Ko}  pct2={finR2Ko}  name1={f1.name} name2={f2.name} color='#f0b020' />
          <MethodBar label="Sub"     pct1={finR1Sub} pct2={finR2Sub} name1={f1.name} name2={f2.name} color='#a78bfa' />
          <MethodBar label="Decision" pct1={finR1Dec} pct2={finR2Dec} name1={f1.name} name2={f2.name} color='#58a6ff' />
        </div>
      )}

      {/* ── ESPN stats not available note ── */}
      {hasPhysical && !hasStriking && !hasGrappling && (
        <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#6e7681' }}>
            Striking/grappling stats not in ESPN data — check{' '}
            <a href="http://www.ufcstats.com" target="_blank" rel="noreferrer" style={{ color: '#58a6ff', textDecoration: 'none' }}>
              UFCStats.com
            </a>
          </span>
        </div>
      )}

      {/* ── Statistical matchup insights ── */}
      {insights.length > 0 && (
        <div style={{ padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'rgba(0,0,0,0.1)' }}>
          <SectionLabel>Statistical Analysis</SectionLabel>
          {insights.map((ins, i) => (
            <div key={i} style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '4px 0', borderBottom: i < insights.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
              <span style={{ fontSize: 13, lineHeight: 1.5, flexShrink: 0 }}>{ins.icon}</span>
              <span style={{ fontFamily: "'Barlow', sans-serif", fontSize: 12.5, color: '#c9d1d9', lineHeight: 1.5, flex: 1 }}>
                {ins.text}
              </span>
              {ins.edge !== 'neutral' && (
                <span style={{
                  marginLeft: 'auto', flexShrink: 0, alignSelf: 'center',
                  fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10,
                  fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase',
                  color: edgeColor(ins.edge), background: `${edgeColor(ins.edge)}18`,
                  padding: '2px 7px', borderRadius: 3,
                }}>
                  {(ins.edge === 'f1' ? f1.name : f2.name).split(' ').pop()}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Recent form ── */}
      {(p1?.recentFights?.length > 0 || p2?.recentFights?.length > 0) && (
        <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <SectionLabel>Recent Form</SectionLabel>
          {[{ f: f1, p: p1 }, { f: f2, p: p2 }].map(({ f, p }) => {
            if (!p || !p.recentFights || !p.recentFights.length) return null;
            return (
              <div key={f.name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
                <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 700, color: '#6e7681', width: 68, flexShrink: 0 }}>
                  {f.name.split(' ').pop()}
                </span>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {p.recentFights.slice(0, 5).map((fight, i) => {
                    const isW = fight.result === 'W';
                    const method = fight.method?.includes('TKO') ? 'TKO'
                                 : fight.method?.includes('KO') ? 'KO'
                                 : fight.method?.startsWith('Sub') ? 'Sub'
                                 : fight.method?.startsWith('Dec') || fight.method?.includes('DEC') ? 'Dec'
                                 : fight.method || '?';
                    return (
                      <span key={i} style={{
                        fontFamily: "'JetBrains Mono', monospace", fontSize: 10.5, fontWeight: 600,
                        color: isW ? '#00e87f' : '#f85149',
                        background: isW ? 'rgba(0,232,127,0.08)' : 'rgba(248,81,73,0.08)',
                        border: `1px solid ${isW ? 'rgba(0,232,127,0.2)' : 'rgba(248,81,73,0.2)'}`,
                        padding: '2px 6px', borderRadius: 4,
                      }}>
                        {fight.result} · {method}{fight.round ? ` R${fight.round}` : ''}
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Moneyline odds ── */}
      {(ml1 || ml2) ? (
        <div style={{ padding: '12px 18px', borderBottom: (ouRounds || propsLean.length) ? '1px solid rgba(255,255,255,0.07)' : 'none' }}>
          {oddsLabel && (
            <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: '#6e7681', marginBottom: 8 }}>
              Moneyline · {oddsLabel}
            </div>
          )}
          <ProbBar ml1={ml1} ml2={ml2} name1={f1.name} name2={f2.name} />
        </div>
      ) : (
        <div style={{ padding: '10px 18px', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#6e7681', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          Live odds not yet available — add Odds API key in Settings
        </div>
      )}

      {/* ── Total rounds ── */}
      {ouRounds && (
        <div style={{ padding: '8px 18px', borderBottom: propsLean.length ? '1px solid rgba(255,255,255,0.07)' : 'none', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: '#6e7681' }}>Total Rounds</span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 700, color: '#adbac7' }}>O/U {ouRounds}</span>
        </div>
      )}

      {/* ── Stats-based props leans ── */}
      {propsLean.length > 0 && (
        <div style={{ padding: '10px 18px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {propsLean.slice(0, 3).map((p, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: 'rgba(0,232,127,0.06)', border: '1px solid rgba(0,232,127,0.18)',
              borderRadius: 6, padding: '4px 10px',
            }}>
              <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px', color: '#00e87f' }}>
                {p.tag}
              </span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#6e7681' }}>
                {p.why}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function MMAVisualizationPanel({
  games, fighterProfiles, oddsData, oddsTimestamp, onGeneratePicks, loading,
}) {
  if (!games || !games.length) return null;

  const oddsGames = (oddsData && oddsData.games) || null;
  const cardName  = (games[0] && games[0].cardName) || 'UFC Fight Card';
  const venue     = games[0]
    ? [games[0].venue.name, games[0].venue.city].filter(Boolean).join(', ')
    : '';

  const mainCardFights = games.filter((_, i) => i >= games.length - 5);
  const prelimFights   = games.filter((_, i) => i < games.length - 5);

  const CTAButton = ({ style }) => (
    <button className="btn-gold" onClick={onGeneratePicks} disabled={loading} style={style}>
      {loading ? 'Analyzing...' : 'Generate AI Picks →'}
    </button>
  );

  return (
    <div style={{ animationName: 'fadeUp', animationDuration: '0.3s', animationFillMode: 'both' }}>

      {/* ── AI CTA banner ── */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(240,176,32,0.14), rgba(240,176,32,0.06))',
        border: '1px solid rgba(240,176,32,0.35)',
        borderRadius: 12, padding: '16px 20px', marginBottom: 24,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
      }}>
        <div>
          <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 16, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '1px', color: '#f0b020', marginBottom: 4 }}>
            Fight card loaded — review stats, then generate AI picks
          </div>
          <div style={{ fontFamily: "'Barlow', sans-serif", fontSize: 13, color: '#8b949e' }}>
            Physical + statistical edges shown below. Add camp/injury intel to Context for sharper picks.
          </div>
        </div>
        <CTAButton style={{ flexShrink: 0, padding: '11px 22px' }} />
      </div>

      {/* ── Event header ── */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 26, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px', color: '#e6edf3', lineHeight: 1 }}>
          {cardName}
        </div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#8b949e', marginTop: 5 }}>
          {venue && `${venue} · `}
          {games.length} fight{games.length !== 1 ? 's' : ''} · ESPN confirmed
          {oddsTimestamp && <span style={{ color: '#00e87f', marginLeft: 8 }}>· Odds as of {oddsTimestamp}</span>}
        </div>
      </div>

      {/* ── Main card ── */}
      <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 11, fontWeight: 700, letterSpacing: '2px', textTransform: 'uppercase', color: '#6e7681', marginBottom: 12 }}>
        Main Card
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 28 }}>
        {[...mainCardFights].reverse().map((fight, i) => (
          <FightCard
            key={fight.id || `main-${i}`}
            fight={fight}
            profiles={fighterProfiles}
            oddsGames={oddsGames}
            originalIdx={games.length - 1 - i}
            totalFights={games.length}
          />
        ))}
      </div>

      {/* ── Prelims ── */}
      {prelimFights.length > 0 && (
        <>
          <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 11, fontWeight: 700, letterSpacing: '2px', textTransform: 'uppercase', color: '#6e7681', marginBottom: 12 }}>
            Prelims
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
            {[...prelimFights].reverse().map((fight, i) => (
              <FightCard
                key={fight.id || `prelim-${i}`}
                fight={fight}
                profiles={fighterProfiles}
                oddsGames={oddsGames}
                originalIdx={prelimFights.length - 1 - i}
                totalFights={games.length}
              />
            ))}
          </div>
        </>
      )}

      {/* ── Bottom CTA ── */}
      <div style={{ textAlign: 'center', paddingBottom: 16 }}>
        <CTAButton style={{ padding: '14px 40px', fontSize: 17 }} />
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#6e7681', marginTop: 8 }}>
          AI covers the main card — paste camp &amp; injury intel in the Context box for sharper picks
        </div>
      </div>
    </div>
  );
}
