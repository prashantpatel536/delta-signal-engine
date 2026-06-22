(() => {
  const INTERVAL_SECONDS = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600 };
  const VISIBLE_BARS_DEFAULT = 80;
  const MAX_SIGNAL_MARKERS = 8;
  const PRICE_MARGIN_PCT = 0.05;
  const NO_AUTOSCALE = () => null;

  const TERMINAL = {
    bg: "#0b0e11",
    grid: "#1e2329",
    border: "#2b3139",
    text: "#848e9c",
    crosshair: "#758696",
    crosshairLabel: "#363a45",
    up: "#0ecb81",
    down: "#f6465d",
    sma: "#f0b90b",
    hh: "#1e88e5",
    ll: "#f6465d",
    volUp: "rgba(14, 203, 129, 0.45)",
    volDown: "rgba(246, 70, 93, 0.45)",
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

  function visualCandle(candle) {
    const open = Number(candle.open);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const close = Number(candle.close);
    if (high > low) {
      if (open !== close) return { open, high, low, close };
      const span = high - low;
      const body = Math.max(span * 0.12, Math.abs(close) * 0.00008, 0.02);
      const mid = close;
      return {
        open: mid + body / 2,
        high,
        low,
        close: mid - body / 2,
      };
    }
    const mid = close || open || 0;
    const pad = Math.max(Math.abs(mid) * 0.00012, 0.05);
    return { open, high: mid + pad, low: mid - pad, close };
  }

  function buildChartDisplaySeries(candles, alignedSma, alignedHh, alignedLl, intervalSec) {
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
      const v = visualCandle(c);
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

  function buildArrowMarkers(chartSignals, realToDisplay) {
    const sorted = [...chartSignals]
      .filter((s) => s.candle_time)
      .sort((a, b) => Number(b.candle_time) - Number(a.candle_time))
      .slice(0, MAX_SIGNAL_MARKERS);

    const seen = new Set();
    const markers = [];
    for (const sig of sorted) {
      const realTime = Math.trunc(Number(sig.candle_time));
      const displayTime = realToDisplay.get(realTime);
      if (!displayTime || seen.has(displayTime)) continue;
      seen.add(displayTime);
      const isBuy = sig.signal === "BUY";
      const statusLabel = formatSignalStatus(sig.status);
      const sideLabel = isBuy ? "BUY" : "SELL";
      const tfLabel = sig.timeframe || sig.signal_timeframe || "";
      const base = tfLabel ? `${sideLabel} (${tfLabel})` : sideLabel;
      const text = statusLabel ? `${base} · ${statusLabel}` : base;
      markers.push({
        time: displayTime,
        position: isBuy ? "belowBar" : "aboveBar",
        shape: isBuy ? "arrowUp" : "arrowDown",
        color: isBuy ? TERMINAL.up : TERMINAL.down,
        text,
        size: 1,
      });
    }
    return markers.sort((a, b) => a.time - b.time);
  }

  function formatSignalStatus(status) {
    if (!status) return "";
    if (status === "TP_HIT") return "TP HIT";
    if (status === "SL_HIT") return "SL HIT";
    return status;
  }

  class ChartEngine {
    constructor(options) {
      this.container = options.container;
      this.legend = options.legend || {};
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
      this.isProgrammaticScroll = false;
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
        { price: sl, color: TERMINAL.down, title: "SL" },
      ];

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
      const pnl = Number(position.unrealized_pnl);
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

    mergeTradeLevelsIntoRange(baseRange) {
      if (!baseRange) return baseRange;
      const levelSource = this.tradeLevels || this.signalLevels;
      if (!levelSource) return baseRange;
      const prices = Object.values(levelSource).filter(Number.isFinite);
      if (!prices.length) return baseRange;

      let minV = baseRange.priceRange.minValue;
      let maxV = baseRange.priceRange.maxValue;
      for (const p of prices) {
        minV = Math.min(minV, p);
        maxV = Math.max(maxV, p);
      }
      const range = maxV - minV || 1;
      const margin = range * PRICE_MARGIN_PCT;
      return { priceRange: { minValue: minV - margin, maxValue: maxV + margin } };
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

    candleRangeFromBars(bars, fromIndex, toIndex) {
      let minV = Infinity;
      let maxV = -Infinity;
      for (let i = fromIndex; i <= toIndex; i += 1) {
        const c = bars[i];
        if (!c) continue;
        minV = Math.min(minV, c.low);
        maxV = Math.max(maxV, c.high);
      }
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

    visibleCandleAutoscaleProvider() {
      const bars = this.context.displayCandles;
      if (!bars.length) return null;
      const logicalRange = this.chart?.timeScale().getVisibleLogicalRange();
      if (!logicalRange) return this.mergeTradeLevelsIntoRange(this.candleRangeFromBars(bars, 0, bars.length - 1));
      const from = Math.max(0, Math.floor(logicalRange.from));
      const to = Math.min(bars.length - 1, Math.ceil(logicalRange.to));
      if (from > to) return this.mergeTradeLevelsIntoRange(this.candleRangeFromBars(bars, 0, bars.length - 1));
      return this.mergeTradeLevelsIntoRange(this.candleRangeFromBars(bars, from, to));
    }

    refreshPriceScale() {
      if (!this.chart || !this.candleSeries) return;
      this.candleSeries.applyOptions({ autoscaleInfoProvider: () => this.visibleCandleAutoscaleProvider() });
      this.chart.priceScale("right").applyOptions({ autoScale: true });
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

    init() {
      const width = this.container.clientWidth;
      const height = this.container.clientHeight;
      if (width <= 0 || height <= 0) return false;

      const self = this;
      this.chart = LightweightCharts.createChart(this.container, {
        layout: { background: { color: TERMINAL.bg }, textColor: TERMINAL.text, fontSize: 11 },
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
        rightPriceScale: { borderColor: TERMINAL.border, scaleMargins: { top: 0.06, bottom: 0.06 } },
        timeScale: {
          borderColor: TERMINAL.border,
          timeVisible: true,
          secondsVisible: false,
          barSpacing: 10,
          minBarSpacing: 4,
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
          mouseWheel: true,
          pinch: true,
        },
        width,
        height,
      });

      this.candleSeries = this.chart.addCandlestickSeries({
        upColor: TERMINAL.up,
        downColor: TERMINAL.down,
        borderUpColor: TERMINAL.up,
        borderDownColor: TERMINAL.down,
        wickUpColor: TERMINAL.up,
        wickDownColor: TERMINAL.down,
        priceScaleId: "right",
        autoscaleInfoProvider: () => self.visibleCandleAutoscaleProvider(),
      });
      this.candleSeries.priceScale().applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.04, bottom: 0.18 },
      });

      this.volumeSeries = this.chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      this.chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.76, bottom: 0 },
        borderVisible: false,
      });

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
        const sma = param.seriesData.get(self.smaSeries)?.value;
        const hh = param.seriesData.get(self.hhSeries)?.value;
        const ll = param.seriesData.get(self.llSeries)?.value;
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
        self.refreshPriceScale();
      });

      this._resizeObserver = new ResizeObserver(() => {
        if (!self.chart) return;
        const w = self.container.clientWidth;
        const h = self.container.clientHeight;
        if (w > 0 && h > 0) self.chart.applyOptions({ width: w, height: h });
      });
      this._resizeObserver.observe(this.container);

      this.ready = true;
      return true;
    }

    update(chartData, { windowSize, timeframe, signalTimeframe, symbol, position, signalQuality }) {
      if (!this.ready) return;

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

      const display = buildChartDisplaySeries(candles, alignedSma, alignedHh, alignedLl, expectedInterval);
      this.context = {
        displayToReal: display.displayToReal,
        realCandles: display.realCandles,
        realToDisplay: display.realToDisplay,
        displayCandles: display.displayCandles,
        latestCandle: candles[candles.length - 1] || null,
        latestSma: alignedSma[alignedSma.length - 1],
        latestHh: alignedHh[alignedHh.length - 1],
        latestLl: alignedLl[alignedLl.length - 1],
      };

      this.candleSeries.setData(display.displayCandles);
      this.volumeSeries.setData(display.volumeData);
      this.smaSeries.setData(display.smaData);
      this.hhSeries.setData(display.hhData);
      this.llSeries.setData(display.llData);

      const markers = buildArrowMarkers(chartData.signals || [], display.realToDisplay);
      this.candleSeries.setMarkers(markers);

      if (position) {
        position = { ...position, current_price: position.current_price ?? candles[candles.length - 1]?.close };
        this.clearSignalLines();
        this.signalLevels = null;
        this.setTradeOverlay(position);
      } else {
        this.setTradeOverlay(null);
        this.setSignalOverlay(signalQuality);
      }
      this.refreshPriceScale();

      const n = display.displayCandles.length;
      if (n > 0) {
        if (!this.userHasPanned) this.scrollToLatest(n);
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
        this.updateLegend(last, alignedSma[n - 1], alignedHh[n - 1], alignedLl[n - 1]);
      }

      if (this.onFootnote) {
        const sigTf = signalTimeframe || chartData.signal_context?.signal_timeframe || timeframe;
        this.onFootnote(`${markers.length} markers · ${n} bars · chart ${timeframe} · signals ${sigTf}`);
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
