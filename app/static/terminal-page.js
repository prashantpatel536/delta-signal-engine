let chartEngine = null;



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



async function refreshTerminal() {

  const prefs = DSE.getPrefs();

  const { symbol, chartTimeframe, signalTimeframe, bars } = prefs;

  const signalQs = `symbol=${encodeURIComponent(symbol)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}`;



  try {

    const [

      chartData,

      pendingLatest,

      signalHistory,

      openPayload,

      account,

      tradeHistory,

      signalStats,

    ] = await Promise.all([

      DSE.fetchJson(

        `/chart/${symbol}?timeframe=${encodeURIComponent(chartTimeframe)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}&limit=${bars}`

      ),

      DSE.fetchJson(`/pending-signals/latest?${signalQs}`),

      DSE.fetchJson(

        `/signal-history?symbol=${encodeURIComponent(symbol)}&signal_timeframe=${encodeURIComponent(signalTimeframe)}`

      ),

      DSE.fetchJson("/open-positions"),

      DSE.fetchJson("/paper/account"),

      DSE.fetchJson("/trade-history"),

      DSE.fetchJson("/signal-statistics"),

    ]);



    const sidebarDot = document.getElementById("sidebar-dot");

    const sidebarText = document.getElementById("sidebar-status-text");

    if (sidebarDot) sidebarDot.className = "dot ok";

    if (sidebarText) sidebarText.textContent = "Live";



    const signals = signalHistory.signals || [];

    const closedMap = closedBySignalId(tradeHistory.trades || []);

    const openPositions = openPayload.positions || [];

    const pendingCount = signalStats.pending ?? 0;

    const approvedCount = signalStats.approved ?? 0;



    Terminal.renderTerminalHeader(account, {

      openCount: openPositions.length,

      pendingCount,

      approvedCount,

      chartTf: chartTimeframe,

      signalTf: signalTimeframe,

    });

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

      Terminal.updateDebugStrip(ctx, chartTimeframe, signalTimeframe, pendingSignal);

    }



    Terminal.renderRecentSignals(signals.slice(0, 25), closedMap);



    await AlertManager.checkAlerts();

  } catch (error) {

    const sidebarDot = document.getElementById("sidebar-dot");

    const sidebarText = document.getElementById("sidebar-status-text");

    if (sidebarDot) sidebarDot.className = "dot error";

    if (sidebarText) sidebarText.textContent = error.message;

    console.error("[terminal]", error);

  }

}



window.refreshTerminal = refreshTerminal;



function initTerminal() {

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



  Terminal.bindTimeframeButtons(() => {

    chartEngine?.resetPan();

    refreshTerminal();

  });



  const engine = buildEngine();

  if (!engine.init()) {

    requestAnimationFrame(initTerminal);

    return;

  }

  refreshTerminal();

  setInterval(refreshTerminal, 10000);

}



initTerminal();

