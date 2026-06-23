function statCard(label, value) {
  return `<div class="stat-card"><span class="stat-label">${label}</span><span class="stat-value">${value ?? "—"}</span></div>`;
}

async function loadDiagnostics() {
  const data = await fetchJson("/api/debug/system/full");

  document.getElementById("system-info-grid").innerHTML = [
    statCard("Git commit", `<code>${data.git_commit?.slice(0, 12) || "—"}</code>`),
    statCard("Build timestamp", data.build_timestamp),
    statCard("Signal engine", data.signal_engine_version),
    statCard("Database path", `<code>${data.database_path}</code>`),
    statCard("Database size", data.database_size_human),
    statCard("Hostname", data.hostname),
  ].join("");

  const db = data.database_info || {};
  document.getElementById("database-info-grid").innerHTML = [
    statCard("Total signals", db.total_signals),
    statCard("Total trades", db.total_trades),
    statCard("Approved signals", db.total_approved_signals),
    statCard("Missed winners", db.total_missed_winners),
    statCard("Missed losers", db.total_missed_losers),
    statCard("Balance", `$${Number(data.paper_account?.balance || 0).toFixed(2)}`),
    statCard("Realized PnL", `$${Number(data.paper_account?.realized_pnl || 0).toFixed(2)}`),
  ].join("");

  document.getElementById("sync-note").textContent = data.sync_note || "";

  document.getElementById("table-counts").textContent = JSON.stringify(
    {
      tables: data.table_row_counts,
      signal_status: data.signal_status_counts,
      position_status: data.position_status_counts,
    },
    null,
    2
  );

  document.getElementById("latest-signals").innerHTML = (data.latest_signals || [])
    .map(
      (s) =>
        `<tr><td>${s.id}</td><td>${s.symbol}</td><td>${s.side}</td><td>${s.status}</td><td>${s.created_at || "—"}</td></tr>`
    )
    .join("");

  document.getElementById("latest-trades").innerHTML = (data.latest_trades || [])
    .map(
      (t) =>
        `<tr><td>${t.id}</td><td>${t.signal_id ?? "—"}</td><td>${t.symbol}</td><td>${t.side}</td><td>${t.status}</td><td>${t.pnl ?? "—"}</td><td>${t.opened_at || "—"}</td></tr>`
    )
    .join("");
}

async function compareRemote() {
  const raw = document.getElementById("remote-json").value.trim();
  const out = document.getElementById("compare-result");
  if (!raw) {
    out.hidden = false;
    out.textContent = "Paste remote JSON first.";
    return;
  }
  let remote;
  try {
    remote = JSON.parse(raw);
  } catch (err) {
    out.hidden = false;
    out.textContent = `Invalid JSON: ${err.message}`;
    return;
  }
  const result = await fetchJson("/api/debug/system/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(remote),
  });
  out.hidden = false;
  out.textContent = JSON.stringify(result, null, 2);

  const banner = document.getElementById("sync-banner");
  banner.hidden = false;
  banner.className = `health-overall ${result.identical ? "ok" : "warn"}`;
  banner.textContent = result.identical
    ? "Local and remote database statistics are identical."
    : `MISMATCH — ${(result.explanation || []).join(" ")}`;
}

document.getElementById("refresh-btn")?.addEventListener("click", () => {
  loadDiagnostics().catch((err) => alert(err.message));
});

document.getElementById("compare-btn")?.addEventListener("click", () => {
  compareRemote().catch((err) => alert(err.message));
});

loadDiagnostics().catch((err) => {
  document.getElementById("sync-note").textContent = `Error: ${err.message}`;
});
