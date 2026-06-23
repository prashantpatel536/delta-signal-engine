const { fetchJson, formatPrice } = window.DSE;

const bodyEl = document.getElementById("risk-matrix-body");
const refreshBtn = document.getElementById("risk-refresh");
let pollTimer = null;

function formatDist(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return n >= 100 ? n.toFixed(1) : n.toFixed(2);
}

function renderMatrix(data) {
  document.getElementById("risk-balance").textContent = `${formatPrice(data.balance)} USD`;
  document.getElementById("risk-margin-pct").textContent = `${data.margin_percent}%`;
  document.getElementById("risk-leverage").textContent = `${data.leverage}x`;
  document.getElementById("risk-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;

  if (!data.rows?.length) {
    bodyEl.innerHTML = `<tr><td colspan="8" class="empty">No live prices available.</td></tr>`;
    return;
  }

  bodyEl.innerHTML = data.rows
    .map(
      (row) => `
      <tr>
        <td><strong>${row.symbol}</strong></td>
        <td>${formatPrice(row.current_price)}</td>
        <td class="down">${formatDist(row.risk_10pct_distance)}</td>
        <td class="down">${formatDist(row.risk_20pct_distance)}</td>
        <td class="down">${formatDist(row.risk_30pct_distance)}</td>
        <td class="up">${formatDist(row.reward_25pct_distance)}</td>
        <td class="up">${formatDist(row.reward_50pct_distance)}</td>
        <td class="up">${formatDist(row.reward_100pct_distance)}</td>
      </tr>`
    )
    .join("");
}

async function loadMatrix() {
  try {
    const data = await fetchJson("/risk/matrix");
    renderMatrix(data);
  } catch (error) {
    bodyEl.innerHTML = `<tr><td colspan="8" class="empty">Error: ${error.message}</td></tr>`;
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(loadMatrix, 5000);
}

refreshBtn?.addEventListener("click", loadMatrix);
loadMatrix();
startPolling();
