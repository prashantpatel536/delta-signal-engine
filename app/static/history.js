const { fetchJson, formatPrice, formatTime } = window.DSE;

const statusFilter = document.getElementById("status-filter");
const periodFilter = document.getElementById("period-filter");
const refreshBtn = document.getElementById("refresh-btn");
const historyBody = document.getElementById("history-body");

function statusClass(status) {
  return status.toLowerCase().replace(/_/g, "-");
}

function outcomeLabel(signal) {
  if (signal.status === "MISSED_WINNER" || signal.status === "MISSED_LOSER") {
    return signal.status.replace("_", " ");
  }
  if (signal.missed_monitoring) return "Monitoring";
  return "—";
}

function formatPoints(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function formatUsd(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

async function loadHistory() {
  const status = statusFilter.value;
  const period = periodFilter?.value || "all";
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (period && period !== "all") params.set("period", period);
  const url = params.toString() ? `/signal-history?${params}` : "/signal-history";

  try {
    const payload = await fetchJson(url);
    if (!payload.signals.length) {
      historyBody.innerHTML = `<tr><td colspan="17" class="empty">No signals found.</td></tr>`;
      return;
    }

    historyBody.innerHTML = payload.signals
      .map((s) => {
        const outcome = outcomeLabel(s);
        const outcomeClass = statusClass(outcome.replace(" ", "-"));
        return `
        <tr>
          <td>${formatTime(s.created_at)}</td>
          <td>${s.symbol}</td>
          <td>${s.signal_timeframe || s.timeframe || "—"}</td>
          <td><span class="signal-type ${s.side.toLowerCase()}">${s.side}</span></td>
          <td>${formatPrice(s.entry)}</td>
          <td>${formatPrice(s.stop_loss)}</td>
          <td>${formatPrice(s.take_profit)}</td>
          <td><span class="status-tag ${statusClass(s.status)}">${s.status}</span></td>
          <td><span class="status-tag ${outcomeClass}">${outcome}</span></td>
          <td>${s.max_favorable_excursion ? formatPoints(s.max_favorable_excursion) : "—"}</td>
          <td>${s.max_adverse_excursion ? formatPoints(s.max_adverse_excursion) : "—"}</td>
          <td>${s.missed_exit_reason || "—"}</td>
          <td>${s.missed_exit_price != null ? formatPrice(s.missed_exit_price) : "—"}</td>
          <td>${formatPoints(s.points_captured)}</td>
          <td>${formatUsd(s.missed_pnl_usd)}</td>
          <td>${formatPct(s.missed_roe_pct)}</td>
          <td>${formatPct(s.missed_account_impact_pct)}</td>
        </tr>`;
      })
      .join("");
  } catch (error) {
    historyBody.innerHTML = `<tr><td colspan="14" class="empty">Error: ${error.message}</td></tr>`;
  }
}

statusFilter.addEventListener("change", loadHistory);
refreshBtn.addEventListener("click", loadHistory);
statusFilter.addEventListener("change", loadHistory);
periodFilter?.addEventListener("change", loadHistory);
loadHistory();
