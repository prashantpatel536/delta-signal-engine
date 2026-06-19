window.AlertManager = {
  SETTINGS_KEY: "dse-alert-settings",
  lastSignalId: null,
  lastClosedPositionId: null,
  bootstrapped: false,

  _audio: { signal: null, tp: null, sl: null },

  defaultSettings() {
    return {
      signalSound: true,
      browserNotifications: true,
      tpAlert: true,
      slAlert: true,
    };
  },

  getSettings() {
    try {
      const raw = localStorage.getItem(this.SETTINGS_KEY);
      return { ...this.defaultSettings(), ...(raw ? JSON.parse(raw) : {}) };
    } catch (_) {
      return this.defaultSettings();
    }
  },

  saveSettings(partial) {
    const next = { ...this.getSettings(), ...partial };
    localStorage.setItem(this.SETTINGS_KEY, JSON.stringify(next));
    return next;
  },

  init() {
    if (this._initialized) return;
    this._initialized = true;
    this.settings = this.getSettings();
    this._audio.signal = new Audio("/static/sounds/signal.mp3");
    this._audio.tp = new Audio("/static/sounds/tp.mp3");
    this._audio.sl = new Audio("/static/sounds/sl.mp3");
    this._audio.signal.volume = 1.0;
    this._audio.tp.volume = 1.0;
    this._audio.sl.volume = 1.0;
    this.renderSettingsPanel();
    this.requestNotificationPermission();
  },

  _ensureInit() {
    if (!this._initialized) this.init();
  },

  requestNotificationPermission() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  },

  renderSettingsPanel() {
    const el = document.getElementById("alert-settings");
    if (!el) return;
    const s = this.settings;
    el.innerHTML = `
      <div class="alert-settings-head">Alerts</div>
      <label class="alert-check"><input type="checkbox" id="alert-signal-sound"${s.signalSound ? " checked" : ""} /> Signal Sound</label>
      <label class="alert-check"><input type="checkbox" id="alert-browser-notify"${s.browserNotifications ? " checked" : ""} /> Browser Notifications</label>
      <label class="alert-check"><input type="checkbox" id="alert-tp"${s.tpAlert ? " checked" : ""} /> TP Alert</label>
      <label class="alert-check"><input type="checkbox" id="alert-sl"${s.slAlert ? " checked" : ""} /> SL Alert</label>
      <button type="button" id="alert-test-sound" class="btn-alert-test">Test Sound</button>`;

    el.querySelector("#alert-signal-sound")?.addEventListener("change", (e) => {
      this.settings = this.saveSettings({ signalSound: e.target.checked });
    });
    el.querySelector("#alert-browser-notify")?.addEventListener("change", (e) => {
      this.settings = this.saveSettings({ browserNotifications: e.target.checked });
      if (e.target.checked) this.requestNotificationPermission();
    });
    el.querySelector("#alert-tp")?.addEventListener("change", (e) => {
      this.settings = this.saveSettings({ tpAlert: e.target.checked });
    });
    el.querySelector("#alert-sl")?.addEventListener("change", (e) => {
      this.settings = this.saveSettings({ slAlert: e.target.checked });
    });
    el.querySelector("#alert-test-sound")?.addEventListener("click", () => {
      this.playSignalSound();
    });
  },

  playSignalSound() {
    this._play(this._audio.signal);
  },

  playTpSound() {
    this._play(this._audio.tp);
  },

  playSlSound() {
    this._play(this._audio.sl);
  },

  _play(audio) {
    if (!audio) return;
    audio.currentTime = 0;
    audio.play().catch((err) => console.warn("[AlertManager] audio play blocked:", err));
  },

  showNotification(title, body) {
    if (!this.settings.browserNotifications) return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    try {
      new Notification(title, {
        body,
        icon: "/static/logo.png",
      });
    } catch (err) {
      console.warn("[AlertManager] notification failed:", err);
    }
  },

  signalLabel(signal) {
    return `${signal.side} ${signal.symbol} ${signal.timeframe}`;
  },

  async checkAlerts() {
    this._ensureInit();
    try {
      const [latest, tradesPayload] = await Promise.all([
        DSE.fetchJson("/signals/latest"),
        DSE.fetchJson("/trade-history"),
      ]);
      const trades = tradesPayload.trades || [];
      this._processLatestSignal(latest);
      this._processClosedTrades(trades);
      if (!this.bootstrapped) {
        this.bootstrapped = true;
      }
    } catch (err) {
      console.warn("[AlertManager] check failed:", err);
    }
  },

  _processLatestSignal(signal) {
    if (!signal?.id) return;
    if (signal.status && signal.status !== "PENDING") {
      this.lastSignalId = signal.id;
      return;
    }

    if (!this.bootstrapped) {
      this.lastSignalId = signal.id;
      return;
    }

    if (this.lastSignalId === null) {
      this.lastSignalId = signal.id;
      return;
    }

    if (signal.id !== this.lastSignalId) {
      this.lastSignalId = signal.id;
      this.onNewSignal(signal);
    }
  },

  onNewSignal(signal) {
    const body = this.signalLabel(signal);
    if (this.settings.signalSound) {
      this.playSignalSound();
    }
    this.showNotification("New Trading Signal", body);
  },

  _processClosedTrades(trades) {
    const maxId = trades.reduce((m, t) => Math.max(m, t.id || 0), 0);

    if (!this.bootstrapped) {
      this.lastClosedPositionId = maxId;
      return;
    }

    if (this.lastClosedPositionId === null) {
      this.lastClosedPositionId = maxId;
      return;
    }

    const fresh = trades
      .filter((t) => t.id > this.lastClosedPositionId)
      .sort((a, b) => a.id - b.id);

    if (!fresh.length) return;

    this.lastClosedPositionId = Math.max(this.lastClosedPositionId, ...fresh.map((t) => t.id));

    for (const trade of fresh) {
      if (trade.exit_reason === "TP") {
        this.onTpHit(trade);
      } else if (trade.exit_reason === "SL") {
        this.onSlHit(trade);
      }
    }
  },

  onTpHit(trade) {
    const body = `${trade.symbol} · TP @ ${DSE.formatPrice(trade.exit_price)}`;
    if (this.settings.tpAlert) {
      this.playTpSound();
      this.showNotification("Take Profit Hit", body);
    }
  },

  onSlHit(trade) {
    const body = `${trade.symbol} · SL @ ${DSE.formatPrice(trade.exit_price)}`;
    if (this.settings.slAlert) {
      this.playSlSound();
      this.showNotification("Stop Loss Hit", body);
    }
  },
};

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("alert-settings")) {
    AlertManager.init();
  }
});