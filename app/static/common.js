window.DSE = {
  PREFS_KEY: "dse-prefs",
  PREFS_VERSION: 3,
  SYMBOL_MAP: { BTC: "BTCUSDT", ETH: "ETHUSDT", SOL: "SOLUSDT" },

  defaultPrefs() {
    return {
      symbol: "ETH",
      chartTimeframe: "5m",
      signalTimeframe: "5m",
      bars: 100,
      prefsVersion: this.PREFS_VERSION,
    };
  },

  getPrefs() {
    try {
      const raw = localStorage.getItem(this.PREFS_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      const defaults = this.defaultPrefs();

      // One-time migration: older saves often stuck chart + signal on 1m
      if ((parsed.prefsVersion || 0) < this.PREFS_VERSION) {
        const migrated = {
          ...defaults,
          symbol: parsed.symbol || defaults.symbol,
          bars: parsed.bars || defaults.bars,
          chartTimeframe: "5m",
          signalTimeframe: "5m",
          prefsVersion: this.PREFS_VERSION,
        };
        localStorage.setItem(this.PREFS_KEY, JSON.stringify(migrated));
        return migrated;
      }

      return {
        ...defaults,
        symbol: parsed.symbol ?? defaults.symbol,
        bars: parsed.bars ?? defaults.bars,
        chartTimeframe: parsed.chartTimeframe ?? defaults.chartTimeframe,
        signalTimeframe: parsed.signalTimeframe ?? defaults.signalTimeframe,
        prefsVersion: this.PREFS_VERSION,
      };
    } catch (_) {
      return this.defaultPrefs();
    }
  },

  setPrefs(partial) {
    const next = { ...this.getPrefs(), ...partial };
    localStorage.setItem(this.PREFS_KEY, JSON.stringify(next));
    return next;
  },

  deltaSymbol(shortOrFull) {
    const upper = String(shortOrFull || "ETH").toUpperCase();
    if (this.SYMBOL_MAP[upper]) return this.SYMBOL_MAP[upper];
    if (upper.endsWith("USDT")) return upper;
    return this.SYMBOL_MAP.ETH;
  },

  shortSymbol(deltaSymbol) {
    const upper = String(deltaSymbol || "").toUpperCase();
    for (const [short, full] of Object.entries(this.SYMBOL_MAP)) {
      if (full === upper) return short;
    }
    return upper.replace("USDT", "") || "ETH";
  },

  assetConfig(shortSymbol) {
    const configs = {
      BTC: { unit: "BTC", defaultQty: 0.001, step: 0.001, decimals: 3 },
      ETH: { unit: "ETH", defaultQty: 0.05, step: 0.01, decimals: 2 },
      SOL: { unit: "SOL", defaultQty: 1, step: 0.1, decimals: 1 },
    };
    return configs[shortSymbol] || configs.ETH;
  },

  bindToolbar(selectors, onChange) {
    const prefs = this.getPrefs();
    const symbolSelect = document.querySelector(selectors.symbol);
    const timeframeSelect = selectors.timeframe ? document.querySelector(selectors.timeframe) : null;
    const windowSelect = document.querySelector(selectors.bars);
    const refreshBtn = document.querySelector(selectors.refresh);

    if (symbolSelect) symbolSelect.value = prefs.symbol;
    if (timeframeSelect) timeframeSelect.value = prefs.timeframe;
    if (windowSelect) windowSelect.value = String(prefs.bars);

    const emit = () => {
      const next = this.setPrefs({
        symbol: symbolSelect?.value || prefs.symbol,
        timeframe: timeframeSelect?.value || prefs.timeframe,
        bars: Number(windowSelect?.value || prefs.bars),
      });
      if (onChange) onChange(next);
    };

    symbolSelect?.addEventListener("change", emit);
    timeframeSelect?.addEventListener("change", emit);
    windowSelect?.addEventListener("change", emit);
    refreshBtn?.addEventListener("click", () => onChange?.(this.getPrefs()));
  },

  readToolbar(selectors) {
    const symbolSelect = selectors.symbol ? document.querySelector(selectors.symbol) : null;
    const timeframeSelect = selectors.timeframe ? document.querySelector(selectors.timeframe) : null;
    const windowSelect = selectors.bars ? document.querySelector(selectors.bars) : null;
    const prefs = this.getPrefs();
    return {
      symbol: symbolSelect?.value || prefs.symbol,
      timeframe: timeframeSelect?.value || prefs.timeframe,
      bars: Number(windowSelect?.value || prefs.bars),
    };
  },

  markActiveNav() {
    const page = document.body.dataset.page;
    if (!page) return;
    document.querySelectorAll(".sidebar-nav .nav-item").forEach((link) => {
      link.classList.toggle("active", link.dataset.nav === page);
    });
  },

  async fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
      let detail = await response.text();
      try {
        detail = JSON.parse(detail).detail || detail;
      } catch (_) {}
      throw new Error(`${response.status}: ${detail}`);
    }
    return response.json();
  },

  formatPrice(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    if (n >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return n.toFixed(2);
  },

  formatTime(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleString();
  },

  formatIsoTime(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  },

  formatPnl(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    const sign = n >= 0 ? "+" : "";
    return `${sign}${this.formatPrice(n)}`;
  },

  formatQuantity(value, shortSymbol) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const { decimals, unit } = this.assetConfig(shortSymbol);
    return `${Number(value).toFixed(decimals)} ${unit}`;
  },

  statusTag(status) {
    const st = String(status || "").toLowerCase();
    return `<span class="status-tag ${st}">${status}</span>`;
  },
};

document.addEventListener("DOMContentLoaded", () => DSE.markActiveNav());
