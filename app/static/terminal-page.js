let chartEngine = null;

function showChartBootError(message) {
  const el = document.getElementById("chart-boot-error");
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
}

function clearChartBootError() {
  const el = document.getElementById("chart-boot-error");
  if (el) {
    el.hidden = true;
    el.textContent = "";
  }
}

function buildEngine() {
  if (chartEngine) return chartEngine;
  chartEngine = ChartEngine.create({
    container: document.getElementById("chart-container"),
    pnlOverlay: document.getElementById("trade-pnl-overlay"),
    tradeTooltip: document.getElementById("trade-line-tooltip"),
    legend: {
      chartSymbol: document.getElementById("chart-symbol"),
      legTime: document.getElementById("leg-time"),
      legO: document.getElementById("leg-o"),
      legH: document.getElementById("leg-h"),
      legL: document.getElementById("leg-l"),
      legC: document.getElementById("leg-c"),
      legV: document.getElementById("leg-v"),
      legSma: document.getElementById("leg-sma"),
      legHh: document.getElementById("leg-hh"),
      legLl: document.getElementById("leg-ll"),
      lastPrice: document.getElementById("last-price"),
      priceChange: document.getElementById("price-change"),
    },
    onFootnote: (text) => {
      const el = document.getElementById("signal-marker-count");
      if (el) el.textContent = text;
    },
  });
  return chartEngine;
}

function closedBySignalId(trades) {
  const map = {};
  (trades || []).forEach((t) => {
    if (t.signal_id != null) map[t.signal_id] = t;
  });
  return map;
}

function signalTfOf(signal) {
  return signal?.signal_timeframe || signal?.timeframe || null;
}

function pickPendingReviewSignal(pendingLatest, chartData, signalTimeframe) {
  const matches = (signal) =>
    signal?.status === "PENDING" && signalTfOf(signal) === signalTimeframe;

  if (matches(pendingLatest)) return pendingLatest;

  const active = chartData?.signal_context?.active_signal;
  if (active?.status === "PENDING" && signalTfOf(active) === signalTimeframe) {
    return {
      id: active.id,
      symbol: chartData.symbol,
      timeframe: active.timeframe || active.signal_timeframe,
      signal_timeframe: active.signal_timeframe || active.timeframe,
      side: active.side,
      entry: active.entry,
      stop_loss: active.stop_loss,
      take_profit: active.take_profit,
      risk_reward: active.risk_reward,
      status: active.status,
      created_at: active.created_at,
      updated_at: active.created_at,
    };
  }
  return null;
}

function setSidebarStatus(ok, message) {
  const sidebarDot = document.getElementById("sidebar-dot");
  const sidebarText = document.getElementById("sidebar-status-text");
  if (sidebarDot) sidebarDot.className = ok ? "dot ok" : "dot error";
  if (sidebarText) sidebarText.textContent = message;
}

async function fetchOptional(url, fallback = null) {
  try {
    return await DSE.fetchJson(url);
  } catch (error) {
    console.warn("[terminal] optional fetch failed:", url, error.message);
    return fallback;
  }
}

async function refreshTerminal() {
  const prefs = DSE.getPrefs();
  const { symbol, chartTimeframe, signalTimeframe, bars } = prefs;
  const signalQs = `symbol=${encodeURIComponent(symbol)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}`;
  const chartUrl = `/chart/${symbol}?timeframe=${encodeURIComponent(chartTimeframe)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}&limit=${bars}`;

  let chartData;
  try {
    chartData = await DSE.fetchJson(chartUrl);
    clearChartBootError();
  } catch (error) {
    setSidebarStatus(false, `Chart: ${error.message}`);
    showChartBootError(`Chart failed to load: ${error.message}`);
    console.error("[terminal] chart fetch failed", error);
    return;
  }

  const [
    pendingLatest,
    signalHistory,
    openPayload,
    account,
    tradeHistory,
    signalStats,
  ] = await Promise.all([
    fetchOptional(`/pending-signals/latest?${signalQs}`, {}),
    fetchOptional(
      `/signal-history?symbol=${encodeURIComponent(symbol)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}`,
      { signals: [] }
    ),
    fetchOptional("/open-positions", { positions: [] }),
    fetchOptional("/paper/account", {}),
    fetchOptional("/trade-history", { trades: [] }),
    fetchOptional("/signal-statistics", {}),
  ]);

  setSidebarStatus(true, "Live");

  const signals = signalHistory?.signals || [];
  const closedMap = closedBySignalId(tradeHistory?.trades || []);
  const openPositions = openPayload?.positions || [];
  const pendingCount = signalStats?.pending ?? 0;
  const approvedCount = signalStats?.approved ?? 0;

  if (account && Object.keys(account).length) {
    Terminal.renderTerminalHeader(account, {
      openCount: openPositions.length,
      pendingCount,
      approvedCount,
      chartTf: chartTimeframe,
      signalTf: signalTimeframe,
    });
  }

  if (signalStats && Object.keys(signalStats).length) {
    Terminal.renderMissedOpportunities(signalStats);
  }

  Terminal.renderSymbolTabs(symbol, () => refreshTerminal());
  Terminal.renderPositionCards(openPositions, null, symbol);

  const activePosition = Terminal.getActivePosition(openPositions, symbol);
  const pendingSignal = pickPendingReviewSignal(pendingLatest, chartData, signalTimeframe);

  Terminal.renderSignalReview(pendingSignal, activePosition, signalTimeframe);
  Terminal.renderPositionSizing(pendingSignal, account, activePosition);

  const engine = buildEngine();
  if (engine.ready) {
    const ctx = chartData.signal_context || {};
    const overlaySignal =
      pendingSignal?.status === "PENDING" ? pendingSignal : ctx.signal_quality || null;
    engine.update(chartData, {
      windowSize: bars,
      timeframe: chartTimeframe,
      signalTimeframe,
      symbol,
      position: activePosition,
      signalQuality: overlaySignal,
    });
    clearChartBootError();
    Terminal.updateDebugStrip(ctx, chartTimeframe, signalTimeframe, pendingSignal);
  } else {
    showChartBootError("Chart engine initializing…");
  }

  Terminal.renderRecentSignals(signals.slice(0, 8), closedMap);

  try {
    await AlertManager.checkAlerts();
  } catch (error) {
    console.warn("[terminal] alerts check failed:", error.message);
  }
}

window.refreshTerminal = refreshTerminal;

async function syncTerminalTimeframesFromServer() {
  try {
    const payload = await DSE.fetchJson("/settings/signal-timeframe");
    const signalTf = payload.signal_timeframe || "5m";
    DSE.setPrefs({ chartTimeframe: "5m", signalTimeframe: signalTf });
    document.querySelectorAll(".chart-tf-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tf === "5m");
    });
    document.querySelectorAll(".signal-tf-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tf === signalTf);
    });
  } catch (error) {
    console.warn("[terminal] timeframe sync failed:", error.message);
    DSE.setPrefs({ chartTimeframe: "5m", signalTimeframe: "5m" });
  }
}

function initTerminal() {
  if (typeof LightweightCharts === "undefined") {
    showChartBootError("Chart library loading…");
    setTimeout(initTerminal, 500);
    return;
  }

  if (!window.__terminalUiBound) {
    window.__terminalUiBound = true;
    Terminal.initMobileNav();
    Terminal.bindPositionClose(refreshTerminal);
    Terminal.bindTerminalActions(refreshTerminal);

    const prefs = DSE.getPrefs();
    const windowSelect = document.getElementById("window-select");
    if (windowSelect) windowSelect.value = String(prefs.bars);

    windowSelect?.addEventListener("change", () => {
      DSE.setPrefs({ bars: Number(windowSelect.value) });
      chartEngine?.resetPan();
      refreshTerminal();
    });

    document.getElementById("refresh-btn")?.addEventListener("click", () => {
      chartEngine?.resetPan();
      refreshTerminal();
    });

    document.getElementById("recalc-missed-btn")?.addEventListener("click", () => {
      Terminal.recalculateMissedOpportunities(() => refreshTerminal());
    });
  }

  const engine = buildEngine();
  if (!engine.init()) {
    window.addEventListener(
      "chart-engine-ready",
      () => {
        clearChartBootError();
        syncTerminalTimeframesFromServer().then(startTerminalPolling);
      },
      { once: true }
    );
    showChartBootError("Chart engine initializing…");
    return;
  }
  clearChartBootError();
  syncTerminalTimeframesFromServer().then(startTerminalPolling);
}

function startTerminalPolling() {
  Terminal.bindTimeframeButtons(() => {
    chartEngine?.resetPan();
    refreshTerminal();
  });
  refreshTerminal();
  setInterval(refreshTerminal, 10000);
}

initTerminal();
