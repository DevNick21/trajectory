function visibleText(node) {
  if (!node) return "";
  return (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
}

function fieldValue(element) {
  if (!element) return "";
  if ("value" in element) return element.value || "";
  if (element.isContentEditable) return element.innerText || "";
  return "";
}

function isEditable(element) {
  if (!element) return false;
  const tag = element.tagName?.toLowerCase();
  return tag === "textarea" || tag === "input" || element.isContentEditable;
}

function nearbyLabel(element) {
  if (!element) return { text: "", confidence: "LOW" };

  const id = element.getAttribute?.("id");
  if (id) {
    const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    const text = visibleText(explicit);
    if (text) return { text, confidence: "HIGH" };
  }

  const ariaLabel = element.getAttribute?.("aria-label");
  if (ariaLabel) return { text: ariaLabel, confidence: "HIGH" };

  const labelledBy = element.getAttribute?.("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((part) => visibleText(document.getElementById(part)))
      .filter(Boolean)
      .join(" ");
    if (text) return { text, confidence: "HIGH" };
  }

  const parent = element.closest?.("label, fieldset, section, div");
  if (parent) {
    const text = visibleText(parent).slice(0, 500);
    if (text) return { text, confidence: text.length > 30 ? "MEDIUM" : "LOW" };
  }

  return { text: "", confidence: "LOW" };
}

function collectContext() {
  const selection = String(window.getSelection?.() || "").trim();
  const active = document.activeElement;
  const editable = isEditable(active) ? active : null;
  const label = nearbyLabel(editable);
  return {
    selectedText: selection,
    activeFieldText: fieldValue(editable),
    detectedQuestion: label.text,
    fieldConfidence: label.confidence,
    pageTitle: document.title || "",
    pageUrl: location.href
  };
}

function writeAnswer(answer) {
  const active = document.activeElement;
  if (!isEditable(active)) {
    return { ok: false, reason: "no_active_editable_field" };
  }

  if ("value" in active) {
    active.focus();
    active.value = answer;
    active.dispatchEvent(new Event("input", { bubbles: true }));
    active.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, method: "value" };
  }

  if (active.isContentEditable) {
    active.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("insertText", false, answer);
    active.dispatchEvent(new Event("input", { bubbles: true }));
    return { ok: true, method: "contenteditable" };
  }

  return { ok: false, reason: "unsupported_field" };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "ASKPICKY_COLLECT_CONTEXT") {
    sendResponse(collectContext());
    return true;
  }
  if (message?.type === "ASKPICKY_WRITE_APPROVED_ANSWER") {
    sendResponse(writeAnswer(message.answer || ""));
    return true;
  }
  return false;
});
