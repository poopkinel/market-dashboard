// Dashboard logic: calls the FastAPI routes and fills in the page.
// All text from the server is inserted with textContent, never innerHTML.

const $ = (id) => document.getElementById(id);
const num = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const price = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 8 });

let currentJob = null;   // the job whose results are shown
let pollTimer = null;

// ---------- helpers ----------

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
    throw new Error(`${response.status}: ${detail}`);
  }
  return body;
}

function setStatus(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function cell(row, text, className) {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) td.className = className;
  row.appendChild(td);
  return td;
}

function fmt(value, suffix = "") {
  return value === null || value === undefined ? "n/a" : num.format(value) + suffix;
}

function timeLabel(ms, withTime = true) {
  const d = new Date(ms);
  return withTime
    ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ---------- 1. prices ----------

async function loadPrices() {
  const source = $("price-source").value;
  setStatus($("price-status"), "Loading…");
  try {
    const data = await api(`/api/prices?source=${encodeURIComponent(source)}`);
    const tbody = $("price-table").querySelector("tbody");
    tbody.replaceChildren();
    for (const p of data.prices) {
      const row = document.createElement("tr");
      cell(row, p.symbol);
      cell(row, price.format(p.price), "num");
      cell(row, p.currency.toUpperCase());
      cell(row, p.source);
      tbody.appendChild(row);
    }
    $("price-table").hidden = data.prices.length === 0;
    setStatus($("price-status"), `Updated ${new Date().toLocaleTimeString()}`);
  } catch (err) {
    setStatus($("price-status"), `Could not load prices. ${err.message}`, true);
  }
}

// ---------- 2. analysis jobs ----------

async function startJob(event) {
  event.preventDefault();
  const body = {
    symbol: $("job-symbol").value.trim(),
    interval: $("job-interval").value,
    days: Number($("job-days").value),
    source: "binance",
  };
  $("job-start").disabled = true;
  setStatus($("job-status"), "Starting…");
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(body) });
    watchJob(job.id);
  } catch (err) {
    setStatus($("job-status"), `Could not start the analysis. ${err.message}`, true);
    $("job-start").disabled = false;
  }
}

// Ask the server about the job every second until it is done or failed.
function watchJob(jobId) {
  clearInterval(pollTimer);
  const check = async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      if (job.status === "pending" || job.status === "running") {
        setStatus($("job-status"),
          `${job.params.symbol}: ${job.status}… ${num.format(job.rows_processed)} rows processed`);
        return;
      }
      clearInterval(pollTimer);
      $("job-start").disabled = false;
      loadJobs();
      if (job.status === "done") {
        showJob(job);
      } else {
        setStatus($("job-status"), `${job.params.symbol}: failed. ${job.error}`, true);
      }
    } catch (err) {
      clearInterval(pollTimer);
      $("job-start").disabled = false;
      setStatus($("job-status"), `Lost track of the job. ${err.message}`, true);
    }
  };
  check();
  pollTimer = setInterval(check, 1000);
}

function showJob(job) {
  currentJob = job;
  const r = job.result;
  const p = job.params;
  setStatus($("job-status"),
    `${p.symbol}/${p.currency.toUpperCase()}, ${p.interval} candles, last ${p.days} days: ` +
    `${num.format(r.rows)} rows processed. Saved to ${job.result_file}.`);

  const tiles = [
    ["Last close", fmt(r.last_close)],
    ["Change", fmt(r.change_pct, "%"), r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : ""],
    ["High", fmt(r.high)],
    ["Low", fmt(r.low)],
    ["Volatility", fmt(r.volatility_pct, "%")],
    ["Max drawdown", fmt(r.max_drawdown_pct, "%")],
    ["Trend (SMA 20 vs 50)", r.trend || "n/a"],
  ];
  const box = $("stat-tiles");
  box.replaceChildren();
  for (const [label, value, cls] of tiles) {
    const tile = document.createElement("div");
    tile.className = "tile";
    const l = document.createElement("div");
    l.className = "label";
    l.textContent = label;
    const v = document.createElement("div");
    v.className = "value" + (cls ? ` ${cls}` : "");
    v.textContent = (cls === "up" ? "▲ " : cls === "down" ? "▼ " : "") + value;
    tile.append(l, v);
    box.appendChild(tile);
  }

  $("chart-title").textContent = `${p.symbol} close price (${p.currency.toUpperCase()})`;
  drawChart($("chart"), r.series);

  const tbody = $("series-table").querySelector("tbody");
  tbody.replaceChildren();
  for (const point of r.series) {
    const row = document.createElement("tr");
    cell(row, timeLabel(point.t));
    cell(row, price.format(point.close), "num");
    tbody.appendChild(row);
  }

  $("job-results").hidden = false;
  $("ai-job").disabled = false;
}

async function loadJobs() {
  try {
    const data = await api("/api/jobs");
    const tbody = $("jobs-table").querySelector("tbody");
    tbody.replaceChildren();
    for (const job of data.jobs.slice(0, 20)) {
      const row = document.createElement("tr");
      cell(row, new Date(job.created_at * 1000).toLocaleTimeString());
      cell(row, job.params.symbol);
      cell(row, job.params.interval);
      cell(row, job.params.days, "num");
      cell(row, job.status);
      cell(row, num.format(job.rows_processed), "num");
      const actions = cell(row, "");
      if (job.status === "done") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "Show";
        button.addEventListener("click", async () => showJob(await api(`/api/jobs/${job.id}`)));
        actions.appendChild(button);
      } else if (job.status === "failed") {
        actions.textContent = job.error;
        actions.className = "muted small";
      }
      tbody.appendChild(row);
    }
  } catch (err) {
    console.error(err);
  }
}

// ---------- chart: a single-series line with a crosshair tooltip ----------

// AI-assisted: drafted with an AI assistant for this reference solution.
// In your own project, say here what Copilot suggested and what you changed or checked.
// Pattern: an SVG line chart with a crosshair that snaps to the nearest point.
function drawChart(container, series) {
  container.replaceChildren();
  if (!series || series.length < 2) {
    container.textContent = "Not enough data to draw a chart.";
    return;
  }
  const W = 960, H = 300, left = 70, right = 12, top = 10, bottom = 28;
  const xs = series.map((p) => p.t), ys = series.map((p) => p.close);
  const xMin = xs[0], xMax = xs[xs.length - 1];
  let yMin = Math.min(...ys), yMax = Math.max(...ys);
  const pad = (yMax - yMin) * 0.05 || yMax * 0.01 || 1;
  yMin -= pad; yMax += pad;
  const x = (t) => left + ((t - xMin) / (xMax - xMin)) * (W - left - right);
  const y = (v) => top + (1 - (v - yMin) / (yMax - yMin)) * (H - top - bottom);

  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs, text) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Line chart of ${series.length} close prices from ${timeLabel(xMin)} to ${timeLabel(xMax)}` });

  // Horizontal gridlines with price labels, with decimals only when the prices are small.
  const range = yMax - yMin;
  const decimals = range >= 50 ? 0 : range >= 1 ? 2 : 4;
  const axisNum = new Intl.NumberFormat(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (range * i) / 4;
    svg.appendChild(el("line", { x1: left, x2: W - right, y1: y(v), y2: y(v), class: i === 0 ? "baseline" : "grid" }));
    svg.appendChild(el("text", { x: left - 8, y: y(v) + 4, "text-anchor": "end", class: "axis-label" }, axisNum.format(v)));
  }
  // Date labels at the start, middle and end.
  const spanDays = (xMax - xMin) / 86400000;
  [0, Math.floor(series.length / 2), series.length - 1].forEach((i, k) => {
    svg.appendChild(el("text", { x: x(xs[i]), y: H - 6, class: "axis-label",
      "text-anchor": ["start", "middle", "end"][k] }, timeLabel(xs[i], spanDays < 3)));
  });

  svg.appendChild(el("path", { class: "line",
    d: series.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.close).toFixed(1)}`).join("") }));

  // Crosshair: a hairline that snaps to the nearest point, with a tooltip.
  const cross = el("line", { class: "crosshair", y1: top, y2: H - bottom, visibility: "hidden" });
  const dot = el("circle", { class: "dot", r: 5, visibility: "hidden" });
  const hit = el("rect", { x: left, y: top, width: W - left - right, height: H - top - bottom, fill: "transparent" });
  svg.append(cross, dot, hit);
  container.appendChild(svg);

  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.hidden = true;
  const tipValue = document.createElement("strong");
  const tipTime = document.createElement("span");
  tip.append(tipValue, tipTime);
  container.appendChild(tip);

  const show = (clientX) => {
    const box = svg.getBoundingClientRect();
    const svgX = ((clientX - box.left) / box.width) * W;
    const t = xMin + ((svgX - left) / (W - left - right)) * (xMax - xMin);
    let i = 0;
    for (let k = 1; k < xs.length; k++) if (Math.abs(xs[k] - t) < Math.abs(xs[i] - t)) i = k;
    const px = x(xs[i]), py = y(ys[i]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("visibility", "visible");
    tipValue.textContent = price.format(ys[i]);
    tipTime.textContent = timeLabel(xs[i]);
    tip.hidden = false;
    const scale = box.width / W;
    const tipLeft = Math.min(px * scale + 12, box.width - tip.offsetWidth - 4);
    tip.style.left = `${Math.max(0, tipLeft)}px`;
    tip.style.top = `${Math.max(0, py * scale - tip.offsetHeight - 10)}px`;
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    tip.hidden = true;
  };
  hit.addEventListener("pointermove", (e) => show(e.clientX));
  hit.addEventListener("pointerleave", hide);
}

// ---------- 3. AI insight ----------

async function askAI(body) {
  setStatus($("ai-status"), "Asking the local model… this can take a while on the first call.");
  $("ai-result").hidden = true;
  $("ai-job").disabled = true;
  $("ai-text-button").disabled = true;
  try {
    const r = await api("/api/insights", { method: "POST", body: JSON.stringify(body) });
    const arrows = { bullish: "▲", bearish: "▼", neutral: "●" };
    $("ai-sentiment").textContent = `${arrows[r.sentiment] || ""} Sentiment: ${r.sentiment}`;
    const risk = $("ai-risk");
    risk.className = `badge risk-${r.risk}`;
    risk.replaceChildren();
    const icon = document.createElement("span");
    icon.className = "dot-icon";
    icon.setAttribute("aria-hidden", "true");
    risk.append(icon, document.createTextNode(`Risk: ${r.risk}`));
    $("ai-summary").textContent = r.summary;
    $("ai-model").textContent = `Model: ${r.model}. Not financial advice.`;
    $("ai-result").hidden = false;
    setStatus($("ai-status"), "");
  } catch (err) {
    setStatus($("ai-status"), `No insight. ${err.message}`, true);
  } finally {
    $("ai-job").disabled = currentJob === null;
    $("ai-text-button").disabled = false;
  }
}

// ---------- 4. telemetry ----------

async function loadTelemetry() {
  try {
    const stats = await api("/api/telemetry");
    const tbody = $("telemetry-table").querySelector("tbody");
    tbody.replaceChildren();
    for (const [name, s] of Object.entries(stats)) {
      const row = document.createElement("tr");
      cell(row, name);
      cell(row, s.calls, "num");
      cell(row, s.errors, "num");
      cell(row, num.format(s.avg_ms), "num");
      cell(row, num.format(s.max_ms), "num");
      tbody.appendChild(row);
    }
  } catch (err) {
    console.error(err);
  }
}

// ---------- wiring ----------

$("price-refresh").addEventListener("click", loadPrices);
$("price-source").addEventListener("change", loadPrices);
$("job-form").addEventListener("submit", startJob);
$("jobs-refresh").addEventListener("click", loadJobs);
$("ai-job").addEventListener("click", () => currentJob && askAI({ job_id: currentJob.id }));
$("ai-text-button").addEventListener("click", () => {
  const text = $("ai-text").value.trim();
  if (text) askAI({ text });
  else setStatus($("ai-status"), "Type some text to classify first.", true);
});
$("telemetry-refresh").addEventListener("click", loadTelemetry);
$("telemetry-details").addEventListener("toggle", (e) => e.target.open && loadTelemetry());

loadPrices();
loadJobs();
