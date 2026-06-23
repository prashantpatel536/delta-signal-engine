const { fetchJson, formatPrice } = window.DSE;

const refreshBtn = document.getElementById("refresh-btn");
const tradesBody = document.getElementById("trades-body");

function pnlClass(pnl) {
  return Number(pnl) >= 0 ? "up" : "down";
}

function formatPoints(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

async function loadTrades() {
  try {
    const payload = await fetchJson("/trade-history");
    if (!payload.trades.length) {
      tradesBody.innerHTML = `<tr><td colspan="11" class="empty">No closed trades yet.</td></tr>`;
      return;
    }

    tradesBody.innerHTML = payload.trades
      .map(
        (t) => `
        <tr>
          <td>${t.symbol}</td>
          <td><span class="signal-type ${t.side.toLowerCase()}">${t.side}</span></td>
          <td>${formatPrice(t.entry)}</td>
          <td>${formatPrice(t.exit_price)}</td>
          <td>${formatPoints(t.price_points)}</td>
          <td class="${pnlClass(t.pnl)}">${formatPrice(t.pnl)}</td>
          <td class="${pnlClass(t.roe)}">${formatPct(t.roe)}</td>
          <td class="${pnlClass(t.account_impact_pct)}">${formatPct(t.account_impact_pct)}</td>
          <td><span class="status-tag ${t.result.toLowerCase()}">${t.result}</span></td>
          <td>${t.exit_reason || "—"}</td>
          <td>${t.duration}</td>
        </tr>`
      )
      .join("");
  } catch (error) {
    tradesBody.innerHTML = `<tr><td colspan="11" class="empty">Error: ${error.message}</td></tr>`;
  }
}

refreshBtn.addEventListener("click", loadTrades);
loadTrades();
