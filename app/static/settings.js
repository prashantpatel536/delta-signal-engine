const tokenEl = document.getElementById("status-token");
const chatEl = document.getElementById("status-chat");
const tgReadyEl = document.getElementById("status-ready");
const emailReadyEl = document.getElementById("email-status-ready");
const smtpServerEl = document.getElementById("email-smtp-server");
const smtpUserEl = document.getElementById("email-smtp-user");
const smtpToEl = document.getElementById("email-alert-to");
const signalTfEl = document.getElementById("server-signal-tf");
const messageEl = document.getElementById("settings-message");
const emailTestResultEl = document.getElementById("email-test-result");
const testTelegramBtn = document.getElementById("test-telegram-btn");
const testEmailBtn = document.getElementById("test-email-btn");
const refreshBtn = document.getElementById("refresh-status-btn");

function showMessage(text, isError = false, target = messageEl) {
  if (!target) return;
  target.hidden = false;
  target.textContent = text;
  target.className = isError ? "settings-message error" : "settings-message ok";
}

async function loadStatus() {
  try {
    const [tgStatus, emailStatus, signalTf] = await Promise.all([
      DSE.fetchJson("/telegram/status"),
      DSE.fetchJson("/email/status"),
      DSE.fetchJson("/settings/signal-timeframe"),
    ]);

    if (tokenEl) tokenEl.textContent = tgStatus.bot_token_set ? "Configured" : "Missing";
    if (chatEl) chatEl.textContent = tgStatus.chat_id_set ? "Configured" : "Missing";
    if (tgReadyEl) {
      tgReadyEl.textContent = tgStatus.configured ? "Yes" : "No";
      tgReadyEl.className = tgStatus.configured ? "up" : "down";
    }
    if (testTelegramBtn) testTelegramBtn.disabled = !tgStatus.configured;

    if (smtpServerEl) smtpServerEl.textContent = emailStatus.smtp_server_set ? "Configured" : "Missing";
    if (smtpUserEl) smtpUserEl.textContent = emailStatus.smtp_username_set ? "Configured" : "Missing";
    if (smtpToEl) smtpToEl.textContent = emailStatus.alert_email_to_set ? "Configured" : "Missing";
    if (emailReadyEl) {
      emailReadyEl.textContent = emailStatus.configured ? "Yes" : "No";
      emailReadyEl.className = emailStatus.configured ? "up" : "down";
    }
    if (testEmailBtn) testEmailBtn.disabled = !emailStatus.configured;

    if (signalTfEl) signalTfEl.textContent = signalTf.signal_timeframe || "5m";
  } catch (error) {
    showMessage(`Status error: ${error.message}`, true);
  }
}

async function sendTelegramTest() {
  if (!testTelegramBtn) return;
  testTelegramBtn.disabled = true;
  try {
    const result = await DSE.fetchJson("/telegram/test", { method: "POST" });
    showMessage(result.message || "Telegram test sent.");
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    testTelegramBtn.disabled = false;
    loadStatus();
  }
}

async function sendEmailTest() {
  if (!testEmailBtn) return;
  testEmailBtn.disabled = true;
  if (emailTestResultEl) emailTestResultEl.hidden = true;
  try {
    const result = await DSE.fetchJson("/test-email", { method: "POST" });
    showMessage(result.ok ? "✓ Test email sent successfully." : result.message, !result.ok, emailTestResultEl);
  } catch (error) {
    showMessage(`✗ ${error.message}`, true, emailTestResultEl);
  } finally {
    testEmailBtn.disabled = false;
    loadStatus();
  }
}

testTelegramBtn?.addEventListener("click", sendTelegramTest);
testEmailBtn?.addEventListener("click", sendEmailTest);
refreshBtn?.addEventListener("click", loadStatus);
loadStatus();
