const body = document.getElementById("signals-body");
const refreshBtn = document.getElementById("refresh-btn");

function activeChipValues(containerId) {
  return [...document.querySelectorAll(`#${containerId} .chip.active`)].map((el) => el.dataset.value);
}

function bindChipFilters(containerId, onChange) {
  document.querySelectorAll(`#${containerId} .chip`).forEach((chip) => {
    chip.addEventListener("click", () => {
      chip.classList.toggle("active");
      onChange();
    });
  });
}

function matchesFilters(signal, symbols, timeframes, statuses) {
  const short = DSE.shortSymbol(signal.symbol);
  return (
    symbols.includes(short) &&
    timeframes.includes(signal.timeframe) &&
    statuses.includes(signal.status)
  );
}

function renderRows(signals) {
  if (!body) return;
  if (!signals.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">No signals match filters</td></tr>`;
    return;
  }

  body.innerHTML = signals
    .map(
      (s) => `
      <tr>
        <td>${DSE.formatIsoTime(s.created_at)}</td>
        <td>${s.symbol}</td>
        <td>${s.timeframe}</td>
        <td><span class="signal-type ${s.side.toLowerCase()}">${s.side}</span></td>
        <td>${DSE.formatPrice(s.entry)}</td>
        <td>${DSE.formatPrice(s.stop_loss)}</td>
        <td>${DSE.formatPrice(s.take_profit)}</td>
        <td>${DSE.statusTag(s.status)}</td>
        <td class="actions-cell">
          ${
            s.status === "PENDING"
              ? `<button type="button" class="btn-approve btn-sm" data-action="approve" data-id="${s.id}">Approve</button>
                 <button type="button" class="btn-reject btn-sm" data-action="reject" data-id="${s.id}">Reject</button>`
              : "—"
          }
        </td>
      </tr>`
    )
    .join("");
}

async function loadSignals() {
  const symbols = activeChipValues("symbol-filters");
  const timeframes = activeChipValues("timeframe-filters");
  const statuses = activeChipValues("status-filters");

  try {
    const requests = statuses.map((status) => DSE.fetchJson(`/signal-history?status=${status}`));
    const payloads = await Promise.all(requests);
    const merged = payloads.flatMap((p) => p.signals || []);
    const seen = new Set();
    const unique = merged.filter((s) => {
      const key = s.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return matchesFilters(s, symbols, timeframes, statuses);
    });
    unique.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    renderRows(unique);
  } catch (error) {
    body.innerHTML = `<tr><td colspan="9" class="empty">Error: ${error.message}</td></tr>`;
  }
}

async function handleAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  button.disabled = true;
  try {
    await DSE.fetchJson(`/signal/${button.dataset.id}/${button.dataset.action}`, { method: "POST" });
    await loadSignals();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
  }
}

function applyPrefsToFilters() {
  const prefs = DSE.getPrefs();
  document.querySelectorAll("#symbol-filters .chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.value === prefs.symbol);
  });
  document.querySelectorAll("#timeframe-filters .chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.value === prefs.timeframe);
  });
}

bindChipFilters("symbol-filters", loadSignals);
bindChipFilters("timeframe-filters", loadSignals);
bindChipFilters("status-filters", loadSignals);
refreshBtn?.addEventListener("click", loadSignals);
body?.addEventListener("click", handleAction);

applyPrefsToFilters();
loadSignals();
setInterval(loadSignals, 30000);
