const tokenEl = document.getElementById("status-token");
const chatEl = document.getElementById("status-chat");
const readyEl = document.getElementById("status-ready");
const messageEl = document.getElementById("settings-message");
const testBtn = document.getElementById("test-telegram-btn");
const refreshBtn = document.getElementById("refresh-status-btn");

function showMessage(text, isError = false) {
  if (!messageEl) return;
  messageEl.hidden = false;
  messageEl.textContent = text;
  messageEl.className = isError ? "settings-message error" : "settings-message ok";
}

async function loadStatus() {
  try {
    const status = await DSE.fetchJson("/telegram/status");
    if (tokenEl) tokenEl.textContent = status.bot_token_set ? "Configured" : "Missing";
    if (chatEl) chatEl.textContent = status.chat_id_set ? "Configured" : "Missing";
    if (readyEl) {
      readyEl.textContent = status.configured ? "Yes" : "No";
      readyEl.className = status.configured ? "up" : "down";
    }
    if (testBtn) testBtn.disabled = !status.configured;
  } catch (error) {
    showMessage(`Status error: ${error.message}`, true);
  }
}

async function sendTest() {
  if (!testBtn) return;
  testBtn.disabled = true;
  try {
    const result = await DSE.fetchJson("/telegram/test", { method: "POST" });
    showMessage(result.message || "Test sent.");
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    testBtn.disabled = false;
    loadStatus();
  }
}

testBtn?.addEventListener("click", sendTest);
refreshBtn?.addEventListener("click", loadStatus);
loadStatus();
