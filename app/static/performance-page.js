const { fetchJson, formatPrice } = window.DSE;

const equityCanvas = document.getElementById("equity-chart");

function setText(id, value, suffix = "") {
  const el = document.getElementById(id);
  if (el) el.textContent = value != null && value !== "" ? `${value}${suffix}` : "—";
}

function pnlClass(value) {
  const n = Number(value);
  if (Number.isNaN(n) || n === 0) return "";
  return n > 0 ? "up" : "down";
}

function formatPnl(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n >= 0 ? "+" : "";
  return `${sign}${formatPrice(n)}`;
}

function renderEdgeBanner(data) {
  const banner = document.getElementById("edge-banner");
  const label = document.getElementById("edge-label");
  const summary = document.getElementById("edge-summary");
  if (!banner || !label || !summary) return;

  banner.className = "edge-banner";
  if (data.edge_status) banner.classList.add(`edge-${data.edge_status}`);

  label.textContent = data.edge_label || "—";
  summary.textContent = data.edge_summary || "";
}

function renderEquityChart(curve, startingBalance) {
  if (!equityCanvas) return;

  const ctx = equityCanvas.getContext("2d");
  const wrap = equityCanvas.parentElement;
  const cw = wrap?.clientWidth || 640;
  const ch = 220;
  const dpr = window.devicePixelRatio || 1;

  equityCanvas.width = cw * dpr;
  equityCanvas.height = ch * dpr;
  equityCanvas.style.width = `${cw}px`;
  equityCanvas.style.height = `${ch}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);

  ctx.fillStyle = "#161b22";
  ctx.fillRect(0, 0, cw, ch);

  const points = [{ date: "start", equity: Number(startingBalance) || 1000 }];
  (curve || []).forEach((p) => points.push({ date: p.date, equity: Number(p.equity) }));

  if (points.length < 2) {
    ctx.fillStyle = "#8b949e";
    ctx.font = "13px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No closed trades yet — equity curve will appear after first close", cw / 2, ch / 2);
    return;
  }

  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const padX = 36;
  const padY = 22;

  ctx.strokeStyle = "#30363d";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = padY + ((ch - padY * 2) * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padX, y);
    ctx.lineTo(cw - padX, y);
    ctx.stroke();
  }

  const baseline = Number(startingBalance) || 1000;
  if (baseline >= min && baseline <= max) {
    const yBase = padY + (ch - padY * 2) * (1 - (baseline - min) / range);
    ctx.strokeStyle = "#484f58";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padX, yBase);
    ctx.lineTo(cw - padX, yBase);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.strokeStyle = "#0ecb81";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, i) => {
    const x = padX + (i / (points.length - 1)) * (cw - padX * 2);
    const y = padY + (ch - padY * 2) * (1 - (point.equity - min) / range);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#0ecb81";
  points.forEach((point, i) => {
    const x = padX + (i / (points.length - 1)) * (cw - padX * 2);
    const y = padY + (ch - padY * 2) * (1 - (point.equity - min) / range);
    ctx.beginPath();
    ctx.arc(x, y, i === points.length - 1 ? 4 : 2.5, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#8b949e";
  ctx.font = "11px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(formatPrice(max), 4, padY + 4);
  ctx.fillText(formatPrice(min), 4, ch - padY);

  const meta = document.getElementById("equity-meta");
  if (meta) {
    const last = curve?.[curve.length - 1];
    meta.textContent = last
      ? `${curve.length} day(s) · last ${last.date} · daily PnL ${formatPnl(last.daily_pnl)}`
      : "Baseline only";
  }
}

let lastPerformanceData = null;
let missedPeriod = "today";

function formatPts(value, signed = false) {
  const n = Number(value ?? 0);
  if (Number.isNaN(n)) return "—";
  if (!signed) return `${n.toFixed(2)} pts`;
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)} pts`;
}

function renderMissedAnalytics(data) {
  const total = Number(data.missed_opportunities ?? (data.missed_winners + data.missed_losers));
  setText("mo-generated", data.signals_generated);
  setText("mo-approved", data.signals_approved);
  setText("mo-winners", data.missed_winners);
  setText("mo-losers", data.missed_losers);
  setText("mo-total", total);
  setText("mo-gross-profit", formatPts(data.gross_missed_profit, true));
  setText("mo-gross-loss", formatPts(data.gross_missed_loss, true));
  setText("mo-gross-profit-usd", formatUsd(data.gross_missed_pnl_usd));
  setText("mo-gross-loss-usd", formatUsd(data.gross_missed_loss_usd));
  const netEl = document.getElementById("mo-net");
  const netUsdEl = document.getElementById("mo-net-usd");
  if (netEl) {
    const net = Number(data.net_missed_profit ?? 0);
    netEl.textContent = formatPts(net, true);
    netEl.className = "stat-value";
    if (net > 0) netEl.classList.add("up");
    if (net < 0) netEl.classList.add("down");
  }
  if (netUsdEl) {
    const netUsd = Number(data.net_missed_pnl_usd ?? 0);
    netUsdEl.textContent = formatUsd(netUsd);
    netUsdEl.className = "stat-value";
    if (netUsd > 0) netUsdEl.classList.add("up");
    if (netUsd < 0) netUsdEl.classList.add("down");
  }
  setText("mo-net-roe-total", data.net_missed_roe_pct != null ? `${Number(data.net_missed_roe_pct).toFixed(2)}%` : "—");
  const symEl = document.getElementById("mo-by-symbol");
  if (symEl && data.by_symbol) {
    symEl.innerHTML = data.by_symbol
      .map(
        (row) => `
        <div class="missed-symbol-row">
          <span class="missed-symbol-label">${row.label} Missed</span>
          <span class="missed-symbol-dual">
            <span class="missed-symbol-value">${Number(row.net_missed_roe_pct || 0).toFixed(2)}% ROE</span>
            <span class="missed-symbol-value">${formatUsd(row.net_missed_pnl_usd)}</span>
          </span>
        </div>`
      )
      .join("");
  }
}

function formatUsd(value) {
  const n = Number(value ?? 0);
  if (Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

async function loadMissedAnalytics(period = missedPeriod) {
  missedPeriod = period;
  try {
    const data = await fetchJson(`/missed-opportunities/analytics?period=${encodeURIComponent(period)}`);
    renderMissedAnalytics(data);
  } catch (error) {
    const grid = document.getElementById("missed-analytics-grid");
    if (grid) {
      grid.innerHTML = `<p class="empty">Error loading missed analytics: ${error.message}</p>`;
    }
  }
}

function renderPerformance(data) {
  lastPerformanceData = data;
  renderEdgeBanner(data);

  setText("pa-start", formatPrice(data.starting_balance));
  setText("pa-current", formatPrice(data.current_balance));
  setText("pa-net", formatPnl(data.net_pnl));
  setText("pa-total", data.total_trades);
  setText("pa-wins", data.winning_trades);
  setText("pa-losses", data.losing_trades);
  setText("pa-winrate", data.total_trades ? data.win_rate : "0", "%");
  setText("pa-avgwin", formatPrice(data.average_win));
  setText("pa-avgloss", formatPrice(data.average_loss));
  setText("pa-maxwin", formatPrice(data.largest_win));
  setText("pa-maxloss", formatPrice(data.largest_loss));
  setText("pa-pf", data.profit_factor != null ? data.profit_factor : "—");
  setText(
    "pa-dd",
    data.max_drawdown_pct > 0
      ? `${formatPrice(data.max_drawdown_usd)} (${data.max_drawdown_pct}%)`
      : formatPrice(0)
  );
  setText("pa-duration", data.average_trade_duration || "—");
  setText("pa-open", data.open_positions);
  setText("pa-avg-roe", data.average_roe != null ? `${data.average_roe}%` : "—");
  setText("pa-best-roe", data.best_roe != null ? `${data.best_roe}%` : "—");
  setText("pa-worst-roe", data.worst_roe != null ? `${data.worst_roe}%` : "—");

  ["pa-net"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.className = "stat-value";
      el.classList.add(pnlClass(data.net_pnl));
    }
  });

  const currentEl = document.getElementById("pa-current");
  if (currentEl) {
    currentEl.className = "stat-value";
    if (data.current_balance >= data.starting_balance) currentEl.classList.add("up");
    else if (data.current_balance < data.starting_balance) currentEl.classList.add("down");
  }

  renderEquityChart(data.daily_equity_curve, data.starting_balance);
}

async function loadPerformance() {
  try {
    const data = await fetchJson("/paper/performance");
    renderPerformance(data);
  } catch (error) {
    const grid = document.getElementById("perf-metrics-grid");
    if (grid) {
      grid.innerHTML = `<p class="empty">Error loading performance analytics: ${error.message}</p>`;
    }
    const summary = document.getElementById("edge-summary");
    if (summary) summary.textContent = error.message;
  }
}

document.getElementById("perf-refresh")?.addEventListener("click", () => {
  loadPerformance();
  loadMissedAnalytics(missedPeriod);
});

document.getElementById("missed-period-tabs")?.addEventListener("click", (event) => {
  const btn = event.target.closest(".period-tab");
  if (!btn) return;
  document.querySelectorAll("#missed-period-tabs .period-tab").forEach((el) => {
    el.classList.toggle("active", el === btn);
  });
  loadMissedAnalytics(btn.dataset.period);
});

window.addEventListener("resize", () => {
  if (lastPerformanceData) renderEquityChart(lastPerformanceData.daily_equity_curve, lastPerformanceData.starting_balance);
});

loadPerformance();
loadMissedAnalytics("today");
setInterval(loadPerformance, 30000);
setInterval(() => loadMissedAnalytics(missedPeriod), 30000);
