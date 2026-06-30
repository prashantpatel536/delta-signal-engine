(() => {
  let chartEngine = null;
  const SOL_BARS_KEY = "solChartBars";
  const DEFAULT_BARS = 200;

  const $ = (id) => document.getElementById(id);

  function statCard(label, value, cls) {
    return `<div class="stat-card ${cls || ""}"><span class="k">${label}</span><strong>${value ?? "—"}</strong></div>`;
  }

  function valCls(v) {
    return v > 0 ? "opt-pos" : v < 0 ? "opt-neg" : "opt-warn";
  }

  function getBars() {
    const sel = $("sol-bars-select");
    if (sel) return parseInt(sel.value, 10) || DEFAULT_BARS;
    return parseInt(localStorage.getItem(SOL_BARS_KEY), 10) || DEFAULT_BARS;
  }

  function buildChartEngine() {
    if (chartEngine) return chartEngine;
    chartEngine = ChartEngine.create({
      container: $("chart-container"),
      showIndicators: false,
      pnlOverlay: $("trade-pnl-overlay"),
      legend: {
        chartSymbol: $("chart-symbol"),
        legTime: $("leg-time"),
        legO: $("leg-o"),
        legH: $("leg-h"),
        legL: $("leg-l"),
        legC: $("leg-c"),
        legV: $("leg-v"),
        lastPrice: $("last-price"),
        priceChange: $("price-change"),
      },
      onFootnote: (text) => {
        const el = $("signal-marker-count");
        if (el) el.textContent = text;
      },
    });
    return chartEngine;
  }

  function renderKpis(data) {
    const m = data.market || {};
    const a = data.account || {};
    $("kpi-grid").innerHTML = `
      ${statCard("Status", data.engine?.running ? "Running" : "Stopped", "opt-pos")}
      ${statCard("Price", m.last_price?.toFixed(4) ?? "—")}
      ${statCard("ATR", m.atr?.toFixed(4) ?? "—")}
      ${statCard("Equity", `$${a.equity}`, valCls(a.equity - (a.initial_capital || 1000)))}
      ${statCard("Today's PnL", `$${a.realized_pnl?.toFixed(2) ?? 0}`, valCls(a.realized_pnl))}
      ${statCard("HA Candle", m.ha_candle?.color ?? "—", m.ha_candle?.color === "green" ? "opt-pos" : "opt-neg")}`;
    $("ws-status").textContent = m.ws_connected ? "WS Connected" : "REST Polling";
    $("sol-status-dot").className = `dot ${data.engine?.running ? "ok" : ""}`;
  }

  function renderPosition(pos) {
    if (!pos) {
      $("position-cards").innerHTML = '<p class="muted">No open position</p>';
      return;
    }
    $("position-cards").innerHTML = `
      ${statCard("Direction", pos.side, pos.side === "BUY" ? "opt-pos" : "opt-neg")}
      ${statCard("Entry", pos.entry)}
      ${statCard("Current PnL %", `${pos.unrealized_pct}%`, valCls(pos.unrealized_pct))}
      ${statCard("Current PnL $", pos.unrealized_usd, valCls(pos.unrealized_usd))}
      ${statCard("Highest Profit %", `${pos.highest_profit_pct ?? 0}%`)}
      ${statCard("Stop", pos.stop_loss)}
      ${statCard("Take Profit", pos.take_profit)}
      ${statCard("Lock Active", pos.lock_active ? "Yes" : "No", pos.lock_active ? "opt-warn" : "")}
      ${statCard("Lock Stop", pos.lock_stop ?? "—")}`;
  }

  function renderStats(s) {
    $("stats-cards").innerHTML = `
      ${statCard("Total Trades", s.total_trades)}
      ${statCard("Wins", s.wins, "opt-pos")}
      ${statCard("Losses", s.losses, "opt-neg")}
      ${statCard("Win Rate", `${s.win_rate}%`, valCls(s.win_rate - 50))}
      ${statCard("Profit Factor", s.profit_factor, valCls(s.profit_factor - 1))}
      ${statCard("Avg Win", s.avg_win, "opt-pos")}
      ${statCard("Avg Loss", s.avg_loss, "opt-neg")}
      ${statCard("Expected Value", s.expected_value, valCls(s.expected_value))}
      ${statCard("Max Win Streak", s.max_win_streak)}
      ${statCard("Max Loss Streak", s.max_loss_streak, "opt-neg")}`;
  }

  function renderTrades(trades) {
    const body = $("trades-body");
    if (!trades?.length) {
      body.innerHTML = '<tr><td colspan="11" class="empty">No trades yet</td></tr>';
      return;
    }
    body.innerHTML = trades.map((t) => `<tr>
      <td>${(t.opened_at || "").slice(0, 19)}</td>
      <td>${(t.closed_at || "").slice(0, 19)}</td>
      <td class="${t.side === "BUY" ? "opt-pos" : "opt-neg"}">${t.side}</td>
      <td>${t.entry}</td>
      <td>${t.exit_price}</td>
      <td class="${valCls(t.pnl_pct)}">${t.pnl_pct}</td>
      <td class="${valCls(t.pnl_usd)}">${t.pnl_usd}</td>
      <td>${t.bars_held ?? "—"}</td>
      <td>${t.exit_reason}</td>
      <td>${t.mfe_pct ?? 0}</td>
      <td>${t.mae_pct ?? 0}</td>
    </tr>`).join("");
  }

  function updateChart(chartData, status) {
    const engine = buildChartEngine();
    if (!engine.ready) return;
    const bars = getBars();
    const pos = status?.position;
    const overlay = pos
      ? {
          ...pos,
          symbol: "SOLUSDT",
          quantity: pos.quantity ?? 0,
          leverage: pos.leverage ?? 1,
          margin_used: pos.margin_used ?? 0,
        }
      : null;
    engine.update(chartData, {
      windowSize: bars,
      timeframe: chartData.timeframe || "5m",
      signalTimeframe: "5m",
      symbol: "SOL",
      position: overlay,
      signalQuality: null,
    });
  }

  function drawLine(canvasId, values, color) {
    const canvas = $(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.parentElement.clientWidth - 16;
    const h = 160;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    if (!values.length) return;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = 36;
    const plotW = w - pad - 8;
    const plotH = h - 28;
    ctx.strokeStyle = color;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = pad + (i / Math.max(values.length - 1, 1)) * plotW;
      const y = 12 + plotH - ((v - min) / (max - min || 1)) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  async function loadResearch() {
    const eq = await DSE.fetchJson("/sol/api/research/equity");
    drawLine("equity-chart", (eq.equity_curve || []).map((p) => p.equity), "#22c55e");
    const trades = await DSE.fetchJson("/sol/api/trades");
    drawLine("pnl-chart", (trades.trades || []).map((t) => parseFloat(t.pnl_usd || 0)), "#f0b90b");
  }

  function renderSettingsForm(s) {
    const fields = [
      ["min_red_candles", "Min Red Candles", "number"],
      ["max_green_candles", "Max Green Candles", "number"],
      ["strong_candle_enabled", "Strong Candle", "checkbox"],
      ["atr_filter_enabled", "ATR Filter", "checkbox"],
      ["atr_multiplier", "ATR Multiplier", "number"],
      ["atr_minimum", "ATR Minimum", "number"],
      ["take_profit_pct", "Take Profit %", "number"],
      ["stop_loss_pct", "Stop Loss %", "number"],
      ["lock_profit_enabled", "Lock Profit", "checkbox"],
      ["lock_trigger_pct", "Lock Trigger %", "number"],
      ["lock_distance_pct", "Lock Distance %", "number"],
      ["leverage", "Leverage", "number"],
      ["position_size_pct", "Position Size %", "number"],
    ];
    $("settings-form").innerHTML = fields.map(([key, label, type]) => {
      const val = s[key];
      if (type === "checkbox") {
        return `<label>${label}<input type="checkbox" data-key="${key}" ${val ? "checked" : ""} /></label>`;
      }
      return `<label>${label}<input type="number" step="any" data-key="${key}" value="${val}" /></label>`;
    }).join("");
  }

  async function refresh() {
    const bars = getBars();
    const [status, chartData, trades] = await Promise.all([
      DSE.fetchJson("/sol/api/status"),
      DSE.fetchJson(`/sol/api/chart?bars=${bars}`),
      DSE.fetchJson("/sol/api/trades"),
    ]);
    renderKpis(status);
    renderPosition(status.position);
    renderStats(status.statistics || {});
    updateChart(chartData, status);
    renderTrades(trades.trades);
    if (!$("settings-form").children.length) {
      renderSettingsForm(status.settings || {});
    }
    const bootErr = $("chart-boot-error");
    if (bootErr && chartData.candles?.length) {
      bootErr.hidden = true;
    }
  }

  $("save-settings")?.addEventListener("click", async () => {
    const updates = {};
    $("settings-form").querySelectorAll("[data-key]").forEach((el) => {
      const key = el.dataset.key;
      if (el.type === "checkbox") updates[key] = el.checked;
      else updates[key] = parseFloat(el.value);
    });
    await DSE.fetchJson("/sol/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    await refresh();
  });

  $("export-csv")?.addEventListener("click", () => {
    window.open("/sol/api/export/trades.csv", "_blank");
  });

  $("sol-bars-select")?.addEventListener("change", (e) => {
    localStorage.setItem(SOL_BARS_KEY, e.target.value);
    chartEngine?.resetPan();
    refresh();
  });

  $("sol-chart-refresh")?.addEventListener("click", () => refresh());
  $("chart-reset-scale")?.addEventListener("click", () => {
    chartEngine?.resetView();
    refresh();
  });

  const savedBars = localStorage.getItem(SOL_BARS_KEY);
  if (savedBars && $("sol-bars-select")) $("sol-bars-select").value = savedBars;

  const engine = buildChartEngine();
  if (!engine.init()) {
    const bootErr = $("chart-boot-error");
    if (bootErr) {
      bootErr.hidden = false;
      bootErr.textContent = "Chart initializing…";
    }
    window.addEventListener("chart-engine-ready", () => refresh(), { once: true });
  } else {
    refresh();
  }
  loadResearch();
  setInterval(refresh, 5000);
})();
