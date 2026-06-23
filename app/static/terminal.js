window.Terminal = {
  TIMEFRAMES: ["1m", "5m", "15m", "1h"],

  initMobileNav() {
    const toggle = document.getElementById("mobile-menu-toggle");
    const sidebar = document.querySelector(".sidebar");
    if (!toggle || !sidebar) return;
    toggle.addEventListener("click", () => {
      sidebar.classList.toggle("sidebar-open");
    });
    document.addEventListener("click", (e) => {
      if (!sidebar.contains(e.target) && e.target !== toggle) {
        sidebar.classList.remove("sidebar-open");
      }
    });
  },

  bindChartTimeframeButtons(onChange) {
    const buttons = document.querySelectorAll(".chart-tf-btn");
    const prefs = DSE.getPrefs();

    const setActive = (tf) => {
      buttons.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tf === tf);
      });
    };

    setActive(prefs.chartTimeframe);
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const tf = btn.dataset.tf;
        DSE.setPrefs({ chartTimeframe: tf });
        setActive(tf);
        onChange?.(DSE.getPrefs());
      });
    });
  },

  bindSignalTimeframeButtons(onChange) {
    const buttons = document.querySelectorAll(".signal-tf-btn");
    const prefs = DSE.getPrefs();

    const setActive = (tf) => {
      buttons.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tf === tf);
      });
    };

    const syncServer = async (tf) => {
      try {
        await DSE.fetchJson("/settings/signal-timeframe", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ signal_timeframe: tf }),
        });
      } catch (error) {
        console.warn("[signal-tf] server sync failed:", error.message);
      }
    };

    setActive(prefs.signalTimeframe);
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const tf = btn.dataset.tf;
        DSE.setPrefs({ signalTimeframe: tf });
        setActive(tf);
        syncServer(tf);
        onChange?.(DSE.getPrefs());
      });
    });
  },

  bindTimeframeButtons(onChange) {
    this.bindChartTimeframeButtons(onChange);
    this.bindSignalTimeframeButtons(onChange);
  },

  formatSignalAge(timestamp) {
    if (!timestamp) return "—";
    const ms = Date.now() - new Date(timestamp).getTime();
    if (ms < 0) return "0 min";
    const min = Math.floor(ms / 60000);
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    return `${h}h ${min % 60}m`;
  },

  positionMetrics(position) {
    const entry = Number(position.entry);
    const sl = Number(position.stop_loss);
    const tp = Number(position.take_profit);
    const qty = Number(position.quantity || 1);
    const isLong = position.side === "BUY";
    const risk = isLong ? (entry - sl) * qty : (sl - entry) * qty;
    const reward = isLong ? (tp - entry) * qty : (entry - tp) * qty;
    const rr = risk > 0 ? reward / risk : Number(position.risk_reward) || 0;
    return { risk: Math.abs(risk), reward: Math.abs(reward), rr };
  },

  renderAccountBar(account) {
    this.renderTerminalHeader(account, {});
  },

  renderTerminalHeader(account, { openCount = 0, pendingCount = 0, approvedCount = 0, chartTf = "5m", signalTf = "5m" } = {}) {
    const el = document.getElementById("terminal-header-bar") || document.getElementById("account-bar");
    if (!el || !account) return;
    const unrealClass = account.unrealized_pnl >= 0 ? "up" : "down";
    const realClass = account.realized_pnl >= 0 ? "up" : "down";
    el.innerHTML = `
      <span class="acct-pill">Balance: <strong>$${DSE.formatPrice(account.total_balance)}</strong></span>
      <span class="acct-pill">Available: <strong>$${DSE.formatPrice(account.available_margin)}</strong></span>
      <span class="acct-pill">Used Margin: <strong>$${DSE.formatPrice(account.used_margin)}</strong></span>
      <span class="acct-pill ${unrealClass}">Unrealized PnL: <strong>${DSE.formatPnl(account.unrealized_pnl)}</strong></span>
      <span class="acct-pill ${realClass}">Realized PnL: <strong>${DSE.formatPnl(account.realized_pnl)}</strong></span>
      <span class="acct-pill">Chart TF: <strong>${chartTf}</strong></span>
      <span class="acct-pill accent">Signal TF: <strong>${signalTf}</strong></span>
      <span class="acct-pill">Pending: <strong>${pendingCount}</strong></span>
      <span class="acct-pill">Approved: <strong>${approvedCount}</strong></span>
      <span class="acct-pill">Open Positions: <strong>${openCount}</strong></span>`;
  },

  formatMissedPts(value) {
    const n = Number(value ?? 0);
    if (Number.isNaN(n)) return "0 pts";
    const sign = n >= 0 ? "+" : "-";
    const abs = Math.abs(n);
    const formatted = Math.abs(abs - Math.round(abs)) < 0.05
      ? String(Math.round(abs))
      : abs.toFixed(1);
    return `${sign}${formatted} pts`;
  },

  formatMissedUsd(value) {
    const n = Number(value ?? 0);
    if (Number.isNaN(n)) return "$0";
    const sign = n >= 0 ? "+" : "-";
    return `${sign}$${Math.abs(n).toFixed(2)}`;
  },

  renderMissedOpportunities(summary) {
    const totalEl = document.getElementById("missed-opportunities-total");
    const winnersEl = document.getElementById("missed-winners");
    const losersEl = document.getElementById("missed-losers");
    const bySymbolEl = document.getElementById("missed-by-symbol");
    const netUsdEl = document.getElementById("missed-net-usd");
    const netRoeEl = document.getElementById("missed-net-roe");
    if (!winnersEl || !summary) return;

    const winners = Number(summary.missed_winners ?? 0);
    const losers = Number(summary.missed_losers ?? 0);
    const total = Number(summary.missed_opportunities ?? winners + losers);
    const net = Number(summary.net_missed_profit ?? 0);
    const netUsd = Number(summary.net_missed_pnl_usd ?? 0);
    const netRoe = Number(summary.net_missed_roe_pct ?? 0);
    const bySymbol = summary.by_symbol || [];

    if (totalEl) totalEl.textContent = total;
    winnersEl.textContent = winners;
    losersEl.textContent = losers;
    if (netUsdEl) {
      netUsdEl.textContent = this.formatMissedUsd(netUsd);
      netUsdEl.className = `missed-stat-value ${netUsd >= 0 ? "up" : "down"}`;
    }
    if (netRoeEl) {
      netRoeEl.textContent = `${netRoe >= 0 ? "+" : ""}${netRoe.toFixed(2)}%`;
      netRoeEl.className = `missed-stat-value ${netRoe >= 0 ? "up" : "down"}`;
    }

    if (bySymbolEl) {
      const rows = bySymbol.map(
        (row) => `
        <div class="missed-symbol-row">
          <span class="missed-symbol-label">${row.label} Net Missed</span>
          <span class="missed-symbol-dual">
            <span class="missed-symbol-value ${Number(row.net_missed_profit) >= 0 ? "up" : "down"}">${this.formatMissedPts(row.net_missed_profit)}</span>
            <span class="missed-symbol-value muted">${this.formatMissedUsd(row.net_missed_pnl_usd)}</span>
          </span>
        </div>`
      );
      rows.push(`
        <div class="missed-symbol-row missed-symbol-total">
          <span class="missed-symbol-label">Total Net Missed</span>
          <span class="missed-symbol-dual">
            <span class="missed-symbol-value ${net >= 0 ? "up" : "down"}">${this.formatMissedPts(net)}</span>
            <span class="missed-symbol-value ${netUsd >= 0 ? "up" : "down"}">${this.formatMissedUsd(netUsd)}</span>
          </span>
        </div>`);
      bySymbolEl.innerHTML = rows.join("");
    }
  },

  async recalculateMissedOpportunities(onComplete) {
    const btn = document.getElementById("recalc-missed-btn");
    const statusEl = document.getElementById("recalc-missed-status");
    if (!btn || !statusEl) return;

    btn.disabled = true;
    statusEl.hidden = false;
    statusEl.className = "missed-recalc-status";
    statusEl.textContent = "Starting recalculation…";

    try {
      const response = await fetch("/admin/recalculate-all", {
        method: "POST",
      });
      if (!response.ok || !response.body) {
        throw new Error(`Recalculation failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "progress") {
            statusEl.textContent = `Recalculating missed ${event.current} / ${event.total}…`;
          } else if (event.type === "phase" && event.phase === "trades") {
            statusEl.textContent = "Recalculating closed trades…";
          } else if (event.type === "complete") {
            finalPayload = event;
          } else if (event.type === "error") {
            throw new Error(event.message || "Recalculation failed");
          }
        }
      }

      if (!finalPayload) {
        throw new Error("Recalculation finished without a result");
      }

      const { summary, trades, missed } = finalPayload;
      statusEl.className = "missed-recalc-status ok";
      const missedChanged = missed?.changed ?? finalPayload.changed ?? 0;
      const missedTotal = missed?.recalculated ?? finalPayload.recalculated ?? 0;
      const tradeTotal = trades?.recalculated ?? 0;
      statusEl.textContent = `Done — missed ${missedChanged}/${missedTotal}, trades ${tradeTotal}`;
      if (summary) {
        this.renderMissedOpportunities(summary);
      }
      onComplete?.(finalPayload);
    } catch (error) {
      statusEl.className = "missed-recalc-status error";
      statusEl.textContent = `Error: ${error.message}`;
    } finally {
      btn.disabled = false;
    }
  },

  renderSymbolTabs(activeShort, onSelect) {
    const el = document.getElementById("symbol-tabs");
    if (!el) return;
    const symbols = ["BTC", "ETH", "SOL"];
    el.innerHTML = symbols
      .map(
        (sym) =>
          `<button type="button" class="symbol-tab${sym === activeShort ? " active" : ""}" data-symbol="${sym}">${sym}USD</button>`
      )
      .join("");
    el.querySelectorAll(".symbol-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        DSE.setPrefs({ symbol: btn.dataset.symbol });
        onSelect?.(btn.dataset.symbol);
      });
    });
  },

  signalDisplayStatus(signal, closedBySignalId) {
    if (signal.status === "TP_HIT") return "TP HIT";
    if (signal.status === "SL_HIT") return "SL HIT";
    if (signal.status === "MISSED_WINNER") return "MISSED WINNER";
    if (signal.status === "MISSED_LOSER") return "MISSED LOSER";
    const trade = closedBySignalId?.[signal.id];
    if (trade?.exit_reason === "TP") return "TP HIT";
    if (trade?.exit_reason === "SL") return "SL HIT";
    return signal.status;
  },

  renderRecentSignals(signals, closedBySignalId) {
    const body = document.getElementById("recent-signals-body");
    if (!body) return;
    if (!signals?.length) {
      body.innerHTML = `<tr><td colspan="8" class="empty">No signals yet</td></tr>`;
      return;
    }
    body.innerHTML = signals
      .map((s) => {
        const status = this.signalDisplayStatus(s, closedBySignalId);
        const statusClass = status.toLowerCase().replace(/\s+/g, "-");
        return `
        <tr>
          <td>${DSE.formatIsoTime(s.created_at)}</td>
          <td>${s.symbol.replace("USDT", "")}</td>
          <td><span class="signal-type ${s.side.toLowerCase()}">${s.side === "BUY" ? "▲" : "▼"} ${s.side}</span></td>
          <td>${DSE.formatPrice(s.entry)}</td>
          <td>${DSE.formatPrice(s.stop_loss)}</td>
          <td>${DSE.formatPrice(s.take_profit)}</td>
          <td>${Number(s.risk_reward).toFixed(1)}</td>
          <td><span class="status-tag ${statusClass}">${status}</span></td>
        </tr>`;
      })
      .join("");
  },

  directionFromSide(side) {
    return side === "BUY" ? "LONG" : "SHORT";
  },

  renderSignalReview(signal, openPosition, signalTimeframe) {
    const el = document.getElementById("signal-review");
    if (!el) return;

    this._activePendingSignal = null;

    if (!signal) {
      el.innerHTML = `
        <div class="panel-head"><h2>Risk Matrix Signal</h2></div>
        <div class="empty">Waiting for next signal on ${signalTimeframe || "—"}</div>`;
      return;
    }

    this._activePendingSignal = signal;
    const sideClass = signal.side === "BUY" ? "buy" : "sell";
    const direction = this.directionFromSide(signal.side);
    const age = this.formatSignalAge(signal.created_at);
    const sourceTf = signal.signal_timeframe || signal.timeframe || signalTimeframe || "—";
    const rp = signal.risk_profile || {};
    const liqStatus = rp.liq_status || "—";
    const liqClass = liqStatus === "SAFE" ? "liq-safe" : liqStatus === "CAUTION" ? "liq-caution" : "liq-danger";
    const statusBadge = signal.status === "APPROVED" ? "approved" : signal.status === "EXPIRED" ? "expired" : "pending";

    el.innerHTML = `
      <div class="panel-head"><h2>Risk Matrix Signal</h2><span class="badge ${statusBadge}">${signal.status}</span></div>
      <div class="review-side ${sideClass}">${signal.side === "BUY" ? "▲ BUY" : "▼ SELL"} · ${signal.symbol}</div>
      <div class="liq-banner ${liqClass}">Liq: ${liqStatus}${rp.liq_buffer != null ? ` (${Number(rp.liq_buffer).toFixed(2)}×)` : ""} · Auto-evaluated</div>
      <dl class="sq-grid review-grid">
        <div><dt>Entry</dt><dd>${DSE.formatPrice(signal.entry)}</dd></div>
        <div><dt>Stop Loss</dt><dd>${DSE.formatPrice(rp.stop_loss ?? signal.stop_loss)}</dd></div>
        <div><dt>Take Profit</dt><dd>${DSE.formatPrice(rp.take_profit ?? signal.take_profit)}</dd></div>
        <div><dt>Liquidation</dt><dd>${rp.liquidation_price != null ? DSE.formatPrice(rp.liquidation_price) : "—"}</dd></div>
        <div><dt>SL Distance</dt><dd>${rp.sl_distance_points != null ? Number(rp.sl_distance_points).toFixed(2) : "—"} pts</dd></div>
        <div><dt>TP Distance</dt><dd>${rp.tp_distance_points != null ? Number(rp.tp_distance_points).toFixed(2) : "—"} pts</dd></div>
        <div><dt>Margin Used</dt><dd>${rp.margin_used != null ? `$${Number(rp.margin_used).toFixed(2)}` : "—"}</dd></div>
        <div><dt>Position Value</dt><dd>${rp.position_value != null ? `$${Number(rp.position_value).toFixed(2)}` : "—"}</dd></div>
        <div><dt>Contracts</dt><dd>${rp.contracts != null ? Number(rp.contracts) : "—"} × ${rp.contract_size ?? "—"}</dd></div>
        <div><dt>Expected Loss</dt><dd>${rp.expected_loss_usd != null ? `$${Number(rp.expected_loss_usd).toFixed(2)} (${Number(rp.expected_loss_pct || 0).toFixed(1)}%)` : "—"}</dd></div>
        <div><dt>Expected Profit</dt><dd>${rp.expected_profit_usd != null ? `$${Number(rp.expected_profit_usd).toFixed(2)} (${Number(rp.expected_profit_pct || 0).toFixed(1)}%)` : "—"}</dd></div>
        <div><dt>Expected ROE</dt><dd>${rp.expected_roe != null ? `${Number(rp.expected_roe).toFixed(1)}%` : "—"}</dd></div>
        <div><dt>RR Ratio</dt><dd>${rp.risk_reward != null ? Number(rp.risk_reward).toFixed(1) : Number(signal.risk_reward).toFixed(1)}</dd></div>
        <div><dt>Leverage</dt><dd>${rp.leverage ?? 25}x / ${rp.margin_percent ?? 50}%</dd></div>
        <div><dt>Signal TF</dt><dd>${sourceTf}</dd></div>
        <div><dt>Age</dt><dd>${age}</dd></div>
      </dl>
      <p class="sizing-hint">Signals auto-execute via risk matrix — no manual approval.</p>`;
  },

  renderPositionSizing(signal, account, hasOpenPosition) {
    const el = document.getElementById("position-sizing");
    if (!el) return;

    if (hasOpenPosition || !signal) {
      el.innerHTML = `
        <div class="panel-head"><h2>Position Sizing</h2></div>
        <div class="empty">${hasOpenPosition ? "Sizing locked while position open" : "Configure after a pending signal arrives"}</div>`;
      return;
    }

    this._activePendingSignal = signal;
    this._lastAccount = account;
    const lev = this._orderState.leverage;
    const pct = this._orderState.marginPercent;
    const avail = account?.available_margin ?? 0;
    const margin = avail * (pct / 100);
    const posVal = margin * lev;
    const qty = signal.entry > 0 ? posVal / Number(signal.entry) : 0;
    const short = DSE.shortSymbol(signal.symbol);

    el.innerHTML = `
      <div class="panel-head"><h2>Position Sizing</h2></div>
      <label class="doc-label" for="doc-lev">Leverage</label>
      <div class="doc-select-wrap">
        <select id="doc-lev" class="doc-select">
          ${[10, 20, 25, 50].map((l) => `<option value="${l}"${l === lev ? " selected" : ""}>${l}x</option>`).join("")}
        </select>
      </div>
      <div class="doc-label">Margin Allocation</div>
      <div class="doc-size-row">
        ${[10, 25, 50, 75, 100].map((p) => `<button type="button" class="doc-size-btn${p === pct ? " active" : ""}" data-pct="${p}">${p}%</button>`).join("")}
      </div>
      <div class="doc-divider"></div>
      <div class="doc-row"><span>Margin Used</span><strong id="doc-margin">${DSE.formatPrice(margin)} USD</strong></div>
      <div class="doc-row"><span>Position Value</span><strong id="doc-pos-val">${DSE.formatPrice(posVal)} USD</strong></div>
      <div class="doc-row"><span>Quantity</span><strong id="doc-qty" class="doc-readonly">${DSE.formatQuantity(qty, short)}</strong></div>
      <div id="doc-warn" class="doc-warn hidden">Insufficient Margin</div>
      <p class="sizing-hint">Position Value = Margin × Leverage · Qty = Position Value ÷ Entry</p>`;

    this._bindSizingControls(signal);
  },

  _bindSizingControls(signal) {
    const levSelect = document.getElementById("doc-lev");
    levSelect?.addEventListener("change", () => {
      this._orderState.leverage = Number(levSelect.value);
      this._recalcSizingPreview(signal);
    });
    document.querySelectorAll(".doc-size-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._orderState.marginPercent = Number(btn.dataset.pct);
        document.querySelectorAll(".doc-size-btn").forEach((b) => b.classList.toggle("active", b === btn));
        this._recalcSizingPreview(signal);
      });
    });
    this._recalcSizingPreview(signal);
  },

  async _recalcSizingPreview(signal) {
    const marginEl = document.getElementById("doc-margin");
    const posEl = document.getElementById("doc-pos-val");
    const qtyEl = document.getElementById("doc-qty");
    const warnEl = document.getElementById("doc-warn");
    const approveBtn = document.getElementById("btn-signal-approve");
    const lev = this._orderState.leverage;
    const pct = this._orderState.marginPercent;

    try {
      const preview = await DSE.fetchJson("/paper/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: signal.symbol,
          side: signal.side,
          entry: signal.entry,
          margin_percent: pct,
          leverage: lev,
          stop_loss: signal.stop_loss,
          take_profit: signal.take_profit,
        }),
      });
      if (marginEl) marginEl.textContent = `${DSE.formatPrice(preview.margin_used)} USD`;
      if (posEl) posEl.textContent = `${DSE.formatPrice(preview.position_value)} USD`;
      if (qtyEl) {
        qtyEl.textContent = DSE.formatQuantity(preview.quantity, DSE.shortSymbol(signal.symbol));
      }
      if (warnEl) warnEl.classList.toggle("hidden", preview.sufficient_margin);
      if (approveBtn) approveBtn.disabled = !preview.sufficient_margin;
    } catch (_) {
      const avail = this._lastAccount?.available_margin ?? 0;
      const margin = avail * (pct / 100);
      const posVal = margin * lev;
      const qty = signal.entry > 0 ? posVal / Number(signal.entry) : 0;
      if (marginEl) marginEl.textContent = `${DSE.formatPrice(margin)} USD`;
      if (posEl) posEl.textContent = `${DSE.formatPrice(posVal)} USD`;
      if (qtyEl) qtyEl.textContent = DSE.formatQuantity(qty, DSE.shortSymbol(signal.symbol));
      if (approveBtn) approveBtn.disabled = margin <= 0 || margin > avail;
      if (warnEl) warnEl.classList.toggle("hidden", margin > 0 && margin <= avail);
    }
  },

  bindTerminalActions(refreshFn) {
    document.addEventListener("click", async (event) => {
      const approveBtn = event.target.closest("#btn-signal-approve");
      const rejectBtn = event.target.closest("#btn-signal-reject");
      if (!approveBtn && !rejectBtn) return;

      const signal = this._activePendingSignal;
      if (!signal) return;

      const button = approveBtn || rejectBtn;
      button.disabled = true;

      try {
        if (rejectBtn) {
          await DSE.fetchJson(`/signal/${signal.id}/reject`, { method: "POST" });
        } else {
          await DSE.fetchJson(`/signal/${signal.id}/approve-trade`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              leverage: this._orderState.leverage,
              margin_percent: this._orderState.marginPercent,
              stop_loss: signal.stop_loss,
              take_profit: signal.take_profit,
            }),
          });
        }
        await refreshFn();
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    });
  },

  _activePendingSignal: null,

  _orderTicketKey: null,
  _lastAccount: null,

  _orderState: {
    leverage: 25,
    marginPercent: 50,
    symbol: null,
    signalKey: null,
  },

  _signalIsBuy(quality) {
    return quality?.side === "BUY";
  },

  _approveLabel(quality) {
    return this._signalIsBuy(quality) ? "APPROVE BUY" : "APPROVE SELL";
  },

  _asset(symbol) {
    return DSE.assetConfig(DSE.shortSymbol(symbol));
  },

  renderOrderTicket(quality, symbol, hasOpenPosition, account) {
    const el = document.getElementById("order-ticket");
    if (!el) return;

    if (hasOpenPosition) {
      this._orderTicketKey = null;
      el.innerHTML = `<div class="doc-empty">Position open — close before new entry</div>`;
      return;
    }

    if (!quality) {
      this._orderTicketKey = null;
      el.innerHTML = `<div class="doc-empty">Waiting for signal…</div>`;
      return;
    }

    const signalKey = `${symbol}:${quality.side}:${quality.entry}:${quality.timestamp}`;
    const sameCard =
      this._orderTicketKey === signalKey && document.getElementById("doc-open");

    if (symbol !== this._orderState.symbol) {
      this._orderState.symbol = symbol;
      this._orderTicketKey = null;
    }

    if (signalKey !== this._orderState.signalKey) {
      this._orderState.signalKey = signalKey;
    }

    if (sameCard) {
      this._patchOrderCard(account, quality);
      return;
    }

    this._orderTicketKey = signalKey;
    this._lastAccount = account;
    this._renderOrderCard(quality, symbol, account);
  },

  _renderOrderCard(quality, symbol, account) {
    this._lastAccount = account;
    const el = document.getElementById("order-ticket");
    if (!el) return;

    const lev = this._orderState.leverage;
    const pct = this._orderState.marginPercent;
    const isBuy = this._signalIsBuy(quality);
    const sideLabel = isBuy ? "LONG" : "SHORT";
    const sideClass = isBuy ? "buy" : "sell";
    const avail = account?.available_margin ?? 0;
    const margin = avail * (pct / 100);
    const posVal = margin * lev;
    const qty = lev > 0 && quality.entry > 0 ? posVal / Number(quality.entry) : 0;

    el.innerHTML = `
      <div class="delta-order-card">
        <div class="doc-signal-head ${sideClass}">
          <span class="doc-signal-symbol">${DSE.deltaSymbol(symbol)}</span>
          <span class="doc-signal-side">${sideLabel}</span>
        </div>
        <div class="doc-signal-source">Signal · ${isBuy ? "▲ BUY" : "▼ SELL"} · review &amp; approve</div>

        <label class="doc-label" for="doc-lev">Leverage</label>
        <div class="doc-select-wrap">
          <select id="doc-lev" class="doc-select" aria-label="Leverage">
            ${[1, 2, 5, 10, 20, 25, 50].map((l) => `<option value="${l}"${l === lev ? " selected" : ""}>${l}x</option>`).join("")}
          </select>
        </div>

        <div class="doc-label">Use Available Balance</div>
        <div class="doc-size-row" role="group" aria-label="Margin allocation">
          ${[10, 25, 50, 75, 100].map((p) => `<button type="button" class="doc-size-btn${p === pct ? " active" : ""}" data-pct="${p}">${p}%</button>`).join("")}
        </div>

        <div class="doc-divider"></div>

        <div class="doc-row">
          <span>Margin Used</span>
          <strong id="doc-margin">${DSE.formatPrice(margin)} USD</strong>
        </div>
        <div class="doc-row">
          <span>Position Value</span>
          <strong id="doc-pos-val">${DSE.formatPrice(posVal)} USD</strong>
        </div>
        <div class="doc-row">
          <span>Quantity</span>
          <strong id="doc-qty" class="doc-readonly">${DSE.formatQuantity(qty, DSE.shortSymbol(symbol))}</strong>
        </div>

        <div class="doc-divider"></div>

        <div class="doc-label">Add TP / SL</div>
        <label class="doc-label" for="doc-tp">TP</label>
        <input type="number" id="doc-tp" class="doc-input" step="any" value="${quality.take_profit}" />
        <label class="doc-label" for="doc-sl">SL</label>
        <input type="number" id="doc-sl" class="doc-input" step="any" value="${quality.stop_loss}" />

        <div class="doc-entry-hint">Entry @ ${DSE.formatPrice(quality.entry)}</div>

        <div id="doc-warn" class="doc-warn hidden">Insufficient Margin</div>
        <button type="button" id="doc-open" class="doc-open ${isBuy ? "long" : "short"}">
          ${this._approveLabel(quality)}
        </button>
      </div>`;

    this._bindOrderCard(quality, symbol);
  },

  _patchOrderCard(account, quality) {
    this._lastAccount = account;
    this._recalcOrderCard(quality);
  },

  _bindOrderCard(quality, symbol) {
    const levSelect = document.getElementById("doc-lev");
    const openBtn = document.getElementById("doc-open");
    const sizeBtns = document.querySelectorAll(".doc-size-btn");

    levSelect?.addEventListener("change", () => {
      this._orderState.leverage = Number(levSelect.value);
      this._recalcOrderCard(quality);
    });

    sizeBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        this._orderState.marginPercent = Number(btn.dataset.pct);
        sizeBtns.forEach((b) => b.classList.toggle("active", b === btn));
        this._recalcOrderCard(quality);
      });
    });

    document.getElementById("doc-tp")?.addEventListener("input", () => this._recalcOrderCard(quality));
    document.getElementById("doc-sl")?.addEventListener("input", () => this._recalcOrderCard(quality));

    openBtn?.addEventListener("click", async () => {
      openBtn.disabled = true;
      try {
        await DSE.fetchJson("/paper/open", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: DSE.deltaSymbol(symbol),
            side: quality.side,
            entry: quality.entry,
            margin_percent: this._orderState.marginPercent,
            leverage: this._orderState.leverage,
            stop_loss: Number(document.getElementById("doc-sl")?.value),
            take_profit: Number(document.getElementById("doc-tp")?.value),
          }),
        });
        if (window.refreshTerminal) await window.refreshTerminal();
      } catch (error) {
        alert(error.message);
        openBtn.disabled = false;
      }
    });

    this._recalcOrderCard(quality);
  },

  async _recalcOrderCard(quality) {
    const marginEl = document.getElementById("doc-margin");
    const posEl = document.getElementById("doc-pos-val");
    const qtyEl = document.getElementById("doc-qty");
    const warnEl = document.getElementById("doc-warn");
    const openBtn = document.getElementById("doc-open");
    const account = this._lastAccount;
    const symbol = this._orderState.symbol;
    const side = quality.side;
    const lev = this._orderState.leverage;
    const pct = this._orderState.marginPercent;

    try {
      const preview = await DSE.fetchJson("/paper/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: DSE.deltaSymbol(symbol),
          side,
          entry: quality.entry,
          margin_percent: pct,
          leverage: lev,
          stop_loss: Number(document.getElementById("doc-sl")?.value ?? quality.stop_loss),
          take_profit: Number(document.getElementById("doc-tp")?.value ?? quality.take_profit),
        }),
      });

      if (marginEl) marginEl.textContent = `${DSE.formatPrice(preview.margin_used)} USD`;
      if (posEl) posEl.textContent = `${DSE.formatPrice(preview.position_value)} USD`;
      if (qtyEl) {
        qtyEl.textContent = DSE.formatQuantity(preview.quantity, DSE.shortSymbol(symbol));
      }
      if (warnEl) warnEl.classList.toggle("hidden", preview.sufficient_margin);
      if (openBtn) openBtn.disabled = !preview.sufficient_margin;
    } catch (_) {
      const avail = account?.available_margin ?? 0;
      const margin = avail * (pct / 100);
      const posVal = margin * lev;
      const qty = Number(quality.entry) > 0 ? posVal / Number(quality.entry) : 0;
      if (marginEl) marginEl.textContent = `${DSE.formatPrice(margin)} USD`;
      if (posEl) posEl.textContent = `${DSE.formatPrice(posVal)} USD`;
      if (qtyEl) qtyEl.textContent = DSE.formatQuantity(qty, DSE.shortSymbol(symbol));
      if (openBtn) openBtn.disabled = margin <= 0 || margin > avail;
      if (warnEl) warnEl.classList.toggle("hidden", margin > 0 && margin <= avail);
    }
  },

  renderCompactStats(signalStats, paperStats, pendingCount) {
    const el = document.getElementById("compact-stats");
    if (!el) return;
    const signals = signalStats?.total ?? 0;
    const positions = paperStats?.open_positions ?? 0;
    const pnl = paperStats?.net_pnl ?? 0;
    const winRate = paperStats?.total_trades ? `${paperStats.win_rate}%` : "0%";
    const pnlClass = pnl >= 0 ? "up" : "down";
    el.innerHTML = `
      <span class="stat-pill">Signals: <strong>${signals}</strong></span>
      <span class="stat-pill accent">Pending: <strong>${pendingCount ?? signalStats?.pending ?? 0}</strong></span>
      <span class="stat-pill">Positions: <strong>${positions}</strong></span>
      <span class="stat-pill ${pnlClass}">PnL: <strong>${DSE.formatPnl(pnl)}</strong></span>
      <span class="stat-pill">Win Rate: <strong>${winRate}</strong></span>
    `;
  },

  renderWatchlist(items, activeShort, onSelect) {
    const el = document.getElementById("watchlist");
    if (!el) return;
    if (!items?.length) {
      el.innerHTML = `<div class="empty">Loading watchlist…</div>`;
      return;
    }
    el.innerHTML = items
      .map((item) => {
        const active = item.short_symbol === activeShort ? " active" : "";
        const chgClass = item.change >= 0 ? "up" : "down";
        const sign = item.change >= 0 ? "+" : "";
        const sigLabel = item.signal || "NONE";
        const sigClass = item.signal ? item.signal.toLowerCase() : "none";
        return `
        <button type="button" class="watch-item watch-item-compact${active}" data-symbol="${item.short_symbol}">
          <span class="watch-symbol">${item.symbol.replace("USDT", "")}</span>
          <span class="watch-change ${chgClass}">${sign}${item.change_pct.toFixed(1)}%</span>
          <span class="watch-signal ${sigClass}">${sigLabel}</span>
        </button>`;
      })
      .join("");

    el.querySelectorAll(".watch-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sym = btn.dataset.symbol;
        DSE.setPrefs({ symbol: sym });
        onSelect?.(sym);
      });
    });
  },

  renderSignalQuality(quality, timeframe) {
    const el = document.getElementById("signal-quality");
    if (!el) return;
    if (!quality) {
      el.innerHTML = `
        <div class="sq-head">Signal Quality</div>
        <div class="empty sq-empty">No active signal on latest bar</div>
        <div class="sq-meta">Signal Source: <strong>${timeframe}</strong></div>`;
      return;
    }
    const sideClass = quality.side === "BUY" ? "buy" : "sell";
    const age = this.formatSignalAge(quality.timestamp);
    const reasons = (quality.reasons || [])
      .map((r) => `<li>✓ ${r}</li>`)
      .join("");
    el.innerHTML = `
      <div class="sq-head">Signal Quality</div>
      <div class="sq-side ${sideClass}">${quality.side === "BUY" ? "▲ BUY" : "▼ SELL"}</div>
      <div class="sq-meta">Signal Source: <strong>${quality.timeframe || timeframe}</strong></div>
      <div class="sq-meta">Signal Age: <strong>${age}</strong></div>
      <dl class="sq-grid">
        <div><dt>Entry</dt><dd>${DSE.formatPrice(quality.entry)}</dd></div>
        <div><dt>SL</dt><dd>${DSE.formatPrice(quality.stop_loss)}</dd></div>
        <div><dt>TP</dt><dd>${DSE.formatPrice(quality.take_profit)}</dd></div>
        <div><dt>RR</dt><dd>${Number(quality.risk_reward).toFixed(1)}</dd></div>
      </dl>
      <div class="sq-reason-label">Reason:</div>
      <ul class="sq-reasons">${reasons}</ul>`;
  },

  renderPositionCards(positions, container, symbolFilter) {
    const el = container || document.getElementById("position-cards");
    if (!el) return;
    const delta = symbolFilter ? DSE.deltaSymbol(symbolFilter) : null;
    const filtered = delta ? positions.filter((p) => p.symbol === delta) : positions;
    const countEl = document.getElementById("open-count");
    if (countEl) countEl.textContent = String(filtered.length);

    el.classList.toggle("no-scroll", filtered.length <= 1);

    if (!filtered.length) {
      el.innerHTML = `<div class="empty">No open positions</div>`;
      return;
    }

    el.innerHTML = filtered
      .map((p) => {
        const sideLabel = p.side === "BUY" ? "LONG" : "SHORT";
        const sideClass = p.side === "BUY" ? "side-long" : "side-short";
        const pnlClass = Number(p.unrealized_pnl) >= 0 ? "up" : "down";
        const roeClass = Number(p.roe) >= 0 ? "up" : "down";
        const short = DSE.shortSymbol(p.symbol);
        return `
        <article class="position-card" data-id="${p.id}">
          <div class="pos-head">
            <strong>${p.symbol}</strong>
            <span class="${sideClass}">${sideLabel}</span>
          </div>
          <dl class="pos-grid pos-grid-delta">
            <div><dt>Entry</dt><dd>${DSE.formatPrice(p.entry)}</dd></div>
            <div><dt>Current</dt><dd>${DSE.formatPrice(p.current_price)}</dd></div>
            <div><dt>Margin Used</dt><dd>${DSE.formatPrice(p.margin_used)}</dd></div>
            <div><dt>Leverage</dt><dd>${Number(p.leverage).toFixed(0)}x</dd></div>
            <div><dt>Pos Value</dt><dd>${DSE.formatPrice(p.position_value)}</dd></div>
            <div><dt>Quantity</dt><dd>${DSE.formatQuantity(p.quantity, short)}</dd></div>
            <div><dt>PnL</dt><dd class="${pnlClass}">${DSE.formatPnl(p.unrealized_pnl)}</dd></div>
            <div><dt>ROE</dt><dd class="${roeClass}">${p.roe != null ? `${Number(p.roe).toFixed(2)}%` : "—"}</dd></div>
            <div><dt>TP</dt><dd class="pos-level">
              <span>${DSE.formatPrice(p.take_profit)}</span>
              <button type="button" class="btn-edit-sm" data-action="edit-tp" data-id="${p.id}" data-value="${p.take_profit}">Edit</button>
            </dd></div>
            <div><dt>SL</dt><dd class="pos-level">
              <span>${DSE.formatPrice(p.stop_loss)}</span>
              <button type="button" class="btn-edit-sm" data-action="edit-sl" data-id="${p.id}" data-value="${p.stop_loss}">Edit</button>
            </dd></div>
            <div><dt>RR</dt><dd>${Number(p.risk_reward || 0).toFixed(2)}</dd></div>
          </dl>
          <div class="pos-quick-actions">
            <button type="button" class="btn-quick" data-action="breakeven" data-id="${p.id}">Move SL to Breakeven</button>
            <button type="button" class="btn-close-sm btn-close-position" data-id="${p.id}">Close Position</button>
          </div>
        </article>`;
      })
      .join("");
  },

  getActivePosition(positions, symbol) {
    const delta = DSE.deltaSymbol(symbol);
    return (positions || []).find((p) => p.symbol === delta) || null;
  },

  renderPending(signals, listEl, countEl) {
    const list = listEl || document.getElementById("pending-list");
    const count = countEl || document.getElementById("pending-count");
    if (count) count.textContent = String(signals.length);
    if (!list) return;

    list.classList.toggle("no-scroll", signals.length <= 2);

    if (!signals.length) {
      list.innerHTML = `<li class="empty">No pending signals</li>`;
      return;
    }

    list.innerHTML = signals
      .map(
        (s) => `
        <li class="pending-card compact" data-id="${s.id}">
          <div class="pending-head">
            <strong>${s.symbol}</strong>
            <span class="signal-type ${s.side.toLowerCase()}">${s.side === "BUY" ? "▲" : "▼"} ${s.side}</span>
          </div>
          <div class="pending-meta">${s.timeframe} · ${DSE.formatIsoTime(s.created_at)}</div>
          <div class="pending-inline">
            <span>E ${DSE.formatPrice(s.entry)}</span>
            <span>SL ${DSE.formatPrice(s.stop_loss)}</span>
            <span>TP ${DSE.formatPrice(s.take_profit)}</span>
          </div>
          <div class="pending-actions">
            <button type="button" class="btn-approve" data-action="approve" data-id="${s.id}">Approve</button>
            <button type="button" class="btn-reject" data-action="reject" data-id="${s.id}">Reject</button>
          </div>
        </li>`
      )
      .join("");
  },

  bindPendingActions(refreshFn) {
    const list = document.getElementById("pending-list");
    if (!list) return;
    list.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      button.disabled = true;
      try {
        await DSE.fetchJson(`/signal/${button.dataset.id}/${button.dataset.action}`, {
          method: "POST",
        });
        await refreshFn();
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    });
  },

  bindPositionClose(refreshFn) {
    PositionManagement.bind(document.getElementById("position-cards"), refreshFn);
  },

  updateDebugStrip(signalContext, chartTimeframe, signalTimeframe, pendingSignal) {
    const chartTfEl = document.getElementById("debug-chart-tf");
    const signalTfEl = document.getElementById("debug-signal-tf");
    const liveRefreshEl = document.getElementById("debug-live-refresh");

    const chartTf = chartTimeframe || signalContext?.chart_timeframe || "—";
    const signalTf =
      signalTimeframe ||
      pendingSignal?.signal_timeframe ||
      pendingSignal?.timeframe ||
      signalContext?.signal_timeframe ||
      signalContext?.active_signal?.signal_timeframe ||
      signalContext?.active_signal?.timeframe ||
      signalContext?.signal_quality?.timeframe ||
      "—";

    if (chartTfEl) chartTfEl.textContent = chartTf;
    if (signalTfEl) signalTfEl.textContent = signalTf;

    if (liveRefreshEl) {
      const ts = signalContext?.last_live_price_refresh || signalContext?.last_refresh;
      if (!ts) {
        liveRefreshEl.textContent = "waiting…";
      } else {
        const ageSec = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
        liveRefreshEl.textContent = ageSec < 60 ? `${ageSec}s ago` : DSE.formatIsoTime(ts);
      }
    }
  },
};
