const { fetchJson, formatPrice } = window.DSE;

function setText(id, value, suffix = "") {
  const el = document.getElementById(id);
  if (el) el.textContent = value != null ? `${value}${suffix}` : "—";
}

async function loadStats() {
  try {
    const [signals, paper] = await Promise.all([
      fetchJson("/signal-statistics"),
      fetchJson("/paper-statistics"),
    ]);

    setText("sig-total", signals.total);
    setText("sig-pending", signals.pending);
    setText("sig-approved", signals.approved);
    setText("sig-rejected", signals.rejected);

    setText("pt-total", paper.total_trades);
    setText("pt-wins", paper.wins);
    setText("pt-losses", paper.losses);
    setText("pt-winrate", paper.win_rate, "%");
    setText("pt-net", formatPrice(paper.net_pnl));
    setText("pt-avgwin", formatPrice(paper.average_win));
    setText("pt-avgloss", formatPrice(paper.average_loss));
    setText("pt-pf", paper.profit_factor != null ? paper.profit_factor : "—");
    setText("pt-open", paper.open_positions);

    const netEl = document.getElementById("pt-net");
    if (netEl) {
      netEl.className = "stat-value";
      if (paper.net_pnl > 0) netEl.classList.add("up");
      if (paper.net_pnl < 0) netEl.classList.add("down");
    }
  } catch (error) {
    document.getElementById("paper-stats-grid").innerHTML =
      `<p class="empty">Error loading statistics: ${error.message}</p>`;
  }
}

loadStats();
