(() => {
  let jobId = null;
  let pollTimer = null;
  let results = [];
  let sortKey = "score";
  let sortDir = -1;

  const $ = (id) => document.getElementById(id);

  function countCombinations() {
    const ranges = [
      [$("gap-start"), $("gap-end"), $("gap-step")],
      [$("min-sl-start"), $("min-sl-end"), $("min-sl-step")],
      [$("max-sl-start"), $("max-sl-end"), $("max-sl-step")],
    ];
    let total = 1;
    for (const [s, e, st] of ranges) {
      const start = parseFloat(s.value);
      const end = parseFloat(e.value);
      const step = parseFloat(st.value);
      if (!step || step <= 0 || end < start) return 0;
      total *= Math.floor((end - start) / step + 1.0001);
    }
    const minCount = Math.floor(
      (parseFloat($("min-sl-end").value) - parseFloat($("min-sl-start").value))
        / parseFloat($("min-sl-step").value) + 1.0001
    );
    const maxCount = Math.floor(
      (parseFloat($("max-sl-end").value) - parseFloat($("max-sl-start").value))
        / parseFloat($("max-sl-step").value) + 1.0001
    );
    let valid = 0;
    const gapN = Math.floor(
      (parseFloat($("gap-end").value) - parseFloat($("gap-start").value))
        / parseFloat($("gap-step").value) + 1.0001
    );
    for (let g = 0; g < gapN; g += 1) {
      for (let mi = 0; mi < minCount; mi += 1) {
        const minSl = parseFloat($("min-sl-start").value) + mi * parseFloat($("min-sl-step").value);
        for (let ma = 0; ma < maxCount; ma += 1) {
          const maxSl = parseFloat($("max-sl-start").value) + ma * parseFloat($("max-sl-step").value);
          if (minSl <= maxSl) valid += 1;
        }
      }
    }
    return valid;
  }

  function updateComboCount() {
    const n = countCombinations();
    $("combo-count").textContent = n ? `${n.toLocaleString()} combinations` : "Invalid ranges";
  }

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
    };
  }

  function formatDuration(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${sec % 60}s`;
  }

  function renderProgress(p) {
    $("progress-panel").hidden = false;
    const pct = p.total ? Math.round((p.completed / p.total) * 100) : 0;
    $("progress-fill").style.width = `${pct}%`;
    $("progress-stats").innerHTML = `
      <span>Total: <b>${p.total}</b></span>
      <span>Done: <b>${p.completed}</b></span>
      <span>Left: <b>${p.remaining}</b></span>
      <span>Elapsed: <b>${formatDuration(Math.round(p.elapsed_seconds || 0))}</b></span>
      <span>ETA: <b>${p.eta_seconds != null ? formatDuration(Math.round(p.eta_seconds)) : "—"}</b></span>
      <span>Status: <b>${p.status}</b></span>`;
  }

  function renderBest(best) {
    if (!best) {
      $("best-card").hidden = true;
      return;
    }
    $("best-card").hidden = false;
    $("best-result-grid").innerHTML = `
      <div><span class="k">Gap</span><strong>${best.gap_filter_pct}%</strong></div>
      <div><span class="k">Min SL</span><strong>${best.min_sl_points}</strong></div>
      <div><span class="k">Max SL</span><strong>${best.max_sl_points}</strong></div>
      <div><span class="k">Profit Factor</span><strong>${best.profit_factor}</strong></div>
      <div><span class="k">Return</span><strong class="${best.return_pct >= 0 ? "up" : "down"}">${best.return_pct}%</strong></div>
      <div><span class="k">Drawdown</span><strong class="down">${best.max_drawdown_pct}%</strong></div>
      <div><span class="k">Win Rate</span><strong>${best.win_rate}%</strong></div>
      <div><span class="k">Trades</span><strong>${best.trade_count}</strong></div>
      <div><span class="k">Score</span><strong class="accent">${best.score}</strong></div>`;
  }

  function scoreSorted() {
    return [...results].sort((a, b) => (b.score || 0) - (a.score || 0));
  }

  function renderTable() {
    const q = ($("results-search").value || "").trim().toLowerCase();
    let rows = scoreSorted();
    if (q) {
      rows = rows.filter((r) =>
        `${r.gap_filter_pct} ${r.min_sl_points} ${r.max_sl_points} ${r.score}`.toLowerCase().includes(q)
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
    const body = $("results-body");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="12" class="empty">No results.</td></tr>';
      return;
    }
    const sortedAll = scoreSorted();
    body.innerHTML = rows.map((r) => {
      const tradeIdx = sortedAll.indexOf(r);
      return `<tr>
        <td>${r.gap_filter_pct}</td>
        <td>${r.min_sl_points}</td>
        <td>${r.max_sl_points}</td>
        <td>${r.profit_factor}</td>
        <td class="${r.return_pct >= 0 ? "up" : "down"}">${r.return_pct}</td>
        <td class="down">${r.max_drawdown_pct}</td>
        <td>${r.win_rate}</td>
        <td>${r.trade_count}</td>
        <td class="up">${r.avg_winner}</td>
        <td class="down">${r.avg_loser}</td>
        <td><strong>${r.score}</strong></td>
        <td><button type="button" class="btn-secondary btn-sm" data-trades="${tradeIdx}">Trades</button></td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-trades]").forEach((btn) => {
      btn.addEventListener("click", () => loadTrades(parseInt(btn.dataset.trades, 10)));
    });
  }

  async function loadTrades(resultIndex) {
    if (!jobId) return;
    const data = await DSE.fetchJson(`/research/btc-optimizer/results/${jobId}/trades/${resultIndex}`);
    const r = results[resultIndex];
    $("trades-panel").hidden = false;
    $("trades-title").textContent = `Trades — Gap ${r.gap_filter_pct}% · Min SL ${r.min_sl_points} · Max SL ${r.max_sl_points}`;
    $("trades-body").innerHTML = (data.trades || []).map((t) => `<tr>
      <td>${t.entry_time?.slice(0, 19) || "—"}</td>
      <td>${t.exit_time?.slice(0, 19) || "—"}</td>
      <td class="${t.side === "BUY" ? "up" : "down"}">${t.side}</td>
      <td>${t.entry}</td>
      <td>${t.exit_price}</td>
      <td>${t.stop_loss}</td>
      <td>${t.take_profit}</td>
      <td>${t.exit_reason}</td>
      <td class="${t.profit_usd >= 0 ? "up" : "down"}">${t.profit_usd}</td>
      <td>${t.r_multiple}</td>
      <td>${formatDuration(t.duration_seconds || 0)}</td>
    </tr>`).join("") || '<tr><td colspan="11" class="empty">No trades</td></tr>';
    $("trades-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderHeatmapGaps() {
    const gaps = [...new Set(results.map((r) => r.gap_filter_pct))].sort((a, b) => a - b);
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

  async function pollProgress() {
    if (!jobId) return;
    try {
      const progress = await DSE.fetchJson(`/research/btc-optimizer/progress/${jobId}`);
      renderProgress(progress);
      if (progress.status === "running") {
        pollTimer = setTimeout(pollProgress, 1500);
        return;
      }
      $("start-btn").disabled = false;
      $("stop-btn").disabled = true;
      const payload = await DSE.fetchJson(`/research/btc-optimizer/results/${jobId}`);
      results = payload.results || [];
      renderBest(payload.best);
      renderTable();
      renderHeatmapGaps();
      $("export-csv").disabled = !results.length;
      $("export-json").disabled = !results.length;
    } catch (err) {
      console.error(err);
      pollTimer = setTimeout(pollProgress, 3000);
    }
  }

  $("optimizer-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("start-btn").disabled = true;
    $("stop-btn").disabled = false;
    results = [];
    renderTable();
    try {
      const resp = await DSE.fetchJson("/research/btc-optimizer/start", {
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
    if (!jobId) return;
    await DSE.fetchJson(`/research/btc-optimizer/stop/${jobId}`, { method: "POST" });
  });

  $("export-csv").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/csv`, "_blank");
  });
  $("export-json").addEventListener("click", () => {
    if (jobId) window.open(`/research/btc-optimizer/export/${jobId}/json`, "_blank");
  });

  $("results-search").addEventListener("input", renderTable);

  document.querySelectorAll("#results-table th[data-sort]").forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir *= -1;
      else {
        sortKey = key;
        sortDir = -1;
      }
      renderTable();
    });
  });

  ["gap-start", "gap-end", "gap-step", "min-sl-start", "min-sl-end", "min-sl-step",
    "max-sl-start", "max-sl-end", "max-sl-step"].forEach((id) => {
    $(id).addEventListener("input", updateComboCount);
  });

  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 90 * 86400000).toISOString().slice(0, 10);
  $("start-date").value = start;
  $("end-date").value = end;
  updateComboCount();

  document.getElementById("mobile-menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("sidebar-open");
  });
})();
