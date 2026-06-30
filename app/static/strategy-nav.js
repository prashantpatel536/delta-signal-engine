/** Shared strategy navigation — Dashboard / Paper / Backtest / Performance / Research / Settings */
(() => {
  const NAV = {
    sol_reversal: {
      brand: "SOL",
      sub: "REVERSAL",
      dashboard: "/sol",
      paper: "/sol",
      backtest: "/sol/backtest",
      performance: "/sol#stats-panel",
      research: "/sol#research",
      settings: "/sol#settings",
    },
    btc_trend: {
      brand: "Δ",
      sub: "TERMINAL",
      dashboard: "/btc",
      paper: "/btc",
      backtest: "/btc/backtest",
      performance: "/performance",
      research: "/research/btc-optimizer",
      settings: "/settings",
    },
  };

  function detectStrategyId() {
    const p = window.location.pathname;
    if (p.startsWith("/sol")) return "sol_reversal";
    if (p.startsWith("/btc")) return "btc_trend";
    const m = p.match(/\/backtest\/([\w_]+)/);
    if (m) return m[1];
    return "btc_trend";
  }

  function renderSidebar(strategyId, active) {
    const cfg = NAV[strategyId] || NAV.btc_trend;
    const el = document.getElementById("strategy-sidebar");
    if (!el) return;
    const items = [
      ["dashboard", "◎", "Dashboard", cfg.dashboard],
      ["paper", "◉", "Paper Trading", cfg.paper],
      ["backtest", "▶", "Backtest", cfg.backtest],
      ["performance", "◔", "Performance", cfg.performance],
      ["research", "◫", "Research", cfg.research],
      ["settings", "⚙", "Settings", cfg.settings],
    ];
    el.innerHTML = `
      <div class="sidebar-brand">
        <div class="brand-icon">${cfg.brand}</div>
        <div><div class="brand-title">${cfg.brand}</div><div class="brand-sub">${cfg.sub}</div></div>
      </div>
      <nav class="sidebar-nav">
        <a class="nav-item" href="/"><span class="nav-icon">⌂</span> Strategy Hub</a>
        ${items.map(([key, icon, label, href]) =>
          `<a class="nav-item ${active === key ? "active" : ""}" href="${href}"><span class="nav-icon">${icon}</span> ${label}</a>`
        ).join("")}
      </nav>`;
  }

  window.StrategyNav = { detectStrategyId, renderSidebar, NAV };
})();
