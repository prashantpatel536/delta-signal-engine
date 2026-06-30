(() => {
  const $ = (id) => document.getElementById(id);
  let strategyId = StrategyNav.detectStrategyId();
  let lastResult = null;
  let lastRunId = null;
  let tradeChartEngine = null;
  let loadedSettings = null;

  const SYMBOLS = { sol_reversal: "SOLUSDT", btc_trend: "BTCUSDT" };

  function defaultDates() {
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - 3);
    return {
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
    };
  }

  function renderConfigForm(timeframes) {
    const d = defaultDates();
    const sym = SYMBOLS[strategyId] || "BTCUSDT";
    $("bt-config-form").innerHTML = `
      <label>Symbol<input id="bt-symbol" value="${sym}" /></label>
      <label>Timeframe<select id="bt-timeframe">${timeframes.map((t) => `<option value="${t}" ${t === "5m" ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <label>Start Date<input type="date" id="bt-start" value="${d.start}" /></label>
      <label>End Date<input type="date" id="bt-end" value="${d.end}" /></label>
      <label>Initial Capital<input type="number" id="bt-capital" value="1000" step="100" /></label>
      <label>Leverage<input type="number" id="bt-leverage" value="25" step="1" /></label>
      <label>Position Size %<input type="number" id="bt-pos-pct" value="50" step="1" /></label>
      <label>Commission %<input type="number" id="bt-commission" value="0.05" step="0.01" /></label>
      <label>Slippage %<input type="number" id="bt-slippage" value="0.02" step="0.01" /></label>
      <label>Run Name<input id="bt-name" placeholder="Optional" /></label>`;
  }

  function configPayload() {
    return {
      strategy_id: strategyId,
      symbol: $("bt-symbol").value.trim(),
      timeframe: $("bt-timeframe").value,
      start_date: $("bt-start").value,
      end_date: $("bt-end").value,
      initial_capital: parseFloat($("bt-capital").value),
      leverage: parseFloat($("bt-leverage").value),
      position_size_pct: parseFloat($("bt-pos-pct").value),
      commission_pct: parseFloat($("bt-commission").value),
      slippage_pct: parseFloat($("bt-slippage").value),
      use_current_settings: true,
      settings: loadedSettings,
      save: $("bt-save").checked,
      name: $("bt-name").value.trim() || null,
    };
  }

  function statCard(k, v, cls) {
    return `<div class="stat-card ${cls || ""}"><span class="k">${k}</span><strong>${v}</strong></div>`;
  }

  function renderStats(s) {
    const g = $("bt-stats-grid");
    g.innerHTML = [
      ["Total Return %", `${s.total_return_pct}%`, s.total_return_pct >= 0 ? "opt-pos" : "opt-neg"],
      ["Net Profit", `$${s.net_profit}`, s.net_profit >= 0 ? "opt-pos" : "opt-neg"],
      ["Initial Capital", `$${s.initial_capital}`],
      ["Final Equity", `$${s.final_equity}`],
      ["Profit Factor", s.profit_factor],
      ["Win Rate", `${s.win_rate}%`],
      ["Total Trades", s.total_trades],
      ["Wins", s.winning_trades, "opt-pos"],
      ["Losses", s.losing_trades, "opt-neg"],
      ["Avg Win", `$${s.avg_win}`, "opt-pos"],
      ["Avg Loss", `$${s.avg_loss}`, "opt-neg"],
      ["Avg Trade", `$${s.avg_trade}`],
      ["Largest Win", `$${s.largest_win}`, "opt-pos"],
      ["Largest Loss", `$${s.largest_loss}`, "opt-neg"],
      ["Max Drawdown", `${s.max_drawdown_pct}%`, "opt-neg"],
      ["Max Win Streak", s.max_win_streak],
      ["Max Loss Streak", s.max_loss_streak, "opt-neg"],
      ["Expectancy", `$${s.expectancy}`],
      ["Avg Hold (bars)", s.avg_holding_bars],
    ].map(([k, v, c]) => statCard(k, v, c)).join("");
    $("bt-results-panel").hidden = false;
  }

  function fmtTs(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString();
  }

  function drawLineChart(canvasId, points, { color = "#14d990", hover = null } = {}) {
    const canvas = $(canvasId);
    if (!canvas || !points.length) return;
    const wrap = canvas.parentElement;
    const w = wrap.clientWidth - 16;
    const h = parseInt(canvas.getAttribute("height"), 10) || 200;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    const vals = points.map((p) => p.y);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const padL = 48;
    const padR = 12;
    const padT = 16;
    const padB = 28;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    ctx.strokeStyle = "#2b3139";
    ctx.beginPath();
    ctx.moveTo(padL, padT);
    ctx.lineTo(padL, h - padB);
    ctx.lineTo(w - padR, h - padB);
    ctx.stroke();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = padL + (i / Math.max(points.length - 1, 1)) * plotW;
      const y = padT + plotH - ((p.y - min) / (max - min || 1)) * plotH;
      p._x = x;
      p._y = y;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    if (hover != null && points[hover]) {
      const p = points[hover];
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p._x, p._y, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawBarChart(canvasId, buckets) {
    const canvas = $(canvasId);
    if (!canvas || !buckets?.length) return;
    const wrap = canvas.parentElement;
    const w = wrap.clientWidth - 16;
    const h = parseInt(canvas.getAttribute("height"), 10) || 140;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    const maxC = Math.max(...buckets.map((b) => b.count), 1);
    const barW = Math.max(4, (w - 40) / buckets.length - 4);
    buckets.forEach((b, i) => {
      const bh = (b.count / maxC) * (h - 40);
      const x = 20 + i * (barW + 4);
      const y = h - 20 - bh;
      ctx.fillStyle = b.count > 0 ? "#14d990" : "#2b3139";
      ctx.fillRect(x, y, barW, bh);
    });
  }

  function setupEquityHover(canvasId, tipId, points) {
    const canvas = $(canvasId);
    const tip = $(tipId);
    if (!canvas) return;
    canvas.onmousemove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      let best = 0;
      let bestD = Infinity;
      points.forEach((p, i) => {
        const d = Math.abs((p._x || 0) - x);
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      });
      drawLineChart(canvasId, points, { hover: best });
      const p = points[best];
      if (tip && p) {
        tip.textContent = `Date: ${fmtTs(p.time)} · Equity: $${p.y.toFixed(2)} · DD: ${p.dd}% · Trade #${p.trade || 0}`;
      }
    };
  }

  function renderCharts(result) {
    const eq = (result.equity_curve || []).map((p) => ({
      time: p.time,
      y: p.equity,
      dd: p.drawdown_pct,
      trade: p.trade_num,
    }));
    if (!eq.length) return;
    drawLineChart("bt-equity-chart", eq);
    setupEquityHover("bt-equity-chart", "bt-equity-tip", eq);
    const dd = (result.drawdown_series || []).map((p) => ({
      time: p.time,
      y: p.drawdown_pct,
    }));
    drawLineChart("bt-dd-chart", dd, { color: "#ff5b6a" });
    $("bt-charts").hidden = false;
  }

  function renderPerformance(perf) {
    if (!perf) return;
    $("bt-perf-stats").innerHTML = [
      ["Daily Return (avg)", perf.daily_return_pct != null ? `${perf.daily_return_pct}%` : "—"],
      ["Weekly Return (est)", perf.weekly_return_pct != null ? `${perf.weekly_return_pct}%` : "—"],
      ["Monthly Return (est)", perf.monthly_return_pct != null ? `${perf.monthly_return_pct}%` : "—"],
      ["Yearly Return (est)", perf.yearly_return_pct != null ? `${perf.yearly_return_pct}%` : "—"],
    ].map(([k, v]) => statCard(k, v)).join("");
    drawBarChart("bt-dist-pnl", perf.trade_distribution || []);
    drawBarChart("bt-dist-hold", perf.holding_time_distribution || []);
    $("bt-performance-panel").hidden = false;
  }

  function renderMonthly(rows) {
    $("bt-monthly-body").innerHTML = (rows || []).map((r) => `<tr>
      <td>${r.month}</td><td>${r.trades}</td>
      <td class="${r.profit >= 0 ? "opt-pos" : "opt-neg"}">${r.profit}</td>
      <td>${r.win_rate}%</td><td>${r.profit_factor}</td></tr>`).join("");
    $("bt-monthly-panel").hidden = !rows?.length;
  }

  async function renderTradeChart(tr, result) {
    const symbol = result.symbol || $("bt-symbol")?.value || "BTCUSDT";
    const tf = result.timeframe || $("bt-timeframe")?.value || "5m";
    const pad = 60 * 60 * 12;
    const startTs = Math.max(0, tr.entry_time - pad);
    const endTs = tr.exit_time + pad;
    try {
      const data = await DSE.fetchJson(
        `/backtest/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${tf}&start_ts=${startTs}&end_ts=${endTs}`
      );
      const candles = data.candles || [];
      if (!candles.length || !window.ChartEngine) return;

      const container = $("bt-trade-chart-container");
      container.innerHTML = "";
      tradeChartEngine = ChartEngine.create(container, { showIndicators: false });
      tradeChartEngine.update({
        candles,
        signals: [
          { time: tr.entry_time, side: tr.side, label: "Entry" },
          { time: tr.exit_time, side: tr.side === "BUY" ? "SELL" : "BUY", label: tr.exit_reason },
        ],
      });
    } catch (e) {
      console.warn("Trade chart failed", e);
    }
  }

  function showTradeDetail(tr) {
    $("bt-trade-detail").hidden = false;
    $("bt-trade-detail-cards").innerHTML = [
      ["Direction", tr.side],
      ["Entry", `${fmtTs(tr.entry_time)} @ ${tr.entry_price}`],
      ["Exit", `${fmtTs(tr.exit_time)} @ ${tr.exit_price}`],
      ["Stop Loss", tr.stop_loss ?? "—"],
      ["Take Profit", tr.take_profit ?? "—"],
      ["Trailing / Lock Stop", tr.lock_stop ?? (tr.lock_active ? "Active" : "—")],
      ["Lock Profit Activation", tr.lock_active ? "Yes" : "No"],
      ["Exit Reason", tr.exit_reason],
      ["Max Profit (price %)", tr.highest_profit_pct ?? tr.mfe_pct],
      ["Max Drawdown (MAE %)", tr.mae_pct],
      ["MFE / MAE", `${tr.mfe_pct ?? "—"} / ${tr.mae_pct ?? "—"}`],
      ["PnL", `$${tr.pnl_usd} (${tr.price_move_pct}% price)`],
    ].map(([k, v]) => statCard(k, v)).join("");
    if (lastResult) renderTradeChart(tr, lastResult);
    $("bt-trade-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderTrades(trades) {
    const body = $("bt-trades-body");
    body.innerHTML = (trades || []).map((t) => `<tr class="bt-trade-row" data-num="${t.trade_num}">
      <td>${t.trade_num}</td>
      <td class="${t.side === "BUY" ? "opt-pos" : "opt-neg"}">${t.side}</td>
      <td>${fmtTs(t.entry_time)}</td>
      <td>${fmtTs(t.exit_time)}</td>
      <td>${t.entry_price}</td>
      <td>${t.exit_price}</td>
      <td class="${t.price_move_pct >= 0 ? "opt-pos" : "opt-neg"}">${t.price_move_pct}</td>
      <td class="${t.pnl_usd >= 0 ? "opt-pos" : "opt-neg"}">${t.pnl_usd}</td>
      <td>${t.bars_held}</td>
      <td>${t.exit_reason}</td>
      <td>${t.mfe_pct ?? "—"}</td>
      <td>${t.mae_pct ?? "—"}</td>
    </tr>`).join("");
    body.querySelectorAll(".bt-trade-row").forEach((row) => {
      row.addEventListener("click", () => {
        const num = parseInt(row.dataset.num, 10);
        const tr = trades.find((x) => x.trade_num === num);
        if (tr) showTradeDetail(tr);
      });
    });
    $("bt-trades-panel").hidden = !trades?.length;
  }

  function updateCompareBtn() {
    const checked = document.querySelectorAll(".bt-run-check:checked");
    const btn = $("bt-compare-btn");
    if (btn) btn.disabled = checked.length < 2;
  }

  async function loadSavedRuns() {
    const data = await DSE.fetchJson(`/backtest/api/runs?strategy_id=${strategyId}`);
    $("bt-runs-body").innerHTML = (data.runs || []).map((r) => {
      const s = r.statistics || {};
      return `<tr>
        <td><input type="checkbox" class="bt-run-check" data-id="${r.id}" /></td>
        <td>${r.name}</td>
        <td>${(r.created_at || "").slice(0, 16)}</td>
        <td class="${s.total_return_pct >= 0 ? "opt-pos" : "opt-neg"}">${s.total_return_pct}%</td>
        <td>${s.total_trades}</td>
        <td>${s.profit_factor}</td>
        <td>${s.max_drawdown_pct}%</td>
        <td><button type="button" class="btn-secondary btn-sm bt-load-run" data-id="${r.id}">Load</button></td>
      </tr>`;
    }).join("") || '<tr><td colspan="8" class="empty">No saved runs</td></tr>';

    document.querySelectorAll(".bt-run-check").forEach((cb) => {
      cb.addEventListener("change", updateCompareBtn);
    });
    document.querySelectorAll(".bt-load-run").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = await DSE.fetchJson(`/backtest/api/runs/${btn.dataset.id}`);
        lastRunId = row.id;
        displayResult(row);
      });
    });
  }

  function renderCompare(runs) {
    const metrics = [
      ["name", "Name"],
      ["total_return_pct", "Return %"],
      ["net_profit", "Net Profit"],
      ["profit_factor", "PF"],
      ["win_rate", "Win Rate"],
      ["total_trades", "Trades"],
      ["max_drawdown_pct", "Max DD"],
      ["expectancy", "Expectancy"],
    ];
    $("bt-compare-head").innerHTML = `<th>Metric</th>${runs.map((r) => `<th>${r.name || r.id}</th>`).join("")}`;
    $("bt-compare-body").innerHTML = metrics.map(([key, label]) => {
      const cells = runs.map((r) => {
        const s = r.statistics || {};
        const v = key === "name" ? (r.name || r.id) : s[key];
        return `<td>${v ?? "—"}</td>`;
      }).join("");
      return `<tr><td>${label}</td>${cells}</tr>`;
    }).join("");
    $("bt-compare-results").hidden = false;
  }

  function displayResult(result) {
    lastResult = result;
    renderStats(result.statistics);
    renderCharts(result);
    renderMonthly(result.monthly_report);
    renderTrades(result.trades);
    renderPerformance(result.performance);
  }

  async function loadStrategySettings() {
    const data = await DSE.fetchJson(`/backtest/api/settings/${strategyId}`);
    loadedSettings = data.settings;
    const s = loadedSettings || {};
    if ($("bt-leverage") && s.leverage != null) $("bt-leverage").value = s.leverage;
    if ($("bt-capital") && s.initial_capital != null) $("bt-capital").value = s.initial_capital;
    if ($("bt-pos-pct") && s.position_size_pct != null) $("bt-pos-pct").value = s.position_size_pct;
    $("bt-status").textContent = "Strategy settings loaded";
    return loadedSettings;
  }

  async function init() {
    StrategyNav.renderSidebar(strategyId, "backtest");
    const cfg = StrategyNav.NAV[strategyId];
    $("bt-title").textContent = `Backtest — ${cfg?.sub || strategyId}`;
    const [tf] = await Promise.all([
      DSE.fetchJson("/backtest/api/timeframes"),
      DSE.fetchJson("/backtest/api/strategies"),
    ]);
    renderConfigForm(tf.timeframes || ["5m"]);
    await loadStrategySettings();
    await loadSavedRuns();
  }

  $("bt-load-settings")?.addEventListener("click", () => loadStrategySettings());

  $("bt-run")?.addEventListener("click", async () => {
    $("bt-status").textContent = "Running…";
    $("bt-run").disabled = true;
    try {
      const resp = await DSE.fetchJson("/backtest/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configPayload()),
      });
      lastRunId = resp.run_id;
      displayResult(resp.result);
      $("bt-status").textContent = `Done — ${resp.result.statistics.total_trades} trades`;
      const diag = resp.result.diagnostics;
      if (diag) {
        $("bt-status").textContent += ` · ${diag.pine_signals_unfiltered} Pine signals / ${diag.bars_in_range} bars`;
      }
      await loadSavedRuns();
    } catch (e) {
      $("bt-status").textContent = `Error: ${e.message}`;
    } finally {
      $("bt-run").disabled = false;
    }
  });

  $("bt-compare-btn")?.addEventListener("click", async () => {
    const ids = [...document.querySelectorAll(".bt-run-check:checked")].map((cb) => parseInt(cb.dataset.id, 10));
    const data = await DSE.fetchJson("/backtest/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: ids }),
    });
    renderCompare(data.runs || []);
  });

  function exportUrl(fmt) {
    if (!lastRunId) {
      $("bt-status").textContent = "Save run first to export";
      return null;
    }
    return `/backtest/api/runs/${lastRunId}/export.${fmt}`;
  }

  $("bt-export-csv")?.addEventListener("click", () => {
    const u = exportUrl("csv");
    if (u) window.open(u, "_blank");
  });
  $("bt-export-xlsx")?.addEventListener("click", () => {
    const u = exportUrl("xlsx");
    if (u) window.open(u, "_blank");
  });
  $("bt-export-json")?.addEventListener("click", () => {
    const u = exportUrl("json");
    if (u) window.open(u, "_blank");
  });
  $("bt-export-pdf")?.addEventListener("click", () => {
    const u = exportUrl("pdf");
    if (u) window.open(u, "_blank");
  });

  init();
})();
