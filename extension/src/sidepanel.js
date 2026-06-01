async function getStored(keys) {
  return chrome.storage.local.get(keys);
}

async function getSession(keys) {
  return chrome.storage.session.get(keys);
}

function setStatus(text) {
  document.getElementById("nudge").textContent = text;
  document.getElementById("result").hidden = false;
}

async function loadContext() {
  const { askpickyLastContext } = await getSession(["askpickyLastContext"]);
  if (!askpickyLastContext) return;
  const question = askpickyLastContext.selectedText || askpickyLastContext.detectedQuestion || "";
  document.getElementById("question").value = question;
  document.getElementById("confidence").textContent = askpickyLastContext.fieldConfidence || "LOW";
}

async function callAssist() {
  const { askpickyApiBase, askpickyAccessToken } = await getStored([
    "askpickyApiBase",
    "askpickyAccessToken"
  ]);
  if (!askpickyAccessToken) {
    setStatus("Connect AskPicky before sending context.");
    return;
  }

  const question = document.getElementById("question").value.trim();
  const jdContext = document.getElementById("jdContext").value.trim();
  const includePrivate = document.getElementById("includePrivate").checked;
  const { askpickyLastContext } = await getSession(["askpickyLastContext"]);

  const startResponse = await fetch(`${askpickyApiBase}/api/assist/start`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${askpickyAccessToken}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      jd_text: jdContext,
      page_url: askpickyLastContext?.pageUrl || "",
      private_mode: true,
      source: "chrome_extension"
    })
  });

  if (!startResponse.ok) {
    setStatus(`AskPicky returned ${startResponse.status}.`);
    return;
  }
  const started = await startResponse.json();

  const critiqueResponse = await fetch(`${askpickyApiBase}/api/assist/critique-draft`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${askpickyAccessToken}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      assist_session_id: started.assist_session?.assist_session_id,
      question_text: question,
      jd_text: jdContext,
      raw_draft: askpickyLastContext?.activeFieldText || "",
      include_private: includePrivate
    })
  });

  if (!critiqueResponse.ok) {
    setStatus(`AskPicky returned ${critiqueResponse.status}.`);
    return;
  }
  const critique = await critiqueResponse.json();
  const payload = critique.critique || {};
  setStatus(payload.primary_nudge || payload.summary || "Review the answer before submitting.");
  document.getElementById("answer").value = payload.suggested_answer || askpickyLastContext?.activeFieldText || "";
}

async function connect() {
  const { askpickyApiBase } = await getStored(["askpickyApiBase"]);
  await chrome.tabs.create({ url: `${askpickyApiBase}/extension/connect` });
}

async function copyAnswer() {
  const answer = document.getElementById("answer").value;
  await navigator.clipboard.writeText(answer);
  setStatus("Copied. Paste it when ready.");
}

async function writeBack() {
  const answer = document.getElementById("answer").value;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const response = await chrome.runtime.sendMessage({
    type: "ASKPICKY_WRITE_APPROVED_ANSWER",
    tabId: tab?.id,
    answer
  });
  if (!response?.ok) {
    await navigator.clipboard.writeText(answer);
    setStatus("Field was uncertain, so the answer was copied instead.");
    return;
  }
  setStatus("Written back. Review before submitting.");
}

document.getElementById("connect").addEventListener("click", connect);
document.getElementById("send").addEventListener("click", callAssist);
document.getElementById("copy").addEventListener("click", copyAnswer);
document.getElementById("write").addEventListener("click", writeBack);
loadContext();
