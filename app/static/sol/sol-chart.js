/**
 * SOL Reversal chart — TradingView-style Lightweight Charts (Delta OHLC).
 * Uses sequential display times (like BTC terminal) to avoid gap artifacts.
 */
(() => {
  const INTERVAL_SEC = 300; // 5m
  const THEME = {
    bg: "#0b0e11",
    grid: "#2b3139",
    text: "#b7bdc6",
    crosshair: "#848e9c",
    up: "#14d990",
    down: "#ff5b6a",
    ha: "#f5c518",
    volUp: "rgba(20, 217, 144, 0.45)",
    volDown: "rgba(255, 91, 106, 0.45)",
  };

  function visualCandle(c) {
    const open = Number(c.open);
    const high = Number(c.high);
    const low = Number(c.low);
    const close = Number(c.close);
    if (high > low && Math.abs(open - close) > 0) {
      return {
        open,
        high: Math.max(high, open, close),
        low: Math.min(low, open, close),
        close,
      };
    }
    const mid = close || open || 0;
    const pad = Math.max(Math.abs(mid) * 0.00015, 0.02);
    return { open: mid + pad / 2, high: mid + pad, low: mid - pad, close: mid - pad / 2 };
  }

  function prepareCandles(raw) {
    const byTime = new Map();
    for (const r of raw || []) {
      let time = Math.trunc(Number(r.time));
      if (time > 1e12) time = Math.trunc(time / 1000);
      const open = Number(r.open);
      const high = Number(r.high);
      const low = Number(r.low);
      const close = Number(r.close);
      const volume = Number(r.volume) || 0;
      if (![time, open, high, low, close].every(Number.isFinite)) continue;
      byTime.set(time, {
        time,
        open,
        high: Math.max(high, open, close, low),
        low: Math.min(low, open, close, high),
        close,
        volume,
      });
    }
    return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
  }

  function toDisplaySeries(candles) {
    if (!candles.length) {
      return { ohlc: [], volume: [], haLine: [], timeMap: new Map() };
    }
    const base = candles[0].time;
    const ohlc = [];
    const volume = [];
    const haLine = [];
    const timeMap = new Map();

    candles.forEach((c, i) => {
      const t = base + i * INTERVAL_SEC;
      timeMap.set(c.time, t);
      const v = visualCandle(c);
      const bull = c.close >= c.open;
      ohlc.push({ time: t, open: v.open, high: v.high, low: v.low, close: v.close });
      volume.push({
        time: t,
        value: c.volume,
        color: bull ? THEME.volUp : THEME.volDown,
      });
    });
    return { ohlc, volume, haLine, timeMap };
  }

  function isoToUnix(iso) {
    if (!iso) return null;
    const ms = Date.parse(iso);
    return Number.isFinite(ms) ? Math.trunc(ms / 1000) : null;
  }

  function buildTradeMarkers(trades, timeMap, candles) {
    if (!trades?.length || !candles.length) return [];
    const candleTimes = candles.map((c) => c.time);
    const nearest = (unix) => {
      if (!unix) return null;
      let best = candleTimes[0];
      let bestD = Math.abs(best - unix);
      for (const t of candleTimes) {
        const d = Math.abs(t - unix);
        if (d < bestD) {
          best = t;
          bestD = d;
        }
      }
      return timeMap.get(best) ?? null;
    };

    const markers = [];
    for (const tr of trades.slice(0, 40)) {
      const entryT = nearest(isoToUnix(tr.opened_at || tr.entry_time));
      const exitT = nearest(isoToUnix(tr.closed_at || tr.exit_time));
      const isBuy = (tr.side || "").toUpperCase() === "BUY";
      const win = Number(tr.pnl_usd || tr.pnl_points || 0) >= 0;
      if (entryT) {
        markers.push({
          time: entryT,
          position: isBuy ? "belowBar" : "aboveBar",
          shape: isBuy ? "arrowUp" : "arrowDown",
          color: "#42a5f5",
          text: `${tr.side} entry`,
          size: 1,
        });
      }
      if (exitT) {
        markers.push({
          time: exitT,
          position: isBuy ? "aboveBar" : "belowBar",
          shape: "circle",
          color: win ? THEME.up : THEME.down,
          text: win ? `+${tr.pnl_pct ?? ""}%` : `${tr.pnl_pct ?? ""}%`,
          size: 1,
        });
      }
    }
    return markers.sort((a, b) => a.time - b.time);
  }

  function buildHaOverlay(haRaw, candles, timeMap) {
    const ha = prepareCandles(haRaw);
    const byTime = new Map(ha.map((c) => [c.time, c.close]));
    return candles
      .map((c) => {
        const close = byTime.get(c.time);
        const t = timeMap.get(c.time);
        if (close == null || t == null) return null;
        return { time: t, value: close };
      })
      .filter(Boolean);
  }

  class SolChartEngine {
    constructor(container) {
      this.container = container;
      this.chart = null;
      this.candleSeries = null;
      this.volumeSeries = null;
      this.haSeries = null;
      this._lastCandles = [];
      this._timeMap = new Map();
      this._init();
    }

    _init() {
      if (!this.container || typeof LightweightCharts === "undefined") return;
      const bgType = LightweightCharts.ColorType?.Solid ?? 0;
      this.chart = LightweightCharts.createChart(this.container, {
        autoSize: true,
        height: 420,
        layout: {
          background: { type: bgType, color: THEME.bg },
          textColor: THEME.text,
          fontSize: 11,
        },
        grid: {
          vertLines: { color: THEME.grid },
          horzLines: { color: THEME.grid },
        },
        crosshair: {
          mode: LightweightCharts.CrosshairMode.Normal,
          vertLine: { color: THEME.crosshair, labelBackgroundColor: "#363a45" },
          horzLine: { color: THEME.crosshair, labelBackgroundColor: "#363a45" },
        },
        rightPriceScale: {
          borderColor: THEME.grid,
          scaleMargins: { top: 0.08, bottom: 0.22 },
        },
        timeScale: {
          borderColor: THEME.grid,
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 8,
          barSpacing: 7,
          minBarSpacing: 4,
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

      this.candleSeries = this.chart.addCandlestickSeries({
        upColor: THEME.up,
        downColor: THEME.down,
        borderUpColor: THEME.up,
        borderDownColor: THEME.down,
        wickUpColor: THEME.up,
        wickDownColor: THEME.down,
        borderVisible: true,
        wickVisible: true,
      });

      this.volumeSeries = this.chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      this.chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        borderVisible: false,
      });

      this.haSeries = this.chart.addLineSeries({
        color: THEME.ha,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    }

    update(payload, trades) {
      if (!this.candleSeries || !payload) return;
      const candles = prepareCandles(payload.ohlc || payload.heikin_ashi);
      if (!candles.length) return;

      this._lastCandles = candles;
      const { ohlc, volume, timeMap } = toDisplaySeries(candles);
      this._timeMap = timeMap;

      this.candleSeries.setData(ohlc);
      this.volumeSeries.setData(volume);

      const haLine = buildHaOverlay(payload.heikin_ashi, candles, timeMap);
      if (haLine.length) this.haSeries.setData(haLine);

      const markers = buildTradeMarkers(trades || [], timeMap, candles);
      if (markers.length) {
        this.candleSeries.setMarkers(markers);
      }

      this.chart.timeScale().fitContent();
    }

    destroy() {
      this.chart?.remove();
    }
  }

  window.SolChartEngine = SolChartEngine;
})();
