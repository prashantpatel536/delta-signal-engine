(() => {
  const INTERVAL_SECONDS = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600 };
  const VISIBLE_BARS_DEFAULT = 80;
  const MAX_SIGNAL_MARKERS = 8;
  const PRICE_MARGIN_PCT = 0.05;
  const PRICE_SCALE_HIT_WIDTH = 64;
  const NO_AUTOSCALE = () => null;

  const TERMINAL = {
    bg: "#0b0e11",
    grid: "#2b3139",
    border: "#363d47",
    text: "#b7bdc6",
    crosshair: "#848e9c",
    crosshairLabel: "#363a45",
    up: "#14d990",
    down: "#ff5b6a",
    sma: "#f5c518",
    hh: "#42a5f5",
    ll: "#ff5b6a",
    volUp: "rgba(20, 217, 144, 0.55)",
    volDown: "rgba(255, 91, 106, 0.55)",
  };

  function formatPrice(value) {
    if (value == null || Number.isNaN(value)) return "—";
    const abs = Math.abs(Number(value));
    const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : 4;
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function formatVolume(value) {
    if (value == null || Number.isNaN(value)) return "—";
    const v = Number(value);
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
    return v.toFixed(0);
  }

  function formatTime(unixSec) {
    if (!unixSec) return "—";
    return new Date(unixSec * 1000).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function prepareCandleSeriesData(rawCandles, expectedIntervalSec, requestedCount) {
    const byTime = new Map();
    let skippedInvalid = 0;
    let duplicateTimestamps = 0;

    for (const raw of rawCandles) {
      const time = Math.trunc(Number(raw.time));
      const open = Number(raw.open);
      const high = Number(raw.high);
      const low = Number(raw.low);
      const close = Number(raw.close);
      const volume = Number(raw.volume) || 0;

      if (
        !Number.isFinite(time) ||
        !Number.isFinite(open) ||
        !Number.isFinite(high) ||
        !Number.isFinite(low) ||
        !Number.isFinite(close)
      ) {
        skippedInvalid += 1;
        continue;
      }

      if (byTime.has(time)) duplicateTimestamps += 1;
      byTime.set(time, {
        time,
        open,
        high: Math.max(high, open, close),
        low: Math.min(low, open, close),
        close,
        volume,
      });
    }

    const candles = Array.from(byTime.values()).sort((a, b) => a.time - b.time);
    const pipeline = {
      api_received: rawCandles.length,
      after_frontend_prepare: candles.length,
      skipped_invalid: skippedInvalid,
      duplicate_timestamps: duplicateTimestamps,
      frontend_removed: rawCandles.length - candles.length - skippedInvalid,
    };

    if (requestedCount != null && candles.length !== requestedCount) {
      console.warn(`[chart] Candle count mismatch: requested ${requestedCount}, got ${candles.length}`, pipeline);
    } else {
      console.info("[chart] Candle pipeline:", pipeline);
    }

    return { candles, pipeline };
  }

  function visualCandle(candle, haMode = false) {
    const open = Number(candle.open);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const close = Number(candle.close);
    if (high > low) {
      const span = high - low;
      const bodySpan = Math.abs(open - close);
      const minBody = haMode ? span * 0.08 : 0;
      if (!haMode && open !== close) return { open, high, low, close };
      if (haMode && bodySpan > minBody && bodySpan > 1e-10) {
        return { open, high: Math.max(high, open, close), low: Math.min(low, open, close), close };
      }
      const body = Math.max(
        span * (haMode ? 0.5 : 0.12),
        Math.abs(close) * (haMode ? 0.0003 : 0.00008),
        haMode ? 0.08 : 0.02,
      );
      const mid = (open + close) / 2 || close;
      return {
        open: mid + body / 2,
        high,
        low,
        close: mid - body / 2,
      };
    }
    const mid = close || open || 0;
    const pad = Math.max(Math.abs(mid) * (haMode ? 0.00035 : 0.00012), haMode ? 0.1 : 0.05);
    return { open: mid + pad / 2, high: mid + pad, low: mid - pad, close: mid - pad / 2 };
  }

  function buildChartDisplaySeries(candles, alignedSma, alignedHh, alignedLl, intervalSec, haMode = false) {
    if (!candles.length) {
      return {
        displayCandles: [],
        volumeData: [],
        smaData: [],
        hhData: [],
        llData: [],
        realToDisplay: new Map(),
        displayToReal: new Map(),
        realCandles: new Map(),
      };
    }

    const baseTime = candles[0].time;
    const realToDisplay = new Map();
    const displayToReal = new Map();
    const realCandles = new Map();
    const displayCandles = [];
    const volumeData = [];
    const smaData = [];
    const hhData = [];
    const llData = [];

    candles.forEach((c, i) => {
      const displayTime = baseTime + i * intervalSec;
      realToDisplay.set(c.time, displayTime);
      displayToReal.set(displayTime, c.time);
      realCandles.set(c.time, c);
      const v = visualCandle(c, haMode);
      const bullish = c.close >= c.open;
      displayCandles.push({ time: displayTime, open: v.open, high: v.high, low: v.low, close: v.close });
      volumeData.push({
        time: displayTime,
        value: c.volume,
        color: bullish ? TERMINAL.volUp : TERMINAL.volDown,
      });
      if (alignedSma[i] != null) smaData.push({ time: displayTime, value: Number(alignedSma[i]) });
      if (alignedHh[i] != null) hhData.push({ time: displayTime, value: Number(alignedHh[i]) });
      if (alignedLl[i] != null) llData.push({ time: displayTime, value: Number(alignedLl[i]) });
    });

    return {
      displayCandles,
      volumeData,
      smaData,
      hhData,
      llData,
      realToDisplay,
      displayToReal,
      realCandles,
    };
  }

  function snapSignalTime(unix, realToDisplay) {
    if (!unix || !realToDisplay.size) return null;
    const exact = realToDisplay.get(unix);
    if (exact) return exact;
    let bestReal = null;
    let bestD = Infinity;
    for (const real of realToDisplay.keys()) {
      const d = Math.abs(real - unix);
      if (d < bestD) {
        bestD = d;
        bestReal = real;
      }
    }
    return bestD <= 600 ? realToDisplay.get(bestReal) : null;
  }

  function buildArrowMarkers(chartSignals, realToDisplay, maxMarkers = MAX_SIGNAL_MARKERS) {
    const sorted = [...chartSignals]
      .filter((s) => s.candle_time)
      .sort((a, b) => Number(b.candle_time) - Number(a.candle_time))
      .slice(0, maxMarkers);

    const seen = new Set();
    const markers = [];
    for (const sig of sorted) {
      const realTime = Math.trunc(Number(sig.candle_time));
      const displayTime = snapSignalTime(realTime, realToDisplay);
      if (!displayTime || seen.has(displayTime)) continue;
      seen.add(displayTime);
      const isBuy = sig.signal === "BUY";
      const statusLabel = formatSignalStatus(sig.status);
      const sideLabel = isBuy ? "BUY" : "SELL";
      const tfLabel = sig.timeframe || sig.signal_timeframe || "";
      const base = tfLabel ? `${sideLabel} (${tfLabel})` : sideLabel;
      const text = statusLabel ? `${base} · ${statusLabel}` : base;
      const isEntry = sig.status === "ENTRY";
      const isExit = sig.status === "TP_HIT" || sig.status === "SL_HIT" || sig.status === "LOCK_HIT";
      const isCondition = sig.status === "HA_CONDITION" || sig.status === "HA_SIGNAL";
      if (!isEntry && !isExit && !isCondition) continue;
      markers.push({
        time: displayTime,
        position: isBuy ? "belowBar" : "aboveBar",
        shape: isExit ? "circle" : isBuy ? "arrowUp" : "arrowDown",
        color: isEntry ? "#2962ff" : isExit ? TERMINAL.down : "#848e9c",
        text,
        size: isCondition ? 0 : 1,
      });
    }
    return markers.sort((a, b) => a.time - b.time);
  }

  function snapTradeTime(unix, realToDisplay) {
    if (!unix || !realToDisplay.size) return null;
    let bestReal = null;
    let bestD = Infinity;
    for (const real of realToDisplay.keys()) {
      const d = Math.abs(real - unix);
      if (d < bestD) {
        bestD = d;
        bestReal = real;
      }
    }
    return bestD <= 600 ? realToDisplay.get(bestReal) : null;
  }

  function buildTradeMarkers(trades, realToDisplay) {
    const sorted = [...(trades || [])].sort(
      (a, b) => Date.parse(b.closed_at || b.opened_at || 0) - Date.parse(a.closed_at || a.opened_at || 0),
    );
    const markers = [];
    const seen = new Set();
    for (const tr of sorted.slice(0, MAX_SIGNAL_MARKERS)) {
      const isBuy = (tr.side || "").toUpperCase() === "BUY";
      const pnl = Number(tr.pnl_pct ?? 0);
      const win = pnl >= 0;
      const entryUnix = Math.trunc(Date.parse(tr.opened_at || tr.entry_time || "") / 1000);
      const exitUnix = Math.trunc(Date.parse(tr.closed_at || tr.exit_time || "") / 1000);
      const entryT = snapTradeTime(entryUnix, realToDisplay);
      const exitT = snapTradeTime(exitUnix, realToDisplay);
      if (entryT && !seen.has(`e-${entryT}`)) {
        seen.add(`e-${entryT}`);
        markers.push({
          time: entryT,
          position: isBuy ? "belowBar" : "aboveBar",
          shape: isBuy ? "arrowUp" : "arrowDown",
          color: "#2962ff",
          text: `${isBuy ? "BUY" : "SELL"} entry`,
          size: 1,
        });
      }
      if (exitT && !seen.has(`x-${exitT}`)) {
        seen.add(`x-${exitT}`);
        markers.push({
          time: exitT,
          position: isBuy ? "aboveBar" : "belowBar",
          shape: "circle",
          color: win ? TERMINAL.up : TERMINAL.down,
          text: win ? `+${Math.abs(pnl).toFixed(2)}% price` : `${pnl.toFixed(2)}% price`,
          size: 1,
        });
      }
    }
    return markers.sort((a, b) => a.time - b.time);
  }

  function formatSignalStatus(status) {
    if (!status) return "";
    if (status === "TP_HIT") return "TP HIT";
    if (status === "SL_HIT") return "SL HIT";
    if (status === "LOCK_HIT") return "LOCK";
    if (status === "ENTRY") return "entry";
    if (status === "HA_CONDITION") return "condition";
    if (status === "HA_SIGNAL") return "Signal";
    return status;
  }

  class ChartEngine {
    constructor(options) {
      this.container = options.container;
      this.legend = options.legend || {};
      this.showIndicators = options.showIndicators !== false;
      this.maxSignalMarkers = options.maxSignalMarkers || MAX_SIGNAL_MARKERS;
      this.onFootnote = options.onFootnote;
      this.onTitle = options.onTitle;
      this.onPriceChange = options.onPriceChange;
      this.chart = null;
      this.candleSeries = null;
      this.volumeSeries = null;
      this.smaSeries = null;
      this.hhSeries = null;
      this.llSeries = null;
      this.ready = false;
      this.userHasPanned = false;
      this.userHasManualPriceScale = false;
      this.isProgrammaticScroll = false;
      this._lastSymbol = null;
      this._lastPositionId = null;
      this.context = {
        displayToReal: new Map(),
        realCandles: new Map(),
        realToDisplay: new Map(),
        displayCandles: [],
        latestCandle: null,
      };
      this._resizeObserver = null;
      this.tradePriceLines = [];
      this.signalPriceLines = [];
      this.activePosition = null;
      this.tradeLevels = null;
      this.signalLevels = null;
      this.pnlOverlayEl = options.pnlOverlay || null;
      this.tradeTooltipEl = options.tradeTooltip || null;
    }

    clearTradeLines() {
      if (!this.candleSeries) return;
      for (const line of this.tradePriceLines) {
        this.candleSeries.removePriceLine(line);
      }
      this.tradePriceLines = [];
    }

    clearSignalLines() {
      if (!this.candleSeries) return;
      for (const line of this.signalPriceLines) {
        this.candleSeries.removePriceLine(line);
      }
      this.signalPriceLines = [];
    }

    clearOverlayLines() {
      this.clearTradeLines();
      this.clearSignalLines();
    }

    setSignalOverlay(signalQuality) {
      this.clearSignalLines();
      this.signalLevels = null;

      if (!signalQuality || !this.candleSeries) {
        this.refreshPriceScale();
        return;
      }

      const entry = Number(signalQuality.entry);
      const sl = Number(signalQuality.stop_loss);
      const tp = Number(signalQuality.take_profit);
      const side = signalQuality.side === "SELL" ? "SELL" : "BUY";
      const statusLabel = formatSignalStatus(signalQuality.status);
      const statusSuffix = statusLabel ? ` (${statusLabel})` : "";
      this.signalLevels = { entry, sl, tp };

      const lines = [
        { price: entry, color: TERMINAL.sma, title: `Signal ${side} Entry${statusSuffix}` },
        { price: tp, color: TERMINAL.hh, title: `Signal TP${statusSuffix}` },
        { price: sl, color: TERMINAL.ll, title: `Signal SL${statusSuffix}` },
      ];

      for (const spec of lines) {
        if (!Number.isFinite(spec.price)) continue;
        this.signalPriceLines.push(
          this.candleSeries.createPriceLine({
            price: spec.price,
            color: spec.color,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: true,
            title: spec.title,
          })
        );
      }

      this.refreshPriceScale();
    }

    setTradeOverlay(position) {
      this.activePosition = position || null;
      this.clearTradeLines();

      if (!position || !this.candleSeries) {
        this.tradeLevels = null;
        if (this.pnlOverlayEl) {
          this.pnlOverlayEl.classList.add("hidden");
          this.pnlOverlayEl.innerHTML = "";
        }
        this.refreshPriceScale();
        return;
      }

      const entry = Number(position.entry);
      const sl = Number(position.stop_loss);
      const tp = Number(position.take_profit);
      const lockStop = Number(position.lock_stop);
      const current = Number(position.current_price);
      const qty = Number(position.quantity);
      const lev = Number(position.leverage);
      const margin = Number(position.margin_used);
      this.tradeLevels = { entry, sl, tp, current };

      const qtyLabel = qty >= 1 ? qty.toFixed(3) : qty.toFixed(4);
      const entryTitle = `ENTRY · ${lev}x · ${qtyLabel} · $${formatPrice(margin)}`;

      const lines = [
        { price: tp, color: TERMINAL.up, title: "TP" },
        { price: entry, color: "#eaecef", title: entryTitle },
      ];
      if (position.lock_active && Number.isFinite(lockStop) && lockStop > 0) {
        lines.push({ price: lockStop, color: TERMINAL.warn || "#f0b90b", title: "LOCK" });
      }
      lines.push({ price: sl, color: TERMINAL.down, title: "SL" });

      for (const spec of lines) {
        if (!Number.isFinite(spec.price)) continue;
        this.tradePriceLines.push(
          this.candleSeries.createPriceLine({
            price: spec.price,
            color: spec.color,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: spec.title,
          })
        );
      }

      this.renderPnlOverlay(position);
      this.refreshPriceScale();
    }

    renderPnlOverlay(position) {
      if (!this.pnlOverlayEl) return;
      const sideLabel = position.side === "BUY" ? "LONG" : "SHORT";
      const sideClass = position.side === "BUY" ? "long" : "short";
      const pnl = Number(position.unrealized_pnl ?? position.unrealized_usd ?? 0);
      const pnlClass = pnl >= 0 ? "up" : "down";
      const qty = Number(position.quantity);
      const lev = Number(position.leverage);
      const margin = Number(position.margin_used);
      this.pnlOverlayEl.classList.remove("hidden");
      this.pnlOverlayEl.innerHTML = `
        <div class="pnl-overlay-side ${sideClass}">${sideLabel} ${position.symbol}</div>
        <div class="pnl-overlay-row">Entry: <b>${formatPrice(position.entry)}</b></div>
        <div class="pnl-overlay-row">Margin: <b>${formatPrice(margin)}</b> · ${lev}x · ${qty.toFixed(3)}</div>
        <div class="pnl-overlay-row">Current: <b>${formatPrice(position.current_price)}</b></div>
        <div class="pnl-overlay-row ${pnlClass}">PnL: <b>${pnl >= 0 ? "+" : ""}${formatPrice(pnl)}</b></div>`;
    }

    _includePrice(value, minRef, maxRef) {
      if (!Number.isFinite(value)) return;
      minRef.v = Math.min(minRef.v, value);
      maxRef.v = Math.max(maxRef.v, value);
    }

    _visibleBarIndices() {
      const bars = this.context.displayCandles;
      if (!bars.length) return { from: 0, to: -1 };
      const logicalRange = this.chart?.timeScale().getVisibleLogicalRange();
      if (!logicalRange) return { from: 0, to: bars.length - 1 };
      return {
        from: Math.max(0, Math.floor(logicalRange.from)),
        to: Math.min(bars.length - 1, Math.ceil(logicalRange.to)),
      };
    }

    _seriesValueAt(data, index) {
      const point = data?.[index];
      if (point == null) return null;
      return typeof point === "object" ? Number(point.value) : Number(point);
    }

    buildAutoscaleInfo() {
      const bars = this.context.displayCandles;
      if (!bars.length) return null;

      const { from, to } = this._visibleBarIndices();
      if (from > to) return null;

      const minRef = { v: Infinity };
      const maxRef = { v: -Infinity };

      for (let i = from; i <= to; i += 1) {
        const c = bars[i];
        if (c) {
          this._includePrice(c.low, minRef, maxRef);
          this._includePrice(c.high, minRef, maxRef);
        }
        this._includePrice(this._seriesValueAt(this.context.smaData, i), minRef, maxRef);
        this._includePrice(this._seriesValueAt(this.context.hhData, i), minRef, maxRef);
        this._includePrice(this._seriesValueAt(this.context.llData, i), minRef, maxRef);
      }

      const levels = this.tradeLevels || this.signalLevels;
      if (levels) {
        this._includePrice(levels.entry, minRef, maxRef);
        this._includePrice(levels.sl, minRef, maxRef);
        this._includePrice(levels.tp, minRef, maxRef);
        if (Number.isFinite(levels.current)) {
          this._includePrice(levels.current, minRef, maxRef);
        }
      }

      let minV = minRef.v;
      let maxV = maxRef.v;
      if (!Number.isFinite(minV) || !Number.isFinite(maxV)) return null;

      let range = maxV - minV;
      if (range <= 0) {
        const pad = Math.max(Math.abs(maxV) * 0.001, 0.05);
        minV -= pad;
        maxV += pad;
        range = maxV - minV;
      }

      const margin = range * PRICE_MARGIN_PCT;
      return { priceRange: { minValue: minV - margin, maxValue: maxV + margin } };
    }

    _isPointOverPriceScale(x) {
      if (!this.container || x == null) return false;
      return x >= this.container.clientWidth - PRICE_SCALE_HIT_WIDTH;
    }

    _isEventOverPriceScale(event) {
      if (!this.container) return false;
      const rect = this.container.getBoundingClientRect();
      return event.clientX - rect.left >= rect.width - PRICE_SCALE_HIT_WIDTH;
    }

    _lockManualPriceScale() {
      if (!this.chart || this.userHasManualPriceScale) return;
      this.userHasManualPriceScale = true;
      this.chart.priceScale("right").applyOptions({ autoScale: false });
    }

    resetPriceScale() {
      this.userHasManualPriceScale = false;
      this.applyAutoPriceScale();
    }

    applyAutoPriceScale() {
      if (!this.chart || !this.candleSeries) return;
      const self = this;
      this.candleSeries.applyOptions({
        autoscaleInfoProvider: () => self.buildAutoscaleInfo(),
      });
      if (!this.userHasManualPriceScale) {
        this.chart.priceScale("right").applyOptions({ autoScale: true });
      }
    }

    refreshPriceScale() {
      this.applyAutoPriceScale();
    }

    _bindPriceScaleInteraction() {
      if (!this.container || !this.chart) return;

      const onPriceScalePointer = (event) => {
        if (this._isEventOverPriceScale(event)) this._lockManualPriceScale();
      };

      this.container.addEventListener("mousedown", onPriceScalePointer);
      this.container.addEventListener("wheel", onPriceScalePointer, { passive: true });
      this.container.addEventListener("touchstart", onPriceScalePointer, { passive: true });

      this.chart.subscribeDblClick((param) => {
        if (param.point && this._isPointOverPriceScale(param.point.x)) {
          this.resetPriceScale();
        }
      });
    }

    visibleCandleAutoscaleProvider() {
      return this.buildAutoscaleInfo();
    }

    updateTradeTooltip(hoverPrice, currentPrice) {
      const levelsSource = this.tradeLevels || this.signalLevels;
      if (!this.tradeTooltipEl || !levelsSource) {
        if (this.tradeTooltipEl) this.tradeTooltipEl.classList.add("hidden");
        return;
      }

      const ref = Number.isFinite(hoverPrice) ? hoverPrice : currentPrice;
      if (!Number.isFinite(ref)) {
        this.tradeTooltipEl.classList.add("hidden");
        return;
      }

      const threshold = Math.max(Math.abs(ref) * 0.002, 0.5);
      const levels = [
        { key: "entry", label: "Entry", price: levelsSource.entry },
        { key: "sl", label: "SL", price: levelsSource.sl },
        { key: "tp", label: "TP", price: levelsSource.tp },
      ];

      const hit = levels.find((l) => Number.isFinite(l.price) && Math.abs(ref - l.price) <= threshold);
      if (!hit) {
        this.tradeTooltipEl.classList.add("hidden");
        return;
      }

      const dist = ref - hit.price;
      const distSign = dist >= 0 ? "+" : "";
      this.tradeTooltipEl.classList.remove("hidden");
      this.tradeTooltipEl.innerHTML = `
        <strong>${hit.label}</strong> ${formatPrice(hit.price)}<br/>
        <span class="muted">Distance: ${distSign}${formatPrice(dist)}</span>`;
    }

    updateLegend(realCandle, sma, hh, ll) {
      const L = this.legend;
      if (!realCandle) {
        if (this.context.latestCandle) {
          this.updateLegend(
            this.context.latestCandle,
            this.context.latestSma,
            this.context.latestHh,
            this.context.latestLl
          );
        }
        return;
      }
      const bullish = realCandle.close >= realCandle.open;
      if (L.legTime) L.legTime.textContent = formatTime(realCandle.time);
      if (L.legO) L.legO.textContent = formatPrice(realCandle.open);
      if (L.legH) L.legH.textContent = formatPrice(realCandle.high);
      if (L.legL) L.legL.textContent = formatPrice(realCandle.low);
      if (L.legC) L.legC.textContent = formatPrice(realCandle.close);
      if (L.legV) L.legV.textContent = formatVolume(realCandle.volume);
      if (L.legSma) L.legSma.textContent = formatPrice(sma);
      if (L.legHh) L.legHh.textContent = formatPrice(hh);
      if (L.legLl) L.legLl.textContent = formatPrice(ll);
      if (L.lastPrice) {
        L.lastPrice.textContent = formatPrice(realCandle.close);
        L.lastPrice.className = `live-price${bullish ? "" : " down"}`;
      }
    }

    scrollToLatest(barCount) {
      if (!this.chart || barCount === 0) return;
      this.isProgrammaticScroll = true;
      const visible = Math.min(VISIBLE_BARS_DEFAULT, barCount);
      this.chart.timeScale().setVisibleLogicalRange({ from: barCount - visible, to: barCount + 4 });
      this.chart.timeScale().scrollToPosition(4, false);
      this.refreshPriceScale();
      requestAnimationFrame(() => {
        this.isProgrammaticScroll = false;
      });
    }

    resetPan() {
      this.userHasPanned = false;
    }

    resetView() {
      this.userHasPanned = false;
      this.resetPriceScale();
    }

    init() {
      if (this.chart) return true;
      if (typeof LightweightCharts === "undefined") {
        console.error("[chart] LightweightCharts not loaded");
        return false;
      }
      const width = this.container.clientWidth;
      const height = this.container.clientHeight;
      if (width <= 0 || height <= 0) {
        this._watchContainerSize();
        return false;
      }

      const self = this;
      const bgType = LightweightCharts.ColorType?.Solid ?? 0;
      this.chart = LightweightCharts.createChart(this.container, {
        autoSize: true,
        layout: {
          background: { type: bgType, color: TERMINAL.bg },
          textColor: TERMINAL.text,
          fontSize: 11,
        },
        grid: { vertLines: { color: TERMINAL.grid }, horzLines: { color: TERMINAL.grid } },
        crosshair: {
          mode: LightweightCharts.CrosshairMode.Normal,
          vertLine: {
            color: TERMINAL.crosshair,
            width: 1,
            style: LightweightCharts.LineStyle.Dashed,
            labelBackgroundColor: TERMINAL.crosshairLabel,
          },
          horzLine: {
            color: TERMINAL.crosshair,
            width: 1,
            style: LightweightCharts.LineStyle.Dashed,
            labelBackgroundColor: TERMINAL.crosshairLabel,
          },
        },
        rightPriceScale: {
          borderColor: TERMINAL.border,
          scaleMargins: { top: 0.05, bottom: 0.05 },
        },
        timeScale: {
          borderColor: TERMINAL.border,
          timeVisible: true,
          secondsVisible: false,
          barSpacing: 12,
          minBarSpacing: 5,
          rightOffset: 8,
        },
        handleScroll: {
          mouseWheel: true,
          pressedMouseMove: true,
          horzTouchDrag: true,
          vertTouchDrag: false,
        },
        handleScale: {
          axisPressedMouseMove: { time: true, price: true },
          axisDoubleClickReset: { price: true, time: false },
          mouseWheel: true,
          pinch: true,
        },
      });

      this.candleSeries = this.chart.addCandlestickSeries({
        upColor: TERMINAL.up,
        downColor: TERMINAL.down,
        borderUpColor: TERMINAL.up,
        borderDownColor: TERMINAL.down,
        wickUpColor: TERMINAL.up,
        wickDownColor: TERMINAL.down,
        borderVisible: true,
        wickVisible: true,
        thinBars: !this.showIndicators,
        priceScaleId: "right",
        autoscaleInfoProvider: () => self.buildAutoscaleInfo(),
      });
      this.candleSeries.priceScale().applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.05, bottom: 0.22 },
      });

      this.volumeSeries = this.chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      this.chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.76, bottom: 0 },
        borderVisible: false,
      });

      if (this.showIndicators) {
        this.smaSeries = this.chart.addLineSeries({
          color: TERMINAL.sma,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: "SMA84",
          autoscaleInfoProvider: NO_AUTOSCALE,
        });
        this.hhSeries = this.chart.addLineSeries({
          color: TERMINAL.hh,
          lineWidth: 1,
          lineType: LightweightCharts.LineType.WithSteps,
          priceLineVisible: false,
          lastValueVisible: true,
          title: "HH50",
          autoscaleInfoProvider: NO_AUTOSCALE,
        });
        this.llSeries = this.chart.addLineSeries({
          color: TERMINAL.ll,
          lineWidth: 1,
          lineType: LightweightCharts.LineType.WithSteps,
          priceLineVisible: false,
          lastValueVisible: true,
          title: "LL50",
          autoscaleInfoProvider: NO_AUTOSCALE,
        });
      } else {
        this.smaSeries = null;
        this.hhSeries = null;
        this.llSeries = null;
      }

      this.chart.applyOptions({
        localization: {
          timeFormatter: (displayTime) => {
            const real = self.context.displayToReal.get(displayTime);
            return real ? formatTime(real) : "";
          },
        },
      });

      this.chart.subscribeCrosshairMove((param) => {
        if (!param.time) {
          self.updateLegend(null);
          self.updateTradeTooltip(null, self.activePosition?.current_price);
          return;
        }
        const realTime = self.context.displayToReal.get(param.time);
        const realCandle = realTime ? self.context.realCandles.get(realTime) : null;
        const sma = self.smaSeries ? param.seriesData.get(self.smaSeries)?.value : null;
        const hh = self.hhSeries ? param.seriesData.get(self.hhSeries)?.value : null;
        const ll = self.llSeries ? param.seriesData.get(self.llSeries)?.value : null;
        self.updateLegend(realCandle, sma, hh, ll);

        let hoverPrice = null;
        if (param.point && self.candleSeries.coordinateToPrice) {
          hoverPrice = self.candleSeries.coordinateToPrice(param.point.y);
        }
        self.updateTradeTooltip(
          hoverPrice,
          realCandle?.close ?? self.activePosition?.current_price
        );
      });

      this.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
        if (!self.isProgrammaticScroll) self.userHasPanned = true;
        if (!self.userHasManualPriceScale) self.applyAutoPriceScale();
      });

      this._bindPriceScaleInteraction();
      this.ready = true;
      this._resizeObserver?.disconnect();
      this._resizeObserver = null;
      this._bindContainerResize();
      return true;
    }

    _bindContainerResize() {
      if (!this.container || !this.chart) return;
      const observer = new ResizeObserver(() => {
        if (!this.chart || !this.container) return;
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        if (w > 0 && h > 0) this.chart.resize(w, h);
      });
      observer.observe(this.container);
      this._resizeObserver = observer;
    }

    _watchContainerSize() {
      if (!this.container || this._resizeObserver) return;
      this._resizeObserver = new ResizeObserver(() => {
        if (this.ready || !this.container) return;
        if (this.container.clientWidth <= 0 || this.container.clientHeight <= 0) return;
        if (this.init()) {
          window.dispatchEvent(new CustomEvent("chart-engine-ready"));
        }
      });
      this._resizeObserver.observe(this.container);
    }

    _applyCandleDisplay(candles, display, { markers, position, symbol, livePrice }) {
      this.context = {
        displayToReal: display.displayToReal,
        realCandles: display.realCandles,
        realToDisplay: display.realToDisplay,
        displayCandles: display.displayCandles,
        smaData: display.smaData,
        hhData: display.hhData,
        llData: display.llData,
        latestCandle: candles[candles.length - 1] || null,
        latestSma: null,
        latestHh: null,
        latestLl: null,
      };

      this.candleSeries.setData(display.displayCandles);
      this.volumeSeries.setData(display.volumeData);
      if (this.showIndicators) {
        this.smaSeries.setData(display.smaData);
        this.hhSeries.setData(display.hhData);
        this.llSeries.setData(display.llData);
      }

      this.candleSeries.setMarkers(markers);

      if (position) {
        const lastClose = candles[candles.length - 1]?.close;
        const overlay = {
          ...position,
          symbol: position.symbol || `${symbol}USDT`,
          current_price: position.current_price ?? livePrice ?? lastClose,
          leverage: position.leverage ?? 1,
          margin_used: position.margin_used ?? 0,
          quantity: position.quantity ?? 0,
        };
        this.clearSignalLines();
        this.signalLevels = null;
        this.setTradeOverlay(overlay);
      } else {
        this.setTradeOverlay(null);
      }

      this.refreshPriceScale();
      const n = display.displayCandles.length;
      if (n > 0 && !this.userHasPanned) this.scrollToLatest(n);
      return n;
    }

    updateCandles(chartData, { timeframe = "5m", windowSize, symbol = "SOL", position, trades, livePrice } = {}) {
      if (!this.ready && !this.init()) {
        this._watchContainerSize();
        return;
      }
      if (!this.ready) return;

      const expectedInterval = INTERVAL_SECONDS[timeframe] || 300;
      let rawCandles = chartData.candles || [];
      if (livePrice != null && rawCandles.length) {
        rawCandles = rawCandles.map((c, i) => {
          if (i !== rawCandles.length - 1) return c;
          const close = Number(livePrice);
          return {
            ...c,
            close,
            high: Math.max(Number(c.high), close),
            low: Math.min(Number(c.low), close),
          };
        });
      }

      const { candles } = prepareCandleSeriesData(rawCandles, expectedInterval, windowSize);
      const empty = [];
      const display = buildChartDisplaySeries(candles, empty, empty, empty, expectedInterval, true);
      const markers = buildTradeMarkers(trades, display.realToDisplay);
      return this._applyCandleDisplay(candles, display, { markers, position, symbol, livePrice });
    }

    update(chartData, { windowSize, timeframe, signalTimeframe, symbol, position, signalQuality }) {
      if (!this.ready) return;

      if (this._lastSymbol !== symbol) {
        this._lastSymbol = symbol;
        this.userHasPanned = false;
        this.userHasManualPriceScale = false;
      }

      const positionId = position?.id ?? null;
      if (positionId !== this._lastPositionId) {
        this._lastPositionId = positionId;
        if (positionId != null) this.userHasManualPriceScale = false;
      }

      const expectedInterval = INTERVAL_SECONDS[timeframe] || 300;
      let rawCandles = chartData.candles || [];
      const livePrice = chartData.signal_context?.live_price;
      if (livePrice != null && rawCandles.length) {
        rawCandles = rawCandles.map((c, i) => {
          if (i !== rawCandles.length - 1) return c;
          const close = Number(livePrice);
          return {
            ...c,
            close,
            high: Math.max(Number(c.high), close),
            low: Math.min(Number(c.low), close),
          };
        });
      }
      const { candles } = prepareCandleSeriesData(rawCandles, expectedInterval, windowSize);
      const backendCounts = chartData.candle_counts || {};
      console.info("[chart] Backend candle_counts:", backendCounts);

      const offset = Math.max(0, chartData.candles.length - candles.length);
      const alignedSma = (chartData.sma84 || []).slice(offset);
      const alignedHh = (chartData.hh50 || []).slice(offset);
      const alignedLl = (chartData.ll50 || []).slice(offset);

      const display = buildChartDisplaySeries(
        candles,
        alignedSma,
        alignedHh,
        alignedLl,
        expectedInterval,
        !this.showIndicators,
      );
      const markerLimit = chartData.signal_marker_limit || this.maxSignalMarkers;
      const markers = buildArrowMarkers(chartData.signals || [], display.realToDisplay, markerLimit);

      if (position) {
        position = { ...position, current_price: position.current_price ?? candles[candles.length - 1]?.close };
        this._applyCandleDisplay(candles, display, { markers, position, symbol, livePrice });
        this.setSignalOverlay(null);
      } else {
        this._applyCandleDisplay(candles, display, { markers, position: null, symbol, livePrice });
        this.setSignalOverlay(signalQuality);
      }

      const n = display.displayCandles.length;
      const alignedSmaForLegend = (chartData.sma84 || []).slice(offset);
      const alignedHhForLegend = (chartData.hh50 || []).slice(offset);
      const alignedLlForLegend = (chartData.ll50 || []).slice(offset);
      this.context.latestSma = alignedSmaForLegend[alignedSmaForLegend.length - 1];
      this.context.latestHh = alignedHhForLegend[alignedHhForLegend.length - 1];
      this.context.latestLl = alignedLlForLegend[alignedLlForLegend.length - 1];

      if (n > 0) {
        const first = candles[0];
        const last = candles[n - 1];
        const change = last.close - first.open;
        const changePct = first.open ? (change / first.open) * 100 : 0;
        const sign = change >= 0 ? "+" : "";
        if (this.legend.priceChange) {
          this.legend.priceChange.textContent = `${sign}${changePct.toFixed(2)}% (${sign}${formatPrice(change)})`;
          this.legend.priceChange.style.color = change >= 0 ? TERMINAL.up : TERMINAL.down;
        }
        if (this.legend.lastPrice) {
          const displayPrice = livePrice != null ? Number(livePrice) : last.close;
          this.legend.lastPrice.textContent = formatPrice(displayPrice);
          this.legend.lastPrice.className = `live-price${displayPrice >= last.open ? "" : " down"}`;
        }
        if (this.legend.chartSymbol) {
          this.legend.chartSymbol.textContent = `${symbol}USDT`;
        }
        this.updateLegend(
          last,
          alignedSmaForLegend[alignedSmaForLegend.length - 1],
          alignedHhForLegend[alignedHhForLegend.length - 1],
          alignedLlForLegend[alignedLlForLegend.length - 1],
        );
      }

      if (this.onFootnote) {
        const sigTf = signalTimeframe || chartData.signal_context?.signal_timeframe || timeframe;
        const ec = chartData.signal_context?.entry_count;
        const rc = chartData.signal_context?.raw_condition_count;
        const minRed = chartData.signal_context?.settings_min_red;
        const slPct = chartData.signal_context?.settings_sl_pct;
        const extra = [
          ec != null ? `${ec} entries` : "",
          rc != null ? `${rc} raw conditions` : "",
          minRed != null ? `minRed=${minRed}` : "",
          slPct != null ? `SL=${slPct}%` : "",
        ].filter(Boolean).join(" · ");
        this.onFootnote(`${markers.length} markers · ${n} bars · chart ${timeframe}${extra ? ` · ${extra}` : ""}`);
      }
      if (this.onTitle) this.onTitle(symbol, timeframe);

      return { markerCount: markers.length, barCount: n, signalContext: chartData.signal_context || {} };
    }

    destroy() {
      this.clearOverlayLines();
      this._resizeObserver?.disconnect();
      this.chart?.remove();
      this.chart = null;
      this.ready = false;
    }
  }

  window.ChartEngine = {
    create(options) {
      return new ChartEngine(options);
    },
  };
})();
