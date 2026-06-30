/**
 * SOL Reversal chart — Heikin Ashi (TradingView-style bodies).
 */
(() => {
  const INTERVAL_SEC = 300;
  const TV = {
    bg: "#131722",
    grid: "#1e222d",
    text: "#d1d4dc",
    crosshair: "#758696",
    up: "#26a69a",
    down: "#ef5350",
  };

  /** Ensure every HA bar has a visible body + wicks for Lightweight Charts. */
  function visualCandle(candle) {
    const open = Number(candle.open);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const close = Number(candle.close);
    const bullish = close >= open;

    if (high > low) {
      if (Math.abs(open - close) > 1e-10) {
        return {
          open,
          high: Math.max(high, open, close),
          low: Math.min(low, open, close),
          close,
        };
      }
      const span = high - low;
      const body = Math.max(span * 0.4, Math.abs(close) * 0.0002, 0.05);
      const mid = (open + close) / 2;
      return bullish
        ? { open: mid - body / 2, close: mid + body / 2, high, low }
        : { open: mid + body / 2, close: mid - body / 2, high, low };
    }

    const mid = close || open || 0;
    const pad = Math.max(Math.abs(mid) * 0.0003, 0.08);
    return {
      open: mid + pad / 2,
      high: mid + pad,
      low: mid - pad,
      close: mid - pad / 2,
    };
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

  /** Evenly spaced bars (TV-style) — avoids gap artifacts from missing candles. */
  function toDisplaySeries(candles) {
    if (!candles.length) return { series: [], timeMap: new Map() };
    const base = candles[0].time;
    const timeMap = new Map();
    const series = candles.map((c, i) => {
      const t = base + i * INTERVAL_SEC;
      timeMap.set(c.time, t);
      const v = visualCandle(c);
      return { time: t, open: v.open, high: v.high, low: v.low, close: v.close };
    });
    return { series, timeMap };
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

  function buildTradeMarkers(trades, candleTimes, timeMap) {
    if (!trades?.length || !candleTimes.length) return [];
    const markers = [];
    for (const tr of trades.slice(0, 50)) {
      const isBuy = (tr.side || "").toUpperCase() === "BUY";
      const pnl = Number(tr.pnl_pct ?? 0);
      const win = pnl >= 0;
      const entryReal = snapToCandle(isoToUnix(tr.opened_at || tr.entry_time), candleTimes);
      const exitReal = snapToCandle(isoToUnix(tr.closed_at || tr.exit_time), candleTimes);
      const entryT = entryReal ? timeMap.get(entryReal) : null;
      const exitT = exitReal ? timeMap.get(exitReal) : null;
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
          scaleMargins: { top: 0.08, bottom: 0.08 },
        },
        timeScale: {
          borderColor: TV.grid,
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 8,
          barSpacing: 10,
          minBarSpacing: 4,
        },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
        handleScale: { mouseWheel: true, pinch: true },
        localization: {
          timeFormatter: (ts) => {
            const d = new Date(ts * 1000);
            return d.toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            });
          },
        },
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
        thinBars: false,
      });
    }

    update(payload, trades) {
      if (!this.haSeries || !payload) return;
      const candles = prepareHaCandles(payload.heikin_ashi);
      if (!candles.length) return;

      const { series, timeMap } = toDisplaySeries(candles);
      this.haSeries.setData(series);

      const markers = buildTradeMarkers(
        trades || [],
        candles.map((c) => c.time),
        timeMap,
      );
      this.haSeries.setMarkers(markers);
      this.chart.timeScale().fitContent();
    }

    destroy() {
      this.chart?.remove();
    }
  }

  window.SolChartEngine = SolChartEngine;
})();
