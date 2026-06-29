(() => {
  let report = null;
  let debounceTimer = null;
  let requestSeq = 0;

  const $ = (id) => document.getElementById(id);

  function buildRequest() {
    return {
      symbol: $("symbol").value,
      timeframe: $("timeframe").value,
      months_back: parseInt($("months-back").value, 10),
      sma_length: parseInt($("sma-length").value, 10),
      target_points: parseFloat($("target-points").value),
      stop_loss_points: parseFloat($("stop-points").value),
      direction: $("direction").value,
    };
  }

  function formatDuration(sec) {
    const s = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${s % 60}s`;
  }

  function statCard(label, value, cls) {
    return `<div class="stat-card ${cls || ""}"><span class="k">${label}</span><strong>${value}</strong></div>`;
  }

  function renderSideStats(elId, stats) {
    const s = stats || {};
    const wrCls = s.win_rate_pct >= 50 ? "opt-pos" : s.win_rate_pct >= 30 ? "opt-warn" : "opt-neg";
    $(elId).innerHTML = `
      ${statCard("Total", s.total ?? 0)}
      ${statCard("Target Hits", s.target_hits ?? 0, "opt-pos")}
      ${statCard("Stop Loss", s.stop_loss ?? 0, "opt-neg")}
      ${statCard("Win Rate %", s.win_rate_pct ?? 0, wrCls)}
      ${statCard("Avg Bars → Target", s.avg_bars_to_target ?? 0)}
      ${statCard("Avg Bars → Stop", s.avg_bars_to_stop ?? 0)}`;
  }

  function renderCombined(c) {
    const wrCls = c.overall_win_rate_pct >= 50 ? "opt-pos" : c.overall_win_rate_pct >= 30 ? "opt-warn" : "opt-neg";
  const evCls = c.expected_value_points > 0 ? "opt-pos" : c.expected_value_points < 0 ? "opt-neg" : "opt-warn";
    $("combined-stats").innerHTML = `
      ${statCard("Total Signals", c.total_signals ?? 0)}
      ${statCard("Win Rate %", c.overall_win_rate_pct ?? 0, wrCls)}
      ${statCard("Expected Value", c.expected_value_points ?? 0, evCls)}
      ${statCard("Profit Factor", c.profit_factor ?? 0)}
      ${statCard("Win Streak", c.longest_win_streak ?? 0, "opt-pos")}
      ${statCard("Loss Streak", c.longest_loss_streak ?? 0, "opt-neg")}`;
  }

  function drawHistogram(canvasId, bins, color) {
    const canvas = $(canvasId);
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 16, 240);
    const h = 180;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    if (!bins || !bins.length) {
      ctx.fillStyle = "#6b7280";
      ctx.fillText("No data", 12, 24);
      return;
    }
    const maxC = Math.max(...bins.map((b) => b.count), 1);
    const pad = { l: 32, r: 8, t: 12, b: 28 };
    const barW = (w - pad.l - pad.r) / bins.length;
    bins.forEach((b, i) => {
      const bh = ((b.count / maxC) * (h - pad.t - pad.b));
      const x = pad.l + i * barW;
      const y = h - pad.b - bh;
      ctx.fillStyle = color;
      ctx.fillRect(x + 1, y, Math.max(barW - 2, 1), bh);
    });
    ctx.fillStyle = "#9ca3af";
    ctx.font = "9px sans-serif";
    ctx.fillText("0", pad.l, h - 8);
    const last = bins[bins.length - 1];
    ctx.fillText(`${last.bin_end}`, w - 40, h - 8);
  }

  function drawMonthly(canvasId, rows) {
    const canvas = $(canvasId);
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 16, 240);
    const h = 180;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    if (!rows || !rows.length) {
      ctx.fillStyle = "#6b7280";
      ctx.fillText("No data", 12, 24);
      return;
    }
    const pad = { l: 36, r: 8, t: 12, b: 36 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const step = plotW / rows.length;
    rows.forEach((r, i) => {
      const barH = (r.win_rate_pct / 100) * plotH;
      const x = pad.l + i * step;
      const y = pad.t + plotH - barH;
      ctx.fillStyle = r.win_rate_pct >= 50 ? "#22c55e" : "#ef4444";
      ctx.fillRect(x + 1, y, Math.max(step - 2, 2), barH);
      ctx.save();
      ctx.translate(x + step / 2, h - 4);
      ctx.rotate(-0.5);
      ctx.fillStyle = "#9ca3af";
      ctx.font = "8px sans-serif";
      ctx.fillText(r.month.slice(5), -10, 0);
      ctx.restore();
    });
    ctx.fillStyle = "#9ca3af";
    ctx.fillText("100%", 4, pad.t + 8);
    ctx.fillText("0%", 4, h - pad.b);
  }

  function drawScatter(canvasId, points) {
    const canvas = $(canvasId);
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 16, 240);
    const h = 180;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    if (!points || !points.length) {
      ctx.fillStyle = "#6b7280";
      ctx.fillText("No data", 12, 24);
      return;
    }
    const pad = { l: 36, r: 12, t: 12, b: 28 };
    const maxBars = Math.max(...points.map((p) => p.bars), 1);
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    points.forEach((p) => {
      const x = pad.l + (p.bars / maxBars) * plotW;
      const y = p.result === "TARGET"
        ? pad.t + plotH * 0.25
        : pad.t + plotH * 0.75;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = p.result === "TARGET" ? "#22c55e" : "#ef4444";
      ctx.fill();
    });
    ctx.fillStyle = "#9ca3af";
    ctx.font="9px sans-serif";
    ctx.fillText("Target", pad.l, pad.t + 10);
    ctx.fillText("Stop", pad.l, pad.t + plotH * 0.75 + 4);
    ctx.fillText("0", pad.l, h - 8);
    ctx.fillText(String(maxBars), w - 24, h - 8);
  }

  function renderTable() {
    const q = ($("signal-search").value || "").trim().toLowerCase();
    let rows = report?.signals || [];
    if (q) {
      rows = rows.filter((s) =>
        `${s.date} ${s.time} ${s.direction} ${s.result} ${s.entry}`.toLowerCase().includes(q)
      );
    }
    const body = $("signals-body");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="11" class="empty">No signals match.</td></tr>';
      return;
    }
    body.innerHTML = rows.map((s) => {
      const resCls = s.result === "TARGET" ? "opt-pos" : s.result === "STOP" ? "opt-neg" : "opt-warn";
      const dirCls = s.direction === "BUY" ? "opt-pos" : "opt-neg";
      return `<tr>
        <td>${s.date}</td>
        <td>${s.time}</td>
        <td class="${dirCls}">${s.direction}</td>
        <td>${s.entry}</td>
        <td>${s.exit}</td>
        <td>${s.target}</td>
        <td>${s.stop}</td>
        <td>${s.bars}</td>
        <td class="${resCls}">${s.result}</td>
        <td>${formatDuration(s.duration_seconds)}</td>
        <td class="${s.pnl_points >= 0 ? "opt-pos" : "opt-neg"}">${s.pnl_points}</td>
      </tr>`;
    }).join("");
  }

  function renderReport(data) {
    report = data;
    const meta = data.meta || {};
    $("analysis-meta").textContent = `${meta.candle_count?.toLocaleString() ?? 0} candles · ${meta.signal_count ?? 0} signals · ${meta.analysis_ms ?? "—"}ms`;
    renderSideStats("buy-stats", data.buy);
    renderSideStats("sell-stats", data.sell);
    renderCombined(data.combined || {});
    const charts = data.charts || {};
    drawHistogram("hist-target", charts.bars_to_target_histogram, "#22c55e");
    drawHistogram("hist-stop", charts.bars_to_stop_histogram, "#ef4444");
    drawMonthly("chart-monthly", charts.monthly_win_rate);
    drawScatter("chart-scatter", charts.target_vs_stop_scatter);
    renderTable();
  }

  async function runAnalysis() {
    const seq = ++requestSeq;
    $("loading-label").textContent = "Analyzing…";
    try {
      const data = await DSE.fetchJson("/research/signal-probability/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest()),
      });
      if (seq !== requestSeq) return;
      renderReport(data);
      $("loading-label").textContent = "";
    } catch (err) {
      if (seq !== requestSeq) return;
      $("loading-label").textContent = "Error";
      $("signals-body").innerHTML = `<tr><td colspan="11" class="empty opt-neg">${err.message || "Analysis failed"}</td></tr>`;
    }
  }

  function scheduleAnalysis() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runAnalysis, 400);
  }

  ["symbol", "timeframe", "months-back", "sma-length", "target-points", "stop-points", "direction"].forEach((id) => {
    $(id).addEventListener("input", scheduleAnalysis);
    $(id).addEventListener("change", scheduleAnalysis);
  });
  $("signal-search").addEventListener("input", renderTable);

  window.addEventListener("resize", () => {
    if (!report) return;
    const charts = report.charts || {};
    drawHistogram("hist-target", charts.bars_to_target_histogram, "#22c55e");
    drawHistogram("hist-stop", charts.bars_to_stop_histogram, "#ef4444");
    drawMonthly("chart-monthly", charts.monthly_win_rate);
    drawScatter("chart-scatter", charts.target_vs_stop_scatter);
  });

  document.getElementById("mobile-menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("sidebar-open");
  });

  runAnalysis();
})();
