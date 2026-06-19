const { fetchJson, formatPrice, formatTime } = window.DSE;

const statusFilter = document.getElementById("status-filter");
const refreshBtn = document.getElementById("refresh-btn");
const historyBody = document.getElementById("history-body");

function statusClass(status) {
  return status.toLowerCase().replace(/\s+/g, "-");
}

async function loadHistory() {
  const status = statusFilter.value;
  const url = status ? `/signal-history?status=${encodeURIComponent(status)}` : "/signal-history";

  try {
    const payload = await fetchJson(url);
    if (!payload.signals.length) {
      historyBody.innerHTML = `<tr><td colspan="8" class="empty">No signals found.</td></tr>`;
      return;
    }

    historyBody.innerHTML = payload.signals
      .map(
        (s) => `
        <tr>
          <td>${formatTime(s.created_at)}</td>
          <td>${s.symbol}</td>
          <td>${s.signal_timeframe || s.timeframe || "—"}</td>
          <td><span class="signal-type ${s.side.toLowerCase()}">${s.side}</span></td>
          <td>${formatPrice(s.entry)}</td>
          <td>${formatPrice(s.stop_loss)}</td>
          <td>${formatPrice(s.take_profit)}</td>
          <td><span class="status-tag ${statusClass(s.status)}">${s.status}</span></td>
        </tr>`
      )
      .join("");
  } catch (error) {
    historyBody.innerHTML = `<tr><td colspan="8" class="empty">Error: ${error.message}</td></tr>`;
  }
}

statusFilter.addEventListener("change", loadHistory);
refreshBtn.addEventListener("click", loadHistory);
loadHistory();
