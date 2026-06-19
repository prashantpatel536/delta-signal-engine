const body = document.getElementById("diag-body");
const symbolSelect = document.getElementById("symbol-select");
const timeframeSelect = document.getElementById("timeframe-select");
const refreshBtn = document.getElementById("refresh-btn");

function row(label, value) {
  return `<div class="diag-row"><span>${label}</span><strong>${value ?? "—"}</strong></div>`;
}

function render(data) {
  if (!body) return;
  const stored = data.latest_stored_signal;
  const runtime = data.runtime_signal;
  body.innerHTML = `
    <section class="panel diag-panel">
      <h2>Latest Stored Signal</h2>
      ${stored ? `
        ${row("ID", stored.id)}
        ${row("Side", stored.side)}
        ${row("Symbol", stored.symbol)}
        ${row("Timeframe", stored.timeframe)}
        ${row("Signal Time", DSE.formatTime(stored.created_at))}
        ${row("Entry", DSE.formatPrice(stored.entry))}
        ${row("Status", stored.status)}
      ` : `<p class="empty">No stored signals</p>`}
    </section>
    <section class="panel diag-panel">
      <h2>Runtime Signal (Cache)</h2>
      ${runtime ? `
        ${row("Side", runtime.signal)}
        ${row("Symbol", runtime.symbol)}
        ${row("Timeframe", runtime.timeframe)}
        ${row("Signal Time", DSE.formatTime(runtime.timestamp))}
        ${row("Candle Time", runtime.candle_time)}
        ${row("Price", DSE.formatPrice(runtime.price))}
      ` : `<p class="empty">No runtime signal on latest bar</p>`}
    </section>
    <section class="panel diag-panel">
      <h2>Indicator Values (Last Bar)</h2>
      ${row("Symbol", data.symbol)}
      ${row("Timeframe", data.timeframe)}
      ${row("Candle Count", data.candle_count)}
      ${row("Last Candle Time", data.last_candle_time)}
      ${row("SMA84", data.sma84 != null ? DSE.formatPrice(data.sma84) : "—")}
      ${row("HH50", data.hh50 != null ? DSE.formatPrice(data.hh50) : "—")}
      ${row("LL50", data.ll50 != null ? DSE.formatPrice(data.ll50) : "—")}
      ${row("Source", data.indicator_source)}
      ${row("Pending Duplicate Block", data.duplicate_pending_blocked ? "Yes" : "No")}
    </section>`;
}

async function load() {
  const symbol = symbolSelect?.value || "ETH";
  const timeframe = timeframeSelect?.value || "5m";
  try {
    const data = await DSE.fetchJson(
      `/debug/signals/data?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`
    );
    render(data);
  } catch (error) {
    body.innerHTML = `<p class="empty">Error: ${error.message}</p>`;
  }
}

const prefs = DSE.getPrefs();
if (symbolSelect) symbolSelect.value = prefs.symbol;
if (timeframeSelect) timeframeSelect.value = prefs.timeframe;
symbolSelect?.addEventListener("change", load);
timeframeSelect?.addEventListener("change", load);
refreshBtn?.addEventListener("click", load);

load();
setInterval(load, 30000);
