/** Shared handlers for open-position TP/SL edits, breakeven, and close. */
window.PositionManagement = {
  async handleAction(button, refreshFn) {
    const positionId = button.dataset.id;
    const action = button.dataset.action || "close";
    button.disabled = true;

    try {
      if (action === "edit-sl" || action === "edit-tp") {
        const label = action === "edit-sl" ? "Stop Loss" : "Take Profit";
        const input = prompt(`Enter new ${label}:`, button.dataset.value || "");
        if (input === null) {
          button.disabled = false;
          return;
        }
        const value = Number(input);
        if (!Number.isFinite(value) || value <= 0) {
          throw new Error("Enter a valid positive price");
        }
        const body = action === "edit-sl" ? { stop_loss: value } : { take_profit: value };
        await DSE.fetchJson(`/position/${positionId}/levels`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else if (action === "breakeven") {
        await DSE.fetchJson(`/position/${positionId}/breakeven`, { method: "POST" });
      } else {
        await DSE.fetchJson(`/position/${positionId}/close`, { method: "POST" });
      }
      await refreshFn();
    } catch (error) {
      alert(error.message);
      button.disabled = false;
    }
  },

  bind(container, refreshFn) {
    if (!container) return;
    container.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action], .btn-close-position");
      if (!button) return;
      this.handleAction(button, refreshFn);
    });
  },
};
