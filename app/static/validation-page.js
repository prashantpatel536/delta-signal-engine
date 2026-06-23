const { fetchJson } = window.DSE;

const bodyEl = document.getElementById("validation-body");
const assumptionsEl = document.getElementById("validation-assumptions");
const complianceEl = document.getElementById("validation-compliance");

function pct(n) {
  return `${Number(n ?? 0).toFixed(2)}%`;
}

async function loadValidation() {
  try {
    const data = await fetchJson("/validation/report");
    const a = data.assumptions;
    assumptionsEl.innerHTML = `
      <span>Capital Usage: <strong>${a.capital_usage_pct ?? 50}%</strong></span>
      <span>Leverage: <strong>${a.leverage ?? 25}x</strong></span>
      <span>Min Target ROE: <strong>${a.min_target_roe_pct ?? 50}%</strong></span>
      <span>Min RR: <strong>${a.min_risk_reward ?? 2}:1</strong></span>
      <span>Closed Trades: <strong>${data.total_closed_trades ?? 0}</strong></span>`;

    const c = data.compliance;
    complianceEl.innerHTML = `
      <div class="stat-card approved"><span class="stat-label">Liq Beyond SL Pass</span><span class="stat-value">${c.liq_beyond_sl_pass}</span></div>
      <div class="stat-card rejected"><span class="stat-label">Liq Beyond SL Fail</span><span class="stat-value">${c.liq_beyond_sl_fail}</span></div>
      <div class="stat-card approved"><span class="stat-label">Min ROE Pass</span><span class="stat-value">${c.min_roe_pass}</span></div>
      <div class="stat-card rejected"><span class="stat-label">Min ROE Fail</span><span class="stat-value">${c.min_roe_fail}</span></div>
      <div class="stat-card approved"><span class="stat-label">Min RR Pass</span><span class="stat-value">${c.min_rr_pass}</span></div>
      <div class="stat-card rejected"><span class="stat-label">Min RR Fail</span><span class="stat-value">${c.min_rr_fail}</span></div>
      <div class="stat-card"><span class="stat-label">Opposite Signal Exits</span><span class="stat-value">${c.opposite_signal_exits}</span></div>`;

    const rows = Object.values(data.symbols || {});
    if (!rows.length) {
      bodyEl.innerHTML = `<tr><td colspan="9" class="empty">No symbol data.</td></tr>`;
      return;
    }
    bodyEl.innerHTML = rows
      .map(
        (s) => `
        <tr>
          <td><strong>${s.label}</strong> ${s.symbol}</td>
          <td>${s.signal_count}</td>
          <td>${Number(s.average_sl_points).toFixed(2)}</td>
          <td>${Number(s.average_tp_points).toFixed(2)}</td>
          <td>${pct(s.average_expected_roe)}</td>
          <td>${pct(s.average_loss_pct)}</td>
          <td>${pct(s.average_profit_pct)}</td>
          <td>${pct(s.average_trade_roe)}</td>
          <td>${s.closed_trades}</td>
        </tr>`
      )
      .join("");
  } catch (error) {
    bodyEl.innerHTML = `<tr><td colspan="9" class="empty">Error: ${error.message}</td></tr>`;
  }
}

document.getElementById("validation-refresh")?.addEventListener("click", loadValidation);
loadValidation();
