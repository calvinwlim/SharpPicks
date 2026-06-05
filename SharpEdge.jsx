import { useState } from "react";

// ─────────────────────────── CONFIG ───────────────────────────────────────

const SPORTS = ["NBA", "MLB", "NFL", "NHL", "NCAAB"];
const FILTERS = ["All", "Player Prop", "Game Total", "Moneyline", "Spread"];
const SPORT_ICONS = { NBA: "🏀", MLB: "⚾", NFL: "🏈", NHL: "🏒", NCAAB: "🎓" };

const TAG_COLORS = {
  "Historical Pattern": "#00e87f",
  "Matchup Edge": "#4a9eff",
  "Home Spot": "#f0b020",
  "Away Spot": "#a78bfa",
  "Back to Back": "#ff4757",
  "Rest Advantage": "#34d399",
  "Travel Spot": "#ff6b35",
  "Injury Report": "#ef4444",
  "Sharp Money": "#00e87f",
  "Hot Streak": "#fb923c",
  "Cold Streak": "#7dd3fc",
  "Playoff Game": "#f0b020",
  "Weather": "#93c5fd",
  "Revenge Spot": "#ec4899",
  "Pace Edge": "#67e8f9",
  "Line Value": "#4ade80",
  "Low Volume": "#c084fc",
  "NRFI Edge": "#fbbf24",
  "Trap Game": "#f87171",
};

// ─────────────────────────── SYSTEM PROMPT ────────────────────────────────

const SYSTEM_PROMPT = `You are an elite professional sharp sports bettor and quantitative analyst with 15+ years of profitable experience. Your ONLY goal is to find bets with genuine positive expected value (+EV) that will generate profit over time.

CRITICAL PHILOSOPHY: A pick is only worth making if you have a REAL mathematical edge. The line is set by the sharpest bettors in the world — you need a specific, data-backed reason to disagree with it. Narrative is not edge. "Team is due" is not edge. Historical records vs specific opponents, usage rate mismatches, volume data, and convergent statistical signals ARE edge.

YOUR PICKS MUST MATCH THIS EXACT ANALYTICAL STYLE:

EXAMPLE 1 (MLB): "Brayan Bello is over in 5/6 games against the Orioles over the last three years for Over 3.5 strikeouts. The Orioles also have the 5th highest strikeout rate, Bello is also over in 26/31 games vs top 14 K rate teams and over in 7/8 vs teams also top 9 in walk rate, giving him a great shot as he's crushed in similar matchups and a day game is extra boost for pitchers."

EXAMPLE 2 (NBA): "Stephon Castle under 1.5 made threes. Castle has 3 or less attempts in 3/3 games vs Knicks this year and is under in 41/42 games with 3 or less attempts this year, and hes under in 6/7 playoff games coming into this game and shot 23% last series vs thunder."

EXAMPLE 3 (NBA): "Over 0.5 keldon johnson made threes. Johnson has 3+ threes taken now in 7 straight games and 4+ in 6/7 and we need just one make today, and he took 2+ threes in every game vs the knicks this year and is over in 77% of games with 2 or more attempts."

KEY PATTERNS IN EXAMPLES:
- Specific H2H fractions (5/6 games, 26/31 games, 41/42 games)
- Team stat rankings ("5th highest K rate", "top 14 K rate teams")
- Multiple converging conditions (H2H record PLUS team ranking PLUS recent streak)
- Threshold logic: confirming attempt volume makes the line achievable ("we just need one make", "3 or fewer attempts in 3/3 games vs this team")
- Situational kickers (day game boost, playoff games, specific series context)

SHARP BETTING FRAMEWORK:
1. H2H RECORDS: Exact fractions vs specific opponent (e.g., "7/9 over vs this team"). Prioritize N≥5 samples.
2. ATTEMPT/VOLUME GATES: For props, first confirm the player will get enough attempts/opportunities. If they have 3 or fewer attempts, under on made threes is near-certain. This is the #1 NBA prop edge.
3. MATCHUP SPECIFICS: Defender assignments, pitcher vs team K%, pace matchup for totals
4. CONVERGENT EDGES: Stack 3+ angles. Single-angle bets are fragile; three aligned signals are strong.
5. SITUATIONAL: Back-to-backs = major fade on fatigued teams/players. 4+ days rest = strong consider. Cross-country travel = small edge against.
6. INJURY CASCADE: Who replaces who, and what does that do to prop structure (usage shifts, role changes)
7. LOW-THRESHOLD PROPS: 0.5 and 1.5 lines are more efficient than high lines. When backed by attempt data, they're some of the best +EV bets available.
8. CLOSING LINE VALUE: Mentally estimate where this line will close. If it moves toward your bet, that validates your edge.

SPORT-SPECIFIC KEYS:
- NBA: Usage rate shifts, attempt rates for props (3PM, assists, blocks), pace for totals, back-to-back fade, rest advantage
- MLB: Pitcher K/9 vs team K%, day/night splits (day game boosts pitchers), park factors, ump tendencies, NRFI in low-scoring environments
- NFL: Target share vs specific coverage schemes, rush share, weather for totals, dome vs outdoor splits
- NHL: Goalie save% trends, power play opportunities, shot volume for goal props
- NCAAB: Pace differential, 3PT rate, home court effect magnitude

STEP 1: Search for the actual game schedule for the date provided.
STEP 2: Search for injury reports, lineup news, confirmed starters.
STEP 3: Search for the specific stats most relevant to your strongest picks.
STEP 4: Return only picks where you have GENUINE CONVERGENT EDGE backed by data.

QUALITY CONTROL: If you can't find strong supporting data for a pick, do not include it. 5 great picks beat 8 mediocre ones every time.

Return ONLY a valid JSON object. Zero text before or after it. No markdown code fences. No preamble. Just the raw JSON:
{
  "date": "YYYY-MM-DD",
  "sport": "NBA",
  "slate_summary": "Sharp 2-3 sentence slate overview. What are the key betting narratives? Any major injury news, schedule spots, or line value situations?",
  "picks": [
    {
      "id": "1",
      "pick": "Exact bet description with line and odds if available (e.g., Jaylen Brown Over 26.5 Points -110)",
      "confidence": 78,
      "bet_type": "Player Prop",
      "units": 1.5,
      "game": "Celtics vs Heat",
      "game_time": "7:30 PM ET",
      "reasoning": "Detailed sharp reasoning matching the style of the examples above. Include specific H2H fractions, team stat rankings, recent streaks, and situational factors. Be specific and data-driven.",
      "key_stats": [
        "Brown is 7/9 over 26.5 vs Heat in last 2 seasons",
        "Heat rank 28th in defensive rating vs wings (per 100 possessions)",
        "Brown averaging 29.4 PPG in last 8 with usage up 3.2% since Tatum out"
      ],
      "risk_level": "low",
      "tags": ["Historical Pattern", "Matchup Edge", "Hot Streak"]
    }
  ],
  "best_bet": "1",
  "games_analyzed": ["Celtics vs Heat", "Lakers vs Warriors"]
}

Rules:
- 5-8 picks, ranked by descending confidence
- "best_bet" = id of single highest-confidence pick
- confidence: 60-69=speculative, 70-79=solid edge, 80-89=strong, 90+=exceptional (rare)
- units: 0.5=risky, 1.0=standard, 1.5=confident, 2.0=high confidence, 3.0=max (rare)
- risk_level: "low" (low threshold, strong history), "medium", or "high"
- Only include picks with genuine +EV edge`;

// ─────────────────────────── HELPERS ──────────────────────────────────────

const getTomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
};

const fmtDate = (s) =>
  new Date(s + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });

// ─────────────────────────── PICK CARD ────────────────────────────────────

function PickCard({ pick, isBest, idx }) {
  const conf = pick.confidence || 72;
  const confC = conf >= 80 ? "#00e87f" : conf >= 70 ? "#f0b020" : "#ff4757";
  const bt = (pick.bet_type || "").toLowerCase();
  const badge =
    bt.includes("prop")   ? { bg: "rgba(74,158,255,0.1)",   c: "#4a9eff",  bd: "rgba(74,158,255,0.22)" }
    : bt.includes("total") ? { bg: "rgba(167,139,250,0.1)", c: "#a78bfa",  bd: "rgba(167,139,250,0.22)" }
    : bt.includes("money") ? { bg: "rgba(0,232,127,0.1)",   c: "#00e87f",  bd: "rgba(0,232,127,0.22)" }
    :                        { bg: "rgba(255,107,53,0.1)",   c: "#ff6b35",  bd: "rgba(255,107,53,0.22)" };

  return (
    <div style={{
      background: "#0c1219",
      border: `1px solid ${isBest ? "#f0b020" : "rgba(255,255,255,0.07)"}`,
      borderRadius: 12, overflow: "hidden", position: "relative",
      boxShadow: isBest ? "0 0 40px rgba(240,176,32,0.1), 0 4px 20px rgba(0,0,0,0.3)" : "0 2px 14px rgba(0,0,0,0.28)",
      animationName: "fadeUp", animationDuration: "0.38s",
      animationTimingFunction: "cubic-bezier(.2,.8,.3,1)",
      animationDelay: `${idx * 0.07}s`, animationFillMode: "both",
      transition: "transform 0.18s, box-shadow 0.18s",
    }}>
      {isBest && (
        <div style={{
          position: "absolute", top: 12, right: 12, zIndex: 2,
          background: "linear-gradient(135deg, #f0b020, #c88a00)",
          color: "#000", padding: "3px 9px", borderRadius: 4,
          fontWeight: 900, fontSize: 9.5, letterSpacing: "2px",
          textTransform: "uppercase", fontFamily: "'Barlow Condensed', sans-serif",
        }}>⭐ BEST BET</div>
      )}

      {/* Pick name + badge */}
      <div style={{ padding: "15px 15px 11px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <div style={{ display: "flex", gap: 9, marginBottom: 7, alignItems: "flex-start" }}>
          <div style={{
            flex: 1, fontFamily: "'Barlow Condensed', sans-serif",
            fontSize: 19, fontWeight: 800, textTransform: "uppercase",
            letterSpacing: "0.3px", color: "#fff", lineHeight: 1.18,
            paddingRight: isBest ? 78 : 0,
          }}>{pick.pick}</div>
          {!isBest && (
            <span style={{
              background: badge.bg, color: badge.c, border: `1px solid ${badge.bd}`,
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize: 9.5, fontWeight: 700, letterSpacing: "1.5px",
              padding: "3px 7px", borderRadius: 4, textTransform: "uppercase",
              flexShrink: 0, lineHeight: "16px", marginTop: 2,
            }}>{pick.bet_type}</span>
          )}
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, color: "#3a4f62",
        }}>
          <span>{pick.game}</span>
          {pick.game_time && (
            <>
              <span style={{ width: 3, height: 3, borderRadius: "50%", background: "#3a4f62", display: "inline-block", flexShrink: 0 }} />
              <span>{pick.game_time}</span>
            </>
          )}
        </div>
      </div>

      {/* Confidence + units + risk */}
      <div style={{
        padding: "9px 15px", borderBottom: "1px solid rgba(255,255,255,0.06)",
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9.5, color: "#3a4f62", textTransform: "uppercase", letterSpacing: "1px", flexShrink: 0 }}>CONF</span>
        <div style={{ flex: 1, height: 3, background: "rgba(255,255,255,0.07)", borderRadius: 2 }}>
          <div style={{ width: `${conf}%`, height: "100%", background: confC, borderRadius: 2 }} />
        </div>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 700, color: confC, minWidth: 34, textAlign: "right" }}>{conf}%</span>
        <div style={{
          background: "#0f1924", border: "1px solid rgba(255,255,255,0.09)",
          borderRadius: 5, padding: "3px 7px", display: "flex", gap: 3, alignItems: "center", flexShrink: 0,
        }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#3a4f62" }}>U</span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, fontWeight: 700, color: "#f0b020" }}>{pick.units || 1}</span>
        </div>
        <span style={{
          fontFamily: "'Barlow Condensed', sans-serif",
          fontSize: 9.5, fontWeight: 700, letterSpacing: "0.5px", textTransform: "uppercase",
          padding: "2px 7px", borderRadius: 4, flexShrink: 0,
          color: pick.risk_level === "low" ? "#00e87f" : pick.risk_level === "high" ? "#ff4757" : "#f0b020",
          background: pick.risk_level === "low" ? "rgba(0,232,127,0.08)" : pick.risk_level === "high" ? "rgba(255,71,87,0.08)" : "rgba(240,176,32,0.08)",
        }}>{pick.risk_level || "med"}</span>
      </div>

      {/* Body */}
      <div style={{ padding: "13px 15px" }}>
        <p style={{ fontFamily: "'Barlow', sans-serif", fontSize: 13, color: "#6a8aa5", lineHeight: 1.7, marginBottom: 12 }}>
          {pick.reasoning}
        </p>
        {pick.key_stats?.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 11 }}>
            {pick.key_stats.slice(0, 4).map((stat, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
                <span style={{ color: "#00e87f", flexShrink: 0, fontSize: 9.5, marginTop: 3 }}>▶</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, color: "#b8cad8", lineHeight: 1.45 }}>{stat}</span>
              </div>
            ))}
          </div>
        )}
        {pick.tags?.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {pick.tags.map((tag, i) => {
              const c = TAG_COLORS[tag] || "#4a9eff";
              return (
                <span key={i} style={{
                  fontFamily: "'Barlow Condensed', sans-serif",
                  fontSize: 9.5, fontWeight: 700, letterSpacing: "0.5px", textTransform: "uppercase",
                  padding: "3px 8px", borderRadius: 4,
                  background: `${c}14`, color: c, border: `1px solid ${c}25`,
                }}>{tag}</span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────── MAIN APP ─────────────────────────────────────

export default function SharpEdge() {
  const [sport, setSport] = useState("NBA");
  const [date, setDate] = useState(getTomorrow());
  const [filter, setFilter] = useState("All");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const analyze = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    const msgs = [
      "Scanning game slate...",
      "Pulling injury reports...",
      "Loading advanced stats...",
      "Analyzing H2H patterns...",
      "Finding sharp edges...",
      "Calibrating +EV scores...",
    ];
    let mi = 0;
    setLoadingMsg(msgs[0]);
    const ticker = setInterval(() => { mi = (mi + 1) % msgs.length; setLoadingMsg(msgs[mi]); }, 2600);

    try {
      const userMsg = `Analyze the ${sport} game slate for ${fmtDate(date)} (${date}). Search for the actual games scheduled, confirm injury/lineup news, and find 5-8 sharp +EV betting picks with specific historical backing and convergent edges.${notes ? `\n\nAdditional context to factor into the analysis:\n${notes}` : ""}`;

      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 4000,
          system: SYSTEM_PROMPT,
          tools: [{ type: "web_search_20250305", name: "web_search" }],
          messages: [{ role: "user", content: userMsg }],
        }),
      });

      if (!res.ok) {
        const ed = await res.json().catch(() => ({}));
        throw new Error(ed.error?.message || `API error: ${res.status}`);
      }

      const data = await res.json();
      const texts = (data.content || []).filter(b => b.type === "text");
      if (!texts.length) throw new Error("No analysis returned. Please try again.");

      const raw = texts[texts.length - 1].text;
      const si = raw.indexOf("{");
      const ei = raw.lastIndexOf("}");
      if (si === -1) throw new Error("Could not parse analysis. Please try again.");

      const parsed = JSON.parse(raw.slice(si, ei + 1));
      if (!parsed.picks?.length) throw new Error("No picks found for this slate.");

      // Normalize ids to strings
      parsed.picks = parsed.picks.map((p, i) => ({ ...p, id: String(p.id ?? i + 1) }));
      parsed.best_bet = String(parsed.best_bet ?? "1");
      setResult(parsed);
    } catch (err) {
      setError(err.message || "Analysis failed. Please try again.");
    } finally {
      clearInterval(ticker);
      setLoading(false);
    }
  };

  const filtered = (result?.picks || []).filter(p => {
    if (filter === "All") return true;
    const f = filter.toLowerCase();
    const b = (p.bet_type || "").toLowerCase();
    if (f.includes("prop")) return b.includes("prop");
    if (f.includes("total")) return b.includes("total");
    if (f.includes("money")) return b.includes("money");
    if (f.includes("spread")) return b.includes("spread");
    return true;
  });

  const avgConf = filtered.length
    ? Math.round(filtered.reduce((a, p) => a + (p.confidence || 70), 0) / filtered.length)
    : 0;

  const totalUnits = parseFloat(
    filtered.reduce((a, p) => a + (parseFloat(p.units) || 1), 0).toFixed(1)
  );

  return (
    <div style={{ minHeight: "100vh", background: "#070a0f", color: "#b8cad8", fontFamily: "'Barlow', sans-serif" }}>
      {/* INJECTED STYLES */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Barlow:wght@300;400;500;600;700&display=swap');
        @keyframes fadeUp { from { opacity:0; transform:translateY(10px) } to { opacity:1; transform:translateY(0) } }
        @keyframes spin { to { transform:rotate(360deg) } }
        @keyframes blink { 0%,100% { opacity:.5 } 50% { opacity:1 } }
        * { box-sizing:border-box }
        textarea { resize:none; font-family:inherit }
        button { font-family:inherit; cursor:pointer }
        input[type="date"] { color-scheme:dark }
        input[type="date"]::-webkit-calendar-picker-indicator { filter:invert(.35) }
        ::-webkit-scrollbar { width:5px; background:#07090f }
        ::-webkit-scrollbar-thumb { background:#0f1924; border-radius:3px }
        .st:hover { color:#b8cad8 !important; background:rgba(255,255,255,0.06) !important }
        .fb:hover { color:#b8cad8 !important }
        .ab:hover:not(:disabled) { background:#00c86a !important; box-shadow:0 4px 24px rgba(0,200,106,.22) }
        .rb:hover { border-color:rgba(0,232,127,0.45) !important; color:#00e87f !important }
      `}</style>

      {/* ── HEADER ── */}
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "13px 24px", borderBottom: "1px solid rgba(255,255,255,0.07)",
        background: "rgba(7,10,15,0.98)", position: "sticky", top: 0, zIndex: 50,
        backdropFilter: "blur(10px)",
      }}>
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8, background: "#00e87f",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900, fontSize: 22, color: "#000",
          }}>S</div>
          <div>
            <div style={{
              fontFamily: "'Barlow Condensed', sans-serif", fontSize: 21, fontWeight: 800,
              letterSpacing: "0.5px", textTransform: "uppercase", color: "#fff", lineHeight: 1,
            }}>SHARP<span style={{ color: "#00e87f" }}>EDGE</span></div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 8.5,
              color: "#2e4255", letterSpacing: "2px", textTransform: "uppercase", marginTop: 2,
            }}>AI SPORTS ANALYSIS</div>
          </div>
        </div>

        {/* Sport tabs */}
        <div style={{ display: "flex", gap: 2, background: "#0c1219", padding: 4, borderRadius: 10, border: "1px solid rgba(255,255,255,0.07)" }}>
          {SPORTS.map(s => (
            <button key={s} className="st" onClick={() => { setSport(s); setResult(null); setError(null); }}
              style={{
                padding: "5px 13px", borderRadius: 7, border: "none",
                fontFamily: "'Barlow Condensed', sans-serif", fontSize: 12.5, fontWeight: 700,
                letterSpacing: "1px", textTransform: "uppercase", transition: "all 0.15s",
                background: sport === s ? "#00e87f" : "transparent",
                color: sport === s ? "#000" : "#2e4255",
              }}>
              {SPORT_ICONS[s]} {s}
            </button>
          ))}
        </div>

        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10.5, color: "#2e4255" }}>
          {fmtDate(date)}
        </div>
      </header>

      {/* ── BODY ── */}
      <div style={{ display: "flex", height: "calc(100vh - 64px)" }}>

        {/* ── SIDEBAR ── */}
        <aside style={{
          width: 258, flexShrink: 0, padding: "22px 15px",
          borderRight: "1px solid rgba(255,255,255,0.07)",
          background: "#0a0d13", display: "flex", flexDirection: "column", gap: 22,
          overflowY: "auto",
        }}>
          {/* Date */}
          <div>
            <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 9.5, fontWeight: 700, letterSpacing: "2px", textTransform: "uppercase", color: "#2e4255", marginBottom: 7 }}>Slate Date</div>
            <input type="date" value={date}
              onChange={e => { setDate(e.target.value); setResult(null); setError(null); }}
              style={{
                width: "100%", background: "#0f1924", border: "1px solid rgba(255,255,255,0.09)",
                borderRadius: 8, padding: "9px 12px", color: "#b8cad8",
                fontFamily: "'JetBrains Mono', monospace", fontSize: 13, outline: "none",
              }} />
          </div>

          {/* Bet type filter */}
          <div>
            <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 9.5, fontWeight: 700, letterSpacing: "2px", textTransform: "uppercase", color: "#2e4255", marginBottom: 7 }}>Filter by Type</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {FILTERS.map(f => (
                <button key={f} className="fb" onClick={() => setFilter(f)} style={{
                  padding: "8px 10px", borderRadius: 7, border: "none", textAlign: "left",
                  fontFamily: "'Barlow', sans-serif", fontSize: 13, fontWeight: 500,
                  transition: "all 0.12s",
                  background: filter === f ? "rgba(0,232,127,0.07)" : "transparent",
                  color: filter === f ? "#00e87f" : "#2e4255",
                  outline: filter === f ? "1px solid rgba(0,232,127,0.18)" : "1px solid transparent",
                }}>{f}</button>
              ))}
            </div>
          </div>

          {/* Context textarea */}
          <div>
            <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 9.5, fontWeight: 700, letterSpacing: "2px", textTransform: "uppercase", color: "#2e4255", marginBottom: 7 }}>Context & Intel</div>
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              placeholder={"Sharpen the analysis:\n• Injury/lineup news\n• Lines you're seeing\n• Specific props or players\n• Weather or venue notes\n• Any recent intel..."}
              style={{
                width: "100%", height: 130, background: "#0f1924",
                border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8,
                padding: "10px 12px", color: "#6a8aa5",
                fontFamily: "'Barlow', sans-serif", fontSize: 12.5, lineHeight: 1.6, outline: "none",
              }} />
            <div style={{ marginTop: 6, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#1e2d3a", lineHeight: 1.5 }}>
              Paste injury news or odds for more precise +EV edge calculation.
            </div>
          </div>

          {/* Spacer + analyze */}
          <div style={{ marginTop: "auto" }}>
            <button className="ab" onClick={analyze} disabled={loading} style={{
              width: "100%", padding: "13px",
              background: loading ? "rgba(0,232,127,0.18)" : "#00e87f",
              color: "#000", border: "none", borderRadius: 10,
              fontFamily: "'Barlow Condensed', sans-serif", fontSize: 15, fontWeight: 900,
              letterSpacing: "1.5px", textTransform: "uppercase",
              transition: "all 0.2s", opacity: loading ? 0.75 : 1,
            }}>
              {loading ? "Analyzing..." : `Analyze ${sport} Slate →`}
            </button>
          </div>
        </aside>

        {/* ── MAIN CONTENT ── */}
        <main style={{ flex: 1, overflowY: "auto", padding: "24px 26px" }}>

          {/* Empty */}
          {!result && !loading && !error && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 14, textAlign: "center" }}>
              <div style={{ width: 76, height: 76, borderRadius: "50%", background: "rgba(0,232,127,0.05)", border: "1px solid rgba(0,232,127,0.09)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34 }}>📊</div>
              <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 30, fontWeight: 800, color: "#1a2836", textTransform: "uppercase", letterSpacing: "1px" }}>Ready to Find Edges</div>
              <div style={{ fontSize: 14, color: "#1a2836", maxWidth: 360, lineHeight: 1.7 }}>
                Select a sport, set the date, paste any intel you have, and click <strong style={{ color: "#22382a" }}>Analyze</strong> to surface sharp, data-backed +EV picks.
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 7, justifyContent: "center", marginTop: 8 }}>
                {["H2H Historical Records", "Attempt Volume Gates", "Matchup-Specific Stats", "Injury Cascade Analysis", "Situational Edges", "+EV Focus"].map(f => (
                  <span key={f} style={{ fontSize: 11.5, padding: "5px 12px", borderRadius: 20, background: "rgba(0,232,127,0.04)", color: "#1a3224", border: "1px solid rgba(0,232,127,0.08)" }}>{f}</span>
                ))}
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 20 }}>
              <div style={{ position: "relative" }}>
                <div style={{ width: 58, height: 58, border: "3px solid rgba(255,255,255,0.05)", borderTopColor: "#00e87f", borderRadius: "50%", animation: "spin 0.75s linear infinite" }} />
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>{SPORT_ICONS[sport]}</div>
              </div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: "#00e87f", animation: "blink 2s ease infinite" }}>{loadingMsg}</div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#1a2836" }}>Searching {sport} data for {fmtDate(date)}</div>
            </div>
          )}

          {/* Error */}
          {error && !loading && (
            <div>
              <div style={{ background: "rgba(255,71,87,0.06)", border: "1px solid rgba(255,71,87,0.18)", borderRadius: 10, padding: "14px 16px", color: "#ff6070", fontSize: 13, marginBottom: 14 }}>
                <strong>Error:</strong> {error}
              </div>
              <button onClick={analyze} style={{ padding: "9px 18px", background: "#00e87f", color: "#000", border: "none", borderRadius: 8, fontFamily: "'Barlow Condensed', sans-serif", fontSize: 13, fontWeight: 900, letterSpacing: "1px", textTransform: "uppercase" }}>↺ Try Again</button>
            </div>
          )}

          {/* Results */}
          {result && !loading && (
            <div style={{ animationName: "fadeUp", animationDuration: "0.3s", animationFillMode: "both" }}>
              {/* Results header */}
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16 }}>
                <div>
                  <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 29, fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.5px", color: "#fff", lineHeight: 1 }}>{sport} Sharp Picks</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#2e4255", textTransform: "uppercase", letterSpacing: "1px", marginTop: 4 }}>{fmtDate(date)}</div>
                </div>
                <div style={{ display: "flex", gap: 16, alignItems: "flex-end" }}>
                  {[
                    { v: filtered.length, l: "Picks" },
                    { v: `${avgConf}%`, l: "Avg Conf", c: avgConf >= 75 ? "#00e87f" : "#f0b020" },
                    { v: `${totalUnits}u`, l: "Units Out", c: "#f0b020" },
                  ].map(({ v, l, c }) => (
                    <div key={l} style={{ textAlign: "right" }}>
                      <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 25, fontWeight: 800, color: c || "#fff", lineHeight: 1 }}>{v}</div>
                      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 8.5, color: "#2e4255", textTransform: "uppercase", letterSpacing: "0.5px" }}>{l}</div>
                    </div>
                  ))}
                  <button className="rb" onClick={analyze} style={{
                    padding: "7px 12px", background: "transparent",
                    border: "1px solid rgba(0,232,127,0.18)", color: "#2e4255", borderRadius: 8,
                    fontFamily: "'Barlow Condensed', sans-serif", fontSize: 11, fontWeight: 700,
                    letterSpacing: "1px", textTransform: "uppercase", transition: "all 0.15s",
                  }}>↺ Regen</button>
                </div>
              </div>

              {/* Slate summary */}
              {result.slate_summary && (
                <div style={{
                  background: "#0c1219", border: "1px solid rgba(255,255,255,0.06)",
                  borderLeft: "3px solid #00e87f", borderRadius: 8,
                  padding: "12px 15px", marginBottom: 14,
                  fontSize: 13.5, color: "#6a8aa5", lineHeight: 1.65,
                }}>
                  <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 9, fontWeight: 700, letterSpacing: "2px", textTransform: "uppercase", color: "#00e87f60", marginRight: 9, verticalAlign: "middle" }}>SLATE</span>
                  {result.slate_summary}
                </div>
              )}

              {/* Games chips */}
              {result.games_analyzed?.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 18 }}>
                  {result.games_analyzed.map((g, i) => (
                    <span key={i} style={{
                      background: "#0c1219", border: "1px solid rgba(255,255,255,0.06)",
                      borderRadius: 6, padding: "4px 10px",
                      fontFamily: "'JetBrains Mono', monospace", fontSize: 10.5, color: "#2e4255",
                    }}>{g}</span>
                  ))}
                </div>
              )}

              {/* Picks grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 14 }}>
                {filtered.map((pick, i) => (
                  <PickCard key={pick.id || i} pick={pick} isBest={pick.id === result.best_bet} idx={i} />
                ))}
              </div>

              {filtered.length === 0 && (
                <div style={{ textAlign: "center", padding: 60, color: "#2e4255", fontSize: 14 }}>
                  No picks match the &quot;{filter}&quot; filter — switch to &quot;All&quot; to see everything.
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
