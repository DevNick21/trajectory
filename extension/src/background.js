const DEFAULT_API_BASE = "https://askpicky.com";

async function ensureSidePanel(tabId) {
  if (chrome.sidePanel?.setOptions) {
    await chrome.sidePanel.setOptions({
      tabId,
      path: "src/sidepanel.html",
      enabled: true
    });
  }
  if (chrome.sidePanel?.open) {
    await chrome.sidePanel.open({ tabId });
  }
}

async function injectCollector(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["src/detector.js", "src/content.js"]
  });
}

async function collectPageContext(tab) {
  if (!tab.id) return null;
  await injectCollector(tab.id);
  const [result] = await chrome.tabs.sendMessage(tab.id, { type: "ASKPICKY_COLLECT_CONTEXT" });
  return result || null;
}

async function configuredApiBase() {
  const { askpickyApiBase } = await chrome.storage.local.get(["askpickyApiBase"]);
  return askpickyApiBase || DEFAULT_API_BASE;
}

async function exchangePairingToken(pairingToken, supabaseAccessToken) {
  const apiBase = await configuredApiBase();
  const response = await fetch(`${apiBase}/api/extension/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pairing_token: pairingToken,
      supabase_access_token: supabaseAccessToken
    })
  });
  if (!response.ok) {
    return { ok: false, status: response.status };
  }
  const body = await response.json();
  await chrome.storage.local.set({
    askpickyAccessToken: body.access_token,
    askpickyConnectedUserId: body.user_id,
    askpickyTokenExpiresAt: body.expires_at
  });
  return { ok: true, userId: body.user_id, expiresAt: body.expires_at };
}

async function storeContextForPanel(tab) {
  const context = await collectPageContext(tab);
  await chrome.storage.session.set({
    askpickyLastContext: {
      ...context,
      pageUrl: tab.url || context?.pageUrl || "",
      collectedAt: new Date().toISOString()
    }
  });
}

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get(["askpickyApiBase"]);
  if (!existing.askpickyApiBase) {
    await chrome.storage.local.set({ askpickyApiBase: DEFAULT_API_BASE });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  await storeContextForPanel(tab);
  await ensureSidePanel(tab.id);
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command !== "send-selection-to-askpicky" || !tab?.id) return;
  await storeContextForPanel(tab);
  await ensureSidePanel(tab.id);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "ASKPICKY_WRITE_APPROVED_ANSWER") return false;
  const tabId = sender.tab?.id || message.tabId;
  if (!tabId) {
    sendResponse({ ok: false, reason: "missing_tab" });
    return false;
  }
  chrome.tabs.sendMessage(
    tabId,
    { type: "ASKPICKY_WRITE_APPROVED_ANSWER", answer: message.answer },
    sendResponse
  );
  return true;
});

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (message?.type !== "ASKPICKY_COMPLETE_PAIRING") return false;
  configuredApiBase()
    .then((apiBase) => {
      const allowedOrigin = new URL(apiBase).origin;
      const senderOrigin = sender.url ? new URL(sender.url).origin : "";
      if (senderOrigin !== allowedOrigin) {
        return { ok: false, reason: "sender_not_allowed" };
      }
      return exchangePairingToken(
        message.pairingToken || "",
        message.supabaseAccessToken || ""
      );
    })
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, reason: error.message }));
  return true;
});
