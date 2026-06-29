(() => {
  let jobId = null;
  let pollTimer = null;
  let topResults = [];
  let allResults = [];
  let previewTimer = null;

  const $ = (id) => document.getElementById(id);

  function buildRequest() {
    return {
      symbol: $("symbol").value,
      timeframe: $("timeframe").value,
      months_back: parseInt($("months-back").value, 10),
      ambiguous: $("ambiguous").value,
      sma: {
        start: parseInt($("sma-start").value, 10),
        end: parseInt($("sma-end").value, 10),
        step: parseInt($("sma-step").value, 10),
      },
      stop: {
        start: parseFloat($("stop-start").value),
        end: parseFloat($("stop-end").value),
        step: parseFloat($("stop-step").value),
      },
      target: {
        start: parseFloat($("target-start").value),
        end: parseFloat($("target-end").value),
        step: parseFloat($("target-step").value),
      },
    };
  }

  function sortBy() {
    return $("sort-by").value || "score";
  }

  function formatDuration(sec) {
    const s = Math.max(0, Math.round(sec || 0));
    const m = Math.floor(s / 60);
    if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
    return `${m}m ${s % 60}s`;
  }

  async function refreshPreview() {
    try {
      const plan = await DSE.fetchJson("/research/sma-optimizer/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest()),
      });
      $("combo-summary").textContent = `${plan.combination_formula} → ${plan.final_combinations?.toLocaleString()} combinations`;
    } catch {
      $("combo-summary").textContent = "Invalid ranges";
    }
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 300);
  }

  function renderProgress(p) {
    $("progress-panel").hidden = false;
    const pct = p.total ? Math.round((p.completed / p.total) * 100) : 0;
    $("progress-fill").style.width = `${pct}%`;
    $("progress-stats").innerHTML = `
      <span>Total: <b>${p.total}</b></span>
      <span>Done: <b>${p.completed}</b></span>
      <span>Left: <b>${p.remaining}</b></span>
      <span>Elapsed: <b>${formatDuration(p.elapsed_seconds)}</b></span>
      <span>ETA: <b>${p.eta_seconds != null ? formatDuration(p.eta_seconds) : "—"}</b></span>
      <span>Status: <b>${p.status}</b></span>`;
    const c = p.current_param || {};
    $("current-param").textContent = c.sma_length != null
      ? `Current: SMA <b>${c.sma_length}</b> · Stop <b>${c.stop_points}</b> · Target <b>${c.target_points}</b>`
      : "";
  }

  function valCls(v, goodHigh = true) {
    if (goodHigh) return v > 0 ? "opt-pos" : v < 0 ? "opt-neg" : "opt-warn";
    return v <= 10 ? "opt-pos" : v <= 25 ? "opt-warn" : "opt-neg";
  }

  function renderTop() {
    const q = ($("top-search").value || "").trim().toLowerCase();
    let rows = [...topResults];
    if (q) {
      rows = rows.filter((r) =>
        `${r.rank} ${r.sma_length} ${r.stop_points} ${r.target_points}`.toLowerCase().includes(q)
      );
    }
    const body = $("top-body");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="11" class="empty">No results yet.</td></tr>';
      $("top-panel").hidden = true;
      return;
    }
    $("top-panel").hidden = false;
    body.innerHTML = rows.map((r) => {
      const idx = allResults.findIndex((x) =>
        x.sma_length === r.sma_length && x.stop_points === r.stop_points && x.target_points === r.target_points
      );
      return `<tr>
        <td><strong>${r.rank}</strong></td>
        <td>${r.sma_length}</td>
        <td>${r.target_points}</td>
        <td>${r.stop_points}</td>
        <td>${r.total_trades}</td>
        <td class="${valCls(r.win_rate)}">${r.win_rate}</td>
        <td class="${valCls(r.profit_factor)}">${r.profit_factor}</td>
        <td class="${valCls(r.expected_value)}">${r.expected_value}</td>
        <td class="${valCls(r.net_points)}">${r.net_points}</td>
        <td class="${valCls(r.score)}"><strong>${r.score}</strong></td>
        <td><button type="button" class="btn-secondary btn-sm" data-trades="${idx}">Trades</button></td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-trades]").forEach((btn) => {
      btn.addEventListener("click", () => loadTrades(parseInt(btn.dataset.trades, 10)));
    });
  }

  async function loadTrades(resultIndex) {
    if (!jobId || resultIndex < 0) return;
    const data = await DSE.fetchJson(
      `/research/sma-optimizer/results/${jobId}/trades/${resultIndex}?sort_by=${sortBy()}`
    );
    const p = data.params || {};
    $("trades-panel").hidden = false;
    $("trades-title").textContent = `Rank ${data.rank ?? "—"} — SMA ${p.sma_length} · Target ${p.target_points} · Stop ${p.stop_points}`;
    $("trades-body").innerHTML = (data.trades || []).map((t) => `<tr>
      <td>${(t.entry_time || "").slice(0, 19)}</td>
      <td class="${t.direction === "BUY" ? "opt-pos" : "opt-neg"}">${t.direction}</td>
      <td>${t.entry}</td>
      <td>${t.exit_price}</td>
      <td>${t.target}</td>
      <td>${t.stop}</td>
      <td>${t.bars}</td>
      <td class="${t.result === "WIN" ? "opt-pos" : "opt-neg"}">${t.result}</td>
      <td class="${valCls(t.pnl_points)}">${t.pnl_points}</td>
    </tr>`).join("") || '<tr><td colspan="9" class="empty">No trades</td></tr>';
    $("trades-panel").scrollIntoView({ behavior: "smooth" });
  }

  function drawHeatmap(data) {
    const canvas = $("heatmap-canvas");
    const ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const w = Math.max(wrap.clientWidth - 24, 320);
    const h = 300;
    canvas.width = w;
    canvas.height = h;
    ctx.fillStyle = "#0b0e11";
    ctx.fillRect(0, 0, w, h);

    if (data.y_values && data.x_labels) {
      const vals = data.y_values;
      const labels = data.x_labels;
      const maxV = Math.max(...vals, 1e-9);
      const minV = Math.min(...vals, 0);
      const pad = { l: 40, r: 8, t: 16, b: 32 };
      const plotW = w - pad.l - pad.r;
      const plotH = h - pad.t - pad.b;
      const step = plotW / Math.max(labels.length - 1, 1);
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 2;
      ctx.beginPath();
      labels.forEach((_, i) => {
        const x = pad.l + i * step;
        const y = pad.t + plotH - ((vals[i] - minV) / (maxV - minV || 1)) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = "#9ca3af";
      ctx.font = "9px sans-serif";
      ctx.fillText(String(labels[0]), pad.l, h - 8);
      ctx.fillText(String(labels[labels.length - 1]), w - 36, h - 8);
      return;
    }

    const grid = data.grid || [];
    if (!grid.length) return;
    const rows = grid.length;
    const cols = grid[0].length;
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
    ctx.font = "9px sans-serif";
    (data.x_labels || []).forEach((lbl, i) => {
      if (i % Math.max(1, Math.floor(cols / 8)) === 0) {
        ctx.fillText(String(lbl), padL + i * cellW, h - 8);
      }
    });
    (data.y_labels || []).forEach((lbl, i) => {
      if (i % Math.max(1, Math.floor(rows / 8)) === 0) {
        ctx.fillText(String(lbl), 4, i * cellH + cellH / 2 + 4);
      }
    });
  }

  async function refreshHeatmap() {
    if (!jobId) return;
    const chart = $("heatmap-chart").value;
    const metric = chart.includes("pf") ? "profit_factor" : chart.includes("net") ? "net_points" : "win_rate";
    try {
      const data = await DSE.fetchJson(
        `/research/sma-optimizer/heatmap/${jobId}?chart=${chart}&metric=${metric}`
      );
      $("heatmap-panel").hidden = false;
      drawHeatmap(data);
    } catch (e) {
      console.warn("heatmap", e);
    }
  }

  function applyPayload(payload) {
    topResults = payload.top_results || [];
    allResults = payload.results || [];
    renderTop();
    refreshHeatmap();
    const has = allResults.length > 0;
    ["export-csv", "export-top", "export-xlsx", "export-json"].forEach((id) => {
      $(id).disabled = !has;
    });
  }

  async function pollProgress() {
    if (!jobId) return;
    try {
      const progress = await DSE.fetchJson(`/research/sma-optimizer/progress/${jobId}`);
      renderProgress(progress);
      const payload = await DSE.fetchJson(
        `/research/sma-optimizer/results/${jobId}?sort_by=${sortBy()}`
      );
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
    try {
      const resp = await DSE.fetchJson("/research/sma-optimizer/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequest()),
      });
      jobId = resp.job_id;
      renderProgress({
        total: resp.total_combinations,
        completed: 0,
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
    if (jobId) await DSE.fetchJson(`/research/sma-optimizer/stop/${jobId}`, { method: "POST" });
  });

  $("sort-by").addEventListener("change", async () => {
    if (!jobId) return;
    const payload = await DSE.fetchJson(
      `/research/sma-optimizer/results/${jobId}?sort_by=${sortBy()}`
    );
    applyPayload(payload);
  });

  $("heatmap-chart").addEventListener("change", refreshHeatmap);
  $("top-search").addEventListener("input", renderTop);

  $("export-csv").addEventListener("click", () => {
    if (jobId) window.open(`/research/sma-optimizer/export/${jobId}/csv?sort_by=${sortBy()}`, "_blank");
  });
  $("export-top").addEventListener("click", () => {
    if (jobId) window.open(`/research/sma-optimizer/export/${jobId}/top-csv?sort_by=${sortBy()}`, "_blank");
  });
  $("export-xlsx").addEventListener("click", () => {
    if (jobId) window.open(`/research/sma-optimizer/export/${jobId}/xlsx?sort_by=${sortBy()}`, "_blank");
  });
  $("export-json").addEventListener("click", () => {
    if (jobId) window.open(`/research/sma-optimizer/export/${jobId}/json?sort_by=${sortBy()}`, "_blank");
  });

  ["symbol", "timeframe", "months-back", "ambiguous",
    "sma-start", "sma-end", "sma-step",
    "stop-start", "stop-end", "stop-step",
    "target-start", "target-end", "target-step"].forEach((id) => {
    $(id).addEventListener("input", schedulePreview);
    $(id).addEventListener("change", schedulePreview);
  });

  window.addEventListener("resize", () => { if (jobId) refreshHeatmap(); });

  document.getElementById("mobile-menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("sidebar-open");
  });

  refreshPreview();
})();
