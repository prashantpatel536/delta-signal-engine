const body = document.getElementById("positions-body");
const symbolSelect = document.getElementById("symbol-select");
const refreshBtn = document.getElementById("refresh-btn");

function pnlClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  return Number(value) >= 0 ? "up" : "down";
}

function render(positions) {
  if (!body) return;
  const symbol = symbolSelect?.value || "";
  const delta = symbol ? DSE.deltaSymbol(symbol) : "";
  const filtered = delta ? positions.filter((p) => p.symbol === delta) : positions;

  if (!filtered.length) {
    body.innerHTML = `<tr><td colspan="16" class="empty">No open positions</td></tr>`;
    return;
  }

  body.innerHTML = filtered
    .map((p) => {
      const sideLabel = p.side === "BUY" ? "LONG" : "SHORT";
      const sideClass = p.side === "BUY" ? "side-long" : "side-short";
      const short = DSE.shortSymbol(p.symbol);
      return `
      <tr data-id="${p.id}">
        <td>${p.symbol}</td>
        <td class="${sideClass}">${sideLabel}</td>
        <td>${DSE.formatPrice(p.entry)}</td>
        <td>${DSE.formatPrice(p.current_price)}</td>
        <td>${DSE.formatPrice(p.margin_used)}</td>
        <td>${Number(p.leverage).toFixed(0)}x</td>
        <td>${DSE.formatPrice(p.position_value)}</td>
        <td>${DSE.formatQuantity(p.quantity, short)}</td>
        <td class="${pnlClass(p.unrealized_pnl)}">${DSE.formatPnl(p.unrealized_pnl)}</td>
        <td class="${pnlClass(p.roe)}">${p.roe != null ? `${Number(p.roe).toFixed(2)}%` : "—"}</td>
        <td>${DSE.formatPrice(p.original_take_profit)}</td>
        <td>
          ${DSE.formatPrice(p.take_profit)}
          <button type="button" class="btn-edit-sm" data-action="edit-tp" data-id="${p.id}" data-value="${p.take_profit}">Edit</button>
        </td>
        <td>${DSE.formatPrice(p.original_stop_loss)}</td>
        <td>
          ${DSE.formatPrice(p.stop_loss)}
          <button type="button" class="btn-edit-sm" data-action="edit-sl" data-id="${p.id}" data-value="${p.stop_loss}">Edit</button>
        </td>
        <td>${Number(p.risk_reward || 0).toFixed(2)}</td>
        <td class="pos-actions-cell">
          <button type="button" class="btn-quick" data-action="breakeven" data-id="${p.id}">Breakeven</button>
          <button type="button" class="btn-close-sm btn-close-position" data-id="${p.id}">Close</button>
        </td>
      </tr>`;
    })
    .join("");
}

async function load() {
  try {
    const payload = await DSE.fetchJson("/open-positions");
    render(payload.positions || []);
  } catch (error) {
    body.innerHTML = `<tr><td colspan="16" class="empty">Error: ${error.message}</td></tr>`;
  }
}

const prefs = DSE.getPrefs();
if (symbolSelect) symbolSelect.value = prefs.symbol;
symbolSelect?.addEventListener("change", load);
refreshBtn?.addEventListener("click", load);
PositionManagement.bind(body, load);

load();
setInterval(load, 30000);
