// Sharp Slate frontend — fetches the API, renders game cards, picks, and the
// Top Board. No framework, no build step.

// ---- API keys (sessionStorage only — cleared when the tab closes) ----------
function apiHeaders() {
  const headers = {};
  const oddsKey = sessionStorage.getItem("oddsApiKey");
  const anthropicKey = sessionStorage.getItem("anthropicApiKey");
  const playerProps = sessionStorage.getItem("oddsPlayerProps");
  if (oddsKey) headers["X-Odds-Api-Key"] = oddsKey;
  if (anthropicKey) headers["X-Anthropic-Api-Key"] = anthropicKey;
  // Only send when the user has made an explicit choice; otherwise the server's
  // ODDS_PLAYER_PROPS env default applies.
  if (playerProps === "1" || playerProps === "0") headers["X-Odds-Player-Props"] = playerProps;
  return headers;
}

function hasAnthropicKey() {
  return !!sessionStorage.getItem("anthropicApiKey");
}

const settingsOverlay = document.getElementById("settings-overlay");
const settingsToggle = document.getElementById("settings-toggle");
const settingsClose = document.getElementById("settings-close");
const settingsSave = document.getElementById("settings-save");
const settingsClear = document.getElementById("settings-clear");
const settingsOddsKey = document.getElementById("settings-odds-key");
const settingsAnthropicKey = document.getElementById("settings-anthropic-key");
const settingsPlayerProps = document.getElementById("settings-player-props");

settingsToggle.addEventListener("click", () => {
  settingsOddsKey.value = sessionStorage.getItem("oddsApiKey") || "";
  settingsAnthropicKey.value = sessionStorage.getItem("anthropicApiKey") || "";
  // Reflect the user's explicit choice if set, else the server's effective default
  // (shown by the Props pill).
  const pp = sessionStorage.getItem("oddsPlayerProps");
  settingsPlayerProps.checked = pp === "1" || (pp === null && pillProps.classList.contains("on"));
  settingsOverlay.classList.add("open");
});
settingsClose.addEventListener("click", () => settingsOverlay.classList.remove("open"));
settingsOverlay.addEventListener("click", (e) => {
  if (e.target === settingsOverlay) settingsOverlay.classList.remove("open");
});
settingsSave.addEventListener("click", () => {
  const odds = settingsOddsKey.value.trim();
  const anthropic = settingsAnthropicKey.value.trim();
  if (odds) sessionStorage.setItem("oddsApiKey", odds); else sessionStorage.removeItem("oddsApiKey");
  if (anthropic) sessionStorage.setItem("anthropicApiKey", anthropic); else sessionStorage.removeItem("anthropicApiKey");
  sessionStorage.setItem("oddsPlayerProps", settingsPlayerProps.checked ? "1" : "0");
  settingsOverlay.classList.remove("open");
  fetch("/api/health", { headers: apiHeaders() })
    .then((r) => r.json())
    .then((d) => setFlags(d.flags || {}))
    .catch(() => {});
  // Re-fetch any open analysis panels so the new key takes effect immediately.
  document.querySelectorAll(".analysis.open").forEach((el) => {
    try {
      const game = JSON.parse(el.dataset.gameJson || "null");
      const date = el.dataset.gameDate;
      if (!game || !date) return;
      const btn = el.closest(".game-card")?.querySelector(".analyze-btn");
      delete el.dataset.loaded;
      loadAnalysis(game, date, el, btn);
    } catch (_) {}
  });
});
settingsClear.addEventListener("click", () => {
  sessionStorage.removeItem("oddsApiKey");
  sessionStorage.removeItem("anthropicApiKey");
  sessionStorage.removeItem("oddsPlayerProps");
  settingsOddsKey.value = "";
  settingsAnthropicKey.value = "";
  settingsPlayerProps.checked = false;
});

const dateInput = document.getElementById("date-input");
const loadBtn = document.getElementById("load-btn");
const slateContainer = document.getElementById("slate-container");
const topBoardSection = document.getElementById("top-board-section");
const topBoardList = document.getElementById("top-board-list");

const pillOdds = document.getElementById("pill-odds");
const pillProps = document.getElementById("pill-props");
const pillAi = document.getElementById("pill-ai");

const charts = new Map(); // gamePk -> [Chart, ...] so we can destroy on re-render

const betSidebar = document.getElementById("bet-sidebar");
const betSidebarClose = document.getElementById("bet-sidebar-close");
const betSidebarOpen = document.getElementById("bet-sidebar-open");
const betCount = document.getElementById("bet-count");
const betEvOnly = document.getElementById("bet-evonly");
const betFilters = document.getElementById("bet-filters");
const betList = document.getElementById("bet-list");

const BET_TIERS = ["Premium", "Strong", "Lean"];
let betItems = []; // { pick, game, evPct, tier, type }
let activeBetTiers = new Set(BET_TIERS);
let activeBetTypes = new Set(); // populated as types are seen
const knownBetTypes = new Set();

const PROP_LABELS = {
  mma_winner: "Winner", mma_moneyline: "Moneyline", mma_distance: "Rounds",
  mma_sigstr: "Sig Strikes", mma_sigstr_total: "Total Sig Strikes", mma_td: "Takedowns",
};

function propTypeLabel(propType) {
  if (!propType) return "Other";
  if (PROP_LABELS[propType]) return PROP_LABELS[propType];
  return propType
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function matchupLabel(game) {
  // MMA fights carry an `event`; MLB/NBA don't. MMA reads "A vs B", others "AWAY @ HOME".
  const sep = game.event != null ? "vs" : "@";
  return `${game.away.abbr} ${sep} ${game.home.abbr}`;
}

// Picks for the boards: the model's prop/moneyline picks, plus — for MMA — the
// winner verdict as a synthetic pick when it isn't a coin flip and no moneyline
// edge already represents it (so the headline lean always reaches the board).
function boardPicks(data) {
  const picks = [...(data.picks || [])];
  const fm = data.fightModel;
  if (fm && fm.pick && !fm.pick.coinFlip && !fm.moneyline) {
    picks.unshift({
      pick: `${fm.pick.fighter} to win`,
      tier: fm.pick.tier, confidence: fm.pick.confidence,
      hasMarket: false, edge: null, propType: "mma_winner",
    });
  }
  return picks;
}

let currentSport = "mlb"; // "mlb" | "nba" | "mma"

const SPORT_ICON = { mlb: "⚾", nba: "🏀", mma: "🥊" };
function setBrandSport(sport) {
  const icon = SPORT_ICON[sport] || "";
  const el = document.getElementById("brand-sport");
  if (el) el.textContent = icon;
  document.title = icon ? `Sharp Picks ${icon}` : "Sharp Picks";
}
setBrandSport(currentSport);

function gameKey(game) {
  return game.gameId != null ? game.gameId : game.gamePk;
}

function todayISO() {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d - tz).toISOString().slice(0, 10);
}

function setFlags(flags) {
  pillOdds.classList.toggle("on", !!flags.hasOdds);
  pillProps.classList.toggle("on", !!flags.playerProps);
  pillAi.classList.toggle("on", !!flags.hasAI);
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

// ---- slate ----------------------------------------------------------------

async function loadYesterdayStrip(date) {
  const strip = document.getElementById("yesterday-strip");
  if (currentSport !== "mlb") {
    strip.style.display = "none";
    return;
  }
  const d = new Date(date + "T00:00:00");
  d.setDate(d.getDate() - 1);
  const yDate = d.toISOString().slice(0, 10);

  try {
    const res = await fetch(`/api/track/${yDate}`);
    const data = await res.json();
    if (!data.graded) {
      strip.style.display = "none";
      return;
    }
    const fmt = (m, label) => {
      const graded = m.w + m.l;
      if (!graded && !m.p) return null;
      const brier = m.brier !== null ? `, Brier ${m.brier.toFixed(3)}` : "";
      const push = m.p ? `-${m.p}p` : "";
      return `${label} ${m.w}-${m.l}${push}${brier}`;
    };
    const parts = [fmt(data.strikeouts, "K"), fmt(data.total, "Total"), fmt(data.moneyline, "ML")]
      .filter(Boolean);
    if (!parts.length) {
      strip.style.display = "none";
      return;
    }
    let text = `Yesterday (${yDate}): ${parts.join(" · ")}`;
    if (data.totalBias !== null && data.totalBias !== undefined) {
      text += ` · total bias ${data.totalBias > 0 ? "+" : ""}${data.totalBias} runs`;
    }
    if (data.pending) text += ` · ${data.pending} pending`;
    strip.textContent = text;
    strip.style.display = "block";
  } catch (e) {
    strip.style.display = "none";
  }
}

// ---- history calendar -------------------------------------------------------

let historyList = [];      // flat list of graded summaries (a date can have >1 sport)
let calViewYear = 0;
let calViewMonth = 0;      // 0-based
let calSelectedDate = "";
let historySport = "all";  // "all" | "mlb" | "nba" | "mma" — active history filter

const calGrid = document.getElementById("history-cal-grid");
const calMonthLabel = document.getElementById("cal-month-label");
const historyDayDetail = document.getElementById("history-day-detail");

const SPORT_LABEL = { all: "All", mlb: "⚾ MLB", nba: "🏀 NBA", mma: "🥊 UFC" };
// Every market we know how to render; renderStatsBar/calendar skip empty ones,
// so each sport shows only its own (MLB: K/total/ML, MMA: ML/method/distance).
const MARKET_LABELS = {
  strikeouts: "Strikeouts", total: "Totals", moneyline: "Moneyline",
  method: "Method", distance: "Distance",
};
const MARKET_KEYS = Object.keys(MARKET_LABELS);
const entrySport = (e) => e.sport || "mlb"; // older graded files predate the field

// Entries matching the active sport filter (record bar aggregates these).
function historyEntries() {
  return historyList.filter((e) => historySport === "all" || entrySport(e) === historySport);
}
// Filtered entries grouped by date (a date may hold an MLB and a UFC entry).
function historyByDate() {
  const m = {};
  for (const e of historyEntries()) (m[e.date] = m[e.date] || []).push(e);
  return m;
}

// Filter chips: "All" plus each sport that actually has tracked data.
function renderHistoryFilter() {
  const el = document.getElementById("history-filter");
  const sports = [...new Set(historyList.map(entrySport))];
  if (!sports.length) { el.style.display = "none"; return; }
  if (!sports.includes(historySport) && historySport !== "all") historySport = "all";
  el.style.display = "flex";
  el.innerHTML = "";
  for (const s of ["all", ...sports]) {
    const chip = document.createElement("button");
    chip.className = "history-filter-chip" + (s === historySport ? " active" : "");
    chip.textContent = SPORT_LABEL[s] || s.toUpperCase();
    chip.addEventListener("click", () => {
      historySport = s;
      renderHistoryFilter();
      renderStatsBar();
      renderCalendar();
    });
    el.appendChild(chip);
  }
}

async function loadHistory() {
  try {
    const res = await fetch("/api/track/history");
    const data = await res.json();
    historyList = data.entries || [];
    renderHistoryFilter();
    renderStatsBar();
    renderCalendar();
  } catch (e) {
    // leave calendar empty on error
  }
}

function statCard(label, big, sub, cls) {
  const card = document.createElement("div");
  card.className = `history-stats-card ${cls || "even"}`;
  card.innerHTML =
    `<div class="hsc-label">${label}</div>` +
    `<div class="hsc-record">${big}</div>` +
    `<div class="hsc-sub">${sub}</div>`;
  return card;
}

function renderStatsBar() {
  const statsEl = document.getElementById("history-stats");
  const metaEl = document.getElementById("history-stats-meta");
  const marketsEl = document.getElementById("history-stats-markets");
  const titleEl = document.querySelector(".history-stats-title");
  if (titleEl) titleEl.textContent = historySport === "all" ? "All-Time Record" : `${historySport.toUpperCase()} Record`;
  const entries = historyEntries();
  if (!entries.length) { statsEl.style.display = "none"; return; }

  const agg = {};
  for (const k of MARKET_KEYS) agg[k] = { w: 0, l: 0, p: 0, briers: [], units: 0, bets: 0, label: MARKET_LABELS[k] };
  let totalGames = 0, totalDays = new Set(entries.map((e) => e.date)).size, biasSum = 0, biasCount = 0;
  let oUnits = 0, oBets = 0, oClvSum = 0, oClvN = 0, oBeatN = 0;

  for (const e of entries) {
    totalGames += e.games || 0;
    if (e.totalBias != null) { biasSum += e.totalBias; biasCount++; }
    const ov = e.overall;
    if (ov) {
      oUnits += ov.units || 0; oBets += ov.bets || 0;
      oClvSum += ov.clvSum || 0; oClvN += ov.clvN || 0; oBeatN += ov.beatN || 0;
    }
    for (const key of MARKET_KEYS) {
      const m = e[key];
      if (!m) continue;
      agg[key].w += m.w || 0; agg[key].l += m.l || 0; agg[key].p += m.p || 0;
      agg[key].units += m.units || 0; agg[key].bets += m.bets || 0;
      if (m.brier != null) agg[key].briers.push(m.brier);
    }
  }

  metaEl.textContent = `${totalDays} day${totalDays !== 1 ? "s" : ""} · ${totalGames} games`
    + (oBets ? ` · ${oBets} +EV bets` : "");

  marketsEl.innerHTML = "";

  // Headline betting record: ROI (did following the model make money) + CLV
  // (did our prices beat the close — the real sharpness test).
  if (oBets > 0) {
    const roi = (oUnits / oBets) * 100;
    marketsEl.appendChild(statCard("ROI",
      `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%`,
      `${oUnits >= 0 ? "+" : ""}${oUnits.toFixed(1)}u · ${oBets} bets`,
      roi > 0 ? "win" : roi < 0 ? "loss" : "even"));
  }
  if (oClvN > 0) {
    const clv = oClvSum / oClvN;
    marketsEl.appendChild(statCard("CLV",
      `${clv >= 0 ? "+" : ""}${clv.toFixed(1)}%`,
      `beat close ${((oBeatN / oClvN) * 100).toFixed(0)}% (${oClvN})`,
      clv > 0 ? "win" : clv < 0 ? "loss" : "even"));
  }

  for (const key of MARKET_KEYS) {
    const m = agg[key];
    if (m.w + m.l + m.p === 0 && m.bets === 0) continue; // no data for this market/sport
    const tot = m.w + m.l;
    const pct = tot > 0 ? ((m.w / tot) * 100).toFixed(1) : null;
    const avgBrier = m.briers.length
      ? (m.briers.reduce((a, b) => a + b, 0) / m.briers.length).toFixed(3)
      : null;
    const winCls = tot > 0 ? (m.w > m.l ? "win" : m.l > m.w ? "loss" : "even") : "even";
    const roiTxt = m.bets > 0
      ? ` · ROI ${m.units / m.bets * 100 >= 0 ? "+" : ""}${(m.units / m.bets * 100).toFixed(1)}%` : "";
    const sub = `${pct !== null ? `${pct}% win` : "—"}`
      + `${avgBrier !== null ? ` · Brier&nbsp;${avgBrier}` : ""}${roiTxt}`;
    marketsEl.appendChild(statCard(m.label,
      `${m.w}-${m.l}${m.p ? `<span class="hsc-push"> · ${m.p}P</span>` : ""}`, sub, winCls));
  }

  if (biasCount > 0) {
    const avgBias = (biasSum / biasCount).toFixed(2);
    const card = statCard("Avg Run Bias",
      `<span class="${parseFloat(avgBias) > 0 ? "win" : parseFloat(avgBias) < 0 ? "loss" : ""}">${avgBias > 0 ? "+" : ""}${avgBias}</span>`,
      "proj − actual runs", "even");
    card.classList.add("history-stats-bias");
    marketsEl.appendChild(card);
  }

  statsEl.style.display = "block";
}

function renderCalendar() {
  const today = new Date();
  if (!calViewYear) {
    calViewYear = today.getFullYear();
    calViewMonth = today.getMonth();
  }

  const MONTH_NAMES = ["January","February","March","April","May","June",
    "July","August","September","October","November","December"];
  calMonthLabel.textContent = `${MONTH_NAMES[calViewMonth]} ${calViewYear}`;

  const DAY_LABELS = ["Su","Mo","Tu","We","Th","Fr","Sa"];
  calGrid.innerHTML = "";

  for (const d of DAY_LABELS) {
    const el = document.createElement("div");
    el.className = "cal-day-label";
    el.textContent = d;
    calGrid.appendChild(el);
  }

  const firstDay = new Date(calViewYear, calViewMonth, 1).getDay();
  const daysInMonth = new Date(calViewYear, calViewMonth + 1, 0).getDate();
  const todayStr = today.toISOString().slice(0, 10);
  const byDate = historyByDate();

  for (let i = 0; i < firstDay; i++) {
    calGrid.appendChild(document.createElement("div"));
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${calViewYear}-${String(calViewMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const dayEntries = byDate[dateStr];

    const cell = document.createElement("div");
    cell.className = "cal-day";
    if (dateStr === todayStr) cell.classList.add("today");
    if (dateStr === calSelectedDate) cell.classList.add("selected");

    const num = document.createElement("div");
    num.className = "cal-day-num";
    num.textContent = d;
    cell.appendChild(num);

    if (dayEntries && dayEntries.length) {
      cell.classList.add("has-data");
      // combined record + a dot per market with data, across the day's entries
      let dw = 0, dl = 0;
      const dots = document.createElement("div");
      dots.className = "cal-day-dots";
      for (const key of MARKET_KEYS) {
        let mw = 0, ml = 0, present = false;
        for (const e of dayEntries) {
          const m = e[key];
          if (m) { mw += m.w || 0; ml += m.l || 0; present = present || (m.w + m.l + (m.p || 0)) > 0; }
        }
        dw += mw; dl += ml;
        if (present) {
          const dot = document.createElement("span");
          dot.className = `cal-dot ${mw + ml === 0 ? "even" : mw > ml ? "win" : ml > mw ? "loss" : "even"}`;
          dots.appendChild(dot);
        }
      }

      if (dw + dl > 0) {
        const rec = document.createElement("div");
        rec.className = "cal-day-record";
        rec.textContent = `${dw}-${dl}`;
        cell.appendChild(rec);
        cell.classList.add(dw > dl ? "winning" : dl > dw ? "losing" : "even");
      } else {
        cell.classList.add("even");
      }
      cell.appendChild(dots);

      cell.addEventListener("click", () => {
        calSelectedDate = dateStr;
        renderCalendar();
        showDayDetail(dayEntries);
      });
    }

    calGrid.appendChild(cell);
  }
}

function showDayDetail(dayEntries) {
  const fmtMarket = (m, label) => {
    if (!m) return "";
    const tot = (m.w || 0) + (m.l || 0);
    if (!tot && !m.p) return "";
    const pct = tot > 0 ? `${((m.w / tot) * 100).toFixed(1)}%` : "—";
    const push = m.p ? `<span class="ddm-push">${m.p}P</span>` : "";
    const brier = m.brier != null ? `<span class="ddm-brier">Brier ${m.brier.toFixed(3)}</span>` : "";
    const roi = m.bets ? `<span class="ddm-brier">ROI ${m.roi >= 0 ? "+" : ""}${m.roi}%</span>` : "";
    const winCls = tot > 0 ? (m.w > m.l ? "win" : m.l > m.w ? "loss" : "even") : "even";
    return `
      <div class="dd-market">
        <span class="ddm-label">${label}</span>
        <span class="ddm-record ${winCls}">${m.w}-${m.l}${push ? " " + push : ""}</span>
        <span class="ddm-pct">${pct}</span>
        ${brier}${roi}
      </div>`;
  };

  const date = dayEntries[0].date;
  const totalGames = dayEntries.reduce((s, e) => s + (e.games || 0), 0);
  const multi = dayEntries.length > 1;

  const sections = dayEntries.map((entry) => {
    const markets = MARKET_KEYS.map((k) => fmtMarket(entry[k], MARKET_LABELS[k])).join("");
    const ov = entry.overall;
    const ovHtml = ov && ov.bets
      ? `<div class="dd-bias">${ov.bets} +EV bets · ROI <span class="${ov.roi > 0 ? "pos" : ov.roi < 0 ? "neg" : ""}">${ov.roi >= 0 ? "+" : ""}${ov.roi}%</span>`
        + (ov.clv != null ? ` · CLV <span class="${ov.clv > 0 ? "pos" : "neg"}">${ov.clv >= 0 ? "+" : ""}${ov.clv}%</span>` : "") + `</div>`
      : "";
    const biasHtml = entry.totalBias != null
      ? `<div class="dd-bias">Run bias: <span class="${entry.totalBias > 0 ? "pos" : entry.totalBias < 0 ? "neg" : ""}">${entry.totalBias > 0 ? "+" : ""}${entry.totalBias} runs</span> <span class="dd-bias-hint">(model proj − actual)</span></div>`
      : "";
    const pendHtml = entry.pending
      ? `<div class="dd-pending">${entry.pending} still pending</div>` : "";
    const head = multi ? `<div class="dd-sport">${SPORT_LABEL[entrySport(entry)]}</div>` : "";
    return `${head}<div class="dd-markets">${markets}</div>${ovHtml}${biasHtml}${pendHtml}`;
  }).join("");

  historyDayDetail.innerHTML = `
    <div class="dd-header">
      <div class="dd-date">${date}</div>
      <div class="dd-games">${totalGames} game${totalGames !== 1 ? "s" : ""}</div>
    </div>
    ${sections}
    <button class="dd-view-btn" id="dd-view-btn">View full slate →</button>
  `;

  document.getElementById("dd-view-btn").addEventListener("click", () => {
    const sport = entrySport(dayEntries[0]);
    dateInput.value = date;
    currentSport = sport;
    setBrandSport(sport);
    document.querySelectorAll(".sport-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.sport === sport));
    showSlateView();
    loadSlate(date);
  });

  historyDayDetail.style.display = "block";
  historyDayDetail.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

document.getElementById("cal-prev").addEventListener("click", () => {
  calViewMonth--;
  if (calViewMonth < 0) { calViewMonth = 11; calViewYear--; }
  renderCalendar();
  historyDayDetail.style.display = "none";
});
document.getElementById("cal-next").addEventListener("click", () => {
  calViewMonth++;
  if (calViewMonth > 11) { calViewMonth = 0; calViewYear++; }
  renderCalendar();
  historyDayDetail.style.display = "none";
});

// ---- slate loading ----------------------------------------------------------

async function loadSlate(date) {
  slateContainer.innerHTML = '<div class="loading">Loading slate…</div>';
  const analyzeAllBtn = document.getElementById("analyze-all-btn");
  if (analyzeAllBtn) analyzeAllBtn.style.display = "none";
  loadYesterdayStrip(date);
  topBoardSection.style.display = "none";
  topBoardList.innerHTML = "";
  betItems = [];
  knownBetTypes.clear();
  activeBetTypes.clear();
  renderBetBoard();
  charts.forEach((list) => list.forEach((c) => c.destroy()));
  charts.clear();

  let data;
  try {
    const res = await fetch(`/api/slate?date=${encodeURIComponent(date)}&sport=${currentSport}`,
      { headers: apiHeaders() });
    data = await res.json();
    setFlags(data.flags || {});
  } catch (e) {
    slateContainer.innerHTML = '<div class="error">Failed to load slate.</div>';
    return;
  }

  if (!data.count) {
    slateContainer.innerHTML = '<div class="empty">No games on this date.</div>';
    return;
  }

  const grid = document.createElement("div");
  grid.className = "slate-grid";

  for (const game of data.games) {
    grid.appendChild(renderGameCard(game, date));
  }

  slateContainer.innerHTML = "";
  slateContainer.appendChild(grid);
  if (analyzeAllBtn) analyzeAllBtn.style.display = "inline-flex";
}

function renderGameCard(game, date) {
  const tpl = document.getElementById("tpl-game-card");
  const node = tpl.content.cloneNode(true);
  const card = node.querySelector(".game-card");
  card.dataset.gamePk = gameKey(game);

  if (currentSport === "nba") {
    card.querySelector(".venue").textContent = game.status || "";
    card.querySelector(".time").textContent = fmtTime(game.gameDate);
  } else if (currentSport === "mma") {
    card.querySelector(".venue").textContent = `${game.rounds}R · ${(game.event || "").split(":")[0]}`;
    card.querySelector(".time").textContent = game.status || "";
    const at = card.querySelector(".at");
    if (at) at.textContent = "vs";
  } else {
    card.querySelector(".venue").textContent = game.venue || "";
    card.querySelector(".time").textContent =
      `${fmtTime(game.gameDate)} · ${game.dayNight === "night" ? "Night" : "Day"}`;
  }

  fillTeam(card.querySelector(".team.away"), game.away);
  fillTeam(card.querySelector(".team.home"), game.home);

  const analysisEl = card.querySelector(".analysis");
  analysisEl.dataset.gameJson = JSON.stringify(game);
  analysisEl.dataset.gameDate = date;
  const btn = card.querySelector(".analyze-btn");
  const refreshBtn = card.querySelector(".refresh-btn");
  btn.addEventListener("click", () => {
    if (analysisEl.classList.contains("open")) {
      analysisEl.classList.remove("open");
      btn.textContent = "Analyze";
      refreshBtn.style.display = "none";
      return;
    }
    btn.textContent = "Hide";
    analysisEl.classList.add("open");
    refreshBtn.style.display = "inline-block";
    if (!analysisEl.dataset.loaded) {
      loadAnalysis(game, date, analysisEl, btn);
    }
  });
  refreshBtn.addEventListener("click", () => {
    delete analysisEl.dataset.loaded;
    loadAnalysis(game, date, analysisEl, btn);
  });

  return node;
}

function fillTeam(el, team) {
  el.querySelector(".abbr").textContent = team.abbr || team.name;
  const pitcherEl = el.querySelector(".pitcher");
  if (currentSport === "nba") {
    pitcherEl.textContent = team.name || "";
  } else if (currentSport === "mma") {
    pitcherEl.textContent = team.record || "";
  } else {
    const pp = team.probablePitcher;
    pitcherEl.textContent = pp ? pp.name : "TBD";
  }
}

// ---- analysis ---------------------------------------------------------------

function fetchAnalysisData(game, date, ai = 0) {
  return fetch(
    `/api/analyze/${gameKey(game)}?date=${encodeURIComponent(date)}&sport=${currentSport}&ai=${ai}`,
    { headers: apiHeaders() }
  ).then((res) => {
    if (!res.ok) throw new Error("bad response");
    return res.json();
  });
}

async function loadAnalysis(game, date, container, btn) {
  container.innerHTML = '<div class="loading">Crunching the numbers…</div>';
  try {
    const data = await fetchAnalysisData(game, date, hasAnthropicKey() ? 1 : 0);
    container.dataset.loaded = "1";
    if (data.sport === "nba") {
      renderNbaAnalysis(data, game, container);
    } else if (data.sport === "mma") {
      renderMmaAnalysis(data, game, container);
    } else {
      renderAnalysis(data, game, container);
      addToTopBoard(data, game);
      addToBetBoard(data, game);
    }
    const card = container.closest(".game-card");
    if (card) { card._analysisLoaded = true; setCardBadge(card, data, game); }
  } catch (e) {
    container.innerHTML = '<div class="error">Could not load analysis for this game.</div>';
    btn.textContent = "Analyze";
    container.classList.remove("open");
  }
}

// ---- per-card badge + "Analyze all" -----------------------------------------

// The single headline play for a card: best +EV bet, else highest-confidence
// pick, else a win-probability lean (NBA / games with no market).
function headlineFor(data, game) {
  const bets = collectBets(data, game);
  if (bets.length) {
    const withEv = bets.filter((b) => b.evPct != null);
    if (withEv.length) return withEv.reduce((a, b) => (b.evPct > a.evPct ? b : a));
    return bets.reduce((a, b) => ((b.pick.confidence || 0) > (a.pick.confidence || 0) ? b : a));
  }
  const gm = data.gameModel;
  if (gm && gm.homeWinProb != null && gm.awayWinProb != null) {
    const homeFav = gm.homeWinProb >= gm.awayWinProb;
    const prob = homeFav ? gm.homeWinProb : gm.awayWinProb;
    const team = homeFav ? game.home.abbr : game.away.abbr;
    const tier = prob >= 0.7 ? "Strong" : prob >= 0.6 ? "Lean" : "Pass";
    return { pick: { pick: `${team} ${Math.round(prob * 100)}%`, confidence: Math.round(prob * 100) },
             evPct: null, tier, type: "Winner" };
  }
  return null;
}

function setCardBadge(card, data, game) {
  const badge = card.querySelector(".card-badge");
  if (!badge) return;
  const h = headlineFor(data, game);
  if (!h) { badge.style.display = "none"; return; }
  const hasEv = h.evPct != null;
  const evTxt = hasEv ? `${h.evPct > 0 ? "+" : ""}${h.evPct.toFixed(1)}% EV` : `${h.pick.confidence}% conf`;
  const evClass = hasEv ? (h.evPct > 0 ? "cb-pos" : "cb-neg") : "";
  badge.className = `card-badge cb-${(h.tier || "lean").toLowerCase()} ${evClass}`.trim();
  badge.style.display = "flex";
  badge.innerHTML =
    `<span class="cb-tier">${h.tier || "Lean"}</span>` +
    `<span class="cb-pick" title="${h.pick.pick}">${h.pick.pick}</span>` +
    `<span class="cb-ev">${evTxt}</span>`;
}

async function quickAnalyze(card) {
  if (card._analysisLoaded) return;
  const analysisEl = card.querySelector(".analysis");
  const game = JSON.parse(analysisEl.dataset.gameJson);
  const date = analysisEl.dataset.gameDate;
  try {
    const data = await fetchAnalysisData(game, date, 0);
    card._analysisLoaded = true;
    addToTopBoard(data, game);
    addToBetBoard(data, game);
    setCardBadge(card, data, game);
  } catch (e) {
    /* leave the card un-badged on failure */
  }
}

async function analyzeAll() {
  const btn = document.getElementById("analyze-all-btn");
  const cards = Array.from(slateContainer.querySelectorAll(".game-card"));
  if (btn) { btn.disabled = true; btn.textContent = "Analyzing…"; }
  const queue = cards.slice();
  const worker = async () => { while (queue.length) await quickAnalyze(queue.shift()); };
  await Promise.all(Array.from({ length: 4 }, worker)); // limited concurrency
  if (btn) { btn.disabled = false; btn.textContent = "⚡ Analyze all"; }
}

function renderAnalysis(data, game, container) {
  container.innerHTML = "";

  if (data.oddsNote) {
    const note = document.createElement("div");
    note.className = "odds-note";
    note.textContent = `⚠ Odds: ${data.oddsNote}`;
    container.appendChild(note);
  }

  if (data.weather) {
    container.appendChild(renderWeatherBadge(data.weather));
  }
  if (data.umpire) {
    container.appendChild(renderUmpireBadge(data.umpire));
  }

  // game model
  if (data.gameModel) {
    const tpl = document.getElementById("tpl-game-model");
    const node = tpl.content.cloneNode(true);
    const gm = data.gameModel;

    const awayWp = node.querySelector(".away-wp");
    awayWp.querySelector(".label").textContent =
      `${game.away.abbr} ${(gm.awayWinProb * 100).toFixed(0)}% win`;
    awayWp.querySelector(".bar > span").style.width = `${(gm.awayWinProb * 100).toFixed(0)}%`;

    const homeWp = node.querySelector(".home-wp");
    homeWp.querySelector(".label").textContent =
      `${game.home.abbr} ${(gm.homeWinProb * 100).toFixed(0)}% win`;
    homeWp.querySelector(".bar > span").style.width = `${(gm.homeWinProb * 100).toFixed(0)}%`;

    container.appendChild(node);
    container.appendChild(renderWinProbBreakdown(gm, game));

    if (gm.total) {
      container.appendChild(renderTotalCard(gm.total));
    }
    if (gm.moneyline) {
      container.appendChild(renderMoneylineCard(gm.moneyline, game));
    }
    if (gm.f5) {
      container.appendChild(renderF5Card(gm.f5, game));
    }
    if (gm.nrfi) {
      container.appendChild(renderNrfiCard(gm.nrfi));
    }
  }

  if (!data.picks || !data.picks.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = data.pickNote || "No graded picks for this game (not enough recent starts).";
    container.appendChild(empty);
    return;
  }

  const chartList = [];
  for (const pick of data.picks) {
    const { node, canvas } = renderPickCard(pick);
    container.appendChild(node);
    const chart = drawChip(canvas, pick);
    if (chart) chartList.push(chart);
  }
  charts.set(game.gamePk, chartList);
}

const WIND_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

function windDirLabel(deg) {
  if (deg === null || deg === undefined) return "";
  return WIND_COMPASS[Math.round(deg / 22.5) % 16];
}

function renderWeatherBadge(weather) {
  const div = document.createElement("div");
  div.className = "splits";
  let text;
  if (weather.isDome) {
    text = "Roof/dome — climate controlled";
  } else if (weather.available) {
    text = `${Math.round(weather.tempF)}°F · wind ${Math.round(weather.windMph)} mph ${windDirLabel(weather.windDir)}`;
  } else {
    text = "Weather unavailable";
  }
  const span = document.createElement("span");
  span.className = "split";
  span.textContent = text;
  div.appendChild(span);
  return div;
}

function renderUmpireBadge(umpire) {
  const div = document.createElement("div");
  div.className = "splits";
  const span = document.createElement("span");
  span.className = "split";
  if (umpire.kFactor) {
    span.textContent =
      `HP ump ${umpire.name}: K ×${umpire.kFactor}, BB ×${umpire.bbFactor}, runs ×${umpire.runFactor}`;
  } else {
    span.textContent = `HP ump ${umpire.name} (no recorded tendency — neutral)`;
  }
  div.appendChild(span);
  return div;
}

function edgeLine(edge) {
  const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
  const num = (v, d = 1) => (v == null ? "—" : v.toFixed(d));
  const evClass = (edge.evPct || 0) > 0 ? "ev-pos" : "ev-neg";
  const parts = [
    `<span>Price: <strong>${edge.price > 0 ? "+" : ""}${edge.price}</strong></span>`,
    `<span>Model: ${pct(edge.modelProb)}</span>`,
    `<span>Fair: ${pct(edge.fairProb)}</span>`,
    `<span class="${evClass}">EV: ${edge.evPct > 0 ? "+" : ""}${num(edge.evPct)}%</span>`,
  ];
  if (edge.kellyPct != null) {
    parts.push(`<span>Kelly: ${num(edge.kellyPct)}% (¼: ${num(edge.kellyPct / 4)}%)</span>`);
  }
  return parts.join("\n");
}

function renderTotalCard(total) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const sideLabel = total.side === "over" ? "Over" : "Under";
  let edgeHtml;
  if (total.hasMarket && total.edge) {
    edgeHtml = `<div class="edge-box">${edgeLine(total.edge)}</div>`;
  } else {
    edgeHtml = `<div class="edge-box"><span>Analysis only — projected total ${total.projection} runs.</span></div>`;
  }
  const factorNote = (label, factor) =>
    factor && factor !== 1
      ? ` ${label} ${factor > 1 ? "up" : "down"} ${Math.abs((factor - 1) * 100).toFixed(1)}%.`
      : "";
  const weatherNote = factorNote("Weather", total.weatherFactor);
  const umpNote = total.umpire ? factorNote(`HP ump ${total.umpire.name}`, total.umpFactor) : "";
  const parkNote = factorNote("Park", total.parkFactor);
  const windNote = total.wind
    ? ` Wind ${Math.abs(total.wind.outMph)} mph ${total.wind.blowing} (${total.windFactor > 1 ? "+" : ""}${((total.windFactor - 1) * 100).toFixed(1)}%).`
    : "";
  const capNote = total.envClamped ? " (env factors capped at ±22% combined)." : "";
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">Game Total — ${sideLabel} ${total.line}</div>
    </div>
    <div class="narrative">Model projects ${total.projection} combined runs (${(total.modelProb * 100).toFixed(0)}% on ${sideLabel.toLowerCase()}); starters + bullpens already baked in.${weatherNote}${parkNote}${windNote}${umpNote}${capNote}</div>
    ${edgeHtml}
  `;
  return card;
}

function renderMoneylineCard(moneyline, game) {
  const card = document.createElement("div");
  card.className = "pick-card";
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">Moneyline</div>
    </div>
    <div class="edge-box">
      <span><strong>${game.away.abbr}</strong></span>
      ${edgeLine(moneyline.away)}
    </div>
    <div class="edge-box">
      <span><strong>${game.home.abbr}</strong></span>
      ${edgeLine(moneyline.home)}
    </div>
  `;
  return card;
}

function renderWinProbBreakdown(gm, game) {
  const away = game.away, home = game.home;
  const f1 = v => v != null ? v.toFixed(1) : "—";

  const recentTag = (season, recent) => {
    if (recent == null) return "";
    const diff = recent - season;
    const sign = diff > 0 ? "+" : "";
    const cls = Math.abs(diff) > 0.3 ? (diff > 0 ? "wpb-hot" : "wpb-cold") : "wpb-neutral";
    return ` <span class="wpb-recent ${cls}">${recent.toFixed(1)} rec</span>`;
  };

  const streakTag = (streak, abbr) => {
    if (!streak || Math.abs(streak) < 2) return "";
    const label = streak > 0 ? `W${streak}` : `L${Math.abs(streak)}`;
    const cls = streak > 0 ? "wpb-streak-w" : "wpb-streak-l";
    return `<span class="wpb-streak ${cls}">${abbr} ${label}</span>`;
  };

  // recentRaTag shows a badge on the opposing staff column when recent RA diverges from season
  const recentRaTag = (staff, recentRa) => {
    if (recentRa == null) return "";
    const diff = recentRa - staff;
    // Higher RA = worse defense, so hot/cold reversed vs offense
    const cls = Math.abs(diff) > 0.3 ? (diff > 0 ? "wpb-cold" : "wpb-hot") : "wpb-neutral";
    return ` <span class="wpb-recent ${cls}">${recentRa.toFixed(1)} rec</span>`;
  };

  const rows = [
    { team: away.abbr, off: gm.awayOffenseRPG, recentOff: gm.awayRecentRPG, staff: gm.homeStaffRA9, recentRa: gm.homeRecentRA, proj: gm.awayProjRuns, hf: false },
    { team: home.abbr, off: gm.homeOffenseRPG, recentOff: gm.homeRecentRPG, staff: gm.awayStaffRA9, recentRa: gm.awayRecentRA, proj: gm.homeProjRuns, hf: true },
  ].map(r => `
    <div class="wpb-row">
      <span class="wpb-team">${r.team}</span>
      <span class="wpb-off">${f1(r.off)} R/G${recentTag(r.off, r.recentOff)}</span>
      <span class="wpb-vs">vs</span>
      <span class="wpb-staff">opp staff ${f1(r.staff)} RA/9${recentRaTag(r.staff, r.recentRa)}</span>
      <span class="wpb-arrow">→</span>
      <span class="wpb-proj">${f1(r.proj)} proj${r.hf ? " <span class='wpb-hf'>+HF</span>" : ""}</span>
    </div>`).join("");

  const awayStreakHtml = streakTag(gm.awayStreak, away.abbr);
  const homeStreakHtml = streakTag(gm.homeStreak, home.abbr);
  const streakRow = (awayStreakHtml || homeStreakHtml)
    ? `<div class="wpb-streaks">${awayStreakHtml}${homeStreakHtml}</div>`
    : "";

  const envNote = gm.envFactor != null && Math.abs(gm.envFactor - 1.0) > 0.01
    ? ` · park/ump ×${gm.envFactor.toFixed(2)}`
    : "";

  const div = document.createElement("div");
  div.className = "win-prob-breakdown";
  div.innerHTML = `
    ${rows}
    ${streakRow}
    <div class="wpb-note">Poisson model · 25% recent/75% season blend (offense &amp; defense) · +0.35 home-field · probs shrunk 25% toward 50%${envNote}</div>
  `;
  return div;
}

function renderF5Card(f5, game) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const sideLabel = f5.side === "over" ? "Over" : "Under";
  const edgeHtml = f5.hasMarket && f5.edge
    ? `<div class="edge-box">${edgeLine(f5.edge)}</div>`
    : `<div class="edge-box"><span>Analysis only — projected first-5 total ${f5.projection} runs.</span></div>`;
  const envNote = f5.envFactor != null && Math.abs(f5.envFactor - 1.0) > 0.01
    ? ` Park/ump ×${f5.envFactor.toFixed(2)} applied.`
    : "";
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">First 5 Innings — ${sideLabel} ${f5.line}</div>
    </div>
    <div class="narrative">Starters-only model: ${f5.projection} runs through 5 (${f5.awayRuns} ${game.away.abbr} / ${f5.homeRuns} ${game.home.abbr}). F5 win: ${game.away.abbr} ${(f5.awayWinProb * 100).toFixed(0)}%, ${game.home.abbr} ${(f5.homeWinProb * 100).toFixed(0)}%, tie ${(f5.tieProb * 100).toFixed(0)}%.${envNote}</div>
    ${edgeHtml}
  `;
  return card;
}

function renderNrfiCard(nrfi) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const edgeHtml = nrfi.hasMarket && nrfi.edge
    ? `<div class="edge-box">${edgeLine(nrfi.edge)}</div>`
    : `<div class="edge-box"><span>Analysis only — no live NRFI line matched.</span></div>`;
  const envNote = nrfi.envFactor != null && Math.abs(nrfi.envFactor - 1.0) > 0.01
    ? ` Park/ump ×${nrfi.envFactor.toFixed(2)} applied.`
    : "";
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">${nrfi.pick}</div>
    </div>
    <div class="narrative">NRFI ${(nrfi.nrfiProb * 100).toFixed(0)}% / YRFI ${(nrfi.yrfiProb * 100).toFixed(0)}%. First-inning scoring chance: away ${(nrfi.pScoreAway * 100).toFixed(0)}%, home ${(nrfi.pScoreHome * 100).toFixed(0)}%.${envNote}</div>
    ${edgeHtml}
  `;
  return card;
}

// ---- NBA rendering ----------------------------------------------------------

function renderNbaAnalysis(data, game, container) {
  container.innerHTML = "";

  if (data.oddsNote) {
    const note = document.createElement("div");
    note.className = "odds-note";
    note.textContent = `⚠ Odds: ${data.oddsNote}`;
    container.appendChild(note);
  }

  const gm = data.gameModel;
  if (!gm) {
    container.innerHTML = '<div class="empty">No model output for this game.</div>';
    return;
  }
  const away = game.away, home = game.home;

  const tpl = document.getElementById("tpl-game-model");
  const node = tpl.content.cloneNode(true);
  const awayWp = node.querySelector(".away-wp");
  awayWp.querySelector(".label").textContent = `${away.abbr} ${(gm.awayWinProb * 100).toFixed(0)}% win`;
  awayWp.querySelector(".bar > span").style.width = `${(gm.awayWinProb * 100).toFixed(0)}%`;
  const homeWp = node.querySelector(".home-wp");
  homeWp.querySelector(".label").textContent = `${home.abbr} ${(gm.homeWinProb * 100).toFixed(0)}% win`;
  homeWp.querySelector(".bar > span").style.width = `${(gm.homeWinProb * 100).toFixed(0)}%`;
  container.appendChild(node);

  container.appendChild(renderNbaScoreCard(gm, away, home));
  if (gm.moneyline) container.appendChild(renderMoneylineCard(gm.moneyline, game));
  if (gm.signals && gm.signals.length) {
    container.appendChild(renderNbaSignals(gm, away, home));
  }

  addToTopBoard(data, game);
  addToBetBoard(data, game);

  if (data.picks && data.picks.length) {
    const heading = document.createElement("div");
    heading.className = "signals-heading";
    heading.style.marginTop = "10px";
    heading.textContent = "Player props";
    container.appendChild(heading);

    const chartList = [];
    for (const pick of data.picks) {
      const { node, canvas } = renderPickCard(pick);
      container.appendChild(node);
      const chart = drawChip(canvas, pick);
      if (chart) chartList.push(chart);
    }
    charts.set(gameKey(game), chartList);
  }
}

function renderNbaScoreCard(gm, away, home) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const sp = gm.modelHomeSpread;
  const spreadTxt = `${home.abbr} ${sp > 0 ? "+" : ""}${sp}`;
  const r = gm.ratings || { home: {}, away: {} };
  const net = (v) => `${v > 0 ? "+" : ""}${v}`;
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">Projected: ${away.abbr} ${gm.awayProjScore} — ${gm.homeProjScore} ${home.abbr}</div>
    </div>
    <div class="nba-lines">
      <span>Spread: <strong>${spreadTxt}</strong></span>
      <span>Total: <strong>${gm.projTotal}</strong></span>
      <span>Pace: ${gm.pace}</span>
    </div>
    <div class="narrative">
      ${away.abbr}: ${r.away.ortg} ORtg / ${r.away.drtg} DRtg (net ${net(r.away.net)}) ·
      ${home.abbr}: ${r.home.ortg} ORtg / ${r.home.drtg} DRtg (net ${net(r.home.net)})
    </div>`;
  return card;
}

function renderNbaSignals(gm, away, home) {
  const favored = gm.homeWinProb >= 0.5 ? "home" : "away";
  const wrap = document.createElement("div");
  wrap.className = "signals-block";
  const heading = document.createElement("div");
  heading.className = "signals-heading";
  heading.textContent = "Signals & discrepancies";
  wrap.appendChild(heading);

  const tagMap = { home: home.abbr, away: away.abbr, over: "OVER", under: "UNDER", neutral: "—" };
  for (const s of gm.signals) {
    let color = "#97a3c4"; // neutral / total leans
    if (s.lean === "home" || s.lean === "away") {
      color = s.lean === favored ? "#3ecf8e" : "#ffcb47"; // agrees w/ projected winner vs leans the dog
    } else if (s.lean === "over" || s.lean === "under") {
      color = "#6ea8fe";
    }
    const row = document.createElement("div");
    row.className = "signal-row";
    row.innerHTML =
      `<span class="signal-dot" style="color:${color}">●</span>` +
      `<span class="signal-label">${s.label}</span>` +
      `<span class="signal-detail">${s.detail}</span>` +
      `<span class="signal-lean" style="color:${color}">${tagMap[s.lean] || s.lean}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

// ---- MMA / UFC rendering ----------------------------------------------------

function renderMmaAnalysis(data, game, container) {
  container.innerHTML = "";

  if (data.oddsNote) {
    const note = document.createElement("div");
    note.className = "odds-note";
    note.textContent = `⚠ Odds: ${data.oddsNote}`;
    container.appendChild(note);
  }

  const fm = data.fightModel;
  if (!fm) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = data.note || "No model output for this fight.";
    container.appendChild(div);
    return;
  }

  // Thin-data banner (one fighter modeled as league-average) — shown above the model.
  if (data.lowData && data.note) {
    const note = document.createElement("div");
    note.className = "odds-note";
    note.textContent = `⚠ ${data.note}`;
    container.appendChild(note);
  }

  // Win-probability bars (away corner = fighter A, home corner = fighter B).
  const tpl = document.getElementById("tpl-game-model");
  const node = tpl.content.cloneNode(true);
  const aWp = node.querySelector(".away-wp");
  aWp.querySelector(".label").textContent = `${fm.aName} ${(fm.aWinProb * 100).toFixed(0)}%`;
  aWp.querySelector(".bar > span").style.width = `${(fm.aWinProb * 100).toFixed(0)}%`;
  const bWp = node.querySelector(".home-wp");
  bWp.querySelector(".label").textContent = `${fm.bName} ${(fm.bWinProb * 100).toFixed(0)}%`;
  bWp.querySelector(".bar > span").style.width = `${(fm.bWinProb * 100).toFixed(0)}%`;
  container.appendChild(node);

  if (fm.pick) container.appendChild(renderMmaPickVerdict(fm.pick));
  if (fm.moneyline) container.appendChild(renderMmaMoneylineCard(fm));
  container.appendChild(renderMmaSummaryCard(fm));
  if (fm.signals && fm.signals.length) container.appendChild(renderMmaSignals(fm));
  if (data.comps) container.appendChild(renderMmaComps(data.comps));

  addToTopBoard(data, game);
  addToBetBoard(data, game);

  // Props (the moneyline is rendered above as its own card, so skip it here).
  const propPicks = (data.picks || []).filter((p) => p.propType !== "mma_moneyline");
  if (propPicks.length) {
    const heading = document.createElement("div");
    heading.className = "signals-heading";
    heading.style.marginTop = "10px";
    heading.textContent = "Props";
    container.appendChild(heading);
    for (const pick of propPicks) {
      const { node: card } = renderPickCard(pick);
      container.appendChild(card);
    }
  }
}

function renderMmaPickVerdict(p) {
  const card = document.createElement("div");
  card.className = "mma-pick mma-pick--" + p.tier.toLowerCase();
  const hist = `${(p.histHitRate * 100).toFixed(0)}%`;
  if (p.coinFlip) {
    card.innerHTML =
      `<div class="mma-pick-label">Coin flip — Pass</div>` +
      `<div class="mma-pick-detail">No confident side (model leans ${p.fighter} just ${p.confidence}%). ` +
      `Picks this close hit only ~${hist} historically — not a play.</div>`;
  } else {
    card.innerHTML =
      `<div class="mma-pick-label">${p.tier} lean · ${p.fighter}</div>` +
      `<div class="mma-pick-detail">${p.confidence}% model confidence · ${p.tier} leans (≥${p.tier === "Strong" ? 70 : 60}%) ` +
      `have hit ~${hist} historically.</div>`;
  }
  return card;
}

function renderMmaMoneylineCard(fm) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const ml = fm.moneyline;
  card.innerHTML = `
    <div class="pick-header"><div class="pick-title">Moneyline</div></div>
    <div class="edge-box"><span><strong>${fm.aName}</strong></span>${edgeLine(ml.a)}</div>
    <div class="edge-box"><span><strong>${fm.bName}</strong></span>${edgeLine(ml.b)}</div>`;
  return card;
}

function renderMmaSummaryCard(fm) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const m = fm.method;
  const rp = fm.roundProbs || {};
  const roundsTxt = Object.keys(rp).filter((k) => k.startsWith("R"))
    .map((k) => `${k} ${(rp[k] * 100).toFixed(0)}%`).join(" · ");
  card.innerHTML = `
    <div class="pick-header"><div class="pick-title">${fm.aName} vs ${fm.bName} (${fm.rounds}R)</div></div>
    <div class="nba-lines">
      <span>KO/TKO <strong>${(m.ko * 100).toFixed(0)}%</strong></span>
      <span>Sub <strong>${(m.sub * 100).toFixed(0)}%</strong></span>
      <span>Decision <strong>${(m.decision * 100).toFixed(0)}%</strong></span>
      <span>Goes distance ${(fm.distanceProb * 100).toFixed(0)}%</span>
    </div>
    <div class="narrative">Finish by round: ${roundsTxt} · decision ${(rp.decision * 100).toFixed(0)}%.
      Projected sig. strikes: ${fm.aName} ${fm.projSigStrikes.a} / ${fm.bName} ${fm.projSigStrikes.b}
      (total ${fm.projSigStrikes.total}) over ~${fm.expMinutes} min.</div>`;
  return card;
}

function renderMmaSignals(fm) {
  const favored = fm.aWinProb >= 0.5 ? "a" : "b";
  const wrap = document.createElement("div");
  wrap.className = "signals-block";
  const heading = document.createElement("div");
  heading.className = "signals-heading";
  heading.textContent = "Signals & discrepancies";
  wrap.appendChild(heading);

  const tagMap = { a: fm.aName.split(" ").pop(), b: fm.bName.split(" ").pop(),
                   over: "OVER", under: "UNDER", neutral: "—" };
  for (const s of fm.signals) {
    let color = "#97a3c4";
    if (s.lean === "a" || s.lean === "b") color = s.lean === favored ? "#3ecf8e" : "#ffcb47";
    else if (s.lean === "over" || s.lean === "under") color = "#6ea8fe";
    const row = document.createElement("div");
    row.className = "signal-row";
    row.innerHTML =
      `<span class="signal-dot" style="color:${color}">●</span>` +
      `<span class="signal-label">${s.label}</span>` +
      `<span class="signal-detail">${s.detail}</span>` +
      `<span class="signal-lean" style="color:${color}">${tagMap[s.lean] || s.lean}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

function renderMmaComps(c) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const m = c.method;
  const rows = c.similar.map((s) =>
    `<div class="signal-row"><span class="signal-label">${s.fav} vs ${s.dog}</span>` +
    `<span class="signal-detail">${s.date.slice(0, 7)} · ${s.result}</span>` +
    `<span class="signal-lean">d ${s.dist}</span></div>`).join("");
  card.innerHTML = `
    <div class="pick-header"><div class="pick-title">Historical comps — ${c.n} most-similar past fights</div></div>
    <div class="nba-lines">
      <span>${c.favorite} (fav) won <strong>${(c.favWinPct * 100).toFixed(0)}%</strong> of comps</span>
      <span>KO ${(m.ko * 100).toFixed(0)}% · Sub ${(m.sub * 100).toFixed(0)}% · Dec ${(m.dec * 100).toFixed(0)}%</span>
      <span>Distance ${(c.distancePct * 100).toFixed(0)}%</span>
      <span>~${c.avgSigStrikes} sig strikes</span>
    </div>
    <div class="narrative">How the most comparable style-matchups actually played out
      (empirical, point-in-time). A second lens to weigh against the model above.</div>
    <div class="signals-block" style="margin-top:6px;">${rows}</div>`;
  return card;
}

// Discrepancy signals: each input behind the model number, tagged by which
// side it leans, so the user can see where the evidence agrees or conflicts
// with the pick (and form their own read) rather than just trusting confidence.
function renderSignals(pick) {
  const wrap = document.createElement("div");
  wrap.className = "signals-block";

  const heading = document.createElement("div");
  heading.className = "signals-heading";
  heading.textContent = "Signals & discrepancies";
  wrap.appendChild(heading);

  for (const s of pick.signals) {
    const agree = s.lean === pick.side;
    const disagree = s.lean !== "neutral" && s.lean !== pick.side;
    const color = agree ? "#3ecf8e" : disagree ? "#ffcb47" : "#97a3c4";
    const tag = s.lean === "neutral" ? "neutral" : `leans ${s.lean}`;

    const row = document.createElement("div");
    row.className = "signal-row";
    row.innerHTML =
      `<span class="signal-dot" style="color:${color}">●</span>` +
      `<span class="signal-label">${s.label}</span>` +
      `<span class="signal-detail">${s.detail}</span>` +
      `<span class="signal-lean" style="color:${color}">${tag}${disagree ? " ⚠" : ""}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

function renderPickCard(pick) {
  const tpl = document.getElementById("tpl-pick-card");
  const node = tpl.content.cloneNode(true);

  node.querySelector(".pick-title").textContent =
    `${pick.pick} — ${pick.confidence}% confidence`;

  const tier = node.querySelector(".tier");
  tier.textContent = pick.tier;
  tier.classList.add(pick.tier);

  const splitsEl = node.querySelector(".splits");
  for (const s of pick.splits) {
    const span = document.createElement("span");
    span.className = "split" + (s.thin ? " split--thin" : "");
    span.textContent = `${s.label}: ${s.hits}/${s.n} (${(s.rate * 100).toFixed(0)}%)`;
    splitsEl.appendChild(span);
  }
  function addChip(text) {
    const span = document.createElement("span");
    span.className = "split";
    span.textContent = text;
    splitsEl.appendChild(span);
  }

  if (pick.platoon) {
    const pl = pick.platoon;
    addChip(
      `Platoon: vs LHB ${(pl.vsLHB * 100).toFixed(1)}% K, vs RHB ${(pl.vsRHB * 100).toFixed(1)}% K ` +
      `· opp ~${(pl.oppLHBPct * 100).toFixed(0)}% LHB (×${pl.factor})`
    );
  }
  if (pick.skill) {
    const sk = pick.skill;
    const whiff = sk.swStrPct != null ? `, ${(sk.swStrPct * 100).toFixed(1)}% whiff` : "";
    addChip(`Statcast: ${(sk.kPct * 100).toFixed(1)}% K${whiff} · blends ${sk.resultsProj}→${sk.blended}`);
  }
  if (pick.umpire && pick.umpire.factor) {
    addChip(`HP ump ${pick.umpire.name}: ×${pick.umpire.factor}`);
  }
  if (pick.lineupConfirmed === true) {
    addChip("Confirmed lineup");
  } else if (pick.lineupConfirmed === false) {
    addChip("Projected lineup (last game's order — not yet confirmed)");
  }

  node.querySelector(".narrative").textContent = pick.narrative || "";

  const edgeBox = node.querySelector(".edge-box");
  if (pick.signals && pick.signals.length) {
    edgeBox.parentNode.insertBefore(renderSignals(pick), edgeBox);
  }

  if (pick.hasMarket && pick.edge) {
    edgeBox.style.display = "flex";
    edgeBox.innerHTML = edgeLine(pick.edge);
  } else {
    edgeBox.style.display = "flex";
    edgeBox.innerHTML = `<span>Analysis only — no live line matched. Projection ${pick.projection} ${pick.statNoun || ""}.</span>`;
  }

  const canvas = node.querySelector("canvas");
  if (!pick.spark || !pick.spark.length) {
    const wrap = node.querySelector(".chip-wrap");
    if (wrap) wrap.style.display = "none";
  }
  return { node, canvas };
}

// ---- scorecard chip ----------------------------------------------------------

function drawChip(canvas, pick) {
  if (!pick.spark || !pick.spark.length) return null;

  const labels = pick.spark.map((s) => s.opp + (s.home ? "" : " (a)"));
  const values = pick.spark.map((s) => s.k);
  const line = pick.line;

  const colors = values.map((v) => {
    const overHits = v > line;
    if (pick.side === "over") return overHits ? "#3ecf8e" : "#3a4566";
    return overHits ? "#3a4566" : "#3ecf8e";
  });

  return new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
          borderRadius: 3,
          barPercentage: 0.7,
        },
        {
          type: "line",
          data: labels.map(() => line),
          borderColor: "#ffcb47",
          borderDash: [4, 4],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: {
        x: { ticks: { color: "#97a3c4", font: { size: 9 } }, grid: { display: false } },
        y: { ticks: { color: "#97a3c4", font: { size: 9 } }, grid: { color: "#25304f" }, beginAtZero: true },
      },
    },
  });
}

// ---- top board ----------------------------------------------------------------

function addToTopBoard(data, game) {
  const key = gameKey(game);
  // On refresh, drop this game's previous entries before re-adding.
  for (const el of Array.from(topBoardList.children)) {
    if (el.dataset.gamePk === String(key)) el.remove();
  }
  const picks = boardPicks(data);
  if (!picks.length) return;
  topBoardSection.style.display = "block";
  const matchup = matchupLabel(game);

  for (const pick of picks) {
    const item = document.createElement("div");
    item.className = "top-board-item";

    const evPct = pick.hasMarket && pick.edge ? pick.edge.evPct : null;
    const sortKey = evPct !== null ? evPct : pick.confidence;

    item.dataset.sortKey = sortKey;
    item.dataset.gamePk = key;
    const evLabel =
      evPct !== null
        ? `<span class="${evPct > 0 ? "ev-pos" : "ev-neg"}">${evPct > 0 ? "+" : ""}${evPct.toFixed(1)}% EV</span>`
        : `<span>${pick.confidence}% conf</span>`;

    item.innerHTML = `
      <div class="tb-pick">${pick.pick}</div>
      <div class="tb-meta">
        <span>${matchup} · ${pick.tier}</span>
        ${evLabel}
      </div>
    `;

    item.addEventListener("click", () => {
      const card = document.querySelector(`.game-card[data-game-pk="${key}"]`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    topBoardList.appendChild(item);
  }

  // Keep the board sorted by EV (or confidence) descending.
  const items = Array.from(topBoardList.children);
  items.sort((a, b) => parseFloat(b.dataset.sortKey) - parseFloat(a.dataset.sortKey));
  items.forEach((el) => topBoardList.appendChild(el));
}

// ---- bet board sidebar ------------------------------------------------------

// Single source of truth for a game's bettable picks (prop/moneyline picks +,
// for MLB, the game-model markets). Reused by the bet board and the card badge.
function collectBets(data, game) {
  const added = [];

  for (const pick of boardPicks(data)) {
    const evPct = pick.hasMarket && pick.edge ? pick.edge.evPct : null;
    added.push({ pick, game, evPct, tier: pick.tier, type: propTypeLabel(pick.propType) });
  }

  const gm = data.gameModel;
  if (gm) {
    if (gm.moneyline) {
      for (const side of ["away", "home"]) {
        const m = gm.moneyline[side];
        if (!m) continue;
        added.push({
          pick: {
            pick: `${game[side].abbr} ML (${m.price > 0 ? "+" : ""}${m.price})`,
            confidence: Math.round(m.modelProb * 100),
          },
          game, evPct: m.evPct, tier: "Strong", type: "Moneyline",
        });
      }
    }
    if (gm.total && gm.total.hasMarket) {
      added.push({
        pick: { pick: gm.total.pick, confidence: Math.round(gm.total.modelProb * 100) },
        game, evPct: gm.total.edge.evPct, tier: "Strong", type: "Total",
      });
    }
    if (gm.f5 && gm.f5.hasMarket) {
      added.push({
        pick: { pick: gm.f5.pick, confidence: Math.round(gm.f5.modelProb * 100) },
        game, evPct: gm.f5.edge.evPct, tier: "Strong", type: "First 5",
      });
    }
    if (gm.nrfi && gm.nrfi.hasMarket) {
      added.push({
        pick: { pick: gm.nrfi.pick, confidence: Math.round(gm.nrfi.modelProb * 100) },
        game, evPct: gm.nrfi.edge.evPct, tier: "Strong", type: "NRFI/YRFI",
      });
    }
  }
  return added;
}

function addToBetBoard(data, game) {
  const key = gameKey(game);
  // On refresh, drop this game's previous entries before re-adding.
  betItems = betItems.filter((it) => gameKey(it.game) !== key);
  const added = collectBets(data, game);
  betItems.push(...added);

  for (const item of added) {
    if (!knownBetTypes.has(item.type)) {
      knownBetTypes.add(item.type);
      activeBetTypes.add(item.type);
    }
  }

  betItems.sort((a, b) => {
    const aKey = a.evPct !== null ? a.evPct : a.pick.confidence;
    const bKey = b.evPct !== null ? b.evPct : b.pick.confidence;
    return bKey - aKey;
  });

  renderBetBoard();
}

function renderBetBoard() {
  // Filter chips for tiers seen so far.
  const tiersSeen = BET_TIERS.filter((t) => betItems.some((i) => i.tier === t));
  betFilters.innerHTML = "";
  for (const tier of tiersSeen) {
    const chip = document.createElement("button");
    chip.className = "bet-filter" + (activeBetTiers.has(tier) ? "" : " off");
    chip.textContent = tier;
    chip.addEventListener("click", () => {
      if (activeBetTiers.has(tier)) activeBetTiers.delete(tier);
      else activeBetTiers.add(tier);
      renderBetBoard();
    });
    betFilters.appendChild(chip);
  }

  // Filter chips for bet types seen so far (ML, Total, Strikeouts, Hits, ...).
  const typesSeen = Array.from(knownBetTypes).filter((t) => betItems.some((i) => i.type === t));
  for (const type of typesSeen) {
    const chip = document.createElement("button");
    chip.className = "bet-filter" + (activeBetTypes.has(type) ? "" : " off");
    chip.textContent = type;
    chip.addEventListener("click", () => {
      if (activeBetTypes.has(type)) activeBetTypes.delete(type);
      else activeBetTypes.add(type);
      renderBetBoard();
    });
    betFilters.appendChild(chip);
  }

  const evOnly = betEvOnly.checked;
  const visible = betItems.filter((item) => {
    if (!activeBetTiers.has(item.tier)) return false;
    if (!activeBetTypes.has(item.type)) return false;
    if (evOnly && !(item.evPct > 0)) return false;
    return true;
  });

  betCount.textContent = `${visible.length} bet${visible.length === 1 ? "" : "s"}`;

  betList.innerHTML = "";
  if (!visible.length) {
    betList.innerHTML = '<div class="empty">Analyze games to populate the board.</div>';
    return;
  }

  for (const item of visible) {
    const { pick, game, evPct, tier, type } = item;
    const el = document.createElement("div");
    el.className = "bet-item";

    const evLabel =
      evPct !== null
        ? `<span class="${evPct > 0 ? "ev-pos" : "ev-neg"}">${evPct > 0 ? "+" : ""}${evPct.toFixed(1)}% EV</span>`
        : `<span>${pick.confidence}% conf</span>`;

    el.innerHTML = `
      <div class="bet-item-top">
        <span class="bet-cat">${type} · ${tier}</span>
        ${evLabel}
      </div>
      <div class="bet-label">${pick.pick}</div>
      <div class="bet-detail">${matchupLabel(game)}</div>
    `;

    el.addEventListener("click", () => {
      const card = document.querySelector(`.game-card[data-game-pk="${gameKey(game)}"]`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    betList.appendChild(el);
  }
}

// ---- init ------------------------------------------------------------------

dateInput.value = todayISO();
loadBtn.addEventListener("click", () => loadSlate(dateInput.value));
document.getElementById("analyze-all-btn").addEventListener("click", analyzeAll);

const slateView = document.getElementById("slate-view");
const historyView = document.getElementById("history-view");
const historyTab = document.getElementById("history-tab");
let historyMode = false;

function showSlateView() {
  historyMode = false;
  slateView.style.display = "";
  historyView.style.display = "none";
  dateInput.style.display = "";
  loadBtn.style.display = "";
}

function showHistoryView() {
  historyMode = true;
  slateView.style.display = "none";
  historyView.style.display = "";
  dateInput.style.display = "none";
  loadBtn.style.display = "none";
  document.querySelectorAll(".sport-tab").forEach((t) => t.classList.remove("active"));
  historyTab.classList.add("active");
  loadHistory();
}

// Sport tabs (MLB / NBA / UFC / History): switch view or sport.
document.querySelectorAll(".sport-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab === historyTab) {
      if (!historyMode) showHistoryView();
      return;
    }
    if (tab.dataset.sport === currentSport && !historyMode) return;
    showSlateView();
    currentSport = tab.dataset.sport;
    setBrandSport(currentSport);
    document.querySelectorAll(".sport-tab").forEach((t) => t.classList.toggle("active", t === tab));
    loadSlate(dateInput.value);
  });
});

// Pull flags on load so the pills reflect server config even before a search.
fetch("/api/health", { headers: apiHeaders() })
  .then((r) => r.json())
  .then((d) => setFlags(d.flags || {}))
  .catch(() => {});

betSidebarClose.addEventListener("click", () => betSidebar.classList.remove("open"));
betSidebarOpen.addEventListener("click", () => betSidebar.classList.add("open"));
document.getElementById("board-toggle").addEventListener("click", () => betSidebar.classList.toggle("open"));

// Click a pick card's header to expand/collapse its details (splits, chart,
// narrative). Keeps long analyses from blowing up page length.
document.addEventListener("click", (e) => {
  const header = e.target.closest(".pick-card .pick-header");
  if (!header) return;
  header.closest(".pick-card").classList.toggle("expanded");
});
betEvOnly.addEventListener("change", renderBetBoard);

loadSlate(dateInput.value);
