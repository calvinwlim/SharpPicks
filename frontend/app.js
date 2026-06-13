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
  charts.forEach((list) => list.forEach((c) => c.destroy()));
  charts.clear();

  let data;
  try {
    const res = await fetch(`/api/slate?date=${encodeURIComponent(date)}`);
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
  card.dataset.gamePk = game.gamePk;

  card.querySelector(".venue").textContent = game.venue || "";
  card.querySelector(".time").textContent =
    `${fmtTime(game.gameDate)} · ${game.dayNight === "night" ? "Night" : "Day"}`;

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
  const pp = team.probablePitcher;
  el.querySelector(".pitcher").textContent = pp ? pp.name : "TBD";
}

// ---- analysis ---------------------------------------------------------------

async function loadAnalysis(game, date, container, btn) {
  container.innerHTML = '<div class="loading">Crunching the numbers…</div>';
  try {
    const res = await fetch(`/api/analyze/${game.gamePk}?date=${encodeURIComponent(date)}&ai=0`);
    if (!res.ok) throw new Error("bad response");
    const data = await res.json();
    container.dataset.loaded = "1";
    renderAnalysis(data, game, container);
    addToTopBoard(data, game);
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
  const bullpenNote = factorNote("Bullpens", total.bullpenFactor);
  const parkNote = factorNote("Park", total.parkFactor);
  const windNote = total.wind
    ? ` Wind ${Math.abs(total.wind.outMph)} mph ${total.wind.blowing} (${total.windFactor > 1 ? "+" : ""}${((total.windFactor - 1) * 100).toFixed(1)}%).`
    : "";
  card.innerHTML = `
    <div class="pick-header">
      <div class="pick-title">Game Total — ${sideLabel} ${total.line}</div>
    </div>
    <div class="narrative">Model projects ${total.projection} combined runs (${(total.modelProb * 100).toFixed(0)}% on ${sideLabel.toLowerCase()}).${weatherNote}${parkNote}${windNote}${umpNote}${bullpenNote}</div>
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
  if (pick.hasMarket && pick.edge) {
    edgeBox.style.display = "flex";
    edgeBox.innerHTML = edgeLine(pick.edge);
  } else {
    edgeBox.style.display = "flex";
    edgeBox.innerHTML = `<span>Analysis only — no live line matched. Projection ${pick.projection} ${pick.statNoun || ""}.</span>`;
  }

  const canvas = node.querySelector("canvas");
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

// ---- init ------------------------------------------------------------------

dateInput.value = todayISO();
loadBtn.addEventListener("click", () => loadSlate(dateInput.value));

// Pull flags on load so the pills reflect server config even before a search.
fetch("/api/health")
  .then((r) => r.json())
  .then((d) => setFlags(d.flags || {}))
  .catch(() => {});

loadSlate(dateInput.value);
