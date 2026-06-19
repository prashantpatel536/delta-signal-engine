const { fetchJson, formatPrice } = window.DSE;

const refreshBtn = document.getElementById("refresh-btn");
const tradesBody = document.getElementById("trades-body");

function pnlClass(pnl) {
  return Number(pnl) >= 0 ? "up" : "down";
}

async function loadTrades() {
  try {
    const payload = await fetchJson("/trade-history");
    if (!payload.trades.length) {
      tradesBody.innerHTML = `<tr><td colspan="12" class="empty">No closed trades yet.</td></tr>`;
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
          <td>${formatPrice(t.original_stop_loss)}</td>
          <td>${formatPrice(t.stop_loss)}</td>
          <td>${formatPrice(t.original_take_profit)}</td>
          <td>${formatPrice(t.take_profit)}</td>
          <td class="${pnlClass(t.pnl)}">${formatPrice(t.pnl)}</td>
          <td><span class="status-tag ${t.result.toLowerCase()}">${t.result}</span></td>
          <td>${t.exit_reason || "—"}</td>
          <td>${t.duration}</td>
        </tr>`
      )
      .join("");
  } catch (error) {
    tradesBody.innerHTML = `<tr><td colspan="12" class="empty">Error: ${error.message}</td></tr>`;
  }
}

refreshBtn.addEventListener("click", loadTrades);
loadTrades();
