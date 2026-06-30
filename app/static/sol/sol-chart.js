/**
 * SOL Reversal chart — Heikin Ashi on real candle times (TradingView-style).
 * Strategy reads HA; chart shows HA candles + paper trade markers.
 */
(() => {
  const TV = {
    bg: "#131722",
    grid: "#1e222d",
    text: "#d1d4dc",
    crosshair: "#758696",
    up: "#26a69a",
    down: "#ef5350",
  };

  function visualCandle(c) {
    const open = Number(c.open);
    const high = Number(c.high);
    const low = Number(c.low);
    const close = Number(c.close);
    if (high > low && Math.abs(open - close) > 1e-9) {
      return {
        open,
        high: Math.max(high, open, close),
        low: Math.min(low, open, close),
        close,
      };
    }
    const mid = close || open || 0;
    const pad = Math.max(Math.abs(mid) * 0.0002, 0.03);
    return { open: mid + pad / 2, high: mid + pad, low: mid - pad, close: mid - pad / 2 };
  }

  function prepareHaCandles(raw) {
    const byTime = new Map();
    for (const r of raw || []) {
      let time = Math.trunc(Number(r.time));
      if (time > 1e12) time = Math.trunc(time / 1000);
      const open = Number(r.open);
      const high = Number(r.high);
      const low = Number(r.low);
      const close = Number(r.close);
      if (![time, open, high, low, close].every(Number.isFinite)) continue;
      byTime.set(time, {
        time,
        open,
        high: Math.max(high, open, close, low),
        low: Math.min(low, open, close, high),
        close,
      });
    }
    return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
  }

  function toHaSeries(candles) {
    return candles.map((c) => {
      const v = visualCandle(c);
      return { time: c.time, open: v.open, high: v.high, low: v.low, close: v.close };
    });
  }

  function isoToUnix(iso) {
    if (!iso) return null;
    const ms = Date.parse(iso);
    return Number.isFinite(ms) ? Math.trunc(ms / 1000) : null;
  }

  function snapToCandle(unix, candleTimes) {
    if (!unix || !candleTimes.length) return null;
    let best = candleTimes[0];
    let bestD = Math.abs(best - unix);
    for (const t of candleTimes) {
      const d = Math.abs(t - unix);
      if (d < bestD) {
        best = t;
        bestD = d;
      }
    }
    return bestD <= 600 ? best : null;
  }

  function buildTradeMarkers(trades, candleTimes) {
    if (!trades?.length || !candleTimes.length) return [];
    const markers = [];
    for (const tr of trades.slice(0, 50)) {
      const isBuy = (tr.side || "").toUpperCase() === "BUY";
      const pnl = Number(tr.pnl_pct ?? 0);
      const win = pnl >= 0;
      const entryT = snapToCandle(isoToUnix(tr.opened_at || tr.entry_time), candleTimes);
      const exitT = snapToCandle(isoToUnix(tr.closed_at || tr.exit_time), candleTimes);
      if (entryT) {
        markers.push({
          time: entryT,
          position: isBuy ? "belowBar" : "aboveBar",
          shape: isBuy ? "arrowUp" : "arrowDown",
          color: "#2962ff",
          text: `entry ${tr.side}`,
          size: 2,
        });
      }
      if (exitT) {
        markers.push({
          time: exitT,
          position: isBuy ? "aboveBar" : "belowBar",
          shape: "square",
          color: win ? TV.up : TV.down,
          text: win ? `Profit +${Math.abs(pnl)}%` : `Loss ${pnl}%`,
          size: 2,
        });
      }
    }
    return markers.sort((a, b) => a.time - b.time);
  }

  class SolChartEngine {
    constructor(container) {
      this.container = container;
      this.chart = null;
      this.haSeries = null;
      this._init();
    }

    _init() {
      if (!this.container || typeof LightweightCharts === "undefined") return;
      const bgType = LightweightCharts.ColorType?.Solid ?? 0;
      this.chart = LightweightCharts.createChart(this.container, {
        autoSize: true,
        height: 440,
        layout: {
          background: { type: bgType, color: TV.bg },
          textColor: TV.text,
          fontSize: 12,
        },
        grid: {
          vertLines: { color: TV.grid },
          horzLines: { color: TV.grid },
        },
        crosshair: {
          mode: LightweightCharts.CrosshairMode.Normal,
          vertLine: { color: TV.crosshair, labelBackgroundColor: "#363a45" },
          horzLine: { color: TV.crosshair, labelBackgroundColor: "#363a45" },
        },
        rightPriceScale: {
          borderColor: TV.grid,
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        timeScale: {
          borderColor: TV.grid,
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 6,
          barSpacing: 8,
          minBarSpacing: 3,
        },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
        handleScale: { mouseWheel: true, pinch: true },
      });

      this.haSeries = this.chart.addCandlestickSeries({
        upColor: TV.up,
        downColor: TV.down,
        borderUpColor: TV.up,
        borderDownColor: TV.down,
        wickUpColor: TV.up,
        wickDownColor: TV.down,
        borderVisible: true,
        wickVisible: true,
      });
    }

    update(payload, trades) {
      if (!this.haSeries || !payload) return;
      const candles = prepareHaCandles(payload.heikin_ashi);
      if (!candles.length) return;

      const series = toHaSeries(candles);
      this.haSeries.setData(series);

      const markers = buildTradeMarkers(trades || [], candles.map((c) => c.time));
      this.haSeries.setMarkers(markers);

      this.chart.timeScale().fitContent();
    }

    destroy() {
      this.chart?.remove();
    }
  }

  window.SolChartEngine = SolChartEngine;
})();
