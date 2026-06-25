(() => {
  let jobId = null;
  let pollTimer = null;
  let topResults = [];
  let allResults = [];
  let sortKey = "rank";
  let sortDir = 1;
  let previewTimer = null;

  const $ = (id) => document.getElementById(id);

  function buildRequest() {
    return {
      start_date: $("start-date").value,
      end_date: $("end-date").value,
      gap: {
        start: parseFloat($("gap-start").value),
        end: parseFloat($("gap-end").value),
        step: parseFloat($("gap-step").value),
      },
      min_sl: {
        start: parseFloat($("min-sl-start").value),
        end: parseFloat($("min-sl-end").value),
        step: parseFloat($("min-sl-step").value),
      },
      max_sl: {
        start: parseFloat($("max-sl-start").value),
        end: parseFloat($("max-sl-end").value),
        step: parseFloat($("max-sl-step").value),
      },
      initial_capital: parseFloat($("initial-capital").value),
      commission_pct: parseFloat($("commission").value),
      leverage: parseFloat($("leverage").value),
      margin_percent: parseFloat($("margin-percent").value),
      timeframe: "5m",
      debug: $("debug-mode").checked,
    };
  }

  function formatDuration(sec) {
    const s = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${s % 60}s`;
  }

  function valClass(metric, value) {
    if (metric === "return_pct" || metric === "profit_usd" || metric === "profit_factor") {
      if (value > 0) return "opt-pos";
      if (value < 0) return "opt-neg";
      return "opt-warn";
    }
    if (metric === "max_drawdown_pct") {
      if (value <= 10) return "opt-pos";
      if (value <= 25) return "opt-warn";
      return "opt-neg";
    }
    if (metric === "win_rate") {
      if (value >= 50) return "opt-pos";
      if (value >= 30) return "opt-warn";
      return "opt-neg";
    }
    if (metric === "score") {
      if (value > 0) return "opt-pos";
      if (value <= -999999) return "opt-neg";
      return "opt-warn";
    }
    return "";
  }

  function renderComboPlan(plan) {
    if (!plan) {
      $("combo-breakdown").innerHTML = '<p class="muted">Adjust parameters to preview combination counts.</p>';
      return;
    }
    const mismatch = plan.mismatch_reason
      ? `<p class="opt-neg">Mismatch: ${plan.mismatch_reason}</p>` : "";
    const skipLines = Object.entries(plan.skip_reasons || {})
      .map(([reason, count]) => `<li>${count} × ${reason}</li>`).join("");
    $("combo-breakdown").innerHTML = `
      <div class="combo-grid">
        <div class="combo-card">
          <span class="combo-label">Gap values</span>
          <code class="combo-values">${(plan.gap_values || []).join(", ")}</code>
          <span class="combo-count">Count: <b>${plan.gap_count}</b></span>
        </div>
        <div class="combo-card">
          <span class="combo-label">Min SL values</span>
          <code class="combo-values">${(plan.min_sl_values || []).join(", ")}</code>
          <span class="combo-count">Count: <b>${plan.min_sl_count}</b></span>
        </div>
        <div class="combo-card">
          <span class="combo-label">Max SL values</span>
          <code class="combo-values">${(plan.max_sl_values || []).join(", ")}</code>
          <span class="combo-count">Count: <b>${plan.max_sl_count}</b></span>
        </div>
      </div>
      <div class="combo-summary pro-cards">
        <div><span class="k">Formula</span><strong>${plan.combination_formula || "—"}</strong></div>
        <div><span class="k">Expected</span><strong>${plan.expected_combinations}</strong></div>
        <div><span class="k">Skipped</span><strong class="opt-warn">${plan.skipped_combinations}</strong></div>
        <div><span class="k">Final tested</span><strong class="opt-pos">${plan.final_tested_combinations}</strong></div>
      </div>
      ${skipLines ? `<ul class="combo-skip-list">${skipLines}</ul>` : ""}
      ${mismatch}`;
  }

  async function refreshComboPreview() {
    try {
      const plan = await DSE.fetchJson("/research/btc-optimizer/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest()),
      });
      renderComboPlan(plan);
    } catch {
      $("combo-breakdown").innerHTML = '<p class="opt-neg">Invalid parameter ranges.</p>';
    }
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshComboPreview, 300);
  }

  function renderProgress(p) {
    $("progress-panel").hidden = false;
    const total = p.total || p.expected_combinations || 0;
    const pct = total ? Math.round((p.completed / total) * 100) : 0;
    $("progress-fill").style.width = `${pct}%`;
    $("progress-stats").innerHTML = `
      <span>Expected: <b>${p.expected_combinations ?? total}</b></span>
      <span>Completed: <b>${p.completed}</b></span>
      <span>Skipped (grid): <b>${p.skipped ?? 0}</b></span>
      <span>Remaining: <b>${p.remaining}</b></span>
      <span>Elapsed: <b>${formatDuration(p.elapsed_seconds)}</b></span>
      <span>ETA: <b>${p.eta_seconds != null ? formatDuration(p.eta_seconds) : "—"}</b></span>
      <span>Status: <b>${p.status}</b></span>`;
    const cur = p.current_param || {};
    $("current-param").innerHTML = p.current_gap != null
      ? `Current: Gap <b>${p.current_gap}%</b> · Min SL <b>${p.current_min_sl}</b> · Max SL <b>${p.current_max_sl}</b>`
      : "";
    if ($("debug-mode").checked && p.debug_log) {
      $("debug-panel").hidden = false;
      $("debug-log").textContent = p.debug_log.map((e) => JSON.stringify(e)).join("\n");
    }
  }

  function statCard(label, value, metric) {
    const cls = valClass(metric, parseFloat(value));
    return `<div class="stat-card ${cls}"><span class="k">${label}</span><strong>${value ?? "—"}</strong></div>`;
  }

  function renderBest(best, dateTested) {
    if (!best) {
      $("best-card").hidden = true;
      return;
    }
    $("best-card").hidden = false;
    $("best-result-grid").innerHTML = `
      ${statCard("Gap", `${best.gap_filter_pct}%`, "return_pct")}
      ${statCard("Min SL", best.min_sl_points, "return_pct")}
      ${statCard("Max SL", best.max_sl_points, "return_pct")}
      ${statCard("Profit Factor", best.profit_factor, "profit_factor")}
      ${statCard("Return %", `${best.return_pct}%`, "return_pct")}
      ${statCard("Drawdown %", `${best.max_drawdown_pct}%`, "max_drawdown_pct")}
      ${statCard("Trades", best.trade_count, "win_rate")}
      ${statCard("Win Rate", `${best.win_rate}%`, "win_rate")}
      ${statCard("Average R", best.avg_r_multiple, "profit_factor")}
      ${statCard("Expectancy", best.expectancy, "profit_usd")}
      ${statCard("Score", best.score, "score")}
      <div class="stat-card"><span class="k">Date Tested</span><strong>${(dateTested || "").slice(0, 19) || "—"}</strong></div>`;
  }

  function renderTopTable() {
    const q = ($("top-search").value || "").trim().toLowerCase();
    let rows = [...topResults];
    if (q) {
      rows = rows.filter((r) =>
        `${r.rank} ${r.gap_filter_pct} ${r.min_sl_points} ${r.max_sl_points} ${r.score}`.toLowerCase().includes(q)
      );
    }
    if (sortKey) {
      rows.sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        if (av === bv) return 0;
        return av > bv ? sortDir : -sortDir;
      });
    }
    const body = $("top-results-body");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="11" class="empty">No rankable results yet.</td></tr>';
      $("top-results-panel").hidden = !topResults.length;
      return;
    }
    $("top-results-panel").hidden = false;
    const sortedAll = [...topResults].sort((a, b) => (a.rank || 0) - (b.rank || 0));
    body.innerHTML = rows.map((r) => {
      const idx = sortedAll.findIndex((x) =>
        x.gap_filter_pct === r.gap_filter_pct
        && x.min_sl_points === r.min_sl_points
        && x.max_sl_points === r.max_sl_points
      );
      const resultIndex = allResults.findIndex((x) =>
        x.gap_filter_pct === r.gap_filter_pct
        && x.min_sl_points === r.min_sl_points
        && x.max_sl_points === r.max_sl_points
      );
      return `<tr>
        <td><strong>${r.rank}</strong></td>
        <td>${r.gap_filter_pct}</td>
        <td>${r.min_sl_points}</td>
        <td>${r.max_sl_points}</td>
        <td class="${valClass("profit_factor", r.profit_factor)}">${r.profit_factor}</td>
        <td class="${valClass("return_pct", r.return_pct)}">${r.return_pct}</td>
        <td class="${valClass("max_drawdown_pct", r.max_drawdown_pct)}">${r.max_drawdown_pct}</td>
        <td class="${valClass("win_rate", r.win_rate)}">${r.win_rate}</td>
        <td>${r.trade_count}</td>
        <td class="${valClass("score", r.score)}"><strong>${r.score}</strong></td>
        <td><button type="button" class="btn-secondary btn-sm" data-detail="${resultIndex}">View</button></td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-detail]").forEach((btn) => {
      btn.addEventListener("click", () => loadDetail(parseInt(btn.dataset.detail, 10)));
    });
  }

  function drawLineChart(canvasId, labels, values, color, yLabel) {
    const canvas = $(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 16, 280);
    const h = 160;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);
    if (!values.length) {
      ctx.fillStyle = "#6b7280";
      ctx.fillText("No data", 12, 24);
      return;
    }
    const pad = { l: 40, r: 8, t: 12, b: 24 };
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const range = maxV - minV || 1;
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = pad.l + (i / Math.max(values.length - 1, 1)) * plotW;
      const y = pad.t + plotH - ((v - minV) / range) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = "#9ca3af";
    ctx.font = "10px sans-serif";
    ctx.fillText(yLabel, 4, 12);
    ctx.fillText(String(maxV.toFixed(1)), 4, pad.t + 8);
    ctx.fillText(String(minV.toFixed(1)), 4, h - pad.b);
    if (labels.length) {
      ctx.fillText(labels[0] || "", pad.l, h - 6);
      ctx.fillText(labels[labels.length - 1] || "", w - 60, h - 6);
    }
  }

  function renderDetailStats(m) {
    const fields = [
      ["Total Trades", m.trade_count], ["Winning", m.winning_trades], ["Losing", m.losing_trades],
      ["Win Rate", `${m.win_rate}%`], ["Loss Rate", `${m.loss_rate}%`],
      ["Profit Factor", m.profit_factor], ["Net Profit", `$${m.net_profit_usd}`],
      ["Return %", `${m.return_pct}%`], ["Max Drawdown", `${m.max_drawdown_pct}%`],
      ["Avg Winner", m.avg_winner], ["Avg Loser", m.avg_loser],
      ["Largest Win", m.largest_winner], ["Largest Loss", m.largest_loser],
      ["Avg Trade", m.avg_trade], ["Avg R", m.avg_r_multiple],
      ["Expectancy", m.expectancy], ["Avg Duration", formatDuration(m.avg_duration_seconds)],
      ["Win Streak", m.longest_winning_streak], ["Loss Streak", m.longest_losing_streak],
      ["Score", m.score],
    ];
    $("detail-stats").innerHTML = fields.map(([k, v]) =>
      `<div class="stat-card"><span class="k">${k}</span><strong>${v ?? "—"}</strong></div>`
    ).join("");
  }

  async function loadDetail(resultIndex) {
    if (!jobId || resultIndex < 0) return;
    const data = await DSE.fetchJson(`/research/btc-optimizer/results/${jobId}/trades/${resultIndex}`);
    const p = data.params || {};
    $("detail-panel").hidden = false;
    $("trades-panel").hidden = false;
    $("detail-title").textContent = `Rank ${data.rank ?? "—"} — Gap ${p.gap_filter_pct}% · Min ${p.min_sl_points} · Max ${p.max_sl_points}`;
    $("trades-title").textContent = `Trade Log — Gap ${p.gap_filter_pct}% · Min SL ${p.min_sl_points} · Max SL ${p.max_sl_points}`;
    renderDetailStats(data.metrics || {});

    const eq = (data.equity_curve || []).map((p) => p.equity);
    const eqLabels = (data.equity_curve || []).map((p) => (p.time || "").slice(0, 10));
    drawLineChart("equity-chart", eqLabels, eq, "#22c55e", "Equity $");

    const dd = (data.drawdown_curve || []).map((p) => p.drawdown_pct);
    const ddLabels = (data.drawdown_curve || []).map((p) => (p.time || "").slice(0, 10));
    drawLineChart("drawdown-chart", ddLabels, dd, "#ef4444", "DD %");

    const daily = (data.daily_profit_curve || []).map((p) => p.profit_usd);
    const dailyLabels = (data.daily_profit_curve || []).map((p) => p.date);
    drawLineChart("daily-chart", dailyLabels, daily, "#f0b90b", "Daily $");

    $("trades-body").innerHTML = (data.trades || []).map((t) => `<tr>
      <td>${t.trade_num}</td>
      <td>${(t.entry_time || "").slice(0, 19)}</td>
      <td>${(t.exit_time || "").slice(0, 19)}</td>
      <td class="${t.side === "BUY" ? "opt-pos" : "opt-neg"}">${t.side}</td>
      <td>${t.entry}</td>
      <td>${t.exit_price}</td>
      <td>${t.stop_loss}</td>
      <td>${t.take_profit}</td>
      <td>${t.exit_reason}</td>
      <td class="${valClass("profit_usd", t.profit_usd)}">${t.profit_usd}</td>
      <td>${t.r_multiple}</td>
      <td>${formatDuration(t.duration_seconds)}</td>
    </tr>`).join("") || '<tr><td colspan="12" class="empty">No trades</td></tr>';

    $("detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderHeatmapGaps() {
    const gaps = [...new Set(allResults.map((r) => r.gap_filter_pct))].sort((a, b) => a - b);
    const sel = $("heatmap-gap");
    sel.innerHTML = gaps.map((g) => `<option value="${g}">${g}%</option>`).join("");
    if (gaps.length) {
      $("heatmap-panel").hidden = false;
      sel.onchange = () => drawHeatmap(parseFloat(sel.value));
      drawHeatmap(gaps[0]);
    }
  }

  async function drawHeatmap(gap) {
    if (!jobId) return;
    const data = await DSE.fetchJson(`/research/btc-optimizer/heatmap/${jobId}?gap=${gap}&metric=profit_factor`);
    const canvas = $("heatmap-canvas");
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 24, 320);
    const h = 300;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);

    const grid = data.grid || [];
    const rows = grid.length;
    const cols = rows ? grid[0].length : 0;
    if (!rows || !cols) return;

    const vals = grid.flat().filter((v) => v != null);
    const minV = Math.min(...vals);
    const maxV = Math.max(...vals);
    const padL = 48;
    const padB = 28;
    const cellW = (w - padL - 8) / cols;
    const cellH = (h - padB - 8) / rows;

    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const v = grid[r][c];
        if (v == null) continue;
        const t = maxV > minV ? (v - minV) / (maxV - minV) : 0.5;
        const red = Math.round(80 + (1 - t) * 120);
        const green = Math.round(40 + t * 160);
        ctx.fillStyle = `rgb(${red},${green},70)`;
        ctx.fillRect(padL + c * cellW, r * cellH + 4, cellW - 1, cellH - 1);
      }
    }
    ctx.fillStyle = "#b7bdc6";
    ctx.font = "10px sans-serif";
    data.max_sl_labels.forEach((lbl, i) => {
      ctx.fillText(String(lbl), padL + i * cellW, h - 8);
    });
    data.min_sl_labels.forEach((lbl, i) => {
      ctx.fillText(String(lbl), 4, i * cellH + cellH / 2 + 4);
    });
  }

  function applyPayload(payload) {
    topResults = payload.top_results || [];
    allResults = payload.results || [];
    renderComboPlan(payload.grid_plan);
    renderBest(payload.best, payload.date_tested);
    renderTopTable();
    renderHeatmapGaps();
    const has = allResults.length > 0;
    ["export-csv", "export-json", "export-top-csv", "export-all-trades", "export-trades-csv"].forEach((id) => {
      $(id).disabled = !has;
    });
  }

  async function pollProgress() {
    if (!jobId) return;
    try {
      const progress = await DSE.fetchJson(`/research/btc-optimizer/progress/${jobId}`);
      renderProgress(progress);
      const payload = await DSE.fetchJson(`/research/btc-optimizer/results/${jobId}`);
      applyPayload(payload);

      if (progress.status === "running") {
        pollTimer = setTimeout(pollProgress, 1200);
        return;
      }
      $("start-btn").disabled = false;
      $("stop-btn").disabled = true;
    } catch (err) {
      console.error(err);
      pollTimer = setTimeout(pollProgress, 3000);
    }
  }

  $("optimizer-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("start-btn").disabled = true;
    $("stop-btn").disabled = false;
    topResults = [];
    allResults = [];
    renderTopTable();
    $("best-card").hidden = true;
    $("detail-panel").hidden = true;
    $("trades-panel").hidden = true;
    try {
      const resp = await DSE.fetchJson("/research/btc-optimizer/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest()),
      });
      jobId = resp.job_id;
      renderComboPlan(resp.grid_plan);
      renderProgress({
        expected_combinations: resp.grid_plan?.expected_combinations,
        total: resp.total_combinations,
        completed: 0,
        skipped: resp.grid_plan?.skipped_combinations,
        remaining: resp.total_combinations,
        elapsed_seconds: 0,
        eta_seconds: null,
        status: "running",
      });
      pollProgress();
    } catch (err) {
      alert(err.message || "Failed to start");
      $("start-btn").disabled = false;
      $("stop-btn").disabled = true;
    }
  });

  $("stop-btn").addEventListener("click", async () => {
    if (!jobId) return;
    await DSE.fetchJson(`/research/btc-optimizer/stop/${jobId}`, { method: "POST" });
  });

  $("export-csv").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/csv`, "_blank");
  });
  $("export-json").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/json`, "_blank");
  });
  $("export-top-csv").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/top-csv`, "_blank");
  });
  $("export-all-trades").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/trades-csv`, "_blank");
  });
  $("export-trades-csv").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/trades-csv`, "_blank");
  });

  $("top-search").addEventListener("input", renderTopTable);
  $("debug-mode").addEventListener("change", () => {
    $("debug-panel").hidden = !$("debug-mode").checked;
  });

  document.querySelectorAll("#top-results-table th[data-sort]").forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir *= -1;
      else {
        sortKey = key;
        sortDir = key === "rank" ? 1 : -1;
      }
      renderTopTable();
    });
  });

  ["gap-start", "gap-end", "gap-step", "min-sl-start", "min-sl-end", "min-sl-step",
    "max-sl-start", "max-sl-end", "max-sl-step"].forEach((id) => {
    $(id).addEventListener("input", schedulePreview);
  });

  const today = new Date();
  $("end-date").value = today.toISOString().slice(0, 10);
  $("start-date").value = new Date(today.getTime() - 90 * 86400000).toISOString().slice(0, 10);
  refreshComboPreview();

  document.getElementById("mobile-menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("sidebar-open");
  });
})();
