// Sharp Slate frontend — fetches the API, renders game cards, picks, and the
// Top Board. No framework, no build step, no browser storage.

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
let betItems = []; // { pick, game, evPct, tier }
let activeBetTiers = new Set(BET_TIERS);

let currentSport = "mlb"; // "mlb" | "nba"

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

async function loadSlate(date) {
  slateContainer.innerHTML = '<div class="loading">Loading slate…</div>';
  topBoardSection.style.display = "none";
  topBoardList.innerHTML = "";
  betItems = [];
  renderBetBoard();
  charts.forEach((list) => list.forEach((c) => c.destroy()));
  charts.clear();

  let data;
  try {
    const res = await fetch(`/api/slate?date=${encodeURIComponent(date)}&sport=${currentSport}`);
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
  const btn = card.querySelector(".analyze-btn");
  btn.addEventListener("click", () => {
    if (analysisEl.classList.contains("open")) {
      analysisEl.classList.remove("open");
      btn.textContent = "Analyze";
      return;
    }
    btn.textContent = "Hide";
    analysisEl.classList.add("open");
    if (!analysisEl.dataset.loaded) {
      loadAnalysis(game, date, analysisEl, btn);
    }
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

async function loadAnalysis(game, date, container, btn) {
  container.innerHTML = '<div class="loading">Crunching the numbers…</div>';
  try {
    const res = await fetch(
      `/api/analyze/${gameKey(game)}?date=${encodeURIComponent(date)}&sport=${currentSport}&ai=0`);
    if (!res.ok) throw new Error("bad response");
    const data = await res.json();
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
  } catch (e) {
    container.innerHTML = '<div class="error">Could not load analysis for this game.</div>';
    btn.textContent = "Analyze";
    container.classList.remove("open");
  }
}

function renderAnalysis(data, game, container) {
  container.innerHTML = "";

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
    empty.textContent = "No graded picks for this game (not enough recent starts).";
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
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">Game Total — ${sideLabel} ${total.line}</div>
    </div>
    <div class="narrative">Model projects ${total.projection} combined runs (${(total.modelProb * 100).toFixed(0)}% on ${sideLabel.toLowerCase()}); starters + bullpens already baked in.${weatherNote}${parkNote}${windNote}${umpNote}</div>
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

function renderF5Card(f5, game) {
  const card = document.createElement("div");
  card.className = "pick-card";
  const sideLabel = f5.side === "over" ? "Over" : "Under";
  const edgeHtml = f5.hasMarket && f5.edge
    ? `<div class="edge-box">${edgeLine(f5.edge)}</div>`
    : `<div class="edge-box"><span>Analysis only — projected first-5 total ${f5.projection} runs.</span></div>`;
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">First 5 Innings — ${sideLabel} ${f5.line}</div>
    </div>
    <div class="narrative">Starters-only model: ${f5.projection} runs through 5 (${f5.awayRuns} ${game.away.abbr} / ${f5.homeRuns} ${game.home.abbr}). F5 win: ${game.away.abbr} ${(f5.awayWinProb * 100).toFixed(0)}%, ${game.home.abbr} ${(f5.homeWinProb * 100).toFixed(0)}%, tie ${(f5.tieProb * 100).toFixed(0)}%.</div>
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
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">${nrfi.pick}</div>
    </div>
    <div class="narrative">NRFI ${(nrfi.nrfiProb * 100).toFixed(0)}% / YRFI ${(nrfi.yrfiProb * 100).toFixed(0)}%. First-inning scoring chance: away ${(nrfi.pScoreAway * 100).toFixed(0)}%, home ${(nrfi.pScoreHome * 100).toFixed(0)}%.</div>
    ${edgeHtml}
  `;
  return card;
}

// ---- NBA rendering ----------------------------------------------------------

function renderNbaAnalysis(data, game, container) {
  container.innerHTML = "";
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
  if (gm.signals && gm.signals.length) {
    container.appendChild(renderNbaSignals(gm, away, home));
  }

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
  const fm = data.fightModel;
  if (!fm) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = data.note || "No model output for this fight.";
    container.appendChild(div);
    return;
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

  container.appendChild(renderMmaSummaryCard(fm));
  if (fm.signals && fm.signals.length) container.appendChild(renderMmaSignals(fm));
  if (data.comps) container.appendChild(renderMmaComps(data.comps));

  if (data.picks && data.picks.length) {
    const heading = document.createElement("div");
    heading.className = "signals-heading";
    heading.style.marginTop = "10px";
    heading.textContent = "Props";
    container.appendChild(heading);
    for (const pick of data.picks) {
      const { node: card } = renderPickCard(pick);
      container.appendChild(card);
    }
  }
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
  if (pick.lineupConfirmed) {
    addChip("Confirmed lineup");
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
  if (!data.picks || !data.picks.length) return;
  topBoardSection.style.display = "block";

  for (const pick of data.picks) {
    const item = document.createElement("div");
    item.className = "top-board-item";

    const evPct = pick.hasMarket && pick.edge ? pick.edge.evPct : null;
    const sortKey = evPct !== null ? evPct : pick.confidence;

    item.dataset.sortKey = sortKey;
    const evLabel =
      evPct !== null
        ? `<span class="${evPct > 0 ? "ev-pos" : "ev-neg"}">${evPct > 0 ? "+" : ""}${evPct.toFixed(1)}% EV</span>`
        : `<span>${pick.confidence}% conf</span>`;

    item.innerHTML = `
      <div class="tb-pick">${pick.pick}</div>
      <div class="tb-meta">
        <span>${game.away.abbr} @ ${game.home.abbr} · ${pick.tier}</span>
        ${evLabel}
      </div>
    `;

    item.addEventListener("click", () => {
      const card = document.querySelector(`.game-card[data-game-pk="${game.gamePk}"]`);
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

function addToBetBoard(data, game) {
  if (!data.picks || !data.picks.length) return;

  for (const pick of data.picks) {
    const evPct = pick.hasMarket && pick.edge ? pick.edge.evPct : null;
    betItems.push({ pick, game, evPct, tier: pick.tier });
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

  const evOnly = betEvOnly.checked;
  const visible = betItems.filter((item) => {
    if (!activeBetTiers.has(item.tier)) return false;
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
    const { pick, game, evPct, tier } = item;
    const el = document.createElement("div");
    el.className = "bet-item";

    const evLabel =
      evPct !== null
        ? `<span class="${evPct > 0 ? "ev-pos" : "ev-neg"}">${evPct > 0 ? "+" : ""}${evPct.toFixed(1)}% EV</span>`
        : `<span>${pick.confidence}% conf</span>`;

    el.innerHTML = `
      <div class="bet-item-top">
        <span class="bet-cat">${tier}</span>
        ${evLabel}
      </div>
      <div class="bet-label">${pick.pick}</div>
      <div class="bet-detail">${game.away.abbr} @ ${game.home.abbr}</div>
    `;

    el.addEventListener("click", () => {
      const card = document.querySelector(`.game-card[data-game-pk="${game.gamePk}"]`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    betList.appendChild(el);
  }
}

// ---- init ------------------------------------------------------------------

dateInput.value = todayISO();
loadBtn.addEventListener("click", () => loadSlate(dateInput.value));

// Sport tabs (MLB / NBA): switch the active sport and reload the slate.
document.querySelectorAll(".sport-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.dataset.sport === currentSport) return;
    currentSport = tab.dataset.sport;
    document.querySelectorAll(".sport-tab").forEach((t) => t.classList.toggle("active", t === tab));
    loadSlate(dateInput.value);
  });
});

// Pull flags on load so the pills reflect server config even before a search.
fetch("/api/health")
  .then((r) => r.json())
  .then((d) => setFlags(d.flags || {}))
  .catch(() => {});

betSidebarClose.addEventListener("click", () => betSidebar.classList.remove("open"));
betSidebarOpen.addEventListener("click", () => betSidebar.classList.add("open"));
document.getElementById("board-toggle").addEventListener("click", () => betSidebar.classList.toggle("open"));
betEvOnly.addEventListener("change", renderBetBoard);

loadSlate(dateInput.value);
