const overallEl = document.getElementById("health-overall");
const gridEl = document.getElementById("health-grid");
const rawEl = document.getElementById("health-raw");
const refreshBtn = document.getElementById("refresh-btn");

function statusClass(status) {
  if (status === "healthy" || status === "ok") return "health-healthy";
  if (status === "degraded") return "health-warn";
  return "health-fail";
}

function card(name, subsystem) {
  return `
    <article class="health-card ${statusClass(subsystem.status)}">
      <div class="health-card-head">
        <span class="health-dot"></span>
        <strong>${name}</strong>
        <span class="health-status">${subsystem.status.toUpperCase()}</span>
      </div>
      <p class="health-detail">${subsystem.detail || "—"}</p>
    </article>`;
}

async function load() {
  try {
    const data = await DSE.fetchJson("/health");
    if (overallEl) {
      overallEl.className = `health-overall ${statusClass(data.status)}`;
      overallEl.textContent = `Overall: ${data.status.toUpperCase()}`;
    }
    if (gridEl) {
      gridEl.innerHTML = [
        card("Market Data", data.market_data),
        card("Database", data.database),
        card("Signal Engine", data.signal_engine),
        card("Paper Trading", data.paper_trading),
        card("Notifications", data.notifications),
      ].join("");
    }
    if (rawEl) {
      rawEl.textContent = JSON.stringify(data, null, 2);
    }
  } catch (error) {
    if (overallEl) overallEl.textContent = `Error: ${error.message}`;
  }
}

refreshBtn?.addEventListener("click", load);
load();
setInterval(load, 15000);
