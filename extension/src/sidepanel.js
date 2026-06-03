const client = globalThis.AskPickyAssistClient;

async function getStored(keys) {
  return chrome.storage.local.get(keys);
}

async function getSession(keys) {
  return chrome.storage.session.get(keys);
}

async function setSession(values) {
  return chrome.storage.session.set(values);
}

function el(id) {
  return document.getElementById(id);
}

function setStatus(text) {
  el("nudge").textContent = text;
  el("result").hidden = false;
}

function renderList(id, items, formatter) {
  const list = el(id);
  list.replaceChildren();
  if (!items?.length) {
    const item = document.createElement("li");
    item.textContent = "No strong signal yet.";
    list.appendChild(item);
    return;
  }
  for (const value of items.slice(0, 5)) {
    const item = document.createElement("li");
    item.textContent = formatter(value);
    list.appendChild(item);
  }
}

function renderReview(state, context) {
  const critique = state.critique?.critique || {};
  const pattern = state.memory?.pattern || {};
  el("questionType").textContent = critique.question_type || pattern.question_type || "unknown";
  el("testing").textContent = critique.what_testing || pattern.what_testing || "";
  el("saveIndicator").textContent = state.saveIndicator || "";
  renderList("missing", critique.missing_evidence || pattern.ideal_evidence || [], String);
  renderList(
    "memories",
    state.memory?.suggestions || critique.suggested_angles || [],
    (item) => `${item.title || item.memory_kind}: ${item.rationale || item.text || ""}`,
  );
  el("answer").value = context?.activeFieldText || el("answer").value || "";
  setStatus(
    critique.targeted_nudge
      || critique.missing_evidence?.[0]
      || pattern.structure_hint
      || "Review the answer before submitting.",
  );
}

function renderPolish(state) {
  const output = state.polished?.output || {};
  if (output.final_answer) {
    el("answer").value = output.final_answer;
  }
  el("questionType").textContent = output.question_type || state.questionType || "unknown";
  el("saveIndicator").textContent = state.saveIndicator || "";
  renderList("missing", output.missing_evidence_flags || [], String);
  setStatus("Polished. Review before copying or writing back.");
}

async function loadContext() {
  const { askpickyLastContext } = await getSession(["askpickyLastContext"]);
  if (!askpickyLastContext) return;
  const question = askpickyLastContext.selectedText || askpickyLastContext.detectedQuestion || "";
  el("question").value = question;
  el("answer").value = askpickyLastContext.activeFieldText || "";
  el("confidence").textContent = askpickyLastContext.fieldConfidence || "LOW";
}

async function authState() {
  const { askpickyApiBase, askpickyAccessToken } = await getStored([
    "askpickyApiBase",
    "askpickyAccessToken"
  ]);
  return {
    apiBase: askpickyApiBase || "https://askpicky.com",
    token: askpickyAccessToken || ""
  };
}

async function callAssist() {
  const { apiBase, token } = await authState();
  if (!token) {
    setStatus("Connect AskPicky before sending context.");
    return;
  }

  const question = el("question").value.trim();
  if (!question) {
    setStatus("Highlight or paste the application question first.");
    return;
  }

  const jdContext = el("jdContext").value.trim();
  const includePrivate = el("includePrivate").checked;
  const { askpickyLastContext } = await getSession(["askpickyLastContext"]);

  try {
    const state = await client.reviewApplicationQuestion({
      apiBase,
      token,
      context: askpickyLastContext || {},
      question,
      jdContext,
      includePrivate
    });
    await setSession({ askpickyAssistState: state });
    renderReview(state, askpickyLastContext || {});
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "AskPicky request failed.");
  }
}

async function polishAnswer() {
  const { apiBase, token } = await authState();
  const { askpickyAssistState } = await getSession(["askpickyAssistState"]);
  if (!token || !askpickyAssistState?.attemptId) {
    setStatus("Send the question to AskPicky before polishing.");
    return;
  }
  try {
    const state = await client.polishApplicationAnswer({
      apiBase,
      token,
      state: askpickyAssistState,
      draft: el("answer").value.trim()
    });
    await setSession({ askpickyAssistState: state });
    renderPolish(state);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Polish failed.");
  }
}

async function approveCurrentAnswer() {
  const { apiBase, token } = await authState();
  const { askpickyAssistState } = await getSession(["askpickyAssistState"]);
  if (!token || !askpickyAssistState?.attemptId) {
    return askpickyAssistState || null;
  }
  const state = await client.approveApplicationAnswer({
    apiBase,
    token,
    state: askpickyAssistState,
    finalAnswer: el("answer").value.trim()
  });
  await setSession({ askpickyAssistState: state });
  el("saveIndicator").textContent = state.saveIndicator || "";
  return state;
}

async function connect() {
  const { askpickyApiBase } = await getStored(["askpickyApiBase"]);
  const url = new URL(`${askpickyApiBase || "https://askpicky.com"}/extension/connect`);
  url.searchParams.set("extension_id", chrome.runtime.id);
  await chrome.tabs.create({ url: url.toString() });
}

async function copyAnswer() {
  const answer = el("answer").value.trim();
  if (!answer) {
    setStatus("There is no answer to copy yet.");
    return;
  }
  try {
    await approveCurrentAnswer();
    await navigator.clipboard.writeText(answer);
    setStatus("Approved and copied. Paste it when ready.");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Copy failed.");
  }
}

async function writeBack() {
  const answer = el("answer").value.trim();
  if (!answer) {
    setStatus("There is no answer to write back yet.");
    return;
  }
  try {
    await approveCurrentAnswer();
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const response = await chrome.runtime.sendMessage({
      type: "ASKPICKY_WRITE_APPROVED_ANSWER",
      tabId: tab?.id,
      answer
    });
    if (!response?.ok) {
      await navigator.clipboard.writeText(answer);
      setStatus("Field was uncertain, so the approved answer was copied instead.");
      return;
    }
    setStatus("Approved and written back. Review before submitting.");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Write-back failed.");
  }
}

el("connect").addEventListener("click", connect);
el("send").addEventListener("click", callAssist);
el("polish").addEventListener("click", polishAnswer);
el("copy").addEventListener("click", copyAnswer);
el("write").addEventListener("click", writeBack);
loadContext();
